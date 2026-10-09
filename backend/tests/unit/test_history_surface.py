"""Bề mặt bền của main (`agent_core/history_surface.py`) + các route của nó.

Kiểm đúng ba thứ mà `HistoryStore` KHÔNG tự quyết được: chủ cục bộ, phạm vi đọc giữa các phiên,
và trạng thái canonical để mang theo khi xoá. Mọi ca chạy trên `HarnessRuntime` thật (SQLite trong
`tmp_path`), riêng route gọi qua aiohttp thật như `test_desktop_api.py` đang làm.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import context_surface, history_surface
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.history_store import HistoryError
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


# ------------------------------------------- F02/F09/F19: lượt nén để lại dấu vết đọc được

def test_a_compaction_keeps_the_raw_view_and_writes_the_host_archive(tmp_path):
    """Đường nén sống: bản thô vào kho bền TRƯỚC khi danh sách sống bị thay, rồi ra workspace host.

    Ca này chạy đúng hàm mà runtime gọi (`context_surface.compact`), không gọi lẻ `prepare_compaction`,
    nên nó bắt được cả việc nối dây lẫn thứ tự.
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'yêu cầu gốc', 'k1')
    saved = [{'role': 'user', 'content': 'yêu cầu gốc'}, {'role': 'assistant', 'content': 'đã làm xong'}]
    compacted = [{'role': 'user', 'content': 'yêu cầu gốc'}]
    event = {'kind': 'compression', 'beforeEstimate': 100, 'afterEstimate': 10}
    context_surface.compact(runtime, sid, saved, compacted, event)
    record = event['historyRecord']
    assert record['recorded'] is True and record['error'] is None, record

    row = store.db.execute('SELECT * FROM history_compactions WHERE checkpoint_id=?',
                           (record['checkpointId'],)).fetchone()
    assert row['state'] == 'committed' and row['session_id'] == sid
    manifest = json.loads(row['manifest_json'])
    assert manifest['agentId'] == sid and manifest['rootSessionId'] == sid
    assert [m['role'] for m in store.history.restore_compaction(manifest)] == ['user', 'assistant']
    kinds = [r['source_type'] for r in store.db.execute(
        "SELECT source_type FROM history_records WHERE session_id=? AND source_type='active_view'", (sid,))]
    assert len(kinds) == 2, 'mọi tin nhắn của active view cũ phải thành record thô'

    # Bản ghim đọc lại được bằng chính bộ đọc checkpoint thường.
    restored = [c for c in store.checkpoints(sid) if isinstance(c['messages'], list) and len(c['messages']) == 2]
    assert restored and restored[-1]['messages'][1]['content'] == 'đã làm xong'

    workspace = Path(session['config']['machineBinding']['workspace'])
    base = workspace / '.session-history' / sid / 'general_agent'
    assert (base / 'compaction_001.md').exists() and (base / 'compaction_001.json').exists()
    identity = json.loads((base / 'identity.json').read_text())
    assert identity == {'project_id': 'p1', 'root_session_id': sid, 'session_id': sid,
                        'agent_id': sid, 'parent_agent_id': None}
    assert record['projection']['projectionStored'] is True
    # §6: cây archive có CẢ `journal.md` lẫn bản nén — nhật ký curated là bản chiếu, không phải
    # transcript thô, và nó phải có mặt ngay khi context bị thay.
    journal = (base / 'journal.md').read_text(encoding='utf-8')
    assert journal.startswith('# Curated journal (not raw transcript)')
    assert record['journal']['projectionStored'] is True
    # INDEX là sổ phiên của bản chiếu (không phải danh sách tệp), và nó chỉ được làm mới khi bản
    # chiếu ghi xong — nên nó có mặt là dấu hiệu cả hai tệp trên đã đi qua cùng một lượt ghi.
    index = json.loads((workspace / '.session-history' / 'INDEX.json').read_text(encoding='utf-8'))
    assert index['projectionOnly'] is True
    assert [s['session_id'] for s in index['sessions']] == [sid]
    stored = store.db.execute('SELECT projection_status FROM history_compactions WHERE checkpoint_id=?',
                              (record['checkpointId'],)).fetchone()
    assert stored['projection_status'] == 'stored'
    store.db.close()


