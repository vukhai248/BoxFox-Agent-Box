"""Bề mặt task model-visible: `task_list`, `task_get`, `task_send`, `task_abandon`.

Kế hoạch v1 §4. Đây là lớp mỏng nối `task_service` (kho bền vững) vào runtime:

- `enabled()` — công tắc giết `BOXFOX_TASK_SURFACE`, mặc định BẬT từ v2 (#6599); tắt tường minh bằng `off` thì công cụ không được
  quảng cáo (`turn_profile_base`) và `dispatch` từ chối thẳng, nên phiên cũ không đổi hành vi.
- `handle(rt, session, name, args)` — bốn handler, chỉ gọi hàm đã có của `task_service` và
  `research_runtime.cancel_child`; không tự ghi bảng nào.
- Phân quyền: chỉ phiên gốc (owner/controller) được `send`/`abandon`; phiên con chỉ đọc task gắn
  với chính nó. Không cấp quyền vì "cùng session root".

Bất biến:

1. `task_send` ack nghĩa là **đã nhận bền vững**, KHÔNG phải con đã đọc/dùng (khác `child_deliveries`).
2. `task_abandon` tách "dừng thực thi" khỏi "kết thúc nhu cầu": nếu còn attempt đang mở thì gọi
   đúng đường `cancel_child` hiện có và trả biên nhận huỷ; không xoá artifact/check/usage.
3. Trùng `messageId`/`invocationId` không tạo hiệu ứng mới (khoá idempotency của `task_service`).
4. Mutation có kết quả không rõ không replay — `task_*` đều là công cụ unsafe, không nằm trong
   `REPLAY_SAFE`.

Theo dõi lượt thử lại (follow-up) của `delegate_task` — ngữ nghĩa đã chọn:

- Một lời gọi mang CÙNG `invocationId` của hợp đồng là một lần THỬ LẠI cùng nhiệm vụ: `create`
  trả lại hàng task cũ (không sinh task/alias thứ hai), và `open_delegate` đọc lại revision HIỆN
  TẠI — `create` chỉ phát lại bản ghi LÚC TẠO nên nếu tin vào số cũ thì mọi lần thử lại đều chết
  ở `bind_attempt` bằng `TASK_REVISION_CONFLICT`.
- Nếu task còn attempt đang mở, lần thử lại bị TỪ CHỐI bằng mã hợp đồng (`TASK_ATTEMPT_CONFLICT`,
  từ chỉ mục attempt đang hoạt động) và runtime đóng đúng con vừa `child_start` bằng lý do
  `TASK_BIND_FAILED` rồi nhả slot fan-out — không để lại con mồ côi hay slot rò.
- Khi attempt trước đã đóng (đã chiếu từ biên nhận của con), cùng lời gọi đó mở attempt MỚI trên
  đúng task ấy — follow-up đi qua admission, không tạo task/alias thứ hai.
- Hợp đồng KHÁC (`invocationId` mới) với cùng `taskId` bị kho từ chối (`TASK_ALIAS_CONFLICT`):
  hợp đồng, không phải alias, là danh tính của nhiệm vụ.
"""


from . import execution_kernel, feature_switches, research_runtime, work_scope
from .orchestration_contracts import ContractError, invalid
from .task_service import TaskService

#: Bốn công cụ của bề mặt này. `schemas_for` gỡ cả bốn khi công tắc tắt (khuôn `PEER_TOOLS`).
TASK_TOOLS = frozenset({'task_list', 'task_get', 'task_send', 'task_abandon'})

SWITCH = 'BOXFOX_TASK_SURFACE'

#: Trần trang cho `task_list`/`task_get` khi model không nói gì.
PAGE_LIMIT = 20
MAX_LIMIT = 100

#: Lý do đóng con khi `bind_attempt` hỏng (task đã có attempt mở, revision đổi giữa chừng, ...):
#: con vừa `child_start` nhưng chưa từng chạy — đóng ngay bằng lý do hợp đồng để không thành con
#: mồ côi và không giữ slot fan-out.
BIND_FAILED_REASON = 'TASK_BIND_FAILED'


