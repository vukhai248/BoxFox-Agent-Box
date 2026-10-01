"""W6.1 source-quality and complete-assignment read regressions."""
import asyncio

import pytest

from agentbox.agent_core import work_checks, work_prompts, work_graph as wg
from test_work_graph import build
from test_work_checks import setup, start


@pytest.mark.parametrize('name', ['web_fetch', 'read_source'])
@pytest.mark.parametrize('quality', ['junk', 'empty', 'wrong-page', 'error-page', 'unknown', None])
def test_unusable_web_body_never_counts_as_source(tmp_path, name, quality):
    store, rt, _, _, sid = build(tmp_path)
    graph = wg.service(rt)
    child = rt.create({}, parent_id=sid, role='research-review')
    store.emit(child['id'], 'tool_end', {'name': name, 'args': {'url': 'https://example.test'},
        'result': {'text': 'Error or wrong document', 'status': 200, 'quality': {'verdict': quality}}})
    assert work_checks.good_reads(graph, child['id']) == []


@pytest.mark.parametrize('result,expected', [
    ({'text': 'recovered body', 'status': 403, 'quality': {'verdict': 'ok'}, 'reader': 'r.jina.ai'}, True),
    ({'text': 'recovered excerpt', 'status': 0, 'quality': {'verdict': 'thin'}}, True),
    ({'text': 'real legacy page', 'status': 200}, True),
    ({'content': 'legacy body'}, True),
    ({'text': 'access denied', 'status': 403}, False),
    ({'text': 'unreachable', 'status': 0}, False),
    ({'text': 'body', 'status': '200'}, False),
    ({'text': 'body', 'quality': 'ok'}, False),
    ({'text': 'body', 'quality': None}, False),
    ({'text': 'body', 'quality': {'verdict': 'ok'}, 'is_error': True}, False),
    ({'text': '   ', 'quality': {'verdict': 'ok'}}, False),
    ({'matches': [], 'results': []}, False),
])
def test_recovered_source_and_legacy_results(tmp_path, result, expected):
    store, rt, _, _, sid = build(tmp_path)
    graph = wg.service(rt)
    store.emit(sid, 'tool_end', {'name': 'web_fetch', 'args': {}, 'result': result})
    assert bool(work_checks.good_reads(graph, sid)) is expected


def test_bad_source_cannot_pass_actual_evidence_check(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    # A grade is only relevant to web reads; feed the web event at the real dispatch boundary.
    async def run():
        _, draft = await setup(rt, sid)
        complete = model.complete
        import json
        async def redirect(*args, **kw):
            result = await complete(*args, **kw)
            for call in result['choices'][0]['message'].get('tool_calls', []):
                if call['function']['name'] == 'file_read':
                    call['function'].update(name='web_fetch', arguments=json.dumps({'url': 'https://example.test'}))
            return result
        model.complete = redirect
        def web(*args, **kw):
            return {'text': 'Access denied', 'quality': {'verdict': 'error-page'}, 'status': 403}
        rt.web.fetch = web
        checked = await start(rt, sid, draft)
        assert checked['checks'][0]['status'] == 'unverified'
    asyncio.run(run())


def test_assignment_progress_tracks_ids_holes_empty_reads_and_restart(tmp_path):
    store, rt, _, _, sid = build(tmp_path)
    async def run():
        rid, draft = await setup(rt, sid)
        graph = rt.work_graph
        first = draft['outputs'][0]['artifact']
        run = graph.get(rid)
        second = await graph.artifacts.put(run, 'R1', 'produce', 'a' * 18000, {}, True)
        empty = await graph.artifacts.put(run, 'R1', 'produce', '', {}, True)
        child = rt.create({}, parent_id=sid, role='research-review')
        binding = {'runId': rid, 'checkId': 'check-progress',
                   'artifactIds': [m['artifactId'] for m in (first, second, empty)]}
        child['config']['workBinding'] = binding
        store.update_config(child['id'], child['config'])
        read = lambda m, offset=0: graph.artifacts.read(child, {'artifactId': m['artifactId'], 'offset': offset})
        result = read(first)
        assert result['coverageComplete'] and not result['allAssignedArtifactsRead']
        assert {x['artifactId'] for x in result['unreadArtifacts']} == {second['artifactId'], empty['artifactId']}
        assert read(second, 16000)['unreadOffset'] == 0  # jumping to the tail leaves a hole
        assert not read(second)['coverageComplete']
        result = read(second, 8000)
        assert result['coverageComplete'] and result['unreadArtifacts'][0]['artifactId'] == empty['artifactId']
        assert read(empty)['allAssignedArtifactsRead']
        from agentbox.agent_core.work_artifacts import Artifacts
        reopened = Artifacts(graph)
        assert reopened.read(child, {'artifactId': first['artifactId']})['allAssignedArtifactsRead']
        # Neither another checker attempt nor another reader may borrow these ranges.
        child['config']['workBinding'] = binding | {'checkId': 'other-check'}
        assert not read(first)['allAssignedArtifactsRead']
        other = rt.create({}, parent_id=sid, role='research-review')
        other['config']['workBinding'] = binding
        assert not reopened.read(other, {'artifactId': first['artifactId']})['allAssignedArtifactsRead']
        root = rt.create({})
        with pytest.raises(ValueError, match='another session'):
            reopened.read(root, {'runId': rid, 'artifactId': first['artifactId']})
    asyncio.run(run())


@pytest.mark.parametrize('lang,terms', [('en', ['actual CSV rows', 'proposed files', 'unread passages']),
                                     ('vi', ['hàng CSV', 'đề xuất file', 'đoạn chưa đọc'])])
def test_review_does_not_invent_artifact_format_requirements(lang, terms):
    assert all(term in work_prompts.review_tail(lang) for term in terms)
    assert 'allAssignedArtifactsRead' in work_checks.contract(lang, {'A1': 'scope'})
