"""H4 runtime acceptance offline: dùng dispatch/delegate/_run/sổ SQLite thật.

Không gọi provider hoặc executor mạng. Model fixture chỉ tạo tool call đã ghim;
con park trong complete để quan sát cleanup qua lượt và Stop một cách xác định.
"""
import asyncio
import copy
import json
import sqlite3

import pytest

from agentbox.agent_core import job_surface, roles, tool_contracts, work_scope
from agentbox.agent_core.harness_jobs import HarnessJobs
from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.agent_core.peer_watchdog import PeerWatchdog, PARENT_ALIVE_STATES
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.tool_groups import TOOL_GROUPS
from agentbox.memory.session_store import SessionStore
from switch_isolation import isolate_off
from test_harness_runtime import FixtureExecutor, answer, call


def request(**updates):
    return {'kind': 'model', 'ownership': 'controller', 'role': 'explore',
            'goal': 'CHILD inspect canonical receipts', 'invocationId': 'launch-1'} | updates


class ControlledModel:
    def __init__(self, root_calls=None):
        self.gate = asyncio.Event()
        self.entered = asyncio.Event()
        self.root_calls = root_calls
        self.root_step = 0
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, **_):
        self.requests.append(copy.deepcopy((messages, tools)))
        user = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
        if isinstance(user, str) and user.startswith('CHILD'):
            self.entered.set()
            await self.gate.wait()
            return answer('Observed receipt paths.')
        self.root_step += 1
        if self.root_step == 1 and self.root_calls:
            return answer(calls=self.root_calls)
        return answer('Parent turn ended.')


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_CONTROLLER_JOBS', 'on')
    monkeypatch.setenv('BOXFOX_PEER_MESH', 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    model = ControlledModel()
    rt = HarnessRuntime(store, FixtureExecutor(), model)
    sid = rt.create({'skills': [], 'tools': sorted(job_surface.JOB_TOOLS | {'delegate_task', 'file_read'})})['id']
    yield store, rt, sid, model
    store.close()


async def start(repo, **updates):
    store, rt, sid, model = repo
    out = await rt.dispatch(store.get(sid), 'start_job', request(**updates))
    return out, out['job']['jobId'], out['sessionId']


async def stop(repo):
    store, rt, sid, _ = repo
    await rt.stop(sid)
    await asyncio.sleep(0)


def get(repo, jid):
    store, rt, sid, _ = repo
    return asyncio.run(rt.dispatch(store.get(sid), 'get_job', {'jobId': jid}))


def test_tool_names_roles_groups_schema_contract():
    assert job_surface.JOB_TOOLS == tool_contracts.CONTROLLER_JOB_TOOLS
    assert job_surface.JOB_TOOLS <= roles.ORCHESTRATOR_TOOLS
    group = next(g for g in TOOL_GROUPS if g['key'] == 'controllerJobs')
    assert set(group['tools']) == job_surface.JOB_TOOLS and not group['alwaysOn']
    assert all(tool_contracts.replay_class(n) == 'unsafe' for n in job_surface.JOB_TOOLS)
    assert 'idle' not in PARENT_ALIVE_STATES


@pytest.mark.parametrize('value', ['', 'off', 'true', '1'])
def test_switch_defaults_off(value):
    assert not job_surface.enabled(value)


def test_switch_off_when_the_env_says_off(monkeypatch):
    # Từ v2 (mặc định BẬT) đường legacy chỉ còn khi env nói TẮT tường minh; bài này đặt
    # `off` thay vì tin vào mặc định, và cắt khóa tổng để env ambient của vòng chạy nhóm
    # (`BOXFOX_REFORM=on`) không chen vào.
    isolate_off(monkeypatch, job_surface.SWITCH)
    assert not job_surface.enabled()


def test_switch_off_runtime_profile_schemas_and_no_ddl(repo, monkeypatch):
    store, rt, sid, _ = repo
    isolate_off(monkeypatch, job_surface.SWITCH)
    assert not job_surface.exists(rt)
    assert not job_surface.JOB_TOOLS & set(rt.turn_profile(store.get(sid))['tools'])
    assert not tool_contracts.schemas_for(job_surface.JOB_TOOLS)
    with pytest.raises(PermissionError, match='JOB_SURFACE_OFF'):
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request()))
    assert not job_surface.exists(rt) and store.children_of(sid) == []


