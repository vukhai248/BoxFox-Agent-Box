"""W3: preserve useful partial output; recover an empty answer once at the same budget."""
import asyncio
import copy
import json

from agentbox.agent_core.limits import TRUNCATED_OUTPUT_NOTICE_CODE
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
import pytest


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


def answer(text='done', calls=None, finish='stop', usage=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': usage if usage is not None else {'prompt_tokens': 10, 'completion_tokens': 2}}


def truncated(text='nửa câu trả lời', output_tokens=4096):
    return answer(text, finish='length', usage={'prompt_tokens': 900, 'completion_tokens': output_tokens})


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append({'messages': copy.deepcopy(messages), 'tools': copy.deepcopy(tools),
                              'max_tokens': max_tokens})
        return next(self.responses)


class FixtureExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args))
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def run_turn(tmp_path, client, values=None, prompt='làm việc'):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create(values or {'skills': []})

    async def run():
        runtime.start(session['id'], prompt)
        return await runtime.tasks[session['id']]

    return store, runtime, session, asyncio.run(run())


def notices(store, sid, code):
    return [e['data'] for e in store.events(sid) if e['type'] == 'notice' and e['data'].get('code') == code]


def turn_ends(store, sid):
    return [e['data'] for e in store.events(sid) if e['type'] == 'turn_end']


# --------------------------------------------------------------------------- #
# Xin ít token hơn, bỏ bộ tool: một lần, và chỉ khi chưa có tool call nào
# --------------------------------------------------------------------------- #

def test_an_empty_length_answer_is_retried_once_without_halving_budget(tmp_path):
    client = FixtureModel([truncated(''), answer('câu trả lời trọn vẹn')])
    store, runtime, session, result = run_turn(tmp_path, client)

    assert len(client.requests) == 2, 'một lần thử lại, không phải một vòng lặp'
    retry = client.requests[1]
    assert retry['max_tokens'] == 4096
    assert retry['tools'] == []
    assert client.requests[0]['max_tokens'] == 4096, 'lần gọi đầu giữ nguyên như trước'
    assert retry['messages'][-1]['role'] == 'user'
    assert len(retry['messages']) == len(client.requests[0]['messages']) + 1
    assert result == 'câu trả lời trọn vẹn', 'câu trả lời thử lại là kết quả của lượt'
    assert store.get(session['id'])['status'] == 'completed'
    assert notices(store, session['id'], TRUNCATED_OUTPUT_NOTICE_CODE) == [], \
        'thử lại thành công thì không có gì phải báo là dở'
    assert turn_ends(store, session['id'])[-1]['status'] == 'completed'
    assert runtime.partial_turn(session['id']) is None, 'thử lại thành công ⇒ không có mã lý do nào'
    assert turn_ends(store, session['id'])[-1]['outputTokens'] == 4098
    assert turn_ends(store, session['id'])[-1]['completionAttempts'] == 2
    store.close()


def test_healthy_tool_calls_keep_normal_execution(tmp_path):
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'x'})]), answer('xong')])
    store, _runtime, session, result = run_turn(tmp_path, client)
    assert len(client.requests) == 2, 'không có lần gọi thừa nào'
    assert client.requests[1]['tools'] != [], 'lượt hai là lượt bình thường, có tool schema'
    assert result == 'xong' and store.get(session['id'])['status'] == 'completed'
    store.close()


# --------------------------------------------------------------------------- #
# Vẫn bị cắt sau khi thử lại: lượt là `partial`, và điều đó là bền
# --------------------------------------------------------------------------- #

def test_useful_partial_text_is_preserved_without_replaying_history(tmp_path):
    client = FixtureModel([truncated('phần đầu của câu trả lời', 4096)])
    store, runtime, session, result = run_turn(tmp_path, client)
    sid = session['id']

    assert len(client.requests) == 1
    assert isinstance(result, str) and result.startswith('phần đầu'), \
        '_run vẫn trả TEXT cho người gọi, không phải một hình dạng của client'
    stored = store.get(sid)
    assert stored['status'] == 'completed', 'từ vựng trạng thái phiên không đổi'
    assert stored['messages'][-1] == {'role': 'assistant', 'content': 'phần đầu của câu trả lời'}
    rows = notices(store, sid, TRUNCATED_OUTPUT_NOTICE_CODE)
    assert len(rows) == 1, 'đúng một notice cho một lượt'
    assert rows[0]['partial'] is True
    assert rows[0]['outputTokens'] == 4096
    assert runtime.partial_turn(sid) == TRUNCATED_OUTPUT_NOTICE_CODE, \
        'B5: hàm trả MÃ LÝ DO, không phải cờ đúng/sai'
    end = turn_ends(store, sid)[-1]
    assert end['status'] == 'partial' and end['finishReason'] == 'length'
    assert end['outputTokens'] == 4096
    attempts = [e['data'] for e in store.events(sid) if e['type'] == 'completion_attempt']
    assert attempts[0]['partialText'] == result
    # `finish` vẫn nói `completed` (từ vựng trạng thái không đổi), còn sự thật dở nằm ở `turn_end`
    # + notice. T2 chỉ THÊM số lượt vào payload, không đổi `status`.
    finishes = [e['data'] for e in store.events(sid) if e['type'] == 'finish']
    assert [row['status'] for row in finishes] == ['completed']
    assert [row['turn'] for row in finishes] == [1]
    store.close()


