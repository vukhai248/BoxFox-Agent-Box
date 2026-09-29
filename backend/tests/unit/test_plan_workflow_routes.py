"""Actual aiohttp routes + real SQLite; no network model/provider calls."""
import asyncio
import hashlib
import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from agentbox.api.server import create_app
from agentbox.agent_core import plan_workflow as pw
from test_plan_workflow import env, scope, ready

HEADERS = {'Host':'127.0.0.1:3102','X-BoxFox-Admin':'1'}

def check_api(rt, callback):
    async def check():
        async with TestServer(create_app(rt)) as server:
            async with ClientSession(headers=HEADERS) as client:
                async def request(method, path, data=None):
                    async with client.request(method, server.make_url('/api/agent'+path), json=data) as response:
                        return response.status, await response.json()
                await callback(request)
    asyncio.run(check())

def test_partial_answer_revision_conflict_and_get_roundtrip(env):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id':k,'field':k,'text':k} for k in ['users','data']])
    async def check(request):
        status, result = await request('POST', '/plans/runs/'+run['runId']+'/answers', {
            'revision':run['revision'],'invocationId':'partial','answers':[{'questionId':'users','text':'Bác sĩ'}]})
        assert status == 200 and result['run']['status'] == 'needs_user' and not result['queued']
        status, copy = await request('GET', '/plans/runs/'+run['runId'])
        assert status == 200 and copy['brief']['users']['text'] == 'Bác sĩ'
        status, error = await request('POST', '/plans/runs/'+run['runId']+'/answers', {
            'revision':run['revision'],'invocationId':'stale','answers':[{'questionId':'data','text':'PDF'}]})
        assert status == 409 and 'PLAN_REVISION_CONFLICT' in error['error']
    check_api(rt, check)

def test_mode_pause_retains_unanswered_questions(env):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id':'data','field':'data','text':'Dữ liệu nào?'}])
    async def check(request):
        status, result = await request('PUT','/sessions/'+run['sessionId']+'/plan-mode',{'on':False})
        assert status == 200 and result['run']['status'] == 'paused'
        status, result = await request('PUT','/sessions/'+run['sessionId']+'/plan-mode',{'on':True})
        assert status == 200 and result['run']['status'] == 'needs_user'
        assert result['run']['questions'][0]['text'] == 'Dữ liệu nào?'
    check_api(rt, check)

def test_ready_approval_and_execute_are_separate_exact_hash(env):
    rt, flow, run = env
    run = ready(rt, flow, run)
    flow.db.execute('DELETE FROM plan_continuations'); flow.db.commit()
    async def check(request):
        body = run['document'] | {'action':'approve','revision':run['revision'],'invocationId':'approve'}
        status, result = await request('POST','/plans/runs/'+run['runId']+'/actions',body)
        assert status == 200 and result['run']['phase'] == 'approved'
        assert not result['queued'] and not rt.tasks
        current = result['run']
        status, same = await request('POST','/plans/runs/'+run['runId']+'/actions',body)
        assert status == 200 and same == result
        status, error = await request('POST','/plans/execute', current['document'] | {
            'revision':current['revision'],'invocationId':'execute'})
        # The fixture disk differs from the snapshot: execute must reread and refuse.
        assert status == 400 and 'PLAN_EXECUTE_STALE' in error['error']
        assert not rt.tasks
    check_api(rt, check)

def test_semantic_gate_cannot_be_disabled_by_proxy_config(env, monkeypatch):
    rt, flow, run = env
    monkeypatch.setenv('BOXFOX_PLAN_VERIFY','off')
    async def check(request):
        status, error = await request('POST','/plans/runs/'+run['runId']+'/actions', {
            'action':'approve','revision':run['revision'],'invocationId':'bad'})
        assert status == 400 and ('PLAN_NOT_READY' in error['error'] or 'PLAN_REVIEW_STALE' in error['error'])
        assert not rt.store.plan_review('clinical',1)
    check_api(rt, check)

def test_legacy_execute_requires_adoption_keeps_history(env):
    rt, flow, run = env
    rt.store.record_plan_review('legacy',1,'approved',source='plan-tab')
    async def check(request):
        status, error = await request('POST','/plans/execute',{'identity':'legacy','version':1,'contentHash':'hash'})
        assert status == 400 and 'PLAN_LEGACY_ADOPTION_REQUIRED' in error['error']
        assert rt.store.plan_review('legacy',1)['decision'] == 'approved'
    check_api(rt, check)


def test_resume_action_reenters_mode_and_restores_wait_without_model_turn(env):
    rt, flow, run = env
    run = scope(rt, flow, run, 'ask', questions=[{'id': 'data', 'field': 'data', 'text': 'Dữ liệu nào?'}])
    flow.set_mode(rt, run['sessionId'], False)
    run = flow.get(run['runId'])
    async def check(request):
        status, result = await request('POST', '/plans/runs/'+run['runId']+'/actions', {
            'action': 'resume', 'revision': run['revision'], 'invocationId': 'resume'})
        assert status == 200 and result['run']['status'] == 'needs_user'
        assert pw.mode(rt.store.get(run['sessionId']))['on']
        assert not result['queued'] and not rt.tasks
    check_api(rt, check)


@pytest.mark.parametrize('action,status', [('pause', 'paused'), ('cancel', 'cancelled')])
def test_owner_pause_or_cancel_is_not_rejected_by_stop_checkpoint(env, action, status):
    rt, flow, run = env
    class WaitingModel:
        async def complete(self, *args, **kwargs):
            await asyncio.Event().wait()
        async def model_metadata_map(self):
            return {}
    rt.client = WaitingModel()
    async def check():
        await rt.submit(run['sessionId'], 'Tiếp tục', invocation_id='active')
        current = flow.get(run['runId'])
        async with TestServer(create_app(rt)) as server:
            async with ClientSession(headers=HEADERS) as client:
                async with client.post(server.make_url('/api/agent/plans/runs/'+run['runId']+'/actions'), json={
                    'action': action, 'revision': current['revision'], 'invocationId': action}) as response:
                    result = await response.json()
                    assert response.status == 200, result
                    assert result['run']['status'] == status
            assert flow.get(run['runId'])['status'] == status
    asyncio.run(check())
