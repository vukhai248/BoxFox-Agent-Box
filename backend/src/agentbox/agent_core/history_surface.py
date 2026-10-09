"""Bề mặt history của main: chỗ nối duy nhất giữa `HistoryStore` và runtime.

`memory/history_store.py` giữ luật; module này cấp đúng ba thứ mà store từ chối đoán:

1. **Danh tính owner cục bộ** (`owner_identity`) — profile này là chủ duy nhất, id ổn định qua
   restart nên một yêu cầu gốc không mất chủ khi tiến trình khởi động lại.
2. **Quyết định phạm vi** (`_authorization`) — cùng project thì đọc được; con chỉ đọc tổ tiên và
   con của chính nó, không bao giờ đọc anh em; capsule chỉ mở cho root sở hữu.
3. **Trạng thái canonical để mang theo** (`_critical_snapshot`, `_quiescence`) — quyết định, blocker,
   check hỏng, task/job đang mở, ngân sách, plan; thiếu nguồn nào thì từ chối xoá, không đoán.

Ngoài ra module cấp cổng công cụ `history_list/search/read`, hook completion/acceptance cho
`LongtaskRuntime`, và số đo dung lượng đĩa cho route `/api/agent/history/storage`.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time

from ..memory.history_files import digest, encode
from ..memory.history_store import CAPSULE_KEYS, HistoryError
from ..memory.storage_usage import StorageUsage
from .longtask_store import LongtaskError

HISTORY_TOOLS = frozenset({'history_list', 'history_search', 'history_read'})
# Re-export: định nghĩa duy nhất nằm ở memory.history_store; tên này giữ cho caller/test cũ.
TERMINAL_RUNS = ('completed', 'cancelled', 'failed')
TERMINAL_WORK = ('shipped', 'cancelled', 'rejected')
MAX_REFS = 20


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def contract_hash(contract):
    """Cùng một định nghĩa hash cho cả route (UI ghim) lẫn binding longtask."""
    return _digest(contract)


def _tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def owner_identity(rt):
    """Chủ cục bộ của profile; id suy ra từ đường DB nên sống qua restart và đổi máy thì đổi chủ."""
    try:
        path = str(rt.store.path)
    except Exception:
        path = 'boxfox'
    return 'owner-' + hashlib.sha256(path.encode()).hexdigest()[:16]


def service(rt):
    """HistoryStore đã gắn hook. Gắn một lần cho mỗi instance; thiếu nguồn thì hook giữ `None`."""
    store = getattr(rt, 'store', None)
    history = getattr(store, 'history', None)
    if history is None:
        raise HistoryError('HISTORY_SURFACE_UNAVAILABLE')
    if not getattr(history, '_surface_wired', False):
        history.binding_resolver = history.binding_resolver or (lambda sid: _resolver(rt, sid))
        history.authorization = history.authorization or _authorization(rt)
        history.critical_snapshot = history.critical_snapshot or _critical_snapshot(rt)
        history.quiescence = history.quiescence or _quiescence(rt)
        history.run_closer = history.run_closer or _run_closer(rt)
        history._surface_wired = True
    return history


def configure_runtime(rt):
    """Gọi một lần lúc dựng app: gắn hook history + longtask.

    Không đo dung lượng ở đây: phép đo là một lượt `os.walk` toàn kho riêng, và bảng cảnh báo
    vẫn được tạo ở lần đo thật đầu tiên (`storage_snapshot`). Đo lúc dựng app chỉ tốn I/O mà
    kết quả bị bỏ đi.
    """
    history = service(rt)
    longtask = getattr(rt, 'longtask', None)
    wired = False
    if longtask is not None and not getattr(longtask, '_surface_wired', False):
        longtask.binding = _binding(rt)
        longtask.authority = _authority(rt)
        longtask.completion = _completion(rt)
        longtask.owner_acceptance = _owner_acceptance(rt)
        longtask._surface_wired = True
        wired = True
    return {'history': True, 'longtask': wired}


def bind_created_session(rt, sid):
    """Ghim binding thô ngay lúc tạo phiên. Hỏng binding không được làm hỏng việc tạo phiên."""
    try:
        return service(rt).bind_session(sid)
    except Exception as exc:
        try:
            from . import system_log
            system_log.write('history.bind.failed', level='error', session_id=sid,
                             error=f'{type(exc).__name__}: {exc}'[:300])
        except Exception:
            pass
        return None


def _resolver(rt, sid):
    """`binding_resolver`: chỉ nguồn do máy chủ cấp mới mở phạm vi project.

    Phiên host có `machineBinding.projectId` đã được store đọc trực tiếp. Docker/chat không có
    project thì ở lại phạm vi `self` — một container cô lập không được chia project với phiên khác.
    """
    session = rt.store.get(sid)
    config = session.get('config') or {}
    project = config.get('historyProjectId')
    if not project:
        return {}
    return {'projectId': str(project)}


def _ancestors(rt, sid, limit=64):
    out, current = [], sid
    for _ in range(limit):
        try:
            parent = (rt.store.get(current) or {}).get('parent_id')
        except KeyError:
            break
        if not parent:
            break
        out.append(parent)
        current = parent
    return out


def _authorization(rt):
    def allowed(caller, target, meta=None):
        if caller == target:
            return True
        try:
            history = service(rt)
            a, b = history.bind_session(caller), history.bind_session(target)
        except Exception:
            return False
        if not a.get('project_id') or a.get('project_id') != b.get('project_id'):
            return False
        if (meta or {}).get('capsule'):
            # Capsule thuộc PROJECT chứ không thuộc cây: một hội thoại MỚI cùng project phải đọc
            # được bài học/trạng thái chuyển tiếp còn lại sau khi raw bị xóa (LT-08, ca "xóa rồi
            # mở phiên mới"). Cổng trên đã chặn khác project; ở đây chỉ root của cây mình mở được.
            # Capsule không mang quyền thực thi (`executionAuthority: false`, `untrusted: true`).
            return a['session_id'] == a['root_session_id']
        if a['session_id'] == a['root_session_id']:
            return True  # root sở hữu: cả project, trừ capsule của cây khác
        if b['root_session_id'] != a['root_session_id']:
            return False
        return target in _ancestors(rt, caller) or caller in _ancestors(rt, target)
    return allowed


def _critical_snapshot(rt):
    """Bản ghim chính xác, có giới hạn, chỉ đọc. Thiếu nguồn nào thì báo đúng nguồn đó."""
    def snapshot(ids):
        ids = [str(i) for i in ids]
        db, names = rt.store.db, _tables(rt.store.db)
        marks = ','.join('?' for _ in ids)
        decisions, blockers, failed, tasks, jobs, budget, plans = [], [], [], [], [], [], []
        if 'session_decisions' in names:
            for r in db.execute(f'SELECT decision_id,session_id,kind,status,revision,deadline FROM session_decisions '
                                f'WHERE session_id IN ({marks}) ORDER BY created LIMIT 200', ids):
                decisions.append({'decisionId': r['decision_id'], 'sessionId': r['session_id'], 'kind': r['kind'],
                                  'status': r['status'], 'revision': r['revision'], 'deadline': r['deadline']})
        if 'longtask_runs' in names:
            for r in db.execute(f'SELECT run_id,session_id,state,blocked_reason,revision,budget_json FROM longtask_runs '
                                f'WHERE session_id IN ({marks}) ORDER BY created DESC LIMIT 50', ids):
                if r['state'] in TERMINAL_RUNS:
                    continue
                blockers.append({'runId': r['run_id'], 'sessionId': r['session_id'], 'state': r['state'],
                                 'reason': r['blocked_reason'], 'revision': r['revision']})
                try:
                    raw = json.loads(r['budget_json'] or '{}')
                except ValueError:
                    raw = {}
                kept = {k: v for k, v in raw.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
                if kept:
                    budget.append({'runId': r['run_id'], 'revision': kept.get('revision'), **kept})
        if 'work_checks' in names and 'work_runs' in names:
            for r in db.execute('SELECT c.id,c.run_id,c.doc FROM work_checks c JOIN work_runs w ON w.id=c.run_id '
                                f'WHERE w.session_id IN ({marks}) ORDER BY c.id LIMIT 200', ids):
                try:
                    doc = json.loads(r['doc'])
                except ValueError:
                    doc = {}
                if doc.get('status') in ('ok', 'passed'):
                    continue
                failed.append({'checkId': r['id'], 'runId': r['run_id'], 'status': doc.get('status'),
                               'kind': doc.get('kind'), 'error': (doc.get('error') or '')[:200]})
        if 'harness_tasks' in names and 'harness_task_attempts' in names:
            for r in db.execute('SELECT t.task_key,t.run_id,t.state,t.acceptance_state,t.revision,t.contract_hash,'
                                'MAX(a.session_id) session_id FROM harness_tasks t JOIN harness_task_attempts a '
                                f'ON a.task_key=t.task_key WHERE a.session_id IN ({marks}) GROUP BY t.task_key LIMIT 200', ids):
                tasks.append({'taskKey': r['task_key'], 'runId': r['run_id'], 'sessionId': r['session_id'],
                              'state': r['state'], 'acceptanceState': r['acceptance_state'],
                              'revision': r['revision'], 'contractHash': r['contract_hash']})
        if 'harness_jobs' in names:
            for r in db.execute(f"SELECT job_id,owner_id,kind,state,revision,task_key FROM harness_jobs "
                                f"WHERE owner_id IN ({marks}) ORDER BY created_at DESC LIMIT 200", ids):
                jobs.append({'jobId': r['job_id'], 'sessionId': r['owner_id'], 'kind': r['kind'], 'state': r['state'],
                             'revision': r['revision'], 'taskKey': r['task_key']})
        if 'plan_owners' in names:
            for r in db.execute(f'SELECT identity,session_id,slug,version FROM plan_owners WHERE session_id IN ({marks}) '
                                f'ORDER BY updated DESC LIMIT 50', ids):
                entry = {'identity': r['identity'], 'sessionId': r['session_id'], 'slug': r['slug'],
                         'version': r['version']}
                if 'plan_reviews' in names:
                    review = db.execute('SELECT version,decision,resumed FROM plan_reviews WHERE identity=? '
                                        'ORDER BY version DESC LIMIT 1', (r['identity'],)).fetchone()
                    if review:
                        entry.update({'reviewVersion': review['version'], 'decision': review['decision'],
                                      'resumed': review['resumed']})
                plans.append(entry)
        return {'decisions': decisions, 'blockers': blockers, 'failedChecks': failed, 'tasks': tasks,
                'jobs': jobs, 'budget': budget, 'plans': plans}
    return snapshot


def _quiescence(rt):
    """Chỉ xoá khi không còn việc đang chạy. Không biết chắc thì trả False."""
    def quiet(ids):
        ids = [str(i) for i in ids]
        db, names = rt.store.db, _tables(rt.store.db)
        marks = ','.join('?' for _ in ids)
        tasks = getattr(rt, 'tasks', None) or {}
        for sid in ids:
            task = tasks.get(sid)
            if task is not None and not task.done():
                return False
        if 'sessions' in names and db.execute(
                f"SELECT 1 FROM sessions WHERE id IN ({marks}) AND status IN ('running','awaiting_decision') "
                f"LIMIT 1", ids).fetchone():
            return False
        if 'longtask_runs' in names and db.execute(
                f"SELECT 1 FROM longtask_runs WHERE session_id IN ({marks}) AND state IN "
                f"('ready','running','interrupted') LIMIT 1", ids).fetchone():
            return False
        if 'harness_jobs' in names and db.execute(
                f"SELECT 1 FROM harness_jobs WHERE owner_id IN ({marks}) AND state IN "
                f"('queued','running','waiting') LIMIT 1", ids).fetchone():
            return False
        if 'harness_task_attempts' in names and db.execute(
                f"SELECT 1 FROM harness_task_attempts WHERE session_id IN ({marks}) AND (status='running' OR "
                f"(status='waiting_input' AND closed_at IS NULL)) LIMIT 1", ids).fetchone():
            return False
        if 'children' in names and db.execute(
                f"SELECT 1 FROM children WHERE (session_id IN ({marks}) OR parent_id IN ({marks})) AND "
                f"status='started' LIMIT 1", ids + ids).fetchone():
            return False
        return True
    return quiet


def _tree(rt, sid, limit=256):
    rows = rt.store.db.execute('WITH RECURSIVE tree(id) AS (SELECT id FROM sessions WHERE id=? UNION '
                               'SELECT s.id FROM sessions s JOIN tree t ON s.parent_id=t.id) '
                               'SELECT id FROM tree LIMIT ?', (sid, limit)).fetchall()
    return [row[0] for row in rows] or [sid]


def _live(rt, sid):
    task = (getattr(rt, 'tasks', None) or {}).get(sid)
    return task is not None and not task.done()


def _progress_fingerprint(rt, ids, run):
    db, marks = rt.store.db, ','.join('?' for _ in ids)
    payload = {'events': db.execute(f'SELECT COALESCE(MAX(seq),0) FROM events WHERE session_id IN ({marks})', ids).fetchone()[0],
               'checkpoints': db.execute(f'SELECT COALESCE(MAX(id),0) FROM checkpoints WHERE session_id IN ({marks})', ids).fetchone()[0],
               'records': db.execute(f'SELECT COALESCE(MAX(seq),0) FROM history_records WHERE session_id IN ({marks})', ids).fetchone()[0],
               'run': run['runId'], 'budgetRevision': (run.get('budget') or {}).get('revision')}
    return _digest(payload)


def _completion(rt):
    """Kết thúc chỉ bằng bằng chứng canonical: graph đã giao, hoặc chủ nghiệm thu.

    Không có bằng chứng thì run ở `runnable` trong ngân sách hữu hạn; hết ngân sách store tự chặn.
    """
    def completion(sid, run):
        db, names = rt.store.db, _tables(rt.store.db)
        ids = _tree(rt, sid)
        live = sorted(i for i in ids if i != sid and _live(rt, i))
        if live:
            return {'state': 'waiting_children', 'acceptanceSatisfied': False,
                    'evidenceFingerprint': _digest({'children': live}), 'requiredActive': True}
        marks = ','.join('?' for _ in ids)
        if 'harness_jobs' in names and db.execute(
                f"SELECT 1 FROM harness_jobs WHERE owner_id IN ({marks}) AND state IN "
                f"('queued','running','waiting') LIMIT 1", ids).fetchone():
            return {'state': 'waiting_job', 'acceptanceSatisfied': False,
                    'evidenceFingerprint': _digest({'jobs': ids}), 'requiredActive': True}
        if 'work_runs' in names:
            graph = db.execute('SELECT id,status,revision FROM work_runs WHERE session_id=? '
                               'ORDER BY updated DESC LIMIT 1', (sid,)).fetchone()
            if graph and graph['status'] not in TERMINAL_WORK:
                return {'state': 'waiting_children', 'acceptanceSatisfied': False,
                        'evidenceFingerprint': _digest({'workRun': graph['id'], 'revision': graph['revision']}),
                        'requiredActive': True}
            if graph and graph['status'] == 'shipped':
                return {'state': 'completed', 'acceptanceSatisfied': True,
                        'evidenceFingerprint': _digest({'workRun': graph['id'], 'revision': graph['revision'],
                                                        'status': graph['status']}),
                        'evidenceRefs': [{'workRunId': graph['id']}]}
        return {'state': 'runnable', 'acceptanceSatisfied': False,
                'evidenceFingerprint': _progress_fingerprint(rt, ids, run)}
    return completion


def _verify_evidence(rt, sid, ref):
    """Một bằng chứng chỉ hợp lệ khi trỏ tới hàng canonical trong chính cây của run."""
    if not isinstance(ref, dict):
        raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
    db, names = rt.store.db, _tables(rt.store.db)
    ids = set(_tree(rt, sid))
    if ref.get('recordId'):
        row = db.execute('SELECT session_id,evidence_state,sha256 FROM history_records WHERE record_id=?',
                         (str(ref['recordId']),)).fetchone()
        if not row or row['session_id'] not in ids or row['evidence_state'] == 'deleted':
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        return {'kind': 'history', 'id': ref['recordId'], 'sha256': row['sha256']}
    if ref.get('workCheckId') and 'work_checks' in names and 'work_runs' in names:
        row = db.execute('SELECT c.doc,w.session_id FROM work_checks c JOIN work_runs w ON w.id=c.run_id '
                         'WHERE c.id=?', (str(ref['workCheckId']),)).fetchone()
        if not row or row['session_id'] not in ids or json.loads(row['doc']).get('status') not in ('ok', 'passed'):
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        return {'kind': 'check', 'id': ref['workCheckId']}
    if ref.get('workArtifactId') and 'work_artifacts' in names:
        row = db.execute('SELECT session_id FROM work_artifacts WHERE id=?', (str(ref['workArtifactId']),)).fetchone()
        if not row or row['session_id'] not in ids:
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        return {'kind': 'artifact', 'id': ref['workArtifactId']}
    if ref.get('jobId') and 'harness_jobs' in names:
        row = db.execute('SELECT owner_id,state FROM harness_jobs WHERE job_id=?', (str(ref['jobId']),)).fetchone()
        if not row or row['owner_id'] not in ids or row['state'] != 'completed':
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        return {'kind': 'job', 'id': ref['jobId']}
    if ref.get('workRunId') and 'work_runs' in names:
        row = db.execute('SELECT session_id,status,revision FROM work_runs WHERE id=?', (str(ref['workRunId']),)).fetchone()
        if not row or row['session_id'] not in ids or row['status'] != 'shipped':
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        return {'kind': 'workRun', 'id': ref['workRunId'], 'revision': row['revision']}
    if ref.get('taskKey') and 'harness_tasks' in names and 'harness_task_attempts' in names:
        # Task không có `session_id` riêng: chủ sở hữu là `owner_id`, còn phiên đã chạy nó nằm ở
        # hàng attempt. Thiếu phép nối này thì một task của phiên/dự án KHÁC vẫn qua được cổng
        # nghiệm thu (đã dựng lại được: bằng chứng ngoài cây bị nhận là hợp lệ).
        rows = db.execute('SELECT t.acceptance_state,t.revision,t.owner_id,a.session_id '
                          'FROM harness_tasks t LEFT JOIN harness_task_attempts a ON a.task_key=t.task_key '
                          'WHERE t.task_key=?', (str(ref['taskKey']),)).fetchall()
        if not rows or rows[0]['acceptance_state'] not in ('accepted', 'satisfied'):
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        if rows[0]['owner_id'] not in ids or any(row['session_id'] not in ids for row in rows):
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        return {'kind': 'task', 'id': ref['taskKey'], 'revision': rows[0]['revision']}
    raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')


def _owner_acceptance(rt):
    """Chủ nghiệm thu: mọi ref phải là hàng canonical trong cây; không nhận lời mô tả của model."""
    def acceptance(sid, run, body):
        refs = body.get('evidenceRefs')
        if not isinstance(refs, list) or not refs or len(refs) > MAX_REFS:
            raise HistoryError('LONGTASK_ACCEPTANCE_REQUIRED')
        verified, failed = [], []
        for ref in refs:
            try:
                verified.append(_verify_evidence(rt, sid, ref))
            except HistoryError as exc:
                failed.append({'ref': ref, 'code': exc.code})
        common = {'evidenceRefs': refs, 'evidenceFingerprint': _digest(verified),
                  'staleChecks': [], 'requiredActive': [], 'requiredBlocked': []}
        if failed:
            return {**common, 'acceptanceSatisfied': False, 'failedChecks': failed}
        return {**common, 'acceptanceSatisfied': True, 'failedChecks': []}
    return acceptance


def _canonical(rt, sid):
    """Binding canonical: một định nghĩa cho cả lúc cấu hình và lúc kiểm lại."""
    session = rt.store.get(sid)
    history = service(rt)
    scope = history.bind_session(sid)
    contract = history.contract(sid)
    project = scope['project_id'] or (session.get('config') or {}).get('historyProjectId') or ''
    if not project:
        raise LongtaskError('LONGTASK_PROJECT_REQUIRED', 'long task needs a bound project workspace', 400)
    return {'projectId': str(project),
            'goalRevision': contract['currentRevision'],
            'contractRevision': contract['currentRevision'],
            'contractHash': contract_hash(contract),
            'ownerEventRef': (contract['revisions'][-1]['record_id'] if contract['revisions']
                              else 'owner:' + owner_identity(rt)),
            'capabilityEpoch': _capability_epoch(rt, session),
            'allocationRef': None}


def _authority(rt):
    """Đọc lại quyền/không gian hiện tại; khác binding đã ghim thì run thành stale, không tự chạy."""
    def authority(sid, run):
        return _canonical(rt, sid)
    return authority


def _capability_epoch(rt, session):
    try:
        from . import execution_kernel
        return execution_kernel.capability_epoch(rt, session)
    except Exception:
        return 1


def _binding(rt):
    """`LongtaskRuntime.binding(sid, body)`: cùng giá trị với `authority`, nên `check()` so được."""
    def build(sid, body):
        value = _canonical(rt, sid)
        if body.get('goalRevision') is not None and body['goalRevision'] != value['goalRevision']:
            raise LongtaskError('LONGTASK_STALE', 'owner goal revision changed')
        if body.get('contractRef') and body['contractRef'] != value['contractHash']:
            raise LongtaskError('LONGTASK_STALE', 'owner contract changed')
        return value
    return build


def storage_snapshot(rt, caller_sid=None, projection_roots=None):
    history = service(rt)
    usage = StorageUsage(history)
    roots = _projection_roots(history) if projection_roots is None else projection_roots
    report = usage.measure(roots)
    if caller_sid:
        event = usage.warning_transition(report['bytes'])
        if event:
            try:
                rt.store.emit(caller_sid, 'storage_warning', event)
            except Exception:
                pass
    return report


def _projection_roots(history):
    if not history.db.execute("SELECT 1 FROM sqlite_master WHERE name='history_projection_files'").fetchone():
        return []
    return sorted({row[0] for row in history.db.execute('SELECT DISTINCT workspace FROM history_projection_files')})


def list_capsules(rt, caller_sid, *, limit=3):
    """Capsule đã chốt của project người gọi — đường ĐỌC LẠI trên bề mặt quản trị (LT-08).

    Ca nghiệm thu "xoá rồi mở hội thoại mới" cần một đường đọc được bằng máy; trước đây
    `read_capsule` chỉ có bài kiểm đơn vị gọi tới nên ca đó không thi hành được.
    """
    return service(rt).project_capsules(caller_sid, limit=limit)


def read_capsule(rt, caller_sid, capsule_id):
    """Nội dung capsule, qua đúng một cổng quyền của store (cùng project, không mang quyền chạy)."""
    return service(rt).read_capsule(caller_sid, capsule_id)


#: Lý do bỏ qua bản chiếu: workspace ở container (hoặc phiên chưa gắn máy) thì host không ghi được.
PROJECTION_SKIPPED = 'remote_or_unbound_workspace'


def _projection_workspace(rt, sid):
    """Workspace host của phiên, hoặc `None` khi phải bỏ qua bản chiếu (container / chưa gắn máy)."""
    session = rt.store.get(sid)
    binding = (session.get('config') or {}).get('machineBinding') or {}
    workspace = binding.get('workspace')
    if not workspace or binding.get('mode') == 'docker':
        return None
    return workspace


def _projection_skip():
    return {'canonicalStored': True, 'projectionStored': False, 'projectionError': None,
            'skipped': PROJECTION_SKIPPED}


def export_projection(rt, sid, checkpoint_id=None):
    """Bản đọc được trong workspace của phiên host. Workspace ở container thì không ghi từ host."""
    from ..memory.history_projection import HistoryProjection
    history = service(rt)
    workspace = _projection_workspace(rt, sid)
    if workspace is None:
        return _projection_skip()
    projection = HistoryProjection(history)
    if checkpoint_id:
        return projection.export_compaction(checkpoint_id, workspace)
    return projection.ensure_session(sid, workspace)


def export_journal(rt, sid):
    """Bản chiếu nhật ký curated (`journal.md`) cạnh bản chiếu nén — cùng chỗ, cùng cách chặn.

    §6 của kế hoạch: cây `.session-history/<sid>/<agent>/` có cả `journal.md` lẫn
    `compaction_NNN.md`. Ghi ở đây (lúc context swap) chứ không phải mỗi lần thêm một hàng nhật ký:
    mỗi lượt một lần ghi tệp cộng làm mới INDEX là giá không cần thiết, còn trước context swap thì
    đây đúng là thứ phải bền.
    """
    from ..memory.history_projection import HistoryProjection
    history = service(rt)
    workspace = _projection_workspace(rt, sid)
    if workspace is None:
        return _projection_skip()
    return HistoryProjection(history).export_journal(sid, workspace)


#: Mã notice khi lượt nén không để lại được manifest thô / bản đọc được. Lượt vẫn đi tiếp:
#: nén hỏng phần bền thì mất khả năng đọc lại, không mất lượt đang chạy.
COMPACTION_DEGRADED_CODE = 'HISTORY_COMPACTION_DEGRADED'
#: Mã notice khi bản thô đã commit nhưng bản chiếu ra workspace không ghi xong. Khác mã trên ở chỗ
#: **không** mất khả năng đọc lại: manifest vẫn còn, chỉ tệp đọc được là thiếu.
PROJECTION_DEGRADED_CODE = 'HISTORY_COMPACTION_PROJECTION_DEGRADED'
#: Mã notice khi bản nén đã ghi xong mà chỉ `journal.md` không ghi xong. Tách khỏi mã trên vì hai
#: tệp là hai lần ghi: gộp lại thì một trong hai lần hỏng sẽ bị báo thành lần kia.
JOURNAL_DEGRADED_CODE = 'HISTORY_COMPACTION_JOURNAL_DEGRADED'


def _failure_code(exc, fallback):
    """Mã để notice nói đúng loại hỏng — **mã**, không phải câu văn của ngoại lệ.

    Lấy `code` của ngoại lệ khi có; nếu không thì chỉ nhận phần đầu thông điệp khi nó đúng dạng mã
    (`HISTORY_SOURCE_CONFLICT`), còn `no such table: x` thì rơi về mã dự phòng và câu văn gốc đi
    kèm trong thông điệp notice (`_failure_detail`).
    """
    code = getattr(exc, 'code', None)
    if code:
        return code
    head = str(exc).split(':', 1)[0].strip()
    return head if re.fullmatch(r'[A-Z][A-Z0-9_]{2,}', head) else fallback


def _failure_detail(exc):
    """Câu văn gốc của ngoại lệ (ngắn lại) — notice cần cả mã lẫn chuyện đã xảy ra."""
    text = str(exc).strip()
    return f'{exc.__class__.__name__}: {text[:160]}' if text else exc.__class__.__name__


def _compaction_numbers(event):
    event = event if isinstance(event, dict) else {}
    numbers = {'reason': event.get('kind'), 'beforeEstimate': event.get('beforeEstimate'),
               'afterEstimate': event.get('afterEstimate'), 'ineffective': event.get('ineffective')}
    return {key: value for key, value in numbers.items() if value is not None}


def record_compaction(rt, sid, saved, compacted, event=None):
    """F02/F09/F19 — giữ bản thô của lượt nén vào kho bền, rồi ghi bản đọc được ra workspace host.

    Ba việc, đúng thứ tự và đúng lý do:

    1. `prepare_compaction` ghi MỌI tin nhắn của active view **trước** nén thành history record
       (blob + segment + sha256) và dựng manifest theo `source_key`/`agent_id`. Đây là bước
       externalize trước prune: sau lời gọi này, danh sách sống có bị cắt cũng không mất bản thô.
    2. `commit_compaction` chốt manifest thành hàng `checkpoints` đọc lại được —
       `SessionStore.checkpoints()` dựng lại đúng active view cũ qua `restore_compaction`.
    3. `export_projection` ghi bản đọc được có đánh số, đúng namespace agent, ra workspace host.
       Phiên container không có workspace host thì bỏ qua và **nói rõ** lý do, không giả là đã ghi.
    4. `export_journal` ghi `journal.md` cạnh đó — cây archive của §6 có cả hai, không chỉ bản nén.

    `source_key` suy từ chính nội dung active view, nên gọi lại cùng một lượt nén là no-op chứ
    không sinh bản thứ hai. Hàm **không bao giờ ném**: lượt đang chạy không được chết vì kho lịch
    sử hỏng — mọi lỗi thành một notice bền `HISTORY_COMPACTION_DEGRADED` kèm mã gốc.
    """
    from . import session_journal
    try:
        # `service(rt)` cũng nằm TRONG try: kho lịch sử dựng hỏng lúc khởi động thì nó ném ở đây,
        # và lượt nén vẫn phải đi tiếp như mọi kiểu hỏng khác của kho.
        history = service(rt)
        key = 'compaction:' + digest(encode(saved).encode())[:16]
        manifest = history.prepare_compaction(sid, saved, source_key=key,
                                              numbers=_compaction_numbers(event))
        history.commit_compaction(manifest['checkpointId'], compacted)
    except Exception as exc:
        code = _failure_code(exc, 'HISTORY_COMPACTION_FAILED')
        session_journal.note_gap(
            rt.store, sid, COMPACTION_DEGRADED_CODE,
            f'{COMPACTION_DEGRADED_CODE}: bản thô của lượt nén không vào được kho lịch sử ({code}; '
            f'{_failure_detail(exc)}) — lượt vẫn đi tiếp, nhưng lần nén này không có manifest đọc '
            'lại được', op='compaction_record')
        return {'recorded': False, 'checkpointId': None, 'projection': None, 'journal': None,
                'error': code}
    # Bản chiếu ghi SAU khi bản thô đã commit, và hỏng bản chiếu không được nói dối là bản thô hỏng
    # (§6: canonical còn bền thì bản chiếu được phép `degraded`). Hai tệp là hai lần ghi riêng, nên
    # hai lần hỏng cũng phải là hai mã riêng: `journal.md` hỏng mà báo là "bản chiếu không ghi xong"
    # thì lại là nói dối theo chiều ngược lại, đúng lúc `projection_status` trong DB nói `stored`.
    try:
        projection = export_projection(rt, sid, manifest['checkpointId'])
    except Exception as exc:
        code = _failure_code(exc, 'PROJECTION_FAILED')
        session_journal.note_gap(
            rt.store, sid, PROJECTION_DEGRADED_CODE,
            f'{PROJECTION_DEGRADED_CODE}: bản thô của lượt nén đã vào kho, nhưng bản đọc được trong '
            f'workspace thì không ghi xong ({code}; {_failure_detail(exc)})', op='compaction_projection')
        projection = {'canonicalStored': True, 'projectionStored': False,
                      'projectionError': code, 'skipped': None}
    else:
        # `HistoryProjection.export_compaction` tự bắt `(OSError, ValueError)` rồi **trả** dict
        # `projectionStored: false` chứ không ném, nên chỉ có `except` là bỏ lọt đúng ca hỏng thật:
        # lượt nén ghi hỏng bản chiếu mà không ai nói gì (L1d-A của đợt soát 2026-10-09 bắt được).
        # Vì thế phải soi lại dict trả về. `skipped` (workspace container) vẫn im lặng: bỏ qua là
        # chủ ý, không phải hỏng.
        if projection.get('projectionStored') is False and not projection.get('skipped'):
            raw_code = str(projection.get('errorCode') or '')
            code = raw_code if re.fullmatch(r'[A-Z][A-Z0-9_]{2,}', raw_code) else 'PROJECTION_FAILED'
            detail = str(projection.get('projectionError') or raw_code or code)[:160]
            session_journal.note_gap(
                rt.store, sid, PROJECTION_DEGRADED_CODE,
                f'{PROJECTION_DEGRADED_CODE}: bản thô của lượt nén đã vào kho, nhưng bản đọc được trong '
                f'workspace thì không ghi xong ({code}; {detail})', op='compaction_projection')
    journal = None
    if not projection.get('skipped'):
        try:
            journal = export_journal(rt, sid)
        except Exception as exc:
            code = _failure_code(exc, 'JOURNAL_EXPORT_FAILED')
            session_journal.note_gap(
                rt.store, sid, JOURNAL_DEGRADED_CODE,
                f'{JOURNAL_DEGRADED_CODE}: bản nén đã ghi xong, còn `journal.md` trong workspace '
                f'thì không ({code}; {_failure_detail(exc)})', op='compaction_journal')
    return {'recorded': True, 'checkpointId': manifest['checkpointId'], 'sourceKey': key,
            'messages': len(saved) if isinstance(saved, list) else None,
            'projection': projection, 'journal': journal, 'error': None}


def scope_target(rt, sid, scope):
    """Phạm vi công cụ/route: `self|parent|root|project`, không nhận id hay đường dẫn từ ngoài."""
    scope = scope or 'self'
    if scope == 'self':
        return 'self', None
    if scope == 'project':
        return 'project', None
    if scope == 'parent':
        parent = (rt.store.get(sid) or {}).get('parent_id')
        if not parent:
            raise HistoryError('HISTORY_SCOPE_DENIED')
        return 'self', parent
    if scope == 'root':
        return 'self', service(rt).bind_session(sid)['root_session_id']
    raise HistoryError('HISTORY_QUERY_INVALID')


def _kinds(value):
    if not value:
        return None
    if not isinstance(value, list):
        raise HistoryError('HISTORY_QUERY_INVALID')
    return [str(item)[:40] for item in value[:12]]


async def dispatch(rt, sid, name, args):
    """Cổng công cụ history. Sai phạm vi/lỗi con trỏ trả về mã hợp đồng, không ném vào lượt."""
    args = args if isinstance(args, dict) else {}
    try:
        history = service(rt)
        if name == 'history_list':
            scope, target = scope_target(rt, sid, args.get('scope'))
            return history.query_history(sid, scope=scope, session_id=target, agent_id=args.get('agentId'),
                                         kinds=_kinds(args.get('kinds')), cursor=args.get('cursor'),
                                         limit=args.get('limit') or 10, mode='list')
        if name == 'history_search':
            scope, target = scope_target(rt, sid, args.get('scope'))
            return history.query_history(sid, query=str(args.get('query') or ''), scope=scope, session_id=target,
                                         agent_id=args.get('agentId'), kinds=_kinds(args.get('kinds')),
                                         cursor=args.get('cursor'), limit=args.get('limit') or 10, mode='search')
        if name == 'history_read':
            ref = args.get('recordId') or args.get('historyRef')
            if not ref:
                raise HistoryError('HISTORY_QUERY_INVALID')
            return history.read_reference(sid, ref, offset=int(args.get('offset') or 0),
                                          limit=int(args.get('maxChars') or 16000))
        raise HistoryError('HISTORY_QUERY_INVALID')
    except HistoryError as exc:
        return {'is_error': True, 'errorCode': exc.code, 'error': str(exc)}
    except Exception as exc:
        return {'is_error': True, 'errorCode': 'HISTORY_SURFACE_FAILED',
                'error': f'{type(exc).__name__}: {exc}'[:300]}


def deletion_preview(rt, sid, body):
    body = body if isinstance(body, dict) else {}
    if (body.get('mode') or 'history_only') != 'history_only':
        raise HistoryError('DELETE_MODE_UNSUPPORTED')
    return service(rt).deletion_preview(
        sid, expected_revision=body.get('expectedRevision'), lessons=body.get('lessons'),
        extraction_required=bool(body.get('extractionRequired')),
        extraction_succeeded=bool(body.get('extractionSucceeded')), retained_refs=body.get('retainedRefs'))


def deletion_confirm(rt, sid, body):
    body = body if isinstance(body, dict) else {}
    if body.get('confirm') is not True or not body.get('operationId'):
        raise HistoryError('DELETE_REQUIRES_CARRY_FORWARD')
    # Cổng yên tĩnh và bản ghim chạy TRƯỚC mọi thay đổi, rồi việc đóng run nằm trong chính giao
    # dịch xoá: một lần xác nhận là đủ, và một lần từ chối không còn huỷ run oan.
    return service(rt).delete_with_capsule(sid, operation_id=str(body['operationId']),
                                           expected_revision=body.get('expectedRevision'), confirm=True)


def _run_closer(rt):
    """Đóng sổ mọi run chưa kết thúc của cây, dùng NGAY TRONG giao dịch của người gọi.

    Xoá phiên là quyết định của chủ: run không còn cơ hội chạy tiếp. Hàng `longtask_runs` còn
    `ready/running` sau khi phiên biến mất sẽ làm `recover()` mò vào một session không tồn tại,
    nên phải chốt trong cùng giao dịch. Hàm KHÔNG tự mở giao dịch — nó chạy bên trong giao dịch
    của `delete_with_capsule`, sau khi bản ghim đã khớp.
    """
    def close(db, ids):
        names = _tables(db)
        if 'longtask_runs' not in names:
            return 0
        marks = ','.join('?' for _ in ids)
        changed = db.execute(
            f"UPDATE longtask_runs SET state='cancelled',blocked_reason='HISTORY_DELETED',"
            f"revision=revision+1,stop_epoch=stop_epoch+1,lease_epoch=lease_epoch+1,"
            f"lease_owner=NULL,lease_expires=NULL,updated=? WHERE session_id IN ({marks}) "
            f"AND state NOT IN ('completed','cancelled','failed')", (time.time(), *ids)).rowcount
        if 'longtask_continuations' in names:
            db.execute(f"UPDATE longtask_continuations SET state='cancelled',updated=? "
                       f"WHERE run_id IN (SELECT run_id FROM longtask_runs WHERE session_id IN ({marks})) "
                       f"AND state IN ('pending','claimed','admitted')", (time.time(), *ids))
        return changed
    return close


def tree_ids(rt, sid):
    return _tree(rt, sid)