def test_the_same_compaction_twice_does_not_write_a_second_archive(tmp_path):
    """Gọi lại cùng một lượt nén là no-op: khoá suy từ nội dung, không sinh bản thứ hai."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')
    saved = [{'role': 'user', 'content': 'mục tiêu'}]
    first = history_surface.record_compaction(runtime, sid, saved, [], event={'kind': 'compression'})
    second = history_surface.record_compaction(runtime, sid, saved, [], event={'kind': 'compression'})
    assert first['checkpointId'] == second['checkpointId'] and first['sourceKey'] == second['sourceKey']
    count = store.db.execute('SELECT COUNT(*) AS n FROM history_compactions WHERE session_id=?',
                             (sid,)).fetchone()['n']
    assert count == 1
    store.db.close()


def test_a_container_session_keeps_the_manifest_and_says_why_it_skips_the_archive(tmp_path):
    """Phiên chạy trong container: bản thô vẫn được giữ, còn bản đọc được thì bỏ qua và NÓI RÕ lý do."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')
    config = dict(store.get(sid)['config'])
    config['machineBinding'] = {**config['machineBinding'], 'mode': 'docker'}
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), sid))
    store.db.commit()
    record = history_surface.record_compaction(runtime, sid, [{'role': 'user', 'content': 'mục tiêu'}], [],
                                               event={'kind': 'compression'})
    assert record['recorded'] is True
    assert record['projection']['projectionStored'] is False
    assert record['projection']['skipped'] == 'remote_or_unbound_workspace'
    assert record['journal'] is None, 'container thì không ghi bản chiếu nào, kể cả nhật ký'
    assert not list((tmp_path).rglob('compaction_*.md')), 'không được ghi bản đọc được từ host'
    store.db.close()


def test_a_child_compaction_lands_in_its_own_agent_namespace(tmp_path):
    """F19: con nén thì bản đọc được vào `subagent_<agentId>`, không lẫn vào namespace của root."""
    store, runtime, root = build(tmp_path, project='p1')
    child = runtime.create(dict(BASE), parent_id=root['id'])
    config = dict(child['config'])
    config['machineBinding'] = dict(root['config']['machineBinding'])
    config['historyAgentId'] = 'worker7'
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), child['id']))
    store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (child['id'],))
    store.db.commit()
    bind(runtime, root['id'])
    scope = bind(runtime, child['id'])
    assert scope['root_session_id'] == root['id'] and scope['agent_id'] == 'worker7'
    record = history_surface.record_compaction(runtime, child['id'], [{'role': 'user', 'content': 'việc con'}],
                                               [], event={'kind': 'compression'})
    workspace = Path(root['config']['machineBinding']['workspace'])
    base = workspace / '.session-history' / root['id'] / 'subagent_worker7'
    assert record['projection']['projectionStored'] is True
    assert (base / 'identity.json').exists()
    assert json.loads((base / 'identity.json').read_text())['parent_agent_id'] == root['id']
    store.db.close()


def test_a_broken_projection_does_not_claim_the_raw_copy_is_lost(tmp_path, monkeypatch):
    """Bản chiếu hỏng thì phải nói ĐÚNG phần nào hỏng: manifest còn, tệp đọc được thì thiếu."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')

    def boom(*args, **kwargs):
        raise OSError('disk full')

    monkeypatch.setattr(history_surface, 'export_projection', boom)
    event = {'kind': 'compression'}
    context_surface.compact(runtime, sid, [{'role': 'user', 'content': 'mục tiêu'}], [], event)
    record = event['historyRecord']

    assert record['recorded'] is True and record['checkpointId'], 'bản thô vẫn phải ở trong kho'
    assert record['projection'] == {'canonicalStored': True, 'projectionStored': False,
                                    'projectionError': 'PROJECTION_FAILED', 'skipped': None}
    # Hai tệp là hai lần ghi độc lập: bản nén hỏng không có nghĩa là nhật ký cũng hỏng, nên nó vẫn
    # được ghi và vẫn được báo đúng.
    assert record['journal']['projectionStored'] is True
    notice = [e for e in store.events(sid)
              if e['type'] == 'notice' and e['data'].get('code') == history_surface.PROJECTION_DEGRADED_CODE]
    assert 'disk full' in notice[0]['data']['message'], 'mã là mã, còn chuyện đã xảy ra vẫn phải có'
    row = store.db.execute('SELECT state FROM history_compactions WHERE checkpoint_id=?',
                           (record['checkpointId'],)).fetchone()
    assert row['state'] == 'committed', 'manifest đã commit thì không được hạ xuống theo bản chiếu'
    codes = [e['data'].get('code') for e in store.events(sid) if e['type'] == 'notice']
    assert history_surface.PROJECTION_DEGRADED_CODE in codes, codes
    assert history_surface.COMPACTION_DEGRADED_CODE not in codes, 'bản thô KHÔNG hỏng, đừng nói là hỏng'
    store.db.close()


def test_a_projection_that_returns_degraded_still_leaves_a_notice(tmp_path, monkeypatch):
    """`export_compaction` bắt lỗi rồi TRẢ dict hỏng chứ không ném: bỏ qua nhánh trả về là nén hỏng im.

    Ca này đúng thứ tự thật: bản thô đã commit (`state=committed`), bản chiếu hỏng, lượt nén vẫn
    trả về — nhưng phải có notice nói vì sao tệp đọc được không có. Bản trước chỉ bắt `except` nên
    ca này đi qua im lặng (đợt soát 2026-10-09, L1d-A).
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')

    def degraded(*args, **kwargs):
        return {'canonicalStored': True, 'projectionStored': False, 'skipped': None,
                'errorCode': 'CHECKPOINT_FILE_FAILED', 'projectionError': 'IsADirectoryError: …'}

    monkeypatch.setattr(history_surface, 'export_projection', degraded)
    event = {'kind': 'compression'}
    context_surface.compact(runtime, sid, [{'role': 'user', 'content': 'mục tiêu'}], [], event)
    record = event['historyRecord']

    assert record['recorded'] is True and record['checkpointId'], 'bản thô vẫn phải ở trong kho'
    assert record['projection']['projectionStored'] is False
    notice = [e for e in store.events(sid) if e['type'] == 'notice'
              and e['data'].get('code') == history_surface.PROJECTION_DEGRADED_CODE]
    assert notice, 'hỏng bản chiếu thì không được im lặng'
    assert 'CHECKPOINT_FILE_FAILED' in notice[0]['data']['message'], notice[0]['data']['message']
    assert 'IsADirectoryError' in notice[0]['data']['message'], 'mã là mã, chuyện đã xảy ra vẫn phải có'
    codes = [e['data'].get('code') for e in store.events(sid) if e['type'] == 'notice']
    assert history_surface.COMPACTION_DEGRADED_CODE not in codes, 'bản thô KHÔNG hỏng, đừng nói là hỏng'
    store.db.close()


