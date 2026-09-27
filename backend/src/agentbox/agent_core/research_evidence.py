"""Luật bằng chứng và chính sách thời gian cho research v2 (P2, §5.6–5.7).

Tệp này **thuần**: không I/O, không `self`, không bao giờ ném. Mọi hàm nhận list các dict bằng
chứng — hình dạng do `SessionStore.evidence_claims` trả ra, cộng vài cờ tuỳ chọn:

```python
{'sourceId': 's-…', 'claimId': 'c-…', 'rowId': 'r3', 'tier': 1,
 'accessLevel': 'fulltext-read', 'originCluster': 'arxiv:2401.1',
 'publishedAt': '2026-03-02' | '', 'updatedAt': '', 'versionLabel': '',
 'sectionKind': 'method' | 'results' | 'limitations' | '', 'sourceKind': 'paper',
 'recordedConditions': False, 'independentReplication': False, 'ladder': 'case-study'}
```

Ý chính của §5.7: **máy tính mức trần** (`confidence_cap`), mô hình chỉ được **hạ** xuống
(`apply_cap`), không bao giờ nâng quá trần. Mức trần là hàm của bằng chứng đang có trong sổ, nên
cùng một nhận định ở hai thời điểm khác nhau có thể có hai trần khác nhau — đó là chủ ý.

Mã luật (`rule`) nằm trong `basis` để cổng chấm và người đọc truy được vì sao ra mức đó. Danh sách
trong `/code/.plans/p23-interfaces.md` §3 là bắt buộc; tệp này thêm đúng ba mã cho các ca không có
bằng chứng hoặc chỉ có nguồn không xác định: `no-evidence`, `undated-only`, `unclassified`.
"""

from __future__ import annotations

import calendar
import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from . import limits

# --- từ vựng dùng chung -----------------------------------------------------

#: Loại nhận định (§5.7). `inference`/`recommendation` không mang độ tin cậy của dữ kiện.
CLAIM_TYPES = ('numeric', 'event', 'method', 'benchmark', 'trend', 'current-fact', 'market', 'gap',
               'inference', 'recommendation')
#: Nhận định do nguồn nói, do agent suy ra, hay do agent đề xuất.
STANCE_ORIGINS = ('source-stated', 'agent-inference', 'agent-proposal')
#: Mức tin cậy. `contested` là **trạng thái** (có phản bác cùng hạng), không nằm trong thang này.
CONFIDENCE_LEVELS = ('high', 'medium', 'low', 'unknown')
CONFIDENCE_RANK = {'unknown': 0, 'low': 1, 'medium': 2, 'high': 3}
#: Mức truy cập của đoạn trích — trùng đúng `source_pack.ACCESS_LEVELS`.
ACCESS_LEVELS = ('snippet', 'abstract', 'fulltext-available', 'fulltext-read')
ACCESS_RANK = {'snippet': 1, 'abstract': 2, 'fulltext-available': 3, 'fulltext-read': 4}
#: Loại nguồn, dùng để chọn mẫu trích xuất và để chấm `market`.
SOURCE_KINDS = ('paper', 'preprint', 'repo', 'dataset', 'model', 'docs', 'blog', 'news', 'vendor',
                'standard', 'forum', 'report', 'page', 'other')
#: Tốc độ lĩnh vực (§5.6). Cửa sổ "hiện trạng" tính bằng ngày.
TIME_VELOCITIES = ('very-fast', 'fast', 'medium', 'slow')
VELOCITY_WINDOW_DAYS = {'very-fast': 270, 'fast': 630, 'medium': 1460, 'slow': 3650}
#: Nấc bằng chứng thị trường (§5.7) — thấp → cao.
MARKET_LADDER = ('lab', 'demo', 'marketing', 'case-study', 'independent', 'legal')

#: Các kiểu nhận định phải nằm trong cửa sổ thời gian mới được coi là "hiện trạng".
CURRENT_CLAIM_TYPES = ('trend', 'current-fact')
#: Các mục ngày theo dõi (§5.6), theo thứ tự ưu tiên dùng làm ngày của bằng chứng.
DATE_FIELDS = ('publishedAt', 'updatedAt', 'eventDate')

