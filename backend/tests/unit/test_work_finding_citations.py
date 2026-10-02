"""W6.1.3 finding/citation contract: only a cited, self-challenged finding blocks.

Deterministic corpus (no model call) built from the saved W6.1 evidence files; the model only
supplies the report text. Every receipt must have been observed in THIS admission.
"""
import asyncio
import hashlib
import json
import re
from pathlib import Path

import pytest

from agentbox.agent_core import roles, tool_contracts, work_checks, work_graph, work_prompts
from test_work_graph import build, ok_script
from test_work_checks import setup, start


CORPUS = Path(__file__).resolve().parents[1] / 'fixtures' / 'work_review_corpus'
CRITERIA = {'A1': 'Preserve the owner constraint', 'A2': 'Distinguish facts and proposals'}


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def seed_events(store, child_id, events):
    """Emit the fixture tool events; returns the seq of the last one (an admission boundary)."""
    last = 0
    for event in events:
        payload = {'id': event['id'], 'name': event['name'], 'args': event.get('args') or {},
                   'result': event.get('result') or {}}
        receipt = payload['result'].get('receipt')
        if event['name'] == 'verify_exec' and not isinstance(receipt, dict):
            content = str(payload['result'].get('content') or '')
            payload['result']['receipt'] = {
                'kind': 'verify_exec', 'language': (event.get('args') or {}).get('language', 'python'),
                'codeHash': digest(str((event.get('args') or {}).get('code') or '')),
                'stdinHash': digest(''), 'outputHash': digest(content),
                'exitCode': payload['result'].get('exit_code', 0), 'durationMs': 1,
                'truncated': False, 'claim': (event.get('args') or {}).get('claim')}
        last = store.emit(child_id, 'tool_end', payload)
    return last


def analyze(rt, run, raw, scope_kind='node', artifacts=(), admission=0, child_id=None):
    graph = work_graph.service(rt)
    child_id = child_id or run['sessionId']
    status, coverage, text = work_checks.parse_report(raw, CRITERIA, require_target=True)
    analysis = work_checks.validate_findings(graph, child_id, admission, text, CRITERIA, scope_kind, artifacts)
    status, coverage, uncited = work_checks.apply_findings(text, status, coverage, analysis)
    return {'status': status, 'coverage': coverage, 'uncited': uncited, 'analysis': analysis,
            'proseWords': work_checks.prose_words(text), 'raw': text}


def run_corpus_case(tmp_path, case):
    """One deterministic corpus case: real store, real artifacts, no model call."""
    store, rt, _, _, sid = build(tmp_path)

    async def check():
        graph = work_graph.service(rt)
        run = graph.create(store.get(sid), {'goal': case['case'], 'flow': 'plan', 'nodes': [
            {'id': 'P1', 'kind': 'plan', 'title': 'Slice', 'goal': 'Write the sub-plan for the slice',
             'acceptance': list(CRITERIA.values()), 'tests': ['python3 -m pytest -q']}]})
        raw = case['reportText']
        artifacts = []
        if case.get('bindArtifact'):
            meta = await graph.artifacts.put(run, 'P1', 'produce', case['bindArtifact']['text'], {}, True)
            artifacts.append(meta)
            raw = raw.replace('{{artifactRef}}', f"artifact:{meta['artifactId']}@{meta['contentHash']}")
        last = seed_events(store, sid, case.get('toolEvents') or [])
        # `admissionAfterEvents` means the fixture events happened BEFORE this review's admission.
        admission = last if case.get('admissionAfterEvents') else 0
        return analyze(rt, run, raw, artifacts=artifacts, admission=admission, child_id=sid)

    return asyncio.run(check())



def criteria_from(prompt):
    """The rubric ids main assigned, read from the reviewer prompt (same trick as the Model fixture)."""
    match = re.search(r'\{"(?:A1|C1|G1)"', prompt)
    return json.JSONDecoder().raw_decode(prompt[match.start():])[0] if match else {'A1': 'contract'}


def report_for(prompt, findings, verdict, revised='auto'):
    criteria = criteria_from(prompt)
    revised = next(iter(criteria)) if revised == 'auto' else revised
    coverage = [{'id': key, 'status': 'revise' if key == revised else 'pass', 'target': 'artifact',
                 'evidence': 'Observed on the opened source.'} for key in criteria]
    if revised is not None:
        coverage[list(criteria).index(revised)]['findingIds'] = [item['id'] for item in findings] or ['F1']
    doc = {'coverage': coverage, 'findings': findings}
    return 'Review of the assigned artifact.\n```json\n' + json.dumps(doc, ensure_ascii=False) + \
        '\n```\nVERDICT: ' + verdict


