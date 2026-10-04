"""Sổ hạch toán usage/chi phí theo từng call; không tự cấp consent hay ngân sách.

Mỗi backend model call ghi ĐÚNG MỘT hàng `harness_usage` theo `call_key`; mỗi
reservation/consent là một hàng `harness_allocations` theo `allocation_id`. Sổ chỉ
là dữ liệu: nó không gọi model, không gọi mạng, không tự tăng hạn mức, không tự
cho rằng một call là free.

Bất biến:
- Giá/chi phí `unknown` là `None`/NULL, không bao giờ là 0. Giá mới không viết lại
  `price_snapshot_json`/`amount` của hàng cũ — mỗi hàng giữ snapshot lúc ghi.
- `reserve_decision` từ chối chi mới khi caller không có ceiling (`None` không phải
  vô hạn) hoặc khi giá unknown mà không có upper estimate kèm nguồn do caller chấp
  nhận (`price['upperEstimate']`).
- `reserve` là một transaction: check-and-write trong `BEGIN IMMEDIATE`, idempotent
  theo `invocation_id` + request hash; vượt phần ceiling còn lại thì bị từ chối và
  không để lại hàng nào.
- `record` idempotent theo `call_key`: payload y hệt thì replay hàng cũ, khác payload
  thì `USAGE_CALL_CONFLICT`. Nhờ đó aggregate không cộng cùng chi phí hai lần.
- Reasoning tokens lưu riêng, không cộng vào input/output; cache read/write lưu riêng
  trong `cached_tokens_json`.
- `settle` chuyển reservation thành consumed theo usage thực; phần chưa dùng được
  `release` giải phóng. Child bị hủy vẫn ghi phần đã dùng (`settle` trước `release`).
  Usage đến muộn không viết lại lịch sử: `reconcile` giữ liability và không bao giờ
  đánh dấu free.

Quy ước chung H3–H8: bảng cộng thêm trên `SessionStore.db`, lỗi `ContractError` mã
`USAGE_*`, docstring tiếng Việt, không thêm dependency ngoài stdlib.

Nối runtime (H7): công tắc `BOXFOX_USAGE_LEDGER` (mặc định TẮT). Khi bật, runtime ghi
một hàng `record()` cho mỗi lần gọi model hoàn tất (`record_completion`) với đúng
`input/output/reasoning/cached` mà router báo; giá lấy từ `pricing` của dòng model
trong router (một snapshot admin cho mỗi request) — không có giá thì `certainty='unknown'`
và `amount=None`, không bao giờ 0. `reserve`/`settle` nối khi root có `harnessAllocationId` do backend ghim tới
allocation đã cấp. Adaptive request thiếu allocation chỉ được dùng route có giá
miễn phí xác nhận. Không tự tạo consent hoặc root allocation từ văn bản model.
"""
from contextlib import contextmanager
import copy
import json
import math
import os
import sqlite3
import time

from .orchestration_contracts import identifier, invalid, object_fields, revision, text
from .work_policy import digest

#: Công tắc giết khi nối vào runtime: mặc định TẮT, chỉ `on` mới bật (khuôn `BOXFOX_TASK_SURFACE`).
SWITCH = 'BOXFOX_USAGE_LEDGER'

RECORD_SCHEMA_VERSION = 1
PAGE_LIMIT = 100
MAX_TEXT = 200
MAX_CURRENCY = 16
PRICE_UNIT = 'per_million_tokens'
CERTAINTIES = ('known', 'estimated', 'unknown')
ALLOCATION_STATES = ('reserved', 'settled', 'released', 'unsettled')

# Cột bắt buộc: DB cũ thiếu cột thì fail closed, không tự đoán/backfill.
REQUIRED_USAGE_COLUMNS = (
    'call_key', 'schema_version', 'owner_id', 'run_id', 'task_key', 'job_id', 'attempt_id',
    'provider_id', 'model_id', 'route_revision', 'purpose', 'requested_json', 'effective_json',
    'input_tokens', 'output_tokens', 'reasoning_tokens', 'cached_tokens_json',
    'price_snapshot_json', 'amount', 'currency', 'certainty', 'observed_at', 'created_at',
)
REQUIRED_ALLOCATION_COLUMNS = (
    'allocation_id', 'schema_version', 'parent_id', 'owner_id', 'policy_revision', 'consent_ref',
    'reservation_json', 'consumed_json', 'state', 'created_at', 'updated_at',
)

# Alias nhận từ payload thật của router/harness (snake_case lẫn camelCase).
_USAGE_FIELDS = {
    'run_id': ('run_id', 'runId'),
    'task_key': ('task_key', 'taskKey'),
    'job_id': ('job_id', 'jobId'),
    'attempt_id': ('attempt_id', 'attemptId'),
    'provider_id': ('provider_id', 'providerId'),
    'model_id': ('model_id', 'modelId'),
    'route_revision': ('route_revision', 'routeRevision'),
    'purpose': ('purpose',),
    'requested': ('requested',),
    'effective': ('effective',),
    'input_tokens': ('input_tokens', 'inputTokens', 'prompt_tokens'),
    'output_tokens': ('output_tokens', 'outputTokens', 'completion_tokens'),
    'reasoning_tokens': ('reasoning_tokens', 'reasoningTokens'),
    'cached_tokens': ('cached_tokens', 'cachedTokens'),
    'price': ('price', 'price_snapshot', 'priceSnapshot'),
    'amount': ('amount',),
    'currency': ('currency',),
    'certainty': ('certainty',),
    'observed_at': ('observed_at', 'observedAt'),
}
_USAGE_PAYLOAD_KEYS = ('run_id', 'task_key', 'job_id', 'attempt_id', 'provider_id', 'model_id',
                       'route_revision', 'purpose', 'requested', 'effective', 'input_tokens',
                       'output_tokens', 'reasoning_tokens', 'cached_tokens', 'price_snapshot',
                       'amount', 'currency', 'certainty', 'observed_at')

_READ_KEYS = ('read', 'readTokens', 'cached', 'cacheRead', 'cache_read_input_tokens')
_WRITE_KEYS = ('write', 'writeTokens', 'cacheWrite', 'cacheWriteInput', 'cache_creation_input_tokens')


