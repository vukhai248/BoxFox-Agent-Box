"""Gửi input trên Windows theo thang ba bậc (H5, kế hoạch §4.3).

1. **UIA pattern action** (mặc định) — ``Invoke``/``Toggle``/``SelectionItem`` qua
   UI Automation: không cướp focus, không di chuyển con trỏ. Xem :mod:`.uia`.
2. **SendInput foreground** — bấm/gõ thật, kèm ba bảo hiểm: kiểm tra foreground
   trước **mỗi** lô sự kiện, khôi phục cửa sổ + con trỏ sau khi xong, và xử lý
   "gửi hụt" (SendInput trả về số sự kiện thật sự được chèn).
3. **PostMessage background** — **không nằm trong phạm vi H5** (ma trận "rơi im
   lặng" trong ``WIN-CAPTURE-REPORT.md`` §6 cho thấy nó vô hiệu với Chromium,
   XAML, UWP, WPF, Tk, GTK, VCL). Gọi vào đây sẽ nhận lỗi có cấu trúc
   ``POST_MESSAGE_UNSUPPORTED``.

Từ chối trước khi gửi (chạy TRƯỚC cổng phê duyệt, không thể bỏ qua):

* UIPI: tiến trình đích có integrity level cao hơn ta ⇒ ``UIPI_BLOCKED``
  (tuyệt đối không tự nâng quyền).
* Desktop không phải ``Default`` (màn hình khoá / UAC / secure desktop) ⇒
  ``DESKTOP_LOCKED``.
* Session 0 (dịch vụ) ⇒ ``SESSION_NOT_INTERACTIVE``.
* Gõ vào phần tử ``IsPassword`` ⇒ ``PASSWORD_FIELD_REFUSED``.

Chuyện gửi hụt: Windows có thể chèn một phần lô rồi chặn phần còn lại. Ta **chỉ**
nhả đúng những phím đã thực sự được chèn, theo **thứ tự ngược**, không nhả phím
chưa từng được chèn, và không bao giờ phát lại cú bấm/đoạn gõ.
"""
from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import (
    DESKTOP_LOCKED,
    INPUT_SHORT_SEND,
    PASSWORD_FIELD_REFUSED,
    POST_MESSAGE_UNSUPPORTED,
    SESSION_NOT_INTERACTIVE,
    SOURCE_CHANGED,
    UIPI_BLOCKED,
    PlatformError,
)
from .windows_platform import (
    INPUT,
    INPUT_KEYBOARD,
    INPUT_MOUSE,
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    MOUSEEVENTF_ABSOLUTE,
    MOUSEEVENTF_HWHEEL,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MIDDLEDOWN,
    MOUSEEVENTF_MIDDLEUP,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_VIRTUALDESK,
    MOUSEEVENTF_WHEEL,
    WHEEL_DELTA,
    MOUSEINPUT,
    KEYBDINPUT,
    SECURITY_MANDATORY_MEDIUM_RID,
    WindowsPlatform,
    get_platform,
)

#: Bàn phím ảo — tên gọi thân thiện → mã phím ảo.
VK_MAP: dict[str, int] = {
    "backspace": 0x08,
    "tab": 0x09,
    "enter": 0x0D,
    "return": 0x0D,
    "shift": 0x10,
    "ctrl": 0x11,
    "control": 0x11,
    "alt": 0x12,
    "pause": 0x13,
    "capslock": 0x14,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "pageup": 0x21,
    "pagedown": 0x22,
    "end": 0x23,
    "home": 0x24,
    "left": 0x25,
    "up": 0x26,
    "right": 0x27,
    "down": 0x28,
    "printscreen": 0x2C,
    "insert": 0x2D,
    "delete": 0x2E,
    "del": 0x2E,
    "win": 0x5B,
    "meta": 0x5B,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
}
#: Tên bổ trợ (modifier) → mã phím ảo.
MODIFIER_KEYS: dict[str, int] = {
    "ctrl": 0x11,
    "control": 0x11,
    "shift": 0x10,
    "alt": 0x12,
    "win": 0x5B,
    "meta": 0x5B,
}
MOUSE_BUTTONS: dict[str, tuple[int, int]] = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}
#: Hướng cuộn → (cờ sự kiện, dấu của ``mouseData``). Dấu dương của bánh xe là cuộn LÊN.
SCROLL_AXIS: dict[str, tuple[int, int]] = {
    "up": (MOUSEEVENTF_WHEEL, 1),
    "down": (MOUSEEVENTF_WHEEL, -1),
    "right": (MOUSEEVENTF_HWHEEL, 1),
    "left": (MOUSEEVENTF_HWHEEL, -1),
}
#: Trần số nấc cuộn một lệnh (mỗi nấc là 120 đơn vị bánh xe).
MAX_SCROLL_STEPS = 20
#: Số điểm dừng mặc định của một cú kéo.
DRAG_STEPS = 12
#: Trần số điểm dừng (một lô sự kiện khổng lồ sẽ bị SendInput cắt).
MAX_DRAG_STEPS = 60
#: Khe hở sau khi NHẤN và trước khi NHẢ (giây). Ứng dụng phân biệt "bấm" với "kéo" bằng thời gian
#: giữ: nhấn-rồi-nhả trong cùng một khung hình bị hiểu là cú bấm.
GESTURE_SETTLE_SEC = 0.03
#: Trần thời gian giữ chuột của `hold` (giây).
MAX_HOLD_SEC = 5.0
#: Trần số điểm của một nét vẽ.
MAX_STROKE_POINTS = 400