_TWO_PART_SUFFIXES = frozenset((
    'co.uk', 'org.uk', 'ac.uk', 'gov.uk', 'me.uk', 'com.au', 'net.au', 'org.au', 'edu.au', 'gov.au',
    'co.nz', 'org.nz', 'co.jp', 'or.jp', 'ne.jp', 'ac.jp', 'com.cn', 'org.cn', 'gov.cn', 'edu.cn',
    'com.tw', 'org.tw', 'edu.tw', 'co.kr', 'or.kr', 'ac.kr', 'com.br', 'com.mx', 'com.ar',
    'co.in', 'org.in', 'ac.in', 'gov.in', 'co.za', 'com.sg', 'edu.sg', 'com.hk', 'edu.hk',
    'com.vn', 'edu.vn', 'gov.vn', 'org.vn',
))

_MONTH_NAMES = ('january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september',
                'october', 'november', 'december')
_MONTH_SHORT = ('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec')

_DATE_RE = re.compile(r'(\d{4})-(\d{2})-(\d{2})')
_MONTH_RE = re.compile(r'(\d{4})-(\d{2})(?!\d)')
_YEAR_RE = re.compile(r'(?<!\d)(\d{4})(?!\d)')

_MARKET_ALIASES = {
    'lab': 'lab', 'lab-claim': 'lab', 'research-lab': 'lab', 'nghiên cứu': 'lab',
    'demo': 'demo', 'prototype': 'demo', 'thử nghiệm': 'demo',
    'marketing': 'marketing', 'marketing-claim': 'marketing', 'vendor': 'marketing',
    'tiếp thị': 'marketing',
    'case-study': 'case-study', 'case study': 'case-study', 'ca-khach-hang': 'case-study',
    'customer': 'case-study', 'deployment': 'case-study',
    'independent': 'independent', 'independent-report': 'independent', 'third-party': 'independent',
    'legal': 'legal', 'filing': 'legal', 'hồ sơ pháp lý': 'legal',
}

_ACCESS_ALIASES = {
    '': 'snippet', 'snippet': 'snippet', 'snippets': 'snippet', 'trích đoạn': 'snippet',
    'abstract': 'abstract', 'abstract-only': 'abstract', 'tóm tắt': 'abstract',
    'fulltext-available': 'fulltext-available', 'fulltext': 'fulltext-available',
    'full-text-available': 'fulltext-available', 'available': 'fulltext-available',
    'fulltext-read': 'fulltext-read', 'full-text-read': 'fulltext-read', 'fulltext_read': 'fulltext-read',
    'open': 'fulltext-available', 'paywalled': 'snippet', 'metadata': 'snippet',
}