def enabled(env=None):
    """Công tắc giết của sổ usage: chỉ `on` mới bật; mọi giá trị khác (kể cả thiếu) là TẮT."""
    return str((env if env is not None else os.environ.get(SWITCH)) or '').strip().lower() == 'on'


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def decode(value):
    return None if value is None else json.loads(value)


def _record_json(value, field):
    """Đọc JSON đã lưu trong sổ; hỏng thì fail closed thay vì lộ `JSONDecodeError` thô."""
    try:
        return decode(value)
    except (TypeError, ValueError):
        invalid(field, 'stored record is not valid JSON', 'USAGE_RECORD_CORRUPT')


def _schema(row):
    if type(row['schema_version']) is not int or row['schema_version'] != RECORD_SCHEMA_VERSION:
        invalid('schemaVersion', 'unsupported persisted record schema', 'USAGE_SCHEMA_UNSUPPORTED')


def _is_number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0)


def _number(value, field, code='USAGE_FIELD_INVALID'):
    if not _is_number(value):
        invalid(field, 'expected a finite non-negative number, not a boolean', code)
    return float(value)


def _token(value, field):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        invalid(field, 'expected a non-negative integer', 'USAGE_FIELD_INVALID')
    return value


def _json_object(value, field):
    if not isinstance(value, dict):
        invalid(field, 'expected an object', 'USAGE_FIELD_INVALID')
    try:
        encode(value)
    except (TypeError, ValueError):
        invalid(field, 'expected JSON-serializable values', 'USAGE_FIELD_INVALID')
    return value


def _cached_tokens(value, field='cached_tokens'):
    """Cache read/write ở hai khe riêng; không suy một khe từ khe kia."""
    if value is None:
        return None
    if not isinstance(value, dict):
        invalid(field, 'expected a cached-token object', 'USAGE_FIELD_INVALID')
    found = {}
    for canonical, aliases in (('read', _READ_KEYS), ('write', _WRITE_KEYS)):
        hits = [key for key in aliases if key in value]
        if len(hits) > 1:
            invalid(field, f'duplicate aliases for {canonical}: {sorted(hits)}', 'USAGE_FIELD_INVALID')
        if hits:
            found[canonical] = _token(value[hits[0]], f'{field}.{canonical}')
    extra = set(value) - set(_READ_KEYS) - set(_WRITE_KEYS)
    if extra:
        invalid(field, f'unsupported fields {sorted(extra)}', 'USAGE_FIELD_INVALID')
    if not found:
        invalid(field, 'expected at least one of read/write', 'USAGE_FIELD_INVALID')
    return {'read': found.get('read'), 'write': found.get('write')}


def _normalize_price(value, field='price'):
    """Chuẩn hoá price snapshot kiểu router (USD / 1M tokens) và BẮT BUỘC có nguồn.

    Thiếu `source` nghĩa là không có giá — kể cả 0 — nên không được lưu thành một
    con số; người gọi phải để amount/certainty là unknown.
    """
    if not isinstance(value, dict):
        invalid(field, 'expected a price object', 'USAGE_FIELD_INVALID')
    allowed = {'source', 'currency', 'unit', 'asOf', 'input', 'cachedInput', 'cacheWriteInput',
               'output', 'updatedAt'}
    extra = set(value) - allowed
    if extra:
        invalid(field, f'unsupported fields {sorted(extra)}', 'USAGE_FIELD_INVALID')
    source = value.get('source')
    if not isinstance(source, str) or not source.strip():
        invalid(field + '.source', 'a price without provenance is not a price', 'USAGE_FIELD_INVALID')
    result = {'source': source.strip()}
    currency = value.get('currency')
    if currency is None:
        result['currency'] = 'USD'
    else:
        text(currency, field + '.currency', MAX_CURRENCY)
        result['currency'] = currency
    unit = value.get('unit')
    if unit is not None and unit != PRICE_UNIT:
        invalid(field + '.unit', f'expected {PRICE_UNIT}', 'USAGE_FIELD_INVALID')
    result['unit'] = PRICE_UNIT
    as_of = value.get('asOf')
    result['asOf'] = None if as_of is None else text(as_of, field + '.asOf', 32)
    for key in ('input', 'cachedInput', 'cacheWriteInput', 'output'):
        component = value.get(key)
        result[key] = None if component is None else _number(component, f'{field}.{key}')
    updated = value.get('updatedAt')
    if updated is not None:
        result['updatedAt'] = _number(updated, field + '.updatedAt')
    return result


def _computed_amount(price, input_tokens, output_tokens, cached):
    """Tính amount từ price + token; thiếu dữ liệu thì trả None, không trả 0.

    Công thức giống router `costFromUsage`: cached read là tập con của input, phần
    miss chịu giá input; cache write cũng nằm trong input nên trừ trước khi tính miss;
    thiếu giá cache thì rơi về giá input chứ không tự đoán giảm giá.
    """
    if not price or price.get('input') is None or price.get('output') is None:
        return None
    if input_tokens is None or output_tokens is None:
        return None
    cached = cached or {}
    inp = input_tokens or 0
    out = output_tokens or 0
    hit = min(cached.get('read') or 0, inp)
    write = min(cached.get('write') or 0, max(0, inp - hit))
    miss = max(0, inp - hit - write)
    cached_price = price['input'] if price.get('cachedInput') is None else price['cachedInput']
    write_price = price['input'] if price.get('cacheWriteInput') is None else price['cacheWriteInput']
    total = (miss * price['input'] + hit * cached_price + write * write_price
             + out * price['output']) / 1_000_000
    return round(total, 6)


def _sum_known(values):
    known = [value for value in values if value is not None]
    return (sum(known) if known else None, len(known) == len(values))


