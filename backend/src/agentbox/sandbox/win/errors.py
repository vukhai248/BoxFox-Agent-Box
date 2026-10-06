"""Structured error codes for the Windows desktop platform layer.

The vocabulary is the one already fixed by the plan (``desktop-alpha-packaging.md``
§4.6) and by the machine-environments roadmap (§8), plus the inspect reason codes of
``docs/architecture/element-selector.md`` (11 codes) and the 6 Windows additions of
§4.1. Callers switch on ``code`` — never on the message text — so every refusal this
package raises carries one of the constants below.
"""
from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Action / refusal codes — plan §4.6 + roadmap §8
# ---------------------------------------------------------------------------
ELEMENT_STALE = "ELEMENT_STALE"
SOURCE_CHANGED = "SOURCE_CHANGED"
SOURCE_IDENTITY_UNAVAILABLE = "SOURCE_IDENTITY_UNAVAILABLE"
CONTROL_BUSY = "CONTROL_BUSY"
DESKTOP_LOCKED = "DESKTOP_LOCKED"
OS_PERMISSION_REQUIRED = "OS_PERMISSION_REQUIRED"
HUMAN_HAS_CONTROL = "HUMAN_HAS_CONTROL"
HUMAN_TOOK_OVER = "HUMAN_TOOK_OVER"
UIA_UNAVAILABLE = "UIA_UNAVAILABLE"
UIA_TIMEOUT = "UIA_TIMEOUT"
UIPI_BLOCKED = "UIPI_BLOCKED"
SESSION_NOT_INTERACTIVE = "SESSION_NOT_INTERACTIVE"
APPROVAL_DENIED = "APPROVAL_DENIED"
APPROVAL_DENIAL_BREAKER = "APPROVAL_DENIAL_BREAKER"
UNSUPPORTED_IN_HOST_MODE = "UNSUPPORTED_IN_HOST_MODE"

# ---------------------------------------------------------------------------
# H5 additions. Not in the plan's list, but each refusal the platform layer
# performs needs its own switchable code (the alternative is a generic message,
# which the plan explicitly forbids).
# ---------------------------------------------------------------------------
PASSWORD_FIELD_REFUSED = "PASSWORD_FIELD_REFUSED"
WINDOW_MINIMIZED = "WINDOW_MINIMIZED"
WINDOW_CLOAKED = "WINDOW_CLOAKED"
WINDOW_IDENTITY_UNAVAILABLE = "WINDOW_IDENTITY_UNAVAILABLE"
INPUT_SHORT_SEND = "INPUT_SHORT_SEND"
POST_MESSAGE_UNSUPPORTED = "POST_MESSAGE_UNSUPPORTED"
UIA_PROVIDER_HANG = "UIA_PROVIDER_HANG"
CAPTURE_FAILED = "CAPTURE_FAILED"

ACTION_CODES: tuple[str, ...] = (
    ELEMENT_STALE,
    SOURCE_CHANGED,
    SOURCE_IDENTITY_UNAVAILABLE,
    CONTROL_BUSY,
    DESKTOP_LOCKED,
    OS_PERMISSION_REQUIRED,
    HUMAN_HAS_CONTROL,
    HUMAN_TOOK_OVER,
    UIA_UNAVAILABLE,
    UIA_TIMEOUT,
    UIPI_BLOCKED,
    SESSION_NOT_INTERACTIVE,
    APPROVAL_DENIED,
    APPROVAL_DENIAL_BREAKER,
    UNSUPPORTED_IN_HOST_MODE,
    PASSWORD_FIELD_REFUSED,
    WINDOW_MINIMIZED,
    WINDOW_CLOAKED,
    WINDOW_IDENTITY_UNAVAILABLE,
    INPUT_SHORT_SEND,
    POST_MESSAGE_UNSUPPORTED,
    UIA_PROVIDER_HANG,
    CAPTURE_FAILED,
)

# ---------------------------------------------------------------------------
# Inspect reasons — element-selector.md §3 (11 codes, kept verbatim) + §4.1 (6)
# ---------------------------------------------------------------------------
NOT_CHROMIUM = "not_chromium"
OUTSIDE_VIEWPORT = "outside_viewport"
FRAME_EXTENTS_UNKNOWN = "frame_extents_unknown"
DEVTOOLS_DOCKED = "devtools_docked"
VIEWPORT_ORIGIN_UNKNOWN = "viewport_origin_unknown"
NO_CDP_TARGET = "no_cdp_target"
AMBIGUOUS_TARGET = "ambiguous_target"
CDP_UNREACHABLE = "cdp_unreachable"
CDP_TIMEOUT = "cdp_timeout"
NO_NODE_AT_POINT = "no_node_at_point"
EXTRACT_FAILED = "extract_failed"

UIA_UNAVAILABLE_REASON = "uia_unavailable"
UIA_TIMEOUT_REASON = "uia_timeout"
UIA_PROVIDER_HANG_REASON = "uia_provider_hang"
UIA_NO_ELEMENT = "uia_no_element"
NO_WINDOW_AT_POINT = "no_window_at_point"
WINDOW_IDENTITY_UNAVAILABLE_REASON = "window_identity_unavailable"

