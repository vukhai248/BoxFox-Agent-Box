"""Quyền sở hữu Research tường minh: chủ, bộ điều khiển, biên nhận điều khiển và bàn giao.

Kế hoạch v1 §9 chốt: Research là hệ chuyên gia độc lập, không phải mode main tự đóng vai
researcher. Module này giữ phần *định danh và quyền* của ranh giới đó:

- `owner_id` (Research lead) và `controller_id` là hai trường riêng. Chỉ hai định danh ấy được
  điều khiển run; peer/phiên con dùng chung session root KHÔNG tự cấp quyền.
- `claim`/`handoff`/`release` khoá lạc quan bằng `expected_revision` và tăng revision trong cùng
  một giao dịch; revision cũ ⇒ `RESEARCH_REVISION_CONFLICT`.
- `authorize` ghi biên nhận vào `harness_research_controls` cho MỌI quyết định, kể cả từ chối.
- `handoff` ghi biên nhận bàn giao vào `harness_research_handoffs` rồi mới đổi controller.
- Ý định canonical do Research lead viết; ý định của main chỉ được lưu như tham chiếu đầu vào
  (`intent_json['sourceRefs']`), không đội lốt canonical.
- `control_view` trả bản đầy đủ cho chủ/bộ điều khiển, bản rút gọn `{runId, state, revision}` cho
  mọi định danh khác — không bao giờ lộ ý định, biên nhận hay lý luận ẩn.

Đây là tầng dữ liệu + luật: không gọi model, không gọi mạng, không tự chạy worker. Người gọi phải
tự xác thực principal trước khi gọi `assign`/`handoff`/`release`; riêng `claim` có actor tường minh
nên tự kiểm quyền và ghi biên nhận. `get` là bản đọc đầy đủ dành cho chủ sở hữu sau khi đã xác
thực; `control_view` mới là bản đọc phân quyền. Không đọc/không trả lý luận ẩn: module chỉ giữ
ý định, biên nhận quyền và biên nhận bàn giao.
"""
from contextlib import contextmanager
import json
import sqlite3
import time
import uuid

from .orchestration_contracts import (
    LIST_MAX, identifier, invalid, object_fields, refs, revision, string_list, text,
)
from .work_policy import digest

RECORD_SCHEMA_VERSION = 1
#: Vòng đời quyền sở hữu: gán → nhận điều khiển → trả tự do. `released` là trạng thái cuối.
OWNERSHIP_STATES = ('assigned', 'active', 'released')
#: Bốn hành động được `authorize` phân xử.
CONTROL_ACTIONS = ('control', 'handoff', 'release', 'read')
#: Trần số biên nhận trả trong `control_view` — view luôn hữu hạn.
CONTROL_VIEW_LIMIT = 50
#: Hai nguồn ý định hợp lệ. Chỉ `research-lead` được viết canonical intent.
INTENT_AUTHORS = ('research-lead', 'main')
CANONICAL_AUTHOR = 'research-lead'
INTENT_TEXT_MAX = 12000
INTENT_SCOPE_MAX = 100
INTENT_SCOPE_ITEM_MAX = 2000
REASON_MAX = 16000

#: Hợp đồng báo cáo cho chuyên gia độc lập. `validate_report` chính là bản thi hành của khung này.
REPORT_SCHEMA = 'boxfox-research-report/1'
REPORT_AUTHOR = CANONICAL_AUTHOR
REPORT_QUESTION_STATES = ('answered', 'partial', 'unresolved', 'blocked')
REPORT_FIELDS = ('schema', 'authoredBy', 'questionState', 'evidenceRefs', 'uncertainty', 'provenance')
REPORT_TEXT_MAX = 8000
REPORT_METHOD_MAX = 400
REPORT_UNCERTAINTY_MAX = 100

