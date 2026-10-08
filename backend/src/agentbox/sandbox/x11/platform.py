"""Nền tảng desktop Linux/X11 — cầu nối để CUA chạy được trên máy Linux.

Vì sao có module này: ``windows_platform.py`` gọi thẳng DLL Win32, nên trước đây
``build_desktop_control()`` trả ``None`` trên Linux và **mọi** công cụ CUA trả
``CUA_UNAVAILABLE``. Module này hiện thực đúng giao diện mà tầng trên đã dùng (xem
``agent_core/desktop_control.py``, ``sandbox/win/capture.py``, ``sandbox/win/input.py``) nhưng gọi
công cụ X11 (``xdotool``, ``xprop``, ``xwininfo``) thay cho Win32. Không có dòng nào ở tầng trên
phải biết máy đang chạy Windows hay Linux.

Ba giới hạn **đã biết**, cố ý không giấu:

* **Không cài hook bàn phím/chuột.** Trên Windows, cờ ``LLMHF_INJECTED`` phân biệt input do agent
  tiêm với input của người thật; X11 không có tương đương. Thà KHÔNG có hook (⇒
  ``DesktopControl.install_hooks()`` trả ``UNSUPPORTED_IN_HOST_MODE``, lease fail-closed) còn hơn có
  một hook luôn báo "người thật" — hook như vậy sẽ tự huỷ quyền của agent sau mỗi cú bấm của chính
  nó. Hệ quả: trên Linux, quyền điều khiển chỉ được trả lại bằng đường tường minh
  (``/desktop/release``, nút "Thu hồi", dừng phiên).
* **``window_from_point`` là phép thử hình học** trên danh sách cửa sổ EWMH, không phải
  ``XQueryPointer``: X11 không có cách hỏi "cửa sổ nào tại điểm (x, y)" cho một điểm bất kỳ. Đủ
  chính xác cho cửa sổ cấp cao nhất — đúng phạm vi sản phẩm hỗ trợ.
* **``last_input_tick``/``idle_seconds`` không tồn tại**, nên ``poll_idle()`` không bao giờ tự phát
  hiện người thật. Đây là lựa chọn có chủ ý, không phải thiếu sót: một tín hiệu sai còn tệ hơn
  không có tín hiệu.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from ..win.errors import CAPTURE_FAILED, PlatformError
from ..win.windows_platform import WindowInfo

#: Mã lỗi khi không mở được ứng dụng (khớp ``host_executor.LAUNCH_FAILED_CODE``).
LAUNCH_FAILED = 'LAUNCH_FAILED'

#: Mã lỗi khi X11 không dùng được (thiếu DISPLAY, thiếu công cụ, X server từ chối).
X11_UNAVAILABLE = 'CUA_UNAVAILABLE'

#: Bao lâu thì coi một lời gọi công cụ X11 là treo (giây). X11 trả lời trong vài ms; 5 s là rộng rãi
#: và vẫn đủ ngắn để một X server treo không làm đơ tiến trình harness.
TOOL_TIMEOUT_SEC = 5.0

#: Số cửa sổ tối đa đọc từ ``_NET_CLIENT_LIST_STACKING`` (tránh payload phình như bên Windows).
MAX_WINDOWS = 200

#: Thuộc tính EWMH cần cho một cửa sổ. Một lời gọi ``xprop`` trả về TẤT CẢ — rẻ hơn 6 lời gọi.
_WINDOW_PROPERTIES = (
    '_NET_WM_PID',
    'WM_CLASS',
    '_NET_WM_STATE',
    '_NET_WM_NAME',
    'WM_NAME',
    '_NET_WM_WINDOW_TYPE',
    '_NET_FRAME_EXTENTS',
)

#: Loại cửa sổ EWMH không phải ứng dụng người dùng (bỏ khỏi danh sách đích).
_NON_CLIENT_TYPES = (
    '_NET_WM_WINDOW_TYPE_DESKTOP',
    '_NET_WM_WINDOW_TYPE_DOCK',
    '_NET_WM_WINDOW_TYPE_TOOLBAR',
    '_NET_WM_WINDOW_TYPE_MENU',
    '_NET_WM_WINDOW_TYPE_SPLASH',
)

_PROP_LINE = re.compile(r'^([A-Za-z0-9_]+)(?:\(([^)]*)\))?\s*[=:]\s*(.*)$')


_OCTAL_ESCAPE = re.compile(r'\\([0-7]{1,3})')
_SIMPLE_ESCAPES = {'n': 10, 't': 9, 'r': 13, 'a': 7, 'b': 8, 'f': 12, 'v': 11, '\\': 92, '"': 34}


def _unescape(value: str) -> str:
    """Chuỗi trong ``xprop`` được bọc bằng nháy kép và escape như C.

    Ký tự ngoài ASCII được ``xprop`` ghi thành escape bát phân của **từng byte UTF-8**:
    ``"BoxFox\\342\\200\\224Agent Box"`` là "BoxFox—Agent Box". Trả nguyên văn thì tiêu đề
    tiếng Việt hiện ra thành ``\\341\\273\\247`` trong danh sách cửa sổ, nên phải gom lại thành
    byte rồi giải mã UTF-8 (lùi về latin-1 khi chuỗi không phải UTF-8 hợp lệ).
    """
    text = value.strip()
    if len(text) < 2 or not text.startswith('"') or not text.endswith('"'):
        return text
    text = text[1:-1]
    out = bytearray()
    index = 0
    while index < len(text):
        char = text[index]
        if char != '\\' or index + 1 >= len(text):
            out.extend(char.encode('utf-8'))
            index += 1
            continue
        following = text[index + 1]
        if following in '01234567':
            match = _OCTAL_ESCAPE.match(text, index)
            out.append(int(match.group(1), 8) & 0xFF)
            index = match.end()
            continue
        if following in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[following])
        else:                       # escape không biết (ví dụ `\ `) ⇒ giữ nguyên ký tự sau dấu chéo
            out.extend(following.encode('utf-8'))
        index += 2
    try:
        return out.decode('utf-8')
    except UnicodeDecodeError:
        return out.decode('latin-1')


def _parse_props(text: str) -> dict[str, str]:
    """``xprop`` → ``{tên_thuộc_tính: giá_thị_thô}`` (giá trị đã bỏ nháy)."""
    props: dict[str, str] = {}
    for line in text.splitlines():
        match = _PROP_LINE.match(line.strip())
        if not match:
            continue
        name, _kind, value = match.group(1), match.group(2), match.group(3)
        if value.strip().lower().startswith('not found'):
            continue
        props[name] = _unescape(value)
    return props


def _first_int(text: str) -> int | None:
    match = re.search(r'0x[0-9a-fA-F]+|\d+', text or '')
    if not match:
        return None
    try:
        return int(match.group(0), 0)
    except ValueError:
        return None


@dataclass
class _CommandResult:
    code: int
    out: str
    err: str = ''
    raw: bytes = b''

    @property
    def ok(self) -> bool:
        return self.code == 0


class X11Platform:
    """Hiện thực giao diện nền tảng desktop bằng công cụ X11.

    ``runner`` được tiêm để test được mà không cần X server thật: nó nhận ``(argv, timeout)`` và
    trả :class:`_CommandResult`. Mặc định chạy tiến trình thật với ``DISPLAY`` đã đặt.
    """

    name = 'x11'
    available = True

    def __init__(self, *, display: str | None = None, runner: Callable[..., Any] | None = None,
                 env: dict[str, str] | None = None) -> None:
        self._display = display
        self._env = dict(env) if env is not None else None
        self._runner = runner
        self._props_cache: dict[int, tuple[float, dict[str, str]]] = {}
        self._notes: list[str] = []

    # -- hạ tầng --------------------------------------------------------------

    @property
    def display(self) -> str:
        if self._display:
            return self._display
        source = self._env if self._env is not None else os.environ
        return str(source.get('DISPLAY') or ':0')

    def notes(self) -> list[str]:
        return list(self._notes)

    def _child_env(self) -> dict[str, str]:
        source = self._env if self._env is not None else os.environ
        env = {key: str(source[key]) for key in ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'XAUTHORITY')
               if source.get(key)}
        env.setdefault('PATH', '/usr/local/bin:/usr/bin:/bin')
        env['DISPLAY'] = self.display
        return env

    def _run(self, argv: Iterable[str], *, timeout: float = TOOL_TIMEOUT_SEC) -> _CommandResult:
        args = [str(part) for part in argv]
        if self._runner is not None:
            return self._runner(args, timeout)
        try:
            done = subprocess.run(args, capture_output=True, timeout=timeout, env=self._child_env(),
                                  check=False)
        except FileNotFoundError as exc:
            return _CommandResult(127, '', str(exc))
        except subprocess.TimeoutExpired:
            return _CommandResult(124, '', 'hết thời gian chờ %s' % args[0])
        except OSError as exc:      # pragma: no cover - phụ thuộc hệ điều hành
            return _CommandResult(126, '', str(exc))
        return _CommandResult(done.returncode, done.stdout.decode('utf-8', 'replace'),
                              done.stderr.decode('utf-8', 'replace'), done.stdout)

    def run_raw(self, argv: Iterable[str], *, timeout: float = TOOL_TIMEOUT_SEC) -> _CommandResult:
        """Chạy công cụ X11 và giữ nguyên **byte** đầu ra (ảnh thô của ``import``).

        Cùng một ``runner`` được tiêm như :meth:`_run`, nên test vẫn thay được bằng hàm giả.
        """
        args = [str(part) for part in argv]
        if self._runner is not None:
            result = self._runner(args, timeout)
            if not isinstance(result, _CommandResult):
                raise TypeError('runner phải trả _CommandResult')
            return result
        try:
            done = subprocess.run(args, capture_output=True, timeout=timeout, env=self._child_env(),
                                  check=False)
        except FileNotFoundError as exc:
            return _CommandResult(127, '', str(exc))
        except subprocess.TimeoutExpired:
            return _CommandResult(124, '', 'hết thời gian chờ %s' % args[0])
        except OSError as exc:      # pragma: no cover - phụ thuộc hệ điều hành
            return _CommandResult(126, '', str(exc))
        return _CommandResult(done.returncode, '', done.stderr.decode('utf-8', 'replace'), done.stdout)

    def _tool(self, name: str) -> str | None:
        """Đường dẫn công cụ X11, hoặc ``None`` khi máy thiếu (đã ghi vào ``notes``)."""
        if self._runner is not None:
            return name
        found = shutil.which(name)
        if found is None and name not in self._notes:
            self._notes.append(name)
        return found

    # -- đọc thuộc tính cửa sổ -------------------------------------------------

    def window_properties(self, hwnd: int, *, fresh: bool = False,
                          ttl: float = 0.0) -> dict[str, str]:
        """Thuộc tính EWMH của một cửa sổ, một lời gọi ``xprop`` cho tất cả.

        ``ttl`` cho phép dùng lại kết quả trong cùng một thao tác (``list_windows`` đọc 6 thuộc
        tính của 3 cửa sổ = 3 lời gọi thay vì 18). Mặc định ``ttl=0`` — luôn đọc mới, vì trạng thái
        cửa sổ đổi nhanh và một câu trả lời cũ nguy hiểm hơn một lời gọi thêm.
        """
        key = int(hwnd)
        now = time.monotonic()
        if not fresh and ttl > 0:
            cached = self._props_cache.get(key)
            if cached is not None and now - cached[0] <= ttl:
                return dict(cached[1])
        tool = self._tool('xprop')
        if tool is None:
            return {}
        result = self._run([tool, '-id', str(key), *_WINDOW_PROPERTIES])
        if not result.ok:
            return {}
        props = _parse_props(result.out)
        self._props_cache[key] = (now, dict(props))
        return props

    def _cached_props(self, hwnd: int) -> dict[str, str]:
        cached = self._props_cache.get(int(hwnd))
        if cached is not None and time.monotonic() - cached[0] <= 2.0:
            return dict(cached[1])
        return self.window_properties(hwnd)

    # -- cửa sổ: danh sách và danh tính ---------------------------------------

    def _client_list(self) -> list[int]:
        """``_NET_CLIENT_LIST_STACKING`` — cửa sổ được WM quản lý, **dưới → trên**."""
        tool = self._tool('xprop')
        if tool is None:
            return []
        result = self._run([tool, '-root', '_NET_CLIENT_LIST_STACKING'])
        if not result.ok:
            return []
        match = re.search(r'window id #(.*)', result.out)
        if not match:
            return []
        ids: list[int] = []
        for token in re.findall(r'0x[0-9a-fA-F]+|\d+', match.group(1)):
            try:
                value = int(token, 0)
            except ValueError:
                continue
            if value:
                ids.append(value)
        return ids[:MAX_WINDOWS]

    def enum_windows(self) -> list[int]:
        """Cửa sổ cấp cao nhất, **trên → dưới** (Z-order), như ``EnumWindows`` của Windows."""
        return list(reversed(self._client_list()))

    def is_window(self, hwnd: int) -> bool:
        if not hwnd:
            return False
        return bool(self._cached_props(int(hwnd)))

    def is_window_visible(self, hwnd: int) -> bool:
        """Cửa sổ có đang được vẽ (``Map State: IsViewable``) hay không."""
        tool = self._tool('xwininfo')
        if tool is None:
            return False
        result = self._run([tool, '-id', str(int(hwnd))])
        if not result.ok:
            return False
        return 'Map State: IsViewable' in result.out

    def is_iconic(self, hwnd: int) -> bool:
        """Thu nhỏ = ``_NET_WM_STATE_HIDDEN`` (cùng nghĩa ``IsIconic``)."""
        props = self._cached_props(hwnd)
        return '_NET_WM_STATE_HIDDEN' in (props.get('_NET_WM_STATE') or '')

    def is_cloaked(self, hwnd: int) -> bool:
        """X11 không có khái niệm cloak của DWM — luôn ``False`` (không bịa)."""
        return False

    def get_ancestor_root(self, hwnd: int) -> int | None:
        """Cửa sổ cấp cao nhất chứa ``hwnd``.

        Danh sách đích của sản phẩm chỉ gồm cửa sổ cấp cao nhất (EWMH), nên ở đây trả về chính nó
        khi nó nằm trong danh sách; ngoài danh sách (cửa sổ con, override-redirect) thì trả ``None``
        để chỗ gọi tự quyết định.
        """
        value = int(hwnd)
        if value in self._client_list():
            return value
        return None

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        """``(left, top, right, bottom)`` tuyệt đối — tương đương ``GetWindowRect``.

        ``xwininfo`` cho toạ độ tuyệt đối của **vùng khách** (vùng vẽ của ứng dụng). Viền trang trí
        của X11 do WM vẽ trong một cửa sổ khác, nên nó không nằm trong vùng này — xem
        :meth:`get_extended_frame_bounds`.
        """
        tool = self._tool('xwininfo')
        if tool is None:
            return None
        result = self._run([tool, '-id', str(int(hwnd))])
        if not result.ok:
            return None
        numbers = {
            'x': re.search(r'Absolute upper-left X:\s*(-?\d+)', result.out),
            'y': re.search(r'Absolute upper-left Y:\s*(-?\d+)', result.out),
            'width': re.search(r'Width:\s*(\d+)', result.out),
            'height': re.search(r'Height:\s*(\d+)', result.out),
        }
        if any(match is None for match in numbers.values()):
            return None
        x = int(numbers['x'].group(1))       # type: ignore[union-attr]
        y = int(numbers['y'].group(1))       # type: ignore[union-attr]
        width = int(numbers['width'].group(1))    # type: ignore[union-attr]
        height = int(numbers['height'].group(1))  # type: ignore[union-attr]
        return x, y, x + width, y + height

    def get_extended_frame_bounds(self, hwnd: int) -> tuple[int, int, int, int] | None:
        """Vùng khách = "viền thật" của một cửa sổ X11.

        Trên Windows, ``DWMWA_EXTENDED_FRAME_BOUNDS`` rộng hơn ``GetWindowRect`` vì bóng đổ của DWM.
        Trên X11 thì ngược lại: cửa sổ khách **không** gồm thanh tiêu đề (WM vẽ nó ở cửa sổ khác), nên
        viền thật đúng bằng vùng khách. Trả về chính vùng đó thay vì ``None`` để tầng soi phần tử
        (``inspect_host``) tính được gốc vùng nội dung web — ``None`` sẽ khoá luôn đường DOM.
        """
        return self.get_window_rect(hwnd)

    def get_window_text(self, hwnd: int) -> str:
        props = self._cached_props(hwnd)
        return str(props.get('_NET_WM_NAME') or props.get('WM_NAME') or '')

    def get_class_name(self, hwnd: int) -> str:
        """Lớp cửa sổ: trường thứ hai của ``WM_CLASS`` (giống ``GetClassName``).

        ``WM_CLASS`` của X11 là hai chuỗi: tên instance (thường kèm tham số) và tên lớp. Tên lớp là
        thứ ổn định, dùng để nhận diện ứng dụng — ví dụ ``Google-chrome``.
        """
        props = self._cached_props(hwnd)
        raw = str(props.get('WM_CLASS') or '')
        parts = [part.strip().strip('"') for part in raw.split(',') if part.strip()]
        if len(parts) >= 2:
            return parts[-1]
        return parts[0] if parts else ''

    def get_window_pid(self, hwnd: int) -> int | None:
        props = self._cached_props(hwnd)
        return _first_int(props.get('_NET_WM_PID') or '')

    def process_image_name(self, pid: int | None) -> str | None:
        """Tên tệp thực thi của tiến trình, đọc từ ``/proc`` (không cần ``ps``)."""
        if not pid:
            return None
        try:
            link = os.readlink('/proc/%d/exe' % int(pid))
        except (OSError, ValueError):
            link = ''
        if link:
            return Path(link).name
        try:
            with open('/proc/%d/comm' % int(pid), 'r', encoding='utf-8') as handle:
                name = handle.read().strip()
        except OSError:
            return None
        return name or None

    def describe_window(self, hwnd: int, *, with_process: bool = True) -> WindowInfo:
        """Danh tính + hình học một cửa sổ; ném ``CAPTURE_FAILED`` khi cửa sổ không còn."""
        value = int(hwnd)
        props = self.window_properties(value, fresh=True)
        if not props:
            raise PlatformError(CAPTURE_FAILED, 'cửa sổ X11 không còn tồn tại.', hwnd=value)
        rect = self.get_window_rect(value)
        if rect is None:
            raise PlatformError(CAPTURE_FAILED, 'không đọc được hình học cửa sổ X11.', hwnd=value)
        pid = _first_int(props.get('_NET_WM_PID') or '')
        raw_class = str(props.get('WM_CLASS') or '')
        parts = [part.strip().strip('"') for part in raw_class.split(',') if part.strip()]
        class_name = parts[-1] if len(parts) >= 2 else (parts[0] if parts else '')
        state = str(props.get('_NET_WM_STATE') or '')
        return WindowInfo(
            hwnd=value,
            title=str(props.get('_NET_WM_NAME') or props.get('WM_NAME') or ''),
            class_name=class_name,
            pid=pid,
            rect=rect,
            extended_bounds=rect,
            cloaked=False,
            iconic='_NET_WM_STATE_HIDDEN' in state,
            process_name=self.process_image_name(pid) if (with_process and pid) else None,
        )

    def window_from_point(self, x: int, y: int) -> int | None:
        """Cửa sổ cấp cao nhất tại ``(x, y)`` — phép thử hình học theo Z-order.

        Duyệt từ trên xuống, trả về cửa sổ đầu tiên có vùng khách chứa điểm. Cửa sổ
        override-redirect (viền báo của chính BoxFox, menu) không nằm trong ``_NET_CLIENT_LIST_STACKING``
        nên không chen vào kết quả — đúng ý đồ: viền báo không được phép che đích.
        """
        px, py = int(x), int(y)
        for hwnd in self.enum_windows():
            if not self.is_window_visible(hwnd):
                continue
            rect = self.get_window_rect(hwnd)
            if rect is None:
                continue
            left, top, right, bottom = rect
            if left <= px < right and top <= py < bottom:
                return hwnd
        return None

    def get_foreground_window(self) -> int | None:
        tool = self._tool('xprop')
        if tool is None:
            return None
        result = self._run([tool, '-root', '_NET_ACTIVE_WINDOW'])
        if not result.ok:
            return None
        return _first_int(result.out.split('=')[-1])

    def set_foreground_window(self, hwnd: int) -> bool:
        """Đưa cửa sổ lên trước và cho nó tiêu điểm (``xdotool windowactivate``)."""
        tool = self._tool('xdotool')
        if tool is None:
            # Máy thiếu công cụ là lỗi triển khai, không phải "cửa sổ vừa đổi": nói thẳng tên gói,
            # nếu trả `False` thì lớp gọi chỉ báo được "cửa sổ mất tiêu điểm" và người dùng mò sai chỗ.
            raise PlatformError(
                X11_UNAVAILABLE,
                'thiếu `xdotool` — cài gói xdotool để BoxFox điều khiển cửa sổ trên Linux.',
                tool='xdotool',
            )
        result = self._run([tool, 'windowactivate', '--sync', str(int(hwnd))])
        return result.ok

    def virtual_screen_bounds(self) -> tuple[int, int, int, int]:
        """``(0, 0, rộng, cao)`` của màn hình ảo — X11 một màn hình ảo duy nhất cho mọi output."""
        tool = self._tool('xwininfo')
        if tool is None:
            return (0, 0, 0, 0)
        result = self._run([tool, '-root'])
        if not result.ok:
            return (0, 0, 0, 0)
        width = re.search(r'-geometry\s+(\d+)x(\d+)', result.out) or re.search(r'Width:\s*(\d+)', result.out)
        height = re.search(r'-geometry\s+\d+x(\d+)', result.out) or re.search(r'Height:\s*(\d+)', result.out)
        if not width or not height:
            return (0, 0, 0, 0)
        return (0, 0, int(width.group(1)), int(height.group(1)))

    def get_dpi_for_window(self, hwnd: int) -> int:
        """X11 không có DPI theo từng cửa sổ: trả 96 (tỉ lệ 1:1) — toạ độ đã là pixel thật."""
        return 96

    def get_cursor_pos(self) -> tuple[int, int] | None:
        tool = self._tool('xdotool')
        if tool is None:
            return None
        result = self._run([tool, 'getmouselocation', '--shell'])
        if not result.ok:
            return None
        x = re.search(r'X=(-?\d+)', result.out)
        y = re.search(r'Y=(-?\d+)', result.out)
        if not x or not y:
            return None
        return int(x.group(1)), int(y.group(1))

    def set_cursor_pos(self, x: int, y: int) -> bool:
        tool = self._tool('xdotool')
        if tool is None:
            return False
        return self._run([tool, 'mousemove', str(int(x)), str(int(y))]).ok

    # -- phiên / quyền ---------------------------------------------------------

    def is_interactive_session(self) -> bool:
        """Có ``DISPLAY`` và X server trả lời ⇒ đây là phiên tương tác được."""
        return bool(self.virtual_screen_bounds()[2:])

    def desktop_locked(self) -> bool:
        """Màn hình khoá của X11 là một cửa sổ toàn màn hình; không có API chuẩn để hỏi.

        Trả ``False`` — nói dối theo hướng nguy hiểm (tưởng đang mở khoá) là điều không nên, nhưng
        không có tín hiệu nào để đọc: các trình khoá phổ biến (light-locker, xscreensaver) đều không
        có thuộc tính EWMH chuẩn. Chốt chặn thật vẫn là ``ensure_foreground`` trước mỗi thao tác.
        """
        return False

    def input_desktop_name(self) -> str | None:
        return self.display

    def process_session_id(self) -> int | None:
        return None

    def process_integrity_level(self, pid: int | None) -> int | None:
        """X11 không có UIPI: không có mức toàn vẹn để so."""
        return None

    def own_integrity_level(self) -> int | None:
        return None

    # -- mutex liên tiến trình -------------------------------------------------

    def _mutex_path(self, name: str) -> Path:
        digest = hashlib.sha256(str(name).encode('utf-8')).hexdigest()[:16]
        base = Path(tempfile.gettempdir())
        return base / ('boxfox-%s.lock' % digest)

    def create_mutex(self, name: str) -> Any:
        """Mở tệp khoá (``flock`` giữ khoá theo *open file description*, tức theo tiến trình)."""
        try:
            handle = open(self._mutex_path(name), 'a+b')
        except OSError:
            return None
        return handle

    def acquire_mutex(self, handle: Any, timeout_ms: int = 0) -> bool:
        """Thử giữ khoá, **không xếp hàng** (đúng ngữ nghĩa ``WaitForSingleObject(.., 0)``)."""
        if handle is None:
            return False
        import fcntl

        deadline = time.monotonic() + max(0, int(timeout_ms)) / 1000.0
        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.02)

    def release_mutex(self, handle: Any) -> None:
        if handle is None:
            return
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    def close_handle(self, handle: Any) -> None:
        if handle is None:
            return
        try:
            handle.close()
        except OSError:
            pass

    # -- mở ứng dụng -----------------------------------------------------------

    def launch_app(self, app: str) -> int | None:
        """Mở một ứng dụng theo tên tệp (không nhận đường dẫn — chốt chặn ở ``_launchable_app``).

        Trả pid của tiến trình vừa mở. Ứng dụng chạy trong session riêng để đóng harness không kéo
        nó theo, và ``stdout``/``stderr`` đi vào ``/dev/null`` để không giữ ống của tiến trình cha.
        """
        name = str(app or '').strip()
        if not name:
            raise PlatformError(LAUNCH_FAILED, 'thiếu tên ứng dụng.', app=app)
        path = shutil.which(name) if self._runner is None else name
        if not path:
            raise PlatformError(LAUNCH_FAILED, 'không thấy ứng dụng `%s` trên máy này.' % name, app=name)
        try:
            process = subprocess.Popen(
                [path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                env=self._child_env(),
                cwd=str(Path.home()),
            )
        except OSError as exc:
            raise PlatformError(LAUNCH_FAILED, 'không mở được `%s`: %s' % (name, exc), app=name) from exc
        return process.pid


_platform: X11Platform | None = None


def get_platform() -> X11Platform | None:
    """Nền tảng X11 dùng chung cho cả tiến trình (tạo một lần), hoặc ``None`` khi máy không có X11."""
    global _platform
    if _platform is None:
        if not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            return None
        _platform = X11Platform()
        if not _platform.is_interactive_session():
            _platform = None
    return _platform


def reset_platform() -> None:
    """Xoá nền tảng dùng chung (dùng trong test)."""
    global _platform
    _platform = None
