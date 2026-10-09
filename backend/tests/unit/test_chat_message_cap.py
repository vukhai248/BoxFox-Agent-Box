"""F08 — lượt chạy sống 2026-10-09: transcript vượt trần ĐẾM của nhà cung cấp.

Nhà cung cấp (`step-5-preview`) từ chối request bằng HTTP 400 *"Provide 1–200 chat messages."* —
một trần ĐẾM, không phải trần token. Bộ nén của harness chỉ đo token (`context_estimate` neo hoá
đơn thật: 141 471 < ngưỡng 176 332), nên nó im lặng trong khi phiên đã ở 202 message; lượt 12 chết
ở bước 20 (`UPSTREAM_HTTP_400`, `router.jsonl` 09:28:12.851Z) và run phải chờ chủ.

Bài này khẳng định phép sửa: request gửi đi được cắt theo ĐƠN VỊ (lời gọi công cụ đi cùng kết quả
của nó) xuống dưới trần, còn transcript lưu trên đĩa thì giữ nguyên.
"""
import asyncio
import copy

from agentbox.agent_core.compression import (CHAT_MESSAGES_MAX, CHAT_MESSAGES_HEADROOM,
                                             message_units, trim_message_count)
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

CAP = CHAT_MESSAGES_MAX - CHAT_MESSAGES_HEADROOM


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name='terminal_exec', arguments='{"command": "ls"}', cid='call_1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append({'messages': copy.deepcopy(messages), 'tools': copy.deepcopy(tools)})
        return next(self.responses)


class FixtureExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args))
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def transcript(count):
    """`count` message: system, đề bài, rồi các CẶP (assistant có tool_calls, tool) và user."""
    messages = [{'role': 'system', 'content': 'SOP'},
                {'role': 'user', 'content': 'đề bài gốc'}]
    index = 0
    while len(messages) < count:
        index += 1
        messages.append({'role': 'assistant', 'content': '', 'tool_calls': [call(cid=f'call_{index}')]})
        if len(messages) < count:
            messages.append({'role': 'tool', 'tool_call_id': f'call_{index}', 'name': 'terminal_exec',
                             'content': f'kết quả {index}'})
        if len(messages) < count and index % 3 == 0:
            messages.append({'role': 'user', 'content': f'chỉ thị {index}'})
    return messages


def test_a_transcript_under_the_cap_is_untouched():
    messages = transcript(CAP)
    assert trim_message_count(messages) is messages, 'dưới trần thì trả CHÍNH danh sách cũ'
    short = [{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': 'y'}]
    assert trim_message_count(short) is short
    assert trim_message_count(None) is None


def test_the_oldest_units_are_dropped_until_the_transcript_fits():
    messages = transcript(CHAT_MESSAGES_MAX + 2)
    assert len(messages) == CHAT_MESSAGES_MAX + 2

    trimmed = trim_message_count(messages)
    assert len(trimmed) <= CAP, 'request phải nằm dưới trần đếm của nhà cung cấp'
    assert trimmed[0] == messages[0], 'tiền tố `system` không bao giờ bị bỏ'
    assert trimmed[1] == messages[1], 'đề bài (message `user` đầu tiên) không bao giờ bị bỏ'
    assert trimmed[-1] == messages[-1], 'đơn vị mới nhất còn nguyên'
    assert len(trimmed) < len(messages), 'phải cắt thật, không trả bản sao y nguyên'
    positions = [index for index, message in enumerate(messages) if any(message is kept for kept in trimmed)]
    assert positions == sorted(positions), 'thứ tự gốc được giữ'
    assert not any(message is messages[2] for message in trimmed), 'đơn vị cũ nhất là thứ bị bỏ trước'


def test_a_call_and_its_results_are_dropped_together():
    messages = transcript(CHAT_MESSAGES_MAX + 2)
    trimmed = trim_message_count(messages)

    ids = {message['tool_call_id'] for message in trimmed if message.get('role') == 'tool'}
    calls = {call['id'] for message in trimmed if message.get('tool_calls')
             for call in message['tool_calls']}
    assert ids == calls, 'không hàng `tool` mồ côi và không lời gọi nào mất kết quả'
    assert all(message.get('role') != 'tool' or message['tool_call_id'] in calls for message in trimmed)
    units = message_units(trimmed)
    assert sum(end - start for start, end in units) == len(trimmed)


def test_the_request_the_provider_receives_stays_under_the_cap(tmp_path):
    """Lượt sống: transcript trên đĩa đã 202 message, request gửi đi phải dưới trần."""
    client = FixtureModel([answer('lượt một'), answer('lượt hai')])
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create({'skills': []})
    sid = session['id']

    async def turn(prompt):
        runtime.start(sid, prompt)
        return await runtime.tasks[sid]

    assert asyncio.run(turn('lượt một')) == 'lượt một'

    messages = list(store.get(sid)['messages']) + transcript(CHAT_MESSAGES_MAX + 2)[2:]
    store.save(sid, messages)
    before = copy.deepcopy(store.get(sid)['messages'])
    assert len(before) > CHAT_MESSAGES_MAX, 'điều kiện của lượt chạy sống: transcript vượt trần'

    assert asyncio.run(turn('lượt hai')) == 'lượt hai'
    sent = client.requests[-1]['messages']
    assert len(sent) <= CAP, 'request gửi nhà cung cấp phải dưới trần đếm'
    assert len(sent) >= 3, 'không được cắt tới mức mất cả đuôi việc đang làm'
    assert store.get(sid)['messages'][:len(before)] == before, \
        'phép cắt chỉ ở request; transcript lưu trên đĩa không bị viết lại'
    store.close()
