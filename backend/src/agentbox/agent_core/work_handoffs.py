"""Explicit root assignments and durable handoff receipts, driven by the run controller.

Notifications do not require acknowledgement or a main model turn. No assignment
is inferred from a role, and an interrupted admission is never replayed blindly.
"""
import json
import time
import uuid

from . import work_policy


CHECK_IDS = {'tests', 'code_review', 'plan_review', 'design_review', 'evidence', 'critique'}
CLOSED = {'cancelled', 'shipped', 'rejected', 'paused'}


class Handoffs:
    def __init__(self, graph):
        self.graph, self.db = graph, graph.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS work_handoffs (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner_id TEXT NOT NULL, doc TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS work_handoff_invocations (
                owner_id TEXT NOT NULL, invocation TEXT NOT NULL, request_hash TEXT NOT NULL,
                result TEXT NOT NULL, PRIMARY KEY(owner_id,invocation));
            CREATE TABLE IF NOT EXISTS work_handoff_actions (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL, owner_id TEXT NOT NULL,
                status TEXT NOT NULL, doc TEXT NOT NULL);
        ''')
        # A process owns no old admission. Claimed-before-admission is safe to
        # retry; admitted might have run tools, so main must inspect it first.
        with self.db:
            self.db.execute("UPDATE work_handoff_actions SET status='pending' WHERE status='claimed'")
            self.db.execute("UPDATE work_handoff_actions SET status='interrupted' WHERE status='admitted'")

    def records(self, run_id):
        return [json.loads(r['doc']) for r in self.db.execute(
            'SELECT doc FROM work_handoffs WHERE run_id=? ORDER BY rowid', (run_id,))]

    def actions(self, run_id=None, pending=False):
        return [dict(r) for r in self.db.execute('SELECT * FROM work_handoff_actions ORDER BY rowid')
                if (not pending or r['status'] == 'pending') and (run_id is None or r['run_id'] == run_id)]

    @staticmethod
    def nodes(run, assignment):
        source = next((n for n in run['nodes'] if n['id'] == assignment['nodeId']), None)
        target = assignment['target']
        dest = next((n for n in run['nodes'] if n['id'] == target.get('nodeId')), None)
        if not source or assignment['stage'] not in source['stages']:
            raise ValueError('WORK_HANDOFF_SCOPE: source node/stage missing')
        if target['kind'] == 'node' and (not dest or target['stage'] not in dest['stages']):
            raise ValueError('WORK_HANDOFF_SCOPE: target node/stage missing')
        return source, dest

    def scope(self, run, assignment):
        source, dest = self.nodes(run, assignment)
        return work_policy.digest({'goal': run['goal'], 'source': work_policy.definition(source),
            'stage': assignment['stage'], 'target': assignment['target'],
            'targetDefinition': work_policy.definition(dest) if dest else None,
            'predicate': assignment['predicate']})

    def valid(self, run, assignment):
        try:
            return assignment['status'] == 'active' and assignment['scopeHash'] == self.scope(run, assignment)
        except (KeyError, ValueError):
            return False

    def action(self, session, args):
        if session.get('parent_id') or session['role'] != 'orchestrator':
            raise PermissionError('WORK_ROOT_ONLY: only main assigns handoffs')
        run = self.graph.current(self.graph.resolve(session['id'], args.get('runId'))['runId'])
        invocation = args.get('invocationId')
        if not isinstance(invocation, str) or not 1 <= len(invocation) <= 120:
            raise ValueError('WORK_HANDOFF_INVOCATION: invocationId required (1..120 chars)')
        digest = work_policy.digest(args)
        old = self.db.execute('SELECT * FROM work_handoff_invocations WHERE owner_id=? AND invocation=?',
                              (session['id'], invocation)).fetchone()
        if old:
            if old['request_hash'] != digest:
                raise ValueError('WORK_HANDOFF_INVOCATION_CONFLICT: invocation reused with different assignment')
            return json.loads(old['result'])
        if run['status'] in CLOSED:
            raise ValueError('WORK_RUN_CLOSED: cannot assign handoff on closed/paused run')
        if args['action'] == 'assign_handoff':
            if isinstance(args.get('revision'), bool) or args.get('revision') != run['revision']:
                raise ValueError(f'WORK_HANDOFF_REVISION_CONFLICT: current run revision is {run["revision"]}')
            target = args.get('target')
            predicate = args.get('predicate')
            if not isinstance(target, dict) or target.get('kind') not in ('check', 'node'):
                raise ValueError('WORK_HANDOFF_TARGET: choose check or existing node')
            if target['kind'] == 'check':
                ids = target.get('checkIds')
                if (set(target) != {'kind', 'checkIds'} or not isinstance(ids, list) or not ids
                        or any(not isinstance(i, str) for i in ids) or len(ids) != len(set(ids))
                        or not set(ids) <= CHECK_IDS or predicate not in ('artifact_finalized', 'code_snapshot_ready')):
                    raise ValueError('WORK_HANDOFF_TARGET: checkIds and artifact/code readiness predicate required')
                target = {'kind': 'check', 'checkIds': sorted(ids)}
            else:
                if set(target) != {'kind', 'nodeId', 'stage'} or predicate != 'required_checks_passed':
                    raise ValueError('WORK_HANDOFF_TARGET: node requires nodeId/stage and required_checks_passed')
            doc = {'transitionId': 'h-' + uuid.uuid4().hex, 'ownerId': session['id'], 'runId': run['runId'],
                'nodeId': args.get('nodeId'), 'stage': args.get('stage', 'produce'),
                'predicate': predicate, 'target': target, 'revision': 1, 'status': 'active', 'createdAt': time.time()}
            source, dest = self.nodes(run, doc)
            if predicate == 'code_snapshot_ready' and doc['stage'] != 'execute':
                raise ValueError('WORK_HANDOFF_PREDICATE: code readiness requires execute source')
            if dest:
                from .work_graph import gate_stage
                if dest['id'] == source['id'] or source['id'] not in dest['dependsOn'] or gate_stage(dest, source, target['stage']) != doc['stage']:
                    raise ValueError('WORK_HANDOFF_DEPENDENCY: target must consume the declared source stage through a DAG edge')
                if target['stage'] == 'execute':
                    self.graph.require_execution(run)  # assigning does not confer approval
            # Do not stack identical active permissions and accidentally double work.
            doc['scopeHash'] = self.scope(run, doc)
            if any(self.valid(run, h) and h['scopeHash'] == doc['scopeHash'] for h in self.records(run['runId'])):
                raise ValueError('WORK_HANDOFF_EXISTS: matching assignment already active')
        elif args['action'] == 'revoke_handoff':
            row = self.db.execute('SELECT doc FROM work_handoffs WHERE id=? AND owner_id=? AND run_id=?',
                                  (args.get('transitionId'), session['id'], run['runId'])).fetchone()
            if not row:
                raise ValueError('WORK_HANDOFF_UNKNOWN: assignment not owned by this run')
            doc = json.loads(row['doc'])
            if isinstance(args.get('revision'), bool) or args.get('revision') != doc['revision']:
                raise ValueError('WORK_HANDOFF_REVISION_CONFLICT: use assignment revision')
            doc.update(status='revoked', revision=doc['revision'] + 1)
        else:
            raise ValueError('WORK_HANDOFF_ACTION: assign_handoff or revoke_handoff required')
        encoded = json.dumps(doc, ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT INTO work_handoffs VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET doc=excluded.doc',
                            (doc['transitionId'], run['runId'], session['id'], encoded))
            self.db.execute('INSERT INTO work_handoff_invocations VALUES(?,?,?,?)', (session['id'], invocation, digest, encoded))
        self.graph.save(run, 'handoff_' + doc['status'], doc['transitionId'])
        if doc['status'] == 'revoked':
            self.graph.continuations.revoke_handoff(doc['transitionId'])
        return doc

    def eligible(self, run, assignment):
        if run['status'] in CLOSED or not self.valid(run, assignment):
            return None
        source, dest = self.nodes(run, assignment)
        state = source['stages'][assignment['stage']]
        meta = state.get('artifact')
        if (not meta or meta['status'] != 'finalized'
                or state['status'] not in ('needs_checks', 'accepted', 'revise')):
            return None
        if assignment['predicate'] == 'code_snapshot_ready' and not meta['binding'].get('codeSnapshot'):
            return None
        if dest:
            from .work_graph import ready_nodes
            if state['status'] != 'accepted' or not self.graph.checks.valid(run, source, assignment['stage']):
                return None
            if dest not in ready_nodes(run, assignment['target']['stage']) or dest['stages'][assignment['target']['stage']]['status'] != 'pending':
                return None  # repairs/retasking require a separate main decision
        return source, dest, meta

    def enqueue(self, run):
        """Called within the same transaction as the durable run state change."""
        for assignment in self.records(run['runId']):
            value = self.eligible(run, assignment)
            if not value:
                continue
            source, dest, meta = value
            identity = {'owner': run['sessionId'], 'run': run['runId'], 'scope': assignment['scopeHash'],
                'artifact': {k: meta[k] for k in ('artifactId', 'version', 'contentHash', 'binding')},
                'policyHash': source['stages'][assignment['stage']].get('policy', {}).get('hash'),
                'targetInput': self.graph.checks.binding(run, dest, assignment['target']['stage']) if dest else None}
            aid = 'handoff-' + work_policy.digest(identity)
            doc = {'action': 'handoff', 'actionId': aid, 'transitionId': assignment['transitionId'],
                'runId': run['runId'], 'ownerId': run['sessionId'], 'nodeId': source['id'], 'stage': assignment['stage'],
                'target': assignment['target'], 'predicate': assignment['predicate'], 'input': identity,
                'artifact': {k: meta[k] for k in ('artifactId', 'version', 'contentHash', 'path')}, 'createdAt': time.time()}
            self.db.execute('INSERT OR IGNORE INTO work_handoff_actions VALUES(?,?,?,?,?)',
                            (aid, run['runId'], run['sessionId'], 'pending', json.dumps(doc, ensure_ascii=False)))

    def notify(self, row, status=None, error=None):
        doc = json.loads(row['doc'])
        status = status or row['status']
        receipt = row['id'] + ':' + status
        if not self.db.execute("SELECT 1 FROM events WHERE session_id=? AND kind='work_notice' AND json_extract(payload,'$.noticeId')=?",
                               (row['owner_id'], receipt)).fetchone():
            self.graph.store.emit(row['owner_id'], 'work_notice', {'noticeId': receipt,
                'type': 'main_decision_required' if status in ('blocked', 'interrupted') else 'notification',
                'event': 'handoff_' + status, 'workKey': row['id'], 'runId': row['run_id'],
                'artifact': doc['artifact'], 'target': doc['target'], 'error': str(error) if error else doc.get('error')})

    def dispatch(self, run_id=None):
        from .work_graph import enabled
        if not enabled():
            return
        # Reconcile a committed assignment if the process died before the next
        # run save/enqueue. This only materializes ready refs; it starts no work.
        ids = [run_id] if run_id else [r[0] for r in self.db.execute('SELECT DISTINCT run_id FROM work_handoffs')]
        for rid in ids:
            with self.db:
                self.enqueue(self.graph.current(rid))
        for row in self.actions(run_id):
            self.notify(row)
            if row['status'] == 'pending':
                self.graph.continuations.kick(row)

    def finish(self, row, status, error=None):
        current = self.db.execute('SELECT status,doc FROM work_handoff_actions WHERE id=?', (row['id'],)).fetchone()
        if current['status'] in ('completed', 'blocked', 'interrupted'):
            return  # stop/revoke/recovery receipt cannot be overwritten by a late callback
        doc = json.loads(current['doc'])
        doc.update(finishedAt=time.time())
        if error:
            doc['error'] = str(error)[:1000]
        with self.db:
            self.db.execute('UPDATE work_handoff_actions SET status=?,doc=? WHERE id=?',
                            (status, json.dumps(doc, ensure_ascii=False), row['id']))
        self.notify(row | {'doc': json.dumps(doc)}, status, error)

    def inspect(self, row, run):
        doc = json.loads(row['doc'])
        assignment = next((h for h in self.records(row['run_id']) if h['transitionId'] == doc['transitionId']), None)
        if not assignment or not self.valid(run, assignment):
            raise ValueError('WORK_HANDOFF_STALE: main revoked or changed assignment scope')
        if run['status'] in CLOSED:
            return None
        value = self.eligible(run, assignment)
        if not value:
            raise ValueError('WORK_HANDOFF_NOT_READY: input/target no longer ready; main must reassess')
        source, dest, meta = value
        registered, _ = self.graph.artifacts.get(run['runId'], meta['artifactId'])
        if registered != meta or any(meta[k] != doc['input']['artifact'][k] for k in ('artifactId', 'version', 'contentHash', 'binding')):
            raise ValueError('WORK_HANDOFF_STALE: immutable artifact input changed')
        binding = self.graph.checks.binding(run, source, doc['stage'])
        if any(meta['binding'].get(k) != v for k, v in binding.items()):
            raise ValueError('WORK_HANDOFF_STALE: source decisions/dependencies changed')
        if dest and self.graph.checks.binding(run, dest, doc['target']['stage']) != doc['input']['targetInput']:
            raise ValueError('WORK_HANDOFF_STALE: target input changed')
        return doc, source, dest, meta

    def claim(self, row):
        doc = json.loads(row['doc']) | {'claimedAt': time.time(), 'leaseUntil': time.time() + 60}
        with self.db:
            return self.db.execute("UPDATE work_handoff_actions SET status='claimed',doc=? WHERE id=? AND status='pending'",
                                   (json.dumps(doc, ensure_ascii=False), row['id'])).rowcount == 1

    async def execute(self, row, session, run):
        import asyncio
        from . import work_checks
        controller = self.graph.continuations
        try:
            value = self.inspect(row, run)
            if not value:
                return
            doc, source, dest, meta = value
            snapshot = meta['binding'].get('codeSnapshot')
            if snapshot and await work_checks.snapshot(self.graph, run['sessionId']) != snapshot:
                raise ValueError('WORK_HANDOFF_STALE: code snapshot changed before admission')
            # Revocation/stop may occur during the snapshot read.
            if not self.inspect(row, run):
                self.finish(row, 'blocked', 'WORK_HANDOFF_PAUSED: main must resume this assignment')
                return
            if dest and doc['target']['stage'] == 'execute':
                self.graph.require_execution(run)
                self.graph.require_planning_current(run)
                await self.graph.require_code_current(run)
                if run['status'] not in ('approved', 'executing', 'executed'):
                    raise ValueError('WORK_APPROVAL_REQUIRED: assignment is not execution approval')
            with self.db:
                admitted = self.db.execute("UPDATE work_handoff_actions SET status='admitted' WHERE id=? AND status='claimed'", (row['id'],)).rowcount
            if not admitted:
                return
            controller.admissions[row['id']] = {'task': asyncio.current_task(), 'owner': run['sessionId'],
                'runId': run['runId'], 'nodeId': dest['id'] if dest else source['id'],
                'stage': doc['target']['stage'] if dest else doc['stage'], 'purpose': 'produce' if dest else 'review', 'children': set()}
            if dest:
                result = await self.graph.run_stage(session, run, dest, doc['target']['stage'], 3,
                                                   controller_action=row['id'])
                ok = result in ('accepted', 'needs_checks', 'needs_user')
            else:
                # A manual/checker admission may already have judged these exact
                # inputs while this action queued. Red/error is a decision, not
                # permission for auto dispatch to start another judgment.
                latest = self.graph.checks.latest(run, source, doc['stage'])
                existing = [latest[c] for c in doc['target']['checkIds'] if c in latest]
                if any(c['status'] != 'pass' for c in existing):
                    self.finish(row, 'blocked', 'Current input already has a non-pass check; main must explicitly select retry, repair or investigation.')
                    return
                result = await self.graph.checks.start_locked(session, run, {'nodeId': source['id'], 'stage': doc['stage'],
                    'artifactId': meta['artifactId'], 'checkIds': doc['target']['checkIds'], 'invocationId': row['id']}, controller_action=row['id'])
                ok = bool(result.get('checks')) and all(c['status'] == 'pass' for c in result['checks'])
            self.finish(row, 'completed' if ok else 'blocked', None if ok else 'Assigned check/producer did not pass; main must select repair or investigation.')
        except asyncio.CancelledError:
            self.finish(row, 'interrupted', 'Admission stopped; inspect saved child and effects before retry.')
            raise
        except Exception as exc:
            self.finish(row, 'blocked', exc)
        finally:
            admission = controller.admissions.pop(row['id'], None)
            if admission:
                controller.children.difference_update(admission['children'])
