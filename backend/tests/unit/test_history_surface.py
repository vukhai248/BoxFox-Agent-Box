"""Bề mặt bền của main (`agent_core/history_surface.py`) + các route của nó.

Kiểm đúng ba thứ mà `HistoryStore` KHÔNG tự quyết được: chủ cục bộ, phạm vi đọc giữa các phiên,
và trạng thái canonical để mang theo khi xoá. Mọi ca chạy trên `HarnessRuntime` thật (SQLite trong
`tmp_path`), riêng route gọi qua aiohttp thật như `test_desktop_api.py` đang làm.
"""
from __future__ import annotations

import asyncio
import json

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import history_surface
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}
BASE = {'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash'}


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'ok': True}

    async def cleanup(self, sid):
        return None


class FixtureModel:
    def __init__(self, responses=()):
        self.responses = iter(responses)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return next(self.responses)


def build(tmp_path, name='sessions.db', values=None, project=None):
    store = SessionStore(tmp_path / name)
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    history_surface.configure_runtime(runtime)
    session = runtime.create(dict(values or BASE))
    if project:
        # `machineBinding` không nằm trong danh sách khoá `create()` chép vào config, nên ca kiểm
        # ghim nó bằng tay rồi buộc `bind_session` đọc lại — đúng đường resolver thật.
        workspace = tmp_path / (name + '-ws')
        workspace.mkdir(exist_ok=True)
        config = dict(session['config'])
        config['machineBinding'] = {'mode': 'host', 'revision': 1, 'projectId': project,
                                    'workspace': str(workspace)}
        store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), session['id']))
        store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (session['id'],))
        store.db.commit()
        session = store.get(session['id'])
        bind(runtime, session['id'])
    return store, runtime, session


def bind(runtime, sid):
    return history_surface.service(runtime).bind_session(sid)


def ingest(runtime, sid, text, key, owner=True):
    return runtime.history_ingest(sid, {'role': 'user', 'content': text}, key, owner=owner)


# --------------------------------------------------------------- hook và phạm vi

def test_session_creation_binds_a_raw_scope_without_breaking_creation(tmp_path):
    store, runtime, session = build(tmp_path)
    scope = bind(runtime, session['id'])
    assert scope['session_id'] == session['id']
    assert scope['root_session_id'] == session['id']
    assert scope['agent_id'] == session['id']
    assert scope['status'] == 'active'
    assert scope['project_id'] is None, 'chat không có project thì ở lại phạm vi self'
    assert history_surface.owner_identity(runtime).startswith('owner-')
    store.close()


def test_child_reads_ancestry_and_descendants_but_never_siblings(tmp_path):
    store, runtime, root = build(tmp_path, project='p1')
    child = runtime.create(dict(BASE), parent_id=root['id'])
    sibling = runtime.create(dict(BASE), parent_id=root['id'])
    grand = runtime.create(dict(BASE), parent_id=child['id'])
    allowed = history_surface._authorization(runtime)

    assert allowed(root['id'], child['id'], {}) is True, 'root sở hữu cả project'
    assert allowed(child['id'], root['id'], {}) is True, 'con đọc được tổ tiên'
    assert allowed(child['id'], grand['id'], {}) is True, 'con đọc được con của nó'
    assert allowed(child['id'], sibling['id'], {}) is False, 'anh em không đọc nhau'
    assert allowed(grand['id'], sibling['id'], {}) is False
    assert allowed(root['id'], sibling['id'], {'capsule': True}) is True, 'chủ gốc mang capsule cả cây'
    assert allowed(child['id'], sibling['id'], {'capsule': True}) is False, 'capsule chỉ mở cho chủ gốc'
    assert allowed(child['id'], child['id'], {}) is True

    # Cây khác project: capsule không bao giờ đi qua ranh giới project.
    (tmp_path / 'other-ws').mkdir()
    other = runtime.create(dict(BASE))
    config = dict(other['config'])
    config['machineBinding'] = {'mode': 'host', 'revision': 1, 'projectId': 'p2',
                                'workspace': str(tmp_path / 'other-ws')}
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), other['id']))
    store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (other['id'],))
    store.db.commit()
    bind(runtime, other['id'])
    assert allowed(root['id'], other['id'], {'capsule': True}) is False, 'capsule của cây khác project'
    store.close()


