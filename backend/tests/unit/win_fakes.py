"""Nền tảng Windows giả cho test H5/H6 — không gọi Win32, không cần comtypes.

Mọi lời gọi đi qua :class:`FakePlatform` đều được ghi lại trong ``calls`` để test
khẳng định đúng thứ tự/đối số (chuỗi chụp GDI, thứ tự nhả phím, chốt chặn...).
"""
from __future__ import annotations

import time
from typing import Any, Callable

from agentbox.sandbox.win import capture as win_capture
from agentbox.sandbox.win import input as win_input
from agentbox.sandbox.win import uia as win_uia
from agentbox.sandbox.win.errors import PlatformError
from agentbox.sandbox.win.windows_platform import (
    INPUT_KEYBOARD,
    INPUT_MOUSE,
    SECURITY_MANDATORY_MEDIUM_RID,
    WindowInfo,
)

BLACK = (0, 0, 0, 255)
WHITE = (255, 255, 255, 255)
RED = (0, 0, 255, 255)  # BGRA


def solid(width: int, height: int, bgra: tuple[int, int, int, int] = WHITE) -> bytes:
    return bytes(bgra) * (int(width) * int(height))


def make_window(
    hwnd: int = 100,
    *,
    title: str = "BoxFox Test Window",
    class_name: str = "Chrome_WidgetWin_1",
    pid: int = 1000,
    rect: tuple[int, int, int, int] = (0, 0, 800, 600),
    extended_bounds: tuple[int, int, int, int] | None = (0, 0, 800, 600),
    cloaked: bool = False,
    iconic: bool = False,
    process_name: str | None = "chrome.exe",
) -> WindowInfo:
    return WindowInfo(
        hwnd=hwnd,
        title=title,
        class_name=class_name,
        pid=pid,
        rect=rect,
        extended_bounds=extended_bounds,
        cloaked=cloaked,
        iconic=iconic,
        process_name=process_name,
    )


