"""A3.1 shared check path/input identity; no automatic handoff or live model."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_graph, work_checks
from test_work_graph import build, raw_tool
from test_work_checks import setup, start


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


def test_new_invocation_on_same_green_input_reuses_check_and_persists_alias(tmp_path):
    async def run_test():
        store,rt,model,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid)
        first=await start(rt,sid,draft,invocationId='manual-first')
        count=len(store.children_of(sid))
        second=await start(rt,sid,draft,invocationId='handoff-replay')
        assert second['checks'][0]['checkId']==first['checks'][0]['checkId']
        assert len(store.children_of(sid))==count
        assert len(rt.work_graph.checks.records(rid))==1
        assert first['checks'][0]['workKey']
        rt.work_graph=work_graph.WorkGraph(rt)
        third=await start(rt,sid,draft,invocationId='handoff-replay')
        assert third['checks']==second['checks']
        assert len(store.children_of(sid))==count
        assert not rt.work_graph.live
    asyncio.run(run_test())


def test_overlapping_check_lists_share_only_the_same_check_input(tmp_path):
    async def run_test():
        store,rt,_,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid,goal='Research medical record export safety')
        one=await start(rt,sid,draft,checkIds=['evidence'],invocationId='one-check')
        both=await start(rt,sid,draft,checkIds=['evidence','critique'],invocationId='both-checks')
        assert both['checks'][0]['checkId']==one['checks'][0]['checkId']
        assert [c['kind'] for c in rt.work_graph.checks.records(rid)]==['evidence','critique']
        assert len(store.children_of(sid))==3  # producer + two different checks
        with pytest.raises(ValueError,match='INVOCATION_CONFLICT'):
            await start(rt,sid,draft,checkIds=['evidence','critique'],invocationId='one-check')
    asyncio.run(run_test())


def test_shared_locked_path_preserves_existing_scheduler_budget_and_manual_reuses_result(tmp_path):
    async def run_test():
        store,rt,_,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid)
        graph=rt.work_graph
        args={'nodeId':'R1','stage':'produce','artifactId':draft['outputs'][0]['artifact']['artifactId'],
              'invocationId':'assigned-core'}
        with pytest.raises(ValueError,match='LOCK_REQUIRED'):
            await graph.checks.start_locked(store.get(sid),graph.get(rid),args)
        budget=[2]
        graph.child_budget[rid]=budget
        async with graph.locks[rid]:
            run=graph.get(rid);graph.live[rid]=run
            try:
                first=await graph.checks.start_locked(store.get(sid),run,args)
            finally:
                graph.live.pop(rid,None)
        assert graph.child_budget[rid] is budget and budget==[1]
        graph.child_budget.pop(rid)
        count=len(store.children_of(sid))
        manual=await start(rt,sid,draft,invocationId='manual-after-core')
        assert manual['checks'][0]['checkId']==first['checks'][0]['checkId']
        assert len(store.children_of(sid))==count
        assert not graph.live and not graph.child_budget
    asyncio.run(run_test())


def test_changed_node_and_artifact_do_not_reuse_old_green_check(tmp_path):
    async def run_test():
        store,rt,_,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid)
        first=await start(rt,sid,draft,invocationId='old-input')
        graph=rt.work_graph;node=graph.get(rid)['nodes'][0]
        graph.graph(store.get(sid),{'action':'update','nodes':[{
            **{k:v for k,v in node.items() if k!='stages'},
            'goal':'Compare export columns and Unicode contracts using src/a.py'}]})
        newer=await raw_tool(rt,sid,'work_run',{'phase':'discover'})
        second=await start(rt,sid,newer,invocationId='new-input')
        assert second['checks'][0]['workKey']!=first['checks'][0]['workKey']
        assert second['checks'][0]['checkId']!=first['checks'][0]['checkId']
        assert len(store.children_of(sid))==4
    asyncio.run(run_test())


def test_explicit_recheck_is_recorded_bounded_and_does_not_hide_newer_finding(tmp_path):
    async def run_test():
        store,rt,_,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid)
        first=await start(rt,sid,draft,invocationId='first')
        for invocation in ['explicit-2','explicit-3']:
            extra=await start(rt,sid,draft,invocationId=invocation,recheck=True)
            assert extra['checks'][0]['requestedRecheck'] is True
            assert extra['checks'][0]['workKey']==first['checks'][0]['workKey']
            assert extra['checks'][0]['checkId']!=first['checks'][0]['checkId']
            count=len(store.children_of(sid))
            replay=await start(rt,sid,draft,invocationId=invocation,recheck=True)
            assert replay['checks']==extra['checks'] and len(store.children_of(sid))==count
        with pytest.raises(ValueError,match='WORK_CHECK_EXHAUSTED'):
            await start(rt,sid,draft,invocationId='explicit-4',recheck=True)
        assert len(rt.work_graph.checks.records(rid))==3
        assert len(store.children_of(sid))==4
        with pytest.raises(ValueError,match='INVOCATION_CONFLICT'):
            await start(rt,sid,draft,invocationId='first',recheck=True)
    asyncio.run(run_test())


def test_legacy_pass_without_workkey_or_alias_keeps_receipt_readable(tmp_path):
    async def run_test():
        store,rt,_,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid)
        first=await start(rt,sid,draft,invocationId='legacy-first')
        doc=first['checks'][0]
        doc.pop('workKey');doc.pop('requestedRecheck')
        rt.work_graph.checks.save(doc)
        with store.db:
            store.db.execute('DELETE FROM work_check_invocations')
        rt.work_graph=work_graph.WorkGraph(rt)
        replay=await start(rt,sid,draft,invocationId='legacy-first')
        new_id=await start(rt,sid,draft,invocationId='new-invocation')
        assert replay['checks'][0]['checkId']==new_id['checks'][0]['checkId']==doc['checkId']
        assert len(store.children_of(sid))==2
    asyncio.run(run_test())


@pytest.mark.parametrize('fault',['content','metadata','policy'])
def test_registry_or_policy_corruption_is_rejected_before_spawning_checker(tmp_path,fault):
    async def run_test():
        store,rt,_,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid);graph=rt.work_graph
        run=graph.get(rid);state=run['nodes'][0]['stages']['produce']
        if fault=='content':
            with store.db:
                store.db.execute('UPDATE work_artifacts SET content=? WHERE id=?',
                                 ('Changed after finalization',state['artifact']['artifactId']))
        elif fault=='metadata':
            state['artifact']['chars']+=1;graph.save(run)
        else:
            state['policy']['required'][0]['criterion']='Changed criterion without updating policy hash'
            graph.save(run)
        with pytest.raises(ValueError,match='WORK_CHECK_STALE|WORK_ARTIFACT_CORRUPT'):
            await start(rt,sid,draft,invocationId='corrupted-input')
        assert len(store.children_of(sid))==1 and not graph.checks.records(rid)
        assert not graph.live and not graph.child_budget
    asyncio.run(run_test())


@pytest.mark.parametrize('state',['paused','cancelled','shipped','rejected'])
def test_shared_core_does_not_bypass_run_state_gate(tmp_path,state):
    async def run_test():
        store,rt,_,_,sid=build(tmp_path)
        rid,draft=await setup(rt,sid);graph=rt.work_graph
        async with graph.locks[rid]:
            run=graph.get(rid);run['status']=state;graph.live[rid]=run
            try:
                with pytest.raises(ValueError,match='WORK_RUN_CLOSED'):
                    await graph.checks.start_locked(store.get(sid),run,{'nodeId':'R1'})
            finally:
                graph.live.pop(rid,None)
        assert len(store.children_of(sid))==1
    asyncio.run(run_test())


def test_cached_green_on_changed_code_cannot_admit_or_become_current_proof(tmp_path):
    async def run_test():
        store,rt,_,executor,sid=build(tmp_path)
        original=executor.execute
        changed=False
        async def observed_snapshot(name,args,*rest,**kwargs):
            if name=='terminal_exec' and args['command']==work_checks.SNAPSHOT_COMMAND:
                return {'exit_code':0,'content':json.dumps({'schema':'work-code/1',
                    'hash':('b' if changed else 'a')*64,'head':'fixture'})}
            return await original(name,args,*rest,**kwargs)
        executor.execute=observed_snapshot
        graph=work_graph.service(rt)
        run=graph.create(store.get(sid),{'goal':'Fix export','flow':'fix','nodes':[{
            'id':'B1','kind':'build','title':'Export','goal':'Fix the exporter Unicode behavior',
            'tests':['vitest ChatHeader.test.tsx'],'acceptance':['Preserve Unicode']}]})
        run['status']='approved';graph.save(run)
        draft=await raw_tool(rt,sid,'work_run',{'phase':'execute'})
        first=await start(rt,sid,draft,invocationId='first-tests')
        assert first['checks'][0]['status']=='pass'
        count=len(store.children_of(sid));changed=True
        for invocation in ['first-tests','new-id-same-code-artifact']:
            with pytest.raises(ValueError,match='WORK_CHECK_STALE'):
                await start(rt,sid,draft,invocationId=invocation)
        assert len(store.children_of(sid))==count
    asyncio.run(run_test())
