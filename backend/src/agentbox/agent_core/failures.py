"""Classify a turn/command failure into a stable code plus a readable message.

Why this module exists
----------------------
Every failure path used to emit ``str(exc)``. Several exceptions that reach the
harness stringify to an EMPTY message (``aiohttp.ServerDisconnectedError``,
``ConnectionResetError``, a bare ``Exception()``, a cancelled socket read).
The chat UI then falls back to the literal ``Agent run failed``
(``frontend/src/store/harnessChatStore.ts:277-283``), which tells the user
nothing and cannot be searched in support chats.

Contract
--------
``classify_failure(exc)`` returns ``(code, message)``:

* ``code`` is an uppercase machine token (``DEADLINE``, ``UPSTREAM_UNREACHABLE``,
  ``UPSTREAM_HTTP_502``, ``TOOL_NOT_PERMITTED``, or ``TURN_FAILED_<EXCNAME>``).
  Tokens already carried by a ``ValueError`` prefix (``CONTEXT_LIMIT: …``) are
  preserved, so existing tests and the UI keep their contract.
* ``message`` is never empty and always contains the original reason, so a
  developer reading the chat or the system log sees what actually broke.
"""

from __future__ import annotations

import asyncio
import re
import traceback

__all__ = ['classify_failure', 'describe_failure', 'failure_detail', 'is_transient', 'level_refusal',
           'retry_advice', 'stop_reason', 'RETRYABLE_STATUS', 'DEFAULT_MAX_RETRIES', 'BACKOFF_SECONDS',
           'RETRY_BUDGET_SECONDS']

# Codes already produced as a ``ValueError('CODE: text')`` prefix by the runtime,
# the command layer or the sandbox. Matched by prefix so the original wording
# survives untouched.
KNOWN_PREFIXES = (
    'CONTEXT_LIMIT',
    'THINKING_LEVEL_UNSUPPORTED',
    'SETUP_REQUIRED',
    'CHILD_FAILED',
    'PLAN_QUALITY_REJECTED',
    'PLAN_EVAL_REJECTED',      # đợt 20 §5: cổng cứng P1/P2/P4/P7/P8 của thang điểm P1–P8
    'PLAN_INVALID',
    'PLAN_SLUG_INVALID',
    'PLAN_WRITE_FAILED',
    'PLAN_WRITE_CONFLICT',     # hai người ghi cùng số version: đọc lại chỉ mục một lần rồi thôi
    # Vòng 25 (D-33/D-34): bốn mã của vòng lặp kế hoạch được `ValueError('MÃ: câu')` ném ra từ
    # `plan_verify`/`decision` — thiếu chúng ở đây thì model nhận `TURN_FAILED_VALUEERROR` thay vì
    # mã nói đúng phần còn thiếu, và chính cổng duyệt (`PLAN_APPROVAL_UNVERIFIED`) cũng mất tên.
    'PLAN_VERIFY_INVALID',
    'PLAN_VERIFY_NO_CRITIC',
    'PLAN_VERIFY_VERDICT_MISSING',
    'PLAN_VERIFY_VERDICT_MISMATCH',
    'PLAN_APPROVAL_UNVERIFIED',
    'DECISION_UNAVAILABLE',
    'DECISION_INVALID',
    'DECISION_NOT_FOUND',
    'DECISION_ALREADY_RESOLVED',
    'MAX_STEPS',          # lượt cũ trong DB: giữ nguyên nghĩa, KHÔNG dùng cho code mới
    'DEADLINE',           # như trên — mã cũ, chỉ để đọc lại bản ghi cũ
    'STEP_BUDGET_EXHAUSTED',  # vòng 22 (D-1): hết ngân sách bước, tách khỏi hết hạn chót
    'DEADLINE_EXCEEDED',      # vòng 22 (D-1): hết hạn chót của lượt
    'ANSWER_TOO_LONG',        # vòng 22 (D-4): câu trả lời vượt trần cứng
    'SKILL_TASK_REQUIRED',
    'MISSING_TASK',
    'SESSION_BUSY',
    'OUTPUT_LIMIT',
    'ROUTER_',
    'WORKSPACE_',
    'WEB_',
    'CLI_',
    # Vòng soát hộp thật: chối của đường thiết kế phải ra ĐÚNG mã hợp đồng `DESIGN_*`
    # (khuôn `WEB_`) chứ không phải `TURN_FAILED_VALUEERROR`, để giao diện có mã mà ánh xạ.
    'DESIGN_',
    # Lớp Work Graph + phỏng vấn nhiều câu (lớp điều phối mới).
    'WORK_',
    'INTERVIEW_',
)

