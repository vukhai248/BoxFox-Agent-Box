"""H4: subscription bền cho main đã park; chỉ nối vào rt.start/tasks hiện có.

Không scheduler/poll/heartbeat. Claim commit trước start; restart không replay
claim có outcome chưa biết. Dữ liệu result không là user intent hoặc quyền mới.
"""
import json
import uuid

from . import execution_kernel, tool_recovery, work_scope
from .orchestration_contracts import invalid

TABLE = 'harness_parked_owners'
COLUMNS = {'park_id', 'schema_version', 'owner_id', 'source_turn', 'jobs_json', 'mode',
           'state', 'wake_invocation', 'events_json', 'reason'}


def exists(rt):
    return rt.store.db.execute("SELECT 1 FROM sqlite_master WHERE name=? AND type='table'", (TABLE,)).fetchone() is not None


def service(rt):
    columns = {r['name'] for r in rt.store.db.execute(f'PRAGMA table_info({TABLE})')}
    if columns and not COLUMNS <= columns:
        invalid('park', 'unsupported persisted parked owner schema', 'JOB_SCHEMA_UNSUPPORTED')
    if not columns:
        rt.store.db.execute(f'CREATE TABLE {TABLE} ('
            'park_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, owner_id TEXT NOT NULL, '
            'source_turn INTEGER NOT NULL, jobs_json TEXT NOT NULL, mode TEXT NOT NULL, '
            'state TEXT NOT NULL, wake_invocation TEXT, events_json TEXT NOT NULL, reason TEXT, '
            'UNIQUE(owner_id,source_turn))')
        rt.store.db.commit()


def row(rt, park_id):
    value = rt.store.db.execute(f'SELECT * FROM {TABLE} WHERE park_id=?', (park_id,)).fetchone()
    if value is None or value['schema_version'] != 1:
        invalid('park', 'unknown or unsupported parked receipt', 'JOB_SCHEMA_UNSUPPORTED')
    try:
        ids, events = json.loads(value['jobs_json']), json.loads(value['events_json'])
        if not isinstance(ids, list) or not 1 <= len(ids) <= 100 or not all(isinstance(i, str) for i in ids) or not isinstance(events, list):
            raise ValueError('invalid selected jobs/events')
    except (ValueError, TypeError):
        invalid('park', 'corrupt parked receipt', 'JOB_RECORD_CORRUPT')
    return dict(value), ids, events


def adaptive(rt, sid):
    from . import job_surface
    owner = rt.store.get(sid)
    return (execution_kernel._policy(owner) is not None
            and not owner.get('parent_id') and owner.get('role') == 'orchestrator')


def validate(rt, value):
    """Không waiver ancestor: owner root, subscription do canonical wait tạo."""
    from . import job_surface
    owner = rt.store.get(value['owner_id'])
    if not adaptive(rt, owner['id']):
        raise PermissionError('JOB_WAKE_DISABLED: owner has no adaptive policy or is not the root')
    if owner['config'].get(job_surface.STOP_KEY) or owner['status'] in ('cancelled', 'interrupted', 'awaiting_decision', 'failed'):
        raise PermissionError('JOB_STOPPED: parked owner no longer admitted')
    if 'wait_jobs' not in tool_recovery.owner_tools(rt.store, owner):
        raise PermissionError('WORK_CAPABILITY_REVOKED: wait subscription revoked')
    binding = work_scope.turn_binding(rt, owner)
    if binding and binding.get('intent') and not binding.get('runId'):
        # Ý định slash chỉ thuộc MỘT lượt; wake không được cấp lại phạm vi ấy.
        raise PermissionError('JOB_WAKE_FORBIDDEN: slash intent scope is single-turn; '
                              'the owner must open a new explicit turn')
    _, ids, _ = row(rt, value['park_id'])
    execution_kernel.guard_tool(rt, owner, 'wait_jobs', {'jobIds': ids})
    for jid in ids:
        job = job_surface.service(rt).get(jid)
        request = job['admission']['capabilityRef'].get('runtimeRequest')
        if (job['ownerId'] != owner['id'] or job['controllerId'] != owner['id']
                or job['ownership'] != 'controller' or not isinstance(request, dict)
                or job['controlState'] or job['state'] in ('cancelled', 'interrupted')
                or job['capabilityEpoch'] != execution_kernel.capability_epoch(rt, owner)):
            raise PermissionError('WORK_CAPABILITY_REVOKED: parked job control/identity revoked')
        job_surface.admission(rt, owner, request, new=False)
        child = rt.store.child(job['admission']['childSessionId'])
        if child is None or child['parent_id'] != owner['id'] or child['started'] != job['admission']['capabilityRef'].get('childStarted'):
            raise PermissionError('JOB_HANDLE_STALE: parked job canonical identity changed')
    return owner