@pytest.mark.parametrize('field,value', [('capabilityRef', {'epoch': 10}), ('controllerId', 'mine'),
    ('ownerId', 'mine'), ('executor', {'pid': 1}), ('childSessionId', 'child'), ('consumerId', 'foreign')])
def test_start_rejects_caller_authority(repo, field, value):
    store, rt, sid, _ = repo
    with pytest.raises(ContractError):
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request(**{field: value})))
    assert store.children_of(sid) == []


@pytest.mark.parametrize('updates,code', [({'kind': 'process'}, 'JOB_EXECUTOR_UNSUPPORTED'),
    ({'ownership': 'turn'}, 'JOB_OWNERSHIP_REQUIRED')])
def test_unsupported_handles_and_implicit_ownership_rejected(repo, updates, code):
    store, rt, sid, _ = repo
    with pytest.raises(ContractError) as exc:
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request(**updates)))
    assert exc.value.code == code and store.children_of(sid) == []


def test_peer_mesh_kill_switch_rejects_new_async_start(repo, monkeypatch):
    store, rt, sid, _ = repo
    monkeypatch.setenv('BOXFOX_PEER_MESH', 'off')
    with pytest.raises(PermissionError, match='JOB_EXECUTOR_UNSUPPORTED'):
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request()))
    assert store.children_of(sid) == []


def test_real_root_run_tool_dispatch_survives_turn_and_completes(repo):
    store, rt, sid, model = repo
    model.root_calls = [call('start_job', request())]

    async def drive():
        await rt.start(sid, 'ROOT launch one controller job')
        results = [json.loads(m['content']) for m in store.get(sid)['messages'] if m['role'] == 'tool']
        assert results[0]['status'] == 'started', results
        jid, child = results[0]['job']['jobId'], results[0]['sessionId']
        await asyncio.wait_for(model.entered.wait(), 2)
        assert store.child(child)['status'] == 'started'
        assert rt.child_slot_holders == {child: sid}
        assert job_surface.owns_child(rt, child)
        assert store.get(sid)['status'] == 'completed'
        assert await rt.reap_children(sid) == []
        wd = PeerWatchdog(store, rt)
        wd.first_scan = False
        assert wd.sweep()['orphan'] == []
        model.gate.set()
        await rt.tasks[child]
        await asyncio.sleep(0)
        job = await rt.dispatch(store.get(sid), 'get_job', {'jobId': jid})
        assert job['state'] == 'succeeded'
        assert job['events'][-1]['payload']['receipt'] == 'canonical_children'
        assert store.child(child)['status'] == 'completed'
        assert rt.child_slot_holders == {} and rt.parent_running.get(sid, 0) == 0
        assert 'accepted' not in json.dumps(job)

    asyncio.run(drive())


def test_legacy_detached_child_still_reaped_with_jobs_enabled(repo):
    store, rt, sid, model = repo
    model.root_calls = [call('delegate_task', {'role': 'explore', 'goal': request()['goal'], 'wait': False})]
    async def drive():
        await rt.start(sid, 'ROOT ordinary delegation')
    asyncio.run(drive())
    child = store.children_of(sid)[0]
    assert child['status'] == 'failed' and child['reason'] == 'PARENT_TURN_ENDED'
    assert not job_surface.exists(rt)
    assert rt.child_slot_holders == {}


def test_idempotent_start_same_invocation_no_new_child_even_closed(repo):
    async def drive():
        store, rt, sid, model = repo
        out, jid, child = await start(repo)
        replay = await rt.dispatch(store.get(sid), 'start_job', request())
        assert replay['status'] == 'replayed' and replay['sessionId'] == child
        assert len(store.children_of(sid)) == 1
        model.gate.set()
        await rt.tasks[child]
        await asyncio.sleep(0)
        replay = await rt.dispatch(store.get(sid), 'start_job', request())
        assert replay['job']['state'] == 'succeeded'
        assert len(store.children_of(sid)) == 1 and not rt.child_slot_holders
    asyncio.run(drive())


def test_invocation_payload_conflict_no_second_child(repo):
    async def drive():
        store, rt, sid, _ = repo
        await start(repo)
        with pytest.raises(ContractError) as exc:
            await rt.dispatch(store.get(sid), 'start_job', request(goal='changed'))
        assert exc.value.code == 'JOB_INVOCATION_CONFLICT' and len(store.children_of(sid)) == 1
        await stop(repo)
    asyncio.run(drive())