_CLAIM_TYPE_ALIASES = {
    'current_fact': 'current-fact', 'currentfact': 'current-fact', 'current fact': 'current-fact',
    'fact': 'current-fact', 'number': 'numeric', 'statistic': 'numeric', 'metric': 'numeric',
    'experiment': 'benchmark', 'evaluation': 'benchmark', 'survey': 'trend',
    'hypothesis': 'inference', 'speculation': 'inference', 'proposal': 'recommendation',
    'recommendation': 'recommendation', 'recommendations': 'recommendation',
    'missing': 'gap', 'limitation': 'gap',
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ('' if value is None else str(value).strip())


def _slug(value: Any) -> str:
    return re.sub(r'\s+', ' ', _text(value)).casefold()


def entries(evidence: Any) -> list:
    """Lọc list bằng chứng: chỉ giữ dict, không bao giờ ném."""
    if isinstance(evidence, Mapping):
        return [dict(evidence)]
    if not isinstance(evidence, (list, tuple, set)):
        return []
    return [dict(item) for item in evidence if isinstance(item, Mapping)]


def _entry_id(entry: Mapping) -> str:
    for key in ('claimId', 'rowId', 'sourceId', 'passageId'):
        value = _text(entry.get(key))
        if value:
            return value
    return ''


def entry_date(entry: Mapping) -> str:
    """Ngày của một mục bằng chứng: `publishedAt` → `updatedAt` → `eventDate` → `''`."""
    if not isinstance(entry, Mapping):
        return ''
    for field in DATE_FIELDS:
        value = parse_date(entry.get(field))
        if value:
            return value
    return ''


# --- thời gian --------------------------------------------------------------

def window_days(velocity: Any) -> int:
    """Số ngày của cửa sổ hiện trạng theo tốc độ lĩnh vực; `0` khi không nhận ra."""
    return int(VELOCITY_WINDOW_DAYS.get(_slug(velocity), 0))


def survey_date(now: Any = None) -> str:
    """Mốc khảo sát `YYYY-MM-DD` (UTC) — runtime cấp, mô hình không tự đoán."""
    stamp = time.time() if now is None else now
    if isinstance(stamp, str):
        parsed = parse_date(stamp)
        if parsed:
            return parsed
        stamp = time.time()
    if isinstance(stamp, datetime):
        moment = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
    else:
        try:
            moment = datetime.fromtimestamp(float(stamp), tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            moment = datetime.now(timezone.utc)
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%d')


def parse_date(value: Any) -> str:
    """Chuẩn hoá một mục ngày về `YYYY-MM-DD`; không đọc được thì trả `''` (không đoán)."""
    if value is None or isinstance(value, bool):
        return ''
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).strftime('%Y-%m-%d')
    if isinstance(value, date):
        return value.strftime('%Y-%m-%d')
    if isinstance(value, (int, float)):
        # Epoch giây hoặc mili giây; giá trị vô lý thì coi như không có ngày.
        stamp = float(value)
        if stamp > 1e11:
            stamp /= 1000.0
        if stamp <= 0 or stamp > 4102444800:  # 2100-01-01
            return ''
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc).strftime('%Y-%m-%d')
        except (OverflowError, OSError, ValueError):
            return ''
    text = _text(value)
    if not text:
        return ''
    match = _DATE_RE.search(text)
    if match:
        return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    spelled = _spelled_month(text)
    if spelled:
        return spelled
    match = _MONTH_RE.search(text)
    if match:
        return _safe_date(int(match.group(1)), int(match.group(2)), 1)
    match = _YEAR_RE.search(text)
    if match:
        return _safe_date(int(match.group(1)), 1, 1)
    return ''


def _spelled_month(text: str) -> str:
    """`'2 March 2026'`, `'March 2, 2026'`, `'Mar 2026'` → `YYYY-MM-DD`; không khớp ⇒ `''`."""
    lowered = text.casefold()
    month = 0
    for index, name in enumerate(_MONTH_NAMES, start=1):
        if re.search(r'\b' + name + r'\.?\b', lowered) or re.search(
                r'\b' + _MONTH_SHORT[index - 1] + r'\.?\b', lowered):
            month = index
            break
    if not month:
        return ''
    year_match = re.search(r'(?<!\d)(\d{4})(?!\d)', text)
    if not year_match:
        return ''
    day_match = re.search(r'(?<!\d)(\d{1,2})(?!\d)', text)
    day = 1
    if day_match:
        candidate = int(day_match.group(1))
        # Ngày đứng trước tháng (`2 March 2026`) hoặc sau tháng (`March 2, 2026`); số 4 chữ số là năm.
        if 1 <= candidate <= 31 and len(day_match.group(1)) <= 2:
            day = candidate
    return _safe_date(int(year_match.group(1)), month, day)


def _safe_date(year: int, month: int, day: int) -> str:
    """Ngày hợp lệ hoá; tháng/ngày ngoài khoảng thì kẹp lại, năm vô lý thì trả `''`."""
    if year < 1000 or year > 9999:
        return ''
    month = min(max(month, 1), 12)
    last_day = calendar.monthrange(year, month)[1]
    try:
        return datetime(year, month, min(max(day, 1), last_day), tzinfo=timezone.utc).strftime('%Y-%m-%d')
    except ValueError:
        return ''


