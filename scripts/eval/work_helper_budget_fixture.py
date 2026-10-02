"""W6.5.3 fixture: a small fictional repo `kho-ve` and 8 long lookup cases with a fixed oracle.

Every case asks a nested Work Graph lookup helper for a long, mandatory output (a table of
>= 10 rows or a three-source comparison). Coverage is deterministic: an item counts only when
all of its regexes match on ONE line of the helper's visible answer (case-insensitive). No LLM
judge. Values are deliberately distinctive so a hit cannot come from generic prose.
Every case also has one mandatory tail item: a line that opens the requested limitations
section (`Giới hạn`/`Hạn chế`/`Limitations` at line start, optionally as heading/bold), so a
cut-off answer loses coverage even when the table itself fits.
"""
import re

FILES = {
    'README.md': '# kho-ve\nDịch vụ giữ và bán vé sự kiện (fixture W6.5.3, không phải hệ thống thật).\n'
                 'Cấu hình: config/; mã: src/kho_ve/; tài liệu: docs/.\n',
    'config/limits.yaml': '''# Giới hạn vận hành kho-ve (fixture)
ingest:
  max_batch_rows: 7731          # số dòng tối đa mỗi lô nhập
  max_payload_kib: 913          # KiB mỗi request nhập
  parse_timeout_ms: 4417        # ms cho một lô
queue:
  visibility_timeout_s: 263     # giây trước khi message hiện lại
  max_redeliveries: 17          # lần giao lại trước khi vào DLQ
  dead_letter_ttl_h: 151        # giờ giữ message trong DLQ
storage:
  shard_count: 29               # số shard bảng vé
  compaction_interval_min: 383  # phút giữa hai lần compaction
  cold_after_days: 47           # ngày trước khi chuyển kho lạnh
api:
  rate_limit_rps: 1187          # request/giây mỗi tenant
  burst: 2311                   # request vượt ngưỡng tức thời
  idle_conn_timeout_s: 97       # giây
  max_page_size: 641            # bản ghi mỗi trang
export:
  csv_max_columns: 1291         # cột tối đa khi xuất CSV
''',
    'src/kho_ve/errors.py': '''"""Mã lỗi công khai của kho-ve (fixture)."""
ERRORS = {
    'KV-E1031': (409, 'Ghế đã bị giữ bởi phiên khác'),
    'KV-E1047': (404, 'Không tìm thấy sự kiện'),
    'KV-E1102': (422, 'Số lượng vé không hợp lệ'),
    'KV-E1158': (429, 'Vượt giới hạn tốc độ tenant'),
    'KV-E1213': (403, 'Tenant không có quyền với sự kiện'),
    'KV-E1279': (410, 'Phiên giữ ghế đã hết hạn'),
    'KV-E1306': (400, 'Thiếu header Idempotency-Key'),
    'KV-E1384': (503, 'Hàng đợi giữ vé tạm không nhận'),
    'KV-E1420': (401, 'Token hết hạn hoặc sai chữ ký'),
    'KV-E1497': (412, 'ETag không khớp phiên bản đơn'),
    'KV-E1533': (413, 'Payload nhập vượt max_payload_kib'),
    'KV-E1589': (507, 'Shard lưu trữ hết dung lượng'),
}


def status_of(code):
    return ERRORS[code][0]
''',
    'src/kho_ve/routes.py': '''"""Bảng định tuyến HTTP của kho-ve (fixture)."""
from .http import route

ROUTES = [
    route('GET', '/v2/events', 'list_events', perm='event:list'),
    route('GET', '/v2/events/{event_id}', 'get_event', perm='event:read'),
    route('GET', '/v2/events/{event_id}/seats', 'list_seats', perm='seat:read'),
    route('POST', '/v2/events/{event_id}/holds', 'create_hold', perm='hold:write'),
    route('DELETE', '/v2/holds/{hold_id}', 'release_hold', perm='hold:release'),
    route('POST', '/v2/holds/{hold_id}/confirm', 'confirm_hold', perm='order:create'),
    route('GET', '/v2/orders/{order_id}', 'get_order', perm='order:read'),
    route('POST', '/v2/orders/{order_id}/refund', 'refund_order', perm='order:refund'),
    route('POST', '/v2/imports', 'start_import', perm='import:run'),
    route('GET', '/v2/imports/{import_id}', 'import_status', perm='import:read'),
    route('POST', '/v2/exports/csv', 'export_csv', perm='export:csv'),
    route('GET', '/v2/admin/shards', 'list_shards', perm='admin:shards'),
]
''',
    'docs/spec/retry.md': '''# Đặc tả thử lại (bản spec 2025-11, fixture)

- Số lần thử tối đa: max_attempts = 6.
- Backoff gốc: 250 ms, nhân đôi mỗi lần.
- Trần backoff: 9500 ms.
- Jitter: full jitter.
- Mã HTTP được thử lại: 502, 503, 504.
- Spec chỉ mô tả mục tiêu; giá trị chạy thật do code và cấu hình quyết định.
''',
    'src/kho_ve/retry.py': '''"""Thử lại khi gọi cổng thanh toán (fixture)."""
# Ưu tiên: khóa có trong config/retry.toml ghi đè hằng số dưới đây; docs/spec/retry.md chỉ là mô tả.
MAX_ATTEMPTS = 5
BASE_DELAY_MS = 320
CAP_MS = 8000
JITTER = 'equal'
RETRYABLE = {429, 503}


def settings(config):
    return {key: config.get(key, default) for key, default in (
        ('max_attempts', MAX_ATTEMPTS), ('base_delay_ms', BASE_DELAY_MS), ('cap_ms', CAP_MS),
        ('jitter', JITTER), ('retryable', sorted(RETRYABLE)))}
''',
    'config/retry.toml': '''# Cấu hình thử lại đang triển khai (fixture)
max_attempts = 7
base_delay_ms = 275
cap_ms = 12000
jitter = "decorrelated"
retryable = [500, 502, 503, 504]
''',
    'docs/adr/0007-hold-queue.md': '''# ADR-0007: Hàng đợi giữ vé
- Ngày: 2024-03-12
- Quyết định: dùng RabbitMQ 3.12 cho hàng đợi giữ vé và hàng đợi email.
- Trạng thái: Superseded by ADR-0011.
''',
    'docs/adr/0011-streaming.md': '''# ADR-0011: Chuyển sang streaming
- Ngày: 2025-01-20
- Quyết định: hàng đợi giữ vé chuyển sang NATS JetStream; email vẫn giữ RabbitMQ 3.12; audit log dùng Kafka 3.6.
- Trạng thái: Partially superseded by ADR-0014 (chỉ phần hàng đợi giữ vé).
''',
    'docs/adr/0014-hold-redis.md': '''# ADR-0014: Hàng đợi giữ vé trên Redis
- Ngày: 2025-09-04
- Quyết định: hàng đợi giữ vé dùng Redis Streams 7.2, consumer group "hold-workers", retention 72h.
- Không đổi: email (RabbitMQ) và audit log (Kafka) theo ADR-0011.
- Trạng thái: Accepted.
''',
    'CHANGELOG.md': '''# Changelog kho-ve (fixture)
## 4.9.0 - 2026-08-28
- Thêm xuất CSV theo cột chọn. Breaking: không.
## 4.8.2 - 2026-07-30
- Sửa lỗi KV-E1279 trả sai mã. Breaking: không.
## 4.8.0 - 2026-06-17
- Bỏ endpoint /v1/holds. Breaking: có.
## 4.7.3 - 2026-05-02
- Tăng shard_count lên 29. Breaking: không.
## 4.7.0 - 2026-03-21
- Bắt buộc Idempotency-Key cho POST. Breaking: có.
## 4.6.1 - 2026-02-09
- Sửa rò kết nối idle. Breaking: không.
## 4.6.0 - 2025-12-15
- Đổi định dạng hold_id sang ULID. Breaking: có.
## 4.5.4 - 2025-11-03
- Cập nhật thư viện Redis client. Breaking: không.
## 4.5.0 - 2025-09-29
- Chuyển hàng đợi giữ vé sang Redis Streams. Breaking: không.
## 4.4.2 - 2025-08-11
- Sửa phân trang max_page_size. Breaking: không.
''',
    'docs/runbook/alerts.md': '''# Runbook cảnh báo kho-ve (fixture)
| Alert | Ngưỡng | Hành động đầu tiên |
|---|---|---|
| KVHoldLagHigh | p95 độ trễ giữ ghế > 412 ms trong 10 phút | Kiểm consumer group hold-workers |
| KVHoldQueueDepth | backlog > 8350 message | Tăng số worker giữ vé |
| KVDeadLetterGrowth | DLQ tăng > 137 message/giờ | Xem max_redeliveries và lỗi gốc |
| KVImportStuck | lô nhập chạy > 1460 giây | Hủy lô và kiểm parse_timeout_ms |
| KVRateLimitSpike | tỉ lệ KV-E1158 > 6.5% | Liên hệ tenant, xem rate_limit_rps |
| KVShardDiskHigh | dung lượng shard > 87% | Chạy compaction thủ công |
| KVPaymentRetryStorm | retry thanh toán > 2200 lần/phút | Kiểm config/retry.toml |
| KVOrderErrorRate | lỗi 5xx đơn hàng > 1.75% | Rollback bản mới nhất |
| KVTokenFailures | KV-E1420 > 340 lần/phút | Kiểm khóa ký JWT |
| KVExportSlow | xuất CSV p99 > 38 giây | Giảm csv_max_columns tạm thời |
''',
    'src/kho_ve/flags.py': '''"""Feature flag của kho-ve (fixture)."""
from .flagkit import Flag

FLAGS = [
    Flag('seat_map_v3', default=False, owner='team-ghe', expires='2026-12-01'),
    Flag('hold_redis_streams', default=True, owner='team-hang-doi', expires='2026-10-15'),
    Flag('csv_column_picker', default=True, owner='team-xuat', expires='2027-01-31'),
    Flag('refund_partial', default=False, owner='team-thanh-toan', expires='2026-11-20'),
    Flag('import_parallel_parse', default=False, owner='team-nhap', expires='2026-12-31'),
    Flag('ulid_hold_ids', default=True, owner='team-hang-doi', expires='2026-10-30'),
    Flag('tenant_burst_v2', default=False, owner='team-api', expires='2027-02-28'),
    Flag('cold_storage_tiering', default=False, owner='team-luu-tru', expires='2027-03-15'),
    Flag('jwt_rotation_auto', default=True, owner='team-bao-mat', expires='2026-12-10'),
    Flag('order_etag_strict', default=True, owner='team-don-hang', expires='2027-04-01'),
    Flag('alert_runbook_links', default=False, owner='team-van-hanh', expires='2026-11-05'),
]
''',
}

