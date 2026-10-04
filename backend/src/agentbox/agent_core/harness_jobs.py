"""Sổ job nền và hộp thư đánh thức bền vững trên SessionStore.

Module này chỉ là DỮ LIỆU: nó không tự cấp quyền, không tự chạy tiến trình, không
gọi model, không gọi mạng. `capability_ref` là tham chiếu đã được cấp ở tầng
admission bên ngoài; ghi nó vào sổ không cấp thêm quyền nào. Caller phải tự gác
principal/controller và tự quyết định có được phép chạy hay không.

Bất biến đã ghim bằng test:
- `append` ghi trạng thái job + hàng outbox trong CÙNG một transaction.
- Không đánh thức model vì heartbeat/log/progress/receipt trung gian.
- Turn-owned job không sống qua lượt; controller-owned job sống qua lượt.
- `cancel` không bao giờ tự nhận là tiến trình đã dừng; completion muộn vẫn lưu
  receipt nhưng job đóng là `cancelled`, không phải `succeeded`.
- `reconcile` không bao giờ sinh tiến trình thay thế (spawned luôn 0).

Giao ước transaction: `_write` chỉ tự mở transaction khi nó là người sở hữu. Caller
đã ở trong transaction phải giữ write lock (`BEGIN IMMEDIATE`); nếu không, commit
đồng thời nổi lên thành `SQLITE_BUSY`, không phải mã xung đột chuẩn.

Giới hạn đã biết của tầng này (không có API nào sửa các giới hạn này):
- `wait` giao event và tiến con trỏ cho bất kỳ `consumer_id` nào ghi trên hàng
  outbox, không đòi wake lock. Hai waiter trên cùng một store có thể lấy mất event
  của nhau; muốn một owner chỉ có một waiter sống thì caller phải tự buộc wake lock
  quanh vòng `wait`/`acquire_wake` (lock chỉ là thoả thuận, không phải chốt).
- `eventSeq` do producer truyền vào `append` là dữ liệu caller: một seq nhảy cách
  (lớn hơn `last+1`) tạo lỗ hổng không phân biệt được với một hàng outbox bị mất.
  Muốn phát hiện mất hàng thì producer phải tự bảo đảm/gác dãy seq liên tục.
"""
from contextlib import contextmanager
import json
import sqlite3
import time
import uuid

from .orchestration_contracts import identifier, invalid, object_fields, refs, revision, text
from .work_policy import digest

RECORD_SCHEMA_VERSION = 1
JOB_SCHEMA = 'boxfox-job-request/1'
ADMISSION_SCHEMA = 'boxfox-job-admission/1'
JOB_KINDS = frozenset({'model', 'process'})
OWNERSHIPS = frozenset({'controller', 'turn'})
JOB_STATES = frozenset({'queued', 'running', 'waiting', 'succeeded', 'partial', 'failed',
                        'interrupted', 'cancelled', 'unknown'})
OPEN_STATES = frozenset({'queued', 'running', 'waiting'})
CLOSED_STATES = JOB_STATES - OPEN_STATES
# Chỉ ba nhóm này đánh thức model; heartbeat/log/progress chỉ nằm trong event stream.
EVENT_KINDS = frozenset({'result', 'blocker', 'owner_subscribed', 'progress', 'heartbeat',
                         'log', 'control'})
WAKE_KINDS = frozenset({'result', 'blocker', 'owner_subscribed'})
CONTROL_STATES = frozenset({'cancel_requested'})
WAKE_TTL_SECONDS = 300.0
PAGE_LIMIT = 100
REASON_MAX = 4000

# Cột bắt buộc của từng bảng: DB cũ thiếu cột thì fail closed, không tự đoán.
TABLES = (
    ('harness_jobs', ('job_id', 'schema_version', 'controller_id', 'owner_id', 'task_key', 'kind',
                      'ownership', 'revision', 'state', 'capability_epoch', 'admission_json',
                      'checkpoint_ref', 'result_refs_json', 'executor_handle_json',
                      'created_at', 'updated_at', 'closed_at')),
    ('harness_wake_outbox', ('wake_id', 'job_id', 'consumer_id', 'event_seq', 'predicate',
                             'status', 'payload_json', 'created_at', 'delivered_at')),
    ('harness_wake_cursors', ('consumer_id', 'job_id', 'last_seq', 'updated_at')),
    ('harness_wake_locks', ('owner_id', 'consumer_id', 'cursor_json', 'acquired_at', 'expires_at')),
    ('harness_job_invocations', ('owner_id', 'invocation_id', 'schema_version', 'request_hash',
                                 'result_json')),
)