# Bug `PLAN_BRIEF_INVALID` → `TURN_FAILED_VALUEERROR` (đo sống): 48 mã `PLAN_*` và nhiều họ mã khác
# được ném dạng `ValueError('MÃ_HOA: câu')` mà không nằm trong danh sách trên, nên model mất tên mã.
# Luật chung: một lỗi dữ liệu mở đầu bằng MÃ_VIẾT_HOA (có ít nhất một dấu gạch dưới) rồi `:` giữ
# nguyên mã ấy. Danh sách trên vẫn là nguồn cho các mã không có gạch dưới và cho thứ tự ưu tiên.
CODE_PREFIX_RE = re.compile(r'^([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+):(?:\s|$)')

# Exceptions that mean "the upstream endpoint is gone"; their ``str()`` is often
# empty, which is exactly the case this module exists for.
_UNREACHABLE_NAMES = {
    'ServerDisconnectedError',
    'ClientConnectionError',
    'ClientConnectorError',
    'ClientOSError',
    'ClientPayloadError',
    'ClientResponseError',
    'ConnectError',
    'ConnectTimeout',
    'ConnectionResetError',
    'ConnectionAbortedError',
    'ConnectionRefusedError',
    'ReadTimeout',
    'ReadError',
    'RemoteProtocolError',
    'TransportError',
    'TimeoutException',
    'IncompleteReadError',
    'ServerTimeoutError',
}


def _reason(exc: BaseException) -> str:
    """Text of the exception that is never empty."""
    text = str(exc).strip()
    return text or repr(exc)