def window_bounds(velocity: Any, *, as_of: Any = None) -> dict:
    """Cửa sổ hiện trạng của một tốc độ: `{'velocity','days','start','end'}` (start/end ISO)."""
    days = window_days(velocity)
    end = survey_date(as_of)
    start = ''
    if days:
        try:
            start = (datetime.strptime(end, '%Y-%m-%d') - timedelta(days=days)).strftime('%Y-%m-%d')
        except ValueError:
            start = ''
    return {'velocity': _slug(velocity) if _slug(velocity) in TIME_VELOCITIES else '',
            'days': days, 'start': start, 'end': end}


def date_in_window(value: Any, *, window_days: int, as_of: Any = None) -> bool:
    """Ngày có nằm trong cửa sổ `[as_of - window_days, as_of]`? Không rõ ngày ⇒ `False`."""
    moment = parse_date(value)
    if not moment or int(window_days or 0) <= 0:
        return False
    end = survey_date(as_of)
    try:
        high = datetime.strptime(end, '%Y-%m-%d')
        low = high - timedelta(days=int(window_days))
        point = datetime.strptime(moment, '%Y-%m-%d')
    except ValueError:
        return False
    return low <= point <= high


def in_window_support(evidence: Any, *, window_days: int, as_of: Any = None) -> dict:
    """Chia bằng chứng thành trong cửa sổ / ngoài cửa sổ / không rõ ngày (theo `claimId`)."""
    rows = entries(evidence)
    inside, outside, undated = [], [], []
    for entry in rows:
        moment = entry_date(entry)
        if not moment:
            undated.append(_entry_id(entry))
            continue
        if date_in_window(moment, window_days=window_days, as_of=as_of):
            inside.append(_entry_id(entry))
        else:
            outside.append(_entry_id(entry))
    return {'inWindow': inside, 'outside': outside, 'undated': undated,
            'counts': {'inWindow': len(inside), 'outside': len(outside), 'undated': len(undated),
                       'total': len(rows)}}


def stale_current_claim(claim_type: Any, evidence: Any, *, window_days: int,
                        as_of: Any = None) -> dict:
    """Nhận định hiện trạng mà **mọi** nguồn đỡ đều ngoài cửa sổ ⇒ lỗi cổng (§5.6).

    Cửa sổ chưa khai (`window_days <= 0`) ⇒ KHÔNG có "ngoài cửa sổ" nào để nói: trả về không-cũ.
    `date_in_window` coi mọi ngày là ngoài cửa sổ khi `window_days <= 0`, nên nếu không chặn ở đây
    hàm sẽ phán bừa `stale=True` cho người gọi sau (`finding 9`).
    """
    kind = normalize_claim_type(claim_type)
    support = in_window_support(evidence, window_days=window_days, as_of=as_of)
    counts = support['counts']
    stale = bool(int(window_days or 0) > 0 and kind in CURRENT_CLAIM_TYPES
                 and counts['outside'] > 0 and counts['inWindow'] == 0)
    return {'stale': stale, 'rule': 'stale-current-claim' if stale else '',
            'inWindow': counts['inWindow'], 'outside': counts['outside'], 'undated': counts['undated']}


# --- gốc nguồn và số nguồn độc lập ------------------------------------------

def registered_domain(host: Any) -> str:
    """Miền đăng ký thô từ host: bỏ `www.`, gộp hậu tố hai phần đã biết. Không tra DNS."""
    text = _slug(host)
    if not text:
        return ''
    if '://' in text or '/' in text:
        # Nhận cả URL đầy đủ: chỉ lấy phần host, bỏ đường dẫn và truy vấn.
        text = re.split(r'[/?#]', text.split('://')[-1])[0]
    text = text.split('@')[-1].split(':')[0].strip('.')
    if not text:
        return ''
    labels = [part for part in text.split('.') if part]
    if len(labels) <= 2:
        return '.'.join(labels)
    last_two = '.'.join(labels[-2:])
    if last_two in _TWO_PART_SUFFIXES and len(labels) >= 3:
        return '.'.join(labels[-3:])
    return last_two


