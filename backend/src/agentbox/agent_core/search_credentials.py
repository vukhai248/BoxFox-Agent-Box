"""Nguồn tìm kiếm người dùng chọn trong Settings → Provider → Web Search (PART 2, task 3).

Harness không giữ khoá tìm kiếm: khoá nằm **mã hoá trong router** (cổng 3101) và chỉ ra khỏi đó
qua `GET /api/router/search/resolve` (admin-gated). Mô-đun này là đầu đọc DUY NHẤT phía harness:

- một lời gọi ĐỒNG BỘ bằng `urllib` (không thêm phụ thuộc), header `x-boxfox-admin: 1`, timeout
  2 giây, bỏ qua proxy môi trường — cùng tinh thần `RouterClient` trong `runtime.py`;
- cache trong tiến trình, TTL `BOXFOX_SEARCH_SOURCE_TTL` giây (mặc định 15): trong TTL **không**
  phát sinh lời gọi HTTP nào; `BOXFOX_SEARCH_REFRESH=1` buộc đọc lại (test);
- **không bao giờ ném**: router chết/sai định dạng ⇒ trả cache cũ nếu còn trong TTL, ngược lại
  `None` — nghĩa là "Mặc định", để đường built-in của PART 1 tiếp tục chạy.

`None` là câu trả lời HỢP LỆ (người dùng chọn "Mặc định"), không phải lỗi. Khoá thô chỉ sống
trong `SearchSource` của tiến trình: không vào log, không vào payload, không vào snapshot.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from dataclasses import dataclass

from .limits import (ROUTER_SEARCH_RESOLVE_URL_DEFAULT, SEARCH_SOURCE_TIMEOUT_SECONDS,
                     SEARCH_SOURCE_TTL_SECONDS)

logger = logging.getLogger(__name__)

__all__ = ['SearchSource', 'active_source', 'invalidate', 'cache_key', 'searxng_url', 'resolve_url']

ROUTER_SEARCH_URL_ENV = 'BOXFOX_ROUTER_SEARCH_URL'
TTL_ENV = 'BOXFOX_SEARCH_SOURCE_TTL'
REFRESH_ENV = 'BOXFOX_SEARCH_REFRESH'

#: Mục CẦN khoá trong `active`: thiếu khoá ⇒ coi như "Mặc định" (D3 — rơi về đường built-in).
#: `searxng`/`custom` cần endpoint (tự chân nói ra khi thiếu); `custom` không bắt buộc khoá.
_KEYED_PROVIDER_IDS = frozenset({'brave', 'tavily', 'exa', 'parallel', 'firecrawl', 'cloudflare'})

#: Sentinel nội bộ: `_fetch()` hỏng (khác hẳn "router trả lời: đang dùng Mặc định").
_FAILED = object()
_ON_VALUES = ('1', 'true', 'yes', 'on')


@dataclass(frozen=True)
class SearchSource:
    """Một nguồn tìm kiếm đang được chọn, đã chuẩn hoá từ `active` của router.

    `revision` là bộ đếm của router: mọi thao tác ghi lên lựa chọn đều tăng nó, nên nó đi vào
    khoá cache tìm kiếm (`cache_key()`) để đổi nguồn là KHÔNG dùng lại kết quả của nguồn cũ.
    """

    provider_id: str
    api_key: str | None
    account_id: str | None
    endpoint: str | None
    revision: int


#: Trạng thái cache trong tiến trình. `value` là câu trả lời THÀNH CÔNG gần nhất (kể cả `None`
#: nghĩa là "Mặc định"); `value_at`/`attempted_at` tách "lần đọc thành công cuối" khỏi "lần thử
#: cuối" để lần đọc hỏng vẫn giữ được cache cũ mà không dội HTTP vào router.
_STATE: dict = {'value': None, 'value_at': 0.0, 'attempted_at': 0.0, 'failure_logged': False}
_LOCK = threading.Lock()


def resolve_url() -> str:
    """Endpoint phân giải của router: `BOXFOX_ROUTER_SEARCH_URL` hoặc loopback mặc định."""
    return (os.environ.get(ROUTER_SEARCH_URL_ENV) or '').strip() or ROUTER_SEARCH_RESOLVE_URL_DEFAULT


def _ttl_seconds() -> float:
    """TTL cache (`BOXFOX_SEARCH_SOURCE_TTL`); giá trị trống/âm/lạ ⇒ mặc định 15 giây."""
    try:
        value = float((os.environ.get(TTL_ENV) or '').strip())
    except ValueError:
        return SEARCH_SOURCE_TTL_SECONDS
    return value if value >= 0 else SEARCH_SOURCE_TTL_SECONDS


def _refresh_requested() -> bool:
    """`BOXFOX_SEARCH_REFRESH=1` ⇒ luôn đọc lại router (test), bỏ qua cache TTL."""
    return (os.environ.get(REFRESH_ENV) or '').strip().lower() in _ON_VALUES


def _text_or_none(value: object) -> str | None:
    text = str(value).strip() if value is not None else ''
    return text or None


def _int_or_zero(value: object) -> int:
    try:
        return int(value)          # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _parse(payload: object) -> SearchSource | None:
    """Chuẩn hoá payload `/resolve`; hình dạng SAI ⇒ `ValueError` (người gọi coi là lần đọc hỏng)."""
    if not isinstance(payload, dict):
        raise ValueError('the resolve payload is not an object')
    active = payload.get('active')
    if active is None:
        return None                                     # "Mặc định" — hợp lệ
    if not isinstance(active, dict):
        raise ValueError('active is neither an object nor null')
    provider_id = str(active.get('id') or '').strip()
    if not provider_id:
        raise ValueError('active has no id')
    api_key = _text_or_none(active.get('apiKey'))
    if provider_id in _KEYED_PROVIDER_IDS and not api_key:
        # D3: mục cần khoá mà khoá trống ⇒ coi như "Mặc định", rơi về đường built-in.
        return None
    return SearchSource(provider_id=provider_id, api_key=api_key,
                        account_id=_text_or_none(active.get('accountId')),
                        endpoint=_text_or_none(active.get('endpoint')),
                        revision=_int_or_zero(payload.get('revision')))


def _fetch() -> object:
    """Một lời đọc router. Trả `SearchSource`, `None` (Mặc định) hoặc sentinel `_FAILED`."""
    request = urllib.request.Request(resolve_url(), method='GET',
                                     headers={'x-boxfox-admin': '1', 'Accept': 'application/json'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=SEARCH_SOURCE_TIMEOUT_SECONDS) as response:
            body = response.read(64 * 1024)
        return _parse(json.loads(body.decode('utf-8', 'replace') or '{}'))
    except Exception as exc:                # router chết/sai định dạng ⇒ KHÔNG bao giờ ném
        _note_failure(exc)
        return _FAILED


def _note_failure(exc: BaseException) -> None:
    """Ghi MỘT dòng cho mỗi đợt hỏng (không phải mỗi lời gọi); câu chữ không chứa khoá/truy vấn."""
    with _LOCK:
        if _STATE['failure_logged']:
            return
        _STATE['failure_logged'] = True
    logger.info('search source resolve failed (%s); the built-in search path stays in charge',
                exc.__class__.__name__)


def active_source(*, force: bool = False) -> SearchSource | None:
    """Nguồn đang được chọn (cache TTL), hoặc `None` = "Mặc định". KHÔNG bao giờ ném.

    `force=True` bỏ qua cache và đọc lại ngay (test/hậu kiểm); hỏng thì vẫn trả cache cũ nếu nó
    còn trong TTL, đúng hợp đồng §Task 3.
    """
    now = time.monotonic()
    ttl = _ttl_seconds()
    if not force and not _refresh_requested():
        with _LOCK:
            if _STATE['attempted_at'] and (now - _STATE['attempted_at']) < ttl:
                return _STATE['value']
    result = _fetch()
    with _LOCK:
        _STATE['attempted_at'] = time.monotonic()
        if result is not _FAILED:
            _STATE['value'] = result
            _STATE['value_at'] = _STATE['attempted_at']
            _STATE['failure_logged'] = False
            return result
        if _STATE['value_at'] and (_STATE['attempted_at'] - _STATE['value_at']) < ttl:
            return _STATE['value']                       # lần đọc hỏng: giữ cache cũ còn trong TTL
        _STATE['value'] = None                           # cache cũ đã hết hạn ⇒ "Mặc định"
        return None


def invalidate() -> None:
    """Xoá cache nguồn: lần gọi sau đọc lại router (test, hoặc sau khi biết lựa chọn đã đổi)."""
    with _LOCK:
        _STATE.update({'value': None, 'value_at': 0.0, 'attempted_at': 0.0, 'failure_logged': False})


def cache_key() -> str:
    """Khoá cache NGẮN của lựa chọn: `'default'`, hoặc `'brave@5'` (provider + revision)."""
    source = active_source()
    if source is None:
        return 'default'
    return f'{source.provider_id}@{source.revision}'


def searxng_url() -> str:
    """Endpoint của mục `searxng` KHI ĐANG ĐƯỢC CHỌN; ngược lại `''` (PART 1 tự đọc env/tự dò)."""
    source = active_source()
    if source is None or source.provider_id != 'searxng':
        return ''
    return str(source.endpoint or '').strip()