def _is_timeout(exc: BaseException) -> bool:
    """True for the builtin timeouts AND the httpx-family ones.

    ``httpx.ReadTimeout``/``ConnectTimeout``/``WriteTimeout``/``PoolTimeout`` derive from
    ``TimeoutException``/``TransportError``, NOT from the builtin ``TimeoutError``, so a slow
    upstream used to be reported as "closed the connection" — the opposite advice.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    name = type(exc).__name__
    return name.endswith('Timeout') or name in {'TimeoutException', 'ReadTimeout', 'ConnectTimeout'}


def _readable(reason: str) -> str:
    """A phrase a person can act on when the exception text is empty or opaque."""
    if reason.startswith('<') or reason.startswith('(') or len(reason) > 200:
        return reason[:200]
    return reason


def classify_failure(exc: BaseException) -> tuple[str, str]:
    """Return ``(code, message)`` for a failure that ended a turn or a command."""
    reason = _reason(exc)
    name = type(exc).__name__

    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        # Vòng 22 (D-1): mã nói rõ là HẠN CHÓT, không lẫn với hết ngân sách bước. Mã cũ
        # `DEADLINE` vẫn đọc được trong lịch sử nên nó nằm lại trong KNOWN_PREFIXES.
        return 'DEADLINE_EXCEEDED', 'DEADLINE_EXCEEDED: the turn ran out of time before an answer was produced'

    # httpx timeouts: the upstream WAS reachable but too slow. Say that, and keep the code
    # distinct from a hard deadline so the retry decision stays separate from the wording.
    if not isinstance(exc, (asyncio.TimeoutError, TimeoutError)) and _is_timeout(exc):
        return 'UPSTREAM_TIMEOUT', (
            f'UPSTREAM_TIMEOUT: the model provider did not answer in time ({name}: {_readable(reason)})'
        )

    if isinstance(exc, PermissionError):
        # W8.A4.2 — cổng phạm vi thi công mang mã RIÊNG của nó (`WORK_SCOPE_*`), không phải mã chung
        # `TOOL_NOT_PERMITTED`: log/giao diện phải phân biệt "vai này không có quyền" với "run này
        # không cho sửa mã", vì bước tiếp theo của hai ca khác nhau.
        if reason.startswith('WORK_SCOPE_'):
            return reason.split(':', 1)[0].strip(), reason
        return 'TOOL_NOT_PERMITTED', 'TOOL_NOT_PERMITTED: ' + reason

    if name in _UNREACHABLE_NAMES or isinstance(exc, (ConnectionError,)):
        return 'UPSTREAM_UNREACHABLE', (
            f'UPSTREAM_UNREACHABLE: the model router or provider closed the connection ({name}: {reason})'
        )

    # ``Router HTTP 502: …`` from RouterClient/complete()
    if isinstance(exc, RuntimeError) and reason.startswith('Router HTTP '):
        head, _, tail = reason.partition(':')
        status = head.split()[-1].strip()
        code = 'UPSTREAM_HTTP_' + (status if status.isdigit() else 'ERROR')
        return code, f'{code}: the model router answered {head} ({tail.strip() or "no detail"})'

    for prefix in KNOWN_PREFIXES:
        if reason.startswith(prefix):
            code = reason.split(':', 1)[0].strip() or prefix
            return code, reason

    match = CODE_PREFIX_RE.match(reason)
    if match and isinstance(exc, (ValueError, LookupError, RuntimeError)):
        return match.group(1), reason

    if isinstance(exc, ValueError) and reason.startswith('Upstream did not return any SSE completion content'):
        return 'TURN_EMPTY_STREAM', 'TURN_EMPTY_STREAM: the provider stream ended without any content or tool call'

    if isinstance(exc, ValueError) and reason.startswith('Model did not produce a complete non-empty final response'):
        return 'TURN_EMPTY_RESPONSE', (
            'TURN_EMPTY_RESPONSE: the model finished without a usable answer (no text, no tool call)'
        )

    if isinstance(exc, ValueError) and reason.startswith('Tool-call batch exceeds limit'):
        return 'TURN_TOOL_BATCH', 'TURN_TOOL_BATCH: the model requested more tool calls in one step than allowed'

    code = 'TURN_FAILED_' + ''.join(ch for ch in name.upper() if ch.isalnum())[:32]
    return code, f'{code}: {name}: {reason}'


def log_safe_failure(exc: BaseException) -> tuple[str, str, str]:
    """``(code, message, detail)`` for a log line that must not carry user content.

    A tool that handles content the user did not write for us — a search query, a fetched
    URL — marks its exception with ``log_message``. Those lines then log the code and the
    counted shape only, and skip the traceback (which repeats the message verbatim).
    """
    code, message = classify_failure(exc)
    safe = getattr(exc, 'log_message', None)
    if safe:
        return code, safe, ''
    return code, message, failure_detail(exc)


def describe_failure(exc: BaseException) -> str:
    """``'CODE: message'`` — the string a caller can emit or log directly."""
    code, message = classify_failure(exc)
    return message if message.startswith(code) else f'{code}: {message}'


def failure_detail(exc: BaseException, limit: int = 12) -> str:
    """Traceback tail for the developer system log (never sent to the model)."""
    frames = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return ''.join(frames)[-4000:] if frames else repr(exc)


# --------------------------------------------------------------------------- #
# Retry policy
# --------------------------------------------------------------------------- #
# One place decides whether a failed model request gets another attempt, how long to wait
# before it, and when to stop. Both the harness step loop and the tests read this, so the
# policy cannot drift between the two.
#
# The rules come from what the failures actually look like in production:
#
# * A throttled or overloaded endpoint (429, 5xx, a dropped socket, an empty stream) is worth
#   another attempt: the same request succeeds a few seconds later. This is the case the old
#   one-shot retry handled, and it missed 429 entirely — a provider limit failed the turn
#   immediately while the provider was merely asking us to slow down.
# * A slow endpoint is NOT worth another attempt: it already spent the turn's window, and a
#   second call starts from zero. ``DEADLINE``/``UPSTREAM_TIMEOUT`` therefore never retry.
# * A rejected request (401/403/404, a bad payload, a context-limit refusal) never retries:
#   the second call fails identically.
# * Waiting is bounded twice: per attempt (a 429 carries ``Retry-After``/``retryAfterMs`` from
#   the router, clamped to ``RATE_LIMIT_MAX_SECONDS``) and per turn
#   (``RETRY_BUDGET_SECONDS`` in total). A retry must also leave ``MIN_RETRY_WINDOW_SECONDS``
#   of the turn budget to be useful, otherwise the loop stops and reports instead of sleeping
#   into a deadline.
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
# Retries AFTER the first call: 4 provider calls at most for one step.
DEFAULT_MAX_RETRIES = 3
BACKOFF_SECONDS = (1.0, 4.0, 12.0)
RATE_LIMIT_MIN_SECONDS = 2.0
RATE_LIMIT_MAX_SECONDS = 30.0
RETRY_BUDGET_SECONDS = 60.0
MIN_RETRY_WINDOW_SECONDS = 5.0
BACKOFF_JITTER = 0.2

# Rate limits arrive from the router with a machine code as well as a status.
_RATE_LIMIT_CODES = frozenset({'RATE_LIMIT', 'CAPACITY', 'UPSTREAM_HTTP_429'})


def router_status(exc: BaseException) -> int | None:
    """HTTP status the model router answered with, when the failure came from it."""
    attached = getattr(exc, 'router_status', None)
    if isinstance(attached, int):
        return attached
    reason = _reason(exc)
    if isinstance(exc, RuntimeError) and reason.startswith('Router HTTP '):
        token = reason.split()[2].rstrip(':') if len(reason.split()) > 2 else ''
        return int(token) if token.isdigit() else None
    return None


def retry_after_seconds(exc: BaseException) -> float | None:
    """``Retry-After`` the router forwarded from the provider, in seconds."""
    milliseconds = getattr(exc, 'retry_after_ms', None)
    if isinstance(milliseconds, (int, float)) and milliseconds > 0:
        return float(milliseconds) / 1000.0
    return None


def _retry_reason(exc: BaseException, status: int | None) -> str | None:
    """Why another attempt could succeed: ``rate-limit``, ``upstream``, ``stream`` or nothing."""
    code = getattr(exc, 'router_code', None)
    # Phán quyết của router là thẩm quyền cao nhất: nó đã tự thử lại theo `retryable`
    # của nhà cung cấp và chỉ trả lời khi đã bỏ cuộc. `retryable: false` nghĩa là
    # nhà cung cấp nói lỗi này không qua được bằng cách gửi lại — bỏ qua phán quyết
    # đó thì lượt chờ thêm tới 3 lần cho một lỗi đã được xác nhận là vĩnh viễn.
    if getattr(exc, 'retryable', None) is False and status != 429 and code not in _RATE_LIMIT_CODES:
        return None
    if status == 429 or code in _RATE_LIMIT_CODES:
        return 'rate-limit'
    name = type(exc).__name__
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)) or _is_timeout(exc):
        # The window is already spent; see the module comment above.
        return None
    if status is not None:
        return 'upstream' if status in RETRYABLE_STATUS else None
    if name in _UNREACHABLE_NAMES or isinstance(exc, ConnectionError):
        return 'stream'
    if name in {'ReadError', 'WriteError', 'PoolTimeout', 'NetworkError', 'HTTPError'}:
        return 'stream'
    if isinstance(exc, ValueError) and _reason(exc).startswith('Upstream did not return any SSE completion content'):
        return 'stream'
    return None


def _retry_delay(exc: BaseException, reason: str, attempt: int, rng) -> float:
    """Seconds to wait before attempt ``attempt + 1``."""
    if reason == 'rate-limit':
        asked = retry_after_seconds(exc)
        base = asked if asked is not None else RATE_LIMIT_MIN_SECONDS
    else:
        base = BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS) - 1)]
        spread = rng.uniform(-BACKOFF_JITTER, BACKOFF_JITTER)
        base = base * (1.0 + spread)
    low, high = (RATE_LIMIT_MIN_SECONDS, RATE_LIMIT_MAX_SECONDS) if reason == 'rate-limit' else (0.5, RETRY_BUDGET_SECONDS)
    return min(max(base, low), high)


def retry_advice(exc: BaseException, attempt: int, remaining_seconds: float | None = None,
                 spent_seconds: float = 0.0, max_retries: int = DEFAULT_MAX_RETRIES,
                 rng=None) -> dict | None:
    """``None`` when the turn must fail, else how long to wait and why.

    ``attempt`` counts retries already performed (0 on the first failure). ``remaining_seconds``
    is the turn budget left, ``spent_seconds`` the time already spent waiting for retries.
    """
    if attempt >= max_retries:
        return None
    status = router_status(exc)
    reason = _retry_reason(exc, status)
    if reason is None:
        return None
    delay = _retry_delay(exc, reason, attempt, rng or __import__('random'))
    if spent_seconds + delay > RETRY_BUDGET_SECONDS:
        return None
    if remaining_seconds is not None and remaining_seconds < delay + MIN_RETRY_WINDOW_SECONDS:
        return None
    code, message = classify_failure(exc)
    return {'code': code, 'message': message, 'reason': reason, 'status': status,
            'delay': round(delay, 3), 'attempt': attempt + 1, 'maxRetries': max_retries,
            'retryAfterSeconds': retry_after_seconds(exc)}


def stop_reason(exc: BaseException, attempt: int, remaining_seconds: float | None = None,
                spent_seconds: float = 0.0, max_retries: int = DEFAULT_MAX_RETRIES) -> str | None:
    """Why no further attempt can be made, for the message the user reads.

    ``permanent`` (this failure class never succeeds on a resend), ``attempts`` (the retry
    count ran out), ``budget`` (the per-turn wait budget is spent), ``window`` (too little
    turn time left for a wait plus a usable attempt). ``None`` when a retry is still possible,
    in which case :func:`retry_advice` returns the wait.
    """
    reason = _retry_reason(exc, router_status(exc))
    if reason is None:
        return 'permanent'
    if attempt >= max_retries:
        return 'attempts'
    delay = _retry_delay(exc, reason, attempt, __import__('random'))
    if spent_seconds + delay > RETRY_BUDGET_SECONDS:
        return 'budget'
    if remaining_seconds is not None and remaining_seconds < delay + MIN_RETRY_WINDOW_SECONDS:
        return 'window'
    return None


def is_transient(exc: BaseException) -> bool:
    """True when a retry can plausibly succeed (routers restart, sockets drop, providers throttle).

    Kept as the one-argument view of :func:`retry_advice` so callers that only need a yes/no
    answer cannot drift from the policy that decides the actual wait.
    """
    return retry_advice(exc, 0) is not None


# Providers that refuse the *thinking level* answer 400 with a message that names it. The
# router publishes a level list from what a provider payload says about thinking, which is
# not the same question as "does this model accept `thinkingLevel`": Google's `models.list`
# marks the whole 2.5 family and Gemma as `thinking: true`, yet those models answer
# `400 INVALID_ARGUMENT: Thinking level is not supported for this model.` (Gemini 2.5 sets
# its thinking budget instead, and Gemma has no level at all). Measured against the live
# Google endpoint on 2026-09-20: gemini-2.5-flash, gemini-2.5-flash-lite, gemma-4-31b-it and
# gemini-3.5-transcribe reject the level while gemini-flash-lite-latest, gemini-3.1-flash-lite
# and gemini-3.8-flash accept it.
_LEVEL_REFUSAL = re.compile(r'thinking level is not supported|thinking is not enabled', re.IGNORECASE)
_LEVEL_REFUSAL_STATUS = frozenset({400, 422})


def level_refusal(exc: BaseException) -> bool:
    """True when a provider refused the request *because of* the thinking level.

    The caller drops `thinkingLevel` from the route and calls again: the turn must answer,
    and a level the provider does not accept is a request problem, not a runtime failure.
    Only 4xx statuses count — a 429/5xx that happens to mention the level is not a refusal
    to *this* level.
    """
    status = router_status(exc)
    if status is not None and status not in _LEVEL_REFUSAL_STATUS:
        return False
    _, message = classify_failure(exc)
    return bool(_LEVEL_REFUSAL.search(message))
