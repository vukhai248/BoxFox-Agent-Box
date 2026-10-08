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

#: Khoảng giữa lúc NHẤN và lúc NHẢ chuột (ms). ``xdotool click`` mặc định 100 ms và ta trả đủ số đó
#: cho mỗi cú bấm (đo được: 102 ms một cú, tức gần một nửa giá thành của ``click``). 12 ms là mức
#: thông thường của XTEST và đã kiểm lại trên terminal, VS Code và Chrome.
CLICK_DELAY_MS = 12

#: Nút cuộn của X11: 4 = lên, 5 = xuống, 6 = trái, 7 = phải. Đây là quy ước của X server, không
#: phải lựa chọn của ta — ``xdotool click 4`` chính là một nấc cuộn lên.
SCROLL_BUTTONS = {'up': 4, 'down': 5, 'left': 6, 'right': 7}

#: Nhịp giữa hai nấc cuộn (ms). Chrome/GTK gộp các sự kiện dày quá thành một cú nhảy, còn quá thưa
#: thì cuộn thành từng khúc rời. 12 ms là mức đã kiểm trên Chrome và trên danh sách dài của GTK.
SCROLL_STEP_DELAY_MS = 12

#: Trần số nấc cho một lệnh cuộn. 20 nấc ≈ một màn hình; xa hơn thì nên cuộn nhiều lần để còn nhìn
#: thấy mình đang ở đâu (đúng cách người thật làm).
MAX_SCROLL_STEPS = 20

#: Số điểm dừng trên đường kéo. Ít quá thì ứng dụng thấy một cú nhảy thay vì một cú kéo; nhiều quá thì
#: mỗi điểm là một tiến trình ``xdotool``. 12 điểm cho quãng vài trăm pixel là mức đã kiểm.
DRAG_STEPS = 12

#: Trần số điểm dừng (kéo qua màn hình rộng vẫn không nên sinh hàng trăm tiến trình).
MAX_DRAG_STEPS = 60

#: Khoảng nghỉ ngay sau khi NHẤN và ngay trước khi NHẢ (giây). Ứng dụng GTK/Cairo coi cú nhấn-rồi-nhả
#: trong cùng một khung hình là **cú bấm**, không phải cú kéo — phải có khe hở thật thì mới thành kéo.
GESTURE_SETTLE_SEC = 0.03

#: Nhịp giữa hai điểm dừng của cú kéo (giây).
DRAG_STEP_SEC = 0.01

#: Nhịp giữa hai điểm của nét vẽ tự do (giây). Dày hơn cú kéo vì nét vẽ trông thô ngay khi thưa.
STROKE_STEP_SEC = 0.008

#: Trần thời gian giữ chuột của ``hold`` (giây) — giữ lâu hơn thì nên là nhiều lệnh, không phải một.
MAX_HOLD_SEC = 5.0

#: Trần số điểm của một nét vẽ. Mỗi điểm là một tiến trình, nên 400 điểm ≈ 2 s là mức tối đa hợp lý.
MAX_STROKE_POINTS = 400

#: Số ký tự mỗi khối ``xdotool type``. Giữa hai khối ta kiểm lại tiêu điểm, nên khối càng nhỏ thì
#: khe hở "gõ nhầm cửa sổ" càng hẹp — 64 khớp với ``TEXT_CHUNK_UNITS`` của bản Windows.
TEXT_CHUNK_CHARS = 64


def typing_chunks(text: str, *, size: int = TEXT_CHUNK_CHARS) -> list[str]:
    """Chia văn bản thành các khối để gõ: ký tự ngoài ASCII đi **một mình một lệnh**.

    Đo trên máy thật (08/10/2026, Chrome, X server có tải vì đang quay phim màn hình): gõ cả câu
    trong một lệnh làm **mất 1–2 ký tự có dấu ở 3/6 lượt**, còn mỗi ký tự ngoài ASCII một lệnh thì
    **6/6 lượt đủ** (490 ms so với 241 ms cho câu 29 ký tự). Lý do: ``xdotool`` phải ánh xạ tạm một
    keycode trống cho mỗi ký tự ngoài ASCII rồi trả lại; máy bận thì ứng dụng đọc sự kiện sau lúc
    ánh xạ đã bị trả lại, và ký tự mất hẳn — thao tác vẫn báo thành công.

    Ký tự ASCII không dính lỗi đó, nên chúng vẫn đi theo khối 64 ký tự cho nhanh.

    Đây là đường **dự phòng**: ``type_text`` còn có đường tốt hơn (ánh xạ sẵn keysym vào keycode
    trống) khi ``xmodmap`` dùng được — xem :func:`keysym_plan`.
    """
    chunks: list[str] = []
    run = ''
    for char in text:
        if ord(char) < 128:
            run += char
            if len(run) >= size:
                chunks.append(run)
                run = ''
            continue
        if run:
            chunks.append(run)
            run = ''
        chunks.append(char)
    if run:
        chunks.append(run)
    return chunks


