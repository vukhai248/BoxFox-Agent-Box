"""H8 runtime parity, repeat denial, restart and guidance: no model calls online."""
import asyncio

import pytest

from agentbox.agent_core import adaptive_surface, execution_kernel, recovery_policy
from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.agent_core.runtime import HarnessRuntime, ORCHESTRATOR_SOP_GUIDANCE
from agentbox.memory.session_store import SessionStore


class Executor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid, **identity):
        self.calls.append((name, args))
        return {'content': 'read fixture'}

    async def cleanup(self, sid):
        pass


class Client:
    def __init__(self):
        self.calls = 0

    async def snapshot(self):
        return {'connections': [{'id': 'c1', 'providerId': 'opencode', 'models': [
            {'id': 'free', 'pricing': {'source': 'documented', 'input': 0, 'output': 0}}]}]}

    async def complete(self, messages, tools, route, **kwargs):
        self.calls += 1
        self.messages = messages
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': 'fixture'}}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1},
                'boxfox': {'connectionId': 'c1', 'modelId': 'free'}}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    executor, client = Executor(), Client()
    rt = HarnessRuntime(store, executor, client)
    session = rt.create({'skills': [], 'tools': ['file_read'], 'connectionId': 'c1', 'modelId': 'free'})
    yield store, rt, session, executor, client
    store.close()


def pin(env):
    store, rt, session, *_ = env
    store.update_config(session['id'], dict(session['config'], harnessPolicy={
        'schema': execution_kernel.POLICY_SCHEMA, 'mode': 'adaptive'}))


def test_legacy_decision_does_not_create_state(env):
    assert adaptive_surface.decide(env[1], env[2]['id']) is None
    assert env[0].db.execute("SELECT name FROM sqlite_master WHERE name='harness_adaptive_state'").fetchone() is None


def test_decision_has_reasons_evidence_alternatives_and_unknown_effort(env):
    pin(env)
    result = adaptive_surface.decide(env[1], env[2]['id'])
    assert result['action'] == 'continue'
    assert result['reason'] and result['evidenceRefs'] == [] and result['alternatives']
    assert result['budget']['outputTokens'] is None  # no invented output capability


def test_repeat_failure_is_denied_until_real_new_evidence(env):
    pin(env)
    store, rt, session, executor, _ = env
    sid = session['id']
    adaptive_surface.after_tool(rt, sid, 'file_read', {'path': 'missing'}, {'is_error': True})
    with pytest.raises(ContractError, match='ADAPTIVE_LOOP_REPEAT'):
        asyncio.run(rt.dispatch(session, 'file_read', {'path': 'missing'}))
    assert executor.calls == []
    asyncio.run(rt.dispatch(session, 'file_read', {'path': 'other'}))
    assert adaptive_surface.before_tool(rt, sid, 'file_read', {'path': 'missing'})['action'] == 'continue'
    assert len(executor.calls) == 1


def test_repeat_successful_read_is_not_a_failure_loop(env):
    pin(env)
    for _ in range(2):
        asyncio.run(env[1].dispatch(env[2], 'file_read', {'path': 'same'}))
    assert len(env[3].calls) == 2


def test_longer_text_and_tool_count_do_not_reset_failure(env):
    pin(env)
    rt, sid = env[1], env[2]['id']
    adaptive_surface.after_tool(rt, sid, 'file_read', {'path': 'missing'}, {'is_error': True})
    adaptive_surface.after_tool(rt, sid, 'skill_view', {}, {'content': 'many words ' * 100})
    with pytest.raises(ContractError, match='ADAPTIVE_LOOP_REPEAT'):
        adaptive_surface.before_tool(rt, sid, 'file_read', {'path': 'missing'})


def test_restart_keeps_failure_signature(env):
    pin(env)
    rt, sid = env[1], env[2]['id']
    adaptive_surface.after_tool(rt, sid, 'file_read', {'path': 'missing'}, {'is_error': True})
    restarted = HarnessRuntime(env[0], env[3], env[4])
    with pytest.raises(ContractError, match='ADAPTIVE_LOOP_REPEAT'):
        adaptive_surface.before_tool(restarted, sid, 'file_read', {'path': 'missing'})


