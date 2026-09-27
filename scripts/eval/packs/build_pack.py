#!/usr/bin/env python3
"""Dựng một **gói nguồn** (§8.3) từ trang đã thu thập + manifest nguồn.

Gói nguồn là cách chạy đánh giá **không phụ thuộc mạng**: `web_search` và `web_fetch`
đọc từ gói thay vì gọi nhà cung cấp, nên chỉ mô hình còn là nguồn nhiễu (#6079).

Định dạng gói là **hợp đồng P0 §3** (B3 sinh, B1 `source_pack.py` đọc)::

    <pack>/pack.json          {"scenarioId","builtAt","sources":[{"url","title","date",
                               "kind","accessLevel","file"}]}
    <pack>/pages/<file>       thân trang: .html | .txt | .json | .pdf
    <pack>/search_index.jsonl mỗi dòng {"query","urls":[{"url","rank","snippet"}]}
    <pack>/meta.json          {"queries":[...]}  (tuỳ chọn)

Mô-đun này **chỉ** đọc/ghi tệp cục bộ — không mở socket, không phụ thuộc ngoài.

Cách dùng::

    python3 scripts/eval/packs/build_pack.py \\
        --manifest <nguồn.json> --out <thư mục gói> [--queries <truy-vấn.jsonl>] [--force]
    python3 scripts/eval/packs/build_pack.py --validate <thư mục gói>

Manifest nguồn:: `{"scenarioId": "S1", "sources": [{"url", "title", "date", "kind",
"accessLevel", "file"}]}` — `file` là đường dẫn tương đối tới manifest; tệp phải nằm trong
cây con của manifest (không cho `..` thoát ra).

Mã thoát: ``0`` xong, ``2`` sai cách dùng / manifest sai / gói không hợp lệ.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import time
from pathlib import Path

PAGE_EXTENSIONS = ('.html', '.htm', '.txt', '.json', '.pdf')
#: Mức truy cập của một nguồn: chỉ xem được toàn văn / tóm tắt / trả tiền / chỉ metadata.
ACCESS_LEVELS = ('open', 'abstract', 'paywalled', 'metadata')
PACK_JSON = 'pack.json'
INDEX_JSONL = 'search_index.jsonl'
PAGES_DIR = 'pages'
META_JSON = 'meta.json'

_SLUG_RE = re.compile(r'[^a-z0-9]+')
_URL_RE = re.compile(r'^[a-zA-Z][a-zA-Z0-9+.-]*://([^/?#]+)(/[^?#]*)?')


def slug_for(url: str) -> str:
    """Tên tệp an toàn, ổn định, suy từ URL (không dùng chính URL làm tên tệp)."""
    match = _URL_RE.match(str(url))
    netloc = match.group(1) if match else ''
    path = (match.group(2) or '') if match else ''
    host = _SLUG_RE.sub('-', netloc.lower()).strip('-') or 'source'
    tail = _SLUG_RE.sub('-', path.strip('/').lower()).strip('-')[:60]
    return f'{host}-{tail}' if tail else host


def load_source_manifest(path: str | Path) -> dict:
    """Đọc manifest nguồn và kiểm từng trường; lỗi ⇒ `ValueError` nói rõ chỗ sai."""
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise ValueError(f'{path}: không phải JSON ({exc})') from exc
    if not isinstance(data, dict):
        raise ValueError(f'{path}: manifest phải là một đối tượng JSON')
    scenario_id = str(data.get('scenarioId') or '').strip()
    if not scenario_id:
        raise ValueError(f'{path}: thiếu "scenarioId"')
    sources = data.get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError(f'{path}: "sources" phải là một danh sách không rỗng')
    cleaned: list[dict] = []
    seen: set[str] = set()
    for index, item in enumerate(sources, start=1):
        if not isinstance(item, dict):
            raise ValueError(f'{path}: sources[{index}] phải là một đối tượng')
        for key in ('url', 'title', 'file'):
            if not str(item.get(key) or '').strip():
                raise ValueError(f'{path}: sources[{index}] thiếu "{key}"')
        access = str(item.get('accessLevel') or 'open')
        if access not in ACCESS_LEVELS:
            raise ValueError(f'{path}: sources[{index}] accessLevel lạ: {access!r} '
                             f'(đang có: {", ".join(ACCESS_LEVELS)})')
        if item['url'] in seen:
            raise ValueError(f'{path}: sources[{index}] trùng url {item["url"]!r}')
        seen.add(item['url'])
        page = Path(str(item['file']))
        if page.is_absolute() or '..' in page.parts:
            raise ValueError(f'{path}: sources[{index}] "file" phải nằm trong cây con của manifest')
        if page.suffix.lower() not in PAGE_EXTENSIONS:
            raise ValueError(f'{path}: sources[{index}] đuôi trang không hợp lệ: {page.suffix} '
                             f'(đang có: {", ".join(PAGE_EXTENSIONS)})')
        cleaned.append({
            'url': str(item['url']),
            'title': str(item['title']),
            'date': str(item.get('date') or ''),
            'kind': str(item.get('kind') or 'web'),
            'accessLevel': access,
            'file': page,
        })
    return {'scenarioId': scenario_id, 'sources': cleaned}


def load_query_index(path: str | Path) -> list[dict]:
    """Đọc kết quả tìm đã chụp: mỗi dòng `{"query","results":[{"url","rank","snippet"}]}`.

    Nhận cả khoá `"urls"` — đó là hình dạng khi ghi ra `search_index.jsonl`, nên hàm
    này kiểm được cả gói đã dựng lẫn dữ liệu thô trước khi dựng.
    """
    path = Path(path)
    rows: list[dict] = []
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError as exc:
            raise ValueError(f'{path}:{number}: dòng không phải JSON ({exc})') from exc
        if not isinstance(item, dict) or not str(item.get('query') or '').strip():
            raise ValueError(f'{path}:{number}: mỗi dòng phải có "query"')
        results = item.get('results') if 'results' in item else item.get('urls')
        if not isinstance(results, list):
            raise ValueError(f'{path}:{number}: thiếu danh sách "results"/"urls"')
        urls = []
        for rank, row in enumerate(results):
            if not isinstance(row, dict) or not str(row.get('url') or '').strip():
                raise ValueError(f'{path}:{number}: results[{rank}] thiếu "url"')
            urls.append({'url': str(row['url']),
                         'rank': int(row.get('rank', rank + 1)),
                         'snippet': str(row.get('snippet') or '')})
        rows.append({'query': str(item['query']), 'urls': urls})
    if not rows:
        raise ValueError(f'{path}: không có dòng kết quả tìm nào')
    return rows


def build_pack(manifest_path: str | Path, out_dir: str | Path, *,
               queries_path: str | Path | None = None, built_at: str | None = None,
               force: bool = False) -> dict:
    """Dựng gói nguồn tại `out_dir`; trả `{'path','pack','sources','indexRows','files'}`."""
    manifest_path = Path(manifest_path).resolve()
    out_dir = Path(out_dir).resolve()
    manifest = load_source_manifest(manifest_path)
    if (out_dir / PACK_JSON).exists() and not force:
        raise ValueError(f'{out_dir}: đã có {PACK_JSON} — dùng --force để ghi đè')
    pages_dir = out_dir / PAGES_DIR
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for item in manifest['sources']:
        source_file = (manifest_path.parent / item['file']).resolve()
        if not source_file.is_file():
            raise ValueError(f'không thấy trang {source_file} (nguồn {item["url"]})')
        page = pages_dir / f'{slug_for(item["url"])}{source_file.suffix.lower()}'
        counter = 1
        while page.exists():
            page = page.with_name(f'{page.stem}-{counter}{page.suffix}')
            counter += 1
        shutil.copyfile(source_file, page)
        rows.append({
            'url': item['url'],
            'title': item['title'],
            'date': item['date'],
            'kind': item['kind'],
            'accessLevel': item['accessLevel'],
            'file': f'{PAGES_DIR}/{page.name}',
        })

    pack = {
        'scenarioId': manifest['scenarioId'],
        # Không bịa mốc `1970-01-01`: thiếu `--built-at` thì ghi mốc HIỆN TẠI (UTC) —
        # `reference_map.load_map` cũng từ chối một bản đồ thiếu ngày (low).
        'builtAt': built_at or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'sources': rows,
    }
    (out_dir / PACK_JSON).write_text(json.dumps(pack, ensure_ascii=False, indent=2) + '\n',
                                     encoding='utf-8')
    index_rows = 0
    if queries_path is not None:
        index = load_query_index(queries_path)
        index_rows = len(index)
        with (out_dir / INDEX_JSONL).open('w', encoding='utf-8') as handle:
            for item in index:
                handle.write(json.dumps(item, ensure_ascii=False) + '\n')
        meta = {'queries': [item['query'] for item in index]}
        (out_dir / META_JSON).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n',
                                         encoding='utf-8')
    return {'path': str(out_dir), 'pack': pack, 'sources': len(rows), 'indexRows': index_rows,
            'files': [row['file'] for row in rows]}


def validate_pack(pack_dir: str | Path) -> dict:
    """Kiểm gói có đúng hợp đồng §3 không; lỗi ⇒ `ValueError`, hợp lệ ⇒ tóm tắt."""
    pack_dir = Path(pack_dir)
    pack_path = pack_dir / PACK_JSON
    if not pack_path.is_file():
        raise ValueError(f'{pack_dir}: thiếu {PACK_JSON}')
    try:
        pack = json.loads(pack_path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise ValueError(f'{pack_path}: không phải JSON ({exc})') from exc
    if not str((pack or {}).get('scenarioId') or '').strip():
        raise ValueError(f'{pack_path}: thiếu "scenarioId"')
    sources = (pack or {}).get('sources')
    if not isinstance(sources, list) or not sources:
        raise ValueError(f'{pack_path}: "sources" phải là một danh sách không rỗng')
    for index, item in enumerate(sources, start=1):
        for key in ('url', 'title', 'date', 'kind', 'accessLevel', 'file'):
            if key not in item:
                raise ValueError(f'{pack_path}: sources[{index}] thiếu "{key}"')
        if item['accessLevel'] not in ACCESS_LEVELS:
            raise ValueError(f'{pack_path}: sources[{index}] accessLevel lạ: {item["accessLevel"]!r}')
        page = pack_dir / str(item['file'])
        if not page.is_file():
            raise ValueError(f'{pack_path}: sources[{index}] thiếu tệp {item["file"]}')
        if page.suffix.lower() not in PAGE_EXTENSIONS:
            raise ValueError(f'{pack_path}: sources[{index}] đuôi trang lạ: {page.suffix}')
    index_path = pack_dir / INDEX_JSONL
    index_rows = 0
    if index_path.is_file():
        index_rows = len(load_query_index(index_path))
    return {'path': str(pack_dir), 'scenarioId': pack['scenarioId'], 'sources': len(sources),
            'indexRows': index_rows, 'hasIndex': index_path.is_file()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Dựng/kiểm gói nguồn §8.3 (offline).')
    parser.add_argument('--manifest', default=None, help='JSON nguồn đã thu thập')
    parser.add_argument('--out', default=None, help='thư mục gói sẽ dựng')
    parser.add_argument('--queries', default=None, help='JSONL kết quả tìm đã chụp (tuỳ chọn)')
    parser.add_argument('--built-at', default=None, help='mốc ISO-8601 ghi vào pack.json')
    parser.add_argument('--force', action='store_true', help='ghi đè gói đã có')
    parser.add_argument('--validate', default=None, help='kiểm một gói đã dựng rồi thoát')
    args = parser.parse_args(argv)
    try:
        if args.validate:
            print(json.dumps(validate_pack(args.validate), ensure_ascii=False, indent=2))
            return 0
        if not args.manifest or not args.out:
            print('cần --manifest và --out (hoặc --validate <thư mục gói>)', file=sys.stderr)
            return 2
        result = build_pack(args.manifest, args.out, queries_path=args.queries,
                            built_at=args.built_at, force=args.force)
        print(json.dumps({'path': result['path'], 'sources': result['sources'],
                          'indexRows': result['indexRows']}, ensure_ascii=False, indent=2))
        return 0
    except ValueError as exc:
        print(f'lỗi gói nguồn: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    raise SystemExit(main())
