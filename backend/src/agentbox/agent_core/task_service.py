"""Durable task data atop SessionStore; never an execution or permission engine.

Callers must gate root/controller/peer principals and admission externally. The
mandatory resolver returns canonical {'runId': ..., 'sessionId': ...} (the Work
Graph shape); merely supplying an owner or controller ID confers no authority.
Reads never reconcile, authorize refs, grant rights, or accept deliverables.
Only explicit projection reads children, whose existing closer remains sole
owner of execution state. A resumed legacy child may reuse its session ID.

Contract for callers: `_write` serializes check-and-write only when it owns the
transaction. A caller that is already inside a transaction must hold a write lock
(`BEGIN IMMEDIATE`); otherwise a concurrent commit surfaces as `SQLITE_BUSY`, not
as a canonical conflict code.
"""
from contextlib import contextmanager
import json
import sqlite3
import time
import uuid

from .orchestration_contracts import (
    MESSAGE_KINDS, TASK_STATES, TaskContract, identifier, invalid, refs, revision, text,
)
from .work_policy import digest

RECORD_SCHEMA_VERSION = 1
PAGE_LIMIT = 100
# An ACTIVE attempt blocks a new one: `running`, or a parked-open `waiting_input` row without a
# `closed_at` (child still started, waiting for input). A projected `needs_user` snapshot has
# `closed_at` set, so it stops blocking and a legacy resume supersedes it with a fresh attempt
# (same session ID, new started stamp). `ATTEMPT_OPEN` = rows a projection may still update.
ATTEMPT_OPEN = ('running', 'waiting_input')
CHILD_OUTCOMES = {'completed': 'succeeded', 'partial': 'partial', 'failed': 'failed',
                  'interrupted': 'interrupted', 'cancelled': 'cancelled',
                  'needs_user': 'waiting_input'}


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def schema(row):
    if type(row['schema_version']) is not int or row['schema_version'] != RECORD_SCHEMA_VERSION:
        invalid('schemaVersion', 'unsupported persisted record schema', 'TASK_SCHEMA_UNSUPPORTED')


def page_args(after, limit):
    if type(limit) is not int or not 1 <= limit <= PAGE_LIMIT:
        invalid('limit', f'expected an integer between 1 and {PAGE_LIMIT}')
    if after is not None:
        identifier(after, 'after')
    return after or '', limit


