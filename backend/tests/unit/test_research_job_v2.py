"""Regressions for durable research and version-bound evidence review."""
import hashlib
import asyncio

import pytest
import json
import urllib.parse

from agentbox.agent_core import research_ledger, research_quality, research_runtime
from agentbox.agent_core import web as web_module
from agentbox.memory.session_store import SessionStore
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import research_continuation_step
from research_intake import admit_lead


def test_openreview_search_records_submission_and_real_next_offset(monkeypatch):
    calls = []
    def fake_request(url, **kwargs):
        calls.append(url)
        offset = int(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)['offset'][0])
        notes = [{'id': f'id-{offset + n}', 'content': {
            'title': {'value': f'Paper {offset + n}'},
            'abstract': {'value': 'Method and limits'},
            'venueid': {'value': 'NeurIPS.cc/2025/Conference'}}} for n in range(2)]
        return 200, 'application/json', json.dumps({'notes': notes, 'count': 5}), url
    monkeypatch.setattr(web_module, 'http_request', fake_request)
    tools = web_module.WebTools()
    first = tools.search({'query': 'synthetic data', 'source': 'openreview', 'count': 2})
    second = tools.search({'query': 'synthetic data', 'source': 'openreview', 'count': 2,
                           'cursor': first['pagination']['nextCursor']})
    assert first['pagination'] == {'supported': True, 'nextCursor': 2}
    assert second['results'][0]['title'] == 'Paper 2'
    assert 'forum=id-0' in first['results'][0]['forumApiUrl']
    assert first['results'][0]['publicationState'] == 'venue-reported'
    assert len(calls) == 2


def test_openreview_search_rejects_cursor_for_general_web():
    with pytest.raises(web_module.WebError, match='cursor is supported only'):
        web_module.WebTools().search({'query': 'a', 'source': 'web', 'cursor': 2})


def test_reader_snapshot_survives_process_recreation(tmp_path, monkeypatch):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    main = store.create({'skills': []})
    body = '<html><title>Research page</title><body>' + ('Evidence text about a result. ' * 50) + '</body></html>'
    calls = []
    def fake_request(url, **kwargs):
        calls.append(url)
        return 200, 'text/html', body, url
    monkeypatch.setattr(web_module, 'http_request', fake_request)
    first = web_module.WebTools(snapshot_store=store)
    fetched = asyncio.run(first.run('web_fetch', {'url': 'https://example.org/study',
                                                  'maxChars': 500}, main['id'],
                                   scope_id=main['id']))
    ref = fetched['ref']
    assert fetched['truncated'] and ref
    second = web_module.WebTools(snapshot_store=store)
    remainder = asyncio.run(second.run('read_source', {'ref': ref, 'offset': 500,
                                                       'maxChars': 500}, main['id'],
                                       scope_id=main['id']))
    assert remainder['fromStore'] is True and 'Evidence text' in remainder['text']
    assert len(calls) == 1
    other = store.create({'skills': []})
    with pytest.raises(web_module.WebError, match='WEB_READ_REF_UNKNOWN'):
        asyncio.run(second.run('read_source', {'ref': ref, 'offset': 500}, other['id'],
                               scope_id=other['id']))
    store.close()


def test_passage_in_middle_of_long_page_and_not_claim_entailment():
    excerpt = 'The reported gain applies only to Dataset A with the stated split and metric.'
    page = ('unrelated introduction ' * 1800) + excerpt + (' more unrelated appendix ' * 1800)
    matched, overlap = research_runtime._passage_match(excerpt, page)
    assert matched and overlap == 1.0
    # A matched quotation can still contradict a claim; source_verify exposes
    # claimSupport='not_checked' and requires a separate evidence review.
    assert research_runtime._passage_match('The model improved on Dataset B.', page)[0] is False
    altered = page.replace('only to Dataset A', 'also to Dataset A')
    assert research_runtime._passage_match(excerpt, altered)[0] is False