#: Số đơn vị UTF-16 tối đa trong một lô gõ (kiểm tra foreground giữa các lô).
TEXT_CHUNK_UNITS = 64
#: Trần độ dài văn bản một lần gõ (chống lô sự kiện khổng lồ).
MAX_TEXT_CHARS = 4096

#: Phím/nút đang bị giữ lại sau một lần gửi hụt — dọn bằng `release_stuck_input`.
_stuck_keys: list[INPUT] = []
_stuck_mouse: list[INPUT] = []


# ---------------------------------------------------------------------------
# Cấu trúc sự kiện
# ---------------------------------------------------------------------------
def mouse_input(dx: int, dy: int, flags: int, mouse_data: int = 0) -> INPUT:
    event = INPUT()
    event.type = INPUT_MOUSE
    event.union.mi = MOUSEINPUT(int(dx), int(dy), int(mouse_data), int(flags), 0, None)
    return event


def key_input(vk: int, scan: int = 0, flags: int = 0) -> INPUT:
    event = INPUT()
    event.type = INPUT_KEYBOARD
    event.union.ki = KEYBDINPUT(int(vk), int(scan), int(flags), 0, None)
    return event


@dataclass
class EventBatch:
    """Lô sự kiện + bản đồ "phím nào được nhả bởi sự kiện nào"."""

    events: list[INPUT] = field(default_factory=list)
    #: ``pairs[i] = j`` nghĩa là sự kiện i (một lần nhấn) được nhả bởi sự kiện j.
    pairs: list[int | None] = field(default_factory=list)
    label: str = "batch"

    def press(self, down: INPUT, up: INPUT) -> None:
        index = len(self.events)
        self.events.append(down)
        self.pairs.append(index + 1)
        self.events.append(up)
        self.pairs.append(None)

    def combo(self, modifier_vks: list[int], key_down: INPUT, key_up: INPUT) -> None:
        """Tổ hợp phím: ``[m1↓ … mn↓ key↓ key↑ mn↑ … m1↑]``.

        Phím bổ trợ phải được NHẢ theo thứ tự ngược sau khi phím chính đã nhả —
        nhả sớm thì tổ hợp mất nghĩa (Ctrl nhả trước khi nhấn A = gõ "a").
        """
        start = len(self.events)
        for vk in modifier_vks:
            self.add(key_input(vk))
        key_index = len(self.events)
        self.events.append(key_down)
        self.pairs.append(key_index + 1)
        self.events.append(key_up)
        self.pairs.append(None)
        for vk in reversed(modifier_vks):
            self.add(key_input(vk, 0, KEYEVENTF_KEYUP))
        for offset in range(len(modifier_vks)):
            self.pairs[start + offset] = len(self.events) - 1 - offset

    def add(self, event: INPUT) -> None:
        self.events.append(event)
        self.pairs.append(None)

    def __len__(self) -> int:
        return len(self.events)


def pending_releases(events: list[INPUT], pairs: list[int | None], sent: int) -> list[INPUT]:
    """Sự kiện nhả cần gửi thêm, theo thứ tự ngược, chỉ cho phím đã được chèn.

    Một lần nhấn đã được chèn (``i < sent``) mà sự kiện nhả của nó *không* được
    chèn (``pairs[i] >= sent``) thì phím đó đang bị giữ ở phía Windows. Phím nhấn
    chưa từng được chèn thì không bao giờ được nhả (nhả một phím chưa nhấn có thể
    làm ứng dụng đích hiểu sai trạng thái bàn phím).
    """
    releases: list[INPUT] = []
    limit = min(int(sent), len(events))
    for index in range(limit - 1, -1, -1):
        pair = pairs[index] if index < len(pairs) else None
        if pair is not None and pair >= sent:
            releases.append(events[pair])
    return releases