TAIL = (' Bắt buộc đủ mọi dòng/mục, không gộp hay bỏ bớt; mỗi dòng ghi path:line và trích ngắn đúng nguyên văn. '
        'Sau bảng ghi kiểm chứng đã làm và giới hạn.')


def pair(*parts):
    return [re.escape(p) if not p.startswith('re:') else p[3:] for p in parts]


CASES = [
    {'id': 'limits_table', 'role': 'explore',
     'question': 'Lập bảng TẤT CẢ 14 khóa giới hạn trong config/limits.yaml: nhóm, khóa, giá trị, đơn vị, ý nghĩa.' + TAIL,
     'items': [pair(k, v) for k, v in (('max_batch_rows', '7731'), ('max_payload_kib', '913'), ('parse_timeout_ms', '4417'),
               ('visibility_timeout_s', '263'), ('max_redeliveries', '17'), ('dead_letter_ttl_h', '151'),
               ('shard_count', '29'), ('compaction_interval_min', '383'), ('cold_after_days', '47'),
               ('rate_limit_rps', '1187'), ('burst', '2311'), ('idle_conn_timeout_s', '97'),
               ('max_page_size', '641'), ('csv_max_columns', '1291'))]},
    {'id': 'error_codes_table', 'role': 'explore',
     'question': 'Lập bảng TẤT CẢ 12 mã lỗi trong src/kho_ve/errors.py: mã, HTTP status, thông điệp, nhóm lỗi (client/server).' + TAIL,
     'items': [pair(k, v) for k, v in (('KV-E1031', '409'), ('KV-E1047', '404'), ('KV-E1102', '422'), ('KV-E1158', '429'),
               ('KV-E1213', '403'), ('KV-E1279', '410'), ('KV-E1306', '400'), ('KV-E1384', '503'),
               ('KV-E1420', '401'), ('KV-E1497', '412'), ('KV-E1533', '413'), ('KV-E1589', '507'))]},
    {'id': 'routes_table', 'role': 'explore',
     'question': 'Lập bảng TẤT CẢ 12 route trong src/kho_ve/routes.py: method, path, handler, quyền (perm).' + TAIL,
     'items': [pair(p, q) for p, q in (('/v2/events', 'event:list'), ('/v2/events/{event_id}', 'event:read'),
               ('/seats', 'seat:read'), ('/holds', 'hold:write'), ('/v2/holds/{hold_id}', 'hold:release'),
               ('/confirm', 'order:create'), ('/v2/orders/{order_id}', 'order:read'), ('/refund', 'order:refund'),
               ('/v2/imports', 'import:run'), ('/v2/imports/{import_id}', 'import:read'),
               ('/v2/exports/csv', 'export:csv'), ('/v2/admin/shards', 'admin:shards'))]},
    {'id': 'retry_three_sources', 'role': 'research',
     'question': ('So sánh chính sách thử lại giữa 3 nguồn docs/spec/retry.md, src/kho_ve/retry.py, config/retry.toml: '
                  'với mỗi nguồn nêu max_attempts, backoff gốc, trần backoff, jitter, mã thử lại; chỉ ra mọi khác biệt và '
                  'nguồn nào thắng khi chạy thật (theo quy tắc ưu tiên ghi trong mã).') + TAIL,
     'items': [pair('re:\\b250\\b'), pair('re:\\b9[.,]?500\\b|9[.,]5\\s*s'), pair('re:\\b320\\b'),
               pair('re:\\b8[.,]?000\\b|\\b8\\s*s\\b'), pair('re:\\b275\\b'), pair('re:\\b12[.,]?000\\b|\\b12\\s*s\\b'),
               pair('re:\\bfull\\b'), pair('re:\\bequal\\b'), pair('re:decorrelated'), pair('re:\\b429\\b'),
               pair('re:\\b500\\b'), pair('re:retry\\.toml', 're:ghi đè|override|ưu tiên|thắng|precedence')]},
    {'id': 'adr_history', 'role': 'research',
     'question': ('Tổng hợp lịch sử 3 ADR trong docs/adr/ (0007, 0011, 0014): bảng ngày, quyết định, trạng thái, bị thay bởi; '
                  'rồi bảng công nghệ hiện hành cho từng workload (giữ vé, email, audit log) với ADR quyết định.') + TAIL,
     'items': [pair('0007', '2024-03-12'), pair('0011', '2025-01-20'), pair('0014', '2025-09-04'),
               pair('re:RabbitMQ'), pair('re:JetStream'), pair('re:Redis Streams'), pair('hold-workers'),
               pair('re:72\\s*h|72 giờ'), pair('re:Kafka'), pair('re:email', 're:RabbitMQ'), pair('re:audit', 're:Kafka'),
               pair('re:Accepted|chấp nhận|hiệu lực')]},
    {'id': 'changelog_table', 'role': 'explore',
     'question': 'Lập bảng TẤT CẢ 10 phiên bản trong CHANGELOG.md: phiên bản, ngày, thay đổi, có breaking hay không.' + TAIL,
     'items': [pair(v, d) for v, d in (('4.9.0', '2026-08-28'), ('4.8.2', '2026-07-30'), ('4.8.0', '2026-06-17'),
               ('4.7.3', '2026-05-02'), ('4.7.0', '2026-03-21'), ('4.6.1', '2026-02-09'), ('4.6.0', '2025-12-15'),
               ('4.5.4', '2025-11-03'), ('4.5.0', '2025-09-29'), ('4.4.2', '2025-08-11'))]},
    {'id': 'alerts_table', 'role': 'explore',
     'question': 'Lập bảng TẤT CẢ 10 cảnh báo trong docs/runbook/alerts.md: tên alert, ngưỡng (giữ số), hành động đầu tiên, khóa cấu hình liên quan nếu có.' + TAIL,
     'items': [pair(a, t) for a, t in (('KVHoldLagHigh', '412'), ('KVHoldQueueDepth', 're:8[.,]?350'),
               ('KVDeadLetterGrowth', '137'), ('KVImportStuck', 're:1[.,]?460'), ('KVRateLimitSpike', 're:6[.,]5'),
               ('KVShardDiskHigh', '87'), ('KVPaymentRetryStorm', 're:2[.,]?200'), ('KVOrderErrorRate', 're:1[.,]75'),
               ('KVTokenFailures', '340'), ('KVExportSlow', '38'))]},
    {'id': 'flags_table', 'role': 'explore',
     'question': 'Lập bảng TẤT CẢ 11 feature flag trong src/kho_ve/flags.py: tên, default, owner, ngày hết hạn.' + TAIL,
     'items': [pair(f, o) for f, o in (('seat_map_v3', 'team-ghe'), ('hold_redis_streams', 'team-hang-doi'),
               ('csv_column_picker', 'team-xuat'), ('refund_partial', 'team-thanh-toan'), ('import_parallel_parse', 'team-nhap'),
               ('ulid_hold_ids', 'team-hang-doi'), ('tenant_burst_v2', 'team-api'), ('cold_storage_tiering', 'team-luu-tru'),
               ('jwt_rotation_auto', 'team-bao-mat'), ('order_etag_strict', 'team-don-hang'),
               ('alert_runbook_links', 'team-van-hanh'))]},
]


TAIL_ITEM = [r'^\s*(#{1,6}\s*|\*\*|[-*]\s*\*\*)?\s*(\d+[.)]\s*)?(Giới hạn|Hạn chế|Limitations?)\b']
for _case in CASES:
    _case['items'].append(TAIL_ITEM)


def coverage(text, case):
    lines = (text or '').splitlines()
    hits = [any(all(re.search(p, line, re.IGNORECASE) for p in item) for line in lines) for item in case['items']]
    return {'covered': sum(hits), 'total': len(hits), 'score': round(100 * sum(hits) / len(hits), 1),
            'missing': [i for i, ok in enumerate(hits) if not ok], 'tailPresent': hits[-1]}