def test_a_projection_that_returns_a_junk_code_still_gets_a_stable_one(tmp_path, monkeypatch):
    """`errorCode` lạ (không phải mã) thì notice phải mang mã ổn định, không mang chuỗi của nhà sản xuất."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')

    def degraded(*args, **kwargs):
        return {'canonicalStored': True, 'projectionStored': False, 'skipped': None,
                'errorCode': 'vỡ ở đâu đó', 'projectionError': 'vỡ ở đâu đó'}

    monkeypatch.setattr(history_surface, 'export_projection', degraded)
    event = {'kind': 'compression'}
    context_surface.compact(runtime, sid, [{'role': 'user', 'content': 'mục tiêu'}], [], event)

    notice = [e for e in store.events(sid) if e['type'] == 'notice'
              and e['data'].get('code') == history_surface.PROJECTION_DEGRADED_CODE]
    assert notice and '(PROJECTION_FAILED;' in notice[0]['data']['message'], notice
    store.db.close()


def test_a_failed_journal_export_does_not_overwrite_a_stored_projection(tmp_path, monkeypatch):
    """Hai tệp là hai lần ghi: `journal.md` hỏng không được báo thành bản nén hỏng.

    Ca này đúng thứ tự mà bản trước gộp nhầm: bản nén ghi xong (DB nói `stored`) rồi tới lượt
    `journal.md` mới hỏng — báo "bản chiếu không ghi xong" ở đây là nói dối theo chiều ngược lại.
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')

    def boom(*args, **kwargs):
        raise OSError('read-only file system')

    monkeypatch.setattr(history_surface, 'export_journal', boom)
    event = {'kind': 'compression'}
    context_surface.compact(runtime, sid, [{'role': 'user', 'content': 'mục tiêu'}], [], event)
    record = event['historyRecord']

    assert record['recorded'] is True and record['projection']['projectionStored'] is True, \
        'bản nén đã ghi xong thì phải nói là đã ghi xong'
    assert record['journal'] is None
    row = store.db.execute('SELECT projection_status FROM history_compactions WHERE checkpoint_id=?',
                           (record['checkpointId'],)).fetchone()
    assert row['projection_status'] == 'stored'
    workspace = Path(session['config']['machineBinding']['workspace'])
    assert (workspace / '.session-history' / sid / 'general_agent' / 'compaction_001.md').exists()
    codes = [e['data'].get('code') for e in store.events(sid) if e['type'] == 'notice']
    assert history_surface.JOURNAL_DEGRADED_CODE in codes, codes
    assert history_surface.PROJECTION_DEGRADED_CODE not in codes, 'bản nén không hỏng'
    store.db.close()