def _send_batch(platform: WindowsPlatform, batch: EventBatch) -> int:
    """Gửi một lô; nếu gửi hụt thì dọn phần đã chèn rồi ném lỗi có cấu trúc."""
    if not batch.events:
        return 0
    sent = platform.send_input(batch.events)
    if sent >= len(batch.events):
        return sent
    releases = pending_releases(batch.events, batch.pairs, sent)
    released = 0
    if releases:
        released = platform.send_input(releases)
        # Phím nào vẫn không nhả được thì ghi nhớ để `release_stuck_input` dọn sau.
        for release in releases[max(0, int(released)) :]:
            if release.type == INPUT_KEYBOARD:
                _stuck_keys.append(release)
            else:
                _stuck_mouse.append(release)
    raise PlatformError(
        INPUT_SHORT_SEND,
        (
            f"SendInput chỉ chèn được {sent}/{len(batch.events)} sự kiện ({batch.label}). "
            "Windows chặn phần còn lại: tiến trình đích có integrity level cao hơn (UIPI), "
            "hoặc desktop đang bị khoá / hiện secure prompt."
        ),
        requested=len(batch.events),
        sent=int(sent),
        stage=batch.label,
        released=int(released),
    )


def release_stuck_input(*, platform: WindowsPlatform | None = None) -> int:
    """Nhả mọi phím/nút còn kẹt từ lần gửi hụt trước (gọi lúc stop/restart)."""
    p = platform or get_platform()
    releases = list(reversed(_stuck_keys)) + list(reversed(_stuck_mouse))
    _stuck_keys.clear()
    _stuck_mouse.clear()
    if not releases:
        return 0
    p.send_input(releases)
    return len(releases)


def reset_stuck_input() -> None:
    """Xoá sổ phím kẹt mà không gửi gì (dùng trong test)."""
    _stuck_keys.clear()
    _stuck_mouse.clear()


def stuck_input_count() -> int:
    """Số phím/nút đang được ghi nhận là kẹt (chỉ để chẩn đoán/test)."""
    return len(_stuck_keys) + len(_stuck_mouse)


