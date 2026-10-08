"""Gửi chuột/bàn phím trên Linux/X11 bằng ``xdotool`` (XTEST).

``sandbox/win/input.py`` dựng cấu trúc ``INPUT`` và gọi ``SendInput`` — chỉ có trên Windows. Ở đây
giữ **nguyên hợp đồng** mà tầng trên gọi (``click``, ``type_text``, ``press_key`` và bộ chốt chặn
``check_preconditions``/``ensure_foreground``/``check_point_ownership``), nhưng đường gửi là
``xdotool`` qua XTEST — tức X server tự sinh sự kiện **như thiết bị thật**, nên ứng dụng không phân
biệt được với người dùng (khác hẳn ``XSendEvent`` mà Chrome/Electron bỏ qua).

Bốn chốt chặn giữ nguyên thứ tự của bản Windows, vì lý do của chúng không đổi:

1. ``check_geometry_revision`` — ảnh soi đã cũ ⇒ không bấm. (Chỉ chạy khi lớp gọi truyền
   ``source_id``/``geometry_revision``; đường ``computer_use`` hiện chưa truyền.)
2. ``check_preconditions`` — phiên tương tác, cửa sổ còn sống, không có UIPI (X11 không có).
3. ``check_point_ownership`` — điểm bấm phải thuộc đúng cửa sổ đích, nếu không là bị che. Chốt này
   chỉ thấy cửa sổ trong ``_NET_CLIENT_LIST_STACKING``; menu/tooltip override-redirect thì không.
4. ``ensure_foreground`` — cửa sổ đích phải đang có tiêu điểm, nếu không thì dừng thay vì gõ nhầm chỗ.

``type_text`` gửi theo từng khối 64 ký tự và **kiểm lại** tiêu điểm giữa các khối, đúng như bản
Windows: X11 không gắn bàn phím với một cửa sổ, nên gõ một mạch 4096 ký tự là gõ vào bất cứ cửa sổ
nào đang có tiêu điểm lúc đó.
"""
from __future__ import annotations

import re
import time
from typing import Any

from ..win.errors import (
    CAPTURE_FAILED,
    PASSWORD_FIELD_REFUSED,
    SESSION_NOT_INTERACTIVE,
    SOURCE_CHANGED,
    PlatformError,
)
from ..win.input import MAX_TEXT_CHARS, is_password_element
from . import platform as x11_platform

#: Nút chuột theo số hiệu X11 (1 = trái, 2 = giữa, 3 = phải).
MOUSE_BUTTONS = {'left': 1, 'middle': 2, 'right': 3}

#: Nhịp gõ mặc định (ms/ký tự) — đủ chậm để ứng dụng không nuốt ký tự, đủ nhanh để không chờ lâu.
TYPE_DELAY_MS = 12

#: Số ký tự mỗi khối ``xdotool type``. Giữa hai khối ta kiểm lại tiêu điểm, nên khối càng nhỏ thì
#: khe hở "gõ nhầm cửa sổ" càng hẹp — 64 khớp với ``TEXT_CHUNK_UNITS`` của bản Windows.
TEXT_CHUNK_CHARS = 64

#: Tên phím của Windows/``keysym`` → tên phím của X11. Không có bảng này thì "Enter" thành "enter"
#: và ``xdotool`` báo lỗi khó hiểu.
_KEY_NAMES = {
    'enter': 'Return', 'return': 'Return', 'esc': 'Escape', 'escape': 'Escape',
    'backspace': 'BackSpace', 'back': 'BackSpace', 'delete': 'Delete', 'del': 'Delete',
    'tab': 'Tab', 'space': 'space', 'spacebar': 'space', 'insert': 'Insert',
    'up': 'Up', 'down': 'Down', 'left': 'Left', 'right': 'Right',
    'pageup': 'Prior', 'pagedown': 'Next', 'pgup': 'Prior', 'pgdn': 'Next',
    'home': 'Home', 'end': 'End', 'printscreen': 'Print', 'capslock': 'Caps_Lock',
    'numlock': 'Num_Lock', 'scrolllock': 'Scroll_Lock', 'pause': 'Pause',
    'menu': 'Menu', 'apps': 'Menu', 'windows': 'Super_L',
    'ctrl': 'ctrl', 'control': 'ctrl', 'alt': 'alt', 'shift': 'shift',
    'win': 'super', 'meta': 'super', 'cmd': 'super', 'super': 'super', 'option': 'alt',
}

