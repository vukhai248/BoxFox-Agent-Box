"""H4: job model-visible trên delegate/sổ con hiện có, không thêm scheduler.

Chỉ backend bind admission sau các guard và slot của delegate. Handle process chưa
được executor hiện tại inspect/cancel theo identity nên bị từ chối. Notification
chỉ mở event waiter; không mở model turn. Stop/revoke thắng completion đến muộn.
"""
import asyncio
import json
import time
import uuid

from . import execution_kernel, tool_recovery, work_scope
from .harness_jobs import HarnessJobs, JOB_SCHEMA, CLOSED_STATES
from .limits import PEER_WAIT_SAFETY_SECONDS
from .orchestration_contracts import identifier, invalid, object_fields, text
from .work_policy import digest

JOB_TOOLS = frozenset({'start_job', 'get_job', 'subscribe_job', 'wait_jobs', 'cancel_job'})
STOP_KEY = 'controllerJobsStopped'


def exists(rt):
    if getattr(rt, 'store', None) is None:
        return False
    return rt.store.db.execute("SELECT 1 FROM sqlite_master WHERE name='harness_jobs' AND type='table'").fetchone() is not None


def service(rt):
    svc = getattr(rt, '_controller_jobs', None)
    if svc is None:
        svc = rt._controller_jobs = HarnessJobs(rt.store)
    return svc


def prepare(args):
    """Không nhận trường quyền/owner/handle từ caller; identity do backend cấp."""
    value = object_fields(args, 'request', ('kind', 'role', 'goal', 'ownership', 'invocationId'),
                          ('context', 'expect'))
    if value['kind'] != 'model':
        invalid('kind', 'executor has no inspectable/cancellable durable process handles', 'JOB_EXECUTOR_UNSUPPORTED')
    if value['ownership'] != 'controller':
        invalid('ownership', 'start_job requires explicit controller ownership', 'JOB_OWNERSHIP_REQUIRED')
    identifier(value['invocationId'], 'invocationId')
    identifier(value['role'], 'role')
    text(value['goal'], 'goal', 4000)
    for field in ('context', 'expect'):
        if field in value:
            text(value[field], field, 4000)
    return dict(value)


def admission(rt, session, request, *, new=True):
    """Recheck canonical parent/role/scope/quyền; không tin capabilityRef của model."""
    current = rt.store.get(session['id'])
    config = current.get('config') or {}
    if current.get('parent_id') or current.get('role') != 'orchestrator':
        raise PermissionError('JOB_FORBIDDEN: only the root controller starts jobs')
    if new:
        from .tool_contracts import peer_mesh_enabled
        if not peer_mesh_enabled():
            raise PermissionError('JOB_EXECUTOR_UNSUPPORTED: async delegation requires the existing peer mesh')
    if config.get(STOP_KEY) or current.get('status') in ('cancelled', 'interrupted'):
        raise PermissionError('JOB_STOPPED: controller was stopped')
    if not {'start_job', 'delegate_task'} <= tool_recovery.owner_tools(rt.store, current):
        raise PermissionError('WORK_CAPABILITY_REVOKED: controller job delegation revoked')
    configured = next((r for r in config.get('subagents', []) if r['id'] == request['role'] and r.get('enabled', True)), None)
    if not configured:
        raise PermissionError('WORK_CAPABILITY_REVOKED: specialist disabled')
    delegated = delegate_args(request)
    execution_kernel.guard_tool(rt, current, 'delegate_task', delegated)
    work_scope.check_delegate(work_scope.resolve(rt, current), request['role'])
    return current


def delegate_args(request):
    return {key: request[key] for key in ('role', 'goal', 'context', 'expect') if key in request} | {'wait': False}


def request_hash(session, request):
    return digest({'action': 'runtime_start_job', 'ownerId': session['id'], 'request': request})


def replay(rt, session, request):
    cached = service(rt)._cached(session['id'], request['invocationId'], request_hash(session, request))
    if cached is None:
        return None
    job = service(rt).get(cached['jobId'])
    return {'status': 'replayed', 'sessionId': job['admission']['childSessionId'], 'job': job}