def origin_cluster(entry: Any) -> str:
    """Cụm gốc của một nguồn: `payload.origin` → doi/arxiv/openreview/ncbi → miền → host → `''`.

    Cùng cụm nghĩa là cùng một nguồn gốc (bản sao, bài viết lại, preprint và bản hội nghị), nên
    luật hai nguồn độc lập (#5983/#5985) đếm cụm chứ không đếm URL.
    """
    if not isinstance(entry, Mapping):
        return ''
    given = _slug(entry.get('originCluster') or entry.get('origin_cluster'))
    if given:
        return given
    payload = entry.get('payload') if isinstance(entry.get('payload'), Mapping) else {}
    for key in ('origin', 'cluster', 'group'):
        value = _slug(payload.get(key) or entry.get(key))
        if value:
            return value
    for key, prefix in (('doi', 'doi'), ('arxivId', 'arxiv'), ('arxiv', 'arxiv'),
                        ('openreview', 'openreview'), ('pmid', 'ncbi'), ('pmcid', 'ncbi'),
                        ('ncbi', 'ncbi')):
        value = _slug(payload.get(key) or entry.get(key))
        if value:
            return prefix + ':' + value
    domain = registered_domain(entry.get('host') or entry.get('url'))
    if domain:
        return domain
    return _slug(entry.get('host')) if _text(entry.get('host')) else ''


def cluster_count(evidence: Any) -> int:
    """Số cụm gốc khác nhau; nguồn không rõ gốc đếm riêng (không gộp bừa vào nhau)."""
    total = 0
    seen = set()
    for entry in entries(evidence):
        cluster = origin_cluster(entry)
        if not cluster:
            total += 1
            continue
        if cluster in seen:
            continue
        seen.add(cluster)
        total += 1
    return total


def clusters_of(evidence: Any) -> list:
    """Danh sách cụm gốc theo thứ tự gặp, đã bỏ trùng; cụm rỗng giữ nguyên vị trí."""
    out = []
    for entry in entries(evidence):
        cluster = origin_cluster(entry)
        if cluster and cluster in out:
            continue
        out.append(cluster)
    return out


# --- mức trần độ tin cậy ----------------------------------------------------

def _best_access(rows: Sequence[Mapping]) -> str:
    best = ''
    for entry in rows:
        level = normalize_access_level(entry.get('accessLevel') or entry.get('access_level'))
        if not best or ACCESS_RANK.get(level, 0) > ACCESS_RANK.get(best, 0):
            best = level
    return best or 'snippet'


def _max_tier(rows: Sequence[Mapping]) -> int:
    tiers = [int(entry.get('tier') or 0) for entry in rows]
    return max(tiers) if tiers else 0


def _min_tier(rows: Sequence[Mapping]) -> int:
    tiers = [int(entry.get('tier') or 0) for entry in rows]
    return min(tiers) if tiers else 0


def _flag(entry: Mapping, *names: str) -> bool:
    for name in names:
        value = entry.get(name)
        if isinstance(value, bool):
            if value:
                return True
        elif _text(value).lower() in ('1', 'true', 'yes', 'y', 'on'):
            return True
    payload = entry.get('payload') if isinstance(entry.get('payload'), Mapping) else {}
    for name in names:
        if payload.get(name) is True:
            return True
    return False


def _has_section(rows: Sequence[Mapping], wanted: Sequence[str]) -> bool:
    for entry in rows:
        if _slug(entry.get('sectionKind') or entry.get('section_kind')) in wanted:
            return True
    return False


def _has_kind(rows: Sequence[Mapping], wanted: Sequence[str]) -> bool:
    for entry in rows:
        if _slug(entry.get('sourceKind') or entry.get('source_kind')) in wanted:
            return True
    return False


def normalize_claim_type(value: Any) -> str:
    """Loại nhận định hợp lệ; lạ ⇒ `inference` (không bao giờ ném)."""
    text = _slug(value).replace('_', '-')
    if text in CLAIM_TYPES:
        return text
    return _CLAIM_TYPE_ALIASES.get(text, 'inference')