# ---------------------------------------------------------------------------
# Toạ độ
# ---------------------------------------------------------------------------
def _round_div(numerator: int, denominator: int) -> int:
    if denominator == 0:
        return 0
    if numerator >= 0:
        return (numerator + denominator // 2) // denominator
    return -((-numerator + denominator // 2) // denominator)


def _to_absolute(value: int, origin: int, extent: int) -> int:
    """Pixel vật lý → thang 0..65535 của SendInput (số học 64 bit, gốc có thể âm)."""
    if extent <= 1:
        return 0
    scaled = _round_div((int(value) - int(origin)) * 65535, int(extent) - 1)
    return max(0, min(65535, scaled))


def normalize_coordinates(
    x: int, y: int, *, platform: WindowsPlatform | None = None
) -> tuple[int, int]:
    """Chuẩn hoá toạ độ **màn hình vật lý** sang hệ absolute của SendInput.

    Desktop ảo có thể có gốc âm (màn hình phụ đặt bên trái/trên), nên phép trừ
    phải là số học 64 bit: cắt về 32 bit sẽ ra toạ độ rác và cú bấm rơi vào màn
    hình khác.
    """
    p = platform or get_platform()
    origin_x, origin_y, width, height = p.virtual_screen_bounds()
    return _to_absolute(x, origin_x, width), _to_absolute(y, origin_y, height)


def denormalize_coordinates(
    nx: int, ny: int, *, platform: WindowsPlatform | None = None
) -> tuple[int, int]:
    """Nghịch đảo (chỉ dùng để kiểm chứng trong test)."""
    p = platform or get_platform()
    origin_x, origin_y, width, height = p.virtual_screen_bounds()
    x = _round_div(int(nx) * max(0, width - 1), 65535) + origin_x
    y = _round_div(int(ny) * max(0, height - 1), 65535) + origin_y
    return x, y


# ---------------------------------------------------------------------------
# Chốt chặn trước khi gửi
# ---------------------------------------------------------------------------
def resolve_window(window: Any, *, platform: WindowsPlatform | None = None) -> int:
    """Nhận HWND, ``WindowInfo`` hay ``None`` (tự tìm cửa sổ tại con trỏ)."""
    if window is None:
        raise PlatformError(SOURCE_CHANGED, "Thiếu cửa sổ đích cho thao tác input.")
    hwnd = getattr(window, "hwnd", window)
    return int(hwnd)


def check_integrity(pid: int | None, *, platform: WindowsPlatform | None = None) -> None:
    """UIPI: đích cao hơn ta ⇒ từ chối, **không** tự nâng quyền."""
    p = platform or get_platform()
    if not pid:
        return
    target = p.process_integrity_level(int(pid))
    if target is None:
        return
    own = p.own_integrity_level()
    if own is None:
        own = SECURITY_MANDATORY_MEDIUM_RID
    if target > own:
        raise PlatformError(
            UIPI_BLOCKED,
            (
                "Tiến trình đích chạy ở integrity level cao hơn BoxFox "
                f"(đích 0x{target:04x} > ta 0x{own:04x}). Windows sẽ chặn mọi sự kiện "
                "SendInput. Hãy chạy BoxFox cùng mức quyền với ứng dụng đích."
            ),
            target_integrity=target,
            own_integrity=own,
            pid=int(pid),
        )


def check_desktop(*, platform: WindowsPlatform | None = None) -> None:
    """Màn hình khoá / UAC / secure desktop và Session 0."""
    p = platform or get_platform()
    if not p.is_interactive_session():
        raise PlatformError(
            SESSION_NOT_INTERACTIVE,
            "BoxFox đang chạy trong phiên không tương tác (Session 0) — không thể gửi input.",
            session=p.process_session_id(),
        )
    if p.desktop_locked():
        raise PlatformError(
            DESKTOP_LOCKED,
            "Desktop hiện tại không phải 'Default' (màn hình đang khoá hoặc có secure prompt).",
            desktop=p.input_desktop_name(),
        )


def check_preconditions(
    window: Any, *, pid: int | None = None, platform: WindowsPlatform | None = None
) -> int:
    """Chạy toàn bộ chốt chặn trước khi gửi; trả về HWND đã chuẩn hoá."""
    p = platform or get_platform()
    hwnd = resolve_window(window, platform=p)
    check_desktop(platform=p)
    if pid is None:
        pid = p.get_window_pid(hwnd) if p.is_window(hwnd) else None
    check_integrity(pid, platform=p)
    return hwnd


def check_point_ownership(
    x: int, y: int, hwnd: int, *, platform: WindowsPlatform | None = None
) -> None:
    """§4.5: ``WindowFromPoint`` tại đúng điểm phải thuộc cửa sổ đích.

    Nếu không, cửa sổ đã bị che từ lúc soi tới lúc bấm ⇒ ``SOURCE_CHANGED`` với
    lý do ``occluded``, **không** gửi input.
    """
    p = platform or get_platform()
    top = p.window_from_point(int(x), int(y))
    root = (p.get_ancestor_root(top) or top) if top else None
    if root is None or int(root) != int(hwnd):
        raise PlatformError(
            SOURCE_CHANGED,
            "Điểm bấm đang bị cửa sổ khác che — không gửi input.",
            reason="occluded",
            point={"x": int(x), "y": int(y)},
            window_at_point=None if root is None else int(root),
            hwnd=int(hwnd),
        )


def check_geometry_revision(
    source_id: str | None, revision: int | None, *, platform: WindowsPlatform | None = None
) -> None:
    """§4.5: input mang ``geometryRevision`` cũ ⇒ ``SOURCE_CHANGED``."""
    if not source_id or revision is None:
        return
    from .capture import current_geometry_revision

    current = current_geometry_revision(str(source_id))
    if current is None or int(current) != int(revision):
        raise PlatformError(
            SOURCE_CHANGED,
            (
                "Cửa sổ/khung đã đổi hình học kể từ lúc soi "
                f"(revision {revision} → {current}) — soi lại trước khi thao tác."
            ),
            reason="geometry_changed",
            source_id=str(source_id),
            revision=int(revision),
            current_revision=current,
        )


def is_password_element(element: Any) -> bool:
    """``True`` nếu phần tử UIA khai báo ``IsPassword``."""
    if element is None:
        return False
    if isinstance(element, Mapping):
        return bool(element.get("isPassword") or element.get("is_password"))
    payload = getattr(element, "payload", None)
    if isinstance(payload, Mapping):
        return bool(payload.get("isPassword") or payload.get("is_password"))
    return bool(getattr(element, "is_password", False))


# ---------------------------------------------------------------------------
# Foreground
# ---------------------------------------------------------------------------
def foreground_matches(hwnd: int, *, platform: WindowsPlatform | None = None) -> bool:
    p = platform or get_platform()
    current = p.get_foreground_window()
    if not current:
        return False
    if int(current) == int(hwnd):
        return True
    root = p.get_ancestor_root(current)
    return bool(root) and int(root) == int(hwnd)


def ensure_foreground(
    hwnd: int,
    *,
    platform: WindowsPlatform | None = None,
    timeout: float = 0.5,
    interval: float = 0.02,
    raise_window: bool = True,
) -> None:
    """Bảo đảm ``hwnd`` đang là cửa sổ foreground, nếu không thì ``SOURCE_CHANGED``.

    Không dùng ``AttachThreadInput`` để giành focus: nếu Windows từ chối, ta dừng
    và báo lỗi thay vì gõ vào cửa sổ sai.
    """
    p = platform or get_platform()
    if foreground_matches(hwnd, platform=p):
        return
    if raise_window:
        p.set_foreground_window(hwnd)
        deadline = time.monotonic() + max(0.0, timeout)
        while time.monotonic() < deadline:
            if foreground_matches(hwnd, platform=p):
                return
            time.sleep(max(0.0, interval))
    if not foreground_matches(hwnd, platform=p):
        raise PlatformError(
            SOURCE_CHANGED,
            (
                "Cửa sổ đích không còn là cửa sổ foreground — người dùng có thể đã "
                "chuyển sang cửa sổ khác. Không gửi input để tránh gõ nhầm chỗ."
            ),
            hwnd=int(hwnd),
            foreground=p.get_foreground_window(),
        )


# ---------------------------------------------------------------------------
# Bậc 2: chuột
# ---------------------------------------------------------------------------
def click(
    x: int,
    y: int,
    *,
    window: Any,
    button: str = "left",
    platform: WindowsPlatform | None = None,
    restore: bool = True,
    timeout: float = 0.5,
    source_id: str | None = None,
    geometry_revision: int | None = None,
) -> dict[str, Any]:
    """Bấm một điểm trên cửa sổ đích bằng SendInput (bậc 2)."""
    p = platform or get_platform()
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, f"Nút chuột không hợp lệ: {button!r}", button=button)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    hwnd = check_preconditions(window, platform=p)
    check_point_ownership(x, y, hwnd, platform=p)
    down_flag, up_flag = MOUSE_BUTTONS[button]
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    nx, ny = normalize_coordinates(x, y, platform=p)
    batch = EventBatch(label="mouse_click")
    batch.add(mouse_input(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))
    batch.add(mouse_input(0, 0, down_flag))
    batch.add(mouse_input(0, 0, up_flag))
    try:
        _send_batch(p, batch)
    finally:
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        "route": "send_input",
        "action": "click",
        "button": button,
        "point": {"x": int(x), "y": int(y)},
        "normalized": {"x": nx, "y": ny},
        "windowId": hwnd,
        "events": len(batch),
    }


def _move_event(x: int, y: int, platform: WindowsPlatform) -> INPUT:
    """Sự kiện di chuyển tuyệt đối trong hệ toạ độ desktop ảo."""
    nx, ny = normalize_coordinates(x, y, platform=platform)
    return mouse_input(nx, ny, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK)


def _release_button(platform: WindowsPlatform, event: INPUT) -> None:
    """Nhả nút chuột, nuốt lỗi. Gọi trong ``finally`` — không được che lỗi thật của thân hàm."""
    try:
        platform.send_input([event])
    except Exception:  # pragma: no cover - best effort, đường thoát cuối
        _stuck_mouse.append(event)


def scroll(
    x: int,
    y: int,
    *,
    window: Any,
    direction: str = "down",
    steps: int = 3,
    platform: WindowsPlatform | None = None,
    restore: bool = True,
    timeout: float = 0.5,
    source_id: str | None = None,
    geometry_revision: int | None = None,
) -> dict[str, Any]:
    """Cuộn con lăn tại một điểm (``MOUSEEVENTF_WHEEL``/``HWHEEL``).

    Windows gửi sự kiện bánh xe cho cửa sổ **dưới con trỏ**, nên con trỏ phải được đặt vào đúng
    cửa sổ đích trước (và đã qua chốt ``check_point_ownership``) rồi mới cuộn.
    """
    p = platform or get_platform()
    if direction not in SCROLL_AXIS:
        raise PlatformError(SOURCE_CHANGED, f"Hướng cuộn không hợp lệ: {direction!r}", direction=direction)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    hwnd = check_preconditions(window, platform=p)
    check_point_ownership(x, y, hwnd, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    try:
        count = max(1, min(MAX_SCROLL_STEPS, int(steps)))
    except (TypeError, ValueError):
        count = 3
    flag, sign = SCROLL_AXIS[direction]
    batch = EventBatch(label="mouse_scroll")
    batch.add(_move_event(int(x), int(y), p))
    batch.add(mouse_input(0, 0, flag, sign * count * WHEEL_DELTA))
    try:
        _send_batch(p, batch)
    finally:
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        "route": "send_input",
        "action": "scroll",
        "direction": direction,
        "steps": count,
        "point": {"x": int(x), "y": int(y)},
        "windowId": hwnd,
        "events": len(batch),
    }


def drag(
    x: int,
    y: int,
    to_x: int,
    to_y: int,
    *,
    window: Any,
    button: str = "left",
    steps: int = DRAG_STEPS,
    platform: WindowsPlatform | None = None,
    restore: bool = True,
    timeout: float = 0.5,
    guard_end: bool = True,
    source_id: str | None = None,
    geometry_revision: int | None = None,
) -> dict[str, Any]:
    """Kéo từ điểm này sang điểm khác: nhấn, đi từng bước, nhả.

    Chia thành ba lô (nhấn → đi → nhả) có khe hở thời gian thật ở giữa: ứng dụng phân biệt cú kéo
    với cú bấm bằng thời gian giữ, mà ba lô gửi liền nhau thì không có thời gian nào cả. Nút chuột
    được nhả trong ``finally`` và, nếu lần nhả đó cũng hỏng, được ghi vào sổ nút kẹt để
    ``release_stuck_input`` dọn sau.
    """
    p = platform or get_platform()
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, f"Nút chuột không hợp lệ: {button!r}", button=button)
    start_x, start_y, end_x, end_y = int(x), int(y), int(to_x), int(to_y)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    hwnd = check_preconditions(window, platform=p)
    check_point_ownership(start_x, start_y, hwnd, platform=p)
    if guard_end:
        check_point_ownership(end_x, end_y, hwnd, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    try:
        count = max(1, min(MAX_DRAG_STEPS, int(steps)))
    except (TypeError, ValueError):
        count = DRAG_STEPS
    down_flag, up_flag = MOUSE_BUTTONS[button]
    down_event = mouse_input(0, 0, down_flag)
    up_event = mouse_input(0, 0, up_flag)
    down_batch = EventBatch(label="mouse_drag_down")
    down_batch.add(_move_event(start_x, start_y, p))
    down_batch.add(down_event)
    move_batch = EventBatch(label="mouse_drag_move")
    for index in range(1, count + 1):
        step_x = round(start_x + (end_x - start_x) * index / count)
        step_y = round(start_y + (end_y - start_y) * index / count)
        move_batch.add(_move_event(step_x, step_y, p))
    up_batch = EventBatch(label="mouse_drag_up")
    up_batch.add(up_event)
    released = False
    try:
        _send_batch(p, down_batch)
        time.sleep(GESTURE_SETTLE_SEC)
        _send_batch(p, move_batch)
        time.sleep(GESTURE_SETTLE_SEC)
        _send_batch(p, up_batch)
        released = True
    finally:
        if not released:
            _release_button(p, up_event)
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        "route": "send_input",
        "action": "drag",
        "button": button,
        "from": {"x": start_x, "y": start_y},
        "to": {"x": end_x, "y": end_y},
        "steps": count,
        "windowId": hwnd,
        "events": len(down_batch) + len(move_batch) + len(up_batch),
    }


