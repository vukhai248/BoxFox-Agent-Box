"""A3.2 explicit handoff, no main relay and shared manual/controller admission."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_graph, work_feedback
from test_work_graph import build, raw_tool, ok_script, EXPLORE
from test_work_checks import RESEARCH


def assign(graph, store, sid, rid, **extra):
    return graph.graph(store.get(sid), {'action':'assign_handoff','runId':rid,
        'revision':graph.current(rid)['revision'],'nodeId':'R1','stage':'produce',
        'predicate':'artifact_finalized','target':{'kind':'check','checkIds':['evidence']},
        'invocationId':'assignment', **extra})


def setup(tmp_path, script=ok_script, nodes=None, goal='Research exporter formats', flow='research'):
    store,rt,model,executor,sid=build(tmp_path,script)
    graph=work_graph.service(rt)
    run=graph.create(store.get(sid),{'goal':goal,'flow':flow,'nodes':nodes or [RESEARCH]})
    return store,rt,model,executor,sid,graph,run['runId']


async def drain(graph):
    for _ in range(8):
        graph.handoffs.dispatch()
        tasks=list(graph.continuations.tasks.values())
        if not tasks:
            return
        results=await asyncio.wait_for(asyncio.gather(*tasks,return_exceptions=True),10)
        assert all(not isinstance(r,BaseException) or isinstance(r,asyncio.CancelledError) for r in results), results
        await asyncio.sleep(0)
    raise AssertionError('controller failed to quiesce')


def test_assigned_research_check_does_not_wait_for_busy_main_or_repeat_on_replay(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path)
        grant=assign(graph,store,sid,rid)
        result=await graph.run(store.get(sid),{'phase':'discover'})
        await drain(graph)
        state=graph.get(rid)['nodes'][0]['stages']['produce']
        assert state['status']=='accepted'
        assert [k for k,_ in model.prompts]==['produce','review']  # no main LLM
        assert len(store.children_of(sid))==2
        actions=graph.handoffs.actions(rid)
        assert len(actions)==1 and actions[0]['status']=='completed'
        notices=[e['data'] for e in store.events(sid) if e['type']=='work_notice' and e['data'].get('workKey')==actions[0]['id']]
        assert len([n for n in notices if n['event']=='handoff_pending'])==1
        artifact=result['nodes'][0]['artifacts']['produce']
        assert notices[0]['artifact']['contentHash']==artifact['contentHash']
        for _ in range(3):
            graph.save(graph.get(rid),'replayed_event')
            await work_feedback.pump(rt)
        await drain(graph)
        assert len(store.children_of(sid))==2
        # Grant scope survives unrelated global revision changes.
        assert graph.handoffs.valid(graph.get(rid),grant)
        assert not graph.continuations.children and not graph.continuations.admissions
    asyncio.run(check())


def test_build_to_assigned_testing_before_tests_pass_no_implicit_debug_or_review(tmp_path):
    async def check():
        node={'id':'B1','kind':'build','title':'Exporter','goal':'Fix exporter Unicode serialization',
              'acceptance':['Preserve Unicode'],'tests':['vitest ChatHeader.test.tsx']}
        store,rt,model,executor,sid,graph,rid=setup(tmp_path,nodes=[node],goal='Fix exporter Unicode',flow='fix')
        run=graph.get(rid);run['status']='approved';graph.save(run)
        assign(graph,store,sid,rid,nodeId='B1',stage='execute',predicate='code_snapshot_ready',target={'kind':'check','checkIds':['tests']})
        await graph.run(store.get(sid),{'phase':'execute'})
        await drain(graph)
        state=graph.get(rid)['nodes'][0]['stages']['execute']
        assert state['status']=='accepted'
        assert [r['role'] for r in store.children_of(sid)]==['build','testing']
        assert [k for k,_ in model.prompts]==['produce','review']
        assert any(n=='terminal_exec' and a['command']=='vitest ChatHeader.test.tsx' for n,a in executor.calls)
        checker=graph.checks.records(rid)[0]
        assert checker['binding']['codeSnapshot']==state['artifact']['binding']['codeSnapshot']
        assert graph.handoffs.actions(rid)[0]['status']=='completed'
    asyncio.run(check())


def test_accepted_source_dispatches_only_explicit_consumer_from_artifact_refs(tmp_path):
    async def check():
        source=EXPLORE | {'id':'R1'}
        dest=EXPLORE | {'id':'E2','dependsOn':['R1'],'goal':'Locate the exporter after inspecting R1 evidence'}
        store,rt,model,_,sid,graph,rid=setup(tmp_path,nodes=[source,dest])
        assign(graph,store,sid,rid,predicate='required_checks_passed',target={'kind':'node','nodeId':'E2','stage':'produce'})
        await graph.run(store.get(sid),{'phase':'discover','nodeIds':['R1']})
        await drain(graph)
        run=graph.get(rid)
        assert run['nodes'][1]['stages']['produce']['status']=='accepted'
        assert len(model.prompts)==2 and all(k=='produce' for k,_ in model.prompts)
        ref=run['nodes'][0]['stages']['produce']['artifact']['artifactId']
        assert ref in model.prompts[1][1]
        assert '## Findings\n- src/a.py:1 fixture' not in model.prompts[1][1]
    asyncio.run(check())


def test_failed_check_requires_main_decision_does_not_auto_retry_or_debug(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path,lambda k,t:'Unsupported recommendation.\nVERDICT: revise' if k=='review' else ok_script(k,t))
        assign(graph,store,sid,rid)
        await graph.run(store.get(sid),{'phase':'discover'})
        await drain(graph)
        assert graph.handoffs.actions(rid)[0]['status']=='blocked'
        assert graph.get(rid)['nodes'][0]['stages']['produce']['status']=='revise'
        for _ in range(3):
            await work_feedback.pump(rt)
        await drain(graph)
        assert len(model.prompts)==2
        assert any(e['type']=='work_notice' and e['data'].get('type')=='main_decision_required' for e in store.events(sid))
    asyncio.run(check())


def test_no_assignment_preserves_manual_path_and_lookup_not_forced_to_review(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path)
        result=await graph.run(store.get(sid),{'phase':'discover'})
        await drain(graph)
        assert result['outputs'][0]['status']=='needs_checks' and len(model.prompts)==1
        assert not graph.handoffs.actions(rid)
    asyncio.run(check())


@pytest.mark.parametrize('mutation',['goal','node','revoke','disabled','partial','hash','policy'])
def test_stale_unavailable_or_partial_handoff_never_admits_checker(tmp_path,mutation):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path)
        await graph.run(store.get(sid),{'phase':'discover'})
        # Hold the run so the assignment queues but cannot start yet.
        lock=graph.locks[rid]
        async with lock:
            assignment=assign(graph,store,sid,rid)
            run=graph.get(rid)
            if mutation=='goal': run['goal']='Changed owner intent entirely'
            elif mutation=='node': run['nodes'][0]['goal']='Changed assignment evidence requirements'
            elif mutation=='partial': run['nodes'][0]['stages']['produce']['artifact']['status']='partial'
            elif mutation=='hash': run['nodes'][0]['stages']['produce']['artifact']['contentHash']='b'*64
            elif mutation=='policy': run['nodes'][0]['stages']['produce']['policy']['hash']='b'*64
            elif mutation=='disabled':
                config=store.get(sid)['config']
                for role in config['subagents']:
                    if role['id']=='research-review': role['enabled']=False
                store.update_config(sid,config)
            elif mutation=='revoke':
                graph.graph(store.get(sid),{'action':'revoke_handoff','runId':rid,'transitionId':assignment['transitionId'],'revision':assignment['revision'],'invocationId':'revoke'})
            if mutation not in ('disabled','revoke'):graph.save(run,'changed_input')
        await drain(graph)
        assert len(model.prompts)==1
        assert all(a['status']=='blocked' for a in graph.handoffs.actions(rid))
        assert not graph.continuations.children
    asyncio.run(check())


def test_manual_check_during_auto_check_joins_same_input_and_child(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path)
        await graph.run(store.get(sid),{'phase':'discover'})
        original=model.complete;started=asyncio.Event();release=asyncio.Event()
        async def gated(*args,**kwargs):
            result=await original(*args,**kwargs)
            text=next(m.get('content','') for m in args[0] if m.get('role')=='user')
            if text.startswith('Independent review'):
                started.set();await release.wait()
            return result
        model.complete=gated
        assign(graph,store,sid,rid)
        await asyncio.wait_for(started.wait(),5)
        meta=graph.current(rid)['nodes'][0]['stages']['produce']['artifact']
        result=await raw_tool(rt,sid,'work_check',{'action':'start','nodeId':'R1','artifactId':meta['artifactId'],'invocationId':'manual-same'})
        assert result['joined'] and result['checks'][0]['status']=='running'
        release.set();await drain(graph)
        replay=await raw_tool(rt,sid,'work_check',{'action':'start','nodeId':'R1','artifactId':meta['artifactId'],'invocationId':'manual-same'})
        assert replay['checks'][0]['checkId']==result['checks'][0]['checkId']
        assert replay['checks'][0]['status']=='pass' and len(store.children_of(sid))==2
    asyncio.run(check())


def test_run_owned_new_checker_survives_root_turn_cleanup_then_root_stop_cancels(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path)
        await graph.run(store.get(sid),{'phase':'discover'})
        started=asyncio.Event();release=asyncio.Event();original=model.complete
        async def blocked(*args,**kwargs):
            result=await original(*args,**kwargs)
            if next(m.get('content','') for m in args[0] if m.get('role')=='user').startswith('Independent review'):
                started.set();await release.wait()
            return result
        model.complete=blocked;rt.active_turn[sid]=17
        assign(graph,store,sid,rid)
        await asyncio.wait_for(started.wait(),5)
        child=store.children_of(sid)[-1]['session_id']
        assert graph.continuations.owns_child(child)
        assert store.children_of(sid)[-1]['parent_turn']==0
        await rt.reap_children(sid,turn=17)
        assert not rt.tasks[child].done()
        await rt.stop(sid)
        assert rt.tasks[child].done()
        assert not graph.continuations.children and not graph.continuations.admissions
        assert graph.handoffs.actions(rid)[0]['status']=='interrupted'
        assert not rt.parent_running.get(sid) and not rt.child_slot_holders
    asyncio.run(check())


@pytest.mark.parametrize('status,expected',[('pending','pending'),('claimed','pending'),('admitted','interrupted'),('completed','completed')])
def test_restart_receipts_never_replay_an_admitted_action(tmp_path,status,expected):
    async def check():
        store,rt,_,_,sid,graph,rid=setup(tmp_path)
        await graph.run(store.get(sid),{'phase':'discover'})
        async with graph.locks[rid]:
            assign(graph,store,sid,rid)
            action=graph.handoffs.actions(rid)[0]
            with graph.db:
                graph.db.execute('UPDATE work_handoff_actions SET status=? WHERE id=?',(status,action['id']))
            # Suppress current worker: emulate a stopped process before releasing lock.
            task=graph.continuations.tasks.get(action['id'])
            if task:task.cancel();await asyncio.gather(task,return_exceptions=True)
        rt.work_graph=None;reopened=work_graph.service(rt)
        assert reopened.handoffs.actions(rid)[0]['status']==expected
        if expected=='pending':
            await drain(reopened)
            assert reopened.handoffs.actions(rid)[0]['status']=='completed'
        else:
            await drain(reopened)
            assert len(store.children_of(sid))==1
    asyncio.run(check())


def test_assignment_guards_root_scope_idempotency_and_artifact_only_execution(tmp_path):
    store,rt,_,_,sid,graph,rid=setup(tmp_path,nodes=[RESEARCH,{'id':'B1','kind':'build','title':'Build','goal':'Implement exporter after R1 report','dependsOn':['R1'],'tests':['vitest ChatHeader.test.tsx']}])
    # Synchronous guard test does not dispatch unfinished artifacts.
    original=assign(graph,store,sid,rid)
    with pytest.raises(ValueError,match='WORK_HANDOFF_EXISTS'):
        assign(graph,store,sid,rid,invocationId='duplicate')
    with pytest.raises(ValueError,match='WORK_HANDOFF_INVOCATION_CONFLICT'):
        assign(graph,store,sid,rid,predicate='code_snapshot_ready')
    with pytest.raises(ValueError,match='WORK_REQUIREMENTS_ONLY'):
        assign(graph,store,sid,rid,invocationId='build',predicate='required_checks_passed',target={'kind':'node','nodeId':'B1','stage':'execute'})
    child=rt.create({},parent_id=sid,role='research')
    with pytest.raises(PermissionError,match='WORK_ROOT_ONLY'):
        graph.graph(child,{'action':'assign_handoff','runId':rid})
    assert original['status']=='active' and not graph.handoffs.actions(rid)


@pytest.mark.parametrize('change',['revoke','disable','ceiling'])
def test_slot_wait_rechecks_permission_and_current_parent_budget(tmp_path,change):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path)
        await graph.run(store.get(sid),{'phase':'discover'})
        original=rt.acquire_child_slot;queued=asyncio.Event();release=asyncio.Event()
        async def gated(owner):
            queued.set();await release.wait();await original(owner)
        rt.acquire_child_slot=gated
        assignment=assign(graph,store,sid,rid)
        await asyncio.wait_for(queued.wait(),5)
        if change=='revoke':
            graph.graph(store.get(sid),{'action':'revoke_handoff','runId':rid,'transitionId':assignment['transitionId'],
                'revision':assignment['revision'],'invocationId':'revoke-queued'})
        else:
            config=store.get(sid)['config']
            if change=='disable':
                for role in config['subagents']:
                    if role['id']=='research-review':role['enabled']=False
            else:config.update(maxSteps=7,deadlineSeconds=120)
            store.update_config(sid,config)
        release.set();await drain(graph)
        if change=='ceiling':
            checker=store.get(store.children_of(sid)[-1]['session_id'])
            assert checker['config']['maxSteps']==7 and checker['config']['deadlineSeconds']==120
            assert graph.handoffs.actions(rid)[0]['status']=='completed'
        else:
            assert len(store.children_of(sid))==1 and len(model.prompts)==1
            assert graph.handoffs.actions(rid)[0]['status']=='blocked'
        assert not rt.parent_running.get(sid) and not graph.continuations.children
    asyncio.run(check())


def test_fake_controller_flag_cannot_create_child_or_escape_root_cleanup(tmp_path):
    async def check():
        store,rt,_,_,sid,graph,rid=setup(tmp_path)
        with pytest.raises(PermissionError,match='WORK_CONTROLLER_RIGHTS'):
            await rt.delegate(store.get(sid),{'role':'research','goal':'Read CSV scope evidence'},
                work={'runId':rid,'nodeId':'R1','stage':'produce','purpose':'produce','controllerAction':'invented'})
        assert not store.children_of(sid)
        assert not graph.continuations.children
    asyncio.run(check())


def test_manual_then_auto_alias_reuses_one_passed_checker(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path)
        draft=await graph.run(store.get(sid),{'phase':'discover'})
        meta=draft['nodes'][0]['artifacts']['produce']
        manual=await raw_tool(rt,sid,'work_check',{'action':'start','nodeId':'R1','artifactId':meta['artifactId'],'invocationId':'manual-first'})
        assign(graph,store,sid,rid)
        await drain(graph)
        assert len(store.children_of(sid))==2 and len(model.prompts)==2
        assert len(graph.checks.records(rid))==1
        assert graph.handoffs.actions(rid)[0]['status']=='completed'
        assert manual['checks'][0]['checkId']==graph.checks.records(rid)[0]['checkId']
    asyncio.run(check())


def test_manual_red_then_auto_assignment_reports_existing_finding_without_retry(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid=setup(tmp_path,lambda k,t:'Unsupported evidence.\nVERDICT: revise' if k=='review' else ok_script(k,t))
        draft=await graph.run(store.get(sid),{'phase':'discover'})
        meta=draft['nodes'][0]['artifacts']['produce']
        manual=await raw_tool(rt,sid,'work_check',{'action':'start','nodeId':'R1','artifactId':meta['artifactId'],'invocationId':'manual-red'})
        assert manual['checks'][0]['status']=='revise'
        assign(graph,store,sid,rid)
        await drain(graph)
        assert len(store.children_of(sid))==2 and len(model.prompts)==2
        assert len(graph.checks.records(rid))==1 and graph.handoffs.actions(rid)[0]['status']=='blocked'
    asyncio.run(check())


def test_dependency_accepted_label_without_required_checks_cannot_handoff(tmp_path):
    async def check():
        dest=EXPLORE | {'id':'E2','dependsOn':['R1']}
        store,rt,model,_,sid,graph,rid=setup(tmp_path,nodes=[RESEARCH,dest])
        await graph.run(store.get(sid),{'phase':'discover','nodeIds':['R1']})
        run=graph.get(rid);run['nodes'][0]['stages']['produce']['status']='accepted';graph.save(run,'fake_label')
        assign(graph,store,sid,rid,predicate='required_checks_passed',target={'kind':'node','nodeId':'E2','stage':'produce'})
        await drain(graph)
        assert len(model.prompts)==1 and not graph.handoffs.actions(rid)
        assert graph.get(rid)['nodes'][1]['stages']['produce']['status']=='pending'
    asyncio.run(check())


def test_branch_waiting_for_user_does_not_block_independent_assigned_check(tmp_path):
    from test_work_feedback_w7 import QUESTIONS
    from test_work_continuations_w7 import call
    async def check():
        first=RESEARCH | {'goal':'Read scope then ask the owner before choosing data formats'}
        second=RESEARCH | {'id':'R2','goal':'Compare the independent exporter alternatives using source facts'}
        store,rt,model,_,sid,graph,rid=setup(tmp_path,nodes=[first,second])
        original=model.complete
        async def waiting(*args,**kwargs):
            messages=args[0]
            prompt=next(m.get('content','') for m in messages if m['role']=='user')
            if 'node R1 (research, produce)' in prompt and any(m.get('name')=='file_read' for m in messages):
                return call('work_report',{'action':'needs_user','checkpoint':'Read source; need owner intent.',
                    'questions':QUESTIONS,'decisionKeys':['users','deploy']})
            return await original(*args,**kwargs)
        model.complete=waiting
        assign(graph,store,sid,rid,nodeId='R2')
        await graph.run(store.get(sid),{'phase':'discover'})
        await drain(graph)
        nodes=graph.get(rid)['nodes']
        assert nodes[0]['stages']['produce']['status']=='needs_user'
        assert nodes[1]['stages']['produce']['status']=='accepted'
        assert len(store.children_of(sid))==3
        assert graph.handoffs.actions(rid)[0]['status']=='completed'
    asyncio.run(check())