def candidate(rt, sid, ids, mode):
    """Chỉ timeout `_wait` canonical; hook cuối batch mới kích hoạt park."""
    if not adaptive(rt, sid):
        return None
    turn = rt.active_turn.get(sid)
    if type(turn) is not int or turn < 1:
        return None  # không có lượt thật thì không có thẩm quyền đánh thức
    service(rt)
    from . import job_surface
    with job_surface.service(rt)._write():
        value = rt.store.db.execute(f'SELECT * FROM {TABLE} WHERE owner_id=? AND source_turn=?', (sid, turn)).fetchone()
        selected = json.dumps(list(dict.fromkeys(ids)))
        if value and value['state'] != 'candidate':
            return value['park_id']  # đã parked/đã wake: không ghi đè lựa chọn cũ
        if value:
            rt.store.db.execute(f'UPDATE {TABLE} SET jobs_json=?,mode=? WHERE park_id=?',
                                (selected, mode, value['park_id']))
            return value['park_id']
        pid = 'park-' + uuid.uuid4().hex
        rt.store.db.execute(f'INSERT INTO {TABLE} VALUES(?,1,?,?,?,?,?,NULL,?,NULL)',
            (pid, sid, turn, selected, mode, 'candidate', '[]'))
    return pid


def park_after_batch(rt, sid):
    """Main chỉ gọi khi hết việc độc lập và `wait_jobs` đã timedOut.

    Sau đó main đóng `_run` như bình thường; callback của task chờ đúng lúc đóng ấy.
    Kết quả về giữa timeout và park được đọc lại ngay sau khi lượt đóng.
    """
    if not exists(rt) or not adaptive(rt, sid):
        return None
    turn = rt.active_turn.get(sid)
    value = rt.store.db.execute(f'SELECT * FROM {TABLE} WHERE owner_id=? AND source_turn=? AND state=\'candidate\'', (sid, turn)).fetchone()
    if value is None:
        return None
    from . import job_surface
    try:
        with job_surface.service(rt)._write():
            validate(rt, value)
            rt.store.db.execute(f'UPDATE {TABLE} SET state=\'parked\' WHERE park_id=? AND state=\'candidate\'', (value['park_id'],))
    except Exception as exc:  # hook cuối batch không được làm chết lượt main
        invalidate(rt, sid, str(exc)[:200], 'blocked')
        from ..observability.system_log import system_log
        system_log.write('job.park_failed', level='warn', session_id=sid, message=str(exc)[:300])
        return None
    task = rt.tasks.get(sid)
    if task is not None and not task.done():
        task.add_done_callback(lambda _: notify(rt, sid))
    else:
        notify(rt, sid)
    return {'parkId': value['park_id'], 'state': 'parked', 'jobIds': json.loads(value['jobs_json'])}


def invalidate(rt, sid, reason, state='stopped'):
    if not exists(rt):
        return
    from . import job_surface
    with job_surface.service(rt)._write():
        rt.store.db.execute(f'UPDATE {TABLE} SET state=?,reason=? WHERE owner_id=? '
            "AND state IN ('candidate','parked','wake_claimed','started')", (state, reason, sid))


def startup(rt):
    if exists(rt):
        service(rt)
        from . import job_surface
        with job_surface.service(rt)._write():
            rt.store.db.execute(f'UPDATE {TABLE} SET state=\'interrupted\',reason=\'restart: no autonomous replay\' '
                "WHERE state IN ('candidate','parked','wake_claimed')")


def notify(rt, sid):
    """Callback đồng bộ, không I/O model: chỉ `rt.start` mở task model."""
    if not exists(rt):
        return
    try:
        try_wake(rt, sid)
    except Exception as exc:
        from ..observability.system_log import system_log
        system_log.write('job.wake_failed', level='warn', session_id=sid, message=str(exc)[:300])


