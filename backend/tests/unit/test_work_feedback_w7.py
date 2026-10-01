"""Durable interview/continuation tests; mock model, no live provider claims."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_feedback, work_graph, work_checks
from agentbox.agent_core.runtime import DecisionError
from test_work_graph import build, answer


QUESTIONS = [{'id': 'users', 'question': 'Who uses the output?', 'options': ['Doctors', 'Nurses']},
             {'id': 'deploy', 'question': 'Where will it run?', 'options': ['Offline', 'Cloud']}]


def setup(tmp_path):
    store, rt, model, executor, sid = build(tmp_path)
    graph = work_graph.service(rt)
    run = graph.create(store.get(sid), {'goal':'Research the clinical summarization options', 'flow':'research', 'nodes':[
        {'id':'R1','kind':'research','title':'Options','goal':'Research options after confirming the intended users',
         'taskKind':'lookup','acceptance':['Use source'], 'dependsOn':[]}]})
    child = rt.create({'skills':[]}, parent_id=sid, role='research', parent_tools=store.get(sid)['config']['tools'])
    child['config']['workBinding'] = {'runId':run['runId'],'nodeId':'R1','stage':'produce','purpose':'produce','artifactIds':[]}
    child['config']['workBudget'] = {'effectiveMaxSteps': 4,'effectiveDeadlineSeconds':120}
    store.update_config(child['id'],child['config'])
    return store,rt,graph,run,sid,child['id']


async def request(rt,graph,cid):
    return await graph.feedback.report(rt.store.get(cid), {'action':'needs_user','checkpoint':'Research NN completed, user needs to select continuation',
        'questions':QUESTIONS,'invocationId':'request-1'}, 'tool-1')


def open_card(rt,graph,sid,req):
    return graph.feedback.open_interview(rt.store.get(sid), {'workRequestId':req['requestId'],'revision':req['revision']},'interview-1')


def test_partial_answers_restart_duplicate_stale_and_ownership(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        req=await request(rt,graph,cid)
        card=open_card(rt,graph,sid,req)
        assert card['deadline'] is None and len(card['questions'])==2
        args=[{'questionId':'users','optionId':card['questions'][0]['options'][0]['id']}]
        first=rt.resolve_decision(sid,card['decisionId'],'submit',answers=args)
        assert first['remaining'] is True and first['answers'][0]['decidedBy']=='user'
        assert rt.resolve_decision(sid,card['decisionId'],'submit',answers=args)==first
        with pytest.raises(DecisionError,match='REVISION_CONFLICT'):
            rt.resolve_decision(sid,card['decisionId'],'submit',answers=[{'questionId':'deploy','optionId':'decide'}])
        other=rt.create({'skills':[]})['id']
        with pytest.raises(DecisionError,match='UNKNOWN'):
            rt.resolve_decision(other,card['decisionId'],'decide')
        # Recreate the service from SQLite, not the RAM pending map.
        graph.feedback=work_feedback.Feedback(graph)
        newer=rt.pending_for(sid)[0]
        assert len(newer['questions'])==1 and len(newer['answers'])==1
        result=rt.resolve_decision(sid,newer['decisionId'],'submit',answers=[{'questionId':'deploy','text':'RNN offline'}])
        assert result['remaining'] is False
        assert rt.resolve_decision(sid,newer['decisionId'],'submit',answers=[{'questionId':'deploy','text':'RNN offline'}])==result
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0]==1
        doc=graph.feedback.get(req['requestId'])
        assert [a['answer'] for a in doc['answers']]==['Doctors','RNN offline']
        events=store.events(sid)
        assert sum(e['type']=='decision_resolved' for e in events)==2
        assert doc['artifact']['status']=='partial'
    asyncio.run(run_test())


def test_empty_submission_never_becomes_consent_and_answer_transaction_rolls_back(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        req=await request(rt,graph,cid);card=open_card(rt,graph,sid,req)
        with pytest.raises(DecisionError,match='empty answer'):
            rt.resolve_decision(sid,card['decisionId'],'submit',answers=[{'questionId':'users'}])
        store.db.execute("CREATE TRIGGER fail_outbox BEFORE INSERT ON work_feedback_outbox BEGIN SELECT RAISE(ABORT,'fault'); END")
        store.db.commit()
        with pytest.raises(Exception,match='fault'):
            rt.resolve_decision(sid,card['decisionId'],'decide')
        assert graph.feedback.get(req['requestId'])['answers']==[]
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_invocations').fetchone()[0]==0
    asyncio.run(run_test())


def test_changed_assignment_cannot_resume_old_request(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        req=await request(rt,graph,cid)
        run['nodes'][0]['goal']='Research a totally different implementation assignment'
        graph.save(run)
        with pytest.raises(work_feedback.FeedbackError,match='STALE'):
            open_card(rt,graph,sid,req)
    asyncio.run(run_test())


def test_actual_child_yields_then_resumes_same_context_with_fresh_budget(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        rt.store.child_start(cid,sid,1,1,'research')
        class Model:
            calls=0
            async def complete(self,messages,tools,route,**kwargs):
                self.calls += 1
                last=next(i for i in range(len(messages)-1,-1,-1) if messages[i]['role']=='user')
                current=messages[last:]
                if self.calls == 1:
                    return {'choices':[{'message':{'tool_calls':[{'id':'report','type':'function','function':{
                        'name':'work_report','arguments':json.dumps({'action':'needs_user','questions':QUESTIONS,'checkpoint':'NN research saved'})}}]},'finish_reason':'tool_calls'}]}
                if self.calls == 2:
                    return {'choices':[{'message':{'tool_calls':[{'id':'read','type':'function','function':{
                        'name':'file_read','arguments':'{"path":"src/a.py"}'}}]},'finish_reason':'tool_calls'}]}
                return answer('RNN continuation based on saved NN checkpoint and owner answer. src/a.py:1')
        rt.client=Model()
        config=store.get(cid)['config'];config['tools'].append('work_report');store.update_config(cid,config)
        await rt.start(cid,'start NN')
        req=graph.feedback.yielded(cid)
        assert req and not graph.child_answer(cid)
        # Parent end reaping cannot kill a yielded/completed child.
        store.child_finish(cid,'needs_user')
        card=open_card(rt,graph,sid,req)
        rt.resolve_decision(sid,card['decisionId'],'decide')
        ready=graph.feedback.get(req['requestId'])
        old=store.get(cid)['config']['workBinding']
        result=await work_feedback.resume_child(rt,store.get(sid),cid,'continue RNN',old,ready)
        assert result['sessionId']==cid and result['resumed'] and result['status']=='completed'
        assert result['lifetimeStepsUsed'] > result['stepsUsed']
        assert store.get(cid)['config']['workRemaining']['maxSteps']==4
        assert len([m for m in store.get(cid)['messages'] if m.get('name')=='work_report'])==1
        with pytest.raises(work_feedback.FeedbackError,match='NO_PROGRESS'):
            await work_feedback.resume_child(rt,store.get(sid),cid,'repeat',old,ready)
    asyncio.run(run_test())


def test_outbox_start_once_and_uncertain_restart_is_not_replayed(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        req=await request(rt,graph,cid);card=open_card(rt,graph,sid,req)
        rt.resolve_decision(sid,card['decisionId'],'decide')
        calls=[]
        def start(owner,prompt,invocation_id):
            calls.append(invocation_id)
            store.emit(owner,'user',{'text':prompt,'invocationId':invocation_id})
        rt.start=start
        await work_feedback.pump(rt);await work_feedback.pump(rt)
        assert len(calls)==1
        # Simulate crash between actual admission event and outbox completion.
        store.db.execute("UPDATE work_feedback_outbox SET status='pending'");store.db.commit()
        await work_feedback.pump(rt)
        assert len(calls)==1
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0]=='interrupted'
    asyncio.run(run_test())


def test_telemetry_sums_admissions_not_max_across_turns(tmp_path):
    store,rt,graph,run,sid,cid=setup(tmp_path)
    for turn,step,tokens in [(1,1,2),(1,3,4),(2,2,5)]:
        store.emit(cid,'turn_end',{'turn':turn,'stepsUsed':step,'outputTokens':tokens})
    assert store.child_usage_from_events(cid)==(5,11)


def test_runtime_main_interview_releases_turn_and_keeps_card_after_finally(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path);req=await request(rt,graph,cid)
        class Model:
            async def complete(self,messages,tools,route,**kwargs):
                return {'choices':[{'message':{'tool_calls':[{'id':'card','type':'function','function':{
                    'name':'interview','arguments':json.dumps({'workRequestId':req['requestId'],'revision':1})}}]},'finish_reason':'tool_calls'}]}
        rt.client=Model();await rt.start(sid,'Interview the unresolved owner decision')
        assert store.get(sid)['status']=='completed'
        assert len(rt.pending_for(sid))==1 and rt.pending_for(sid)[0]['durable']
        assert not rt.pending and not rt.run_budget and not rt.store.live_children(sid)
    asyncio.run(run_test())


def test_checkpoint_blocks_later_tools_in_the_same_group_and_cancel_invalidates_answer(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path);req=await request(rt,graph,cid)
        with pytest.raises(PermissionError,match='CHECKPOINT_YIELDED'):
            await rt.dispatch(store.get(cid),'file_read',{'path':'src/a.py'})
        card=open_card(rt,graph,sid,req)
        await rt.stop(sid)
        assert not rt.pending_for(sid)
        with pytest.raises(DecisionError,match='NOT_READY'):
            rt.resolve_decision(sid,card['decisionId'],'decide')
    asyncio.run(run_test())


def test_evidence_checkpoint_requires_actual_new_read_before_reset(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        req=await graph.feedback.report(store.get(cid),{'action':'needs_evidence','checkpoint':'Parser fact needs executable confirmation'},'proof')
        args={'action':'resume','requestId':req['requestId'],'revision':1,'context':'checked','evidenceRefs':['src/a.py']}
        with pytest.raises(work_feedback.FeedbackError,match='EVIDENCE_REQUIRED'):
            graph.feedback.main_action(store.get(sid),args)
        store.emit(sid,'tool_end',{'name':'file_read','args':{'path':'src/a.py'},'result':{'content':'observed'}})
        assert graph.feedback.main_action(store.get(sid),args)['status']=='ready'
    asyncio.run(run_test())


def test_restart_during_resume_keeps_original_child_and_checkpoint(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path);req=await request(rt,graph,cid)
        req['status']='resuming'
        with store.db: graph.feedback.save(req)
        run['nodes'][0]['stages']['produce'].update(status='running',requestId=req['requestId'],attempts=1)
        graph.save(run)
        rt.work_graph=work_graph.WorkGraph(rt);graph=rt.work_graph
        assert graph.feedback.get(req['requestId'])['status']=='interrupted'
        state=graph.get(run['runId'])['nodes'][0]['stages']['produce']
        assert state['status']=='needs_user' and state['checkpoint']['childId']==cid
        assert not work_graph.ready_nodes(graph.get(run['runId']),'produce')
    asyncio.run(run_test())


def test_self_checkpoint_cannot_reset_budget_or_become_opened_evidence(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        req=await graph.feedback.report(store.get(cid),{'action':'checkpoint','checkpoint':'Same work, different prose'},'self-1')
        work=store.get(cid)['config']['workBinding'] | {'artifactIds':[req['artifact']['artifactId']]}
        with pytest.raises(work_feedback.FeedbackError,match='NO_PROGRESS'):
            await work_feedback.resume_child(rt,store.get(sid),cid,'continue',work)
        store.emit(sid,'tool_end',{'name':'file_read','args':{'path':req['artifact']['path']},
                                 'result':{'content':'Same work, different prose'}})
        with pytest.raises(work_feedback.FeedbackError,match='EVIDENCE_REQUIRED'):
            graph.feedback.main_action(store.get(sid),{'action':'resume','requestId':req['requestId'],
                'revision':1,'evidenceRefs':[req['artifact']['path']]})
        assert store.db.execute('SELECT COUNT(*) FROM work_resume_inputs').fetchone()[0]==0
    asyncio.run(run_test())


def test_evidence_body_and_resume_invocation_are_stable_across_retries(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        def read(who,body):
            store.emit(who,'tool_end',{'name':'file_read','args':{'path':'src/a.py'},'result':{'content':body}})
        read(cid,'already known')
        req=await graph.feedback.report(store.get(cid),{'action':'needs_evidence','checkpoint':'Need a new fact'},'proof-1')
        args={'action':'resume','requestId':req['requestId'],'revision':1,'invocationId':'resume-proof',
              'evidenceRefs':['src/a.py']}
        read(sid,'already known')
        with pytest.raises(work_feedback.FeedbackError,match='NO_PROGRESS'):
            graph.feedback.main_action(store.get(sid),args)
        read(sid,'newly verified revision')
        ready=graph.feedback.main_action(store.get(sid),args)
        assert ready['evidenceProofs'][0]['contentHash']==work_feedback.work_policy.digest('newly verified revision')
        assert graph.feedback.main_action(store.get(sid),args)==ready
        with pytest.raises(work_feedback.FeedbackError,match='INVOCATION_CONFLICT'):
            graph.feedback.main_action(store.get(sid),args | {'context':'changed'})
        assert graph.feedback.get(req['requestId'])['revision']==2
    asyncio.run(run_test())


def test_rereading_previous_proof_cannot_grant_another_turn(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        store.child_start(cid,sid,1,1,'research')
        class Model:
            async def complete(self,*args,**kwargs): return answer('Verified new input, completed report.')
        rt.client=Model()
        req=await graph.feedback.report(store.get(cid),{'action':'needs_evidence','checkpoint':'Waiting for proof'},'proof-1')
        def read(body):
            store.emit(sid,'tool_end',{'name':'file_read','args':{'path':'src/a.py'},'result':{'content':body}})
        read('version 1')
        ready=graph.feedback.main_action(store.get(sid),{'action':'resume','requestId':req['requestId'],'revision':1,'evidenceRefs':['src/a.py']})
        old=store.get(cid)['config']['workBinding']
        result=await work_feedback.resume_child(rt,store.get(sid),cid,'continue',old,ready)
        assert result['status']=='completed'
        newer=await graph.feedback.report(store.get(cid),{'action':'needs_evidence','checkpoint':'Same issue phrased differently'},'proof-2')
        read('version 1')
        with pytest.raises(work_feedback.FeedbackError,match='NO_PROGRESS'):
            graph.feedback.main_action(store.get(sid),{'action':'resume','requestId':newer['requestId'],'revision':1,'evidenceRefs':['src/a.py']})
        read('version 2')
        ready2=graph.feedback.main_action(store.get(sid),{'action':'resume','requestId':newer['requestId'],'revision':1,'evidenceRefs':['src/a.py']})
        result2=await work_feedback.resume_child(rt,store.get(sid),cid,'continue from new revision',old,ready2)
        assert result2['status']=='completed' and result2['lifetimeStepsUsed']>result2['stepsUsed']
    asyncio.run(run_test())


def test_resumed_budget_reapplies_requested_profile_and_current_parent_ceiling(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        store.child_start(cid,sid,1,1,'research')
        config=store.get(cid)['config']
        config['workBudget'].update(requestedMaxSteps=8,requestedDeadlineSeconds=120)
        store.update_config(cid,config)
        parent=store.get(sid)['config'];parent.update(maxSteps=6,deadlineSeconds=90);store.update_config(sid,parent)
        req=await request(rt,graph,cid);card=open_card(rt,graph,sid,req)
        rt.resolve_decision(sid,card['decisionId'],'decide');ready=graph.feedback.get(req['requestId'])
        class Model:
            async def complete(self,*args,**kwargs):return answer('Completed after new owner input.')
        rt.client=Model()
        result=await work_feedback.resume_child(rt,store.get(sid),cid,'continue',config['workBinding'],ready)
        assert result['budget']['effectiveMaxSteps']==6
        assert result['budget']['effectiveDeadlineSeconds']==90 and result['budget']['clamped']
        assert store.get(cid)['config']['workRemaining']=={'maxSteps':6,'deadlineSeconds':90}
    asyncio.run(run_test())


def test_kill_switch_defers_pending_outbox_without_starting_main(tmp_path,monkeypatch):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path);req=await request(rt,graph,cid);card=open_card(rt,graph,sid,req)
        rt.resolve_decision(sid,card['decisionId'],'decide')
        rt.start=lambda *a,**kw:pytest.fail('disabled Work Graph cannot admit main')
        monkeypatch.setenv('BOXFOX_WORK_GRAPH','off')
        await work_feedback.pump(rt)
        assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0]=='pending'
    asyncio.run(run_test())


def test_work_report_guidance_distinguishes_completed_final_from_checkpoint():
    from agentbox.agent_core.roles import with_work_graph
    guidance=with_work_graph('role instructions')
    assert 'return the full deliverable in your final answer' in guidance
    assert 'only when blocked' in guidance


def test_absolute_self_checkpoint_path_is_not_new_evidence(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        req=await graph.feedback.report(store.get(cid),{'action':'checkpoint','checkpoint':'My own prose'},'own-path')
        absolute='/home/agent/workspace/' + req['artifact']['path']
        store.emit(sid,'tool_end',{'name':'file_read','args':{'path':absolute},'result':{'content':'My own prose'}})
        assert graph.feedback.opened(sid,cid,after=req['createdAt'])==[]
    asyncio.run(run_test())


def test_failed_source_body_cannot_refresh_budget_but_reader_recovery_can():
    event={'name':'web_fetch','args':{'url':'https://example.test/source'},'result':{'content':'Access denied','status':403}}
    assert work_feedback.evidence_signature(event) is None
    event['result']['quality']={'verdict':'unusable'}
    assert work_feedback.evidence_signature(event) is None
    event['result'].update(content='Recovered original source',quality={'verdict':'ok'})
    assert work_feedback.evidence_signature(event)['contentHash']==work_feedback.work_policy.digest('Recovered original source')


def test_cancelled_resume_releases_slot_and_retains_interrupted_request(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        store.child_start(cid,sid,1,1,'research')
        req=await request(rt,graph,cid);card=open_card(rt,graph,sid,req)
        rt.resolve_decision(sid,card['decisionId'],'decide');ready=graph.feedback.get(req['requestId'])
        started=asyncio.Event()
        class Model:
            async def complete(self,*args,**kwargs):
                started.set()
                await asyncio.Future()
        rt.client=Model()
        driver=asyncio.create_task(work_feedback.resume_child(rt,store.get(sid),cid,'continue',store.get(cid)['config']['workBinding'],ready))
        await asyncio.wait_for(started.wait(),5)
        driver.cancel()
        with pytest.raises(asyncio.CancelledError):await driver
        assert graph.feedback.get(req['requestId'])['status']=='interrupted'
        assert store.child(cid)['status']=='cancelled'
        assert not store.live_children(sid)
    asyncio.run(run_test())
