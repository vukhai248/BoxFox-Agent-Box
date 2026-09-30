"""Vòng 22 — phần B: ngân sách không còn "mất trắng", và lượt rỗng được thử lại MỘT lần.

Bốn sự việc đo được ở vòng 21, mỗi sự việc có một ca ở đây:

- BUG-42: chạm trần bước hoặc hạn chót thì lượt `failed` trắng dù việc trên đĩa đã xong. Bản
  này chạy **đường chẩn đoán** (B3/B4): giữ chỗ ba bước cuối cho việc đọc lại trạng thái + trả
  bốn phần (đã làm / tắc ở đâu / còn lại / thử gì tiếp), rồi đóng lượt là `partial` — hàng
  `sessions` vẫn `completed` (bất biến #1: không thêm từ vựng trạng thái).
- BUG-41: lượt rỗng (`TURN_EMPTY_RESPONSE`) đóng thẳng bằng lỗi, không thử lại lần nào (B8).
- B9: `turn_end` chưa có số luỹ kế của lượt (`stepsUsed`, `deadlineUsedMs`, `toolsRun`).
"""
import asyncio
import copy
import json

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core.limits import (DEADLINE_NOTICE_CODE, DIAGNOSIS_MIN_CHARS, STEP_BUDGET_NOTICE_CODE,
                                        WRAP_UP_STEPS_RESERVED)
from agentbox.agent_core.runtime import DIAGNOSIS_PARTS, DIAGNOSIS_PROMPT, HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}

DIAGNOSIS_TEXT = ('Đã làm: đọc xong hai tệp và sửa một tệp. Tắc ở đâu: tệp thứ ba còn thiếu dữ liệu. '
                  'Còn lại: chưa chạy test. Thử gì tiếp: chạy `pytest tests/unit -q` rồi đọc lỗi đầu tiên.')


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    """Model giả: trả lần lượt các phản hồi; một `BaseException` trong danh sách thì NÉM ra.

    Ném được là điều kiện để kiểm đường hạn chót (B4): `_run` nhận `asyncio.TimeoutError` ở
    giữa lượt đúng như khi `asyncio.timeout(config['deadlineSeconds'])` hết giờ.
    """

    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append({'messages': copy.deepcopy(messages), 'tools': copy.deepcopy(tools),
                              'route': copy.deepcopy(route), 'max_tokens': max_tokens})
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        return item


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def notices(store, sid, code=None):
    rows = [e['data'] for e in store.events(sid) if e['type'] == 'notice']
    return [row for row in rows if code is None or row.get('code') == code]


def blockers(store, sid):
    return [e['data'] for e in store.events(sid) if e['type'] == 'blocker']


def turn_ends(store, sid):
    return [e['data'] for e in store.events(sid) if e['type'] == 'turn_end']


def tool_starts(store, sid, name=None):
    rows = [e['data'] for e in store.events(sid) if e['type'] == 'tool_start']
    return [row for row in rows if name is None or row.get('name') == name]


def run_turn(tmp_path, client, values=None, prompt='làm việc dài'):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash',
                              **(values or {})})

    async def run():
        await runtime.submit(session['id'], prompt)
        await runtime.tasks[session['id']]

    asyncio.run(run())
    return store, runtime, session


# --------------------------------------------------------------------------- #
# (a) hết bước ⇒ chẩn đoán ⇒ partial (không mất trắng)
# --------------------------------------------------------------------------- #