def blocking_finding(**overrides):
    item = {'id': 'F1', 'severity': 'blocking', 'scope': 'node',
            'claim': 'Labels are missing from the export.', 'evidenceRefs': ['call_invented'],
            'counterCheck': {'strongest': 'Maybe labels come later', 'checkedBy': 'call_invented',
                             'outcome': 'refuted'},
            'impact': 'A1 requires labels', 'fix': 'add labels'}
    item.update(overrides)
    return item


@pytest.mark.parametrize('path', sorted(CORPUS.glob('*.json')), ids=lambda p: p.stem)
def test_corpus_cases_match_expected(tmp_path, path):
    case = json.loads(path.read_text())
    result = run_corpus_case(tmp_path, case)
    expected = case['expected']
    assert result['status'] == expected['status'], (case['case'], result['analysis'])
    assert result['analysis']['blocking'] == expected['blocking'], (case['case'], result['analysis'])
    assert result['analysis']['downgraded'] == expected['downgraded'], (case['case'], result['analysis'])
    if 'overLimit' in expected:
        assert (result['proseWords'] > work_checks.PROSE_WORD_CAP) is expected['overLimit']


def test_blocking_finding_without_receipt_is_downgraded_to_note(tmp_path):
    async def check():
        store, rt, model, _, sid = build(tmp_path)
        _, draft = await setup(rt, sid)
        original = model.complete
        async def reviewer(*args, **kwargs):
            result = await original(*args, **kwargs)
            prompt = next(m.get('content', '') for m in args[0] if m['role'] == 'user')
            if prompt.startswith('Independent review') and result['choices'][0]['finish_reason'] == 'stop':
                return {'choices': [{'message': {'content': report_for(
                    prompt, [blocking_finding(criterionId=next(iter(criteria_from(prompt))))], 'revise')},
                    'finish_reason': 'stop'}], 'usage': {}}
            return result
        model.complete = reviewer
        result = await start(rt, sid, draft)
        doc = result['checks'][0]
        assert doc['status'] == 'unverified'
        assert doc['downgraded'][0]['reason'] == 'UNKNOWN_RECEIPT'
        assert doc['attempts'][0]['contractError'] == 'WORK_FINDING_UNCITED'
        assert doc['attempts'][0]['findings'] == 1 and doc['attempts'][0]['blocking'] == 0
    asyncio.run(check())


def test_cited_true_finding_keeps_revise(tmp_path):
    async def check():
        store, rt, model, executor, sid = build(tmp_path)
        _, draft = await setup(rt, sid)
        original = model.complete
        asked = set()
        async def reviewer(*args, **kwargs):
            result = await original(*args, **kwargs)
            prompt = next(m.get('content', '') for m in args[0] if m['role'] == 'user')
            if not prompt.startswith('Independent review'):
                return result
            if result['choices'][0]['finish_reason'] == 'stop' and prompt not in asked:
                # One real verify_exec receipt before the verdict, like a live reviewer.
                asked.add(prompt)
                call = {'id': 'call_verify', 'type': 'function', 'function': {
                    'name': 'verify_exec', 'arguments': json.dumps({
                        'language': 'python', 'code': "import csv;print(csv.Error)", 'claim': 'csv.Error'})}}
                return {'choices': [{'message': {'tool_calls': [call]}, 'finish_reason': 'tool_calls'}],
                        'usage': {}}
            if result['choices'][0]['finish_reason'] == 'stop':
                finding = blocking_finding(criterionId=next(iter(criteria_from(prompt))),
                                           claim='parse_rows raises csv.Error, not ValueError, on a NUL byte.',
                                           evidenceRefs=['call_verify'],
                                           counterCheck={'strongest': 'A wrapper may convert it',
                                                         'checkedBy': 'call_verify', 'outcome': 'refuted'})
                return {'choices': [{'message': {'content': report_for(prompt, [finding], 'revise')},
                                     'finish_reason': 'stop'}], 'usage': {}}
            return result
        model.complete = reviewer
        original_execute = executor.execute
        async def verifying(name, args, *rest, **kwargs):
            if name == 'verify_exec':
                return {'content': 'csv.Error\n', 'exit_code': 1, 'is_error': False,
                        'receipt': {'kind': 'verify_exec', 'language': 'python',
                                    'codeHash': digest(args['code']), 'stdinHash': digest(''),
                                    'outputHash': digest('csv.Error\n'), 'exitCode': 1, 'durationMs': 3,
                                    'truncated': False, 'claim': args['claim']}}
            return await original_execute(name, args, *rest, **kwargs)
        executor.execute = verifying
        result = await start(rt, sid, draft)
        doc = result['checks'][0]
        assert doc['status'] == 'revise'
        assert doc['blocking'] == ['F1'] and doc['downgraded'] == []
        assert result['nodes'][0]['stages']['produce'] == 'revise'
    asyncio.run(check())


