"""W9: `browser_use` không được để một tab bận JS giữ cả lượt gọi, và lỗi attach phải nêu ĐÚNG bước.

Đo trong box bằng `deploy/docker/tests/probe_cdp_attach.py` (bản trước khi sửa):
`connect_over_cdp` bình thường 0,19–0,88 s, nhưng khi có MỘT tab đang chạy vòng lặp JS trên main
thread thì attach mất 58,2–59,2 s (vòng lặp 40 s) — vì Playwright phải khởi tạo chính trang đó. Trần
15 s cũ vì thế nổ `Timeout 15000ms exceeded` dù websocket đã kết nối, đúng chữ ký lỗi sweep
W8-A4.1/W7-A3.3. Các ca dưới đây khoá lại: ngân sách attach có thử lại, `/json/version` được chờ
trước khi attach, và marker của phiên được đọc/ghi bằng `wait_for_function` (có trần) thay vì
`page.evaluate` (không có trần).
"""
import sys
import types

import pytest

from agentbox.sandbox import worker


class FakeTimeout(Exception):
    """Đứng thay `playwright.sync_api.TimeoutError`."""


class FakePage:
    """Một trang của `context.pages`: bận JS (`busy`) thì mọi lệnh chờ đều hết trần."""

    def __init__(self, url='about:blank', title='', marker=None, busy=False):
        self.url = url
        self._title = title
        self.marker = marker
        self.busy = busy
        self.wait_calls = []
        self.evaluates = []
        self.goto_calls = []

    def title(self):
        return self._title

    def set_default_timeout(self, _ms):
        pass

    def wait_for_function(self, expression, arg=None, timeout=None):
        self.wait_calls.append({'expression': expression, 'arg': arg, 'timeout': timeout})
        if self.busy:
            raise FakeTimeout('Timeout %dms exceeded.' % (timeout or 0))
        if 'window.name === value' in expression:
            if self.marker != arg:
                raise FakeTimeout('Timeout %dms exceeded.' % (timeout or 0))
            return None
        if 'window.name = value' in expression:
            self.marker = arg
            return None
        raise AssertionError('wait_for_function lạ: ' + expression)

    def evaluate(self, expression, arg=None):
        self.evaluates.append({'expression': expression, 'arg': arg})
        return None

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append({'url': url, 'wait_until': wait_until, 'timeout': timeout})
        self.url = url

    def locator(self, _selector):
        return FakeLocator()


class FakeLocator:
    def inner_text(self):
        return 'nội dung trang'

    def evaluate_all(self, _expression, _nonce):
        return []


class FakeContext:
    def __init__(self, pages=()):
        self.pages = list(pages)
        self.new_pages = []

    def new_page(self):
        page = FakePage(url='about:blank')
        self.pages.append(page)
        self.new_pages.append(page)
        return page


class FakeChromium:
    def __init__(self, client=None, failures=0):
        self.client = client
        self.failures = failures
        self.attach_calls = []

    def connect_over_cdp(self, endpoint, timeout=None):
        self.attach_calls.append({'endpoint': endpoint, 'timeout': timeout})
        if self.failures > 0:
            self.failures -= 1
            raise FakeTimeout('Timeout %dms exceeded.' % (timeout or 0))
        return self.client


class FakeBrowser:
    def __init__(self, contexts):
        self.contexts = contexts