SCHEMA = '''
    CREATE TABLE IF NOT EXISTS harness_jobs (
        job_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
        controller_id TEXT NOT NULL, owner_id TEXT NOT NULL, task_key TEXT,
        kind TEXT NOT NULL, ownership TEXT NOT NULL, revision INTEGER NOT NULL,
        state TEXT NOT NULL, capability_epoch INTEGER NOT NULL,
        admission_json TEXT NOT NULL, checkpoint_ref TEXT,
        result_refs_json TEXT NOT NULL, executor_handle_json TEXT,
        created_at REAL NOT NULL, updated_at REAL NOT NULL, closed_at REAL
    );
    CREATE INDEX IF NOT EXISTS harness_jobs_owner ON harness_jobs(owner_id, state);
    CREATE UNIQUE INDEX IF NOT EXISTS harness_jobs_task_open ON harness_jobs(owner_id, task_key)
        WHERE task_key IS NOT NULL AND state IN ('queued','running','waiting');
    CREATE TABLE IF NOT EXISTS harness_wake_outbox (
        wake_id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES harness_jobs(job_id),
        consumer_id TEXT NOT NULL, event_seq INTEGER NOT NULL, predicate TEXT NOT NULL,
        status TEXT NOT NULL, payload_json TEXT NOT NULL,
        created_at REAL NOT NULL, delivered_at REAL,
        UNIQUE(job_id, consumer_id, event_seq, predicate)
    );
    CREATE INDEX IF NOT EXISTS harness_wake_outbox_job
        ON harness_wake_outbox(job_id, consumer_id, event_seq);
    CREATE TABLE IF NOT EXISTS harness_wake_cursors (
        consumer_id TEXT NOT NULL, job_id TEXT NOT NULL, last_seq INTEGER NOT NULL,
        updated_at REAL NOT NULL, PRIMARY KEY(consumer_id, job_id)
    );
    CREATE TABLE IF NOT EXISTS harness_wake_locks (
        owner_id TEXT PRIMARY KEY, consumer_id TEXT NOT NULL, cursor_json TEXT NOT NULL,
        acquired_at REAL NOT NULL, expires_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS harness_job_invocations (
        owner_id TEXT NOT NULL, invocation_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
        request_hash TEXT NOT NULL, result_json TEXT NOT NULL,
        PRIMARY KEY(owner_id, invocation_id)
    );
'''


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def wake_worthy(event):
    """Sự kiện có đáng đánh thức model theo LOẠI hay không.

    `result`/`blocker`/`owner_subscribed` đánh thức; heartbeat, log, progress và
    receipt trung gian thì không, dù chúng vẫn được ghi vào outbox/event stream.
    """
    return isinstance(event, dict) and event.get('kind') in WAKE_KINDS


def should_wake(event):
    """`wake_worthy` cộng cờ `intermediate` của producer: receipt trung gian không đánh thức."""
    return wake_worthy(event) and not event.get('intermediate', False)


def _decode(raw, field, shape=None):
    """Giải JSON đã lưu; hỏng/sai hình dạng là JOB_RECORD_CORRUPT, không lộ lỗi thô."""
    try:
        value = json.loads(raw)
    except (TypeError, ValueError) as exc:
        invalid(field, f'corrupt persisted job record: {exc}', 'JOB_RECORD_CORRUPT')
    if shape is not None and not isinstance(value, shape):
        invalid(field, 'corrupt persisted job record: unexpected shape', 'JOB_RECORD_CORRUPT')
    return value


def _stored_refs(raw):
    """Đọc danh sách result refs đã lưu; sai hình dạng là JOB_RECORD_CORRUPT."""
    merged = _decode(raw, 'result_refs_json', list)
    for item in merged:
        if not isinstance(item, dict) or not {'artifactId', 'version', 'contentHash'} <= set(item):
            invalid('result_refs_json', 'corrupt persisted job record: unexpected ref shape',
                    'JOB_RECORD_CORRUPT')
    return merged


def _state(value, field='state'):
    if not isinstance(value, str) or value not in JOB_STATES:
        invalid(field, 'unsupported job state')
    return value


def _cursor(value, field):
    if value is None:
        return 0
    if type(value) is not int or value < 0:
        invalid(field, 'expected a non-negative integer, not a boolean')
    return value