#: Số keycode trống tối đa ta chiếm cùng lúc để ánh xạ keysym Unicode. Máy này có 30 chỗ trống;
#: giữ trần thấp để không đụng vào vùng keycode mà bố cục bàn phím khác có thể dùng.
MAX_REMAPPED_KEYCODES = 10


def keysym_name(char: str) -> str:
    """Tên keysym Unicode của một ký tự: ``đ`` → ``U0111``."""
    return 'U%04X' % ord(char)


def _spare_keycodes(platform: Any) -> list[int]:
    """Các keycode chưa gán keysym nào, ưu tiên số lớn (vùng ``xdotool`` vẫn dùng để ánh xạ tạm)."""
    tool = platform._tool('xmodmap')
    if tool is None:
        return []
    result = platform._run([tool, '-pke'])
    if not result.ok:
        return []
    spare: list[int] = []
    for line in result.out.splitlines():
        fields = line.split()
        # `keycode 249 =` — dấu `=` đứng ngay sau số hiệu nghĩa là không có keysym nào.
        if len(fields) == 3 and fields[0] == 'keycode' and fields[2] == '=':
            try:
                spare.append(int(fields[1]))
            except ValueError:
                continue
    spare.sort(reverse=True)
    return spare


def keysym_plan(platform: Any, chars: list[str]) -> dict[str, int]:
    """Ánh xạ các ký tự ngoài ASCII vào keycode trống **một lần cho cả lần gõ**; trả ``{}`` nếu không được.

    Vì sao không để ``xdotool type`` tự lo: nó ánh xạ rồi **trả lại ngay** cho từng ký tự, nên khi
    máy bận, ứng dụng đọc sự kiện sau lúc ánh xạ đã bị trả lại ⇒ ký tự mất hẳn; và với chữ hoa
    Latin-1/2 thì nó gửi nhầm chữ thường (đo được: ``Á`` → ``á``). Ánh xạ **giữ nguyên trong suốt
    lần gõ** thì ứng dụng luôn đọc đúng, kể cả chữ hoa: đo trên máy thật 08/10/2026,
    ``ÁÀẢĐÊÔƠƯỔỢ`` đi đúng từng ký tự (trước đó mất hoa 16/26 ký tự).

    Trả về ``{kí tự: keycode}``; người gọi phải trả keycode về ``NoSymbol`` sau khi gõ xong.
    """
    unique = list(dict.fromkeys(char for char in chars if ord(char) >= 128))
    if not unique:
        return {}
    spare = _spare_keycodes(platform)
    if len(spare) < len(unique):
        return {}
    chosen = spare[:len(unique)]
    tool = platform._tool('xmodmap')
    if tool is None:
        return {}
    args: list[str] = []
    for char, keycode in zip(unique, chosen):
        args += ['-e', 'keycode %d = %s' % (keycode, keysym_name(char))]
    result = platform._run([tool] + args, timeout=5.0)
    if not result.ok:
        return {}
    return dict(zip(unique, chosen))


