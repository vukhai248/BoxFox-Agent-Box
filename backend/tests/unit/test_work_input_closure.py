"""A3.3b: exact input closure, reviewed targets and independently opened evidence."""
import asyncio
import json
import re

import pytest

from agentbox.agent_core import work_graph, work_checks
from test_work_graph import build, EXPLORE, answer


async def fixture(tmp_path, large=False):
    store, rt, model, _, sid = build(tmp_path)
    graph = work_graph.service(rt)
    run = graph.create(store.get(sid), {'goal': 'Research bounded facts only', 'flow': 'research', 'nodes': [
        EXPLORE | {'id': 'R0'}, EXPLORE | {'id': 'R1', 'dependsOn': ['R0']},
        EXPLORE | {'id': 'E2', 'kind': 'research', 'dependsOn': ['R1']}, EXPLORE | {'id': 'OTHER'}]})
    metas = []
    for node in run['nodes']:
        meta = await graph.artifacts.put(run, node['id'], 'produce',
            ('Original input\n' * 1800 if large and node['id'] == 'R0' else node['id'] + ' bound content'),
            graph.checks.binding(run, node, 'produce'), True)
        node['stages']['produce'].update(status='accepted', artifact=meta)
        metas.append(meta)
    target = run['nodes'][2]
    lookup = await graph.artifacts.put(run, 'E2', 'knowledge', 'Helper source quote',
        graph.checks.binding(run, target, 'produce') | {'purpose': 'knowledge', 'verification': 'unreviewed'}, True)
    primary = await graph.artifacts.put(run, 'E2', 'produce', 'Current deliverable',
        graph.checks.binding(run, target, 'produce') | {'lookupArtifactIds': [lookup['artifactId']]}, True)
    return store, rt, model, sid, graph, run, target, metas, lookup, primary


def test_closure_pins_transitive_versions_excludes_unrelated_and_keeps_targets_first(tmp_path):
    async def check():
        _, _, _, _, graph, run, target, metas, lookup, primary = await fixture(tmp_path)
        # A newer registry version is not the version this deliverable used.
        newer = await graph.artifacts.put(run, 'R1', 'produce', 'New unbound source', metas[1]['binding'], True)
        run['nodes'][1]['stages']['produce']['artifact'] = newer
        closure = graph.artifacts.input_closure(run['runId'], [primary])
        assert [m['artifactId'] for m in closure] == [m['artifactId'] for m in (primary, lookup, metas[1], metas[0])]
        assert metas[3]['artifactId'] not in {m['artifactId'] for m in closure}
        assert newer['artifactId'] not in {m['artifactId'] for m in closure}
        assert graph.artifacts.input_closure(run['runId'], [primary, metas[1]])[:2] == [primary, metas[1]]
    asyncio.run(check())


def test_checker_receives_and_reads_input_closure_with_explicit_run_and_target_ids(tmp_path):
    async def check():
        store, _, model, sid, graph, run, node, metas, lookup, primary = await fixture(tmp_path, large=True)
        result = await graph.checks.judge(store.get(sid), run, node, 'produce',
            {'id': 'evidence', 'executorRole': 'research-review'}, [primary], {'C1': 'Check original sources'}, {'checkId': 'closure-check'})
        assert result['status'] == 'pass', result
        child = store.get(result['childId'])
        refs = child['config']['workBinding']['artifactIds']
        assert len(refs) == 4 and metas[3]['artifactId'] not in refs
        assert all(graph.artifacts.covered('closure-check', graph.artifacts.get(run['runId'], aid)[0], child['id']) for aid in refs)
        prompt = next(t for k, t in model.prompts if k == 'review')
        packet = json.JSONDecoder().raw_decode(prompt[re.search(r'\{"snapshots":', prompt).start():])[0]
        assert packet['runId'] == run['runId']
        assert packet['reviewTargetArtifactIds'] == [primary['artifactId']]
        assert 'not an exhaustive log of another child' in prompt
        assert 'does not prove the final producer did not run it' in prompt
        assert set(packet['inputArtifactIds']) == {lookup['artifactId'], metas[0]['artifactId'], metas[1]['artifactId']}
        assert 'Original input' not in prompt and 'bound content' not in prompt
        with pytest.raises(PermissionError, match='WORK_ARTIFACT_SCOPE'):
            graph.artifacts.read(child, {'artifactId': metas[3]['artifactId']})
    asyncio.run(check())


