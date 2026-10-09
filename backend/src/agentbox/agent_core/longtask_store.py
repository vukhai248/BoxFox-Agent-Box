"""Only missing root binding/budget receipts; no graph, scheduler or money ledger."""
import hashlib
import json
import math
import time
import uuid

from .decision_store import encode, event, write

TERMINAL = frozenset({'completed', 'cancelled', 'failed'})


class LongtaskError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def finite(value, name, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise LongtaskError('LONGTASK_BUDGET_INVALID', name + ' must be explicit, finite and positive', 400)
    if integer and type(value) is not int:
        raise LongtaskError('LONGTASK_BUDGET_INVALID', name + ' must be an integer', 400)
    return value


class LongtaskStore:
    def __init__(self, store):
        self.store, self.db = store, store.db
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS longtask_runs (
                run_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, project_id TEXT NOT NULL,
                owner_id TEXT NOT NULL, session_id TEXT NOT NULL, work_run_id TEXT, plan_run_id TEXT,
                state TEXT NOT NULL, revision INTEGER NOT NULL, goal_revision INTEGER NOT NULL,
                contract_hash TEXT NOT NULL, binding_json TEXT NOT NULL, resume_policy TEXT NOT NULL,
                budget_json TEXT NOT NULL, checkpoint_ref_json TEXT, last_progress_json TEXT NOT NULL,
                stop_epoch INTEGER NOT NULL, capability_epoch INTEGER NOT NULL, lease_owner TEXT,
                lease_expires REAL, lease_epoch INTEGER NOT NULL, blocked_reason TEXT, created REAL, updated REAL);
            CREATE UNIQUE INDEX IF NOT EXISTS longtask_root_active ON longtask_runs(session_id)
                WHERE state NOT IN ('completed','cancelled','failed');
            CREATE TABLE IF NOT EXISTS longtask_segments (
                run_id TEXT NOT NULL, receipt_key TEXT NOT NULL, schema_version INTEGER NOT NULL,
                steps INTEGER NOT NULL, bound_ms REAL NOT NULL, used_ms REAL, state TEXT NOT NULL,
                stop_epoch INTEGER NOT NULL, created REAL, updated REAL, PRIMARY KEY(run_id,receipt_key));
            CREATE TABLE IF NOT EXISTS longtask_continuations (
                id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, run_id TEXT NOT NULL,
                source_key TEXT NOT NULL, expected_revision INTEGER NOT NULL, stop_epoch INTEGER NOT NULL,
                invocation_id TEXT NOT NULL UNIQUE, state TEXT NOT NULL, receipt_json TEXT, created REAL, updated REAL,
                UNIQUE(run_id,source_key));
            CREATE TABLE IF NOT EXISTS longtask_inspections (
                run_id TEXT NOT NULL, invocation_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                binding_hash TEXT NOT NULL, receipt_refs_json TEXT NOT NULL, evidence_refs_json TEXT NOT NULL,
                acceptance_json TEXT, created REAL NOT NULL, PRIMARY KEY(run_id,invocation_id));
            CREATE TABLE IF NOT EXISTS longtask_invocations (
                session_id TEXT NOT NULL, invocation_id TEXT NOT NULL, schema_version INTEGER NOT NULL,
                request_hash TEXT NOT NULL, result_json TEXT NOT NULL, PRIMARY KEY(session_id,invocation_id));
        ''')

    @staticmethod
    def view(row):
        if row is None:
            return None
        b = json.loads(row['budget_json'])
        return {'runId': row['run_id'], 'sessionId': row['session_id'], 'ownerId': row['owner_id'],
                'projectId': row['project_id'], 'state': row['state'], 'revision': row['revision'],
                'goalRevision': row['goal_revision'], 'contractRevision': json.loads(row['binding_json']).get('contractRevision', row['goal_revision']),
                'contractHash': row['contract_hash'], 'binding': json.loads(row['binding_json']),
                'workRunId': row['work_run_id'], 'planRunId': row['plan_run_id'],
                'resumePolicy': row['resume_policy'], 'budget': b,
                'remainingBudget': {'steps': max(0, b['totalStepLimit'] - b['totalStepsUsed']),
                                    'activeTimeMs': max(0, b['activeTimeLimitMs'] - b['activeTimeUsedMs'])},
                'checkpointRef': json.loads(row['checkpoint_ref_json']) if row['checkpoint_ref_json'] else None,
                'lastProgress': json.loads(row['last_progress_json']), 'blockedReason': row['blocked_reason'],
                'stopEpoch': row['stop_epoch'], 'capabilityEpoch': row['capability_epoch'],
                'leaseEpoch': row['lease_epoch']}

    def get(self, sid=None, run_id=None):
        if run_id:
            row = self.db.execute('SELECT * FROM longtask_runs WHERE run_id=?', (run_id,)).fetchone()
        else:
            row = self.db.execute('SELECT * FROM longtask_runs WHERE session_id=? ORDER BY created DESC LIMIT 1',
                                  (sid,)).fetchone()
        return self.view(row)

    def _retry(self, sid, iid, body):
        if not isinstance(iid, str) or not iid.strip():
            raise LongtaskError('LONGTASK_INVOCATION_REQUIRED', 'invocationId required', 400)
        digest = hashlib.sha256(encode(body).encode()).hexdigest()
        row = self.db.execute('SELECT * FROM longtask_invocations WHERE session_id=? AND invocation_id=?',
                              (sid, iid)).fetchone()
        if row and row['request_hash'] != digest:
            raise LongtaskError('LONGTASK_INVOCATION_CONFLICT', 'same invocation with different payload')
        return (json.loads(row['result_json']) if row else None), digest

    def _remember(self, sid, iid, digest, result):
        self.db.execute('INSERT INTO longtask_invocations VALUES(?,?,1,?,?)', (sid, iid, digest, encode(result)))
        return result

    def configure(self, sid, body, binding):
        with write(self.db):
            cached, digest = self._retry(sid, body.get('invocationId'), body)
            if cached:
                return cached
            current = self.get(sid)
            if current and current['state'] not in TERMINAL:
                if body.get('expectedRevision') != current['revision']:
                    raise LongtaskError('LONGTASK_STALE', 'run revision changed')
                if body.get('enabled') is not False:
                    raise LongtaskError('LONGTASK_CONSENT_REQUIRED', 'live budget/scope changes require owner decision')
                self._barrier(current, 'paused', 'LONGTASK_DISABLED')
                result = self.get(run_id=current['runId'])
            else:
                if body.get('enabled') is not True:
                    raise LongtaskError('LONGTASK_INVALID', 'enabled must be true for a new run', 400)
                if body.get('resumePolicy') not in ('manual', 'safe_auto'):
                    raise LongtaskError('LONGTASK_INVALID', 'explicit resumePolicy required', 400)
                raw = body.get('budget') or {}
                now = time.time()
                budget = {'revision': 1, 'approvedByEventRef': binding['ownerEventRef'],
                          'totalStepLimit': finite(raw.get('totalStepLimit'), 'totalStepLimit', True),
                          'totalStepsUsed': 0, 'activeTimeLimitMs': finite(raw.get('activeTimeLimitMs'), 'activeTimeLimitMs'),
                          'activeTimeUsedMs': 0, 'wallStartedAt': now, 'wallDeadlineAt': raw.get('wallDeadlineAt'),
                          'checkpointReserveSteps': 1, 'checkpointReserveMs': 1000,
                          'allocationRef': binding.get('allocationRef')}
                if budget['wallDeadlineAt'] is not None and finite(budget['wallDeadlineAt'], 'wallDeadlineAt') <= now:
                    raise LongtaskError('LONGTASK_BUDGET_INVALID', 'wall deadline is in the past', 400)
                rid = 'lt-' + uuid.uuid4().hex
                self.db.execute('INSERT INTO longtask_runs VALUES(?,1,?,?,?,?,?,\'ready\',1,?,?,?, ?,?,NULL,\'{}\',0,?,NULL,NULL,0,NULL,?,?)',
                                (rid, binding['projectId'], sid, sid, binding.get('workRunId'), binding.get('planRunId'),
                                 binding['goalRevision'], binding['contractHash'], encode(binding), body['resumePolicy'],
                                 encode(budget), binding['capabilityEpoch'], now, now))
                result = self.get(run_id=rid)
            event(self.db, sid, 'longtask', result)
            return self._remember(sid, body['invocationId'], digest, result)

    def repin(self, run, binding, *, resume_policy=None):
        """Ghim lại run vào hợp đồng HIỆN TẠI — không đụng ngân sách đã tiêu.

        Yêu cầu chủ mới (hoặc quyền/không gian được cấp lại) làm bản ghim cũ hết hiệu lực. Run cũ
        không được tự chạy tiếp theo bản cũ, nhưng chủ phải có đường thoát: nếu không thì cách duy
        nhất là `cancel` rồi lập run mới — đã gặp thật ở vòng kiểm.
        """
        if resume_policy not in (None, 'manual', 'safe_auto'):
            raise LongtaskError('LONGTASK_INVALID', 'resumePolicy must be manual or safe_auto', 400)
        state = 'ready' if (run['state'] == 'needs_user' and run['blockedReason'] == 'LONGTASK_STALE') else run['state']
        with write(self.db):
            self.db.execute('UPDATE longtask_runs SET goal_revision=?,contract_hash=?,binding_json=?,'
                            'resume_policy=COALESCE(?,resume_policy),state=?,blocked_reason=?,'
                            'revision=revision+1,updated=? WHERE run_id=?',
                            (binding['goalRevision'], binding['contractHash'], encode(binding), resume_policy,
                             state, None if state == 'ready' else run['blockedReason'], time.time(), run['runId']))
            result = self.get(run_id=run['runId'])
            # Lời `inspect` đã ghi ghim BIÊN NHẬN bị cắt, không ghim bản hợp đồng. Chỉ thị mới của
            # chủ tiến goal/contract revision NGAY TRONG lượt của chính chủ (`start()` nhận lượt
            # trước, ingress của chủ ghi sau), nên nếu lời xác nhận vẫn khoá theo vân tay cũ thì
            # cổng `LONGTASK_UNSAFE_INTERRUPTION` mở ra rồi tự đóng lại ở bước đầu của chính lượt
            # đó — rào không còn đường mở (đo sống 2026-10-09, phiên `72106f67490847a9be5b179a5cc92a6c`:
            # `inspect` trả `ready`/`blockedReason: null`, rồi lượt `t20b` và `t20c` chết ở bước 1
            # với `toolCalls: 0` và `deadlineUsedMs` 386/55 ms). Quyền/nơi chạy đổi vẫn là stale
            # thật vì các khoá phạm vi (`capabilityEpoch`, dự án, allocation, work/plan run) bị chặn
            # TRƯỚC khi tới đây, còn vân tay vẫn giữ `capabilityEpoch`.
            self.db.execute('UPDATE longtask_inspections SET binding_hash=? WHERE run_id=?',
                            (self.inspection_binding(result), run['runId']))
            event(self.db, run['sessionId'], 'longtask', result)
            return result

    def _barrier(self, run, state, reason):
        self.db.execute('UPDATE longtask_runs SET state=?,blocked_reason=?,revision=revision+1,stop_epoch=stop_epoch+1,'
                        'lease_epoch=lease_epoch+1,lease_owner=NULL,lease_expires=NULL,updated=? WHERE run_id=?',
                        (state, reason, time.time(), run['runId']))
        self.db.execute("UPDATE longtask_continuations SET state='cancelled',updated=? WHERE run_id=? AND state IN ('pending','claimed')",
                        (time.time(), run['runId']))

    def barrier(self, sid, state='paused', reason='OWNER_STOP'):
        with write(self.db):
            run = self.get(sid)
            if run and run['state'] not in TERMINAL:
                self._barrier(run, state, reason)
                event(self.db, sid, 'longtask', self.get(sid))
        return self.get(sid)

    @staticmethod
    def inspection_binding(run):
        return hashlib.sha256(encode({'runId': run['runId'], 'goalRevision': run['goalRevision'],
            'contractHash': run['contractHash'], 'contractRevision': run['contractRevision'],
            'capabilityEpoch': run['capabilityEpoch']}).encode()).hexdigest()

    def inspected(self, run):
        refs = []
        for row in self.db.execute('SELECT receipt_refs_json FROM longtask_inspections WHERE run_id=? AND binding_hash=?',
                                   (run['runId'], self.inspection_binding(run))):
            refs.extend(json.loads(row['receipt_refs_json']))
        return refs

    def _inspection(self, run, body, acceptance):
        if body.get('confirm') is not True or run['state'] not in ('ready', 'needs_user', 'paused', 'interrupted'):
            raise LongtaskError('LONGTASK_INSPECTION_REQUIRED', 'explicit confirmed owner inspection required')
        refs = body.get('receiptRefs') or []
        if body['action'] == 'inspect' and not refs:
            raise LongtaskError('LONGTASK_INSPECTION_REQUIRED', 'exact unsafe receipt refs required')
        if not isinstance(refs, list) or len(refs) > 100:
            raise LongtaskError('LONGTASK_INSPECTION_INVALID', 'receipt refs must be bounded list', 400)
        targets = {run['sessionId']}
        pending = [run['sessionId']]
        while pending:
            root = pending.pop()
            for row in self.db.execute('SELECT id FROM sessions WHERE parent_id=?', (root,)):
                if row['id'] not in targets:
                    targets.add(row['id'])
                    pending.append(row['id'])
        for ref in refs:
            if not isinstance(ref, dict) or set(ref) != {'sessionId', 'seq'} or ref['sessionId'] not in targets or type(ref['seq']) is not int:
                raise LongtaskError('LONGTASK_INSPECTION_SCOPE', 'foreign or malformed receipt ref', 403)
            row = self.db.execute('SELECT * FROM events WHERE session_id=? AND seq=?',
                                  (ref['sessionId'], ref['seq'])).fetchone()
            if row is None or row['kind'] != 'tool_end' or (json.loads(row['payload']).get('result') or {}).get('errorCode') != 'TOOL_INTERRUPTED_UNSAFE':
                raise LongtaskError('LONGTASK_INSPECTION_INVALID', 'ref must identify exact unsafe interruption receipt')
        evidence = body.get('evidenceRefs') or []
        if body['action'] == 'accept':
            if not evidence or not isinstance(evidence, list) or len(evidence) > 100:
                raise LongtaskError('LONGTASK_ACCEPTANCE_REQUIRED', 'scoped canonical evidence refs required')
            if (not acceptance or acceptance.get('acceptanceSatisfied') is not True
                    or acceptance.get('evidenceRefs') != evidence or not acceptance.get('evidenceFingerprint')
                    or acceptance.get('failedChecks') or acceptance.get('staleChecks')
                    or acceptance.get('requiredActive') or acceptance.get('requiredBlocked')):
                raise LongtaskError('LONGTASK_ACCEPTANCE_REQUIRED', 'scoped canonical acceptance remains blocked')
        self.db.execute('INSERT INTO longtask_inspections VALUES(?,?,1,?,?,?,?,?)',
                        (run['runId'], body['invocationId'], self.inspection_binding(run), encode(refs),
                         encode(evidence), encode(acceptance) if acceptance else None, time.time()))
        # Inspection acknowledges ambiguity; it does not turn the unsafe tool into safe replay.
        self.db.execute('UPDATE longtask_runs SET state=?,blocked_reason=NULL,revision=revision+1,updated=? WHERE run_id=?',
                        ('completed' if body['action'] == 'accept' else 'ready', time.time(), run['runId']))

    def action(self, sid, body, *, acceptance=None):
        with write(self.db):
            cached, digest = self._retry(sid, body.get('invocationId'), body)
            if cached:
                return cached
            run = self.get(sid)
            if not run or body.get('runId') != run['runId']:
                raise LongtaskError('LONGTASK_UNKNOWN', 'run does not belong to this session', 404)
            if body.get('expectedRevision') != run['revision']:
                raise LongtaskError('LONGTASK_STALE', 'run revision changed')
            action = body.get('action')
            if action in ('pause', 'cancel'):
                self._barrier(run, 'paused' if action == 'pause' else 'cancelled', 'OWNER_' + action.upper())
            elif action in ('inspect', 'accept'):
                self._inspection(run, body, acceptance)
            elif action == 'resume':
                if run['state'] in TERMINAL or run['state'] in ('budget_exhausted', 'needs_user'):
                    raise LongtaskError('LONGTASK_BLOCKED', 'resume cannot override budget/evidence/unsafe blocker')
                # `blocked_reason` là LÝ DO đang chặn, không phải lịch sử: run đã `ready` mà còn giữ
                # `OWNER_STOP`/`LONGTASK_MANUAL_RESTART` thì giao diện và mọi cổng đọc ra một rào
                # không còn tồn tại — chủ `resume` xong vẫn thấy "chủ đã dừng" (đo sống 2026-10-09,
                # phiên `72106f67490847a9be5b179a5cc92a6c`: `resume` trả `state: ready` kèm
                # `blockedReason: OWNER_STOP`). `inspect`/`accept` xoá cùng trường theo cùng lý do.
                self.db.execute("UPDATE longtask_runs SET state='ready',blocked_reason=NULL,"
                                "revision=revision+1,updated=? WHERE run_id=?",
                                (time.time(), run['runId']))
            else:
                raise LongtaskError('LONGTASK_INVALID', 'action must be resume/pause/cancel/inspect/accept', 400)
            result = self.get(sid)
            event(self.db, sid, 'longtask', result)
            return self._remember(sid, body['invocationId'], digest, result)

    def transition(self, run, state, reason=None, checkpoint=None, progress=None):
        with write(self.db):
            current = self.get(run_id=run['runId'])
            if current['stopEpoch'] != run['stopEpoch'] or current['state'] in TERMINAL:
                return current  # late result retained separately, never resurrect cancelled.
            self.db.execute('UPDATE longtask_runs SET state=?,blocked_reason=?,checkpoint_ref_json=COALESCE(?,checkpoint_ref_json),'
                            'last_progress_json=COALESCE(?,last_progress_json),revision=revision+1,updated=? WHERE run_id=?',
                            (state, reason, encode(checkpoint) if checkpoint else None,
                             encode(progress) if progress is not None else None, time.time(), run['runId']))
            result = self.get(run_id=run['runId'])
            event(self.db, run['sessionId'], 'longtask', result)
            return result

    def claim_turn(self, run, runner_id, expires):
        with write(self.db):
            row = self.db.execute('SELECT * FROM longtask_runs WHERE run_id=?', (run['runId'],)).fetchone()
            current = self.view(row)
            if current['stopEpoch'] != run['stopEpoch'] or current['revision'] != run['revision']:
                raise LongtaskError('LONGTASK_STALE', 'lease claim binding changed')
            if row['lease_owner'] not in (None, runner_id):
                # Even expired ambiguous execution requires startup reconciliation, no blind takeover.
                raise LongtaskError('LONGTASK_LEASE_BUSY', 'another runner owns this root; reconcile first')
            self.db.execute('UPDATE longtask_runs SET lease_owner=?,lease_expires=?,lease_epoch=lease_epoch+?,updated=? WHERE run_id=?',
                            (runner_id, expires, 1 if row['lease_owner'] is None else 0, time.time(), run['runId']))
            return self.get(run_id=run['runId'])

    def reserve(self, run, key, steps, bound_ms, *, manual=False):
        finite(bound_ms, 'segment upper bound')
        with write(self.db):
            old = self.db.execute('SELECT * FROM longtask_segments WHERE run_id=? AND receipt_key=?',
                                  (run['runId'], key)).fetchone()
            if old:
                raise LongtaskError('LONGTASK_SEGMENT_REPLAY', 'an admitted segment cannot dispatch twice')
            now = self.get(run_id=run['runId'])
            if now['state'] == 'budget_exhausted':
                raise LongtaskError('LONGTASK_BUDGET_EXHAUSTED', 'checkpoint saved; owner must add budget')
            allowed = (('ready', 'running', 'waiting_children', 'waiting_job', 'needs_user', 'interrupted')
                       if manual else ('ready', 'running'))
            if (now['stopEpoch'] != run['stopEpoch'] or now['revision'] != run['revision']
                    or now['leaseEpoch'] != run['leaseEpoch']
                    or now['state'] not in allowed):
                raise LongtaskError('LONGTASK_STALE', 'admission binding changed')
            b = now['budget']
            if b.get('wallDeadlineAt') is not None and time.time() >= b['wallDeadlineAt']:
                raise LongtaskError('LONGTASK_WALL_DEADLINE', 'wall deadline reached')
            if (b['totalStepsUsed'] + steps + b['checkpointReserveSteps'] > b['totalStepLimit']
                    or b['activeTimeUsedMs'] + bound_ms + b['checkpointReserveMs'] > b['activeTimeLimitMs']):
                # Chưa tiêu gì mà trần một lượt đã lớn hơn cả hạn mức thì đây KHÔNG phải "hết ngân
                # sách": nói đúng chuyện (hạn mức nhỏ hơn trần một lượt) để chủ biết phải đặt lại
                # bao nhiêu, thay vì một thẻ xin thêm đúng bằng phần vừa thiếu.
                if b['activeTimeUsedMs'] == 0 and b['totalStepsUsed'] == 0:
                    raise LongtaskError('LONGTASK_BUDGET_TOO_SMALL',
                                        f'the allowance is smaller than one turn upper bound ({int(bound_ms)} ms)')
                raise LongtaskError('LONGTASK_BUDGET_EXHAUSTED', 'not enough budget plus checkpoint reserve')
            b['totalStepsUsed'] += steps
            b['activeTimeUsedMs'] += bound_ms
            self.db.execute('INSERT INTO longtask_segments VALUES(?,?,1,?,?,NULL,\'reserved\',?,?,?)',
                            (run['runId'], key, steps, bound_ms, run['stopEpoch'], time.time(), time.time()))
            self.db.execute("UPDATE longtask_runs SET budget_json=?,state='running',updated=? WHERE run_id=?",
                            (encode(b), time.time(), run['runId']))
        return key

    def settle_segment(self, run, key, used_ms):
        # A crash keeps upper bound reserved; downtime never counted as actual active execution.
        with write(self.db):
            row = self.db.execute('SELECT * FROM longtask_segments WHERE run_id=? AND receipt_key=?',
                                  (run['runId'], key)).fetchone()
            if not row or row['state'] != 'reserved':
                return False
            current = self.get(run_id=run['runId'])
            b = current['budget']
            used_ms = max(0, used_ms)
            b['activeTimeUsedMs'] += used_ms - row['bound_ms']
            self.db.execute("UPDATE longtask_segments SET state='settled',used_ms=?,updated=? WHERE run_id=? AND receipt_key=?",
                            (used_ms, time.time(), run['runId'], key))
            self.db.execute('UPDATE longtask_runs SET budget_json=?,updated=? WHERE run_id=?',
                            (encode(b), time.time(), run['runId']))
            return True

    def queue(self, run, source_key):
        if run['workRunId'] or run['planRunId']:
            raise LongtaskError('LONGTASK_CONTROLLER_OWNED', 'use owning controller outbox')
        with write(self.db):
            current = self.get(run_id=run['runId'])
            if current['revision'] != run['revision'] or current['stopEpoch'] != run['stopEpoch'] or current['state'] != 'ready':
                raise LongtaskError('LONGTASK_STALE', 'queue binding changed')
            iid = 'ltc-' + hashlib.sha256((run['runId'] + ':' + source_key).encode()).hexdigest()
            self.db.execute('INSERT OR IGNORE INTO longtask_continuations VALUES(?,1,?,?,?,?,?,\'pending\',NULL,?,?)',
                            (iid, run['runId'], source_key, run['revision'], run['stopEpoch'], iid, time.time(), time.time()))
            return iid

    def recover(self):
        with write(self.db):
            self.db.execute("UPDATE longtask_continuations SET state='pending' WHERE state='claimed'")
            self.db.execute("UPDATE longtask_continuations SET state='interrupted' WHERE state='admitted'")
            self.db.execute("UPDATE longtask_runs SET state='interrupted',blocked_reason='HARNESS_RESTART',"
                            "revision=revision+1,lease_epoch=lease_epoch+1,lease_owner=NULL,lease_expires=NULL "
                            "WHERE state='running'")
        return {'spawned': 0}