def test_kill_switch_blocks_new_requests_keeps_state_readable(env, monkeypatch):
    pin(env)
    adaptive_surface.decide(env[1], env[2]['id'])
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'off')
    with pytest.raises(ContractError, match='ADAPTIVE_DISABLED'):
        asyncio.run(env[1].complete_model(env[2]['id'], [], [], env[2]['config']['route']))
    assert env[4].calls == 0
    assert adaptive_surface.state(env[1], env[2]['id']) == ([], [])


def test_dynamic_adaptive_guidance_does_not_rewrite_original_intent(env):
    pin(env)
    messages = [{'role': 'system', 'content': ORCHESTRATOR_SOP_GUIDANCE + '\nOWNER KEEP THIS'},
                {'role': 'user', 'content': 'original intent'}]
    asyncio.run(env[1].complete_model(env[2]['id'], messages, [], env[2]['config']['route']))
    sent = env[4].messages
    assert adaptive_surface.GUIDANCE in sent[0]['content']
    assert 'Hierarchical 5-Phase Execution Workflow' not in sent[0]['content']
    assert 'OWNER KEEP THIS' in sent[0]['content']
    assert sent[1] == messages[1]
    assert ORCHESTRATOR_SOP_GUIDANCE in messages[0]['content']


def test_unknown_recovery_denies_retry_but_transport_retry_is_allowed():
    assert recovery_policy.may_retry(recovery_policy.decision('NEW_UNKNOWN_CODE')) is False
    assert recovery_policy.may_retry(recovery_policy.decision('UPSTREAM_HTTP_503')) is True
    assert recovery_policy.may_retry(recovery_policy.decision('WORK_CAPABILITY_REVOKED')) is False
    assert recovery_policy.may_retry(recovery_policy.decision('UPSTREAM_TIMEOUT')) is False


def test_stop_revocation_wins_over_adaptive_goal_or_branch(env):
    pin(env)
    result = adaptive_surface.decide(env[1], env[2]['id'], {'revoked': True, 'goalMet': True,
                                                         'branch': {'needed': True}})
    assert result['action'] in ('stop', 'blocked')
    assert 'ADAPTIVE_EPOCH_REVOKED' in result['reason']


def test_real_runtime_adaptive_turn_is_measured_and_decided(env):
    pin(env)
    async def drive():
        await env[1].submit(env[2]['id'], 'small fixture task')
        await env[1].tasks[env[2]['id']]
    asyncio.run(drive())
    assert env[0].get(env[2]['id'])['status'] == 'completed'
    assert env[4].calls == 1
    assert any(e['type'] == 'harness_decision' for e in env[0].events(env[2]['id']))


@pytest.mark.parametrize('deny', [False, True])
def test_recovery_gate_is_live_and_only_removes_retries(env, monkeypatch, deny):
    from agentbox.agent_core import failures
    original_advice = failures.retry_advice
    def immediate(*args, **kwargs):
        advice = original_advice(*args, **kwargs)
        return dict(advice, delay=0) if advice else advice
    monkeypatch.setattr(failures, 'retry_advice', immediate)
    original = env[4].complete
    first = True
    async def flaky(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            env[4].calls += 1
            raise RuntimeError('Router HTTP 503: fixture transport failure')
        return await original(*args, **kwargs)
    env[4].complete = flaky
    if deny:
        original_decision = recovery_policy.decision
        monkeypatch.setattr(recovery_policy, 'decision', lambda *a, **kw: original_decision('NEW_UNKNOWN_CODE'))
    async def drive():
        await env[1].submit(env[2]['id'], 'fixture')
        await env[1].tasks[env[2]['id']]
    asyncio.run(drive())
    assert env[4].calls == (1 if deny else 2)
    assert env[0].get(env[2]['id'])['status'] == ('failed' if deny else 'completed')
    assert any(e['type'] == 'recovery_decision' for e in env[0].events(env[2]['id']))