class FakePlatform:
    """Hiện thực giả của :class:`WindowsPlatform` — chỉ những gì tầng trên dùng."""

    name = "fake"

    def __init__(
        self,
        *,
        windows: list[WindowInfo] | None = None,
        virtual_screen: tuple[int, int, int, int] = (0, 0, 1920, 1080),
        dpi: int = 96,
        foreground: int | None = 100,
        cursor: tuple[int, int] = (10, 10),
        desktop: str | None = "Default",
        session: int | None = 1,
        interactive: bool = True,
        own_integrity: int = SECURITY_MANDATORY_MEDIUM_RID,
        integrity_by_pid: dict[int, int] | None = None,
        dpi_v2: bool = True,
        dpi_shcore: bool = True,
        print_ok: dict[int, bool] | None = None,
        print_pixels: Callable[[int, int, int, int], bytes] | None = None,
        blit_pixels: Callable[[int, int, int, int, int], bytes] | None = None,
        blit_ok: bool = True,
        accept_events: int | None = None,
        point_map: dict[tuple[int, int], int | None] | None = None,
        uia_accessor: Any = None,
        input_tick: int = 100_000,
        now_tick: int = 100_000,
        idle_value: float | None = None,
        hook_ok: bool = True,
        mouse_hook_handle: int = 0x2000,
        keyboard_hook_handle: int = 0x1000,
        hook_events: list[dict[str, Any]] | None = None,
        mutex_ok: bool = True,
        mutex_handle: int = 0x777,
        mutex_acquired: bool = True,
    ) -> None:
        self.windows: dict[int, WindowInfo] = {w.hwnd: w for w in (windows or [make_window()])}
        self.virtual_screen = virtual_screen
        self.dpi = dpi
        self.foreground = foreground
        self.cursor = cursor
        self.desktop = desktop
        self.session = session
        self.interactive = interactive
        self.own_integrity = own_integrity
        self.integrity_by_pid = dict(integrity_by_pid or {})
        self.dpi_v2 = dpi_v2
        self.dpi_shcore = dpi_shcore
        self.print_ok = dict(print_ok or {})
        self.print_pixels = print_pixels
        self.blit_pixels = blit_pixels
        self.blit_ok = blit_ok
        self.accept_events = accept_events
        self.point_map = dict(point_map or {})
        self._uia_accessor = uia_accessor
        self.calls: list[tuple[str, tuple]] = []
        self.notes: list[str] = []
        self.bitmaps: dict[int, dict[str, Any]] = {}
        self.selected: dict[int, int] = {}
        #: Mọi sự kiện đã đưa vào SendInput (kể cả phần bị Windows chặn).
        self.sent_events: list[Any] = []
        self.input_tick = int(input_tick)
        self.now_tick = int(now_tick)
        self.idle_value = idle_value
        self.hook_ok = hook_ok
        self.mouse_hook_handle = int(mouse_hook_handle)
        self.keyboard_hook_handle = int(keyboard_hook_handle)
        self.hook_events = list(hook_events or [])
        self.mutex_ok = mutex_ok
        self.mutex_handle = int(mutex_handle)
        self.mutex_acquired = mutex_acquired
        self.mouse_callback: Any = None
        self.keyboard_callback: Any = None
        self._next_dc = 10
        self._next_bitmap = 100

    # -- ghi vết -----------------------------------------------------------
    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def called(self, name: str) -> list[tuple]:
        return [args for call, args in self.calls if call == name]

    def call_names(self) -> list[str]:
        return [call for call, _ in self.calls]

    # -- DPI ---------------------------------------------------------------
    def set_process_dpi_awareness_context(self, context: int) -> bool:
        self._record("set_process_dpi_awareness_context", context)
        return self.dpi_v2

    def set_process_dpi_awareness_shcore(self, awareness: int) -> bool:
        self._record("set_process_dpi_awareness_shcore", awareness)
        return self.dpi_shcore

    def note(self, message: str) -> None:
        self.notes.append(message)

    # -- phiên / desktop ---------------------------------------------------
    def is_interactive_session(self) -> bool:
        return bool(self.interactive)

    def process_session_id(self) -> int | None:
        return self.session

    def input_desktop_name(self) -> str | None:
        return self.desktop

    def desktop_locked(self) -> bool:
        return self.desktop is None or self.desktop != "Default"

    def window_station_name(self) -> str | None:
        return "WinSta0"

    # -- cửa sổ ------------------------------------------------------------
    def is_window(self, hwnd: int) -> bool:
        return int(hwnd) in self.windows

    def is_window_visible(self, hwnd: int) -> bool:
        return int(hwnd) in self.windows

    def is_iconic(self, hwnd: int) -> bool:
        window = self.windows.get(int(hwnd))
        return bool(window and window.iconic)

    def is_cloaked(self, hwnd: int) -> bool:
        window = self.windows.get(int(hwnd))
        return bool(window and window.cloaked)

    def get_ancestor_root(self, hwnd: int) -> int | None:
        return int(hwnd) if hwnd else None

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        window = self.windows.get(int(hwnd))
        return None if window is None else window.rect

    def get_extended_frame_bounds(self, hwnd: int) -> tuple[int, int, int, int] | None:
        window = self.windows.get(int(hwnd))
        return None if window is None else window.extended_bounds

    def get_window_text(self, hwnd: int) -> str:
        window = self.windows.get(int(hwnd))
        return "" if window is None else window.title

    def get_class_name(self, hwnd: int) -> str:
        window = self.windows.get(int(hwnd))
        return "" if window is None else window.class_name

    def get_window_pid(self, hwnd: int) -> int | None:
        window = self.windows.get(int(hwnd))
        return None if window is None else window.pid

    def describe_window(self, hwnd: int, *, with_process: bool = True) -> WindowInfo:
        window = self.windows.get(int(hwnd))
        if window is None:
            raise PlatformError("CAPTURE_FAILED", "HWND không tồn tại.", hwnd=hwnd)
        return window

    def window_from_point(self, x: int, y: int) -> int | None:
        key = (int(x), int(y))
        if key in self.point_map:
            return self.point_map[key]
        for hwnd, window in reversed(list(self.windows.items())):
            bx, by, bw, bh = window.bounds
            if bx <= x < bx + bw and by <= y < by + bh:
                return hwnd
        return None

    def enum_windows(self) -> list[int]:
        return list(self.windows)

    def get_foreground_window(self) -> int | None:
        return self.foreground

    def set_foreground_window(self, hwnd: int) -> bool:
        self._record("set_foreground_window", hwnd)
        self.foreground = int(hwnd)
        return True

    def get_cursor_pos(self) -> tuple[int, int] | None:
        return self.cursor

    def set_cursor_pos(self, x: int, y: int) -> bool:
        self._record("set_cursor_pos", x, y)
        self.cursor = (int(x), int(y))
        return True

    def get_system_metrics(self, index: int) -> int:
        origin_x, origin_y, width, height = self.virtual_screen
        return {0: width, 1: height, 76: origin_x, 77: origin_y, 78: width, 79: height}.get(index, 0)

    def virtual_screen_bounds(self) -> tuple[int, int, int, int]:
        return self.virtual_screen

    def get_dpi_for_window(self, hwnd: int) -> int | None:
        return self.dpi

    # -- tiến trình --------------------------------------------------------
    def process_integrity_level(self, pid: int) -> int | None:
        return self.integrity_by_pid.get(int(pid), SECURITY_MANDATORY_MEDIUM_RID)

    def own_integrity_level(self) -> int | None:
        return self.own_integrity

    def process_image_name(self, pid: int) -> str | None:
        return "app.exe"

    # -- GDI ---------------------------------------------------------------
    def get_dc(self, hwnd: int | None = None) -> int | None:
        self._record("get_dc", hwnd)
        return 1

    def get_window_dc(self, hwnd: int) -> int | None:
        self._record("get_window_dc", hwnd)
        return 2

    def release_dc(self, hwnd: int | None, dc: int) -> bool:
        self._record("release_dc", hwnd, dc)
        return True

    def create_compatible_dc(self, dc: int) -> int | None:
        self._next_dc += 1
        self._record("create_compatible_dc", dc)
        return self._next_dc

    def create_compatible_bitmap(self, dc: int, width: int, height: int) -> int | None:
        self._next_bitmap += 1
        handle = self._next_bitmap
        self.bitmaps[handle] = {"width": int(width), "height": int(height), "pixels": solid(width, height, BLACK)}
        self._record("create_compatible_bitmap", dc, width, height, handle)
        return handle

    def select_object(self, dc: int, obj: int) -> int | None:
        self._record("select_object", dc, obj)
        self.selected[int(dc)] = int(obj)
        return 999

    def delete_dc(self, dc: int) -> bool:
        self._record("delete_dc", dc)
        return True

    def delete_object(self, obj: int) -> bool:
        self._record("delete_object", obj)
        return True

    def bit_blt(self, dst_dc, x, y, width, height, src_dc, src_x, src_y, rop=0x00CC0020) -> bool:
        self._record("bit_blt", dst_dc, x, y, width, height, src_dc, src_x, src_y)
        if not self.blit_ok:
            return False
        bitmap = self._bitmap_for_dc(dst_dc)
        if bitmap is not None:
            source = self.blit_pixels or (lambda src, sx, sy, w, h: solid(w, h, WHITE))
            bitmap["pixels"] = source(src_dc, src_x, src_y, int(width), int(height))
        return True

    def print_window(self, hwnd: int, dc: int, flags: int) -> bool:
        self._record("print_window", hwnd, dc, flags)
        ok = self.print_ok.get(flags, True)
        if not ok:
            return False
        bitmap = self._bitmap_for_dc(dc)
        if bitmap is not None:
            source = self.print_pixels or (lambda h, f, w, ht: solid(w, ht, WHITE))
            bitmap["pixels"] = source(hwnd, flags, bitmap["width"], bitmap["height"])
        return True

    def read_bitmap_bgra(self, dc: int, bitmap: int, width: int, height: int) -> bytes | None:
        entry = self.bitmaps.get(bitmap)
        if entry is None:
            return None
        return entry["pixels"]

    def _bitmap_for_dc(self, dc: int) -> dict[str, Any] | None:
        """Bitmap đang được chọn vào ``dc`` (nhờ theo dõi SelectObject)."""
        return self.bitmaps.get(self.selected.get(int(dc)))

    # -- input -------------------------------------------------------------
    def send_input(self, events: list[Any]) -> int:
        self.sent_events.extend(events)
        self._record("send_input", len(events))
        if self.accept_events is None:
            return len(events)
        accepted = max(0, int(self.accept_events))
        self.accept_events = max(0, accepted - len(events))
        return min(len(events), accepted)

    # -- hook + thời gian nhàn rỗi + mutex (H7) ----------------------------
    def set_mouse_hook(self, callback: Callable[[int, int, int], int]) -> int | None:
        self._record("set_mouse_hook")
        self.mouse_callback = callback
        return self.mouse_hook_handle if self.hook_ok else None

    def unhook_mouse(self) -> None:
        self._record("unhook_mouse")
        self.mouse_callback = None

    def set_keyboard_hook(self, callback: Callable[[int, int, int], int]) -> int | None:
        self._record("set_keyboard_hook")
        self.keyboard_callback = callback
        return self.keyboard_hook_handle if self.hook_ok else None

    def unhook_keyboard(self) -> None:
        self._record("unhook_keyboard")
        self.keyboard_callback = None

    def hook_event(self, kind: str, wparam: int, lparam: int) -> dict[str, Any]:
        """Trả sự kiện đã xếp hàng (``hook_events``); hết hàng ⇒ ``{}``."""
        self._record("hook_event", kind, wparam, lparam)
        return dict(self.hook_events.pop(0)) if self.hook_events else {}

    def last_input_tick(self) -> int:
        self._record("last_input_tick")
        return self.input_tick

    def tick_count(self) -> int:
        return self.now_tick

    def idle_seconds(self, now_tick: int | None = None) -> float | None:
        self._record("idle_seconds", now_tick)
        if self.idle_value is not None:
            return self.idle_value
        if self.input_tick <= 0:
            return None
        now = int(now_tick) if now_tick else self.now_tick
        return max(0, now - self.input_tick) / 1000.0

    def create_mutex(self, name: str) -> int | None:
        self._record("create_mutex", name)
        return self.mutex_handle if self.mutex_ok else None

    def acquire_mutex(self, handle: int, timeout_ms: int = 0) -> bool:
        self._record("acquire_mutex", handle, timeout_ms)
        return bool(handle) and self.mutex_acquired

    def release_mutex(self, handle: int) -> bool:
        self._record("release_mutex", handle)
        return bool(handle)

    def close_handle(self, handle: int) -> bool:
        self._record("close_handle", handle)
        return bool(handle)

    def call_next_hook(self, code: int, wparam: int, lparam: int, *, hook: int | None = None) -> int:
        """``CallNextHookEx`` — H7 khoá bất biến "không bao giờ nuốt phím của người dùng" ở đây."""
        self._record("call_next_hook", code, wparam, lparam)
        return 0

    # -- UIA ---------------------------------------------------------------
    def uia_accessor(self) -> Any:
        return self._uia_accessor


