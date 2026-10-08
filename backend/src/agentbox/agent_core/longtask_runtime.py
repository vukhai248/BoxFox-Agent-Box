"""Opt-in adapter for existing finite turns/controllers. All autonomous gates fail closed."""
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import time
import uuid

from .decision_store import encode, write
from .longtask_store import LongtaskError, LongtaskStore, TERMINAL
from . import tool_recovery


class ProfileWriterGuard:
    """Acquire BEFORE SessionStore (its constructor performs a recovery sweep).

    Advisory OS lock, released on process death; never delete the lock file.
    """
    def __init__(self, db_path):
        self.path = Path(str(Path(db_path).resolve()) + '.writer.lock')
        self.file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                f.seek(0)
                if not f.read(1):
                    f.write(b'0')
                    f.flush()
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, IOError) as exc:
            f.close()
            raise LongtaskError('PROFILE_WRITER_BUSY', 'another harness writes this data profile') from exc
        self.file = f
        return self

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None


def _same_authority_scope(pinned, current):
    """Hai bản ghim chỉ khác phần hợp đồng chủ (goal/revision/hash/event) hay khác cả phạm vi?

    Chỉ khác phần hợp đồng ⇒ lượt của chủ được re-base. Khác phạm vi (dự án, capability epoch,
    allocation, work/plan run) ⇒ stale thật: dừng lại, không tự chạy tiếp.
    """
    return all((pinned or {}).get(key) == (current or {}).get(key) for key in LongtaskRuntime.SCOPE_KEYS)


def enabled():
    return os.environ.get('BOXFOX_LONGTASK_CONTINUITY', '0') == '1'