#: Bảng + cột bắt buộc. DB cũ thiếu cột ⇒ đóng cửa (`RESEARCH_OWNER_SCHEMA_UNSUPPORTED`), không
#: tự backfill và không ghi `PRAGMA user_version` (DB dùng chung với các module khác).
TABLES = (
    ('harness_research_ownership',
     ('run_id', 'schema_version', 'owner_id', 'controller_id', 'revision', 'intent_json', 'state',
      'created_at', 'updated_at', 'released_at', 'release_reason')),
    ('harness_research_handoffs',
     ('handoff_id', 'run_id', 'from_controller', 'to_controller', 'reason', 'revision', 'created_at')),
    ('harness_research_controls',
     ('control_id', 'run_id', 'actor_id', 'action', 'allowed', 'code', 'reason', 'created_at')),
    ('harness_research_invocations',
     ('run_id', 'invocation_id', 'schema_version', 'request_hash', 'result_json')),
)
# `harness_research_invocations` khoá theo `(run_id, invocation_id)`: mỗi run Research là một
# không gian idempotency riêng; cùng invocation + cùng payload ⇒ replay, khác payload ⇒ xung đột.

SCRIPT = '''
    CREATE TABLE IF NOT EXISTS harness_research_ownership (
        run_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
        owner_id TEXT NOT NULL, controller_id TEXT NOT NULL,
        revision INTEGER NOT NULL, intent_json TEXT NOT NULL,
        state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
        released_at REAL, release_reason TEXT);
    CREATE TABLE IF NOT EXISTS harness_research_handoffs (
        handoff_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES harness_research_ownership(run_id),
        from_controller TEXT NOT NULL, to_controller TEXT NOT NULL, reason TEXT NOT NULL,
        revision INTEGER NOT NULL, created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS harness_research_handoffs_run
        ON harness_research_handoffs(run_id, revision);
    CREATE TABLE IF NOT EXISTS harness_research_controls (
        control_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, actor_id TEXT NOT NULL,
        action TEXT NOT NULL, allowed INTEGER NOT NULL, code TEXT NOT NULL,
        reason TEXT NOT NULL, created_at REAL NOT NULL);
    CREATE INDEX IF NOT EXISTS harness_research_controls_run
        ON harness_research_controls(run_id, created_at);
    CREATE TABLE IF NOT EXISTS harness_research_invocations (
        run_id TEXT NOT NULL, invocation_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
        request_hash TEXT NOT NULL, result_json TEXT NOT NULL,
        PRIMARY KEY(run_id, invocation_id));
'''


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _record_schema(row):
    if type(row['schema_version']) is not int or row['schema_version'] != RECORD_SCHEMA_VERSION:
        invalid('schemaVersion', 'unsupported persisted record schema', 'RESEARCH_OWNER_SCHEMA_UNSUPPORTED')


def _load_intent(row):
    """Đọc `intent_json`; bản ghi hỏng bị đóng cửa như schema không hỗ trợ, không đoán."""
    try:
        state = json.loads(row['intent_json'])
    except ValueError as exc:
        invalid('intentJson', f'corrupt intent record: {exc}', 'RESEARCH_OWNER_SCHEMA_UNSUPPORTED')
    if not isinstance(state, dict):
        invalid('intentJson', 'corrupt intent record', 'RESEARCH_OWNER_SCHEMA_UNSUPPORTED')
    return state


def _empty_intent():
    """Khung ý định rỗng: canonical chưa có (`authoredBy=None`) và chưa có tham chiếu đầu vào."""
    return {'authoredBy': None, 'text': None, 'scope': [], 'intentRevision': None, 'sourceRefs': []}


def _normalize_intent(value):
    """Ý định đầu vào → cấu trúc TẤT ĐỊNH (băm được, chưa gắn dấu thời gian).

    `authoredBy='main'` vẫn hợp lệ ở đây, nhưng người gọi phải lưu nó như tham chiếu đầu vào —
    xem `_store_intent`; nó không bao giờ trở thành canonical.
    """
    intent = object_fields(value, 'intent', ('authoredBy', 'text'), ('scope', 'sourceRefs'))
    if intent['authoredBy'] not in INTENT_AUTHORS:
        invalid('intent.authoredBy', 'expected research-lead or main')
    text(intent['text'], 'intent.text', INTENT_TEXT_MAX)
    scope = string_list(intent.get('scope', []), 'intent.scope', limit=INTENT_SCOPE_MAX,
                        item_limit=INTENT_SCOPE_ITEM_MAX)
    source_refs = refs(intent.get('sourceRefs', []), 'intent.sourceRefs')
    return {'authoredBy': intent['authoredBy'], 'text': intent['text'], 'scope': scope,
            'sourceRefs': source_refs}