def hold(
    x: int,
    y: int,
    *,
    window: Any,
    button: str = "left",
    seconds: float = 1.0,
    platform: WindowsPlatform | None = None,
    restore: bool = True,
    timeout: float = 0.5,
    source_id: str | None = None,
    geometry_revision: int | None = None,
) -> dict[str, Any]:
    """Nhấn giữ chuột tại một điểm trong ``seconds`` giây rồi nhả."""
    p = platform or get_platform()
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, f"Nút chuột không hợp lệ: {button!r}", button=button)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    hwnd = check_preconditions(window, platform=p)
    check_point_ownership(x, y, hwnd, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    try:
        duration = max(0.05, min(MAX_HOLD_SEC, float(seconds)))
    except (TypeError, ValueError):
        duration = 1.0
    down_flag, up_flag = MOUSE_BUTTONS[button]
    up_event = mouse_input(0, 0, up_flag)
    down_batch = EventBatch(label="mouse_hold_down")
    down_batch.add(_move_event(int(x), int(y), p))
    down_batch.add(mouse_input(0, 0, down_flag))
    released = False
    try:
        _send_batch(p, down_batch)
        time.sleep(duration)
        _send_batch(p, EventBatch(label="mouse_hold_up", events=[up_event], pairs=[None]))
        released = True
    finally:
        if not released:
            _release_button(p, up_event)
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        "route": "send_input",
        "action": "hold",
        "button": button,
        "point": {"x": int(x), "y": int(y)},
        "seconds": round(duration, 3),
        "windowId": hwnd,
        "events": len(down_batch) + 1,
    }