def test_budget_exhausted_turn_closes_with_diagnosis(tmp_path):
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]),
                           answer(calls=[call('file_read', {'path': 'b'})]),
                           answer(DIAGNOSIS_TEXT)])
    store, _runtime, session = run_turn(tmp_path, client, values={'maxSteps': 2})
    sid = session['id']

    assert store.get(sid)['status'] == 'completed', 'bất biến #1: hàng `sessions` vẫn `completed`'
    assert turn_ends(store, sid)[-1]['status'] == 'partial', 'turn_end nói thật về lượt chốt'
    rows = notices(store, sid, STEP_BUDGET_NOTICE_CODE)
    assert len(rows) == 1, 'một lượt chạm trần = một notice'
    assert rows[0]['diagnosis'] is True and rows[0]['partial'] is True
    assert rows[0]['stepsUsed'] == 2 and rows[0]['maxSteps'] == 2
    assert rows[0]['reservedSteps'] == WRAP_UP_STEPS_RESERVED
    assert len(blockers(store, sid)) == 1, 'một bản ghi `blocker` như cũ'
    row = store.journal_tail(sid, limit=50)[0]
    assert row['payload']['record']['numbers']['step'] == 2
    # Lượt chốt là lời gọi KHÔNG tool, và prompt chẩn đoán đi kèm yêu cầu cuối.
    last = client.requests[-1]
    assert last['tools'] == [], 'lượt chốt không được gửi tool schema'
    assert any(DIAGNOSIS_PARTS.split(' / ')[0] in (m.get('content') or '') for m in last['messages'] if m['role'] == 'user')
    assert store.get(sid)['messages'][-1]['content'] == DIAGNOSIS_TEXT
    store.close()


def test_empty_diagnosis_keeps_the_old_failure_path(tmp_path):
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]), answer('')])
    store, _runtime, session = run_turn(tmp_path, client, values={'maxSteps': 1})
    errors = [e['data'] for e in store.events(session['id']) if e['type'] == 'error']
    assert store.get(session['id'])['status'] == 'failed'
    assert errors and errors[-1]['code'] == STEP_BUDGET_NOTICE_CODE
    store.close()


def test_too_short_diagnosis_is_not_accepted(tmp_path):
    short = 'x' * (DIAGNOSIS_MIN_CHARS - 1)
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]), answer(short)])
    store, _runtime, session = run_turn(tmp_path, client, values={'maxSteps': 1})
    assert store.get(session['id'])['status'] == 'failed', '"ok" không phải chẩn đoán'
    assert notices(store, session['id'], STEP_BUDGET_NOTICE_CODE) == []
    store.close()


# --------------------------------------------------------------------------- #
# (d0) trong cửa sổ giữ chỗ: tool vẫn dùng được, "sửa lại một lần" thật sự xảy ra
# --------------------------------------------------------------------------- #

def test_diagnosis_window_still_allows_one_correcting_write(tmp_path):
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]),
                           answer(calls=[call('file_read', {'path': 'b'})]),
                           answer(calls=[call('file_write', {'path': 'c', 'content': 'fixed'})]),
                           answer(DIAGNOSIS_TEXT)])
    store, _runtime, session = run_turn(tmp_path, client, values={'maxSteps': 4})
    sid = session['id']

    assert len(tool_starts(store, sid, 'file_write')) == 1, 'đường cũ sai ⇒ đúng một lần sửa'
    assert len(tool_starts(store, sid)) == 3
    assert turn_ends(store, sid)[-1]['status'] == 'partial'
    assert notices(store, sid, STEP_BUDGET_NOTICE_CODE)[0]['diagnosis'] is True
    assert store.get(sid)['messages'][-1]['content'] == DIAGNOSIS_TEXT
    # Câu chỉ dẫn gửi đi mang ĐỦ bốn phần: đó là thứ model phải trả lời.
    prompt = [m for m in client.requests[-1]['messages'] if m['role'] == 'user'][-1]['content']
    for part in DIAGNOSIS_PARTS.split(' / '):
        assert part in prompt, f'{part} phải có trong câu chỉ dẫn'
    store.close()


# --------------------------------------------------------------------------- #
# (d) hết hạn chót ⇒ cùng đường chẩn đoán, ngoài ngân sách đã hết
# --------------------------------------------------------------------------- #