def hook_event_dict(
    *,
    injected: bool = False,
    vkey: int | None = None,
    scan_code: int | None = None,
    flags: int = 0,
    point: tuple[int, int] | None = None,
    message: int = 0,
) -> dict[str, Any]:
    """Một sự kiện hook đúng hình dạng ``WindowsPlatform.hook_event`` trả về."""
    return {
        "injected": bool(injected),
        "vkey": vkey,
        "scanCode": scan_code,
        "flags": int(flags),
        "point": point,
        "message": int(message),
    }


def uia_node(
    *,
    runtime_id: str = "42.1",
    name: str = "OK",
    control_type: int = 50000,
    control_type_name: str = "Button",
    bounds: tuple[int, int, int, int] = (10, 20, 100, 40),
    patterns: list[str] | None = None,
    pid: int = 1000,
    is_password: bool = False,
    handle: Any = "element",
) -> dict[str, Any]:
    """Một node theo đúng hợp đồng ``build_subtree`` mà accessor phải trả."""
    pattern_list = list(patterns if patterns is not None else ["Invoke"])
    box = {"x": bounds[0], "y": bounds[1], "width": bounds[2], "height": bounds[3]}
    return {
        "runtime_id": runtime_id,
        "name": name,
        "control_type": control_type,
        "control_type_name": control_type_name,
        "bounds": box,
        "patterns": pattern_list,
        "pid": pid,
        "payload": {
            "name": name,
            "controlType": control_type_name,
            "controlTypeId": control_type,
            "automationId": "okButton",
            "className": "Button",
            "helpText": "",
            "isEnabled": True,
            "isOffscreen": False,
            "isPassword": is_password,
            "patterns": pattern_list,
        },
        "handle": handle,
    }