def enabled(env=None):
    """Bề mặt task: đặt tường minh > khóa tổng `BOXFOX_REFORM` > mặc định BẬT từ v2 (#6599), tắt tường minh bằng `off`.

    `env` là giá trị thô của test; truyền vào thì thắng mọi thứ (giữ nguyên khuôn cũ).
    """
    if env is not None:
        return str(env or '').strip().lower() == 'on'
    return feature_switches.member_switch(SWITCH)


def service(rt):
    """`TaskService` của runtime này, với resolver đọc run từ Work Graph hiện có."""
    return TaskService(rt.store, lambda owner_id, run_id: _resolve_run(rt, owner_id, run_id))


def open_delegate(rt, session, args):
    """Tạo task cho một lần `delegate_task` có hợp đồng, trước khi con được sinh.

    Trả `None` khi công tắc tắt, khi lượt này không phải main (chỉ phiên GỐC tạo task), hoặc khi
    lời gọi không mang `task`. Hợp đồng đi NGUYÊN VĂN qua `TaskContract.parse`; `invocationId`
    trong hợp đồng là khoá idempotency, nên thử lại cùng một lời gọi không sinh task thứ hai.

    Ghi task KHÔNG cấp quyền chạy: quyền vẫn do các cổng hiện có quyết định, và attempt chỉ được
    ghi sau khi con thật sự được admit (`bind_attempt`).
    """
    if not enabled():
        return None
    contract = (args or {}).get('task')
    if contract is None:
        return None
    if session.get('parent_id'):
        return None
    if not isinstance(contract, dict):
        invalid('task', 'expected a boxfox-task-contract/1 object')
    if contract.get('role') != args.get('role'):
        invalid('task.role', 'contract role must match the delegated role', 'TASK_DELEGATE_ROLE_MISMATCH')
    root = _root_id(rt, session)
    run_id = _run_id(rt, session, args)
    if not run_id:
        invalid('runId', 'no canonical run is bound to this turn', 'TASK_SURFACE_NO_RUN')
    svc = service(rt)
    created = svc.create(root, run_id, dict(contract), controller_id=root)
    # `create` phát lại bản ghi LÚC TẠO theo `invocationId`; revision đã nhích nếu task từng nhận
    # attempt. Trả revision HIỆN TẠI để lần bind sau không chết vì số cũ (follow-up còn đường).
    current = svc.get(root, run_id, created['taskKey'])
    return {'taskKey': current['taskKey'], 'taskId': current['taskId'], 'revision': current['revision'],
            'runId': run_id, 'ownerId': root}


def bind_attempt(rt, session, opened, child_id):
    """Ghi attempt của con vừa được admit vào task vừa tạo. `opened is None` ⇒ no-op.

    `capabilityEpoch` đọc từ ĐÚNG một nguồn (`execution_kernel.capability_epoch`); bề mặt không
    tự đặt số. `admissionId` gắn với phiên con nên một con chỉ có một admission cho mỗi lần admit.
    """
    if opened is None:
        return None
    return service(rt).record_attempt(
        opened['ownerId'], opened['runId'], opened['taskKey'], invocation_id='delegate-' + child_id,
        expected_revision=opened['revision'], session_id=child_id, admission_id='admission-' + child_id,
        capability_epoch=execution_kernel.capability_epoch(rt, session))