def test_deadline_runs_the_diagnosis_path_with_read_window(tmp_path):
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]),
                           asyncio.TimeoutError(),
                           answer(calls=[call('file_read', {'path': 'b'})]),
                           answer(DIAGNOSIS_TEXT)])
    store, _runtime, session = run_turn(tmp_path, client, values={'maxSteps': 8})
    sid = session['id']

    assert store.get(sid)['status'] == 'completed'
    assert turn_ends(store, sid)[-1]['status'] == 'partial'
    rows = notices(store, sid, DEADLINE_NOTICE_CODE)
    assert len(rows) == 1 and rows[0]['diagnosis'] is True
    assert rows[0]['deadlineUsedMs'] > 0 and rows[0]['readToolCalls'] == 1
    assert len(tool_starts(store, sid, 'file_read')) == 2, 'nhịp đọc lại trạng thái THẬT SỰ chạy'
    store.close()


def test_deadline_read_window_is_capped(tmp_path):
    client = FixtureModel([asyncio.TimeoutError(),
                           answer(calls=[call('file_read', {'path': 'a'}, 'c1'),
                                         call('file_read', {'path': 'b'}, 'c2'),
                                         call('file_read', {'path': 'c'}, 'c3')]),
                           answer(DIAGNOSIS_TEXT)])
    store, _runtime, session = run_turn(tmp_path, client, values={'maxSteps': 8})
    sid = session['id']

    assert store.get(sid)['status'] == 'completed'
    assert len(tool_starts(store, sid, 'file_read')) == 2, 'trần là hai lời gọi đọc'
    assert notices(store, sid, DEADLINE_NOTICE_CODE)[0]['readToolCalls'] == 2
    store.close()


def test_deadline_without_diagnosis_still_fails(tmp_path):
    client = FixtureModel([asyncio.TimeoutError(), asyncio.TimeoutError()])
    store, _runtime, session = run_turn(tmp_path, client, values={'maxSteps': 8})
    errors = [e['data'] for e in store.events(session['id']) if e['type'] == 'error']
    assert store.get(session['id'])['status'] == 'failed', 'không nuốt lỗi thật'
    assert errors[-1]['code'] == DEADLINE_NOTICE_CODE
    store.close()


# --------------------------------------------------------------------------- #
# (B8) lượt rỗng: thử lại ĐÚNG một lần, và cách thử phụ thuộc route
# --------------------------------------------------------------------------- #

def test_empty_response_is_retried_once_with_forced_tool_choice(tmp_path):
    # `length` KHÔNG phải ca này: đó là C2 (nhà cung cấp cắt ở trần output) và có đường riêng.
    # Empty success terminal is distinct from provider content_filter/refusal (which must not retry).
    client = FixtureModel([answer('', finish='stop'), answer('câu trả lời thật')])
    store, _runtime, session = run_turn(tmp_path, client, prompt='đếm 1 tới 3')
    sid = session['id']

    assert len(client.requests) == 2, 'một lần thử lại, không phải một vòng lặp'
    assert client.requests[1]['route']['tool_choice'] == 'required', 'buộc model phải hành động'
    assert 'tool_choice' not in client.requests[0]['route'], 'lần gọi đầu không bị đổi'
    assert store.get(sid)['status'] == 'completed'
    assert [e for e in store.events(sid) if e['type'] == 'error'] == []
    retry = notices(store, sid, 'TURN_EMPTY_RESPONSE_RETRY')
    assert len(retry) == 1 and retry[0]['attempt'] == 1 and retry[0]['how'] == 'tool-choice-required'
    store.close()


def test_empty_response_with_thinking_retries_without_tools(tmp_path):
    client = FixtureModel([answer('', finish='stop'), answer('câu trả lời thật')])
    store, _runtime, session = run_turn(tmp_path, client, values={'thinkingLevel': 'high'})
    sid = session['id']

    assert client.requests[1]['tools'] == [], 'route có thinking ⇒ bỏ tool, xin chữ'
    assert 'tool_choice' not in client.requests[1]['route']
    assert notices(store, sid, 'TURN_EMPTY_RESPONSE_RETRY')[0]['how'] == 'plain-text'
    store.close()


