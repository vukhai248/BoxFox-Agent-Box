"""H7 runtime: fixtures local, không price override trên router thật."""
import asyncio
import copy

import pytest

from switch_isolation import isolate_off
from agentbox.agent_core import execution_kernel, usage_surface
from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

PRICE = {'input': 5, 'output': 25, 'cachedInput': 1, 'cacheWriteInput': 5,
         'unit': 'per_million_tokens', 'source': 'manual', 'asOf': '2026-10-04'}


class Client:
    def __init__(self):
        self.price = copy.deepcopy(PRICE)
        self.calls = 0
        self.error = None
        self.usage = {'prompt_tokens': 100, 'completion_tokens': 20,
                      'prompt_tokens_details': {'cached_tokens': 40},
                      'completion_tokens_details': {'reasoning_tokens': 10}}
        self.meta = {'connectionId': 'c1', 'modelId': 'm1'}

    async def snapshot(self):
        return {'connections': [{'id': 'c1', 'providerId': 'opencode', 'revision': 1,
                                 'models': [{'id': 'm1', 'contextWindow': 1000, 'pricing': self.price}]}]}

    async def complete(self, messages, tools, route, **kwargs):
        self.calls += 1
        self.messages = messages
        if self.error:
            raise self.error
        return {'boxfox': self.meta, 'usage': self.usage,
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'fixture'}}]}


class Executor:
    async def execute(self, name, args, sid):
        return {'content': 'fixture'}

    async def cleanup(self, sid):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_USAGE_LEDGER', 'on')
    monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    client = Client()
    rt = HarnessRuntime(store, Executor(), client)
    session = rt.create({'connectionId': 'c1', 'modelId': 'm1', 'skills': []})
    yield store, rt, session, client
    store.close()


def call(env, purpose='completion'):
    store, rt, session, client = env
    return asyncio.run(rt.complete_model(session['id'], session['messages'], [],
                                         session['config']['route'], max_tokens=100, purpose=purpose))


def rows(env):
    store, rt, session, client = env
    return usage_surface.service(rt).calls(session['id'])['items']


def adaptive(env):
    store, rt, session, _ = env
    store.update_config(session['id'], dict(session['config'], harnessPolicy={
        'schema': execution_kernel.POLICY_SCHEMA, 'mode': 'adaptive'}))


def allocate(env, amount=.01):
    store, rt, session, _ = env
    ledger = usage_surface.service(rt)
    ledger.reserve('root-budget', session['id'], 1, 'fixture-consent',
                   {'amount': amount, 'ceiling': amount}, 'fixture-root')
    config = store.get(session['id'])['config']
    store.update_config(session['id'], dict(config, harnessAllocationId='root-budget'))
    return ledger


def test_off_legacy_has_no_rows(env, monkeypatch):
    isolate_off(monkeypatch, 'BOXFOX_USAGE_LEDGER')
    call(env)
    assert env[3].calls == 1
    assert env[0].db.execute("SELECT name FROM sqlite_master WHERE name='harness_usage'").fetchone() is None


def test_each_request_costs_once_with_cache_and_reasoning_overlap(env):
    call(env)
    call(env, 'summary')
    call(env, 'recovery')
    data = rows(env)
    assert len(data) == 3
    assert {r['purpose'] for r in data} == {'completion', 'summary', 'recovery'}
    assert all(r['amount'] == .00084 for r in data)  # 60*5 + 40*1 + 20*25, /1M
    assert all(r['reasoningTokens'] == 10 and r['certainty'] == 'estimated' for r in data)
    assert len({r['callKey'] for r in data}) == 3


@pytest.mark.parametrize('usage', [None, {'prompt_tokens': 10}, {'completion_tokens': 10}])
def test_missing_usage_is_unknown_not_free(env, usage):
    env[3].usage = usage
    call(env)
    assert rows(env)[0]['amount'] is None
    assert rows(env)[0]['certainty'] == 'unknown'


def test_unknown_route_price_and_provenance_never_guess(env):
    env[3].meta = {'connectionId': 'another', 'modelId': 'm1'}
    call(env)
    assert rows(env)[0]['priceSnapshot'] is None
    assert rows(env)[0]['amount'] is None


