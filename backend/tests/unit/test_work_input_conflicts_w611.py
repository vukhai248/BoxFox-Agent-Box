"""Typed assignment conflicts, using scripted reviewers; no semantic LLM oracle."""
import asyncio
import json
import re

import pytest

from agentbox.agent_core import work_checks
from test_work_graph import build, raw_tool
from test_work_checks import RESEARCH, setup, start


def conflict_reviewer(model, whole=False, partial=False):
    original = model.complete
    switch = {'enabled': True}

    async def complete(messages, *args, **kwargs):
        result = await original(messages, *args, **kwargs)
        first = next(str(m.get('content') or '') for m in messages if m['role'] == 'user')
        prefix = 'Whole-plan review' if whole else 'Independent review'
        message = result['choices'][0]['message']
        if switch['enabled'] and first.startswith(prefix) and message.get('content'):
            report = json.loads(re.findall(r'```json\s*\n(.*?)\n```', message['content'], re.S)[-1])
            item = next(c for c in report['coverage'] if c['id'] == ('R1.A1' if whole else 'A1'))
            item.update(status='revise', target='criterion', evidence='Opened source contradicts this premise; main must correct the criterion.')
            message['content'] = ('The artifact is factually correct; the assignment conflicts with source.\n```json\n'
                                  + json.dumps(report) + '\n```\nVERDICT: revise')
            if partial:
                result['choices'][0]['finish_reason'] = 'length'
        return result

    model.complete = complete
    return switch


@pytest.mark.parametrize('target,status,cid', [
    ('criterion', 'pass', 'A1'), ('criterion', 'unverified', 'A1'),
    ('criterion', 'revise', 'C1'), ('criterion', 'revise', 'G1'),
    ('unknown', 'revise', 'A1'), (None, 'revise', 'A1'),
])
def test_malformed_conflicts_cannot_pass(target, status, cid):
    text = '```json\n' + json.dumps({'coverage': [
        {'id': cid, 'status': status, 'target': target, 'evidence': 'Reference'}
    ]}) + '\n```\nVERDICT: revise'
    assert work_checks.parse_report(text, [cid])[0] == 'error'


def test_legacy_report_is_readable_but_new_revise_requires_explicit_target():
    report = {'coverage': [{'id': 'A1', 'status': 'revise', 'evidence': 'Conflicting requirement'}]}
    text = '```json\n' + json.dumps(report) + '\n```\nVERDICT: revise'
    assert work_checks.parse_report(text, ['A1'])[0] == 'revise'
    assert work_checks.parse_report(text, ['A1'], require_target=True)[0] == 'error'
    for target in ('artifact', 'criterion'):
        report['coverage'][0]['target'] = target
        text = '```json\n' + json.dumps(report) + '\n```\nVERDICT: revise'
        assert work_checks.parse_report(text, ['A1'], require_target=True)[0] == 'revise'


@pytest.mark.parametrize('lang', ['en', 'vi'])
def test_every_json_contract_example_includes_target(lang):
    contract = work_checks.contract(lang, {'A1': 'Requirement'})
    assert '"target":"artifact|criterion"' in contract
    assert '"status":"revise","target":"criterion"' in contract
    skeleton = json.loads(contract.splitlines()[-1])
    assert skeleton['coverage'][0]['target'] == 'artifact'


def test_missing_target_retries_once_without_turning_into_producer_feedback(tmp_path):
    store, rt, model, _, sid = build(tmp_path)
    conflict_reviewer(model)
    original = model.complete

    async def missing_target(messages, *args, **kwargs):
        result = await original(messages, *args, **kwargs)
        message = result['choices'][0]['message']
        if message.get('content') and '```json' in message['content']:
            report = json.loads(re.findall(r'```json\s*\n(.*?)\n```', message['content'], re.S)[-1])
            for item in report['coverage']:
                item.pop('target', None)
            message['content'] = '```json\n' + json.dumps(report) + '\n```\nVERDICT: revise'
        return result

    model.complete = missing_target

    async def run():
        _, draft = await setup(rt, sid)
        result = await start(rt, sid, draft)
        doc = result['checks'][0]
        assert doc['status'] == 'error' and len(doc['attempts']) == 2
        assert not doc['inputConflicts']
        assert result['nodes'][0]['stages']['produce'] == 'needs_checks'
        assert 'explicitly set target' in model.prompts[-1][1]
        assert len(store.children_of(sid)) == 3  # one producer, two reviewers

    asyncio.run(run())