@pytest.mark.parametrize('fault', ['foreign', 'partial', 'wrong_lookup_kind', 'wrong_dependency', 'corrupt', 'cycle', 'wrong_target'])
def test_invalid_bound_inputs_fail_before_spawning_checker(tmp_path, fault):
    async def check():
        store, _, _, sid, graph, run, node, metas, lookup, primary = await fixture(tmp_path)
        binding = dict(primary['binding'])
        if fault == 'foreign':
            other = graph.create(store.get(sid), {'goal': 'Another run', 'flow': 'research'})
            foreign = await graph.artifacts.put(other, 'X', 'produce', 'Foreign', {}, True)
            binding['lookupArtifactIds'] = [foreign['artifactId']]
        elif fault == 'partial':
            partial = await graph.artifacts.put(run, 'E2', 'knowledge', 'Partial', {'purpose': 'knowledge'}, False)
            binding['lookupArtifactIds'] = [partial['artifactId']]
        elif fault == 'wrong_lookup_kind':
            binding['lookupArtifactIds'] = [metas[0]['artifactId']]
        elif fault == 'wrong_dependency':
            binding['dependencies'] = {'R1': {'artifact': metas[0]['artifactId']}}
        elif fault == 'corrupt':
            with graph.db:
                graph.db.execute('UPDATE work_artifacts SET content=? WHERE id=?', ('tampered', lookup['artifactId']))
        elif fault == 'cycle':
            # Deliberate registry fault; immutable production writers never self-reference.
            altered = lookup | {'binding': lookup['binding'] | {'lookupArtifactIds': [lookup['artifactId']]}}
            with graph.db:
                graph.db.execute('UPDATE work_artifacts SET metadata=? WHERE id=?', (json.dumps(altered), lookup['artifactId']))
        if fault not in ('corrupt', 'cycle', 'wrong_target'):
            primary = await graph.artifacts.put(run, 'E2', 'produce', 'Current', binding, True)
        if fault == 'wrong_target':
            primary = primary | {'version': 999}
        before = len(store.children_of(sid))
        result = await graph.checks.judge(store.get(sid), run, node, 'produce',
            {'id': 'evidence', 'executorRole': 'research-review'}, [primary], {'C1': 'Check sources'}, {'checkId': 'bad-input'})
        assert result['status'] == 'unverified' and result['error'].startswith('WORK_ARTIFACT_'), result
        assert result['finishedAt'] and result['attempts'] == []
        assert len(store.children_of(sid)) == before
    asyncio.run(check())


def test_workspace_copy_of_supporting_artifact_cannot_count_as_original_source(tmp_path):
    async def check():
        store, _, _, sid, graph, run, _, metas, _, primary = await fixture(tmp_path)
        child = graph.rt.create({}, parent_id=sid, role='research-review')
        binding = {'runId': run['runId'], 'artifactIds': [primary['artifactId'], metas[1]['artifactId']]}
        store.update_config(child['id'], child['config'] | {'workBinding': binding})
        store.emit(child['id'], 'tool_end', {'name': 'file_read', 'args': {'path': '/workspace/' + metas[1]['path']},
                                            'result': {'content': 'Copied artifact text'}})
        assert work_checks.good_reads(graph, child['id']) == []
    asyncio.run(check())


