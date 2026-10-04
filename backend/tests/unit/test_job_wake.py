"""H4 follow-up offline: park receipt bền -> wake qua rt.start, không scheduler thứ hai.

Model fixture chỉ chạy tool call đã ghim; con park trong `complete` để mốc
result/Stop/restart xác định. Không gọi provider hay executor mạng.
"""
import asyncio
import copy
import json

from agentbox.agent_core import execution_kernel, job_surface, job_wake
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_harness_runtime import FixtureExecutor, answer, call


def request(**updates):
    return {'kind': 'model', 'ownership': 'controller', 'role': 'explore',
            'goal': 'CHILD inspect canonical receipts', 'invocationId': 'launch-1'} | updates


class ScriptedModel:
    """Bước root theo kịch bản; con chặn ở gate để mốc result do test quyết định."""

    def __init__(self, steps=None):
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self.steps = list(steps if steps is not None else [[call('start_job', request())]])
        self.count = 0
        self.requests = []

    async def snapshot(self):
        return {'connections': [{'id': 'c1', 'providerId': 'p', 'revision': 1, 'models': [
            {'id': 'free', 'pricing': {'source': 'documented', 'input': 0, 'output': 0}}]}]}

    async def complete(self, messages, tools, route, max_tokens=4096, **_):
        self.requests.append(copy.deepcopy((messages, tools)))
        user = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
        if isinstance(user, str) and user.startswith('CHILD'):
            self.entered.set()
            await self.gate.wait()
            return answer('Observed receipt paths.')
        self.count += 1
        return answer(calls=self.steps.pop(0) if self.steps else [])


def environment(tmp_path, monkeypatch, **switches):
    monkeypatch.setenv('BOXFOX_CONTROLLER_JOBS', 'on')
    monkeypatch.setenv('BOXFOX_PEER_MESH', 'on')
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'on')
    monkeypatch.setenv('BOXFOX_USAGE_LEDGER', 'on')
    for name, value in switches.items():
        monkeypatch.setenv(name, value)
    store = SessionStore(tmp_path / 'sessions.db')
    model = ScriptedModel()
    rt = HarnessRuntime(store, FixtureExecutor(), model)
    sid = rt.create({'skills': [], 'tools': sorted(job_surface.JOB_TOOLS | {'delegate_task', 'file_read'}),
                     'connectionId': 'c1', 'modelId': 'free'})['id']
    config = dict(store.get(sid)['config'], harnessPolicy={'schema': execution_kernel.POLICY_SCHEMA,
                                                           'mode': 'adaptive'})
    store.update_config(sid, config)
    return store, rt, sid, model


async def arm(env):
    """Lượt root thật (start_job) + wait_jobs timeout trên cùng dispatch rồi park."""
    store, rt, sid, model = env
    await rt.start(sid, 'ROOT park on job result')
    child = store.children_of(sid)[0]['session_id']
    jid = job_surface._bound(rt, child)[0]['jobId']
    out = await rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 0})
    assert out['timedOut'] and model.count == 2
    receipt = job_surface.park_after_batch(rt, sid)
    assert receipt and receipt['state'] == 'parked' and receipt['jobIds'] == [jid]
    return child, jid


async def finish(rt, child):
    rt.client.gate.set()
    await asyncio.gather(rt.tasks[child], return_exceptions=True)
    await asyncio.sleep(0)


def wake_rows(store, sid):
    return store.db.execute("SELECT * FROM harness_parked_owners WHERE owner_id=?", (sid,)).fetchall()


