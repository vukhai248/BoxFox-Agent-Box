"""W10 — bản ghim mã của run không-git và đường xoá hàng rào "mã đã đổi".

Đo ở W10.F ca S12: workspace KHÔNG có git ⇒ run chạy chế độ `touchset` và artifact được ghim
bằng dirty manifest (`work-dirty/1`). Nhưng mọi cổng so sánh lại đọc cây bằng ảnh chụp git
(`work-code/1`), nên hai kiểu không bao giờ bằng nhau: MỌI lượt kiểm bị từ chối
"Code changed before check.", nút đứng mãi ở `needs_checks`, `work_run` không chạy lại (chỉ chạy
stage `pending`/`revise`), `retry` từ chối vì nút không rejected/failed — main chỉ còn
`action=update`, đường duy nhất xoá luôn bản nháp.

Bài này khoá lại: (1) so sánh đúng schema, (2) ghim lại khi mã đổi NGOÀI file của nút,
(3) trả stage về sản xuất khi mã đổi ĐÚNG vào file của nút, (4) `resolve` xoá được hàng rào,
(5) thông báo `retry` chỉ đúng đường, (6) `stuck_criteria` leo thang cả ở stage `produce`.
"""
import asyncio
import uuid

import pytest

from agentbox.agent_core import work_checks, work_graph as wg, work_worktrees as ww
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_work_worktree import RealExecutor, WriteOne


def touchset_run(tmp_path, name, written='src/out-1.py', declared=None):
    """Một lượt execute THẬT trong workspace không có git (chế độ touchset)."""
    folder = tmp_path / name
    folder.mkdir()
    (folder / 'src').mkdir()
    (folder / 'src' / 'app.py').write_text('def header():\n    return "chat"\n', encoding='utf-8')
    store = SessionStore(tmp_path / (name + '.db'))
    runtime = HarnessRuntime(store, RealExecutor(folder), WriteOne(written))
    sid = runtime.create({'skills': []})['id']
    service = wg.service(runtime)
    session = store.get(sid)

    async def run():
        doc = service.create(session, {'goal': 'Sửa export_markdown khi workspace không có git.', 'flow': 'fix',
            'nodes': [{'id': 'B1', 'kind': 'build', 'title': 'Export',
                       'goal': 'Viết tệp xuất markdown trong src/ và báo lại đường dẫn đã ghi.',
                       'acceptance': ['tệp xuất tồn tại'], 'tests': ['vitest export.test.ts'],
                       'files': declared if declared is not None else [written]}]})
        doc['status'] = 'approved'
        doc['executionRequested'] = True
        service.set_repair_default(doc)
        service.save(doc, 'probe_approved')
        iso = await service.ensure_isolation(session, doc, {})
        node = service.find_node(doc, 'B1')
        status = await service.run_stage(session, doc, node, 'execute', 3)
        service.save(doc, 'probe_stage')
        return iso, doc['runId'], status

    iso, run_id, status = asyncio.run(run())
    return folder, runtime, sid, service, run_id, status


def start_check(runtime, sid, run_id, check_ids=None):
    run = wg.service(runtime).get(run_id)
    state = wg.service(runtime).find_node(run, 'B1')['stages']['execute']
    args = {'action': 'start', 'runId': run_id, 'nodeId': 'B1', 'stage': 'execute',
            'artifactId': state['artifact']['artifactId'], 'invocationId': uuid.uuid4().hex}
    if check_ids:
        args['checkIds'] = check_ids
    return asyncio.run(runtime.work_tool(runtime.store.get(sid), 'work_check', args))


def test_touchset_binding_is_read_back_with_its_own_schema(tmp_path, monkeypatch):
    """Cổng kiểm phải đọc cây bằng dirty manifest, không phải ảnh chụp git."""
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    folder, runtime, sid, service, run_id, status = touchset_run(tmp_path, 'w10-schema')
    assert status in ('needs_checks', 'accepted')
    run = service.get(run_id)
    binding = service.find_node(run, 'B1')['stages']['execute']['artifact']['binding']
    assert binding['codeSnapshot']['schema'] == work_checks.DIRTY_SCHEMA
    assert binding['codeSnapshot'].get('declared'), 'bản ghim phải giữ phần khai báo của nút'
    result = start_check(runtime, sid, run_id)
    statuses = [doc['status'] for doc in result['checks']]
    assert 'superseded' not in statuses, result['checks']


def test_tree_moved_outside_declared_files_rebinds_the_draft(tmp_path, monkeypatch):
    """Mã đổi ngoài phạm vi nút ⇒ ghim lại bản nháp (giữ nguyên vòng sửa) và kiểm tiếp."""
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    folder, runtime, sid, service, run_id, status = touchset_run(tmp_path, 'w10-rebind')
    (folder / 'docs').mkdir()
    (folder / 'docs' / 'foreign.md').write_text('tệp ngoài phạm vi nút\n', encoding='utf-8')
    result = start_check(runtime, sid, run_id)
    run = service.get(run_id)
    binding = service.find_node(run, 'B1')['stages']['execute']['artifact']['binding']
    trail = binding.get('codeRebound') or {}
    assert trail and trail['from'] != trail['to'], binding
    assert binding['codeSnapshot']['hash'] == trail['to']
    assert [doc['status'] for doc in result['checks']].count('superseded') == 0, result['checks']