@pytest.mark.parametrize('name', ['get_job', 'subscribe_job', 'wait_jobs', 'cancel_job'])
@pytest.mark.parametrize('actor', ['foreign', 'child'])
def test_owner_checks_all_read_and_control_surfaces(repo, name, actor):
    async def drive():
        store, rt, sid, _ = repo
        out, jid, child = await start(repo)
        other = rt.create({'skills': []})['id'] if actor == 'foreign' else child
        args = {'jobId': jid, 'jobIds': [jid], 'expectedRevision': out['job']['revision'], 'reason': 'cancel'}
        with pytest.raises(PermissionError, match='JOB_FORBIDDEN'):
            await rt.dispatch(store.get(other), name, args)
        assert job_surface.service(rt).get(jid)['controlState'] is None
        await stop(repo)
    asyncio.run(drive())


def test_wait_parks_and_wakes_only_after_durable_child_close(repo):
    async def drive():
        store, rt, sid, model = repo
        _, jid, child = await start(repo)
        await model.entered.wait()
        await rt.dispatch(store.get(sid), 'subscribe_job', {'jobId': jid, 'predicate': 'result'})
        waiting = asyncio.create_task(rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 2}))
        await asyncio.sleep(0)
        assert not waiting.done()
        svc = job_surface.service(rt)
        svc.append(jid, {'kind': 'heartbeat'})
        svc.append(jid, {'kind': 'log'})
        await asyncio.sleep(0)
        assert not waiting.done()
        model.gate.set()
        result = await asyncio.wait_for(waiting, 3)
        assert result['ready'] and not result['timedOut']
        assert [e['kind'] for e in result['events']] == ['result']
        assert result['jobs'][jid]['state'] == 'succeeded'
        cursor = result['cursor']
        again = await rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'afterSeq': cursor, 'timeoutSeconds': 0})
        assert again['ready'] and again['events'] == []
        assert not svc.db.execute('SELECT 1 FROM harness_wake_locks').fetchone()
        assert not rt._job_waiters
    asyncio.run(drive())


def test_overlapping_owner_wait_rejected_and_cancelled_wait_releases_lock(repo):
    async def drive():
        store, rt, sid, _ = repo
        _, jid, _ = await start(repo)
        waiting = asyncio.create_task(rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 2}))
        await asyncio.sleep(0)
        with pytest.raises(ContractError) as exc:
            await rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 0})
        assert exc.value.code == 'JOB_WAKE_LOCKED'
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)
        assert not job_surface.service(rt).db.execute('SELECT 1 FROM harness_wake_locks').fetchone()
        await stop(repo)
    asyncio.run(drive())


def test_cancel_uses_canonical_child_stop_with_durable_epoch_receipt(repo):
    async def drive():
        store, rt, sid, _ = repo
        out, jid, child = await start(repo)
        result = await rt.dispatch(store.get(sid), 'cancel_job', {'jobId': jid,
            'expectedRevision': out['job']['revision'], 'reason': 'no longer needed'})
        assert result['cancelRequested'] and result['receiptRef']
        assert result['capabilityEpoch'] == out['job']['capabilityEpoch'] + 1
        assert result['job']['state'] == 'cancelled'
        assert store.child(child)['status'] == 'cancelled'
        assert not rt.child_slot_holders
    asyncio.run(drive())


def test_kill_switch_blocks_starts_but_preserves_receipt_reads_and_cleanup(repo, monkeypatch):
    async def drive():
        store, rt, sid, model = repo
        _, jid, child = await start(repo)
        monkeypatch.setenv(job_surface.SWITCH, 'off')
        assert job_surface.owns_child(rt, child)
        names = set(rt.turn_profile(store.get(sid))['tools'])
        assert 'start_job' not in names and job_surface.READ_TOOLS <= names
        schemas = tool_contracts.schemas_for(names, job_receipts=True)
        assert job_surface.READ_TOOLS <= {s['function']['name'] for s in schemas}
        with pytest.raises(PermissionError, match='JOB_SURFACE_OFF'):
            await rt.dispatch(store.get(sid), 'start_job', request(invocationId='second'))
        model.gate.set()
        await rt.tasks[child]
        await asyncio.sleep(0)
        assert (await rt.dispatch(store.get(sid), 'get_job', {'jobId': jid}))['state'] == 'succeeded'
    asyncio.run(drive())