def test_skip_input_range_cannot_pass_even_when_target_and_source_read(tmp_path):
    async def check():
        store, _, model, sid, graph, run, node, metas, _, primary = await fixture(tmp_path)
        original = model.complete
        async def omit(messages, *args, **kwargs):
            result = await original(messages, *args, **kwargs)
            message = result['choices'][0]['message']
            calls = message.get('tool_calls', [])
            message['tool_calls'] = [c for c in calls if json.loads(c['function']['arguments']).get('artifactId') != metas[0]['artifactId']]
            if calls and not message['tool_calls']:
                return answer('```json\n{"coverage":[{"id":"C1","status":"pass","target":"artifact","evidence":"claimed"}]}\n```\nVERDICT: ok')
            return result
        model.complete = omit
        result = await graph.checks.judge(store.get(sid), run, node, 'produce',
            {'id': 'evidence', 'executorRole': 'research-review'}, [primary], {'C1': 'Check sources'}, {'checkId': 'skip-input'})
        assert result['status'] == 'unverified' and 'ranges' in result['error'], result
    asyncio.run(check())


def test_own_plan_input_is_pinned_and_wrong_node_is_rejected(tmp_path):
    async def check():
        _, _, _, _, graph, run, _, metas, _, _ = await fixture(tmp_path)
        execution = await graph.artifacts.put(run, 'E2', 'execute', 'Implementation receipt',
                                             {'ownPlan': metas[2]['artifactId']}, True)
        assert graph.artifacts.input_closure(run['runId'], [execution]) == [execution, metas[2], metas[1], metas[0]]
        wrong = await graph.artifacts.put(run, 'E2', 'execute', 'Implementation receipt',
                                         {'ownPlan': metas[1]['artifactId']}, True)
        with pytest.raises(ValueError, match='WORK_ARTIFACT_INPUT_BINDING'):
            graph.artifacts.input_closure(run['runId'], [wrong])
    asyncio.run(check())


def test_oversized_reference_packet_checkpoints_before_runtime_cuts_json(tmp_path):
    async def check():
        store, _, _, sid, graph, run, node, _, _, primary = await fixture(tmp_path)
        # Deterministic limit probe, not a claim that a normal four-ref graph is large.
        fake_inputs = [primary | {'artifactId': 'large-input-' + str(i), 'path': 'x' * 1000} for i in range(20)]
        graph.artifacts.input_closure = lambda rid, targets: [primary] + fake_inputs
        result = await graph.checks.judge(store.get(sid), run, node, 'produce',
            {'id': 'evidence', 'executorRole': 'research-review'}, [primary], {'C1': 'Check sources'}, {'checkId': 'large-input'})
        assert result['status'] == 'unverified' and result['error'].startswith('WORK_CHECK_INPUT_CONTEXT_TOO_LARGE')
        assert not store.children_of(sid)
    asyncio.run(check())


def test_historical_green_stays_readable_but_is_not_current_input_verification(tmp_path):
    from test_work_checks import setup, start

    async def check():
        store, rt, _, _, sid = build(tmp_path)
        rid, draft = await setup(rt, sid)
        first = await start(rt, sid, draft, invocationId='old-input-contract')
        old = first['checks'][0]
        old.pop('inputVersion')
        rt.work_graph.checks.save(old)
        run = rt.work_graph.get(rid)
        assert not rt.work_graph.checks.valid(run, run['nodes'][0], 'produce')
        assert rt.work_graph.checks.records(rid)[0]['status'] == 'pass'
        with pytest.raises(ValueError, match='WORK_CHECK_RECEIPT_STALE'):
            await start(rt, sid, draft, invocationId='old-input-contract')
        renewed = await start(rt, sid, draft, invocationId='current-input-contract')
        assert renewed['checks'][0]['inputVersion'] == work_checks.INPUTS_VERSION
        assert renewed['checks'][0]['checkId'] != old['checkId']
        assert len(store.children_of(sid)) == 3
        assert rt.work_graph.checks.records(rid)[0] == old
    asyncio.run(check())
