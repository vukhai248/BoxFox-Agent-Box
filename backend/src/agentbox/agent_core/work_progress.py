"""Admission history and observable progress; neither a semantic judge nor a budget.

Backend input/evidence hashes ignore invocation, artifact version and child IDs.
Three admissions without new opened evidence stop this branch for a main decision.
New real input permits a fresh owner-clamped turn; lifetime receipts remain intact.
"""
import json
import sqlite3
import time
import uuid

from . import work_policy, work_checks, work_feedback


LIMIT = 3


class Progress:
    def __init__(self, graph):
        self.graph, self.rt, self.db = graph, graph.rt, graph.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_progress (
                id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, run_id TEXT NOT NULL,
                scope TEXT NOT NULL, status TEXT NOT NULL, doc TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS work_progress_scope ON work_progress(scope);
            CREATE INDEX IF NOT EXISTS work_progress_run ON work_progress(run_id);
            CREATE UNIQUE INDEX IF NOT EXISTS work_progress_active ON work_progress(scope)
                WHERE status IN ('reserved','admitted');
        ''')
        self.recover()

    def records(self, run_id=None, scope=None, limit=None):
        where, values = [], []
        for key, value in (('run_id', run_id), ('scope', scope)):
            if value is not None:
                where.append(key + '=?'); values.append(value)
        sql = 'SELECT * FROM work_progress' + (' WHERE ' + ' AND '.join(where) if where else '')
        sql += ' ORDER BY rowid DESC LIMIT ?' if limit else ' ORDER BY rowid'
        rows = self.db.execute(sql, values + ([limit] if limit else [])).fetchall()
        return [json.loads(r['doc']) | {'status': r['status']} for r in (reversed(rows) if limit else rows)]

    def get(self, ident):
        row = self.db.execute('SELECT * FROM work_progress WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('WORK_PROGRESS_UNKNOWN: no backend admission')
        return json.loads(row['doc']) | {'status': row['status']}

    def save(self, doc, status, expected=None):
        sql = 'UPDATE work_progress SET status=?,doc=? WHERE id=?'
        values = [status, json.dumps(doc, ensure_ascii=False), doc['admissionId']]
        if expected:
            sql += ' AND status=?'; values.append(expected)
        return self.db.execute(sql, values).rowcount == 1

    def assignment(self, run, work):
        node = next((n for n in run['nodes'] if n['id'] == work.get('nodeId')), None)
        return {'goal': run['goal'], 'definition': work_policy.digest({k: v for k, v in node.items()
                    if k not in ('id', 'title', 'stages')}) if node else None,
                'decisions': [{'answers': [{k: a.get(k) for k in ('question', 'answer', 'decidedBy', 'note')}
                    for a in r.get('answers', [])]} for r in self.graph.feedback.records(run['runId'])
                    if r.get('answers') and r['status'] not in ('stale', 'cancelled')
                    and (work.get('nodeId') is None or r['binding'].get('nodeId') == work['nodeId'])],
                'interviews': [r.get('answers', []) for r in run.get('interviews', [])]}

    async def reserve(self, owner, work, child_id=None, request=None):
        from .work_graph import enabled
        run = self.graph.resolve(owner, work['runId'])
        if not enabled() or run['status'] in ('paused', 'cancelled', 'rejected', 'shipped'):
            raise ValueError('WORK_PROGRESS_PAUSED: run is stopped, paused or disabled')
        scope = work_policy.digest({'owner': owner, 'run': run['runId'],
            **{k: work.get(k) for k in ('nodeId', 'stage', 'purpose', 'checkKind', 'helperRole', 'lookupQuestion')}})
        inputs = self.assignment(run, work) | {
            'artifacts': work_feedback.input_snapshots(self.graph.feedback, child_id, work),
            'evidence': sorted([{k: v for k, v in p.items() if k != 'sourceSeq'}
                for p in (request or {}).get('evidenceProofs', [])], key=work_policy.digest)}
        if work.get('stage') == 'execute' and work.get('purpose') == 'produce':
            code = await work_checks.snapshot(self.graph, owner)
            if not code:
                raise ValueError('WORK_CODE_SNAPSHOT_REQUIRED: failed code inspection cannot admit a fresh execution turn')
            inputs['codeHash'] = code['hash']
            run = self.graph.resolve(owner, work['runId'])
            if not enabled() or run['status'] in ('paused', 'cancelled', 'rejected', 'shipped'):
                raise ValueError('WORK_PROGRESS_PAUSED: run stopped while reading code')
            if any(inputs[k] != v for k, v in self.assignment(run, work).items()):
                raise ValueError('WORK_PROGRESS_STALE: assignment changed while reading code')
        input_hash = work_policy.digest(inputs)
        history = self.records(scope=scope)
        actual = [r for r in history if r['status'] != 'aborted']
        novel = bool(actual and input_hash not in {r['inputHash'] for r in actual})
        previous = actual[-1] if actual else None
        if previous and previous['status'] in ('reserved', 'admitted'):
            raise ValueError('WORK_PROGRESS_BUSY: this assignment already has an active admission')
        if previous and previous['status'] in ('finished', 'interrupted') and previous.get('blocked') and not novel:
            raise ValueError('WORK_NO_PROGRESS: inspect saved admissions; main must change evidence/input or strategy')
        ident = 'wa-' + uuid.uuid4().hex
        doc = {'admissionId': ident, 'ownerId': owner, 'runId': run['runId'], 'scope': scope,
            'work': {k: work.get(k) for k in ('nodeId', 'stage', 'purpose', 'checkKind', 'helperRole', 'lookupQuestion')},
            'assignmentHash': work_policy.digest(self.assignment(run, work)),
            'inputHash': input_hash, 'novelInput': novel, 'createdAt': time.time(),
            'streakBefore': 0 if novel or not previous else previous.get('streak', 0),
            'streak': 0 if novel or not previous else previous.get('streak', 0)}
        try:
            with self.db:
                # The partial unique index also arbitrates separate SQLite workers.
                self.db.execute('INSERT INTO work_progress VALUES(?,?,?,?,?,?)',
                    (ident, owner, run['runId'], scope, 'reserved', json.dumps(doc, ensure_ascii=False)))
        except sqlite3.IntegrityError as exc:
            raise ValueError('WORK_PROGRESS_BUSY: another worker won this assignment') from exc
        return ident

    def attach(self, ident, owner, work, child_id):
        doc = self.get(ident)
        if doc['status'] != 'reserved' or doc['ownerId'] != owner or doc['runId'] != work['runId']:
            raise ValueError('WORK_PROGRESS_SCOPE: admission does not belong to this assignment')
        if any(doc['work'].get(k) != work.get(k) for k in doc['work']):
            raise ValueError('WORK_PROGRESS_SCOPE: assignment changed')
        child = self.rt.store.get(child_id)
        if child.get('parent_id') != owner:
            raise PermissionError('WORK_PROGRESS_SCOPE: child belongs to another owner')
        doc.update(childId=child_id, admissionSeq=work.get('admissionSeq', 0), admittedAt=time.time())
        with self.db:
            won = self.save(doc, 'admitted', expected='reserved')
        if not won:
            raise ValueError('WORK_PROGRESS_BUSY: admission stopped or claimed by another worker')

    def finish(self, ident, result=None, output='', *, interrupted=False):
        doc = self.get(ident)
        if doc['status'] not in ('reserved', 'admitted'):
            return doc  # duplicate/late callback cannot overwrite Stop or recovery
        cid = doc.get('childId')
        started = bool(cid and self.db.execute(
            "SELECT 1 FROM events WHERE session_id=? AND seq>? AND kind='user' LIMIT 1",
            (cid, doc['admissionSeq'])).fetchone())
        if not started:
            with self.db:
                self.save(doc | {'finishedAt': time.time()}, 'aborted', expected=doc['status'])
            return self.get(ident)
        history = self.records(scope=doc['scope'])
        children = {r['childId'] for r in history if r.get('childId')}
        self_refs = set()
        for row in self.db.execute('SELECT metadata FROM work_artifacts').fetchall():
            meta = json.loads(row['metadata'])
            if (meta.get('producerId') in children or meta['binding'].get('checkpoint')
                    or meta['binding'].get('purpose') == 'check_inputs'):
                self_refs.update((meta['path'].replace('\\', '/').removeprefix('./'), 'artifact:' + meta['artifactId']))
        node = next((n for n in self.graph.current(doc['runId'])['nodes'] if n['id'] == doc['work'].get('nodeId')), {})
        commands = {'command:' + c.strip() for c in node.get('tests', [])}
        def original(proof):
            ref = proof['ref'].replace('\\', '/').removeprefix('./')
            return (not any(ref == p or ref.endswith('/' + p) for p in self_refs)
                    and (proof['kind'] != 'terminal_exec' or proof['ref'] in commands))
        proofs = [{k: v for k, v in p.items() if k != 'sourceSeq'} for p in
                  self.graph.feedback.opened(cid, cid) if p['sourceSeq'] > doc['admissionSeq'] and original(p)]
        proof_hashes = sorted({work_policy.digest(p) for p in proofs})
        seen = {p for r in history if r['admissionId'] != ident
                for p in r.get('proofHashes', [])}
        progressed = bool(set(proof_hashes) - seen)
        result = result or {}
        waiting = result.get('status') == 'needs_user'
        streak = 0 if progressed else doc['streakBefore'] + (0 if waiting else 1)
        steps, tokens = self.rt.store.child_usage_from_events(cid)
        doc.update(finishedAt=time.time(), proofHashes=proof_hashes, newProofs=len(set(proof_hashes)-seen),
            progressed=progressed, streak=streak, blocked=interrupted or streak >= LIMIT,
            outcome={'status': result.get('status', 'interrupted'),
                'reason': str(result.get('reason') or result.get('last_error') or '')[:1000],
                'outputHash': work_policy.digest(output.strip()), 'outputChars': len(output),
                'lifetimeStepsUsed': steps, 'lifetimeOutputTokens': tokens},
            errors=[{'tool': e.get('name'), 'code': str((e.get('result') or {}).get('errorCode') or
                     (e.get('result') or {}).get('code') or (e.get('result') or {}).get('error') or '')[:500]}
                    for e in work_checks.observations(self.graph, cid, after=doc['admissionSeq'])
                    if isinstance(e.get('result'), dict) and e['result'].get('is_error')])
        with self.db:
            won = self.save(doc, 'interrupted' if interrupted else 'finished', expected=doc['status'])
        if won and doc['blocked']:
            self.rt.store.emit(doc['ownerId'], 'work_notice', {'type': 'main_decision_required',
                'event': 'progress_stopped', 'runId': doc['runId'], 'admissionId': ident,
                'childId': cid, 'streak': streak, 'reason': 'WORK_ADMISSION_INTERRUPTED' if interrupted else 'WORK_NO_PROGRESS'})
        return self.get(ident)

    def blocked(self, run_id=None):
        sql = ("SELECT * FROM work_progress WHERE rowid IN (SELECT MAX(rowid) FROM work_progress "
               "WHERE status!='aborted' GROUP BY scope) AND status IN ('finished','interrupted') "
               "AND json_extract(doc,'$.blocked')=1")
        rows = self.db.execute(sql + (' AND run_id=?' if run_id else ''), (run_id,) if run_id else ()).fetchall()
        return [json.loads(r['doc']) | {'status': r['status']} for r in rows]

    def valid(self, doc):
        run = self.graph.resolve(doc['ownerId'], doc['runId'])
        return (self.get(doc['admissionId'])['status'] in ('finished', 'interrupted')
                and any(d['admissionId'] == doc['admissionId'] for d in self.blocked(run['runId']))
                and work_policy.digest(self.assignment(run, doc['work'])) == doc['assignmentHash'])

    def recover(self):
        for doc in self.records():
            if doc['status'] in ('reserved', 'admitted'):
                # A real start without a canonical graph completion is uncertain,
                # even if a finish event exists; do not replay its possible effects.
                self.finish(doc['admissionId'], interrupted=True)

    def cancel(self, owner):
        with self.db:
            self.db.execute("UPDATE work_progress SET status='cancelled' WHERE owner_id=? "
                            "AND status IN ('reserved','admitted','finished','interrupted')", (owner,))
