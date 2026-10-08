"""Ranh giới ctypes duy nhất của tầng nền tảng Windows (H5).

Mọi lời gọi Win32 của BoxFox nằm ở đây, và **chỉ** ở đây. Phần còn lại của gói
(`capture`, `input`, `uia`) chỉ nói chuyện với một đối tượng nền tảng, nên trên
Linux toàn bộ tầng vẫn import được và kiểm thử được bằng cách tiêm một nền tảng
giả (`set_platform`).

Ba luật cứng, mỗi luật đều đã từng gây lỗi im lặng trong các dự án CUA:

1. **Mọi hàm có argtypes/restype tường minh.** Thiếu ``restype`` thì ctypes cắt
   kết quả về 32 bit: HWND/LPARAM là con trỏ 64 bit, cắt xong vẫn "chạy" nhưng
   gửi input tới sai cửa sổ.
2. **Callback giữ tham chiếu ở cấp module.** Một ``WINFUNCTYPE`` bị thu gom rác
   trong lúc hook còn sống sẽ làm tiến trình crash.
3. **Không nạp DLL lúc import.** ``ctypes.WinDLL`` không tồn tại trên Linux, nên
   các thư viện được nạp lười ở lần dùng đầu tiên.

Struct ``INPUT`` ở đây là bố cục x64 (40 byte) — sai kích thước thì ``SendInput``
trả về 0 và không có sự kiện nào được gửi.
"""
from __future__ import annotations

import ctypes
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

from .errors import CAPTURE_FAILED, PlatformError, UNSUPPORTED_IN_HOST_MODE

IS_WINDOWS = sys.platform == "win32"

# --- hằng số Win32 ---------------------------------------------------------
# DPI (user32.SetProcessDpiAwarenessContext / shcore.SetProcessDpiAwareness)
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
PROCESS_PER_MONITOR_DPI_AWARE = 2

# GetSystemMetrics
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

# GDI
SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0
PW_RENDERFULLCONTENT = 0x00000002
PW_CLIENTONLY = 0x00000001

# DwmGetWindowAttribute
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14

# GetAncestor
GA_PARENT = 1
GA_ROOT = 2
GA_ROOTOWNER = 3

# SendInput
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0

# Token / integrity
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenIntegrityLevel = 25
SECURITY_MANDATORY_UNTRUSTED_RID = 0x0000
SECURITY_MANDATORY_LOW_RID = 0x1000
SECURITY_MANDATORY_MEDIUM_RID = 0x2000
SECURITY_MANDATORY_HIGH_RID = 0x3000
SECURITY_MANDATORY_SYSTEM_RID = 0x4000

# Desktop / window station
DESKTOP_READOBJECTS = 0x0001
DESKTOP_SWITCHDESKTOP = 0x0100
UOI_NAME = 2

# Hooks
WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14

# Cờ trong MSLLHOOKSTRUCT.flags / KBDLLHOOKSTRUCT.flags. Windows đặt cờ INJECTED cho
# MỌI sự kiện sinh bởi SendInput (kể cả của chính ta) và LOWER_IL_INJECTED khi sự kiện
# được tiêm từ tiến trình có integrity thấp hơn. Vì vậy: **cờ tắt ⇒ người thật**.
LLMHF_INJECTED = 0x00000001
LLMHF_LOWER_IL_INJECTED = 0x00000002
LLKHF_EXTENDED = 0x00000001
LLKHF_LOWER_IL_INJECTED = 0x00000002
LLKHF_INJECTED = 0x00000010
LLKHF_ALTDOWN = 0x00000020
LLKHF_UP = 0x00000080
#: Gộp hai cờ "có bàn tay máy" cho từng loại hook.
MOUSE_INJECTED_FLAGS = LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED
KEYBOARD_INJECTED_FLAGS = LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED
#: Dưới ngưỡng này chắc chắn không phải con trỏ hợp lệ (trang NULL của tiến trình).
HOOK_MIN_POINTER = 0x10000

# GetLastInputInfo / GetTickCount64. ``dwTime`` là DWORD 32 bit nên tràn sau ~49,7 ngày;
# mọi phép trừ phải làm theo modulo 2^32 rồi mới tới trần "không đo được".
IDLE_TICK_MODULO = 0x1_0000_0000
#: Nhàn rỗi quá 30 ngày thì không phân biệt được với tràn số ⇒ coi như không đo được.
MAX_IDLE_MS = 30 * 24 * 60 * 60 * 1000

# Mutex liên tiến trình (CreateMutexW / WaitForSingleObject)
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF
#: Tên mutex đã chốt cho khoá input desktop — namespace ``Local\`` là của phiên đăng nhập.
DESKTOP_INPUT_MUTEX_NAME = "Local\\BoxFoxDesktopInput-v1"

# UIA / COM
COINIT_MULTITHREADED = 0x0
RPC_E_CHANGED_MODE = -2147417850  # 0x80010106
S_FALSE = 1
S_OK = 0

#: Tên desktop an toàn — bất kỳ tên khác nghĩa là màn hình đang bị khoá hoặc có
#: secure prompt (UAC), và mọi cú gửi input sẽ rơi vào hư không.
DEFAULT_DESKTOP_NAME = "Default"
#: Window station tương tác của phiên đăng nhập.
INTERACTIVE_WINDOW_STATION = "WinSta0"

# Cửa sổ viền báo vùng đang bị điều khiển (overlay). Một cửa sổ layered, trong suốt với chuột
# (WS_EX_TRANSPARENT ⇒ mọi cú bấm xuyên qua), không hiện trên taskbar/Alt-Tab (TOOLWINDOW +
# NOACTIVATE), và KHÔNG BAO GIỜ cướp tiêu điểm của ứng dụng đang bị điều khiển.
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
WM_PAINT = 0x000F
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_APP = 0x8000
WM_LBUTTONDOWN = 0x0201
GWL_EXSTYLE = -20
SW_SHOWNORMAL = 1
SW_SHOWNA = 8
SW_HIDE = 0
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
LWA_ALPHA = 0x00000002
NULL_BRUSH = 5
PS_DASH = 3
ERROR_INSUFFICIENT_BUFFER = 122
#: Mã `ShellExecuteW` trả về khi thành công là > 32 (giá trị nhỏ là mã lỗi).
SHELL_EXECUTE_MIN_OK = 32


# --- struct -----------------------------------------------------------------
class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_int32),
        ("top", ctypes.c_int32),
        ("right", ctypes.c_int32),
        ("bottom", ctypes.c_int32),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    """Bố cục x64: 40 byte (type 4 + đệm 4 + union 32)."""

    _fields_ = [("type", ctypes.c_uint32), ("union", _INPUTUNION)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32),
        ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32),
        ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16),
        ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32),
        ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32),
        ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.c_uint32 * 3),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
        ("time", ctypes.c_uint32),
        ("pt", POINT),
    ]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", ctypes.c_uint32)]


class TOKEN_MANDATORY_LABEL(ctypes.Structure):
    _fields_ = [("Label", SID_AND_ATTRIBUTES)]


