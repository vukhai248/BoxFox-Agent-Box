"""Root grant + card foundation; direct worker routing is tested separately."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_feedback, work_grants
from test_work_feedback_w7 import setup, QUESTIONS
from test_work_graph import answer


def grant(graph,store,sid,run,**overrides):
    return graph.grants.action(store.get(sid),{'action':'grant','runId':run['runId'],
        'revision':graph.get(run['runId'])['revision'],'nodeId':'R1','decisionKeys':['users','deploy'],
        'publishInterview':True,'resumeOnAnswers':True,'invocationId':'root-grant',**overrides})


async def report(graph,store,cid,**overrides):
    return await graph.feedback.report(store.get(cid),{'action':'needs_user','checkpoint':'Source checked, need intended users/deployment.',
        'questions':QUESTIONS,'decisionKeys':['users','deploy'],**overrides},'request-granted')


def test_grant_publishes_same_questions_under_root_without_starting_root_model(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        rights=grant(graph,store,sid,run)
        rt.start=lambda *a,**kw:pytest.fail('publication cannot call main model')
        req=await report(graph,store,cid)
        assert req['status']=='needs_user' and req['grantId']==rights['grantId']
        card=rt.pending_for(sid)[0]
        assert card['sessionId']==sid and not card['requiresMainYield'] and card['deadline'] is None
        assert card['questions']==rt.normalize_interview({'questions':QUESTIONS})
        assert graph.feedback.yielded(cid)['requestId']==req['requestId']
        assert sum(e['type']=='decision_requested' for e in store.events(sid))==1
        assert (await report(graph,store,cid))==req
        assert sum(e['type']=='decision_requested' for e in store.events(sid))==1
    asyncio.run(run_test())


def test_grant_invocation_revision_revoke_and_scope_are_persistent(tmp_path):
    store,rt,graph,run,sid,cid=setup(tmp_path)
    rights=grant(graph,store,sid,run)
    assert grant(graph,store,sid,run)==rights
    with pytest.raises(work_feedback.FeedbackError,match='INVOCATION_CONFLICT'):
        grant(graph,store,sid,run,publishInterview=False)
    with pytest.raises(work_feedback.FeedbackError,match='REVISION_CONFLICT'):
        grant(graph,store,sid,run,revision=0,invocationId='stale-grant')
    graph.grants=work_grants.Grants(graph)
    binding=store.get(cid)['config']['workBinding']
    assert graph.grants.find(run,binding,['users'])['grantId']==rights['grantId']
    revised=run | {'goal':'A new unrelated owner goal'}
    assert graph.grants.find(revised,binding,['users']) is None
    revoked=graph.grants.action(store.get(sid),{'action':'revoke','grantId':rights['grantId'],'revision':1,'invocationId':'revoke-rights'})
    assert revoked['status']=='revoked' and graph.grants.find(run,binding,['users']) is None
    with pytest.raises(work_feedback.FeedbackError,match='ROOT_ONLY'):
        graph.grants.action(store.get(cid),{'action':'grant'})


def test_missing_rights_and_duplicate_decision_route_main_instead_of_second_card(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        original=await report(graph,store,cid)
        assert original['status']=='waiting_main' and not rt.pending_for(sid)
        # A fresh child in the same assignment cannot publish a conflicting logical decision.
        grant(graph,store,sid,run)
        second=rt.create({'skills':[]},parent_id=sid,role='research',parent_tools=store.get(sid)['config']['tools'])
        config=second['config'];config['workBinding']=store.get(cid)['config']['workBinding'];store.update_config(second['id'],config)
        duplicate=await report(graph,store,second['id'])
        assert duplicate['status']=='waiting_main' and duplicate['routingReason']=='decision_conflict'
        assert duplicate['conflictingRequestId']==original['requestId'] and not rt.pending_for(sid)
        with pytest.raises(work_feedback.FeedbackError,match='INTERVIEW_CONFLICT'):
            graph.feedback.open_interview(store.get(sid),{'workRequestId':duplicate['requestId'],'revision':1},'manual')
    asyncio.run(run_test())


def test_read_answer_ref_is_bound_to_original_child_and_resolves_source_refs(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        rights=grant(graph,store,sid,run)
        req=await report(graph,store,cid);card=rt.pending_for(sid)[0]
        rt.resolve_decision(sid,card['decisionId'],'decide')
        saved=await graph.feedback.report(store.get(cid),{'action':'read','requestId':req['requestId']},'read-answer')
        assert saved['childId']==cid and len(saved['answers'])==2
        assert all(a['source']=='user_action' for a in saved['answers'])
        other=rt.create({'skills':[]},parent_id=sid,role='research',parent_tools=store.get(sid)['config']['tools'])
        with pytest.raises(work_feedback.FeedbackError,match='SCOPE'):
            await graph.feedback.report(store.get(other['id']),{'action':'read','requestId':req['requestId']},'cross-child')
        event={'name':'read_source','args':{'ref':'stored-source-1'},'result':{'content':'Real retained source body','url':'https://example.test/source','quality':{'verdict':'ok'}}}
        assert work_feedback.evidence_signature(event)['ref']=='https://example.test/source'
    asyncio.run(run_test())


@pytest.mark.parametrize('automatic', [False, True])
def test_answer_event_keeps_existing_transcript_status_after_partial_answer_reload(tmp_path, automatic):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        if automatic:
            grant(graph,store,sid,run)
        req=await report(graph,store,cid)
        card=(rt.pending_for(sid)[0] if automatic else graph.feedback.open_interview(
            store.get(sid),{'workRequestId':req['requestId'],'revision':req['revision']},'manual-card'))
        payload=[{'questionId':'users','optionId':card['questions'][0]['options'][0]['id']}]
        first=rt.resolve_decision(sid,card['decisionId'],'submit',answers=payload)
        assert first['status']=='resolved' and first['remaining'] is True
        assert rt.resolve_decision(sid,card['decisionId'],'submit',answers=payload)==first
        graph.feedback=work_feedback.Feedback(graph)
        remaining=rt.pending_for(sid)[0]
        assert [q['id'] for q in remaining['questions']]==['deploy']
        final=rt.resolve_decision(sid,remaining['decisionId'],'submit',answers=[
            {'questionId':'deploy','text':'Offline only'}])
        assert final['status']=='resolved' and not final['remaining']
        resolutions=[e['data'] for e in store.events(sid) if e['type']=='decision_resolved']
        assert len(resolutions)==2
        assert all(e['status']=='answered' and e['outcome']=='answered' and e['resolved']
                   and e['reason']=='user' and e['resolvedAt']>0 for e in resolutions)
        assert [q['id'] for q in resolutions[0]['questions']]==['users','deploy']
        assert all(a['source']=='user_action' for e in resolutions for a in e['answers'])
        assert resolutions[0]['answers'][0]['answer']=='Doctors'
        assert resolutions[1]['answers'][0]['answer']=='Offline only'
        assert not rt.pending_for(sid)
        assert store.db.execute('SELECT COUNT(*) FROM work_feedback_outbox').fetchone()[0]==1
    asyncio.run(run_test())


def test_actual_child_yields_after_auto_publication_even_if_answer_arrives_early(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        grant(graph,store,sid,run)
        config=store.get(cid)['config'];config['tools'].append('work_report');store.update_config(cid,config)
        base_report=graph.feedback.report
        async def early_answer(session,args,call_id):
            req=await base_report(session,args,call_id)
            card=rt.pending_for(sid)[0]
            rt.resolve_decision(sid,card['decisionId'],'decide')
            return req
        graph.feedback.report=early_answer
        class Model:
            calls=0
            async def complete(self,*args,**kwargs):
                self.calls+=1
                return {'choices':[{'message':{'tool_calls':[{'id':'auto-question','type':'function','function':{
                    'name':'work_report','arguments':json.dumps({'action':'needs_user','questions':QUESTIONS,
                        'decisionKeys':['users','deploy'],'checkpoint':'Known facts saved; owner intent needed.'})}}]},'finish_reason':'tool_calls'}]}
        rt.client=Model()
        await rt.start(cid,'Read facts then ask the missing owner intent.')
        assert rt.client.calls==1 and not graph.child_answer(cid)
        req=graph.feedback.records(run['runId'])[0]
        assert req['status']=='ready' and len(req['answers'])==2
        assert store.get(cid)['status']=='completed'
        finish=next(e['data'] for e in reversed(store.events(cid)) if e['type']=='finish')
        assert finish['needsUser'] and finish['workRequestId']==req['requestId']
    asyncio.run(run_test())


def test_auto_card_does_not_force_unrelated_main_progress_turn_to_yield(tmp_path):
    async def run_test():
        store,rt,graph,run,sid,cid=setup(tmp_path)
        grant(graph,store,sid,run);await report(graph,store,cid)
        class Model:
            calls=0
            async def complete(self,*args,**kwargs):
                self.calls+=1
                if self.calls==1:
                    return {'choices':[{'message':{'tool_calls':[{'id':'read-progress','type':'function','function':{
                        'name':'file_read','arguments':'{"path":"src/a.py"}'}}]},'finish_reason':'tool_calls'}]}
                return answer('Progress report; research waits for the owner, other branches can continue.')
        rt.client=Model();await rt.start(sid,'Report progress only.')
        ends=[e['data'] for e in store.events(sid) if e['type']=='turn_end']
        assert not any(e.get('reason')=='work_checkpoint' for e in ends)
        assert len(rt.pending_for(sid))==1
        assert rt.client.calls>=2
    asyncio.run(run_test())


def test_granted_node_must_send_decision_keys_on_needs_user(tmp_path):
    """#6475: đã có grant cho đúng ô thì `needs_user` không được bỏ `decisionKeys`.

    Bỏ trường này là rơi im lặng khỏi đường grant: không kiểm thu hồi, không khớp câu hỏi với
    quyền đã giao, card thiếu khoá quyết định. Không có grant thì đường dự phòng (main trả lời)
    vẫn chạy như cũ.
    """
    async def run_test():
        store, rt, graph, run, sid, cid = setup(tmp_path)
        child = store.get(cid)
        # Chưa có grant: needs_user không khoá vẫn lưu được để main trả lời.
        first = await graph.feedback.report(child, {'action': 'needs_user', 'checkpoint': 'Cần chốt phạm vi',
                                                    'questions': QUESTIONS, 'invocationId': 'no-grant'}, 'tool-ng')
        assert first['decisionKeys'] == []
        assert first['status'] == 'waiting_main'
        # Có grant cho đúng node/stage/purpose: thiếu decisionKeys phải bị chặn đúng mã.
        grant(graph, store, sid, run)
        with pytest.raises(work_feedback.FeedbackError, match='WORK_DECISION_KEYS_INVALID'):
            await graph.feedback.report(child, {'action': 'needs_user', 'checkpoint': 'Cần chốt phạm vi',
                                                'questions': QUESTIONS, 'invocationId': 'granted-no-keys'}, 'tool-g')
    asyncio.run(run_test())