def test_a_history_store_that_never_materialized_does_not_kill_the_compaction(tmp_path, monkeypatch):
    """Kho lịch sử dựng hỏng từ lúc khởi động: `service(rt)` ném, và lượt nén vẫn phải đi tiếp."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')

    def boom(*args, **kwargs):
        raise HistoryError('HISTORY_SURFACE_UNAVAILABLE')

    monkeypatch.setattr(history_surface, 'service', boom)
    event = {'kind': 'compression'}
    receipt = context_surface.compact(runtime, sid, [{'role': 'user', 'content': 'mục tiêu'}], [], event)

    assert receipt and receipt.get('ref'), 'lượt nén vẫn phải trả về bản ghi của nó'
    assert event['historyRecord'] == {'recorded': False, 'checkpointId': None, 'projection': None,
                                      'journal': None, 'error': 'HISTORY_SURFACE_UNAVAILABLE'}
    codes = [e['data'].get('code') for e in store.events(sid) if e['type'] == 'notice']
    assert history_surface.COMPACTION_DEGRADED_CODE in codes, codes
    store.db.close()


def test_a_broken_history_store_leaves_a_notice_and_the_compaction_still_returns(tmp_path):
    """Kho lịch sử hỏng thì lượt nén không được chết: một notice bền, và không có manifest giả."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')

    def boom(*args, **kwargs):
        raise HistoryError('HISTORY_TEST_BOOM')

    store.history.prepare_compaction = boom
    event = {'kind': 'compression'}
    receipt = context_surface.compact(runtime, sid, [{'role': 'user', 'content': 'mục tiêu'}], [], event)
    assert receipt and receipt.get('ref')
    assert event['historyRecord'] == {'recorded': False, 'checkpointId': None, 'projection': None,
                                      'journal': None, 'error': 'HISTORY_TEST_BOOM'}
    notices = [e for e in store.events(sid) if e['type'] == 'notice']
    assert any(n['data'].get('code') == history_surface.COMPACTION_DEGRADED_CODE for n in notices), notices
    assert store.db.execute('SELECT COUNT(*) AS n FROM history_compactions WHERE session_id=?',
                            (sid,)).fetchone()['n'] == 0
    store.db.close()


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