def stroke(
    points: Any,
    *,
    window: Any,
    button: str = "left",
    platform: WindowsPlatform | None = None,
    restore: bool = True,
    timeout: float = 0.5,
    source_id: str | None = None,
    geometry_revision: int | None = None,
) -> dict[str, Any]:
    """Vẽ một nét tự do qua danh sách điểm: nhấn ở điểm đầu, đi qua từng điểm, nhả ở điểm cuối."""
    p = platform or get_platform()
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, f"Nút chuột không hợp lệ: {button!r}", button=button)
    path: list[tuple[int, int]] = []
    for point in points or ():
        try:
            px, py = point
            path.append((int(px), int(py)))
        except (TypeError, ValueError) as exc:
            raise PlatformError(SOURCE_CHANGED, f"Điểm của nét vẽ không hợp lệ: {point!r}") from exc
    if len(path) < 2:
        raise PlatformError(SOURCE_CHANGED, "Nét vẽ cần ít nhất hai điểm.", points=len(path))
    if len(path) > MAX_STROKE_POINTS:
        raise PlatformError(
            SOURCE_CHANGED,
            f"Nét vẽ có {len(path)} điểm, quá trần {MAX_STROKE_POINTS} — chia thành nhiều nét.",
            points=len(path),
        )
    check_geometry_revision(source_id, geometry_revision, platform=p)
    hwnd = check_preconditions(window, platform=p)
    check_point_ownership(path[0][0], path[0][1], hwnd, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    down_flag, up_flag = MOUSE_BUTTONS[button]
    up_event = mouse_input(0, 0, up_flag)
    down_batch = EventBatch(label="mouse_stroke_down")
    down_batch.add(_move_event(path[0][0], path[0][1], p))
    down_batch.add(mouse_input(0, 0, down_flag))
    move_batch = EventBatch(label="mouse_stroke_move")
    for px, py in path[1:]:
        move_batch.add(_move_event(px, py, p))
    released = False
    try:
        _send_batch(p, down_batch)
        time.sleep(GESTURE_SETTLE_SEC)
        _send_batch(p, move_batch)
        time.sleep(GESTURE_SETTLE_SEC)
        _send_batch(p, EventBatch(label="mouse_stroke_up", events=[up_event], pairs=[None]))
        released = True
    finally:
        if not released:
            _release_button(p, up_event)
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        "route": "send_input",
        "action": "stroke",
        "button": button,
        "points": len(path),
        "from": {"x": path[0][0], "y": path[0][1]},
        "to": {"x": path[-1][0], "y": path[-1][1]},
        "windowId": hwnd,
        "events": len(down_batch) + len(move_batch) + 1,
    }