def try_wake(rt, sid):
    from . import job_surface
    task = rt.tasks.get(sid)
    if task is not None and not task.done():
        return None  # không mở lượt thứ hai chồng lên, kể cả khi status đã completed
    value = rt.store.db.execute(f'SELECT * FROM {TABLE} WHERE owner_id=? AND state=\'parked\' ORDER BY source_turn DESC LIMIT 1', (sid,)).fetchone()
    if value is None:
        return None
    value, ids, _ = row(rt, value['park_id'])
    try:
        owner = validate(rt, value)
        if owner['status'] == 'running':
            return None
        if rt.active_turn.get(sid) != value['source_turn']:
            invalidate(rt, sid, 'owner has a newer turn', 'superseded')
            return None
    except (PermissionError, ValueError) as exc:
        invalidate(rt, sid, str(exc), 'blocked')
        return None
    svc = job_surface.service(rt)
    token = 'wake-' + value['park_id']
    try:
        svc.acquire_wake(sid, token)
    except ValueError as exc:
        if getattr(exc, 'code', None) == 'JOB_WAKE_LOCKED':
            return None
        raise
    try:
        with svc._write():
            fresh, ids, _ = row(rt, value['park_id'])
            if fresh['state'] != 'parked':
                return None
            validate(rt, fresh)
            placeholders = ','.join('?' for _ in ids)
            pending = rt.store.db.execute('SELECT 1 FROM harness_wake_outbox '
                f"WHERE consumer_id=? AND job_id IN ({placeholders}) AND predicate='result' AND status='pending' LIMIT 1",
                (sid, *ids)).fetchone()
            if pending is None:
                return None
            if value['mode'] == 'all' and any(svc.get(jid)['state'] not in job_surface.CLOSED_STATES for jid in ids):
                return None
            # Snapshot và cursor được ghi cùng lúc với claim. Không heartbeat/log/progress.
            result = svc.wait(ids, value['mode'], consumer_id=sid, owner_id=sid, lock_token=token)
            if not result['ready'] or not result['events']:
                return None
            invocation = 'job-wake-' + value['park_id']
            rt.store.db.execute(f'UPDATE {TABLE} SET state=\'wake_claimed\',wake_invocation=?,events_json=? '
                "WHERE park_id=? AND state='parked'", (invocation, json.dumps(result['events']), value['park_id']))
        try:
            # Không await giữa claim, recheck start và gắn vào rt.tasks.
            task = rt.start(sid, 'Controller job result', invocation_id=invocation, job_wake=value['park_id'])
        except PermissionError as exc:
            invalidate(rt, sid, str(exc)[:200], 'blocked')  # từ chối dứt khoát, chưa có effect
            return None
        except Exception as exc:
            invalidate(rt, sid, 'start outcome unknown: ' + str(exc)[:200], 'start_unknown')
            return None
        return task
    finally:
        svc.release_wake(sid, token)


def before_start(rt, sid, pid, invocation):
    """`rt.start` gọi TRƯỚC khi đổi trạng thái; id opaque do backend cấp, không nhận claim của caller."""
    value, ids, events = row(rt, pid)
    if value['owner_id'] != sid or value['state'] != 'wake_claimed' or value['wake_invocation'] != invocation:
        raise PermissionError('JOB_WAKE_FORBIDDEN: no claimed canonical wake receipt')
    owner = validate(rt, value)
    task = rt.tasks.get(sid)
    if (task is not None and not task.done()) or rt.active_turn.get(sid) != value['source_turn']:
        raise PermissionError('JOB_WAKE_FORBIDDEN: busy or superseded owner')
    data = {'parkId': pid, 'jobIds': ids, 'events': events, 'invocationId': invocation,
            'note': 'Committed controller job data only; no new user intent, grant or spending consent.'}
    binding = work_scope.turn_binding(rt, owner)
    # Chỉ mang theo binding RUN canonical; ý định slash đã bị validate từ chối.
    carried = {'runId': binding['runId'], 'reason': 'harness'} if binding and binding.get('runId') else None
    return data, carried


def after_start(rt, sid, pid):
    from . import job_surface
    with job_surface.service(rt)._write():
        rt.store.db.execute(f'UPDATE {TABLE} SET state=\'started\' WHERE park_id=? AND state=\'wake_claimed\'', (pid,))


def guard_active(rt, sid):
    if not exists(rt):
        return
    invocation = rt.turn_invocations.get(sid)
    if not invocation or not invocation.startswith('job-wake-'):
        return
    value = rt.store.db.execute(f'SELECT * FROM {TABLE} WHERE owner_id=? AND wake_invocation=?', (sid, invocation)).fetchone()
    if value is None or value['state'] != 'started':
        raise PermissionError('JOB_WAKE_FORBIDDEN: invalid active controller wake')
    validate(rt, value)
