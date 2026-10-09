"""Viền báo vùng đang bị điều khiển — quyết định thuần, vẽ bằng nền tảng.

Người dùng phải thấy agent đang làm việc **ở cửa sổ nào**, cả trên màn hình thật lẫn trong panel.
Tệp này giữ phần quyết định (khi nào hiện, bám cửa sổ nào, khi nào tự ẩn) để máy Linux kiểm được
bằng nền tảng giả; phần vẽ cửa sổ viền nằm ở `sandbox/win/windows_platform.py` (Windows, nét đứt)
và `sandbox/x11/overlay.py` (Linux, băng mờ dần) — cùng hợp đồng bốn hàm.

Ba luật, theo hợp đồng §7 và quyết định của chủ dự án:

1. Viền chỉ hiện khi **agent** đang giữ quyền điều khiển và vừa có hoạt động CUA thật.
2. Người dùng chạm máy (lease về tay người) ⇒ viền **ẩn ngay**: nó là tín hiệu "agent đang ở đây",
   không phải một hình trang trí.
3. Không có hoạt động trong :data:`AUTO_HIDE_SEC` ⇒ tự ẩn, để một tiến trình treo không để lại
   vòng xanh vĩnh viễn trên màn hình người dùng.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any

#: Không hoạt động CUA trong bao lâu thì tự ẩn viền (giây).
AUTO_HIDE_SEC = 15.0

#: Màu viền mặc định (RGB). Panel dùng cùng tông `--cua` để hai nơi đọc ra một thứ.
BORDER_COLOR = (0x38, 0xBD, 0xF8)


@dataclass(frozen=True)
class ScreenWindow:
    """Cửa sổ **tổng hợp** cho đích "cả máy" — chỉ đủ để `_bounds_of` và `snapshot()` chạy.

    `hwnd = 0` là chủ ý: `snapshot()['windowId']` phải là `None` để panel hiểu đây là đích cả máy,
    không đi tìm một cửa sổ có mã 0 trong danh sách cửa sổ (và không vẽ nhầm viền cửa sổ).
    """

    hwnd: int = 0
    title: str = ''
    bounds: tuple[int, int, int, int] = (0, 0, 0, 0)


def screen_window(bounds: Any) -> ScreenWindow:
    """Đối tượng cửa sổ tổng hợp phủ `bounds` `(x, y, rộng, cao)` — đích CUA "cả máy".

    Nhận cả bộ bốn số của `virtual_screen_bounds()`; kích thước âm/không đọc được bị kẹp về 0 (khi đó
    `_bounds_of` từ chối và viền không vẽ — đúng luật "không đoán bừa chỗ đang bị điều khiển").
    """
    try:
        x, y, width, height = (int(part) for part in tuple(bounds)[:4])
    except (TypeError, ValueError):
        return ScreenWindow()
    return ScreenWindow(bounds=(x, y, max(0, width), max(0, height)))


def _read(window: Any, name: str) -> Any:
    """Đọc `name` từ **thuộc tính** hoặc từ **mapping** — hai hình dạng cửa sổ tầng trên đưa xuống."""
    value = getattr(window, name, None)
    if value is None and isinstance(window, dict):
        value = window.get(name)
    return value


def _bounds_of(window: Any) -> dict | None:
    """Hình chữ nhật màn hình của cửa sổ (toạ độ vật lý), hoặc `None` nếu không đọc được.

    Đọc theo thứ tự: `bounds` (đã là `(x, y, w, h)` — thuộc tính thật của `WindowInfo`) → mapping
    `{x, y, width, height}` → bộ bốn số của `rect`/`extended_bounds`, vốn là
    **`(left, top, right, bottom)`** trên CẢ HAI nền tảng (`windows_platform.py:740`,
    `sandbox/x11/platform.py::get_window_rect`). Đọc thẳng bộ bốn số đó như `(x, y, w, h)` là lỗi
    đã đo được: cửa sổ `(96, 1039, 1824, 1080)` cho ra `width=1824, height=1080` thay vì
    `1728 × 41`.
    """
    if window is None:
        return None
    bounds = _read(window, 'bounds')
    if bounds is None and isinstance(window, dict):
        if all(key in window for key in ('x', 'y', 'width', 'height')):
            bounds = (window['x'], window['y'], window['width'], window['height'])
    if bounds is None:
        rect = _read(window, 'extended_bounds') or _read(window, 'rect')
        if not rect:
            return None
        try:
            left, top, right, bottom = (int(part) for part in tuple(rect)[:4])
        except (TypeError, ValueError):
            return None
        bounds = (left, top, max(0, right - left), max(0, bottom - top))
    try:
        x, y, width, height = (int(part) for part in tuple(bounds)[:4])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {'x': x, 'y': y, 'width': width, 'height': height}


class CuaOverlay:
    """Bộ điều khiển viền: quyết định thuần, nền tảng chỉ nhận lệnh vẽ.

    `platform` cần có `overlay_show(bounds, color)`, `overlay_set_bounds(bounds)`, `overlay_hide()`
    và (tuỳ chọn) `overlay_close()` + `overlay_source(hwnd)`. Nền tảng không có ⇒ mọi lệnh là no-op:
    CUA vẫn chạy, chỉ mất tín hiệu thị giác — đúng tinh thần "hỏng êm" của bản alpha. `reason` là
    câu nói **vì sao** viền tắt (ví dụ thiếu `python-xlib`), để panel không phải nói "không rõ".
    """

    def __init__(self, platform: Any = None, *, enabled: bool = True,
                 auto_hide: float = AUTO_HIDE_SEC, clock=time.monotonic, reason: str = '') -> None:
        self.platform = platform
        self.enabled = bool(enabled) and platform is not None
        self.auto_hide = float(auto_hide)
        self._clock = clock
        self._lock = threading.RLock()
        self._visible = False
        self._paused = ''
        self._window_id: int | None = None
        self._title = ''
        self._bounds: dict | None = None
        self._last_note = 0.0
        self._timer: threading.Timer | None = None
        self._failures = 0
        #: Vì sao viền KHÔNG dùng được (thiếu gói, mặt viền chết). Giữ riêng khỏi `last_reason` để
        #: các lý do thoáng qua (`agent_activity`, `idle`, `session_cleanup`…) không xoá mất câu nói
        #: được VIỆC CẦN LÀM — panel (J8) đọc chính `reason` này để hiện một dòng cảnh báo.
        self._unavailable_reason = '' if self.enabled else (str(reason or '') or 'overlay_unavailable')
        #: Lý do gần nhất viền không hiện (để `GET /machines/target` nói được vì sao).
        self.last_reason = self._unavailable_reason

    # -- lệnh từ đường CUA ---------------------------------------------------

    def note(self, window: Any, *, reason: str = 'agent_activity') -> bool:
        """Có hoạt động CUA trên `window`: hiện viền và bám cửa sổ đó. Trả `True` nếu đang hiện."""
        bounds = _bounds_of(window)
        if bounds is None:
            # Không biết cửa sổ nào thì KHÔNG vẽ (không đoán bừa chỗ đang bị điều khiển).
            self.last_reason = 'no_window'
            return False
        hwnd = int(getattr(window, 'hwnd', 0) or 0)
        with self._lock:
            if not self.enabled:
                # Câu "thiếu `python-xlib`…" là câu nói được việc cần làm; đừng thay bằng câu chung.
                self.last_reason = self._unavailable_reason or 'overlay_unavailable'
                return False
            if self._paused:
                self.last_reason = self._paused
                return False
            self._last_note = self._clock()
            self._window_id = hwnd or None
            self._title = str(getattr(window, 'title', '') or '')
            self._bounds = bounds
            self.last_reason = reason
            # Nguồn lấy màu nền (chỉ X11 có): cửa sổ đích, hoặc `0` cho đích "cả máy" (đọc ở root).
            # Hàm thiếu ⇒ bỏ qua, KHÔNG tính là lỗi — mặt viền nào không cần thì không phải khai.
            self._call_optional('overlay_source', hwnd)
            if not self._visible:
                if not self._call('overlay_show', bounds, BORDER_COLOR):
                    return False
                self._visible = True
            else:
                self._call('overlay_set_bounds', bounds)
            self._schedule_auto_hide()
            return True

    def pause(self, reason: str) -> None:
        """Tạm dừng viền (người dùng giữ quyền, đích bị xoá…): ẩn ngay và không tự hiện lại."""
        with self._lock:
            self._paused = str(reason or 'paused')
            self.last_reason = self._paused
            self._cancel_timer()
            self._hide_locked()

    def resume(self) -> None:
        with self._lock:
            self._paused = ''
            self.last_reason = ''

    def hide(self, reason: str = 'hidden') -> None:
        """Ẩn viền nhưng vẫn cho phép hiện lại ở lần hoạt động sau."""
        with self._lock:
            self._cancel_timer()
            self.last_reason = str(reason or 'hidden')
            self._hide_locked()

    def close(self) -> None:
        """Dọn hẳn (tiến trình tắt): ẩn và đóng cửa sổ viền nếu nền tảng có."""
        with self._lock:
            self._cancel_timer()
            self._hide_locked()
            self._call('overlay_close')

    def snapshot(self) -> dict:
        with self._lock:
            return {'enabled': self.enabled, 'visible': self._visible, 'paused': self._paused or None,
                    'windowId': self._window_id, 'title': self._title, 'bounds': self._bounds,
                    'reason': self.last_reason or None,
                    'idleSeconds': (round(self._clock() - self._last_note, 3)
                                    if self._last_note else None)}

    # -- nội bộ --------------------------------------------------------------

    def _call(self, name: str, *args) -> bool:
        method = getattr(self.platform, name, None) if self.platform is not None else None
        if method is None:
            self.last_reason = self._unavailable_reason or 'overlay_unavailable'
            return False
        try:
            method(*args)
            return True
        except Exception as exc:              # viền là tính năng phụ: hỏng thì tắt êm, không chặn CUA
            self._failures += 1
            self.last_reason = 'overlay_failed:%s' % type(exc).__name__
            if self._failures >= 3:
                self.enabled = False
                self._unavailable_reason = self.last_reason
            return False

    def _call_optional(self, name: str, *args) -> bool:
        """Gọi một hàm **không bắt buộc** của mặt viền (`overlay_source`): thiếu/hỏng ⇒ bỏ qua.

        Không tính vào `_failures`: một tiện ích (chỗ lấy màu nền) không được phép tắt viền.
        """
        method = getattr(self.platform, name, None) if self.platform is not None else None
        if method is None:
            return False
        try:
            method(*args)
            return True
        except Exception:
            return False

    def _hide_locked(self) -> None:
        if self._visible:
            self._call('overlay_hide')
            self._visible = False

    def _schedule_auto_hide(self) -> None:
        self._cancel_timer()
        if self.auto_hide <= 0:
            return
        timer = threading.Timer(self.auto_hide, self._auto_hide)
        timer.daemon = True
        self._timer = timer
        timer.start()

    def _cancel_timer(self) -> None:
        timer, self._timer = self._timer, None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                pass

    def _auto_hide(self) -> None:
        with self._lock:
            if not self._visible:
                return
            if self._clock() - self._last_note < self.auto_hide:
                return                        # có hoạt động mới trong lúc chờ: lần note sau lo tiếp
            self.last_reason = 'idle'
            self._hide_locked()