def _usage_payload(owner_id, usage):
    """Chuẩn hoá `**usage` thành payload bất biến (dùng cho cả hash lẫn INSERT)."""
    provided = {}
    for canonical, aliases in _USAGE_FIELDS.items():
        hits = [key for key in aliases if key in usage]
        if len(hits) > 1:
            invalid('usage', f'duplicate aliases for {canonical}: {sorted(hits)}', 'USAGE_FIELD_INVALID')
        if hits:
            provided[canonical] = usage[hits[0]]
    extra = set(usage) - {key for aliases in _USAGE_FIELDS.values() for key in aliases}
    if extra:
        invalid('usage', f'unsupported fields {sorted(extra)}', 'USAGE_FIELD_INVALID')

    payload = {'owner_id': owner_id}
    for field in ('run_id', 'task_key', 'job_id', 'attempt_id', 'provider_id', 'model_id',
                  'route_revision'):
        value = provided.get(field)
        if value is not None:
            identifier(value, field)
        payload[field] = value
    purpose = provided.get('purpose')
    payload['purpose'] = None if purpose is None else text(purpose, 'purpose', MAX_TEXT)
    for field in ('requested', 'effective'):
        value = provided.get(field)
        payload[field] = None if value is None else _json_object(value, field)
    for field in ('input_tokens', 'output_tokens', 'reasoning_tokens'):
        payload[field] = _token(provided.get(field), field)
    cached = provided.get('cached_tokens')
    payload['cached_tokens'] = None if cached is None else _cached_tokens(cached)
    price = provided.get('price')
    payload['price_snapshot'] = None if price is None else _normalize_price(price, 'price')

    currency = provided.get('currency')
    if currency is not None:
        text(currency, 'currency', MAX_CURRENCY)
    certainty = provided.get('certainty')
    if certainty is not None and certainty not in CERTAINTIES:
        invalid('certainty', 'expected known, estimated or unknown', 'USAGE_CERTAINTY_INVALID')
    if 'amount' in provided:
        amount = None if provided['amount'] is None else _number(provided['amount'], 'amount')
    else:
        amount = _computed_amount(payload['price_snapshot'], payload['input_tokens'],
                                  payload['output_tokens'], payload['cached_tokens'])
    if amount is None:
        if certainty is not None and certainty != 'unknown':
            invalid('certainty', 'an unknown amount cannot be known or estimated', 'USAGE_CERTAINTY_INVALID')
        certainty = 'unknown'
    else:
        if certainty == 'unknown':
            invalid('certainty', 'a known amount cannot be unknown', 'USAGE_CERTAINTY_INVALID')
        certainty = certainty or 'estimated'
        currency = currency or 'USD'
    payload['amount'] = amount
    payload['currency'] = currency
    payload['certainty'] = certainty
    observed = provided.get('observed_at')
    payload['observed_at'] = time.time() if observed is None else _number(observed, 'observedAt')
    return payload


def _usage_row_payload(row):
    """Dựng lại payload từ hàng đã lưu để so hash idempotent của `record`."""
    payload = {'owner_id': row['owner_id']}
    for field in ('run_id', 'task_key', 'job_id', 'attempt_id', 'provider_id', 'model_id',
                  'route_revision', 'purpose'):
        payload[field] = row[field]
    payload['requested'] = _record_json(row['requested_json'], 'requestedJson')
    payload['effective'] = _record_json(row['effective_json'], 'effectiveJson')
    for field in ('input_tokens', 'output_tokens', 'reasoning_tokens'):
        payload[field] = row[field]
    payload['cached_tokens'] = _record_json(row['cached_tokens_json'], 'cachedTokensJson')
    payload['price_snapshot'] = _record_json(row['price_snapshot_json'], 'priceSnapshotJson')
    payload['amount'] = row['amount']
    payload['currency'] = row['currency']
    payload['certainty'] = row['certainty']
    payload['observed_at'] = row['observed_at']
    return payload


def _usage_hash(payload):
    """Hash idempotency bỏ qua mốc thời gian sổ sách (`observed_at`/`created_at`).

    Retry cùng call có thể quan sát ở thời điểm khác nhau; nếu tính `observed_at` vào
    hash thì mọi lần retry thành conflict oan.
    """
    return digest({key: value for key, value in payload.items() if key != 'observed_at'})


def _usage_view(row):
    _schema(row)
    return {'callKey': row['call_key'], 'schemaVersion': row['schema_version'],
            'ownerId': row['owner_id'], 'runId': row['run_id'], 'taskKey': row['task_key'],
            'jobId': row['job_id'], 'attemptId': row['attempt_id'], 'providerId': row['provider_id'],
            'modelId': row['model_id'], 'routeRevision': row['route_revision'], 'purpose': row['purpose'],
            'requested': _record_json(row['requested_json'], 'requestedJson'),
            'effective': _record_json(row['effective_json'], 'effectiveJson'),
            'inputTokens': row['input_tokens'], 'outputTokens': row['output_tokens'],
            'reasoningTokens': row['reasoning_tokens'],
            'cachedTokens': _record_json(row['cached_tokens_json'], 'cachedTokensJson'),
            'priceSnapshot': _record_json(row['price_snapshot_json'], 'priceSnapshotJson'),
            'amount': row['amount'],
            'currency': row['currency'], 'certainty': row['certainty'],
            'observedAt': row['observed_at'], 'createdAt': row['created_at']}


def _decision(allowed, reason, certainty, amount, currency, basis, ceiling):
    return {'allowed': allowed, 'reason': reason, 'certainty': certainty, 'amount': amount,
            'currency': currency, 'basis': basis, 'ceiling': ceiling}


