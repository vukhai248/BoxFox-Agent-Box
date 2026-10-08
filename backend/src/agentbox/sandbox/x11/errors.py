"""Mã lỗi của tầng desktop — **cùng một bộ từ vựng** với bản Windows.

Không định nghĩa mã mới: chỗ gọi ở tầng trên (``host_executor``, ``machine_router``, ``api/server``)
bắt lỗi theo ``code``, nên hai nền tảng phải nói cùng một thứ tiếng. Từ vựng gốc nằm ở
``sandbox/win/errors.py`` (kế hoạch §4.6 + §8); module này chỉ mở lại đúng những tên mà nền tảng X11
dùng, để ``sandbox/x11`` đọc được như một gói độc lập.
"""
from __future__ import annotations

from ..win.errors import (  # noqa: F401  (mở lại có chủ ý)
    ACTION_CODES,
    CAPTURE_FAILED,
    CONTROL_BUSY,
    DESKTOP_LOCKED,
    ELEMENT_STALE,
    HUMAN_HAS_CONTROL,
    HUMAN_TOOK_OVER,
    INSPECT_REASONS,
    INPUT_SHORT_SEND,
    OS_PERMISSION_REQUIRED,
    PASSWORD_FIELD_REFUSED,
    PlatformError,
    SESSION_NOT_INTERACTIVE,
    SOURCE_CHANGED,
    SOURCE_IDENTITY_UNAVAILABLE,
    UIA_UNAVAILABLE,
    UIPI_BLOCKED,
    UNSUPPORTED_IN_HOST_MODE,
    WINDOW_CLOAKED,
    WINDOW_MINIMIZED,
    refuse,
)

__all__ = [
    "ACTION_CODES",
    "CAPTURE_FAILED",
    "CONTROL_BUSY",
    "DESKTOP_LOCKED",
    "ELEMENT_STALE",
    "HUMAN_HAS_CONTROL",
    "HUMAN_TOOK_OVER",
    "INSPECT_REASONS",
    "INPUT_SHORT_SEND",
    "OS_PERMISSION_REQUIRED",
    "PASSWORD_FIELD_REFUSED",
    "PlatformError",
    "SESSION_NOT_INTERACTIVE",
    "SOURCE_CHANGED",
    "SOURCE_IDENTITY_UNAVAILABLE",
    "UIA_UNAVAILABLE",
    "UIPI_BLOCKED",
    "UNSUPPORTED_IN_HOST_MODE",
    "WINDOW_CLOAKED",
    "WINDOW_MINIMIZED",
    "refuse",
]
