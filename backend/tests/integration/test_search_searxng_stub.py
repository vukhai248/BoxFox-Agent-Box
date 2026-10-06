"""D3 tầng 2 — SearXNG GIẢ trên loopback: không Docker, không Internet, chạy mặc định.

Bốn bài ở đây khoá đúng bốn hành vi mà đường built-in phải có trước khi tin được một container
thật: (1) đọc được hình dạng JSON của SearXNG, (2) tự dò thấy đích đã cấu hình, (3) instance trả
0 hàng là "rỗng" chứ KHÔNG phải "chết", (4) cổng chết thì rơi xuống chân kế tiếp mà không ném.

Stub chỉ nghe trên `127.0.0.1` với cổng do hệ điều hành cấp, nên bài không thể lỡ tay gọi ra ngoài.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from agentbox.agent_core import search_pipeline as sp
from agentbox.agent_core.web import WebError, WebTools

STUB_ROW = {'title': 'Hướng dẫn điều trị ngoại trú',
            'url': 'https://example.org/huong-dan',
            'content': 'Phác đồ ngoại trú cho người lớn.',
            'engine': 'stub-engine'}


class _Handler(BaseHTTPRequestHandler):
    rows: list[dict] = [STUB_ROW]
    unresponsive: list = []
    seen: list[dict] = []

    def log_message(self, *args):                      # im lặng: không đổ log ra pytest
        pass

    def _send(self, status: int, body: str):
        payload = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == sp.SEARXNG_HEALTH_PATH:
            return self._send(200, 'OK')
        if parsed.path == sp.SEARXNG_CONFIG_PATH:
            return self._send(200, json.dumps({'engines': [{'name': 'stub-engine'}]}))
        if parsed.path == '/search':
            query = parse_qs(parsed.query)
            type(self).seen.append({'q': query.get('q', [''])[0], 'format': query.get('format', [''])[0],
                                    'engines': query.get('engines', [''])[0]})
            if query.get('empty') == ['1']:
                return self._send(200, json.dumps({'results': [], 'unresponsive_engines': []}))
            return self._send(200, json.dumps({'results': type(self).rows,
                                               'unresponsive_engines': type(self).unresponsive}))
        return self._send(404, json.dumps({'error': 'not found'}))


@pytest.fixture()
def stub(monkeypatch):
    """SearXNG giả trên cổng trống; fixture trả `(url, stop)` và tự dọn."""
    _Handler.rows = [STUB_ROW]
    _Handler.unresponsive = []
    _Handler.seen = []
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_address[1]}'
    monkeypatch.delenv(sp.SEARXNG_URL_ENV, raising=False)
    monkeypatch.delenv(sp.SEARXNG_AUTODETECT_URL_ENV, raising=False)
    sp.reset_autodetect()
    sp.reset_store()
    try:
        yield url, server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        sp.reset_autodetect()
        sp.reset_store()


def _closed_port() -> str:
    """Một cổng đã đóng thật: mở rồi đóng ngay để lấy số cổng không ai nghe."""
    server = ThreadingHTTPServer(('127.0.0.1', 0), _Handler)
    port = server.server_address[1]
    server.server_close()
    return f'http://127.0.0.1:{port}'


def test_the_harness_parses_a_local_searxng_stub(stub, monkeypatch):
    url, _ = stub
    monkeypatch.setenv(sp.SEARXNG_URL_ENV, url)
    response = sp.searxng_search('phác đồ ngoại trú', engines=['stub-engine'], count=5)
    assert response['error'] is None, response['error']
    assert [row['url'] for row in response['results']] == [STUB_ROW['url']]
    assert response['unresponsive'] == []
    assert _Handler.seen[-1]['format'] == 'json', 'phải xin JSON, không phải HTML'
    assert _Handler.seen[-1]['q'] == 'phác đồ ngoại trú'


def test_autodetect_finds_a_stub_on_the_configured_url(stub, monkeypatch):
    url, _ = stub
    monkeypatch.setenv(sp.SEARXNG_AUTODETECT_URL_ENV, url)
    assert sp.resolved_searxng_url() == url
    assert sp.searxng_available() is True
    assert sp.search_status()['searxng']['origin'] == 'autodetect'


def test_a_stub_that_answers_empty_is_empty_not_dead(stub, monkeypatch):
    url, _ = stub
    monkeypatch.setenv(sp.SEARXNG_URL_ENV, url)
    monkeypatch.setenv('BOXFOX_SEARCH_DB', '/var/tmp/boxfox-stub-empty.sqlite')
    sp.reset_store()
    _Handler.rows = []
    try:
        response = sp.searxng_search('không có gì', engines=['stub-engine'], count=5)
        assert response['error'] is None and response['results'] == []
        with pytest.raises(WebError) as caught:
            sp.run_pipeline(['không có gì'], source='web', count=5, options={})
        assert caught.value.code == 'WEB_SEARCH_EMPTY', str(caught.value)
        assert 'not a query problem' not in str(caught.value), 'rỗng KHÔNG phải lỗi cấu hình'
        assert caught.value.details['searchFailure']['kind'] == ''
    finally:
        _Handler.rows = [STUB_ROW]
        sp.reset_store()


def test_a_dead_port_is_not_detected(stub, monkeypatch):
    """Cổng chết: tự dò trượt, chuỗi rơi xuống chân kế tiếp, KHÔNG ném ra ngoài.

    Chân kế tiếp được THAY bằng một chân luôn hỏng để bài không phụ thuộc Internet của máy chạy:
    điều cần khoá là `WebError` ĐÃ PHÂN LOẠI đi ra tới người gọi, không phải một ngoại lệ trần.
    """
    from agentbox.agent_core import web as web_module
    monkeypatch.setenv(sp.SEARXNG_AUTODETECT_URL_ENV, _closed_port())
    def dead_leg(query, count, options):
        raise web_module.WebError('WEB_SEARCH_UNAVAILABLE', 'stub leg: refused')

    monkeypatch.setattr(web_module, 'GENERAL_PROVIDERS', (dead_leg,))
    assert sp.resolved_searxng_url() == ''
    assert sp.searxng_available() is False
    status = sp.search_status()
    assert status['searxng']['reachable'] is False and status['searxng']['url'] == ''
    with pytest.raises(WebError) as caught:
        WebTools().search({'query': 'kiểm tra'})
    assert caught.value.code == 'WEB_SEARCH_UNAVAILABLE'
    assert caught.value.details['searchFailure']['kind'] == 'config'
    assert 'not a query problem' in str(caught.value)