def test_stop_blocks_queued_and_new_admission_but_fresh_user_turn_can_admit(repo):
    async def drive():
        store, rt, sid, _ = repo
        _, jid, child = await start(repo)
        await stop(repo)
        assert job_surface.service(rt).get(jid)['state'] == 'cancelled'
        with pytest.raises(PermissionError, match='JOB_STOPPED'):
            await rt.dispatch(store.get(sid), 'start_job', request(invocationId='after-stop'))
        await rt.start(sid, 'ROOT fresh user turn')
        assert not store.get(sid)['config'].get(job_surface.STOP_KEY)
    asyncio.run(drive())


def test_after_slot_recheck_revoke_prevents_child_and_slot_leak(repo, monkeypatch):
    store, rt, sid, _ = repo
    original = rt.acquire_child_slot
    async def revoke(parent):
        await original(parent)
        config = store.get(parent)['config']
        config['tools'].remove('delegate_task')
        store.update_config(parent, config)
    monkeypatch.setattr(rt, 'acquire_child_slot', revoke)
    with pytest.raises(PermissionError, match='WORK_CAPABILITY_REVOKED'):
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request()))
    assert store.children_of(sid) == [] and rt.parent_running.get(sid, 0) == 0


def test_plan_scope_write_job_uses_existing_delegate_guard(repo, monkeypatch):
    store, rt, sid, _ = repo
    monkeypatch.setattr(work_scope, 'resolve', lambda *_: work_scope.scope('artifact_only', 'plan-1', 'no implementation consent'))
    with pytest.raises(PermissionError, match='WORK_SCOPE_DELEGATE_ROLE'):
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request(role='build')))
    assert store.children_of(sid) == []


def test_revoke_blocks_child_tool_and_late_success_stays_cancelled(repo):
    async def drive():
        store, rt, sid, model = repo
        _, jid, child = await start(repo)
        await model.entered.wait()
        config = store.get(sid)['config']
        config['tools'].remove('file_read')
        store.update_config(sid, config)
        with pytest.raises(PermissionError, match='WORK_CAPABILITY_REVOKED'):
            await rt.dispatch(store.get(child), 'file_read', {'path': 'x'})
        model.gate.set()
        await rt.tasks[child]
        await asyncio.sleep(0)
        job = job_surface.service(rt).get(jid)
        assert job['state'] == 'cancelled'
        assert job['events'][-1]['reportedState'] == 'succeeded'
    asyncio.run(drive())


def test_watchdog_restart_closes_canonical_child_and_job_without_respawn(repo):
    async def drive():
        store, rt, sid, _ = repo
        _, jid, child = await start(repo)
        report = PeerWatchdog(store, rt).sweep()
        assert report['restart'] == [child]
        assert job_surface.service(rt).get(jid)['state'] == 'interrupted'
        assert store.child(child)['reason'] == 'RESTART'
        assert len(store.children_of(sid)) == 1
        await stop(repo)
    asyncio.run(drive())


def test_constructor_restart_reconcile_does_not_trust_started_model_row(tmp_path, monkeypatch):
    monkeypatch.setenv(job_surface.SWITCH, 'on')
    store = SessionStore(tmp_path / 'restart.db')
    rt = HarnessRuntime(store, FixtureExecutor(), ControlledModel())
    sid = rt.create({'skills': [], 'tools': sorted(job_surface.JOB_TOOLS | {'delegate_task'})})['id']
    child = rt.create({'skills': []}, parent_id=sid, role='explore')['id']
    store.child_start(child, sid, 1, 1, 'explore', request()['goal'])
    job = job_surface.bind(rt, store.get(sid), request(), child)
    store.close()
    reopened = SessionStore(tmp_path / 'restart.db')
    new_rt = HarnessRuntime(reopened, FixtureExecutor(), ControlledModel())
    receipt = job_surface.service(new_rt).get(job['jobId'])
    assert receipt['state'] == 'interrupted' and new_rt.tasks == {}
    assert reopened.child(child)['status'] == 'started', 'watchdog remains the canonical closer'
    PeerWatchdog(reopened, new_rt).sweep()
    assert reopened.child(child)['reason'] == 'RESTART'
    assert len(reopened.children_of(sid)) == 1
    reopened.close()


