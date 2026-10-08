"""Loopback harness API; UI uses the Vite /api/agent proxy."""
import asyncio
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from aiohttp import web
from ..agent_core import design_runtime, execution_kernel, plan_registry, research_runtime
from ..agent_core import permissions as permissions_module
from ..agent_core import plan_workflow, work_graph
from ..agent_core import usage_surface
from ..agent_core.plan_header import IDENTITY_PATTERN
from ..agent_core.peer_watchdog import PeerWatchdog
from ..agent_core.runtime import HarnessRuntime, DecisionError
from ..agent_core.failures import (BACKOFF_JITTER, BACKOFF_SECONDS, DEFAULT_MAX_RETRIES,
                                   RATE_LIMIT_MAX_SECONDS, RETRY_BUDGET_SECONDS)
from ..agent_core.limits import (CHILD_DEADLINE_SECONDS, CHILD_MAX_STEPS, DEADLINE_DEFAULT_SECONDS,
                                 DEADLINE_MAX_SECONDS, INSTRUCTIONS_MAX_CHARS, MAX_STEPS_DEFAULT,
                                 MAX_STEPS_MAX)
from ..agent_core.limits import parallel_read_tools_enabled, peer_mesh_enabled, peer_wait_max
from ..agent_core.limits import (READ_STORE_MAX_ENTRIES, WEB_READER_DEFAULT_MODE, WEB_READER_MODES,
                                 WEB_READ_STORE_DEFAULT_MODE, WEB_READ_STORE_MODES)
from ..agent_core.limits import (SEARCH_CACHE_TTL_SECONDS, SEARCH_ENGINE_ROTATION_N, SEARCH_PIPELINE_TOP_K,
                                 SEARXNG_TIMEOUT_SECONDS)
from ..agent_core.web import MAX_TEXT_HARD
from ..agent_core.limits import (EVIDENCE_DEFAULT_MODE, EVIDENCE_MAX_ARTIFACTS, EVIDENCE_MODES,
                                 EVIDENCE_PROBE_MAX_FILES, EVIDENCE_PROBE_TIMEOUT_SECONDS,
                                 EVIDENCE_REPAIR_MAX_TOKENS, EVIDENCE_REPAIR_MIN_REMAINING_SECONDS,
                                 EVIDENCE_REPAIR_TIMEOUT_SECONDS)
# Vòng 25 (D-33..D-35) — cổng phản biện/cổng nguồn và hạn chót của lượt lập kế hoạch. Route đọc
# cùng hằng với runtime, nên `runtime_info` và hành vi thật không thể lệch nhau.
from ..agent_core.limits import (PLAN_APPROVAL_UNVERIFIED_CODE, PLAN_REVIEW_MIN_ANSWER_CHARS,
                                 PLAN_SOURCES_DEFAULT_MODE, PLAN_SOURCES_MODES,
                                 PLAN_TURN_EXTENSION_SECONDS, PLAN_VERIFY_DEFAULT_MODE,
                                 PLAN_VERIFY_MODES, PLAN_VERIFY_REVISE_MAX,
                                 PLAN_WAKE_FAILED_CODE, PLAN_WAKE_NO_OWNER_CODE)
from ..agent_core.roles import ORCHESTRATOR_TOOLS, ROLES
from ..agent_core.limits import (CHILD_WALL_MAX_SECONDS, FANOUT_GLOBAL_CEILING, FANOUT_PER_PARENT_DEFAULT,
                                 FANOUT_PER_PARENT_MAX, PEER_DELIVER_MAX, PEER_WAIT_MAX_SECONDS,
                                 PEER_WAIT_SAFETY_SECONDS, WATCHDOG_TICK_SECONDS)
# Vòng 27 (đợt 5–8) — khối `research` của `runtime_info` đọc CÙNG hằng và CÙNG hàm với runtime:
# bảng công tắc, hạn mức theo mức, danh mục hồ sơ và thang nguồn không thể lệch khỏi hành vi thật.
from ..agent_core import research_profiles, research_quality, research_runtime, search_pipeline, source_tiers
from ..agent_core.limits import (DOSSIER_MAX_BYTES, RESEARCH_BRIEF_DEFAULT_MODE, RESEARCH_BRIEF_MODES,
                                 RESEARCH_GATE_DEFAULT_MODE, RESEARCH_GATE_MODES,
                                 RESEARCH_MAX_ROWS_PER_DOSSIER, RESEARCH_PROGRESS_DEFAULT_MODE,
                                 RESEARCH_PROGRESS_MODES, RESEARCH_PROGRESS_NUDGE_SECONDS,
                                 RESEARCH_REVIEW_MIN_ANSWER_CHARS, RESEARCH_TIERS,
                                 RESEARCH_TIER_CHILD_SECONDS, RESEARCH_TIER_CHILD_STEPS,
                                 RESEARCH_TIER_DEFAULT, RESEARCH_TIER_HARD_CEILING_SECONDS,
                                 RESEARCH_VERIFY_REVISE_MAX, STEER_DEFAULT_MODE, STEER_MAX_PENDING,
                                 STEER_MODES, STEER_TEXT_MAX_CHARS)
from ..agent_core.tool_groups import tool_groups
from ..memory.session_store import SessionStore
from ..observability.system_log import (DEFAULT_READ_LINES, MAX_READ_LINES, clamp_lines,
                                        redact_entry, system_log)
from ..sandbox.executor import SandboxExecutor
from ..agent_core.desktop_control import DesktopControl
from ..sandbox.host_executor import (HostExecutor, approval_options, approval_reason,
                                     approval_verdict)
from .owner_settings import OwnerSettings


logger = logging.getLogger('boxfox.harness.api')
RESEARCH_PUMP_KEY = web.AppKey('research_pump', asyncio.Task)
IDLE_WATCH_KEY = web.AppKey('idle_watch', asyncio.Task)

#: Nhịp lấy mẫu của bộ theo dõi "người thật chạm máy" trên nền tảng không có hook (X11).
#: Mỗi mẫu là hai tiến trình con ngắn (~20 ms), chạy trong luồng riêng nên không chặn vòng lặp.
IDLE_WATCH_INTERVAL_SEC = 1.0


def idle_watch_supported(control) -> bool:
    """Nền tảng của bộ điều khiển có TỰ theo dõi được người can thiệp mà không cần hook hệ điều hành?

    Windows không cần: hook `WH_MOUSE_LL`/`WH_KEYBOARD_LL` đã lo việc đó (và đường `poll_idle` của
    nó chưa được kiểm trên máy Windows thật). X11 thì cần — ở đó chỉ có mẫu con trỏ + tiêu điểm.
    Cờ này nằm trên chính đối tượng nền tảng để chỗ gọi không phải rẽ nhánh theo `sys.platform`.
    """
    return bool(getattr(getattr(control, 'platform', None), 'supports_idle_watch', False))


def research_job_pumpable(runtime, job, session):
    """P1 (§5.2, cửa 4): bơm chỉ chạy job thuộc MODE, và chỉ theo hai đường (M-08).

    (a) mode đang bật và `researchMode.activeRunId` = job đó;
    (b) `state.background = true` (người dùng chọn "Tiếp tục chạy nền", #6078) dù mode đã tắt.

    Job `origin='main'` (việc nhẹ main tự mở) KHÔNG bao giờ được bơm: nó xong trong lượt hoặc
    thành `partial`. Job đang `clarifying` cũng không: lượt của nó là lượt đang chờ người dùng.
    """
    from ..agent_core import runtime as runtime_module
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    origin = str(state.get('origin') or '')
    if origin not in {runtime_module.RESEARCH_JOB_ORIGIN, runtime_module.RESEARCH_JOB_ORIGIN_MAIN}:
        # Job cũ (ghi trước P1) không có `origin`: giữ nguyên đường bơm cũ.
        return True
    if origin != runtime_module.RESEARCH_JOB_ORIGIN:
        return False
    if str(state.get('phase') or '') == 'clarifying':
        return False
    if bool(state.get('background')):
        return True
    if not runtime_module.research_mode_available():
        return False
    mode = runtime_module.research_mode(session)
    return bool(mode['on']) and str(mode.get('activeRunId') or '') == str(job['research_id'])


def design_job_pumpable(runtime, job, session):
    """P1 (design-interfaces §5): bơm chỉ chạy job thuộc MODE, theo hai đường như research.

    (a) mode đang bật và `designMode.activeRunId` = job đó;
    (b) `state.background = true` (chủ nhà chọn "Tiếp tục chạy nền") dù mode đã tắt.

    Run `origin='delegate'` KHÔNG bao giờ được bơm: lượt của nó là lượt của nhánh được giao.
    Run đang `needs_user`/`paused` cũng không — nó đang chờ người dùng.
    """
    from ..agent_core import runtime as runtime_module
    state = job.get('state') if isinstance(job.get('state'), dict) else {}
    origin = str(state.get('origin') or '')
    if origin != design_runtime.DESIGN_JOB_ORIGIN:
        return False
    if job['status'] in {'needs_user', 'paused'}:
        return False
    if bool(state.get('background')):
        return True
    if not runtime_module.design_mode_available():
        return False
    mode = runtime_module.design_mode(session)
    return bool(mode['on']) and str(mode.get('activeRunId') or '') == str(job['design_id'])


async def design_continuation_step(runtime):
    """Bơm lại một lần cho mỗi run design đủ điều kiện: phải đang ở pha `scaffolding`/`reviewing`
    và qua được `design_job_pumpable` (mode đang bật với `activeRunId`, hoặc cờ chạy nền).
    """
    for job in runtime.store.design_jobs_active():
        try:
            sid = job['session_id']
            session = runtime.store.get(sid)
            if session['status'] in {'running', 'awaiting_decision'}:
                continue
            state = job.get('state') if isinstance(job.get('state'), dict) else {}
            if str(state.get('phase') or '') not in {'scaffolding', 'reviewing'}:
                continue
            if not design_job_pumpable(runtime, job, session):
                continue
            attempt = int(state.get('continuationAttempt') or 0) + 1
            state['continuationAttempt'] = attempt
            runtime.store.design_job_save(job['design_id'], sid, state, revision=job['revision'])
            await runtime.submit(
                sid,
                f'Continue design job {job["design_id"]} from design_status. Keep the touch list '
                'authoritative, write only approved paths, and stop with a qualified partial result '
                'if a path is blocked.',
                invocation_id=f'design-resume-{job["design_id"]}-{attempt}')
        except Exception:
            logger.exception('design continuation could not start for %s', job['design_id'])


async def research_continuation_step(runtime):
    """Resume eligible research jobs once; persisted turns keep retries idempotent."""
    for job in runtime.store.research_jobs_active():
        sid = job['session_id']
        try:
            session = runtime.store.get(sid)
            if session['status'] in {'running', 'awaiting_decision'}:
                continue
            if not research_job_pumpable(runtime, job, session):
                continue
            state = dict(job['state'])
            used = runtime.store.research_job_used_seconds(sid, job['research_id'])
            remaining = int(state.get('budgetSeconds') or 0) - used
            if remaining < 60:
                # F6 (§5.3/§5.10): bơm cạn ngân sách cũng là một đường KẾT THÚC, và đi qua CÙNG cửa
                # với `research_update` (`close_run`): run TIỀN CẢNH cũng nhận pha `done` + thẻ báo
                # cáo, không chỉ run nền — `finish_background_run` tự bỏ qua khi cờ nền tắt, nên
                # trước đây một run tiền cảnh biến mất im lặng (đợt soát `3dc745f`, finding 2).
                research_runtime.close_run(runtime, session, job, state, 'partial',
                                           f'hết ngân sách: còn {remaining} s trên '
                                           f'{int(state.get("budgetSeconds") or 0)} s')
                continue
            turn = int(session.get('turn_count') or 0)
            if turn <= int(state.get('lastContinuationTurn') or 0) and \
                    time.time() - float(state.get('lastContinuationAt') or 0) < 90:
                continue
            progress = (sum(q.get('status') in ('answered', 'evidenced')
                            for q in state.get('questions', [])),
                        len(state.get('findings', [])), runtime.store.source_count(sid),
                        len(runtime.store.dossier_versions(job['research_id'])))
            old = tuple(state.get('lastProgress') or ())
            stalled = (int(state.get('stalledTurns') or 0) + 1 if old == progress else 0)
            state.update(lastProgress=list(progress), stalledTurns=stalled,
                         lastContinuationTurn=turn, lastContinuationAt=time.time(),
                         continuationAttempt=int(state.get('continuationAttempt') or 0) + 1)
            if stalled >= 2:
                # F6: hai lượt bơm không tiến được ⇒ kết thúc y như cạn ngân sách, qua cùng cửa
                # (`close_run`), nên run tiền cảnh cũng có pha `done`, lý do, và thẻ báo cáo.
                research_runtime.close_run(runtime, session, job, state, 'partial',
                                           'bơm hai lượt liền không tiến được: câu trả lời, hàng '
                                           'nguồn và bản hồ sơ đều đứng yên')
                continue
            runtime.store.research_job_save(job['research_id'], sid, state,
                                            revision=job['revision'])
            # Clamp the next autonomous turn to the remaining aggregate budget.
            session['config']['deadlineSeconds'] = max(
                60, min(int(session['config'].get('deadlineSeconds') or 600), int(remaining)))
            runtime.store.update_config(sid, session['config'])
            await runtime.submit(sid,
                f'Continue research job {job["research_id"]} from research_status. '
                'Prioritize unanswered decision-critical questions, verify important claims, '
                'record findings with research_update, and stop with a qualified partial '
                'result if evidence is blocked. Do not exceed the remaining job budget.',
                invocation_id=f'research-resume-{job["research_id"]}-{state["continuationAttempt"]}')
        except Exception:
            # One malformed or temporarily unavailable job must not kill the pump.
            logger.exception('research continuation could not start for %s', job['research_id'])

DEFAULT_HARNESS_PORT = 3102
HARNESS_VERSION = '0.1.0'

# Grammar của identity plan, neo vào cùng hằng số với khối header/`plan_registry` nên không có bản
# sao thứ ba của `_SLUG`. Ghi chú người dùng khi duyệt plan bị cắt ở đây: sổ duyệt là chỗ ghi lại
# lý do, không phải chỗ dán cả một tài liệu.
_PLAN_IDENTITY_RE = re.compile(rf'^{IDENTITY_PATTERN}$')
_PLAN_NOTE_MAX_CHARS = 4096