def release_keycodes(platform: Any, keycodes: Any) -> None:
    """Trả các keycode đã chiếm về trạng thái trống (``NoSymbol``)."""
    values = [int(code) for code in keycodes]
    if not values:
        return
    tool = platform._tool('xmodmap')
    if tool is None:
        return
    args: list[str] = []
    for keycode in values:
        args += ['-e', 'keycode %d = NoSymbol' % keycode]
    platform._run([tool] + args, timeout=5.0)

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
    """Điểm bấm phải thuộc cửa sổ đích — nếu không, cửa sổ đã bị che từ lúc soi.

    Cửa sổ của **chính ứng dụng đích** cũng được nhận: hộp thoại modal của ứng dụng (VS Code,
    Chrome, trình soạn thảo…) nằm trên cửa sổ đích và có tiêu điểm, nên nếu từ chối thì agent vừa
    không bấm được nút của hộp thoại, vừa không làm gì được với cửa sổ chính — chết cứng.
    """
    p = _platform(platform)
    # Đọc lại hình học cửa sổ đích NGAY TRƯỚC khi soi điểm. Bộ đệm 0,5 s rất rẻ, nhưng nếu người
    # dùng vừa di chuyển cửa sổ đích thì hình học cũ vẫn chứa điểm bấm, chốt sẽ cho qua một cú bấm
    # thật ra rơi vào cửa sổ khác. Một lệnh `xwininfo` để đổi lấy điều đó là rẻ.
    p.get_window_rect(int(hwnd), fresh=True)
    top = p.window_from_point(int(x), int(y))
    root = (p.get_ancestor_root(top) or top) if top else None
    if root is None or not p.is_own_window(hwnd, root):
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
    """Cửa sổ đích (hoặc hộp thoại của chính nó) đang có tiêu điểm?

    Nhận cả hộp thoại của ứng dụng đích: khi ứng dụng mở hộp thoại modal, WM **không cho** cửa sổ
    chính lấy lại tiêu điểm, nên đòi hỏi tuyệt đối là tự khoá mọi thao tác bàn phím vào ứng dụng.
    """
    p = _platform(platform)
    current = p.get_foreground_window()
    if not current:
        return False
    # ``is_own_window`` đã nhận cả trường hợp ``current`` CHÍNH LÀ cửa sổ đích (nó so danh tính
    # trước khi đi theo chuỗi chủ sở hữu), và X11 chỉ trả về cửa sổ cấp cao nhất trong
    # ``_NET_ACTIVE_WINDOW``. Nhánh ``get_ancestor_root`` cũ không bao giờ thêm được kết quả ĐÚNG nào
    # mà mỗi vòng chờ lại tốn thêm một lệnh ``xprop``.
    return p.is_own_window(hwnd, current)


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
        # `mousemove --sync` chờ một sự kiện MotionNotify tới đúng toạ độ; con trỏ đã ở đúng chỗ thì
        # X server KHÔNG sinh sự kiện nào và `xdotool` chờ tới hết thời gian chờ (đo được: bấm hai
        # lần liên tiếp vào cùng một điểm làm lần thứ hai treo đủ 5 s rồi báo `SOURCE_CHANGED`).
        # Vì vậy con trỏ đã ở đúng chỗ thì đi KHÔNG đồng bộ — vẫn kéo con trỏ về đúng điểm đã kiểm
        # quyền nếu người thật vừa di chuột trong lúc chờ tiêu điểm, mà không chờ sự kiện không tới.
        if previous_cursor != (int(x), int(y)):
            moved = _xdotool(p, 'mousemove', '--sync', str(int(x)), str(int(y)))
        else:
            moved = _xdotool(p, 'mousemove', str(int(x)), str(int(y)))
        _fail(moved, 'mousemove', point={'x': int(x), 'y': int(y)})
        pressed = _xdotool(p, 'click', '--delay', str(CLICK_DELAY_MS), str(MOUSE_BUTTONS[button]))
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


def _prepare_point(x: int, y: int, *, window: Any, platform: Any = None, timeout: float = 0.5,
                   source_id: str | None = None, geometry_revision: int | None = None) -> tuple:
    """Bốn chốt chặn của một thao tác bắt đầu bằng một điểm, trả ``(p, hwnd, tiêu điểm, con trỏ)``.

    Dùng chung cho ``click``, ``scroll``, ``drag``, ``hold`` và ``stroke``: cả năm đều bắt đầu bằng
    "điểm này phải thuộc cửa sổ đích, và cửa sổ đích phải đang có tiêu điểm".
    """
    p = _platform(platform)
    check_geometry_revision(source_id, geometry_revision, platform=p)
    hwnd = check_preconditions(window, platform=p)
    check_point_ownership(int(x), int(y), hwnd, platform=p)
    previous_foreground = p.get_foreground_window()
    previous_cursor = p.get_cursor_pos()
    ensure_foreground(hwnd, platform=p, timeout=timeout)
    return p, hwnd, previous_foreground, previous_cursor