def test_projection_commit_visible_on_second_connection_and_deduped(repo):
    async def drive():
        store, rt, sid, model = repo
        _, jid, child = await start(repo)
        model.gate.set()
        await rt.tasks[child]
        await asyncio.sleep(0)
        before = job_surface.service(rt).get(jid)
        job_surface.project_child(rt, child)
        assert job_surface.service(rt).get(jid)['revision'] == before['revision']
        conn = sqlite3.connect(store.db.execute('PRAGMA database_list').fetchone()['file'])
        assert conn.execute('SELECT state FROM harness_jobs WHERE job_id=?', (jid,)).fetchone()[0] == 'succeeded'
        assert conn.execute("SELECT COUNT(*) FROM harness_wake_outbox WHERE job_id=? AND predicate='result'", (jid,)).fetchone()[0] == 1
        conn.close()
    asyncio.run(drive())


def test_wait_library_requires_live_matching_lock_before_consuming(repo):
    store, rt, sid, _ = repo
    svc = HarnessJobs(store)
    with pytest.raises(ContractError) as exc:
        svc.wait(['unknown'], consumer_id=sid, owner_id=sid)
    assert exc.value.code == 'JOB_UNKNOWN'


def test_concurrent_start_same_invocation_after_slot_creates_one_child(repo):
    async def drive():
        store, rt, sid, _ = repo
        replies = await asyncio.gather(*(rt.dispatch(store.get(sid), 'start_job', request()) for _ in range(2)))
        assert {r['status'] for r in replies} == {'started', 'replayed'}
        assert len({r['job']['jobId'] for r in replies}) == 1
        assert len(store.children_of(sid)) == 1 and rt.parent_running.get(sid) == 1
        await stop(repo)
    asyncio.run(drive())


def test_stop_wins_when_first_start_is_waiting_for_slot(repo, monkeypatch):
    async def drive():
        store, rt, sid, _ = repo
        acquired, release = asyncio.Event(), asyncio.Event()
        original = rt.acquire_child_slot
        async def queued(parent):
            await original(parent)
            acquired.set()
            await release.wait()
        monkeypatch.setattr(rt, 'acquire_child_slot', queued)
        starting = asyncio.create_task(rt.dispatch(store.get(sid), 'start_job', request()))
        await acquired.wait()
        await rt.stop(sid)
        release.set()
        with pytest.raises(PermissionError, match='JOB_STOPPED'):
            await starting
        assert not store.children_of(sid) and rt.parent_running.get(sid, 0) == 0
        assert job_surface.service(rt).open_jobs(sid) == []
    asyncio.run(drive())


def test_child_start_failure_closes_job_and_releases_slot(repo, monkeypatch):
    store, rt, sid, _ = repo
    def fail(*_args, **_kwargs):
        raise RuntimeError('fixture child start failure')
    monkeypatch.setattr(rt, 'start', fail)
    with pytest.raises(RuntimeError, match='fixture child start failure'):
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request()))
    assert not rt.child_slot_holders and rt.parent_running.get(sid, 0) == 0
    assert store.children_of(sid)[0]['reason'] == 'JOB_START_FAILED'
    jid = store.db.execute('SELECT job_id FROM harness_jobs').fetchone()['job_id']
    assert get(repo, jid)['state'] == 'failed'


def test_bind_failure_after_receipt_commit_projects_failed_child(repo, monkeypatch):
    store, rt, sid, _ = repo
    original = job_surface.bind
    def fail(*args):
        original(*args)
        raise RuntimeError('fixture lost bind response')
    monkeypatch.setattr(job_surface, 'bind', fail)
    with pytest.raises(RuntimeError, match='fixture lost bind response'):
        asyncio.run(rt.dispatch(store.get(sid), 'start_job', request()))
    assert not rt.child_slot_holders and rt.parent_running.get(sid, 0) == 0
    jid = store.db.execute('SELECT job_id FROM harness_jobs').fetchone()['job_id']
    assert get(repo, jid)['state'] == 'failed'
    assert store.children_of(sid)[0]['reason'] == 'JOB_BIND_FAILED'
    assert not rt.tasks