def test_no_project_means_no_cross_session_read_even_with_the_same_owner(tmp_path):
    store, runtime, root = build(tmp_path)
    other = runtime.create(dict(BASE))
    assert history_surface._authorization(runtime)(root['id'], other['id'], {}) is False
    store.close()


# --------------------------------------------------------------- công cụ history

def test_history_tools_dispatch_contract_shapes_and_denials(tmp_path):
    store, runtime, session = build(tmp_path)
    sid = session['id']
    ingest(runtime, sid, 'hãy đọc tệp ghi chú rồi tóm tắt', 'k1')
    runtime.history_ingest(sid, {'role': 'assistant', 'content': 'đã đọc xong'}, 'k2')

    listed = asyncio.run(history_surface.dispatch(runtime, sid, 'history_list', {}))
    assert set(listed) >= {'hits', 'nextCursor', 'hasMore', 'coverage'}
    assert listed['hits'] and listed['hits'][0]['sessionId'] == sid
    found = asyncio.run(history_surface.dispatch(runtime, sid, 'history_search', {'query': 'tóm tắt'}))
    assert found['hits'] and 'tóm tắt' in found['hits'][0]['snippet']
    record_id = found['hits'][0]['recordId']
    read = asyncio.run(history_surface.dispatch(runtime, sid, 'history_read', {'recordId': record_id}))
    assert read['untrusted'] is True and 'tóm tắt' in read['content']

    missing = asyncio.run(history_surface.dispatch(runtime, sid, 'history_read', {'recordId': 'nope'}))
    assert missing['is_error'] is True and missing['errorCode'] == 'HISTORY_REFERENCE_NOT_FOUND'
    denied = asyncio.run(history_surface.dispatch(runtime, sid, 'history_list', {'scope': 'parent'}))
    assert denied['is_error'] is True and denied['errorCode'] == 'HISTORY_SCOPE_DENIED'
    project = asyncio.run(history_surface.dispatch(runtime, sid, 'history_list', {'scope': 'project'}))
    assert project['is_error'] is True and project['errorCode'] == 'HISTORY_SCOPE_DENIED'
    store.close()


def test_critical_snapshot_covers_every_required_key_and_stays_bounded(tmp_path):
    store, runtime, session = build(tmp_path)
    sid = session['id']
    child = runtime.create(dict(BASE), parent_id=sid)
    runtime.decision_store.request(
        {'decisionId': 'd1', 'sessionId': sid, 'kind': 'interview', 'options': [], 'deadline': None},
        {'question': 'chọn đi'}, {})
    snapshot = history_surface._critical_snapshot(runtime)([sid, child['id']])
    assert set(snapshot) == set(history_surface.CAPSULE_KEYS)
    assert [item['decisionId'] for item in snapshot['decisions']] == ['d1']
    assert json.loads(json.dumps(snapshot)) == snapshot
    store.close()


def test_quiescence_is_false_while_a_child_runs_and_true_once_it_is_done(tmp_path):
    store, runtime, session = build(tmp_path)
    sid = session['id']
    child = runtime.create(dict(BASE), parent_id=sid)
    quiet = history_surface._quiescence(runtime)
    assert quiet([sid]) is True

    async def live_child():
        pending = asyncio.get_running_loop().create_future()
        runtime.tasks[child['id']] = pending
        assert quiet([sid, child['id']]) is False, 'con đang chạy thì cây chưa yên'
        pending.set_result(True)
        assert quiet([sid, child['id']]) is True

    asyncio.run(live_child())

    store.emit(sid, 'tool_end', {'id': 'c1', 'name': 'file_write', 'result': {'ok': True}})
    store.db.execute("INSERT INTO children(session_id,parent_id,parent_turn,spawn_step,role,status,started) "
                     "VALUES(?,?,0,0,'worker','started',0)", (child['id'], sid))
    store.db.commit()
    assert quiet([sid, child['id']]) is False, 'con còn mở trong sổ thì chưa yên'
    store.close()


# --------------------------------------------------------------- xoá có mang theo