class HarnessJobs:
    def __init__(self, store, confirm_executor=None):
        """`confirm_executor(handle) -> bool` hỏi executor xem handle còn đúng danh tính.

        Không truyền adapter (hoặc adapter lỗi/trả falsy) nghĩa là KHÔNG xác nhận
        được; `reconcile` fail closed chứ không sinh tiến trình thay thế.
        """
        if confirm_executor is not None and not callable(confirm_executor):
            raise TypeError('confirm_executor(handle) must be callable when provided')
        self.store, self.db = store, store.db
        self.confirm_executor = confirm_executor
        self.wake_ttl_seconds = WAKE_TTL_SECONDS
        for table, required in TABLES:
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if columns and not set(required) <= columns:
                invalid('schemaVersion', f'{table} does not match the job record schema',
                        'JOB_SCHEMA_UNSUPPORTED')
        self.db.executescript(SCHEMA)

    @contextmanager
    def _write(self):
        # Giống task_service: tự mở transaction khi mình sở hữu, còn trong transaction
        # của caller thì dùng savepoint để giữ nguyên tính nguyên tử của caller.
        if self.db.in_transaction:
            self.db.execute('SAVEPOINT harness_jobs_write')
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK TO harness_jobs_write')
                raise
            finally:
                self.db.execute('RELEASE harness_jobs_write')
        else:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                yield

    @staticmethod
    def _schema(row):
        if type(row['schema_version']) is not int or row['schema_version'] != RECORD_SCHEMA_VERSION:
            invalid('schemaVersion', 'unsupported persisted job record schema', 'JOB_SCHEMA_UNSUPPORTED')

    def _job(self, job_id):
        identifier(job_id, 'jobId')
        row = self.db.execute('SELECT * FROM harness_jobs WHERE job_id=?', (job_id,)).fetchone()
        if row is None:
            invalid('jobId', 'unknown job', 'JOB_UNKNOWN')
        self._schema(row)
        return row

    @staticmethod
    def _expected(row, expected_revision):
        revision(expected_revision)
        if row['revision'] != expected_revision:
            invalid('expectedRevision', 'job revision changed', 'JOB_REVISION_CONFLICT')

    def _next_seq(self):
        # `event_seq` là con trỏ TOÀN CỤC của outbox: `wait` chỉ có một `cursor` vô hướng
        # cho nhiều job, nên thứ tự phải dùng chung một dãy tăng.
        row = self.db.execute('SELECT COALESCE(MAX(event_seq),0) AS seq FROM harness_wake_outbox').fetchone()
        return row['seq']

    def _job_seq(self, job_id):
        row = self.db.execute('SELECT COALESCE(MAX(event_seq),0) AS seq FROM harness_wake_outbox '
                              'WHERE job_id=?', (job_id,)).fetchone()
        return row['seq']

    def _cached(self, owner_id, invocation_id, request_hash):
        identifier(invocation_id, 'invocationId')
        row = self.db.execute('SELECT * FROM harness_job_invocations WHERE owner_id=? AND invocation_id=?',
                              (owner_id, invocation_id)).fetchone()
        if row is None:
            return None
        if type(row['schema_version']) is not int or row['schema_version'] != RECORD_SCHEMA_VERSION:
            invalid('schemaVersion', 'unsupported persisted invocation receipt', 'JOB_SCHEMA_UNSUPPORTED')
        if row['request_hash'] != request_hash:
            invalid('invocationId', 'invocation reused with a different request', 'JOB_INVOCATION_CONFLICT')
        result = _decode(row['result_json'], 'result_json', dict)
        job_id = result.get('jobId')
        if not isinstance(job_id, str):
            invalid('result_json', 'corrupt persisted invocation receipt: missing jobId',
                    'JOB_RECORD_CORRUPT')
        self._job(job_id)
        return result

    def _remember(self, owner_id, invocation_id, request_hash, result):
        try:
            self.db.execute('INSERT INTO harness_job_invocations VALUES(?,?,?,?,?)',
                            (owner_id, invocation_id, RECORD_SCHEMA_VERSION, request_hash, encode(result)))
        except sqlite3.IntegrityError:
            # Caller đồng thời có thể đã commit invocation này; hàng là chân lý, nên
            # replay receipt khớp hash thay vì báo lỗi mơ hồ.
            cached = self._cached(owner_id, invocation_id, request_hash)
            if cached is not None:
                return cached
            raise
        return result

    @staticmethod
    def _view(row):
        return {
            'schemaVersion': row['schema_version'], 'jobId': row['job_id'],
            'controllerId': row['controller_id'], 'ownerId': row['owner_id'],
            'taskKey': row['task_key'], 'kind': row['kind'], 'ownership': row['ownership'],
            'survivesTurn': row['ownership'] == 'controller', 'revision': row['revision'],
            'state': row['state'], 'capabilityEpoch': row['capability_epoch'],
            'admission': _decode(row['admission_json'], 'admission_json', dict),
            'checkpointRef': row['checkpoint_ref'],
            'resultRefs': _stored_refs(row['result_refs_json']),
            'executorHandle': (_decode(row['executor_handle_json'], 'executor_handle_json', dict)
                               if row['executor_handle_json'] else None),
            'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
            'closedAt': row['closed_at'],
        }

    @staticmethod
    def _request(owner_id, value):
        request = object_fields(value, 'request', ('schema', 'kind', 'ownership'),
                                ('controllerId', 'taskKey', 'childSessionId', 'executor', 'checkpointRef'))
        if request['schema'] != JOB_SCHEMA:
            invalid('schema', 'unsupported job request schema', 'HARNESS_SCHEMA_UNSUPPORTED')
        if request['kind'] not in JOB_KINDS:
            invalid('kind', 'expected model or process')
        if request['ownership'] not in OWNERSHIPS:
            invalid('ownership', 'expected controller or turn')
        normalized = {'schema': JOB_SCHEMA, 'kind': request['kind'],
                      'ownership': request['ownership'],
                      'controllerId': request.get('controllerId', owner_id)}
        identifier(normalized['controllerId'], 'controllerId')
        if 'taskKey' in request:
            identifier(request['taskKey'], 'taskKey', alias=True)
            normalized['taskKey'] = request['taskKey']
        if 'childSessionId' in request:
            identifier(request['childSessionId'], 'childSessionId')
            normalized['childSessionId'] = request['childSessionId']
        if 'executor' in request:
            handle = request['executor']
            if not isinstance(handle, dict) or not all(isinstance(key, str) for key in handle):
                invalid('executor', 'expected a JSON object handle')
            normalized['executor'] = dict(handle)
        if 'checkpointRef' in request:
            text(request['checkpointRef'], 'checkpointRef', 400)
            normalized['checkpointRef'] = request['checkpointRef']
        try:
            encode(normalized)
        except (TypeError, ValueError) as exc:
            invalid('request', f'not a finite JSON document: {exc}')
        return normalized

    @staticmethod
    def _capability(value):
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            invalid('capabilityRef', 'expected a JSON object reference')
        try:
            encode(value)
        except (TypeError, ValueError) as exc:
            invalid('capabilityRef', f'not a finite JSON document: {exc}')
        epoch = value.get('epoch', 1)
        if type(epoch) is not int or epoch < 1:
            invalid('capabilityRef.epoch', 'expected a positive integer, not a boolean')
        return dict(value), epoch

    @staticmethod
    def _event(value, owner_id):
        event = object_fields(value, 'event', ('kind',),
                              ('consumerId', 'predicate', 'state', 'resultRefs', 'receiptRef',
                               'reason', 'payload', 'intermediate', 'eventSeq', 'controlState'))
        if event['kind'] not in EVENT_KINDS:
            invalid('event.kind', 'unsupported job event kind')
        normalized = {'kind': event['kind'],
                      'consumerId': event.get('consumerId', owner_id),
                      'predicate': event.get('predicate', event['kind'])}
        identifier(normalized['consumerId'], 'event.consumerId')
        identifier(normalized['predicate'], 'event.predicate')
        if 'state' in event:
            normalized['state'] = _state(event['state'], 'event.state')
        if 'resultRefs' in event:
            normalized['resultRefs'] = refs(event['resultRefs'], 'event.resultRefs')
        if 'receiptRef' in event:
            identifier(event['receiptRef'], 'event.receiptRef')
            normalized['receiptRef'] = event['receiptRef']
        if 'reason' in event:
            text(event['reason'], 'event.reason', REASON_MAX)
            normalized['reason'] = event['reason']
        if 'payload' in event:
            payload = event['payload']
            if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
                invalid('event.payload', 'expected a JSON object')
            normalized['payload'] = dict(payload)
        if 'intermediate' in event:
            if type(event['intermediate']) is not bool:
                invalid('event.intermediate', 'expected a boolean')
            normalized['intermediate'] = event['intermediate']
        if 'eventSeq' in event:
            if type(event['eventSeq']) is not int or event['eventSeq'] < 1:
                invalid('event.eventSeq', 'expected a positive integer, not a boolean')
            normalized['eventSeq'] = event['eventSeq']
        if 'controlState' in event:
            if event['kind'] != 'control' or event['controlState'] not in CONTROL_STATES:
                invalid('event.controlState', 'only control events carry a supported control state')
            normalized['controlState'] = event['controlState']
        try:
            encode(normalized)
        except (TypeError, ValueError) as exc:
            invalid('event', f'not a finite JSON document: {exc}')
        return normalized

    def start(self, owner_id, request, capability_ref, invocation_id):
        """Mở job mới; idempotent theo `(owner_id, invocation_id)` + hash request.

        Chỉ ghi sổ: trả về `{jobId, controllerId, kind, state, ownership, revision, ...}`.
        Trùng invocation cùng hash thì replay receipt cũ; khác hash là
        `JOB_INVOCATION_CONFLICT`. Hai job đang mở cùng một task alias của một owner
        là `JOB_ALIAS_CONFLICT`.
        """
        identifier(owner_id, 'ownerId')
        identifier(invocation_id, 'invocationId')
        payload = self._request(owner_id, request)
        capability, epoch = self._capability(capability_ref)
        request_hash = digest({'action': 'start_job', 'ownerId': owner_id, 'request': payload,
                               'capabilityRef': capability})
        with self._write():
            cached = self._cached(owner_id, invocation_id, request_hash)
            if cached is not None:
                return cached
            job_id, now = 'job-' + uuid.uuid4().hex, time.time()
            admission = {'schema': ADMISSION_SCHEMA, 'invocationId': invocation_id,
                         'capabilityRef': capability, 'childSessionId': payload.get('childSessionId'),
                         'request': payload}
            handle = payload.get('executor')
            if handle is None and payload.get('childSessionId'):
                handle = {'childSessionId': payload['childSessionId']}
            try:
                self.db.execute('INSERT INTO harness_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                (job_id, RECORD_SCHEMA_VERSION, payload['controllerId'], owner_id,
                                 payload.get('taskKey'), payload['kind'], payload['ownership'], 1,
                                 'queued', epoch, encode(admission), payload.get('checkpointRef'),
                                 '[]', encode(handle) if handle is not None else None, now, now, None))
            except sqlite3.IntegrityError:
                cached = self._cached(owner_id, invocation_id, request_hash)
                if cached is not None:
                    return cached
                invalid('taskKey', 'another open job already uses this task alias', 'JOB_ALIAS_CONFLICT')
            return self._remember(owner_id, invocation_id, request_hash, self._view(self._job(job_id)))

    def append(self, job_id, event, expected_revision=None):
        """Producer commit: trạng thái/revision job + hàng outbox trong MỘT transaction.

        Trả về `event_seq` mới. Gửi lại đúng `(job_id, event_seq, consumer, predicate)`
        không có tác dụng thứ hai (không tăng revision, không thêm hàng). Producer đã
        commit trước khi bất kỳ thông báo nào được gửi.
        """
        with self._write():
            return self._append_locked(self._job(job_id), event, expected_revision)

    def _append_locked(self, row, event, expected_revision):
        normalized = self._event(event, row['owner_id'])
        seq = normalized.pop('eventSeq', None)
        last = self._next_seq()
        if seq is not None and seq <= last:
            # Replay được kiểm TRƯỚC revision: producer mất response gửi lại đúng event
            # đã áp dụng phải nhận receipt cũ, dù revision hiện tại đã tiến (như cancel).
            existing = self.db.execute(
                'SELECT * FROM harness_wake_outbox WHERE job_id=? AND consumer_id=? AND event_seq=? '
                'AND predicate=?', (row['job_id'], normalized['consumerId'], seq,
                                    normalized['predicate'])).fetchone()
            if existing is None:
                invalid('eventSeq', 'event sequence already used by another consumer/predicate',
                        'JOB_EVENT_CONFLICT')
            stored = _decode(existing['payload_json'], 'payload_json', dict)
            replayed = {key: value for key, value in stored.items()
                        if key not in ('jobId', 'eventSeq', 'state', 'reportedState')}
            expected = {key: value for key, value in normalized.items() if key != 'state'}
            states = {stored.get('state'), stored.get('reportedState')}
            if replayed != expected or ('state' in normalized and normalized['state'] not in states):
                invalid('eventSeq', 'event sequence replayed with a different payload',
                        'JOB_EVENT_CONFLICT')
            return existing['event_seq']
        if expected_revision is not None:
            self._expected(row, expected_revision)
        if seq is None:
            seq = last + 1
        state = normalized.get('state')
        reported = state
        control = self._control(row['job_id'])
        cancel_requested = control is not None and control.get('controlState') == 'cancel_requested'
        if state is not None:
            if row['state'] in CLOSED_STATES:
                # Job đã đóng: chỉ nhận receipt cùng trạng thái, không viết lại lịch sử.
                if state != row['state']:
                    invalid('state', 'closed job cannot change state', 'JOB_CLOSED')
            elif cancel_requested and state in CLOSED_STATES:
                # Completion đến muộn sau cancel: lưu receipt nhưng không xác nhận thành công.
                state = 'cancelled'
        now = time.time()
        payload = dict(normalized)
        if state is not None:
            payload['state'] = state
        if reported is not None and reported != state:
            payload['reportedState'] = reported
        payload.update({'jobId': row['job_id'], 'eventSeq': seq})
        refs_json = row['result_refs_json']
        if 'resultRefs' in normalized:
            merged = _stored_refs(row['result_refs_json'])
            known = {(item['artifactId'], item['version']): item['contentHash'] for item in merged}
            for item in normalized['resultRefs']:
                key = (item['artifactId'], item['version'])
                if key in known:
                    if known[key] != item['contentHash']:
                        invalid('event.resultRefs', 'artifact version already recorded with a different hash',
                                'JOB_REF_CONFLICT')
                    continue
                merged.append(item)
                known[key] = item['contentHash']
            refs_json = encode(merged)
        if state is not None:
            self.db.execute('UPDATE harness_jobs SET state=?, revision=revision+1, updated_at=?, '
                            'closed_at=?, result_refs_json=? WHERE job_id=?',
                            (state, now, now if state in CLOSED_STATES else None, refs_json,
                             row['job_id']))
        else:
            self.db.execute('UPDATE harness_jobs SET revision=revision+1, updated_at=?, '
                            'result_refs_json=? WHERE job_id=?', (now, refs_json, row['job_id']))
        self.db.execute('INSERT INTO harness_wake_outbox VALUES(?,?,?,?,?,?,?,?,?)',
                        ('wake-' + uuid.uuid4().hex, row['job_id'], normalized['consumerId'], seq,
                         normalized['predicate'], 'pending', encode(payload), now, None))
        return seq

    def cancel(self, job_id, expected_revision, reason):
        """Ghi `cancel_requested` + receipt; KHÔNG bao giờ tự nhận tiến trình đã dừng.

        Idempotent: gọi lại trả đúng receipt cũ, không tăng revision lần nữa. Job vẫn
        mở cho tới khi completion muộn (đóng `cancelled`) hoặc `reconcile` quyết định.
        """
        revision(expected_revision)
        text(reason, 'reason', REASON_MAX)
        with self._write():
            row = self._job(job_id)
            control = self._control(job_id)
            if control is not None and control.get('controlState') == 'cancel_requested':
                return {'jobId': job_id, 'cancelRequested': True, 'alreadyRequested': True,
                        'receiptRef': control.get('receiptRef'), 'controlState': 'cancel_requested',
                        'state': row['state'], 'revision': row['revision'],
                        'capabilityEpoch': row['capability_epoch'], 'closedAt': row['closed_at']}
            self._expected(row, expected_revision)
            if row['state'] in CLOSED_STATES:
                invalid('jobId', 'job already closed; nothing to cancel', 'JOB_CLOSED')
            receipt_ref = 'receipt-' + uuid.uuid4().hex
            # Cancel tạo epoch mới: capability đã admit cho job này bị vượt qua.
            self.db.execute('UPDATE harness_jobs SET capability_epoch=capability_epoch+1 WHERE job_id=?',
                            (job_id,))
            self._append_locked(row, {'kind': 'control', 'predicate': 'control',
                                      'consumerId': row['owner_id'], 'reason': reason,
                                      'receiptRef': receipt_ref,
                                      'controlState': 'cancel_requested'}, None)
            updated = self._job(job_id)
            return {'jobId': job_id, 'cancelRequested': True, 'alreadyRequested': False,
                    'receiptRef': receipt_ref, 'controlState': 'cancel_requested',
                    'state': updated['state'], 'revision': updated['revision'],
                    'capabilityEpoch': updated['capability_epoch'], 'closedAt': updated['closed_at']}

    def get(self, job_id, cursor=None):
        """Ảnh chụp job + event stream sau `cursor`; không bao giờ mutate trạng thái job."""
        row = self._job(job_id)
        after = _cursor(cursor, 'cursor')
        events = self._events(job_id, after)
        view = self._view(row)
        control = self._control(job_id)
        reason = next((item['reason'] for item in reversed(events) if item.get('reason')), None)
        if reason is None and control is not None:
            reason = control.get('reason')
        handle = view['executorHandle'] if isinstance(view['executorHandle'], dict) else {}
        view.update({
            'reason': reason,
            'outputRef': view['resultRefs'][-1] if view['resultRefs'] else None,
            'exitCode': handle.get('exitCode'),
            'processState': handle.get('processState'),
            'controlState': control.get('controlState') if control else None,
            'controlReceiptRef': control.get('receiptRef') if control else None,
            'events': events,
            'cursor': events[-1]['eventSeq'] if events else after,
            'lastEventSeq': self._job_seq(job_id),
        })
        return view

    def subscribe(self, job_id, consumer_id, predicate=None, after_seq=0):
        """Đăng ký consumer theo dõi job; con trỏ chỉ tiến, không bao giờ lùi."""
        identifier(consumer_id, 'consumerId')
        if predicate is not None:
            identifier(predicate, 'predicate')
        after = _cursor(after_seq, 'afterSeq')
        with self._write():
            row = self._job(job_id)
            self._advance_cursor(consumer_id, job_id, after)
            current = self.db.execute('SELECT last_seq FROM harness_wake_cursors WHERE consumer_id=? '
                                      'AND job_id=?', (consumer_id, job_id)).fetchone()['last_seq']
            return {'subscriptionId': 'sub-' + digest({'jobId': job_id, 'consumerId': consumer_id})[:24],
                    'jobId': job_id, 'consumerId': consumer_id, 'predicate': predicate,
                    'state': row['state'], 'cursor': current}

    def wait(self, job_ids, mode='any', after_seq=0):
        """Ảnh chụp đánh thức; KHÔNG bao giờ ngủ/chờ timeout, kể cả khi job đã đóng.

        Trả `{events, cursor, ready, interrupted, jobs}`:
        - `events`: sự kiện đáng đánh thức, gộp theo `(job_id, consumer_id, predicate)`
          nên một batch chỉ còn MỘT wake (bản mới nhất); hàng đã giao được đánh dấu
          `delivered` và con trỏ wake `(consumer, job)` tiến tới seq lớn nhất đã quan sát.
        - `jobs`: trạng thái + refs từng job, kể cả khi không có event mới.
        - `ready`: `any` = có job đóng/đã có wake; `all` = mọi job đều vậy. Job có
          child canonical đã đóng cũng tính là đóng (trả ngay, không park).
        - `cursor`: mốc `event_seq` toàn cục lớn nhất đã quan sát. `after_seq` chỉ áp cho
          hàng của consumer đã có con trỏ wake; job mới gia nhập tập theo dõi vẫn thấy
          event wake chưa đọc của nó (không bị con trỏ toàn cục bỏ qua).
        """
        if mode not in ('any', 'all'):
            invalid('mode', 'expected any or all')
        after = _cursor(after_seq, 'afterSeq')
        if not isinstance(job_ids, list) or not job_ids:
            invalid('jobIds', 'expected a non-empty list of job IDs')
        if len(job_ids) > PAGE_LIMIT:
            invalid('jobIds', 'too many jobs')
        ids = []
        for job_id in job_ids:
            identifier(job_id, 'jobIds')
            if job_id not in ids:
                ids.append(job_id)
        with self._write():
            rows = [self._job(job_id) for job_id in ids]
            observed = []
            for job_id in ids:
                # Con trỏ wake theo (consumer, job) là sàn đọc: hàng của consumer chưa
                # từng có con trỏ không bị `after_seq` toàn cục chặn, nên job gia nhập
                # tập theo dõi sau vẫn thấy event wake chưa đọc của nó.
                observed.extend(self.db.execute(
                    'SELECT o.* FROM harness_wake_outbox AS o '
                    'LEFT JOIN harness_wake_cursors AS c ON c.job_id=o.job_id '
                    'AND c.consumer_id=o.consumer_id '
                    'WHERE o.job_id=? AND o.event_seq > CASE WHEN c.consumer_id IS NULL THEN 0 ELSE ? END '
                    'AND o.event_seq > COALESCE(c.last_seq, 0) ORDER BY o.event_seq',
                    (job_id, after)).fetchall())
            observed.sort(key=lambda item: item['event_seq'])
            groups = {}
            for item in observed:
                if not should_wake(_decode(item['payload_json'], 'payload_json', dict)):
                    continue
                groups.setdefault((item['job_id'], item['consumer_id'], item['predicate']), []).append(item)
            wakes, now = [], time.time()
            for members in sorted(groups.values(), key=lambda group: max(row['event_seq'] for row in group)):
                latest = max(members, key=lambda item: item['event_seq'])
                wakes.append(latest)
                for member in members:
                    if member['status'] != 'delivered':
                        self.db.execute('UPDATE harness_wake_outbox SET status=?, delivered_at=? '
                                        'WHERE wake_id=?', ('delivered', now, member['wake_id']))
            # Mọi hàng đã quan sát đều tiến con trỏ wake của (consumer, job): lần wait sau
            # chỉ đọc phần mới, kể cả khi hàng chỉ là heartbeat/log/progress không đánh thức.
            advanced = {}
            for item in observed:
                key = (item['job_id'], item['consumer_id'])
                advanced[key] = max(advanced.get(key, 0), item['event_seq'])
            for (job_id, consumer_id), seq in advanced.items():
                self._advance_cursor(consumer_id, job_id, seq)
            woken = {item['job_id'] for item in wakes}
            jobs, interrupted, flags = {}, [], []
            for row in rows:
                closed = row['state'] in CLOSED_STATES or self._child_closed(row)
                ready = closed or row['job_id'] in woken
                view = dict(self._view(row), closed=closed, ready=ready)
                jobs[row['job_id']] = view
                if row['state'] in ('interrupted', 'unknown'):
                    interrupted.append(view)
                flags.append(ready)
            ready = any(flags) if mode == 'any' else all(flags)
            cursor = max([after] + [item['event_seq'] for item in observed])
            return {'events': [self._wake_view(item) for item in wakes], 'cursor': cursor,
                    'ready': ready, 'interrupted': interrupted, 'jobs': jobs}

    def acquire_wake(self, owner_id, consumer_id):
        """Một owner chỉ có MỘT wake lock sống; lock hết hạn thì consumer khác được thu hồi."""
        identifier(owner_id, 'ownerId')
        identifier(consumer_id, 'consumerId')
        now = time.time()
        with self._write():
            row = self.db.execute('SELECT * FROM harness_wake_locks WHERE owner_id=?',
                                  (owner_id,)).fetchone()
            if row is not None and row['expires_at'] > now and row['consumer_id'] != consumer_id:
                invalid('ownerId', f'wake lock held by another consumer until {row["expires_at"]}',
                        'JOB_WAKE_LOCKED')
            reclaimed = row is not None and row['consumer_id'] != consumer_id
            cursors = {item['job_id']: item['last_seq'] for item in self.db.execute(
                'SELECT * FROM harness_wake_cursors WHERE consumer_id=?', (consumer_id,))}
            expires = now + self.wake_ttl_seconds
            self.db.execute('INSERT INTO harness_wake_locks VALUES(?,?,?,?,?) '
                            'ON CONFLICT(owner_id) DO UPDATE SET consumer_id=excluded.consumer_id, '
                            'cursor_json=excluded.cursor_json, acquired_at=excluded.acquired_at, '
                            'expires_at=excluded.expires_at',
                            (owner_id, consumer_id, encode(cursors), now, expires))
            return {'ownerId': owner_id, 'consumerId': consumer_id, 'cursor': cursors,
                    'acquiredAt': now, 'expiresAt': expires, 'reclaimed': reclaimed}

    def release_wake(self, owner_id, consumer_id):
        """Nhả lock của chính mình; gọi lại là no-op, không giành lock của consumer khác."""
        identifier(owner_id, 'ownerId')
        identifier(consumer_id, 'consumerId')
        with self._write():
            cursor = self.db.execute('DELETE FROM harness_wake_locks WHERE owner_id=? AND consumer_id=?',
                                     (owner_id, consumer_id))
            return {'ownerId': owner_id, 'consumerId': consumer_id, 'released': cursor.rowcount > 0}

    def reconcile(self):
        """Sau restart: đóng job không còn xác nhận được executor; KHÔNG sinh tiến trình thay thế.

        - Job `turn` không sống qua lượt ⇒ `interrupted`.
        - Model job chỉ sống nếu child canonical vẫn mở ⇒ còn lại `interrupted`.
        - Process job chỉ sống nếu adapter `confirm_executor` xác nhận đúng danh tính
          ⇒ còn lại `unknown`.
        - Job đã có `cancel_requested` đóng thành `cancelled`.
        """
        outcome = {'scanned': 0, 'confirmed': [], 'interrupted': [], 'unknown': [],
                   'cancelled': [], 'spawned': 0}
        with self._write():
            placeholders = ','.join('?' for _ in OPEN_STATES)
            rows = self.db.execute(f'SELECT * FROM harness_jobs WHERE state IN ({placeholders}) '
                                   'ORDER BY created_at, job_id', tuple(sorted(OPEN_STATES))).fetchall()
            for row in rows:
                self._schema(row)
                outcome['scanned'] += 1
                control = self._control(row['job_id'])
                cancel_requested = control is not None and control.get('controlState') == 'cancel_requested'
                if cancel_requested:
                    state, reason = 'cancelled', 'cancel requested before restart; executor not confirmed'
                elif row['ownership'] == 'turn':
                    state, reason = 'interrupted', 'turn-owned job does not survive its turn'
                elif row['kind'] == 'model':
                    child_id = self._child_session(row)
                    child = self.store.child(child_id) if child_id else None
                    if child is not None and child['status'] == 'started' and child['finished'] is None:
                        outcome['confirmed'].append(row['job_id'])
                        continue
                    state, reason = 'interrupted', 'model executor unconfirmed after restart'
                else:
                    handle = (_decode(row['executor_handle_json'], 'executor_handle_json', dict)
                              if row['executor_handle_json'] else None)
                    confirmed = False
                    if handle is not None and self.confirm_executor is not None:
                        try:
                            confirmed = bool(self.confirm_executor(dict(handle)))
                        except Exception:
                            confirmed = False
                    if confirmed:
                        outcome['confirmed'].append(row['job_id'])
                        continue
                    state, reason = 'unknown', 'process executor identity unconfirmed after restart'
                self._append_locked(row, {'kind': 'result', 'predicate': 'reconcile',
                                          'consumerId': row['owner_id'], 'state': state,
                                          'reason': reason}, None)
                outcome[state].append(row['job_id'])
        return outcome

    def open_jobs(self, owner_id=None):
        """Job chưa đóng, mới nhất xếp sau; lọc theo owner khi có."""
        if owner_id is not None:
            identifier(owner_id, 'ownerId')
        placeholders = ','.join('?' for _ in OPEN_STATES)
        sql = f'SELECT * FROM harness_jobs WHERE state IN ({placeholders})'
        args = list(sorted(OPEN_STATES))
        if owner_id is not None:
            sql += ' AND owner_id=?'
            args.append(owner_id)
        rows = self.db.execute(sql + ' ORDER BY created_at, job_id', tuple(args)).fetchall()
        for row in rows:
            self._schema(row)
        return [self._view(row) for row in rows]

    def _advance_cursor(self, consumer_id, job_id, seq):
        self.db.execute('INSERT INTO harness_wake_cursors VALUES(?,?,?,?) '
                        'ON CONFLICT(consumer_id,job_id) DO UPDATE SET '
                        'last_seq=MAX(last_seq, excluded.last_seq), updated_at=excluded.updated_at',
                        (consumer_id, job_id, seq, time.time()))

    def _events(self, job_id, after):
        rows = self.db.execute('SELECT * FROM harness_wake_outbox WHERE job_id=? AND event_seq>? '
                               'ORDER BY event_seq, predicate', (job_id, after)).fetchall()
        seen, items = set(), []
        for row in rows:
            key = (row['event_seq'], row['predicate'])
            if key in seen:
                continue
            seen.add(key)
            items.append(self._wake_view(row))
        return items

    @staticmethod
    def _wake_view(row):
        event = _decode(row['payload_json'], 'payload_json', dict)
        event.update({'wakeId': row['wake_id'], 'status': row['status'],
                      'createdAt': row['created_at'], 'deliveredAt': row['delivered_at']})
        return event

    def _control(self, job_id):
        row = self.db.execute("SELECT * FROM harness_wake_outbox WHERE job_id=? AND predicate='control' "
                              'ORDER BY event_seq DESC LIMIT 1', (job_id,)).fetchone()
        if row is None:
            return None
        payload = _decode(row['payload_json'], 'payload_json', dict)
        return {'controlState': payload.get('controlState'), 'reason': payload.get('reason'),
                'receiptRef': payload.get('receiptRef'), 'eventSeq': row['event_seq'],
                'wakeId': row['wake_id'], 'createdAt': row['created_at']}

    @staticmethod
    def _child_session(row):
        handle = (_decode(row['executor_handle_json'], 'executor_handle_json', dict)
                  if row['executor_handle_json'] else None)
        if isinstance(handle, dict):
            for key in ('childSessionId', 'sessionId'):
                value = handle.get(key)
                if isinstance(value, str) and value:
                    return value
        admission = _decode(row['admission_json'], 'admission_json', dict)
        value = admission.get('childSessionId')
        return value if isinstance(value, str) and value else None

    def _child_closed(self, row):
        child_id = self._child_session(row)
        if child_id is None:
            return False
        child = self.store.child(child_id)
        if child is None:
            return False
        return child['status'] != 'started' or child['finished'] is not None