# --------------------------------------------------------------------------- #
# (B9) số luỹ kế của lượt nằm trong `turn_end`
# --------------------------------------------------------------------------- #

def test_turn_end_carries_cumulative_usage(tmp_path):
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]),
                           answer(calls=[call('file_read', {'path': 'b'})]),
                           answer('xong')])
    store, _runtime, session = run_turn(tmp_path, client, prompt='đọc hai tệp')
    ends = turn_ends(store, session['id'])

    assert len(ends) == 3, 'một turn_end cho mỗi bước'
    assert [row['stepsUsed'] for row in ends] == [1, 2, 3], 'luỹ kế: lần đóng CUỐI là số của cả lượt'
    assert ends[-1]['toolsRun'] == 2
    assert all(row['deadlineUsedMs'] > 0 for row in ends)
    assert ends[-1]['status'] == 'completed'
    store.close()


# --------------------------------------------------------------------------- #
# E2 — cùng luật đó, nhưng đi qua HTTP THẬT của harness (`POST /turns`)
# --------------------------------------------------------------------------- #

async def open_session_http(server, values):
    """Mở phiên qua `POST /api/agent/sessions` như giao diện làm, trả về `(sid, url)`."""
    async with ClientSession(headers=HEADERS) as http:
        # Không gửi `connectionId`/`modelId`: đường `create` chỉ tra metadata model khi có hai
        # khoá đó, và model giả ở đây không có `model_metadata` (model thật của lượt vẫn do
        # `route` của lượt quyết định, nên đường chạy không đổi).
        async with http.post(str(server.make_url('/api/agent/sessions')),
                             json={'skills': [], **values}) as resp:
            assert resp.status == 201
            return (await resp.json())['id'], str(server.make_url('/api/agent/sessions'))


def test_http_turn_with_a_tiny_step_budget_closes_partial_with_content(tmp_path):
    """E2 — `maxSteps: 1`: cửa sổ chẩn đoán mở ngay từ bước đầu, lượt vẫn nói ra sự thật.

    Đây là nửa tích hợp của ca (f) ở E1: thay vì gọi thẳng `_run`, mọi thứ đi qua HTTP của
    harness đúng như giao diện gọi, và điều được kiểm là **payload trả về** (event), không phải
    biến trong bộ nhớ.
    """
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]),
                               answer(DIAGNOSIS_TEXT)])
        runtime = HarnessRuntime(store, FixtureExecutor(), client)
        async with TestServer(create_app(runtime)) as server:
            sid, url = await open_session_http(server, {'maxSteps': 1})
            async with ClientSession(headers=HEADERS) as http:
                async with http.post(f'{url}/{sid}/turns', json={'prompt': 'đọc tệp a'}) as resp:
                    assert resp.status == 202
                await runtime.tasks[sid]
                async with http.get(f'{url}/{sid}') as resp:
                    payload = await resp.json()

            assert payload['status'] == 'completed', 'bất biến #1: hàng `sessions` không có `partial`'
            ends = [e['data'] for e in payload['events'] if e['type'] == 'turn_end']
            assert ends[-1]['status'] == 'partial' and ends[-1]['stepsUsed'] == 1
            notices_http = [e['data'] for e in payload['events'] if e['type'] == 'notice'
                            and e['data'].get('code') == STEP_BUDGET_NOTICE_CODE]
            assert len(notices_http) == 1 and notices_http[0]['diagnosis'] is True
            final = [e['data'] for e in payload['events'] if e['type'] == 'assistant' and e['data'].get('final')]
            assert final and len(final[-1]['text'].strip()) >= DIAGNOSIS_MIN_CHARS, \
                'câu trả lời cuối KHÔNG rỗng — đây là điều BUG-42 làm mất'
            assert DIAGNOSIS_TEXT in final[-1]['text']
            assert payload['config']['maxSteps'] == 1, 'kẹp dưới vẫn là một ngân sách hợp lệ'
        store.close()

    asyncio.run(run())