def _move_to(p: Any, x: int, y: int, *, sync: bool = False) -> None:
    """Di chuyển con trỏ, có ghi lại vị trí là "của chính ta" TRƯỚC khi di chuyển.

    Ghi sớm là cố ý: bộ theo dõi "người thật chạm máy" lấy mẫu ở luồng khác, nên ghi sau khi di
    chuyển là có một khe hở để nó đọc cú di chuyển của chính ta thành người thật. Ghi sớm mà lệnh
    hỏng thì cùng lắm là nhả quyền về tay người — hướng an toàn.

    ``sync`` chỉ dùng cho điểm ĐẦU TIÊN: ``mousemove --sync`` chờ một sự kiện ``MotionNotify`` tới
    đúng toạ độ, mà con trỏ đã ở đúng chỗ thì X server không sinh sự kiện nào (đo được: treo đủ 5 s).
    Các điểm giữa của cú kéo đi KHÔNG đồng bộ — chúng bắt buộc phải sinh sự kiện vì con trỏ đang đi.
    """
    p.note_own_pointer(int(x), int(y))
    if sync:
        result = _xdotool(p, 'mousemove', '--sync', str(int(x)), str(int(y)))
    else:
        result = _xdotool(p, 'mousemove', str(int(x)), str(int(y)))
    _fail(result, 'mousemove', point={'x': int(x), 'y': int(y)})


def _release_button(p: Any, code: int) -> None:
    """Nhả nút chuột, nuốt mọi lỗi. Dùng trong ``finally`` — không được che lỗi thật của thân hàm."""
    try:
        _xdotool(p, 'mouseup', str(int(code)))
    except Exception:       # pragma: no cover - best effort, đường thoát cuối
        pass


def scroll(x: int, y: int, *, window: Any, direction: str = 'down', steps: int = 3,
           platform: Any = None, restore: bool = True, timeout: float = 0.5,
           source_id: str | None = None, geometry_revision: int | None = None) -> dict[str, Any]:
    """Cuộn con lăn tại một điểm, đúng cửa sổ dưới con trỏ.

    X11 gửi sự kiện con lăn cho **cửa sổ nằm dưới con trỏ**, nên phải đưa con trỏ vào đúng cửa sổ
    đích trước (và đã qua chốt ``check_point_ownership``) rồi mới cuộn — cuộn mà không nhìn con trỏ
    là cuộn nhầm cửa sổ.
    """
    p = _platform(platform)
    if direction not in SCROLL_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, 'hướng cuộn không hợp lệ: %r' % (direction,),
                            direction=direction)
    p, hwnd, previous_foreground, previous_cursor = _prepare_point(
        x, y, window=window, platform=p, timeout=timeout, source_id=source_id,
        geometry_revision=geometry_revision)
    try:
        count = max(1, min(MAX_SCROLL_STEPS, int(steps)))
    except (TypeError, ValueError):
        count = 3
    button = SCROLL_BUTTONS[direction]
    try:
        _move_to(p, int(x), int(y), sync=previous_cursor != (int(x), int(y)))
        # Một tiến trình cho cả loạt nấc: `--repeat` sinh đúng số sự kiện nhấn-rồi-nhả cách nhau
        # `--delay`, rẻ hơn nhiều so với gọi `xdotool` từng nấc.
        rolled = _xdotool(p, 'click', '--repeat', str(count), '--delay',
                          str(SCROLL_STEP_DELAY_MS), str(button))
        _fail(rolled, 'scroll', direction=direction)
    finally:
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    return {
        'route': 'xtest',
        'action': 'scroll',
        'direction': direction,
        'steps': count,
        'point': {'x': int(x), 'y': int(y)},
        'windowId': hwnd,
        'events': count * 2,
    }


