"""Loopback harness API; UI uses the Vite /api/agent proxy."""
import asyncio
import hashlib
import logging
import os
import re
import sys
import time
from pathlib import Path
from aiohttp import web
from ..agent_core import plan_registry, research_runtime
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
from ..agent_core import research_profiles, research_quality, research_runtime, source_tiers
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
from .owner_settings import OwnerSettings


logger = logging.getLogger('boxfox.harness.api')
RESEARCH_PUMP_KEY = web.AppKey('research_pump', asyncio.Task)


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


def create_app(runtime):
    @web.middleware
    async def boundary(request, handler):
        if request.host not in allowed_hosts():
            return web.json_response({'error': 'Host not allowed'}, status=403)
        if request.path != '/api/agent/health':
            if request.headers.get('X-BoxFox-Admin') != '1' or request.headers.get('Origin', 'http://localhost:3100') not in {'http://localhost:3100', 'http://127.0.0.1:3100'}:
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
        async def pump():
            while True:
                await asyncio.sleep(15)
                await research_continuation_step(runtime)
        _app[RESEARCH_PUMP_KEY] = asyncio.create_task(pump())

    async def stop_research_continuations(_app):
        task = _app.get(RESEARCH_PUMP_KEY)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    app.on_startup.append(research_continuations)
    app.on_cleanup.append(stop_research_continuations)

    async def health(request):
        return web.json_response({'status': 'ok', 'service': 'boxfox-harness', 'version': HARNESS_VERSION})

    async def catalog(request):
        return web.json_response({'roles': [{'id': r.id, 'name': r.name, 'instructions': r.instructions, 'tools': sorted(r.tools)} for r in ROLES.values()], 'skills': runtime.catalog.list(runtime.commands.settings()['enabled'])})

    async def runtime_info(request):
        """Nút vặn của runtime, chỉ đọc và không tham số — cho tab Harness của Settings.

        Bảng này là nguồn duy nhất cho mọi con số giao diện hiển thị (tám nhóm công cụ,
        bộ của từng vai trò, chính sách retry, trần bước/thời gian/ký tự): không chỗ nào
        ở phía UI được chép tay lại một con số, nếu không hai bên sẽ lệch nhau và khối
        "Tool access" sẽ hứa điều engine từ chối.
        """
        return web.json_response({
            'toolGroups': tool_groups(),
            'tools': sorted(ORCHESTRATOR_TOOLS),
            'roles': [{'id': r.id, 'name': r.name, 'tools': sorted(r.tools), 'skills': list(r.skills)}
                      for r in ROLES.values()],
            'retry': {'maxRetries': DEFAULT_MAX_RETRIES,
                      'backoffSeconds': list(BACKOFF_SECONDS),
                      'rateLimitMaxSeconds': RATE_LIMIT_MAX_SECONDS,
                      'budgetSeconds': RETRY_BUDGET_SECONDS,
                      'jitter': BACKOFF_JITTER},
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
                               'storeMaxEntries': READ_STORE_MAX_ENTRIES}},
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
        return web.json_response(await ClaudeExecutor(runtime.executor.container).probe())

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
        return web.json_response(runtime.create(value), status=201)

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
        return web.json_response({k: v for k, v in value.items() if k != 'messages'} |
                                 {'events': runtime.store.events(sid, int(request.query.get('after', '0'))),
                                  'sessionMetrics': runtime.session_metrics(sid),
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
            result = runtime.resolve_decision(sid, body.get('decisionId'), body.get('choice'), body.get('note'))
        except DecisionError as exc:
            return web.json_response({'error': str(exc)}, status=exc.status)
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

    async def delete_session(request):
        sid = request.match_info['sid']
        if sid in runtime.tasks:
            try:
                await runtime.stop(sid)
            except Exception:
                pass
        runtime.store.delete(sid)
        return web.json_response({'status': 'deleted', 'id': sid})

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

    async def plan_index_or_none():
        """Chỉ mục box, hoặc `None` khi không đọc được (đã ghi nhật ký `PLAN_INDEX_UNAVAILABLE`).

        Không bao giờ raise: mất chỉ mục chỉ làm mất phần *số đo* (nhóm nào có những bản nào), còn
        quyết định của người dùng vẫn phải ghi được.
        """
        try:
            return await plan_registry.read_plan_index(runtime.executor)
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
        index = await plan_index_or_none()
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
            row = runtime.store.record_plan_review(
                identity, version, decision, note=note, source='plan-tab', session_id=owned,
                content_size=None if entry is None else entry.size_bytes,
                content_modified_at=None if entry is None else entry.modified_at)
        except ValueError as exc:
            raise ApiError('PLAN_REVIEW_INVALID', str(exc), 400) from None

        forwarded = True
        try:
            await runtime.executor.request('/__box/plans/review',
                                           {'identity': identity, 'version': version,
                                            'decision': decision, 'note': note})
        except Exception as exc:
            forwarded = False
            system_log.write('plan.review.forward_failed', level='warn', code='PLAN_REVIEW_FORWARD_FAILED',
                             message='Đã ghi quyết định duyệt vào sổ của harness nhưng chưa chuyển được '
                                     'sang box; badge trong .reviews sẽ cập nhật ở lần duyệt sau.',
                             reason=f'{type(exc).__name__}: {exc}')
        # M6 (D-35/Q3/Q4) — quyết định đã vào sổ, giờ mở MỘT LƯỢT THẬT trong phiên gốc. Cú bấm cũ
        # chỉ ghi sổ rồi im lặng (đo vòng 25: 3/3 lần bấm, 55-60 s không có gì xảy ra).
        if not owned:
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

        index = await plan_index_or_none()
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
    app.router.add_get('/api/agent/skills/{skill}', skill)
    app.router.add_get('/api/agent/skills/{skill}/readiness', readiness)
    app.router.add_get('/api/agent/sessions', list_sessions)
    app.router.add_get('/api/agent/research/jobs', research_jobs)
    app.router.add_get('/api/agent/research/jobs/{research_id}', research_job_detail)
    app.router.add_patch('/api/agent/research/jobs/{research_id}', research_job_update)
    app.router.add_put('/api/agent/sessions/{sid}/research-mode', research_mode_set)
    app.router.add_post('/api/agent/research/prompts/{prompt_id}/answer', research_prompt_answer)
    app.router.add_post('/api/agent/research/prompts/{prompt_id}/dismiss', research_prompt_dismiss)
    app.router.add_post('/api/agent/sessions', create)
    app.router.add_get('/api/agent/sessions/{sid}', session)
    app.router.add_delete('/api/agent/sessions/{sid}', delete_session)
    app.router.add_post('/api/agent/sessions/{sid}/turns', turn)
    app.router.add_post('/api/agent/sessions/{sid}/stop', stop)
    app.router.add_post('/api/agent/sessions/{sid}/decisions', decision)
    app.router.add_get('/api/agent/sessions/{sid}/journal', session_journal)
    app.router.add_get('/api/agent/journal/tasks', journal_tasks)
    app.router.add_post('/api/agent/plans/review', plan_review)
    app.router.add_get('/api/agent/plans/status', plan_status)
    app.router.add_post('/api/agent/plans/verify', plan_verify_route)
    # DEV-only surface: the system log is host-only and read-only. There is deliberately
    # no write route and no route of the box that reaches it (plan §3.1 + §3.2).
    app.router.add_get('/api/agent/system-log', system_log_view)
    app.on_cleanup.append(close)
    return app



def main():
    data = Path(os.environ.get('BOXFOX_AGENT_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'BoxFox/harness')))
    port = harness_port()
    runtime = HarnessRuntime(SessionStore(data / 'sessions.sqlite'), SandboxExecutor(
        api_key=os.environ.get('BOXFOX_API_KEY', 'boxfox-local-dev-token')))
    system_log.write('harness.start', dataDir=str(data), port=port, pid=os.getpid(),
                     python=sys.version.split()[0])
    try:
        web.run_app(create_app(runtime), host='127.0.0.1', port=port, print=None)
    finally:
        # `close()` is the normal path (`harness.stop` + reset). This call covers a
        # startup that died before the aiohttp cleanup ran; it is a no-op when the file
        # was already reset, because then there is no active file left to rename.
        system_log.rotate_on_shutdown()


if __name__ == '__main__':
    main()