def test_input_conflict_is_durable_blocks_retries_and_needs_changed_acceptance(tmp_path):
    store, rt, model, _, sid = build(tmp_path)
    switch = conflict_reviewer(model)

    async def run():
        rid, draft = await setup(rt, sid)
        aid = draft['nodes'][0]['artifacts']['produce']['artifactId']
        checked = await start(rt, sid, draft, invocationId='conflict')
        assert checked['nodes'][0]['stages']['produce'] == 'revise'
        assert checked['checks'][0]['inputConflicts'][0]['requirement'] == RESEARCH['acceptance'][0]
        assert 'correct the conflicting' in checked['next']
        count = len(store.children_of(sid))
        # Replayed invocation and new attempts cannot silently override the conflict.
        for invocation in ('conflict', 'new-check'):
            again = await start(rt, sid, draft, invocationId=invocation)
            assert again['checks'][0]['inputConflicts']
        before = rt.work_graph.get(rid)
        again = await raw_tool(rt, sid, 'work_run', {'phase': 'discover'})
        assert again['inputConflicts']
        assert rt.work_graph.get(rid)['status'] == before['status']
        assert len(store.children_of(sid)) == count
        # Metadata changes or reordered criteria do not erase unchanged conflicts.
        for patch in ({'title': 'Retitled result'}, {'acceptance': list(reversed(RESEARCH['acceptance']))}):
            await raw_tool(rt, sid, 'work_graph', {'action': 'update', 'nodes': [{'id': 'R1', **patch}]})
            again = await raw_tool(rt, sid, 'work_run', {'phase': 'discover'})
            assert again['inputConflicts'] and len(store.children_of(sid)) == count
        # Correcting the requirement creates a new draft and requires fresh checks.
        await raw_tool(rt, sid, 'work_graph', {'action': 'update', 'nodes': [
            {'id': 'R1', 'acceptance': ['Corrected factual premise', RESEARCH['acceptance'][1]]}]})
        switch['enabled'] = False
        fresh = await raw_tool(rt, sid, 'work_run', {'phase': 'discover'})
        assert fresh['nodes'][0]['artifacts']['produce']['artifactId'] != aid
        assert fresh['nodes'][0]['stages']['produce'] == 'needs_checks'
        assert (await start(rt, sid, fresh))['nodes'][0]['stages']['produce'] == 'accepted'
        assert all(r['status'] == 'superseded' for r in rt.work_graph.checks.records(rid) if r['artifactId'] == aid)
        # SQLite retains the original conflict/requirement independently of live objects.
        assert json.loads(store.db.execute('SELECT doc FROM work_checks WHERE invocation=?',
                                          ('conflict:evidence',)).fetchone()[0])['inputConflicts']

    asyncio.run(run())


def test_whole_review_routes_criterion_conflict_to_main(tmp_path):
    store, rt, model, _, sid = build(tmp_path)

    async def run():
        rid, draft = await setup(rt, sid)
        await start(rt, sid, draft)
        conflict_reviewer(model, whole=True)
        result = await raw_tool(rt, sid, 'work_graph', {'action': 'verify'})
        assert result['verdict'] == 'revise' and result['reviseNodes'] == ['R1']
        state = rt.work_graph.get(rid)['nodes'][0]['stages']['produce']
        assert state['inputConflicts'][0]['id'] == 'A1'
        assert state['inputConflicts'][0]['requirement'] == RESEARCH['acceptance'][0]
        count = len(store.children_of(sid))
        assert (await raw_tool(rt, sid, 'work_run', {'phase': 'discover'}))['inputConflicts']
        assert len(store.children_of(sid)) == count

    asyncio.run(run())


def test_partial_reviewer_cannot_confirm_assignment_conflict(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    conflict_reviewer(model, partial=True)

    async def run():
        _, draft = await setup(rt, sid)
        result = await start(rt, sid, draft)
        assert all(c['status'] == 'error' and not c['inputConflicts'] for c in result['checks'])
        assert not rt.work_graph.active(sid)['nodes'][0]['stages']['produce'].get('inputConflicts')

    asyncio.run(run())
