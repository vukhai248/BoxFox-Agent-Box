"""W8.A4.2 — phạm vi thi công do backend sở hữu (`ExecutionScope`).

Cổng này trả lời một câu: lời gọi tool/delegate/custom command NÀY có được đổi mã trong workspace
không. Câu trả lời đọc từ trạng thái backend (lượt đã gắn run, binding của con, admission còn sống),
không từ prompt hay lời model tự nhận. Quy tắc đã duyệt (phương án C): chỉ run Work Graph bị gate;
lượt chat thường không gắn run và custom command ngoài run giữ hành vi cũ (`legacy`).

- Root: lượt gắn run khi (1) lượt bắt đầu với `config.workIntent` (`/plan|/research|/design`), (2) lượt
  là admission harness có `workDecisionBatch`, (3) trong lượt một tool `work_*` resolve được run của chính
  phiên. Ý định slash chỉ thuộc MỘT lượt: lượt dùng nó được đánh dấu `spent`, và lượt người dùng kế tiếp
  bỏ nó nếu không run nào ra đời từ đó (§1.2). Root KHÔNG BAO GIỜ tự sửa mã trong run: artifact-only, chờ
  duyệt, hay đã duyệt (sửa mã qua Build node) đều chặn ghi trực tiếp.
- Con có `workBinding`: chỉ producer execute của node thi công, run có `executionRequested`, đã duyệt và
  admission còn hiệu lực mới là `run_execute`.
- Con thường/custom command mang `config.scopeOrigin` ghi lúc tạo; thiếu ⇒ `legacy` (con cũ).

`root` trong Scope chỉ là chỗ để track isolation (A4.3) điền worktree; ở đây luôn là `None`.
"""
import json
import re
import shlex

from .roles import ROLES

MUTATING_TOOLS = frozenset({'file_write', 'file_edit_block'})
# Lấy đúng các nhánh design ghi file trong `HarnessRuntime.dispatch`.
DESIGN_MUTATING = frozenset({'design_branch_create', 'design_write', 'design_revert'})
TERMINAL = 'terminal_exec'
# Role ghi = role có công cụ sửa file (`roles.WRITE`); role mới có quyền ghi tự động bị gate.
WRITE_ROLES = frozenset(role_id for role_id, role in ROLES.items() if set(role.tools) & MUTATING_TOOLS)

TURN_KEY = 'workTurnScope'
ORIGIN_KEY = 'scopeOrigin'
BLOCK_MARKER = '=== WORK SCOPE ==='
BLOCK_END = '=== END WORK SCOPE ==='

MODES = ('legacy', 'artifact_only', 'approval_pending', 'root_delegates', 'run_execute',
         'read_only_check', 'closed')
OPEN_MODES = ('legacy', 'run_execute')
CLOSED_STATUSES = ('shipped', 'cancelled', 'rejected')
STOPPED_STATUSES = ('paused',) + CLOSED_STATUSES
EXECUTE_STATUSES = ('approved', 'executing', 'executed')
APPROVED_STATUSES = EXECUTE_STATUSES + ('execute_failed',)
# Node có pha execute do role ghi chạy: các kind thi công và pha execute của Plan (`EXECUTE_ROLE`).
EXECUTE_NODE_KINDS = ('build', 'debug', 'testing', 'simplify', 'plan')

ARTIFACT_ONLY = 'WORK_SCOPE_ARTIFACT_ONLY'
APPROVAL_REQUIRED = 'WORK_SCOPE_APPROVAL_REQUIRED'
ROOT_DELEGATES = 'WORK_SCOPE_ROOT_DELEGATES'
TERMINAL_MUTATING = 'WORK_SCOPE_TERMINAL_MUTATING'
DELEGATE_ROLE = 'WORK_SCOPE_DELEGATE_ROLE'
COMMAND_ROLE = 'WORK_SCOPE_COMMAND_ROLE'
REVOKED = 'WORK_SCOPE_REVOKED'
RUN_CLOSED = 'WORK_SCOPE_RUN_CLOSED'

MODE_CODE = {'artifact_only': ARTIFACT_ONLY, 'approval_pending': APPROVAL_REQUIRED,
             'root_delegates': ROOT_DELEGATES, 'closed': RUN_CLOSED}