def test_http_child_that_hits_its_budget_gives_the_parent_a_diagnosis(tmp_path):
    """E2 — con chạm trần qua HTTP: cha nhận `partial` + chẩn đoán, không phải `failed` trắng.

    Đây là phép kiểm 5 của E.2, chạy qua đường thật của harness thay vì gọi `delegate` trực tiếp.
    """
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        client = FixtureModel([answer(calls=[call('delegate_task', {'role': 'explore',
                                                                   'goal': 'đọc ba tệp'})]),
                               answer(calls=[call('file_read', {'path': 'a', 'path2': 'b'})]),
                               answer(calls=[call('file_write', {'path': 'notes.md',
                                                                 'content': 'x'})]),
                               answer(DIAGNOSIS_TEXT),
                               answer('câu trả lời cuối của cha')])
        runtime = HarnessRuntime(store, FixtureExecutor(), client)
        async with TestServer(create_app(runtime)) as server:
            sid, url = await open_session_http(server, {'maxSteps': 3})
            async with ClientSession(headers=HEADERS) as http:
                async with http.post(f'{url}/{sid}/turns', json={'prompt': 'nhờ chuyên gia đọc ba tệp'}) as resp:
                    assert resp.status == 202
                await runtime.tasks[sid]
                async with http.get(f'{url}/{sid}') as resp:
                    payload = await resp.json()

            rows = [e['data'] for e in payload['events'] if e['type'] == 'child']
            assert len(rows) == 2, 'một event mở + một event kết quả'
            child = rows[-1]
            assert child['status'] == 'partial'
            assert child['diagnosis'] is True
            assert child['answerChars'] > 0 and child['is_error'] is False
            assert child['reason'] == STEP_BUDGET_NOTICE_CODE
            assert store.get(child['sessionId'])['status'] == 'completed'
        store.close()

    asyncio.run(run())


def test_a_later_turn_still_gets_the_deadline_diagnosis(tmp_path):
    """Soát engine #1 (High): cổng chẩn đoán của hạn chót phải theo **lượt**, không theo phiên.

    Phiên ở đây đã có một lượt chốt dở (chạm trần bước) từ TRƯỚC; lượt sau chạm hạn chót vẫn phải
    đi đường chẩn đoán. Cổng cũ hỏi `partial_turn(sid)` — hàm này quét **mọi** notice bền của
    phiên — nên lượt thứ hai bị đóng bằng `failed` trắng không chẩn đoán: đúng thứ B4/BUG-42 dựng
    lên để xoá, chỉ đổi cửa vào.
    """
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'a'})]),
                           answer(DIAGNOSIS_TEXT),          # lượt 1: chạm trần bước ⇒ partial
                           asyncio.TimeoutError(),         # lượt 2: hết hạn chót
                           answer(DIAGNOSIS_TEXT)])        # lượt 2: chẩn đoán
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash',
                              'maxSteps': 2})
    sid = session['id']

    async def run():
        await runtime.submit(sid, 'lượt một')
        await runtime.tasks[sid]
        await runtime.submit(sid, 'lượt hai, dài hơn')
        await runtime.tasks[sid]

    asyncio.run(run())

    assert len(notices(store, sid, STEP_BUDGET_NOTICE_CODE)) == 1, 'lượt đầu chốt dở như thiết kế'
    rows = notices(store, sid, DEADLINE_NOTICE_CODE)
    assert len(rows) == 1 and rows[0]['diagnosis'] is True, 'lượt hai VẪN có chẩn đoán'
    assert [e for e in store.events(sid) if e['type'] == 'error'] == [], 'không có `failed` trắng'
    assert store.get(sid)['status'] == 'completed', 'bất biến #1: hàng `sessions` vẫn `completed`'
    assert turn_ends(store, sid)[-1]['status'] == 'partial'
    store.close()
