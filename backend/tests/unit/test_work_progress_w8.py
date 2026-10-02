"""Observable progress is admission evidence, never a semantic acceptance oracle."""
import asyncio
import json
import sqlite3

import pytest

from agentbox.agent_core import work_graph, work_feedback, work_checks
from agentbox.agent_core.work_progress import Progress
from test_work_graph import build


def setup(tmp_path):
    store, rt, model, executor, sid = build(tmp_path)
    graph = work_graph.service(rt)
    run = graph.create(store.get(sid), {'goal': 'Read source, report facts only', 'flow': 'research',
        'nodes': [{'id': 'E1', 'kind': 'explore', 'title': 'First source', 'taskKind': 'lookup', 'goal': 'Read source and report observed facts'},
                  {'id': 'E2', 'kind': 'explore', 'title': 'Second source', 'taskKind': 'lookup', 'goal': 'Read another source and report observed facts'}]})
    work = {'runId': run['runId'], 'nodeId': 'E1', 'stage': 'produce', 'purpose': 'produce', 'artifactIds': []}
    return store, rt, graph, run, sid, work


async def admission(rt, graph, sid, work, *, cid=None, body=None, status='partial', output='Unfinished', error=None):
    pid = await graph.progress.reserve(sid, work, cid)
    if not cid:
        cid = rt.create({'skills': []}, parent_id=sid, role='explore',
                        parent_tools=rt.store.get(sid)['config']['tools'])['id']
    seq = rt.store.db.execute('SELECT COALESCE(MAX(seq),0) FROM events WHERE session_id=?', (cid,)).fetchone()[0]
    binding = work | {'admissionSeq': seq, 'progressAdmissionId': pid}
    cfg = rt.store.get(cid)['config']; cfg['workBinding'] = binding; rt.store.update_config(cid, cfg)
    graph.progress.attach(pid, sid, binding, cid)
    rt.store.emit(cid, 'user', {'text': 'Synthetic admission', 'turn': seq+1})
    if body is not None:
        rt.store.emit(cid, 'tool_end', {'name': 'file_read', 'args': {'path': 'src/a.py'},
                                      'result': {'content': body}})
    if error:
        rt.store.emit(cid, 'tool_end', {'name': 'web_fetch', 'args': {'url': 'https://example.invalid'},
                                      'result': {'is_error': True, 'errorCode': error, 'error': 'failed'}})
    rt.store.emit(cid, 'turn_end', {'stepsUsed': 1, 'outputTokens': 2, 'turn': seq+1})
    rt.store.emit(cid, 'finish', {'status': 'completed', 'partial': status == 'partial', 'turn': seq+1})
    return cid, graph.progress.finish(pid, {'status': status, 'reason': error}, output)


