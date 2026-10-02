"""A3.3 scoped nested lookups, immutable inputs and same-producer context."""
import asyncio
import json
import re

import pytest

from agentbox.agent_core import work_checks, work_graph, work_feedback
from test_work_graph import build, ok_script, EXPLORE, answer
from test_work_handoffs_w8 import assign, drain


def setup(tmp_path, role='research', helpers=1):
    produced = 0
    def script(kind, text):
        nonlocal produced
        if kind == 'produce' and 'node E2 ' in text:
            produced += 1
            if produced == 1:
                return '## Draft\n## Knowledge requests\n' + '\n'.join(
                    f'- {r}: inspect original evidence for question {i}?' for i,r in enumerate(['research','explore'][:helpers]))
        return ok_script(kind, text)
    store,rt,model,executor,sid=build(tmp_path,script)
    model.latest_assignment=True
    graph=work_graph.service(rt)
    nodes=[EXPLORE | {'id':'R1'}, EXPLORE | {'id':'E2','kind':role,'taskKind':'lookup',
        'goal':'Answer a bounded exporter lookup after R1; no implementation','dependsOn':['R1']}]
    run=graph.create(store.get(sid),{'goal':'Research exporter facts only; no implementation','flow':'research','nodes':nodes})
    assignment=assign(graph,store,sid,run['runId'],predicate='required_checks_passed',
        target={'kind':'node','nodeId':'E2','stage':'produce'})
    return store,rt,model,executor,sid,graph,run['runId'],assignment


