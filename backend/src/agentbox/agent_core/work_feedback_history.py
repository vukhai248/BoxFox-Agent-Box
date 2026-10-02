"""Transactional interview events and recovery from recorded user actions.

These helpers never commit. The request, receipt, outbox and transcript share
their caller's SQLite transaction; no model output or elapsed time is consent.
"""
import json
import math
import time


class CardHistory:
    def __init__(self, feedback):
        self.feedback, self.db = feedback, feedback.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_card_events (
                owner_id TEXT NOT NULL, kind TEXT NOT NULL, decision_id TEXT NOT NULL,
                seq INTEGER NOT NULL, PRIMARY KEY(owner_id,kind,decision_id));
        ''')

    def event(self, owner, kind, payload, after=0):
        """Insert without committing, deduplicating only the same logical event."""
        decision = payload.get('decisionId')
        if decision:
            wanted = {k: v for k, v in payload.items() if k != 'resolvedAt'}
            cached = self.db.execute('SELECT e.seq,e.payload FROM work_card_events c JOIN events e ON e.seq=c.seq '
                'WHERE c.owner_id=? AND c.kind=? AND c.decision_id=? AND e.session_id=? AND e.kind=? AND e.seq>?',
                (owner, kind, decision, owner, kind, after)).fetchone()
            if cached and all(json.loads(cached['payload']).get(k) == v for k, v in wanted.items()):
                return cached['seq']
            rows = self.db.execute(
                "SELECT seq,payload FROM events WHERE session_id=? AND kind=? AND seq>? "
                "AND json_extract(payload,'$.decisionId')=? ORDER BY seq DESC",
                (owner, kind, after, decision)).fetchall()
            seq = next((row['seq'] for row in rows if all(
                json.loads(row['payload']).get(k) == v for k, v in wanted.items())), None)
        else:
            seq = None
        if seq is None:
            seq = self.db.execute('INSERT INTO events(session_id,kind,payload,created) VALUES(?,?,?,?)',
                (owner, kind, json.dumps(payload, ensure_ascii=False), time.time())).lastrowid
        if decision:
            self.db.execute('INSERT INTO work_card_events VALUES(?,?,?,?) '
                'ON CONFLICT(owner_id,kind,decision_id) DO UPDATE SET seq=excluded.seq',
                (owner, kind, decision, seq))
        return seq

    def record(self, doc, kind, payload):
        """Keep exact backend-authored event payloads with the request itself."""
        history = doc.setdefault('cardHistory', [])
        old = next((e for e in history if e['kind'] == kind and
                    e['payload']['decisionId'] == payload['decisionId']), None)
        if old is None:
            history.append({'kind': kind, 'payload': json.loads(json.dumps(payload))})
        elif old['payload'] != payload:
            raise ValueError('WORK_CARD_HISTORY_CONFLICT: logical card event changed')
        self.flush(doc)

    def flush(self, doc):
        seq = 0
        for entry in doc.get('cardHistory', []):
            seq = self.event(doc['ownerId'], entry['kind'], entry['payload'], after=seq)

    def legacy(self, doc):
        """Recover answer rounds only when both receipt and user provenance agree."""
        receipts = []
        questions = {q['id'] for q in doc['questions']}
        saved = doc['answers']
        for row in self.db.execute('SELECT result FROM work_feedback_invocations WHERE owner_id=? ORDER BY rowid',
                                   (doc['ownerId'],)):
            try:
                result = json.loads(row['result'])
            except (ValueError, TypeError):
                continue
            if (not isinstance(result, dict) or result.get('requestId') != doc['requestId'] or result.get('status') != 'resolved'
                    or result.get('outcome') != 'answered' or result.get('choice') not in ('submit', 'decide')):
                continue
            try:
                rid, revision = result['decisionId'].rsplit('-r', 1)
                revision = int(revision)
                answers = result['answers']
                valid = (rid == doc['requestId'] and revision > 0 and
                    result['revision'] == revision + 1 and isinstance(answers, list) and bool(answers))
                ids = set()
                for value in answers:
                    stamp = value.get('confirmedAt')
                    valid = valid and (value in saved and value.get('questionId') in questions and
                        value.get('questionId') not in ids and value.get('source') == 'user_action' and
                        value.get('requestRevision') == revision and isinstance(stamp, (int, float)) and
                        not isinstance(stamp, bool) and math.isfinite(stamp) and stamp > 0)
                    ids.add(value.get('questionId'))
                if valid:
                    receipts.append((revision, result))
            except (KeyError, TypeError, AttributeError, ValueError):
                continue
        history, prior, next_revision = [], [], 1
        rounds = {}
        for revision, result in receipts:
            if revision in rounds and rounds[revision] != result:
                rounds[revision] = None  # Conflicting receipts cannot confirm a round.
            elif revision not in rounds:
                rounds[revision] = result
        for revision, result in sorted(rounds.items()):
            if revision != next_revision or result is None:
                break
            ids = {a['questionId'] for a in prior}
            new_ids = {a['questionId'] for a in result['answers']}
            if ids & new_ids or result.get('remaining') != (len(ids | new_ids) < len(questions)):
                break
            card = self.feedback.card(doc | {'revision': revision, 'answers': prior})
            history.extend([
                {'kind': 'decision_requested', 'payload': card},
                {'kind': 'decision_resolved', 'payload': card | result | {
                    'status': 'answered', 'resolved': True, 'reason': 'user',
                    'resolvedAt': max(a['confirmedAt'] for a in result['answers'])}}])
            prior = prior + result['answers']
            next_revision += 1
        if doc['status'] == 'needs_user' and doc['revision'] == next_revision and saved == prior:
            history.append({'kind': 'decision_requested', 'payload': self.feedback.card(doc)})
        # Closing an existing pending card is not answering it. Don't fabricate
        # a publication for an ungranted waiting_main request or invent a round.
        if doc['status'] in ('cancelled', 'stale'):
            closed = {e['payload']['decisionId'] for e in history if e['kind'] == 'decision_resolved'}
            rows = self.db.execute("SELECT payload FROM events WHERE session_id=? AND kind='decision_requested' "
                "AND json_extract(payload,'$.workRequestId')=? ORDER BY seq", (doc['ownerId'], doc['requestId']))
            for row in rows:
                card = json.loads(row['payload'])
                if card['decisionId'] in closed:
                    continue
                history.extend([{'kind': 'decision_requested', 'payload': card},
                    {'kind': 'decision_resolved', 'payload': card | {'status': 'cancelled', 'resolved': True,
                        'outcome': 'cancelled', 'reason': 'assignment_changed' if doc['status'] == 'stale' else 'session_cancelled',
                        'choice': None, 'resolvedAt': time.time()}}])
                closed.add(card['decisionId'])
        return history

    def reconcile(self, doc):
        with self.db:
            if 'cardHistory' not in doc:
                history = self.legacy(doc)
                if history:
                    doc['cardHistory'] = history
                    self.feedback.save(doc)
            self.flush(doc)

    def recover(self):
        # Called before controller recovery, so it uses persisted records only.
        for row in self.db.execute('SELECT doc FROM work_requests ORDER BY rowid').fetchall():
            self.reconcile(json.loads(row['doc']))