def resume_attempt(rt, session, child_id, attempt_no, turn=0):
    """H11 — con được GỌI LẠI: mở attempt MỚI trên CÙNG session con (attempt_seq kế tiếp).

    `TaskService.record_attempt` đã dựng sẵn cho ca này ("A resumed legacy child may reuse its
    session ID"): hàng `children` vừa được `child_start` mở lại nên `started` là mốc MỚI, và điều
    kiện `previous['started_at'] != child['started']` chính là dấu hiệu con đã được mở lại. Con
    chưa từng gắn task (công tắc tắt, hoặc `delegate_task` không mang hợp đồng) ⇒ no-op.

    Idempotency key mang CẢ lượt của cha (`resume-<con>-<lượt>-<n>`): vòng soát H11 đo được rằng
    chỉ `resume-<con>-<n>` làm lời gọi lại ở lượt thứ hai trùng key với lượt đầu — kho task từ
    chối bằng `TASK_INVOCATION_CONFLICT` và attempt mới im lặng biến mất.
    """
    if not enabled() and not _task_store_exists(rt):
        return None
    row = rt.store.db.execute(
        'SELECT t.task_key AS task_key, t.run_id AS run_id, t.owner_id AS owner_id, '
        't.revision AS revision FROM harness_tasks t JOIN harness_task_attempts a '
        'ON a.task_key=t.task_key WHERE a.session_id=? ORDER BY a.attempt_seq DESC LIMIT 1',
        (child_id,)).fetchone()
    if row is None:
        return None
    key = f'resume-{child_id}-{int(turn or 0)}-{attempt_no}'
    return service(rt).record_attempt(
        row['owner_id'], row['run_id'], row['task_key'],
        invocation_id=key, expected_revision=row['revision'],
        session_id=child_id, admission_id=key,
        capability_epoch=execution_kernel.capability_epoch(rt, session))


def project_child(rt, child_id):
    """Ghim kết cục của một con vào attempt đang mở của nó, nếu con đó có task.

    Gọi từ các bộ đóng con HIỆN CÓ (`close_detached_child`, `cancel_child`, người dọn T7). Hàm
    này không bao giờ ném: đóng con không được hỏng vì sổ task. Con chưa từng gắn task ⇒ no-op.

    Công tắc TẮT và kho CHƯA TỪNG có bảng task ⇒ no-op trước khi dựng `TaskService`: mỗi lần dựng
    chạy DDL (`executescript`) và có thể chốt giao dịch đang mở của người gọi, nên một triển khai
    chưa bao giờ bật công tắc không phải trả giá đó. Kho đã từng tạo task thì vẫn chiếu (ưu tiên
    toàn vẹn sổ).
    """
    try:
        if not enabled() and not _task_store_exists(rt):
            return None
        child = rt.store.child(child_id)
        if child is None or child['finished'] is None:
            return None
        return service(rt).close_attempt(child_id, child['status'], child['reason'])
    except Exception as exc:  # pragma: no cover - chốt chặn cuối
        from ..observability.system_log import system_log
        system_log.write('task.attempt_projection_failed', level='warn', session_id=child_id,
                         message=str(exc)[:300])
        return None


def current_revision(rt, opened):
    """Revision HIỆN TẠI của task trong `opened` — đọc lại ngay trước khi quảng cáo.

    `create` phát lại bản ghi lúc tạo (revision cũ), còn `bind_attempt` và chiếu kết cục đều nhích
    revision, nên biên nhận phải hỏi kho tại thời điểm trả kết quả thay vì phát lại số cũ — model
    dùng số cũ cho `task_send`/`task_abandon` sẽ bị `TASK_REVISION_CONFLICT` ngay lần đầu.
    """
    row = rt.store.db.execute('SELECT revision FROM harness_tasks WHERE task_key=?',
                              (opened['taskKey'],)).fetchone()
    if row is None:
        invalid('taskKey', 'unknown task', 'TASK_UNKNOWN')
    return row['revision']


def _task_store_exists(rt):
    """Kho này đã từng tạo bảng task chưa — chỉ một SELECT `sqlite_master`, không DDL."""
    row = rt.store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='harness_tasks'"
                              ).fetchone()
    return row is not None


def _resolve_run(rt, owner_id, run_id):
    """Run của chính phiên sở hữu — không đoán, không tự tạo run mới."""
    graph = work_scope._graph(rt)
    if graph is None:
        return None
    try:
        run = graph.resolve(owner_id, run_id or None)
    except (ValueError, KeyError):
        return None
    if not isinstance(run, dict) or not run.get('runId'):
        return None
    return {'runId': run['runId'], 'sessionId': run.get('sessionId') or owner_id}


def _root_id(rt, session):
    return rt.root_session_id(session['id'])