for _index in range(1, 25):
    _KEY_NAMES['f%d' % _index] = 'F%d' % _index

#: Phím bổ trợ hợp lệ trong ``modifiers``.
_MODIFIER_NAMES = {'ctrl': 'ctrl', 'control': 'ctrl', 'alt': 'alt', 'shift': 'shift',
                   'win': 'super', 'meta': 'super', 'cmd': 'super', 'super': 'super'}


def _platform(platform: Any = None) -> Any:
    chosen = platform if platform is not None else x11_platform.get_platform()
    if chosen is None:
        raise PlatformError(CAPTURE_FAILED, 'máy này không có nền tảng X11 để gửi input.')
    return chosen


def _xdotool(platform: Any, *args: str, timeout: float = 5.0) -> Any:
    tool = platform._tool('xdotool')
    if tool is None:
        raise PlatformError(
            x11_platform.X11_UNAVAILABLE,
            'thiếu `xdotool` — cài gói xdotool để điều khiển chuột/bàn phím trên Linux.',
            tool='xdotool',
        )
    return platform._run([tool, *args], timeout=timeout)


def _fail(result: Any, action: str, **details: Any) -> None:
    if result.ok:
        return
    raise PlatformError(
        SOURCE_CHANGED,
        'X11 từ chối `%s`: %s' % (action, (result.err or '').strip()[:200]),
        action=action,
        exit_code=result.code,
        **details,
    )


# ---------------------------------------------------------------------------
# Chốt chặn
# ---------------------------------------------------------------------------
def resolve_window(window: Any, *, platform: Any = None) -> int:
    """Nhận ``WindowInfo``/id/``None`` → id cửa sổ X11."""
    if window is None:
        raise PlatformError(SOURCE_CHANGED, 'thiếu cửa sổ đích cho thao tác input.')
    value = getattr(window, 'hwnd', window)
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise PlatformError(SOURCE_CHANGED, 'cửa sổ đích không hợp lệ: %r' % (value,)) from exc


def check_integrity(pid: int | None, *, platform: Any = None) -> None:
    """X11 không có UIPI ⇒ không có gì để so. Giữ hàm để chỗ gọi không phải rẽ nhánh."""
    return None


def check_desktop(*, platform: Any = None) -> None:
    p = _platform(platform)
    if not p.is_interactive_session():
        raise PlatformError(
            SESSION_NOT_INTERACTIVE,
            'không kết nối được X server (DISPLAY sai hoặc X server đã tắt) — không gửi input.',
            display=p.display,
        )


def check_preconditions(window: Any, *, pid: int | None = None, platform: Any = None) -> int:
    """Toàn bộ chốt chặn trước khi gửi; trả về id cửa sổ đã chuẩn hoá."""
    p = _platform(platform)
    hwnd = resolve_window(window, platform=p)
    check_desktop(platform=p)
    if not p.is_window(hwnd):
        raise PlatformError(SOURCE_CHANGED, 'cửa sổ %d không còn tồn tại.' % hwnd, hwnd=hwnd)
    if pid is None:
        pid = p.get_window_pid(hwnd)
    check_integrity(pid, platform=p)
    return hwnd


def check_point_ownership(x: int, y: int, hwnd: int, *, platform: Any = None) -> None:
    """Điểm bấm phải thuộc cửa sổ đích — nếu không, cửa sổ đã bị che từ lúc soi."""
    p = _platform(platform)
    top = p.window_from_point(int(x), int(y))
    root = (p.get_ancestor_root(top) or top) if top else None
    if root is None or int(root) != int(hwnd):
        raise PlatformError(
            SOURCE_CHANGED,
            'điểm bấm đang bị cửa sổ khác che — không gửi input.',
            reason='occluded',
            point={'x': int(x), 'y': int(y)},
            window_at_point=None if root is None else int(root),
            hwnd=int(hwnd),
        )


