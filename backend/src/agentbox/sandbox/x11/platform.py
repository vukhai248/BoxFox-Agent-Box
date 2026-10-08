"""Nền tảng desktop Linux/X11 — cầu nối để CUA chạy được trên máy Linux.

Vì sao có module này: ``windows_platform.py`` gọi thẳng DLL Win32, nên trước đây
``build_desktop_control()`` trả ``None`` trên Linux và **mọi** công cụ CUA trả
``CUA_UNAVAILABLE``. Module này hiện thực đúng giao diện mà tầng trên đã dùng (xem
``agent_core/desktop_control.py``, ``sandbox/win/capture.py``, ``sandbox/win/input.py``) nhưng gọi
công cụ X11 (``xdotool``, ``xprop``, ``xwininfo``) thay cho Win32. Không có dòng nào ở tầng trên
phải biết máy đang chạy Windows hay Linux.

Bốn giới hạn **đã biết**, cố ý không giấu:

* **Không cài hook bàn phím/chuột.** Trên Windows, cờ ``LLMHF_INJECTED`` phân biệt input do agent
  tiêm với input của người thật; X11 không có tương đương. Thà KHÔNG có hook (⇒
  ``DesktopControl.install_hooks()`` trả ``UNSUPPORTED_IN_HOST_MODE``, lease fail-closed) còn hơn có
  một hook luôn báo "người thật" — hook như vậy sẽ tự huỷ quyền của agent sau mỗi cú bấm của chính
  nó. Thay vào đó, việc phát hiện người can thiệp chạy bằng **lấy mẫu** (``last_input_tick``): nó
  chỉ thấy chuột và tiêu điểm, **không** thấy bàn phím, và có thể báo nhầm khi ứng dụng khác tự
  đổi tiêu điểm. Xem :meth:`X11Platform.last_input_tick`.
* **``window_from_point`` là phép thử hình học** trên danh sách cửa sổ EWMH, không phải
  ``XQueryPointer``: X11 không có cách hỏi "cửa sổ nào tại điểm (x, y)" cho một điểm bất kỳ. Đủ
  chính xác cho cửa sổ cấp cao nhất — đúng phạm vi sản phẩm hỗ trợ.
* **Cửa sổ override-redirect không nằm trong phép thử đó** — không chỉ viền báo của BoxFox mà cả
  menu thả xuống, tooltip, bong bóng thông báo của ứng dụng khác. Nếu một menu đang mở ngay trên
  điểm bấm, ``check_point_ownership`` vẫn cho qua và cú bấm rơi vào menu. Đây là lỗ đã biết của
  nền tảng, không phải điều bất ngờ; vá nó cần một phép thử điểm ảnh theo cây cửa sổ
  (``xwininfo -root -children`` + so ngăn xếp), việc còn lại của nền tảng Linux.
* **``type_text`` gửi từng khối 64 ký tự** và kiểm lại tiêu điểm giữa các khối, nhưng bàn phím X11
  không gắn với cửa sổ: vẫn có khe hở giữa lúc kiểm và lúc gõ. ``check_geometry_revision`` và
  chốt ô mật khẩu là **hợp đồng dùng chung** với bản Windows; đường ``computer_use`` hiện không
  truyền ``element``/``sourceId`` nên hai chốt đó chỉ chạy khi lớp gọi cung cấp tham số.
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

#: Locale UTF-8 dùng khi phiên không có locale nào. Đo trên máy thật (08/10/2026): ứng dụng chạy
#: trong phiên ``LC_ALL=C`` **nuốt mọi ký tự ngoài ASCII** khi nhận input XTEST — "chào" thành "cho".
#: Đây là lỗi im lặng: lệnh gõ vẫn trả về thành công, chỉ có chữ trên màn hình là mất dấu.
_UTF8_LOCALE_CANDIDATES = ('C.UTF-8', 'C.utf8', 'en_US.UTF-8', 'en_US.utf8')
_utf8_locale_cache: str | None = None

#: Chữ hoa từng bị **mất dấu hoa** khi `xdotool type` tự ánh xạ keysym (đo 08/10/2026: `Á` → `á`,
#: 16/26 ký tự hoa sai). Nay `sandbox/x11/input.py` ánh xạ sẵn keysym vào keycode trống và giữ
#: nguyên trong suốt lần gõ, nên chữ hoa đi đúng; danh sách dưới chỉ còn dùng cho **ghi chú** khi
#: máy thiếu `xmodmap` (khi đó phải quay lại đường `xdotool type`).
_CASE_LOST = ('Á', 'À', 'Ã', 'Â', 'Ê', 'Ô', 'É', 'È', 'Í', 'Ì', 'Ó', 'Ò', 'Õ', 'Ú', 'Ù', 'Ý')
#: Chữ hoa Latin Extended (3 byte UTF-8) thì gõ ĐÚNG — đo cùng lượt.
_CASE_KEPT = ('Ả', 'Ạ', 'Ă', 'Đ', 'Ơ', 'Ư', 'Ẽ', 'Ĩ', 'Ũ', 'Ỳ')


def has_utf8_locale(env: dict[str, str]) -> bool:
    """``True`` khi locale *hiệu lực* của môi trường là UTF-8.

    Thứ tự ưu tiên đúng như libc: ``LC_ALL`` > ``LC_CTYPE`` > ``LANG``.
    """
    for key in ('LC_ALL', 'LC_CTYPE', 'LANG'):
        value = str(env.get(key) or '').strip()
        if value:
            folded = value.lower()
            return 'utf-8' in folded or 'utf8' in folded
    return False


def utf8_locale() -> str:
    """Tên locale UTF-8 có thật trên máy này (dò một lần cho cả tiến trình)."""
    global _utf8_locale_cache
    if _utf8_locale_cache is None:
        _utf8_locale_cache = _UTF8_LOCALE_CANDIDATES[0]
        try:
            done = subprocess.run(['locale', '-a'], capture_output=True, text=True, timeout=5.0)
        except (OSError, subprocess.SubprocessError):      # pragma: no cover - máy thiếu `locale`
            return _utf8_locale_cache
        names = {line.strip() for line in done.stdout.splitlines()}
        for candidate in _UTF8_LOCALE_CANDIDATES:
            if candidate in names:
                _utf8_locale_cache = candidate
                break
    return _utf8_locale_cache

#: Bao lâu thì dùng lại hình học cửa sổ đã đọc (giây). Một thao tác soi gọi ``window_from_point``
#: tới năm lần, mỗi lần duyệt cả chồng cửa sổ — đo được 42 tiến trình con cho MỘT ảnh chụp. Giữ
#: ngắn (0,5 s) để một cửa sổ vừa bị di chuyển vẫn được đọc lại trước thao tác kế tiếp.
GEOMETRY_CACHE_SEC = 0.5

#: Bao lâu thì chờ ``_NET_ACTIVE_WINDOW`` đổi sau khi xin WM kích hoạt (giây). Ngắn vì đây là
#: vòng thăm dò của chính ta, không phải ``--sync`` của ``xdotool`` (thứ chặn tới hết thời gian
#: chờ công cụ khi WM từ chối kích hoạt — xem :meth:`X11Platform.set_foreground_window`).
ACTIVATE_WAIT_SEC = 0.25

#: Thuộc tính EWMH cần cho một cửa sổ. Một lời gọi ``xprop`` trả về TẤT CẢ — rẻ hơn 6 lời gọi.
_WINDOW_PROPERTIES = (
    '_NET_WM_PID',
    'WM_CLASS',
    '_NET_WM_STATE',
    '_NET_WM_NAME',
    'WM_NAME',
    '_NET_WM_WINDOW_TYPE',
    'WM_TRANSIENT_FOR',
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
        self._geometry_cache: dict[int, tuple[float, str]] = {}
        self._notes: list[str] = []
        if self._env_source().get('WAYLAND_DISPLAY'):
            self._notes.append(
                'phiên Wayland: chỉ thấy được cửa sổ X11/XWayland, ứng dụng Wayland thuần không '
                'hiện trong danh sách và không nhận được input XTEST'
            )
        if not has_utf8_locale(self._env_source()):
            self._notes.append(
                'phiên này không có locale UTF-8: ứng dụng **đang chạy** sẽ nuốt mọi ký tự ngoài '
                'ASCII khi nhận input (chữ có dấu biến mất, lệnh vẫn báo thành công). Ứng dụng do '
                'BoxFox mở thì đã được cấp locale `%s`; muốn gõ chữ có dấu vào ứng dụng có sẵn, hãy '
                'mở lại ứng dụng đó từ BoxFox.' % utf8_locale()
            )
        if shutil.which('xmodmap') is None:
            self._notes.append(
                'máy thiếu `xmodmap`: chữ có dấu vẫn gõ được nhưng phải đi đường dự phòng của '
                '`xdotool type`, đường này từng làm mất ký tự khi máy bận và làm mất dấu hoa của '
                'các chữ hoa Latin-1/2 (%s; các chữ hoa Latin Extended như %s thì đúng). Muốn chắc, '
                'hãy đọc lại ảnh cửa sổ sau khi gõ.'
                % (', '.join(_CASE_LOST), ', '.join(_CASE_KEPT))
            )
        # Theo dõi "người thật vừa chạm máy" bằng cách lấy mẫu con trỏ + tiêu điểm
        # (quyết định #6785). X11 không có bộ đếm input toàn cục như `GetLastInputInfo`, nên
        # "tick" ở đây là bộ đếm của CHÍNH TA: nó tăng khi con trỏ hoặc tiêu điểm đổi mà lần đổi
        # đó không do ta gây ra.
        # Bắt đầu từ 1, không phải 0: `DesktopControl.poll_idle` dùng 0 làm nghĩa "chưa có mốc nào"
        # (`if not previous: return False`), mà bộ đếm của ta thì bắt đầu từ con số không. Trên
        # Windows, `GetLastInputInfo` là số tick của hệ thống nên chưa bao giờ bằng 0 — giữ đúng
        # tính chất đó để lần chạm ĐẦU TIÊN của người cũng nhả được quyền, không phải đợi lần thứ hai.
        self._input_tick = 1
        self._last_pointer: tuple[int, int] | None = None
        self._last_foreground: int | None = None
        self._own_pointer: tuple[int, int] | None = None
        self._own_foreground: int | None = None
        self._last_change_at: float | None = None

    # -- hạ tầng --------------------------------------------------------------

    def _env_source(self) -> Any:
        return self._env if self._env is not None else os.environ

    @property
    def display(self) -> str:
        if self._display:
            return self._display
        return str(self._env_source().get('DISPLAY') or ':0')

    def notes(self) -> list[str]:
        return list(self._notes)

    def _child_env(self) -> dict[str, str]:
        source = self._env if self._env is not None else os.environ
        env = {key: str(source[key]) for key in ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'LC_CTYPE', 'XAUTHORITY')
               if source.get(key)}
        env.setdefault('PATH', '/usr/local/bin:/usr/bin:/bin')
        env['DISPLAY'] = self.display
        # Không có locale UTF-8 thì mọi ký tự ngoài ASCII gõ vào ứng dụng sẽ **biến mất** (đo trên máy
        # thật 08/10/2026: `xfce4-terminal` mở bằng `env -i` nuốt sạch dấu — "chào" thành "cho"; mở
        # kèm `LANG=C.UTF-8` thì nhận đủ). Tiến trình con ở đây gồm cả `xdotool` (nó giải mã đối số
        # theo locale) và cả ứng dụng mà BoxFox mở, nên thiếu locale là lỗi im lặng rất khó lần.
        if not has_utf8_locale(env):
            env['LANG'] = utf8_locale()
            env.pop('LC_ALL', None)
            env.pop('LC_CTYPE', None)
        return env

    def _spawn(self, args: list[str], timeout: float) -> Any:
        """Chạy tiến trình con; lỗi hệ điều hành trả ``_CommandResult`` thay vì ném ra ngoài."""
        try:
            return subprocess.run(args, capture_output=True, timeout=timeout, env=self._child_env(),
                                  check=False)
        except FileNotFoundError as exc:
            return _CommandResult(127, '', str(exc))
        except subprocess.TimeoutExpired:
            return _CommandResult(124, '', 'hết thời gian chờ %s' % args[0])
        except OSError as exc:      # pragma: no cover - phụ thuộc hệ điều hành
            return _CommandResult(126, '', str(exc))

    def _run(self, argv: Iterable[str], *, timeout: float = TOOL_TIMEOUT_SEC) -> _CommandResult:
        args = [str(part) for part in argv]
        if self._runner is not None:
            return self._runner(args, timeout)
        done = self._spawn(args, timeout)
        if isinstance(done, _CommandResult):
            return done
        return _CommandResult(done.returncode, done.stdout.decode('utf-8', 'replace'),
                              done.stderr.decode('utf-8', 'replace'), done.stdout)

    def run_raw(self, argv: Iterable[str], *, timeout: float = TOOL_TIMEOUT_SEC) -> _CommandResult:
        """Chạy công cụ X11 và giữ nguyên **byte** đầu ra (ảnh thô của ``import``).

        Cùng một ``runner`` được tiêm như :meth:`_run`, nên test vẫn thay được bằng hàm giả. Không
        gọi lại :meth:`_run`: ở đây đầu ra là cả khung ảnh nhiều MB, giải mã sang ``str`` là vô ích.
        """
        args = [str(part) for part in argv]
        if self._runner is not None:
            result = self._runner(args, timeout)
            if not isinstance(result, _CommandResult):
                raise TypeError('runner phải trả _CommandResult')
            return result
        done = self._spawn(args, timeout)
        if isinstance(done, _CommandResult):
            return done
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

    def window_properties(self, hwnd: int) -> dict[str, str]:
        """Thuộc tính EWMH của một cửa sổ — MỘT lời gọi ``xprop`` cho cả sáu thuộc tính.

        Kết quả được ghi vào ``_props_cache`` để các hàm đọc riêng lẻ (``get_window_pid``,
        ``get_class_name``…) dùng lại trong cùng một thao tác thay vì gọi lại ``xprop``.
        """
        key = int(hwnd)
        now = time.monotonic()
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
        text = self._xwininfo_text(int(hwnd))
        if text is None:
            return False
        return 'Map State: IsViewable' in text

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

    def _xwininfo_text(self, hwnd: int, *, fresh: bool = False) -> str | None:
        """Đầu ra thô của ``xwininfo -id <hwnd>``, dùng lại trong :data:`GEOMETRY_CACHE_SEC` giây.

        Cả hình học lẫn trạng thái ``Map State`` đều nằm trong **cùng một** lời gọi này; trước đây
        mỗi thứ gọi riêng một lần, nên chỉ một phép thử \"cửa sổ tại điểm\" đã tốn hai tiến trình con
        cho mỗi cửa sổ trong chồng.
        """
        key = int(hwnd)
        if not fresh:
            cached = self._geometry_cache.get(key)
            if cached is not None and time.monotonic() - cached[0] <= GEOMETRY_CACHE_SEC:
                return cached[1]
        tool = self._tool('xwininfo')
        if tool is None:
            return None
        result = self._run([tool, '-id', str(key)])
        if not result.ok:
            return None
        self._geometry_cache[key] = (time.monotonic(), result.out)
        return result.out

    def get_window_rect(self, hwnd: int, *, fresh: bool = False) -> tuple[int, int, int, int] | None:
        """``(left, top, right, bottom)`` tuyệt đối — tương đương ``GetWindowRect``.

        ``xwininfo`` cho toạ độ tuyệt đối của **vùng khách** (vùng vẽ của ứng dụng). Viền trang trí
        của X11 do WM vẽ trong một cửa sổ khác, nên nó không nằm trong vùng này — xem
        :meth:`get_extended_frame_bounds`.

        Kết quả được dùng lại trong :data:`GEOMETRY_CACHE_SEC` giây (trừ khi ``fresh=True``): một
        lần soi duyệt cả chồng cửa sổ năm lần, mỗi lần một ``xwininfo`` cho từng cửa sổ.
        """
        text = self._xwininfo_text(int(hwnd), fresh=fresh)
        if text is None:
            return None
        numbers = {
            'x': re.search(r'Absolute upper-left X:\s*(-?\d+)', text),
            'y': re.search(r'Absolute upper-left Y:\s*(-?\d+)', text),
            'width': re.search(r'Width:\s*(\d+)', text),
            'height': re.search(r'Height:\s*(\d+)', text),
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

    def get_window_owner(self, hwnd: int) -> int | None:
        """``WM_TRANSIENT_FOR`` — cửa sổ mà cửa sổ này thuộc về (hộp thoại modal, popup của app).

        Đây là cách EWMH nói \"tôi là hộp thoại của cửa sổ kia\". ``None`` khi cửa sổ không khai báo
        (mọi cửa sổ cấp cao nhất bình thường), hoặc khi thuộc tính trỏ vào chính nó.
        """
        props = self._cached_props(hwnd)
        owner = _first_int(props.get('WM_TRANSIENT_FOR') or '')
        if owner is None or int(owner) == int(hwnd):
            return None
        return int(owner)

    def is_own_window(self, hwnd: int, candidate: int) -> bool:
        """``candidate`` có phải chính ``hwnd`` hoặc một hộp thoại của ``hwnd`` không.

        Dùng cho hai chốt chặn input: khi một ứng dụng mở hộp thoại modal của chính nó (VS Code,
        Chrome, trình soạn thảo…), cửa sổ hộp thoại **có** tiêu điểm và **nằm trên** cửa sổ đích.
        Chốt cũ coi đó là \"bị cửa sổ khác che\" nên mọi thao tác vào ứng dụng đều bị từ chối, và
        không có đường nào để bấm nút của hộp thoại — agent chết cứng. Hộp thoại của chính ứng dụng
        thì vẫn là ứng dụng đích, nên nhận.
        """
        value = int(candidate)
        target = int(hwnd)
        for _ in range(4):      # chuỗi hộp thoại lồng nhau (hộp thoại của hộp thoại) hiếm khi sâu hơn
            if value == target:
                return True
            owner = self.get_window_owner(value)
            if owner is None:
                return False
            value = owner
        return value == target

    def transient_windows(self, hwnd: int) -> list[int]:
        """Các hộp thoại/popup của ``hwnd`` đang hiển thị, **dưới → trên** theo chồng cửa sổ.

        Chỉ xét những cửa sổ nằm TRÊN ``hwnd``: đúng thứ tự cần để ghép ảnh, và cũng đúng thực tế —
        hộp thoại của một ứng dụng luôn ở trên cửa sổ chính của nó.
        """
        stacking = self._client_list()
        if not stacking:
            return []
        target = int(hwnd)
        start = stacking.index(target) + 1 if target in stacking else 0
        found: list[int] = []
        for candidate in stacking[start:]:
            if candidate == target:
                continue
            if self.get_window_owner(candidate) == target and self.is_window_visible(candidate):
                found.append(candidate)
        return found

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
        props = self.window_properties(value)
        if not props:
            raise PlatformError(CAPTURE_FAILED, 'cửa sổ X11 không còn tồn tại.', hwnd=value)
        rect = self.get_window_rect(value, fresh=True)
        if rect is None:
            raise PlatformError(CAPTURE_FAILED, 'không đọc được hình học cửa sổ X11.', hwnd=value)
        # Lời gọi `window_properties` ngay trên vừa ghi cache, nên các hàm đọc dưới đây dùng lại
        # đúng dict đó — không thêm lời gọi `xprop` nào.
        pid = self.get_window_pid(value)
        state = str(props.get('_NET_WM_STATE') or '')
        return WindowInfo(
            hwnd=value,
            title=self.get_window_text(value),
            class_name=self.get_class_name(value),
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

    def set_foreground_window(self, hwnd: int, *, wait: float = ACTIVATE_WAIT_SEC) -> bool:
        """Đưa cửa sổ lên trước và cho nó tiêu điểm (``xdotool windowactivate``).

        **Không** dùng ``--sync``. Khi cửa sổ đích đang có hộp thoại modal của chính nó, WM từ chối
        kích hoạt, và ``--sync`` chặn cho tới hết thời gian chờ của công cụ: đo trên máy này là
        **hơn 12 giây cho một lời gọi** (mỗi thao tác input của agent treo theo, rồi vẫn hỏng). Ở
        đây gửi yêu cầu rồi tự thăm dò ``_NET_ACTIVE_WINDOW`` trong ``wait`` giây — biết ngay kết quả
        và rẻ hơn ``--sync`` (đo được 62 ms → 3 ms cho mỗi lần kích hoạt).
        """
        tool = self._tool('xdotool')
        if tool is None:
            # Máy thiếu công cụ là lỗi triển khai, không phải "cửa sổ vừa đổi": nói thẳng tên gói,
            # nếu trả `False` thì lớp gọi chỉ báo được "cửa sổ mất tiêu điểm" và người dùng mò sai chỗ.
            raise PlatformError(
                X11_UNAVAILABLE,
                'thiếu `xdotool` — cài gói xdotool để BoxFox điều khiển cửa sổ trên Linux.',
                tool='xdotool',
            )
        result = self._run([tool, 'windowactivate', str(int(hwnd))])
        # Ghi NGAY khi yêu cầu đã gửi, không đợi WM: tiêu điểm đổi ở phía WM vài ms sau đó, và bộ
        # theo dõi "người thật chạm máy" lấy mẫu ở luồng khác — ghi muộn là có khe hở để nó đọc
        # cú kích hoạt của chính ta thành người thật.
        if result.ok:
            self._own_foreground = int(hwnd)
        target = int(hwnd)
        if not result.ok or wait <= 0:
            return result.ok
        deadline = time.monotonic() + wait
        while True:
            if self.get_foreground_window() == target:
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

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
        # Ghi trước khi di chuyển (xem `input.click`): bộ theo dõi ở luồng khác không được đọc cú
        # di chuyển của chính ta thành người thật.
        self.note_own_pointer(int(x), int(y))
        return self._run([tool, 'mousemove', str(int(x)), str(int(y))]).ok

    # -- phát hiện người thật chạm máy ----------------------------------------
    #
    #: Nền tảng này tự theo dõi được người can thiệp (không cần hook của HĐH).
    supports_idle_watch = True

    def note_own_pointer(self, x: int, y: int) -> None:
        """Ghi vị trí con trỏ mà CHÍNH TA vừa đặt, để không đọc nó là người thật.

        ``click`` tự di chuyển con trỏ rồi trả về chỗ cũ; cả hai lần đều phải đi qua đây.
        """
        self._own_pointer = (int(x), int(y))

    def last_input_tick(self) -> int:
        """Bộ đếm thô của "người vừa tương tác", lấy mẫu từ con trỏ và tiêu điểm.

        Mỗi lời gọi lấy mẫu một lần (một ``xdotool``, một ``xprop``) và tăng bộ đếm khi:

        * con trỏ đổi vị trí mà không phải vị trí ta vừa đặt, hoặc
        * cửa sổ đang có tiêu điểm đổi mà không phải cửa sổ ta vừa kích hoạt.

        Cách này **không** nhìn thấy bàn phím (X11 không có hook) và có thể báo nhầm khi một ứng
        dụng khác tự đổi tiêu điểm (ví dụ cửa sổ mới mở đòi focus). Đổi lại, nó không bao giờ
        tự kích hoạt bằng chính cú click của agent — điều tệ nhất trong một cơ chế tự nhả quyền.
        """
        pointer = self.get_cursor_pos()
        if pointer is not None:
            if self._last_pointer is not None and pointer != self._last_pointer:
                if pointer != self._own_pointer:
                    self._input_tick += 1
                    self._last_change_at = time.monotonic()
            self._last_pointer = pointer
        foreground = self.get_foreground_window()
        if foreground is not None:
            if self._last_foreground is not None and int(foreground) != int(self._last_foreground):
                if int(foreground) != int(self._own_foreground or 0):
                    self._input_tick += 1
                    self._last_change_at = time.monotonic()
            self._last_foreground = int(foreground)
        if self._last_change_at is None:
            # Mẫu đầu tiên: ta biết trạng thái hiện tại, nên đồng hồ "yên ắng" bắt đầu từ đây.
            self._last_change_at = time.monotonic()
        return self._input_tick

    def idle_seconds(self) -> float | None:
        """Số giây kể từ lần đổi con trỏ/tiêu điểm cuối cùng mà ta QUAN SÁT được.

        X11 không có "thời điểm người cuối cùng tương tác"; đây là suy luận từ chính các mẫu của
        :meth:`last_input_tick`, nên nó chỉ đúng kể từ lần lấy mẫu đầu tiên.
        """
        if self._last_change_at is None:
            return None
        return max(0.0, time.monotonic() - self._last_change_at)

    # -- phiên / quyền ---------------------------------------------------------

    def is_interactive_session(self) -> bool:
        """Có ``DISPLAY`` **và** X server trả lời ⇒ đây là phiên tương tác được.

        Phải hỏi kích thước màn hình ảo: ``DISPLAY`` trỏ vào X server đã tắt thì mọi lời gọi đều
        rỗng và kích thước là 0×0. (Đừng viết ``bool(bounds[2:])`` — tuple ``(0, 0)`` vẫn là
        truthy, nên phép thử đó nhận mọi máy hỏng.)
        """
        width, height = self.virtual_screen_bounds()[2:]
        return int(width) > 0 and int(height) > 0

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
