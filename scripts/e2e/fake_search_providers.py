#!/usr/bin/env python3
"""Máy chủ provider tìm kiếm GIẢ — chạy cục bộ cho E2E của "Web Search API" (PART 2, task 6).

Trả JSON đúng hình dạng mà harness đọc cho từng nhà cung cấp, để kiểm thử xuyên hệ thống
(router → harness → UI API) **không cần một khoá API thật nào**:

| Đường dẫn | Hình dạng trả về | Header xác thực mà harness phải gửi |
|---|---|---|
| `GET  /brave`      | `{"web": {"results": [{title,url,description}]}}`        | `X-Subscription-Token` |
| `POST /tavily`     | `{"results": [{title,url,content}]}`                     | `Authorization: Bearer` |
| `POST /exa`        | `{"results": [{title,url,text}]}`                        | `x-api-key` |
| `POST /parallel`   | `{"results": [{title,url,excerpts}]}`                    | `x-api-key` |
| `POST /firecrawl`  | `{"success": true, "data": [{title,url,description}]}`   | `Authorization: Bearer` (tuỳ chọn) |
| `POST /cloudflare` | `{"items": [{title,url,description}]}`                   | `Authorization: Bearer` |
| `POST /custom`     | `{"results": [...]}` hoặc `{"items": [...]}` (`?shape=items`) | `Authorization: Bearer` (tuỳ chọn) |
| `GET  /searxng/search` | `{"results": [{url,title,snippet,engine}]}`          | — (SearXNG tự host không khoá) |

Tham số điều khiển lỗi (mọi đường dẫn): `?status=401` trả đúng mã đó kèm thân lỗi;
`?empty=1` trả danh sách rỗng nhưng vẫn HTTP 200.

Nhật ký lời gọi: mỗi request ghi một dòng vào file JSONL (`--log <path>`) và vào bộ nhớ;
`GET /__calls` trả cả nhật ký, `POST /__reset` xoá sạch. Kịch bản E2E dùng nhật ký này để
khẳng định "chỉ provider được chọn bị gọi" và "khoá thô không rò vào thân bài".

Chạy tay:  `python3 scripts/e2e/fake_search_providers.py --port 0`  → in `FAKE_READY <cổng>`.
Nhúng:     `from fake_search_providers import FakeSearchProviders` (ngữ cảnh `with`).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

#: Tên provider theo đường dẫn — dùng chung cho nhật ký và cho kịch bản E2E.
PATH_PROVIDERS = {
    '/brave': 'brave',
    '/tavily': 'tavily',
    '/exa': 'exa',
    '/parallel': 'parallel',
    '/firecrawl': 'firecrawl',
    '/cloudflare': 'cloudflare',
    '/custom': 'custom',
    '/searxng/search': 'searxng',
}

#: Header mà mỗi provider cần, để kịch bản E2E khẳng định "khoá được gửi đúng chỗ".
AUTH_HEADERS = {
    'brave': 'X-Subscription-Token',
    'tavily': 'Authorization',
    'exa': 'x-api-key',
    'parallel': 'x-api-key',
    'firecrawl': 'Authorization',
    'cloudflare': 'Authorization',
    'custom': 'Authorization',
    'searxng': None,
}

#: Header nhạy cảm KHÔNG được xuất hiện trong thân bài trả về hay trong nhật ký (chỉ ghi tên).
SECRET_HEADERS = ('authorization', 'x-subscription-token', 'x-api-key')


def _row(title: str, url: str, snippet: str, engine: str | None = None) -> dict:
    row = {'title': title, 'url': url, 'snippet': snippet}
    if engine:
        row['engine'] = engine
    return row


def _payload(provider: str, query: str, count: int, shape: str) -> dict:
    """Thân bài đúng hình dạng của từng provider (tất cả đều có `url` để harness nhận)."""
    rows = [_row(f'{provider} result {index + 1} — {query}',
                 f'https://example.test/{provider}/{index + 1}',
                 f'đoạn mô tả {index + 1} cho "{query}" từ {provider}')
            for index in range(max(1, min(count, 5)))]
    if provider == 'brave':
        return {'web': {'results': [{'title': r['title'], 'url': r['url'], 'description': r['snippet']}
                                    for r in rows]}}
    if provider == 'tavily':
        return {'results': [{'title': r['title'], 'url': r['url'], 'content': r['snippet']} for r in rows]}
    if provider == 'exa':
        return {'results': [{'title': r['title'], 'url': r['url'], 'text': r['snippet']} for r in rows]}
    if provider == 'parallel':
        return {'results': [{'title': r['title'], 'url': r['url'], 'excerpts': [r['snippet']]} for r in rows]}
    if provider == 'firecrawl':
        return {'success': True,
                'data': [{'title': r['title'], 'url': r['url'], 'description': r['snippet']} for r in rows]}
    if provider == 'cloudflare':
        return {'items': [{'title': r['title'], 'url': r['url'], 'description': r['snippet']} for r in rows]}
    if provider == 'searxng':
        return {'results': [_row(r['title'], r['url'], r['snippet'], engine='bing') for r in rows],
                'number_of_results': len(rows)}
    # custom: hai hình dạng phổ biến, chọn bằng ?shape=items
    key = 'items' if shape == 'items' else 'results'
    return {key: rows}


class _Handler(BaseHTTPRequestHandler):
    server_version = 'FakeSearchProviders/1.0'

    # -- tiện ích ---------------------------------------------------------
    def log_message(self, *args) -> None:      # im lặng: nhật ký do kịch bản đọc
        return

    def _read_body(self) -> tuple[dict, str]:
        length = int(self.headers.get('Content-Length') or 0)
        raw = self.rfile.read(length) if length else b''
        text = raw.decode('utf-8', 'replace')
        try:
            return (json.loads(text) if text.strip() else {}), text
        except json.JSONDecodeError:
            return {}, text

    def _record(self, provider: str, query: str, count: int, body_text: str) -> None:
        headers = {name: self.headers.get(name) for name in AUTH_HEADERS.values() if name}
        self.server.calls.append({                        # type: ignore[attr-defined]
            'provider': provider,
            'method': self.command,
            'path': self.path,
            'query': query,
            'count': count,
            'authHeaders': {name: ('<present>' if value else None) for name, value in headers.items()},
            'hasSecretInBody': any(marker in body_text.lower() for marker in SECRET_HEADERS),
            'at': time.time(),
        })
        path = self.server.log_path                  # type: ignore[attr-defined]
        if path:
            with open(path, 'a', encoding='utf-8') as handle:
                handle.write(json.dumps(self.server.calls[-1], ensure_ascii=False) + '\n')  # type: ignore[attr-defined]

    def _send(self, status: int, payload: dict) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    # -- điều khiển -------------------------------------------------------
    def _control(self) -> bool:
        if self.path.startswith('/__calls'):
            self._send(200, {'calls': list(self.server.calls)})      # type: ignore[attr-defined]
            return True
        if self.path.startswith('/__reset'):
            self.server.calls.clear()                                # type: ignore[attr-defined]
            self._send(200, {'reset': True})
            return True
        if self.path.startswith('/__health'):
            self._send(200, {'ok': True})
            return True
        return False

    def _dispatch(self) -> None:
        if self._control():
            return
        split = urlsplit(self.path)
        provider = PATH_PROVIDERS.get(split.path)
        if provider is None:
            self._send(404, {'error': 'unknown fake provider path', 'path': split.path})
            return
        params = parse_qs(split.query)
        query = (params.get('q') or params.get('query') or [''])[0]
        shape = (params.get('shape') or ['results'])[0]
        body, body_text = self._read_body()
        if not query:
            query = str(body.get('query') or body.get('objective') or '')
        try:
            count = int((params.get('count') or [body.get('count') or body.get('limit')
                                                 or body.get('max_results') or body.get('numResults') or 3])[0])
        except (TypeError, ValueError):
            count = 3
        self._record(provider, query, count, body_text)

        status = int((params.get('status') or ['200'])[0])
        if status != 200:
            self._send(status, {'error': f'fake failure for {provider}', 'status': status})
            return
        if (params.get('empty') or ['0'])[0] in ('1', 'true', 'yes'):
            payload = _payload(provider, query, 0, shape)
            for key in ('results', 'items', 'data', 'web'):
                if key in payload:
                    payload[key] = [] if key != 'web' else {'results': []}
            self._send(200, payload)
            return
        self._send(200, _payload(provider, query, count, shape))

    def do_GET(self) -> None:                     # noqa: N802 — API của BaseHTTPRequestHandler
        self._dispatch()

    def do_POST(self) -> None:                    # noqa: N802
        self._dispatch()


class FakeSearchProviders:
    """Máy chủ giả chạy trong một thread; dùng như ngữ cảnh `with`."""

    def __init__(self, port: int = 0, log_path: str | None = None) -> None:
        self._server = ThreadingHTTPServer(('127.0.0.1', port), _Handler)
        self._server.calls = []                                    # type: ignore[attr-defined]
        self._server.log_path = log_path                           # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # -- vòng đời ---------------------------------------------------------
    def __enter__(self) -> 'FakeSearchProviders':
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    # -- truy vấn ---------------------------------------------------------
    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f'http://127.0.0.1:{self.port}'

    def url(self, provider: str, **params) -> str:
        path = '/searxng/search' if provider == 'searxng' else f'/{provider}'
        if not params:
            return self.base_url + path
        pairs = '&'.join(f'{key}={value}' for key, value in params.items())
        return f'{self.base_url}{path}?{pairs}'

    def calls(self, provider: str | None = None) -> list[dict]:
        rows = list(self._server.calls)                            # type: ignore[attr-defined]
        return [row for row in rows if provider is None or row['provider'] == provider]

    def reset(self) -> None:
        self._server.calls.clear()                                 # type: ignore[attr-defined]

    def env(self) -> dict:
        """Biến môi trường trỏ harness/router vào máy chủ giả này (kèm hook loopback của test)."""
        return {
            'BOXFOX_WEB_TEST_ALLOW_LOOPBACK': '1',
            'BOXFOX_SEARXNG_URL': self.url('searxng'),
            'BOXFOX_SEARXNG_AUTODETECT': 'off',
            'BOXFOX_SEARCH_PIPELINE': 'off',
            'BOXFOX_BRAVE_SEARCH_URL': self.url('brave'),
            'BOXFOX_TAVILY_SEARCH_URL': self.url('tavily'),
            'BOXFOX_EXA_SEARCH_URL': self.url('exa'),
            'BOXFOX_PARALLEL_SEARCH_URL': self.url('parallel'),
            'BOXFOX_FIRECRAWL_SEARCH_URL': self.url('firecrawl'),
            'BOXFOX_CLOUDFLARE_SEARCH_URL': self.url('cloudflare'),
            'BOXFOX_CUSTOM_SEARCH_URL': self.url('custom'),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Máy chủ provider tìm kiếm giả cho E2E của BoxFox')
    parser.add_argument('--port', type=int, default=int(os.environ.get('FAKE_SEARCH_PORT', '0')))
    parser.add_argument('--log', default=os.environ.get('FAKE_SEARCH_LOG') or None)
    args = parser.parse_args(argv)
    with FakeSearchProviders(port=args.port, log_path=args.log) as fake:
        print(f'FAKE_READY {fake.port}', flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return 0
    return 0


if __name__ == '__main__':
    sys.exit(main())