def _append_input(state, normalized, now):
    """Ý định của main chỉ vào `sourceRefs`, khử trùng theo băm nội dung; trả True nếu có ghi mới."""
    entry = {'authoredBy': 'main', 'text': normalized['text'], 'scope': list(normalized['scope']),
             'sourceRefs': [dict(item) for item in normalized['sourceRefs']]}
    entry['inputHash'] = digest(entry)
    entry['recordedAt'] = now
    entries = state.setdefault('sourceRefs', [])
    if entry['inputHash'] in {item.get('inputHash') for item in entries}:
        return False
    entries.append(entry)
    return True


def _apply_canonical(state, normalized, expected_revision):
    """Ghi canonical intent; chỉ cho ghi đè khi đã có một lần tăng revision điều khiển ở giữa."""
    if state.get('authoredBy') == CANONICAL_AUTHOR and state.get('intentRevision') == expected_revision:
        invalid('intent', 'canonical intent overwrite requires a control revision bump',
                'RESEARCH_INTENT_CONFLICT')
    state['authoredBy'] = CANONICAL_AUTHOR
    state['text'] = normalized['text']
    state['scope'] = list(normalized['scope'])
    state['intentRevision'] = expected_revision


def _store_intent(state, normalized, expected_revision, now):
    if normalized['authoredBy'] == CANONICAL_AUTHOR:
        _apply_canonical(state, normalized, expected_revision)
        return True
    return _append_input(state, normalized, now)


