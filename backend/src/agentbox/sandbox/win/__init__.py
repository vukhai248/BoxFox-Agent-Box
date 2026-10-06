"""Tầng nền tảng Windows của BoxFox (H5) — ctypes + UIA, không phụ thuộc nặng.

Bốn module, mỗi module một trách nhiệm:

* :mod:`.windows_platform` — ranh giới ctypes duy nhất (mọi argtypes/restype,
  struct ``INPUT`` x64, callback giữ tham chiếu cấp module) + ``get_platform``/
  ``set_platform`` để tiêm nền tảng giả trong test.
* :mod:`.capture` — chuỗi chụp GDI ba bước, hai chốt chặn (khung đen, bị che),
  mã hoá PNG bằng ``zlib``.
* :mod:`.input` — thang ba bậc (UIA pattern → SendInput → PostMessage không hỗ
  trợ) kèm các chốt từ chối trước khi gửi (UIPI, desktop khoá, Session 0, ô mật
  khẩu) và xử lý "gửi hụt".
* :mod:`.uia` — UI Automation qua comtypes (nạp lười), watchdog mỗi lời gọi và sổ
  đăng ký phần tử có giới hạn.

Toàn bộ gói **import được trên Linux**: không có ``ctypes.WinDLL`` nào chạy lúc
import, ``comtypes`` chỉ được nạp khi thực sự dùng UIA.
"""
from __future__ import annotations

from .errors import PlatformError
from .windows_platform import (
    WindowsPlatform,
    get_platform,
    set_platform,
)

__all__ = [
    "PlatformError",
    "WindowsPlatform",
    "get_platform",
    "set_platform",
]