def test_stale_cancel_revision_has_no_cancel_effect(repo):
    async def drive():
        store, rt, sid, _ = repo
        _, jid, child = await start(repo)
        with pytest.raises(ContractError) as exc:
            await rt.dispatch(store.get(sid), 'cancel_job', {'jobId': jid, 'expectedRevision': 1, 'reason': 'stale'})
        assert exc.value.code == 'JOB_REVISION_CONFLICT'
        assert job_surface.service(rt).get(jid)['controlState'] is None
        assert store.child(child)['status'] == 'started'
        await stop(repo)
    asyncio.run(drive())


def test_bound_child_identity_change_cannot_cancel_new_attempt(repo):
    async def drive():
        store, rt, sid, _ = repo
        out, jid, child = await start(repo)
        store.db.execute('UPDATE children SET started=started+1 WHERE session_id=?', (child,))
        store.db.commit()
        with pytest.raises(ContractError) as exc:
            await rt.dispatch(store.get(sid), 'cancel_job', {'jobId': jid,
                'expectedRevision': out['job']['revision'], 'reason': 'old job'})
        assert exc.value.code == 'JOB_HANDLE_STALE'
        assert not rt.tasks[child].cancelled()
        assert store.child(child)['status'] == 'started'
        assert job_surface.service(rt).get(jid)['state'] == 'interrupted'
        await stop(repo)
    asyncio.run(drive())


def test_canonical_artifact_only_run_blocks_write_job_without_fake_scope(repo):
    async def drive():
        store, rt, sid, _ = repo
        config = store.get(sid)['config']
        config['tools'].append('work_graph')
        store.update_config(sid, config)
        await rt.dispatch(store.get(sid), 'work_graph', {'action': 'create', 'goal': 'Research receipt design',
            'flow': 'research', 'nodes': [{'id': 'R1', 'kind': 'research', 'title': 'Inspect',
            'goal': 'Find durable receipts', 'acceptance': ['Cite code'], 'tests': []}]})
        assert work_scope.resolve(rt, store.get(sid))['mode'] == 'artifact_only'
        with pytest.raises(PermissionError, match='WORK_SCOPE_DELEGATE_ROLE'):
            await rt.dispatch(store.get(sid), 'start_job', request(role='build'))
        assert store.children_of(sid) == []
    asyncio.run(drive())


def test_get_receipts_are_paginated_and_cursor_does_not_consume_wakes(repo):
    async def drive():
        store, rt, sid, _ = repo
        _, jid, _ = await start(repo)
        svc = job_surface.service(rt)
        for i in range(110):
            svc.append(jid, {'kind': 'log', 'payload': {'line': i}})
        page = await rt.dispatch(store.get(sid), 'get_job', {'jobId': jid})
        assert len(page['events']) == 100
        later = await rt.dispatch(store.get(sid), 'get_job', {'jobId': jid, 'cursor': page['cursor']})
        assert len(later['events']) == 11
        assert not svc.db.execute('SELECT 1 FROM harness_wake_cursors').fetchone()
        await stop(repo)
    asyncio.run(drive())


def test_owner_locked_wait_cannot_consume_foreign_consumer_outbox(repo):
    async def drive():
        store, rt, sid, _ = repo
        _, jid, _ = await start(repo)
        svc = job_surface.service(rt)
        svc.append(jid, {'kind': 'blocker', 'consumerId': 'foreign-consumer'})
        result = await rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 0})
        assert not result['ready'] and result['events'] == []
        row = svc.db.execute("SELECT status FROM harness_wake_outbox WHERE consumer_id='foreign-consumer'").fetchone()
        assert row['status'] == 'pending'
        await stop(repo)
    asyncio.run(drive())