class ResearchOwnership:
    """Sổ quyền sở hữu run Research trên `SessionStore`; chỉ là dữ liệu + luật, không chạy worker."""

    def __init__(self, store):
        self.store, self.db = store, store.db
        for table, required in TABLES:
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if columns and not set(required) <= columns:
                invalid('schemaVersion', f'{table} does not match the record schema',
                        'RESEARCH_OWNER_SCHEMA_UNSUPPORTED')
        self.db.executescript(SCRIPT)

    @contextmanager
    def _write(self):
        # Khuôn `task_service._write`: một mình thì BEGIN IMMEDIATE; nằm trong giao dịch của người
        # gọi thì chỉ mở savepoint để giữ nguyên tính nguyên tử của người gọi.
        if self.db.in_transaction:
            self.db.execute('SAVEPOINT harness_research_owner_write')
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK TO harness_research_owner_write')
                raise
            finally:
                self.db.execute('RELEASE harness_research_owner_write')
        else:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                yield

    def _cached(self, run_id, invocation_id, request_hash, conflict_code):
        """Replay kết quả cũ theo `invocationId`; cùng mã lệnh khác payload ⇒ mã xung đột."""
        identifier(invocation_id, 'invocationId')
        row = self.db.execute('SELECT * FROM harness_research_invocations WHERE run_id=? AND invocation_id=?',
                              (run_id, invocation_id)).fetchone()
        if row is None:
            return None
        if row['schema_version'] != RECORD_SCHEMA_VERSION:
            invalid('schemaVersion', 'unsupported invocation record schema',
                    'RESEARCH_OWNER_SCHEMA_UNSUPPORTED')
        if row['request_hash'] != request_hash:
            invalid('invocationId', 'invocation reused with a different request', conflict_code)
        return json.loads(row['result_json'])

    def _remember(self, run_id, invocation_id, request_hash, result):
        self.db.execute('INSERT INTO harness_research_invocations VALUES(?,?,?,?,?)',
                        (run_id, invocation_id, RECORD_SCHEMA_VERSION, request_hash, encode(result)))
        return result

    def _row(self, run_id):
        row = self.db.execute('SELECT * FROM harness_research_ownership WHERE run_id=?',
                              (run_id,)).fetchone()
        if row is None:
            invalid('runId', 'unknown research run', 'RESEARCH_OWNERSHIP_UNKNOWN')
        _record_schema(row)
        return row

    def _handoffs(self, run_id):
        rows = self.db.execute('SELECT * FROM harness_research_handoffs WHERE run_id=? '
                               'ORDER BY revision DESC, rowid DESC LIMIT ?',
                               (run_id, CONTROL_VIEW_LIMIT)).fetchall()
        return [{'handoffId': row['handoff_id'], 'runId': row['run_id'],
                 'fromController': row['from_controller'], 'toController': row['to_controller'],
                 'reason': row['reason'], 'revision': row['revision'], 'createdAt': row['created_at']}
                for row in rows]

    def _controls(self, run_id):
        rows = self.db.execute('SELECT * FROM harness_research_controls WHERE run_id=? '
                               'ORDER BY created_at DESC, rowid DESC LIMIT ?',
                               (run_id, CONTROL_VIEW_LIMIT)).fetchall()
        return [{'controlId': row['control_id'], 'runId': row['run_id'], 'actorId': row['actor_id'],
                 'action': row['action'], 'allowed': bool(row['allowed']), 'code': row['code'],
                 'reason': row['reason'], 'createdAt': row['created_at']} for row in rows]

    def _view(self, row):
        return {'schemaVersion': row['schema_version'], 'runId': row['run_id'],
                'ownerId': row['owner_id'], 'controllerId': row['controller_id'],
                'revision': row['revision'], 'state': row['state'],
                'intent': _load_intent(row),
                'handoffs': self._handoffs(row['run_id']), 'controls': self._controls(row['run_id']),
                'createdAt': row['created_at'], 'updatedAt': row['updated_at'],
                'releasedAt': row['released_at'], 'releaseReason': row['release_reason']}

    @staticmethod
    def _check_revision(row, expected_revision):
        revision(expected_revision)
        if row['revision'] != expected_revision:
            invalid('expectedRevision', 'research ownership revision changed',
                    'RESEARCH_REVISION_CONFLICT')

    def assign(self, run_id, owner_id, controller_id, intent, invocation_id):
        """Tạo sổ quyền cho run: owner và controller là hai trường riêng, revision bắt đầu từ 1.

        Idempotent theo `(run_id, invocationId)` + băm yêu cầu; một run chỉ có đúng một sổ quyền,
        nên gán lại (kể cả sau `release`) phải mở run mới.
        """
        identifier(run_id, 'runId')
        identifier(owner_id, 'ownerId')
        identifier(controller_id, 'controllerId')
        identifier(invocation_id, 'invocationId')
        normalized = _normalize_intent(intent)
        request_hash = digest({'action': 'assign', 'runId': run_id, 'ownerId': owner_id,
                               'controllerId': controller_id, 'intent': normalized})
        with self._write():
            cached = self._cached(run_id, invocation_id, request_hash, 'RESEARCH_OWNERSHIP_CONFLICT')
            if cached is not None:
                return cached
            if self.db.execute('SELECT 1 FROM harness_research_ownership WHERE run_id=?',
                               (run_id,)).fetchone() is not None:
                invalid('runId', 'run already has an ownership record', 'RESEARCH_OWNERSHIP_CONFLICT')
            state, now = _empty_intent(), time.time()
            _store_intent(state, normalized, 1, now)
            try:
                self.db.execute('INSERT INTO harness_research_ownership VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                (run_id, RECORD_SCHEMA_VERSION, owner_id, controller_id, 1,
                                 encode(state), 'assigned', now, now, None, None))
            except sqlite3.IntegrityError:
                # Người gọi song song có thể đã ghi cùng run; chỉ replay khi đúng invocation + payload.
                cached = self._cached(run_id, invocation_id, request_hash, 'RESEARCH_OWNERSHIP_CONFLICT')
                if cached is not None:
                    return cached
                invalid('runId', 'run already has an ownership record', 'RESEARCH_OWNERSHIP_CONFLICT')
            return self._remember(run_id, invocation_id, request_hash, self._view(self._row(run_id)))

    def get(self, run_id):
        """Bản đọc đầy đủ (ý định, biên nhận) — người gọi phải tự xác thực principal trước."""
        identifier(run_id, 'runId')
        return self._view(self._row(run_id))

    def authorize(self, run_id, actor_id, action):
        """Phân xử quyền trên run; MỌI quyết định trên run đã biết đều được ghi biên nhận.

        Chỉ `owner_id` và `controller_id` được phép; peer/phiên con dù chung session root cũng
        nhận `RESEARCH_CONTROL_FORBIDDEN`. Run không tồn tại trả `RESEARCH_OWNERSHIP_UNKNOWN`
        (không có sổ để gắn biên nhận) — hàm không ném cho hai ca quyết định này.
        """
        identifier(run_id, 'runId')
        identifier(actor_id, 'actorId')
        if not isinstance(action, str) or action not in CONTROL_ACTIONS:
            invalid('action', 'unsupported research control action', 'RESEARCH_CONTROL_ACTION_UNKNOWN')
        row = self.db.execute('SELECT * FROM harness_research_ownership WHERE run_id=?',
                              (run_id,)).fetchone()
        if row is None:
            return {'allowed': False, 'code': 'RESEARCH_OWNERSHIP_UNKNOWN',
                    'reason': 'unknown research run'}
        _record_schema(row)
        allowed = actor_id in (row['owner_id'], row['controller_id'])
        code = 'RESEARCH_CONTROL_ALLOWED' if allowed else 'RESEARCH_CONTROL_FORBIDDEN'
        reason = ('owner or controller' if allowed
                  else 'actor is neither the research owner nor the controller')
        now = time.time()
        with self._write():
            self.db.execute('INSERT INTO harness_research_controls VALUES(?,?,?,?,?,?,?,?)',
                            ('control-' + uuid.uuid4().hex, run_id, actor_id, action,
                             1 if allowed else 0, code, reason, now))
        return {'allowed': allowed, 'code': code, 'reason': reason}

    def claim(self, run_id, controller_id, expected_revision, invocation_id=None):
        """Chủ hoặc bộ điều khiển hiện tại nhận điều khiển run; revision tăng đúng một nhịp.

        Có actor tường minh nên tự kiểm quyền (`control`) và để lại biên nhận, kể cả khi bị từ chối.
        """
        identifier(run_id, 'runId')
        identifier(controller_id, 'controllerId')
        revision(expected_revision)
        request_hash = digest({'action': 'claim', 'runId': run_id, 'controllerId': controller_id,
                               'expectedRevision': expected_revision})
        if invocation_id is not None:
            cached = self._cached(run_id, invocation_id, request_hash, 'RESEARCH_INVOCATION_CONFLICT')
            if cached is not None:
                return cached
        decision = self.authorize(run_id, controller_id, 'control')
        if not decision['allowed']:
            if decision['code'] == 'RESEARCH_OWNERSHIP_UNKNOWN':
                invalid('runId', decision['reason'], 'RESEARCH_OWNERSHIP_UNKNOWN')
            invalid('controllerId', decision['reason'], 'RESEARCH_CONTROL_FORBIDDEN')
        with self._write():
            row = self._row(run_id)
            self._check_revision(row, expected_revision)
            if row['state'] == 'released':
                invalid('runId', 'released research run cannot be claimed',
                        'RESEARCH_OWNERSHIP_RELEASED')
            now = time.time()
            self.db.execute("UPDATE harness_research_ownership SET controller_id=?, state='active', "
                            'revision=revision+1, updated_at=? WHERE run_id=?',
                            (controller_id, now, run_id))
            result = self._view(self._row(run_id))
            if invocation_id is not None:
                self._remember(run_id, invocation_id, request_hash, result)
            return result

    def handoff(self, run_id, to_controller_id, reason, expected_revision, invocation_id=None):
        """Bàn giao quyền điều khiển: ghi biên nhận bàn giao rồi mới đổi controller, cùng giao dịch.

        Người gọi phải tự `authorize(run_id, actor_id, 'handoff')` trước — hàm này không có tham số
        actor nên không thể tự xác thực. `fromController` trong biên nhận là bộ điều khiển cũ.
        """
        identifier(run_id, 'runId')
        identifier(to_controller_id, 'toControllerId')
        text(reason, 'reason')
        if len(reason) > REASON_MAX:
            invalid('reason', f'reason exceeds {REASON_MAX} characters')
        revision(expected_revision)
        request_hash = digest({'action': 'handoff', 'runId': run_id,
                               'toControllerId': to_controller_id, 'reason': reason,
                               'expectedRevision': expected_revision})
        with self._write():
            if invocation_id is not None:
                cached = self._cached(run_id, invocation_id, request_hash,
                                      'RESEARCH_INVOCATION_CONFLICT')
                if cached is not None:
                    return cached
            row = self._row(run_id)
            self._check_revision(row, expected_revision)
            if row['state'] == 'released':
                invalid('runId', 'released research run cannot be handed off',
                        'RESEARCH_OWNERSHIP_RELEASED')
            now = time.time()
            new_revision = expected_revision + 1
            self.db.execute('INSERT INTO harness_research_handoffs VALUES(?,?,?,?,?,?,?)',
                            ('handoff-' + uuid.uuid4().hex, run_id, row['controller_id'],
                             to_controller_id, reason, new_revision, now))
            self.db.execute("UPDATE harness_research_ownership SET controller_id=?, state='active', "
                            'revision=?, updated_at=? WHERE run_id=?',
                            (to_controller_id, new_revision, now, run_id))
            result = self._view(self._row(run_id))
            if invocation_id is not None:
                self._remember(run_id, invocation_id, request_hash, result)
            return result

    def release(self, run_id, reason, expected_revision, invocation_id=None):
        """Trả tự do run và ghi lý do vào sổ. Đã `released` thì lặp lại trả đúng bản đã ghi.

        Idempotent: lần ghi đầu thắng, lý do cũ được giữ nguyên dù gọi lại bằng lý do khác. Người
        gọi phải tự `authorize(run_id, actor_id, 'release')` trước.
        """
        identifier(run_id, 'runId')
        text(reason, 'reason')
        if len(reason) > REASON_MAX:
            invalid('reason', f'reason exceeds {REASON_MAX} characters')
        revision(expected_revision)
        request_hash = digest({'action': 'release', 'runId': run_id, 'reason': reason,
                               'expectedRevision': expected_revision})
        with self._write():
            if invocation_id is not None:
                cached = self._cached(run_id, invocation_id, request_hash,
                                      'RESEARCH_INVOCATION_CONFLICT')
                if cached is not None:
                    return cached
            row = self._row(run_id)
            if row['state'] == 'released':
                result = self._view(row)
                if invocation_id is not None:
                    self._remember(run_id, invocation_id, request_hash, result)
                return result
            self._check_revision(row, expected_revision)
            now = time.time()
            self.db.execute("UPDATE harness_research_ownership SET state='released', released_at=?, "
                            'release_reason=?, revision=revision+1, updated_at=? WHERE run_id=?',
                            (now, reason, now, run_id))
            result = self._view(self._row(run_id))
            if invocation_id is not None:
                self._remember(run_id, invocation_id, request_hash, result)
            return result

    def record_intent(self, run_id, intent, expected_revision, invocation_id=None):
        """Ghi ý định/scope: canonical thuộc Research lead, ý định của main chỉ là tham chiếu vào.

        Ghi đè canonical mà chưa có nhịp tăng revision điều khiển nào ở giữa ⇒
        `RESEARCH_INTENT_CONFLICT`: đổi ý định phải đi kèm một thay đổi/khẳng định quyền điều khiển.
        Tham chiếu đầu vào của main là phép ghi cộng thêm, khử trùng theo băm, không tăng revision.
        """
        identifier(run_id, 'runId')
        revision(expected_revision)
        normalized = _normalize_intent(intent)
        request_hash = digest({'action': 'record_intent', 'runId': run_id, 'intent': normalized,
                               'expectedRevision': expected_revision})
        with self._write():
            if invocation_id is not None:
                cached = self._cached(run_id, invocation_id, request_hash,
                                      'RESEARCH_INVOCATION_CONFLICT')
                if cached is not None:
                    return cached
            row = self._row(run_id)
            self._check_revision(row, expected_revision)
            if row['state'] == 'released':
                invalid('runId', 'released research run does not accept new intent',
                        'RESEARCH_OWNERSHIP_RELEASED')
            state, now = _load_intent(row), time.time()
            if _store_intent(state, normalized, expected_revision, now):
                self.db.execute('UPDATE harness_research_ownership SET intent_json=?, updated_at=? '
                                'WHERE run_id=?', (encode(state), now, run_id))
            result = self._view(self._row(run_id))
            if invocation_id is not None:
                self._remember(run_id, invocation_id, request_hash, result)
            return result

    def control_view(self, run_id, actor_id):
        """Bản đầy đủ cho chủ/bộ điều khiển; mọi định danh khác chỉ thấy `{runId, state, revision}`.

        Bản rút gọn không chứa ý định, biên nhận hay bất kỳ lý luận ẩn nào — chỉ đủ để theo dõi.
        """
        identifier(run_id, 'runId')
        identifier(actor_id, 'actorId')
        row = self._row(run_id)
        if actor_id not in (row['owner_id'], row['controller_id']):
            return {'runId': row['run_id'], 'state': row['state'], 'revision': row['revision']}
        view = self._view(row)
        return {key: view[key] for key in ('runId', 'ownerId', 'controllerId', 'revision', 'state',
                                           'intent', 'handoffs', 'controls')}