class LongtaskRuntime:
    def __init__(self, rt):
        self.rt, self.store = rt, LongtaskStore(rt.store)
        # Main supplies canonical owner/contract and current live authority/workspace checks.
        # binding(sid, body) -> {projectId,goalRevision,contractRevision,contractHash,
        # ownerEventRef,capabilityEpoch,allocationRef?,workRunId?,planRunId?}.
        # authority(sid, run) -> same binding after read-only workspace/permission validation.
        # completion(sid, run) -> {state,evidenceFingerprint,acceptanceSatisfied,...}.
        self.binding = self.authority = self.completion = self.controller_continue = self.owner_acceptance = None
        self.recovered = False
        self.runner_id = 'runner-' + uuid.uuid4().hex
        self.snapshots = {}
        self.autonomous = {}
        self.wait_ms = {}

    #: Khoá phạm vi của bản ghim: khác một trong số này là mất quyền/đổi dự án, không phải
    #: "chủ vừa nói thêm một câu" — nên chúng vẫn chặn cứng.
    SCOPE_KEYS = ('projectId', 'capabilityEpoch', 'allocationRef', 'workRunId', 'planRunId')

    def root_run(self, sid):
        root = self.rt.root_session_id(sid)
        run = self.store.get(root)
        return run if run and run['state'] not in TERMINAL else None

    def configure(self, sid, body):
        session = self.rt.store.get(sid)
        if session.get('parent_id'):
            raise LongtaskError('LONGTASK_ROOT_ONLY', 'only owner root can configure', 403)
        current = self.store.get(sid)
        if current and current['state'] not in TERMINAL:
            if body.get('enabled') is not True:
                return self.store.configure(sid, body, current['binding'])
            # Chủ chủ động ghim lại (route PUT): hợp đồng phải khớp canonical hiện tại, còn ngân sách
            # đã tiêu thì giữ nguyên — đổi hạn mức vẫn phải qua quyết định của chủ.
            if body.get('expectedRevision') != current['revision']:
                raise LongtaskError('LONGTASK_STALE', 'run revision changed')
            fresh = self.binding(sid, body) if callable(self.binding) else None
            if not fresh:
                raise LongtaskError('LONGTASK_CANONICAL_BINDING_UNAVAILABLE', 'canonical owner contract hook required')
            return self.store.repin(current, fresh, resume_policy=body.get('resumePolicy'))
        if not callable(self.binding):
            raise LongtaskError('LONGTASK_CANONICAL_BINDING_UNAVAILABLE', 'canonical owner contract hook required')
        binding = self.binding(sid, body)
        for field in ('projectId', 'goalRevision', 'contractHash', 'ownerEventRef', 'capabilityEpoch'):
            if not binding or not binding.get(field):
                raise LongtaskError('LONGTASK_CANONICAL_BINDING_UNAVAILABLE', 'missing canonical ' + field)
        if body.get('goalRevision') != binding['goalRevision']:
            raise LongtaskError('LONGTASK_STALE', 'owner goal revision changed')
        return self.store.configure(sid, body, binding)

    def check(self, sid, snapshot=None, *, autonomous=False):
        run = self.store.get(run_id=snapshot['runId']) if snapshot else self.root_run(sid)
        if not run:
            return None
        if snapshot and (snapshot['revision'] != run['revision'] or snapshot['stopEpoch'] != run['stopEpoch']
                         or snapshot['capabilityEpoch'] != run['capabilityEpoch'] or snapshot['leaseEpoch'] != run['leaseEpoch']):
            raise LongtaskError('LONGTASK_STALE', 'owner correction/stop/capability changed at boundary')
        if autonomous:
            # Only automatic continuation is confined to an actively executing run.
            if run['state'] not in ('ready', 'running', 'interrupted'):
                raise LongtaskError('LONGTASK_BLOCKED', run['blockedReason'] or run['state'])
        elif run['state'] == 'paused':
            # An owner-paused run waits for an explicit resume action, not an ordinary turn.
            raise LongtaskError('LONGTASK_BLOCKED', run['blockedReason'] or run['state'])
        if autonomous and (not enabled() or run['resumePolicy'] != 'safe_auto'):
            raise LongtaskError('LONGTASK_MANUAL', 'automatic continuation is not enabled')
        if not callable(self.authority):
            raise LongtaskError('LONGTASK_REVALIDATION_UNAVAILABLE', 'current authority/workspace hook required')
        current = self.authority(run['sessionId'], run)
        if current != run['binding']:
            if autonomous or not _same_authority_scope(run['binding'], current):
                raise LongtaskError('LONGTASK_STALE', 'canonical scope, permission or workspace binding changed')
            # Lượt của CHÍNH chủ: yêu cầu vừa gửi là chỉ thị hiện hành, nên run ghim lại vào revision
            # mới rồi chạy tiếp. Đổi dự án/quyền/không gian (các khoá phạm vi) vẫn là stale thật —
            # và tự chạy tiếp (`autonomous`) thì không bao giờ re-base sau correction.
            run = self.store.repin(run, current)
        if self.rt.decision_store.page(run['sessionId'])['decisions']:
            raise LongtaskError('LONGTASK_PENDING_DECISION', 'owner decision unresolved')
        # Descendants included: a fresh callId must not dodge ambiguous old mutation.
        ids = [run['sessionId']]
        for root in ids:
            ids.extend(row['id'] for row in self.rt.store.db.execute('SELECT id FROM sessions WHERE parent_id=?', (root,))
                       if row['id'] not in ids)
        inspected = {(ref['sessionId'], ref['seq']) for ref in self.store.inspected(run)}
        for target in ids:
            if any(item.get('replay') != 'safe' for item in tool_recovery.interrupted_calls(self.rt.store, target)):
                raise LongtaskError('LONGTASK_UNSAFE_INTERRUPTION', 'unresolved unsafe tool intent')
            rows = self.rt.store.db.execute("SELECT seq,payload FROM events WHERE session_id=? AND kind='tool_end'", (target,))
            if any((json.loads(row['payload']).get('result') or {}).get('errorCode') == tool_recovery.INTERRUPTED_UNSAFE
                   and (target, row['seq']) not in inspected for row in rows):
                raise LongtaskError('LONGTASK_UNSAFE_INTERRUPTION', 'unsafe interruption requires owner inspection')
        return run

    def checkpoint(self, run, reason):
        # Canonical failure propagates; never claim stored when disk/SQLite commit failed.
        sid = run['sessionId']
        session = self.rt.store.get(sid)
        messages = self.rt.active_messages.get(sid, session['messages'])
        self.rt.store.checkpoint(sid, messages, reason, {})
        ref = self.rt.store.db.execute('SELECT MAX(id) FROM checkpoints WHERE session_id=?', (sid,)).fetchone()[0]
        return {'kind': 'checkpoint', 'id': ref,
                'runId': run['runId'], 'goalRevision': run['goalRevision'], 'budget': run['budget']}

    def block(self, sid, exc):
        run = self.root_run(sid)
        if not run or run['state'] in ('cancelled', 'paused'):
            return
        ref = self.checkpoint(run, exc.code)
        state = 'budget_exhausted' if exc.code == 'LONGTASK_BUDGET_EXHAUSTED' else 'needs_user'
        if exc.code == 'LONGTASK_WALL_DEADLINE':
            state = 'paused'
        run = self.store.transition(run, state, exc.code, checkpoint=ref)
        if state == 'budget_exhausted':
            self.budget_card(run)

    def park_failed_turn(self, sid, error):
        """Lượt chết vì lỗi KHÁC `LongtaskError` vẫn phải đóng sổ run.

        `reserve` đã đẩy run sang `running` và giữ lease. Bỏ mặc ở đó thì chủ đọc ra một tác vụ
        "đang chạy" không có ai chạy, `blockedReason` rỗng, và chỉ `recover()` sau lần khởi động
        sau mới sửa — trong khi lượt vừa chết đã biết rõ chuyện gì xảy ra.
        """
        run = self.root_run(sid)
        if not run or run['state'] not in ('ready', 'running'):
            return None
        self.block(sid, LongtaskError('LONGTASK_TURN_FAILED', str(error)[:200]))
        return self.root_run(sid)

    def budget_card(self, run):
        b = run['budget']
        did = hashlib.sha256((run['runId'] + ':budget:' + str(b['revision'])).encode()).hexdigest()[:16]
        if self.rt.decision_store.get(run['sessionId'], did):
            return did
        delta = {'steps': b['totalStepLimit'], 'activeTimeMs': b['activeTimeLimitMs']}
        record = {'decisionId': did, 'sessionId': run['sessionId'], 'kind': 'budget',
                  'options': [{'id': 'extend', 'label': 'Add the same finite budget', 'kind': 'approve', 'budgetDelta': delta},
                              {'id': 'reject', 'label': 'Keep checkpoint paused', 'kind': 'reject'}],
                  'deadline': None, 'defaultChoice': 'reject', 'resolved': False, 'outcome': None,
                  'toolCallId': None, 'budgetRevision': b['revision'], 'runId': run['runId']}
        payload = {**record, 'question': 'Task budget exhausted. Add steps/time without changing scope?',
                   'used': b, 'checkpointRef': run['checkpointRef']}
        binding = self.rt.decision_binding(run['sessionId'], None, {})
        self.rt.decision_store.request(record, payload, binding)
        self.rt.hydrate_decisions(run['sessionId'])
        return did

    def budget_effect(self, record, choice):
        run = self.store.get(run_id=record['runId'])
        option = next(item for item in record['options'] if item['id'] == choice)
        def apply(db):
            current = self.store.get(run_id=run['runId'])
            b = current['budget']
            if current['state'] != 'budget_exhausted' or b['revision'] != record['budgetRevision']:
                raise LongtaskError('DECISION_STALE', 'budget revision changed')
            state = 'paused'
            if choice == 'extend':
                delta = option['budgetDelta']  # stored backend option, never free text/model payload.
                b['totalStepLimit'] += delta['steps']
                b['activeTimeLimitMs'] += delta['activeTimeMs']
                b['revision'] += 1
                state = 'ready'
            db.execute('UPDATE longtask_runs SET budget_json=?,state=?,revision=revision+1,updated=? WHERE run_id=?',
                       (encode(b), state, time.time(), run['runId']))
        return apply

    async def model(self, sid, callback):
        snapshot = self.snapshots.get(sid)
        run = self.check(sid, snapshot)
        if not run:
            return await callback()
        key = 'model-' + uuid.uuid4().hex
        # Existing finite turn cap is a conservative call upper bound, not task wall time.
        bound = self.rt.turn_budget_seconds(self.rt.store.get(sid), self.rt.turn_invocations.get(sid)) * 1000
        try:
            self.store.reserve(run, key, 1, bound, manual=not self.autonomous.get(sid, False))
        except LongtaskError as exc:
            self.block(sid, exc)
            raise
        started = time.monotonic()
        try:
            return await callback()
        finally:
            self.store.settle_segment(run, key, (time.monotonic() - started) * 1000)

    async def tool(self, sid, callback):
        run = self.check(sid, self.snapshots.get(sid))
        if not run:
            return await callback()
        key = 'tool-' + uuid.uuid4().hex
        bound = self.rt.turn_budget_seconds(self.rt.store.get(sid), self.rt.turn_invocations.get(sid)) * 1000
        try:
            self.store.reserve(run, key, 0, bound, manual=not self.autonomous.get(sid, False))
        except LongtaskError as exc:
            self.block(sid, exc)
            raise
        started, waits = time.monotonic(), self.wait_ms.get(sid, 0)
        try:
            return await callback()
        finally:
            elapsed = (time.monotonic() - started) * 1000 - (self.wait_ms.get(sid, 0) - waits)
            self.store.settle_segment(run, key, elapsed)

    def finish(self, sid):
        try:
            run = self.check(sid, self.snapshots.get(sid))
        except LongtaskError as exc:
            # A pending owner decision or a stale binding parks the run; end-of-turn bookkeeping
            # must never fail the turn itself.
            self.block(sid, exc)
            return self.root_run(sid)
        if not run:
            return None
        if not callable(self.completion):
            exc = LongtaskError('LONGTASK_EVIDENCE_UNAVAILABLE', 'scoped canonical acceptance hook required')
            self.block(sid, exc)
            return self.store.get(run_id=run['runId'])
        proposal = self.completion(sid, run)
        state = proposal.get('state')
        if state not in ('runnable', 'waiting_children', 'waiting_job', 'needs_user', 'completed'):
            raise LongtaskError('LONGTASK_EVIDENCE_INVALID', 'invalid deterministic completion projection')
        if state == 'completed' and (proposal.get('acceptanceSatisfied') is not True
                or proposal.get('failedChecks') or proposal.get('staleChecks') or proposal.get('requiredActive')
                or proposal.get('requiredBlocked') or not proposal.get('evidenceFingerprint')):
            state = 'needs_user'
        progress = run['lastProgress']
        if not run['workRunId'] and state == 'runnable':
            fingerprint = proposal.get('evidenceFingerprint')
            unchanged = progress.get('unchangedCount', 0) + 1 if not fingerprint or fingerprint == progress.get('fingerprint') else 0
            progress = {'fingerprint': fingerprint, 'unchangedCount': unchanged}
            if unchanged >= 3:
                state = 'needs_user'
                proposal['blockedReason'] = 'LONGTASK_NO_PROGRESS'
        ref = self.checkpoint(run, proposal.get('blockedReason') or 'LONGTASK_TURN_END')
        result = self.store.transition(run, 'ready' if state == 'runnable' else state,
                                       proposal.get('blockedReason'), checkpoint=ref, progress=progress)
        if state == 'runnable' and enabled() and run['resumePolicy'] == 'safe_auto':
            if run['workRunId'] or run['planRunId']:
                if callable(self.controller_continue):
                    self.controller_continue(result, proposal)  # existing controller/outbox owns admission.
                else:
                    self.store.transition(result, 'needs_user', 'LONGTASK_CONTROLLER_UNAVAILABLE')
            else:
                self.store.queue(result, 'turn:' + str(self.rt.active_turn.get(sid, 0)))
        return result

    async def recover(self):
        from . import task_surface, job_surface
        if self.recovered:
            return {'spawned': 0, 'alreadyRecovered': True}
        task_report = task_surface.reconcile_startup(self.rt)
        job_surface.reconcile_startup(self.rt)
        for row in self.store.db.execute("SELECT session_id FROM longtask_runs WHERE state NOT IN ('completed','cancelled','failed')").fetchall():
            sid = row['session_id']
            session = self.rt.store.get(sid)
            messages = session['messages']
            safe_reads = tool_recovery.reconcile(self.rt, sid, messages)
            if safe_reads:
                self.rt.pending_replays[sid] = safe_reads
            self.rt.store.save(sid, messages, session['status'])
        report = self.store.recover()
        self.recovered = True
        for row in self.store.db.execute("SELECT run_id FROM longtask_runs WHERE state='interrupted'").fetchall():
            run = self.store.get(run_id=row['run_id'])
            if not enabled() or run['resumePolicy'] != 'safe_auto':
                self.store.barrier(run['sessionId'], reason='LONGTASK_MANUAL_RESTART')
                continue
            try:
                self.check(run['sessionId'], autonomous=True)
                if not callable(self.completion):
                    raise LongtaskError('LONGTASK_EVIDENCE_UNAVAILABLE', 'recovery projection unavailable')
                proposal = self.completion(run['sessionId'], run)
                if proposal.get('state') != 'runnable':
                    raise LongtaskError('LONGTASK_RECOVERY_BLOCKED', 'projection not runnable')
                run = self.store.transition(run, 'ready')
                if run['workRunId'] or run['planRunId']:
                    if not callable(self.controller_continue):
                        raise LongtaskError('LONGTASK_CONTROLLER_UNAVAILABLE', 'owning controller hook required')
                    self.controller_continue(run, {'source': 'restart', **proposal})
                else:
                    self.store.queue(run, 'restart:' + str(run['leaseEpoch']))
            except LongtaskError as exc:
                self.block(run['sessionId'], exc)
        return {**report, 'alreadyRecovered': False, 'tasks': task_report}

    async def pump(self):
        if not self.recovered:
            return {'admitted': 0, 'reason': 'recovery not completed'}
        admitted = 0
        # Existing server calls this; no standalone polling loop or executor reattachment.
        rows = self.store.db.execute("SELECT * FROM longtask_continuations WHERE state='pending' ORDER BY created LIMIT 20").fetchall()
        for row in rows:
            run = self.store.get(run_id=row['run_id'])
            sid = run['sessionId']
            if sid in self.rt.tasks and not self.rt.tasks[sid].done():
                continue
            if not enabled() or run['resumePolicy'] != 'safe_auto':
                if run['state'] not in TERMINAL and run['state'] != 'paused':
                    self.store.barrier(sid, reason='LONGTASK_AUTO_DISABLED')
                continue
            try:
                run = self.check(sid, autonomous=True)
                if run['revision'] != row['expected_revision'] or run['stopEpoch'] != row['stop_epoch']:
                    raise LongtaskError('LONGTASK_STALE', 'outbox revision changed')
                with write(self.store.db):
                    changed = self.store.db.execute("UPDATE longtask_continuations SET state='admitted',updated=? WHERE id=? AND state='pending' "
                        "AND EXISTS(SELECT 1 FROM longtask_runs r WHERE r.run_id=longtask_continuations.run_id "
                        "AND r.state='ready' AND r.revision=longtask_continuations.expected_revision "
                        "AND r.stop_epoch=longtask_continuations.stop_epoch)",
                        (time.time(), row['id'])).rowcount
                if not changed:
                    continue
                self.rt.start(sid, 'Continue the canonical task within its current contract.',
                              invocation_id=row['invocation_id'], longtask_continuation=dict(row))
                admitted += 1
            except LongtaskError as exc:
                self.block(sid, exc)
        return {'admitted': admitted}
