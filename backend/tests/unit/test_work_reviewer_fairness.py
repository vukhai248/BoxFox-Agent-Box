"""W6.1.3 checker duty versus tested behavior; keep strict contracts and gates."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_checks, work_graph, work_prompts
from test_work_graph import build, ok_script, answer, raw_tool
from test_work_checks import setup, start


@pytest.mark.parametrize('lang',['en','vi'])
def test_final_review_tail_requires_coverage_and_verdict_in_visible_answer(lang):
    text=work_prompts.child_contract('review',lang)
    assert 'fenced json' in text and 'coverage' in text
    assert all(k in text for k in ('id','status','target','evidence','VERDICT: ok','VERDICT: revise'))
    assert 'prose' in text.lower()
    assert work_checks.parse_report('All behavior is correct; no blocking findings.',{'A1':'Unicode','C1':'commands'})[0]=='error'


def test_failing_behavior_keeps_revise_while_honest_checker_execution_can_pass_C1(tmp_path):
    async def check():
        store,rt,model,executor,sid=build(tmp_path)
        graph=work_graph.service(rt)
        node={'id':'B1','kind':'build','title':'Unicode export','goal':'Fix exporter Unicode preservation',
              'acceptance':['Preserve Unicode'],'tests':['vitest ChatHeader.test.tsx']}
        run=graph.create(store.get(sid),{'goal':'Fix exporter Unicode','flow':'fix','nodes':[node]})
        run['status']='approved';graph.save(run)
        draft=await raw_tool(rt,sid,'work_run',{'phase':'execute'})
        original=model.complete
        async def reviewer(*args,**kwargs):
            result=await original(*args,**kwargs)
            prompt=next(m.get('content','') for m in args[0] if m['role']=='user')
            if prompt.startswith('Independent review') and result['choices'][0]['finish_reason']=='stop':
                assert 'C1 is the assigned checker duty' in prompt
                assert 'mark the violated A criterion revise' in prompt
                assert 'If an A criterion explicitly requires producer-run tests' in prompt
                assert 'criticalChanges=false does not prove' in prompt
                return answer('Unicode fails; command really executed and reported.\n```json\n'+json.dumps({'coverage':[
                    {'id':'A1','status':'revise','target':'artifact','evidence':'Observed Unicode assertion failure.'},
                    {'id':'C1','status':'pass','target':'artifact','evidence':'Ran required command; reported exit 1 honestly.'}]})+'\n```\nVERDICT: revise')
            return result
        model.complete=reviewer
        original_execute=executor.execute
        async def failing(name,args,*rest,**kwargs):
            if name=='terminal_exec' and args['command']=='vitest ChatHeader.test.tsx':
                return {'content':'Unicode assertion fails','exit_code':1,'is_error':True}
            return await original_execute(name,args,*rest,**kwargs)
        executor.execute=failing
        result=await start(rt,sid,draft)
        doc=result['checks'][0]
        assert doc['status']=='revise'
        assert {i['id']:i['status'] for i in doc['coverage']}=={'A1':'revise','C1':'pass'}
        assert result['nodes'][0]['stages']['execute']=='revise'
        assert not work_checks.test_proof(graph,doc['childId'],node['tests'])
        assert len(doc['attempts'])==1
    asyncio.run(check())


def test_prose_only_attempt_is_rejected_and_contract_error_survives_retry(tmp_path):
    async def check():
        store,rt,model,_,sid=build(tmp_path)
        _,draft=await setup(rt,sid)
        original=model.complete;first=True
        async def missing(*args,**kwargs):
            nonlocal first
            result=await original(*args,**kwargs)
            prompt=next(m.get('content','') for m in args[0] if m['role']=='user')
            if prompt.startswith('Independent review') and result['choices'][0]['finish_reason']=='stop' and first:
                first=False
                return answer('All facts match the opened original evidence. No blocking findings.')
            return result
        model.complete=missing
        result=await start(rt,sid,draft)
        doc=result['checks'][0]
        assert doc['status']=='pass' and len(doc['attempts'])==2
        assert doc['attempts'][0]['status']=='error'
        assert doc['attempts'][0]['contractError']=='Missing single final VERDICT line.'
        assert doc['attempts'][0]['completed'] is True
        assert 'contractError' not in doc['attempts'][1]
        assert len(rt.work_graph.checks.records(result['runId']))==1
    asyncio.run(check())


def test_checker_prose_pass_cannot_replace_missing_actual_test_command(tmp_path):
    # Explicit test of the existing enforcement, separate from prompt compliance.
    class Store:
        def get(self,cid):return {'config':{'workBinding':{'admissionSeq':0}}}
    class DB:
        def execute(self,*args):return self
        def fetchall(self):return []
    class Graph:
        store=Store();db=DB()
    assert not work_checks.test_proof(Graph(),'child',['python -m pytest -q'])
