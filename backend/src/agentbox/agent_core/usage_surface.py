"""Nối sổ usage vào model request; giá giả chỉ được tiêm bằng fixture của test.

Sổ quan sát legacy không cấp chi tiêu mới. Adaptive request cần allocation do
backend đã lưu, hoặc route có giá miễn phí xác nhận từ router. Không dùng estimate
của tokenizer làm upper bound tài chính: reservation dùng context limit công bố.
Timeout/cancel giữ liability, không giải phóng phần có outcome chưa biết.
"""
import math
import time
import uuid

from . import execution_kernel, job_surface, output_policy, usage_ledger
from .orchestration_contracts import invalid


def service(rt):
    ledger = getattr(rt, '_usage_ledger', None)
    if ledger is None:
        ledger = rt._usage_ledger = usage_ledger.UsageLedger(rt.store)
    return ledger


def root_session(rt, sid):
    seen = set()
    current = rt.store.get(sid)
    while current and current.get('parent_id'):
        if current['id'] in seen:
            invalid('ownerId', 'cyclic session lineage', 'USAGE_OWNER_UNKNOWN')
        seen.add(current['id'])
        current = rt.store.get(current['parent_id'])
    if not current:
        invalid('ownerId', 'missing canonical root session', 'USAGE_OWNER_UNKNOWN')
    from . import research_gateway
    return research_gateway.budget_root(rt, current) or current


def _count(*values):
    return next((v for v in values if type(v) is int and v >= 0), None)


def counts(usage):
    usage = usage if isinstance(usage, dict) else {}
    detail = usage.get('prompt_tokens_details')
    detail = detail if isinstance(detail, dict) else {}
    return {**output_policy.usage_counts(usage),
            'cachedTokens': {'read': _count(usage.get('cache_read_input_tokens'),
                                           usage.get('cached_tokens'), detail.get('cached_tokens')),
                             'write': _count(usage.get('cache_creation_input_tokens'))}}


def _price(row):
    raw = row.get('pricing')
    if not isinstance(raw, dict) or raw.get('source') not in ('manual', 'ping', 'documented'):
        return None
    for key in ('input', 'output'):
        value = raw.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            return None
    for key in ('cachedInput', 'cacheWriteInput'):
        value = raw.get(key)
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                  or not math.isfinite(value) or value < 0):
            return None
    # Đổi tên cache field cho contract sổ; không sửa bảng giá router.
    return {'input': raw['input'], 'output': raw['output'],
            'cachedInput': raw.get('cachedInput'), 'cacheWriteInput': raw.get('cacheWriteInput'),
            'unit': 'per_million_tokens', 'currency': 'USD',
            'source': raw['source'], 'asOf': raw.get('asOf'),
            'updatedAt': raw.get('updatedAt')}


async def route_rows(rt, route):
    """Một snapshot cục bộ, không ping provider; route không rõ thì không đoán giá."""
    snapshot = getattr(rt.client, 'snapshot', None)
    try:
        state = await snapshot() if callable(snapshot) else None
    except Exception:
        state = None  # Không đọc được metadata không phải giá 0 hoặc consent.
    if not isinstance(state, dict):
        return []
    # Alias không cho biết target ở admission: caller cần chọn route tường minh.
    if route.get('aliasId') or not route.get('modelId'):
        return []
    if not route.get('connectionId') and not route.get('providerId'):
        return []
    rows = []
    for connection in state.get('connections') or []:
        if route.get('connectionId') and connection.get('id') != route['connectionId']:
            continue
        if not route.get('connectionId') and connection.get('providerId') != route['providerId']:
            continue
        for row in connection.get('models') or []:
            if row.get('id') == route['modelId']:
                rows.append({**row, '_connectionId': connection.get('id'),
                             '_providerId': connection.get('providerId'),
                             '_routeRevision': connection.get('revision')})
    return rows


