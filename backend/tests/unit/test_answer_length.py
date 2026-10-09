"""D2 — trần độ dài **câu trả lời** cuối (D-4): 60 000 thì cảnh báo, 150 000 thì cắt + `partial`.

Câu trả lời trước đợt này không có trần nào: `runtime._run` chỉ kiểm "trọn vẹn và không rỗng"
rồi phát nguyên văn và lưu nguyên hàng `assistant` vào transcript. Hệ quả đo được ở vòng 21:
lượt càng trả lời dài càng dễ đứt ngân sách bước/hạn chót — mà đứt ngân sách thì mất trắng
(BUG-42). Ngưỡng của **kế hoạch** (`plan_eval.PLAN_WARN_CHARS` / `PLAN_MAX_CHARS`) là bộ số
khác và KHÔNG bị đụng ở đây.
"""
import asyncio
import copy
import json

from agentbox.agent_core.limits import (ANSWER_LENGTH_HINT, ANSWER_LENGTH_WARN_CODE, ANSWER_MAX_CHARS,
                                        ANSWER_TOO_LONG_CODE, ANSWER_WARN_CHARS)
from agentbox.agent_core.runtime import HarnessRuntime, answer_truncation_tail
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.worker import SESSION_OP_NAMES


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
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
        if name in SESSION_OP_NAMES:
            # Op nhật ký của box (A1/A7): hợp đồng thật là `{ok, …}` — thiếu `ok` thì harness coi
            # là chưa ghi được và ghim `JOURNAL_DEGRADED` (đúng như worker thật trả).
            return {'ok': True}
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def notices(store, sid, code=None):
    rows = [e['data'] for e in store.events(sid) if e['type'] == 'notice']
    return [row for row in rows if code is None or row.get('code') == code]


def run_turn(tmp_path, client):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash'})

    async def run():
        await runtime.submit(session['id'], 'viết báo cáo')
        await runtime.tasks[session['id']]

    asyncio.run(run())
    return store, runtime, session


def turn_ends(store, sid):
    return [e['data'] for e in store.events(sid) if e['type'] == 'turn_end']


def test_every_role_prompt_carries_the_answer_length_rule(tmp_path):
    """D1 — câu chỉ dẫn độ dài nằm ở MỘT chỗ (`limits.ANSWER_LENGTH_HINT`) và có mặt ở mọi prompt.

    `runtime.start()` là nơi duy nhất dựng prompt hệ thống, cho orchestrator và cho mọi vai trong
    `roles.py`; nếu chỗ đó bị bỏ qua thì một vai sẽ chạy mà không biết trần — đó là điều bài này
    chặn.
    """
    from agentbox.agent_core.roles import ROLES

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([answer('x')] * 40))
        for role in sorted(ROLES):
            sid = runtime.create({'skills': []}, role=role)['id']
            runtime.start(sid, 'chào')
            await runtime.tasks[sid]
            prompt = store.get(sid)['messages'][0]['content']
            assert f'ASSIGNED ROLE: {role.upper()}' in prompt, role
            assert ANSWER_LENGTH_HINT in prompt, f'vai {role} phải biết trần độ dài câu trả lời'
            assert '60,000' in prompt, 'con số trong câu chỉ dẫn là con số THẬT của `limits.py`'
        store.close()

    asyncio.run(run())


def test_a_long_answer_is_warned_but_kept_whole(tmp_path):
    """(a) 70 000 ký tự: MỘT notice cảnh báo, câu trả lời nguyên vẹn, lượt vẫn `completed`."""
    text = 'a' * 70_000
    store, _runtime, session = run_turn(tmp_path, FixtureModel([answer(text)]))
    sid = session['id']

    rows = notices(store, sid, ANSWER_LENGTH_WARN_CODE)
    assert len(rows) == 1, 'một lượt = một cảnh báo'
    assert rows[0]['chars'] == 70_000 and rows[0]['limit'] == ANSWER_WARN_CHARS
    assert store.get(sid)['messages'][-1]['content'] == text, 'cảnh báo KHÔNG được cắt câu trả lời'
    assert turn_ends(store, sid)[-1]['status'] == 'completed'
    assert notices(store, sid, ANSWER_TOO_LONG_CODE) == []
    assert 60_000 < 70_000 <= ANSWER_MAX_CHARS
    store.close()