def _run_id(rt, session, args):
    """Run của lượt: ưu tiên tham số model gửi, sau đó binding của lượt, cuối cùng là run đang mở."""
    given = str((args or {}).get('runId') or '').strip()
    if given:
        return given
    binding = work_scope.turn_binding(rt, rt.store.get(session['id'])) or {}
    if binding.get('runId'):
        return binding['runId']
    graph = work_scope._graph(rt)
    if graph is None:
        return ''
    try:
        run = graph.resolve(_root_id(rt, session), None)
    except (ValueError, KeyError):
        return ''
    return str((run or {}).get('runId') or '')


def _page_args(args):
    after = str((args or {}).get('cursor') or '').strip() or None
    limit = (args or {}).get('limit')
    if limit is None:
        return after, PAGE_LIMIT
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        invalid('limit', f'expected an integer between 1 and {MAX_LIMIT}')
    return after, limit


def _bound_tasks(rt, session, run_id):
    """Task mà chính phiên con này đang giữ attempt — đường đọc duy nhất của một child."""
    rows = rt.store.db.execute('SELECT task_key FROM harness_task_attempts WHERE session_id=? '
                               'ORDER BY attempt_seq DESC', (session['id'],)).fetchall()
    keys, out = [], []
    svc = service(rt)
    for row in rows:
        if row['task_key'] not in keys:
            keys.append(row['task_key'])
    for key in keys:
        try:
            out.append(svc.get(_root_id(rt, session), run_id, key))
        except ContractError:
            continue
    return out


async def handle(rt, session, name, args):
    """Chạy một công cụ bề mặt task. Mọi mã lỗi đã là mã hợp đồng (`TASK_*`, `TASK_SURFACE_*`)."""
    args = args if isinstance(args, dict) else {}
    if not enabled():
        raise PermissionError(f'TASK_SURFACE_OFF: {name} is unavailable while {SWITCH} is off')
    root = _root_id(rt, session)
    is_root = not session.get('parent_id')
    run_id = _run_id(rt, session, args)
    if not run_id:
        invalid('runId', 'no canonical run is bound to this turn', 'TASK_SURFACE_NO_RUN')
    svc = service(rt)
    if name == 'task_list':
        return _list(rt, svc, session, root, run_id, args)
    if name == 'task_get':
        return _get(rt, svc, session, root, run_id, args)
    if name == 'task_send':
        if not is_root:
            raise PermissionError('TASK_SURFACE_FORBIDDEN: only the owner/controller sends task messages')
        return _send(rt, svc, session, root, run_id, args)
    if name == 'task_abandon':
        if not is_root:
            raise PermissionError('TASK_SURFACE_FORBIDDEN: only the owner/controller abandons a task')
        return await _abandon(rt, svc, session, root, run_id, args)
    raise PermissionError(f'TASK_SURFACE_UNKNOWN: {name}')


def _list(rt, svc, session, root, run_id, args):
    after, limit = _page_args(args)
    state = args.get('status') or None
    if session.get('parent_id'):
        items = [task for task in _bound_tasks(rt, session, run_id)
                 if state is None or task['state'] == state]
        return {'runId': run_id, 'status': state, 'items': items[:limit], 'cursor': None,
                'note': 'a child sees only the tasks bound to its own session'}
    page = svc.list(root, run_id, after=after, limit=limit, state=state)
    return {'runId': run_id, 'status': state, 'items': page['items'], 'cursor': page.get('cursor')}


def _get(rt, svc, session, root, run_id, args):
    task_key = _task_key(svc, root, run_id, args)
    task = svc.get(root, run_id, task_key)
    if session.get('parent_id'):
        bound = {row['session_id'] for row in
                 rt.store.db.execute('SELECT session_id FROM harness_task_attempts WHERE task_key=?',
                                     (task_key,)).fetchall()}
        if session['id'] not in bound:
            raise PermissionError('TASK_SURFACE_FORBIDDEN: this task is not bound to this session')
    attempts = svc.attempts(root, run_id, task_key, limit=MAX_LIMIT)
    messages = svc.messages(root, run_id, task_key, limit=MAX_LIMIT)
    return {'task': task, 'attempts': attempts['items'], 'messages': messages['items'],
            'receipts': _receipts(rt, attempts['items'])}