def report_contract():
    """Khung báo cáo mà chuyên gia Research độc lập phải thoả trước khi publish.

    Trả cấu trúc dữ liệu thuần (JSON-serializable) để runtime và kiểm tra đọc chung một nguồn với
    `validate_report`. Khung này mô tả hình dạng bắt buộc, không cấp quyền publish.
    """
    return {
        'schema': REPORT_SCHEMA,
        'authoredBy': REPORT_AUTHOR,
        'required': list(REPORT_FIELDS),
        'additionalFields': False,
        'questionState': {'required': ['status', 'summary'], 'optional': ['questionRef'],
                          'status': list(REPORT_QUESTION_STATES)},
        'evidenceRefs': {'minItems': 1, 'maxItems': LIST_MAX,
                         'item': {'artifactId': 'bounded identifier', 'contentHash': 'sha256 hex',
                                  'version': 'positive integer', 'optional': ['ownerId', 'kind']}},
        'uncertainty': {'maxItems': REPORT_UNCERTAINTY_MAX,
                        'item': {'type': 'text', 'maxLength': REPORT_TEXT_MAX}},
        'provenance': {'required': ['method'], 'optional': ['ownerId', 'controllerId', 'runId']},
        'rejections': {'uncited': 'RESEARCH_REPORT_UNCITED',
                       'authorship': 'RESEARCH_REPORT_AUTHORSHIP'},
    }