@pytest.mark.parametrize('exc', [ConnectionError('fixture'), asyncio.CancelledError()])
def test_failed_request_records_unknown_usage_and_retains_liability(env, exc):
    ledger = allocate(env)
    env[3].error = exc
    with pytest.raises(type(exc)):
        call(env)
    assert rows(env)[0]['amount'] is None
    unsettled = ledger.unsettled(env[2]['id'])
    assert len([r for r in unsettled if r['allocationId'].startswith('call-')]) == 1
    assert ledger.get_allocation('root-budget')['remaining'] == .0025


def test_reservation_releases_only_unused_amount(env):
    ledger = allocate(env)
    call(env)
    assert ledger.get_allocation('root-budget')['remaining'] == .00916
    assert len(rows(env)) == 1


def test_ceiling_blocks_before_model_and_spawn_does_not_reset_ceiling(env):
    ledger = allocate(env, amount=.0075)
    call(env)
    with pytest.raises(ContractError, match='USAGE_CEILING_EXCEEDED'):
        call(env)
    assert env[3].calls == 1
    child = env[0].create({'route': env[2]['config']['route']}, role='explore', parent_id=env[2]['id'])
    with pytest.raises(ContractError, match='USAGE_CEILING_EXCEEDED'):
        asyncio.run(env[1].complete_model(child['id'], [], [], env[2]['config']['route'], max_tokens=100))
    assert env[3].calls == 1
    assert ledger.get_allocation('root-budget')['remaining'] == .00666


def test_adaptive_no_allocation_blocks_paid_request(env):
    adaptive(env)
    with pytest.raises(ContractError, match='USAGE_NO_CONSENT'):
        call(env)
    assert env[3].calls == 0


def test_adaptive_confirmed_free_route_passes_and_mock_price_restores(env):
    adaptive(env)
    env[3].price = {**PRICE, 'input': 0, 'output': 0, 'cachedInput': 0, 'cacheWriteInput': 0}
    call(env)
    assert rows(env)[0]['amount'] == 0
    env[3].price = copy.deepcopy(PRICE)
    with pytest.raises(ContractError, match='USAGE_NO_CONSENT'):
        call(env)
    assert env[3].calls == 1


def test_adaptive_ledger_kill_switch_cannot_fallback_legacy(env, monkeypatch):
    adaptive(env)
    isolate_off(monkeypatch, 'BOXFOX_USAGE_LEDGER')
    with pytest.raises(ContractError, match='USAGE_LEDGER_DISABLED'):
        call(env)
    assert env[3].calls == 0


def test_other_root_allocation_cannot_be_used(env):
    store, rt, session, client = env
    other = store.create({})
    ledger = usage_surface.service(rt)
    ledger.reserve('other-budget', other['id'], 1, 'other-consent',
                   {'amount': 1, 'ceiling': 1}, 'other-create')
    store.update_config(session['id'], dict(session['config'], harnessAllocationId='other-budget'))
    with pytest.raises(ContractError, match='USAGE_ALLOCATION_UNKNOWN'):
        call(env)
    assert client.calls == 0


def test_real_runtime_turn_produces_ledger_row(env):
    store, rt, session, client = env
    async def drive():
        await rt.submit(session['id'], 'fixture')
        await rt.tasks[session['id']]
    asyncio.run(drive())
    assert store.get(session['id'])['status'] == 'completed'
    assert len(rows(env)) == client.calls == 1


def test_snapshot_error_preserves_legacy_unknown_and_blocks_adaptive(env):
    async def unavailable():
        raise ConnectionError('metadata unavailable')
    env[3].snapshot = unavailable
    call(env)
    assert rows(env)[0]['amount'] is None
    adaptive(env)
    with pytest.raises(ContractError, match='USAGE_NO_CONSENT'):
        call(env)
    assert env[3].calls == 1


def test_flag_revoked_during_snapshot_blocks_adaptive_request(env, monkeypatch):
    adaptive(env)
    original = env[3].snapshot
    async def snapshot():
        monkeypatch.setenv('BOXFOX_ADAPTIVE_HARNESS', 'off')
        return await original()
    env[3].snapshot = snapshot
    with pytest.raises(ContractError, match='ADAPTIVE_DISABLED'):
        call(env)
    assert env[3].calls == 0


def test_usd_price_cannot_consume_non_usd_allocation(env):
    store, rt, session, client = env
    ledger = usage_surface.service(rt)
    ledger.reserve('eur-budget', session['id'], 1, 'fixture-consent',
                   {'amount': 1, 'ceiling': 1, 'currency': 'EUR'}, 'fixture-eur')
    store.update_config(session['id'], dict(session['config'], harnessAllocationId='eur-budget'))
    with pytest.raises(ContractError, match='USAGE_CURRENCY_MISMATCH'):
        call(env)
    assert client.calls == 0


