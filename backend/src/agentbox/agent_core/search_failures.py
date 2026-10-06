"""Phân loại lỗi tìm kiếm web (F05) — câu chữ nói đúng VIỆC CẦN LÀM, không xui sửa truy vấn vô ích.

Bối cảnh (đo 06/10/2026, `docs/plan/Work-Graph-fix.md` F05): khi hạ tầng tìm kiếm chết (Firecrawl
403/429, thiếu khoá, SearXNG chưa bật), thông báo cũ vẫn kết thúc bằng lời khuyên "thử truy vấn
khác" — agent đọc thế là đổi câu chữ rồi gọi lại, đốt bước trên một hạ tầng không thể chữa bằng
truy vấn. Mô-đun này tách bốn ca:

- ``config`` — chưa cấu hình gì cả (không khoá env, không nguồn chọn, không SearXNG): chỉ đường bật.
- ``infra``  — CÓ backend được cấu hình/chọn nhưng mọi chân đều hỏng: nói rõ là vấn đề backend.
- ``empty``  — mọi chân trả lời mà không có hàng nào: ĐÂY mới là ca được phép nói tới truy vấn.
- ``source`` — nhóm nguồn cụ thể (`source="wikipedia"`, …) hỏng: nói tên nguồn, gợi ý nguồn khác.

Mô-đun KHÔNG nhập `web`/`search_pipeline` (tránh vòng nhập) — chỉ nhận dữ liệu đã gom sẵn.
"""
from __future__ import annotations

WEB_SEARCH_UNAVAILABLE = 'WEB_SEARCH_UNAVAILABLE'
WEB_SEARCH_EMPTY = 'WEB_SEARCH_EMPTY'
#: Sentinel `_search_leg` trả khi MỌI chân trả danh sách rỗng (không chân nào ném).
NO_PROVIDER_ANSWERED = 'no provider answered'
KINDS = ('config', 'infra', 'source')
#: Con trỏ tới tab Settings do PART 1 đặt — PART 2 không thêm lần nữa.
SETTINGS_POINTER = 'Settings → Provider → Web Search'
UP_SCRIPT = 'bash deploy/searxng/up.sh'
PROBE_SCRIPT = 'python3 deploy/searxng/probe.py'


def classify(*, source: str, reasons, answered_empty: bool, backends, missing,
             searxng_url: str = '', autodetect_url: str = '') -> dict:
    """`{'code', 'kind'}` theo bảng F05. Không đoán mò: chỉ dùng dữ liệu người gọi đưa vào.

    - `reasons`: lý do từng chân (rỗng ⇒ không chân nào ném).
    - `answered_empty`: MỌI chân trả lời với danh sách rỗng (không chân nào ném).
    - `backends`: backend ĐƯỢC CẤU HÌNH/CHỌN (không phải "mọi chân đã thử" — chân keyless luôn có
      mặt nên nếu tính nó thì ca "chưa cấu hình gì" sẽ bị xếp nhầm thành `infra`).
    - `missing`: tên các biến khoá còn thiếu (chỉ dùng cho câu chữ).
    """
    del searxng_url, autodetect_url                       # hai tham số này chỉ dùng ở `message_for`
    reasons = [str(reason) for reason in (reasons or []) if str(reason).strip()]
    backends = [str(backend) for backend in (backends or []) if str(backend).strip()]
    missing = [str(name) for name in (missing or []) if str(name).strip()]
    if answered_empty and not reasons:
        return {'code': WEB_SEARCH_EMPTY, 'kind': ''}
    if str(source or 'web') != 'web':
        return {'code': WEB_SEARCH_UNAVAILABLE, 'kind': 'source'}
    if backends:
        return {'code': WEB_SEARCH_UNAVAILABLE, 'kind': 'infra'}
    return {'code': WEB_SEARCH_UNAVAILABLE, 'kind': 'config'}


def message_for(*, code: str, kind: str, source: str, reasons, backends, missing,
                query: str = '', searxng_url: str = '', autodetect_url: str = '') -> str:
    """Câu gửi MODEL: nói rõ cấu hình/hạ tầng, kèm việc cần làm, kèm lý do từng chân.

    Bản này ĐƯỢC chứa truy vấn và URL (model cần biết cái gì hỏng); bản ghi nhật ký thì không
    (`log_line_for`).
    """
    reasons = [str(reason) for reason in (reasons or []) if str(reason).strip()]
    missing = [str(name) for name in (missing or []) if str(name).strip()]
    head = f'no result for {query!r}: ' if query else 'no result: '
    detail = ' | '.join(reasons[:3]) if reasons else 'no backend answered'
    if code == WEB_SEARCH_EMPTY:
        return (head + f'the search backends answered but returned no rows ({detail}). This is not '
                'an infrastructure failure: change or widen the query once, or try another source; '
                'do not repeat the same call unchanged.')
    if kind == 'source':
        return (head + f'the {source!r} source failed: {detail}. Try another source (for example '
                '"web" or "wikipedia"); do not repeat the same call unchanged.')
    if kind == 'infra':
        names = ', '.join(str(backend) for backend in (backends or [])) or 'the configured backend'
        target = searxng_url or autodetect_url or ''
        where = f' at {target}' if target else ''
        return (head + f'every configured web-search backend failed ({names}{where}): {detail}. '
                f'This is a backend problem, not a query problem — do not retry the same search. '
                f'Check it with {PROBE_SCRIPT} or {UP_SCRIPT}, set BOXFOX_SEARXNG_URL, or add a '
                f'search key in {SETTINGS_POINTER}.')
    keys = f' Missing keys: {", ".join(missing)}.' if missing else ''
    return (head + f'nothing is configured to search the web and this is a configuration problem, '
            f'not a query problem ({detail}). Enable the built-in search with {UP_SCRIPT}, set '
            f'BOXFOX_SEARXNG_URL, or add a search key in {SETTINGS_POINTER}.{keys} Do not retry the '
            'same search until a backend is configured.')


def log_line_for(*, code: str, kind: str, source: str, queries: int, attempts: int) -> str:
    """Bản ghi nhật ký: KHÔNG truy vấn, KHÔNG URL (quy ước `WebError.log_message`)."""
    if code == WEB_SEARCH_EMPTY:
        return f'every search backend answered with no rows for {queries} quer' \
               f'{"y" if queries == 1 else "ies"}'
    if kind == 'source':
        return f'source {source!r} failed for {queries} quer' \
               f'{"y" if queries == 1 else "ies"} ({attempts} attempt(s))'
    if kind == 'infra':
        return f'every configured web-search backend failed for {queries} quer' \
               f'{"y" if queries == 1 else "ies"} ({attempts} attempt(s))'
    return f'no web-search backend is configured for {queries} quer' \
           f'{"y" if queries == 1 else "ies"}'