# --------------------------------------------------------------------------- #
# Cha đọc kết quả con: `partial`, không phải `failed` và không phải "xong"
# --------------------------------------------------------------------------- #

def test_the_parent_sees_a_truncated_child_as_partial(tmp_path):
    # Bề mặt 7 đã xoá: vai `research` bị cổng Research chặn từ main; `explore` là vai main còn giao được.
    client = FixtureModel([answer(calls=[call('delegate_task', {'role': 'explore', 'goal': 'tra cứu'})]),
                           truncated('phần đầu của báo cáo', 4096),
                           answer('câu trả lời cuối của cha')])
    store, runtime, session, result = run_turn(tmp_path, client, prompt='nhờ chuyên gia')
    sid = session['id']

    child_events = [e['data'] for e in store.events(sid) if e['type'] == 'child']
    assert child_events[0]['status'] == 'started' and len(child_events) == 2
    child = child_events[-1]  # hàng thứ hai là kết quả cuối cùng cha dùng
    assert child['status'] == 'partial'
    assert child['reason'] == TRUNCATED_OUTPUT_NOTICE_CODE
    assert child['is_error'] is True, 'cha phải biết đây không phải một kết quả trọn vẹn'
    assert child['last_error'] == TRUNCATED_OUTPUT_NOTICE_CODE
    assert child['summary'] == 'phần đầu của báo cáo', 'diagnostic nằm ở metadata, không nối vào báo cáo'
    assert child['tools_run'] == []
    tool_result = next(json.loads(m['content']) for m in store.get(sid)['messages'] if m['role'] == 'tool')
    assert tool_result['summary'] == child['summary'] and tool_result['status'] == 'partial'

    child_row = store.get(child['sessionId'])
    assert child_row['status'] == 'completed', 'hàng `sessions` của con đổi từ vựng: KHÔNG'
    assert turn_ends(store, child['sessionId'])[-1]['status'] == 'partial'
    assert store.get(sid)['status'] == 'completed', 'lượt cha vẫn xong bình thường'
    assert result == 'câu trả lời cuối của cha'
    store.close()


def test_partial_report_keeps_source_url_and_actual_tool_timeline_separate(tmp_path):
    report = '## Nguồn đã đọc\nhttps://example.org/tai-lieu'
    client = FixtureModel([answer(calls=[call('delegate_task', {'role': 'explore', 'goal': 'đọc app.py'})]),
                           answer(calls=[call('file_read', {'path': 'app.py'})]),
                           truncated(report), answer('Đã nhận bản dở.')])
    store, runtime, session, result = run_turn(tmp_path, client)
    try:
        child = [e['data'] for e in store.events(session['id']) if e['type'] == 'child'][-1]
        assert child['summary'] == report and child['summary'].endswith('/tai-lieu')
        assert '[Diagnostic:' not in child['summary'] and 'tools_run=' not in child['summary']
        assert child['status'] == 'partial' and child['last_error'] == TRUNCATED_OUTPUT_NOTICE_CODE
        assert child['tools_run'] == ['file_read']
        assert len([e for e in store.events(child['sessionId']) if e['type'] == 'tool_start']) == 1
        assert store.get(child['sessionId'])['messages'][-1]['content'] == report
    finally:
        store.close()


def test_incomplete_calls_never_execute_even_when_json_is_valid(tmp_path):
    for finish in ('length', 'stream_incomplete'):
        response = answer('nguồn: https://example.org/a', calls=[call('file_read', {'path':'x'})])
        response['choices'][0]['finish_reason'] = finish
        client = FixtureModel([response])
        store, runtime, session, result = run_turn(tmp_path/finish, client)
        try:
            events = store.events(session['id'])
            assert not [e for e in events if e['type'] == 'tool_start']
            assert len(client.requests) == 1
            attempt = next(e['data'] for e in events if e['type'] == 'completion_attempt')
            assert attempt['unexecutedToolCalls'] == response['choices'][0]['message']['tool_calls']
            assert 'tool_calls' not in store.get(session['id'])['messages'][-1]
            assert runtime.partial_turn(session['id'])
            assert result.endswith('/a')
        finally:
            store.close()