def normalize_access_level(value: Any) -> str:
    """Mức truy cập hợp lệ; `''`/lạ ⇒ `snippet` (mặc định thận trọng)."""
    text = _slug(value).replace('_', '-')
    if text in ACCESS_LEVELS:
        return text
    return _ACCESS_ALIASES.get(text, 'snippet')


def normalize_source_kind(value: Any) -> str:
    """Loại nguồn hợp lệ; lạ ⇒ `other`."""
    text = _slug(value).replace('_', '-')
    if text in SOURCE_KINDS:
        return text
    return {'article': 'news', 'blogpost': 'blog', 'github': 'repo', 'huggingface': 'model',
            'documentation': 'docs', 'paper-abstract': 'paper'}.get(text, 'other')


def is_inference(claim_type: Any) -> bool:
    """`inference`/`recommendation` không mang độ tin cậy của dữ kiện."""
    return normalize_claim_type(claim_type) in ('inference', 'recommendation')


def normalize_stance(value: Any) -> str:
    """Nguồn gốc lập trường của nhận định; lạ ⇒ `source-stated` chỉ khi nói rõ, còn lại suy luận."""
    text = _slug(value).replace('_', '-')
    if text in STANCE_ORIGINS:
        return text
    return 'agent-inference'


def _result(cap: str, rule: str, basis: dict, reasons: list) -> dict:
    return {'cap': cap if cap in CONFIDENCE_LEVELS or cap == 'contested' else 'unknown',
            'rule': rule, 'basis': dict(basis or {}), 'reasons': [text for text in reasons if text]}