def drag(x: int, y: int, to_x: int, to_y: int, *, window: Any, button: str = 'left',
         steps: int = DRAG_STEPS, platform: Any = None, restore: bool = True, timeout: float = 0.5,
         guard_end: bool = True, source_id: str | None = None,
         geometry_revision: int | None = None) -> dict[str, Any]:
    """Kéo từ điểm này sang điểm khác: nhấn, đi từng bước, nhả.

    ``guard_end`` kiểm cả điểm ĐÍCH có thuộc cửa sổ đích không. Bật khi đích của phiên là một cửa sổ
    (mọi thứ phải nằm trong cửa sổ đó), tắt khi đích là **cả máy** — lúc đó kéo từ cửa sổ này sang
    cửa sổ khác (thả tệp vào một ứng dụng khác, kéo thẻ trình duyệt ra ngoài) là việc hợp lệ.

    Nút chuột được nhả trong ``finally``: một nút còn giữ là cả máy không dùng được nữa, kể cả khi
    bước giữa của cú kéo hỏng.
    """
    p = _platform(platform)
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, 'nút chuột không hợp lệ: %r' % (button,), button=button)
    start_x, start_y, end_x, end_y = int(x), int(y), int(to_x), int(to_y)
    p, hwnd, previous_foreground, previous_cursor = _prepare_point(
        start_x, start_y, window=window, platform=p, timeout=timeout, source_id=source_id,
        geometry_revision=geometry_revision)
    if guard_end:
        check_point_ownership(end_x, end_y, hwnd, platform=p)
    try:
        count = max(1, min(MAX_DRAG_STEPS, int(steps)))
    except (TypeError, ValueError):
        count = DRAG_STEPS
    code = MOUSE_BUTTONS[button]
    released = None
    try:
        _move_to(p, start_x, start_y, sync=previous_cursor != (start_x, start_y))
        _fail(_xdotool(p, 'mousedown', str(code)), 'mousedown', button=button)
        time.sleep(GESTURE_SETTLE_SEC)
        for index in range(1, count + 1):
            step_x = round(start_x + (end_x - start_x) * index / count)
            step_y = round(start_y + (end_y - start_y) * index / count)
            _move_to(p, step_x, step_y)
            if index < count:
                time.sleep(DRAG_STEP_SEC)
        time.sleep(GESTURE_SETTLE_SEC)
        released = _xdotool(p, 'mouseup', str(code))
    finally:
        if released is None:
            _release_button(p, code)
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    _fail(released, 'mouseup', button=button)
    return {
        'route': 'xtest',
        'action': 'drag',
        'button': button,
        'from': {'x': start_x, 'y': start_y},
        'to': {'x': end_x, 'y': end_y},
        'steps': count,
        'windowId': hwnd,
        'events': count + 3,
    }


def hold(x: int, y: int, *, window: Any, button: str = 'left', seconds: float = 1.0,
         platform: Any = None, restore: bool = True, timeout: float = 0.5,
         source_id: str | None = None, geometry_revision: int | None = None) -> dict[str, Any]:
    """Nhấn giữ chuột tại một điểm trong ``seconds`` giây rồi nhả.

    Dùng cho những chỗ ứng dụng phân biệt "bấm" với "giữ": nhấn giữ để mở menu ngữ cảnh, giữ nút
    tăng tốc, hay giữ chuột phải để hiện bảng chọn. Nút chuột được nhả trong ``finally``.
    """
    p = _platform(platform)
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, 'nút chuột không hợp lệ: %r' % (button,), button=button)
    p, hwnd, previous_foreground, previous_cursor = _prepare_point(
        x, y, window=window, platform=p, timeout=timeout, source_id=source_id,
        geometry_revision=geometry_revision)
    try:
        duration = max(0.05, min(MAX_HOLD_SEC, float(seconds)))
    except (TypeError, ValueError):
        duration = 1.0
    code = MOUSE_BUTTONS[button]
    released = None
    try:
        _move_to(p, int(x), int(y), sync=previous_cursor != (int(x), int(y)))
        _fail(_xdotool(p, 'mousedown', str(code)), 'mousedown', button=button)
        time.sleep(duration)
        released = _xdotool(p, 'mouseup', str(code))
    finally:
        if released is None:
            _release_button(p, code)
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    _fail(released, 'mouseup', button=button)
    return {
        'route': 'xtest',
        'action': 'hold',
        'button': button,
        'point': {'x': int(x), 'y': int(y)},
        'seconds': round(duration, 3),
        'windowId': hwnd,
        'events': 3,
    }