def bind(rt, session, request, child_id):
    """Chỉ gọi sau child_start, TRƯỚC start: mất process không replay mutation."""
    current = admission(rt, session, request)
    child = rt.store.child(child_id)
    if child is None or child['parent_id'] != current['id'] or child['role'] != request['role'] or child['status'] != 'started':
        invalid('childSessionId', 'canonical child binding missing', 'JOB_ADMISSION_REQUIRED')
    capability = {'epoch': execution_kernel.capability_epoch(rt, current),
                  'runtimeRequest': request, 'childStarted': child['started'],
                  'admissionId': 'delegate-' + child_id}
    from . import context_surface
    checkpoint = context_surface.handoff(rt, current)
    payload = {'schema': JOB_SCHEMA, 'kind': 'model', 'ownership': 'controller',
               'controllerId': current['id'], 'childSessionId': child_id}
    # Sổ job giữ locator text; JSON ghim owner/version/hash, không chỉ artifactId.
    payload['checkpointRef'] = json.dumps(checkpoint['ref'], sort_keys=True, separators=(',', ':'))
    job = service(rt).start(current['id'], payload,
        capability, request['invocationId'], runtime_request_hash=request_hash(current, request))
    service(rt).append(job['jobId'], {'kind': 'progress', 'state': 'running', 'intermediate': True})
    return service(rt).get(job['jobId'])


def _bound(rt, child_id):
    if not exists(rt):
        return []
    rows = rt.store.db.execute("SELECT * FROM harness_jobs WHERE kind='model' AND state IN ('queued','running','waiting')").fetchall()
    svc = service(rt)
    return [svc.get(row['job_id']) for row in rows if svc._child_session(row) == child_id]


def owns_child(rt, child_id):
    """Chỉ admitted controller job giữ con qua lượt; idle nói chung không được giữ."""
    try:
        jobs = _bound(rt, child_id)
    except (KeyError, ValueError):
        return False
    for job in jobs:
        try:
            if job['ownership'] != 'controller' or job['ownerId'] != job['controllerId'] or job['controlState']:
                continue
            child = rt.store.child(child_id)
            capability = job['admission']['capabilityRef']
            request = capability.get('runtimeRequest')
            if not isinstance(request, dict) or child is None or child['parent_id'] != job['ownerId'] or child['started'] != capability.get('childStarted'):
                continue
            parent = rt.store.get(job['ownerId'])
            admission(rt, parent, request, new=False)
            if job['capabilityEpoch'] != execution_kernel.capability_epoch(rt, parent):
                continue
            return True
        except (KeyError, ValueError, PermissionError):
            continue
    return False


def guard_child(rt, current, name):
    """Revoke giữa lượt chặn effect kế tiếp ngay cả khi policy adaptive tắt."""
    if current.get('parent_id') and name in JOB_TOOLS:
        raise PermissionError('JOB_FORBIDDEN: only the root controller uses job tools')
    jobs = _bound(rt, current['id']) if current.get('parent_id') else []
    if jobs and (not owns_child(rt, current['id']) or name not in tool_recovery.owner_tools(rt.store, current)):
        for job in jobs:
            if not job['controlState']:
                service(rt).cancel(job['jobId'], job['revision'], 'controller stopped or capability revoked')
        raise PermissionError('WORK_CAPABILITY_REVOKED: controller job no longer admitted')


def guard_request(rt, sid):
    """Main gọi trước model request (và sau awaited admission): không cấp lượt mới."""
    current = rt.store.get(sid)
    from . import job_wake
    job_wake.guard_active(rt, sid)
    jobs = _bound(rt, sid) if current.get('parent_id') else []
    if jobs and not owns_child(rt, sid):
        for job in jobs:
            if not job['controlState']:
                service(rt).cancel(job['jobId'], job['revision'], 'model request admission revoked')
        raise PermissionError('WORK_CAPABILITY_REVOKED: no new model request for revoked controller job')
    return bool(jobs)