def restore_context(
    previous_foreground: int | None,
    previous_cursor: tuple[int, int] | None,
    *,
    platform: WindowsPlatform | None = None,
) -> None:
    """Trả con trỏ và cửa sổ foreground về trạng thái trước thao tác (best-effort)."""
    p = platform or get_platform()
    if previous_cursor is not None:
        try:
            p.set_cursor_pos(previous_cursor[0], previous_cursor[1])
        except Exception:  # pragma: no cover - best effort
            pass
    if previous_foreground:
        try:
            p.set_foreground_window(int(previous_foreground))
        except Exception:  # pragma: no cover - best effort
            pass


# ---------------------------------------------------------------------------
# Bậc 2: bàn phím
# ---------------------------------------------------------------------------
def text_batch(text: str) -> EventBatch:
    """Sự kiện ``KEYEVENTF_UNICODE`` cho từng đơn vị UTF-16 (kể cả surrogate pair)."""
    batch = EventBatch(label="type_text")
    for unit in _utf16_units(text):
        batch.press(
            key_input(0, unit, KEYEVENTF_UNICODE),
            key_input(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
        )
    return batch


def modifier_batch(modifiers: list[int], key_down: INPUT, key_up: INPUT) -> EventBatch:
    """Bọc một lần nhấn phím trong các phím bổ trợ (nhả theo thứ tự ngược)."""
    batch = EventBatch(label="press_key")
    batch.combo(modifiers, key_down, key_up)
    return batch


def type_text(
    text: str,
    *,
    window: Any,
    element: Any = None,
    platform: WindowsPlatform | None = None,
    timeout: float = 0.5,
    source_id: str | None = None,
    geometry_revision: int | None = None,
) -> dict[str, Any]:
    """Gõ văn bản bằng ``KEYEVENTF_UNICODE`` (không phụ thuộc layout bàn phím)."""
    p = platform or get_platform()
    check_geometry_revision(source_id, geometry_revision, platform=p)
    if is_password_element(element):
        raise PlatformError(
            PASSWORD_FIELD_REFUSED,
            "Từ chối gõ vào ô mật khẩu (IsPassword) — BoxFox không nhập bí mật.",
        )
    if not text:
        return {"route": "send_input", "action": "type_text", "chars": 0, "windowId": None}
    if len(text) > MAX_TEXT_CHARS:
        raise PlatformError(
            SOURCE_CHANGED,
            f"Văn bản quá dài ({len(text)} > {MAX_TEXT_CHARS} ký tự) cho một lần gõ.",
            length=len(text),
        )
    hwnd = check_preconditions(window, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    units = _utf16_units(text)
    sent_units = 0
    try:
        for start in range(0, len(units), TEXT_CHUNK_UNITS):
            chunk = units[start : start + TEXT_CHUNK_UNITS]
            ensure_foreground(hwnd, platform=p, timeout=timeout, raise_window=False)
            batch = EventBatch(label="type_text")
            for unit in chunk:
                batch.press(
                    key_input(0, unit, KEYEVENTF_UNICODE),
                    key_input(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
                )
            _send_batch(p, batch)
            sent_units += len(chunk)
    finally:
        restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        "route": "send_input",
        "action": "type_text",
        "windowId": hwnd,
        "chars": len(text),
        "units": sent_units,
    }


def _utf16_units(text: str) -> list[int]:
    units: list[int] = []
    for char in text:
        encoded = char.encode("utf-16-le")
        for offset in range(0, len(encoded), 2):
            units.append(int.from_bytes(encoded[offset : offset + 2], "little"))
    return units


def press_key(
    key: str,
    *,
    window: Any,
    modifiers: list[str] | tuple[str, ...] = (),
    platform: WindowsPlatform | None = None,
    timeout: float = 0.5,
    source_id: str | None = None,
    geometry_revision: int | None = None,
) -> dict[str, Any]:
    """Nhấn một phím (tên trong :data:`VK_MAP`, hoặc một ký tự) kèm phím bổ trợ."""
    p = platform or get_platform()
    check_geometry_revision(source_id, geometry_revision, platform=p)
    modifier_vks = _modifier_vks(modifiers)
    name = (key or "").strip().lower()
    if name in VK_MAP:
        vk = VK_MAP[name]
        down = key_input(vk)
        up = key_input(vk, 0, KEYEVENTF_KEYUP)
    elif len(key) == 1:
        units = _utf16_units(key)
        if len(units) != 1:
            raise PlatformError(SOURCE_CHANGED, "Ký tự không nằm trong BMP.", key=key)
        down = key_input(0, units[0], KEYEVENTF_UNICODE)
        up = key_input(0, units[0], KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)
    else:
        raise PlatformError(SOURCE_CHANGED, f"Không hiểu tên phím: {key!r}", key=key)
    hwnd = check_preconditions(window, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    batch = modifier_batch(modifier_vks, down, up)
    try:
        _send_batch(p, batch)
    finally:
        restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        "route": "send_input",
        "action": "press_key",
        "key": name,
        "modifiers": list(modifiers),
        "windowId": hwnd,
        "events": len(batch),
    }


def _modifier_vks(modifiers: list[str] | tuple[str, ...]) -> list[int]:
    vks: list[int] = []
    for name in modifiers:
        normalized = str(name).strip().lower()
        if normalized not in MODIFIER_KEYS:
            raise PlatformError(SOURCE_CHANGED, f"Phím bổ trợ không hợp lệ: {name!r}", modifier=name)
        vks.append(MODIFIER_KEYS[normalized])
    return vks


# ---------------------------------------------------------------------------
# Bậc 1 (UIA) và bậc 3 (PostMessage)
# ---------------------------------------------------------------------------
#: Pattern UIA được phép dùng thay cho cú bấm thật.
UIA_ACTION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Invoke", "invoke"),
    ("Toggle", "toggle"),
    ("SelectionItem", "select"),
)


def click_element(
    token: str,
    *,
    window: Any = None,
    platform: WindowsPlatform | None = None,
    session: Any = None,
    timeout: float = 0.5,
) -> dict[str, Any]:
    """Thang ba bậc cho một phần tử: UIA pattern → SendInput → (không hỗ trợ)."""
    from . import uia as uia_module

    p = platform or get_platform()
    node = uia_module.resolve(token, platform=p, session=session)
    payload = getattr(node, "payload", {}) or {}
    patterns = list(getattr(node, "patterns", []) or [])
    for pattern, action in UIA_ACTION_PATTERNS:
        if pattern in patterns:
            result = uia_module.invoke(token, platform=p, session=session)
            return {
                "route": "uia_pattern",
                "action": action,
                "pattern": pattern,
                "elementToken": token,
                "windowId": payload.get("windowId"),
                "detail": result,
            }
    bounds = getattr(node, "bounds", None) or {}
    center_x = int(bounds.get("x", 0)) + int(bounds.get("width", 0)) // 2
    center_y = int(bounds.get("y", 0)) + int(bounds.get("height", 0)) // 2
    target = window if window is not None else payload.get("windowId")
    if target is None:
        raise PlatformError(SOURCE_CHANGED, "Phần tử không kèm cửa sổ đích cho cú bấm dự phòng.")
    result = click(center_x, center_y, window=target, platform=p, timeout=timeout)
    result["elementToken"] = token
    return result


def post_message_background(*_args: Any, **_kwargs: Any) -> Any:
    """Bậc 3 — **không** hiện thực trong H5 (xem docstring module)."""
    raise PlatformError(
        POST_MESSAGE_UNSUPPORTED,
        (
            "Gửi input nền bằng PostMessage chưa được hỗ trợ: phần lớn khung giao diện "
            "(Chromium, XAML, UWP, WPF, Tk, GTK, VCL) bỏ qua thông điệp được post mà "
            "không có sự kiện trong hàng đợi input của hệ thống."
        ),
    )
