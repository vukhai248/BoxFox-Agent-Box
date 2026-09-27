"""Chế độ gói nguồn (`BOXFOX_WEB_PACK`) — tìm và đọc KHÔNG chạm mạng (kế hoạch v2 §8.3).

VÌ SAO có chế độ này: so sánh B0/B1/A1 của 8.7 không được để nhà cung cấp tìm kiếm làm nhiễu. Gói
là một thư mục chụp sẵn (HTML/PDF/JSON API) cộng chỉ mục truy vấn; bật gói thì `web_search` trả từ
chỉ mục của gói và `web_fetch` trả tệp của gói. Không có một lời gọi mạng nào trong tệp này.

Định dạng (B3 sinh, B1 đọc):
```
<pack>/pack.json          {"scenarioId","builtAt","sources":[{"url","title","date","kind",
                           "accessLevel","file"}]}
<pack>/pages/<file>        .html | .txt | .json | .pdf
<pack>/search_index.jsonl  mỗi dòng {"query","urls":[{"url","rank","snippet"}]}
<pack>/meta.json           {"queries":[...]}   (tuỳ chọn)
```

Phân biệt quan trọng: `pack_search` trả `None` khi gói KHÔNG có `search_index.jsonl` (người gọi
phải rơi về đường thật), và trả `[]` khi CÓ chỉ mục nhưng không dòng nào khớp (gói trả lời "không
có gì", không được rơi về mạng).
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from . import reading

__all__ = ['active_pack', 'pack_search', 'pack_fetch', 'pack_pages', 'PACK_ENV']

PACK_ENV = 'BOXFOX_WEB_PACK'
_MAX_PAGES_BYTES = 4 * 1024 * 1024
#: Từ vựng `accessLevel` DUY NHẤT cho hàng trả mô hình: giống `academic.ACCESS_LEVELS` (hợp đồng
#: §4), để một trường không mang hai từ vựng (low). Gói khai theo từ vựng §3
#: (`open|abstract|paywalled|metadata`), nên đọc gói thì quy đổi.
ACCESS_LEVELS = ('snippet', 'abstract', 'fulltext-available', 'fulltext-read')
_PACK_ACCESS_MAP = {'open': 'fulltext-available', 'abstract': 'abstract',
                    'paywalled': 'snippet', 'metadata': 'snippet'}


def _access_level(value) -> str:
    """Quy `accessLevel` của gói về từ vựng chung; giá trị đã đúng từ vựng thì giữ nguyên."""
    text = str(value or '').strip().lower()
    if text in ACCESS_LEVELS:
        return text
    return _PACK_ACCESS_MAP.get(text, 'snippet')


def _fold(value: str) -> str:
    """Bỏ dấu + hạ chữ để so khớp truy vấn — dùng chung `reading.fold_text`."""
    return reading.fold_text(str(value or ''))


def _tokens(value: str) -> set[str]:
    return {tok for tok in re.findall(r'[^\W_]+', _fold(value)) if len(tok) > 1}


def _key(value: str) -> str:
    return ' '.join(_fold(value).split())


def active_pack() -> Path | None:
    """`BOXFOX_WEB_PACK` khi nó trỏ vào một thư mục đọc được; ngược lại `None`."""
    raw = (os.environ.get(PACK_ENV) or '').strip()
    if not raw:
        return None
    path = Path(os.path.expanduser(raw))
    try:
        if path.is_dir():
            return path
    except OSError:
        return None
    return None


def _sources(root: Path) -> list[dict]:
    try:
        payload = json.loads((root / 'pack.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return []
    items = payload.get('sources') if isinstance(payload, dict) else None
    return [item for item in (items or []) if isinstance(item, dict) and item.get('url')]


def _url_key(value: str) -> str:
    """Khoá so khớp URL trong gói: bỏ fragment, `www.`, và dấu `/` cuối."""
    try:
        normalized = reading.normalize_url(str(value or ''))
    except Exception:  # pragma: no cover - normalize_url không ném, nhưng giữ đường an toàn
        normalized = str(value or '').strip()
    return normalized.rstrip('/')


def _index_entries(root: Path) -> list[dict] | None:
    """Đọc `search_index.jsonl`; `None` khi KHÔNG có tệp (khác hẳn "có mà rỗng")."""
    path = root / 'search_index.jsonl'
    if not path.is_file():
        return None
    entries = []
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        return None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict) and item.get('query'):
            entries.append(item)
    return entries


def _row_for(url: str, source: dict, snippet: str = '', rank: int = 0) -> dict:
    return {'title': str(source.get('title') or url),
            'url': str(url),
            'snippet': str(snippet or '')[:400],
            'provider': 'pack',
            'engines': ['pack'],
            'rank': rank,
            'publishedAt': str(source.get('date') or ''),
            'dateSource': 'provider' if source.get('date') else 'unknown',
            'accessLevel': _access_level(source.get('accessLevel')),
            'sourceKind': str(source.get('kind') or 'page')}


def pack_search(query: str, count: int, options: dict) -> list[dict] | None:
    """Tìm trong chỉ mục của gói. Xem docstring đầu tệp về `None` so với `[]`."""
    root = active_pack()
    if root is None:
        return None
    entries = _index_entries(root)
    if entries is None:
        return None
    try:
        limit = max(1, int(count or 5))
    except (TypeError, ValueError):
        limit = 5

    query_key = _key(query)
    query_tokens = _tokens(query)
    exact = next((item for item in entries if _key(item.get('query')) == query_key), None)
    match = exact
    if match is None and query_tokens:
        best, best_score = None, 0
        for item in entries:
            tokens = _tokens(str(item.get('query') or ''))
            if not tokens or not tokens.issubset(query_tokens):
                continue
            score = len(tokens)                      # dòng khớp càng nhiều token càng đặc thù
            if score > best_score:
                best, best_score = item, score
        match = best
    if match is None:
        return []                                    # có chỉ mục, không dòng nào khớp ⇒ rỗng

    sources = {_url_key(item.get('url')): item for item in _sources(root)}
    rows = []
    for entry in (match.get('urls') or []):
        if not isinstance(entry, dict) or not entry.get('url'):
            continue
        url = str(entry['url'])
        source = sources.get(_url_key(url), {})
        rows.append(_row_for(url, source, snippet=str(entry.get('snippet') or ''),
                             rank=int(entry.get('rank') or 0)))
        if len(rows) >= limit:
            break
    return rows


def _read_page(path: Path) -> tuple[str, str]:
    """``(text, contentType)`` của một tệp trong gói — không chạm mạng."""
    suffix = path.suffix.lower()
    if suffix == '.pdf':
        raw = path.read_bytes()[:_MAX_PAGES_BYTES]
        markdown, _info = reading.pdf_to_markdown(raw)
        return markdown, 'application/pdf'
    text = path.read_text(encoding='utf-8', errors='replace')
    if suffix in {'.html', '.htm'}:
        from .web import html_to_text       # import muộn: `web.py` nhập chính mô-đun này
        _title, body, _links = html_to_text(text)
        return body, 'text/html'
    if suffix == '.json':
        return text, 'application/json'
    return text, 'text/plain'


def pack_fetch(url: str) -> dict | None:
    """Trả thân của một trang trong gói, hoặc `None` khi URL không có trong gói."""
    root = active_pack()
    if root is None:
        return None
    key = _url_key(url)
    for source in _sources(root):
        if _url_key(str(source.get('url'))) != key:
            continue
        file_name = str(source.get('file') or '')
        if not file_name:
            return None
        # Chốt `..`/đường dẫn tuyệt đối: gói do host tạo (`build_pack` đã chặn), nhưng một gói
        # dựng tay không được phép thoát khỏi cây của gói (low).
        if os.path.isabs(file_name) or '..' in Path(file_name).parts:
            return None
        # Hợp đồng §3 (và `build_pack.validate_pack`) nói `file` là đường dẫn TƯƠNG ĐỐI TRONG GÓI,
        # tức đã gồm tiền tố `pages/`. Bản đầu chỉ ghép thêm `pages/` nên mọi gói do `build_pack.py`
        # dựng đều đọc trượt (`<gói>/pages/pages/<tệp>`) và `web_fetch` báo "không có trong gói".
        # Vẫn nhận dạng cũ (tên tệp trần, tương đối trong `pages/`) để gói tự dựng tay không vỡ.
        candidates = [root / file_name, root / 'pages' / file_name]
        path = None
        for candidate in candidates:
            try:
                if candidate.is_file() and root.resolve() in candidate.resolve().parents:
                    path = candidate
                    break
            except OSError:
                continue
        if path is None:
            return None
        text, content_type = _read_page(path)
        if not text.strip():
            return None
        return {'url': str(url), 'title': str(source.get('title') or ''),
                'text': text, 'contentType': content_type,
                'publishedAt': str(source.get('date') or ''),
                'dateSource': 'provider' if source.get('date') else 'unknown'}


def pack_pages() -> list[dict]:
    """Mọi trang khai trong gói (cho chỉ mục cục bộ và cho mục "Nguồn" của báo cáo)."""
    root = active_pack()
    if root is None:
        return []
    return [{'url': str(item.get('url')), 'title': str(item.get('title') or ''),
             'publishedAt': str(item.get('date') or ''), 'kind': str(item.get('kind') or ''),
             'accessLevel': _access_level(item.get('accessLevel')),
             'file': str(item.get('file') or '')}
            for item in _sources(root)]