def _send(rt, svc, session, root, run_id, args):
    task_key = _task_key(svc, root, run_id, args)
    receipt = svc.send(root, run_id, task_key, invocation_id=_invocation(args),
                       message_id=_message_id(args), sender_id=session['id'],
                       expected_revision=args.get('expectedRevision'),
                       kind=args.get('kind'), body=args.get('body'),
                       input_refs=args.get('inputRefs'))
    # Ack = đã ghi bền vững, KHÔNG phải con đã đọc. Nói thẳng để model không tin sai.
    return {'message': receipt, 'ack': 'received', 'consumed': False,
            'note': 'received means durable storage only; delivery into the child transcript is separate'}


async def _abandon(rt, svc, session, root, run_id, args):
    task_key = _task_key(svc, root, run_id, args)
    reason = args.get('reason')
    receipt = svc.abandon(root, run_id, task_key, invocation_id=_invocation(args),
                          expected_revision=args.get('expectedRevision'), reason=reason)
    cancel = None
    if receipt.get('controlState') == 'cancel_requested':
        attempt = _open_attempt(rt, task_key)
        if attempt is not None:
            # Đường huỷ thật duy nhất hiện có: `cancel_child` (chỉ cha, đóng một lần, có biên nhận).
            cancel = await _cancel(rt, session, attempt['session_id'], reason)
    return {'task': receipt, 'cancel': cancel,
            'note': 'abandon ends the need; cancel stops execution. Artifacts/checks/usage are kept'}


def _open_attempt(rt, task_key):
    row = rt.store.db.execute('SELECT session_id, status FROM harness_task_attempts WHERE task_key=? '
                              "AND status IN ('running','waiting_input') AND closed_at IS NULL "
                              'ORDER BY attempt_seq DESC LIMIT 1', (task_key,)).fetchone()
    return {'session_id': row['session_id'], 'status': row['status']} if row is not None else None


async def _cancel(rt, session, child_id, reason):
    """Gọi đúng `cancel_child` để có biên nhận `child_close_once` + event; lỗi thì trả lý do, không ném."""
    try:
        return await research_runtime.cancel_child(rt, session, {'sessionId': child_id,
                                                                 'reason': reason or 'task abandoned'})
    except Exception as exc:  # đường huỷ hỏng ⇒ abandon vẫn đã ghi, nói rõ phần chưa làm được
        return {'status': 'cancel_failed', 'sessionId': child_id, 'error': str(exc)}


def _receipts(rt, attempts):
    """Biên nhận thô từ sổ con: trạng thái đóng và lý do, không suy diễn thêm."""
    out = []
    for attempt in attempts:
        row = rt.store.child(attempt['sessionId'])
        out.append({'attemptId': attempt['attemptId'], 'sessionId': attempt['sessionId'],
                    'attemptStatus': attempt['status'], 'childStatus': (row or {}).get('status'),
                    'childReason': (row or {}).get('reason'),
                    'startedAt': attempt['startedAt'], 'closedAt': attempt.get('closedAt')})
    return out


def _task_key(svc, owner_id, run_id, args):
    """Khoá backend từ tham số model: `taskKey` dùng thẳng, `taskId` tra alias trong run.

    Model chỉ thấy `taskId` (alias do hợp đồng đặt); `task-<uuid>` là chi tiết kho, nhưng vẫn nhận
    để một lượt đã đọc được khoá từ `task_list` gọi tiếp được mà không phải tra lại.
    """
    key = str(args.get('taskKey') or '').strip()
    if key:
        return key
    alias = str(args.get('taskId') or '').strip()
    if not alias:
        invalid('taskId', 'taskId or taskKey is required')
    return svc.key_for(owner_id, run_id, alias)


def _invocation(args):
    value = str(args.get('invocationId') or '').strip()
    if not value:
        invalid('invocationId', 'invocationId is required for an idempotent write')
    return value


def _message_id(args):
    value = str(args.get('messageId') or '').strip()
    if not value:
        invalid('messageId', 'messageId is required for an idempotent message')
    return value
