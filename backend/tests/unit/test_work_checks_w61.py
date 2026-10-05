"""W6.1: no silent loss, capability preflight and evidence-backed criticism."""
import asyncio

import pytest

from agentbox.agent_core import work_checks, work_graph as wg, work_prompts
from agentbox.agent_core.roles import work_check_tools
from test_work_checks import setup, start
from test_work_graph import build, ok_script


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


def test_all_24_acceptance_items_reach_checker_and_missing_last_cannot_pass(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    async def run():
        node = {'id': 'R1', 'kind': 'research', 'title': 'Detailed evidence',
                'goal': 'Research all twenty-four explicitly assigned requirements',
                'acceptance': [f'Requirement {i}' for i in range(24)]}
        _, draft = await setup(rt, sid, node)
        checked = await start(rt, sid, draft)
        coverage = checked['checks'][0]['coverage']
        assert {c['id'] for c in coverage} == {f'A{i+1}' for i in range(24)} | {'C1'}
        assert 'Requirement 23' in model.prompts[-1][1]
        import json
        incomplete = '```json\n' + json.dumps({'coverage': coverage[:-2] + coverage[-1:]}) + '\n```\nVERDICT: ok'
        assert work_checks.parse_report(incomplete, {c['id']: 'required' for c in coverage})[0] == 'error'
    asyncio.run(run())


@pytest.mark.parametrize('field,value', [
    ('acceptance', ['x'] * 65), ('acceptance', ['x' * 601]),
    ('acceptance', [{'text': 'wrong shape'}]), ('dependsOn', ['N1'] * 17),
    ('tests', ['pytest'] * 21), ('files', ['a.py'] * 41),
])
def test_oversized_or_invalid_lists_are_rejected_not_truncated(field, value):
    node = {'id': 'R1', 'kind': 'research', 'title': 'Evidence',
            'goal': 'Research the assigned scope using original evidence', field: value}
    with pytest.raises(ValueError, match='WORK_NODE_INVALID'):
        wg.normalize_node(node)


def test_disabled_checker_is_preflighted_without_spawn_or_retry_consumption(tmp_path):
    store, rt, _, _, sid = build(tmp_path)
    async def run():
        rid, draft = await setup(rt, sid)
        config = store.get(sid)['config']
        config['subagents'] = [r | {'enabled': False} if r['id'] == 'research-review' else r
                              for r in config['subagents']]
        store.update_config(sid, config)
        count = len(store.children_of(sid))
        for _ in range(4):
            with pytest.raises(ValueError, match='WORK_CHECK_UNAVAILABLE.*research-review'):
                await start(rt, sid, draft, invocationId='retry-after-owner-enables')
        assert len(store.children_of(sid)) == count
        assert rt.work_graph.checks.records(rid) == []
        config['subagents'] = [r | {'enabled': True} for r in config['subagents']]
        store.update_config(sid, config)
        checked = await start(rt, sid, draft, invocationId='retry-after-owner-enables')
        assert checked['checks'][0]['status'] == 'pass'
    asyncio.run(run())


def test_tester_needs_terminal_and_reviewers_can_search_only_if_owner_allows():
    config = {'tools': ['file_read'], 'subagents': [{'id': 'testing', 'enabled': True}]}
    assert 'terminal_exec' in work_checks.preflight({'config': config}, {'id': 'tests', 'executorRole': 'testing'})
    config['tools'].append('terminal_exec')
    assert work_checks.preflight({'config': config}, {'id': 'tests', 'executorRole': 'testing'}) is None
    assert 'web_search' not in work_check_tools('plan-review', ['file_read'])
    tools = work_check_tools('plan-review', ['file_read', 'web_search', 'web_fetch', 'file_write'])
    assert {'web_search', 'web_fetch', 'work_artifact_read'} <= tools
    assert not tools & {'file_write', 'file_edit_block', 'terminal_exec', 'write_plan'}


def test_unopened_source_cannot_produce_confirmed_evidence_revise(tmp_path):
    def script(kind, prompt):
        return 'Unsupported suspicion\nVERDICT: revise' if kind == 'review' else ok_script(kind, prompt)
    _, rt, _, executor, sid = build(tmp_path, script)
    original = executor.execute
    async def unavailable(name, args, *rest, **kwargs):
        if name == 'file_read':
            return {'is_error': True, 'error': 'Source unavailable'}
        return await original(name, args, *rest, **kwargs)
    executor.execute = unavailable
    async def run():
        _, draft = await setup(rt, sid)
        checked = await start(rt, sid, draft)
        assert checked['checks'][0]['status'] == 'unverified'
        assert checked['nodes'][0]['stages']['produce'] == 'needs_checks'
        assert 'No successfully opened original evidence' in checked['checks'][0]['error']
    asyncio.run(run())


@pytest.mark.parametrize('lang', ['en', 'vi'])
def test_review_contract_requires_self_challenge_and_targeted_source_verification(lang):
    prompt = work_prompts.review_tail(lang)
    expected = ('strongest counterargument', 'Search/open', 'declared limitation', 'outside owner scope') if lang == 'en' else (
        'bác bỏ chính finding', 'tìm và mở nguồn', 'Giới hạn đã khai báo', 'ngoài phạm vi')
    assert all(term in prompt for term in expected)


def test_workspace_artifact_copy_is_not_original_source(tmp_path):
    store, rt, _, _, sid = build(tmp_path)
    async def run():
        _, draft = await setup(rt, sid)
        checked = await start(rt, sid, draft)
        child = checked['checks'][0]['childId']
        meta = draft['nodes'][0]['artifacts']['produce']
        for path in (meta['path'], '/workspace/' + meta['path'], meta['path'].replace('/', '\\')):
            store.emit(child, 'tool_end', {'name':'file_read','args':{'path':path},'result':{'content':'self-citation'}})
        reads = work_checks.good_reads(rt.work_graph, child)
        assert reads and all(x['result'].get('content') != 'self-citation' for x in reads)
    asyncio.run(run())


def test_self_citation_via_file_read_does_not_pass_evidence_gate(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    complete = model.complete
    async def self_read(messages, tools, route, **kwargs):
        import json
        result = await complete(messages, tools, route, **kwargs)
        first = next(str(m.get('content') or '') for m in messages if m['role'] == 'user')
        if first.startswith('Independent review'):
            run = rt.work_graph.active(sid)
            path = run['nodes'][0]['stages']['produce']['artifact']['path']
            for call in result['choices'][0]['message'].get('tool_calls', []):
                if call['function']['name'] == 'file_read':
                    call['function']['arguments'] = json.dumps({'path': path})
        return result
    model.complete = self_read
    async def run():
        _, draft = await setup(rt, sid)
        checked = await start(rt, sid, draft)
        assert checked['checks'][0]['status'] == 'unverified'
        assert checked['nodes'][0]['stages']['produce'] == 'needs_checks'
    asyncio.run(run())