def confidence_cap(claim_type: Any, evidence: Any, *, stance_origin: Any = 'source-stated',
                   window_days: int = 0, as_of: Any = None, conflict: bool = False) -> dict:
    """Mức trần độ tin cậy tính từ sổ (§5.7). Trả `{'cap','rule','basis','reasons'}`."""
    rows = entries(evidence)
    kind = normalize_claim_type(claim_type)
    origin = normalize_stance(stance_origin)
    clusters = cluster_count(rows)
    best_access = _best_access(rows) if rows else ''
    basis = {'claimType': kind, 'stanceOrigin': origin, 'clusters': clusters,
             'bestAccess': best_access, 'minTier': _min_tier(rows) if rows else 0,
             'maxTier': _max_tier(rows) if rows else 0, 'sources': len(rows)}
    if window_days:
        support = in_window_support(rows, window_days=window_days, as_of=as_of)
        basis['inWindow'] = support['counts']['inWindow']
        basis['outside'] = support['counts']['outside']
        basis['undated'] = support['counts']['undated']

    if conflict:
        return _result('contested', 'contested-counter-evidence', basis,
                       ['Có bằng chứng phản bác cùng hạng — không lấy theo đa số.'])
    if not rows:
        return _result('unknown', 'no-evidence', basis, ['Chưa có nguồn nào đỡ nhận định này.'])
    if is_inference(kind):
        return _result('unknown', 'no-evidence-confidence', basis,
                       ['Suy luận/đề xuất không mang độ tin cậy của dữ kiện; phải liệt kê tiền đề.'])

    primary_fulltext = any(
        int(entry.get('tier') or 0) <= 1
        and normalize_access_level(entry.get('accessLevel') or entry.get('access_level')) == 'fulltext-read'
        for entry in rows)
    if kind in ('numeric', 'event', 'current-fact'):
        if primary_fulltext or clusters >= 2:
            rule = 'primary-fulltext' if primary_fulltext else 'two-independent-clusters'
            return _result('high', rule, basis, ['Nguồn gốc tầng 1 đọc toàn văn hoặc hai cụm khớp.'])
        if _min_tier(rows) >= 4:
            return _result('low', 'tier4-only', basis, ['Chỉ có nguồn tầng 4.'])
        if best_access == 'snippet':
            return _result('low', 'snippet-only', basis, ['Chỉ có trích đoạn, chưa đọc thân nguồn.'])
        if best_access == 'abstract':
            return _result('medium', 'abstract-only', basis, ['Chỉ có abstract.'])
        if clusters == 1 and 1 <= _min_tier(rows) <= 2:
            return _result('medium', 'single-secondary', basis, ['Một nguồn thứ cấp duy nhất.'])
        return _result('medium', 'single-secondary', basis, ['Một nguồn đỡ, chưa đủ hai cụm.'])
    if kind == 'method':
        # §5.7: \"đã đọc mục phương pháp trong toàn văn\" là thuộc tính của MỘT lần đọc, nên mục và
        # mức truy cập phải nằm trên CÙNG một hàng (một hàng `method` + một hàng full-text khác
        # KHÔNG đủ — `finding 5`).
        read = any(
            _slug(row.get('sectionKind') or row.get('section_kind')) in
            ('method', 'methods', 'methodology', 'approach')
            and normalize_access_level(row.get('accessLevel') or row.get('access_level')) == 'fulltext-read'
            for row in rows)
        if read:
            return _result('high', 'method-fulltext', basis, ['Đã đọc mục phương pháp trong toàn văn.'])
        if best_access in ('abstract', 'fulltext-available') or _min_tier(rows) <= 2:
            return _result('medium', 'method-abstract', basis, ['Mới có abstract hoặc mô tả cấp cao.'])
        return _result('low', 'method-secondary', basis, ['Mô tả thứ cấp về phương pháp.'])
    if kind == 'benchmark':
        conditions = any(_flag(row, 'recordedConditions', 'recorded_conditions') for row in rows)
        numbers = _has_section(rows, ('results', 'experiments', 'benchmark', 'table', 'tables'))
        # §5.7: bảng số, điều kiện ghi rõ và mức đọc toàn văn là thuộc tính của CÙNG một lần đọc.
        # `clusters` là số hạng duy nhất được phép gộp qua nhiều hàng (`finding 5`).
        read = next((row for row in rows
                     if _slug(row.get('sectionKind') or row.get('section_kind')) in
                     ('results', 'experiments', 'benchmark', 'table', 'tables')
                     and normalize_access_level(row.get('accessLevel') or row.get('access_level'))
                     == 'fulltext-read'
                     and _flag(row, 'recordedConditions', 'recorded_conditions')), None)
        if read is not None and (clusters >= 2 or _flag(read, 'independentReplication',
                                                        'independent_replication')):
            return _result('high', 'benchmark-conditions+replication', basis,
                           ['Bảng số từ toàn văn, điều kiện ghi rõ, có nguồn độc lập.'])
        if _has_kind(rows, ('blog', 'news', 'forum')):
            return _result('low', 'benchmark-third-party-numbers', basis,
                           ['Số liệu lấy từ blog/tin tức, không phải bảng gốc.'])
        if numbers or _has_kind(rows, ('paper', 'preprint')) or conditions:
            return _result('medium', 'benchmark-author-reported', basis,
                           ['Tác giả tự báo cáo, chưa có nguồn độc lập tái hiện.'])
        return _result('low', 'benchmark-third-party-numbers', basis,
                       ['Số liệu đi qua trung gian, không có bảng gốc.'])
    if kind == 'trend':
        support = in_window_support(rows, window_days=window_days, as_of=as_of) if window_days else None
        inside = support['counts']['inWindow'] if support else 0
        survey_seen = any(_flag(row, 'survey', 'isSurvey') for row in rows) or _has_section(
            rows, ('related-work', 'related', 'survey', 'overview'))
        # Chỉ khi CÓ cửa sổ đo được mới được thưởng \"gần đây\": cửa sổ chưa khai (`window_days = 0`)
        # không đồng nghĩa mọi hàng đều nằm trong cửa sổ — đó là `finding 3`.
        if support is not None and inside >= 2 and survey_seen:
            return _result('high', 'trend-window+survey', basis,
                           ['Nhiều cụm gần đây trong cửa sổ và có tổng quan gần.'])
        if clusters >= 2:
            return _result('medium', 'trend-two-clusters', basis, ['Hai cụm nguồn đỡ xu hướng.'])
        return _result('low', 'trend-one-cluster', basis, ['Một cụm nguồn cho xu hướng.'])
    if kind == 'market':
        return market_cap(rows)
    if kind == 'gap':
        systematic = any(_flag(row, 'systematic', 'systematicSearch', 'citationChase') for row in rows)
        if systematic:
            return _result('medium', 'gap-systematic', basis,
                           ['Đã tìm đủ facet liên quan và săn trích dẫn; khoảng trống chưa bao giờ '
                            'được coi là "cao" nếu chỉ suy từ việc không thấy.'])
        return _result('low', 'gap-narrow', basis, ['Tìm hẹp — khoảng trống chỉ là giả thuyết.'])
    if not rows:
        return _result('unknown', 'no-evidence', basis, ['Chưa có nguồn nào đỡ nhận định này.'])
    return _result('low', 'unclassified', basis, ['Chưa có luật riêng cho loại nhận định này.'])