def test_deletion_preview_then_confirm_keeps_the_capsule_and_hides_raw(tmp_path):
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ref = ingest(runtime, sid, 'yêu cầu gốc phải giữ', 'k1')
    preview = history_surface.deletion_preview(runtime, sid, {'mode': 'history_only'})
    assert preview['validation']['status'] == 'validated'
    assert preview['validation']['errors'] == []
    assert preview['capsuleId'] and len(preview['expectedRevision']) == 64
    assert preview['sessionIds'] == [sid]

    result = history_surface.deletion_confirm(runtime, sid, {
        'operationId': preview['operationId'], 'expectedRevision': preview['expectedRevision'], 'confirm': True})
    assert result['status'] == 'deleted' and result['capsuleId'] == preview['capsuleId']
    capsule = history_surface.service(runtime).read_capsule(sid, preview['capsuleId'])
    assert capsule['executionAuthority'] is False
    assert capsule['critical'].keys() == set(history_surface.CAPSULE_KEYS)
    # Bản ghim còn nguyên, nhưng bản thô chỉ còn là mộ: nội dung rỗng, cờ `deleted`.
    tombstone = history_surface.service(runtime).read_reference(sid, ref['recordId'])
    assert tombstone['evidenceState'] == 'deleted' and tombstone['content'] == ''
    try:
        history_surface.service(runtime)._payload(sid, ref)
        raise AssertionError('payload thô đã xoá thì không đọc lại được')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'HISTORY_DELETED'
    store.close()


