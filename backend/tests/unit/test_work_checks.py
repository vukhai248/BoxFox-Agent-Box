"""W6 acceptance V01–V14 through real dispatch/storage; scripted model only."""
import asyncio
import json
import subprocess
import sys
import uuid

import pytest

from agentbox.agent_core import work_graph as wg, work_policy as policy, work_checks as checks
from test_work_graph import build, raw_tool, tool, PLAN, EXPLORE, ok_script, answer


RESEARCH = {'id': 'R1', 'kind': 'research', 'title': 'Compare approaches',
            'goal': 'Compare two export formats using the provided evidence',
            'acceptance': ['Keep the exact owner constraints', 'Distinguish facts and proposals']}


async def setup(rt, sid, node=RESEARCH, goal='Research the two approaches', flow='research'):
    created = await raw_tool(rt, sid, 'work_graph', {'action': 'create', 'goal': goal, 'flow': flow})
    await raw_tool(rt, sid, 'work_graph', {'action': 'add', 'nodes': [node]})
    result = await raw_tool(rt, sid, 'work_run', {'phase': 'discover' if node['kind'] in wg.DISCOVERY_KINDS + ('plan',) else 'execute'})
    return created['runId'], result


async def start(rt, sid, result, **overrides):
    node = result['nodes'][0]
    stage = 'produce' if 'produce' in node['artifacts'] else 'execute'
    args = {'action': 'start', 'runId': result['runId'], 'nodeId': node['id'], 'stage': stage,
            'artifactId': node['artifacts'][stage]['artifactId'], 'invocationId': uuid.uuid4().hex}
    args.update(overrides)
    return await raw_tool(rt, sid, 'work_check', args)