def validate_report(payload):
    """Chuẩn hoá báo cáo của chuyên gia; từ chối báo cáo không trích dẫn hoặc do main viết kết luận.

    Trả bản đã cắt khỏi container của người gọi, hoặc ném `ContractError`:
    `RESEARCH_REPORT_UNCITED` (không có tham chiếu bằng chứng), `RESEARCH_REPORT_AUTHORSHIP`
    (không phải Research lead viết), `HARNESS_SCHEMA_UNSUPPORTED` (sai schema), và lỗi hợp đồng
    chung cho trường lạ/vượt trần.
    """
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        invalid('report', 'expected an object with string keys')
    if payload.get('authoredBy') != REPORT_AUTHOR:
        invalid('authoredBy', 'conclusions must be explicitly authored by the research lead',
                'RESEARCH_REPORT_AUTHORSHIP')
    if payload.get('schema') != REPORT_SCHEMA:
        invalid('schema', 'unsupported research report schema', 'HARNESS_SCHEMA_UNSUPPORTED')
    if not isinstance(payload.get('evidenceRefs'), list) or not payload.get('evidenceRefs'):
        invalid('evidenceRefs', 'at least one evidence reference is required',
                'RESEARCH_REPORT_UNCITED')
    object_fields(payload, 'report', REPORT_FIELDS)
    question = object_fields(payload['questionState'], 'questionState', ('status', 'summary'),
                             ('questionRef',))
    if question['status'] not in REPORT_QUESTION_STATES:
        invalid('questionState.status', 'unsupported question state')
    text(question['summary'], 'questionState.summary', REPORT_TEXT_MAX)
    normalized_question = {'status': question['status'], 'summary': question['summary']}
    if 'questionRef' in question:
        identifier(question['questionRef'], 'questionState.questionRef')
        normalized_question['questionRef'] = question['questionRef']
    evidence = refs(payload['evidenceRefs'], 'evidenceRefs')
    uncertainty = string_list(payload['uncertainty'], 'uncertainty', limit=REPORT_UNCERTAINTY_MAX,
                              item_limit=REPORT_TEXT_MAX)
    provenance = object_fields(payload['provenance'], 'provenance', ('method',),
                               ('ownerId', 'controllerId', 'runId'))
    text(provenance['method'], 'provenance.method', REPORT_METHOD_MAX)
    normalized_provenance = {'method': provenance['method']}
    for name in ('ownerId', 'controllerId', 'runId'):
        if name in provenance:
            identifier(provenance[name], 'provenance.' + name)
            normalized_provenance[name] = provenance[name]
    return {'schema': REPORT_SCHEMA, 'authoredBy': REPORT_AUTHOR,
            'questionState': normalized_question, 'evidenceRefs': evidence,
            'uncertainty': list(uncertainty), 'provenance': normalized_provenance}
