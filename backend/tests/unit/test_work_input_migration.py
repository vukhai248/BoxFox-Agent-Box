"""Historical passes stay readable but must not open current dependency gates."""
import asyncio

from agentbox.agent_core import work_graph, work_policy
from test_work_graph import build, EXPLORE
from test_work_checks import RESEARCH, start


def test_old_input_contract_waits_for_recheck_while_independent_branch_proceeds(tmp_path):
    async def check():
        store, rt, _, _, sid = build(tmp_path)
        graph = work_graph.service(rt)
        run = graph.create(store.get(sid), {'goal': 'Research only', 'flow': 'research', 'nodes': [
            RESEARCH, EXPLORE | {'id': 'E2', 'dependsOn': ['R1']}, EXPLORE | {'id': 'E3'}]})
        draft = await graph.run(store.get(sid), {'phase': 'discover', 'nodeIds': ['R1']})
        first = await start(rt, sid, draft, invocationId='historical')
        old = first['checks'][0]
        old.pop('inputVersion')
        graph.checks.save(old)
        before = len(store.children_of(sid))
        result = await graph.run(store.get(sid), {'phase': 'discover', 'nodeIds': ['E2', 'E3']})
        assert len(store.children_of(sid)) == before + 1  # E3, no E2
        assert [n['stages']['produce'] for n in result['nodes']] == ['needs_checks', 'pending', 'accepted']
        current = graph.get(run['runId'])
        assert current['nodes'][0]['stages']['produce']['artifact'] == draft['outputs'][0]['artifact']
        assert graph.checks.records(run['runId'])[0] == old
        renewed = await start(rt, sid, draft, invocationId='new-input-contract')
        assert renewed['checks'][0]['checkId'] != old['checkId']
        final = await graph.run(store.get(sid), {'phase': 'discover', 'nodeIds': ['E2']})
        assert final['nodes'][1]['stages']['produce'] == 'accepted'
        assert len(store.children_of(sid)) == before + 3  # E3 + fresh check + E2
    asyncio.run(check())


def test_old_whole_review_approval_is_retained_in_history_not_current_permission(tmp_path):
    async def check():
        store, rt, _, _, sid = build(tmp_path)
        graph = work_graph.service(rt)
        run = graph.create(store.get(sid), {'goal': 'Research only', 'flow': 'research', 'nodes': [EXPLORE]})
        await graph.run(store.get(sid), {'phase': 'discover'})
        run = graph.get(run['runId'])
        old_binding = work_policy.digest({'goal': run['goal'], 'interviews': run.get('interviews'),
            'nodes': [{k:v for k,v in n.items() if k != 'stages'} for n in run['nodes']],
            'artifacts': [n['stages']['produce'].get('artifact', {}).get('artifactId') for n in run['nodes'] if 'produce' in n['stages']]})
        old_review = {'binding': old_binding, 'status': 'ok', 'rounds': [{'verdict': 'ok'}]}
        run.update(status='approved', review=old_review, approval={'status': 'approved', 'by': 'owner'})
        graph.refresh(run)
        assert run['status'] == 'drafting' and run['approval'] is None
        assert run['reviewHistory'][-1] == old_review
        assert run['review']['status'] is None
    asyncio.run(check())