def test_a_live_run_makes_the_first_confirm_conflict_and_the_second_one_delete(tmp_path):
    """Huỷ run đang sống đổi bản ghim critical, nên lần xác nhận đầu phải trả conflict.

    Đây là hệ quả đã biết của thứ tự `settle_deleted_runs` → `delete_with_capsule`: bản xem trước
    thứ hai thấy cây đã yên và đi hết đường. Ca kiểm ghim đúng hành vi đó thay vì để nó thành
    một lần hỏng không tên.
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu còn dở', 'k1')
    goal = history_surface.service(runtime).contract(sid)['currentRevision']
    runtime.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i1',
                                     'goalRevision': goal,
                                     'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
    preview = history_surface.deletion_preview(runtime, sid, {'mode': 'history_only'})
    assert preview['validation']['status'] == 'validated'
    try:
        history_surface.deletion_confirm(runtime, sid, {'operationId': preview['operationId'],
                                                        'expectedRevision': preview['expectedRevision'],
                                                        'confirm': True})
        raise AssertionError('run đang sống bị huỷ làm đổi bản ghim: lần đầu phải conflict')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'DELETE_REVISION_CONFLICT'
    second = history_surface.deletion_preview(runtime, sid, {'mode': 'history_only'})
    assert second['operationId'] != preview['operationId']
    result = history_surface.deletion_confirm(runtime, sid, {'operationId': second['operationId'],
                                                             'expectedRevision': second['expectedRevision'],
                                                             'confirm': True})
    assert result['status'] == 'deleted' and result['capsuleId'] == second['capsuleId']
    store.close()


def test_deletion_preview_refuses_a_stale_revision_and_a_foreign_mode(tmp_path):
    store, runtime, session = build(tmp_path)
    sid = session['id']
    ingest(runtime, sid, 'nội dung', 'k1')
    try:
        history_surface.deletion_preview(runtime, sid, {'mode': 'history_only', 'expectedRevision': 'x' * 64})
        raise AssertionError('revision lệch phải bị từ chối')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'DELETE_REVISION_CONFLICT'
    try:
        history_surface.deletion_preview(runtime, sid, {'mode': 'workspace_and_history'})
        raise AssertionError('chỉ có một chế độ xoá được duyệt')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'DELETE_MODE_UNSUPPORTED'
    store.close()


# --------------------------------------------------------------- tác vụ dài

def test_completion_hook_reports_waiting_runnable_and_shipped(tmp_path):
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    run = {'runId': 'lt-x', 'budget': {'revision': 1}}
    completion = history_surface._completion(runtime)

    assert completion(sid, run)['state'] == 'runnable'
    child = runtime.create(dict(BASE), parent_id=sid)

    async def while_child_runs():
        pending = asyncio.get_running_loop().create_future()
        runtime.tasks[child['id']] = pending
        waiting = completion(sid, run)
        assert waiting['state'] == 'waiting_children' and waiting['requiredActive'] is True
        pending.set_result(True)

    asyncio.run(while_child_runs())

    from agentbox.agent_core import work_graph
    work_graph.service(runtime)
    runtime.store.db.execute("INSERT INTO work_runs VALUES('w1',?,'shipped',3,'{}',0,0)", (sid,))
    runtime.store.db.commit()
    shipped = completion(sid, run)
    assert shipped['state'] == 'completed' and shipped['acceptanceSatisfied'] is True
    assert shipped['evidenceFingerprint'] and shipped['evidenceRefs'] == [{'workRunId': 'w1'}]
    store.close()


def test_owner_acceptance_verifies_canonical_refs_only(tmp_path):
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ref = ingest(runtime, sid, 'bằng chứng trong cây', 'k1')
    foreign = runtime.create(dict(BASE))
    foreign_ref = ingest(runtime, foreign['id'], 'bằng chứng ngoài cây', 'k2')
    acceptance = history_surface._owner_acceptance(runtime)

    ok = acceptance(sid, {'runId': 'lt'}, {'evidenceRefs': [{'recordId': ref['recordId']}]})
    assert ok['acceptanceSatisfied'] is True and ok['evidenceFingerprint']
    assert ok['evidenceRefs'] == [{'recordId': ref['recordId']}]

    bad = acceptance(sid, {'runId': 'lt'}, {'evidenceRefs': [{'recordId': foreign_ref['recordId']}]})
    assert bad['acceptanceSatisfied'] is False and bad['failedChecks']
    try:
        acceptance(sid, {'runId': 'lt'}, {'evidenceRefs': []})
        raise AssertionError('thiếu ref thì không được nghiệm thu')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'LONGTASK_ACCEPTANCE_REQUIRED'
    store.close()


def test_longtask_configure_needs_a_project_and_pins_the_contract(tmp_path):
    store, runtime, chat = build(tmp_path)
    try:
        runtime.configure_longtask(chat['id'], {'enabled': True, 'resumePolicy': 'manual',
                                                'invocationId': 'i1', 'goalRevision': 0,
                                                'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
        raise AssertionError('chat không có project thì không mở được tác vụ dài')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'LONGTASK_PROJECT_REQUIRED'
    store.close()

    store2, runtime2, session = build(tmp_path, name='s2.db', project='p1')
    sid = session['id']
    # Neo canonical chỉ có nghĩa khi chủ đã ghi ít nhất một yêu cầu: revision 0 = chưa có mốc nào.
    ingest(runtime2, sid, 'mục tiêu ban đầu của chủ', 'k1')
    goal = history_surface.service(runtime2).contract(sid)['currentRevision']
    assert goal >= 1
    created = runtime2.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual',
                                                'invocationId': 'i1', 'goalRevision': goal,
                                                'contractRef': history_surface.contract_hash(
                                                    history_surface.service(runtime2).contract(sid)),
                                                'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
    assert created['state'] == 'ready' and created['goalRevision'] == goal
    assert created['binding']['projectId'] == 'p1'
    try:
        runtime2.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i2',
                                          'goalRevision': goal + 1,
                                          'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
        raise AssertionError('goalRevision lệch phải bị từ chối')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'LONGTASK_STALE'
    store2.close()


# --------------------------------------------------------------- route

def test_routes_expose_the_three_session_keys_and_the_durable_surface(tmp_path):
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'nội dung tìm được', 'k1')

    async def call():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession() as client:
                base = str(server.make_url('')).rstrip('/')
                out = {}
                async with client.get(base + f'/api/agent/sessions/{sid}', headers=HEADERS) as response:
                    out['session'] = await response.json()
                    out['session_status'] = response.status
                async with client.get(base + f'/api/agent/history/search?callerSessionId={sid}&query=tìm',
                                      headers=HEADERS) as response:
                    out['search'] = await response.json()
                    out['search_status'] = response.status
                async with client.get(base + f'/api/agent/history/storage?callerSessionId={sid}',
                                      headers=HEADERS) as response:
                    out['storage'] = await response.json()
                async with client.get(base + f'/api/agent/sessions/{sid}/decisions?state=pending',
                                      headers=HEADERS) as response:
                    out['decisions'] = await response.json()
                async with client.put(base + f'/api/agent/sessions/{sid}/longtask', headers=HEADERS,
                                      json={'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i1',
                                            'goalRevision': out['session']['goalRevision'],
                                            'contractRef': out['session']['contractRef'],
                                            'budget': {'totalStepLimit': 4, 'activeTimeLimitMs': 60000}}) as response:
                    out['longtask'] = await response.json()
                    out['longtask_status'] = response.status
                async with client.post(base + f'/api/agent/sessions/{sid}/longtask/actions', headers=HEADERS,
                                       json={'runId': out['longtask']['runId'], 'action': 'pause',
                                             'expectedRevision': out['longtask']['revision'],
                                             'invocationId': 'i2'}) as response:
                    out['paused'] = await response.json()
                async with client.post(base + f'/api/agent/sessions/{sid}/deletion-preview', headers=HEADERS,
                                       json={'mode': 'history_only'}) as response:
                    out['preview'] = await response.json()
                async with client.delete(base + f'/api/agent/sessions/{sid}', headers=HEADERS) as response:
                    out['legacy_delete'] = await response.json()
                    out['legacy_delete_status'] = response.status
                async with client.get(base + f'/api/agent/sessions/{sid}/tasks', headers=HEADERS) as response:
                    out['tasks'] = await response.json()
                return out

    out = asyncio.run(call())
    assert out['session_status'] == 200
    assert {'longtask', 'goalRevision', 'contractRef'} <= set(out['session'])
    assert out['session']['longtask'] is None and out['session']['goalRevision'] >= 1
    assert len(out['session']['contractRef']) == 64
    assert out['search_status'] == 200 and out['search']['hits']
    assert out['storage']['unit'] == 'GB' and out['storage']['measurementComplete'] is True
    assert out['storage']['warningAtBytes'] == 4_000_000_000
    assert out['decisions']['decisions'] == []
    assert out['longtask_status'] == 200 and out['longtask']['state'] == 'ready'
    assert out['paused']['state'] == 'paused'
    assert out['preview']['validation']['status'] == 'validated'
    assert out['legacy_delete_status'] == 409
    assert out['legacy_delete']['code'] == 'DELETE_REQUIRES_CARRY_FORWARD'
    # Mỗi lần xem trước cấp một operation/capsule mới; cả hai đều phải tự kiểm đạt.
    assert out['legacy_delete']['preview']['capsuleId'] != out['preview']['capsuleId']
    assert out['legacy_delete']['preview']['validation']['status'] == 'validated'
    assert out['legacy_delete']['preview']['sessionIds'] == out['preview']['sessionIds']
    assert out['tasks'] == {'tasks': [], 'hasMore': False, 'nextAfter': None}
    store.close()


def test_history_route_needs_an_explicit_caller_and_never_a_foreign_scope(tmp_path):
    store, runtime, session = build(tmp_path)
    sid = session['id']

    async def call():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession() as client:
                base = str(server.make_url('')).rstrip('/')
                async with client.get(base + '/api/agent/history/search', headers=HEADERS) as response:
                    missing = (response.status, await response.json())
                async with client.get(base + f'/api/agent/history/search?callerSessionId={sid}&scope=project',
                                      headers=HEADERS) as response:
                    denied = (response.status, await response.json())
                async with client.get(base + f'/api/agent/history/records/unknown?callerSessionId={sid}',
                                      headers=HEADERS) as response:
                    absent = (response.status, await response.json())
                return missing, denied, absent

    missing, denied, absent = asyncio.run(call())
    assert missing[0] == 400 and missing[1]['code'] == 'HISTORY_CALLER_REQUIRED'
    assert denied[0] == 403 and denied[1]['code'] == 'HISTORY_SCOPE_DENIED'
    assert absent[0] == 404 and absent[1]['code'] == 'HISTORY_REFERENCE_NOT_FOUND'
    store.close()