def research_lead(env, monkeypatch, *, admit=True):
    from agentbox.agent_core import research_gateway
    monkeypatch.setenv(research_gateway.SWITCH, 'on')
    store, rt, session, client = env
    config = store.get(session['id'])['config']
    # Trần output 100 giữ upper bound admission (contextWindow fixture 1000) trong ngân sách .01.
    store.update_config(session['id'], dict(config, maxTokens=100,
                                            tools=list(set(config['tools']) | research_gateway.GATEWAY_TOOLS)))
    request = {'schema': research_gateway.SCHEMA, 'goal': 'fixture evidence', 'decisionContext': 'fixture',
               'questions': ['what evidence?'], 'constraints': [], 'inputRefs': [],
               'desiredOutput': 'versioned report', 'freshnessRequirement': 'as of request',
               'permissionEnvelopeRef': None, 'allocationRef': None, 'consentRef': None}
    receipt = asyncio.run(rt.dispatch(store.get(session['id']), 'research_job_submit',
                                      {'request': request, 'invocationId': 'fixture-submit'}))
    lead = store.get(receipt['ownerControllerId'])
    if admit:
        # Đường canonical duy nhất mở model: prepare async rồi resume; chặn lượt nền của lead.
        monkeypatch.setattr(rt, 'start', lambda *args, **kwargs: None)
        asyncio.run(rt.dispatch(store.get(session['id']), 'research_job_control', {
            'jobId': receipt['researchJobId'], 'expectedRevision': receipt['revision'],
            'invocationId': 'fixture-resume', 'action': 'resume', 'reason': 'fixture admission'}))
        assert research_gateway._binding(store, run_id=receipt['researchJobId'])['state'] == 'running'
    return lead, request


def test_research_financial_root_stays_shared_despite_separate_control(env, monkeypatch):
    ledger = allocate(env)
    lead, request = research_lead(env, monkeypatch)
    assert lead['parent_id'] is None
    assert usage_surface.root_session(env[1], lead['id'])['id'] == env[2]['id']
    asyncio.run(env[1].complete_model(lead['id'], [], [], lead['config']['route'], max_tokens=100))
    assert ledger.get_allocation('root-budget')['remaining'] == .00916
    assert rows(env)[0]['runId'] == lead['id']


def test_research_free_admission_requires_fresh_backend_snapshot_not_fake_refs(env, monkeypatch):
    lead, request = research_lead(env, monkeypatch, admit=False)
    rt = env[1]
    env[3].price = {**PRICE, 'input': 0, 'output': 0, 'cachedInput': 0, 'cacheWriteInput': 0}
    assert rt.research_admission(lead, request) is False
    asyncio.run(rt.prepare_research_admission(lead, request))
    assert rt.research_admission(lead, request) is True
    assert rt.research_admission(lead, dict(request, consentRef='forged')) is False
    assert rt.research_admission(lead, dict(request, permissionEnvelopeRef='forged')) is False


def test_plain_child_cannot_evade_root_adaptive_consent(env):
    adaptive(env)
    child = env[0].create({'route': env[2]['config']['route']}, role='explore', parent_id=env[2]['id'])
    with pytest.raises(ContractError, match='USAGE_NO_CONSENT'):
        asyncio.run(env[1].complete_model(child['id'], [], [], env[2]['config']['route'], max_tokens=100))
    assert env[3].calls == 0


def test_manual_compact_goes_through_the_usage_seam(env, monkeypatch):
    """`/compact` do người dùng gọi cũng đi qua seam chung: một hàng usage, không gọi thẳng client."""
    from agentbox.agent_core.compression import ContextCompressor

    store, rt, session, client = env

    async def compact(self, messages, tools, summarize, force=False, usage=None):
        await summarize(messages, max_tokens=64)
        return [messages[0], {'role': 'assistant', 'content': 'gộp'}], {
            'kind': 'compression', 'strategy': 'summary', 'beforeEstimate': 2000,
            'afterEstimate': 20, 'budgetTokens': 10000}

    monkeypatch.setattr(ContextCompressor, 'compact', compact)
    asyncio.run(rt.submit(session['id'], '/compact'))
    assert client.calls == 1, 'lượt tóm tắt của /compact phải đi qua seam, không gọi thẳng client'
    assert [row['purpose'] for row in rows(env)] == ['summary']
