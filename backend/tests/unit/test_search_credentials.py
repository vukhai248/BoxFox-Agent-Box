"""`search_credentials` — đọc nguồn tìm kiếm người dùng chọn từ router (PART 2, task 3).

Router được giả bằng `http.server` thật trên loopback: mô-đun này gọi `urllib` trực tiếp (không qua
`assert_public_url`), nên đếm được ĐÚNG số lời gọi HTTP — con số mà nghiệm thu của kế hoạch đòi
("cached for the whole ttl" phải là 1 lời gọi cho 5 lần `active_source()`).
"""
import http.server
import json
import logging
import socket
import threading
import time

import pytest

from agentbox.agent_core import search_credentials

BRAVE = {'id': 'brave', 'apiKey': 'brave-key', 'accountId': None, 'endpoint': None}


class _Handler(http.server.BaseHTTPRequestHandler):
    """Trả payload/trạng thái do test đặt; ghi lại path + header của mọi lời gọi."""

    payload: object = {'revision': 1, 'active': None}
    raw: str | None = None
    status = 200
    calls: list[dict] = []

    def do_GET(self):                                   # noqa: N802 - tên của thư viện chuẩn
        type(self).calls.append({'path': self.path, 'headers': dict(self.headers)})
        body = self.raw if self.raw is not None else json.dumps(self.payload)
        chunk = body.encode('utf-8')
        self.send_response(type(self).status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(chunk)))
        self.end_headers()
        self.wfile.write(chunk)

    def log_message(self, *args):                       # pragma: no cover - im lặng khi test
        pass


class _Router:
    """Bọc máy chủ giả: đặt câu trả lời, đếm lời gọi, và tự dọn khi hết test."""

    def __init__(self, handler, server):
        self._handler = handler
        self._server = server
        self.url = f'http://127.0.0.1:{server.server_address[1]}/api/router/search/resolve'

    def answer(self, payload=None, *, raw=None, status=200) -> None:
        self._handler.payload = payload if payload is not None else {'revision': 1, 'active': None}
        self._handler.raw = raw
        self._handler.status = status

    @property
    def calls(self) -> list[dict]:
        return self._handler.calls

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture
def router(monkeypatch):
    """Router giả trên loopback + `BOXFOX_ROUTER_SEARCH_URL` trỏ vào nó, cache đã xoá."""
    handler = type('_RecordingHandler', (_Handler,), {'calls': []})
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fake = _Router(handler, server)
    monkeypatch.setenv(search_credentials.ROUTER_SEARCH_URL_ENV, fake.url)
    search_credentials.invalidate()
    try:
        yield fake
    finally:
        fake.close()
        thread.join(timeout=2)
        search_credentials.invalidate()


def _dead_url(monkeypatch) -> None:
    """Trỏ `BOXFOX_ROUTER_SEARCH_URL` vào một cổng vừa đóng: kết nối bị từ chối, không ai trả lời."""
    probe = socket.socket()
    probe.bind(('127.0.0.1', 0))
    port = probe.getsockname()[1]
    probe.close()
    monkeypatch.setenv(search_credentials.ROUTER_SEARCH_URL_ENV,
                       f'http://127.0.0.1:{port}/api/router/search/resolve')
    search_credentials.invalidate()


def test_no_router_answer_means_the_builtin_path_stays_in_charge(router, monkeypatch):
    router.answer(status=500)
    assert search_credentials.active_source() is None          # 500 ⇒ "Mặc định", không ném
    _dead_url(monkeypatch)
    assert search_credentials.active_source() is None          # không ai nghe ⇒ vẫn "Mặc định"
    assert search_credentials.cache_key() == 'default'


def test_the_selected_provider_is_read_once_and_cached_for_the_whole_ttl(router):
    router.answer({'revision': 5, 'active': BRAVE})
    seen = [search_credentials.active_source() for _ in range(5)]
    assert [source.provider_id for source in seen] == ['brave'] * 5
    assert len(router.calls) == 1                              # TTL 15 s ⇒ đúng MỘT lời gọi HTTP
    assert search_credentials.cache_key() == 'brave@5'


def test_an_expired_ttl_refetches_and_picks_up_a_new_selection(router, monkeypatch):
    monkeypatch.setenv(search_credentials.TTL_ENV, '0.05')
    router.answer({'revision': 5, 'active': BRAVE})
    assert search_credentials.active_source().provider_id == 'brave'
    router.answer({'revision': 6, 'active': {'id': 'tavily', 'apiKey': 'tavily-key'}})
    time.sleep(0.08)
    assert search_credentials.active_source().provider_id == 'tavily'
    assert len(router.calls) == 2
    assert search_credentials.cache_key() == 'tavily@6'


def test_a_malformed_payload_never_raises_and_falls_back_to_the_previous_source(router, caplog):
    router.answer({'revision': 5, 'active': BRAVE})
    assert search_credentials.active_source().provider_id == 'brave'
    router.answer(raw='{"revision": 6, "active": {')
    with caplog.at_level(logging.INFO, logger='agentbox.agent_core.search_credentials'):
        assert search_credentials.active_source(force=True).provider_id == 'brave'
    assert len(router.calls) == 2
    assert 'search source resolve failed' in caplog.text
    # Chỉ MỘT dòng cho cả đợt hỏng: lần hỏng thứ hai không ghi thêm.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger='agentbox.agent_core.search_credentials'):
        search_credentials.active_source(force=True)
    assert caplog.text == ''


def test_a_selected_provider_without_a_key_resolves_to_none(router):
    router.answer({'revision': 2, 'active': {'id': 'brave', 'apiKey': None}})
    assert search_credentials.active_source() is None           # D3: thiếu khoá ⇒ đường built-in
    assert search_credentials.cache_key() == 'default'


def test_the_searxng_url_comes_from_the_selected_entry(router):
    router.answer({'revision': 3, 'active': {'id': 'searxng', 'endpoint': 'http://127.0.0.1:9999/'}})
    assert search_credentials.searxng_url() == 'http://127.0.0.1:9999/'
    router.answer({'revision': 4, 'active': BRAVE})
    search_credentials.invalidate()
    assert search_credentials.searxng_url() == ''               # không chọn searxng ⇒ để PART 1 lo


def test_the_resolve_request_carries_the_admin_header(router):
    router.answer({'revision': 1, 'active': None})
    search_credentials.active_source()
    assert len(router.calls) == 1
    assert router.calls[0]['path'] == '/api/router/search/resolve'
    headers = {name.lower(): value for name, value in router.calls[0]['headers'].items()}
    assert headers.get('x-boxfox-admin') == '1'
