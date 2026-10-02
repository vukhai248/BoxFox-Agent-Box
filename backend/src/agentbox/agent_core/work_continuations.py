"""Run-owned continuation of a specifically granted, durable checkpoint.

Notifications do not open a model turn. The active scheduler consumes ready
requests in its live run; otherwise a worker takes the same run lock. No role
pipeline or implementation permission is implied by an interview grant.
"""
import asyncio
import json
import time

from .work_feedback import FeedbackError


class Continuations:
    def __init__(self, graph):
        self.graph, self.rt, self.db = graph, graph.rt, graph.db
        self.tasks = {}
        self.wakes = {}
        self.schedulers = {}
        self.children = set()
        self.admissions = {}  # backend action -> active task/scope; never a model flag
        # A claim with no child admission is safe to retry. Once an admission
        # may have started, retain an interrupted receipt, never replay tools.
        for row in self.db.execute("SELECT * FROM work_feedback_outbox WHERE status='claimed'").fetchall():
            doc = graph.feedback.get(row['request_id'])
            admitted = doc['status'] in ('resuming', 'interrupted', 'consumed')
            with self.db:
                self.db.execute('UPDATE work_feedback_outbox SET status=? WHERE id=?',
                                ('interrupted' if admitted else 'pending', row['id']))

    def wake(self, run_id):
        self.wakes.setdefault(run_id, asyncio.Event()).set()

    def rows(self, run_id=None):
        rows = self.db.execute("SELECT * FROM work_feedback_outbox WHERE status='pending' ORDER BY rowid").fetchall()
        return [r for r in rows if json.loads(r['doc']).get('action') == 'resume_child'
                and (run_id is None or json.loads(r['doc']).get('runId') == run_id)]

    def authorized(self, doc, run):
        from . import work_graph
        if not work_graph.enabled() or run['status'] == 'paused':
            raise FeedbackError('WORK_CONTINUATION_PAUSED', 'continuation is disabled or paused')
        grant = next((g for g in self.graph.grants.records(run['runId'])
                      if g['grantId'] == doc.get('grantId')), None)
        if (not grant or not grant['resumeOnAnswers']
                or not self.graph.grants.valid(grant, run, doc['binding'])
                or not set(doc.get('decisionKeys') or []) <= set(grant['decisionKeys'])):
            raise FeedbackError('WORK_CONTINUATION_RIGHTS', 'main must decide: continuation grant is missing, revoked or stale')
        return grant

    def inspect(self, row):
        from . import work_graph
        if not work_graph.enabled():
            return None
        doc = self.graph.feedback.get(row['request_id'], row['owner_id'])
        if doc['status'] in ('consumed', 'resuming'):
            self.finish(row['id'], 'superseded')  # manual admission already won
            return None
        run = self.graph.feedback.validate(doc)
        if doc['status'] != 'ready':
            raise FeedbackError('WORK_REQUEST_NOT_READY', 'saved answers are not ready for continuation')
        if run['status'] == 'paused':
            return None
        self.authorized(doc, run)
        b = doc['binding']
        node = next((n for n in run['nodes'] if n['id'] == b.get('nodeId')), None)
        if b['purpose'] != 'produce' or not node:
            # Answers affect the producer's decision binding. A checker may not
            # bless the old immutable artifact after that input changes.
            raise FeedbackError('WORK_CHECK_INPUT_CHANGED', 'main must reassess the artifact and check binding after this decision')
        state = node['stages'][b['stage']]
        if state.get('requestId') != doc['requestId'] or state['status'] not in ('needs_user', 'pending'):
            if state['status'] == 'running':
                return None  # original admission is still yielding
            raise FeedbackError('WORK_CONTINUATION_STATE', 'checkpoint is no longer the current stage')
        if b['stage'] == 'execute':
            self.graph.require_execution(run)
            self.graph.require_planning_current(run)
            if run['status'] not in ('approved', 'executing', 'executed'):
                raise FeedbackError('WORK_APPROVAL_REQUIRED', 'continuation does not confer execution approval')
        elif run['status'] in ('approved', 'executing', 'executed', 'execute_failed'):
            raise FeedbackError('WORK_PHASE_INVALID', 'main must reassess planning after execution approval')
        return doc, run, node

    def claim(self, row):
        payload = json.loads(row['doc']) | {'claimedAt': time.time()}
        with self.db:
            result = self.db.execute("UPDATE work_feedback_outbox SET status='claimed',doc=? WHERE id=? AND status='pending'",
                                     (json.dumps(payload, ensure_ascii=False), row['id']))
        return result.rowcount == 1

    def finish(self, oid, status, error=None):
        row = self.db.execute('SELECT * FROM work_feedback_outbox WHERE id=?', (oid,)).fetchone()
        if not row or row['status'] in ('cancelled', 'completed', 'blocked', 'interrupted', 'superseded'):
            return
        payload = json.loads(row['doc']) | {'finishedAt': time.time()}
        if error:
            payload['error'] = str(error)[:1000]
        with self.db:
            self.db.execute('UPDATE work_feedback_outbox SET status=?,doc=? WHERE id=?',
                            (status, json.dumps(payload, ensure_ascii=False), oid))
        self.rt.store.emit(row['owner_id'], 'work_notice', {
            'type': 'main_decision_required' if status in ('blocked', 'interrupted') else 'notification',
            'event': 'continuation_' + status, 'workKey': oid, 'requestId': row['request_id'],
            'runId': payload.get('runId'), 'error': payload.get('error')})

    def owns_child(self, child_id):
        return child_id in self.children

    def authorize_new(self, owner, work):
        """Validate real controller ownership before slot creation/start, including after waits."""
        action = self.admissions.get(work.get('controllerAction'))
        task = asyncio.current_task()
        scope = action if action and action['task'] is task else (action or {}).get('helpers', {}).get(task)
        if not action or not scope or action['owner'] != owner:
            raise PermissionError('WORK_CONTROLLER_RIGHTS: no active backend admission')
        if any(scope[k] != work.get(k) for k in ('runId', 'nodeId', 'stage', 'purpose')):
            raise PermissionError('WORK_CONTROLLER_RIGHTS: action scope mismatch')
        if scope.get('helperRole') and scope['helperRole'] != work.get('helperRole'):
            raise PermissionError('WORK_CONTROLLER_RIGHTS: helper role mismatch')
        run = self.graph.current(action['runId'])
        if action.get('requestId'):
            row = self.db.execute('SELECT * FROM work_feedback_outbox WHERE id=?', (work['controllerAction'],)).fetchone()
            request = self.graph.feedback.get(action['requestId'])
            if not row or row['status'] != 'claimed' or request['status'] not in ('ready', 'resuming', 'consumed'):
                raise PermissionError('WORK_CONTROLLER_RIGHTS: answer admission no longer active')
            self.graph.feedback.validate(request)
            self.authorized(request, run)
            if work['stage'] == 'execute':
                self.graph.require_execution(run)
                self.graph.require_planning_current(run)
                if run['status'] not in ('approved', 'executing', 'executed'):
                    raise PermissionError('WORK_CONTROLLER_RIGHTS: answer is not execution approval')
            return action
        row = self.db.execute('SELECT * FROM work_handoff_actions WHERE id=?', (work['controllerAction'],)).fetchone()
        transition = json.loads(row['doc'])['transitionId'] if row else None
        assignment = next((h for h in self.graph.handoffs.records(run['runId']) if h['transitionId'] == transition), None)
        if (not row or row['status'] != 'admitted' or run['status'] in ('paused', 'cancelled', 'shipped', 'rejected')
                or not assignment or not self.graph.handoffs.valid(run, assignment)):
            raise PermissionError('WORK_CONTROLLER_RIGHTS: admission stopped, revoked or stale')
        return action

    def helper_task(self, owner, action_id, role, operation):
        """Only the owning producer task may register a bounded research/explore task."""
        action = self.admissions.get(action_id) or {}
        base = {k: action.get(k) for k in ('runId', 'nodeId', 'stage', 'purpose')}
        self.authorize_new(owner, base | {'controllerAction': action_id})
        if action.get('task') is not asyncio.current_task() or base['purpose'] != 'produce' or role not in ('research', 'explore'):
            raise PermissionError('WORK_CONTROLLER_RIGHTS: helper must belong to the active producer')
        scope = base | {'purpose': 'knowledge', 'helperRole': role}

        async def execute():
            task = asyncio.current_task()
            action.setdefault('helpers', {})[task] = scope
            try:
                self.authorize_new(owner, scope | {'controllerAction': action_id})
                return await operation()
            finally:
                action['helpers'].pop(task, None)
        return asyncio.create_task(execute())

    def register_new(self, owner, work, child_id):
        action = self.authorize_new(owner, work)
        action['children'].add(child_id)
        self.children.add(child_id)

    async def after_slot(self, owner, work):
        action = self.authorize_new(owner, work)
        row = self.db.execute('SELECT doc FROM work_handoff_actions WHERE id=?', (work['controllerAction'],)).fetchone()
        source = (action.get('codeSnapshot') if action.get('requestId') else
                  json.loads(row['doc'])['input']['artifact']['binding'].get('codeSnapshot'))
        if source:
            from .work_checks import snapshot_of
            if await snapshot_of(self.graph, owner, source) != source:
                raise ValueError('WORK_HANDOFF_STALE: code changed while queued for a child slot')
        self.authorize_new(owner, work)

    async def execute(self, row, session, run, node):
        doc = self.graph.feedback.get(row['request_id'])
        self.authorized(doc, run)
        self.children.add(doc['childId'])
        self.admissions[row['id']] = {'task': asyncio.current_task(), 'owner': run['sessionId'],
            'runId': run['runId'], 'nodeId': node['id'], 'stage': doc['binding']['stage'],
            'purpose': 'produce', 'requestId': doc['requestId'], 'children': {doc['childId']}}
        try:
            state = node['stages'][doc['binding']['stage']]
            if doc['binding']['stage'] == 'execute':
                from .work_checks import snapshot
                root, base = self.graph.worktrees.code_root(run, node)
                self.admissions[row['id']]['codeSnapshot'] = await snapshot(self.graph, session['id'], root, base)
                if not self.admissions[row['id']]['codeSnapshot']:
                    raise ValueError('WORK_CODE_SNAPSHOT_REQUIRED: answer continuation requires current code')
            await self.graph.run_stage(session, run, node, doc['binding']['stage'],
                                       state.get('maxRounds', 3), controller_action=row['id'])
            status = self.graph.feedback.get(doc['requestId'])['status']
            self.finish(row['id'], 'completed' if status == 'consumed' else 'blocked',
                        state.get('error') if status != 'consumed' else None)
        except asyncio.CancelledError:
            self.finish(row['id'], 'interrupted', 'Continuation stopped; inspect saved child and checkpoint.')
            raise
        except (KeyError, ValueError) as exc:
            self.finish(row['id'], 'blocked', exc)
        finally:
            action = self.admissions.pop(row['id'], None)
            self.children.difference_update(action['children'] if action else {doc['childId']})

    def inject(self, session, run, stage, only, running, limit):
        """Called only by the scheduler holding the canonical live run/lock."""
        for row in self.graph.handoffs.actions(run['runId'], pending=True):
            doc = json.loads(row['doc'])
            target = doc['target']
            node_id = target.get('nodeId', doc['nodeId'])
            chosen_stage = target.get('stage', doc['stage'])
            if chosen_stage != stage or node_id in running or len(running) >= limit:
                continue
            try:
                if self.graph.handoffs.inspect(row, run) and self.graph.handoffs.claim(row):
                    running[node_id] = asyncio.create_task(self.graph.handoffs.execute(row, session, run))
            except (KeyError, ValueError) as exc:
                self.graph.handoffs.finish(row, 'blocked', exc)
        for row in self.rows(run['runId']):
            try:
                value = self.inspect(row)
                if not value:
                    continue
                doc, _, node = value
                if doc['binding']['stage'] != stage or (only and node['id'] not in only):
                    continue
                if node['id'] in running or len(running) >= limit:
                    continue
                if self.claim(row):
                    running[node['id']] = asyncio.create_task(self.execute(row, session, run, node))
            except (KeyError, ValueError) as exc:
                self.finish(row['id'], 'blocked', exc)

    async def worker(self, row):
        run_id = json.loads(row['doc'])['runId']
        lock = self.graph.locks.setdefault(run_id, asyncio.Lock())
        try:
            async with lock:
                if json.loads(row['doc']).get('action') == 'handoff':
                    run = self.graph.get(run_id)
                    current = next((r for r in self.graph.handoffs.actions(run_id) if r['id'] == row['id']), None)
                    if not current or current['status'] != 'pending':
                        return
                    try:
                        if not self.graph.handoffs.inspect(current, run) or not self.graph.handoffs.claim(current):
                            return
                        self.graph.live[run_id] = run
                        self.graph.child_budget[run_id] = [8]
                        await self.graph.handoffs.execute(current, self.rt.store.get(row['owner_id']), run)
                    except (KeyError, ValueError) as exc:
                        self.graph.handoffs.finish(current, 'blocked', exc)
                    finally:
                        self.graph.child_budget.pop(run_id, None)
                        self.graph.live.pop(run_id, None)
                    return
                value = self.inspect(row)
                if not value or not self.claim(row):
                    return
                _, run, node = value
                self.graph.live[run_id] = run
                self.graph.child_budget[run_id] = [5]  # same child + <=3 lookups + same-child synthesis
                try:
                    session = self.rt.store.get(row['owner_id'])
                    if node['stages'].get('execute') and json.loads(row['doc']).get('stage') == 'execute':
                        await self.graph.require_code_current(run)
                    await self.execute(row, session, run, node)
                    # Reconcile only this admission. Handoff to other roles is
                    # an independently assigned W8 action, not an implicit chain.
                    stage = json.loads(row['doc'])['stage']
                    states = [n['stages'][stage]['status'] for n in run['nodes'] if stage in n['stages']]
                    if run['status'] not in ('cancelled', 'rejected', 'shipped', 'paused'):
                        run['status'] = ('executed' if all(s == 'accepted' for s in states) else 'approved') if stage == 'execute' else (
                            'needs_revision' if any(s in ('failed', 'rejected') for s in states) else 'discovering')
                        self.graph.save(run, 'continuation_finished', row['request_id'])
                finally:
                    self.graph.child_budget.pop(run_id, None)
                    self.graph.live.pop(run_id, None)
        except asyncio.CancelledError:
            raise
        except (KeyError, ValueError) as exc:
            self.finish(row['id'], 'blocked', exc)

    def kick(self, row):
        run_id = json.loads(row['doc'])['runId']
        self.wake(run_id)
        if run_id in self.schedulers:
            return  # active scheduler owns mutation and admission
        if row['id'] not in self.tasks:
            task = self.tasks[row['id']] = asyncio.create_task(self.worker(row))
            task.add_done_callback(lambda _: self.tasks.pop(row['id'], None))

    def revoke(self, grant_id):
        for row in self.db.execute("SELECT * FROM work_feedback_outbox WHERE status IN ('pending','claimed')").fetchall():
            doc = self.graph.feedback.get(row['request_id'])
            if doc.get('grantId') == grant_id:
                self.finish(row['id'], 'blocked', 'WORK_CONTINUATION_RIGHTS: main revoked this grant')
                task = self.tasks.get(row['id']) or self.admissions.get(row['id'], {}).get('task')
                if task:
                    task.cancel()
                child_task = self.rt.tasks.get(doc['childId'])
                if doc['status'] == 'resuming' and child_task and not child_task.done():
                    child_task.cancel()

    def revoke_handoff(self, transition_id):
        for row in self.graph.handoffs.actions():
            if json.loads(row['doc'])['transitionId'] != transition_id or row['status'] not in ('pending', 'claimed', 'admitted'):
                continue
            self.graph.handoffs.finish(row, 'blocked', 'WORK_HANDOFF_REVOKED: main revoked this assignment')
            task = self.tasks.get(row['id']) or self.admissions.get(row['id'], {}).get('task')
            if task:
                task.cancel()

    def cancel_request(self, request_id):
        for row in self.db.execute('SELECT id FROM work_feedback_outbox WHERE request_id=?', (request_id,)):
            task = self.tasks.get(row['id']) or self.admissions.get(row['id'], {}).get('task')
            if task:
                task.cancel()
        doc = self.graph.feedback.get(request_id)
        if doc['childId'] in self.children:
            task = self.rt.tasks.get(doc['childId'])
            if task and not task.done():
                task.cancel()

    async def stop(self, owner):
        handoffs = self.graph.handoffs.actions()
        for row in handoffs:
            if row['owner_id'] == owner and row['status'] in ('pending', 'claimed', 'admitted'):
                self.graph.handoffs.finish(row, 'interrupted', 'Root stopped; main must inspect before resuming.')
        tasks = {task for oid, task in list(self.tasks.items()) if self.db.execute(
            'SELECT 1 FROM work_feedback_outbox WHERE id=? AND owner_id=?', (oid, owner)).fetchone()
            or any(r['id'] == oid and r['owner_id'] == owner for r in handoffs)}
        tasks.update(a['task'] for a in self.admissions.values() if a['owner'] == owner)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