def test_side_remark_does_not_block_criterion_pass(tmp_path):
    async def check():
        store, rt, model, _, sid = build(tmp_path)
        _, draft = await setup(rt, sid)
        original = model.complete
        async def reviewer(*args, **kwargs):
            result = await original(*args, **kwargs)
            prompt = next(m.get('content', '') for m in args[0] if m['role'] == 'user')
            if prompt.startswith('Independent review') and result['choices'][0]['finish_reason'] == 'stop':
                note = blocking_finding(severity='note', criterionId=next(iter(criteria_from(prompt))),
                                        evidenceRefs=[], claim='Heading order could be tighter.')
                return {'choices': [{'message': {'content': report_for(prompt, [note], 'ok', revised=None)},
                                     'finish_reason': 'stop'}], 'usage': {}}
            return result
        model.complete = reviewer
        result = await start(rt, sid, draft)
        doc = result['checks'][0]
        assert doc['status'] == 'pass' and doc['findingNotes'] == ['F1']
        assert result['nodes'][0]['stages']['produce'] == 'accepted'
    asyncio.run(check())


def test_legacy_policy10_report_still_parses(tmp_path):
    async def check():
        store, rt, _, _, sid = build(tmp_path)
        _, draft = await setup(rt, sid)
        raw = ('Legacy report.\n```json\n' + json.dumps({'coverage': [
            {'id': 'A1', 'status': 'revise', 'target': 'artifact', 'evidence': 'missing'},
            {'id': 'A2', 'status': 'pass', 'target': 'artifact', 'evidence': 'ok'}]}) + '\n```\nVERDICT: revise')
        result = analyze(rt, work_graph.service(rt).get(draft['runId']), raw)
        assert result['status'] == 'revise' and result['uncited'] is None
        assert result['analysis']['findings'] == 0
    asyncio.run(check())


def test_review_contract_describes_findings_and_caps():
    for lang in ('en', 'vi'):
        contract = work_checks.contract(lang, CRITERIA)
        assert 'counterCheck' in contract and 'evidenceRefs' in contract
        assert 'verify:<codeHash>' in contract
        tail = work_prompts.review_tail(lang)
        assert ('ghi chú' in tail) if lang == 'vi' else ('note' in tail.lower())


def test_review_contract_demands_tool_call_ids_and_verify_exec():
    """Quyết định #6423: ref phải là toolCallId trong chính lượt (hoặc verify:<codeHash>), không phải prose."""
    for lang in ('en', 'vi'):
        contract = work_checks.contract(lang, CRITERIA)
        assert 'toolCallId' in contract, lang
        assert 'verify_exec' in contract, lang
        assert 'file_read:src/x.py' in contract, lang          # ví dụ ref SAI bị hạ cấp
    instructions = roles.REVIEW_INSTRUCTIONS + roles.RESEARCH_REVIEW_INSTRUCTIONS + roles.WORK_REVIEWER_NOTE
    assert 'toolCallId' in instructions and 'verify:<codeHash>' in instructions
    # verify_exec giờ đọc được repo (read-only), ghi scratch và ra mạng — prompt phải nói đúng quyền đó.
    assert 'READ-ONLY on the repository' in instructions
    assert '/tmp/work' in instructions
    schema = next(item for item in tool_contracts.SCHEMAS if item['function']['name'] == 'verify_exec')
    description = schema['function']['description']
    assert 'READ-ONLY but readable' in description and 'scratch' in description and 'network' in description