class ApiError(Exception):
    """HTTP failure the client can act on: a stable code plus a readable message.

    The middleware used to turn any ``KeyError`` into ``{'error': 'Not found'}``. A missing
    session is exactly that shape, so the chat showed the word "Not found" for a stale id —
    with no code, no id and nothing for support to search. Codes here are the contract the UI
    reads (``SESSION_NOT_FOUND`` lets it start a fresh session instead of failing forever).
    """

    def __init__(self, code, message, status=400, extra=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        # P1 (§5.12): lời hỏi thoát đi KÈM lỗi 409 (`{prompt:{kind:'exit-choice'}}`), nên phản hồi
        # lỗi phải mang thêm dữ liệu, không chỉ code + message.
        self.extra = extra if isinstance(extra, dict) else {}


def missing_session(sid):
    """404 for an id this harness does not know (deleted, or a store from another run)."""
    return ApiError('SESSION_NOT_FOUND',
                    f'session {sid} is not known to this harness; it was deleted or the harness '
                    'started with an empty store', 404)


def _action_error(exc, statuses=None, default=400):
    """`ValueError` mang mã hợp đồng (`CODE: chi tiết`) → `ApiError`; status tra theo mã.

    Mã trần (không có dấu `:`) giữ nguyên mã và để thân lỗi RỖNG — `ApiError` tự ghép
    `error = code: message`, nên lặp lại mã ở thân lỗi là nói hai lần một chuyện.
    """
    text = str(exc)
    code, sep, detail = text.partition(':')
    return ApiError(code, detail.strip() if sep else '', (statuses or {}).get(code, default))


def _open_allocations(rt):
    """Trần chi đang mở cho khối `usage` của runtime-info — chỉ đọc, không cấp chi.

    Chỉ đọc THẬT: bảng của sổ chi chưa có thì trả `[]` ngay, không dựng sổ — dựng sổ là
    ghi schema, kể cả khi cả nhóm công tắc đang tắt. Một hàng hỏng hoặc bảng thiếu KHÔNG
    được làm đỏ cả tab Harness: tab này còn phục vụ việc chẩn đoán, nên chỗ này trả `[]`
    và ghi log thay vì ném ra ngoài.
    """
    try:
        tables = {row[0] for row in rt.store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('harness_allocations', 'harness_usage')")}
        if len(tables) < 2:  # thiếu một trong hai là schema dở dang: tuyệt đối không dựng sổ
            return []
        return usage_surface.service(rt).open_allocations()
    except Exception:
        logger.exception('usage allocations unavailable')
        return []


#: Mã khoá lạc quan của lượt chủ nhà → status HTTP: một chỗ khai cho CẢ nhánh `scope`/`deepen`
#: lẫn phần còn lại của handler (cùng một luật "khoá cũ ⇒ 409, đích không có ⇒ 404").
_RESEARCH_CONFLICT_STATUS = {'RESEARCH_SCOPE_REVISION_STALE': 409,
                             'RESEARCH_JOB_REVISION_CONFLICT': 409,
                             'RESEARCH_FACET_UNKNOWN': 404,
                             'RESEARCH_QUESTION_UNKNOWN': 404,
                             # P5 (§5.8): bốn cửa từ chối của `action='refresh'` — công tắc tắt, chưa
                             # có hồ sơ, run gốc đang chạy, đã có run làm mới đang chạy.
                             'RESEARCH_REFRESH_DISABLED': 409,
                             'RESEARCH_REFRESH_NO_DOSSIER': 409,
                             'RESEARCH_REFRESH_SOURCE_ACTIVE': 409,
                             'RESEARCH_REFRESH_RUN_ACTIVE': 409}

#: Mã khoá lạc quan của các tuyến design → status HTTP: khoá cũ ⇒ 409. Cùng luật với research.
_DESIGN_CONFLICT_STATUS = {'DESIGN_TOUCH_LIST_REVISION_STALE': 409,
                           'DESIGN_TOUCH_LIST_REQUIRED': 409,
                           'DESIGN_JOB_REVISION_CONFLICT': 409}


def _plan_review_json(row):
    """Một hàng `plan_reviews` → camelCase cho UI; `None` khi chưa có quyết định nào."""
    if not row:
        return {'review': None}
    return {'review': {
        'identity': row.get('identity'), 'version': row.get('version'),
        'decision': row.get('decision'), 'note': row.get('note') or '',
        'source': row.get('source') or 'plan-tab', 'sessionId': row.get('session_id'),
        'decidedAt': row.get('decided_at'), 'contentSize': row.get('content_size'),
        'contentModifiedAt': row.get('content_modified_at'),
    }}


def repo_commit() -> str | None:
    """Commit of this checkout, read from `.git` directly (no subprocess), or None.

    The diagnostics line a dev copies out of the system-log panel has to name the build
    it came from; when there is no `.git` (a packaged run) the answer is honestly `None`
    and the panel prints `unknown` instead of inventing a hash.
    """
    git = Path(__file__).resolve().parents[4] / '.git'
    try:
        head = git / 'HEAD'
        text = head.read_text(encoding='utf-8').strip()
        if text.startswith('ref:'):
            ref = text[4:].strip()
            return (git / ref).read_text(encoding='utf-8').strip()[:40] or None
        return text[:40] or None
    except OSError:
        return None


def harness_port() -> int:
    """Port the harness binds. Read per call, not at import: a wrapper or a test that sets
    `BOXFOX_HARNESS_PORT` after this module is imported must still get a matching allow-list,
    and a non-numeric value must not kill the process with a bare `ValueError`."""
    raw = (os.environ.get('BOXFOX_HARNESS_PORT') or '').strip()
    if not raw:
        return DEFAULT_HARNESS_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ValueError(f'BOXFOX_HARNESS_PORT must be a number, got {raw!r}') from None
    if not 1 <= port <= 65535:
        raise ValueError(f'BOXFOX_HARNESS_PORT must be 1-65535, got {port}')
    return port


def allowed_hosts() -> set[str]:
    """The UI and the Vite proxy use 3100/3102; the override adds an isolated instance's
    own port without dropping the defaults."""
    port = harness_port()
    return {
        '127.0.0.1:3102', 'localhost:3102', '127.0.0.1:3100', 'localhost:3100',
        f'127.0.0.1:{port}', f'localhost:{port}',
    }


def allowed_origins() -> set[str]:
    """Origin của UI. Mặc định chỉ hai origin loopback của bản chạy chuẩn;

    `BOXFOX_UI_ORIGINS` (phân tách bằng dấu phẩy) thêm origin của MỘT bản chạy
    tách riêng — cùng tinh thần với `BOXFOX_HARNESS_PORT`: bản tách riêng khai cổng của nó,
    mặc định không bị nới.
    """
    origins = {'http://localhost:3100', 'http://127.0.0.1:3100'}
    for item in (os.environ.get('BOXFOX_UI_ORIGINS') or '').split(','):
        item = item.strip().rstrip('/')
        if item:
            origins.add(item)
    return origins


# --- Chọn chế độ thi hành (H4) ---------------------------------------------------------------
# `BOXFOX_EXECUTION_MODE=host|docker` — mặc định `docker` để hành vi cũ không đổi một byte khi
# người dùng chỉ cài bản cập nhật. `cloud` được chừa chỗ nhưng CHƯA cài: báo lỗi rõ thay vì im
# lặng rơi về docker (im lặng thì người dùng tưởng đã bật cloud).
EXECUTION_MODE_ENV = 'BOXFOX_EXECUTION_MODE'
EXECUTION_MODES = ('docker', 'host')
# Chỗ chừa cho chế độ cloud. Giá trị này KHÔNG im lặng rơi về docker: người dùng gõ nó ra nghĩa là
# họ muốn cloud, và im lặng chạy docker sẽ khiến họ tin nhầm là đã bật.
EXECUTION_MODES_RESERVED = ('cloud',)
EXECUTION_MODE_DEFAULT = 'docker'


def execution_mode(env=None):
    """`'docker'` | `'host'` (hoặc `'cloud'` chưa cài). Giá trị lạ ⇒ mặc định, không bao giờ ném."""
    source = os.environ if env is None else env
    raw = str(source.get(EXECUTION_MODE_ENV) or '').strip().lower()
    if raw in EXECUTION_MODES or raw in EXECUTION_MODES_RESERVED:
        return raw
    return EXECUTION_MODE_DEFAULT


def host_workspace(env=None):
    """Thư mục làm việc của host mode — nơi mọi đường dẫn tương đối neo vào."""
    source = os.environ if env is None else env
    explicit = str(source.get('BOXFOX_HOST_WORKSPACE') or '').strip()
    if explicit:
        return Path(explicit).expanduser()
    return Path.home() / 'BoxFox' / 'workspace'


def attach_host_approver(runtime):
    """Nối thẻ duyệt vào executor host MỨC TIẾN TRÌNH (DA2 của bản bàn giao).

    Phiên IDE đi qua `SessionMachineExecutor.host()` — đường đó đã có thẻ duyệt riêng. Nhưng khi
    tiến trình chạy host mode mà phiên lại do executor mức tiến trình phục vụ (`build_executor`),
    trước đây không có `approver` nên MỌI lời gọi cần hỏi bị từ chối im lặng. Không có `approver`
    vẫn phải là fail-closed, nên chỉ nối khi executor thật sự là host và chưa có thẻ duyệt.
    """
    executor = getattr(runtime, 'executor', None)
    if not isinstance(executor, HostExecutor) or executor.approver is not None:
        return False

    async def approve(name, args, decision, session_id=None):
        # `SessionStore.get` ném `KeyError` khi thiếu phiên: thiếu phiên là TỪ CHỐI, không phải lỗi 500.
        try:
            session = runtime.store.get(session_id) if session_id else None
        except KeyError:
            session = None
        # Phiên con chạy trong lượt của cha và không có chat riêng: `runtime.decision` sẽ ném.
        if not session or session.get('parent_id'):
            return 'deny'
        outcome = await runtime.decision(session, 'request_approval', {
            'action': f'{name} {json.dumps(args, ensure_ascii=False)[:1500]}',
            'reason': approval_reason(decision, name, args),
            'options': approval_options(decision, name, args)})
        return approval_verdict(outcome, decision, name)

    executor.approver = approve
    return True


def build_executor(data, env=None):
    """Executor theo chế độ đang chọn. `data` là thư mục hồ sơ (audit, luật, DB)."""
    source = os.environ if env is None else env
    mode = execution_mode(source)
    if mode == 'cloud':
        raise RuntimeError('EXECUTION_MODE_UNIMPLEMENTED: `%s=cloud` chưa được cài đặt trong bản '
                           'alpha này — chọn `docker` (mặc định) hoặc `host`.' % EXECUTION_MODE_ENV)
    if mode == 'host':
        workspace = host_workspace(source)
        profile_dir = Path(data)
        policy = permissions_module.PermissionPolicy(str(workspace), profile_dir=profile_dir, env=source)
        desktop = build_desktop_control(profile_dir, source)
        executor = HostExecutor(str(workspace), policy=policy, env=source, desktop=desktop,
                                overlay=build_cua_overlay(source, desktop))
        return executor
    return SandboxExecutor(api_key=source.get('BOXFOX_API_KEY', 'boxfox-local-dev-token'))


def build_cua_overlay(env=None, desktop=None):
    """Viền báo vùng đang bị điều khiển trên màn hình thật, hoặc `None`.

    Chỉ có nghĩa khi có `DesktopControl` (Windows hoặc X11 thật). Biến `BOXFOX_CUA_OVERLAY=0` tắt hẳn
    viền — một số môi trường (chụp màn hình tự động, VM không compositor) không muốn thêm cửa sổ
    luôn-trên-cùng.

    Trên Linux, máy **thiếu `python-xlib`** vẫn trả về một `CuaOverlay` **đang tắt** kèm câu nói rõ
    thiếu gói gì (`snapshot()['reason']`) — CUA chạy bình thường, chỉ mất tín hiệu thị giác, nhưng
    người dùng đọc được vì sao (quyết định J0.8).
    """
    source = os.environ if env is None else env
    if str(source.get('BOXFOX_CUA_OVERLAY') or '').strip().lower() in ('0', 'off', 'false'):
        return None
    if desktop is None:
        return None
    try:
        from ..agent_core.cua_overlay import CuaOverlay
    except Exception:
        return None
    if sys.platform == 'win32':
        try:
            from ..sandbox.win.windows_platform import CuaOverlayWindow
        except Exception:
            return None
        try:
            return CuaOverlay(CuaOverlayWindow(getattr(desktop, 'platform', None)))
        except Exception:
            return None
    if sys.platform.startswith('linux'):
        try:
            from ..sandbox.x11 import overlay as x11_overlay
        except Exception:
            return None
        reason = x11_overlay.unavailable_reason()
        if reason:
            return CuaOverlay(None, reason=reason)
        try:
            return CuaOverlay(x11_overlay.X11OverlayWindow(getattr(desktop, 'platform', None)))
        except Exception:
            return None
    return None


def build_desktop_control(profile_dir, env=None):
    """`DesktopControl` cho host mode, hoặc `None` khi máy này không điều khiển desktop được.

    Không ném: máy không có nền tảng desktop (không phải Windows, không có X11, thiếu công cụ) vẫn
    phải khởi động harness — các công cụ tệp/lệnh chạy bình thường, còn công cụ CUA trả
    `CUA_UNAVAILABLE`.
    """
    source = os.environ if env is None else env
    if str(source.get('BOXFOX_DESKTOP_CONTROL') or '').strip().lower() in ('0', 'off', 'false'):
        return None
    try:
        if sys.platform == 'win32':
            from ..sandbox.win import windows_platform

            platform = windows_platform.get_platform()
        elif sys.platform.startswith('linux'):
            from ..sandbox.x11 import platform as x11_platform

            platform = x11_platform.get_platform()
        else:
            return None
    except Exception:
        return None
    if platform is None or getattr(platform, 'name', '') in ('', 'unavailable'):
        return None
    try:
        return DesktopControl(profile_dir=Path(profile_dir), platform=platform)
    except Exception:
        return None


def create_app(runtime):
    @web.middleware
    async def boundary(request, handler):
        if request.host not in allowed_hosts():
            return web.json_response({'error': 'Host not allowed'}, status=403)
        if request.path != '/api/agent/health':
            if request.headers.get('X-BoxFox-Admin') != '1' or request.headers.get('Origin', 'http://localhost:3100') not in allowed_origins():
                return web.json_response({'error': 'Local administration required'}, status=403)
        try:
            return await handler(request)
        except ApiError as exc:
            # Thân lỗi RỖNG (mã trần, không kèm chi tiết) thì đừng ghép thêm ': ' — `error` phải
            # đọc ra đúng bằng `code`, không lặp mã hai lần.
            error = f'{exc.code}: {exc.message}' if exc.message else exc.code
            return web.json_response({'error': error, 'code': exc.code,
                                      **exc.extra}, status=exc.status)
        except KeyError as exc:
            # A KeyError inside a handler is an internal defect (a missing key in a payload or a
            # record) — never "the route does not exist". Reporting it as a bare `Not found` cost
            # a whole support round: the user sees one opaque word and nothing gets logged.
            logger.exception('internal error: missing key %r while handling %s %s',
                             exc.args[0] if exc.args else exc, request.method, request.path)
            return web.json_response({
                'error': f'INTERNAL_ERROR: the harness hit a missing key {exc} while handling '
                         f'{request.method} {request.path}', 'code': 'INTERNAL_ERROR'}, status=500)
        except PermissionError as exc:
            return web.json_response({'error': str(exc)}, status=403)
        except (ValueError, TypeError) as exc:
            return web.json_response({'error': str(exc)}, status=409 if any(c in str(exc) for c in ('SESSION_BUSY', 'REVISION_CONFLICT', 'INVOCATION_CONFLICT')) else 400)

    app = web.Application(middlewares=[boundary], client_max_size=1048576)

    # Bề mặt bền (history/longtask) phải có hook TRƯỚC khi có phiên nào: binding thô được ghim
    # ngay lúc tạo phiên, còn hook completion/acceptance phải sẵn sàng khi lượt đầu kết thúc.
    try:
        from ..agent_core import history_surface
        history_surface.configure_runtime(runtime)
    except Exception:
        logger.exception('history surface unavailable; history/longtask routes stay closed')

    async def heal_stored_context_windows(_app):
        """Lượt sửa một lần lúc khởi động: phiên cũ còn giữ cửa sổ ngữ cảnh đoán theo tên.

        Không được phép làm sập khởi động: router chưa lên cũng chỉ là 0 phiên được
        sửa (`heal_context_windows` trả 0 và không ghi gì).
        """
        try:
            healed = await runtime.heal_context_windows()
        except Exception:
            logger.exception('context-window heal skipped')
            return
        if healed:
            logger.info('context window healed for %s stored sessions', healed)

    app.on_startup.append(heal_stored_context_windows)

    async def start_peer_watchdog(_app):
        """T10 — sổ con phải được quét kể cả khi mọi đường dọn con khác chết theo tiến trình.

        Nhịp quét đầu tiên đóng mọi hàng `started` còn sót từ lần chạy trước bằng lý do `RESTART`:
        thao tác tool không được chạy lại, nên một con của lần chạy trước không bao giờ có kết quả —
        để nó `started` thì giao diện hiển thị "đang chạy" cho một phiên đã chết.
        """
        watchdog = PeerWatchdog(runtime.store, runtime)
        runtime.watchdog = watchdog
        watchdog.start()
        # Không ghi gì lúc khởi động: file nhật ký phải rỗng cho tới khi có VIỆC xảy ra, và việc
        # watchdog làm thì chính nó ghi (`watchdog.child_closed` / `watchdog.wait_forced`).

    app.on_startup.append(start_peer_watchdog)

    async def research_continuations(_app):
        """Resume only new durable jobs, using stored progress and the original budget."""
        plan_workflow.service(runtime).recover()
        async def pump():
            while True:
                await asyncio.sleep(15)
                await research_continuation_step(runtime)
                await design_continuation_step(runtime)
                try:
                    await plan_workflow.pump(runtime)
                    from ..agent_core import work_feedback
                    await work_feedback.pump(runtime)
                except Exception:
                    logger.exception('plan continuation deferred; durable admission will retry')
                # Tác vụ dài dùng chung một nhịp với các controller khác: hàng chờ đã ghi bền,
                # nên một nhịp lỗi không mất việc, chỉ hoãn.
                try:
                    await runtime.pump_longtasks()
                except Exception:
                    logger.exception('long task continuation deferred; durable admission will retry')
        _app[RESEARCH_PUMP_KEY] = asyncio.create_task(pump())

    async def stop_research_continuations(_app):
        task = _app.get(RESEARCH_PUMP_KEY)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.on_startup.append(research_continuations)
    app.on_cleanup.append(stop_research_continuations)

    async def recover_longtasks(_app):
        """Khôi phục tác vụ dài SAU khi graph/plan/watchdog đã dọn hàng cũ.

        `recover()` chỉ mở lại việc đã ghi bền; nó không tự chạy nếu `BOXFOX_LONGTASK_CONTINUITY`
        chưa bật, và không có hàng nào thì trả `{'spawned': 0}`. Lỗi ở đây không được làm sập
        khởi động — nhịp `pump` phía trên sẽ không nhận việc cho tới khi lần khôi phục sau chạy xong.
        """
        try:
            await runtime.recover_longtasks()
        except Exception:
            logger.exception('long task recovery deferred')

    app.on_startup.append(recover_longtasks)

    async def idle_watch(_app):
        """Nhả quyền điều khiển về tay người khi họ chạm máy, trên nền tảng không có hook.

        Windows phát hiện người thật bằng hook ``WH_MOUSE_LL``/``WH_KEYBOARD_LL``; X11 không có
        tương đương, nên ở đó ``poll_idle()`` lấy mẫu con trỏ + cửa sổ đang có tiêu điểm
        (:meth:`X11Platform.last_input_tick`) và tự nhả quyền khi thấy thay đổi mà chính agent
        không gây ra. Chỉ chạy khi nền tảng khai báo ``supports_idle_watch`` — nhờ vậy hành vi
        Windows đang chạy thật không đổi cho tới khi đường hook của nó được kiểm trên máy Windows.
        """
        # `runtime` có thể là bản giả không có `executor` (bài kiểm dựng app với runtime tối thiểu),
        # nên hỏi hai lớp bằng `getattr` — thiếu executor nghĩa là chưa có gì để theo dõi.
        control = getattr(getattr(runtime, 'executor', None), 'desktop', None)
        if not idle_watch_supported(control):
            return

        async def pump():
            while True:
                await asyncio.sleep(IDLE_WATCH_INTERVAL_SEC)
                try:
                    await asyncio.to_thread(control.poll_idle)
                except Exception:
                    logger.exception('idle watch deferred')

        _app[IDLE_WATCH_KEY] = asyncio.create_task(pump())

    async def stop_idle_watch(_app):
        task = _app.get(IDLE_WATCH_KEY)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.on_startup.append(idle_watch)
    app.on_cleanup.append(stop_idle_watch)

    def _search_status():
        """Khối `search` của health: lỗi ở đây KHÔNG được kéo cả route xuống (chỉ đọc, không mạng)."""
        try:
            from ..agent_core import web as web_module
            return web_module.search_status()
        except Exception as exc:
            return {'error': type(exc).__name__, 'reason': str(exc)[:200]}

    def desktop_control():
        """Bộ điều khiển desktop của executor đang chạy. Docker mode KHÔNG có ⇒ lỗi có mã."""
        control = getattr(runtime.executor, 'desktop', None)
        if control is None:
            raise ApiError('DESKTOP_CONTROL_UNAVAILABLE',
                           'chế độ đang chạy không điều khiển được desktop (chỉ host mode trên '
                           'Windows có)', 409)
        return control

    def desktop_lease_snapshot():
        """Snapshot lease cho health/UI — `None` khi không có hàng rào (docker mode)."""
        control = getattr(runtime.executor, 'desktop', None)
        if control is None:
            return None
        try:
            snapshot = control.snapshot()
        except Exception as exc:      # health không bao giờ được ném vì một tệp hỏng
            return {'holder': 'human', 'epoch': 0, 'error': '%s: %s' % (type(exc).__name__, exc)}
        return {'holder': snapshot.get('holder'), 'epoch': snapshot.get('epoch'),
                'generation': snapshot.get('generation'),
                'hooksInstalled': snapshot.get('hooksInstalled'),
                'mutexHeld': snapshot.get('mutexHeld'), 'mutexName': snapshot.get('mutexName'),
                'since': snapshot.get('since'), 'reason': snapshot.get('reason')}

    def machine_policy():
        """Policy của MÁY khi tiến trình chạy docker nhưng máy được cấu hình host, hoặc `None`.

        Bản desktop có thể chạy tiến trình ở chế độ docker (máy có Docker Desktop) trong khi người
        dùng chọn máy ở chế độ host: `runtime.executor.policy` khi đó là `None` nên health nói
        `policy:false`, và tab Settings → Machine & Permissions hiện "Máy này không có động cơ
        quyền" dù bốn route quyền trả 200 và phiên host vẫn chạy được (`permissions_policy()` đã
        có sẵn đúng đường đọc ấy cho các route).

        Trả `None` khi máy KHÔNG ở chế độ host hoặc chưa chọn folder: bản chỉ có Docker giữ nguyên
        trạng thái trống, không mời người dùng vào một bảng quyền không gác gì.
        """
        engine = getattr(runtime, 'machine_registry', None)
        # Đúng đối tượng mà các route quyền dùng: `SessionMachineExecutor.permissions_policy`.
        reader = getattr(getattr(runtime, 'executor', None), 'permissions_policy', None)
        if engine is None or reader is None:
            return None
        try:
            state = engine.state()
            if state.get('mode') != 'host' or not state.get('projectId'):
                return None
            if engine.active_project() is None:
                return None
            return reader()
        except Exception:                # health không bao giờ được vỡ vì một tầng phụ
            return None

    def execution_status():
        """Khối `execution` của health: đang chạy chế độ nào, quyền nào, sàn cứng chạm mấy lần.

        Đường thường rẻ như phần còn lại của health: chỉ đọc biến và bộ đếm trong bộ nhớ, KHÔNG
        chạm đĩa/mạng. Chỉ khi executor KHÔNG có policy (tiến trình docker) mới hỏi thêm sổ máy —
        một lần đọc SQLite, chỉ để nói thật trạng thái của `permissions_policy()`.
        """
        policy = getattr(runtime.executor, 'policy', None)
        if policy is None:
            policy = machine_policy()
        # `mode` là thứ ĐANG chạy (suy từ chính executor), không phải thứ được cấu hình: health phải
        # nói được sự thật kể cả khi executor được dựng tay trong test hay bởi một bản cài khác.
        # Tiến trình docker + máy cấu hình host ⇒ `policy` ở trên đến từ sổ máy, nên `mode` nói
        # `host` (máy đang phục vụ phiên host) còn `configured` vẫn nói chế độ của tiến trình.
        mode = 'host' if policy is not None else execution_mode()
        payload = {'mode': mode, 'modeDefault': EXECUTION_MODE_DEFAULT,
                   'modes': list(EXECUTION_MODES), 'configured': execution_mode()}
        if policy is None:
            payload.update({'scope': None, 'permissionMode': None, 'policy': False, 'network': None,
                            'cuaEnabled': None, 'lease': None, 'hardlineHits': 0, 'workspace': None})
            return payload
        permission_mode = policy.mode_value()
        payload.update({
            'scope': policy.scope_value(),
            'permissionMode': permission_mode,
            'network': policy.network_value(),
            'policy': True,
            'cuaEnabled': bool(permissions_module.MODE_CAPABILITIES[permission_mode]['cua']),
            # `lease` là hàng rào đồng thời thật (H7): `None` nghĩa là "máy này không có hàng rào",
            # khác hẳn `holder: human` nghĩa là "có hàng rào và người đang giữ".
            'lease': desktop_lease_snapshot(),
            'hardlineHits': policy.hardline_hits,
            'workspace': policy.workspace,
        })
        return payload

    async def health(request):
        # W6.1.3: `?probe=verify` chạy probe bwrap trong box; mặc định chỉ trả lần quan sát gần nhất
        # (health phải rẻ, không docker exec mỗi lần gọi).
        if request.query.get('probe') == 'search':
            # Dò SearXNG CHỈ khi được hỏi: `probe_searxng` là lời gọi mạng thật (2 s), không được
            # chạy trong đường health thường.
            try:
                search_pipeline.probe_now()
            except Exception:
                pass
        if request.query.get('probe') == 'verify':
            from ..agent_core import verify_exec
            try:
                answer = await runtime.executor.execute('verify_exec_probe', {'refresh': True}, 'health')
            except Exception as exc:  # box không chạy: báo thật, không giả là có isolation
                answer = {'available': False, 'reason': str(exc)[:300]}
            runtime.verify_exec_status = verify_exec.observed(answer, getattr(runtime, 'verify_exec_status', None))
        return web.json_response({'status': 'ok', 'service': 'boxfox-harness', 'version': HARNESS_VERSION,
                                  'verifyExec': getattr(runtime, 'verify_exec_status', None)
                                  or {'available': None, 'reason': 'not probed yet'},
                                  'search': _search_status(),
                                  'execution': execution_status()})

    async def catalog(request):
        return web.json_response({'roles': [{'id': r.id, 'name': r.name, 'instructions': r.instructions, 'tools': sorted(r.tools)} for r in ROLES.values()], 'skills': runtime.catalog.list(runtime.commands.settings()['enabled'])})

    async def runtime_info(request):
        """Nút vặn của runtime, chỉ đọc và không tham số — cho tab Harness của Settings.

        Bảng này là nguồn duy nhất cho mọi con số giao diện hiển thị (tám nhóm công cụ,
        bộ của từng vai trò, chính sách retry, trần bước/thời gian/ký tự): không chỗ nào
        ở phía UI được chép tay lại một con số, nếu không hai bên sẽ lệch nhau và khối
        "Tool access" sẽ hứa điều engine từ chối.
        """
        from ..agent_core import work_budget
        return web.json_response({
            'toolGroups': tool_groups(),
            # H10.2 — khối `usage`: trần chi đang mở, chỉ đọc, trần cứng 20 hàng; bảng chưa
            # có thì `[]` để tab Harness không đỏ vì tính năng chưa dùng.
            'usage': {'allocations': _open_allocations(runtime)},
            'tools': sorted(ORCHESTRATOR_TOOLS),
            'roles': [{'id': r.id, 'name': r.name, 'tools': sorted(r.tools), 'skills': list(r.skills)}
                      for r in ROLES.values()],
            'retry': {'maxRetries': DEFAULT_MAX_RETRIES,
                      'backoffSeconds': list(BACKOFF_SECONDS),
                      'rateLimitMaxSeconds': RATE_LIMIT_MAX_SECONDS,
                      'budgetSeconds': RETRY_BUDGET_SECONDS,
                      'jitter': BACKOFF_JITTER},
            'workGraphBudgets': work_budget.profiles(),
            'limits': {'instructionsChars': INSTRUCTIONS_MAX_CHARS,
                       'maxStepsDefault': MAX_STEPS_DEFAULT,
                       'maxStepsMax': MAX_STEPS_MAX,
                       'deadlineDefaultSeconds': DEADLINE_DEFAULT_SECONDS,
                       'deadlineMaxSeconds': DEADLINE_MAX_SECONDS,
                       'childMaxSteps': CHILD_MAX_STEPS,
                       'childDeadlineSeconds': CHILD_DEADLINE_SECONDS,
                       # T13 — khối `peer`: giao diện đọc trần từ ĐÂY, không chép tay con số. Bốn giá
                       # trị `*Now` là giá trị ĐANG có hiệu lực (env đọc ở thời điểm gọi), khác với
                       # hằng số mặc định: một máy đang chạy `BOXFOX_PEER_FANOUT=1` phải thấy 1.
                       'peer': {'enabled': peer_mesh_enabled(),
                                'fanoutPerParentDefault': FANOUT_PER_PARENT_DEFAULT,
                                'fanoutPerParentMax': FANOUT_PER_PARENT_MAX,
                                'fanoutPerParentNow': runtime.fanout_limit({}),
                                'fanoutGlobalCeiling': FANOUT_GLOBAL_CEILING,
                                'deliverMax': PEER_DELIVER_MAX,
                                'waitSafetySeconds': PEER_WAIT_SAFETY_SECONDS,
                                'waitMaxSeconds': PEER_WAIT_MAX_SECONDS,
                                'waitMaxNow': peer_wait_max(),
                                'parallelReadTools': parallel_read_tools_enabled(),
                                'watchdogTickSeconds': WATCHDOG_TICK_SECONDS,
                                'childWallMaxSeconds': CHILD_WALL_MAX_SECONDS},
                       # Đợt 3 (P3.5) — nhóm `gate`: giao diện và DEV đọc trạng thái THẬT của cổng
                       # bằng chứng từ đây, không chép tay con số nào.
                       'gate': {'evidenceMode': runtime.evidence_mode()[0],
                                'modes': list(EVIDENCE_MODES),
                                'default': EVIDENCE_DEFAULT_MODE,
                                'repairMaxTokens': EVIDENCE_REPAIR_MAX_TOKENS,
                                'repairTimeoutSeconds': EVIDENCE_REPAIR_TIMEOUT_SECONDS,
                                'repairMinRemainingSeconds': EVIDENCE_REPAIR_MIN_REMAINING_SECONDS,
                                'probeTimeoutSeconds': EVIDENCE_PROBE_TIMEOUT_SECONDS,
                                'probeMaxFiles': EVIDENCE_PROBE_MAX_FILES,
                                'maxArtifacts': EVIDENCE_MAX_ARTIFACTS,
                                # Vòng 25 (D-33..D-35) — cùng nhóm `gate` nói luôn trạng thái THẬT
                                # của hai cổng vòng lặp kế hoạch: giao diện không chép tay con số nào,
                                # và DEV thấy được mức đang áp của cổng phản biện/nguồn.
                                'planVerifyMode': runtime.plan_verify_mode()[0],
                                'planVerifyModes': list(PLAN_VERIFY_MODES),
                                'planVerifyDefault': PLAN_VERIFY_DEFAULT_MODE,
                                'planSourcesMode': runtime.plan_sources_mode()[0],
                                'planSourcesModes': list(PLAN_SOURCES_MODES),
                                'planSourcesDefault': PLAN_SOURCES_DEFAULT_MODE,
                                'planReviewMinAnswerChars': PLAN_REVIEW_MIN_ANSWER_CHARS,
                                'planVerifyReviseMax': PLAN_VERIFY_REVISE_MAX,
                                'planTurnExtensionSeconds': PLAN_TURN_EXTENSION_SECONDS,
                                # Vòng 27 (đợt 4, A5) — cùng nhóm `gate`: mức ĐANG ÁP của cổng chất
                                # lượng research và giá trị thô khi env đặt sai (khuôn `evidenceMode`),
                                # kèm tóm tắt ghi đè thang nguồn. Bản đầy đủ nằm ở khối `research`.
                                'researchGate': {'mode': research_quality.gate_mode()[0],
                                                 'modes': list(RESEARCH_GATE_MODES),
                                                 'default': RESEARCH_GATE_DEFAULT_MODE,
                                                 # `gate_mode()` đã trả `None` khi giá trị hợp lệ.
                                                 'unknown': research_quality.gate_mode()[1]},
                                'researchTiers': {'overrides': source_tiers.overrides_summary(),
                                                  'tiers': {str(key): value
                                                            for key, value in source_tiers.TIERS.items()}}},
                       # Vòng 27 (đợt 1, A-9) — khối `web`: giao diện và DEV đọc mức ĐANG ÁP của
                       # lớp đọc nguồn từ đây, không chép tay con số nào. `textHardChars` là trần
                       # một lời gọi; `storeMaxEntries` là trần bộ đệm đọc (A-4).
                       # Vòng 27 (đợt 5–8) — khối `research`: mức ĐANG ÁP của bốn công tắc mới
                       # (`brief`/`gate`/`progress`/`steer`) và hạn mức theo mức. `*Now` là giá trị
                       # đọc ở thời điểm gọi, đúng khuôn khối `peer`.
                       'research': {'briefMode': research_runtime.brief_mode()[0],
                                    'briefModes': list(RESEARCH_BRIEF_MODES),
                                    'briefDefault': RESEARCH_BRIEF_DEFAULT_MODE,
                                    'gateMode': research_runtime.research_quality.gate_mode()[0],
                                    'gateModes': list(RESEARCH_GATE_MODES),
                                    'gateDefault': RESEARCH_GATE_DEFAULT_MODE,
                                    'progressMode': research_runtime.research_progress_mode()[0],
                                    'progressModes': list(RESEARCH_PROGRESS_MODES),
                                    'progressDefault': RESEARCH_PROGRESS_DEFAULT_MODE,
                                    'progressNudgeSeconds': RESEARCH_PROGRESS_NUDGE_SECONDS,
                                    'steerMode': research_runtime.steer_mode()[0],
                                    'steerModes': list(STEER_MODES),
                                    'steerDefault': STEER_DEFAULT_MODE,
                                    'steerMaxPending': STEER_MAX_PENDING,
                                    'steerTextMaxChars': STEER_TEXT_MAX_CHARS,
                                    'tiers': list(RESEARCH_TIERS),
                                    'tierDefault': RESEARCH_TIER_DEFAULT,
                                    'tierLimits': {str(tier): research_runtime.research_tier_limits(tier)
                                                   for tier in RESEARCH_TIERS},
                                    'profiles': research_profiles.describe(),
                                    # Thang nguồn: bốn tầng + tầng 0 (host-doc), nhãn loại,
                                    # và tóm tắt ghi đè từ env (`source`, `hosts`, `officialSocial`,
                                    # `unknown`) — DEV đọc ở đây, không chép tay con số nào.
                                    'sourceTiers': {'tiers': {str(key): value
                                                              for key, value in source_tiers.TIERS.items()},
                                                    'tierLabels': {str(key): value
                                                                   for key, value in source_tiers.TIER_LABELS.items()},
                                                    'typeLabels': dict(source_tiers.TYPE_LABELS),
                                                    'overrides': source_tiers.overrides_summary()},
                                    'reviewMinAnswerChars': RESEARCH_REVIEW_MIN_ANSWER_CHARS,
                                    'verifyReviseMax': RESEARCH_VERIFY_REVISE_MAX,
                                    'maxRowsPerDossier': RESEARCH_MAX_ROWS_PER_DOSSIER,
                                    'maxDossierBytes': DOSSIER_MAX_BYTES,
                                    'childStepsByTier': dict(RESEARCH_TIER_CHILD_STEPS),
                                    'childSecondsByTier': dict(RESEARCH_TIER_CHILD_SECONDS),
                                    'hardCeilingSecondsByTier': dict(RESEARCH_TIER_HARD_CEILING_SECONDS)},
                       'web': {'readerMode': runtime.web_reader_mode()[0],
                               'readerModes': list(WEB_READER_MODES),
                               'readerDefault': WEB_READER_DEFAULT_MODE,
                               'readStoreMode': runtime.web_read_store_mode()[0],
                               'readStoreModes': list(WEB_READ_STORE_MODES),
                               'readStoreDefault': WEB_READ_STORE_DEFAULT_MODE,
                               'textHardChars': MAX_TEXT_HARD,
                               'storeMaxEntries': READ_STORE_MAX_ENTRIES},
                       'search': {'pipelineMode': search_pipeline.pipeline_mode(),
                                  'pipelineModes': ['off', 'on', 'auto'],
                                  'pipelineDefault': 'auto',
                                  'autodetect': search_pipeline.autodetect_enabled(),
                                  'autodetectUrl': search_pipeline.autodetect_url(),
                                  'autodetectEnv': search_pipeline.SEARXNG_AUTODETECT_ENV,
                                  'engineRotation': SEARCH_ENGINE_ROTATION_N,
                                  'topK': SEARCH_PIPELINE_TOP_K,
                                  'cacheTtlSeconds': SEARCH_CACHE_TTL_SECONDS,
                                  'searxngTimeoutSeconds': SEARXNG_TIMEOUT_SECONDS}},
        })

    async def skill_settings(request):
        return web.json_response(runtime.commands.settings() if request.method == 'GET' else runtime.commands.configure(await request.json()))

    # Chỉ dẫn của chủ máy: một tài liệu + `revision` (bảng riêng, xem owner_settings.py).
    # Cùng khuôn với skill-settings: GET đọc, PUT ghi kèm `revision` và trả bản mới.
    owner_directives = OwnerSettings(runtime.store)

    async def owner_settings(request):
        return web.json_response(owner_directives.settings() if request.method == 'GET'
                                 else owner_directives.configure(await request.json()))

    async def commands(request):
        if request.method == 'GET':
            return web.json_response({'commands': runtime.commands.list(), 'custom': runtime.commands.custom()})
        return web.json_response(runtime.commands.save(await request.json()), status=201)

    async def command(request):
        value = await request.json()
        if request.method == 'DELETE':
            runtime.commands.delete(request.match_info['slug'], value.get('revision'))
            return web.json_response({'status': 'deleted'})
        return web.json_response(runtime.commands.save(value, request.match_info['slug']))

    async def resolve(request):
        return web.json_response(runtime.commands.preview((await request.json()).get('prompt')))

    async def executor_status(request):
        from ..sandbox.claude_executor import ClaudeExecutor
        container = getattr(runtime.executor, 'container', None)
        if container is None:
            # Host mode không có container: trả lời được câu hỏi thay vì ném AttributeError.
            return web.json_response({'status': 'unavailable', 'reason': 'executor has no container (host mode)'})
        return web.json_response(await ClaudeExecutor(container).probe())

    def permission_policy():
        """Chính sách quyền của máy này. Docker mode KHÔNG có ⇒ lỗi có mã, không 500.

        Ở bản desktop, tiến trình có thể đang chạy chế độ docker trong khi máy được cấu hình host
        (phiên IDE chạy trên máy thật). Khi đó executor không có `policy` nhưng `SessionMachineExecutor`
        vẫn dựng được policy của folder dự án — nhờ vậy nút chọn quyền ở thanh chat và tab
        Settings → Machines đọc/ghi được thay vì trả 409.
        """
        policy = getattr(runtime.executor, 'policy', None)
        if policy is None:
            provider = getattr(runtime.executor, 'permissions_policy', None)
            if callable(provider):
                try:
                    policy = provider()
                except Exception:      # thiếu folder/quyền đọc ⇒ coi như máy không có động cơ quyền
                    policy = None
        if policy is None:
            raise ApiError('PERMISSIONS_UNAVAILABLE',
                           'chế độ đang chạy không có động cơ quyền (chỉ host mode có)', 409)
        return policy

    async def permissions(request):
        """`GET` đọc toàn bộ chính sách; `PUT` đổi `mode`/`scope` và ghi xuống tầng đã chọn.

        Ghi vào tầng nào là tham số (`layer`), mặc định tầng `user` (`~/.boxfox/settings.json`) —
        đó là chỗ "sở thích của người dùng" nằm, còn `managed` là của bản cài và không sửa từ UI.
        """
        policy = permission_policy()
        if request.method == 'PUT':
            payload = await request.json()
            layer = str(payload.get('layer') or permissions_module.LAYER_USER).strip().lower()
            if layer not in policy.paths:
                raise ApiError('PERMISSION_LAYER_UNKNOWN', 'tầng `%s` không tồn tại' % layer, 400)
            data = dict(policy.layers.get(layer) or {})
            changed = {}
            mode = str(payload.get('mode') or '').strip().lower()
            if mode:
                if mode not in permissions_module.MODES:
                    raise ApiError('PERMISSION_MODE_UNKNOWN', 'chế độ `%s` không có' % mode, 400)
                data['mode'] = mode
                changed['mode'] = mode
            scope = str(payload.get('scope') or '').strip().lower()
            if scope:
                if scope not in permissions_module.SCOPES:
                    raise ApiError('PERMISSION_SCOPE_UNKNOWN', 'phạm vi `%s` không có' % scope, 400)
                data['scope'] = scope
                changed['scope'] = scope
            network = str(payload.get('network') or '').strip().lower()
            if network:
                if network not in permissions_module.NETWORKS:
                    raise ApiError('PERMISSION_NETWORK_UNKNOWN', 'mức mạng `%s` không có' % network, 400)
                data['network'] = network
                changed['network'] = network
            if not changed:
                raise ApiError('PERMISSION_UPDATE_EMPTY', 'cần `mode`, `scope` hoặc `network`', 400)
            error = permissions_module._write_json(policy.paths[layer], data)
            if error:
                raise ApiError('PERMISSION_WRITE_FAILED', error, 409)
            policy.reload()
            system_log.write('permissions.updated', level='info', message='quyền đã đổi từ UI',
                             data={'layer': layer, **changed})
        snapshot = policy.snapshot()
        snapshot['execution'] = execution_status()
        return web.json_response(snapshot)

    async def permissions_decide(request):
        """Hỏi động cơ quyền, và (khi người dùng đã trả lời) ghi nhớ quyết định đó.

        Thẻ duyệt của giao diện gọi đúng route này hai lần: lần đầu để lấy `reason`/`rule` hiện
        lên thẻ, lần sau kèm `decision` để chốt. `allow_always` mới ghi luật xuống đĩa — và luật đó
        vẫn phải qua kiểm tra phạm vi của động cơ.
        """
        payload = await request.json()
        tool = str(payload.get('tool') or '').strip()
        if not tool:
            raise ApiError('PERMISSION_TOOL_REQUIRED', 'cần `tool`', 400)
        args = payload.get('args') if isinstance(payload.get('args'), dict) else {}
        session_id = payload.get('sessionId') or None
        actor = str(payload.get('actor') or 'user')
        policy = permission_policy()
        decision = policy.decide(tool, args, session_id=session_id, actor=actor)
        # Quyết định phải vào ĐÚNG policy mà phiên đọc lúc gọi tool. Phiên IDE có policy riêng
        # (`SessionMachineExecutor.session_policy`), nên ghi vào policy dùng chung của folder thì
        # "cho phép cả phiên" trên thẻ chỉ là lời hứa suông (vòng review đợt 1b).
        remember = policy
        provider = getattr(runtime.executor, 'policy_for_session', None)
        if session_id and callable(provider):
            try:
                remember = provider(session_id) or policy
            except Exception:
                remember = policy
        answer = str(payload.get('decision') or '').strip().lower()
        extra = {}
        if answer:
            if answer not in ('allow', 'allow_session', 'allow_always', 'deny'):
                raise ApiError('PERMISSION_DECISION_UNKNOWN', 'quyết định `%s` không có' % answer, 400)
            if answer == 'deny':
                remember.note_denial(session_id)
                extra['breaker'] = remember.denials.get(str(session_id or ''), 0) >= permissions_module.DENIAL_BREAKER_LIMIT
            else:
                remember.note_approval(session_id)
                # Cùng khoá với `decide()` — kể cả mã phiên và tài nguyên, nếu không thì lần hỏi sau
                # lại thấy `ask` dù người dùng đã chọn "cho phép cả phiên".
                key = remember.session_key(tool, args, cwd=remember.workspace, session_id=session_id)
                # Nhóm "luôn hỏi" là một lần cho một lần: ghi nhớ nó sẽ tạo một luật chết trong
                # `.boxfox/settings.local.json` mà `decide()` không bao giờ đọc (vòng review đợt 1b).
                guarded = str(decision.rule or '').startswith('guarded:')
                if answer in ('allow_session', 'allow_always') and not guarded:
                    remember.remember(key, permissions_module.allow('', 'user'), 'session')
                if answer == 'allow_always' and not guarded:
                    ok, code, message, rules = remember.save_rule(tool, args, actor=actor,
                                                                  session_id=session_id)
                    extra.update({'saved': ok, 'saveCode': code, 'saveMessage': message, 'rules': rules})
                elif answer == 'allow_always':
                    extra.update({'saved': False, 'saveCode': 'GUARDED_SINGLE_SHOT',
                                  'saveMessage': 'Lệnh thuộc nhóm luôn hỏi: chỉ cho phép một lần.'})
            extra['decision'] = answer
        return web.json_response({'tool': tool, 'sessionId': session_id,
                                  'outcome': decision.outcome, 'reason': decision.reason,
                                  'rule': decision.rule, 'layer': decision.layer, **extra})

    async def permissions_pending(request):
        policy = permission_policy()
        return web.json_response({'pending': policy.pending_items()})

    async def permissions_rules(request):
        """`GET` liệt kê luật kèm tệp nguồn; `DELETE` thu hồi một luật (màn Settings → Quyền)."""
        policy = permission_policy()
        if request.method == 'DELETE':
            payload = await request.json()
            rule = str(payload.get('rule') or '').strip()
            if not rule:
                raise ApiError('PERMISSION_RULE_REQUIRED', 'cần `rule`', 400)
            layer = str(payload.get('layer') or '').strip().lower() or None
            ok, code, message = policy.revoke_rule(rule, layer)
            if not ok:
                raise ApiError('PERMISSION_REVOKE_FAILED', message, 409)
            system_log.write('permissions.revoked', level='info', message='luật đã bị thu hồi',
                             data={'rule': rule})
            return web.json_response({'ok': True, 'message': message})
        snapshot = policy.snapshot()
        return web.json_response({'rules': snapshot['rules'], 'sources': snapshot['ruleSources'],
                                  'layers': snapshot['layers']})

    # -- H7: bề mặt CUA (lease + soi phần tử) -------------------------------

    async def desktop_lease(request):
        """`GET` đọc lease; `POST` đổi người giữ quyền.

        `claim` là nút "Trả quyền cho agent" của NGƯỜI DÙNG — đường duy nhất được phép `force`; agent
        không có cách nào tự gọi nó. `release` là nút "Dừng/Trả quyền" (đưa về người). `stop` là nút
        Dừng khẩn: tăng epoch + generation, nhả phím/chuột đang giữ, đưa lease về người.
        """
        control = desktop_control()
        if request.method == 'GET':
            return web.json_response(desktop_lease_snapshot() or {})
        payload = await request.json()
        action = str(payload.get('action') or '').strip().lower()
        reason = str(payload.get('reason') or '').strip()
        viewer_id = payload.get('viewerId') or None
        if action == 'claim':
            ok, state, error = control.agent_lease(reason or 'người dùng trả quyền cho agent',
                                                   viewer_id=viewer_id, force=True)
            code = '' if ok else state
            if not ok:
                raise ApiError('DESKTOP_LEASE_FAILED', str(error or code), 409)
        elif action == 'release':
            control.release_to_human(reason or 'người dùng lấy lại quyền', viewer_id=viewer_id)
        elif action == 'stop':
            control.emergency_stop(reason or 'nút Dừng khẩn')
        else:
            raise ApiError('DESKTOP_LEASE_ACTION_UNKNOWN',
                           'hành động `%s` không có (nhận: claim, release, stop)' % action, 400)
        system_log.write('desktop.lease', level='info', message='lease đổi từ UI',
                         data={'action': action, 'reason': reason})
        return web.json_response(desktop_lease_snapshot() or {})

    async def desktop_inspect_element(request):
        """Soi phần tử tại một điểm framebuffer — đường của khung Element Selector ở host mode.

        Cùng hình dạng phản hồi với `/__box/inspect-element` của box, nên giao diện không phải biết
        mình đang ở chế độ nào. Lỗi nền tảng giữ NGUYÊN mã (`ELEMENT_STALE`, `DESKTOP_LOCKED`, …).
        """
        from ..agent_core import inspect_host
        control = desktop_control()
        granted, state, _error = control.agent_lease('người dùng soi phần tử')
        if not granted:
            snapshot = control.snapshot() or {}
            raise ApiError('HUMAN_HAS_CONTROL', 'người dùng đang điều khiển máy — chưa soi được',
                           409, {'holder': snapshot.get('holder')})
        payload = await request.json()
        try:
            x, y = int(payload.get('x')), int(payload.get('y'))
        except (TypeError, ValueError):
            raise ApiError('INSPECT_POINT_INVALID', 'cần toạ độ nguyên (x, y)', 400)
        try:
            result = inspect_host.inspect_element(x, y)
        except Exception as exc:
            code = getattr(exc, 'code', None) or 'INSPECT_FAILED'
            raise ApiError(code, str(exc), 409)
        return web.json_response(result)

    async def skill(request):
        return web.json_response(runtime.catalog.read(request.match_info['skill']))

    async def readiness(request):
        sid = request.match_info['skill']
        # `catalog.items[sid]` raises KeyError for an unknown skill; the middleware now reports
        # that as a 500, which is the right answer for a bug and the wrong one for a typo in a
        # URL. Validate here so an unknown skill is the 404 the client can act on.
        if sid not in runtime.catalog.items:
            raise ApiError('SKILL_NOT_FOUND', f'skill {sid} is not in this harness catalog', 404)
        item = runtime.catalog.items[sid]
        if sid == 'claude-code':
            return await executor_status(request)
        if sid in {'codex', 'opencode'}:
            return web.json_response({'status': 'adapter_unavailable'})
        payload = runtime.catalog.read(sid)
        result = await runtime.executor.execute('__skill_readiness', {'basePath': payload['basePath'],
            'requirements': item['requirements'], 'platforms': item['platforms']}, 'skill-readiness')
        return web.json_response(result)

    async def create(request):
        value = await request.json()
        if not isinstance(value, dict):
            raise ValueError('JSON object required')
        # The router owns provider metadata (context window AND its source label). Read it once per
        # session and hand the whole record to the harness: `runtime.resolve_context_window` reads the
        # number and the label together, so nothing here may overwrite the request's own value — a copy
        # guarded by a falsy check used to drop an explicit 0 or an inherited number silently.
        if value.get('connectionId') and value.get('modelId'):
            metadata = await runtime.client.model_metadata(value.get('connectionId'), value.get('modelId'))
            if metadata:
                value['modelMetadata'] = metadata
        elif value.get('providerId') and value.get('modelId'):
            # Route provider: phiên không nói trước connection nào sẽ phục vụ lượt (router tự
            # chọn trong nhóm và failover khi hết hạn mức), nên record phải là bản GỘP của mọi
            # connection dùng được — cùng luật `aggregate_model_metadata` của harness.
            metadata = await runtime.client.provider_model_metadata(value.get('providerId'), value.get('modelId'))
            if metadata:
                value['modelMetadata'] = metadata
        # Tab Instructions nói tài liệu áp cho phiên MỚI, nhưng chỉ đường giao diện gửi
        # chỉ dẫn kèm yêu cầu; một phiên tạo không qua giao diện (script, lịch chạy) trước
        # đây không nhận được gì dù tài liệu đã lưu. Thiếu hẳn `instructions` trong yêu cầu
        # thì đọc tài liệu đang lưu, cắt bằng cùng trần với runtime. Engine không đổi luật:
        # nó vẫn chỉ đọc `values['instructions']`, và chỉ dẫn client gửi kèm luôn thắng.
        if not str(value.get('instructions') or '').strip():
            value['instructions'] = owner_directives.for_engine()
        from ..sandbox.machine_router import MachineError
        try:
            return web.json_response(runtime.create(value), status=201)
        except MachineError as exc:
            raise ApiError(exc.code, str(exc), exc.status) from None

    async def list_sessions(request):
        limit = min(100, max(1, int(request.query.get('limit', '50'))))
        return web.json_response({'sessions': runtime.store.list(limit)})

    async def research_jobs(request):
        sid = request.query.get('sessionId', '').strip()
        if not sid:
            raise ApiError('RESEARCH_SESSION_REQUIRED', 'sessionId is required')
        try:
            runtime.store.get(sid)
        except KeyError:
            raise missing_session(sid) from None
        jobs = runtime.store.research_jobs_for(sid)
        return web.json_response({'jobs': [{**job,
            # P2/P4 (§5.5, §5.12): giao diện đọc bản bao phủ và bản đồ hướng của run. Đo lại khi
            # ĐỌC (`write=False`) nên không ghi gì; tắt `BOXFOX_RESEARCH_COVERAGE` thì trả `{}`.
            'coverage': research_runtime.coverage_refresh(runtime, job['research_id'],
                                                          write=False),
            'facets': runtime.store.facet_list(job['research_id']),
            # P1 (§5.12): bơm/API/giao diện đọc `phase`, `origin` và `scope.revision` ngoài `status`.
            'phase': (job['state'] or {}).get('phase'),
            'origin': (job['state'] or {}).get('origin'),
            'background': bool((job['state'] or {}).get('background')),
            'scopeRevision': int(((job['state'] or {}).get('scope') or {}).get('revision') or 0),
            'usedSeconds': runtime.store.research_job_used_seconds(sid, job['research_id']),
            'remainingSeconds': max(0, job['state'].get('budgetSeconds', 0)
                                    - runtime.store.research_job_used_seconds(sid, job['research_id'])),
            # Bằng chứng của CHÍNH run (cặp nhận định/đoạn trích/nguồn + mức truy cập + quan hệ đã
            # soát), không phải cả sổ của phiên: thẻ báo cáo đếm nguồn theo run, dòng thời gian đếm
            # nguồn theo mức truy cập (bảng 4.8).
            'evidence': research_runtime.evidence_rows(runtime, sid, job['research_id'], limit=20),
            'evidenceGraph': runtime.store.evidence_graph(sid, limit=50),
            'dependentPlans': runtime.store.research_dependent_plans(job['research_id']),
            'branches': [{**branch, 'questionId':
                          (runtime.store.get(branch['session_id'])['config'] or {}).get('researchQuestionId')}
                         for branch in runtime.store.children_of(sid)],
            'dossier': runtime.store.dossier_latest(job['research_id']),
            'reviews': runtime.store.research_verifications(job['research_id'], limit=10),
            } for job in jobs]})

    async def research_job_update(request):
        research_id = request.match_info['research_id']
        job = runtime.store.research_job(research_id)
        if job is None:
            raise ApiError('RESEARCH_JOB_UNKNOWN', research_id, 404)
        body = await request.json()
        action = str(body.get('action') or '')
        if action not in {'pause', 'resume', 'cancel', 'prioritize', 'skip', 'budget', 'scope',
                          'deepen', 'refresh'}:
            raise ApiError('RESEARCH_ACTION_INVALID', action)
        if action == 'scope':
            # §5.12: chủ nhà sửa thẻ phạm vi trên giao diện. Khoá lạc quan là `revision` của THẺ.
            try:
                return web.json_response(research_runtime.scope_update(runtime, job['session_id'],
                                                                       job, body))
            except ValueError as exc:
                raise _action_error(exc, _RESEARCH_CONFLICT_STATUS) from None
        if action == 'deepen':
            # §5.12: xin đào sâu một câu hỏi/hướng — xếp vào hàng đợi của run, nâng ưu tiên facet.
            try:
                return web.json_response(research_runtime.deepen(runtime, job['session_id'],
                                                                 job, body))
            except ValueError as exc:
                raise _action_error(exc, _RESEARCH_CONFLICT_STATUS) from None
        if action == 'refresh':
            # P5 (§5.8, use case H): mở RUN LÀM MỚI kế thừa sổ nguồn của một run đã có hồ sơ. Công
            # tắc `BOXFOX_RESEARCH_REFRESH=off` do chính `refresh_run` chặn (một chỗ đọc công tắc).
            try:
                return web.json_response(await research_runtime.refresh_run(
                    runtime, runtime.store.get(job['session_id']), job, body))
            except ValueError as exc:
                raise _action_error(exc, _RESEARCH_CONFLICT_STATUS) from None
        if action in {'pause', 'cancel'}:
            # P1 (§5.3/M-09): dừng theo JOB — KHÔNG `runtime.stop(session)`. Huỷ con của job, và chỉ
            # dừng lượt đang chạy khi nó đúng là lượt tiếp tục của job này.
            halted = await runtime.research_halt(job, 'pause' if action == 'pause' else 'cancel')
            return web.json_response({'job': halted})
        state = dict(job['state'])
        status = job['status']
        if action == 'resume':
            status = 'researching'
            if job['status'] not in {'paused', 'partial', 'needs_user'}:
                raise ApiError('RESEARCH_RESUME_INVALID', 'Job is not paused or partial')
            # A paused job may have stopped in the same turn the pump last saw.
            # Explicit resume must wake it even without a new user turn.
            state['lastContinuationTurn'] = -1
            state['stalledTurns'] = 0
        elif action == 'budget':
            seconds = body.get('budgetSeconds')
            if isinstance(seconds, bool) or not isinstance(seconds, int) or not 60 <= seconds <= 86400:
                raise ApiError('RESEARCH_BUDGET_INVALID', 'budgetSeconds must be 60..86400')
            state['budgetSeconds'] = seconds
        else:
            qid = str(body.get('questionId') or '')
            question = next((item for item in state.get('questions', []) if item['id'] == qid), None)
            if question is None:
                raise ApiError('RESEARCH_QUESTION_UNKNOWN', qid, 404)
            if action == 'skip':
                question['status'] = 'blocked'
                question['note'] = str(body.get('reason') or 'Skipped by user')[:1000]
            else:
                question['importance'] = str(body.get('importance') or 'high')
        try:
            updated = runtime.store.research_job_save(research_id, job['session_id'], state,
                                                      status=status, revision=body.get('revision'))
        except ValueError as exc:
            raise _action_error(exc, _RESEARCH_CONFLICT_STATUS) from None
        if action == 'resume' and (job['state'] or {}).get('phase') == research_runtime.PHASE_DONE:
            # B1/C1 (§5.3): `completed`/`partial` là pha ĐÓNG, mà `resume` mở LẠI run — một run đang
            # chạy lại không được mang pha `done`, nếu không luật "done là cuối" chặn mọi bước tiến pha
            # sau đó và thanh tiến trình nói "xong" cho một run vừa được hồi sức. Chỉ run ĐÃ ĐÓNG mới
            # cần rời `done`; một run `paused` giữ nguyên pha thật của nó lúc bị tạm dừng. `set_phase`
            # trả về hàng job vừa ghi, nên không cần đọc lại lần nữa.
            updated = research_runtime.set_phase(runtime, job['session_id'], updated, 'searching',
                                                'owner-resume', force=True) or updated
        if action == 'skip':
            owner = runtime.store.get(job['session_id'])
            for branch in runtime.store.children_of(job['session_id']):
                if branch.get('role') != 'research' or branch.get('status') != 'started':
                    continue
                child = runtime.store.get(branch['session_id'])
                if child['config'].get('researchQuestionId') == qid:
                    await research_runtime.cancel_child(runtime, owner, {
                        'sessionId': branch['session_id'], 'reason': 'Question skipped by user'})
        return web.json_response({'job': updated})

    async def research_mode_set(request):
        """P1 (§5.12): `PUT /api/agent/sessions/{sid}/research-mode` — bật/tắt mode.

        Tắt khi có run đang hoạt động mà thiếu lựa chọn ⇒ 409 `RESEARCH_EXIT_CHOICE_REQUIRED` kèm
        một lời hỏi `exit-choice`; mode KHÔNG đổi (M-10c).
        """
        sid = request.match_info['sid']
        session = known_session(sid)
        body = await request.json()
        if 'on' not in body:
            raise ApiError('RESEARCH_MODE_BODY_INVALID', 'body needs `on` (true/false)')
        # F4: công tắc `BOXFOX_RESEARCH_MODE=off` giết cả tính năng (lệnh `/research` là lệnh vai
        # cũ, hai cổng brief tắt, bơm từ chối job của mode). API phải nói THẲNG điều đó thay vì bật
        # lên một chế độ nửa vời mà phần còn lại của hệ thống không phục vụ.
        from ..agent_core import runtime as runtime_module
        from ..agent_core.limits import RESEARCH_MODE_UNAVAILABLE_CODE
        if not runtime_module.research_mode_available():
            raise ApiError(RESEARCH_MODE_UNAVAILABLE_CODE,
                           'Research mode is switched off in this build (BOXFOX_RESEARCH_MODE=off) — '
                           'turn the switch on before using it', 409)
        try:
            if body.get('on') is True and plan_workflow.mode(session)['on']:
                await runtime.stop(sid)
                plan_workflow.service(runtime).set_mode(runtime, sid, False, by='research')
                session = known_session(sid)
            result = research_runtime.apply_research_mode(runtime, session, body)
        except ValueError as exc:
            payload = getattr(exc, 'payload', None)
            if isinstance(payload, dict) and payload.get('prompt'):
                raise ApiError(payload.get('code') or 'RESEARCH_EXIT_CHOICE_REQUIRED', str(exc),
                               int(payload.get('status') or 409), extra={'prompt': payload['prompt']}) from None
            raise
        return web.json_response(result)

    async def research_prompt_answer(request):
        """P1 (§5.12): trả lời MỘT lời hỏi nhiều câu trong MỘT lần gọi (M-17).

        `start=true` (nút "Bắt đầu") ⇒ run rời `needs_user` và mở lượt tiếp tục; nhận cả khi mode
        đã tắt nếu run đang chạy nền.
        """
        prompt_id = request.match_info['prompt_id']
        body = await request.json()
        job = runtime.store.research_job_by_prompt(prompt_id)
        if job is None:
            raise ApiError('RESEARCH_PROMPT_UNKNOWN', prompt_id, 404)
        try:
            result = research_runtime.answer_prompt(runtime, job['session_id'], job,
                                                    {**body, 'promptId': prompt_id})
        except ValueError as exc:
            # D-7 (vòng kiểm thử P2–P5): đi qua `_action_error` như các handler anh em. Truyền nguyên
            # `text` (đã chứa mã) vào `message` khiến middleware ghép mã LẦN HAI:
            # `error = "CODE: CODE: chi tiết"` — người dùng đọc thấy mã lặp.
            raise _action_error(exc, {'RESEARCH_SCOPE_REVISION_STALE': 409}) from None
        if result.get('resume'):
            session = runtime.store.get(job['session_id'])
            if session['status'] not in {'running', 'awaiting_decision'}:
                updated = runtime.store.research_job(job['research_id'])
                if research_job_pumpable(runtime, updated, session):
                    await runtime.submit(job['session_id'],
                        f'Continue research job {job["research_id"]} from research_status after the owner '
                        'answered the scope prompt. Apply the confirmed answers, then continue the plan.',
                        invocation_id=f'research-resume-{job["research_id"]}-prompt')
        return web.json_response(result)

    async def research_prompt_dismiss(request):
        """P1 (§4.6, M-15): đóng lời hỏi thoát mà KHÔNG chọn ⇒ không đổi gì."""
        prompt_id = request.match_info['prompt_id']
        job = runtime.store.research_job_by_prompt(prompt_id)
        if job is None:
            raise ApiError('RESEARCH_PROMPT_UNKNOWN', prompt_id, 404)
        try:
            return web.json_response(research_runtime.dismiss_prompt(runtime, job['session_id'], job, prompt_id))
        except ValueError as exc:
            raise ApiError('RESEARCH_PROMPT_UNKNOWN', str(exc), 404) from None

    async def research_job_detail(request):
        """P1 (§5.12): `GET /api/agent/research/jobs/{id}` — chi tiết một run cho tab Research."""
        research_id = request.match_info['research_id']
        job = runtime.store.research_job(research_id)
        if job is None:
            raise ApiError('RESEARCH_JOB_UNKNOWN', research_id, 404)
        sid = job['session_id']
        state = job['state'] if isinstance(job.get('state'), dict) else {}
        return web.json_response({
            'job': {**job, 'phase': state.get('phase'), 'origin': state.get('origin'),
                    'background': bool(state.get('background')),
                    'scopeRevision': int((state.get('scope') or {}).get('revision') or 0),
                    'usedSeconds': runtime.store.research_job_used_seconds(sid, research_id),
                    'coverage': research_runtime.coverage_refresh(runtime, research_id,
                                                                  write=False),
                    'facets': runtime.store.facet_list(research_id)},
            'scope': state.get('scope') or {},
            'prompts': state.get('prompts') or [],
            'questions': state.get('questions') or [],
            'findings': state.get('findings') or [],
            'blockedSources': state.get('blockedSources') or [],
            'evidence': research_runtime.evidence_rows(runtime, sid, research_id, limit=50),
            'dossier': runtime.store.dossier_latest(research_id),
            'reviews': runtime.store.research_verifications(research_id, limit=10)})

    def design_job_known(design_id):
        job = runtime.store.design_job(design_id)
        if job is None:
            raise ApiError('DESIGN_JOB_UNKNOWN', design_id, 404)
        return job

    async def design_mode_set(request):
        """P1 (design-interfaces §5): `PUT /api/agent/sessions/{sid}/design-mode` — bật/tắt mode.

        Tắt khi có run đang hoạt động mà thiếu lựa chọn ⇒ 409 `DESIGN_EXIT_CHOICE_REQUIRED` kèm một
        lời hỏi `exit-choice`; mode KHÔNG đổi.
        """
        sid = request.match_info['sid']
        known_session(sid)
        body = await request.json()
        if 'on' not in body:
            raise ApiError('DESIGN_MODE_BODY_INVALID', 'body needs `on` (true/false)')
        from ..agent_core import runtime as runtime_module
        from ..agent_core.limits import DESIGN_MODE_UNAVAILABLE_CODE
        if not runtime_module.design_mode_available():
            raise ApiError(DESIGN_MODE_UNAVAILABLE_CODE,
                           'Design mode is switched off in this build (BOXFOX_DESIGN_MODE=off) — '
                           'turn the switch on before using it', 409)
        try:
            if body.get('on') is True and plan_workflow.mode(known_session(sid))['on']:
                await runtime.stop(sid)
                plan_workflow.service(runtime).set_mode(runtime, sid, False, by='design')
            result = design_runtime.apply_design_mode(runtime, sid, body.get('on'),
                                                      str(body.get('by') or 'toggle'),
                                                      body.get('activeRun'))
        except ValueError as exc:
            payload = getattr(exc, 'payload', None)
            if isinstance(payload, dict) and payload.get('prompt'):
                raise ApiError(payload.get('code') or 'DESIGN_EXIT_CHOICE_REQUIRED', str(exc),
                               int(payload.get('status') or 409),
                               extra={'prompt': payload['prompt']}) from None
            raise
        return web.json_response(result)

    async def design_runs(request):
        """P1 (§5): `GET /api/agent/design/runs?sessionId=` — danh sách run của một phiên."""
        sid = request.query.get('sessionId', '').strip()
        if not sid:
            raise ApiError('DESIGN_SESSION_REQUIRED', 'sessionId is required')
        known_session(sid)
        return web.json_response({'runs': [design_runtime.design_run_payload(job)
                                           for job in runtime.store.design_jobs_for(sid)]})

    async def design_run_detail(request):
        """P1 (§5): `GET /api/agent/design/runs/{id}` — chi tiết một run cho tab Design."""
        job = design_job_known(request.match_info['design_id'])
        state = job['state'] if isinstance(job.get('state'), dict) else {}
        # `with_canvas=True`: chỉ tuyến chi tiết mang cảnh canvas (xem `design_run_payload`).
        payload = design_runtime.design_run_payload(job, with_canvas=True)
        # P4 (§5, §6): `batch`/`review` đi CẢ trong `job` (payload chuẩn) LẪN ở tầng vỏ — giao diện
        # đọc `job.batch ?? envelope.batch` (`designStore.refreshDetail`), nên hai đường đều phải có.
        return web.json_response({'job': payload, 'batch': payload['batch'],
                                  'review': payload['review'],
                                  'prompts': state.get('prompts') or [],
                                  'touchList': state.get('touchList'),
                                  'brief': state.get('brief') or {},
                                  'phaseHistory': state.get('phaseHistory') or []})

    async def design_run_update(request):
        """P1 (§5): `PATCH /api/agent/design/runs/{id}` — tạm dừng/chạy tiếp/huỷ/sửa brief."""
        job = design_job_known(request.match_info['design_id'])
        sid, body = job['session_id'], await request.json()
        action = str(body.get('action') or '')
        if action not in {'pause', 'resume', 'cancel', 'scope', 'touch-list', 'approve-batch',
                          'revert-batch'}:
            raise ApiError('DESIGN_ACTION_INVALID', action)
        if action == 'scope':
            try:
                return web.json_response(design_runtime.design_scope(runtime, sid, job, 'update',
                                                                     body.get('patch')))
            except ValueError as exc:
                raise _action_error(exc, _DESIGN_CONFLICT_STATUS) from None
        if action == 'touch-list':
            # §5: sửa từng dòng của danh sách chạm đi qua CÙNG tuyến với đề xuất — mỗi lần ghi tăng
            # `touchList.revision`, nên một thẻ cũ không thể ghi đè một thẻ mới.
            try:
                return web.json_response(design_runtime.design_touch_list_store(
                    runtime, sid, job, body.get('items') or [], body.get('forbidden'),
                    body.get('revision')))
            except ValueError as exc:
                raise _action_error(exc, _DESIGN_CONFLICT_STATUS) from None
        if action == 'approve-batch':
            # P3 (§6.5): duyệt CẢ LÔ — ghim dấu đã duyệt cho thẻ so sánh; không còn gì phải ghi thêm.
            state = dict(job['state'] or {})
            state['batchApprovedAt'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            updated = runtime.store.design_job_save(job['design_id'], sid, state,
                                                    revision=body.get('revision'))
            return web.json_response({'job': design_runtime.design_run_payload(updated)})
        if action == 'revert-batch':
            # P3 (§6.5): hoàn tác cả lô đã ghi — gọi op `design_revert` của worker qua harness.
            try:
                result = await design_runtime.design_revert(runtime, sid, job, None, 'batch')
            except ValueError as exc:
                raise _action_error(exc, _DESIGN_CONFLICT_STATUS) from None
            updated = runtime.store.design_job(job['design_id'])
            return web.json_response({'job': design_runtime.design_run_payload(updated),
                                      'result': result})
        if action == 'cancel':
            updated = design_runtime.close_run(runtime, sid, job, 'cancelled',
                                               str(body.get('reason') or 'owner-cancel'),
                                               revision=body.get('revision'))
            return web.json_response({'job': design_runtime.design_run_payload(updated)})
        if action == 'resume' and job['status'] not in {'paused', 'partial', 'needs_user'}:
            raise ApiError('DESIGN_RESUME_INVALID', 'Run is not paused or partial')
        state = dict(job['state'] or {})
        try:
            updated = runtime.store.design_job_save(job['design_id'], sid, state,
                                                    status='paused' if action == 'pause'
                                                    else 'designing',
                                                    revision=body.get('revision'))
        except ValueError as exc:
            raise _action_error(exc, _DESIGN_CONFLICT_STATUS) from None
        if action == 'pause':
            # P4 (§7.2): run vừa rơi vào `paused` ⇒ đúng MỘT `design_notice` loại `blocked`.
            updated = design_runtime.notify_run(runtime, sid, updated) or updated
        phase_moved = False
        if action == 'resume' and (job['state'] or {}).get('phase') == design_runtime.PHASE_DONE:
            # Pha `done` là pha ĐÓNG; một run vừa được hồi sức không được mang pha ấy.
            updated = design_runtime.set_phase(runtime, sid, updated, 'briefing', 'owner-resume',
                                               force=True) or updated
            phase_moved = True  # `set_phase` đã phát `design_run` cho lần nhích pha này.
        if not phase_moved:
            # §9: pause/resume đổi `status` ⇒ phải có đúng một `design_run`, nếu không giao diện
            # không biết run vừa tạm dừng hay chạy lại.
            runtime.store.emit(sid, 'design_run', design_runtime.design_job_event(updated))
        return web.json_response({'job': design_runtime.design_run_payload(updated)})

    async def design_touch_list_approve(request):
        """P1 (§5): `POST /api/agent/design/runs/{id}/touch-list/approve` — duyệt cả danh sách."""
        job = design_job_known(request.match_info['design_id'])
        body = await request.json()
        try:
            result = design_runtime.design_touch_list_approve(runtime, job['session_id'], job,
                                                              body.get('revision'),
                                                              body.get('answers'))
        except ValueError as exc:
            raise _action_error(exc, _DESIGN_CONFLICT_STATUS) from None
        live = runtime.store.design_job(job['design_id'])
        if result.get('canvasOps') or design_runtime.canvas_scene_has_nodes(live):
            # Cảnh gieo (P1) đi cùng đường với mọi lần vẽ khác: ảnh chụp bền ghi qua box, cùng chỗ
            # với `canvas_draw` của agent — không có đường vẽ tắt nào.
            # Điều kiện là "cảnh CÓ nội dung", không phải "lượt này có op": một lần ghi hỏng trước
            # đó làm lượt duyệt lại không sinh op nào, và ảnh chụp sẽ mất hẳn nếu chỉ hỏi `canvasOps`.
            await design_runtime.persist_design_canvas(runtime, job['session_id'], live)
        return web.json_response(result)

    async def design_prompt_answer(request):
        """P1 (§5): `POST /api/agent/design/prompts/{promptId}/answer` — trả lời MỘT lời hỏi.

        `start=true` phải MỞ LƯỢT TIẾP TỤC (hợp đồng §7.3). `design_runtime.design_prompt_answer` chỉ
        ghi sổ (`resume: true`); lượt do tuyến này mở, đúng khuôn `research_prompt_answer`. Thiếu nó
        thì run đứng nguyên ở pha `briefing` với `status='designing'`: không lượt nào chạy tiếp, và
        `design_continuation_step` không phủ pha ấy (nó chỉ nhận `scaffolding`/`reviewing`) — chủ nhà
        đã trả lời mà không có gì nhúc nhích (đo sống 2026-09-27, phiên `23d1ee8a…`, lời hỏi
        `dp-be5d1e19e28c`).
        """
        prompt_id = request.match_info['prompt_id']
        body = await request.json()
        job = runtime.store.design_job_by_prompt(prompt_id)
        if job is None:
            raise ApiError('DESIGN_PROMPT_UNKNOWN', prompt_id, 404)
        try:
            result = design_runtime.design_prompt_answer(runtime, job['session_id'], prompt_id,
                                                         body.get('answers'),
                                                         start=bool(body.get('start')))
        except ValueError as exc:
            raise _action_error(exc, _DESIGN_CONFLICT_STATUS) from None
        if result.get('resume'):
            # Hai điều là hợp đồng của đường này:
            # - `promptId` nằm trong `invocationId` vì một run có thể có NHIỀU lời hỏi: dùng chung mã
            #   thì lời hỏi thứ hai trả lại kết quả đã ghi của lời hỏi thứ nhất và lượt KHÔNG mở;
            # - KHÔNG bỏ qua khi phiên đang chạy: `submit` biến lời dặn thành CHỈ THỊ GIỮA LƯỢT (mặc
            #   định), còn bỏ qua hẳn thì run ở lại pha `briefing` mà không bơm nào phủ (F1).
            sid = job['session_id']
            updated = runtime.store.design_job(job['design_id'])
            if design_job_pumpable(runtime, updated, runtime.store.get(sid)):
                try:
                    await runtime.submit(
                        sid,
                        f'Continue design job {job["design_id"]} from design_status after the owner '
                        'answered the prompt. Apply the confirmed answers, keep the touch list '
                        'authoritative, write only approved paths, and stop with a qualified partial '
                        'result if a path is blocked.',
                        invocation_id=f'design-resume-{job["design_id"]}-{prompt_id}')
                except ValueError as exc:
                    # Chỉ tới đây khi phiên ĐANG CHẠY mà chủ nhà đã tắt chỉ thị giữa lượt
                    # (`BOXFOX_STEER=off`). Câu trả lời đã ghi sổ: ghi nhật ký hệ thống rồi trả kết
                    # quả bình thường — run có thể đứng ở `briefing` tới lượt sau, và điều đó phải
                    # đọc được thay vì biến thành lỗi cho giao diện.
                    if 'SESSION_BUSY' not in str(exc):
                        raise
                    system_log.write('design.prompt.resume_busy', level='warn',
                                     code='DESIGN_RESUME_BUSY',
                                     message='phiên đang chạy và chế độ chỉ thị giữa lượt đang tắt — '
                                             'câu trả lời đã ghi sổ, lượt tiếp tục chưa mở',
                                     session_id=sid, designId=job['design_id'], promptId=prompt_id)
        return web.json_response(result)

    async def session_canvas(request):
        """P2 (§6.4, hợp đồng §5): `POST /api/agent/sessions/{sid}/canvas` — giao thức boxfox.canvas.v1.

        `type:'scene'` lưu cảnh chủ nhà vào run (và ảnh chụp `.design/<slug>/canvas.v1.json`) rồi phát
        một `design_canvas {actor:'user'}` — KHÔNG mở lượt. `type:'directive'` xếp chỉ thị cho lượt
        Design Lead kế tiếp và trả `{accepted:true}`. Gói sai giao thức ⇒ `DESIGN_CANVAS_PROTOCOL_INVALID`.
        """
        sid = request.match_info['sid']
        session = known_session(sid)
        from ..agent_core import runtime as runtime_module
        mode = runtime_module.design_mode(session)
        if not mode['on']:
            raise ApiError('DESIGN_MODE_REQUIRED', 'Design mode is off for this session', 409)
        run_id = str(mode.get('activeRunId') or '')
        job = runtime.store.design_job(run_id) if run_id else None
        if job is None or job['session_id'] != sid:
            raise ApiError('DESIGN_JOB_UNKNOWN', run_id or 'no active run', 404)
        body = await request.json()
        if str(body.get('protocol') or '') != design_runtime.CANVAS_PROTOCOL:
            raise ApiError('DESIGN_CANVAS_PROTOCOL_INVALID', 'body needs protocol boxfox.canvas.v1')
        kind = str(body.get('type') or '')
        if kind == 'scene':
            scene = body.get('scene')
            if not isinstance(scene, dict):
                raise ApiError('DESIGN_CANVAS_PROTOCOL_INVALID', 'body needs a `scene` object')
            updated = design_runtime.canvas_store_scene(runtime, sid, job, scene)
            await design_runtime.persist_design_canvas(
                runtime, sid, runtime.store.design_job(job['design_id']))
            state = updated['state'] if isinstance(updated.get('state'), dict) else {}
            seq = int(state.get('canvasSeq') or 0)
            return web.json_response({'ok': True, 'seq': seq, 'sceneVersion': seq})
        if kind == 'directive':
            instruction = str(body.get('instruction') or '').strip()
            target = str(body.get('targetNodeId') or '').strip()
            # `target` rỗng là HỢP LỆ: nghĩa "cả canvas" — dùng cho canvas đang trống, khi chủ nhà
            # chưa có node nào để bấm vào. Chỉ thiếu CHỮ mới là gói sai.
            if not instruction:
                raise ApiError('DESIGN_CANVAS_PROTOCOL_INVALID',
                               'a directive needs instruction (targetNodeId may be empty)')
            design_runtime.canvas_queue_directive(runtime, sid, job, target,
                                                  body.get('targetNodeTitle'), instruction)
            return web.json_response({'accepted': True})
        raise ApiError('DESIGN_CANVAS_PROTOCOL_INVALID', 'type must be scene or directive')

    def known_session(sid):
        """The session record, or an explicit 404 the UI can act on."""
        try:
            return runtime.store.get(sid)
        except KeyError:
            raise missing_session(sid) from None

    async def session(request):
        sid = request.match_info['sid']
        value = known_session(sid)
        # Do not resend large multimodal transcripts on every polling request.
        # N10 (đợt 20): kèm `sessionMetrics` — trước đây không có cách nào biết một phiên đã dài
        # bao nhiêu, đã nén mấy lần, hay `deadlineSeconds` đã bị hạ trần lúc tạo, mà không tải cả
        # transcript. Bốn khoá này đọc từ chính hàng đã lưu nên rẻ.
        journal_tail = runtime.journal_records(sid, limit=50)
        # W7.1: a session can hold far more than one 500-event page. `hasMore`/`nextAfter` let a
        # client walk the whole log; older clients that ignore them keep today's behaviour.
        page = runtime.store.events_page(sid, int(request.query.get('after', '0')))
        return web.json_response({k: v for k, v in value.items() if k != 'messages'} |
                                 {'events': page['events'], 'hasMore': page['hasMore'],
                                  'nextAfter': page['nextAfter'],
                                  'sessionMetrics': runtime.session_metrics(sid),
                                  **durable_session_view(sid),
                                  # A9 (đợt 20): khối `journal` cộng thêm — chỗ đọc cũ không phải biết
                                  # tới nó, còn UI sau này có sẵn `records`/`lastSeq`/`degraded`.
                                  'journal': {'records': journal_tail['records'],
                                              'lastSeq': journal_tail['nextSeq'],
                                              'degraded': journal_tail['degraded']}})

    async def turn(request):
        body = await request.json()
        sid = request.match_info['sid']
        # Check before submitting: `runtime.submit` would raise the same KeyError and the user
        # would get `INTERNAL_ERROR` for what is really a stale session id.
        known_session(sid)
        result = await runtime.submit(sid, body.get('prompt'), body.get('image'), body.get('route'),
                                      body.get('invocationId'), images=body.get('images'),
                                      attachments=body.get('attachments'))
        return web.json_response(result, status=202 if result['status'] in ('running', 'steered') else 200)

    async def stop(request):
        sid = request.match_info['sid']
        known_session(sid)
        await runtime.stop(sid)
        return web.json_response({'status': known_session(sid)['status']})

    async def decision(request):
        """Answer a pending ask_user / request_approval (contract §2: 200/400/404/409)."""
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            return web.json_response({'error': 'DECISION_INVALID: a JSON body with decisionId and choice is required'}, status=400)
        sid = request.match_info['sid']
        try:
            result = runtime.resolve_decision(sid, body.get('decisionId'), body.get('choice'), body.get('note'),
                                              body.get('answers'), invocation_id=body.get('invocationId'),
                                              expected_revision=body.get('expectedRevision'))
        except DecisionError as exc:
            return web.json_response({'error': str(exc)}, status=exc.status)
        except Exception as exc:
            if getattr(exc, 'code', None):
                return surface_error(exc)
            raise
        # A7 (đợt 20): quyết định của người dùng được ghim vào nhật ký phiên — bản ghi `D:` giữ cả
        # `choice`, nên đọc lại biết đã chốt phương án nào (phát hiện đợt 4: `alternative` từng bị
        # ghi thành `approved` trơ). Ghi nhật ký hỏng không bao giờ làm hỏng câu trả lời cho UI.
        await runtime.pin_decision(sid, result)
        return web.json_response(result)

    async def session_journal(request):
        """`GET /api/agent/sessions/{sid}/journal?after=&kind=&limit=` — nhật ký bền của một phiên."""
        sid = request.match_info['sid']
        known_session(sid)
        try:
            after = int(request.query['after']) if 'after' in request.query else None
            limit = int(request.query.get('limit', '50'))
        except ValueError:
            return web.json_response({'error': 'JOURNAL_BAD_QUERY: after/limit phải là số'}, status=400)
        kind = request.query.get('kind') or None
        return web.json_response(runtime.journal_records(sid, after=after, kind=kind, limit=limit))

    async def journal_tasks(request):
        """`GET /api/agent/journal/tasks?status=&limit=` — task qua mọi phiên, đọc từ bảng nhật ký."""
        try:
            limit = int(request.query.get('limit', '50'))
        except ValueError:
            return web.json_response({'error': 'JOURNAL_BAD_QUERY: limit phải là số'}, status=400)
        return web.json_response(runtime.journal_tasks(status=request.query.get('status') or None, limit=limit))

    # --------------------------------------------------- bề mặt bền: history / longtask
    #
    # Đây là đường DUY NHẤT để UI chạm vào history, ngân sách tác vụ dài và xoá có mang theo.
    # Không route nào nhận `projectId`, đường dẫn riêng hay id phiên khác từ client: phạm vi lấy
    # từ chính phiên gọi (`callerSessionId`), còn thiếu nguồn canonical thì từ chối thay vì đoán.

    def surface_error(exc):
        raw = str(exc)
        code = getattr(exc, 'code', None) or (raw.split(':', 1)[0].strip()
                                             if raw.isupper() or ':' in raw else 'DURABLE_ERROR')
        status = getattr(exc, 'status', None)
        if status is None:
            if code in ('HISTORY_SCOPE_DENIED', 'CAPSULE_EVIDENCE_SCOPE_DENIED'):
                status = 403
            elif code.endswith('_NOT_FOUND'):
                status = 404
            elif code.endswith(('_INVALID', '_REQUIRED', '_UNSUPPORTED', '_UNKNOWN')):
                status = 400
            else:
                status = 409
        message = raw if raw.startswith(code) else f'{code}: {raw}'
        return web.json_response({'error': message, 'code': code}, status=status)

    def surface():
        from ..agent_core import history_surface
        return history_surface

    def query_int(request, name, default, maximum=None):
        raw = request.query.get(name)
        if raw in (None, ''):
            return default
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ValueError('HISTORY_QUERY_INVALID')
        if value < 1:
            raise ValueError('HISTORY_QUERY_INVALID')
        return min(value, maximum) if maximum else value

    def caller_session(request):
        sid = request.query.get('callerSessionId') or request.query.get('sessionId')
        if not sid:
            raise ValueError('HISTORY_CALLER_REQUIRED')
        known_session(sid)
        return sid

    def durable_session_view(sid):
        """Ba khoá cho UI: `longtask` (null = có tính năng, chưa bật), `goalRevision`, `contractRef`.

        Không có nguồn canonical thì trả `None` — UI sẽ giữ nút xác nhận ở trạng thái tắt thay vì
        bật một tác vụ dài với số hiệu phiên bản bịa.
        """
        try:
            from ..agent_core import history_surface
            contract = history_surface.service(runtime).contract(sid)
            return {'longtask': runtime.longtask_state(sid), 'goalRevision': contract['currentRevision'],
                    'contractRef': history_surface.contract_hash(contract)}
        except Exception:
            return {'longtask': None, 'goalRevision': None, 'contractRef': None}

    async def history_sessions(request):
        try:
            sid = caller_session(request)
            result = surface().service(runtime).list_sessions(
                sid, scope=request.query.get('scope', 'self'), session_id=request.query.get('targetSessionId'),
                agent_id=request.query.get('agentId'), cursor=request.query.get('cursor'),
                limit=query_int(request, 'limit', 20, 50))
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def history_search(request):
        try:
            sid = caller_session(request)
            service = surface().service(runtime)
            scope, target = surface().scope_target(runtime, sid, request.query.get('scope', 'self'))
            result = service.query_history(
                sid, query=request.query.get('query', ''), scope=scope, session_id=target,
                # `getall` ném KeyError khi thiếu khoá, nên hỏi `in` trước: thiếu `kind` là hợp lệ.
                agent_id=request.query.get('agentId'),
                kinds=request.query.getall('kind') if 'kind' in request.query else None,
                cursor=request.query.get('cursor'), limit=query_int(request, 'limit', 10, 50),
                mode=request.query.get('mode', 'search'))
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def history_record(request):
        try:
            sid = caller_session(request)
            result = surface().service(runtime).read_reference(
                sid, request.match_info['recordId'], offset=query_int(request, 'offset', 0),
                limit=query_int(request, 'maxChars', 16000, 16000))
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def history_storage(request):
        try:
            sid = request.query.get('callerSessionId') or request.query.get('sessionId')
            if sid:
                known_session(sid)
            result = surface().storage_snapshot(runtime, sid)
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def session_deletion_preview(request):
        sid = request.match_info['sid']
        try:
            known_session(sid)
            body = await request.json() if request.can_read_body else {}
            if not isinstance(body, dict):
                raise ValueError('DELETE_MODE_UNSUPPORTED')
            result = surface().deletion_preview(runtime, sid, body)
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def session_deletion_confirm(request):
        sid = request.match_info['sid']
        try:
            known_session(sid)
            body = await request.json() if request.can_read_body else {}
            if not isinstance(body, dict):
                raise ValueError('DELETE_REQUIRES_CARRY_FORWARD')
            for target in surface().tree_ids(runtime, sid):
                if target in runtime.tasks:
                    try:
                        await runtime.stop(target)
                    except Exception:
                        pass
            result = surface().deletion_confirm(runtime, sid, body)
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def session_decisions(request):
        sid = request.match_info['sid']
        try:
            known_session(sid)
            result = runtime.pending_decisions(sid, request.query.get('state', 'pending'),
                                               request.query.get('after') or None,
                                               query_int(request, 'limit', 20, 100))
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def session_longtask(request):
        sid = request.match_info['sid']
        try:
            known_session(sid)
            body = await request.json() if request.can_read_body else {}
            if not isinstance(body, dict):
                raise ValueError('LONGTASK_INVALID')
            result = runtime.configure_longtask(sid, body)
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def session_longtask_actions(request):
        sid = request.match_info['sid']
        try:
            known_session(sid)
            body = await request.json() if request.can_read_body else {}
            if not isinstance(body, dict):
                raise ValueError('LONGTASK_INVALID')
            result = await runtime.longtask_action(sid, body)
        except Exception as exc:
            return surface_error(exc)
        return web.json_response(result)

    async def session_tasks(request):
        """`GET /sessions/{sid}/tasks` — task của cả cây, bản tóm tắt, phân trang theo `taskKey`."""
        sid = request.match_info['sid']
        try:
            known_session(sid)
            limit = query_int(request, 'limit', 20, 50)
            state = request.query.get('state') or 'active'
            after = request.query.get('after') or None
            if 'harness_tasks' not in {row[0] for row in runtime.store.db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'")}:
                return web.json_response({'tasks': [], 'hasMore': False, 'nextAfter': None})
            ids = surface().tree_ids(runtime, sid)
            marks = ','.join('?' for _ in ids)
            clauses, args = [f'a.session_id IN ({marks})'], list(ids)
            if state == 'active':
                clauses.append("t.state NOT IN ('completed','cancelled','failed')")
            elif state != 'all':
                clauses.append('t.state=?')
                args.append(state)
            rows = runtime.store.db.execute(
                'SELECT t.task_key,t.run_id,t.owner_id,t.task_alias,t.revision,t.state,t.acceptance_state,'
                't.control_state,t.updated_at,MAX(a.session_id) session_id,COUNT(a.attempt_id) attempts '
                'FROM harness_tasks t JOIN harness_task_attempts a ON a.task_key=t.task_key WHERE '
                + ' AND '.join(clauses) + ' AND (? IS NULL OR t.task_key>?) GROUP BY t.task_key '
                'ORDER BY t.updated_at DESC LIMIT ?', (*args, after, after, limit + 1)).fetchall()
            items = [{'taskKey': r['task_key'], 'runId': r['run_id'], 'ownerId': r['owner_id'],
                      'alias': r['task_alias'], 'revision': r['revision'], 'state': r['state'],
                      'acceptanceState': r['acceptance_state'], 'controlState': r['control_state'],
                      'sessionId': r['session_id'], 'attempts': r['attempts'],
                      'updatedAt': r['updated_at']} for r in rows[:limit]]
        except Exception as exc:
            return surface_error(exc)
        return web.json_response({'tasks': items, 'hasMore': len(rows) > limit,
                                  'nextAfter': items[-1]['taskKey'] if items and len(rows) > limit else None})

    async def delete_session(request):
        """Xoá phiên: bản cũ nhận 409 kèm bản xem trước; chỉ xoá khi chủ xác nhận có capsule."""
        sid = request.match_info['sid']
        try:
            known_session(sid)
            body = await request.json() if request.can_read_body else {}
        except Exception:
            body = {}
        if isinstance(body, dict) and body.get('confirm') is True and body.get('operationId'):
            return await session_deletion_confirm(request)
        if sid in runtime.tasks:
            try:
                await runtime.stop(sid)
            except Exception:
                pass
        try:
            preview = surface().deletion_preview(runtime, sid, {'mode': 'history_only'})
        except Exception as exc:
            return surface_error(exc)
        return web.json_response({'error': 'DELETE_REQUIRES_CARRY_FORWARD: xoá phiên cần xác nhận '
                                          'với capsule mang theo', 'code': 'DELETE_REQUIRES_CARRY_FORWARD',
                                  'preview': preview}, status=409)

    # ------------------------------------------------------------------ plan duyệt (vòng 20)
    #
    # Hai route này là ĐƯỜNG DUY NHẤT để tab Plan ghi/đọc trạng thái duyệt. Nguồn chân lý là bảng
    # SQLite của harness (`plan_reviews`, `plan_evaluations`), KHÔNG phải `.reviews/<identity>.json`
    # trong workspace: file đó agent ghi được nên nó chỉ là bản hiển thị, và không bao giờ là căn cứ
    # để cho hay không cho ghi một plan mới (§4.1 của plan vòng 20).
    #
    # Nối từ phía runtime (workstream A/C), giữ đúng chữ ký này:
    #
    #   * `request_approval` mang thêm hai tham số tuỳ chọn `planIdentity` (string) và `planVersion`
    #     (int ≥ 1) trong `args`; `runtime.decision()` chép chúng vào `record` đang chờ
    #     (`self.pending[decision_id]`) với **đúng hai tên khoá** `planIdentity`/`planVersion` —
    #     `plan_registry.pending_submissions()` đọc chính hai khoá đó để trả trạng thái `submitted`.
    #   * `settle()` gọi một lần, ngay trước khi phát `decision_resolved`:
    #         self.store.record_plan_review(identity=record.get('planIdentity'),
    #                                       version=record.get('planVersion'),
    #                                       decision='approved' if status == 'approved' else 'changes_requested',
    #                                       note=(note or ''), source='approval',
    #                                       session_id=record['sessionId'])
    #     Chỉ gọi khi cả hai khoá đều có (một `request_approval` cũ không mang chúng thì không ghi gì).
    #     "Chưa đồng ý" ở đây chính là điều kiện của luật v2 (R1) nên `rejected`/`expired`/`cancelled`
    #     đều thành `changes_requested`.

    def plan_identity_arg(value):
        """Identity hợp lệ (cùng grammar với khối header) hoặc `ApiError` 400."""
        text = str(value or '').strip().strip('/')
        if not text or not _PLAN_IDENTITY_RE.match(text):
            raise ApiError('PLAN_IDENTITY_INVALID',
                           'identity phải là chữ thường, các từ cách nhau một dấu gạch, có thể kèm '
                           'thư mục (ví dụ "clinical-patient-record-lookup-research")', 400)
        return text

    def plan_session_arg(value):
        """Mã phiên đi kèm lượt đọc/ghi plan; `None` khi chỗ gọi cũ không gửi.

        Chỉ host mode cần: chỉ mục `.plans` nằm trong folder của CHÍNH phiên đó. Docker bỏ qua.
        """
        text = str(value or '').strip()
        return text or None

    async def plan_index_or_none(session=None):
        """Chỉ mục box, hoặc `None` khi không đọc được (đã ghi nhật ký `PLAN_INDEX_UNAVAILABLE`).

        Không bao giờ raise: mất chỉ mục chỉ làm mất phần *số đo* (nhóm nào có những bản nào), còn
        quyết định của người dùng vẫn phải ghi được.
        """
        try:
            return await plan_registry.read_plan_index(runtime.executor, session=session)
        except Exception:
            return None

    def plan_wake_prompt(identity, version, relative_path, decision, note):
        """Prompt của lượt mở từ tab Plan — tiếng Việt, có tiền tố `[Tab Plan]` để transcript tự
        nói nguồn gốc của lượt (chủ nhà bấm ở tab, không phải gõ trong chat)."""
        where = relative_path or f'{identity} v{version}'
        if decision == 'changes_requested':
            lines = [f'[Tab Plan] chủ nhà yêu cầu sửa kế hoạch {identity}@v{version} ({where}).',
                     'Sửa ĐÚNG các điểm đã nêu, giữ nguyên phần đã đúng, rồi ghi bản kế tiếp bằng '
                     '`write_plan` (bản mới phải khai nó sửa bản nào).',
                     'Sau khi ghi: phản biện lại (`delegate_task role=\'plan-review\'` rồi `plan_verify`).',
                     f'Tối đa {PLAN_VERIFY_REVISE_MAX} vòng sửa trong lượt này; chạm trần thì báo chủ '
                     'nhà trung thực kèm danh sách lỗi chưa sửa.',
                     'KHÔNG mở một kế hoạch mới cho cùng chủ đề.']
        else:
            lines = [f'[Tab Plan] chủ nhà đã duyệt kế hoạch {identity}@v{version} ({where}).',
                     'Bắt đầu thi công theo đúng các milestone trong bản ĐÃ DUYỆT; bám tiêu chí '
                     'nghiệm thu của bản đó.']
        if (note or '').strip():
            lines.append(f'Điều kiện kèm theo của chủ nhà: {note.strip()}')
        else:
            lines.append('Không kèm ghi chú.')
        return '\n'.join(lines)

    async def plan_wake(owner, identity, version, relative_path, decision, note, prompt=None):
        """Mở MỘT lượt thật trong phiên gốc cho cú bấm ở tab Plan; không bao giờ im lặng.

        `invocationId` suy từ chính nội dung quyết định nên cú bấm trùng (double-click, hoặc
        người dùng bấm lại sau khi mạng chớp) trả lại kết quả đã lưu thay vì mở lượt thứ hai.
        Mọi kết cục không-mở-được đều trả về một `wake` có mã và câu giải thích: quyết định của
        chủ nhà đã vào sổ từ trước đó, nên đánh thức hỏng không được làm mất nó — nhưng cũng
        không được giả vờ là đã mở lượt.
        """
        invocation_id = 'plan-wake-' + hashlib.sha1(
            f'{identity}@{version}:{decision}:{note}'.encode('utf-8')).hexdigest()[:16]
        if prompt is None:
            prompt = plan_wake_prompt(identity, version, relative_path, decision, note)
        try:
            await runtime.submit(owner, prompt, invocation_id=invocation_id, allow_steer=False)
        except ValueError as exc:
            message = str(exc)
            if 'SESSION_BUSY' in message:
                system_log.write('plan.review.wake_busy', level='warn', code='PLAN_WAKE_BUSY',
                                 message=f'phiên {owner} đang chạy một lượt — quyết định đã ghi sổ, '
                                         f'lượt mới chưa mở', session_id=owner, identity=identity,
                                 version=version, decision=decision)
                return {'resumed': False, 'wake': {
                    'state': 'busy', 'code': 'PLAN_WAKE_BUSY',
                    'message': f'phiên {owner} đang chạy một lượt — quyết định đã ghi sổ, lượt mới '
                               f'chưa mở'}}
            if 'INVOCATION_CONFLICT' in message:
                system_log.write('plan.review.wake_duplicate', level='info', code='PLAN_WAKE_DUPLICATE',
                                 message='cú bấm trùng với một lượt đã mở trước đó',
                                 session_id=owner, identity=identity, version=version, decision=decision)
                return {'resumed': True, 'wake': {'state': 'duplicate', 'code': 'PLAN_WAKE_DUPLICATE',
                                                 'sessionId': owner}}
            system_log.write('plan.review.wake_failed', level='error', code=PLAN_WAKE_FAILED_CODE,
                             message=message, session_id=owner, identity=identity, version=version,
                             decision=decision)
            return {'resumed': False, 'wake': {'state': 'failed', 'code': PLAN_WAKE_FAILED_CODE,
                                               'message': message}}
        except Exception as exc:  # pragma: no cover - mọi lỗi khác của `submit`
            message = f'{type(exc).__name__}: {exc}'
            system_log.write('plan.review.wake_failed', level='error', code=PLAN_WAKE_FAILED_CODE,
                             message=message, session_id=owner, identity=identity, version=version,
                             decision=decision)
            return {'resumed': False, 'wake': {'state': 'failed', 'code': PLAN_WAKE_FAILED_CODE,
                                               'message': message}}
        system_log.write('plan.review.wake', level='info',
                         message=f'đã mở lượt mới trong phiên {owner} từ tab Plan',
                         session_id=owner, identity=identity, version=version, decision=decision,
                         invocationId=invocation_id)
        try:
            runtime.store.set_plan_review_resumed(identity, version)
        except Exception:  # pragma: no cover - hàng sổ đã ghi; cột `resumed` chỉ là dấu vết thêm
            pass
        turn_count = (runtime.store.get(owner) or {}).get('turn_count') or 0
        return {'resumed': True, 'turnId': f'{owner}#{turn_count}',
                'wake': {'state': 'opened', 'sessionId': owner}}

    def plan_wake_missing(identity, version, event, **log_fields):
        """Kết cục `missing` cho cả hai đường đánh thức: một câu, hai route, không lệch chữ.

        Quyết định của chủ nhà đã vào sổ từ trước đó — đánh thức hỏng không được làm mất nó, nhưng
        cũng không được giả vờ là đã mở lượt.
        """
        message = (f'harness chưa biết phiên nào sở hữu kế hoạch {identity} — hãy mở phiên và '
                   f'yêu cầu trực tiếp')
        system_log.write(event, level='warn', code=PLAN_WAKE_NO_OWNER_CODE,
                         message=f'harness chưa biết phiên nào sở hữu kế hoạch {identity}',
                         identity=identity, version=version, **log_fields)
        return {'resumed': False, 'wake': {'state': 'missing', 'code': PLAN_WAKE_NO_OWNER_CODE,
                                          'message': message}}

    async def plan_review(request):
        """`POST /api/agent/plans/review` — người dùng duyệt/yêu cầu sửa một bản plan (§4.1).

        Ghi vào sổ duyệt TRƯỚC, rồi mới chuyển tiếp sang box để badge của tab Plan chạy như cũ.
        Chuyển tiếp hỏng thì quyết định **vẫn** đã được ghi (`forwarded: false` + nhật ký
        `plan_review_forward_failed`): một cú bấm của người dùng không được biến mất vì box đang tắt.
        """
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            raise ApiError('PLAN_REVIEW_INVALID', 'a JSON body with identity, version, decision is required', 400)
        identity = plan_identity_arg(body.get('identity'))
        version = body.get('version')
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ApiError('PLAN_REVIEW_INVALID', 'version phải là số nguyên dương (bản plan bị duyệt)', 400)
        decision = str(body.get('decision') or '')
        if decision not in SessionStore.PLAN_REVIEW_DECISIONS:
            raise ApiError('PLAN_REVIEW_INVALID',
                           'decision phải là "approved" hoặc "changes_requested"', 400)
        note = body.get('note')
        if note is not None and not isinstance(note, str):
            raise ApiError('PLAN_REVIEW_INVALID', 'note phải là chuỗi', 400)
        note = (note or '').strip()
        if len(note) > _PLAN_NOTE_MAX_CHARS:
            raise ApiError('PLAN_REVIEW_INVALID',
                           f'note dài quá {_PLAN_NOTE_MAX_CHARS} ký tự', 400)

        # Chốt số đo tại thời điểm duyệt, nếu đọc được: về sau box báo số khác thì bản duyệt này
        # đã cũ và không còn tính là "đã đồng ý" (§4.2). Không đọc được thì để `None` — thà không
        # có số đo còn hơn bịa một con số để rồi lặng lẽ coi là còn hiệu lực.
        session_arg = plan_session_arg(body.get('sessionId'))
        index = await plan_index_or_none(session_arg)
        entry = None
        relative_path = None
        if index is not None:
            group = index.group(identity)
            if group is not None:
                entry = next((item for item in group.versions if item.version == version), None)
                if entry is not None:
                    relative_path = entry.relative_path
        # Vòng 25 (D-34) — CỔNG PHẢN BIỆN, chặn TRƯỚC khi ghi sổ và trước khi chuyển tiếp box: một
        # cú Duyệt cho bản chưa có phán quyết `ok` không được tạo ra hàng duyệt nào (nếu không, tab
        # Plan sẽ nói "đã duyệt" cho một bản chưa ai phản biện). Cùng câu từ chối với đường chat.
        approval_warning = None
        if decision == 'approved':
            semantic_block = plan_workflow.service(runtime).approval_blocked(identity, version)
            if semantic_block:
                raise ApiError('PLAN_NOT_READY', semantic_block, 409)
            blocked = runtime.plan_approval_blocked(identity, version)
            if blocked:
                mode = runtime.plan_verify_mode()[0]
                if mode == 'enforce':
                    return web.json_response({'blocked': True, 'code': PLAN_APPROVAL_UNVERIFIED_CODE,
                                              'reason': blocked,
                                              'remedy': f"gọi plan-review rồi plan_verify với verdict=ok "
                                                        f"cho đúng bản v{version}"},
                                             status=409)
                if mode == 'warn':
                    approval_warning = blocked
                    system_log.write('plan.approval.unverified', level='warn',
                                     code=PLAN_APPROVAL_UNVERIFIED_CODE,
                                     message=f'{blocked} (đã ghi sổ vì cổng đang ở chế độ warn)',
                                     identity=identity, version=version, mode=mode)
        # Vòng 25 (D-36): hàng sổ ghi luôn PHIÊN SỞ HỮU nếu harness đã biết — trước đây cột này
        # toàn `NULL`, nên quyết định không nói được nó thuộc về phiên nào (BUG-2).
        owned = runtime.plan_ownership_view(identity)['sessionId']
        try:
            workflow = plan_workflow.service(runtime)
            planning_run = workflow.for_document(identity, version)
            if planning_run:
                workflow_result = workflow.action(planning_run['runId'], body | {
                    'action': 'approve' if decision == 'approved' else 'request_changes'})
                row = runtime.store.plan_review(identity, version)
            else:
                row = runtime.store.record_plan_review(
                    identity, version, decision, note=note, source='plan-tab', session_id=owned,
                    content_size=None if entry is None else entry.size_bytes,
                    content_modified_at=None if entry is None else entry.modified_at)
        except ValueError as exc:
            if planning_run:
                raise
            raise ApiError('PLAN_REVIEW_INVALID', str(exc), 400) from None

        forwarded = True
        try:
            await runtime.executor.request('/__box/plans/review',
                                           {'identity': identity, 'version': version,
                                            'decision': decision, 'note': note},
                                           session=session_arg or owned)
        except Exception as exc:
            forwarded = False
            system_log.write('plan.review.forward_failed', level='warn', code='PLAN_REVIEW_FORWARD_FAILED',
                             message='Đã ghi quyết định duyệt vào sổ của harness nhưng chưa chuyển được '
                                     'sang box; badge trong .reviews sẽ cập nhật ở lần duyệt sau.',
                             reason=f'{type(exc).__name__}: {exc}')
        # M6 (D-35/Q3/Q4) — quyết định đã vào sổ, giờ mở MỘT LƯỢT THẬT trong phiên gốc. Cú bấm cũ
        # chỉ ghi sổ rồi im lặng (đo vòng 25: 3/3 lần bấm, 55-60 s không có gì xảy ra).
        if decision == 'approved':
            wake = {'resumed': False, 'wake': {'state': 'accepted',
                    'message': f'Đã duyệt v{version}. Chọn Triển khai để bắt đầu thi công.'}}
        elif planning_run:
            await plan_workflow.pump(runtime)
            wake = {'resumed': workflow_result['queued'], 'wake': {'state': 'opened', 'sessionId': planning_run['sessionId']}}
        elif not owned:
            wake = plan_wake_missing(identity, version, 'plan.review.wake_failed', decision=decision)
        else:
            wake = await plan_wake(owned, identity, version, relative_path, decision, note)
        payload = {'identity': identity, 'version': version, 'decision': decision, 'note': note,
                   'forwarded': forwarded, 'recorded': True,
                   'review': _plan_review_json(row)['review'],
                   'resumed': bool(wake.get('resumed'))}
        if wake.get('turnId'):
            payload['turnId'] = wake['turnId']
        payload['wake'] = wake['wake']
        if approval_warning:
            payload['approvalWarning'] = approval_warning
        return web.json_response(payload)

    async def plan_status(request):
        """`GET /api/agent/plans/status?identity=&version=` — trạng thái duyệt cho tab Plan (§4.2).

        Không có `version` → trả trạng thái của bản **mới nhất** trong nhóm. Có `version` → trả đúng
        bản đó (duyệt một bản cũ ghi vào sổ đúng bản cũ và không áp cho bản mới hơn).
        Identity không có trong chỉ mục → 200 với `{state: "none"}`. Chỉ mục không đọc được →
        `{state: "unknown", indexAvailable: false}`: đó là sự thật, không phải một lần đoán.
        """
        identity = plan_identity_arg(request.query.get('identity'))
        wanted = request.query.get('version')
        version = None
        if wanted not in (None, ''):
            if not str(wanted).isdigit() or int(wanted) < 1:
                raise ApiError('PLAN_STATUS_INVALID', 'version phải là số nguyên dương', 400)
            version = int(wanted)

        # `sessionId` (tuỳ chọn) để host mode đọc đúng `.plans` của phiên đang mở tab.
        index = await plan_index_or_none(plan_session_arg(request.query.get('sessionId')))
        group = index.group(identity) if index is not None else None
        reviews = runtime.store.plan_reviews_for(identity)
        submitted = plan_registry.pending_submissions(getattr(runtime, 'pending', {}).values(), identity)
        if group is not None and version is None:
            state = plan_registry.group_state(group.versions, reviews=reviews, submitted=submitted)
        else:
            entries = () if group is None else tuple(item for item in group.versions
                                                     if version is None or item.version == version)
            state = plan_registry.group_state(entries, reviews=reviews, submitted=submitted,
                                             index_available=index is not None)
        payload = state.to_payload() | {'identity': identity}
        evaluation = runtime.store.plan_evaluation(identity, state.state_version or 0)
        if state.state_version is None and version is not None:
            # Bản được hỏi không có trên box (đã bị xoá, hoặc gõ sai số): không nhóm nào để đo, nên
            # `stateVersion` phải nói đúng bản đang được hỏi thay vì im lặng trả `null` bên cạnh
            # hàng sổ duyệt của chính bản đó.
            payload['stateVersion'] = version
            evaluation = runtime.store.plan_evaluation(identity, version)
        payload['version'] = version if version is not None else state.state_version
        payload['researchDependencies'] = runtime.store.plan_research_dependencies(
            identity, payload['version'] or 0)
        payload['researchStale'] = any(item['stale'] for item in payload['researchDependencies'])
        # Vòng 25 (D-33/D-36): HAI khoá này LUÔN có mặt — giao diện phân biệt được "harness cũ,
        # thiếu trường" với "harness mới, chưa có phê biện" (`state: 'none'`). Bản được hỏi dùng
        # ĐÚNG số đã phân giải ở trên, không đọc lại chỉ mục lần thứ hai.
        asked = payload['version']
        payload['verification'] = runtime.plan_verification_view(identity, asked or 0)
        payload['workflow'] = plan_workflow.service(runtime).for_document(identity, asked or 0)
        semantic_block = plan_workflow.service(runtime).approval_blocked(identity, asked or 0)
        payload['semanticBlocked'] = semantic_block
        if payload['workflow'] and semantic_block and payload.get('state') == 'approved':
            payload['reviewStale'] = True
        payload['ownership'] = runtime.plan_ownership_view(identity)
        # Vòng 25 (hậu kiểm soát mã, F1/F5): công tắc của cổng duyệt đi KÈM trạng thái để tab Plan
        # đọc được cùng một sự thật với harness. Không có khoá này, giao diện chỉ biết "bản này
        # chưa `ok`" rồi tự đoán là harness sẽ từ chối — mạnh hơn harness ở chế độ `warn`/`off`
        # (chặn một cú duyệt mà harness cho qua), yếu hơn ở chế độ `enforce` + `revise` (mời một cú
        # bấm mà harness chắc chắn trả 409). `*Unknown` là giá trị env lạ đã bị hạ về mặc định:
        # hạ cấp cổng trong im lặng là thứ kế hoạch cấm, nên nó đi ra tới mặt người dùng.
        verify_mode, verify_unknown = runtime.plan_verify_mode()
        sources_mode, sources_unknown = runtime.plan_sources_mode()
        payload['gate'] = {'verifyMode': verify_mode, 'verifyUnknown': verify_unknown,
                           'sourcesMode': sources_mode, 'sourcesUnknown': sources_unknown}
        payload['evaluation'] = None if evaluation is None else {
            'identity': evaluation.get('identity'), 'version': evaluation.get('version'),
            'total': evaluation.get('total'), 'verdict': evaluation.get('verdict'),
            'evaluatedAt': evaluation.get('evaluated_at'), 'payload': evaluation.get('payload'),
        }
        return web.json_response(payload)


    async def plan_verify_route(request):
        """`POST /api/agent/plans/verify` — CHẠY PHIÊN PHẢN BIỆN cho một bản đã ghi (D-33).

        Đường này **không ghi gì**: hàng `plan_verifications` chỉ ra đời từ tool `plan_verify` của
        orchestrator, sau khi cổng provenance kiểm bằng chứng thật. Ở đây chỉ mở một lượt trong
        phiên sở hữu và yêu cầu nó chạy phê bình — tab Plan cần nút này vì một bản kế hoạch ghi xong
        rồi lượt kết thúc thì không còn ai phản biện nó nữa.
        """
        try:
            body = await request.json()
        except Exception:
            body = None
        if not isinstance(body, dict):
            raise ApiError('PLAN_VERIFY_INVALID', 'a JSON body with identity and version is required', 400)
        identity = plan_identity_arg(body.get('identity'))
        version = body.get('version')
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise ApiError('PLAN_VERIFY_INVALID', 'version phải là số nguyên dương (bản plan cần phản biện)', 400)
        owned = runtime.plan_ownership_view(identity)['sessionId']
        if not owned:
            return web.json_response({'recorded': False,
                                      **plan_wake_missing(identity, version,
                                                          'plan.verify.wake_failed')})
        prompt = '\n'.join([
            f'[Tab Plan] kế hoạch {identity}@v{version} chưa có phản biện độc lập đạt.',
            "Chạy phiên phản biện: `delegate_task` với role='plan-review' trên ĐÚNG bản đó (nêu "
            "đường dẫn tệp và yêu cầu câu trả lời kết thúc bằng dòng `VERDICT: ok` hoặc "
            "`VERDICT: revise`).",
            'Sau đó ghi phán quyết bằng `plan_verify(identity, version, verdict, issues, summary)`.',
            'Nếu nó trả `revise`: sửa các điểm đã nêu, ghi bản kế tiếp rồi phản biện lại.',
        ])
        wake = await plan_wake(owned, identity, version, None, 'verify', '', prompt=prompt)
        payload = {'recorded': False, 'resumed': bool(wake.get('resumed')), 'wake': wake['wake']}
        if wake.get('turnId'):
            payload['turnId'] = wake['turnId']
        return web.json_response(payload)

    async def system_log_view(request):
        """Read-only view of the developer system log (plan §3.1).

        The log lives in `~/BoxFox/logs` on the HOST, so this route is the only way the
        UI can see it; nothing inside the box reaches it and no box route proxies it
        (plan §3.2 — proven by `deploy/docker/tests/test_ide_proxy_system_log.py`).
        A missing file is not an error: it only means the harness has not run yet, and
        the answer is an explicit empty list. Bad filter values raise ValueError, which
        the boundary middleware turns into a 400.
        """
        query = request.query
        limit = clamp_lines(query.get('lines'))
        entries = system_log.read(level=query.get('level'), source=query.get('source'),
                                  session_id=query.get('sessionId'), event=query.get('event'),
                                  lines=limit, since=query.get('since'))
        return web.json_response({
            # Second pass at the API layer: the writer redacts, but the file is a file,
            # so a secret value never leaves the harness through this route either.
            'entries': [redact_entry(entry) for entry in entries],
            'count': len(entries),
            'exists': system_log.path.exists(),
            'file': system_log.path.name,
            'lines': limit,
            'cap': MAX_READ_LINES,
            'runId': system_log.run_id,
            'version': HARNESS_VERSION,
            'commit': repo_commit(),
        })

    async def plan_mode_set(request):
        sid = request.match_info['sid']
        session = runtime.store.get(sid)
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get('on'), bool):
            raise ValueError('PLAN_MODE_INVALID: on phải boolean')
        if session['status'] in {'running', 'awaiting_decision'}:
            if body['on']:
                raise ValueError('SESSION_BUSY: chờ lượt hiện tại trước khi chuyển mode')
            await runtime.stop(sid)
        result = plan_workflow.service(runtime).set_mode(runtime, sid, body['on'], by='toggle')
        return web.json_response(result)

    async def work_runs(request):
        """`GET /api/agent/sessions/{sid}/work` — Work Graph runs of one session (newest first)."""
        sid = request.match_info['sid']
        session = known_session(sid)
        service = work_graph.service(runtime)
        return web.json_response({'enabled': work_graph.enabled(),
                                  'autopilot': work_graph.autopilot_on(session),
                                  'runs': [service.view(run) for run in service.runs(sid)]})

    async def work_artifact_get(request):
        sid = request.match_info['sid']
        session = known_session(sid)
        service = work_graph.service(runtime)
        result = service.artifacts.read(session, {'runId': request.match_info['runId'],
            'artifactId': request.match_info['artifactId'], 'offset': request.query.get('offset', 0),
            'limit': request.query.get('limit', 8000)})
        return web.json_response(result)

    async def autopilot_set(request):
        """`PUT /api/agent/sessions/{sid}/autopilot {on}` — skip the owner approval gate of the Work Graph."""
        sid = request.match_info['sid']
        known_session(sid)
        body = await request.json()
        if not isinstance(body, dict) or not isinstance(body.get('on'), bool):
            raise ValueError('AUTOPILOT_INVALID: on phải boolean')
        return web.json_response(work_graph.set_autopilot(runtime, sid, body['on']))

    async def execution_policy(request):
        """`GET|PUT /api/agent/sessions/{sid}/execution-policy` — mode của run (H8).

        Người vận hành là bên DUY NHẤT ghi được policy; model không có tool nào chạm tới nó.
        Mode lạ ⇒ 400 kèm mã, không đặt nửa vời.
        """
        sid = request.match_info['sid']
        known_session(sid)
        if request.method == 'GET':
            return web.json_response(execution_kernel.status(runtime, sid))
        body = await request.json()
        if not isinstance(body, dict):
            raise ApiError('EXECUTION_POLICY_BODY_INVALID', 'body needs `mode` (adaptive/legacy)')
        try:
            return web.json_response(execution_kernel.set_policy(runtime, sid, body.get('mode')))
        except ValueError as exc:
            raise _action_error(exc, {'POLICY_MODE_INVALID': 400}) from None

    async def usage_allocation(request):
        """`GET|PUT|DELETE /api/agent/sessions/{sid}/usage-allocation` — trần chi của run (H10.2).

        Người vận hành là bên DUY NHẤT mở được trần; model không có tool nào chạm tới nó.
        PUT mở một reservation trong sổ rồi ghim `harnessAllocationId` vào ĐÚNG root mà
        `usage_surface.complete()` đọc (kể cả khi gọi từ phiên con hay research-root).
        Không auto-grant: thiếu `ceiling`/`consentRef` là lỗi, không có giá trị mặc định;
        đã ghim rồi thì 409 — gỡ bằng DELETE trước, để không có đường ghi đè ngầm.
        """
        sid = request.match_info['sid']
        known_session(sid)
        ledger = usage_surface.service(runtime)
        root = usage_surface.root_session(runtime, sid)
        attached = (root['config'] or {}).get('harnessAllocationId')
        if request.method == 'GET':
            return web.json_response({'sessionId': root['id'], 'attached': bool(attached),
                                      'allocation': ledger.get_allocation(attached) if attached else None})
        if request.method == 'DELETE':
            if not attached:
                return web.json_response({'sessionId': root['id'], 'detached': False,
                                          'released': None, 'reason': 'no allocation attached'})
            view = ledger.get_allocation(attached)
            released = view['remaining']
            # `remaining == 0.0` là trạng thái HỢP LỆ (con đang giữ trọn trần), không phải
            # "không còn gì để trả": vẫn phải gọi release để luật đóng `remaining == 0` chốt
            # hàng lại, nếu không con trỏ đi rồi mà hàng `reserved` ở lại vĩnh viễn.
            if released is not None:
                ledger.release(attached, released, 'operator detached',
                               invocation_id='detach-' + attached)
            config = dict(root['config'] or {})
            config.pop('harnessAllocationId', None)
            runtime.store.update_config(root['id'], config)
            return web.json_response({'sessionId': root['id'], 'detached': True, 'released': released})
        body = await request.json()
        if not isinstance(body, dict):
            raise ApiError('USAGE_ALLOCATION_BODY_INVALID', 'body needs `ceiling` and `consentRef`')
        # `attached` ở trên đọc TRƯỚC `await request.json()`, nên hai PUT song song cùng thấy
        # `None`: cả hai reserve, cái sau ghi đè con trỏ và bỏ rơi reservation của cái trước
        # (không còn đường DELETE — hàng mồ côi vĩnh viễn). Chốt lại SAU await; từ đây tới
        # `update_config` không còn await nào nên vòng lặp sự kiện giữ lát cắt này nguyên tử.
        root = usage_surface.root_session(runtime, sid)
        attached = (root['config'] or {}).get('harnessAllocationId')
        if attached:
            raise ApiError('ALLOCATION_ALREADY_ATTACHED',
                           'detach the current allocation before attaching another', 409)
        ceiling, consent = body.get('ceiling'), body.get('consentRef')
        if consent is None or not str(consent).strip():
            raise ApiError('USAGE_NO_CONSENT', 'consentRef is required to attach a ceiling')
        if not isinstance(ceiling, (int, float)) or isinstance(ceiling, bool) or not ceiling > 0:
            raise ApiError('USAGE_FIELD_INVALID', 'ceiling must be a positive number')
        try:
            # `int` khổng lồ (10**400) qua được `isinstance` nhưng `float()` ném
            # OverflowError: đó vẫn là ceiling sai, không được rơi ra 500.
            amount = float(ceiling)
        except OverflowError:
            raise ApiError('USAGE_FIELD_INVALID', 'ceiling must be a positive number') from None
        allocation_id = 'alloc-' + uuid.uuid4().hex
        try:
            view = ledger.reserve(allocation_id, root['id'],
                                  execution_kernel.capability_epoch(runtime, root), str(consent),
                                  # `ceiling` là bắt buộc với root: `None` không phải vô hạn,
                                  # nên trần phải khai đúng bằng số tiền người vận hành chốt.
                                  {'amount': amount, 'ceiling': amount,
                                   'currency': 'USD', 'purpose': body.get('purpose') or 'session'},
                                  'attach-' + allocation_id)
        except ValueError as exc:
            raise _action_error(exc, {'USAGE_ALLOCATION_CONFLICT': 409,
                                      'USAGE_ALLOCATION_UNKNOWN': 409}) from None
        config = dict(root['config'] or {})
        config['harnessAllocationId'] = allocation_id
        runtime.store.update_config(root['id'], config)
        return web.json_response({'sessionId': root['id'], 'attached': True, 'allocation': view})

    async def plan_runs(request):
        workflow = plan_workflow.service(runtime)
        rid = request.match_info.get('runId')
        if rid:
            return web.json_response(workflow.get(rid))
        sid = request.query.get('sessionId')
        runtime.store.get(sid)
        return web.json_response({'runs': workflow.runs(sid)})

    async def plan_run_mutate(request):
        workflow = plan_workflow.service(runtime)
        rid = request.match_info['runId']
        run = workflow.get(rid)
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('PLAN_BODY_INVALID')
        if request.path.endswith('/answers'):
            result = workflow.answers(rid, body)
        else:
            # Commit the owner action before cancellation. stop() checkpoints active work;
            # stopping first would increment the revision and reject this valid action.
            result = workflow.action(rid, body)
            if body.get('action') in {'pause', 'cancel'} and run['sessionId'] in runtime.tasks:
                await runtime.stop(run['sessionId'])
            if body.get('action') in {'resume', 'new', 'current'}:
                config = runtime.store.get(run['sessionId'])['config']
                config['planMode'] = dict(config.get('planMode') or {}) | {'activeRunId': result['run']['runId']}
                runtime.store.update_config(run['sessionId'], config)
                workflow.set_mode(runtime, run['sessionId'], True)
        # Answers and continuation are already committed; pump failure must not lose them.
        try:
            await plan_workflow.pump(runtime)
        except Exception:
            logger.exception('plan resume deferred')
        return web.json_response(result)

    async def plan_execute(request):
        workflow = plan_workflow.service(runtime)
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError('PLAN_BODY_INVALID')
        run = workflow.for_document(body.get('identity'), body.get('version'))
        if run is None:
            raise ValueError('PLAN_LEGACY_ADOPTION_REQUIRED: mở /plan với đường dẫn bản cũ để khảo sát, '
                             'xác nhận brief và phản biện theo chuẩn mới trước khi triển khai')
        session = runtime.store.get(run['sessionId'])
        if session['status'] in {'running', 'awaiting_decision'} and run['status'] != 'executing':
            raise ValueError('SESSION_BUSY')
        doc = run['document']
        if (doc['identity'], doc['version'], doc['contentHash']) != (body.get('identity'), body.get('version'), body.get('contentHash')):
            raise ValueError('PLAN_EXECUTE_STALE: bản/hash yêu cầu không phải bản hiện tại')
        # Read every slice and compare actual bytes, not filesystem size/mtime or a UI assertion.
        chunks, offset = [], 0
        for _ in range(60):
            result = await runtime.executor.execute('file_read', {'path': doc['relativePath'],
                                                   'offset': offset, 'limit': 30000}, session['id'])
            if result.get('is_error') or not isinstance(result.get('content'), str):
                raise ValueError('PLAN_EXECUTE_UNREADABLE: chưa đọc được bản đã duyệt')
            chunks.append(result['content'])
            next_offset = result.get('nextOffset')
            if next_offset is None:
                break
            if not isinstance(next_offset, int) or next_offset <= offset:
                raise ValueError('PLAN_EXECUTE_UNREADABLE')
            offset = next_offset
        else:
            raise ValueError('PLAN_EXECUTE_UNREADABLE')
        digest = hashlib.sha256(''.join(chunks).encode('utf-8')).hexdigest()
        if digest != doc['contentHash']:
            raise ValueError('PLAN_EXECUTE_STALE: nội dung trên đĩa đã đổi; phải phản biện và duyệt lại')
        result = workflow.execute(run, body)
        try:
            await plan_workflow.pump(runtime)
        except Exception:
            logger.exception('plan execution admitted durably but not started')
        return web.json_response(result)

    async def close(app):
        watchdog = getattr(runtime, 'watchdog', None)
        if watchdog is not None:
            await watchdog.stop()
        for sid in list(runtime.tasks):
            await runtime.stop(sid)
        runtime.store.close()
        # Graceful shutdown is the owner's "reset on shutdown": mark the end of the run
        # in the file it happened in, then reset it to `harness.previous.jsonl` so the
        # next run opens a fresh, empty active file (plan §3.3). A hard kill never gets
        # here, so an abrupt death loses nothing — the file simply stays.
        try:
            port = harness_port()
        except ValueError:
            port = None
        system_log.write('harness.stop', port=port, pid=os.getpid())
        system_log.rotate_on_shutdown()

    app.router.add_get('/api/agent/health', health)
    app.router.add_get('/api/agent/catalog', catalog)
    app.router.add_get('/api/agent/runtime-info', runtime_info)
    app.router.add_get('/api/agent/skill-settings', skill_settings)
    app.router.add_put('/api/agent/skill-settings', skill_settings)
    app.router.add_get('/api/agent/owner-settings', owner_settings)
    app.router.add_put('/api/agent/owner-settings', owner_settings)
    app.router.add_get('/api/agent/commands', commands)
    app.router.add_post('/api/agent/commands', commands)
    app.router.add_post('/api/agent/commands/resolve', resolve)
    app.router.add_put('/api/agent/commands/{slug}', command)
    app.router.add_delete('/api/agent/commands/{slug}', command)
    app.router.add_get('/api/agent/executors/claude-code', executor_status)
    app.router.add_get('/api/agent/desktop/lease', desktop_lease)
    app.router.add_post('/api/agent/desktop/lease', desktop_lease)
    app.router.add_post('/api/agent/desktop/inspect-element', desktop_inspect_element)
    app.router.add_get('/api/agent/permissions', permissions)
    app.router.add_put('/api/agent/permissions', permissions)
    app.router.add_post('/api/agent/permissions/decide', permissions_decide)
    app.router.add_get('/api/agent/permissions/pending', permissions_pending)
    app.router.add_get('/api/agent/permissions/rules', permissions_rules)
    app.router.add_delete('/api/agent/permissions/rules', permissions_rules)
    app.router.add_get('/api/agent/skills/{skill}', skill)
    app.router.add_get('/api/agent/skills/{skill}/readiness', readiness)
    if getattr(runtime, 'machine_registry', None) is not None:
        from ..sandbox.machine_router import register_routes
        register_routes(app, runtime)
    app.router.add_get('/api/agent/sessions', list_sessions)
    app.router.add_get('/api/agent/research/jobs', research_jobs)
    app.router.add_get('/api/agent/research/jobs/{research_id}', research_job_detail)
    app.router.add_patch('/api/agent/research/jobs/{research_id}', research_job_update)
    app.router.add_put('/api/agent/sessions/{sid}/research-mode', research_mode_set)
    app.router.add_get('/api/agent/sessions/{sid}/execution-policy', execution_policy)
    app.router.add_put('/api/agent/sessions/{sid}/execution-policy', execution_policy)
    app.router.add_get('/api/agent/sessions/{sid}/usage-allocation', usage_allocation)
    app.router.add_put('/api/agent/sessions/{sid}/usage-allocation', usage_allocation)
    app.router.add_delete('/api/agent/sessions/{sid}/usage-allocation', usage_allocation)
    app.router.add_post('/api/agent/research/prompts/{prompt_id}/answer', research_prompt_answer)
    app.router.add_post('/api/agent/research/prompts/{prompt_id}/dismiss', research_prompt_dismiss)
    # P1 (design-interfaces §5) — bảy tuyến của chế độ Design.
    app.router.add_put('/api/agent/sessions/{sid}/design-mode', design_mode_set)
    app.router.add_get('/api/agent/design/runs', design_runs)
    app.router.add_get('/api/agent/design/runs/{design_id}', design_run_detail)
    app.router.add_patch('/api/agent/design/runs/{design_id}', design_run_update)
    app.router.add_post('/api/agent/design/runs/{design_id}/touch-list/approve', design_touch_list_approve)
    app.router.add_post('/api/agent/design/prompts/{prompt_id}/answer', design_prompt_answer)
    app.router.add_post('/api/agent/sessions/{sid}/canvas', session_canvas)
    app.router.add_post('/api/agent/sessions', create)
    app.router.add_get('/api/agent/sessions/{sid}', session)
    app.router.add_delete('/api/agent/sessions/{sid}', delete_session)
    app.router.add_post('/api/agent/sessions/{sid}/turns', turn)
    app.router.add_post('/api/agent/sessions/{sid}/stop', stop)
    app.router.add_post('/api/agent/sessions/{sid}/decisions', decision)
    app.router.add_get('/api/agent/sessions/{sid}/decisions', session_decisions)
    app.router.add_put('/api/agent/sessions/{sid}/longtask', session_longtask)
    app.router.add_post('/api/agent/sessions/{sid}/longtask/actions', session_longtask_actions)
    app.router.add_get('/api/agent/sessions/{sid}/tasks', session_tasks)
    app.router.add_post('/api/agent/sessions/{sid}/deletion-preview', session_deletion_preview)
    app.router.add_post('/api/agent/sessions/{sid}/deletion-confirm', session_deletion_confirm)
    app.router.add_get('/api/agent/history/sessions', history_sessions)
    app.router.add_get('/api/agent/history/search', history_search)
    app.router.add_get('/api/agent/history/storage', history_storage)
    app.router.add_get('/api/agent/history/records/{recordId}', history_record)
    app.router.add_get('/api/agent/sessions/{sid}/journal', session_journal)
    app.router.add_get('/api/agent/journal/tasks', journal_tasks)
    app.router.add_post('/api/agent/plans/review', plan_review)
    app.router.add_get('/api/agent/plans/status', plan_status)
    app.router.add_post('/api/agent/plans/verify', plan_verify_route)
    app.router.add_put('/api/agent/sessions/{sid}/plan-mode', plan_mode_set)
    app.router.add_get('/api/agent/sessions/{sid}/work', work_runs)
    app.router.add_get('/api/agent/sessions/{sid}/work/runs/{runId}/artifacts/{artifactId}', work_artifact_get)
    app.router.add_put('/api/agent/sessions/{sid}/autopilot', autopilot_set)
    app.router.add_get('/api/agent/plans/runs', plan_runs)
    app.router.add_get('/api/agent/plans/runs/{runId}', plan_runs)
    app.router.add_post('/api/agent/plans/runs/{runId}/answers', plan_run_mutate)
    app.router.add_post('/api/agent/plans/runs/{runId}/actions', plan_run_mutate)
    app.router.add_post('/api/agent/plans/execute', plan_execute)
    # DEV-only surface: the system log is host-only and read-only. There is deliberately
    # no write route and no route of the box that reaches it (plan §3.1 + §3.2).
    app.router.add_get('/api/agent/system-log', system_log_view)
    app.on_cleanup.append(close)
    return app



def main():
    data = Path(os.environ.get('BOXFOX_AGENT_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'BoxFox/harness')))
    port = harness_port()
    executor = build_executor(data)
    runtime = HarnessRuntime(SessionStore(data / 'sessions.sqlite'), executor)
    attach_host_approver(runtime)
    # Gắn ở CẢ HAI chế độ: host mode cũng cần `/api/agent/machines/*` (cấu hình folder, cây tệp,
    # `.plans`) — trước đây thiếu ở host nên giao diện rơi về Docker binding và tab Plan trắng số.
    # `default_mode`/`default_workspace` chỉ tạo cấu hình cho CSDL mới (bản desktop mở ra là host).
    from ..sandbox.machine_router import attach
    mode = execution_mode()
    # Bộ điều khiển desktop dùng CHUNG cho mọi phiên host: ở chế độ host nó đã có sẵn trên executor,
    # còn ở chế độ docker (mặc định của bản desktop, máy vẫn cấu hình host) phải dựng riêng — thiếu
    # nó thì mọi phiên host trả `CUA_UNAVAILABLE` và route lease trả 409.
    shared_desktop = getattr(executor, 'desktop', None) or build_desktop_control(data)
    shared_overlay = getattr(executor, 'overlay', None) or build_cua_overlay(None, shared_desktop)
    attach(runtime, data, default_mode=mode,
           default_workspace=host_workspace() if mode == 'host' else None,
           desktop=shared_desktop, overlay=shared_overlay)
    system_log.write('harness.start', dataDir=str(data), port=port, pid=os.getpid(),
                     python=sys.version.split()[0])
    # Host mode: bật DPI awareness + bảng phần tử (H5) và hook phát hiện người thật (H7) MỘT LẦN
    # cho cả tiến trình. Hook hỏng ⇒ fail-closed ở tầng lease, KHÔNG làm chết khởi động: agent vẫn
    # dùng được công cụ tệp/lệnh.
    if shared_desktop is not None:
        prepare = getattr(executor, 'prepare', None)
        prepared, prepare_code = prepare() if prepare is not None else (True, '')
        hooks_ok, hooks_code = shared_desktop.install_hooks()
        system_log.write('desktop.ready', level='info' if prepared else 'warn',
                         message='điều khiển desktop đã sẵn sàng' if prepared else 'chưa sẵn sàng',
                         data={'prepared': prepared, 'prepareCode': prepare_code,
                               'hooks': hooks_ok, 'hooksCode': hooks_code})
    try:
        web.run_app(create_app(runtime), host='127.0.0.1', port=port, print=None)
    finally:
        # `close()` is the normal path (`harness.stop` + reset). This call covers a
        # startup that died before the aiohttp cleanup ran; it is a no-op when the file
        # was already reset, because then there is no active file left to rename.
        system_log.rotate_on_shutdown()


if __name__ == '__main__':
    main()