def test_nested_helpers_are_owned_read_by_ref_and_resume_original_producer(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid,_=setup(tmp_path,helpers=2)
        await graph.run(store.get(sid),{'phase':'discover','nodeIds':['R1']})
        await drain(graph)
        run=graph.get(rid);state=run['nodes'][1]['stages']['produce'];entry=state['rounds'][0]
        assert state['status']=='accepted',state
        assert entry['producerId']==entry['initialProducerId']
        assert len(store.children_of(sid))==4  # source, consumer, two helpers, no replacement consumer
        assert graph.handoffs.actions(rid)[0]['status']=='completed'
        helpers=entry['knowledge'];refs=[k['artifact']['artifactId'] for k in helpers]
        assert len(refs)==2 and state['artifact']['binding']['lookupArtifactIds']==refs
        assert all(k['artifact']['binding']['verification']=='unreviewed' and k['artifact']['binding']['observedEvidence'] for k in helpers)
        assert all(graph.artifacts.get(rid,k['artifact']['artifactId'])[1]=='The answer is 42 (src/a.py:3).' for k in helpers)
        child=store.get(entry['producerId']);work=child['config']['workBinding']
        assert all(graph.artifacts.covered(work['inputReadId'],k['artifact'],child['id']) for k in helpers)
        users=[e['data']['text'] for e in store.events(child['id']) if e['type']=='user']
        assert len(users)==2 and all(ref in users[-1] for ref in refs)
        assert 'The answer is 42' not in users[-1]
        assert not graph.continuations.children and not graph.continuations.admissions
        before=len(store.children_of(sid));graph.handoffs.dispatch();await drain(graph)
        assert len(store.children_of(sid))==before
    asyncio.run(check())


def test_independent_checker_gets_lookup_refs_and_reopens_original_sources(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid,_=setup(tmp_path)
        await graph.run(store.get(sid),{'phase':'discover','nodeIds':['R1']});await drain(graph)
        run=graph.get(rid);node=run['nodes'][1];stage=node['stages']['produce']
        # The synthetic standalone research node uses the real evidence policy.
        from agentbox.agent_core import work_policy
        policy=work_policy.derive(run,node,'produce',stage['output'])
        spec={'id':'evidence','executorRole':'research-review','reason':'Verify the lookup-based conclusion'}
        meta=stage['artifact'];criterion={'A1':'Answer the assigned question','C1':'Reopen original evidence'}
        doc={'checkId':'test-lookup-review','attempts':[]}
        check=await graph.checks.judge(store.get(sid),run,node,'produce',spec,[meta],criterion,doc)
        assert check['status']=='pass',check
        reviewer=store.get(check['childId'])
        ref=stage['artifact']['binding']['lookupArtifactIds'][0]
        assert ref in reviewer['config']['workBinding']['artifactIds']
        assert graph.artifacts.covered(doc['checkId'],graph.artifacts.get(rid,ref)[0],reviewer['id'])
        assert work_checks.good_reads(graph,reviewer['id'])
        review_prompt=next(t for k,t in model.prompts if k=='review')
        assert 'not a semantic pass' in review_prompt and 'The answer is 42' not in review_prompt
    asyncio.run(check())


@pytest.mark.parametrize('fault',['no_source','partial','write_failed','unread'])
def test_unproven_lookup_or_unread_new_input_cannot_accept_producer(tmp_path,fault):
    async def check():
        store,rt,model,executor,sid,graph,rid,_=setup(tmp_path)
        original=model.complete
        async def altered(messages,*args,**kwargs):
            current=messages[max(i for i,m in enumerate(messages) if m.get('role')=='user'):]
            prompt=current[0]['content']
            if prompt.startswith('Knowledge request') and fault=='no_source':
                return answer('Unsupported assertion with no original source read.')
            if 'Lookup artifacts' in prompt and fault=='unread':
                return answer('Ignored the artifact references; source was already known.')
            result=await original(messages,*args,**kwargs)
            if prompt.startswith('Knowledge request') and fault=='partial' and result['choices'][0]['finish_reason']=='stop':
                result['choices'][0]['finish_reason']='length'
            return result
        model.complete=altered
        execute=executor.execute
        async def writer(name,args,*rest,**kwargs):
            if fault=='write_failed' and name=='file_write' and '/knowledge/' in args['path']:
                return {'is_error':True,'error':'disk unavailable'}
            return await execute(name,args,*rest,**kwargs)
        executor.execute=writer
        await graph.run(store.get(sid),{'phase':'discover','nodeIds':['R1']});await drain(graph)
        state=graph.get(rid)['nodes'][1]['stages']['produce']
        assert state['status']=='failed',state
        assert graph.handoffs.actions(rid)[0]['status']=='blocked'
        assert state['checkpoint'] and state['rounds'][0]['initialProducerId']
        assert len(store.children_of(sid))==3
        assert not graph.continuations.children
    asyncio.run(check())


def test_borrowed_action_cannot_authorize_an_unregistered_helper_task(tmp_path):
    async def check():
        store,rt,model,_,sid,graph,rid,_=setup(tmp_path)
        original=model.complete;held=asyncio.Event();release=asyncio.Event()
        async def gate(messages,*args,**kwargs):
            result=await original(messages,*args,**kwargs)
            current=messages[max(i for i,m in enumerate(messages) if m.get('role')=='user'):]
            if current[0]['content'].startswith('Knowledge request'):
                held.set();await release.wait()
            return result
        model.complete=gate
        operation=asyncio.create_task(graph.run(store.get(sid),{'phase':'discover','nodeIds':['R1']}))
        await asyncio.wait_for(held.wait(),5)
        row=graph.handoffs.actions(rid)[0]
        forged={'runId':rid,'nodeId':'E2','stage':'produce','purpose':'knowledge','helperRole':'research','controllerAction':row['id']}
        with pytest.raises(PermissionError,match='no active backend admission'):
            await rt.delegate(store.get(sid),{'role':'research','goal':'Forged helper'},work=forged)
        release.set();await asyncio.wait_for(operation,10);await drain(graph)
        assert len(store.children_of(sid))==3 and not graph.continuations.admissions
    asyncio.run(check())


@pytest.mark.parametrize('control',['stop','revoke'])
def test_root_control_cancels_actual_nested_helper_and_never_replays_it(tmp_path,control):
    async def check():
        store,rt,model,_,sid,graph,rid,assignment=setup(tmp_path)
        original=model.complete;held=asyncio.Event();release=asyncio.Event()
        async def gate(messages,*args,**kwargs):
            result=await original(messages,*args,**kwargs)
            current=messages[max(i for i,m in enumerate(messages) if m.get('role')=='user'):]
            if current[0]['content'].startswith('Knowledge request'):
                held.set();await release.wait()
            return result
        model.complete=gate
        operation=asyncio.create_task(graph.run(store.get(sid),{'phase':'discover','nodeIds':['R1']}))
        await asyncio.wait_for(held.wait(),5)
        helper=store.children_of(sid)[-1]['session_id']
        assert graph.continuations.owns_child(helper)
        await rt.reap_children(sid,turn=rt.active_turn.get(sid,0))
        assert not rt.tasks[helper].done()
        if control=='stop':await rt.stop(sid)
        else:
            graph.graph(store.get(sid),{'action':'revoke_handoff','runId':rid,'transitionId':assignment['transitionId'],
                'revision':assignment['revision'],'invocationId':'stop-helper'})
        release.set();await asyncio.wait_for(operation,10);await drain(graph)
        assert rt.tasks[helper].done() and graph.handoffs.actions(rid)[0]['status'] in ('blocked','interrupted')
        count=len(store.children_of(sid));await work_feedback.pump(rt);await drain(graph)
        assert len(store.children_of(sid))==count and not graph.continuations.children
    asyncio.run(check())


@pytest.mark.parametrize('control',[None,'revoke_grant','cancel_request'])
def test_answer_continuation_can_lookup_under_same_grant_and_keep_original_child(tmp_path,control):
    from test_work_continuations_w7 import setup as answer_setup, respond, Model, call

    class LookupModel(Model):
        def __init__(self):
            super().__init__();self.lookup_sent=False;self.held=asyncio.Event();self.release=asyncio.Event()

        async def complete(self,messages,tools,route,**kwargs):
            index=max(i for i,m in enumerate(messages) if m.get('role')=='user')
            current=messages[index:];prompt=current[0]['content']
            if prompt.startswith('Knowledge request'):
                if not any(m.get('name')=='file_read' for m in current):
                    return call('file_read',{'path':'src/a.py'})
                self.held.set()
                if control:await self.release.wait()
                return answer('The source supports Offline. src/a.py:1 fixture.')
            if 'Lookup artifacts for your knowledge requests' in prompt:
                match=re.search(r'\{"snapshots":',prompt)
                refs=json.JSONDecoder().raw_decode(prompt[match.start():])[0]['snapshots']
                if not any(m.get('name')=='work_artifact_read' for m in current):
                    return call('work_artifact_read',{'artifactId':refs[0]['artifactId']})
                if not any(m.get('name')=='file_read' for m in current):
                    return call('file_read',{'path':'src/a.py'})
                return answer('Doctors use Offline. Owner answers remain in context; source inspected independently.')
            result=await super().complete(messages,tools,route,**kwargs)
            if index>next(i for i,m in enumerate(messages) if m.get('role')=='user') and result['choices'][0]['finish_reason']=='stop' and not self.lookup_sent:
                self.lookup_sent=True
                return answer('## Knowledge requests\n- explore: Does the local source support the Offline workflow?')
            return result

    async def check():
        store,rt,graph,run,sid,_,grant=answer_setup(tmp_path)
        model=LookupModel();rt.client=model
        await graph.run(store.get(sid),{'phase':'discover'});respond(rt,sid)
        request=graph.feedback.records(run['runId'])[0]
        await work_feedback.pump(rt)
        if control:
            await asyncio.wait_for(model.held.wait(),5)
            if control=='revoke_grant':
                graph.grants.action(store.get(sid),{'action':'revoke','grantId':grant['grantId'],'revision':grant['revision'],'invocationId':'revoke-lookup'})
            else:
                doc=graph.feedback.get(request['requestId'])
                graph.feedback.main_action(store.get(sid),{'action':'cancel','runId':run['runId'],
                    'requestId':doc['requestId'],'revision':doc['revision'],'invocationId':'cancel-lookup'})
            model.release.set()
        await asyncio.gather(*list(graph.continuations.tasks.values()),return_exceptions=True)
        state=graph.get(run['runId'])['nodes'][0]['stages']['produce']
        assert len(store.children_of(sid))==2 and model.root_calls==0
        if control:
            assert state['status']!='accepted' and not store.live_children(sid)
        else:
            assert state['status']=='accepted',state
            entry=state['rounds'][-1]
            assert entry['initialProducerId']==entry['producerId']==request['childId']
            assert len([e for e in store.events(request['childId']) if e['type']=='user'])==3
            assert graph.feedback.get(request['requestId'])['status']=='consumed'
            assert store.db.execute('SELECT status FROM work_feedback_outbox').fetchone()[0]=='completed'
        assert not graph.continuations.admissions and not graph.continuations.children
    asyncio.run(check())