def _free(price):
    return price is not None and all(price.get(k) in (None, 0) for k in
                                     ('input', 'output', 'cachedInput', 'cacheWriteInput'))


def _bound(rows, max_tokens):
    """Upper bound theo metadata; mọi target có thể chọn đều phải có giá và context."""
    bounds = []
    for row in rows:
        price = _price(row)
        if _free(price):
            bounds.append(0)
            continue
        context = row.get('contextWindow')
        if price is None or type(context) is not int or context <= 0:
            invalid('pricing', 'route has no priced context upper bound', 'USAGE_PRICE_UNKNOWN')
        input_rate = max(price['input'], price.get('cachedInput') or 0, price.get('cacheWriteInput') or 0)
        bounds.append((context * input_rate + max_tokens * price['output']) / 1_000_000)
    if not bounds:
        invalid('pricing', 'route has no confirmed targets', 'USAGE_PRICE_UNKNOWN')
    # Làm tròn lên: không làm reservation thấp hơn bound vì sai số thập phân.
    return math.ceil(max(bounds) * 1_000_000) / 1_000_000


def _actual_row(rows, response, route):
    meta = response.get('boxfox') if isinstance(response, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    connection_id = meta.get('connectionId') or route.get('connectionId')
    model_id = meta.get('modelId') or route.get('modelId')
    matches = [r for r in rows if r['_connectionId'] == connection_id and r['id'] == model_id]
    return matches[0] if len(matches) == 1 else None


async def complete(rt, sid, messages, tools, route, *, purpose='completion', **kwargs):
    """Một backend call key cho mỗi request, kể cả retry, summary và error/cancel."""
    from . import research_gateway
    job_surface.guard_request(rt, sid)
    research_gateway.guard_request(rt, sid)
    session = rt.store.get(sid)
    root = root_session(rt, sid)
    ledger = service(rt)
    call_key = 'call-' + uuid.uuid4().hex
    rows = await route_rows(rt, route)
    # snapshot là await point: đọc lại authority, allocation và kill switch sau đó.
    job_surface.guard_request(rt, sid)
    research_gateway.guard_request(rt, sid)
    session = rt.store.get(sid)
    root = root_session(rt, sid)
    adaptive = execution_kernel._policy(session) is not None or execution_kernel._policy(root) is not None
    allocation_id = root['config'].get('harnessAllocationId')
    if (adaptive or allocation_id) and ('cancelled' in (root.get('status'), session.get('status'))):
        invalid('ownerId', 'canonical owner or request session stopped', 'USAGE_OWNER_STOPPED')
    reservation = None
    tokens = kwargs.get('max_tokens', 4096)
    if type(tokens) is not int or tokens <= 0:
        invalid('maxTokens', 'expected positive request ceiling', 'USAGE_FIELD_INVALID')
    if allocation_id:
        parent = ledger.get_allocation(allocation_id)
        if parent['ownerId'] != root['id']:
            invalid('allocationId', 'allocation belongs to another root', 'USAGE_ALLOCATION_UNKNOWN')
        if parent['reservation']['currency'] != 'USD':
            invalid('currency', 'router price USD cannot settle another currency', 'USAGE_CURRENCY_MISMATCH')
        bound = _bound(rows, tokens)
        reservation = ledger.reserve(call_key, root['id'], parent['policyRevision'], None,
                                     {'amount': bound, 'currency': 'USD', 'purpose': purpose},
                                     call_key, parent_id=allocation_id)
    elif adaptive and (not rows or not all(_free(_price(row)) for row in rows)):
        invalid('allocationId', 'adaptive spend requires backend allocation or confirmed free route',
                'USAGE_NO_CONSENT')
    response = None
    try:
        response = await rt.client.complete(messages, tools, route, **kwargs)
        return response
    finally:
        # finally chạy cả CancelledError: outcome chưa biết vẫn có một hàng usage.
        row = _actual_row(rows, response or {}, route)
        usage = counts((response or {}).get('usage'))
        record = ledger.record(call_key, root['id'], **{
            'runId': sid, 'attemptId': call_key,
            'providerId': (row or {}).get('_providerId') or route.get('providerId'),
            'modelId': (row or {}).get('id') or route.get('modelId'),
            'routeRevision': str(row['_routeRevision']) if row and row.get('_routeRevision') is not None else None, 'purpose': purpose,
            'requested': {'maxTokens': tokens}, 'effective': {'maxTokens': tokens},
            **usage, 'priceSnapshot': _price(row) if row else None})
        rt.store.emit(sid, 'harness_usage', {'callKey': call_key, 'purpose': purpose,
                                           'amount': record['amount'], 'certainty': record['certainty']})
        if reservation:
            ledger.settle(call_key, {'amount': record['amount'], 'currency': 'USD',
                                     'source': record['certainty']}, invocation_id='settle-' + call_key)
            if record['amount'] is not None:
                ledger.release(call_key, max(0, round(reservation['reservation']['amount'] - record['amount'], 6)),
                               'request completed with known usage',
                               invocation_id='release-' + call_key)


async def prepare_research_admission(rt, lead, request):
    """Đọc giá trước transaction; cache là dữ liệu backend, không phải ref model tự khai.

    Trả literal `True` khi đã chụp xong (admission đồng bộ vẫn kiểm lại trong lock); hook
    chỉ chuẩn bị dữ liệu, không cấp consent.
    """
    from . import research_gateway
    if not research_gateway.is_lead(rt, rt.store.get(lead['id'])):
        return False
    route = rt.store.get(lead['id'])['config'].get('route') or {}
    rows = await route_rows(rt, route)
    cache = getattr(rt, '_research_price_admissions', None)
    if cache is None:
        cache = rt._research_price_admissions = {}
    from .work_policy import digest
    cache[lead['id']] = {'rows': rows, 'routeHash': digest(route), 'requestHash': digest(request),
                        'observedAt': time.monotonic()}
    return True


def research_admission(rt, lead, request):
    """Literal True chỉ khi current authority + snapshot + allocation/free đều kiểm được."""
    from . import research_gateway
    from .work_policy import digest
    current = rt.store.get(lead['id'])
    if not research_gateway.is_lead(rt, current):
        return False
    root = root_session(rt, lead['id'])
    if root.get('status') in ('cancelled', 'awaiting_decision'):
        return False
    # Chưa có kho permissionEnvelope refs: không biến chuỗi model thành quyền.
    if request.get('permissionEnvelopeRef') is not None:
        return False
    route = current['config'].get('route') or {}
    snapshot = getattr(rt, '_research_price_admissions', {}).get(lead['id'])
    if (not snapshot or time.monotonic() - snapshot['observedAt'] > 10
            or snapshot['routeHash'] != digest(route) or snapshot['requestHash'] != digest(request)):
        return False
    tools = set(current['config'].get('tools') or [])
    if not tools or not tools <= (set(root['config'].get('tools') or []) | {research_gateway.PUBLISH_TOOL}):
        return False
    if 'research_brief' not in tools or 'research_status' not in tools:
        return False
    rows = snapshot['rows']
    allocation_id = root['config'].get('harnessAllocationId')
    if not allocation_id:
        return (request.get('allocationRef') is None and request.get('consentRef') is None
                and bool(rows) and all(_free(_price(row)) for row in rows))
    if request.get('allocationRef') not in (None, allocation_id):
        return False
    parent = service(rt).get_allocation(allocation_id)
    if (parent['ownerId'] != root['id'] or parent['reservation']['currency'] != 'USD'
            or request.get('consentRef') not in (None, parent['consentRef'])):
        return False
    try:
        tokens = output_policy.request_budget(current['config'])
        bound = _bound(rows, tokens)
    except ValueError:
        return False
    return parent['remaining'] is not None and bound <= parent['remaining']