def market_rank(value: Any) -> int:
    """Nấc bằng chứng thị trường (1…6 theo `MARKET_LADDER`); không nhận ra ⇒ `0`."""
    key = _slug(value)
    if not key:
        return 0
    key = _MARKET_ALIASES.get(key, key.replace(' ', '-'))
    if key in MARKET_LADDER:
        return MARKET_LADDER.index(key) + 1
    return 0


def market_cap(evidence: Any) -> dict:
    """Mức trần cho nhận định `market`: cao chỉ từ nấc báo cáo độc lập/hồ sơ pháp lý (§5.7)."""
    rows = entries(evidence)
    ranks = [market_rank(entry.get('ladder') or entry.get('marketLadder')) for entry in rows]
    best = max(ranks) if ranks else 0
    basis = {'claimType': 'market', 'ladder': MARKET_LADDER[best - 1] if best else '',
             'ranks': sorted(set(rank for rank in ranks if rank)), 'sources': len(rows)}
    if not rows or not best:
        return _result('unknown', 'no-evidence', basis, ['Chưa có bằng chứng thị trường nào.'])
    if best >= market_rank('independent'):
        return _result('high', 'market-independent', basis,
                       ['Báo cáo triển khai độc lập hoặc hồ sơ pháp lý.'])
    if best == market_rank('case-study'):
        return _result('medium', 'market-case-study', basis, ['Ca khách hàng do bên thứ ba kể.'])
    return _result('low', 'market-marketing', basis, ['Tiếp thị, demo hoặc tuyên bố của nhà cung cấp.'])


def apply_cap(level: Any, cap: Any) -> str:
    """Hạ mức xuống trần, **không** nâng: `min` theo `CONFIDENCE_RANK`, giữ `contested`."""
    if _slug(cap) == 'contested':
        return 'contested'
    if _slug(level) == 'contested':
        return 'contested'
    low = _slug(level)
    high = _slug(cap)
    if low not in CONFIDENCE_RANK:
        low = 'unknown'
    if high not in CONFIDENCE_RANK:
        high = 'unknown'
    return low if CONFIDENCE_RANK[low] <= CONFIDENCE_RANK[high] else high


def basis_payload(claim_type: Any, evidence: Any, *, rule: str, extra: Any = None) -> dict:
    """Gói `basis` ghi vào `research_claim_meta`: đủ để soi lại vì sao ra mức đó."""
    rows = entries(evidence)
    groups = {}
    for entry in rows:
        cluster = origin_cluster(entry)
        groups.setdefault(cluster or '?', []).append(_entry_id(entry))
    basis = {'claimType': normalize_claim_type(claim_type), 'rule': _text(rule),
             'clusters': cluster_count(rows), 'bestAccess': _best_access(rows) if rows else '',
             'minTier': _min_tier(rows) if rows else 0, 'maxTier': _max_tier(rows) if rows else 0,
             'sources': len(rows), 'groups': groups}
    if isinstance(extra, Mapping):
        for key, value in extra.items():
            basis[str(key)] = value
    return basis
