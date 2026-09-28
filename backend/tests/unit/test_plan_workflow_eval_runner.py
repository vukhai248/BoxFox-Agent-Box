"""Evaluation setup tests are not live provider quality evidence."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import socket
import sys
import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('plan_workflow_eval', ROOT/'scripts/eval/plan_workflow_eval.py')
runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)

def test_dry_run_has_24_cells_and_zero_network(monkeypatch,capsys):
    monkeypatch.setattr(sys,'argv',['plan_workflow_eval.py'])
    monkeypatch.setattr(socket,'socket',lambda *a,**kw: pytest.fail('dry run opened a socket'))
    runner.main()
    body=json.loads(capsys.readouterr().out)
    assert body['cells']==24 and body['modelCalls']==0 and len(body['cases'])==12

def test_execute_refuses_missing_budget_before_network(monkeypatch):
    monkeypatch.delenv('BOXFOX_EVAL_ALLOW_SPEND',raising=False)
    monkeypatch.delenv('BOXFOX_EVAL_BUDGET_USD',raising=False)
    monkeypatch.setattr(sys,'argv',['plan_workflow_eval.py','--execute'])
    monkeypatch.setattr(socket,'socket',lambda *a,**kw: pytest.fail('refused run opened a socket'))
    with pytest.raises(SystemExit) as error: runner.main()
    assert error.value.code==2

def test_isolated_executor_really_writes_utf8_and_refuses_implementation(tmp_path):
    executor=runner.IsolatedExecutor(tmp_path)
    async def check():
        text='Kế hoạch tổng hợp hồ sơ y tế có dấu'
        value=await executor.execute('write_plan',{'slug':'medical','version':1,'markdown':text},'root')
        assert (tmp_path/value['relativePath']).read_bytes()==text.encode('utf-8')
        read=await executor.execute('file_read',{'path':value['relativePath']},'root')
        assert read['content']==text and read['nextOffset'] is None
        journal=await executor.execute('journal_append',{'record':{'id':'fact','text':'đã đọc'}},'root')
        assert journal['seq']==1 and (tmp_path/journal['relPath']).exists()
        with pytest.raises(ValueError,match='EVAL_EXECUTION_PROHIBITED'):
            await executor.execute('file_write',{'path':'app.py','content':'bad'},'root')
        with pytest.raises(ValueError,match='EVAL_PATH_OUTSIDE'):
            await executor.execute('file_read',{'path':'../outside'},'root')
    asyncio.run(check())

def test_scripted_no_plan_stays_blocked_and_exports_artifacts(tmp_path,monkeypatch):
    from agentbox.agent_core.runtime import RouterClient
    async def fixture(self,*args,**kwargs):
        return {'choices':[{'message':{'content':'Fixture turn.'},'finish_reason':'stop'}]}
    monkeypatch.setattr(RouterClient,'complete',fixture)
    pack=json.loads(runner.PACK.read_text(encoding='utf-8')); case=pack['cases'][0]
    args=SimpleNamespace(out=str(tmp_path),variant='reform',router='http://127.0.0.1:1')
    result=asyncio.run(runner.cell(args,{'skills':[]},case,1,pack))
    assert result['runs'][0]['status']=='blocked'
    assert not result['approved'] and not result['approvalStartedBuild']
    directory=tmp_path/'reform'/case['id']/'1'
    assert (directory/'sessions.sqlite').exists() and (directory/'result.json').exists() and (directory/'events.json').exists()


def test_error_report_separates_provider_product_and_evaluation_failures():
    classified = runner.classify_errors([
        {'type': 'error', 'data': {'code': 'UPSTREAM_HTTP_502'}},
        {'type': 'error', 'data': {'code': 'PLAN_REVISION_CONFLICT'}},
        {'type': 'error', 'data': {'code': 'EVAL_EXECUTION_PROHIBITED_OR_UNSUPPORTED'}},
        {'type': 'usage', 'data': {'tokens': 1}},
    ])
    assert len(classified['providerErrors']) == len(classified['productErrors']) == len(classified['evaluationErrors']) == 1