def test_empty_recovery_is_bounded_and_usage_is_not_fabricated(tmp_path):
    first = truncated('', 8192)
    second = truncated('bản dở', 8192)
    first['usage'] = None
    client = FixtureModel([first, second])
    store, runtime, session, result = run_turn(tmp_path, client, {'skills':[],'maxTokens':8192})
    try:
        assert [r['max_tokens'] for r in client.requests] == [8192,8192]
        assert result == 'bản dở'
        end = turn_ends(store, session['id'])[-1]
        assert 'outputTokens' not in end
        assert end['knownOutputTokens'] == 8192 and end['completionUsageComplete'] is False
        assert runtime.partial_turn(session['id']) == TRUNCATED_OUTPUT_NOTICE_CODE
    finally:
        store.close()


def test_refusal_is_not_retried(tmp_path):
    response = answer('', finish='content_filter')
    response['choices'][0]['message']['refusal'] = 'fixture refusal'
    client = FixtureModel([response])
    store, runtime, session, _ = run_turn(tmp_path, client)
    try:
        assert len(client.requests) == 1
        assert store.get(session['id'])['status'] == 'failed'
        assert any(e['type'] == 'error' and e['data']['code'] == 'UPSTREAM_REFUSAL'
                   for e in store.events(session['id']))
    finally:
        store.close()


def test_reasoning_only_completion_stays_partial_after_one_recovery(tmp_path):
    response = answer('')
    response['choices'][0]['message']['reasoning_content'] = 'reasoning fixture'
    client = FixtureModel([response, response])
    store, runtime, session, _ = run_turn(tmp_path, client)
    try:
        assert len(client.requests) == 2
        assert runtime.partial_turn(session['id']) == 'PROVIDER_REASONING_ONLY'
        attempts = [e['data'] for e in store.events(session['id']) if e['type'] == 'completion_attempt']
        assert [a['reasoningChars'] for a in attempts] == [17,17]
    finally:
        store.close()


def test_long_history_empty_completion_does_not_replay(tmp_path):
    response = truncated('')
    client = FixtureModel([response])
    store, runtime, session, _ = run_turn(tmp_path, client,
        {'skills':[], 'contextWindow':200000}, prompt='x'*70000)
    try:
        assert len(client.requests) == 1
        assert runtime.partial_turn(session['id']) == TRUNCATED_OUTPUT_NOTICE_CODE
    finally:
        store.close()


def test_child_output_profile_inherits_owner_ceiling(tmp_path):
    client = FixtureModel([answer(calls=[call('delegate_task', {'role':'plan','goal':'fixture plan'})]),
                           answer('child result'), answer('main result')])
    store, runtime, session, _ = run_turn(tmp_path, client, {'skills':[], 'outputTokenCeiling':7000})
    try:
        child = next(e['data'] for e in store.events(session['id']) if e['type'] == 'child')
        config = store.get(child['sessionId'])['config']
        assert config['maxTokens'] == 16000 and config['outputTokenCeiling'] == 7000
        assert [r['max_tokens'] for r in client.requests] == [4096,7000,4096]
        assert store.get(session['id'])['config']['outputTokenCeiling'] == 7000
    finally:
        store.close()


def test_malformed_tool_json_never_reaches_executor(tmp_path):
    malformed = call('file_read', {'path':'x'})
    malformed['function']['arguments'] = '{"path":'
    client = FixtureModel([answer(calls=[malformed]), answer('Đã nhận lỗi input.')])
    store, runtime, session, _ = run_turn(tmp_path, client)
    try:
        assert not [c for c in runtime.executor.calls if c[0] == 'file_read']
        result = next(json.loads(m['content']) for m in store.get(session['id'])['messages'] if m['role'] == 'tool')
        assert result['is_error'] is True
    finally:
        store.close()


def test_main_research_delegation_is_refused_and_no_child_is_spawned(tmp_path, monkeypatch):
    """Bề mặt 7 đã xoá: main không còn đường giao vai `research`.

    Trước đây bài này chốt trần output research mặc định (`BOXFOX_RESEARCH_OUTPUT_TOKENS`,
    `[4096, 16000, 4096]`) đi thẳng từ main sang con. Nay lời gọi thành lỗi tool
    `RESEARCH_MAIN_READ_ONLY` mà model đọc được, không phiên con nào được sinh — trần research
    chỉ còn đi qua Research lead có binding (miền của `test_research_gateway.py`)."""
    monkeypatch.delenv('BOXFOX_RESEARCH_OUTPUT_TOKENS', raising=False)
    client = FixtureModel([answer(calls=[call('delegate_task', {'role':'research','goal':'fixture research'})]),
                           answer('main result')])
    store, runtime, session, result = run_turn(tmp_path, client)
    try:
        assert [r['max_tokens'] for r in client.requests] == [4096, 4096]
        assert not [e for e in store.events(session['id']) if e['type'] == 'child'], 'không có con nào được sinh'
        assert store.children_of(session['id']) == []
        payload = json.loads(next(m['content'] for m in store.get(session['id'])['messages'] if m['role'] == 'tool'))
        assert payload['is_error'] is True and payload['errorCode'] == 'TOOL_NOT_PERMITTED'
        assert 'RESEARCH_MAIN_READ_ONLY' in payload['error']
        assert result == 'main result'
    finally:
        store.close()