def reserve_decision(price, caller_ceiling=None):
    """Quyết định chi trước admission. Hàm thuần: không ghi sổ, không tự cấp consent.

    - `caller_ceiling is None` → `USAGE_NO_CONSENT` (None KHÔNG phải vô hạn).
    - Giá unknown chỉ được chấp nhận khi caller đưa upper estimate rõ nguồn
      (`price['upperEstimate'] = {'amount', 'source'}`); thiếu nguồn thì bị từ chối
      `USAGE_PRICE_UNKNOWN`.
    - Vượt ceiling còn lại → `USAGE_CEILING_EXCEEDED`. Free (amount 0) vẫn cần
      nguồn giá xác nhận, nên một amount 0 thiếu `source` không được coi là giá.
    """
    if caller_ceiling is None:
        return _decision(False, 'USAGE_NO_CONSENT', 'unknown', None, None, None, None)
    ceiling = _number(caller_ceiling, 'callerCeiling')
    if not isinstance(price, dict):
        return _decision(False, 'USAGE_PRICE_UNKNOWN', 'unknown', None, None, None, ceiling)
    upper = price.get('upperEstimate')
    upper_amount = upper_source = None
    if isinstance(upper, dict):
        candidate = upper.get('amount')
        source = upper.get('source')
        if _is_number(candidate) and isinstance(source, str) and source.strip():
            upper_amount, upper_source = float(candidate), source.strip()
    known = price.get('amount')
    known_source = price.get('source')
    currency = price.get('currency') if isinstance(price.get('currency'), str) else 'USD'
    if upper_amount is not None:
        amount, basis, certainty = upper_amount, upper_source, 'estimated'
    elif _is_number(known) and isinstance(known_source, str) and known_source.strip():
        amount, basis, certainty = float(known), known_source.strip(), 'known'
    else:
        return _decision(False, 'USAGE_PRICE_UNKNOWN', 'unknown', None, currency, None, ceiling)
    if amount > ceiling:
        return _decision(False, 'USAGE_CEILING_EXCEEDED', certainty, amount, currency, basis, ceiling)
    reason = 'USAGE_UPPER_ESTIMATE' if certainty == 'estimated' else 'USAGE_PRICE_KNOWN'
    return _decision(True, reason, certainty, amount, currency, basis, ceiling)


# --- Price book trong tiến trình: caller (runtime wiring) nạp giá đã đọc từ router;
# --- ledger không tự gọi mạng và không tự bịa giá. Mọi tra cứu miss trả None.
_PRICE_HISTORY = {}


def clear_prices():
    """Xoá price book — chỉ dùng cho test/khởi động lại, không phải nghiệp vụ."""
    _PRICE_HISTORY.clear()


def register_price(provider_id, model_id, price, route_revision=None, recorded_at=None):
    """Ghi một snapshot giá theo (provider, model, route) để tra cứu lịch sử."""
    identifier(provider_id, 'providerId')
    identifier(model_id, 'modelId')
    if route_revision is not None:
        identifier(route_revision, 'routeRevision')
    normalized = _normalize_price(price, 'price')
    moment = time.time() if recorded_at is None else _number(recorded_at, 'recordedAt')
    entry = {'providerId': provider_id, 'modelId': model_id, 'routeRevision': route_revision,
             'recordedAt': moment, **normalized}
    _PRICE_HISTORY.setdefault((provider_id, model_id, route_revision or ''), []).append(entry)
    return copy.deepcopy(entry)


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        time.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None
    return value


def _date_of(timestamp):
    return time.strftime('%Y-%m-%d', time.gmtime(timestamp))


def price_snapshot(provider_id, model_id, route_revision=None, as_of=None):
    """Snapshot giá mới nhất tại/before `as_of`; unknown trả None (không trả 0/free).

    Bản trả về là bản copy có `known=True` cùng `source`/`currency`/`asOf`; giá theo
    đơn vị `per_million_tokens` nên giữ nguyên các thành phần `input`/`output`/cache
    thay vì gộp thành một `amount` mơ hồ. Miss lịch sử giá trả `None`.
    """
    identifier(provider_id, 'providerId')
    identifier(model_id, 'modelId')
    if route_revision is not None:
        identifier(route_revision, 'routeRevision')
    entries = _PRICE_HISTORY.get((provider_id, model_id, route_revision or ''), ())
    if not entries:
        return None
    if as_of is None:
        candidates = entries
    elif isinstance(as_of, str):
        limit = _date(as_of)
        if limit is None:
            invalid('asOf', 'expected a YYYY-MM-DD date or a timestamp', 'USAGE_FIELD_INVALID')
        candidates = [item for item in entries
                      if (item.get('asOf') or _date_of(item['recordedAt'])) <= limit]
    else:
        moment = _number(as_of, 'asOf')
        candidates = [item for item in entries if item['recordedAt'] <= moment]
    if not candidates:
        return None
    snapshot = copy.deepcopy(max(candidates, key=lambda item: item['recordedAt']))
    snapshot['known'] = True      # miss ở trên trả None: unknown không bao giờ thành 0/free
    return snapshot