def stroke(points: Any, *, window: Any, button: str = 'left', platform: Any = None,
           restore: bool = True, timeout: float = 0.5, source_id: str | None = None,
           geometry_revision: int | None = None) -> dict[str, Any]:
    """Vẽ một nét tự do qua danh sách điểm: nhấn ở điểm đầu, đi qua từng điểm, nhả ở điểm cuối.

    Đây là "kéo" nhưng cho nhiều điểm, tức là cú kéo mà ứng dụng vẽ (Paint, công cụ chú thích ảnh,
    bảng vẽ). Mỗi điểm là một lệnh ``xdotool``, nên trần ``MAX_STROKE_POINTS`` giữ cho một nét không
    biến thành một lượt chạy dài.
    """
    p = _platform(platform)
    if button not in MOUSE_BUTTONS:
        raise PlatformError(SOURCE_CHANGED, 'nút chuột không hợp lệ: %r' % (button,), button=button)
    path = []
    for point in (points or ()):
        try:
            px, py = point
            path.append((int(px), int(py)))
        except (TypeError, ValueError) as exc:
            raise PlatformError(SOURCE_CHANGED, 'điểm của nét vẽ không hợp lệ: %r' % (point,)) from exc
    if len(path) < 2:
        raise PlatformError(SOURCE_CHANGED, 'nét vẽ cần ít nhất hai điểm.', points=len(path))
    if len(path) > MAX_STROKE_POINTS:
        raise PlatformError(SOURCE_CHANGED,
                            'nét vẽ có %d điểm, quá trần %d — chia thành nhiều nét.'
                            % (len(path), MAX_STROKE_POINTS), points=len(path))
    start_x, start_y = path[0]
    p, hwnd, previous_foreground, previous_cursor = _prepare_point(
        start_x, start_y, window=window, platform=p, timeout=timeout, source_id=source_id,
        geometry_revision=geometry_revision)
    code = MOUSE_BUTTONS[button]
    released = None
    try:
        _move_to(p, start_x, start_y, sync=previous_cursor != (start_x, start_y))
        _fail(_xdotool(p, 'mousedown', str(code)), 'mousedown', button=button)
        time.sleep(GESTURE_SETTLE_SEC)
        for step_x, step_y in path[1:]:
            _move_to(p, step_x, step_y)
            time.sleep(STROKE_STEP_SEC)
        time.sleep(GESTURE_SETTLE_SEC)
        released = _xdotool(p, 'mouseup', str(code))
    finally:
        if released is None:
            _release_button(p, code)
        if restore:
            restore_context(previous_foreground, previous_cursor, platform=p)
    _fail(released, 'mouseup', button=button)
    return {
        'route': 'xtest',
        'action': 'stroke',
        'button': button,
        'points': len(path),
        'from': {'x': start_x, 'y': start_y},
        'to': {'x': path[-1][0], 'y': path[-1][1]},
        'windowId': hwnd,
        'events': len(path) + 2,
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
    chunks = typing_chunks(text)
    # Ánh xạ sẵn các keysym Unicode vào keycode trống, giữ nguyên trong suốt lần gõ: ứng dụng đọc
    # đúng cả chữ hoa, và không còn khe hở "ánh xạ đã bị trả lại" làm mất ký tự khi máy bận.
    plan = keysym_plan(p, [chunk for chunk in chunks if len(chunk) == 1 and ord(chunk) >= 128])
    sent = 0
    try:
        for chunk in chunks:
            # Không nâng cửa sổ lại (người dùng có thể đã cố tình đổi), chỉ KIỂM: mất tiêu điểm
            # giữa chừng ⇒ dừng ngay, phần còn lại không rơi vào cửa sổ của người.
            ensure_foreground(hwnd, platform=p, timeout=timeout, raise_window=False)
            if len(chunk) == 1 and chunk in plan:
                result = _xdotool(p, 'key', '--clearmodifiers', keysym_name(chunk),
                                  timeout=max(5.0, 0.05 * len(chunk) + 2.0))
            else:
                result = _xdotool(p, 'type', '--clearmodifiers', '--delay', str(TYPE_DELAY_MS), '--',
                                  chunk, timeout=max(5.0, 0.05 * len(chunk) + 2.0))
            _fail(result, 'type')
            sent += len(chunk)
    finally:
        release_keycodes(p, plan.values())
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
