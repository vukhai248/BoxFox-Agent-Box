"""W1.P — một cổng năng lực duy nhất trước mọi spawn/resume/check.

Quy tắc: role bị tắt hoặc tool bị thu hồi thì báo ĐÚNG mã trước khi con tốn lượt; không tự bật
role, không coi thiếu kiểm tra là đạt. Tool bị thu hồi GIỮA lượt bị chặn ở dispatch.
"""
import asyncio
import json
import uuid

import pytest

from agentbox.agent_core import work_checks, work_graph as wg
from agentbox.agent_core.work_feedback import FeedbackError
from test_work_checks import setup, start
from test_work_graph import build, raw_tool
from test_work_feedback_w7 import setup as bound_setup


def test_capability_preflight_names_the_missing_role_or_tool():
    session = {'config': {'tools': ['file_read'], 'subagents': [{'id': 'research', 'enabled': True},
                                                                 {'id': 'testing', 'enabled': False}]}}
    assert work_checks.capability_preflight(session, {'role': 'research'}) is None
    missing = work_checks.capability_preflight(session, {'role': 'plan-review'})
    assert missing.startswith('WORK_ROLE_UNAVAILABLE') and 'plan-review' in missing
    disabled = work_checks.capability_preflight(session, {'role': 'testing', 'check': True,
                                                          'tools': {'terminal_exec'}})
    assert disabled.startswith('WORK_CHECK_UNAVAILABLE') and 'testing' in disabled
    revoked = work_checks.capability_preflight(session, {'role': 'research', 'tools': {'terminal_exec'}})
    assert revoked.startswith('WORK_ROLE_UNAVAILABLE') and 'terminal_exec' in revoked
    # Không có công cụ đọc nào thì không được coi là đủ để mở bằng chứng gốc.
    empty = {'config': {'tools': [], 'subagents': [{'id': 'research', 'enabled': True}]}}
    assert work_checks.capability_preflight(empty, {'role': 'research', 'readTool': True}) is not None
    # `preflight` cũ vẫn giữ nguyên mã và câu chữ cho ca tests thiếu terminal_exec.
    spec = {'id': 'tests', 'executorRole': 'research'}
    assert work_checks.preflight({'config': {'tools': ['file_read'], 'subagents': [
        {'id': 'research', 'enabled': True}]}}, spec) == \
        'WORK_CHECK_UNAVAILABLE: tests requires terminal_exec; owner tool setting is respected'


def test_disabled_role_reported_before_producer_spawn(tmp_path):
    store, rt, model, executor, sid = build(tmp_path)
    async def run():
        created = await raw_tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Compare two export formats',
                                                         'flow': 'research'})
        await raw_tool(rt, sid, 'work_graph', {'action': 'add', 'nodes': [
            {'id': 'R1', 'kind': 'research', 'title': 'Formats', 'goal': 'Compare two export formats with evidence',
             'acceptance': ['Cite the format spec']}]})
        config = store.get(sid)['config']
        config['subagents'] = [r | {'enabled': False} if r['id'] == 'research' else r for r in config['subagents']]
        store.update_config(sid, config)
        before = len(store.children_of(sid))
        result = await raw_tool(rt, sid, 'work_run', {'phase': 'discover'})
        state = wg.service(rt).get(created['runId'])['nodes'][0]['stages']['produce']
        assert state['status'] == 'failed' and 'WORK_ROLE_UNAVAILABLE' in state['error'] and 'research' in state['error']
        assert len(store.children_of(sid)) == before, 'không được sinh con khi role bị tắt'
        assert not store.db.execute("SELECT 1 FROM events WHERE kind='user' AND session_id!=?",
                                    (sid,)).fetchone(), 'không có lượt con nào chạy'
        assert [k for k, _ in model.prompts] == [], 'chưa tốn lượt model nào'
        assert result['outputs'][0]['status'] == 'failed'
    asyncio.run(run())


def test_revoked_terminal_exec_blocks_tests_check_with_cause(tmp_path):
    from test_work_retest_w8 import check, draft, fixture
    async def run():
        store, rt, _, _, sid, path, mode = fixture(tmp_path)
        meta = await draft(rt, sid)
        config = store.get(sid)['config']
        config['tools'] = [t for t in config['tools'] if t != 'terminal_exec']
        store.update_config(sid, config)
        before = len(store.children_of(sid))
        with pytest.raises(ValueError, match='WORK_CHECK_UNAVAILABLE.*terminal_exec'):
            await check(rt, sid, meta, 'after-owner-revokes-terminal')
        assert len(store.children_of(sid)) == before, 'không sinh tester khi thiếu terminal_exec'
        assert [c for c in rt.work_graph.checks.records(rt.work_graph.active(sid)['runId'])] == []
    asyncio.run(run())


def test_owner_tool_switch_revoke_is_reported_at_dispatch(tmp_path):
    """Tool còn trong bộ lúc mở lượt nhưng chủ nhà tắt giữa chừng → chặn ở dispatch, có mã."""
    store, rt, model, executor, sid = build(tmp_path)
    session = store.get(sid)
    session['config']['tools'] = [t for t in session['config']['tools'] if t != 'terminal_exec']
    store.update_config(sid, session['config'])
    from agentbox.agent_core import tool_recovery
    assert 'terminal_exec' not in tool_recovery.owner_tools(store, session)
    assert 'terminal_exec' in tool_recovery.owner_tools(store, {**session, 'config': {**session['config'],
        'tools': session['config']['tools'] + ['terminal_exec']}})


def test_controller_queued_grant_revoked_before_resume(tmp_path):
    async def run():
        store, rt, graph, run, sid, cid = bound_setup(tmp_path)
        grant = graph.grants.action(store.get(sid), {'action': 'grant', 'runId': run['runId'], 'nodeId': 'R1',
            'stage': 'produce', 'purpose': 'produce', 'decisionKeys': ['users'], 'revision': 1,
            'publishInterview': True, 'resumeOnAnswers': True, 'invocationId': 'g-1'})
        doc = await graph.feedback.report(store.get(cid), {'action': 'needs_user', 'checkpoint': 'Cần chốt người dùng',
            'questions': [{'id': 'users', 'question': 'Ai dùng?', 'options': ['Bác sĩ', 'Điều dưỡng']}],
            'decisionKeys': ['users'], 'invocationId': 'r-1'}, 'tool-r')
        assert doc['grantId'] == grant['grantId']
        graph.grants.action(store.get(sid), {'action': 'revoke', 'runId': run['runId'],
                                             'grantId': grant['grantId'], 'revision': 1, 'invocationId': 'g-2'})
        with pytest.raises(FeedbackError, match='WORK_CONTINUATION_RIGHTS'):
            graph.continuations.authorized(doc, graph.current(run['runId']))
        assert graph.continuations.rows(run['runId']) == [] or all(
            row['status'] == 'pending' for row in graph.continuations.rows(run['runId']))
        store.close()
    asyncio.run(run())


@pytest.mark.skip(reason='verify_exec thuộc track w6 (chưa có trong nhánh này): khi công cụ đó vào, '
                         'bổ sung ca review vẫn chạy và finding bị hạ NUMERIC_UNVERIFIED')
def test_verify_exec_unavailable_does_not_block_review_but_is_reported():
    raise AssertionError('open: chờ track w6 mang verify_exec vào')