def check_geometry_revision(source_id: str | None, revision: int | None, *,
                            platform: Any = None) -> None:
    """Input mang ``geometryRevision`` cũ ⇒ ``SOURCE_CHANGED`` (dùng chung với bản Windows)."""
    if not source_id or revision is None:
        return
    from ..win.capture import current_geometry_revision

    current = current_geometry_revision(str(source_id))
    if current is None or int(current) != int(revision):
        raise PlatformError(
            SOURCE_CHANGED,
            'cửa sổ đã đổi hình học kể từ lúc soi (revision %s → %s) — soi lại trước khi thao tác.'
            % (revision, current),
            reason='geometry_changed',
            source_id=str(source_id),
            revision=int(revision),
            current_revision=current,
        )


# ---------------------------------------------------------------------------
# Tiêu điểm
# ---------------------------------------------------------------------------
def foreground_matches(hwnd: int, *, platform: Any = None) -> bool:
    p = _platform(platform)
    current = p.get_foreground_window()
    if not current:
        return False
    if int(current) == int(hwnd):
        return True
    root = p.get_ancestor_root(current)
    return bool(root) and int(root) == int(hwnd)


def ensure_foreground(hwnd: int, *, platform: Any = None, timeout: float = 0.5,
                      interval: float = 0.02, raise_window: bool = True) -> None:
    """Bảo đảm cửa sổ đích đang có tiêu điểm, nếu không thì ``SOURCE_CHANGED``.

    X11 có cửa sổ "focus follows mouse": con trỏ nằm ở cửa sổ khác vẫn có thể cướp tiêu điểm ngay
    sau khi ta kích hoạt. Vì vậy phải *kiểm lại* sau khi kích hoạt, đúng như bản Windows.
    """
    p = _platform(platform)
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
            'cửa sổ đích không giữ được tiêu điểm — không gửi input để tránh gõ nhầm chỗ.',
            hwnd=int(hwnd),
            foreground=p.get_foreground_window(),
        )


def restore_context(previous_foreground: Any, previous_cursor: Any, *, platform: Any = None) -> None:
    """Trả con trỏ và tiêu điểm về trạng thái trước thao tác (best-effort)."""
    p = _platform(platform)
    if previous_cursor is not None:
        try:
            p.set_cursor_pos(int(previous_cursor[0]), int(previous_cursor[1]))
        except Exception:       # pragma: no cover - best effort
            pass
    if previous_foreground:
        try:
            p.set_foreground_window(int(previous_foreground))
        except Exception:       # pragma: no cover - best effort
            pass


# ---------------------------------------------------------------------------
# Chuột
# ---------------------------------------------------------------------------
def click(x: int, y: int, *, window: Any, button: str = 'left', platform: Any = None,
          restore: bool = True, timeout: float = 0.5, source_id: str | None = None,
          geometry_revision: int | None = None) -> dict[str, Any]:
    """Bấm một điểm trên cửa sổ đích bằng XTEST (``xdotool mousemove`` + ``click``)."""
    p = _platform(platform)
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, 'nút chuột không hợp lệ: %r' % (button,), button=button)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    hwnd = check_preconditions(window, platform=p)
    check_point_ownership(x, y, hwnd, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    try:
        # Ghi vị trí con trỏ mà CHÍNH TA sắp đặt TRƯỚC khi di chuyển: bộ theo dõi "người thật chạm
        # máy" lấy mẫu ở luồng khác, nên ghi sau khi di chuyển là có một khe hở để nó đọc cú di
        # chuyển của chính ta thành người thật. Ghi sớm mà lệnh hỏng thì cùng lắm là nhả quyền về
        # tay người — hướng an toàn.
        p.note_own_pointer(int(x), int(y))
        moved = _xdotool(p, 'mousemove', '--sync', str(int(x)), str(int(y)))
        _fail(moved, 'mousemove', point={'x': int(x), 'y': int(y)})
        pressed = _xdotool(p, 'click', str(MOUSE_BUTTONS[button]))
        _fail(pressed, 'click', button=button)
    finally:
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        'route': 'xtest',
        'action': 'click',
        'button': button,
        'point': {'x': int(x), 'y': int(y)},
        'windowId': hwnd,
        'events': 3,
    }