def test_three_unproductive_new_children_stop_without_main_relay_then_keep_other_branch_running(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        children = []
        for _ in range(3):
            cid, doc = await admission(rt, graph, sid, work, error='PROVIDER_OUTPUT_TRUNCATED')
            children.append(cid)
        assert len(set(children)) == 3 and doc['blocked'] and doc['streak'] == 3
        assert all(r['errors'][0]['code'] == 'PROVIDER_OUTPUT_TRUNCATED' for r in graph.progress.records())
        with pytest.raises(ValueError, match='WORK_NO_PROGRESS'):
            await graph.progress.reserve(sid, work | {'attempt': 99, 'invocationId': 'new'})
        graph.decisions.reconcile()
        stops = [d for d in graph.decisions.records() if d['kind'] == 'progress']
        assert len(stops) == 1 and stops[0]['status'] == 'pending'
        assert graph.decisions.valid(stops[0]) is True
        assert not rt.tasks and not model_prompts(rt)
        other = await graph.progress.reserve(sid, work | {'nodeId': 'E2'})
        assert graph.progress.get(other)['status'] == 'reserved'
        graph.progress.finish(other)  # no model/user event, not a consumed attempt
    asyncio.run(run_test())


def model_prompts(rt):
    return rt.client.prompts


def test_repeated_successful_source_only_counts_once_and_new_body_is_observed_progress(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        _, first = await admission(rt, graph, sid, work, body='original')
        assert first['progressed'] and first['streak'] == 0
        _, second = await admission(rt, graph, sid, work, body='original')
        assert not second['progressed'] and second['streak'] == 1
        _, third = await admission(rt, graph, sid, work, body='new real source')
        assert third['newProofs'] == 1 and third['streak'] == 0
        assert all(r['outcome']['status'] == 'partial' for r in graph.progress.records())
    asyncio.run(run_test())


def test_same_child_retains_lifetime_usage_and_replay_completion_is_idempotent(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        cid, first = await admission(rt, graph, sid, work)
        _, second = await admission(rt, graph, sid, work, cid=cid)
        assert second['outcome']['lifetimeStepsUsed'] == 2
        assert second['outcome']['lifetimeOutputTokens'] == 4
        assert graph.progress.finish(second['admissionId'], {'status': 'completed'}, 'fake replacement') == second
        assert first['streak'] == 1 and second['streak'] == 2
    asyncio.run(run_test())


def test_answer_and_scope_change_reset_once_but_reused_input_does_not(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        for _ in range(3):
            await admission(rt, graph, sid, work)
        current = graph.get(run['runId']); current['nodes'][0]['goal'] = 'Investigate a genuinely different question'
        graph.save(current)
        _, fresh = await admission(rt, graph, sid, work)
        assert fresh['novelInput'] and fresh['streak'] == 1
        # Returning to an already admitted input is not a reset.
        current['nodes'][0]['goal'] = run['nodes'][0]['goal']; graph.save(current)
        _, old = await admission(rt, graph, sid, work)
        assert not old['novelInput'] and old['streak'] == 2
    asyncio.run(run_test())


def test_unrelated_answer_and_global_revision_cannot_reset_streak(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        _, one = await admission(rt, graph, sid, work)
        child = rt.create({'skills': []}, parent_id=sid, role='explore', parent_tools=store.get(sid)['config']['tools'])
        cfg = child['config']; cfg['workBinding'] = work | {'nodeId': 'E2'}; store.update_config(child['id'], cfg)
        req = await graph.feedback.report(store.get(child['id']), {'action': 'needs_user',
            'checkpoint': 'Separate branch intent', 'questions': [{'id': 'format', 'question': 'Which format?',
                'options': ['CSV', 'JSON']}]}, 'question')
        card = graph.feedback.open_interview(store.get(sid), {'workRequestId': req['requestId'], 'revision': 1}, 'card')
        rt.resolve_decision(sid, card['decisionId'], 'decide')
        graph.save(graph.get(run['runId']))
        _, two = await admission(rt, graph, sid, work)
        assert not two['novelInput'] and two['streak'] == 2
    asyncio.run(run_test())


def test_new_user_action_answer_is_fresh_and_old_main_stop_is_superseded(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        for _ in range(3):
            cid, stop = await admission(rt, graph, sid, work)
        graph.decisions.reconcile(); decision = graph.decisions.records()[0]
        req = await graph.feedback.report(store.get(cid), {'action': 'needs_user', 'checkpoint': 'Saved progress',
            'questions': [{'id': 'intent', 'question': 'Which direction?', 'options': ['NN', 'RNN']}]}, 'intent')
        card = graph.feedback.open_interview(store.get(sid), {'workRequestId': req['requestId'], 'revision': 1}, 'card')
        rt.resolve_decision(sid, card['decisionId'], 'decide')
        assert graph.decisions.valid(decision) is False
        _, resumed = await admission(rt, graph, sid, work, cid=cid)
        assert resumed['novelInput'] and resumed['streak'] == 1
    asyncio.run(run_test())


def test_question_yield_is_not_a_failed_admission_and_does_not_reset_old_errors(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        await admission(rt, graph, sid, work)
        _, question = await admission(rt, graph, sid, work, status='needs_user', output='Question')
        assert question['streak'] == 1 and not question['blocked']
        _, failure = await admission(rt, graph, sid, work)
        assert failure['streak'] == 2
    asyncio.run(run_test())


def test_checkpoint_index_version_invocation_and_failed_source_never_fake_progress(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        cid, one = await admission(rt, graph, sid, work)
        checkpoint = await graph.artifacts.put(run, 'E1', 'produce', 'new prose', {'checkpoint': True}, False, cid)
        index = await graph.artifacts.put(run, 'E1', 'produce', 'new index', {'purpose': 'check_inputs'}, True, cid)
        changed = work | {'artifactIds': [checkpoint['artifactId'], index['artifactId']], 'attempt': 77}
        cid2, two = await admission(rt, graph, sid, changed, error='HTTP_503')
        assert not two['novelInput'] and not two['progressed'] and two['streak'] == 2
        pid = await graph.progress.reserve(sid, changed, cid2)
        cfg = store.get(cid2)['config']; seq=store.db.execute('SELECT MAX(seq) FROM events WHERE session_id=?',(cid2,)).fetchone()[0]
        bound = changed | {'admissionSeq':seq}; cfg['workBinding']=bound;store.update_config(cid2,cfg)
        graph.progress.attach(pid,sid,bound,cid2);store.emit(cid2,'user',{'text':'synthetic'})
        store.emit(cid2,'tool_end',{'name':'file_read','args':{'path':checkpoint['path']},'result':{'content':'new prose'}})
        store.emit(cid2,'tool_end',{'name':'work_artifact_read','args':{'artifactId':index['artifactId']},'result': index | {'content':'new index'}})
        store.emit(cid2,'tool_end',{'name':'web_fetch','args':{'url':'https://example.invalid'},'result':{'status':503,'content':'error body'}})
        third=graph.progress.finish(pid,{'status':'partial'})
        assert third['blocked'] and third['newProofs']==0
    asyncio.run(run_test())


def test_helpers_and_checker_kinds_have_separate_scopes_and_unique_active_admissions(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        a=await graph.progress.reserve(sid,work | {'purpose':'knowledge','helperRole':'research','lookupQuestion':'Question A'})
        b=await graph.progress.reserve(sid,work | {'purpose':'knowledge','helperRole':'research','lookupQuestion':'Question B'})
        c=await graph.progress.reserve(sid,work | {'purpose':'review','checkKind':'evidence'})
        d=await graph.progress.reserve(sid,work | {'purpose':'review','checkKind':'critique'})
        assert len({graph.progress.get(i)['scope'] for i in (a,b,c,d)})==4
        with pytest.raises(ValueError,match='WORK_PROGRESS_BUSY'):
            await graph.progress.reserve(sid,work | {'purpose':'review','checkKind':'critique','checkId':'new id'})
        row=store.db.execute('SELECT * FROM work_progress WHERE id=?',(a,)).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            with store.db: store.db.execute('INSERT INTO work_progress VALUES(?,?,?,?,?,?)',('new',sid,run['runId'],row['scope'],'admitted',row['doc']))
    asyncio.run(run_test())


@pytest.mark.parametrize('started', [False, True])
def test_actual_sqlite_restart_never_replays_uncertain_admission(tmp_path, started):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        pid=await graph.progress.reserve(sid,work)
        child=rt.create({'skills':[]},parent_id=sid,role='explore',parent_tools=store.get(sid)['config']['tools'])
        graph.progress.attach(pid,sid,work | {'admissionSeq':0},child['id'])
        if started: store.emit(child['id'],'user',{'text':'started'})
        store.db.close()
        from agentbox.memory.session_store import SessionStore
        rt.store=SessionStore(tmp_path/'sessions.db')
        rt.work_graph=work_graph.WorkGraph(rt); newer=rt.work_graph
        recovered=newer.progress.get(pid)
        assert recovered['status']==('interrupted' if started else 'aborted')
        assert not rt.tasks and not rt.client.prompts
        if started:
            with pytest.raises(ValueError,match='WORK_NO_PROGRESS'): await newer.progress.reserve(sid,work)
            newer.decisions.reconcile()
            assert len([d for d in newer.decisions.records() if d['kind']=='progress'])==1
        else:
            another=await newer.progress.reserve(sid,work)
            assert newer.progress.get(another)['streakBefore']==0
    asyncio.run(run_test())


def test_stop_and_late_finish_do_not_recreate_decisions_or_drop_receipts(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        for _ in range(3): cid, doc = await admission(rt, graph, sid, work)
        graph.decisions.reconcile()
        await rt.stop(sid)
        graph.progress.finish(doc['admissionId'], {'status':'completed'}, 'late')
        graph.decisions.reconcile()
        assert graph.progress.blocked()==[]
        assert len(graph.progress.records())==3
        assert all(r['status']=='cancelled' for r in graph.progress.records())
        assert all(d['status']=='cancelled' for d in graph.decisions.records())
        assert not rt.client.prompts
    asyncio.run(run_test())


def test_artifact_version_and_git_head_do_not_reset_but_new_content_and_code_do(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        source={'schema':'work-code/1','hash':'a'*64,'head':'first','criticalChanges':False}
        meta=await graph.artifacts.put(run,'E2','produce','facts',{'codeSnapshot':source},True,'other')
        inputs=work | {'artifactIds':[meta['artifactId']]}
        await admission(rt,graph,sid,inputs)
        meta2=await graph.artifacts.put(run,'E2','produce','facts',{'codeSnapshot':source | {'head':'commit','criticalChanges':True}},True,'other-new')
        _, two=await admission(rt,graph,sid,work | {'artifactIds':[meta2['artifactId']]})
        assert not two['novelInput'] and two['streak']==2
        meta3=await graph.artifacts.put(run,'E2','produce','facts',{'codeSnapshot':source | {'hash':'b'*64}},True,'other')
        _, three=await admission(rt,graph,sid,work | {'artifactIds':[meta3['artifactId']]})
        assert three['novelInput'] and three['streak']==1
    asyncio.run(run_test())


def test_cosmetic_title_and_arbitrary_terminal_output_do_not_grant_progress(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        cid, _ = await admission(rt, graph, sid, work)
        current=graph.get(run['runId']); current['nodes'][0]['title']='Cosmetic rename'; graph.save(current)
        pid=await graph.progress.reserve(sid,work,cid)
        doc=graph.progress.get(pid); assert not doc['novelInput']
        seq=store.db.execute('SELECT MAX(seq) FROM events WHERE session_id=?',(cid,)).fetchone()[0]
        graph.progress.attach(pid,sid,work | {'admissionSeq':seq},cid)
        store.emit(cid,'user',{'text':'synthetic'})
        store.emit(cid,'tool_end',{'name':'terminal_exec','args':{'command':'echo random-123'},
                                 'result':{'content':'random-123','exit_code':0}})
        result=graph.progress.finish(pid,{'status':'completed'},'changed prose')
        assert result['streak']==2 and not result['progressed']
    asyncio.run(run_test())


def test_real_runtime_admissions_count_proofs_stop_stage_and_do_not_call_main_or_debug(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        node=run['nodes'][0]
        for _ in range(4): await graph.run_stage(store.get(sid),run,node,'produce',10)
        history=graph.progress.records(run['runId'])
        assert [r['streak'] for r in history]==[0,1,2,3]
        assert node['stages']['produce']['status']=='failed'
        assert node['stages']['produce']['error'].startswith('WORK_NO_PROGRESS')
        assert node['stages']['produce']['artifact']['status']=='partial'
        count=len(rt.client.prompts)
        await graph.run_stage(store.get(sid),run,node,'produce',10)
        assert len(rt.client.prompts)==count and len(graph.progress.records())==4
        assert all(kind=='produce' for kind,_ in rt.client.prompts)
        assert not graph.checks.records(run['runId']) and len(graph.progress.blocked())==1
        await graph.run_stage(store.get(sid),run,run['nodes'][1],'produce',10)
        assert run['nodes'][1]['stages']['produce']['status']=='accepted'
    asyncio.run(run_test())


def test_owner_limits_lowered_during_slot_wait_apply_to_manual_admission(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        acquire=rt.acquire_child_slot
        async def lower(owner):
            cfg=store.get(owner)['config'];cfg.update(maxSteps=6,deadlineSeconds=90);store.update_config(owner,cfg)
            return await acquire(owner)
        rt.acquire_child_slot=lower
        await graph.run_stage(store.get(sid),run,run['nodes'][0],'produce',3)
        child=store.get(store.children_of(sid)[0]['session_id'])
        assert child['config']['maxSteps']==6 and child['config']['deadlineSeconds']==90
        assert child['config']['workBudget']['effectiveMaxSteps']==6
        assert graph.progress.records()[0]['outcome']['lifetimeStepsUsed']>0
    asyncio.run(run_test())


def test_code_snapshot_wait_revalidates_pause_and_stale_assignment(tmp_path, monkeypatch):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        async def pause(*args):
            current=graph.get(run['runId']);current['status']='paused';graph.save(current)
            return {'hash':'a'*64}
        monkeypatch.setattr(work_checks,'snapshot',pause)
        with pytest.raises(ValueError,match='WORK_PROGRESS_PAUSED'):
            await graph.progress.reserve(sid,work | {'stage':'execute'})
        assert graph.progress.records()==[]
        current=graph.get(run['runId']);current['status']='discovering';graph.save(current)
        async def scope_change(*args):
            current=graph.get(run['runId']);current['nodes'][0]['goal']='Changed assignment during code snapshot';graph.save(current)
            return {'hash':'a'*64}
        monkeypatch.setattr(work_checks,'snapshot',scope_change)
        with pytest.raises(ValueError,match='WORK_PROGRESS_STALE'):
            await graph.progress.reserve(sid,work | {'stage':'execute'})
        assert graph.progress.records()==[]
    asyncio.run(run_test())


def test_foreign_owner_attach_and_late_stop_compare_and_swap(tmp_path, monkeypatch):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        pid=await graph.progress.reserve(sid,work)
        other=rt.create({'skills':[]})['id']
        with pytest.raises(ValueError,match='WORK_PROGRESS_SCOPE'):
            graph.progress.attach(pid,other,work,other)
        graph.progress.finish(pid)
        for _ in range(2): await admission(rt,graph,sid,work)
        pid=await graph.progress.reserve(sid,work)
        child=rt.create({'skills':[]},parent_id=sid,role='explore',parent_tools=store.get(sid)['config']['tools'])['id']
        graph.progress.attach(pid,sid,work | {'admissionSeq':0},child)
        store.emit(child,'user',{'text':'started'})
        original=graph.progress.save
        def concurrent_stop(doc,status,expected=None):
            graph.progress.cancel(sid)
            return original(doc,status,expected)
        monkeypatch.setattr(graph.progress,'save',concurrent_stop)
        before=len(store.events(sid))
        result=graph.progress.finish(pid,{'status':'partial'})
        assert result['status']=='cancelled' and len(store.events(sid))==before
        assert graph.progress.blocked()==[]
    asyncio.run(run_test())


def test_failed_code_inspection_is_not_fresh_input_or_permission_to_run(tmp_path, monkeypatch):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        async def failed(*args): return None
        monkeypatch.setattr(work_checks,'snapshot',failed)
        with pytest.raises(ValueError,match='WORK_CODE_SNAPSHOT_REQUIRED'):
            await graph.progress.reserve(sid,work | {'stage':'execute'})
        assert graph.progress.records()==[] and not rt.client.prompts
    asyncio.run(run_test())


def test_root_artifact_without_producer_id_can_refresh_checker_input(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        old=await graph.artifacts.put(run,'E2','produce','root provided version one',{},True,None)
        task=work | {'purpose':'review','checkKind':'evidence','artifactIds':[old['artifactId']]}
        for _ in range(3): await admission(rt,graph,sid,task)
        new=await graph.artifacts.put(run,'E2','produce','root provided version two',{},True,None)
        cid, current=await admission(rt,graph,sid,task | {'artifactIds':[new['artifactId']]})
        assert current['novelInput'] and current['streak']==1
        assert work_feedback.input_snapshots(graph.feedback,None,task)
        assert work_feedback.input_snapshots(graph.feedback,None,task)!=work_feedback.input_snapshots(graph.feedback,None,task | {'artifactIds':[new['artifactId']]})
    asyncio.run(run_test())


def test_whole_checker_includes_real_answers_from_its_component_nodes(tmp_path):
    async def run_test():
        store, rt, graph, run, sid, work = setup(tmp_path)
        whole=work | {'nodeId':None,'purpose':'review','checkKind':'whole'}
        for _ in range(3): await admission(rt,graph,sid,whole)
        cid, _=await admission(rt,graph,sid,work,status='needs_user')
        req=await graph.feedback.report(store.get(cid),{'action':'needs_user','checkpoint':'A consequential component decision',
            'questions':[{'id':'intent','question':'Which direction?','options':['NN','RNN']}]},'question')
        card=graph.feedback.open_interview(store.get(sid),{'workRequestId':req['requestId'],'revision':1},'card')
        rt.resolve_decision(sid,card['decisionId'],'decide')
        _, current=await admission(rt,graph,sid,whole)
        assert current['novelInput'] and current['streak']==1
    asyncio.run(run_test())