class FakeUiaAccessor:
    """Accessor UIA giả: điều khiển được độ trễ, số lần lỗi và node trả về."""

    name = "fake-uia"

    def __init__(
        self,
        nodes: list[dict[str, Any]] | None = None,
        *,
        delay: float = 0.0,
        errors: int = 0,
        exception: BaseException | None = None,
        empty: bool = False,
    ) -> None:
        self.nodes = nodes if nodes is not None else [uia_node()]
        self.delay = float(delay)
        self.remaining_errors = int(errors)
        self.exception = exception or RuntimeError("uia boom")
        self.empty = empty
        self.calls: list[tuple[str, ...]] = []

    def initialize(self) -> str:
        self.calls.append(("initialize",))
        return "mta"

    def element_from_point(self, x: int, y: int) -> Any:
        self.calls.append(("element_from_point", str(x), str(y)))
        self._maybe_fail()
        return None if self.empty else "element"

    def build_subtree(self, element: Any) -> list[dict[str, Any]]:
        self.calls.append(("build_subtree",))
        self._maybe_fail()
        return list(self.nodes)

    def invoke(self, handle: Any, pattern: str) -> bool:
        self.calls.append(("invoke", pattern))
        self._maybe_fail()
        return True

    def focus(self, handle: Any) -> bool:
        self.calls.append(("focus",))
        return True

    def reset(self) -> None:
        self.calls.append(("reset",))

    def _maybe_fail(self) -> None:
        if self.delay:
            time.sleep(self.delay)
        if self.remaining_errors > 0:
            self.remaining_errors -= 1
            raise self.exception