# ---------------------------------------------------------------------------
# Bàn phím
# ---------------------------------------------------------------------------
def _key_name(key: str) -> str:
    text = str(key or '').strip()
    if not text:
        raise PlatformError(SOURCE_CHANGED, 'thiếu tên phím cho thao tác `key`.')
    if len(text) == 1:
        return text
    mapped = _KEY_NAMES.get(text.casefold())
    if mapped:
        return mapped
    if re.fullmatch(r'[A-Za-z0-9_]+', text):
        return text
    raise PlatformError(SOURCE_CHANGED, 'tên phím không hợp lệ: %r' % (key,), key=key)


def _combo(key: str, modifiers: Any) -> str:
    parts: list[str] = []
    for name in modifiers or ():
        folded = str(name).strip().casefold()
        if not folded:
            continue
        mapped = _MODIFIER_NAMES.get(folded)
        if mapped is None:
            raise PlatformError(SOURCE_CHANGED, 'phím bổ trợ không hợp lệ: %r' % (name,),
                                modifier=str(name))
        parts.append(mapped)
    parts.append(_key_name(key))
    return '+'.join(parts)


def type_text(text: str, *, window: Any, element: Any = None, platform: Any = None,
              timeout: float = 0.5, source_id: str | None = None,
              geometry_revision: int | None = None) -> dict[str, Any]:
    """Gõ văn bản bằng XTEST (``xdotool type``) — không phụ thuộc layout bàn phím của tiến trình."""
    p = _platform(platform)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    if is_password_element(element):
        raise PlatformError(
            PASSWORD_FIELD_REFUSED,
            'từ chối gõ vào ô mật khẩu (IsPassword) — BoxFox không nhập bí mật.',
        )
    if not text:
        return {'route': 'xtest', 'action': 'type_text', 'chars': 0, 'windowId': None}
    if len(text) > MAX_TEXT_CHARS:
        raise PlatformError(
            SOURCE_CHANGED,
            'văn bản quá dài (%d > %d ký tự) cho một lần gõ.' % (len(text), MAX_TEXT_CHARS),
            length=len(text),
        )
    hwnd = check_preconditions(window, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    sent = 0
    try:
        for start in range(0, len(text), TEXT_CHUNK_CHARS):
            chunk = text[start:start + TEXT_CHUNK_CHARS]
            # Không nâng cửa sổ lại (người dùng có thể đã cố tình đổi), chỉ KIỂM: mất tiêu điểm
            # giữa chừng ⇒ dừng ngay, phần còn lại không rơi vào cửa sổ của người.
            ensure_foreground(hwnd, platform=p, timeout=timeout, raise_window=False)
            result = _xdotool(p, 'type', '--clearmodifiers', '--delay', str(TYPE_DELAY_MS), '--',
                              chunk, timeout=max(5.0, 0.05 * len(chunk) + 2.0))
            _fail(result, 'type')
            sent += len(chunk)
    finally:
        restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        'route': 'xtest',
        'action': 'type_text',
        'windowId': hwnd,
        'chars': len(text),
        'units': sent,
    }


def press_key(key: str, *, modifiers: Any = (), window: Any, element: Any = None,
              platform: Any = None, timeout: float = 0.5, source_id: str | None = None,
              geometry_revision: int | None = None) -> dict[str, Any]:
    """Nhấn một phím (kèm phím bổ trợ) vào cửa sổ đích bằng XTEST."""
    p = _platform(platform)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    if is_password_element(element):
        raise PlatformError(
            PASSWORD_FIELD_REFUSED,
            'từ chối nhấn phím trong ô mật khẩu (IsPassword) — BoxFox không nhập bí mật.',
        )
    combo = _combo(key, modifiers)
    hwnd = check_preconditions(window, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    try:
        result = _xdotool(p, 'key', '--clearmodifiers', combo)
        _fail(result, 'key', combo=combo)
    finally:
        restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        'route': 'xtest',
        'action': 'press_key',
        'windowId': hwnd,
        'key': _key_name(key),
        'combo': combo,
        'events': 2 + 2 * len([part for part in (modifiers or ()) if str(part).strip()]),
    }