def test_second_child_model_request_after_parent_completion_keeps_admitted_lifetime(repo):
    class TwoStepModel(ControlledModel):
        child_steps = 0
        async def complete(self, messages, tools, route, max_tokens=4096, **kwargs):
            user = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), '')
            if isinstance(user, str) and user.startswith('CHILD'):
                self.child_steps += 1
                if self.child_steps == 1:
                    self.entered.set()
                    await self.gate.wait()
                    return answer(calls=[call('file_read', {'path': 'receipts.py'})])
                return answer('Observed two-step receipt paths.')
            return await super().complete(messages, tools, route, max_tokens=max_tokens, **kwargs)

    async def drive():
        store, rt, sid, _ = repo
        model = rt.client = TwoStepModel([call('start_job', request())])
        await rt.start(sid, 'ROOT cross-turn multi-step job')
        assert store.get(sid)['status'] == 'completed'
        child = store.children_of(sid)[0]['session_id']
        assert job_surface.guard_request(rt, child)
        model.gate.set()
        await rt.tasks[child]
        await asyncio.sleep(0)
        assert model.child_steps == 2
        assert store.child(child)['status'] == 'completed'
        assert ('file_read', {'path': 'receipts.py'}, child) in rt.executor.calls
    asyncio.run(drive())


def test_model_request_guard_blocks_revoke_before_any_new_request(repo):
    async def drive():
        store, rt, sid, _ = repo
        _, jid, child = await start(repo)
        config = store.get(sid)['config']
        config['tools'].remove('start_job')
        store.update_config(sid, config)
        with pytest.raises(PermissionError, match='WORK_CAPABILITY_REVOKED'):
            job_surface.guard_request(rt, child)
        assert job_surface.service(rt).get(jid)['controlState'] == 'cancel_requested'
        await stop(repo)
    asyncio.run(drive())


def test_job_binds_persisted_canonical_context_checkpoint_not_caller_text(repo, monkeypatch):
    from agentbox.agent_core import context_surface
    monkeypatch.setenv(context_surface.SWITCH, 'on')

    async def drive():
        store, rt, sid, _ = repo
        result = await rt.dispatch(store.get(sid), 'start_job', request())
        checkpoint = result['job']['checkpointRef']
        assert checkpoint
        import json
        bundle = context_surface.load_bundle(rt, store.get(sid), json.loads(checkpoint))
        assert bundle.manifest_hash
        assert result['job']['ownerId'] == sid
        await stop(repo)
    asyncio.run(drive())


def test_model_job_inherits_backend_policy_and_disabled_adaptive_blocks_model(repo):
    from agentbox.agent_core import execution_kernel
    async def drive():
        store, rt, sid, model = repo
        policy = {'schema': execution_kernel.POLICY_SCHEMA, 'mode': 'adaptive'}
        store.update_config(sid, dict(store.get(sid)['config'], harnessPolicy=policy))
        # Không chạy model cha: root guard riêng vẫn chặn adaptive OFF. Gọi canonical
        # delegate seam để kiểm child không rơi xuống legacy khi policy được thừa kế.
        request_value = job_surface.prepare(request())
        result = await rt.delegate(store.get(sid), job_surface.delegate_args(request_value),
                                   job_request=request_value)
        child = result['sessionId']
        assert store.get(child)['config'][execution_kernel.POLICY_KEY] == policy
        await rt.tasks[child]
        assert not model.entered.is_set()
        assert store.get(child)['status'] == 'failed'
        assert job_surface.service(rt).get(result['job']['jobId'])['state'] == 'failed'
        await stop(repo)
    asyncio.run(drive())


def test_timed_out_wait_does_not_autonomously_reopen_completed_model_turn(repo):
    async def drive():
        store, rt, sid, _ = repo
        model = rt.client = ControlledModel([call('start_job', request())])
        await rt.start(sid, 'ROOT job then close turn')
        child = store.children_of(sid)[0]['session_id']
        jid = job_surface._bound(rt, child)[0]['jobId']
        out = await rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 0})
        assert out['timedOut'] and sid not in rt._job_waiters
        before = model.root_step
        model.gate.set()
        await rt.tasks[child]
        await asyncio.sleep(0)
        # Giới hạn runtime chủ động ghim: outbox tồn tại, không tự mở lượt trả phí mới.
        assert model.root_step == before and rt.tasks[sid].done()
        pending = store.db.execute('SELECT count(*) FROM harness_wake_outbox WHERE consumer_id=? '
            "AND predicate='result' AND status='pending'", (sid,)).fetchone()[0]
        assert pending == 1
        out = await rt.dispatch(store.get(sid), 'wait_jobs', {'jobIds': [jid], 'timeoutSeconds': 0})
        assert out['ready'] and out['events'] and not out['timedOut']
    asyncio.run(drive())