#: The 11 codes of the existing box contract, in the documented order.
LEGACY_INSPECT_REASONS: tuple[str, ...] = (
    NOT_CHROMIUM,
    OUTSIDE_VIEWPORT,
    FRAME_EXTENTS_UNKNOWN,
    DEVTOOLS_DOCKED,
    VIEWPORT_ORIGIN_UNKNOWN,
    NO_CDP_TARGET,
    AMBIGUOUS_TARGET,
    CDP_UNREACHABLE,
    CDP_TIMEOUT,
    NO_NODE_AT_POINT,
    EXTRACT_FAILED,
)

#: The 6 Windows additions of plan §4.1.
WINDOWS_INSPECT_REASONS: tuple[str, ...] = (
    UIA_UNAVAILABLE_REASON,
    UIA_TIMEOUT_REASON,
    UIA_PROVIDER_HANG_REASON,
    UIA_NO_ELEMENT,
    NO_WINDOW_AT_POINT,
    WINDOW_IDENTITY_UNAVAILABLE_REASON,
)

#: All 17 reason codes (vocabulary; `not_chromium` is deliberately never emitted,
#: exactly like the box path — a soft degrade is not a failure).
INSPECT_REASONS: tuple[str, ...] = LEGACY_INSPECT_REASONS + WINDOWS_INSPECT_REASONS

#: The reasons that may appear in a `desktop` payload (all but `not_chromium`).
EMITTED_INSPECT_REASONS: tuple[str, ...] = tuple(
    reason for reason in INSPECT_REASONS if reason != NOT_CHROMIUM
)

#: User-facing message per reason — the 10 legacy strings are copied verbatim from
#: `deploy/docker/inspect_element.py` so the drawer shows the same text in both modes.
INSPECT_MESSAGES: dict[str, str] = {
    OUTSIDE_VIEWPORT: (
        "Thanh tra phần tử Chrome thất bại: điểm bấm nằm ngoài vùng nội dung web "
        "(titlebar/tab/toolbar/scrollbar)."
    ),
    FRAME_EXTENTS_UNKNOWN: (
        "Không đọc được viền trang trí cửa sổ nên không thể xác định điểm bấm có rơi "
        "vào trang trí hay không."
    ),
    DEVTOOLS_DOCKED: (
        "DevTools đang được ghim (docked) trong chính cửa sổ này — đóng hoặc tách "
        "DevTools rồi thử lại."
    ),
    VIEWPORT_ORIGIN_UNKNOWN: (
        "Không suy được gốc vùng nội dung web (side panel hoặc giao diện Chromium "
        "bất thường)."
    ),
    NO_CDP_TARGET: "Không tìm được tab Chrome (CDP) khớp với cửa sổ này.",
    AMBIGUOUS_TARGET: (
        "Có nhiều tab khớp cửa sổ này, không xác định được chính xác tab nào."
    ),
    CDP_UNREACHABLE: (
        "Không kết nối được Chrome DevTools Protocol (Chromium desktop có thể đã "
        "tắt hoặc đang khởi động lại)."
    ),
    CDP_TIMEOUT: "Vượt thời gian chờ khi lấy dữ liệu phần tử qua Chrome DevTools Protocol.",
    NO_NODE_AT_POINT: "Không tìm thấy phần tử DOM nào tại điểm bấm này.",
    EXTRACT_FAILED: "Trích xuất dữ liệu phần tử thất bại.",
    UIA_UNAVAILABLE_REASON: (
        "Không truy cập được UI Automation trên máy này (thiếu thành phần UIA hoặc "
        "ứng dụng không cung cấp accessibility)."
    ),
    UIA_TIMEOUT_REASON: (
        "UI Automation không trả lời trong thời gian cho phép — ứng dụng đích có thể "
        "đang bận."
    ),
    UIA_PROVIDER_HANG_REASON: (
        "Nhà cung cấp UI Automation của ứng dụng đích bị treo; đã bỏ dở lần soi để "
        "không treo tiến trình."
    ),
    UIA_NO_ELEMENT: "UI Automation không trả về phần tử nào tại điểm bấm này.",
    NO_WINDOW_AT_POINT: "Không có cửa sổ nào tại điểm bấm này.",
    WINDOW_IDENTITY_UNAVAILABLE_REASON: (
        "Không đọc được danh tính cửa sổ tại điểm bấm (tiêu đề/tiến trình)."
    ),
}


class PlatformError(Exception):
    """Structured refusal raised by the Windows platform layer.

    ``code`` is one of the constants above; ``details`` carries machine-readable
    context (never a secret) so the API layer can render the failure without
    parsing the message.
    """

    def __init__(self, code: str, message: str = "", **details: Any) -> None:
        self.code = code
        self.message = message
        self.details: dict[str, Any] = dict(details)
        super().__init__(f"{code}: {message}" if message else code)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"ok": False, "code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload


def refuse(code: str, message: str = "", **details: Any) -> PlatformError:
    """Build (do not raise) a :class:`PlatformError` — keeps call sites one-liners."""
    return PlatformError(code, message, **details)