def project_child(rt, child_id):
    """Projection dedupe trên canonical close; không làm hỏng bộ đóng con."""
    try:
        child = rt.store.child(child_id)
        if child is None:
            return
        for job in _bound(rt, child_id):
            started = job['admission']['capabilityRef'].get('childStarted')
            if started is None:
                continue  # bản thư viện cũ không tự nhận admission runtime mới
            if started != child['started']:
                service(rt).append(job['jobId'], {'kind': 'result', 'state': 'interrupted',
                    'reason': 'canonical child identity changed; no replay or cancellation of new attempt'})
                notify(rt, job['ownerId'])
                continue
            if child['finished'] is None:
                continue
            state = {'completed': 'succeeded', 'partial': 'partial', 'cancelled': 'cancelled',
                     'interrupted': 'interrupted'}.get(child['status'], 'failed')
            if child.get('reason') == 'RESTART':
                state = 'interrupted'
            svc = service(rt)
            if child.get('reason') != 'RESTART' and not owns_child(rt, child_id) and not job['controlState']:
                svc.cancel(job['jobId'], job['revision'], 'controller capability revoked before completion')
            with svc._write():
                row = svc._job(job['jobId'])
                if row['state'] in CLOSED_STATES:
                    continue
                svc._append_locked(row, {'kind': 'result', 'state': state,
                    'payload': {'sessionId': child_id, 'childStatus': child['status'],
                                'childReason': child.get('reason'), 'receipt': 'canonical_children'},
                    'reason': child.get('reason') or 'canonical child closed'}, None)
            # Commit trước notify; chỉ event waiter, không model turn.
            notify(rt, job['ownerId'])
    except Exception as exc:  # bộ đóng con không được chết vì projection
        from ..observability.system_log import system_log
        system_log.write('job.projection_failed', level='warn', session_id=child_id, message=str(exc)[:300])


def notify(rt, owner_id):
    for event in getattr(rt, '_job_waiters', {}).get(owner_id, set()):
        event.set()
    from . import job_wake
    job_wake.notify(rt, owner_id)


def park_after_batch(rt, sid):
    """Main gọi khi wait_jobs timedOut và không có việc độc lập; đóng _run sau hook."""
    from . import job_wake
    return job_wake.park_after_batch(rt, sid)


def reconcile_startup(rt):
    """Async model handle không sống qua restart, kể cả canonical row còn started."""
    if exists(rt):
        from . import job_wake
        job_wake.startup(rt)
        service(rt).reconcile(restart=True)


def on_stop(rt, sid):
    """Ghi barrier/cancel trước await task: Stop luôn thắng admission đang chờ slot."""
    if not exists(rt):
        return
    from . import job_wake
    job_wake.invalidate(rt, sid, 'user Stop')
    current = rt.store.get(sid)
    if not current.get('parent_id'):
        config = dict(current['config'], **{STOP_KEY: True})
        rt.store.update_config(sid, config)
    for job in service(rt).open_jobs():
        if job['ownerId'] == sid or job['admission'].get('childSessionId') == sid:
            service(rt).cancel(job['jobId'], job['revision'], 'user Stop')


def begin_turn(rt, sid):
    from . import job_wake
    job_wake.invalidate(rt, sid, 'new explicit owner turn', 'superseded')
    current = rt.store.get(sid)
    if not current.get('parent_id') and (current.get('config') or {}).get(STOP_KEY):
        config = dict(current['config'])
        config.pop(STOP_KEY, None)
        rt.store.update_config(sid, config)


def owned(rt, session, job_id):
    identifier(job_id, 'jobId')
    if not exists(rt):
        invalid('jobId', 'unknown job', 'JOB_UNKNOWN')
    job = service(rt).get(job_id)
    if session.get('parent_id') or session['id'] != job['ownerId'] or session['id'] != job['controllerId']:
        raise PermissionError('JOB_FORBIDDEN: only the admitted owner/controller can read or control this job')
    child_id = job['admission'].get('childSessionId')
    if child_id:
        project_child(rt, child_id)
    return service(rt).get(job_id)