def test_a_new_conversation_in_the_same_project_reads_the_capsule(tmp_path):
    """LT-08 ca 7: xoá raw rồi mở HỘI THOẠI MỚI cùng project — bài học/trạng thái còn đọc được.

    Cửa sổ đọc là project (capsule không mang quyền thực thi), nhưng một root của project phải mở
    được nó; nếu không thì "xoá có mang theo" chỉ là nửa đường: capsule ghi ra mà không ai đọc.
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'yêu cầu gốc phải giữ', 'k1')
    preview = history_surface.deletion_preview(runtime, sid, {
        'mode': 'history_only', 'lessons': [{'fact': 'đọc giữa log là đủ'}]})
    history_surface.deletion_confirm(runtime, sid, {
        'operationId': preview['operationId'], 'expectedRevision': preview['expectedRevision'], 'confirm': True})

    fresh = runtime.create(dict(BASE))
    workspace = tmp_path / 'fresh-ws'
    workspace.mkdir(exist_ok=True)
    config = dict(fresh['config'])
    config['machineBinding'] = {'mode': 'host', 'revision': 1, 'projectId': 'p1', 'workspace': str(workspace)}
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), fresh['id']))
    store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (fresh['id'],))
    store.db.commit()
    bind(runtime, fresh['id'])

    service = history_surface.service(runtime)
    assert [item['capsuleId'] for item in service.project_capsules(fresh['id'])] == [preview['capsuleId']]
    capsule = service.read_capsule(fresh['id'], preview['capsuleId'])
    assert capsule['executionAuthority'] is False
    assert capsule['critical'].keys() == set(history_surface.CAPSULE_KEYS)
    assert capsule['lessons'] == [{'fact': 'đọc giữa log là đủ'}]
    # Con của hội thoại mới không phải root ⇒ không mở được capsule.
    child = runtime.create(dict(BASE), parent_id=fresh['id'])
    with pytest.raises(HistoryError):
        service.read_capsule(child['id'], preview['capsuleId'])
    store.close()


def test_the_retained_state_block_goes_into_the_brief_of_a_new_conversation(tmp_path, monkeypatch):
    """Khối trạng thái chuyển tiếp (LT-08) nằm trong system prompt của hội thoại mới cùng project."""
    from agentbox.agent_core import session_journal

    monkeypatch.setenv('BOXFOX_LONGTASK_CONTINUITY', '1')
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'giữ nguyên yêu cầu gốc này', 'k1')
    preview = history_surface.deletion_preview(runtime, sid, {
        'mode': 'history_only', 'lessons': [{'fact': 'đọc giữa log là đủ'}]})
    history_surface.deletion_confirm(runtime, sid, {
        'operationId': preview['operationId'], 'expectedRevision': preview['expectedRevision'], 'confirm': True})

    fresh = runtime.create(dict(BASE))
    workspace = tmp_path / 'fresh-ws'
    workspace.mkdir(exist_ok=True)
    config = dict(fresh['config'])
    config['machineBinding'] = {'mode': 'host', 'revision': 1, 'projectId': 'p1', 'workspace': str(workspace)}
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), fresh['id']))
    store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (fresh['id'],))
    store.db.commit()
    bind(runtime, fresh['id'])

    block = session_journal.retained_state_block(store, fresh['id'])
    assert block.startswith(session_journal.RETAINED_STATE_HEADER)
    assert 'giữ nguyên yêu cầu gốc này' in block, 'yêu cầu chủ gốc phải còn trong bản chốt'
    assert 'đọc giữa log là đủ' in block and 'tombstone' in block
    assert len(block) <= session_journal.RETAINED_STATE_MAX_CHARS + len(session_journal.RETAINED_STATE_HEADER) + 200
    # Khối vào system prompt, và chèn lại không chồng (cùng luật với khối ghim).
    prompt = session_journal.inject_brief('SYSTEM', block)
    assert block in prompt
    assert session_journal.inject_brief(prompt, block) == prompt
    # Con của hội thoại mới không phải hội thoại ⇒ không dựng khối.
    child = runtime.create(dict(BASE), parent_id=fresh['id'])
    assert session_journal.retained_state_block(store, child['id']) == ''
    # Cờ tác vụ dài tắt thì khối rỗng (chế độ mặc định giữ nguyên prompt cũ).
    monkeypatch.delenv('BOXFOX_LONGTASK_CONTINUITY')
    assert session_journal.retained_state_block(store, fresh['id']) == ''
    store.close()


def test_a_live_run_is_closed_inside_the_delete_and_the_capsule_keeps_the_blocker(tmp_path):
    """Một lần xác nhận là đủ, và bản chốt giữ ĐÚNG blocker/ngân sách mà chủ đã nhìn thấy.

    Trước đây `settle_deleted_runs` chạy TRƯỚC cổng bản ghim, nên chính nó làm bản ghim lệch:
    lần xác nhận đầu luôn trả `DELETE_REVISION_CONFLICT`, chủ phải làm lại preview → xác nhận,
    và bản chốt được ghi là bản của lần xem trước thứ HAI — lúc đó run đã bị huỷ nên capsule
    mất sạch blocker lẫn ngân sách. Nay việc đóng run nằm trong giao dịch xoá, sau bước kiểm
    bản ghim, nên một lượt là xong và bản chốt vẫn mang theo thứ đáng giữ.
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu còn dở', 'k1')
    goal = history_surface.service(runtime).contract(sid)['currentRevision']
    runtime.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i1',
                                     'goalRevision': goal,
                                     'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
    # Run cạn ngân sách: chưa kết thúc, không còn nhịp chạy — đúng trạng thái mà cổng yên tĩnh
    # cho qua và cũng đúng trạng thái đã làm bản ghim lệch ở lần xác nhận đầu.
    runtime.longtask.store.transition(runtime.longtask.store.get(sid), 'budget_exhausted',
                                      'LONGTASK_BUDGET_EXHAUSTED')
    preview = history_surface.deletion_preview(runtime, sid, {'mode': 'history_only'})
    assert preview['validation']['status'] == 'validated'
    assert preview['retainedSummary']['critical']['blockers'], 'run chưa xong phải vào bản xem trước'

    result = history_surface.deletion_confirm(runtime, sid, {'operationId': preview['operationId'],
                                                             'expectedRevision': preview['expectedRevision'],
                                                             'confirm': True})
    assert result['status'] == 'deleted' and result['capsuleId'] == preview['capsuleId']
    row = store.db.execute('SELECT state,blocked_reason FROM longtask_runs WHERE session_id=?', (sid,)).fetchone()
    assert row['state'] == 'cancelled' and row['blocked_reason'] == 'HISTORY_DELETED'

    # Hội thoại mới cùng project đọc lại bản chốt: blocker và ngân sách vẫn còn nguyên.
    fresh = runtime.create(dict(BASE))
    workspace = tmp_path / 'after-ws'
    workspace.mkdir(exist_ok=True)
    config = dict(fresh['config'])
    config['machineBinding'] = {'mode': 'host', 'revision': 1, 'projectId': 'p1', 'workspace': str(workspace)}
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), fresh['id']))
    store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (fresh['id'],))
    store.db.commit()
    bind(runtime, fresh['id'])
    capsule = history_surface.service(runtime).read_capsule(fresh['id'], preview['capsuleId'])
    assert capsule['critical']['blockers'], 'bản chốt phải giữ blocker của run'
    assert capsule['critical']['budget'], 'bản chốt phải giữ ngân sách của run'
    assert capsule['executionAuthority'] is False and capsule['untrusted'] is True
    store.close()


