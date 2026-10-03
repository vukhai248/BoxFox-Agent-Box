"""H3 — bề mặt task: công tắc giết, phân quyền, ghi bền vững và chiếu kết cục của con.

Không model, không provider, không mạng: chỉ `SessionStore` + `TaskService` thật trên SQLite tạm.
Ba tầng được ghim riêng:

1. **Quảng cáo** — `turn_profile`/`schemas_for` chỉ trả bốn công cụ `task_*` khi `BOXFOX_TASK_SURFACE=on`.
2. **Thực thi** — `dispatch` từ chối khi công tắc tắt, kể cả phiên đã giữ tên công cụ từ trước.
3. **Dữ liệu** — `task_list/get/send/abandon` chỉ gọi hàm có sẵn của `TaskService`, và bộ đóng con
   hiện có (`child_finish`, `child_close_once`) chiếu được kết cục vào attempt đang mở.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3

import pytest

from agentbox.agent_core import roles, task_surface, tool_contracts, work_scope
from agentbox.agent_core.orchestration_contracts import ContractError, TASK_SCHEMA
from agentbox.agent_core.task_service import TaskService
from agentbox.agent_core.tool_contracts import TASK_SURFACE_TOOLS, schemas_for
from agentbox.memory.session_store import SessionStore


def request(**updates):
    value = {'schema': TASK_SCHEMA, 'taskId': 'inspect-recovery', 'invocationId': 'inv-create',
             'role': 'explore', 'goal': 'Find durable execution receipts.', 'intent': 'analysis',
             'mode': 'read_only', 'inputs': [],
             'scope': {'read': ['backend/src'], 'write': [], 'externalSources': 'none'},
             'deliverable': {'kind': 'knowledge', 'format': 'markdown', 'evidence': ['file_line'],
                             'acceptance': ['Cite the canonical closer.']},
             'dependsOn': [], 'budget': {'allocationPolicy': 'inherited'}}
    value.update(updates)
    return value


class FakeRT:
    """Runtime tối thiểu: chỉ `store` và `root_session_id` (đi lên theo `parent_id`)."""

    def __init__(self, store):
        self.store = store

    def root_session_id(self, sid):
        seen = set()
        while sid and sid not in seen:
            seen.add(sid)
            record = self.store.get(sid)
            if record is None:
                break
            if not record.get('parent_id'):
                return sid
            sid = record['parent_id']
        return sid


@pytest.fixture
def repo(tmp_path, monkeypatch):
    # Bề mặt task mặc định TẮT; các ca dữ liệu bật công tắc tường minh, ca công tắc tự tắt lại.
    monkeypatch.setenv('BOXFOX_TASK_SURFACE', 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    owner = store.create({'skills': []})['id']
    rt = FakeRT(store)
    runs = {}

    def resolve(owner_id, run_id):
        run = runs.get(run_id)
        return copy.deepcopy(run) if run and run['sessionId'] == owner_id else None

    def service(_rt):
        return TaskService(store, resolve)

    monkeypatch.setattr(task_surface, 'service', service)
    runs['run-1'] = {'runId': 'run-1', 'sessionId': owner}
    yield store, rt, owner, runs
    store.close()


def task(repo, **updates):
    store, rt, owner, _ = repo
    updates.setdefault('invocationId', f'inv-create-{len(updates)}{id(updates) % 1000}')
    return task_surface.service(rt).create(owner, 'run-1', request(**updates), controller_id=owner)


def child(repo, *, role='explore', root=None):
    store, rt, owner, _ = repo
    sid = store.create({'skills': []}, role=role, parent_id=root or owner)['id']
    store.child_start(sid, owner, 1, 2, role, 'Find receipts')
    return sid


def attempt(repo, item, sid, *, invocation='inv-attempt', admission='admission-1', expected=None, epoch=1):
    store, rt, owner, _ = repo
    if expected is None:
        expected = task_surface.service(rt).get(owner, 'run-1', item['taskKey'])['revision']
    return task_surface.service(rt).record_attempt(
        owner, 'run-1', item['taskKey'], invocation_id=invocation, expected_revision=expected,
        session_id=sid, admission_id=admission, capability_epoch=epoch)


def session(rt, sid):
    return rt.store.get(sid)


def fresh(repo, item):
    store, rt, owner, _ = repo
    return task_surface.service(rt).get(owner, 'run-1', item['taskKey'])


def run(rt, sid, name, args):
    return asyncio.run(task_surface.handle(rt, session(rt, sid), name, args))


# --- 1. Công tắc giết ---------------------------------------------------------------------

def test_switch_is_off_by_default_and_only_on_enables():
    assert task_surface.enabled() is False
    assert task_surface.enabled('off') is False
    assert task_surface.enabled('') is False
    assert task_surface.enabled('ON') is True
    assert task_surface.enabled(' on ') is True


def test_tool_names_are_one_contract_in_two_modules():
    assert task_surface.TASK_TOOLS == TASK_SURFACE_TOOLS
    assert tool_contracts.task_surface_enabled('on') is True
    group = next(g for g in __import__('agentbox.agent_core.tool_groups', fromlist=['TOOL_GROUPS'])
                 .TOOL_GROUPS if g['key'] == 'taskSurface')
    assert group['alwaysOn'] is False
    assert set(group['tools']) == TASK_SURFACE_TOOLS
    assert TASK_SURFACE_TOOLS <= roles.ORCHESTRATOR_TOOLS


def test_schemas_for_drops_the_surface_when_off(monkeypatch):
    names = ['task_list', 'task_get', 'task_send', 'task_abandon', 'read_source']
    monkeypatch.delenv('BOXFOX_TASK_SURFACE', raising=False)
    assert [s['function']['name'] for s in schemas_for(names)] == ['read_source']
    monkeypatch.setenv('BOXFOX_TASK_SURFACE', 'on')
    assert {s['function']['name'] for s in schemas_for(names)} == set(names)


def test_turn_profile_hides_the_surface_for_every_profile(monkeypatch, tmp_path):
    from agentbox.agent_core.runtime import HarnessRuntime
    from test_harness_runtime import FixtureExecutor, FixtureModel

    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([]))
    config = {'skills': [], 'tools': ['task_list', 'task_get', 'task_send', 'task_abandon', 'read_source']}
    sid = runtime.create(config)['id']
    monkeypatch.delenv('BOXFOX_TASK_SURFACE', raising=False)
    assert runtime.turn_profile(session(runtime, sid))['tools'] == ['read_source']
    monkeypatch.setenv('BOXFOX_TASK_SURFACE', 'on')
    assert set(runtime.turn_profile(session(runtime, sid))['tools']) == set(config['tools'])
    store.close()


# --- 2. Cổng thực thi ---------------------------------------------------------------------

def test_dispatch_refuses_every_task_tool_when_the_switch_is_off(monkeypatch, tmp_path):
    from agentbox.agent_core.runtime import HarnessRuntime
    from test_harness_runtime import FixtureExecutor, FixtureModel

    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([]))
    config = {'skills': [], 'tools': ['task_list']}
    sid = runtime.create(config)['id']
    monkeypatch.delenv('BOXFOX_TASK_SURFACE', raising=False)
    with pytest.raises(PermissionError, match='TASK_SURFACE_OFF'):
        asyncio.run(runtime.dispatch(session(runtime, sid), 'task_list', {'runId': 'run-1'}))
    store.close()


# --- 3. Đọc/ghi qua bề mặt ----------------------------------------------------------------

def test_list_and_get_read_back_the_contract(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    listing = run(rt, owner, 'task_list', {'runId': 'run-1'})
    assert [row['taskKey'] for row in listing['items']] == [item['taskKey']]
    assert listing['cursor'] is None
    detail = run(rt, owner, 'task_get', {'runId': 'run-1', 'taskId': item['taskId']})
    assert detail['task']['state'] == 'running'
    assert [a['status'] for a in detail['attempts']] == ['running']
    assert detail['receipts'][0]['childStatus'] == 'started'
    assert detail['messages'] == []


def test_child_reads_only_its_own_tasks(repo):
    store, rt, owner, _ = repo
    mine, other = task(repo), task(repo, taskId='other-task')
    sid = child(repo)
    attempt(repo, mine, sid)
    listing = run(rt, sid, 'task_list', {'runId': 'run-1'})
    assert [row['taskKey'] for row in listing['items']] == [mine['taskKey']]
    assert run(rt, sid, 'task_get', {'runId': 'run-1', 'taskId': mine['taskId']})['task']['taskKey']
    with pytest.raises(PermissionError, match='TASK_SURFACE_FORBIDDEN'):
        run(rt, sid, 'task_get', {'runId': 'run-1', 'taskId': other['taskId']})


def test_child_cannot_send_or_abandon(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    for name in ('task_send', 'task_abandon'):
        with pytest.raises(PermissionError, match='TASK_SURFACE_FORBIDDEN'):
            run(rt, sid, name, {'runId': 'run-1', 'taskId': item['taskId'], 'invocationId': 'inv-1',
                                'messageId': 'msg-1', 'kind': 'information', 'body': 'hi',
                                'expectedRevision': item['revision'], 'reason': 'stop'})


def test_send_is_idempotent_and_a_reused_id_with_other_body_conflicts(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    args = {'runId': 'run-1', 'taskId': item['taskId'], 'invocationId': 'inv-send',
            'messageId': 'msg-1', 'kind': 'information', 'body': 'receipts live in the store',
            'expectedRevision': item['revision']}
    first = run(rt, owner, 'task_send', args)
    assert first['ack'] == 'received' and first['consumed'] is False
    again = run(rt, owner, 'task_send', dict(args, invocationId='inv-send-2'))
    assert again['message']['messageId'] == first['message']['messageId']
    with pytest.raises(ContractError) as exc:
        run(rt, owner, 'task_send', dict(args, invocationId='inv-send-3', body='a different body'))
    assert exc.value.code == 'TASK_MESSAGE_CONFLICT'
    assert run(rt, owner, 'task_get', {'runId': 'run-1', 'taskId': item['taskId']})['messages']


def test_send_requires_ids_and_an_expected_revision(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    with pytest.raises(ContractError) as exc:
        run(rt, owner, 'task_send', {'runId': 'run-1', 'taskId': item['taskId'], 'kind': 'information',
                                     'body': 'x', 'expectedRevision': item['revision']})
    assert exc.value.field == 'invocationId'


def test_missing_run_is_named(repo, monkeypatch):
    store, rt, owner, _ = repo
    monkeypatch.setattr(work_scope, 'turn_binding', lambda _rt, _session: None)
    monkeypatch.setattr(work_scope, '_graph', lambda _rt: None)
    with pytest.raises(ContractError) as exc:
        run(rt, owner, 'task_list', {})
    assert exc.value.code == 'TASK_SURFACE_NO_RUN'


def test_unknown_tool_name_fails_closed(repo):
    store, rt, owner, _ = repo
    with pytest.raises(PermissionError, match='TASK_SURFACE_UNKNOWN'):
        asyncio.run(task_surface.handle(rt, session(rt, owner), 'task_dance', {'runId': 'run-1'}))


# --- 4. Abandon + đường huỷ thật ---------------------------------------------------------

def test_abandon_requests_cancel_through_cancel_child(repo, monkeypatch):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    calls = []

    async def fake_cancel(_rt, session, args):
        calls.append((session['id'], dict(args)))
        return {'sessionId': args['sessionId'], 'status': 'cancelled', 'cancelledBy': 'owner'}

    monkeypatch.setattr(task_surface.research_runtime, 'cancel_child', fake_cancel)
    current = fresh(repo, item)
    result = run(rt, owner, 'task_abandon', {'runId': 'run-1', 'taskId': item['taskId'],
                                             'invocationId': 'inv-abandon',
                                             'expectedRevision': current['revision'],
                                             'reason': 'owner changed scope'})
    assert result['task']['controlState'] == 'cancel_requested'
    assert calls == [(owner, {'sessionId': sid, 'reason': 'owner changed scope'})]
    assert result['cancel']['cancelledBy'] == 'owner'
    assert 'Artifacts' in result['note']


def test_abandon_without_an_open_attempt_does_not_cancel(repo, monkeypatch):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)

    async def boom(*_args, **_kwargs):  # pragma: no cover - không được gọi
        raise AssertionError('no open attempt ⇒ no cancel')

    monkeypatch.setattr(task_surface.research_runtime, 'cancel_child', boom)
    current = fresh(repo, item)
    result = run(rt, owner, 'task_abandon', {'runId': 'run-1', 'taskId': item['taskId'],
                                             'invocationId': 'inv-abandon',
                                             'expectedRevision': current['revision'],
                                             'reason': 'never started'})
    assert result['cancel'] is None
    # Không có attempt đang mở ⇒ không có gì để DỪNG: chỉ nhu cầu kết thúc, không yêu cầu huỷ.
    assert result['task']['controlState'] is None
    assert result['task']['state'] == 'abandoned'


def test_a_broken_cancel_path_still_reports_the_recorded_abandon(repo, monkeypatch):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)

    async def boom(*_args, **_kwargs):
        raise RuntimeError('CANCEL_CHILD_NOT_MINE: nope')

    monkeypatch.setattr(task_surface.research_runtime, 'cancel_child', boom)
    current = fresh(repo, item)
    result = run(rt, owner, 'task_abandon', {'runId': 'run-1', 'taskId': item['taskId'],
                                             'invocationId': 'inv-abandon',
                                             'expectedRevision': current['revision'],
                                             'reason': 'stop'})
    assert result['task']['controlState'] == 'cancel_requested'
    assert result['cancel']['status'] == 'cancel_failed'
    assert 'CANCEL_CHILD_NOT_MINE' in result['cancel']['error']


# --- 5. Chiếu kết cục của con vào attempt -------------------------------------------------

def test_project_child_closes_the_open_attempt(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    store.child_finish(sid, 'completed', reason=None, steps_used=3, output_tokens=10, answer_chars=42)
    assert task_surface.project_child(rt, sid)['status'] == 'succeeded'
    detail = run(rt, owner, 'task_get', {'runId': 'run-1', 'taskId': item['taskId']})
    assert detail['task']['state'] == 'succeeded'
    assert detail['receipts'][0]['childStatus'] == 'completed'
    # Chiếu lại lần hai: không còn attempt mở nên là no-op, và không sinh revision mới.
    revision = detail['task']['revision']
    assert task_surface.project_child(rt, sid) is None
    assert run(rt, owner, 'task_get', {'runId': 'run-1', 'taskId': item['taskId']})['task']['revision'] == revision


def test_project_child_is_a_noop_for_unknown_or_open_children(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    assert task_surface.project_child(rt, 'no-such-child') is None
    assert task_surface.project_child(rt, sid) is None
    assert task_surface.project_child(rt, child(repo)) is None


def test_project_child_never_raises_and_logs(repo, monkeypatch):
    store, rt, owner, _ = repo
    sid = child(repo)

    def broken(_rt):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(task_surface, 'service', broken)
    store.child_finish(sid, 'failed', reason='PROVIDER_STREAM_INTERRUPTED', steps_used=1,
                       output_tokens=2, answer_chars=0)
    assert task_surface.project_child(rt, sid) is None


def test_close_attempt_skips_a_reopened_child(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    store.child_finish(sid, 'completed', reason=None, steps_used=1, output_tokens=1, answer_chars=1)
    store.child_start(sid, owner, 1, 2, 'explore', 'again')
    assert task_surface.service(rt).close_attempt(sid, 'completed', None) is None
    assert run(rt, owner, 'task_get', {'runId': 'run-1', 'taskId': item['taskId']})['attempts'][0]['status'] == 'running'


def test_close_attempt_does_not_resurrect_an_abandoned_task(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    service = task_surface.service(rt)
    service.abandon(owner, 'run-1', item['taskKey'], invocation_id='inv-abandon',
                    expected_revision=fresh(repo, item)['revision'], reason='owner moved on')
    store.child_finish(sid, 'cancelled', reason='OWNER_CANCELLED', steps_used=1, output_tokens=1,
                       answer_chars=0)
    assert task_surface.project_child(rt, sid)['status'] == 'cancelled'
    detail = run(rt, owner, 'task_get', {'runId': 'run-1', 'taskId': item['taskId']})
    assert detail['task']['controlState'] == 'cancel_requested'
    assert detail['attempts'][0]['status'] == 'cancelled'


def test_close_attempt_ignores_unknown_outcomes(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    assert task_surface.service(rt).close_attempt(sid, 'vibing', None) is None


def test_closed_snapshot_is_immutable_after_a_new_attempt(repo):
    store, rt, owner, _ = repo
    item = task(repo)
    sid = child(repo)
    attempt(repo, item, sid)
    store.child_finish(sid, 'completed', reason=None, steps_used=1, output_tokens=1, answer_chars=1)
    assert task_surface.project_child(rt, sid)['status'] == 'succeeded'
    # Đúng câu lệnh mở lại của `work_feedback.resume_child`: `child_start` không xoá `finished`.
    store.db.execute("UPDATE children SET status='started',finished=NULL,started=? WHERE session_id=?",
                     (__import__('time').time(), sid))
    store.db.commit()
    second = attempt(repo, item, sid, invocation='inv-attempt-2', admission='admission-2')
    assert second['attemptSeq'] == 2 and second['status'] == 'running'
    detail = run(rt, owner, 'task_get', {'runId': 'run-1', 'taskId': item['taskId']})
    # `attempts()` phân trang theo `attemptId`; thứ tự lịch sử đọc theo `attemptSeq`.
    assert [a['status'] for a in sorted(detail['attempts'], key=lambda a: a['attemptSeq'])] == \
           ['succeeded', 'running']


# --- 6. `delegate_task` mang hợp đồng task (đường nối thật của H3) --------------------------

def delegate_args(goal='Find receipts', role='explore', **updates):
    contract = {'schema': TASK_SCHEMA, 'taskId': 'inspect-receipts',
                'invocationId': 'inv-delegate-receipts', 'role': role, 'goal': goal,
                'intent': 'analysis', 'mode': 'read_only', 'inputs': [],
                'scope': {'read': ['backend/src'], 'write': [], 'externalSources': 'none'},
                'deliverable': {'kind': 'knowledge', 'format': 'markdown', 'evidence': ['file_line'],
                                'acceptance': ['Name the canonical closer.']},
                'dependsOn': [], 'budget': {'allocationPolicy': 'inherited'}, 'wait': False}
    contract.update(updates.pop('contract', {}))
    args = {'role': role, 'goal': goal, 'wait': False, 'task': contract, 'runId': 'run-1'}
    args.update(updates)
    return args


def runtime_repo(tmp_path, monkeypatch, answers):
    """Runtime thật + kho thật; chỉ `_resolve_run` được thay bằng run của fixture."""
    from agentbox.agent_core.runtime import HarnessRuntime
    from test_harness_runtime import FixtureExecutor, FixtureModel

    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel(answers))
    sid = runtime.create({'skills': [], 'tools': ['delegate_task', 'task_list']})['id']
    monkeypatch.setenv('BOXFOX_TASK_SURFACE', 'on')
    monkeypatch.setattr(task_surface, '_resolve_run',
                        lambda _rt, owner_id, run_id: {'runId': run_id, 'sessionId': owner_id}
                        if run_id == 'run-1' else None)
    return store, runtime, sid


def test_delegate_with_a_contract_creates_the_task_and_binds_the_attempt(tmp_path, monkeypatch):
    import asyncio
    from test_harness_runtime import answer, call

    store, runtime, sid = runtime_repo(tmp_path, monkeypatch, [
        answer(calls=[call('delegate_task', delegate_args())]),
        answer('cha chốt lượt, con còn chạy')])
    async def drive():
        runtime.start(sid, 'giao việc có hợp đồng')
        await runtime.tasks[sid]

    asyncio.run(drive())

    service = task_surface.service(runtime)
    listing = service.list(sid, 'run-1')
    assert [row['taskId'] for row in listing['items']] == ['inspect-receipts']
    key = listing['items'][0]['taskKey']
    detail = service.get(sid, 'run-1', key)
    assert detail['contract']['goal'] == 'Find receipts'
    attempts = service.attempts(sid, 'run-1', key)['items']
    assert len(attempts) == 1 and attempts[0]['status'] == 'failed'
    assert attempts[0]['reason'] == 'PARENT_TURN_ENDED', 'người dọn T7 đóng con, chiếu vào attempt'
    assert attempts[0]['sessionId'] in [c['session_id'] for c in store.children_of(sid)]
    receipt = [json.loads(m['content']) for m in store.get(sid)['messages'] if m['role'] == 'tool'][0]
    assert receipt['task']['taskKey'] == key and receipt['task']['attempt']['status'] == 'running'
    assert receipt['task']['taskId'] == 'inspect-receipts'
    store.close()


def test_delegate_without_a_contract_creates_nothing(tmp_path, monkeypatch):
    import asyncio
    from test_harness_runtime import answer, call

    store, runtime, sid = runtime_repo(tmp_path, monkeypatch, [
        answer(calls=[call('delegate_task', {'role': 'explore', 'goal': 'Find receipts',
                                             'wait': False, 'runId': 'run-1'})]),
        answer('xong')])
    async def drive():
        runtime.start(sid, 'giao việc thường')
        await runtime.tasks[sid]

    asyncio.run(drive())
    assert task_surface.service(runtime).list(sid, 'run-1')['items'] == []
    receipt = [json.loads(m['content']) for m in store.get(sid)['messages'] if m['role'] == 'tool'][0]
    assert 'task' not in receipt
    store.close()


def test_delegate_contract_role_mismatch_fails_before_any_child(tmp_path, monkeypatch):
    import asyncio
    from test_harness_runtime import answer, call

    store, runtime, sid = runtime_repo(tmp_path, monkeypatch, [answer('xong')])
    session = store.get(sid)
    with pytest.raises(ContractError) as exc:
        task_surface.open_delegate(runtime, session, delegate_args(role='explore',
                                                                  contract={'role': 'review'}))
    assert exc.value.code == 'TASK_DELEGATE_ROLE_MISMATCH'
    assert store.children_of(sid) == []
    store.close()


def test_open_delegate_is_a_noop_for_a_non_root_session_and_a_disabled_switch(tmp_path, monkeypatch):
    store, runtime, sid = runtime_repo(tmp_path, monkeypatch, [])
    child_id = runtime.create({'skills': []}, parent_id=sid, role='explore')['id']
    assert task_surface.open_delegate(runtime, store.get(child_id), delegate_args()) is None
    monkeypatch.delenv('BOXFOX_TASK_SURFACE', raising=False)
    assert task_surface.open_delegate(runtime, store.get(sid), delegate_args()) is None
    store.close()
