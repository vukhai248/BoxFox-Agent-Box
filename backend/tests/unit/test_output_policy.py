"""W3 budget, completion, and usage contracts; no live provider calls."""
import pytest

from agentbox.agent_core import output_policy as policy


@pytest.mark.parametrize('role,expected', [('research',16000), ('plan',16000), ('design',16000),
                                         ('explore',None), ('review',None), ('debug',None)])
def test_producer_profiles(role, expected, monkeypatch):
    monkeypatch.delenv('BOXFOX_RESEARCH_OUTPUT_TOKENS', raising=False)
    monkeypatch.delenv('BOXFOX_DOCUMENT_OUTPUT_TOKENS', raising=False)
    assert policy.child_budget(role) == expected
    assert policy.child_budget(role, {'purpose':'produce','stage':'produce'}) == expected
    assert policy.child_budget(role, {'purpose':'review','stage':'review'}) is None


def test_configured_profiles_and_knowledge_lookup(monkeypatch):
    monkeypatch.setenv('BOXFOX_RESEARCH_OUTPUT_TOKENS', '12288')
    monkeypatch.setenv('BOXFOX_DOCUMENT_OUTPUT_TOKENS', '32000')
    assert policy.child_budget('research') == 12288
    assert policy.child_budget('research', task_kind='knowledge') is None
    assert policy.child_budget('plan') == 32000
    monkeypatch.setenv('BOXFOX_RESEARCH_OUTPUT_TOKENS', 'banana')
    with pytest.raises(ValueError, match='OUTPUT_BUDGET_INVALID'):
        policy.child_budget('research')


@pytest.mark.parametrize('value', [True,False,0,-1,'16000',None,64001,1.5])
def test_invalid_request_budget(value):
    with pytest.raises(ValueError, match='OUTPUT_BUDGET_INVALID'):
        policy.request_budget({'maxTokens':value})


def test_effective_caps_and_unknown_model():
    config = {'maxTokens':16000, 'outputTokenCeiling':12000,
              'route':{'modelId':'fixture'}, 'modelMetadata':{'id':'fixture','maxOutputTokens':9000}}
    assert policy.request_budget(config) == 9000
    config['contextWindow'] = 6000
    assert policy.request_budget(config, 1000) == 4488
    with pytest.raises(ValueError, match='OUTPUT_CONTEXT_EXHAUSTED'):
        policy.request_budget(config, 6000)
    assert policy.request_budget({'maxTokens':16000, 'modelMetadata':{'id':'unknown'}}) == 16000
    assert policy.request_budget({'maxTokens':16000, 'route':{'modelId':'other'},
                                  'modelMetadata':{'id':'fixture','maxOutputTokens':9000}}) == 16000
    assert policy.request_budget({}) == 4096


@pytest.mark.parametrize('finish,message,expected', [
    ('stop',{'content':'x'},'complete'), ('tool_calls',{'tool_calls':[{}]},'complete'),
    ('length',{'content':'x'},'output_limit'), ('max_tokens',{},'output_limit'),
    ('stream_incomplete',{'content':'x'},'stream_interrupted'), (None,{'content':'x'},'stream_interrupted'),
    ('stop',{'reasoning_content':'thinking'},'reasoning_only'), ('stop',{},'empty'),
    ('stop',{'refusal':'no'},'provider_refusal'), ('content_filter',{},'provider_refusal'),
    ('error',{'content':'failed'},'provider_error')])
def test_completion_reason(finish, message, expected):
    assert policy.completion_reason({'choices':[{'finish_reason':finish,'message':message}]}) == expected


def test_usage_does_not_invent_missing_counts():
    assert policy.usage_counts(None) == {'inputTokens':None,'outputTokens':None,'reasoningTokens':None}
    assert policy.usage_counts({'output_tokens':10,'output_tokens_details':{'reasoning_tokens':7}}) == {
        'inputTokens':None,'outputTokens':10,'reasoningTokens':7}
    assert policy.usage_counts({'completion_tokens':True,'prompt_tokens':-1})['outputTokens'] is None