class FakePlaywright:
    def __init__(self, chromium):
        self.chromium = chromium


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Không ca nào thật sự phải chờ, và không ca nào được mở socket ra ngoài."""
    monkeypatch.setattr(worker.time, 'sleep', lambda _seconds: None)
    monkeypatch.setattr(worker.socket, 'create_connection', _open_socket)


def _open_socket(*_args, **_kwargs):
    class _Socket:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    return _Socket()


def _install_playwright(monkeypatch, playwright):
    """`browser()` import Playwright trong hàm, nên thay `sys.modules` là đủ."""
    module = types.ModuleType('playwright.sync_api')
    module.sync_playwright = lambda: _ContextManager(playwright)
    package = types.ModuleType('playwright')
    package.sync_api = module
    monkeypatch.setitem(sys.modules, 'playwright', package)
    monkeypatch.setitem(sys.modules, 'playwright.sync_api', module)


class _ContextManager:
    def __init__(self, playwright):
        self._playwright = playwright

    def __enter__(self):
        return self._playwright

    def __exit__(self, *_exc):
        return False


def _browser_with(monkeypatch, pages=(), failures=0, contexts=None, ready=True):
    # `browser()` chờ CDP trả JSON trước khi attach; ca nào không đo bước đó thì đứng thay bằng True.
    monkeypatch.setattr(worker, 'cdp_ready', lambda _deadline: ready)
    context = FakeContext(pages) if contexts is None else contexts
    chromium = FakeChromium(FakeBrowser(contexts=[context] if contexts is None else contexts),
                            failures=failures)
    _install_playwright(monkeypatch, FakePlaywright(chromium))
    return chromium, context


def test_attach_retries_once_and_reports_attempts(monkeypatch):
    """Lần attach đầu bị chặn (trang bận) không được kết thúc lượt gọi: thử lại rồi mới trả kết quả."""
    chromium, _ = _browser_with(monkeypatch, failures=1)
    client, attach = worker.cdp_attach(FakePlaywright(chromium))
    assert len(chromium.attach_calls) == 2
    assert attach['attempts'] == 2
    assert attach['attachSec'] >= 0
    assert [call['timeout'] for call in chromium.attach_calls] == [worker.CDP_ATTACH_ATTEMPT_TIMEOUT_MS] * 2
    assert client is chromium.client


def test_attach_failure_names_the_step(monkeypatch):
    """Cạn ngân sách phải nói rõ attach hỏng (kèm endpoint), không đổ cho mạng hay treo im."""
    chromium = FakeChromium(failures=99)
    with pytest.raises(ValueError) as caught:
        worker.cdp_attach(FakePlaywright(chromium))
    message = str(caught.value)
    assert message.startswith('BROWSER_CDP_ATTACH_TIMEOUT')
    assert worker.CDP_ENDPOINT in message
    assert str(worker.CDP_ATTACH_ATTEMPTS) in message
    assert len(chromium.attach_calls) == worker.CDP_ATTACH_ATTEMPTS


def test_attach_budget_covers_the_measured_block_and_fits_the_harness():
    """Ngân sách attach phải phủ ca đo được (59,2 s) mà vẫn dưới trần 140 s của `docker exec`."""
    budget = worker.CDP_ATTACH_ATTEMPTS * worker.CDP_ATTACH_ATTEMPT_TIMEOUT_MS / 1000
    assert budget >= 59.2, 'probe: một tab bận JS giữ attach đúng ~59,2 s (đo cả 4 mức vòng lặp)'
    assert worker.CDP_ATTACH_ATTEMPT_TIMEOUT_MS / 1000 < 59.2, 'một lần thử không được dài hơn ca đo'
    assert worker.CDP_READY_TIMEOUT + budget + 25 <= 140, '+25 s cho `page.goto` (worker.py)'


def test_cdp_ready_waits_for_json_not_just_the_open_port(monkeypatch):
    """Cổng TCP mở là chưa đủ: phải đợi `/json/version` trả JSON rồi mới attach."""
    attempts = {'count': 0}
    waits = []
    monkeypatch.setattr(worker.time, 'sleep', waits.append)
    monkeypatch.setattr(worker.time, 'monotonic', lambda: 0.0)

    def _probe(_path, timeout=None):
        attempts['count'] += 1
        if attempts['count'] < 3:
            raise OSError('connection refused')
        return {'Browser': 'Chrome/140'}

    monkeypatch.setattr(worker, 'cdp_http_json', _probe)
    assert worker.cdp_ready(10.0) is True
    assert attempts['count'] == 3
    assert len(waits) == 2, 'giữa hai lần thử phải có nghỉ, không dội endpoint'


def test_cdp_ready_gives_up_at_the_deadline(monkeypatch):
    """Hết trần thì trả False (để `browser()` báo BROWSER_CDP_NOT_READY), không lặp vô hạn."""
    clock = {'now': 0.0}
    monkeypatch.setattr(worker.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(worker.time, 'sleep', lambda seconds: clock.__setitem__('now', clock['now'] + seconds))

    def _probe(_path, timeout=None):
        raise OSError('connection refused')

    monkeypatch.setattr(worker, 'cdp_http_json', _probe)
    assert worker.cdp_ready(3.0) is False
    assert clock['now'] >= 3.0


def test_marker_read_and_write_are_bounded(monkeypatch):
    """Đọc/ghi marker dùng `wait_for_function` với trần, KHÔNG dùng `page.evaluate` (không có trần)."""
    page = FakePage(marker='boxfox-harness-sess')
    assert worker.page_has_marker(page, 'boxfox-harness-sess') is True
    assert page.wait_calls[-1]['timeout'] == worker.CDP_PAGE_MARKER_TIMEOUT_MS
    assert page.evaluates == []
    busy = FakePage(busy=True)
    assert worker.page_has_marker(busy, 'boxfox-harness-sess') is False
    assert worker.page_set_marker(busy, 'boxfox-harness-sess') is False
    assert worker.page_set_marker(page, 'boxfox-harness-sess') is True
    assert page.marker == 'boxfox-harness-sess'


def test_snapshot_skips_a_blocked_page_and_finds_the_session_page(monkeypatch):
    """Tab bận JS không được chặn việc tìm trang của phiên (trang bận bị bỏ qua, không treo)."""
    busy = FakePage(url='http://example.com/busy', busy=True)
    mine = FakePage(url='http://example.com/mine', title='Trang của phiên', marker='boxfox-harness-s1')
    _, context = _browser_with(monkeypatch, pages=[busy, mine])
    result = worker.browser({'action': 'snapshot'}, 's1')
    assert result['url'] == 'http://example.com/mine'
    assert result['title'] == 'Trang của phiên'
    assert result['attach']['attempts'] == 1
    assert context.new_pages == [], 'không mở tab mới khi trang của phiên vẫn còn'


def test_navigate_marks_the_new_page_before_going_to_the_url(monkeypatch):
    """Trang mới được đặt marker TRƯỚC `goto`, và marker sau điều hướng cũng có trần."""
    _, context = _browser_with(monkeypatch)
    result = worker.browser({'action': 'navigate', 'url': 'http://example.com/a'}, 's2')
    assert len(context.new_pages) == 1
    page = context.new_pages[0]
    assert page.goto_calls == [{'url': 'http://example.com/a', 'wait_until': 'domcontentloaded', 'timeout': 25000}]
    assert page.marker == 'boxfox-harness-s2'
    assert page.evaluates == [], 'marker không được đặt bằng `page.evaluate` (không có trần)'
    assert result['attach']['markerSet'] is True


class _BusyAfterGoto(FakePage):
    """Trang bận JS NGAY SAU khi điều hướng — ca đo được trong box (vòng lặp 40 s)."""

    def goto(self, url, wait_until=None, timeout=None):
        super().goto(url, wait_until=wait_until, timeout=timeout)
        self.busy = True


def test_navigate_survives_a_busy_page_after_goto(monkeypatch):
    """Trang vừa điều hướng bận JS: lượt điều hướng vẫn trả kết quả, chỉ marker là không đặt lại được."""
    page = _BusyAfterGoto(url='about:blank', marker='boxfox-harness-s3')
    _, context = _browser_with(monkeypatch, pages=[page])
    result = worker.browser({'action': 'navigate', 'url': 'http://example.com/busy'}, 's3')
    assert result['attach']['markerSet'] is False
    assert page.goto_calls[-1]['url'] == 'http://example.com/busy'
    assert context.new_pages == [], 'không mở tab mới khi đã có trang của phiên'


def test_snapshot_without_the_session_page_asks_to_navigate_first(monkeypatch):
    """Không còn trang của phiên (tab bận hoặc chưa điều hướng) → lỗi rõ, không mở tab mới."""
    _browser_with(monkeypatch, pages=[FakePage(url='http://example.com/other', busy=True)])
    with pytest.raises(ValueError) as caught:
        worker.browser({'action': 'snapshot'}, 's4')
    assert 'Navigate first' in str(caught.value)


def test_no_browser_and_not_navigate_fails_fast(monkeypatch):
    """Chưa có Chromium: `snapshot` báo lỗi ngay (không chờ hết trần rồi mới báo)."""
    def _refuse(*_args, **_kwargs):
        raise OSError('connection refused')

    _browser_with(monkeypatch)
    monkeypatch.setattr(worker.socket, 'create_connection', _refuse)
    launched = []
    monkeypatch.setattr(worker.subprocess, 'Popen', lambda *args, **kwargs: launched.append(args))
    with pytest.raises(ValueError) as caught:
        worker.browser({'action': 'snapshot'}, 's5')
    assert 'not running' in str(caught.value)
    assert launched == [], 'không tự mở Chromium cho hành động không phải `navigate`'


def test_no_browser_navigate_launches_chromium(monkeypatch):
    """`navigate` khi chưa có Chromium vẫn mở `box-chromium` như trước (hợp đồng cũ giữ nguyên)."""
    state = {'first': True}

    def _connect(*_args, **_kwargs):
        if state['first']:
            state['first'] = False
            raise OSError('connection refused')
        return _open_socket()

    monkeypatch.setattr(worker.socket, 'create_connection', _connect)
    launched = []
    monkeypatch.setattr(worker.subprocess, 'Popen', lambda *args, **kwargs: launched.append(args))
    _, context = _browser_with(monkeypatch)
    worker.browser({'action': 'navigate', 'url': 'http://example.com/a'}, 's6')
    assert launched and launched[0][0] == ['box-chromium', 'about:blank']
    assert len(context.new_pages) == 1