def test_an_oversized_answer_is_cut_and_the_turn_is_partial(tmp_path):
    """(b) 200 000 ký tự: cắt còn 150 000 + dòng cuối, notice `ANSWER_TOO_LONG`, lượt `partial`."""
    text = 'b' * 200_000
    store, _runtime, session = run_turn(tmp_path, FixtureModel([answer(text)]))
    sid = session['id']

    rows = notices(store, sid, ANSWER_TOO_LONG_CODE)
    assert len(rows) == 1
    assert rows[0]['chars'] == 200_000 and rows[0]['keptChars'] == ANSWER_MAX_CHARS
    assert rows[0]['partial'] is True and rows[0]['journalSeq'] == 1, 'ghim MỘT hàng `X:`'
    tail = answer_truncation_tail()
    kept = store.get(sid)['messages'][-1]['content']
    assert len(kept) == ANSWER_MAX_CHARS + len(tail), 'transcript giữ bản ĐÃ CẮT, không phải bản gốc'
    assert kept.startswith('b' * 100) and kept.endswith(tail)
    assert turn_ends(store, sid)[-1]['status'] == 'partial'
    assert store.get(sid)['status'] == 'completed', 'bất biến #1: hàng `sessions` vẫn `completed`'
    assert notices(store, sid, ANSWER_LENGTH_WARN_CODE) == [], 'quá trần thì không còn là cảnh báo'
    store.close()


def test_a_normal_answer_gets_no_notice_at_all(tmp_path):
    """(c) 12 000 ký tự: không notice nào — ngưỡng không được tạo nhiễu."""
    store, _runtime, session = run_turn(tmp_path, FixtureModel([answer('c' * 12_000)]))
    sid = session['id']

    assert notices(store, sid) == []
    assert turn_ends(store, sid)[-1]['status'] == 'completed'
    store.close()


def test_a_cut_answer_is_partial_for_the_parent_too(tmp_path):
    """Soát engine #7: lượt bị cắt ở trần độ dài là `partial` với CHA, không phải `completed`.

    `turn_end` của lượt đã nói `partial` từ D2; từ vòng 25 hàng `finish` mang luôn `partial` +
    `code`, và H11 đọc chính hàng `finish` cuối ấy — nên cha đọc con này là `partial` kèm ĐÚNG mã
    `ANSWER_TOO_LONG`, không còn hai chỗ nói hai chuyện.
    """
    store, runtime, session = run_turn(tmp_path, FixtureModel([answer('d' * 200_000)]))
    sid = session['id']

    assert notices(store, sid, ANSWER_TOO_LONG_CODE)[0]['partial'] is True
    assert runtime.partial_turn(sid) == ANSWER_TOO_LONG_CODE, 'đúng mã lý do, không phải mã khác'
    store.close()


def test_a_diagnosis_is_never_stored_past_the_length_ceiling(tmp_path):
    """Soát engine #3b: đường chốt trong cửa sổ giữ chỗ cũng qua cổng độ dài (D2).

    Trước đợt này `finish_partial` lưu nguyên văn câu chẩn đoán, nên một câu 200 000 ký tự vào
    thẳng transcript dù trần là 150 000 — đường vòng qua D-4.
    """
    store, _runtime, session = run_turn(tmp_path, FixtureModel([answer('e' * 200_000)]))
    sid = session['id']

    rows = notices(store, sid, ANSWER_TOO_LONG_CODE)
    assert len(rows) == 1 and rows[0]['keptChars'] == ANSWER_MAX_CHARS
    kept = store.get(sid)['messages'][-1]['content']
    assert len(kept) == ANSWER_MAX_CHARS + len(answer_truncation_tail())
    store.close()