def test_a_refused_delete_does_not_close_the_run(tmp_path):
    """Từ chối xoá (bản ghim lệch) không được để lại dấu vết: run vẫn sống để chủ còn đường lùi."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')
    goal = history_surface.service(runtime).contract(sid)['currentRevision']
    runtime.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i1',
                                     'goalRevision': goal,
                                     'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
    preview = history_surface.deletion_preview(runtime, sid, {'mode': 'history_only'})
    try:
        history_surface.deletion_confirm(runtime, sid, {'operationId': preview['operationId'],
                                                        'expectedRevision': 'x' * 64, 'confirm': True})
        raise AssertionError('bản ghim lệch phải bị từ chối')
    except Exception as exc:
        assert getattr(exc, 'code', '') == 'DELETE_REVISION_CONFLICT'
    row = store.db.execute('SELECT state,revision FROM longtask_runs WHERE session_id=?', (sid,)).fetchone()
    assert row['state'] == 'ready' and row['revision'] == 1, 'lượt bị từ chối không được đóng run'
    assert store.get(sid), 'phiên vẫn còn'
    store.close()


def test_the_confirm_route_deletes_a_session_with_a_parked_run_in_one_shot(tmp_path):
    """Đường HTTP thật: preview → xác nhận MỘT lần, run chưa kết thúc vẫn được đóng trong giao dịch.

    Hai bài kiểm trước gọi thẳng `history_surface.deletion_confirm`, nên chúng không thấy được
    thứ nằm TRƯỚC bước ấy: handler `session_deletion_confirm` từng gọi `runtime.stop` cho mọi
    phiên có task, và `runtime.stop` đẩy revision/stop_epoch/lease_epoch của run lên — đúng những
    trường vào bản ghim critical. Hệ quả trên máy thật: bản ghim không bao giờ khớp, lần xác nhận
    nào cũng 409, và lượt bị từ chối thì kịp đổi trạng thái run. Ca này ghim cả đường HTTP.
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu còn dở', 'k1')
    goal = history_surface.service(runtime).contract(sid)['currentRevision']
    runtime.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i1',
                                     'goalRevision': goal,
                                     'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
    runtime.longtask.store.transition(runtime.longtask.store.get(sid), 'budget_exhausted',
                                      'LONGTASK_BUDGET_EXHAUSTED')

    async def call():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession() as client:
                # Sổ task giữ một hàng cho phiên này kể cả sau khi lượt đã xong — đúng như harness
                # thật, và đúng là điều kiện để vòng `runtime.stop` cũ trong handler chạy.
                done = asyncio.get_running_loop().create_future()
                done.set_result(None)
                runtime.tasks[sid] = done
                base = str(server.make_url('/api/agent/sessions')) + '/' + sid
                async with client.post(base + '/deletion-preview', headers=HEADERS,
                                       json={'mode': 'history_only'}) as response:
                    preview = (response.status, await response.json())
                async with client.post(base + '/deletion-confirm', headers=HEADERS,
                                       json={'operationId': preview[1].get('operationId'),
                                             'expectedRevision': preview[1].get('expectedRevision'),
                                             'confirm': True}) as response:
                    confirm = (response.status, await response.json())
                # Đọc TRONG lúc app còn sống: `create_app` đóng kho lúc dọn dẹp.
                row = store.db.execute('SELECT state,blocked_reason FROM longtask_runs WHERE session_id=?',
                                       (sid,)).fetchone()
                return preview, confirm, dict(row)

    preview, confirm, row = asyncio.run(call())
    assert preview[0] == 200 and preview[1]['validation']['status'] == 'validated'
    assert confirm[0] == 200, confirm
    assert confirm[1]['status'] == 'deleted' and confirm[1]['capsuleId'] == preview[1]['capsuleId']
    assert row['state'] == 'cancelled' and row['blocked_reason'] == 'HISTORY_DELETED'


