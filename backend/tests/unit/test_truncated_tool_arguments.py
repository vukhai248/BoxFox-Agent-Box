"""F04 — lượt chạy sống 2026-10-09: một lời gọi đứt không được phát lại nguyên trạng.

Nhà cung cấp trả `finish_reason: tool_calls` trong khi trần output đã tiêu hết (4096/4096),
nên tham số của `write_plan` đứt ở ký tự 52 và thiếu dấu đóng. Vòng tool xử lý đúng phần
của nó (lỗi đọc được, model tự sửa — `test_malformed_tool_json_never_reaches_executor`),
nhưng hàng `assistant` giữ nguyên chuỗi hỏng, và từ đó MỌI request sau bị từ chối bằng
`[400] Provider returned error` — ba lượt của chủ và cả lượt tóm tắt của `/compact` chết ở
bước 1 (đo trực tiếp trên router: cùng transcript, tham số hợp lệ trả 200, tham số đứt trả
400 trong 0,6 s).

Bài này khẳng định hai nửa của phép sửa: transcript lưu trên đĩa KHÔNG bị viết lại, còn
request gửi đi thì sạch.
"""
import asyncio
import copy
import json

import pytest

from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.tool_arg_errors import is_json_object, replayable_messages
from agentbox.memory.session_store import SessionStore

# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ, như `test_child_truncation.py`.
pytestmark = pytest.mark.legacy_path

# Đúng chuỗi mà lượt chạy sống ghi vào phiên `72106f67490847a9be5b179a5cc92a6c`.
CUT_OFF = '{"directory": "qc-copilot", "identity": "qc-copilot"'


def answer(text='done', calls=None, finish='stop', usage=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': usage if usage is not None else {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, arguments, cid='call_cut'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': arguments}}


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


def run_turn(tmp_path, client, prompt='viết kế hoạch'):
    store = SessionStore(tmp_path / 'sessions.db')
    executor = FixtureExecutor()
    runtime = HarnessRuntime(store, executor, client)
    session = runtime.create({'skills': []})

    async def run():
        runtime.start(session['id'], prompt)
        return await runtime.tasks[session['id']]

    return store, runtime, executor, session, asyncio.run(run())


def sent_calls(client, index=-1):
    rows = [message for message in client.requests[index]['messages'] if message.get('tool_calls')]
    return [call for row in rows for call in row['tool_calls']]


def test_is_json_object_reads_the_cut_off_shape_as_not_an_object():
    assert is_json_object('{"path": "x"}') is True
    assert is_json_object(CUT_OFF) is False, 'thiếu dấu đóng là thiếu dấu đóng'
    assert is_json_object('{"path": "x"} trailing junk') is False
    assert is_json_object('[1, 2]') is False
    assert is_json_object('') is False
    assert is_json_object(None) is False


def test_a_cut_off_call_is_never_replayed_to_the_provider(tmp_path):
    """Lượt hỏng: vòng tool vẫn trả lỗi cho model, nhưng request kế tiếp không mang chuỗi đứt."""
    client = FixtureModel([answer('Đang ghi kế hoạch', calls=[call('write_plan', CUT_OFF)],
                                  usage={'prompt_tokens': 167146, 'completion_tokens': 4096}),
                           answer('Đã gửi lại bản ngắn.')])
    store, runtime, executor, session, result = run_turn(tmp_path, client)
    sid = session['id']

    assert [name for name, _ in executor.calls] == ['session_ensure'], \
        'lời gọi đứt không được chạy; chỉ op dựng thư mục phiên của lượt'
    assert result == 'Đã gửi lại bản ngắn.', 'lượt đi tiếp trong cùng turn, không bị cắt thành partial'

    stored = [message for message in store.get(sid)['messages'] if message.get('tool_calls')]
    assert len(stored) == 1, 'transcript trên đĩa giữ nguyên hàng `assistant` như model đã gửi'
    assert stored[0]['tool_calls'][0]['function']['arguments'] == CUT_OFF
    tool_row = [message for message in store.get(sid)['messages'] if message['role'] == 'tool'][0]
    assert 'cut off before the closing brace' in json.loads(tool_row['content'])['error'], \
        'model nhận được câu lỗi nói rõ chuỗi bị cắt — nó tự sửa được'

    replayed = sent_calls(client)
    assert replayed[0]['function']['arguments'] == '{}', \
        'request thứ hai phát lại lời gọi đó thành object rỗng, không phải chuỗi đứt'
    assert replayed[0]['id'] == 'call_cut', 'id giữ nguyên: cặp với hàng `tool` của nó'
    store.close()


def test_a_stored_cut_off_call_is_replayed_as_an_empty_object(tmp_path):
    """Phiên đã nhiễm (bản cũ ghi vào): request phải sạch, transcript thì giữ nguyên."""
    client = FixtureModel([answer('xong'), answer('xong')])
    store, runtime, executor, session, _ = run_turn(tmp_path, client, prompt='lượt một')
    sid = session['id']

    messages = list(store.get(sid)['messages'])
    messages += [{'role': 'assistant', 'content': '', 'tool_calls': [call('write_plan', CUT_OFF)]},
                 {'role': 'tool', 'tool_call_id': 'call_cut', 'name': 'write_plan',
                  'content': json.dumps({'is_error': True, 'error': 'Invalid tool arguments'})}]
    store.save(sid, messages)
    before = copy.deepcopy(store.get(sid)['messages'])

    async def second_turn():
        runtime.start(sid, 'lượt hai')
        return await runtime.tasks[sid]

    assert asyncio.run(second_turn()) == 'xong'
    sent = [message for message in client.requests[-1]['messages'] if message.get('tool_calls')]
    assert len(sent) == 1, 'lời gọi cũ vẫn nằm trong request, nó không bị xoá khỏi lịch sử'
    assert sent[0]['tool_calls'][0]['function']['arguments'] == '{}'
    assert store.get(sid)['messages'][:len(before)] == before, \
        'phép sửa chỉ ở request; transcript lưu trên đĩa không bị viết lại'
    assert 'write_plan' not in [name for name, _ in executor.calls], \
        'lời gọi đã sửa thành `{}` cũng không được chạy'
    store.close()


def test_the_replay_repair_leaves_healthy_transcripts_alone():
    healthy = [{'role': 'assistant', 'tool_calls': [call('file_read', '{"path": "x"}', cid='c9')]},
               {'role': 'user', 'content': 'tiếp'}]
    assert replayable_messages(healthy) is healthy, 'không có gì phải sửa thì trả chính danh sách vào'
    empty = [{'role': 'assistant', 'tool_calls': [call('work_status', '', cid='c8')]}]
    assert replayable_messages(empty) is empty, \
        'chuỗi rỗng là lời gọi không tham số của vài nhà cung cấp, không phải chuỗi bị cắt'
    repaired = replayable_messages([{'role': 'assistant', 'tool_calls': [call('write_plan', CUT_OFF)]}])
    assert repaired[0]['tool_calls'][0]['function']['arguments'] == '{}'
    assert repaired[0]['tool_calls'][0]['id'] == 'call_cut'