class TaskService:
    def __init__(self, store, resolve_run):
        if not callable(resolve_run):
            raise TypeError('resolve_run(owner_id, run_id) is mandatory')
        self.store, self.db, self.resolve_run = store, store.db, resolve_run
        for table, required in (
                ('harness_tasks', ('task_key', 'schema_version', 'run_id', 'owner_id', 'task_alias', 'revision')),
                ('harness_task_attempts', ('attempt_id', 'schema_version', 'task_key', 'session_id',
                                           'attempt_seq', 'admission_id', 'status')),
                ('harness_task_messages', ('message_id', 'schema_version', 'task_key', 'request_hash')),
                ('harness_invocations', ('owner_id', 'invocation_id', 'schema_version', 'request_hash'))):
            columns = {row['name'] for row in self.db.execute(f'PRAGMA table_info({table})')}
            if columns and not set(required) <= columns:
                invalid('schemaVersion', f'{table} does not match the record schema', 'TASK_SCHEMA_UNSUPPORTED')
        # No global user_version and no backfill/recovery of any legacy record.
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS harness_tasks (
                task_key TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                run_id TEXT NOT NULL, owner_id TEXT NOT NULL, controller_id TEXT NOT NULL,
                task_alias TEXT NOT NULL, revision INTEGER NOT NULL,
                contract_hash TEXT NOT NULL, contract_json TEXT NOT NULL,
                state TEXT NOT NULL, acceptance_state TEXT NOT NULL,
                control_state TEXT, abandoned_at REAL, abandon_reason TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(run_id, task_alias));
            CREATE INDEX IF NOT EXISTS harness_tasks_run ON harness_tasks(owner_id,run_id,task_key);
            CREATE TABLE IF NOT EXISTS harness_task_attempts (
                attempt_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL,
                task_key TEXT NOT NULL REFERENCES harness_tasks(task_key),
                session_id TEXT NOT NULL, attempt_seq INTEGER NOT NULL,
                admission_id TEXT NOT NULL UNIQUE, capability_epoch INTEGER NOT NULL,
                contract_hash TEXT NOT NULL, task_revision INTEGER NOT NULL,
                status TEXT NOT NULL, reason TEXT, result_refs_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL, started_at REAL NOT NULL, closed_at REAL,
                UNIQUE(session_id, attempt_seq));
            CREATE UNIQUE INDEX IF NOT EXISTS harness_task_active ON harness_task_attempts(task_key)
                WHERE status='running' OR (status='waiting_input' AND closed_at IS NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS harness_session_active ON harness_task_attempts(session_id)
                WHERE status='running' OR (status='waiting_input' AND closed_at IS NULL);
            CREATE TABLE IF NOT EXISTS harness_task_messages (
                message_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                task_key TEXT NOT NULL REFERENCES harness_tasks(task_key), sender_id TEXT NOT NULL,
                expected_revision INTEGER NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL,
                request_hash TEXT NOT NULL, delivery_state TEXT NOT NULL,
                received_at REAL NOT NULL, consumed_at REAL,
                PRIMARY KEY(task_key,message_id));
            CREATE TABLE IF NOT EXISTS harness_invocations (
                owner_id TEXT NOT NULL, invocation_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                run_id TEXT NOT NULL, request_hash TEXT NOT NULL, result_json TEXT NOT NULL,
                PRIMARY KEY(owner_id,invocation_id));
        ''')
        # These two tables first shipped in this change, so a stale predicate from an earlier
        # build is refreshed here instead of silently keeping the parked-attempt dead end.
        # The active predicate must still cover a parked-open attempt (`waiting_input` with no
        # `closed_at`); only a projected `needs_user` snapshot stops blocking a new attempt.
        for name, table in (('harness_task_active', 'task_key'),
                            ('harness_session_active', 'session_id')):
            row = self.db.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                                  (name,)).fetchone()
            if row is None or 'closed_at' in (row['sql'] or ''):
                continue
            with self.db:
                self.db.execute(f'DROP INDEX IF EXISTS {name}')
                self.db.execute(f'CREATE UNIQUE INDEX {name} ON harness_task_attempts({table}) '
                                "WHERE status='running' OR (status='waiting_input' AND closed_at IS NULL)")

    @contextmanager
    def _write(self):
        # Serialize check-and-write across SQLite connections, including dedupe and expected
        # revision. Inside a caller's transaction a savepoint keeps the caller's atomicity but
        # takes no new write lock: such callers must already hold it (BEGIN IMMEDIATE), because
        # a concurrent commit is then resolved by the constraint re-check, not by the lock.
        # Never commit a caller's enclosing transaction.
        if self.db.in_transaction:
            self.db.execute('SAVEPOINT harness_task_write')
            try:
                yield
            except BaseException:
                self.db.execute('ROLLBACK TO harness_task_write')
                raise
            finally:
                self.db.execute('RELEASE harness_task_write')
        else:
            with self.db:
                self.db.execute('BEGIN IMMEDIATE')
                yield

    def _run(self, owner_id, run_id):
        identifier(owner_id, 'ownerId')
        identifier(run_id, 'runId')
        run = self.resolve_run(owner_id, run_id)
        if not isinstance(run, dict) or run.get('runId') != run_id:
            invalid('runId', 'canonical run required', 'TASK_RUN_UNKNOWN')
        if run.get('sessionId') != owner_id:
            invalid('ownerId', 'canonical run belongs to another owner', 'TASK_OWNER_MISMATCH')
        return run

    def _task(self, owner_id, run_id, task_key):
        identifier(task_key, 'taskKey')
        row = self.db.execute('SELECT * FROM harness_tasks WHERE task_key=?', (task_key,)).fetchone()
        if row is None:
            invalid('taskKey', 'unknown task', 'TASK_UNKNOWN')
        if row['owner_id'] != owner_id or row['run_id'] != run_id:
            invalid('taskKey', 'task belongs to another owner/run', 'TASK_OWNER_MISMATCH')
        schema(row)
        contract = TaskContract.parse(json.loads(row['contract_json']))
        if (contract.contract_hash != row['contract_hash']
                or contract.payload['taskId'] != row['task_alias']):
            invalid('contractHash', 'persisted immutable contract mismatch', 'TASK_CONTRACT_CORRUPT')
        return row

    @staticmethod
    def _view(row, *, contract=False):
        result = {'schemaVersion': row['schema_version'], 'taskKey': row['task_key'],
                  'runId': row['run_id'], 'ownerId': row['owner_id'], 'controllerId': row['controller_id'],
                  'taskId': row['task_alias'], 'revision': row['revision'],
                  'contractHash': row['contract_hash'], 'state': row['state'],
                  'acceptanceState': row['acceptance_state'], 'controlState': row['control_state'],
                  'abandonedAt': row['abandoned_at'], 'abandonReason': row['abandon_reason'],
                  'createdAt': row['created_at'], 'updatedAt': row['updated_at']}
        if contract:
            result['contract'] = json.loads(row['contract_json'])
        return result

    @staticmethod
    def _expected(row, expected_revision):
        revision(expected_revision)
        if row['revision'] != expected_revision:
            invalid('expectedRevision', 'task revision changed', 'TASK_REVISION_CONFLICT')

    def _cached(self, owner_id, run_id, invocation_id, request_hash):
        identifier(invocation_id, 'invocationId')
        row = self.db.execute('SELECT * FROM harness_invocations WHERE owner_id=? AND invocation_id=?',
                              (owner_id, invocation_id)).fetchone()
        if row is None:
            return None
        schema(row)
        if row['request_hash'] != request_hash or row['run_id'] != run_id:
            invalid('invocationId', 'invocation reused with different request', 'TASK_INVOCATION_CONFLICT')
        result = json.loads(row['result_json'])
        self._task(owner_id, run_id, result['taskKey'])
        if 'attemptId' in result:
            record = self.db.execute('SELECT * FROM harness_task_attempts WHERE attempt_id=?',
                                     (result['attemptId'],)).fetchone()
            if record is None:
                invalid('attemptId', 'missing invocation result', 'TASK_RECORD_CORRUPT')
            schema(record)
        if 'messageId' in result:
            record = self.db.execute('SELECT * FROM harness_task_messages WHERE task_key=? AND message_id=?',
                                     (result['taskKey'], result['messageId'])).fetchone()
            if record is None:
                invalid('messageId', 'missing invocation result', 'TASK_RECORD_CORRUPT')
            schema(record)
        return result

    def _remember(self, owner_id, run_id, invocation_id, request_hash, result):
        self.db.execute('INSERT INTO harness_invocations VALUES(?,?,?,?,?,?)',
                        (owner_id, invocation_id, RECORD_SCHEMA_VERSION, run_id, request_hash, encode(result)))
        return result

    def create(self, owner_id, run_id, request, *, controller_id):
        self._run(owner_id, run_id)
        identifier(controller_id, 'controllerId')
        contract = TaskContract.parse(request)
        payload = contract.payload
        invocation = payload['invocationId']
        request_hash = digest({'action': 'create', 'runId': run_id, 'ownerId': owner_id,
                               'controllerId': controller_id, 'contract': payload})
        with self._write():
            cached = self._cached(owner_id, run_id, invocation, request_hash)
            if cached is not None:
                return cached
            key, now = 'task-' + uuid.uuid4().hex, time.time()
            try:
                self.db.execute('''INSERT INTO harness_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                                (key, RECORD_SCHEMA_VERSION, run_id, owner_id, controller_id, payload['taskId'],
                                 1, contract.contract_hash, contract.payload_json, 'queued', 'unverified',
                                 None, None, None, now, now))
            except sqlite3.IntegrityError:
                # A concurrent caller may have committed this invocation; replay its receipt
                # instead of misreporting an alias conflict.
                cached = self._cached(owner_id, run_id, invocation, request_hash)
                if cached is not None:
                    return cached
                invalid('taskId', 'alias already exists in this run', 'TASK_ALIAS_CONFLICT')
            result = self._view(self._task(owner_id, run_id, key), contract=True)
            return self._remember(owner_id, run_id, invocation, request_hash, result)

    def get(self, owner_id, run_id, task_key):
        self._run(owner_id, run_id)
        return self._view(self._task(owner_id, run_id, task_key), contract=True)

    def list(self, owner_id, run_id, *, after=None, limit=20, state=None):
        self._run(owner_id, run_id)
        after, limit = page_args(after, limit)
        if state is not None and (not isinstance(state, str) or state not in TASK_STATES):
            invalid('state', 'unknown task state')
        sql = 'SELECT task_key FROM harness_tasks WHERE owner_id=? AND run_id=? AND task_key>?'
        args = [owner_id, run_id, after]
        if state is not None:
            sql += ' AND state=?'
            args.append(state)
        rows = self.db.execute(sql + ' ORDER BY task_key LIMIT ?', (*args, limit + 1)).fetchall()
        items = [self._view(self._task(owner_id, run_id, r['task_key'])) for r in rows[:limit]]
        return {'items': items, 'hasMore': len(rows) > limit,
                'nextAfter': items[-1]['taskKey'] if items else None}

    def send(self, owner_id, run_id, task_key, *, invocation_id, message_id, sender_id,
             expected_revision, kind, body, input_refs=None):
        self._run(owner_id, run_id)
        identifier(message_id, 'messageId')
        identifier(sender_id, 'senderId')
        revision(expected_revision)
        if not isinstance(kind, str) or kind not in MESSAGE_KINDS:
            invalid('kind', 'unsupported task message kind')
        text(body, 'body')
        if len(body) > 16000:
            invalid('body', 'message exceeds 16000 characters')
        inputs = refs([] if input_refs is None else input_refs, 'inputRefs')
        if len(inputs) > PAGE_LIMIT:
            invalid('inputRefs', 'too many references')
        payload = {'body': body, 'inputRefs': inputs}
        identity = {'action': 'send', 'runId': run_id, 'taskKey': task_key, 'messageId': message_id,
                    'senderId': sender_id, 'expectedRevision': expected_revision, 'kind': kind, 'payload': payload}
        request_hash = digest(identity)
        with self._write():
            task = self._task(owner_id, run_id, task_key)
            old = self.db.execute('SELECT * FROM harness_task_messages WHERE task_key=? AND message_id=?',
                                  (task_key, message_id)).fetchone()
            if old is not None:
                schema(old)
            cached = self._cached(owner_id, run_id, invocation_id, request_hash)
            if cached is not None:
                return cached
            if old is not None:
                if old['request_hash'] != request_hash:
                    invalid('messageId', 'message ID reused with different payload', 'TASK_MESSAGE_CONFLICT')
                result = self._message_view(old)
            else:
                self._expected(task, expected_revision)
                try:
                    self.db.execute('INSERT INTO harness_task_messages VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                                    (message_id, RECORD_SCHEMA_VERSION, task_key, sender_id, expected_revision,
                                     kind, encode(payload), request_hash, 'received', time.time(), None))
                except sqlite3.IntegrityError:
                    # A concurrent caller may have committed this message ID; the row is the
                    # authority, so replay it when the payload matches and reject a mismatch.
                    old = self.db.execute('SELECT * FROM harness_task_messages WHERE task_key=? AND message_id=?',
                                          (task_key, message_id)).fetchone()
                    if old is None:
                        raise
                    schema(old)
                    if old['request_hash'] != request_hash:
                        invalid('messageId', 'message ID reused with different payload', 'TASK_MESSAGE_CONFLICT')
                result = self._message_view(self.db.execute(
                    'SELECT * FROM harness_task_messages WHERE task_key=? AND message_id=?',
                    (task_key, message_id)).fetchone())
            return self._remember(owner_id, run_id, invocation_id, request_hash, result)

    @staticmethod
    def _message_view(row):
        schema(row)
        return {'schemaVersion': row['schema_version'], 'taskKey': row['task_key'],
                'messageId': row['message_id'], 'senderId': row['sender_id'],
                'expectedRevision': row['expected_revision'], 'kind': row['kind'],
                'payload': json.loads(row['payload_json']), 'deliveryState': row['delivery_state'],
                'receivedAt': row['received_at'], 'consumedAt': row['consumed_at']}

    def messages(self, owner_id, run_id, task_key, *, after=None, limit=20):
        self._run(owner_id, run_id)
        self._task(owner_id, run_id, task_key)
        after, limit = page_args(after, limit)
        rows = self.db.execute('SELECT * FROM harness_task_messages WHERE task_key=? AND message_id>? '
                               'ORDER BY message_id LIMIT ?', (task_key, after, limit + 1)).fetchall()
        items = [self._message_view(row) for row in rows[:limit]]
        return {'items': items, 'hasMore': len(rows) > limit,
                'nextAfter': items[-1]['messageId'] if items else None}

    def abandon(self, owner_id, run_id, task_key, *, invocation_id, expected_revision, reason):
        self._run(owner_id, run_id)
        revision(expected_revision)
        text(reason, 'reason')
        if len(reason) > 16000:
            invalid('reason', 'reason exceeds 16000 characters')
        request_hash = digest({'action': 'abandon', 'runId': run_id, 'taskKey': task_key,
                               'expectedRevision': expected_revision, 'reason': reason})
        with self._write():
            task = self._task(owner_id, run_id, task_key)
            cached = self._cached(owner_id, run_id, invocation_id, request_hash)
            if cached is not None:
                return cached
            self._expected(task, expected_revision)
            if task['abandoned_at'] is not None:
                invalid('taskKey', 'task already abandoned', 'TASK_ABANDONED')
            active = self.db.execute('SELECT * FROM harness_task_attempts WHERE task_key=? '
                                     'AND status IN (?,?) AND closed_at IS NULL',
                                     (task_key, *ATTEMPT_OPEN)).fetchone()
            if active is not None:
                schema(active)
            now = time.time()
            self.db.execute("UPDATE harness_tasks SET state='abandoned', abandoned_at=?, abandon_reason=?, "
                            'control_state=?, revision=revision+1, updated_at=? WHERE task_key=?',
                            (now, reason, 'cancel_requested' if active else None, now, task_key))
            result = self._view(self._task(owner_id, run_id, task_key))
            return self._remember(owner_id, run_id, invocation_id, request_hash, result)

    def _child(self, task, session_id):
        identifier(session_id, 'sessionId')
        child = self.store.child(session_id)
        if child is None:
            invalid('sessionId', 'canonical child required', 'TASK_CHILD_UNKNOWN')
        role = json.loads(task['contract_json'])['role']
        if child['parent_id'] != task['owner_id'] or child['role'] != role:
            invalid('sessionId', 'child owner/role mismatch', 'TASK_CHILD_BINDING')
        return child

    @staticmethod
    def _attempt_view(row):
        schema(row)
        return {'schemaVersion': row['schema_version'], 'taskKey': row['task_key'],
                'attemptId': row['attempt_id'], 'sessionId': row['session_id'], 'attemptSeq': row['attempt_seq'],
                'admissionId': row['admission_id'], 'capabilityEpoch': row['capability_epoch'],
                'contractHash': row['contract_hash'], 'taskRevision': row['task_revision'],
                'status': row['status'], 'reason': row['reason'], 'resultRefs': json.loads(row['result_refs_json']),
                'provenance': json.loads(row['provenance_json']),
                'startedAt': row['started_at'], 'closedAt': row['closed_at']}

    def record_attempt(self, owner_id, run_id, task_key, *, invocation_id, expected_revision,
                       session_id, admission_id, capability_epoch):
        """Record an already-admitted canonical child, not permission to start it."""
        self._run(owner_id, run_id)
        identifier(admission_id, 'admissionId')
        revision(expected_revision)
        if type(capability_epoch) is not int or capability_epoch < 1:
            invalid('capabilityEpoch', 'expected a positive integer, not a boolean')
        request_hash = digest({'action': 'record_attempt', 'runId': run_id, 'taskKey': task_key,
                               'expectedRevision': expected_revision, 'sessionId': session_id,
                               'admissionId': admission_id, 'capabilityEpoch': capability_epoch})
        with self._write():
            task = self._task(owner_id, run_id, task_key)
            child = self._child(task, session_id)
            cached = self._cached(owner_id, run_id, invocation_id, request_hash)
            if cached is not None:
                return cached
            self._expected(task, expected_revision)
            if task['abandoned_at'] is not None:
                invalid('taskKey', 'abandoned tasks cannot admit follow-ups', 'TASK_ABANDONED')
            if child['status'] != 'started' or child['finished'] is not None:
                invalid('sessionId', 'new attempt requires an open canonical child', 'TASK_CHILD_NOT_ACTIVE')
            previous = self.db.execute('SELECT * FROM harness_task_attempts WHERE session_id=? '
                                       'ORDER BY attempt_seq DESC LIMIT 1', (session_id,)).fetchone()
            if previous is not None:
                schema(previous)
                if previous['started_at'] == child['started']:
                    invalid('sessionId', 'canonical child has not reopened', 'TASK_ATTEMPT_BINDING')
            seq = previous['attempt_seq'] + 1 if previous else 1
            attempt_id = 'attempt-' + uuid.uuid4().hex
            provenance = {'source': 'children', 'parentId': child['parent_id'], 'role': child['role'],
                          'parentTurn': child['parent_turn'], 'spawnStep': child['spawn_step'],
                          'startedAt': child['started'], 'admissionId': admission_id}
            try:
                self.db.execute('INSERT INTO harness_task_attempts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                                (attempt_id, RECORD_SCHEMA_VERSION, task_key, session_id, seq, admission_id,
                                 capability_epoch, task['contract_hash'], task['revision'], 'running', None,
                                 '[]', encode(provenance), child['started'], None))
            except sqlite3.IntegrityError:
                cached = self._cached(owner_id, run_id, invocation_id, request_hash)
                if cached is not None:
                    return cached
                invalid('admissionId', 'active attempt or admission reuse', 'TASK_ATTEMPT_CONFLICT')
            self.db.execute("UPDATE harness_tasks SET state='running', revision=revision+1, updated_at=? "
                            'WHERE task_key=?', (time.time(), task_key))
            result = self._attempt_view(self.db.execute('SELECT * FROM harness_task_attempts WHERE attempt_id=?',
                                                       (attempt_id,)).fetchone())
            return self._remember(owner_id, run_id, invocation_id, request_hash, result)

    def attempts(self, owner_id, run_id, task_key, *, after=None, limit=20):
        self._run(owner_id, run_id)
        task = self._task(owner_id, run_id, task_key)
        after, limit = page_args(after, limit)
        rows = self.db.execute('SELECT * FROM harness_task_attempts WHERE task_key=? AND attempt_id>? '
                               'ORDER BY attempt_id LIMIT ?', (task_key, after, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            self._child(task, row['session_id'])
            items.append(self._attempt_view(row))
        return {'items': items, 'hasMore': len(rows) > limit,
                'nextAfter': items[-1]['attemptId'] if items else None}

    def project_attempt(self, owner_id, run_id, task_key, attempt_id, *, result_refs=None):
        """Explicit, idempotent child projection. Does not close/reopen the child.

        A `needs_user` close is a closed `waiting_input` snapshot (`closed_at` set); the legacy
        resume reopens the same child with a new started stamp and supersedes it with a fresh
        attempt. Closed snapshots stay immutable even after the canonical session is reused; a
        parked child (`waiting_since` set, still started) keeps its row open. Unknown/missing
        execution receipts fail closed, never accepted.
        """
        self._run(owner_id, run_id)
        identifier(attempt_id, 'attemptId')
        with self._write():
            task = self._task(owner_id, run_id, task_key)
            row = self.db.execute('SELECT * FROM harness_task_attempts WHERE attempt_id=? AND task_key=?',
                                  (attempt_id, task_key)).fetchone()
            if row is None:
                invalid('attemptId', 'unknown task attempt', 'TASK_ATTEMPT_UNKNOWN')
            schema(row)
            child = self._child(task, row['session_id'])
            inputs = refs(result_refs, 'resultRefs') if result_refs is not None else json.loads(row['result_refs_json'])
            if len(inputs) > PAGE_LIMIT:
                invalid('resultRefs', 'too many references')
            if row['status'] not in ATTEMPT_OPEN or row['closed_at'] is not None:
                # A closed snapshot (including a projected `needs_user` park) is immutable: a
                # legacy resume supersedes it with a fresh attempt, never by rewriting this row.
                if inputs != json.loads(row['result_refs_json']):
                    invalid('resultRefs', 'closed attempt snapshot is immutable', 'TASK_ATTEMPT_CLOSED')
                return self._attempt_view(row)
            if row['started_at'] != child['started']:
                invalid('sessionId', 'canonical child was reopened without closing projection', 'TASK_ATTEMPT_BINDING')
            if child['status'] == 'started':
                status = 'waiting_input' if child['waiting_since'] is not None else 'running'
                if inputs:
                    invalid('resultRefs', 'terminal child receipt required', 'TASK_CHILD_NOT_TERMINAL')
            else:
                status = CHILD_OUTCOMES.get(child['status'])
                if status is None or child['finished'] is None:
                    invalid('status', 'unsupported or incomplete child close receipt', 'TASK_CHILD_NOT_TERMINAL')
            # A resumed child keeps the previous close reason; never show it on an open attempt.
            reason = child['reason'] if child['status'] != 'started' else None
            result_json = encode(inputs)
            if (row['status'], row['reason'], row['result_refs_json'], row['closed_at']) == (
                    status, reason, result_json, child['finished']):
                return self._attempt_view(row)
            self.db.execute('UPDATE harness_task_attempts SET status=?, reason=?, result_refs_json=?, closed_at=? '
                            'WHERE attempt_id=?', (status, reason, result_json, child['finished'], attempt_id))
            if task['abandoned_at'] is None:
                self.db.execute('UPDATE harness_tasks SET state=?, revision=revision+1, updated_at=? WHERE task_key=?',
                                (status, time.time(), task_key))
            else:
                self.db.execute('UPDATE harness_tasks SET revision=revision+1, updated_at=? WHERE task_key=?',
                                (time.time(), task_key))
            return self._attempt_view(self.db.execute('SELECT * FROM harness_task_attempts WHERE attempt_id=?',
                                                      (attempt_id,)).fetchone())