async def handle(rt, session, name, args):
    """Bề mặt thật: start dùng delegate; wait park trên event hữu hạn, không model polling."""
    args = args if isinstance(args, dict) else {}
    if name == 'start_job':
        request = prepare(args)
        current = admission(rt, session, request)
        cached = replay(rt, current, request)
        if cached is not None:
            return cached
        return await rt.delegate(current, delegate_args(request), job_request=request)
    if name == 'wait_jobs':
        return await _wait(rt, session, args)
    job = owned(rt, session, args.get('jobId'))
    svc = service(rt)
    if name == 'get_job':
        return svc.get(job['jobId'], args.get('cursor'))
    if name == 'subscribe_job':
        predicate = args.get('predicate')
        if predicate not in (None, 'result'):
            invalid('predicate', 'model jobs currently support terminal result subscriptions only', 'JOB_PREDICATE_UNSUPPORTED')
        return svc.subscribe(job['jobId'], session['id'], predicate, args.get('afterSeq', 0))
    if name == 'cancel_job':
        child = rt.store.child(job['admission']['childSessionId'])
        if child is None or child['started'] != job['admission']['capabilityRef'].get('childStarted'):
            invalid('jobId', 'canonical child identity is unavailable; cannot cancel another attempt', 'JOB_HANDLE_STALE')
        receipt = svc.cancel(job['jobId'], args.get('expectedRevision'), args.get('reason'))
        from .research_runtime import cancel_child
        child_id = job['admission']['childSessionId']
        result = await cancel_child(rt, session, {'sessionId': child_id, 'reason': args['reason']})
        project_child(rt, child_id)
        return dict(receipt, child=result, job=owned(rt, session, job['jobId']))
    raise PermissionError('JOB_TOOL_UNKNOWN: ' + name)


async def _wait(rt, session, args):
    ids = args.get('jobIds')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 100:
        invalid('jobIds', 'expected 1-100 job IDs')
    for job_id in ids:
        owned(rt, session, job_id)
    timeout = args.get('timeoutSeconds', PEER_WAIT_SAFETY_SECONDS)
    if type(timeout) not in (int, float) or not 0 <= timeout <= PEER_WAIT_SAFETY_SECONDS:
        invalid('timeoutSeconds', 'finite timeout exceeds the existing peer wait safety bound')
    svc, owner = service(rt), session['id']
    token = 'wait-' + uuid.uuid4().hex
    event = asyncio.Event()
    waiters = getattr(rt, '_job_waiters', None)
    if waiters is None:
        waiters = rt._job_waiters = {}
    svc.acquire_wake(owner, token)
    waiters.setdefault(owner, set()).add(event)
    # Outbox consumer is the canonical owner; lock holder is a backend invocation,
    # không dùng model consumerId để giành khoá của lượt khác.
    deadline = time.monotonic() + timeout
    try:
        while True:
            event.clear()
            for job_id in ids:
                owned(rt, session, job_id)
            result = svc.wait(ids, args.get('mode', 'any'), args.get('afterSeq', 0),
                              consumer_id=owner, owner_id=owner, lock_token=token)
            if result['ready'] or time.monotonic() >= deadline:
                if not result['ready']:
                    from . import job_wake
                    job_wake.candidate(rt, owner, ids, args.get('mode', 'any'))
                return dict(result, timedOut=not result['ready'])
            remaining = min(deadline - time.monotonic(), svc.wake_ttl_seconds / 2)
            try:
                await asyncio.wait_for(event.wait(), remaining)
            except asyncio.TimeoutError:
                if time.monotonic() >= deadline:
                    from . import job_wake
                    job_wake.candidate(rt, owner, ids, args.get('mode', 'any'))
                    return dict(result, timedOut=True)
            svc.acquire_wake(owner, token)
    finally:
        waiters[owner].discard(event)
        if not waiters[owner]:
            waiters.pop(owner, None)
        svc.release_wake(owner, token)