NEXT_STEP = {
    ARTIFACT_ONLY: 'use read tools (file_read, codebase_grep, a read-only terminal command) and report '
                   'findings; to change code, ask the owner to open a fix run',
    APPROVAL_REQUIRED: 'call work_graph action=verify, then action=submit, and wait for owner approval; '
                       'code changes then run in Build nodes',
    ROOT_DELEGATES: 'add or assign a Build node (work_graph action=update) and run work_run phase=execute; '
                    'main does not edit code of an execution run directly',
    TERMINAL_MUTATING: 'use file_read/codebase_grep or one read-only command (pwd, ls, cat, rg, '
                       'git status/log/diff/show)',
    DELEGATE_ROLE: 'delegate explore/research/plan instead, or add a Build node to the run',
    COMMAND_ROLE: 'run this command in a new turn that is not bound to a Work Graph run',
    REVOKED: 'stop editing; main must re-check the assignment (work_graph action=status)',
    RUN_CLOSED: 'start a new turn or a new run',
}


class ScopeError(PermissionError):
    """Từ chối của cổng phạm vi; `classify_failure` đọc mã ở đầu thông điệp."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def scope(mode, run_id=None, reason='', code=None, admission=None):
    return {'mode': mode, 'runId': run_id, 'reason': reason, 'root': None, 'touchSet': None,
            'admission': admission, **({'code': code} if code else {})}


LEGACY = scope('legacy', reason='not bound to a Work Graph run')


def deny(code, current, action):
    run = current.get('runId') or 'not created yet'
    return ScopeError(code, f'{code}: {action} is blocked — {current.get("reason") or current["mode"]} '
                            f'(run {run}). Next: {NEXT_STEP[code]}.')


# --------------------------------------------------------------------------- #
# Phân loại lệnh terminal (chỉ dùng ngoài `legacy`/`run_execute`)
# --------------------------------------------------------------------------- #

READ_COMMANDS = frozenset({'pwd', 'ls', 'cat', 'head', 'tail', 'wc', 'stat', 'file', 'du', 'tree', 'which',
                           'echo', 'grep', 'egrep', 'rg'})
# Cờ của lệnh đọc mà vẫn ghi file hoặc chạy chương trình khác.
READ_COMMAND_BANNED = {'rg': ('--pre', '--pre-glob'), 'tree': ('-o',)}
FIND_BANNED = frozenset({'-exec', '-execdir', '-ok', '-okdir', '-delete', '-fprint', '-fprint0', '-fprintf',
                         '-fls'})
GIT_READ = frozenset({'status', 'log', 'diff', 'show', 'rev-parse', 'ls-files', 'blame', 'grep'})
GIT_BRANCH_READ = frozenset({'--show-current', '-a', '-l', '--list'})
GIT_BANNED = ('-c', '--output', '--ext-diff', '-O', '--open-files-in-pager')
SHELL_FORBIDDEN = ('>', '<', ';', '`', '$(', '${', '\n', '\r')
ASSIGNMENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*=')
LONE_AMPERSAND_RE = re.compile(r'(?<!&)&(?!&)')
SEGMENT_SPLIT_RE = re.compile(r'&&|\|\||\|')


def banned_option(word, banned):
    """`word` có phải (hoặc mang) một tuỳ chọn bị cấm không?

    Ba dạng phải khớp: `-O`, `--open-files-in-pager=rm` và dạng DÍNH LIỀN của tuỳ chọn ngắn —
    `-O<cmd>`, `-oout.txt`. Dạng dính liền từng lọt lưới: `git grep -O'touch f' foo` được xếp là
    `read` trong khi git thật sự CHẠY `<cmd>` (đã kiểm bằng receipt ở scratch repo). Tuỳ chọn dài
    vẫn chỉ khớp `=`/đúng tên, để `--pre` không nuốt `--prefix` hay `--pretty`.
    """
    for b in banned:
        if word == b or word.startswith(b + '='):
            return True
        if len(b) == 2 and b[0] == '-' and b[1] != '-' and word.startswith(b):
            return True
    return False


def read_segment(words):
    head, rest = words[0], words[1:]
    if ASSIGNMENT_RE.match(head) or 'sudo' in words:
        return False
    if head in READ_COMMANDS:
        banned = READ_COMMAND_BANNED.get(head, ())
        return not any(banned_option(w, banned) for w in rest)
    if head == 'find':
        return not any(w in FIND_BANNED for w in rest)
    if head == 'cd':
        return len(rest) <= 1
    if head == 'git':
        if not rest or any(banned_option(w, GIT_BANNED) for w in rest):
            return False
        sub, tail = rest[0], rest[1:]
        if sub in GIT_READ:
            return True
        if sub == 'branch':
            return not tail or (len(tail) == 1 and tail[0] in GIT_BRANCH_READ)
        if sub == 'remote':
            return tail == ['-v']
    return False


def classify_command(command):
    """`'read'` chỉ khi MỌI segment thuộc allowlist đọc; mặc định `'mutate'`.

    python/node/pip/npm/make/test runner đều là mutate: chúng có thể ghi, cài hoặc chạy mã.
    """
    if not isinstance(command, str) or not command.strip():
        return 'mutate'
    if any(token in command for token in SHELL_FORBIDDEN) or LONE_AMPERSAND_RE.search(command):
        return 'mutate'
    for segment in SEGMENT_SPLIT_RE.split(command):
        try:
            words = shlex.split(segment)
        except ValueError:
            return 'mutate'
        if not words or not read_segment(words):
            return 'mutate'
    return 'read'


# --------------------------------------------------------------------------- #
# Gắn lượt của root
# --------------------------------------------------------------------------- #

def _memory(rt):
    return rt.__dict__.setdefault('_work_turn_scopes', {})


def turn_binding(rt, session):
    """Binding của lượt root: bản trong bộ nhớ thắng (bản config có thể bị ghi đè bởi bản sao cũ)."""
    sid = session['id']
    memory = _memory(rt)
    if sid in memory:
        return memory[sid]
    value = (session.get('config') or {}).get(TURN_KEY)
    return value if isinstance(value, dict) else None


def store_binding(rt, sid, binding):
    _memory(rt)[sid] = binding
    current = rt.store.get(sid)
    config = current.get('config') or {}
    if config.get(TURN_KEY) == binding or (binding is None and TURN_KEY not in config):
        return
    if binding is None:
        config.pop(TURN_KEY, None)
    else:
        config[TURN_KEY] = binding
    rt.store.update_config(sid, config)


def _graph(rt):
    from . import work_graph
    return work_graph.service(rt) if work_graph.enabled() else None


def begin_turn(rt, sid, turn, invocation_id=None):
    """Lượt root mới: bỏ binding cũ; gắn intent slash hoặc run của batch harness của lượt này."""
    from . import work_graph
    session = rt.store.get(sid)
    if session.get('parent_id'):
        return None
    config = session.get('config') or {}
    binding = None
    if work_graph.enabled():
        if config.get(work_graph.INTENT_CONFIG_KEY):
            binding = {'turn': turn, 'runId': None, 'reason': 'intent', 'intent': True}
            mark_intent_spent(rt, sid, turn)
        graph = getattr(rt, 'work_graph', None)
        decisions = getattr(graph, 'decisions', None) if graph is not None else None
        if invocation_id and decisions is not None:
            row = decisions.db.execute('SELECT doc FROM work_main_batches WHERE id=? AND owner_id=?',
                                       (invocation_id, sid)).fetchone()
            run_id = json.loads(row['doc']).get('runId') if row else None
            if run_id:
                binding = {'turn': turn, 'runId': run_id, 'reason': 'harness',
                           **({'intent': True} if binding else {})}
    store_binding(rt, sid, binding)
    return binding


def mark_intent_spent(rt, sid, turn):
    """Ghi dấu ý định slash đã TIÊU vào lượt `turn` — lượt sau nó không còn hiệu lực (§1.2).

    Không xoá ở đây: `work_graph.create` còn đọc `workIntent` trong chính lượt này để lấy goal/flow.
    """
    from . import work_graph
    session = rt.store.get(sid)
    config = session.get('config') or {}
    intent = config.get(work_graph.INTENT_CONFIG_KEY)
    if isinstance(intent, dict) and intent.get('spent') != turn:
        intent['spent'] = turn
        rt.store.update_config(sid, config)
        return True
    return False


def drop_spent_intent(rt, sid):
    """Bỏ ý định slash đã tiêu ở lượt TRƯỚC mà không ra run.

    Ý định chỉ thuộc MỘT lượt: `/research <text>` ghi ý định rồi mới dựng lượt, nên nếu lượt ấy
    không tạo run thì lượt người dùng kế tiếp phải trở lại `legacy` — không thì mọi lượt sau bị
    khoá ghi vĩnh viễn bởi một ý định đã hết việc. Ý định VỪA đặt trong chính lượt đang mở chưa có
    dấu `spent`, nên không bị xoá (thứ tự thật là `set_intent` → `reset_user_turn` → `start`).
    """
    from . import work_graph
    session = rt.store.get(sid)
    config = session.get('config') or {}
    intent = config.get(work_graph.INTENT_CONFIG_KEY)
    if isinstance(intent, dict) and intent.get('spent') is not None:
        config.pop(work_graph.INTENT_CONFIG_KEY, None)
        rt.store.update_config(sid, config)
        return True
    return False


def reset_user_turn(rt, sid):
    """Một tin nhắn người dùng mới (trước khi dựng prompt): binding + ý định đã tiêu hết hiệu lực."""
    session = rt.store.get(sid)
    if not session.get('parent_id'):
        store_binding(rt, sid, None)
        drop_spent_intent(rt, sid)


def bind_tool(rt, session, name, args, result):
    """Một tool `work_*` của root vừa resolve một run của CHÍNH phiên ⇒ lượt gắn run đó từ đây."""
    if session.get('parent_id') or name == 'interview':
        return None
    graph = _graph(rt)
    if graph is None:
        return None
    sid = session['id']
    run_id = result.get('runId') if isinstance(result, dict) else None
    run_id = run_id or (args or {}).get('runId')
    if not run_id and result is None:
        return None  # Lỗi không nói tên run: không đoán.
    try:
        run = graph.resolve(sid, run_id or None)
    except ValueError:
        return None
    current = turn_binding(rt, rt.store.get(sid)) or {}
    if current.get('runId') == run['runId']:
        return current
    binding = {'turn': rt.active_turn.get(sid), 'runId': run['runId'],
               'reason': current.get('reason') or 'work_tool',
               **({'intent': True} if current.get('intent') else {})}
    store_binding(rt, sid, binding)
    return binding


def origin_for_child(rt, session):
    """`config.scopeOrigin` cho con thường/custom command tạo trong lượt không phải legacy.

    Con KHÔNG thừa hưởng `run_execute`: admission là của từng child, nên một cháu không có binding
    chỉ được đọc (`artifact_only`) — muốn sửa mã thì phải là node thi công có admission riêng.
    """
    current = resolve(rt, session)
    if current['mode'] == 'legacy':
        return None
    sid = session['id']
    inherited = (session.get('config') or {}).get(ORIGIN_KEY) or {}
    mode = current['mode'] if current['mode'] in MODE_CODE else 'artifact_only'
    return {'ownerId': inherited.get('ownerId') or session.get('parent_id') or sid,
            'runId': current['runId'], 'mode': mode, 'reason': current['reason'],
            'turn': rt.active_turn.get(sid)}


# --------------------------------------------------------------------------- #
# Resolve
# --------------------------------------------------------------------------- #

def run_reason(run):
    flow, status = run.get('flow'), run.get('status')
    if status in CLOSED_STATUSES:
        return scope('closed', run['runId'], f'run {run["runId"]} is {status}')
    if not run.get('executionRequested'):
        return scope('artifact_only', run['runId'],
                     f'run {run["runId"]} (flow={flow}) only produces artifacts; the owner did not request '
                     'code execution')
    if status in APPROVED_STATUSES:
        return scope('root_delegates', run['runId'],
                     f'run {run["runId"]} is approved for execution; its code changes go through Build nodes')
    return scope('approval_pending', run['runId'],
                 f'run {run["runId"]} requests execution but status={status} is not owner-approved')


def root_scope(rt, session):
    from . import work_graph
    graph = _graph(rt)
    if graph is None:
        return LEGACY  # Công tắc giết trả root về hành vi trước Work Graph.
    binding = turn_binding(rt, session)
    intent = (session.get('config') or {}).get(work_graph.INTENT_CONFIG_KEY)
    run_id = (binding or {}).get('runId')
    if not run_id:
        if binding or intent:
            command = (intent or {}).get('command') or 'slash'
            return scope('artifact_only', None, f'the owner asked for /{command}; this turn only produces '
                                                'artifacts')
        return LEGACY
    try:
        run = graph.current(run_id)
    except ValueError:
        return scope('closed', run_id, f'run {run_id} no longer exists')
    if run.get('sessionId') != session['id']:
        return scope('artifact_only', run_id, f'run {run_id} belongs to another session and grants nothing')
    return run_reason(run)


def admission_live(graph, work):
    """Admission của con còn hiệu lực (SQLite, không đòi `asyncio.current_task()`)."""
    try:
        run = graph.current(work.get('runId'))
    except ValueError:
        return False
    if run.get('status') in STOPPED_STATUSES:
        return False
    ident = work.get('progressAdmissionId')
    if not ident:
        return False
    row = graph.db.execute('SELECT status FROM work_progress WHERE id=?', (ident,)).fetchone()
    if not row or row['status'] not in ('reserved', 'admitted'):
        return False
    action = work.get('controllerAction')
    if action:
        outbox = graph.db.execute('SELECT status FROM work_feedback_outbox WHERE id=?', (action,)).fetchone()
        if outbox is not None:
            return outbox['status'] == 'claimed'
        handoff = graph.db.execute('SELECT status,doc FROM work_handoff_actions WHERE id=?', (action,)).fetchone()
        if handoff is None or handoff['status'] != 'admitted':
            return False
        transition = json.loads(handoff['doc']).get('transitionId')
        assignment = next((h for h in graph.handoffs.records(run['runId']) if h['transitionId'] == transition),
                          None)
        return bool(assignment) and graph.handoffs.valid(run, assignment)
    return True


def binding_scope(rt, owner_id, work):
    """Scope của một binding Work Graph (con đã tạo hoặc sắp tạo qua `delegate(work=...)`)."""
    run_id = work.get('runId')
    if work.get('checkId') or work.get('diagnosticOnly'):
        return scope('read_only_check', run_id, 'bound check/diagnosis is read-only')
    graph = _graph(rt)
    if graph is None:
        return scope('closed', run_id, 'the Work Graph is switched off')
    try:
        run = graph.current(run_id)
    except ValueError:
        return scope('closed', run_id, f'run {run_id} no longer exists')
    if run.get('sessionId') != owner_id:
        return scope('artifact_only', run_id, f'run {run_id} belongs to another session and grants nothing')
    node = next((n for n in run.get('nodes', []) if n.get('id') == work.get('nodeId')), None)
    if node is None and work.get('nodeId'):
        # W8.A4.5: nút tổng hợp là nút ẢO — không nằm trong `run['nodes']`, nhưng vòng sửa của nó
        # chạy một child Build trên nhánh run, nên phải được xét như nút build chứ không phải
        # assignment chỉ-sinh-artifact. Thiếu nhánh này, mọi vòng sửa ở nút tổng hợp bị cổng
        # WORK_SCOPE_ARTIFACT_ONLY chặn (`run_stage` bắt lỗi thành `status: failed`).
        from .work_worktrees import INTEGRATION_NODE
        if work['nodeId'] == INTEGRATION_NODE:
            node = graph.integration_node(run)
    kind = (node or {}).get('kind')
    executes = (work.get('purpose') == 'produce' and work.get('stage') == 'execute' and node is not None
                and kind in EXECUTE_NODE_KINDS
                and (kind != 'debug' or (work.get('taskKind') or node.get('taskKind')) == 'implementation'))
    base = run_reason(run)
    if not executes or base['mode'] in ('closed', 'artifact_only'):
        if base['mode'] == 'closed':
            return base
        return scope('artifact_only', run_id,
                     f'this assignment ({work.get("purpose")}/{work.get("stage")} of node {work.get("nodeId")}) '
                     f'only produces artifacts' if base['mode'] != 'artifact_only' else base['reason'])
    if run.get('status') == 'paused':
        return scope('closed', run_id, f'run {run_id} is paused', code=REVOKED)
    if run.get('status') not in EXECUTE_STATUSES:
        return scope('approval_pending', run_id, f'run {run_id} status={run.get("status")} is not an approved '
                                                 'execution')
    if not admission_live(graph, work):
        return scope('closed', run_id, f'the execution admission of node {work.get("nodeId")} was stopped, '
                                       'revoked or finished', code=REVOKED)
    return scope('run_execute', run_id, f'approved execution of node {work.get("nodeId")}',
                 admission=work.get('controllerAction') or work.get('progressAdmissionId'))


def resolve(rt, session):
    config = session.get('config') or {}
    if not session.get('parent_id'):
        # Ý định và binding đều được persist NGAY khi đổi, còn dict đang lưu hành có thể là bản cũ;
        # đọc bản mới nhất để lượt không đọc phải một `workIntent` đã bị `create` xoá.
        try:
            fresh = rt.store.get(session['id'])
        except (KeyError, TypeError):
            fresh = session
        return root_scope(rt, fresh)
    work = config.get('workBinding')
    if isinstance(work, dict) and work.get('runId'):
        return binding_scope(rt, session['parent_id'], work)
    origin = config.get(ORIGIN_KEY)
    if isinstance(origin, dict) and origin.get('mode') in MODES and origin['mode'] not in OPEN_MODES:
        return scope(origin['mode'], origin.get('runId'),
                     (origin.get('reason') or '') + ' (inherited from the owner turn)')
    return LEGACY


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #

def code_for(current):
    return current.get('code') or MODE_CODE.get(current['mode'], ARTIFACT_ONLY)


def check_tool(rt, session, name, args, current=None):
    current = current or resolve(rt, session)
    if current['mode'] in ('legacy', 'run_execute', 'read_only_check'):
        # read_only_check giữ các cổng WORK_CHECK_READ_ONLY/WORK_DIAGNOSTIC_READ_ONLY sẵn có.
        return current
    if name in MUTATING_TOOLS or name in DESIGN_MUTATING:
        raise deny(code_for(current), current, f'`{name}`')
    if name == TERMINAL and classify_command((args or {}).get('command')) != 'read':
        code = current.get('code') or (RUN_CLOSED if current['mode'] == 'closed' else TERMINAL_MUTATING)
        raise deny(code, current, 'this terminal command (not a read-only allowlisted command)')
    return current


def check_delegate(current, role):
    if current['mode'] != 'legacy' and role in WRITE_ROLES:
        raise deny(DELEGATE_ROLE, current, f'delegating to the write role {role!r}')
    return current


def check_command(current, roles, executor=None):
    if current['mode'] == 'legacy':
        return current
    writes = sorted(set(roles or ()) & WRITE_ROLES)
    if writes or executor == 'claude-code':
        what = 'the claude-code executor' if executor == 'claude-code' else 'role ' + ', '.join(writes)
        raise deny(COMMAND_ROLE, current, f'a custom command with {what}')
    return current


def check_execute_binding(rt, owner_id, work):
    """`delegate(work=...)` của producer execute cần `run_execute` hợp lệ cho node đích."""
    if work.get('stage') != 'execute' or work.get('purpose') != 'produce' \
            or work.get('checkId') or work.get('diagnosticOnly'):
        return None
    current = binding_scope(rt, owner_id, work)
    if current['mode'] != 'run_execute':
        raise deny(code_for(current), current, 'starting an execution child')
    return current


def apply_profile(rt, session, profile):
    """Áp phạm vi của lượt lên hồ sơ công cụ: ngoài `legacy`/`run_execute`, bỏ công cụ sửa mã.

    `terminal_exec` được GIỮ: lệnh đọc hợp lệ vẫn có ích cho main (đo sống §33.13). Cổng thật nằm ở
    `check_tool` trong `dispatch` — đây chỉ là danh sách để model không gọi thứ chắc chắn bị từ chối.
    """
    current = resolve(rt, session)
    if current['mode'] in OPEN_MODES:
        return profile
    tools = [name for name in (profile.get('tools') or [])
             if name not in MUTATING_TOOLS and name not in DESIGN_MUTATING]
    block = prompt_block(current)
    prompt = profile.get('promptBlock') or ''
    if block:
        prompt = f'{prompt}\n{block}' if prompt else block
    return profile | {'tools': tools, 'promptBlock': prompt, 'workScope': current}


def prompt_block(current):
    if current['mode'] in OPEN_MODES or current['mode'] == 'read_only_check':
        return ''
    run = current.get('runId') or 'not created yet'
    return (f'{BLOCK_MARKER}\nRun {run} does not let main change code in this turn ({current["reason"]}). '
            'file_write/file_edit_block are off and terminal_exec only accepts read-only commands '
            '(pwd, ls, cat, rg, git status/log/diff/show). To change code, propose a fix run or ask the '
            f'owner to approve one; approved code changes run in Build nodes.\n{BLOCK_END}')