class UsageLedger:
    """Sổ usage + allocation trên SessionStore; chỉ ghi nhận, không cấp quyền chi."""

    def __init__(self, store):
        self.store, self.db = store, store.db
        for table, required in (
                ('harness_usage', REQUIRED_USAGE_COLUMNS),
                ('harness_allocations', REQUIRED_ALLOCATION_COLUMNS)):
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if columns and not set(required) <= columns:
                invalid('schemaVersion', f'{table} does not match the record schema',
                        'USAGE_SCHEMA_UNSUPPORTED')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS harness_usage (
                call_key TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                owner_id TEXT NOT NULL, run_id TEXT, task_key TEXT, job_id TEXT, attempt_id TEXT,
                provider_id TEXT, model_id TEXT, route_revision TEXT, purpose TEXT,
                requested_json TEXT, effective_json TEXT,
                input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
                cached_tokens_json TEXT, price_snapshot_json TEXT,
                amount REAL, currency TEXT, certainty TEXT NOT NULL,
                observed_at REAL, created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS harness_usage_owner
                ON harness_usage(owner_id, run_id, call_key);
            CREATE TABLE IF NOT EXISTS harness_allocations (
                allocation_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                parent_id TEXT, owner_id TEXT NOT NULL, policy_revision INTEGER NOT NULL,
                consent_ref TEXT NOT NULL, reservation_json TEXT NOT NULL,
                consumed_json TEXT NOT NULL, state TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS harness_allocations_owner
                ON harness_allocations(owner_id, parent_id, allocation_id);
        ''')

    @contextmanager
    def _write(self):
        # Một transaction cho check-and-write (dedupe, ceiling, insert/update). Bên trong
        # transaction của caller thì dùng savepoint để giữ atomicity của caller, không
        # commit hộ và không mở khoá ghi mới.
        if self.db.in_transaction:
            self.db.execute('SAVEPOINT usage_ledger_write')
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK TO usage_ledger_write')
                raise
            finally:
                self.db.execute('RELEASE usage_ledger_write')
        else:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                yield

    def _allocation_row(self, allocation_id):
        identifier(allocation_id, 'allocationId')
        row = self.db.execute('SELECT * FROM harness_allocations WHERE allocation_id=?',
                              (allocation_id,)).fetchone()
        if row is None:
            invalid('allocationId', 'unknown allocation', 'USAGE_ALLOCATION_UNKNOWN')
        _schema(row)
        return row

    def _allocation_view(self, row):
        """View của allocation; `remaining` trừ cả phần con đang giữ để khớp đường reserve."""
        _schema(row)
        stored = _record_json(row['reservation_json'], 'reservationJson')
        consumed = _record_json(row['consumed_json'], 'consumedJson')
        reservation = {key: value for key, value in stored.items() if key != 'invocation'}
        if row['state'] == 'unsettled':
            remaining = None
        else:
            remaining = round(reservation['amount'] - (consumed.get('amount') or 0.0)
                              - (consumed.get('releasedAmount') or 0.0)
                              - self._held(row['allocation_id']), 6)
        return {'allocationId': row['allocation_id'], 'schemaVersion': row['schema_version'],
                'parentId': row['parent_id'], 'ownerId': row['owner_id'],
                'policyRevision': row['policy_revision'], 'consentRef': row['consent_ref'],
                'reservation': reservation, 'consumed': consumed, 'state': row['state'],
                'remaining': remaining, 'createdAt': row['created_at'], 'updatedAt': row['updated_at']}

    def _held(self, parent_id):
        """Phần reservation con còn tính vào hạn mức cha: `reservation.amount - releasedAmount`.

        Áp cho MỌI con, kể cả con đã chốt/đóng: phần con đã tiêu vẫn nằm trong hạn mức
        cha sau khi con đóng, còn phần con trả lại (`releasedAmount`) thì được giải
        phóng. Con đang usage-unknown giữ nguyên toàn bộ mức giữ chỗ (không đoán free).
        """
        total = 0.0
        for row in self.db.execute('SELECT schema_version, reservation_json, consumed_json '
                                   'FROM harness_allocations WHERE parent_id=?', (parent_id,)):
            _schema(row)
            reservation = _record_json(row['reservation_json'], 'reservationJson')
            consumed = _record_json(row['consumed_json'], 'consumedJson')
            total += reservation['amount'] - (consumed.get('releasedAmount') or 0.0)
        return round(total, 6)

    @staticmethod
    def _reservation(reservation):
        fields = object_fields(reservation, 'reservation', ('amount',),
                               ('ceiling', 'currency', 'price', 'purpose'))
        amount = _number(fields['amount'], 'reservation.amount')
        ceiling = None if fields.get('ceiling') is None else _number(fields['ceiling'],
                                                                    'reservation.ceiling')
        currency = fields.get('currency')
        if currency is None:
            currency = 'USD'
        else:
            text(currency, 'reservation.currency', MAX_CURRENCY)
        price = fields.get('price')
        if price is not None:
            price = _json_object(price, 'reservation.price')
        purpose = fields.get('purpose')
        if purpose is not None:
            text(purpose, 'reservation.purpose', MAX_TEXT)
        return {'amount': amount, 'ceiling': ceiling, 'currency': currency, 'price': price,
                'purpose': purpose}

    def reserve(self, allocation_id, owner_id, policy_revision, consent_ref, reservation,
                invocation_id, parent_id=None):
        """Giữ chỗ ngân sách trong MỘT transaction; idempotent theo invocation + request hash.

        Root cần `ceiling` + `consent_ref` (thiếu → `USAGE_NO_CONSENT`; `None` không phải
        vô hạn). Con kế thừa consent/currency của cha và không được vượt phần ceiling còn
        lại của cha. Consent của con là bất biến: chỉ được bỏ trống để kế thừa hoặc lặp
        đúng `consent_ref` của cha; khai consent khác cha bị từ chối (`USAGE_FIELD_INVALID`)
        vì con không có đường tự cấp consent mới. Reservation kèm `price` còn phải qua
        `reserve_decision`.
        """
        identifier(allocation_id, 'allocationId')
        identifier(owner_id, 'ownerId')
        revision(policy_revision, 'policyRevision')
        identifier(invocation_id, 'invocationId')
        if parent_id is not None:
            identifier(parent_id, 'parentId')
            if parent_id == allocation_id:
                invalid('parentId', 'allocation cannot be its own parent', 'USAGE_FIELD_INVALID')
        if consent_ref is None:
            if parent_id is None:
                invalid('consentRef', 'root allocation requires caller consent', 'USAGE_NO_CONSENT')
        else:
            identifier(consent_ref, 'consentRef')
        normalized = self._reservation(reservation)
        request_hash = digest({'action': 'reserve', 'allocationId': allocation_id, 'ownerId': owner_id,
                               'parentId': parent_id, 'policyRevision': policy_revision,
                               'consentRef': consent_ref, 'reservation': normalized})
        with self._write():
            row = self.db.execute('SELECT * FROM harness_allocations WHERE allocation_id=?',
                                  (allocation_id,)).fetchone()
            if row is not None:
                _schema(row)
                stored = _record_json(row['reservation_json'], 'reservationJson')
                invocation = stored.get('invocation') or {}
                if (row['owner_id'] != owner_id or invocation.get('invocationId') != invocation_id
                        or invocation.get('requestHash') != request_hash):
                    invalid('allocationId', 'allocation reused with a different request',
                            'USAGE_ALLOCATION_CONFLICT')
                return self._allocation_view(row)
            if parent_id is None:
                if normalized['ceiling'] is None:
                    invalid('reservation.ceiling', 'caller ceiling is required; None is not unlimited',
                            'USAGE_NO_CONSENT')
                ceiling, consent = normalized['ceiling'], consent_ref
            else:
                parent = self._allocation_row(parent_id)
                if parent['owner_id'] != owner_id:
                    invalid('parentId', 'parent allocation belongs to another owner',
                            'USAGE_ALLOCATION_UNKNOWN')
                if parent['state'] != 'reserved':
                    invalid('parentId', 'parent allocation is not open', 'USAGE_ALLOCATION_CLOSED')
                parent_reservation = _record_json(parent['reservation_json'], 'reservationJson')
                parent_consumed = _record_json(parent['consumed_json'], 'consumedJson')
                if normalized['currency'] != parent_reservation['currency']:
                    invalid('reservation.currency', 'child currency must match the parent',
                            'USAGE_FIELD_INVALID')
                if consent_ref is not None and consent_ref != parent['consent_ref']:
                    invalid('consentRef', 'child consent must match the parent; omit it to inherit',
                            'USAGE_FIELD_INVALID')
                parent_remaining = round(parent_reservation['amount']
                                         - (parent_consumed.get('amount') or 0.0)
                                         - (parent_consumed.get('releasedAmount') or 0.0)
                                         - self._held(parent_id), 6)
                own = normalized['ceiling']
                ceiling = max(0.0, parent_remaining if own is None else min(own, parent_remaining))
                consent = parent['consent_ref']
            if normalized['price'] is not None:
                decision = reserve_decision(normalized['price'], ceiling)
                if not decision['allowed']:
                    invalid('reservation.price', 'price is not admitted for this ceiling',
                            decision['reason'])
                if normalized['amount'] < decision['amount']:
                    invalid('reservation.amount', 'reservation does not cover the priced bound',
                            'USAGE_CEILING_EXCEEDED')
            if normalized['amount'] > ceiling:
                invalid('reservation.amount', 'reservation exceeds the remaining ceiling',
                        'USAGE_CEILING_EXCEEDED')
            now = time.time()
            stored = {**normalized,
                      'invocation': {'invocationId': invocation_id, 'requestHash': request_hash}}
            consumed = {'amount': None, 'currency': normalized['currency'], 'releasedAmount': 0.0,
                        'lateAmount': 0.0, 'settledAt': None, 'usage': None, 'source': None,
                        'releases': [], 'invocations': {}}
            try:
                self.db.execute('INSERT INTO harness_allocations VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (allocation_id, RECORD_SCHEMA_VERSION, parent_id, owner_id,
                                 policy_revision, consent, encode(stored), encode(consumed),
                                 'reserved', now, now))
            except sqlite3.IntegrityError:
                # Caller khác có thể đã commit cùng allocation; hàng đã lưu là chân lý.
                row = self.db.execute('SELECT * FROM harness_allocations WHERE allocation_id=?',
                                      (allocation_id,)).fetchone()
                if row is None:
                    raise
                _schema(row)
                stored = _record_json(row['reservation_json'], 'reservationJson')
                invocation = stored.get('invocation') or {}
                if (row['owner_id'] != owner_id or invocation.get('invocationId') != invocation_id
                        or invocation.get('requestHash') != request_hash):
                    invalid('allocationId', 'allocation reused with a different request',
                            'USAGE_ALLOCATION_CONFLICT')
            return self._allocation_view(self._allocation_row(allocation_id))

    def get_allocation(self, allocation_id):
        return self._allocation_view(self._allocation_row(allocation_id))

    def _save(self, row, consumed, state, now):
        self.db.execute('UPDATE harness_allocations SET consumed_json=?, state=?, updated_at=? '
                        'WHERE allocation_id=?',
                        (encode(consumed), state, now, row['allocation_id']))

    def settle(self, allocation_id, actual, invocation_id=None):
        """Chuyển reservation → consumed theo usage thực; phần chưa dùng chờ `release`.

        `actual['amount'] is None` nghĩa là usage chưa về: giữ `unsettled` liability,
        không release. Amount đến muộn sau khi đã settled chỉ cộng vào `lateAmount` —
        không viết lại `consumed.amount` đã chốt.

        Hạn mức của allocation trừ cả phần con đang giữ (`_held`): settle không được
        đẩy `consumed + released + held` vượt reservation. Mọi `invocation_id` đã áp
        được ghi trong `consumed['invocations']`; retry bất kỳ invocation cũ nào (kể cả
        khi invocation khác đã chen vào) đều replay, khác payload thì
        `USAGE_INVOCATION_CONFLICT`.
        """
        identifier(allocation_id, 'allocationId')
        if invocation_id is not None:
            identifier(invocation_id, 'invocationId')
        fields = object_fields(actual, 'actual', ('amount',), ('currency', 'usage', 'source'))
        amount = None if fields['amount'] is None else _number(fields['amount'], 'actual.amount')
        usage_payload = fields.get('usage')
        if usage_payload is not None:
            _json_object(usage_payload, 'actual.usage')
        source = fields.get('source')
        if source is not None:
            text(source, 'actual.source', MAX_TEXT)
        currency = fields.get('currency')
        if currency is not None:
            text(currency, 'actual.currency', MAX_CURRENCY)
        request_hash = digest({'action': 'settle', 'allocationId': allocation_id, 'amount': amount,
                               'currency': currency, 'usage': usage_payload, 'source': source})
        with self._write():
            row = self._allocation_row(allocation_id)
            reservation = _record_json(row['reservation_json'], 'reservationJson')
            consumed = _record_json(row['consumed_json'], 'consumedJson')
            invocations = dict(consumed.get('invocations') or {})
            if invocation_id is not None and invocation_id in invocations:
                if invocations[invocation_id] != request_hash:
                    invalid('invocationId', 'settle invocation reused with a different request',
                            'USAGE_INVOCATION_CONFLICT')
                return self._allocation_view(row)
            if row['state'] == 'released':
                invalid('allocationId', 'allocation is closed', 'USAGE_ALLOCATION_CLOSED')
            if currency is not None and currency != reservation['currency']:
                invalid('actual.currency', 'currency mismatch with the reservation', 'USAGE_FIELD_INVALID')
            if amount is not None:
                released = consumed.get('releasedAmount') or 0.0
                held = self._held(allocation_id)
                reported = max(consumed.get('amount') or 0.0, amount)
                if reported + released + held > reservation['amount']:
                    invalid('actual.amount',
                            'actual usage plus child holds exceeds the reservation',
                            'USAGE_SETTLE_EXCEEDS')
            now = time.time()
            if amount is None:
                if row['state'] == 'reserved':
                    consumed.update({'amount': None, 'usage': usage_payload, 'source': source})
                    state = 'unsettled'
                else:
                    state = row['state']
            else:
                if row['state'] in ('reserved', 'unsettled'):
                    consumed.update({'amount': amount, 'currency': currency or reservation['currency'],
                                     'usage': usage_payload, 'source': source, 'settledAt': now})
                    state = 'settled'
                else:
                    current = consumed.get('amount')
                    if amount < current:
                        invalid('actual.amount', 'late usage cannot reduce a settled amount',
                                'USAGE_SETTLE_CONFLICT')
                    if amount > current:
                        consumed['lateAmount'] = round(max(consumed.get('lateAmount') or 0.0,
                                                           amount - current), 6)
                    state = row['state']
            if invocation_id is not None:
                invocations[invocation_id] = request_hash
                consumed['invocations'] = invocations
            self._save(row, consumed, state, now)
            return self._allocation_view(self._allocation_row(allocation_id))

    def release(self, allocation_id, amount, reason, invocation_id=None):
        """Giải phóng phần reservation chưa dùng; usage unknown thì từ chối (`USAGE_UNSETTLED`).

        Phần con đang giữ (`_held`) không được giải phóng: `available` trừ cả held. Mọi
        `invocation_id` đã áp được ghi trong `consumed['invocations']`; retry bất kỳ
        invocation cũ nào đều replay, khác payload thì `USAGE_INVOCATION_CONFLICT`.
        """
        identifier(allocation_id, 'allocationId')
        value = _number(amount, 'amount')
        text(reason, 'reason', MAX_TEXT)
        if invocation_id is not None:
            identifier(invocation_id, 'invocationId')
        request_hash = digest({'action': 'release', 'allocationId': allocation_id, 'amount': value,
                               'reason': reason})
        with self._write():
            row = self._allocation_row(allocation_id)
            reservation = _record_json(row['reservation_json'], 'reservationJson')
            consumed = _record_json(row['consumed_json'], 'consumedJson')
            invocations = dict(consumed.get('invocations') or {})
            if invocation_id is not None and invocation_id in invocations:
                if invocations[invocation_id] != request_hash:
                    invalid('invocationId', 'release invocation reused with a different request',
                            'USAGE_INVOCATION_CONFLICT')
                return self._allocation_view(row)
            if row['state'] == 'unsettled':
                invalid('allocationId', 'cannot release while actual usage is unknown',
                        'USAGE_UNSETTLED')
            releases = consumed.get('releases') or []
            released = consumed.get('releasedAmount') or 0.0
            available = round(reservation['amount'] - (consumed.get('amount') or 0.0) - released
                              - self._held(allocation_id), 6)
            if value > available:
                invalid('amount', 'release exceeds the unspent reservation after child holds',
                        'USAGE_RELEASE_EXCEEDS')
            now = time.time()
            if value > 0:
                entry = {'amount': value, 'reason': reason, 'at': now}
                if invocation_id is not None:
                    entry.update({'invocationId': invocation_id, 'requestHash': request_hash})
                releases.append(entry)
                consumed['releasedAmount'] = round(released + value, 6)
                consumed['releases'] = releases
            if invocation_id is not None:
                invocations[invocation_id] = request_hash
                consumed['invocations'] = invocations
            total = round((consumed.get('amount') or 0.0) + (consumed.get('releasedAmount') or 0.0), 6)
            state = 'released' if total >= reservation['amount'] else row['state']
            self._save(row, consumed, state, now)
            return self._allocation_view(self._allocation_row(allocation_id))

    def record(self, call_key, owner_id, **usage):
        """Một hàng cho một backend model call; idempotent theo `call_key` + payload hash.

        Giá unknown ⇒ `amount=None`, `certainty='unknown'`. Trùng call_key cùng payload
        thì replay hàng cũ; khác payload thì `USAGE_CALL_CONFLICT`.
        """
        identifier(call_key, 'callKey')
        identifier(owner_id, 'ownerId')
        payload = _usage_payload(owner_id, usage)
        request_hash = _usage_hash(payload)
        with self._write():
            row = self.db.execute('SELECT * FROM harness_usage WHERE call_key=?', (call_key,)).fetchone()
            if row is not None:
                _schema(row)
                if _usage_hash(_usage_row_payload(row)) != request_hash:
                    invalid('callKey', 'call key reused with a different payload', 'USAGE_CALL_CONFLICT')
                return _usage_view(row)
            self.db.execute(
                'INSERT INTO harness_usage VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (call_key, RECORD_SCHEMA_VERSION, owner_id, payload['run_id'], payload['task_key'],
                 payload['job_id'], payload['attempt_id'], payload['provider_id'], payload['model_id'],
                 payload['route_revision'], payload['purpose'],
                 None if payload['requested'] is None else encode(payload['requested']),
                 None if payload['effective'] is None else encode(payload['effective']),
                 payload['input_tokens'], payload['output_tokens'], payload['reasoning_tokens'],
                 None if payload['cached_tokens'] is None else encode(payload['cached_tokens']),
                 None if payload['price_snapshot'] is None else encode(payload['price_snapshot']),
                 payload['amount'], payload['currency'], payload['certainty'],
                 payload['observed_at'], time.time()))
            return _usage_view(self.db.execute('SELECT * FROM harness_usage WHERE call_key=?',
                                               (call_key,)).fetchone())

    def calls(self, owner_id=None, run_id=None, cursor=None, limit=100):
        """Keyset page theo call_key; chỉ đọc, không reconcile hay sửa hàng."""
        if owner_id is not None:
            identifier(owner_id, 'ownerId')
        if run_id is not None:
            identifier(run_id, 'runId')
        if cursor is not None:
            identifier(cursor, 'cursor')
        if type(limit) is not int or not 1 <= limit <= PAGE_LIMIT:
            invalid('limit', f'expected an integer between 1 and {PAGE_LIMIT}')
        sql = 'SELECT * FROM harness_usage WHERE call_key>?'
        args = [cursor or '']
        if owner_id is not None:
            sql += ' AND owner_id=?'
            args.append(owner_id)
        if run_id is not None:
            sql += ' AND run_id=?'
            args.append(run_id)
        rows = self.db.execute(sql + ' ORDER BY call_key LIMIT ?', (*args, limit + 1)).fetchall()
        items = [_usage_view(row) for row in rows[:limit]]
        return {'items': items, 'hasMore': len(rows) > limit,
                'nextCursor': items[-1]['callKey'] if items else None}

    def aggregate(self, owner_id, run_id=None):
        """Tổng theo (currency, certainty); nhóm unknown có amount None, không gộp vào 0."""
        identifier(owner_id, 'ownerId')
        if run_id is not None:
            identifier(run_id, 'runId')
        sql = 'SELECT * FROM harness_usage WHERE owner_id=?'
        args = [owner_id]
        if run_id is not None:
            sql += ' AND run_id=?'
            args.append(run_id)
        groups = {}
        total_calls = 0
        for row in self.db.execute(sql + ' ORDER BY call_key', args):
            _schema(row)
            total_calls += 1
            key = (row['currency'], row['certainty'])
            group = groups.setdefault(key, {'calls': 0, 'amount': None if row['certainty'] == 'unknown' else 0.0,
                                            'input': [], 'output': [], 'reasoning': [],
                                            'read': [], 'write': []})
            group['calls'] += 1
            if row['certainty'] != 'unknown':
                group['amount'] = round(group['amount'] + (row['amount'] or 0.0), 6)
            group['input'].append(row['input_tokens'])
            group['output'].append(row['output_tokens'])
            group['reasoning'].append(row['reasoning_tokens'])
            cached = _record_json(row['cached_tokens_json'], 'cachedTokensJson') or {}
            group['read'].append(cached.get('read'))
            group['write'].append(cached.get('write'))
        items = []
        for currency, certainty in sorted(groups, key=lambda item: (item[0] or '', item[1])):
            group = groups[(currency, certainty)]
            input_total, input_complete = _sum_known(group['input'])
            output_total, output_complete = _sum_known(group['output'])
            reasoning_total, reasoning_complete = _sum_known(group['reasoning'])
            read_total, read_complete = _sum_known(group['read'])
            write_total, write_complete = _sum_known(group['write'])
            items.append({'currency': currency, 'certainty': certainty, 'calls': group['calls'],
                          'amount': group['amount'], 'inputTokens': input_total,
                          'outputTokens': output_total, 'reasoningTokens': reasoning_total,
                          'cachedReadTokens': read_total, 'cachedWriteTokens': write_total,
                          'tokensComplete': all((input_complete, output_complete, reasoning_complete,
                                                 read_complete, write_complete))})
        unknown_calls = sum(group['calls'] for key, group in groups.items() if key[1] == 'unknown')
        return {'ownerId': owner_id, 'runId': run_id, 'calls': total_calls,
                'unknownCalls': unknown_calls, 'groups': items}

    def _allocation_rows(self, owner_id=None):
        sql = 'SELECT * FROM harness_allocations'
        args = []
        if owner_id is not None:
            sql += ' WHERE owner_id=?'
            args.append(owner_id)
        return self.db.execute(sql + ' ORDER BY allocation_id', args)

    def unsettled(self, owner_id=None):
        """Reservation chưa chốt/usage unknown/còn late — kèm liability, không sửa hàng."""
        if owner_id is not None:
            identifier(owner_id, 'ownerId')
        items = []
        for row in self._allocation_rows(owner_id):
            liability = _liability(row, self._held(row['allocation_id']))
            if liability is not None:
                items.append({**self._allocation_view(row), 'liability': liability})
        return items

    def _unknown_usage(self, owner_id=None):
        sql = 'SELECT * FROM harness_usage WHERE amount IS NULL'
        args = []
        if owner_id is not None:
            sql += ' AND owner_id=?'
            args.append(owner_id)
        return [_usage_view(row) for row in self.db.execute(sql + ' ORDER BY call_key', args)]

    def reconcile(self, owner_id=None):
        """Báo cáo liability đến muộn/unknown — chỉ đọc, không viết lại lịch sử."""
        if owner_id is not None:
            identifier(owner_id, 'ownerId')
        items = self.unsettled(owner_id)
        unknown = self._unknown_usage(owner_id)
        amounts = [item['liability']['amount'] for item in items
                   if item['liability']['amount'] is not None]
        if not items:
            unsettled_amount = 0.0
        elif len(amounts) != len(items):
            unsettled_amount = None
        else:
            unsettled_amount = round(sum(amounts), 6)
        late = round(sum((_record_json(row['consumed_json'], 'consumedJson').get('lateAmount') or 0.0)
                         for row in self._allocation_rows(owner_id)), 6)
        return {'ownerId': owner_id, 'checkedAt': time.time(), 'unsettled': items,
                'unknownUsage': unknown, 'unsettledAmount': unsettled_amount,
                'lateAmount': late, 'unknownCalls': len(unknown)}


def _liability(row, children_held=0.0):
    """Liability còn lại của một allocation; None nghĩa là đã chốt sổ.

    `children_held` là phần reservation con đang giữ — trừ ra để liability của cha
    không đếm trùng với liability của chính các con.
    """
    _schema(row)
    reservation = _record_json(row['reservation_json'], 'reservationJson')
    consumed = _record_json(row['consumed_json'], 'consumedJson')
    amount = consumed.get('amount')
    released = consumed.get('releasedAmount') or 0.0
    late = consumed.get('lateAmount') or 0.0
    if row['state'] == 'unsettled':
        return {'amount': None, 'reason': 'usage_unknown'}
    if row['state'] == 'reserved':
        remaining = round(reservation['amount'] - released - children_held, 6)
        return {'amount': remaining, 'reason': 'unsettled_reservation'} if remaining > 0 else None
    remainder = round(reservation['amount'] - (amount or 0.0) - released - children_held, 6)
    if remainder > 0:
        return {'amount': round(remainder + late, 6), 'reason': 'unreleased_remainder'}
    if late > 0:
        return {'amount': late, 'reason': 'late_usage'}
    return None