def test_parked_owner_wakes_on_committed_result_through_rt_start(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, jid = await arm(env)
        assert wake_rows(store, sid)[0]['state'] == 'parked'
        await finish(rt, child)
        assert model.count == 3  # chỉ result đã commit mới mở lượt model mới
        wake = model.requests[-1][0]
        prompt = next(m['content'] for m in wake if m['role'] == 'system' and 'parkId' in m['content'])
        data = json.loads(prompt)
        assert data['jobIds'] == [jid] and data['events']
        assert len([m for m in wake if m['role'] == 'user']) == 1  # không có user giả
        assert store.get(sid)['status'] == 'completed'
        assert job_surface.service(rt).get(jid)['state'] == 'succeeded'
        assert wake_rows(store, sid)[0]['state'] == 'started'
        assert store.db.execute("SELECT count(*) FROM events WHERE session_id=? AND kind='job_wake'",
                                (sid,)).fetchone()[0] == 1
        assert store.db.execute("SELECT count(*) FROM events WHERE session_id=? AND kind='user'",
                                (sid,)).fetchone()[0] == 1
    asyncio.run(drive())
    store.close()


def test_progress_and_heartbeat_do_not_wake_but_result_does(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, jid = await arm(env)
        job_surface.service(rt).append(jid, {'kind': 'progress', 'state': 'running', 'intermediate': True})
        job_wake.notify(rt, sid)
        await asyncio.sleep(0)
        assert model.count == 2 and wake_rows(store, sid)[0]['state'] == 'parked'
        await finish(rt, child)
        assert model.count == 3
    asyncio.run(drive())
    store.close()


def test_stop_before_result_blocks_wake(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, _ = await arm(env)
        await rt.stop(sid)
        await asyncio.sleep(0)
        assert wake_rows(store, sid)[0]['state'] == 'stopped'
        await finish(rt, child)
        assert model.count == 2  # Stop thắng result đến muộn
        assert store.db.execute("SELECT count(*) FROM events WHERE session_id=? AND kind='job_wake'",
                                (sid,)).fetchone()[0] == 0
    asyncio.run(drive())
    store.close()


def test_restart_interrupts_parked_receipt_and_never_replays(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, jid = await arm(env)
        second = HarnessRuntime(store, FixtureExecutor(), ScriptedModel())
        assert wake_rows(store, sid)[0]['state'] == 'interrupted'
        assert job_surface.service(second).get(jid)['state'] == 'interrupted'
        await finish(rt, child)
        job_wake.notify(second, sid)
        await asyncio.sleep(0)
        assert model.count == 2 and second.client.count == 0
    asyncio.run(drive())
    store.close()


def test_unknown_start_outcome_is_not_replayed(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, _ = await arm(env)
        original = rt.start
        rt.start = lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom'))
        await finish(rt, child)
        assert wake_rows(store, sid)[0]['state'] == 'start_unknown'
        rt.start = original
        job_wake.notify(rt, sid)
        await asyncio.sleep(0)
        assert model.count == 2  # outcome chưa biết thì không replay
    asyncio.run(drive())
    store.close()


def test_busy_owner_defers_wake_until_turn_closes(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, _ = await arm(env)
        busy = asyncio.get_running_loop().create_task(asyncio.sleep(0.05))
        rt.tasks[sid] = busy
        await finish(rt, child)
        assert model.count == 2 and wake_rows(store, sid)[0]['state'] == 'parked'
        await busy
        job_wake.notify(rt, sid)
        await asyncio.sleep(0)
        assert model.count == 3
    asyncio.run(drive())
    store.close()


def test_kill_switch_blocks_wake_but_keeps_durable_result(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, _ = await arm(env)
        monkeypatch.setenv('BOXFOX_CONTROLLER_JOBS', 'off')
        await finish(rt, child)
        receipt = wake_rows(store, sid)[0]
        assert model.count == 2 and receipt['state'] == 'blocked'
        assert job_surface.SWITCH in (receipt['reason'] or '')
        pending = store.db.execute("SELECT count(*) FROM harness_wake_outbox WHERE consumer_id=? "
            "AND predicate='result' AND status='pending'", (sid,)).fetchone()[0]
        assert pending == 1
    asyncio.run(drive())
    store.close()


def test_wake_refuses_single_turn_intent_scope(tmp_path, monkeypatch):
    from agentbox.agent_core import work_scope
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, _ = await arm(env)
        work_scope.store_binding(rt, sid, {'turn': rt.active_turn[sid], 'runId': None,
                                           'reason': 'intent', 'intent': True})
        await finish(rt, child)
        receipt = wake_rows(store, sid)[0]
        assert model.count == 2 and receipt['state'] == 'blocked'
        assert 'single-turn' in receipt['reason']
    asyncio.run(drive())
    store.close()


def test_wake_carries_only_canonical_run_binding(tmp_path, monkeypatch):
    from agentbox.agent_core import work_scope
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        child, _ = await arm(env)
        work_scope.store_binding(rt, sid, {'turn': rt.active_turn[sid], 'runId': 'run-1',
                                           'reason': 'harness'})
        await finish(rt, child)
        assert model.count == 3
        binding = work_scope.turn_binding(rt, store.get(sid))
        assert binding['runId'] == 'run-1' and binding['reason'] == 'harness'
        assert not binding.get('intent')
    asyncio.run(drive())
    store.close()


def test_park_fails_soft_when_subscription_revoked(tmp_path, monkeypatch):
    env = environment(tmp_path, monkeypatch)
    store, rt, sid, model = env

    async def drive():
        await rt.start(sid, 'ROOT park on job result')
        child = store.children_of(sid)[0]['session_id']
        jid = job_surface._bound(rt, child)[0]['jobId']
        out = await rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 0})
        assert out['timedOut']
        config = dict(store.get(sid)['config'])
        config['tools'] = [name for name in config['tools'] if name != 'wait_jobs']
        store.update_config(sid, config)
        assert job_surface.park_after_batch(rt, sid) is None
        receipt = wake_rows(store, sid)[0]
        assert receipt['state'] == 'blocked' and 'WORK_CAPABILITY_REVOKED' in receipt['reason']
        assert model.count == 2
    asyncio.run(drive())
    store.close()