def test_the_confirm_route_refuses_a_live_run_without_touching_it(tmp_path):
    """Run đang ở `ready`: xác nhận trả `DELETE_NOT_QUIESCENT` và KHÔNG được đổi gì của run."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')
    goal = history_surface.service(runtime).contract(sid)['currentRevision']
    runtime.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i1',
                                     'goalRevision': goal,
                                     'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})

    async def call():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession() as client:
                # Sổ task giữ một hàng cho phiên này kể cả sau khi lượt đã xong — đúng như harness
                # thật, và đúng là điều kiện để vòng `runtime.stop` cũ trong handler chạy.
                done = asyncio.get_running_loop().create_future()
                done.set_result(None)
                runtime.tasks[sid] = done
                base = str(server.make_url('/api/agent/sessions')) + '/' + sid
                async with client.post(base + '/deletion-preview', headers=HEADERS,
                                       json={'mode': 'history_only'}) as response:
                    preview = (response.status, await response.json())
                async with client.post(base + '/deletion-confirm', headers=HEADERS,
                                       json={'operationId': preview[1].get('operationId'),
                                             'expectedRevision': preview[1].get('expectedRevision'),
                                             'confirm': True}) as response:
                    confirm = (response.status, await response.json())
                row = store.db.execute('SELECT state,revision,stop_epoch FROM longtask_runs WHERE session_id=?',
                                       (sid,)).fetchone()
                return preview, confirm, dict(row)

    preview, confirm, row = asyncio.run(call())
    assert preview[0] == 200
    assert confirm[0] == 409 and confirm[1]['code'] == 'DELETE_NOT_QUIESCENT', confirm
    assert row['state'] == 'ready' and row['revision'] == 1 and row['stop_epoch'] == 0, \
        'lượt bị từ chối không được chạm vào run'


def test_a_store_without_a_run_closer_refuses_to_delete_over_open_runs(tmp_path):
    """Kho chưa nối người đóng sổ: từ chối, KHÔNG xoá phiên rồi bỏ lại run chưa kết thúc."""
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'mục tiêu', 'k1')
    goal = history_surface.service(runtime).contract(sid)['currentRevision']
    runtime.configure_longtask(sid, {'enabled': True, 'resumePolicy': 'manual', 'invocationId': 'i1',
                                     'goalRevision': goal,
                                     'budget': {'totalStepLimit': 5, 'activeTimeLimitMs': 60000}})
    runtime.longtask.store.transition(runtime.longtask.store.get(sid), 'budget_exhausted',
                                      'LONGTASK_BUDGET_EXHAUSTED')
    preview = history_surface.deletion_preview(runtime, sid, {'mode': 'history_only'})
    history = store.history
    history.run_closer = None
    with pytest.raises(HistoryError, match='DELETE_RUN_CLOSER_MISSING'):
        history.delete_with_capsule(sid, operation_id=preview['operationId'],
                                    expected_revision=preview['expectedRevision'], confirm=True)
    assert store.get(sid), 'phiên phải còn nguyên khi kho thiếu người đóng sổ'
    row = store.db.execute('SELECT state FROM longtask_runs WHERE session_id=?', (sid,)).fetchone()
    assert row['state'] == 'budget_exhausted'
    store.db.close()


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


def test_owner_acceptance_accepts_a_check_the_work_graph_marked_pass(tmp_path):
    """Chủ nghiệm thu phải nhận đúng từ vựng trạng thái của work graph.

    `work_checks` ghi `pass` khi một vòng kiểm đạt (`work_checks.py:249,267`,
    `work_graph.py:2209` dịch `pass -> verdict ok`), còn `_verify_evidence` chỉ nhận `ok|passed`.
    Đo sống 2026-10-09 (phiên `72106f67490847a9be5b179a5cc92a6c`): `accept` với ref
    `workCheckId` của chính vòng kiểm đã đạt trả `LONGTASK_ACCEPTANCE_REQUIRED`, buộc chủ phải
    nghiệm thu bằng một `workArtifactId` yếu hơn.
    """
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    from agentbox.agent_core import work_graph
    work_graph.service(runtime)
    doc = json.dumps({'nodeId': 'B1', 'stage': 'execute', 'kind': 'tests', 'status': 'pass',
                      'verdict': 'ok', 'rounds': 1})
    runtime.store.db.execute("INSERT INTO work_runs VALUES('w1',?,'executed',3,'{}',0,0)", (sid,))
    runtime.store.db.execute("INSERT INTO work_checks VALUES('c1','w1','i1','h1',?)", (doc,))
    runtime.store.db.commit()
    acceptance = history_surface._owner_acceptance(runtime)

    ok = acceptance(sid, {'runId': 'lt'}, {'evidenceRefs': [{'workCheckId': 'c1'}]})
    assert ok['acceptanceSatisfied'] is True, ok['failedChecks']
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


def test_the_capsule_reads_back_over_http_after_the_raw_history_is_gone(tmp_path, monkeypatch):
    """LT-08 ca 7 qua ĐÚNG đường HTTP: xoá raw rồi mở hội thoại mới cùng project.

    Ca này trước đây không thi hành được: `read_capsule` chỉ có bài kiểm đơn vị gọi tới, nên
    "xoá có mang theo" ghi ra một capsule mà không bề mặt nào đọc lại. Hai route mới
    (`GET /api/agent/history/capsules`, `.../capsules/{id}`) khép khoảng trống đó; ca này ghim cả
    đường đọc lẫn ba cửa từ chối: khác project, con của hội thoại mới, và thiếu người gọi.
    """
    monkeypatch.setenv('BOXFOX_LONGTASK_CONTINUITY', '1')
    store, runtime, session = build(tmp_path, project='p1')
    sid = session['id']
    ingest(runtime, sid, 'giữ nguyên yêu cầu gốc này', 'k1')
    preview = history_surface.deletion_preview(runtime, sid, {
        'mode': 'history_only', 'lessons': [{'fact': 'đọc giữa log là đủ'}]})
    history_surface.deletion_confirm(runtime, sid, {
        'operationId': preview['operationId'], 'expectedRevision': preview['expectedRevision'], 'confirm': True})

    fresh = runtime.create(dict(BASE))
    workspace = tmp_path / 'fresh-ws'
    workspace.mkdir(exist_ok=True)
    config = dict(fresh['config'])
    config['machineBinding'] = {'mode': 'host', 'revision': 1, 'projectId': 'p1', 'workspace': str(workspace)}
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(config), fresh['id']))
    store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (fresh['id'],))
    store.db.commit()
    bind(runtime, fresh['id'])
    child = runtime.create(dict(BASE), parent_id=fresh['id'])
    # Cùng kho, KHÁC project: ca từ chối phải chạy trên phiên có thật, nếu không thì 404 của
    # `known_session` sẽ che mất phán quyết thật của cổng quyền.
    other = runtime.create(dict(BASE))
    other_ws = tmp_path / 'other-ws'
    other_ws.mkdir(exist_ok=True)
    other_config = dict(other['config'])
    other_config['machineBinding'] = {'mode': 'host', 'revision': 1, 'projectId': 'p2',
                                      'workspace': str(other_ws)}
    store.db.execute('UPDATE sessions SET config=? WHERE id=?', (json.dumps(other_config), other['id']))
    store.db.execute('DELETE FROM history_sessions WHERE session_id=?', (other['id'],))
    store.db.commit()
    bind(runtime, other['id'])

    async def call():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession() as client:
                base = str(server.make_url('')).rstrip('/')
                capsules = base + '/api/agent/history/capsules'
                one = capsules + '/' + preview['capsuleId']
                async with client.get(f'{capsules}?callerSessionId={fresh["id"]}', headers=HEADERS) as response:
                    listed = (response.status, await response.json())
                async with client.get(f'{one}?callerSessionId={fresh["id"]}', headers=HEADERS) as response:
                    capsule = (response.status, await response.json())
                async with client.get(f'{one}?callerSessionId={other["id"]}', headers=HEADERS) as response:
                    cross = (response.status, await response.json())
                async with client.get(f'{one}?callerSessionId={child["id"]}', headers=HEADERS) as response:
                    nested = (response.status, await response.json())
                async with client.get(f'{capsules}?callerSessionId={child["id"]}', headers=HEADERS) as response:
                    nested_list = (response.status, await response.json())
                async with client.get(one, headers=HEADERS) as response:
                    anonymous = (response.status, await response.json())
                return listed, capsule, cross, nested, nested_list, anonymous

    listed, capsule, cross, nested, nested_list, anonymous = asyncio.run(call())
    assert listed[0] == 200 and [item['capsuleId'] for item in listed[1]['capsules']] == [preview['capsuleId']]
    assert capsule[0] == 200
    assert capsule[1]['lessons'] == [{'fact': 'đọc giữa log là đủ'}]
    assert capsule[1]['executionAuthority'] is False and capsule[1]['untrusted'] is True
    assert cross[0] == 403 and cross[1]['code'] == 'HISTORY_SCOPE_DENIED'
    assert nested[0] == 403 and nested[1]['code'] == 'HISTORY_SCOPE_DENIED'
    assert nested_list[0] == 403 and nested_list[1]['code'] == 'HISTORY_SCOPE_DENIED', 'danh sách phải cùng luật với đường đọc'
    assert anonymous[0] == 400 and anonymous[1]['code'] == 'HISTORY_CALLER_REQUIRED'
    store.close()