def test_tree_moved_inside_declared_files_sends_the_stage_back_to_production(tmp_path, monkeypatch):
    """Mã đổi ĐÚNG vào file nút khai báo ⇒ từ chối kiểm và trả stage về sản xuất (giữ lịch sử)."""
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    folder, runtime, sid, service, run_id, status = touchset_run(tmp_path, 'w10-moved')
    (folder / 'src' / 'out-1.py').write_text('# sửa ngoài lượt sản xuất\n', encoding='utf-8')
    result = start_check(runtime, sid, run_id)
    run = service.get(run_id)
    state = service.find_node(run, 'B1')['stages']['execute']
    assert state['status'] == 'pending', state
    assert state['codeMoved'] == ['src/out-1.py']
    assert 'WORK_CHECK_CODE_MOVED' in result['checks'][-1]['error']
    assert state['rounds'], 'lịch sử vòng sửa phải còn'


def test_resolve_returns_a_refused_stage_to_production(tmp_path, monkeypatch):
    """Hàng rào "mã đã đổi" phải có đường xoá: `resolve` trả stage về pending, không mất bản nháp."""
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    folder, runtime, sid, service, run_id, status = touchset_run(tmp_path, 'w10-resolve')
    (folder / 'src' / 'out-1.py').write_text('# sửa ngoài lượt sản xuất\n', encoding='utf-8')
    start_check(runtime, sid, run_id)
    run = service.get(run_id)
    node = service.find_node(run, 'B1')
    node['stages']['execute']['status'] = 'needs_checks'   # trạng thái kẹt của ca S12
    service.save(run, 'probe_stuck')
    result = asyncio.run(runtime.work_tool(runtime.store.get(sid), 'work_graph',
                                           {'action': 'resolve', 'runId': run_id, 'nodeIds': ['B1']}))
    run = service.get(run_id)
    state = service.find_node(run, 'B1')['stages']['execute']
    assert state['status'] == 'pending'
    assert result['resolved'] and result['resolved'][0]['codeMoved'] == ['src/out-1.py']


def test_retry_names_the_clearing_path_when_nothing_is_rejected(tmp_path, monkeypatch):
    """Nút kẹt ở needs_checks không phải "không có gì để chạy lại": thông báo phải chỉ đường."""
    monkeypatch.setenv(ww.ISOLATION_ENV, 'touchset')
    folder, runtime, sid, service, run_id, status = touchset_run(tmp_path, 'w10-retry')
    run = service.get(run_id)
    node = service.find_node(run, 'B1')
    node['stages']['execute'].update(status='needs_checks', codeMoved=['src/out-1.py'])
    service.save(run, 'probe_stuck')
    with pytest.raises(ValueError) as exc:
        asyncio.run(runtime.work_tool(runtime.store.get(sid), 'work_graph',
                                      {'action': 'retry', 'runId': run_id, 'nodeIds': ['B1']}))
    assert 'action=resolve' in str(exc.value) and 'work_run phase=execute' in str(exc.value)


def test_next_step_names_the_clearing_path_for_a_moved_tree():
    """`next_step` phải nói đường xoá thay vì lặp lại "call work_check action=start"."""
    node = {'id': 'B1', 'kind': 'build', 'title': 't', 'goal': 'g', 'acceptance': ['a'], 'files': ['src/a.py'],
            'dependsOn': [], 'stages': {'execute': {'status': 'needs_checks', 'codeMoved': ['src/a.py'],
                                                    'artifact': {'artifactId': 'a-1'}, 'rounds': []}}}
    run = {'runId': 'r-1', 'status': 'approved', 'goal': 'g', 'title': 't', 'nodes': [node], 'flow': 'fix',
           'isolation': {'mode': 'touchset'}, 'history': [], 'review': {'status': 'ok'},
           'checks': {'records': []}, 'sessionId': 's-1'}

    class Graph:
        all_nodes = staticmethod(lambda run: run['nodes'])
        feedback = type('F', (), {'records': staticmethod(lambda run_id: [])})()
    text = wg.WorkGraph.next_step(Graph(), run)
    assert 'action=resolve' in text and 'work_run phase=execute' in text


def test_stuck_criteria_escalates_after_producer_rounds():
    """W10: stage `produce` đỏ mãi vì một tiêu chí cũng phải leo thang thành hàng rào."""
    doc = {'status': 'revise', 'coverage': [{'id': 'A1', 'status': 'revise', 'target': 'artifact',
                                             'evidence': 'claims only'}]}
    criteria = {'A1': 'tiêu chí nghiệm thu'}
    assert work_checks.stuck_criteria({'rounds': [{}]}, doc, criteria) == []
    out = work_checks.stuck_criteria({'rounds': [{}, {}]}, doc, criteria)
    assert out and out[0]['source'] == 'stuck_criteria' and out[0]['id'] == 'A1'
    # Stage execute của run git vẫn đếm số vòng SỬA, không đếm vòng sản xuất.
    assert work_checks.stuck_criteria({'repairs': [{}], 'rounds': [{}, {}]}, doc, criteria) == []
    assert work_checks.stuck_criteria({'repairs': [{}, {}]}, doc, criteria)
    # Tiêu chí đã được dán nhãn `criterion` không leo thang (đó là hàng rào của chính lượt kiểm).
    labelled = {'status': 'revise', 'coverage': [{'id': 'A1', 'status': 'revise', 'target': 'criterion'}]}
    assert work_checks.stuck_criteria({'rounds': [{}, {}]}, labelled, criteria) == []