def decode_events(events: list[Any]) -> list[dict[str, Any]]:
    """Đổi danh sách ``INPUT`` thành dict dễ khẳng định trong test."""
    out: list[dict[str, Any]] = []
    for event in events:
        if event.type == INPUT_MOUSE:
            mouse = event.union.mi
            out.append({"kind": "mouse", "flags": mouse.dwFlags, "dx": mouse.dx, "dy": mouse.dy,
                        "data": mouse.mouseData})
        elif event.type == INPUT_KEYBOARD:
            key = event.union.ki
            out.append({"kind": "key", "vk": key.wVk, "scan": key.wScan, "flags": key.dwFlags})
    return out


def wheel_delta(data: int) -> int:
    """`mouseData` là DWORD: `SendInput` đọc 16 bit thấp như số CÓ DẤU, nên -600 hiện ra 64936.

    Dùng chung cho các bài kiểm cuộn của `win_input` và của `host_executor` — hai bản sao của cùng
    một phép đổi dấu là hai chỗ để lệch nhau.
    """
    low = int(data) & 0xFFFF
    return low - 65536 if low >= 32768 else low


def reset_win_state() -> None:
    """Dọn trạng thái cấp module giữa các test."""
    win_capture.reset_dpi_awareness()
    win_capture.reset_geometry_state()
    win_input.reset_stuck_input()
    win_uia.set_accessor(None)
    win_uia.set_session(None)
