"""Hàng đợi chỉ thị giữa lượt (#5961, vòng 27 đợt 7, C-7).

Chủ nhà gõ thêm một câu khi lượt đang chạy: câu ấy phải tới được model ở ranh giới bước kế tiếp,
ĐÚNG MỘT LẦN, và không được mở lượt thứ hai. Ba mặt ấy nằm ở ba tầng khác nhau — bảng
`session_steers`, hai hàm bơm của harness, và route `turn` của API — nên ca kiểm đi qua cả ba.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import limits, research_runtime
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


class FixtureExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return {'content': 'ok'}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.delenv('BOXFOX_STEER', raising=False)
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    sid = runtime.create({'skills': []})['id']
    runtime.active_turn[sid] = 1
    yield store, runtime, sid, store.get(sid)
    store.close()


def test_a_queued_steer_is_claimed_once_and_only_once(harness):
    store, runtime, sid, session = harness
    record = store.queue_steer(sid, 'chỉ đọc tầng 1', 1)
    assert record['state'] == 'pending' and record['turn'] == 1 and record['injected'] is None
    assert store.pending_steer_count(sid) == 1
    claimed = store.claim_steers(sid, limit=3)
    assert [row['id'] for row in claimed] == [record['id']]
    assert store.pending_steer_count(sid) == 0, 'bơm rồi thì không còn chờ'
    assert store.claim_steers(sid, limit=3) == [], 'lần thứ hai không nhận lại chỉ thị cũ'
    row = store.steer(record['id'])
    assert row['state'] == 'injected' and row['injected'] is not None


def test_a_pending_steer_the_turn_never_used_is_dropped_not_injected(harness):
    """Chủ nhà đổi ý (hoặc lượt đóng trước nhịp bơm): hàng phải thành `dropped`, không nằm lại `pending`."""
    store, runtime, sid, session = harness
    record = store.queue_steer(sid, 'đổi hướng', 1)
    row = store.mark_steer(record['id'])
    assert row['state'] == 'dropped' and row['injected'] is not None
    assert store.pending_steer_count(sid) == 0
    assert store.claim_steers(sid, limit=3) == []


def test_the_owner_text_reaches_the_transcript_once_with_its_prefix(harness):
    store, runtime, sid, session = harness
    messages = list(session['messages'])
    asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'chỉ đọc nguồn tầng 1'))
    assert research_runtime.drain_steers(runtime, sid, messages) == 1
    injected = [m for m in messages if m['role'] == 'user']
    assert len(injected) == 1
    assert injected[0]['content'].startswith(limits.OWNER_STEER_PREFIX)
    assert 'tầng 1' in injected[0]['content']
    stored = store.get(sid)['messages']
    assert [m['content'] for m in stored if m['role'] == 'user'] == [injected[0]['content']], \
        'bơm vào transcript là lưu lại, không chỉ nằm trong RAM'
    assert research_runtime.drain_steers(runtime, sid, messages) == 0, 'lần gọi thứ hai không bơm lại'


def test_the_drain_stops_at_its_own_limit_and_leaves_the_rest_pending(harness):
    store, runtime, sid, session = harness
    messages = list(session['messages'])
    for index in range(limits.STEER_DRAIN_MAX + 2):
        asyncio.run(research_runtime.queue_owner_steer(runtime, sid, f'chỉ thị {index}'))
    assert research_runtime.drain_steers(runtime, sid, messages) == limits.STEER_DRAIN_MAX
    assert store.pending_steer_count(sid) == 2, 'phần còn lại chờ lượt bơm sau'


def test_the_queue_has_a_ceiling_and_says_so(harness):
    store, runtime, sid, session = harness
    for index in range(limits.STEER_MAX_PENDING):
        asyncio.run(research_runtime.queue_owner_steer(runtime, sid, f'chỉ thị {index}'))
    with pytest.raises(ValueError, match='STEER_QUEUE_FULL'):
        asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'một câu nữa'))
    with pytest.raises(ValueError, match='STEER_EMPTY'):
        asyncio.run(research_runtime.queue_owner_steer(runtime, sid, '   '))


def test_an_empty_switch_returns_none_instead_of_queueing(harness, monkeypatch):
    store, runtime, sid, session = harness
    monkeypatch.setenv('BOXFOX_STEER', 'off')
    assert asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'x')) is None
    assert store.pending_steer_count(sid) == 0


def test_a_very_long_steer_is_cut_before_it_is_stored(harness):
    store, runtime, sid, session = harness
    answer = asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'x' * (limits.STEER_TEXT_MAX_CHARS + 500)))
    row = store.steer(answer['steerId'])
    assert len(row['text']) == limits.STEER_TEXT_MAX_CHARS


def test_the_steer_leaves_a_decision_row_and_an_event(harness):
    store, runtime, sid, session = harness
    asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'chỉ đọc tầng 1'))
    events = [row['data'] for row in store.events(sid) if row['type'] == 'user']
    assert events and events[-1]['steer'] is True and events[-1]['control'] is True
    rows = store.journal_tail(sid, limit=10, kinds=('decision',))
    assert rows and rows[-1]['payload']['record']['data']['kind'] == 'owner-steer'
    assert 'tầng 1' in rows[-1]['text']


def test_the_steer_never_reaches_a_child_transcript(harness):
    """Chỉ thị là chuyện giữa chủ nhà và phiên gốc — con không nhận nó (route cũng chặn)."""
    store, runtime, sid, session = harness
    child = runtime.create({'skills': []}, parent_id=sid, role='research')
    asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'chỉ đọc tầng 1'))
    child_messages = list(store.get(child['id'])['messages'])
    assert research_runtime.drain_steers(runtime, child['id'], child_messages) == 0
    assert child_messages == store.get(child['id'])['messages'], 'transcript của con không đổi'
    assert all(not str(m.get('content') or '').startswith(limits.OWNER_STEER_PREFIX)
               for m in store.get(child['id'])['messages'])
    # Câu ấy vẫn tới được phiên gốc, đúng một lần.
    own_messages = list(store.get(sid)['messages'])
    assert research_runtime.drain_steers(runtime, sid, own_messages) == 1
    assert any(str(m.get('content') or '').startswith(limits.OWNER_STEER_PREFIX)
               for m in store.get(sid)['messages'])


def test_a_failed_transcript_write_puts_the_steer_back_in_the_queue(tmp_path, monkeypatch):
    """Chỉ thị không được RƠI khi transcript ghi hỏng: `claim_steers` đánh dấu `injected` trước đó."""
    store = SessionStore(tmp_path / 'state.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    sid = runtime.create({'skills': []})['id']
    answer = asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'đổi trọng tâm: giá vàng'))
    assert answer['status'] == 'steered'

    def boom(*_args, **_kwargs):
        raise RuntimeError('disk full')

    monkeypatch.setattr(store, 'save', boom)
    messages = []
    assert research_runtime.drain_steers(runtime, sid, messages) == 0
    assert store.pending_steer_count(sid) == 1, 'chỉ thị ở lại hàng chờ'
    monkeypatch.undo()
    assert research_runtime.drain_steers(runtime, sid, messages) == 1
    assert store.pending_steer_count(sid) == 0
    assert 'giá vàng' in messages[0]['content']


def test_a_btw_question_uses_the_same_queue_with_its_own_label(harness):
    """P5 — `/btw` giữa lượt KHÔNG cắt lượt: nó vào đúng hàng đợi steer nhưng mang nhãn `btw`."""
    store, runtime, sid, session = harness
    answer = asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'pin này dùng ở đâu?', kind='btw'))
    assert answer['status'] == 'steered'
    row = store.steer(answer['steerId'])
    assert row['kind'] == 'btw' and row['state'] == 'pending'
    events = [row['data'] for row in store.events(sid) if row['type'] == 'user']
    assert events[-1]['btw'] is True and events[-1]['steer'] is True
    assert events[-1]['text'] == 'pin này dùng ở đâu?', 'hàng btw hiện nguyên câu hỏi, nhãn do chip btw lo'
    assert not events[-1]['text'].startswith(limits.OWNER_STEER_PREFIX)
    rows = store.journal_tail(sid, limit=10, kinds=('decision',))
    assert rows[-1]['payload']['record']['data']['kind'] == 'btw-ask', 'sổ phiên phải đọc ra đây là câu hỏi phụ'


def test_a_btw_question_the_closing_turn_never_used_is_announced(harness):
    """P5 (vòng kiểm thử đầu-cuối vòng 3) — hàng `btw` chưa kịp bơm mà lượt đã đóng thì phải có
    hàng NÓI RA. Phiên `d378b42b` để lại hàng `pending` sau lượt `completed` trong im lặng."""
    store, runtime, sid, session = harness
    answer = asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'pin này dùng ở đâu?', kind='btw'))
    assert research_runtime.notice_pending_btw(runtime, sid) == 1
    notices = [row['data'] for row in store.events(sid) if row['type'] == 'notice']
    assert notices and notices[-1]['code'] == limits.BTW_PENDING_NOTICE_CODE
    assert notices[-1]['count'] == 1 and notices[-1]['steerIds'] == [answer['steerId']]
    assert 'lượt kế tiếp' in notices[-1]['message']
    assert store.steer(answer['steerId'])['state'] == 'pending', \
        'báo ra KHÔNG gỡ hàng khỏi hàng chờ — câu hỏi vẫn phải tới model ở lượt kế'
    # Bơm được rồi thì không còn gì để nói: hàng đã `injected`, lượt kế đọc nó từ transcript.
    assert research_runtime.drain_steers(runtime, sid, list(session['messages'])) == 1
    assert research_runtime.notice_pending_btw(runtime, sid) == 0


class BtwMidStepModel:
    """Model của lượt ngắn tự xếp câu hỏi phụ NGAY TRONG bước (tức SAU nhịp bơm của bước ấy).

    Đúng khuôn "lượt đã ở bước chót": nhịp bơm của bước đã đi qua trước khi câu hỏi tới, và lượt
    chẳng còn bước nào nữa để bơm lại — hàng ở lại `pending` tới lúc lượt đóng.
    """

    def __init__(self, store, sid):
        self.store, self.sid, self.steer_id = store, sid, None

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        record = self.store.queue_steer(self.sid, 'pin này dùng ở đâu?', 1, kind='btw')
        self.steer_id = record['id']
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


def test_the_closing_turn_itself_announces_a_btw_it_could_not_inject(harness):
    """Đường THẬT: lượt chạy tới lúc đóng thì TỰ phát hàng báo — không phải test gọi tay helper.

    Ca này đi qua `HarnessRuntime.start` → `_run` → `finally`, đúng chỗ lượt đóng và đúng khuôn của
    phiên thật `d378b42b` (hàng `pending` sau khi lượt `completed`).
    """
    store, runtime, sid, session = harness
    model = BtwMidStepModel(store, sid)
    runtime.client = model

    async def drive():
        await runtime.start(sid, 'việc thật của lượt')

    asyncio.run(drive())
    assert model.steer_id is not None, 'câu hỏi phải được xếp trong bước, không phải trước lượt'
    notices = [row['data'] for row in store.events(sid) if row['type'] == 'notice']
    assert [row['code'] for row in notices] == [limits.BTW_PENDING_NOTICE_CODE]
    assert notices[0]['count'] == 1 and notices[0]['steerIds'] == [model.steer_id]
    assert store.steer(model.steer_id)['state'] == 'pending', \
        'hàng vẫn chờ để lượt kế bơm — hàng báo KHÔNG được thay việc bơm'


def test_a_left_over_plain_steer_is_not_announced_as_a_side_question(harness):
    """Chỉ thị giữa lượt chờ lượt sau là ĐÚNG luật đã công bố — chỉ câu hỏi phụ mới cần hàng báo."""
    store, runtime, sid, session = harness
    asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'đổi hướng sang tầng 2'))
    assert research_runtime.notice_pending_btw(runtime, sid) == 0
    assert [row for row in store.events(sid) if row['type'] == 'notice'] == []


def test_the_btw_block_carries_its_own_prefix_and_rules(harness):
    store, runtime, sid, session = harness
    messages = list(session['messages'])
    asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'chỉ thị thường'))
    asyncio.run(research_runtime.queue_owner_steer(runtime, sid, 'câu hỏi phụ?', kind='btw'))
    assert research_runtime.drain_steers(runtime, sid, messages) == 2
    injected = [m['content'] for m in messages if m['role'] == 'user']
    assert len(injected) == 1, 'hai hàng vẫn vào ĐÚNG MỘT khối user — không mở lượt thứ hai'
    assert limits.OWNER_STEER_PREFIX in injected[0] and limits.BTW_ASK_PREFIX in injected[0]
    assert 'KHÔNG ghi tệp' in injected[0], 'khối btw phải nói rõ luật: ngắn, không đổi việc, không ghi tệp'
    assert injected[0].index(limits.OWNER_STEER_PREFIX) < injected[0].index(limits.BTW_ASK_PREFIX)
    assert store.pending_steer_count(sid) == 0


def test_an_idle_btw_question_is_framed_as_a_side_question():
    framed = research_runtime.btw_question_prompt('  pin này để làm gì?  ')
    assert framed.startswith(limits.BTW_ASK_PREFIX) and framed.endswith('pin này để làm gì?')
    with pytest.raises(ValueError, match='BTW_EMPTY'):
        research_runtime.btw_question_prompt('   ')
    # P5 — MỘT luật độ dài duy nhất: hàm dựng khung KHÔNG cắt im lặng. Cổng lệnh là nơi từ chối
    # (`BTW_QUESTION_TOO_LONG`, xem `test_skill_commands.test_btw_requires_a_question_and_caps_its_length`),
    # nên ở đây câu hỏi đi nguyên vẹn dù dài hơn trần — người hỏi không bị xén lặng lẽ.
    over = 'x' * (limits.BTW_QUESTION_MAX_CHARS + 100)
    assert research_runtime.btw_question_prompt(over) == limits.BTW_ASK_PREFIX + ' ' + over


def test_the_recap_excerpt_skips_a_btw_question():
    """P4/P5 — bản nhắc việc không được đội lốt "việc chủ giao" cho một câu hỏi phụ của `/btw`."""
    from agentbox.agent_core.runtime import turn_prompt_excerpt
    mostly = [{'role': 'user', 'content': 'việc thật của lượt'},
              {'role': 'user', 'content': limits.BTW_ASK_PREFIX + ' pin này để làm gì?'}]
    assert turn_prompt_excerpt(mostly) == 'việc thật của lượt'
    assert turn_prompt_excerpt(mostly[:1] + mostly[:1]) == 'việc thật của lượt'
    only_btw = [{'role': 'user', 'content': limits.BTW_ASK_PREFIX + ' pin này để làm gì?'}]
    assert turn_prompt_excerpt(only_btw) == '', 'hết việc của chủ thì phải nói là không thấy'
    assert turn_prompt_excerpt([{'role': 'user', 'content': '  '}]) == ''