def test_reviewer_must_read_every_slice_of_the_bound_version(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    child = store.create({'skills': []}, role='research-review')
    document = 'one\ntwo\nthree\n'
    path = '.research/example/v1-example.md'
    digest = hashlib.sha256(document.encode()).hexdigest()
    class Runtime:
        pass
    runtime = Runtime()
    runtime.store = store
    store.emit(child['id'], 'tool_end', {'name': 'file_read', 'args': {'path': path},
                                        'result': {'content': document[:4], 'truncated': True}})
    assert not research_runtime._review_read_proof(runtime, child['id'], path, digest)
    store.emit(child['id'], 'tool_end', {'name': 'file_read',
                                        'args': {'path': path, 'offset': 4},
                                        'result': {'content': document[4:], 'truncated': False}})
    assert research_runtime._review_read_proof(runtime, child['id'], path, digest)
    assert not research_runtime._review_read_proof(runtime, child['id'], path,
                                                   hashlib.sha256(b'changed').hexdigest())
    store.close()


def test_job_checkpoint_survives_reopen_and_budget_use_is_idempotent(tmp_path):
    path = tmp_path / 'sessions.sqlite'
    store = SessionStore(path)
    main = store.create({'skills': []})
    state = {'goal': 'compare options', 'questions': [{'id': 'q1', 'status': 'unexplored'}],
             'budgetSeconds': 600}
    first = store.research_job_save('compare-options', main['id'], state, status='researching')
    assert first['revision'] == 1
    store.emit(main['id'], 'turn_end', {'turn': 1, 'deadlineUsedMs': 1000})
    store.emit(main['id'], 'turn_end', {'turn': 1, 'deadlineUsedMs': 2500})
    store.emit(main['id'], 'turn_end', {'turn': 2, 'deadlineUsedMs': 700})
    assert store.research_job_used_seconds(main['id']) == 3.2
    store.close()
    reopened = SessionStore(path)
    assert reopened.research_job('compare-options')['state'] == state
    assert reopened.research_job_used_seconds(main['id']) == 3.2
    reopened.close()


def test_tier_two_consequential_job_cannot_complete_before_required_reviews(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    main = store.create({'skills': []})
    store.research_job_save('example', main['id'], {
        'budgetSeconds': 1200, 'tier': 2, 'reviewModes': ['evidence', 'critique'],
        'questions': [{'id': 'q1', 'importance': 'high', 'status': 'answered'}],
    }, status='synthesizing')
    store.record_dossier(main['id'], 'example', 1, '.research/example/v1-example.md',
                         quality_ok=True)
    class Runtime:
        pass
    runtime = Runtime()
    runtime.store = store
    with pytest.raises(ValueError, match='RESEARCH_JOB_INCOMPLETE'):
        research_runtime.research_update(runtime, main, {'researchId': 'example',
                                                         'status': 'completed'})
    store.dossier_critique_set('example', 1, 'ok')
    assert research_runtime.research_update(runtime, main, {
        'researchId': 'example', 'status': 'completed'})['status'] == 'completed'
    store.close()


def test_budget_is_scoped_to_one_research_job(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    main = store.create({'skills': []})
    for turn, job, ms in [(1, 'job-a', 3000), (2, 'job-b', 9000), (3, 'job-a', 4500)]:
        store.emit(main['id'], 'turn_end', {'turn': turn, 'researchId': job,
                                           'deadlineUsedMs': ms})
    assert store.research_job_used_seconds(main['id'], 'job-a') == 7.5
    assert store.research_job_used_seconds(main['id'], 'job-b') == 9.0
    store.close()


def test_research_continuation_retries_after_restart_with_original_budget(tmp_path):
    path = tmp_path / 'sessions.sqlite'
    store = SessionStore(path)
    main = store.create({'skills': [], 'deadlineSeconds': 500})
    sid = main['id']
    store.research_job_save('resume', sid, {'budgetSeconds': 120,
                            'questions': [{'id': 'q1', 'status': 'unexplored'}]},
                            status='researching')
    class Runtime:
        def __init__(self, db):
            self.store = db
            self.calls = []
        async def submit(self, session_id, prompt, *, invocation_id):
            self.calls.append((session_id, prompt, invocation_id))
    runtime = Runtime(store)
    asyncio.run(research_continuation_step(runtime))
    assert len(runtime.calls) == 1
    assert store.get(sid)['config']['deadlineSeconds'] == 120
    asyncio.run(research_continuation_step(runtime))
    assert len(runtime.calls) == 1, 'one idle tick must not create duplicate work'
    store.close()
    reopened = SessionStore(path)
    resumed = Runtime(reopened)
    state = reopened.research_job('resume')['state']
    state['lastContinuationAt'] = 0
    reopened.research_job_save('resume', sid, state)
    asyncio.run(research_continuation_step(resumed))
    assert len(resumed.calls) == 1
    assert resumed.calls[0][2] != runtime.calls[0][2]
    reopened.emit(sid, 'turn_end', {'turn': 1, 'researchId': 'resume',
                                   'deadlineUsedMs': 110000})
    asyncio.run(research_continuation_step(resumed))
    assert reopened.research_job('resume')['status'] == 'partial'
    assert len(resumed.calls) == 1
    reopened.close()


def test_one_passage_can_link_to_two_claims_with_independent_assessment(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    main = store.create({'skills': []})
    base = {'url': 'https://example.org/paper', 'host': 'example.org', 'tier': 0,
            'claim': 'Claim A', 'excerpt': 'The result is conditional on the sample.'}
    row = store.source_add(main['id'], base)
    assert row['tier'] == 0
    first = store.evidence_link(main['id'], row['rowId'], 'Claim A')
    second = store.evidence_link(main['id'], row['rowId'], 'Claim B')
    assert first['passageId'] == second['passageId']
    assert first['claimId'] != second['claimId']
    store.evidence_assess(main['id'], first['passageId'], second['claimId'],
                          'reviewer-1', 'hash-1', 'contradicts',
                          'The text explicitly restricts the result to this sample.')
    graph = store.evidence_graph(main['id'])
    assert len(graph) == 2
    assert next(item for item in graph if item['claim'] == 'Claim B')['assessments'][0]['relation'] == 'contradicts'
    store.close()


def test_new_dossier_flags_an_empirical_finding_with_no_row_pointer():
    report = ('## Câu hỏi\nChọn hướng.\n\n## Phát hiện\n'
              'Phương pháp A vượt phương pháp B trên nhiều bộ dữ liệu độc lập '
              'và có thể áp dụng cho mọi bệnh viện trong nước.\n\n'
              '## Nguồn\nChưa có nguồn.\n')
    verdict = research_quality.assess(markdown=report, rows=[], level=1,
                                      require_claim_citations=True)
    assert 'research-findings-unlinked' in [issue.code for issue in verdict.issues]


def test_short_verbatim_passage_needs_no_fabricated_padding_in_v2():
    row = research_ledger.Row(row_id='r1', claim='The finding is conditional',
                              url='https://example.org/paper', host='example.org', tier=0,
                              excerpt='Only Dataset A.')
    assert 'research-excerpt-missing' in [issue.code for issue in research_ledger.assess_rows([row])]
    assert 'research-excerpt-missing' not in [
        issue.code for issue in research_ledger.assess_rows([row], min_excerpt_chars=1)]
    verdict = research_quality.assess(rows=[row], markdown='## Câu hỏi\nA\n## Phát hiện\nB [r1]\n## Nguồn\nr1',
                                      level=1, require_claim_citations=True)
    assert 'research-excerpt-missing' not in [issue.code for issue in verdict.issues]


def test_new_job_saves_an_incomplete_dossier_as_draft(tmp_path):
    class Executor:
        async def execute(self, name, args, sid):
            if name == 'dossier_write':
                return {'relativePath': args['path'], 'bytes': len(args['markdown'].encode())}
            return {'ok': True}
        async def cleanup(self, sid):
            pass
    class Model:
        pass
    store = SessionStore(tmp_path / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Model())
    main = runtime.create({'skills': []})
    main['config']['research'] = {
        'researchId': 'example', 'jobMode': 'v2', 'jobProfile': 'market',
        'dossierDir': research_runtime.dossier_dir_for('example')}
    store.update_config(main['id'], main['config'])
    child = runtime.create({'skills': []}, parent_id=main['id'], role='research')
    store.child_start(child['id'], main['id'], 1, 1, 'research', 'No evidence found')
    store.child_finish(child['id'], 'cancelled')
    result = asyncio.run(research_runtime.dossier_write(runtime, main, {
        'researchId': 'example', 'level': 1, 'profile': 'users',
        'markdown': '## Câu hỏi\nChọn gì?\n\n## Phát hiện\nChưa rõ.\n\n## Nguồn\nChưa có.\n'}))
    assert result['state'] == 'draft' and result['gate']['ok'] is False
    assert 'research-lineage-missing' not in result['gate']['issues']
    row = store.dossier('example', 1)
    assert row['quality_ok'] == 0 and row['content_hash']
    store.close()


def test_review_of_another_dossier_cannot_supply_a_verdict(tmp_path):
    class Executor:
        async def execute(self, name, args, sid):
            return {'ok': True}
        async def cleanup(self, sid):
            pass
    class Model:
        pass
    store = SessionStore(tmp_path / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Model())
    main = runtime.create({'skills': []})
    document = '## Câu hỏi\nA\n## Phát hiện\nB\n## Nguồn\nC\n'
    digest = hashlib.sha256(document.encode()).hexdigest()
    path = '.research/example/v1-example.md'
    store.record_dossier(main['id'], 'example', 1, path, content_hash=digest)
    child = runtime.create({'skills': []}, parent_id=main['id'], role='research-review')
    child['config']['reviewTarget'] = {'kind': 'research', 'researchId': 'other',
                                      'version': 1, 'path': path, 'contentHash': digest,
                                      'mode': 'critique'}
    store.update_config(child['id'], child['config'])
    store.child_start(child['id'], main['id'], 1, 1, 'research-review', 'review')
    with store.db:
        store.db.execute('UPDATE children SET started=started+1 WHERE session_id=?', (child['id'],))
    store.emit(child['id'], 'tool_end', {'name': 'file_read', 'args': {'path': path},
                                        'result': {'content': document, 'truncated': False}})
    store.emit(child['id'], 'assistant', {'text': 'Evidence and reasoning reviewed. ' * 25 + '\nVERDICT: ok'})
    store.child_finish(child['id'], 'completed', answer_chars=800)
    with pytest.raises(ValueError, match='RESEARCH_VERIFY_NO_CRITIC'):
        research_runtime.research_critique(runtime, main['id'], 'example', 1)
    child['config']['reviewTarget']['researchId'] = 'example'
    store.update_config(child['id'], child['config'])
    critic, verdict, _ = research_runtime.research_critique(runtime, main['id'], 'example', 1)
    assert critic['session_id'] == child['id'] and verdict == 'ok'
    store.close()


def test_claim_assessment_requires_reading_the_bound_dossier(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    main = store.create({'skills': []})
    child = store.create({'skills': []}, parent_id=main['id'], role='research-review')
    document = '# Research\nA claim and its evidence.\n'
    digest = hashlib.sha256(document.encode()).hexdigest()
    path = '.research/claim/v1-claim.md'
    store.record_dossier(main['id'], 'claim', 1, path, content_hash=digest)
    child['config']['reviewTarget'] = {'kind': 'research', 'researchId': 'claim',
                                      'version': 1, 'path': path, 'contentHash': digest,
                                      'mode': 'evidence'}
    store.update_config(child['id'], child['config'])
    row = store.source_add(main['id'], {'url': 'https://example.org/a', 'host': 'example.org',
                                        'claim': 'A improves B', 'excerpt': 'A only improves B on dataset X.'})
    link = store.evidence_link(main['id'], row['rowId'], 'A improves B')
    class Runtime:
        pass
    runtime = Runtime()
    runtime.store = store
    args = {'passageId': link['passageId'], 'claimId': link['claimId'],
            'relation': 'insufficient',
            'rationale': 'The quoted result is restricted to dataset X only.'}
    with pytest.raises(ValueError, match='DOCUMENT_NOT_READ'):
        research_runtime.claim_assess(runtime, child, args)
    store.emit(child['id'], 'tool_end', {'name': 'file_read', 'args': {'path': path},
                                        'result': {'content': document, 'truncated': False}})
    result = research_runtime.claim_assess(runtime, child, args)
    assert result['relation'] == 'insufficient'
    assert store.evidence_graph(main['id'])[0]['assessments'][0]['content_hash'] == digest
    store.close()


def test_new_research_version_marks_dependent_plan_stale(tmp_path):
    store = SessionStore(tmp_path / 'sessions.sqlite')
    main = store.create({'skills': []})
    store.record_dossier(main['id'], 'study', 1, '.research/study/v1-study.md',
                         content_hash='hash-v1')
    store.plan_research_link('decision-plan', 1, [{'researchId': 'study', 'version': 1,
                                                   'contentHash': 'hash-v1'}])
    assert store.plan_research_dependencies('decision-plan', 1)[0]['stale'] is False
    store.record_dossier(main['id'], 'study', 2, '.research/study/v2-study.md',
                         content_hash='hash-v2')
    assert store.plan_research_dependencies('decision-plan', 1)[0]['stale'] is True
    class Runtime:
        pass
    runtime = Runtime()
    runtime.store = store
    assert 'PLAN_RESEARCH_STALE' in HarnessRuntime.plan_approval_blocked(runtime, 'decision-plan', 1)
    store.close()


def test_new_research_branch_requires_a_known_question(tmp_path):
    class Executor:
        async def execute(self, name, args, sid):
            return {'ok': True}
        async def cleanup(self, sid):
            pass
    class Model:
        pass
    store = SessionStore(tmp_path / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Model())
    root = runtime.create({'skills': []})
    # Bề mặt 7 đã xoá lối thoát của main, nên nhánh research chỉ còn giao được từ LEAD đã admit.
    lead, run_id = admit_lead(store, runtime, root)
    store.research_job_save(run_id, lead['id'], {
        'questions': [{'id': 'q1', 'text': 'Which approach?', 'status': 'unexplored'}],
        'budgetSeconds': 600}, status='researching')
    with pytest.raises(ValueError, match='RESEARCH_BRANCH_QUESTION_REQUIRED'):
        asyncio.run(runtime.delegate(store.get(lead['id']), {'role': 'research', 'goal': 'Find evidence'}))
    assert store.children_of(lead['id']) == []
    store.close()


def test_delegating_a_v2_question_marks_it_researching(tmp_path):
    class Executor:
        async def execute(self, name, args, sid):
            return {'ok': True}
        async def cleanup(self, sid):
            pass
    class Model:
        pass
    store = SessionStore(tmp_path / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Model())
    root = runtime.create({'skills': []})
    lead, run_id = admit_lead(store, runtime, root)
    store.research_job_save(run_id, lead['id'], {
        'questions': [{'id': 'q1', 'text': 'Which approach?', 'status': 'unexplored'}],
        'budgetSeconds': 600}, status='scoping')
    runtime.start = lambda *_: asyncio.get_running_loop().create_future()
    result = asyncio.run(runtime.delegate(store.get(lead['id']),
                                          {'role': 'research', 'goal': 'Find evidence',
                                           'questionId': 'q1', 'wait': False}))
    job = store.research_job(run_id)
    assert result['status'] == 'started'
    assert job['status'] == 'researching'
    assert job['state']['questions'][0]['status'] == 'researching'
    store.close()


def test_user_supplied_workspace_text_can_be_verified_without_web(tmp_path):
    class Executor:
        async def execute(self, name, args, sid):
            assert name == 'file_read' and args['path'] == 'docs/user-note.md'
            return {'content': 'The clinic uses a paper referral form.',
                    'truncated': False, 'nextOffset': None}
        async def cleanup(self, sid):
            pass
    class Model:
        pass
    store = SessionStore(tmp_path / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Model())
    main = runtime.create({'skills': []})
    row = store.source_add(main['id'], {'url': 'docs/user-note.md', 'method': 'workspace',
                                        'tier': 0, 'claim': 'The clinic uses paper referrals.',
                                        'excerpt': 'The clinic uses a paper referral form.'})
    result = asyncio.run(research_runtime.source_verify(runtime, main, {'rowId': row['rowId']}))
    assert result['status'] == 'ok' and result['matched'] is True
    assert result['claimSupport'] == 'not_checked'
    store.close()


def test_source_verify_walks_to_later_pdf_pages(tmp_path):
    class Executor:
        async def cleanup(self, sid):
            pass
    class Model:
        pass
    store = SessionStore(tmp_path / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Model())
    main = runtime.create({'skills': []})
    excerpt = 'The decisive result appears on page forty one with the correct split.'
    row = store.source_add(main['id'], {'url': 'https://example.org/paper.pdf',
                                        'host': 'example.org', 'claim': 'A result exists',
                                        'excerpt': excerpt})
    calls = []
    class FakeWeb:
        def fetch(self, args):
            calls.append(args)
            if args.get('pdfStartPage') == 41:
                return {'text': '## Trang 41\n\n' + excerpt, 'pdfNextPage': None,
                        'nextOffset': None, 'status': 200}
            return {'text': '## Trang 1\n\n' + ('Background material. ' * 20),
                    'pdfNextPage': 41, 'nextOffset': None, 'status': 200}
    runtime.web = FakeWeb()
    result = asyncio.run(research_runtime.source_verify(runtime, main, {'rowId': row['rowId']}))
    assert result['status'] == 'ok' and result['matched'] is True
    assert calls[1]['pdfStartPage'] == 41
    store.close()


def test_plan_review_must_read_the_bound_plan_version(tmp_path):
    class Executor:
        async def execute(self, name, args, sid):
            return {'ok': True}
        async def cleanup(self, sid):
            pass
    class Model:
        pass
    store = SessionStore(tmp_path / 'sessions.sqlite')
    runtime = HarnessRuntime(store, Executor(), Model())
    main = runtime.create({'skills': []})
    document = '# Plan\n## Verification\nInspect output.\n'
    digest = hashlib.sha256(document.encode()).hexdigest()
    path = '.plans/v1-example.md'
    store.emit(main['id'], 'plan_written', {'identity': 'example', 'version': 1,
                                           'relativePath': path, 'contentHash': digest})
    child = runtime.create({'skills': []}, parent_id=main['id'], role='plan-review')
    child['config']['reviewTarget'] = {'kind': 'plan', 'identity': 'other',
                                      'version': 1, 'path': path, 'contentHash': digest}
    store.update_config(child['id'], child['config'])
    store.child_start(child['id'], main['id'], 1, 1, 'plan-review', 'review')
    with store.db:
        store.db.execute('UPDATE children SET started=started+1 WHERE session_id=?', (child['id'],))
    store.emit(child['id'], 'tool_end', {'name': 'file_read', 'args': {'path': path},
                                        'result': {'content': document, 'truncated': False}})
    store.emit(child['id'], 'assistant', {'text': 'Plan review and feasibility. ' * 25 + '\nVERDICT: ok'})
    store.child_finish(child['id'], 'completed', answer_chars=800)
    with pytest.raises(ValueError, match='PLAN_VERIFY_NO_CRITIC'):
        runtime.plan_critique(main['id'], 'example', 1)
    child['config']['reviewTarget']['identity'] = 'example'
    store.update_config(child['id'], child['config'])
    critic, verdict, _ = runtime.plan_critique(main['id'], 'example', 1)
    assert critic['session_id'] == child['id'] and verdict == 'ok'
    store.close()
