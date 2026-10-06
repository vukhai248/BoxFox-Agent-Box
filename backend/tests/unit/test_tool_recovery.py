"""W1: recovery advice must match the tool failure, without a live provider."""
import asyncio
import json

import pytest

from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.tool_contracts import SCHEMAS, reflection_hint
from agentbox.agent_core.web import WebError
from agentbox.memory.session_store import SessionStore


@pytest.mark.parametrize('name,code', [
    ('web_search', 'WEB_SEARCH_UNAVAILABLE'),
    ('web_fetch', 'WEB_FETCH_FAILED'),
    ('read_source', 'WEB_FETCH_FAILED'),
    ('paper_citations', 'WEB_SEARCH_UNAVAILABLE'),
])
def test_provider_failure_does_not_advise_fixing_input_schema(name, code):
    hint = reflection_hint(name, code)
    assert code in hint
    assert 'Fix only that input' not in hint
    assert 'HTTP' in hint
    assert 'required=' not in hint


def test_search_capability_hint_names_configuration_and_an_available_alternative():
    hint = reflection_hint('web_search', 'WEB_SEARCH_UNAVAILABLE')
    assert 'configuration' in hint and 'web_fetch' in hint
    assert 'identical' in hint


def test_the_search_hint_never_tells_the_model_to_fix_the_query():
    """F05: cả hai mã tìm kiếm phải nói rõ đó không phải lỗi truy vấn."""
    unavailable = reflection_hint('web_search', 'WEB_SEARCH_UNAVAILABLE')
    assert 'do not re-run the same search' in unavailable
    assert 'report it and stop' in unavailable
    empty = reflection_hint('web_search', 'WEB_SEARCH_EMPTY')
    assert 'returned no rows' in empty and 'not a broken backend' in empty
    assert 'once' in empty, 'nới truy vấn MỘT lần, không lặp vô hạn'
    for hint in (unavailable, empty):
        assert 'Fix only that input' not in hint
        assert 'not fix missing keys' in hint or 'not a broken backend' in hint


def test_revision_hint_reads_status_before_reapplying_a_mutation():
    hint = reflection_hint('plan_scope', 'PLAN_REVISION_CONFLICT')
    assert 'action="status"' in hint
    assert 'latest' in hint and 'revision' in hint
    assert 'blindly' in hint


def test_partial_delegate_recovery_reads_result_metadata_instead_of_fixing_arguments():
    hint = reflection_hint('delegate_task')
    assert 'last_error' in hint and 'reason' in hint and 'status' in hint
    assert 'Fix only that input' not in hint


def test_invalid_delegate_arguments_still_get_schema_recovery():
    hint = reflection_hint('delegate_task', 'TURN_FAILED_VALUEERROR')
    assert 'Fix only that input' in hint and "required=['role', 'goal']" in hint


def test_input_error_keeps_the_existing_schema_recovery_contract():
    hint = reflection_hint('plan_scope', 'PLAN_BRIEF_INVALID')
    assert 'Fix only that input' in hint and 'required=' in hint
    assert 'brief:object' in hint
    assert 'required=' in reflection_hint('web_fetch', 'WEB_URL_INVALID')


def test_plan_question_schema_advertises_the_option_tradeoff_the_backend_stores():
    schema = next(s['function'] for s in SCHEMAS if s['function']['name'] == 'plan_scope')
    option = schema['parameters']['properties']['questions']['items']['properties']['options']['items']
    assert option['properties']['tradeoff']['type'] == 'string'
    assert option['required'] == ['id', 'label']


def test_real_tool_envelope_preserves_search_error_and_capability_recovery(tmp_path):
    class Model:
        calls = 0

        async def complete(self, messages, tools, route, **kwargs):
            self.calls += 1
            message = {'content': 'Không có nguồn tìm kiếm khả dụng.'}
            if self.calls == 1:
                message['tool_calls'] = [{'id': 'search', 'type': 'function', 'function': {
                    'name': 'web_search', 'arguments': json.dumps({'queries': ['mô hình tiếng Việt']})}}]
            return {'choices': [{'message': message,
                                 'finish_reason': 'tool_calls' if self.calls == 1 else 'stop'}]}

    class Web:
        async def run(self, name, args, sid, **kwargs):
            raise WebError('WEB_SEARCH_UNAVAILABLE',
                           'BOXFOX_SEARXNG_URL is not set; search provider refused HTTP 403')

    class Executor:
        async def execute(self, name, args, sid):
            assert name != 'web_search', 'web tools must remain on the host'
            return {'content': 'fixture'}

        async def cleanup(self, sid):
            pass

    store = SessionStore(tmp_path / 'sessions.sqlite')
    try:
        runtime = HarnessRuntime(store, Executor(), Model())
        runtime.web = Web()
        sid = runtime.create({'skills': []})['id']
        async def run():
            await runtime.start(sid, 'Tìm nguồn công khai')
        asyncio.run(run())
        result = next(json.loads(m['content']) for m in store.get(sid)['messages'] if m['role'] == 'tool')
        assert result['is_error'] is True and result['errorCode'] == 'WEB_SEARCH_UNAVAILABLE'
        assert 'HTTP 403' in result['error'] and 'BOXFOX_SEARXNG_URL' in result['error']
        assert 'configuration' in result['reflection_hint']
        assert 'Fix only that input' not in result['reflection_hint']
        assert result['recovery']['class'] == 'capability_gap'
        assert result['recovery']['action'] == 'checkpoint_and_ask'
        assert result['recovery']['replay'] is False
        assert store.get(sid)['status'] == 'completed'
    finally:
        store.close()
