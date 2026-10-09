"""Canonical pending cards. Futures are a cache, never durable approval authority."""
from contextlib import contextmanager
import hashlib
import json
import time


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


class DecisionStoreError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


@contextmanager
def write(db):
    # No SessionStore.emit/save here: their context managers commit enclosing transactions.
    if db.in_transaction:
        raise RuntimeError('durable writer requires a clean transaction boundary')
    with db:
        db.execute('BEGIN IMMEDIATE')
        yield


def event(db, sid, kind, payload):
    return db.execute('INSERT INTO events(session_id,kind,payload,created) VALUES(?,?,?,?)',
                      (sid, kind, encode(payload), time.time())).lastrowid


class DecisionStore:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS session_decisions (
                session_id TEXT NOT NULL, decision_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                run_id TEXT, kind TEXT NOT NULL, status TEXT NOT NULL, revision INTEGER NOT NULL,
                request_json TEXT NOT NULL, binding_json TEXT NOT NULL, deadline REAL,
                outcome_json TEXT, created REAL NOT NULL, resolved_at REAL,
                invocation_id TEXT, reply_hash TEXT, reply_json TEXT,
                PRIMARY KEY(session_id,decision_id));
            CREATE INDEX IF NOT EXISTS session_decisions_pending ON session_decisions(session_id,status,decision_id);
        ''')

    @staticmethod
    def view(row):
        if row is None:
            return None
        value = json.loads(row['request_json'])
        value.update(revision=row['revision'], resolved=row['status'] != 'pending',
                     status=row['status'], outcome=json.loads(row['outcome_json']) if row['outcome_json'] else None,
                     binding=json.loads(row['binding_json']), durable=True)
        return value

    def get(self, sid, decision_id):
        return self.view(self.db.execute('SELECT * FROM session_decisions WHERE session_id=? AND decision_id=?',
                                        (sid, decision_id)).fetchone())

    def request(self, record, payload, binding):
        request = {k: v for k, v in record.items() if k != 'future'}
        request.update(payload)
        with write(self.db):
            self.db.execute('INSERT INTO session_decisions '
                            '(session_id,decision_id,schema_version,run_id,kind,status,revision,request_json,'
                            'binding_json,deadline,created) VALUES(?,?,1,?,?,\'pending\',1,?,?,?,?)',
                            (record['sessionId'], record['decisionId'], binding.get('runId'), record['kind'],
                             encode(request), encode(binding), record.get('deadline'), time.time()))
            event(self.db, record['sessionId'], 'decision_requested', payload)
        return self.get(record['sessionId'], record['decisionId'])

    def page(self, sid, state='pending', after=None, limit=20):
        if state not in ('pending', 'all', 'approved', 'answered', 'rejected', 'expired', 'cancelled'):
            raise DecisionStoreError('DECISION_INVALID', 'unknown decision state', 400)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DecisionStoreError('DECISION_INVALID', 'limit must be 1..100', 400)
        where, params = 'session_id=? AND decision_id>?', [sid, after or '']
        if state != 'all':
            where += ' AND status=?'
            params.append(state)
        rows = self.db.execute('SELECT * FROM session_decisions WHERE ' + where + ' ORDER BY decision_id LIMIT ?',
                               (*params, limit + 1)).fetchall()
        items = [self.view(row) for row in rows[:limit]]
        return {'decisions': items, 'hasMore': len(rows) > limit,
                'nextAfter': items[-1]['decisionId'] if items else None}

    def retry(self, sid, did, invocation_id, payload):
        if not invocation_id:
            return None
        row = self.db.execute('SELECT * FROM session_decisions WHERE session_id=? AND decision_id=?',
                              (sid, did)).fetchone()
        if row and row['invocation_id'] == invocation_id:
            if row['reply_hash'] != hashlib.sha256(encode(payload).encode()).hexdigest():
                raise DecisionStoreError('DECISION_INVOCATION_CONFLICT', 'same invocation with different reply')
            return json.loads(row['reply_json'])
        return None

    def settle(self, record, outcome, resolved_event, *, invocation_id=None, reply_payload=None,
               reply=None, expected_revision=None, current_binding=None, side_effect=None):
        sid, did = record['sessionId'], record['decisionId']
        with write(self.db):
            row = self.db.execute('SELECT * FROM session_decisions WHERE session_id=? AND decision_id=?',
                                  (sid, did)).fetchone()
            if row is None:
                raise DecisionStoreError('DECISION_NOT_FOUND', 'decision not found', 404)
            old = self.retry(sid, did, invocation_id, reply_payload)
            if old is not None:
                return old
            if row['status'] != 'pending':
                raise DecisionStoreError('DECISION_ALREADY_RESOLVED', 'decision already answered')
            if expected_revision is not None and expected_revision != row['revision']:
                raise DecisionStoreError('DECISION_STALE', 'decision revision changed')
            binding = json.loads(row['binding_json'])
            if current_binding is not None and binding != current_binding:
                raise DecisionStoreError('DECISION_STALE', 'decision binding changed')
            if row['deadline'] is not None and row['deadline'] <= time.time() and outcome['reason'] == 'user':
                raise DecisionStoreError('DECISION_STALE', 'decision expired')
            if side_effect is not None:
                side_effect(self.db)
            self.db.execute('UPDATE session_decisions SET status=?,revision=revision+1,outcome_json=?,resolved_at=?,'
                            'invocation_id=?,reply_hash=?,reply_json=? WHERE session_id=? AND decision_id=?',
                            (outcome['status'], encode(outcome), time.time(), invocation_id,
                             hashlib.sha256(encode(reply_payload).encode()).hexdigest() if invocation_id else None,
                             encode(reply) if reply is not None else None, sid, did))
            event(self.db, sid, 'decision_resolved', resolved_event)
        return reply

    def bound(self, sid, call_id, binding):
        # Only same dispatch binding, never a new approval for a similar mutation.
        rows = self.db.execute('SELECT * FROM session_decisions WHERE session_id=? '
                               "AND json_extract(request_json,'$.toolCallId')=? ORDER BY created DESC",
                               (sid, call_id))
        for row in rows:
            item = self.view(row)
            if item['binding'] == binding:
                return item
        return None
