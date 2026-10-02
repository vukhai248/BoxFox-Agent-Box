"""A cached check still needs intact, exactly bound registry inputs and manifest."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_policy
from test_work_graph import build
from test_work_checks import setup, start
from test_work_input_manifest import large_fixture, ManifestModel


@pytest.mark.parametrize('fault', ['body', 'partial', 'deleted', 'binding'])
@pytest.mark.parametrize('invocation', ['same-cached-input', 'new-cached-input'])
def test_cached_green_cannot_bypass_changed_supporting_input(tmp_path, fault, invocation):
    async def check():
        store, rt, _, _, sid = build(tmp_path)
        rid, _ = await setup(rt, sid)
        g = rt.work_graph;run = g.get(rid);node = run['nodes'][0];state = node['stages']['produce']
        lookup = await g.artifacts.put(run, node['id'], 'knowledge', 'Saved source note', {'purpose': 'knowledge'}, True)
        primary = await g.artifacts.put(run, node['id'], 'produce', state['output'],
            state['artifact']['binding'] | {'lookupArtifactIds': [lookup['artifactId']]}, True)
        state['artifact'] = primary;g.save(run);draft = g.result(run)
        first = await start(rt, sid, draft, invocationId='same-cached-input')
        assert first['checks'][0]['status'] == 'pass'
        history = g.checks.records(rid)
        before = len(store.children_of(sid))
        with store.db:
            if fault == 'body':
                store.db.execute('UPDATE work_artifacts SET content=? WHERE id=?', ('corrupt', lookup['artifactId']))
            elif fault == 'deleted':
                store.db.execute('DELETE FROM work_artifacts WHERE id=?', (lookup['artifactId'],))
            else:
                changed = lookup | ({'status': 'partial'} if fault == 'partial' else {'binding': {'purpose': 'produce'}})
                store.db.execute('UPDATE work_artifacts SET metadata=? WHERE id=?', (json.dumps(changed), lookup['artifactId']))
        assert not g.checks.valid(g.get(rid), g.get(rid)['nodes'][0], 'produce')
        with pytest.raises(ValueError, match='WORK_ARTIFACT_(CORRUPT|UNKNOWN|INPUT_PARTIAL|INPUT_KIND)'):
            await start(rt, sid, draft, invocationId=invocation)
        assert len(store.children_of(sid)) == before
        assert g.checks.records(rid) == history
    asyncio.run(check())


def test_cached_green_cannot_bypass_corrupt_manifest_and_history_is_preserved(tmp_path):
    async def check():
        store, rt, sid, g, run, node, _, _, primary = await large_fixture(tmp_path)
        policy = work_policy.derive(run, node, 'produce', 'Research a sourced fact')
        primary = await g.artifacts.put(run, node['id'], 'produce', 'Research this fact',
                                       primary['binding'] | {'policyHash': policy['hash']}, True)
        node['stages']['produce'].update(status='needs_checks', attempts=1, artifact=primary, policy=policy,
            output='Research this fact', rounds=[{'attempt': 1}])
        g.save(run);rt.client = ManifestModel()
        args = {'action': 'start', 'runId': run['runId'], 'nodeId': node['id'], 'artifactId': primary['artifactId'],
                'checkIds': ['evidence'], 'invocationId': 'manifest-cached-check'}
        first = await g.checks.tool(store.get(sid), args)
        record = first['checks'][0]
        assert record['status'] == 'pass' and record['inputManifest']
        before = len(store.children_of(sid));history = g.checks.records(run['runId'])
        with store.db:
            store.db.execute('UPDATE work_artifacts SET content=? WHERE id=?', ('tampered', record['inputManifest']['artifactId']))
        current = g.get(run['runId'])
        assert not g.checks.valid(current, current['nodes'][2], 'produce')
        with pytest.raises(ValueError, match='WORK_ARTIFACT_CORRUPT'):
            await g.checks.tool(store.get(sid), args)
        assert len(store.children_of(sid)) == before and g.checks.records(run['runId']) == history
    asyncio.run(check())