def test_V01_main_gets_draft_then_explicitly_dispatches_check(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    async def run():
        rid, draft = await setup(rt, sid)
        assert draft['outputs'][0]['status'] == 'needs_checks'
        assert [k for k, _ in model.prompts] == ['produce']
        with pytest.raises(ValueError, match='WORK_NOT_READY'):
            await raw_tool(rt, sid, 'work_graph', {'action': 'verify'})
        checked = await start(rt, sid, draft)
        assert checked['checks'][0]['status'] == 'pass'
        assert checked['nodes'][0]['stages']['produce'] == 'accepted'
        meta = draft['outputs'][0]['artifact']
        assert meta['artifactId'] in model.prompts[-1][1]
        assert '## Findings\n- src/a.py:1 fixture' not in model.prompts[-1][1]
        assert rt.work_graph.checks.records(rid)[0]['coverage']
    asyncio.run(run())


def test_V06_simple_lookup_reads_source_without_reviewer(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    async def run():
        _, result = await setup(rt, sid, EXPLORE, 'Locate the chat header', 'research')
        assert result['outputs'][0]['status'] == 'accepted'
        assert result['outputs'][0]['policy']['required'] == []
        assert len(model.prompts) == 1
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['build', 'debug', 'testing', 'simplify', 'plan'])
def test_V03_V08_actual_patch_cannot_be_disguised_as_diagnosis(kind):
    node = {'kind': kind, 'goal': 'Look up one harmless field', 'artifactKind': 'diagnostic', 'taskKind': 'diagnostic'}
    derived = policy.derive({'goal': 'Inspect one field'}, node, 'execute', changed=True)
    assert derived['artifactKind'] == 'patch'
    assert [c['id'] for c in derived['required']] == ['tests']


@pytest.mark.parametrize('kind', ['plan', 'design', 'research'])
def test_V08_declared_artifact_cannot_lower_role_minimum(kind):
    value = policy.derive({'goal': 'Compare the existing alternatives'},
                          {'kind': kind, 'goal': 'Produce the full requested deliverable', 'artifactKind': 'knowledge'}, 'produce')
    assert value['required'] and value['artifactKind'] == kind


def test_V07_consequential_research_requires_evidence_and_independent_critique(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    async def run():
        _, result = await setup(rt, sid, goal='Research medical record safety')
        assert [r['id'] for r in result['outputs'][0]['policy']['required']] == ['evidence', 'critique']
        first = await start(rt, sid, result, checkIds=['evidence'])
        assert first['nodes'][0]['stages']['produce'] == 'needs_checks'
        second = await start(rt, sid, result, checkIds=['critique'])
        assert second['nodes'][0]['stages']['produce'] == 'accepted'
        assert [k for k, _ in model.prompts] == ['produce', 'review', 'review']
    asyncio.run(run())


def test_separate_check_pass_does_not_erase_previous_blocking_finding(tmp_path):
    rejected = False
    def script(kind, text):
        nonlocal rejected
        if kind == 'review' and '"id": "evidence"' in text and not rejected:
            rejected = True
            return 'Fix unsupported recommendation.\nVERDICT: revise'
        return ok_script(kind, text)
    _, rt, _, _, sid = build(tmp_path, script)
    async def run():
        _, result = await setup(rt, sid, goal='Research medical record safety')
        evidence = await start(rt, sid, result, checkIds=['evidence'])
        assert evidence['nodes'][0]['stages']['produce'] == 'revise'
        critique = await start(rt, sid, result, checkIds=['critique'])
        assert critique['checks'][0]['status'] == 'pass'
        assert critique['nodes'][0]['stages']['produce'] == 'revise'
        state = rt.work_graph.active(sid)['nodes'][0]['stages']['produce']
        assert 'Fix unsupported recommendation' in state['feedback']
        # A newer pass for the SAME required check supersedes its older finding.
        resolved = await start(rt, sid, result, checkIds=['evidence'])
        assert resolved['nodes'][0]['stages']['produce'] == 'accepted'
    asyncio.run(run())


def test_whole_json_finding_routes_node_even_without_revise_marker(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    original = model.complete
    async def missing_marker(messages, tools, route, **kwargs):
        result = await original(messages, tools, route, **kwargs)
        first = next(m.get('content', '') for m in messages if m['role'] == 'user')
        if first.startswith('Whole-plan review') and result['choices'][0]['finish_reason'] == 'stop':
            coverage = [{'id': k, 'status': 'revise' if k == 'R1.A2' else 'pass',
                         'target': 'artifact',
                         'evidence': 'Separate facts from recommendations.' if k == 'R1.A2' else 'Observed fixture.'}
                        for k in ('G1', 'G2', 'G3', 'R1.A1', 'R1.A2')]
            return answer('Missing labels in R1.\n```json\n' + json.dumps({'coverage': coverage}) + '\n```\nVERDICT: revise')
        return result
    model.complete = missing_marker
    async def run():
        _, draft = await setup(rt, sid)
        await start(rt, sid, draft)
        reviewed = await raw_tool(rt, sid, 'work_graph', {'action': 'verify'})
        assert reviewed['reviseNodes'] == ['R1']
        assert reviewed['nodes'][0]['stages']['produce'] == 'revise'
        state = rt.work_graph.active(sid)['nodes'][0]['stages']['produce']
        assert 'Separate facts' in state['feedback']
        repaired = await raw_tool(rt, sid, 'work_run', {'phase': 'discover'})
        assert repaired['outputs'][0]['artifact']['artifactId'] != draft['outputs'][0]['artifact']['artifactId']
    asyncio.run(run())


def test_many_dependency_refs_fit_prompt_without_copying_bindings(tmp_path):
    _, rt, _, _, _ = build(tmp_path)
    graph = wg.service(rt)
    deps = []
    for i in range(16):
        node = wg.normalize_node(EXPLORE | {'id': f'E{i}'})
        node['stages']['produce'].update(status='accepted', artifact={
            'artifactId': f'a-{i}', 'nodeId': f'E{i}', 'stage': 'produce', 'version': i + 1,
            'contentHash': 'a' * 64, 'path': f'.plans/work/session/run/E{i}/produce/v1-a.md',
            'chars': 24000, 'status': 'finalized', 'binding': {'opaque': 'x' * 4000}})
        deps.append(node)
    consumer = wg.normalize_node(PLAN | {'dependsOn': [n['id'] for n in deps]})
    context = graph.dependency_context({'runId': 'w-fixture', 'nodes': deps + [consumer]}, consumer, 'produce')
    assert len(context) < 16000 and 'opaque' not in context
    assert len(json.loads(context)['acceptedDependencySnapshots']) == 16


def test_internal_knowledge_without_opened_evidence_stays_unverified(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    async def invented(*args, **kwargs):
        return answer('I know the source says CSV; no tools used.')
    model.complete = invented
    graph = wg.service(rt)
    run = graph.create(rt.store.get(sid), {'goal': 'Research export formats', 'flow': 'research'})
    result = asyncio.run(graph.answer_knowledge(rt.store.get(sid), run, wg.normalize_node(RESEARCH),
                        'produce', [{'role': 'explore', 'question': 'Where is CSV declared?'}], 1))
    assert result[0]['status'] == 'unverified' and result[0]['answer'].startswith('UNVERIFIED:')


def test_V01_research_candidate_plan_requires_plan_gate():
    p = policy.derive({'goal': 'Compare alternatives'}, RESEARCH, 'produce', '# Report\n## Implementation plan\nM1')
    assert p['artifactKind'] == 'plan'
    assert p['required'][0]['id'] == 'plan_review'


def test_V02_diagnostic_is_not_forced_into_semantic_review(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    node = {'id': 'D1', 'kind': 'debug', 'title': 'Diagnose', 'goal': 'Diagnose a header read failure only',
            'tests': ['Reproduction is not run'], 'taskKind': 'diagnostic'}
    async def run():
        await raw_tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Fix header read failure', 'flow': 'fix'})
        await raw_tool(rt, sid, 'work_graph', {'action': 'add', 'nodes': [node]})
        graph = rt.work_graph
        run = graph.active(sid)
        run['status'] = 'approved'
        graph.save(run)
        result = await raw_tool(rt, sid, 'work_run', {'phase': 'execute'})
        assert result['outputs'][0]['status'] == 'accepted'
        assert len(model.prompts) == 1
        child = rt.store.get(rt.store.children_of(sid)[0]['session_id'])
        with pytest.raises(PermissionError, match='WORK_DIAGNOSTIC_READ_ONLY'):
            await rt.dispatch(child, 'file_write', {'path': 'src/a.py', 'content': 'patch'})
    asyncio.run(run())


@pytest.mark.parametrize('mutation', ['file_write', 'file_edit_block', 'write_plan', 'delegate_task'])
def test_V05_checker_direct_write_or_delegation_blocked(tmp_path, mutation):
    _, rt, _, _, sid = build(tmp_path)
    async def run():
        await setup(rt, sid)
        child = rt.create({}, parent_id=sid, role='testing')
        child['config']['workBinding'] = {'checkId': 'c-real'}
        rt.store.update_config(child['id'], child['config'])
        with pytest.raises(PermissionError, match='WORK_CHECK_READ_ONLY'):
            await rt.dispatch(child, mutation, {})
    asyncio.run(run())


def test_V10_large_artifact_tail_read_and_unicode_roundtrip(tmp_path):
    text = '# Thiết kế\n' + 'Dữ liệu và hợp đồng\n' * 1600 + '\nTAIL: sai hợp đồng cuối file'
    _, rt, model, _, sid = build(tmp_path, lambda k, t: text if k == 'produce' else ok_script(k, t))
    async def run():
        rid, result = await setup(rt, sid)
        meta = result['outputs'][0]['artifact']
        assert meta['chars'] == len(text) > 20000
        assert rt.work_graph.artifacts.get(rid, meta['artifactId'])[1] == text
        checked = await start(rt, sid, result)
        assert checked['checks'][0]['status'] == 'pass'
        checker = checked['checks'][0]['childId']
        assert rt.work_graph.artifacts.covered(checked['checks'][0]['checkId'], meta, checker)
        offsets = rt.store.db.execute('SELECT start FROM work_artifact_reads WHERE reader_id=?', (checker,)).fetchall()
        assert max(row[0] for row in offsets) >= 24000
        assert 'TAIL:' not in model.prompts[-1][1]  # Only refs; content arrives through tools.
    asyncio.run(run())


def test_V10_unread_tail_never_passes(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    original = model.complete
    async def omit(messages, tools, route, **kwargs):
        first = next(m.get('content', '') for m in messages if m['role'] == 'user')
        if first.startswith('Independent review'):
            return answer('```json\n' + json.dumps({'coverage': [
                {'id': key, 'status': 'pass', 'evidence': 'claimed'} for key in ('A1', 'A2', 'C1')]}) + '\n```\nVERDICT: ok')
        return await original(messages, tools, route, **kwargs)
    model.complete = omit
    async def run():
        _, result = await setup(rt, sid)
        checked = await start(rt, sid, result)
        assert checked['checks'][0]['status'] == 'unverified'
        assert checked['nodes'][0]['stages']['produce'] == 'needs_checks'
    asyncio.run(run())


@pytest.mark.parametrize('truncated', ['length', 'content_filter'])
def test_V09_partial_producer_is_stored_but_not_accepted(tmp_path, truncated):
    _, rt, model, _, sid = build(tmp_path)
    async def partial(*args, **kwargs):
        value = answer('## Draft\nnot finished')
        value['choices'][0]['finish_reason'] = truncated
        return value
    model.complete = partial
    async def run():
        _, result = await setup(rt, sid)
        meta = result['outputs'][0]['artifact']
        assert meta['status'] == 'partial'
        assert result['outputs'][0]['status'] != 'accepted'
        with pytest.raises(ValueError, match='WORK_CHECK_NOT_READY'):
            await start(rt, sid, result)
    asyncio.run(run())


def test_V11_session_ownership_and_child_scope(tmp_path):
    _, rt, _, _, sid = build(tmp_path)
    async def run():
        rid, result = await setup(rt, sid)
        meta = result['outputs'][0]['artifact']
        other = rt.create({})
        with pytest.raises(ValueError, match='another session'):
            rt.work_graph.artifacts.read(other, {'runId': rid, 'artifactId': meta['artifactId']})
        child = rt.create({}, parent_id=sid, role='research-review')
        child['config']['workBinding'] = {'runId': rid, 'artifactIds': []}
        with pytest.raises(PermissionError, match='WORK_ARTIFACT_SCOPE'):
            rt.work_graph.artifacts.read(child, {'artifactId': meta['artifactId']})
    asyncio.run(run())


def test_invocation_dedup_and_stale_artifact_conflict(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    async def run():
        _, result = await setup(rt, sid)
        first = await start(rt, sid, result, invocationId='same')
        count = len(model.prompts)
        second = await start(rt, sid, result, invocationId='same')
        assert len(model.prompts) == count
        assert first['checks'][0]['checkId'] == second['checks'][0]['checkId']
        with pytest.raises(ValueError, match='WORK_CHECK_STALE'):
            await start(rt, sid, result, artifactId='old-version')
        with pytest.raises(ValueError, match='WORK_CHECK_INVALID'):
            await start(rt, sid, result, checkIds=['not_required'])
    asyncio.run(run())


def test_changed_definition_invalidates_checks_and_dependent_artifacts(tmp_path):
    _, rt, _, _, sid = build(tmp_path)
    async def run():
        await tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Add export'})
        await tool(rt, sid, 'work_graph', {'action': 'add', 'nodes': [RESEARCH, PLAN | {'dependsOn': ['R1']}]})
        await tool(rt, sid, 'work_run', {'phase': 'discover'})
        await tool(rt, sid, 'work_graph', {'action': 'verify'})
        old = rt.work_graph.active(sid)
        old_aid = old['nodes'][0]['stages']['produce']['artifact']['artifactId']
        await raw_tool(rt, sid, 'work_graph', {'action': 'update', 'nodes': [{'id': 'R1', 'files': ['src/other.py']}]})
        run = rt.work_graph.active(sid)
        assert run['status'] == 'drafting'
        assert [n['stages']['produce']['status'] for n in run['nodes']] == ['pending', 'pending']
        assert run['reviewHistory']
        assert any(c['status'] == 'superseded' for c in rt.work_graph.checks.records(run['runId']))
        assert rt.work_graph.artifacts.get(run['runId'], old_aid)[1]
    asyncio.run(run())


def test_V12_contradiction_with_valid_sources_remains_revise(tmp_path):
    def script(kind, text):
        return 'Recommendation violates owner scope\nVERDICT: revise' if kind == 'review' else ok_script(kind, text)
    _, rt, _, _, sid = build(tmp_path, script)
    async def run():
        _, result = await setup(rt, sid)
        checked = await start(rt, sid, result)
        assert checked['checks'][0]['status'] == 'revise'
        assert checked['nodes'][0]['stages']['produce'] == 'revise'
    asyncio.run(run())


@pytest.mark.parametrize('raw', [
    'VERDICT: ok\ntrailing content', 'VERDICT: ok\nVERDICT: ok',
    '```json\n{"coverage":[]}\n```\nVERDICT: ok',
    '```json\n{"coverage":[{"id":"C1","status":"pass","evidence":""}]}\n```\nVERDICT: ok',
])
def test_V13_invalid_checker_contract_never_passes(raw):
    assert checks.parse_report(raw, {'C1': 'criterion'})[0] == 'error'


def test_V13_no_reviewer_of_reviewer(tmp_path):
    _, rt, model, _, sid = build(tmp_path)
    async def run():
        _, result = await setup(rt, sid)
        await start(rt, sid, result)
        assert [k for k, _ in model.prompts] == ['produce', 'review']
    asyncio.run(run())


@pytest.mark.parametrize('flow', ['plan', 'research', 'design'])
def test_V14_autopilot_cannot_execute_artifact_only_run(tmp_path, flow):
    _, rt, _, executor, sid = build(tmp_path)
    wg.set_autopilot(rt, sid, True)
    async def run():
        await tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Prepare the requested artifact', 'flow': flow})
        await tool(rt, sid, 'work_graph', {'action': 'add', 'nodes': [PLAN | {'dependsOn': []}]})
        await tool(rt, sid, 'work_run', {'phase': 'discover'})
        await raw_tool(rt, sid, 'work_graph', {'action': 'verify'})
        for name, args in [('work_graph', {'action': 'submit'}), ('work_run', {'phase': 'execute'}), ('work_ship', {})]:
            with pytest.raises(ValueError, match='WORK_REQUIREMENTS_ONLY'):
                await raw_tool(rt, sid, name, args)
        assert not any('git checkout' in a.get('command', '') for n, a in executor.calls)
    asyncio.run(run())


def test_snapshot_detects_real_source_and_allows_cache(tmp_path):
    subprocess.run(['git', 'init', '-q'], cwd=tmp_path, check=True)
    (tmp_path / 'src.py').write_text('before', encoding='utf-8')
    subprocess.run(['git', 'add', 'src.py'], cwd=tmp_path, check=True)
    subprocess.run(['git', '-c', 'user.name=fixture', '-c', 'user.email=fixture@localhost', 'commit', '-qm', 'fixture'], cwd=tmp_path, check=True)
    def actual():
        return json.loads(subprocess.check_output([sys.executable, '-c', checks.SNAPSHOT_SCRIPT], cwd=tmp_path))
    before = actual()
    (tmp_path / '.pytest_cache').mkdir()
    (tmp_path / '.pytest_cache/run').write_text('cache')
    assert actual() == before
    (tmp_path / 'src.py').write_text('after')
    assert actual() != before
    (tmp_path / 'new.py').write_text('new source')
    assert actual() != before


def test_actual_test_command_required_no_prose_pass(tmp_path):
    _, rt, _, _, sid = build(tmp_path)
    graph = wg.service(rt)
    assert not checks.test_proof(graph, sid, ['pytest -q'])
    rt.store.emit(sid, 'tool_end', {'name': 'terminal_exec', 'args': {'command': 'pytest -q'},
                                 'result': {'exit_code': 1, 'content': 'FAILED'}})
    assert not checks.test_proof(graph, sid, ['pytest -q'])
    rt.store.emit(sid, 'tool_end', {'name': 'terminal_exec', 'args': {'command': 'pytest -q'},
                                 'result': {'exit_code': 0, 'content': '1 passed'}})
    assert checks.test_proof(graph, sid, ['pytest -q'])
    assert not checks.test_proof(graph, sid, ['pytest -q tests/missing.py'])


def test_newer_finding_invalidates_previous_pass(tmp_path):
    state = {'verdict': 'ok'}
    def script(kind, text):
        return 'Actual finding\nVERDICT: ' + state['verdict'] if kind == 'review' else ok_script(kind, text)
    _, rt, _, _, sid = build(tmp_path, script)
    async def run():
        _, result = await setup(rt, sid)
        await start(rt, sid, result)
        state['verdict'] = 'revise'
        checked = await start(rt, sid, result)
        assert checked['nodes'][0]['stages']['produce'] == 'revise'
        current = rt.work_graph.active(sid)
        assert not rt.work_graph.checks.valid(current, current['nodes'][0], 'produce')
    asyncio.run(run())


def test_V04_failed_testing_returns_main_findings_without_acceptance(tmp_path):
    def script(kind, text):
        return 'Command failed: vitest ChatHeader.test.tsx\nVERDICT: revise' if kind == 'review' else ok_script(kind, text)
    _, rt, _, executor, sid = build(tmp_path, script)
    original = executor.execute
    async def failed(name, args, *rest, **kwargs):
        if name == 'terminal_exec' and args['command'] == 'vitest ChatHeader.test.tsx':
            return {'exit_code': 1, 'is_error': True, 'content': 'FAILED export keeps Unicode'}
        return await original(name, args, *rest, **kwargs)
    executor.execute = failed
    async def run():
        node = {'id': 'B1', 'kind': 'build', 'title': 'Export', 'goal': 'Fix export to preserve the original characters',
                'tests': ['vitest ChatHeader.test.tsx'], 'acceptance': ['Preserve Unicode']}
        graph = wg.service(rt)
        run = graph.create(rt.store.get(sid), {'goal': 'Fix export', 'flow': 'fix', 'nodes': [node]})
        run['status'] = 'approved'
        graph.save(run)
        result = await raw_tool(rt, sid, 'work_run', {'phase': 'execute'})
        checked = await start(rt, sid, result)
        assert checked['checks'][0]['status'] == 'revise'
        assert 'Command failed' in checked['checks'][0]['findings']
        assert checked['nodes'][0]['stages']['execute'] != 'accepted'
    asyncio.run(run())


def test_V05_terminal_source_side_effect_supersedes_test_check(tmp_path):
    _, rt, _, executor, sid = build(tmp_path)
    original = executor.execute
    changed = {'source': False}
    async def side_effect(name, args, *rest, **kwargs):
        if name == 'terminal_exec' and args['command'] == 'vitest ChatHeader.test.tsx':
            changed['source'] = True
        if name == 'terminal_exec' and args['command'] == checks.SNAPSHOT_COMMAND:
            return {'exit_code': 0, 'content': json.dumps({'schema':'work-code/1', 'hash': ('b' if changed['source'] else 'a')*64, 'head':'fixture'})}
        return await original(name, args, *rest, **kwargs)
    executor.execute = side_effect
    async def run():
        graph = wg.service(rt)
        node = {'id':'B1','kind':'build','title':'Export','goal':'Fix the exporter Unicode behavior',
                'tests':['vitest ChatHeader.test.tsx'],'acceptance':['Preserve Unicode']}
        run = graph.create(rt.store.get(sid), {'goal':'Fix export','flow':'fix','nodes':[node]})
        run['status']='approved'
        graph.save(run)
        result = await raw_tool(rt,sid,'work_run',{'phase':'execute'})
        checked = await start(rt,sid,result)
        assert checked['checks'][0]['status']=='superseded'
        assert checked['nodes'][0]['stages']['execute']=='needs_checks'
    asyncio.run(run())


def test_snapshot_detects_ignored_source_change(tmp_path):
    subprocess.run(['git','init','-q'],cwd=tmp_path,check=True)
    (tmp_path/'.gitignore').write_text('private.py\n')
    subprocess.run(['git','add','.gitignore'],cwd=tmp_path,check=True)
    subprocess.run(['git','-c','user.name=fixture','-c','user.email=fixture@localhost','commit','-qm','fixture'],cwd=tmp_path,check=True)
    def actual():
        return json.loads(subprocess.check_output([sys.executable,'-c',checks.SNAPSHOT_SCRIPT],cwd=tmp_path))
    (tmp_path/'private.py').write_text('first')
    before=actual()
    (tmp_path/'private.py').write_text('second')
    assert before != actual()


def test_V14_plain_plan_request_cannot_be_relabelled_mixed(tmp_path):
    _,rt,_,_,sid=build(tmp_path)
    rt.store.save(sid,[{'role':'user','content':'Please create a plan for CSV export'}])
    graph=wg.service(rt)
    run=graph.create(rt.store.get(sid),{'goal':'Build a CSV exporter','flow':'mixed'})
    assert not run['executionRequested']


def test_restart_keeps_artifacts_and_flags_running_check_as_error(tmp_path):
    store,rt,_,_,sid=build(tmp_path)
    async def run():
        rid,result=await setup(rt,sid)
        await start(rt,sid,result)
        doc=rt.work_graph.checks.records(rid)[0]
        doc['status']='running'
        rt.work_graph.checks.save(doc)
        restored=wg.WorkGraph(rt)
        assert restored.checks.records(rid)[0]['status']=='error'
        aid=result['outputs'][0]['artifact']['artifactId']
        assert restored.artifacts.get(rid,aid)[1]
        assert not restored.checks.valid(restored.get(rid),restored.get(rid)['nodes'][0],'produce')
    asyncio.run(run())


def test_closed_run_cannot_start_checks(tmp_path):
    _,rt,_,_,sid=build(tmp_path)
    async def run():
        _,result=await setup(rt,sid)
        await raw_tool(rt,sid,'work_graph',{'action':'cancel'})
        with pytest.raises(ValueError,match='WORK_RUN_CLOSED'):
            await start(rt,sid,result)
    asyncio.run(run())


def test_api_owned_artifact_paging_and_cross_session_rejection(tmp_path):
    from test_plan_workflow_routes import check_api
    _,rt,_,_,sid=build(tmp_path)
    async def seed():
        return await setup(rt,sid)
    rid,result=asyncio.run(seed())
    other=rt.create({})['id']
    aid=result['outputs'][0]['artifact']['artifactId']
    async def callback(request):
        suffix=f'/work/runs/{rid}/artifacts/{aid}?limit=12'
        status,body=await request('GET',f'/sessions/{sid}'+suffix)
        assert status==200 and len(body['content'])==12 and body['nextOffset']==12
        status,body=await request('GET',f'/sessions/{other}'+suffix)
        assert status==400 and 'another session' in body['error']
    check_api(rt,callback)


def test_lookup_research_uses_evidence_without_extra_reviewer():
    value = policy.derive({'goal': 'Look up one format'}, RESEARCH | {'taskKind': 'lookup'}, 'produce')
    assert value['artifactKind'] == 'knowledge' and not value['required']


def test_create_cannot_cancel_active_check(tmp_path):
    _, rt, _, _, sid = build(tmp_path)
    graph = wg.service(rt)
    run = graph.create(rt.store.get(sid), {'goal': 'Research export formats', 'flow': 'research'})
    async def active():
        lock = graph.locks.setdefault(run['runId'], asyncio.Lock())
        async with lock:
            with pytest.raises(ValueError, match='WORK_RUN_BUSY'):
                graph.create(rt.store.get(sid), {'goal': 'Research another format'})
        assert graph.get(run['runId'])['status'] != 'cancelled'
    asyncio.run(active())


def test_failed_snapshot_write_does_not_leave_verifying_run(tmp_path):
    _, rt, _, executor, sid = build(tmp_path)
    async def run():
        await tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Prepare export plan', 'flow': 'plan', 'nodes': [PLAN | {'dependsOn': []}]})
        await tool(rt, sid, 'work_run', {'phase': 'discover'})
        original = executor.execute
        async def failed(name, args, *rest, **kwargs):
            if name == 'file_write':
                return {'is_error': True, 'error': 'fixture disk full'}
            return await original(name, args, *rest, **kwargs)
        executor.execute = failed
        graph = rt.work_graph
        before = len(graph.artifacts.db.execute('SELECT * FROM work_artifacts').fetchall())
        with pytest.raises(ValueError, match='WORK_ARTIFACT_WRITE_FAILED'):
            await raw_tool(rt, sid, 'work_graph', {'action': 'verify'})
        assert graph.active(sid)['status'] == 'needs_revision'
        assert len(graph.artifacts.db.execute('SELECT * FROM work_artifacts').fetchall()) == before
    asyncio.run(run())


def test_owner_decision_change_blocks_old_execution_approval(tmp_path):
    _, rt, _, _, sid = build(tmp_path)
    async def run():
        await tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Fix CSV exporter', 'flow': 'fix', 'nodes': [PLAN | {'dependsOn': []}]})
        await tool(rt, sid, 'work_run', {'phase': 'discover'})
        await raw_tool(rt, sid, 'work_graph', {'action': 'verify'})
        graph = rt.work_graph
        state = graph.active(sid)
        state['status'] = 'approved'
        state['interviews'] = [{'answers': [{'question': 'format', 'answer': 'CSV only'}]}]
        graph.save(state)
        with pytest.raises(ValueError, match='WORK_NOT_VERIFIED'):
            await raw_tool(rt, sid, 'work_run', {'phase': 'execute'})
    asyncio.run(run())


def test_bundled_planning_skill_authoring_contract():
    from pathlib import Path
    import re
    root = Path(__file__).resolve().parents[2]
    text = (root / 'src/agentbox/vendor/hermes/skills/software-development/work-graph-planning/SKILL.md').read_text(encoding='utf-8')
    description = re.search(r'^description: "(.*)"$', text, re.M).group(1)
    assert len(description) <= 60 and description.endswith('.')
    headings = ['When to Use', 'Prerequisites', 'How to Run', 'Quick Reference', 'Procedure', 'Pitfalls', 'Verification']
    assert [text.index('## ' + h) for h in headings] == sorted(text.index('## ' + h) for h in headings)


def test_execution_only_run_can_still_request_existing_autopilot_approval(tmp_path):
    _, rt, _, _, sid = build(tmp_path)
    wg.set_autopilot(rt, sid, True)
    async def run():
        await raw_tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Fix Unicode export', 'flow': 'fix',
            'nodes': [{'id': 'B1', 'kind': 'build', 'title': 'Export', 'goal': 'Fix the Unicode export behavior only',
                       'tests': ['python -m pytest -q'], 'acceptance': ['Keep original Unicode']} ]})
        result = await raw_tool(rt, sid, 'work_graph', {'action': 'submit'})
        assert result['status'] == 'approved'
    asyncio.run(run())


def test_failed_replacement_cannot_check_old_artifact(tmp_path):
    _, rt, _, executor, sid = build(tmp_path)
    async def run():
        _, result = await setup(rt, sid)
        graph = rt.work_graph
        current = graph.active(sid)
        current['nodes'][0]['stages']['produce']['status'] = 'revise'
        graph.save(current)
        original = executor.execute
        async def failed(name, args, *rest, **kwargs):
            if name == 'file_write':
                return {'is_error': True, 'error': 'disk full'}
            return await original(name, args, *rest, **kwargs)
        executor.execute = failed
        await raw_tool(rt, sid, 'work_run', {'phase': 'discover'})
        assert not graph.active(sid)['nodes'][0]['stages']['produce'].get('artifact')
        with pytest.raises(ValueError, match='WORK_CHECK_NOT_READY'):
            await start(rt, sid, result)
    asyncio.run(run())


@pytest.mark.parametrize('change', ['title', 'remove'])
def test_graph_change_clears_old_verified_status_and_preserves_history(tmp_path, change):
    _, rt, _, _, sid = build(tmp_path)
    async def run():
        await tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Prepare CSV export plan', 'flow': 'plan', 'nodes': [PLAN | {'dependsOn': []}]})
        await tool(rt, sid, 'work_run', {'phase': 'discover'})
        await raw_tool(rt, sid, 'work_graph', {'action': 'verify'})
        args = {'action': 'remove', 'nodeIds': ['P1']} if change == 'remove' else {'action': 'update', 'nodes': [{'id': 'P1', 'title': 'New title'}]}
        await raw_tool(rt, sid, 'work_graph', args)
        current = rt.work_graph.active(sid)
        assert current['status'] == 'drafting'
        assert current['review']['status'] is None and current['reviewHistory']
    asyncio.run(run())