class LASTINPUTINFO(ctypes.Structure):
    """``GetLastInputInfo`` — 8 byte (cbSize 4 + dwTime 4)."""

    _fields_ = [("cbSize", ctypes.c_uint32), ("dwTime", ctypes.c_uint32)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    """Tham số ``lParam`` của WH_MOUSE_LL — bố cục x64: 32 byte."""

    _fields_ = [
        ("pt", POINT),
        ("mouseData", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KBDLLHOOKSTRUCT(ctypes.Structure):
    """Tham số ``lParam`` của WH_KEYBOARD_LL — bố cục x64: 24 byte."""

    _fields_ = [
        ("vkCode", ctypes.c_uint32),
        ("scanCode", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


#: Tham chiếu sống cho mọi callback đã đăng ký với Win32 (luật 2 ở docstring).
_CALLBACK_REFS: list[Any] = []


class WNDCLASSW(ctypes.Structure):
    """``WNDCLASSW`` — bố cục x64 của lớp cửa sổ (dùng cho cửa sổ viền)."""

    _fields_ = [
        ("style", ctypes.c_uint32),
        ("lpfnWndProc", ctypes.c_void_p),
        ("cbClsExtra", ctypes.c_int32),
        ("cbWndExtra", ctypes.c_int32),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
    ]

def make_hook_proc(callback: Callable[[int, int, int], int]) -> Any:
    """Bọc ``callback`` thành WINFUNCTYPE và giữ tham chiếu ở cấp module.

    Hook number là số nguyên; ``WPARAM``/``LPARAM`` khai báo theo kích thước con
    trỏ để không bị cắt trên x64.
    """
    factory = getattr(ctypes, "WINFUNCTYPE", None)
    if factory is None:
        raise PlatformError(
            UNSUPPORTED_IN_HOST_MODE,
            "WINFUNCTYPE không tồn tại trên nền tảng này (không phải Windows).",
        )
    proc = factory(
        ctypes.c_ssize_t, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t
    )(callback)
    _CALLBACK_REFS.append(proc)
    return proc


def make_window_proc(callback: Callable[[int, int, int, int], int]) -> Any:
    """Bọc ``callback`` thành ``WNDPROC`` và giữ tham chiếu ở cấp module (luật 2).

    ``WNDPROC`` là ``LRESULT (HWND, UINT, WPARAM, LPARAM)`` — HWND/WPARAM/LPARAM khai báo theo
    kích thước con trỏ để không bị cắt trên x64.
    """
    factory = getattr(ctypes, "WINFUNCTYPE", None)
    if factory is None:
        raise PlatformError(
            UNSUPPORTED_IN_HOST_MODE,
            "WINFUNCTYPE không tồn tại trên nền tảng này (không phải Windows).",
        )
    proc = factory(
        ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t
    )(callback)
    _CALLBACK_REFS.append(proc)
    return proc


@dataclass(frozen=True)
class WindowInfo:
    """Danh tính + hình học của một cửa sổ, ở toạ độ vật lý (physical pixel)."""

    hwnd: int
    title: str
    class_name: str
    pid: int | None
    rect: tuple[int, int, int, int]
    extended_bounds: tuple[int, int, int, int] | None = None
    cloaked: bool = False
    iconic: bool = False
    process_name: str | None = None

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) — ưu tiên viền DWM thật, tránh vệt đen của bóng đổ."""
        rect = self.extended_bounds or self.rect
        left, top, right, bottom = rect
        return left, top, max(0, right - left), max(0, bottom - top)


class WindowsPlatform:
    """Hiện thực thật: nạp DLL/comtypes lười, ở lần dùng đầu tiên."""

    name = "windows"
    #: False ở :class:`UnavailablePlatform` — xem :meth:`_require_available`.
    available = True

    def __init__(self) -> None:
        self._libs: dict[str, Any] = {}
        self._dpi_mode: str | None = None
        self._dpi_attempted = False
        self._integrity_cache: dict[int, int | None] = {}
        self._process_name_cache: dict[int, str | None] = {}
        self._hook: int | None = None
        self._mouse_hook: int | None = None
        self._uia_accessor: Any = None
        self._notes: list[str] = []

    # -- nạp lười ----------------------------------------------------------
    def _load(self, lib_name: str, funcs: dict[str, tuple[list[Any], Any]]) -> Any:
        lib = self._libs.get(lib_name)
        if lib is None:
            win_dll = getattr(ctypes, "WinDLL", None)
            if win_dll is None:
                raise PlatformError(
                    UNSUPPORTED_IN_HOST_MODE,
                    f"ctypes.WinDLL không có trên nền tảng này (cần Windows cho {lib_name}).",
                )
            lib = win_dll(lib_name, use_last_error=True)
            self._libs[lib_name] = lib
        for func_name, (argtypes, restype) in funcs.items():
            func = getattr(lib, func_name, None)
            if func is None:
                continue
            func.argtypes = argtypes
            func.restype = restype
        return lib

    def _require_available(self) -> None:
        """Chốt cho các hàm KHÔNG đi qua DLL: thuần Python, hoặc no-op khi chưa cài hook.

        ``_load`` đã từ chối sẵn mọi hàm chạm DLL, nhưng ``hook_event`` (chỉ đọc
        struct) và ``unhook_mouse`` (no-op khi chưa có hook) sẽ lặng lẽ "thành công"
        ngoài Windows nếu không có chốt này.
        """
        if not self.available:
            raise PlatformError(
                UNSUPPORTED_IN_HOST_MODE,
                "Tầng nền tảng Windows chỉ chạy trên Windows.",
                platform=sys.platform,
            )

    @property
    def user32(self) -> Any:
        return self._load(
            "user32",
            {
                "GetDC": ([ctypes.c_void_p], ctypes.c_void_p),
                "GetWindowDC": ([ctypes.c_void_p], ctypes.c_void_p),
                "ReleaseDC": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
                "PrintWindow": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint], ctypes.c_int),
                "GetSystemMetrics": ([ctypes.c_int], ctypes.c_int),
                "GetWindowRect": ([ctypes.c_void_p, ctypes.POINTER(RECT)], ctypes.c_int),
                "GetClientRect": ([ctypes.c_void_p, ctypes.POINTER(RECT)], ctypes.c_int),
                "ClientToScreen": ([ctypes.c_void_p, ctypes.POINTER(POINT)], ctypes.c_int),
                "ScreenToClient": ([ctypes.c_void_p, ctypes.POINTER(POINT)], ctypes.c_int),
                "IsWindow": ([ctypes.c_void_p], ctypes.c_int),
                "IsWindowVisible": ([ctypes.c_void_p], ctypes.c_int),
                "IsIconic": ([ctypes.c_void_p], ctypes.c_int),
                "IsZoomed": ([ctypes.c_void_p], ctypes.c_int),
                "GetAncestor": ([ctypes.c_void_p, ctypes.c_uint], ctypes.c_void_p),
                "GetForegroundWindow": ([], ctypes.c_void_p),
                "SetForegroundWindow": ([ctypes.c_void_p], ctypes.c_int),
                "BringWindowToTop": ([ctypes.c_void_p], ctypes.c_int),
                "ShowWindow": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
                "SetWindowPos": (
                    [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint],
                    ctypes.c_int,
                ),
                "WindowFromPoint": ([POINT], ctypes.c_void_p),
                "ChildWindowFromPointEx": (
                    [ctypes.c_void_p, POINT, ctypes.c_uint],
                    ctypes.c_void_p,
                ),
                "GetWindowTextW": ([ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
                "GetWindowTextLengthW": ([ctypes.c_void_p], ctypes.c_int),
                "GetClassNameW": ([ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int], ctypes.c_int),
                "GetWindowThreadProcessId": (
                    [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)],
                    ctypes.c_uint32,
                ),
                "EnumWindows": ([ctypes.c_void_p, ctypes.c_ssize_t], ctypes.c_int),
                "GetCursorPos": ([ctypes.POINTER(POINT)], ctypes.c_int),
                "GetLastInputInfo": ([ctypes.POINTER(LASTINPUTINFO)], ctypes.c_int),
                "SetCursorPos": ([ctypes.c_int, ctypes.c_int], ctypes.c_int),
                "GetDpiForWindow": ([ctypes.c_void_p], ctypes.c_uint),
                "SetProcessDPIAware": ([], ctypes.c_int),
                "SetProcessDpiAwarenessContext": ([ctypes.c_void_p], ctypes.c_int),
                "GetThreadDpiAwarenessContext": ([], ctypes.c_void_p),
                "SetThreadDpiAwarenessContext": ([ctypes.c_void_p], ctypes.c_void_p),
                "OpenInputDesktop": (
                    [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32],
                    ctypes.c_void_p,
                ),
                "CloseDesktop": ([ctypes.c_void_p], ctypes.c_int),
                "GetUserObjectInformationW": (
                    [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)],
                    ctypes.c_int,
                ),
                "GetProcessWindowStation": ([], ctypes.c_void_p),
                "MapVirtualKeyW": ([ctypes.c_uint, ctypes.c_uint], ctypes.c_uint),
                "SendInput": ([ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int], ctypes.c_uint),
                "SetWindowsHookExW": (
                    [ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32],
                    ctypes.c_void_p,
                ),
                "UnhookWindowsHookEx": ([ctypes.c_void_p], ctypes.c_int),
                "CallNextHookEx": (
                    [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t],
                    ctypes.c_ssize_t,
                ),
                "GetMessageW": (
                    [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint],
                    ctypes.c_int,
                ),
                "PostThreadMessageW": (
                    [ctypes.c_uint32, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t],
                    ctypes.c_int,
                ),
                "PostQuitMessage": ([ctypes.c_int], None),
                "GetClassLongPtrW": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_void_p),
                "MessageBoxW": ([ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint], ctypes.c_int),
                # Cửa sổ viền overlay (F). Mọi hàm ở đây phải có argtypes/restype tường minh:
                # thiếu restype ⇒ HWND 64 bit bị cắt và cửa sổ viền "tạo được" nhưng không điều
                # khiển được nữa.
                "RegisterClassW": ([ctypes.POINTER(WNDCLASSW)], ctypes.c_uint16),
                "CreateWindowExW": (
                    [ctypes.c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32,
                     ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
                    ctypes.c_void_p,
                ),
                "DefWindowProcW": (
                    [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t],
                    ctypes.c_ssize_t,
                ),
                "DestroyWindow": ([ctypes.c_void_p], ctypes.c_int),
                "PostMessageW": (
                    [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_size_t, ctypes.c_ssize_t],
                    ctypes.c_int,
                ),
                "PostQuitMessage": ([ctypes.c_int], None),
                "DispatchMessageW": ([ctypes.POINTER(MSG)], ctypes.c_ssize_t),
                "TranslateMessage": ([ctypes.POINTER(MSG)], ctypes.c_int),
                "BeginPaint": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p),
                "EndPaint": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_int),
                "InvalidateRect": ([ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
                "UpdateWindow": ([ctypes.c_void_p], ctypes.c_int),
                "SetLayeredWindowAttributes": (
                    [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint8, ctypes.c_uint32],
                    ctypes.c_int,
                ),
                "LoadCursorW": ([ctypes.c_void_p, ctypes.c_wchar_p], ctypes.c_void_p),
            },
        )

    @property
    def gdi32(self) -> Any:
        return self._load(
            "gdi32",
            {
                "CreateCompatibleDC": ([ctypes.c_void_p], ctypes.c_void_p),
                "CreateCompatibleBitmap": (
                    [ctypes.c_void_p, ctypes.c_int, ctypes.c_int],
                    ctypes.c_void_p,
                ),
                "SelectObject": ([ctypes.c_void_p, ctypes.c_void_p], ctypes.c_void_p),
                "BitBlt": (
                    [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_uint32],
                    ctypes.c_int,
                ),
                "GetDIBits": (
                    [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), ctypes.c_uint],
                    ctypes.c_int,
                ),
                "DeleteDC": ([ctypes.c_void_p], ctypes.c_int),
                "DeleteObject": ([ctypes.c_void_p], ctypes.c_int),
                "GetDeviceCaps": ([ctypes.c_void_p, ctypes.c_int], ctypes.c_int),
                # Vẽ viền overlay: pen đứt nét, tô bằng NULL_BRUSH để chỉ thấy đường viền.
                "CreatePen": ([ctypes.c_int, ctypes.c_int, ctypes.c_uint32], ctypes.c_void_p),
                "GetStockObject": ([ctypes.c_int], ctypes.c_void_p),
                "Rectangle": (
                    [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int],
                    ctypes.c_int,
                ),
            },
        )

    @property
    def dwmapi(self) -> Any:
        return self._load(
            "dwmapi",
            {
                "DwmGetWindowAttribute": (
                    [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32],
                    ctypes.c_int32,
                ),
                "DwmIsCompositionEnabled": ([ctypes.POINTER(ctypes.c_int)], ctypes.c_int32),
            },
        )

    @property
    def shell32(self) -> Any:
        return self._load("shell32", {})

    @property
    def ole32(self) -> Any:
        return self._load(
            "ole32",
            {
                "CoInitializeEx": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_int32),
                "CoUninitialize": ([], None),
                "CoCreateInstance": (
                    [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p],
                    ctypes.c_int32,
                ),
            },
        )

    @property
    def kernel32(self) -> Any:
        return self._load(
            "kernel32",
            {
                "GetCurrentProcessId": ([], ctypes.c_uint32),
                "GetCurrentProcess": ([], ctypes.c_void_p),
                "OpenProcess": ([ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32], ctypes.c_void_p),
                "CloseHandle": ([ctypes.c_void_p], ctypes.c_int),
                "OpenProcessToken": ([ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)], ctypes.c_int),
                "GetTokenInformation": (
                    [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)],
                    ctypes.c_int,
                ),
                "QueryFullProcessImageNameW": (
                    [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)],
                    ctypes.c_int,
                ),
                "ProcessIdToSessionId": ([ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)], ctypes.c_int),
                "WTSGetActiveConsoleSessionId": ([], ctypes.c_uint32),
                "GetModuleHandleW": ([ctypes.c_wchar_p], ctypes.c_void_p),
                "GetLastError": ([], ctypes.c_uint32),
                "GetTickCount64": ([], ctypes.c_uint64),
                "CreateMutexW": (
                    [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p],
                    ctypes.c_void_p,
                ),
                "GetApplicationUserModelId": (
                    [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.c_wchar_p],
                    ctypes.c_int32,
                ),
                "WaitForSingleObject": ([ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint32),
                "ReleaseMutex": ([ctypes.c_void_p], ctypes.c_int),
            },
        )

    # -- DPI ---------------------------------------------------------------
    def set_process_dpi_awareness_context(self, context: int) -> bool:
        """``SetProcessDpiAwarenessContext`` — chỉ có từ Win10 1703."""
        func = getattr(self.user32, "SetProcessDpiAwarenessContext", None)
        if func is None:
            return False
        return bool(func(ctypes.c_void_p(context)))

    def set_process_dpi_awareness_shcore(self, awareness: int) -> bool:
        """``shcore.SetProcessDpiAwareness`` — dự phòng khi user32 thiếu API."""
        try:
            shcore = self._load("shcore", {"SetProcessDpiAwareness": ([ctypes.c_int], ctypes.c_int32)})
        except (OSError, PlatformError):
            return False
        return shcore.SetProcessDpiAwareness(awareness) in (S_OK, S_FALSE)

    def dpi_awareness_notes(self) -> list[str]:
        return list(self._notes)

    def note(self, message: str) -> None:
        """Ghi chú chẩn đoán (dùng cho metadata của capture, không phải lỗi)."""
        self._notes.append(message)

    # -- phiên / desktop ---------------------------------------------------
    def _user_object_name(self, handle: int) -> str | None:
        if not handle:
            return None
        buf = ctypes.create_unicode_buffer(256)
        needed = ctypes.c_uint32(0)
        ok = self.user32.GetUserObjectInformationW(
            ctypes.c_void_p(handle), UOI_NAME, buf, ctypes.sizeof(buf), ctypes.byref(needed)
        )
        return buf.value if ok else None

    def input_desktop_name(self) -> str | None:
        """Tên desktop đang nhận input; ``None`` khi không mở được."""
        handle = self.user32.OpenInputDesktop(
            0, False, DESKTOP_READOBJECTS | DESKTOP_SWITCHDESKTOP
        )
        if not handle:
            return None
        try:
            return self._user_object_name(handle)
        finally:
            self.user32.CloseDesktop(ctypes.c_void_p(handle))

    def window_station_name(self) -> str | None:
        return self._user_object_name(self.user32.GetProcessWindowStation())

    def process_session_id(self) -> int | None:
        sid = ctypes.c_uint32(0)
        ok = self.kernel32.ProcessIdToSessionId(self.kernel32.GetCurrentProcessId(), ctypes.byref(sid))
        return int(sid.value) if ok else None

    def active_console_session_id(self) -> int | None:
        value = int(self.kernel32.WTSGetActiveConsoleSessionId())
        return None if value == 0xFFFFFFFF else value

    def is_interactive_session(self) -> bool:
        """Session 0 (dịch vụ) không có desktop tương tác ⇒ input luôn thất bại."""
        session = self.process_session_id()
        if session is None or session == 0:
            return False
        station = self.window_station_name()
        if station is not None and station != INTERACTIVE_WINDOW_STATION:
            return False
        return self.input_desktop_name() is not None

    def desktop_locked(self) -> bool:
        name = self.input_desktop_name()
        if name is None:
            return True
        return name != DEFAULT_DESKTOP_NAME

    # -- truy vấn cửa sổ ---------------------------------------------------
    def is_window(self, hwnd: int) -> bool:
        return bool(hwnd) and bool(self.user32.IsWindow(ctypes.c_void_p(hwnd)))

    def is_window_visible(self, hwnd: int) -> bool:
        return bool(self.user32.IsWindowVisible(ctypes.c_void_p(hwnd)))

    def is_iconic(self, hwnd: int) -> bool:
        return bool(self.user32.IsIconic(ctypes.c_void_p(hwnd)))

    def get_ancestor_root(self, hwnd: int) -> int | None:
        root = self.user32.GetAncestor(ctypes.c_void_p(hwnd), GA_ROOT)
        return int(root) if root else None

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        rect = RECT()
        if not self.user32.GetWindowRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            return None
        return rect.left, rect.top, rect.right, rect.bottom

    def get_client_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        rect = RECT()
        if not self.user32.GetClientRect(ctypes.c_void_p(hwnd), ctypes.byref(rect)):
            return None
        return rect.left, rect.top, rect.right, rect.bottom

    def client_to_screen(self, hwnd: int, x: int, y: int) -> tuple[int, int] | None:
        point = POINT(x, y)
        if not self.user32.ClientToScreen(ctypes.c_void_p(hwnd), ctypes.byref(point)):
            return None
        return point.x, point.y

    def screen_to_client(self, hwnd: int, x: int, y: int) -> tuple[int, int] | None:
        point = POINT(x, y)
        if not self.user32.ScreenToClient(ctypes.c_void_p(hwnd), ctypes.byref(point)):
            return None
        return point.x, point.y

    def get_window_text(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(ctypes.c_void_p(hwnd))
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(ctypes.c_void_p(hwnd), buf, length + 1)
        return buf.value

    def get_class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(256)
        self.user32.GetClassNameW(ctypes.c_void_p(hwnd), buf, 256)
        return buf.value

    def get_window_pid(self, hwnd: int) -> int | None:
        pid = ctypes.c_uint32(0)
        self.user32.GetWindowThreadProcessId(ctypes.c_void_p(hwnd), ctypes.byref(pid))
        return int(pid.value) or None

    def window_from_point(self, x: int, y: int) -> int | None:
        hwnd = self.user32.WindowFromPoint(POINT(int(x), int(y)))
        return int(hwnd) if hwnd else None

    def child_window_from_point(self, hwnd: int, x: int, y: int, flags: int = 0) -> int | None:
        child = self.user32.ChildWindowFromPointEx(ctypes.c_void_p(hwnd), POINT(int(x), int(y)), flags)
        return int(child) if child else None

    def enum_windows(self) -> list[int]:
        """HWND theo thứ tự Z-order từ trên xuống (EnumWindows duyệt từ trên cùng)."""
        handles: list[int] = []

        def _callback(hwnd: int, _lparam: int) -> int:
            handles.append(int(hwnd))
            return 1

        proc = self._enum_proc(_callback)
        self.user32.EnumWindows(proc, 0)
        return handles

    def _enum_proc(self, callback: Callable[[int, int], int]) -> Any:
        factory = getattr(ctypes, "WINFUNCTYPE", None)
        if factory is None:
            raise PlatformError(UNSUPPORTED_IN_HOST_MODE, "WINFUNCTYPE không tồn tại trên nền tảng này.")
        proc = factory(ctypes.c_int, ctypes.c_void_p, ctypes.c_ssize_t)(callback)
        _CALLBACK_REFS.append(proc)
        return proc

    def get_foreground_window(self) -> int | None:
        hwnd = self.user32.GetForegroundWindow()
        return int(hwnd) if hwnd else None

    def set_foreground_window(self, hwnd: int) -> bool:
        return bool(self.user32.SetForegroundWindow(ctypes.c_void_p(hwnd)))

    def show_window(self, hwnd: int, command: int) -> bool:
        return bool(self.user32.ShowWindow(ctypes.c_void_p(hwnd), command))

    def get_cursor_pos(self) -> tuple[int, int] | None:
        point = POINT()
        if not self.user32.GetCursorPos(ctypes.byref(point)):
            return None
        return point.x, point.y

    def set_cursor_pos(self, x: int, y: int) -> bool:
        return bool(self.user32.SetCursorPos(int(x), int(y)))

    def get_system_metrics(self, index: int) -> int:
        return int(self.user32.GetSystemMetrics(index))

    def virtual_screen_bounds(self) -> tuple[int, int, int, int]:
        """(x, y, w, h) của toàn bộ desktop ảo — gốc có thể **âm**."""
        return (
            self.get_system_metrics(SM_XVIRTUALSCREEN),
            self.get_system_metrics(SM_YVIRTUALSCREEN),
            self.get_system_metrics(SM_CXVIRTUALSCREEN),
            self.get_system_metrics(SM_CYVIRTUALSCREEN),
        )

    def get_dpi_for_window(self, hwnd: int) -> int | None:
        func = getattr(self.user32, "GetDpiForWindow", None)
        if func is None:
            return None
        value = int(func(ctypes.c_void_p(hwnd)))
        return value or None

    # -- DWM ---------------------------------------------------------------
    def dwm_get_window_attribute(self, hwnd: int, attribute: int, size: int) -> Any:
        """Trả về buffer đã ghi, hoặc ``None`` khi DWM không sẵn sàng."""
        try:
            dwm = self.dwmapi
        except (OSError, PlatformError):
            return None
        buf = ctypes.create_string_buffer(size)
        result = dwm.DwmGetWindowAttribute(
            ctypes.c_void_p(hwnd), ctypes.c_uint32(attribute), buf, ctypes.c_uint32(size)
        )
        if result != S_OK:
            return None
        return buf

    def get_extended_frame_bounds(self, hwnd: int) -> tuple[int, int, int, int] | None:
        buf = self.dwm_get_window_attribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.sizeof(RECT))
        if buf is None:
            return None
        rect = ctypes.cast(buf, ctypes.POINTER(RECT)).contents
        return rect.left, rect.top, rect.right, rect.bottom

    def is_cloaked(self, hwnd: int) -> bool:
        """Cửa sổ UWP bị "cloaked" (vd: đang ở tab khác của Task View) vẫn vẽ ra đen."""
        buf = self.dwm_get_window_attribute(hwnd, DWMWA_CLOAKED, ctypes.sizeof(ctypes.c_int))
        if buf is None:
            return False
        return ctypes.cast(buf, ctypes.POINTER(ctypes.c_int)).contents.value != 0

    # -- tiến trình --------------------------------------------------------
    def process_image_name(self, pid: int) -> str | None:
        if pid in self._process_name_cache:
            return self._process_name_cache[pid]
        name: str | None = None
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            try:
                size = ctypes.c_uint32(1024)
                buf = ctypes.create_unicode_buffer(1024)
                if self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                    name = buf.value or None
            finally:
                self.kernel32.CloseHandle(handle)
        self._process_name_cache[pid] = name
        return name

    def process_integrity_level(self, pid: int) -> int | None:
        """RID toàn vẹn (0x2000 = medium). ``None`` khi không đọc được."""
        if pid in self._integrity_cache:
            return self._integrity_cache[pid]
        level: int | None = None
        for access in (PROCESS_QUERY_LIMITED_INFORMATION, PROCESS_QUERY_INFORMATION):
            handle = self.kernel32.OpenProcess(access, False, pid)
            if not handle:
                continue
            try:
                level = self._integrity_from_process(handle)
            finally:
                self.kernel32.CloseHandle(handle)
            if level is not None:
                break
        self._integrity_cache[pid] = level
        return level

    def _integrity_from_process(self, process_handle: int) -> int | None:
        token = ctypes.c_void_p()
        if not self.kernel32.OpenProcessToken(process_handle, TOKEN_QUERY, ctypes.byref(token)):
            return None
        try:
            return self._integrity_from_token(token)
        finally:
            self.kernel32.CloseHandle(token)

    def _integrity_from_token(self, token: Any) -> int | None:
        needed = ctypes.c_uint32(0)
        self.kernel32.GetTokenInformation(
            token, TokenIntegrityLevel, None, 0, ctypes.byref(needed)
        )
        if not needed.value:
            return None
        buf = ctypes.create_string_buffer(needed.value)
        if not self.kernel32.GetTokenInformation(
            token, TokenIntegrityLevel, buf, needed.value, ctypes.byref(needed)
        ):
            return None
        label = ctypes.cast(buf, ctypes.POINTER(TOKEN_MANDATORY_LABEL)).contents
        sid = label.Label.Sid
        if not sid:
            return None
        # SID: Revision(1) Count(1) Authority(6) SubAuthority[Count](4) — RID là
        # sub-authority cuối cùng.
        count = ctypes.cast(sid, ctypes.POINTER(ctypes.c_ubyte))[1]
        if count < 1:
            return None
        base = ctypes.cast(sid, ctypes.c_void_p).value or 0
        rid = ctypes.cast(base + 8 + (int(count) - 1) * 4, ctypes.POINTER(ctypes.c_uint32)).contents
        return int(rid.value)

    def own_integrity_level(self) -> int | None:
        return self.process_integrity_level(int(self.kernel32.GetCurrentProcessId()))

    # -- GDI ---------------------------------------------------------------
    def get_dc(self, hwnd: int | None = None) -> int | None:
        dc = self.user32.GetDC(ctypes.c_void_p(hwnd) if hwnd else None)
        return int(dc) if dc else None

    def get_window_dc(self, hwnd: int) -> int | None:
        dc = self.user32.GetWindowDC(ctypes.c_void_p(hwnd))
        return int(dc) if dc else None

    def release_dc(self, hwnd: int | None, dc: int) -> bool:
        return bool(self.user32.ReleaseDC(ctypes.c_void_p(hwnd) if hwnd else None, ctypes.c_void_p(dc)))

    def create_compatible_dc(self, dc: int) -> int | None:
        handle = self.gdi32.CreateCompatibleDC(ctypes.c_void_p(dc))
        return int(handle) if handle else None

    def create_compatible_bitmap(self, dc: int, width: int, height: int) -> int | None:
        if width <= 0 or height <= 0:
            return None
        handle = self.gdi32.CreateCompatibleBitmap(ctypes.c_void_p(dc), int(width), int(height))
        return int(handle) if handle else None

    def select_object(self, dc: int, obj: int) -> int | None:
        previous = self.gdi32.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(obj))
        return int(previous) if previous else None

    def delete_dc(self, dc: int) -> bool:
        return bool(self.gdi32.DeleteDC(ctypes.c_void_p(dc)))

    def delete_object(self, obj: int) -> bool:
        return bool(self.gdi32.DeleteObject(ctypes.c_void_p(obj)))

    def bit_blt(
        self,
        dst_dc: int,
        x: int,
        y: int,
        width: int,
        height: int,
        src_dc: int,
        src_x: int,
        src_y: int,
        rop: int = SRCCOPY,
    ) -> bool:
        return bool(
            self.gdi32.BitBlt(
                ctypes.c_void_p(dst_dc),
                int(x),
                int(y),
                int(width),
                int(height),
                ctypes.c_void_p(src_dc),
                int(src_x),
                int(src_y),
                ctypes.c_uint32(rop),
            )
        )

    def print_window(self, hwnd: int, dc: int, flags: int) -> bool:
        return bool(self.user32.PrintWindow(ctypes.c_void_p(hwnd), ctypes.c_void_p(dc), ctypes.c_uint(flags)))

    def read_bitmap_bgra(self, dc: int, bitmap: int, width: int, height: int) -> bytes | None:
        """Đọc bitmap thành BGRA top-down (``biHeight`` âm ⇒ hàng 0 ở trên)."""
        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = int(width)
        info.bmiHeader.biHeight = -int(height)
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB
        info.bmiHeader.biSizeImage = int(width) * int(height) * 4
        buffer = ctypes.create_string_buffer(info.bmiHeader.biSizeImage)
        lines = self.gdi32.GetDIBits(
            ctypes.c_void_p(dc),
            ctypes.c_void_p(bitmap),
            0,
            int(height),
            buffer,
            ctypes.byref(info),
            DIB_RGB_COLORS,
        )
        if lines != int(height):
            return None
        return buffer.raw

    # -- input -------------------------------------------------------------
    def send_input(self, events: list[INPUT]) -> int:
        """Trả về số sự kiện Windows **thực sự** chèn (có thể < len(events))."""
        if not events:
            return 0
        array = (INPUT * len(events))(*events)
        return int(self.user32.SendInput(len(events), array, ctypes.sizeof(INPUT)))

    def map_virtual_key(self, vk: int, map_type: int = MAPVK_VK_TO_VSC) -> int:
        return int(self.user32.MapVirtualKeyW(int(vk), int(map_type)))

    def get_last_error(self) -> int:
        return int(self.kernel32.GetLastError())

    # -- hook input (bàn phím + chuột) -------------------------------------
    def set_keyboard_hook(self, callback: Callable[[int, int, int], int]) -> int | None:
        proc = make_hook_proc(callback)
        module = self.kernel32.GetModuleHandleW(None)
        hook = self.user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, module, 0)
        if not hook:
            return None
        self._hook = int(hook)
        return self._hook

    def unhook_keyboard(self) -> None:
        if self._hook:
            self.user32.UnhookWindowsHookEx(ctypes.c_void_p(self._hook))
            self._hook = None

    def set_mouse_hook(self, callback: Callable[[int, int, int], int]) -> int | None:
        """``WH_MOUSE_LL`` — giống :meth:`set_keyboard_hook`, hook riêng cho chuột."""
        proc = make_hook_proc(callback)
        module = self.kernel32.GetModuleHandleW(None)
        hook = self.user32.SetWindowsHookExW(WH_MOUSE_LL, proc, module, 0)
        if not hook:
            return None
        self._mouse_hook = int(hook)
        return self._mouse_hook

    def unhook_mouse(self) -> None:
        self._require_available()
        if self._mouse_hook:
            self.user32.UnhookWindowsHookEx(ctypes.c_void_p(self._mouse_hook))
            self._mouse_hook = None

    def hook_event(self, kind: str, wparam: int, lparam: int) -> dict:
        """Đọc ``lParam`` của hook thành dict thuần — KHÔNG bao giờ ném ra ngoài.

        Hàm này chạy bên trong callback của hook hệ thống, nơi một exception sẽ bị
        Windows coi là lỗi nghiêm trọng, nên mọi trường hợp lạ (con trỏ rỗng/con trỏ
        cụt, ``kind`` lạ) đều trả ``{}``.

        ``injected`` gộp cả cờ INJECTED lẫn LOWER_IL_INJECTED: sự kiện do ta gửi
        bằng ``SendInput`` luôn mang cờ, nên **cờ tắt nghĩa là người thật**.
        """
        self._require_available()
        if not isinstance(kind, str):
            return {}
        message = int(wparam or 0)
        pointer = int(lparam or 0)
        if pointer < HOOK_MIN_POINTER:
            return {}
        try:
            if kind == "mouse":
                data = ctypes.cast(
                    ctypes.c_void_p(pointer), ctypes.POINTER(MSLLHOOKSTRUCT)
                ).contents
                flags = int(data.flags)
                return {
                    "injected": bool(flags & MOUSE_INJECTED_FLAGS),
                    "vkey": None,
                    "scanCode": None,
                    "flags": flags,
                    "point": (int(data.pt.x), int(data.pt.y)),
                    "message": message,
                }
            if kind == "keyboard":
                data = ctypes.cast(
                    ctypes.c_void_p(pointer), ctypes.POINTER(KBDLLHOOKSTRUCT)
                ).contents
                flags = int(data.flags)
                return {
                    "injected": bool(flags & KEYBOARD_INJECTED_FLAGS),
                    "vkey": int(data.vkCode),
                    "scanCode": int(data.scanCode),
                    "flags": flags,
                    "point": None,
                    "message": message,
                }
        except (ValueError, OSError, ctypes.ArgumentError):
            return {}
        return {}

    # -- thời gian nhàn rỗi ------------------------------------------------
    def last_input_tick(self) -> int:
        """Tick của sự kiện input cuối cùng trong phiên; 0 = không đọc được."""
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not self.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0
        return int(info.dwTime)

    def tick_count(self) -> int:
        """``GetTickCount64`` — đồng hồ đơn điệu mili-giây từ lúc khởi động."""
        return int(self.kernel32.GetTickCount64())

    def idle_seconds(self, now_tick: int | None = None) -> float | None:
        """Số giây kể từ input cuối; ``None`` khi không đo được.

        ``now_tick`` là mốc "bây giờ" theo cùng đồng hồ (``0``/``None`` ⇒ đọc đồng hồ
        thật). Phép trừ làm theo modulo 2^32 vì ``dwTime`` là DWORD 32 bit, nên tràn
        sau ~49,7 ngày vẫn ra số dương đúng; quá :data:`MAX_IDLE_MS` thì trả ``None``
        thay vì một con số vô lý.
        """
        last = self.last_input_tick()
        if last <= 0:
            return None
        now = int(now_tick) if now_tick else self.tick_count()
        if now <= 0:
            return None
        delta = (now - last) % IDLE_TICK_MODULO
        if delta > MAX_IDLE_MS:
            return None
        return delta / 1000.0

    # -- mutex liên tiến trình ---------------------------------------------
    def create_mutex(self, name: str) -> int | None:
        """``CreateMutexW`` — handle hoặc ``None``; tên nên là
        :data:`DESKTOP_INPUT_MUTEX_NAME`."""
        handle = self.kernel32.CreateMutexW(None, False, str(name))
        return int(handle) if handle else None

    def acquire_mutex(self, handle: int, timeout_ms: int = 0) -> bool:
        """``WaitForSingleObject`` — ``WAIT_OBJECT_0``/``WAIT_ABANDONED`` ⇒ giữ được."""
        if not handle:
            return False
        result = int(self.kernel32.WaitForSingleObject(int(handle), int(timeout_ms)))
        return result in (WAIT_OBJECT_0, WAIT_ABANDONED)

    def release_mutex(self, handle: int) -> bool:
        if not handle:
            return False
        return bool(self.kernel32.ReleaseMutex(int(handle)))

    def close_handle(self, handle: int) -> bool:
        if not handle:
            return False
        return bool(self.kernel32.CloseHandle(int(handle)))

    def call_next_hook(
        self, code: int, wparam: int, lparam: int, *, hook: int | None = None
    ) -> int:
        """``CallNextHookEx`` — ``hook`` mặc định là hook đang cài (bàn phím, rồi chuột)."""
        if hook is None:
            handle = self._hook or self._mouse_hook
        else:
            handle = int(hook)
        return int(
            self.user32.CallNextHookEx(
                ctypes.c_void_p(handle) if handle else None,
                int(code),
                ctypes.c_size_t(wparam),
                ctypes.c_ssize_t(lparam),
            )
        )

    def pump_messages(self, on_message: Callable[[MSG], bool]) -> None:
        """Vòng lặp message tối thiểu cho thread đang cài hook."""
        msg = MSG()
        while self.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if not on_message(msg):
                break

    def post_quit_message(self, exit_code: int = 0) -> None:
        self.user32.PostQuitMessage(int(exit_code))

    # -- UIA ---------------------------------------------------------------
    def uia_accessor(self) -> Any:
        """Accessor UIA mặc định (comtypes, nạp lười — không import khi thiếu)."""
        if self._uia_accessor is None:
            from .uia import ComUiaAccessor

            self._uia_accessor = ComUiaAccessor(self)
        return self._uia_accessor

    # -- khởi chạy ứng dụng + danh tính app (CUA theo app) ------------------
    def launch_app(self, app: str) -> int:
        """Mở một ứng dụng bằng ``ShellExecuteW``. Ném ``LAUNCH_FAILED`` khi Windows từ chối.

        Chỉ nhận TÊN tệp/ứng dụng đơn giản (`notepad`, `notepad.exe`, `chrome`): đường dẫn và tham
        số là đường tiêm lệnh, và `HostExecutor._launchable_app` đã chặn chúng trước khi tới đây.
        Trả về mã ``HINSTANCE`` > 32 (mọi giá trị nhỏ hơn là mã lỗi của ShellExecute).
        """
        self._require_available()
        name = str(app or "").strip()
        if not name:
            raise PlatformError(LAUNCH_FAILED, "Thiếu tên ứng dụng.", app=app)
        func = getattr(self.shell32, "ShellExecuteW", None)
        if func is None:
            raise PlatformError(LAUNCH_FAILED, "ShellExecuteW không khả dụng.", app=name)
        func.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_wchar_p,
                         ctypes.c_wchar_p, ctypes.c_int]
        func.restype = ctypes.c_void_p
        result = func(None, "open", name, None, None, SW_SHOWNORMAL)
        value = int(result or 0)
        if value <= SHELL_EXECUTE_MIN_OK:
            raise PlatformError(LAUNCH_FAILED, f"ShellExecuteW trả mã {value}.", app=name, code=value)
        self.note(f"launch_app:{name}")
        return value

    def process_aumid(self, pid: int) -> str | None:
        """AppUserModelID của tiến trình (Win8+), hoặc ``None``.

        App cổ điển (Notepad cũ, app tự viết) không có AUMID — ``None`` là câu trả lời hợp lệ, và
        khoá quyền khi đó rơi về ``processName``.
        """
        if not pid:
            return None
        try:
            kernel32 = self.kernel32
        except PlatformError:
            return None
        func = getattr(kernel32, "GetApplicationUserModelId", None)
        if func is None:
            return None
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return None
        try:
            length = ctypes.c_uint32(0)
            status = func(handle, ctypes.byref(length), None)
            if not length.value:
                return None
            if status != ERROR_INSUFFICIENT_BUFFER and status != 0:
                return None
            buffer = ctypes.create_unicode_buffer(length.value)
            if func(handle, ctypes.byref(length), buffer) != 0:
                return None
            return buffer.value or None
        except Exception:
            return None
        finally:
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass

    # -- tiện ích ----------------------------------------------------------
    def describe_window(self, hwnd: int, *, with_process: bool = True) -> WindowInfo:
        """Danh tính + hình học một cửa sổ; ném ``CAPTURE_FAILED`` khi HWND chết."""
        if not self.is_window(hwnd):
            raise PlatformError(CAPTURE_FAILED, "HWND không còn tồn tại.", hwnd=hwnd)
        rect = self.get_window_rect(hwnd)
        if rect is None:
            raise PlatformError(CAPTURE_FAILED, "Không đọc được GetWindowRect.", hwnd=hwnd)
        pid = self.get_window_pid(hwnd)
        return WindowInfo(
            hwnd=hwnd,
            title=self.get_window_text(hwnd),
            class_name=self.get_class_name(hwnd),
            pid=pid,
            rect=rect,
            extended_bounds=self.get_extended_frame_bounds(hwnd),
            cloaked=self.is_cloaked(hwnd),
            iconic=self.is_iconic(hwnd),
            process_name=self.process_image_name(pid) if (with_process and pid) else None,
        )


class CuaOverlayWindow:
    """Cửa sổ viền báo vùng đang bị điều khiển: layered, xuyên chuột, luôn trên cùng.

    Win32 bắt cửa sổ và vòng lặp thông điệp của nó sống cùng một thread, nên lớp này giữ một thread
    riêng; lệnh từ tiến trình (hiện/đổi vùng/ẩn/đóng) đi qua ``PostMessageW`` để không bao giờ chặn
    đường CUA. Cửa sổ **không bao giờ** nhận tiêu điểm: `WS_EX_NOACTIVATE` + `SWP_NOACTIVATE`, nếu
    không thì chính viền báo lại cướp tiêu điểm của ứng dụng đang bị điều khiển.

    Đây là lớp "hỏng êm": mọi lỗi Win32 ném ra ngoài, và `CuaOverlay` (agent_core) tự tắt viền sau
    ba lần lỗi thay vì chặn thao tác.
    """

    #: Thông điệp riêng của tiến trình (``WM_APP`` trở lên là vùng dành cho ứng dụng).
    WM_SET_BOUNDS = WM_APP + 1
    WM_HIDE = WM_APP + 2
    WM_QUIT = WM_APP + 3
    CLASS_NAME = "BoxFoxCuaOverlay"

    def __init__(self, platform: "WindowsPlatform | None" = None, *, thickness: int = 3) -> None:
        self.platform = platform or get_platform()
        self.thickness = int(thickness)
        self._thread: threading.Thread | None = None
        self._hwnd = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._color = (0x38, 0xBD, 0xF8)

    # -- API cho `CuaOverlay` ------------------------------------------------
    def overlay_show(self, bounds: dict, color: tuple[int, int, int] | None = None) -> None:
        """Hiện viền quanh `bounds` (`{x, y, width, height}`, toạ độ vật lý)."""
        if color:
            self._color = tuple(int(part) for part in color[:3])
        self.overlay_set_bounds(bounds)
        self.platform.user32.ShowWindow(self._hwnd, SW_SHOWNA)

    def overlay_set_bounds(self, bounds: dict) -> None:
        x, y = int(bounds['x']), int(bounds['y'])
        width, height = max(1, int(bounds['width'])), max(1, int(bounds['height']))
        self._ensure_window()
        # `SetWindowPos` với `SWP_NOACTIVATE`: đổi vùng mà không cướp tiêu điểm.
        user32 = self.platform.user32
        user32.SetWindowPos(self._hwnd, HWND_TOPMOST, x, y, width, height,
                            SWP_NOACTIVATE | SWP_SHOWWINDOW)
        user32.InvalidateRect(self._hwnd, None, True)

    def overlay_hide(self) -> None:
        if self._hwnd:
            self.platform.user32.ShowWindow(self._hwnd, SW_HIDE)

    def overlay_close(self) -> None:
        hwnd = self._hwnd
        if hwnd:
            self.platform.user32.PostMessageW(hwnd, self.WM_QUIT, 0, 0)
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2)
        self._hwnd = 0

    # -- nội bộ --------------------------------------------------------------
    def _ensure_window(self) -> None:
        if self._hwnd:
            return
        with self._lock:
            if self._hwnd:
                return
            thread = threading.Thread(target=self._run, name="boxfox-cua-overlay", daemon=True)
            thread.start()
            self._thread = thread
            # Cửa sổ phải tồn tại trước khi đặt vùng: chờ tối đa 2 giây rồi bỏ cuộc (viền là phụ).
            self._ready.wait(timeout=2.0)
            if not self._hwnd:
                raise PlatformError(CAPTURE_FAILED, "Không tạo được cửa sổ viền overlay.")

    def _run(self) -> None:                                 # pragma: no cover - cần Windows thật
        """Thread sở hữu cửa sổ: đăng ký lớp, tạo cửa sổ, chạy vòng lặp thông điệp."""
        try:
            user32, kernel32, gdi32 = self.platform.user32, self.platform.kernel32, self.platform.gdi32
            instance = kernel32.GetModuleHandleW(None)
            proc = make_window_proc(self._wnd_proc)
            wc = WNDCLASSW()
            wc.style = 0
            wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
            wc.hInstance = instance
            wc.hCursor = user32.LoadCursorW(None, ctypes.cast(32512, ctypes.c_wchar_p))  # IDC_ARROW
            wc.hbrBackground = None
            wc.lpszClassName = self.CLASS_NAME
            if not user32.RegisterClassW(ctypes.byref(wc)):
                raise PlatformError(CAPTURE_FAILED, "RegisterClassW cho viền overlay thất bại.")
            hwnd = user32.CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
                self.CLASS_NAME, "", WS_POPUP, 0, 0, 1, 1, None, None, instance, None)
            if not hwnd:
                raise PlatformError(CAPTURE_FAILED, "CreateWindowExW cho viền overlay thất bại.")
            self._hwnd = int(hwnd)
            user32.SetLayeredWindowAttributes(hwnd, 0, 230, LWA_ALPHA)
            self._ready.set()
            msg = MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            self._ready.set()
        finally:
            self._hwnd = 0

    def _wnd_proc(self, hwnd, message, wparam, lparam):      # pragma: no cover - cần Windows thật
        user32, gdi32 = self.platform.user32, self.platform.gdi32
        if message == WM_PAINT:
            ps = ctypes.create_string_buffer(72)             # PAINTSTRUCT (x64: 72 byte)
            dc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            if dc:
                pen = gdi32.CreatePen(PS_DASH, self.thickness,
                                      self._color[0] | (self._color[1] << 8) | (self._color[2] << 16))
                old_pen = gdi32.SelectObject(dc, pen) if pen else None
                old_brush = gdi32.SelectObject(dc, gdi32.GetStockObject(NULL_BRUSH))
                rect = RECT()
                user32.GetClientRect(hwnd, ctypes.byref(rect))
                gdi32.Rectangle(dc, 0, 0, rect.right, rect.bottom)
                if old_brush:
                    gdi32.SelectObject(dc, old_brush)
                if old_pen:
                    gdi32.SelectObject(dc, old_pen)
                if pen:
                    gdi32.DeleteObject(pen)
                user32.EndPaint(hwnd, ctypes.byref(ps))
            return 0
        if message == self.WM_QUIT:
            user32.DestroyWindow(hwnd)
            user32.PostQuitMessage(0)
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)


class UnavailablePlatform(WindowsPlatform):
    """Nền tảng giữ chỗ trên hệ điều hành không phải Windows.

    Mọi hàm chạm DLL đều ném ``UNSUPPORTED_IN_HOST_MODE`` qua :meth:`_load`; các hàm
    thuần Python (``hook_event``) hoặc no-op khi chưa cài hook (``unhook_mouse``) ném
    qua ``available = False`` để H7 kiểm thử được bằng nền tảng giả trên Linux.
    """

    name = "unavailable"
    available = False

    def _load(self, lib_name: str, funcs: dict[str, tuple[list[Any], Any]]) -> Any:  # pragma: no cover - trivial
        raise PlatformError(
            UNSUPPORTED_IN_HOST_MODE,
            "Tầng nền tảng Windows chỉ chạy trên Windows.",
            platform=sys.platform,
        )


_platform: WindowsPlatform | None = None


def get_platform() -> WindowsPlatform:
    """Nền tảng hiện hành — Windows thật, hoặc nền tảng giả do test tiêm vào."""
    global _platform
    if _platform is None:
        _platform = WindowsPlatform() if IS_WINDOWS else UnavailablePlatform()
    return _platform


def set_platform(platform: WindowsPlatform | None) -> None:
    """Ghi đè nền tảng hiện hành (``None`` ⇒ trả về mặc định của hệ điều hành)."""
    global _platform
    _platform = platform


def callback_ref_count() -> int:
    """Số callback đang được giữ sống — test dùng để chống hồi quy luật 2."""
    return len(_CALLBACK_REFS)


def clear_callback_refs() -> None:
    """Chỉ dùng trong test: giải phóng callback đã đăng ký."""
    _CALLBACK_REFS.clear()


@dataclass
class FakeWindow:
    """Cửa sổ giả cho test — dùng chung giữa các file test của H5."""

    hwnd: int
    title: str = ""
    class_name: str = ""
    pid: int | None = 1000
    rect: tuple[int, int, int, int] = (0, 0, 800, 600)
    extended_bounds: tuple[int, int, int, int] | None = None
    cloaked: bool = False
    iconic: bool = False
    visible: bool = True
    process_name: str | None = "app.exe"
    integrity: int | None = SECURITY_MANDATORY_MEDIUM_RID
    children: list[int] = field(default_factory=list)
