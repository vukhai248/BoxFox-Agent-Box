"""`source_verify` — mở LẠI nguồn và so với đoạn trích đã ghim (vòng 27 đợt 3, A-3/B-1).

Chủ nhà hỏi đúng một câu: "dòng sổ này có thật đúng như người viết nói không?". Ca kiểm ghim bốn
kết cục mà `web_fetch` trả về — mở lại được và trùng, mở lại được nhưng đã đổi, "thành công giả"
(HTTP 200 với thân bài rỗng/tiêu đề trang chủ), và không mở được — cùng luật quan trọng nhất: lỗi mở
lại **không bao giờ** được coi là `ok`.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import limits, research_runtime
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ nên pin `BOXFOX_REFORM=off` cho mọi bài
# (xem `tests/unit/conftest.py`). Bài nào cần đường mới thì đặt env tường minh trong bài.
pytestmark = pytest.mark.legacy_path


#: Đủ dài để một lần mở lại được coi là "trang thật" (trên sàn thành-công-giả 300 ký tự).
EXCERPT = ('Người bệnh đúng tuyến được hưởng 80% chi phí khám chữa bệnh, và hồ sơ chuyển tuyến '
           'gồm giấy chuyển tuyến cùng bản tóm tắt điều trị. ') * 3


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


class FakeWeb:
    """`web.fetch` giả: trả đúng thứ ta muốn đo, kể cả ném lỗi."""

    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def fetch(self, args):
        self.calls.append(dict(args))
        if self.error is not None:
            raise self.error
        return dict(self.payload or {})


@pytest.fixture()
def harness(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    sid = runtime.create({'skills': []})['id']
    session = store.get(sid)
    # Gọi THẲNG engine: biên dispatch của main đã bị Research gateway đóng (`RESEARCH_MAIN_READ_ONLY`)
    # — biên ấy được ghim ở `tests/unit/test_research_gateway.py`.
    research_runtime.source_add(runtime, session,
                                {'claim': 'mức hưởng đúng tuyến', 'url': 'https://moh.gov.vn/a',
                                 'excerpt': EXCERPT})
    yield store, runtime, sid, session
    store.close()


def verify(runtime, session, row_id='r1'):
    """Mở lại nguồn qua ENGINE `source_verify` — cửa dispatch của main đã đóng (xem chú thích fixture)."""
    return asyncio.run(research_runtime.source_verify(runtime, session, {'rowId': row_id}))


def test_a_page_that_still_says_the_same_thing_is_ok(harness):
    store, runtime, sid, session = harness
    runtime.web = FakeWeb({'text': EXCERPT, 'title': 'Chuyển tuyến', 'status': 200,
                           'fetchedAt': '2026-09-24T02:00:00Z'})
    answer = verify(runtime, session)
    assert answer['status'] == 'ok' and answer['matched'] is True
    assert answer['unreachable'] is False and answer['fakeSuccess'] is False
    assert answer['overlap'] >= 0.8
    assert store.source_row(sid, 'r1')['status'] == 'ok'


def test_a_page_whose_text_changed_is_stale_and_says_what_to_do(harness):
    store, runtime, sid, session = harness
    runtime.web = FakeWeb({'text': ('Quy định đã được thay thế bằng văn bản mới, nội dung khác hẳn '
                                    'so với bản đã đọc. ') * 6, 'status': 200})
    answer = verify(runtime, session)
    assert answer['status'] == 'stale' and answer['matched'] is False
    assert 'source_add' in answer['message']
    assert store.source_row(sid, 'r1')['status'] == 'stale'


def test_a_two_hundred_byte_success_is_a_fake_success(harness):
    store, runtime, sid, session = harness
    runtime.web = FakeWeb({'text': 'x' * 120, 'title': 'Chi tiết văn bản', 'status': 200})
    answer = verify(runtime, session)
    assert answer['fakeSuccess'] is True
    assert answer['status'] == 'unverified' and answer['matched'] is False
    assert 'thành công giả' in answer['message']
    assert str(limits.SOURCE_FAKE_SUCCESS_MIN_CHARS) in answer['message']


def test_a_page_whose_title_says_home_is_not_the_article(harness):
    store, runtime, sid, session = harness
    runtime.web = FakeWeb({'text': EXCERPT, 'title': 'Trang chủ', 'status': 200})
    answer = verify(runtime, session)
    assert answer['fakeSuccess'] is True
    assert answer['status'] == 'unverified', 'thân bài trùng mà tiêu đề là trang chủ ⇒ KHÔNG phải ok'


def test_a_hard_forbidden_url_never_becomes_ok(harness):
    store, runtime, sid, session = harness
    error = RuntimeError('WEB_BLOCKED_PRIVATE_HOST')
    runtime.web = FakeWeb(error=error)
    answer = verify(runtime, session)
    assert answer['unreachable'] is True
    assert answer['status'] == 'unverified' and answer['matched'] is False
    assert 'chưa mở được bản gốc' in answer['message']
    assert store.source_row(sid, 'r1')['status'] == 'unverified'


def test_verifying_a_row_that_is_not_in_the_ledger_asks_for_the_list(harness):
    store, runtime, sid, session = harness
    with pytest.raises(ValueError, match='SOURCE_VERIFY_UNKNOWN'):
        verify(runtime, session, row_id='r99')
    with pytest.raises(ValueError, match='SOURCE_VERIFY_INVALID'):
        asyncio.run(research_runtime.source_verify(runtime, session, {}))


def test_verifying_never_writes_the_excerpt_back(harness):
    """Mở lại KHÔNG được sửa đoạn trích đã ghim: đoạn trích là thứ đã đọc lúc ấy."""
    store, runtime, sid, session = harness
    runtime.web = FakeWeb({'text': 'nội dung mới hoàn toàn khác', 'status': 200})
    verify(runtime, session)
    assert store.source_row(sid, 'r1')['excerpt'] == EXCERPT.strip()
