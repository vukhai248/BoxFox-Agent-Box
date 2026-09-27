#!/usr/bin/env python3
"""Probe SearXNG cục bộ: đo mức sẵn sàng theo TỪNG ENGINE (đầu vào của P0b, kế hoạch 8.7).

VÌ SAO cần: bước 7 của ống tìm (5.4.1) dựa vào việc "engine nào còn khoẻ"; trước khi bật
`BOXFOX_SEARCH_PIPELINE=on` cần biết instance trả lời được, engine nào ra kết quả, engine nào bị
chặn/hết giờ. Script này chỉ ĐỌC, không ghi DB, không cần khoá.

Cách dùng:
    BOXFOX_SEARXNG_URL=http://127.0.0.1:8888 python deploy/searxng/probe.py
    python deploy/searxng/probe.py --url http://127.0.0.1:8888 --query "retrieval augmented generation"

Nó gọi `/search?format=json` cho vài truy vấn thử, rồi in:
  * trạng thái chung (HTTP, có JSON không);
  * số kết quả theo từng engine trong trường `engine` của kết quả;
  * danh sách `unresponsive_engines` (engine bị CAPTCHA/403/429/hết giờ);
  * một lời gọi `engines=brave` riêng để kiểm nền proxy Brave (8.7 mục "Cấu hình so sánh").

Mã thoát: 0 = ít nhất một truy vấn trả kết quả; 2 = instance trả lời nhưng không có kết quả nào;
3 = không kết nối được.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_QUERIES = ('retrieval augmented generation', 'tin tức công nghệ mới nhất')
DEFAULT_ENGINES = ('brave', 'duckduckgo', 'mojeek', 'qwant', 'startpage', 'bing', 'google')


def _call(base: str, query: str, *, engines: str = '', timeout: float = 12.0) -> tuple[int, str]:
    params = {'q': query, 'format': 'json', 'safesearch': '0', 'pageno': 1}
    if engines:
        params['engines'] = engines
    url = base.rstrip('/') + '/search?' + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return getattr(response, 'status', 200), response.read(4 * 1024 * 1024).decode('utf-8', 'replace')
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.read(400) or b'').decode('utf-8', 'replace')
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, f'{exc.__class__.__name__}: {exc}'


def probe(base: str, queries: tuple[str, ...]) -> int:
    answered_with_results = False
    answered = False
    for query in queries:
        started = time.time()
        status, body = _call(base, query)
        elapsed = int((time.time() - started) * 1000)
        print(f'\n== {query!r}  (HTTP {status}, {elapsed} ms)')
        if status == 0:
            print(f'   không kết nối được: {body}')
            continue
        answered = True
        try:
            payload = json.loads(body or '{}')
        except ValueError:
            print(f'   trả lời không phải JSON: {body[:200]}')
            continue
        per_engine: dict[str, int] = {}
        for item in (payload.get('results') or []):
            engine = str(item.get('engine') or 'unknown')
            per_engine[engine] = per_engine.get(engine, 0) + 1
        if payload.get('results'):
            answered_with_results = True
        for engine, hits in sorted(per_engine.items(), key=lambda kv: (-kv[1], kv[0])):
            print(f'   OK    {engine:<24} {hits} kết quả')
        for item in (payload.get('unresponsive_engines') or []):
            engine = item[0] if isinstance(item, (list, tuple)) and item else str(item)
            reason = item[1] if isinstance(item, (list, tuple)) and len(item) > 1 else ''
            print(f'   LỖI   {engine:<24} {reason}')
        if not per_engine:
            print('   (không có engine nào trả kết quả)')

    # Nền proxy Brave của 8.7: một truy vấn, chỉ engine brave.
    started = time.time()
    status, body = _call(base, queries[0], engines='brave')
    print(f'\n== nền Brave (engines=brave)  (HTTP {status}, {int((time.time() - started) * 1000)} ms)')
    try:
        payload = json.loads(body or '{}')
        print(f'   brave trả {len(payload.get("results") or [])} kết quả; '
              f'unresponsive={payload.get("unresponsive_engines")}')
    except ValueError:
        print(f'   trả lời không phải JSON: {body[:200]}')

    if not answered:
        return 3
    return 0 if answered_with_results else 2


def main() -> int:
    parser = argparse.ArgumentParser(description='Probe SearXNG cục bộ theo từng engine')
    parser.add_argument('--url', default=os.environ.get('BOXFOX_SEARXNG_URL') or 'http://127.0.0.1:8888')
    parser.add_argument('--query', action='append', default=[], help='thêm truy vấn thử (lặp được)')
    args = parser.parse_args()
    queries = tuple(args.query) or DEFAULT_QUERIES
    print(f'SearXNG: {args.url}')
    print(f'Engines web mặc định cần có: {", ".join(DEFAULT_ENGINES)}')
    return probe(args.url, queries)


if __name__ == '__main__':
    sys.exit(main())
