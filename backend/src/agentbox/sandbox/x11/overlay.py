"""Viền báo vùng đang bị điều khiển trên desktop Linux/X11 — anh em của `win/windows_platform.py`.

Vì sao là một cửa sổ X11 riêng, chứ không phải một ảnh vẽ đè lên ảnh chụp: người dùng phải thấy
viền trên **màn hình thật**, không chỉ trong panel. Cách làm giống bản Windows (`CuaOverlayWindow`)
nhưng khác hẳn về hình dạng: Windows vẽ một nét đứt, X11 vẽ một **băng mờ dần** vì X11 không có
alpha thật khi máy không chạy compositor (máy đo được: `_NET_WM_CM_S0` vắng).

**Bốn điều "không bao giờ" — ba điều đầu đã ĐO trên máy này (08/10/2026, DISPLAY=:1, Xvnc
1920×1080, XFCE, không compositor):**

* **Không cướp tiêu điểm**: `override_redirect=True`, `event_mask=0`, và không bao giờ gọi
  `set_input_focus`. WM không quản lý cửa sổ này nên nó không được kích hoạt, không có trang trí.
* **Không chặn cú bấm**: shape ``Input`` đặt bằng **rỗng**, nên mọi cú bấm trong băng rơi xuống cửa
  sổ bên dưới. Đo được: `xdotool mousemove 205 300; xdotool getmouselocation` → `window:23068675`
  (cửa sổ bên dưới), không phải viền.
* **Không lọt vào danh sách cửa sổ**: `override_redirect` ⇒ không có trong `_NET_CLIENT_LIST*`.
  Đo được: `xprop -root _NET_CLIENT_LIST_STACKING` vẫn **9** cửa sổ khi viền đang hiện. Nhờ vậy viền
  không thành đích CUA (`X11Platform.window_from_point` chỉ soi danh sách đó) và không hiện trong
  danh sách cửa sổ của panel.
* **Không chặn đường CUA**: mọi lời gọi X đi qua **luồng riêng** với hạn chờ 0,5 s cho mỗi lệnh
  (`COMMAND_TIMEOUT_SEC`); lỗi nền tảng ném ra ngoài để `CuaOverlay` tự tắt viền sau ba lần, thay vì
  làm treo một lượt CUA.

**Vì sao vẽ bằng shape + `poly_fill_rectangle`:** cửa sổ được cắt đúng bằng các vòng 1 px
(`ring_rectangles`) nên phần trong suốt không cần alpha; mỗi màu chỉ tốn **một** lệnh
`poly_fill_rectangle`. Đo được trên máy này: 540 hình chữ nhật rời rạc hết **5,0 ms**, gộp theo màu
còn rẻ hơn; đọc một điểm ảnh bằng `XGetImage` hết **0,052 ms** (so với ~35 ms của
`import -crop 1x1`) nên việc làm mới màu nền mỗi giây là rẻ.

**Giới hạn đã biết, không giấu:** không có compositor ⇒ không có alpha thật, nên băng là màu đã pha
sẵn vào màu nền **lấy mẫu được**; đích "cả máy" chụp bằng `import -window root` sẽ **dính** viền của
chính ta ở sát mép (đánh đổi đã biết của khuôn `override_redirect`, bản Windows cũng vậy).
"""

from __future__ import annotations

import math
import os
import queue
import threading
import time
from typing import Any

from ..win.errors import CAPTURE_FAILED, PlatformError

# ---------------------------------------------------------------------------
# Hình dạng và màu — hằng số có tên để chỉnh một chỗ (kế hoạch §J0.1–J0.3)
# ---------------------------------------------------------------------------

#: Băng viền dày bằng 1/8 cạnh ngắn màn hình (1920×1080 ⇒ 135 px) — đúng lời chủ nhà
#: "nhạt dần khi vào tầm 1/8 màn hình".
BAND_DIVISOR = 8

#: Trần băng viền theo cạnh ngắn của vùng viền: cửa sổ 200×150 ⇒ 50 px, không bị viền phủ kín.
BAND_LIMIT_DIVISOR = 3

#: Số vòng ngoài cùng vẽ ở đỉnh alpha (lõi đặc của ảnh tham chiếu: 1–2 px).
CORE_PX = 2

#: Alpha đỉnh của màu nhấn. Đo trên nền sáng cho `(147,216,248)`, gần ảnh tham chiếu
#: `(157,195,229)` nhưng xanh hơn — đây là **một hằng số** để chủ nhà chỉnh nếu muốn xám hơn.
PEAK_ALPHA = 0.5

#: Khoảng cách từ mép tới điểm lấy màu nền, khi đọc theo chính cửa sổ đích.
SAMPLE_INSET = 2

#: Màu nền dự phòng khi không đọc được màu thật — màu trang của ảnh tham chiếu.
FALLBACK_BACKDROP = (238, 244, 249)

#: Làm mới màu nền tối đa mỗi 1 giây (mỗi lần làm mới: 4 `XGetImage` + vẽ lại nếu màu đổi).
REFRESH_SEC = 1.0

#: Hạn chờ một lệnh vẽ. Đường CUA không được phép chờ một X server treo.
COMMAND_TIMEOUT_SEC = 0.5

#: Đổi màu nền từ mức này trở lên (một kênh) thì mới vẽ lại — tránh vẽ lại vì nhiễu 1–2 mức.
COLOUR_EPSILON = 4

#: Số màu tối đa dùng lại cho các vòng. 135 vòng ⇒ 46 màu: sai lệch alpha ≤ 0,5 vòng (≤ 1 mức màu),
#: trong khi số lần đổi màu GC giảm từ 135 xuống 46 cho mỗi lần vẽ.
DRAWN_COLOURS = 64

#: Màu nhấn mặc định — cùng token `--cua` của panel và `cua_overlay.BORDER_COLOR`. `CuaOverlay`
#: luôn truyền màu của nó vào `overlay_show`; giá trị này chỉ là đường lui khi ai đó gọi thẳng lớp này.
ACCENT_COLOR = (0x38, 0xBD, 0xF8)

#: Câu nói rõ **thiếu gì** khi máy không có `python-xlib` (khuôn câu của `x11/platform.py:748`).
XLIB_MISSING_REASON = (
    'thiếu `python-xlib` — cài gói python3-xlib (hoặc `pip install python-xlib`) '
    'để BoxFox vẽ viền báo trên desktop.'
)

# ---------------------------------------------------------------------------
# Hằng số giao thức X11 (giá trị cố định trong `X.h`).
# Khai tại đây để mô-đun **không cần `Xlib` lúc nạp** — nhờ vậy máy chưa cài gói vẫn nhập được mô-đun
# (và `build_cua_overlay` còn hỏi được `unavailable_reason()`), còn test thì bơm được display giả.
# ---------------------------------------------------------------------------

X_INPUT_OUTPUT = 1
X_COPY_FROM_PARENT = 0
X_ABOVE = 0
X_ZPIXMAP = 2
X_ALL_PLANES = 0xFFFFFFFF
SHAPE_SET = 0
SHAPE_BOUNDING = 0
SHAPE_INPUT = 2
SHAPE_UNSORTED = 0


def _load_xlib():
    """Nạp `Xlib` — mô-đun **tuỳ chọn** (chỉ Linux mới cần, và chỉ để vẽ viền).

    Tách riêng để `unavailable_reason()` hỏi được "máy có gói chưa" mà không phải bắt lỗi import ở
    ba nơi, và để test bơm được một mô-đun giả (hoặc một mô-đun ném lỗi).
    """
    import Xlib

    return Xlib


def open_display(name: str | None = None):
    """Mở một `Display` X11. Tách riêng để test bơm được display giả, không cần X server."""
    return _load_xlib().display.Display(name)


def unavailable_reason() -> str:
    """`''` khi máy vẽ được viền, ngược lại là **một câu nêu tên gói cần cài**."""
    try:
        _load_xlib()
    except Exception:
        return XLIB_MISSING_REASON
    return ''


# ---------------------------------------------------------------------------
# Phần thuần — không cần X server (đây là chỗ test bám vào)
# ---------------------------------------------------------------------------


def band_width(width: int, height: int, screen_width: int = 0, screen_height: int = 0) -> int:
    """Bề dày băng viền (px) cho một vùng `width`×`height` trên màn hình `screen_width`×`screen_height`.

    Băng = 1/8 cạnh ngắn **màn hình**, nhưng không quá 1/3 cạnh ngắn **vùng viền** để một cửa sổ
    nhỏ không bị viền phủ kín. Đo được: màn 1920×1080 ⇒ 135 px; cửa sổ 600×400 trên màn đó ⇒ 133 px
    (trần 1/3 của 400); cửa sổ 200×150 ⇒ 50 px.
    """
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        return 0
    short = min(width, height)
    screen_short = min(int(screen_width), int(screen_height))
    if screen_short <= 0:
        screen_short = short              # chưa biết màn hình: lấy chính vùng viền làm mốc
    band = min(screen_short // BAND_DIVISOR, short // BAND_LIMIT_DIVISOR)
    return max(1, band)


def _ring_rectangles(width: int, height: int, ring: int) -> list[tuple[int, int, int, int]]:
    """Bốn hình chữ nhật 1 px của **một** vòng `ring` (đúng hình dạng đã đo trên máy này).

    Bốn góc bị hai hình phủ lên nhau (cùng một màu nên vô hại); vòng `ring` nằm sát đúng mép `ring`.
    """
    t = int(ring)
    if t < 0:
        return []
    width, height = int(width), int(height)
    rects = [
        (t, t, width - 2 * t, 1),
        (t, height - t - 1, width - 2 * t, 1),
        (t, t, 1, height - 2 * t),
        (width - t - 1, t, 1, height - 2 * t),
    ]
    return [rect for rect in rects if rect[2] > 0 and rect[3] > 0]


def ring_rectangles(width: int, height: int, band: int) -> list[tuple[int, int, int, int]]:
    """Toàn bộ hình chữ nhật của băng viền: `band` vòng, mỗi vòng 4 hình 1 px.

    Đây là danh sách đưa thẳng cho `shape_rectangles(...)` (shape ``Bounding``), nên **phần trong
    suốt không cần alpha**: X server cắt bỏ mọi thứ ngoài các hình này.
    """
    rects: list[tuple[int, int, int, int]] = []
    for ring in range(max(0, int(band))):
        rects.extend(_ring_rectangles(width, height, ring))
    return rects


def sample_points(width: int, height: int, inset: int = SAMPLE_INSET) -> list[tuple[int, int]]:
    """Bốn điểm giữa-cạnh để lấy màu nền, cách mép `inset` px và **luôn nằm trong hộp**.

    `inset` do người gọi chọn vì hai chế độ đọc khác nhau (đo được, không phải suy đoán):
    đọc theo **cửa sổ đích** thì lấy mẫu trong băng (`SAMPLE_INSET`) — cửa sổ trả nội dung thật của
    nó; đọc theo **root** cho đích "cả máy" thì phải lấy ở **ngoài** băng (`band + SAMPLE_INSET`),
    nếu không sẽ đọc ra chính màu viền của mình.
    """
    width, height = max(1, int(width)), max(1, int(height))
    step = max(0, int(inset))
    left = min(step, width - 1)
    right = max(0, width - 1 - step)
    top = min(step, height - 1)
    bottom = max(0, height - 1 - step)
    mid_x, mid_y = (width - 1) // 2, (height - 1) // 2
    return [(left, mid_y), (right, mid_y), (mid_x, top), (mid_x, bottom)]


def fade_alpha(ring: int, band: int) -> float:
    """Alpha của vòng `ring` theo đường mờ dần **tuyến tính**: `PEAK_ALPHA * (1 - ring/band)`.

    Đơn điệu giảm theo `ring`; `fade_alpha(0, band) == PEAK_ALPHA`; vòng cuối gần như trong suốt.
    """
    band = int(band)
    if band <= 0:
        return 0.0
    ring = max(0, min(int(ring), band))
    return PEAK_ALPHA * (1.0 - ring / band)


def ring_alpha(ring: int, band: int) -> float:
    """Alpha dùng thật cho vòng `ring`: `CORE_PX` vòng đầu giữ đỉnh, phần còn lại mờ dần."""
    if int(ring) < CORE_PX:
        return PEAK_ALPHA
    return fade_alpha(ring, band)


def blend(backdrop: tuple[int, int, int], accent: tuple[int, int, int], alpha: float) -> tuple[int, int, int]:
    """Pha màu nhấn vào màu nền theo `alpha` (0 ⇒ nền, 1 ⇒ nhấn) — thay cho alpha thật của X11."""
    ratio = max(0.0, min(1.0, float(alpha)))
    return tuple(                       # type: ignore[return-value]
        int(round(int(backdrop[index]) + (int(accent[index]) - int(backdrop[index])) * ratio))
        for index in range(3)
    )


def _colour_level(ring: int, band: int, colours: int) -> int:
    """Vòng đại diện cho nhóm màu của `ring`: gộp `band` vòng xuống còn ≤ `colours` mức.

    Làm tròn về mức gần nhất nên sai lệch alpha ≤ nửa bước — đo được là ≤ 1 mức màu cho mọi bề dày
    băng (bước = `band / DRAWN_COLOURS`, mà `PEAK_ALPHA = 0,5` nên sai lệch màu ≤ 0,5 × 255/64).
    """
    band = max(0, int(band))
    step = max(1, int(math.ceil(band / float(max(1, int(colours))))))
    return min(band, ((max(0, int(ring)) + step // 2) // step) * step)


def ring_colour(ring: int, band: int, backdrop: tuple[int, int, int], accent: tuple[int, int, int],
                *, colours: int = DRAWN_COLOURS) -> tuple[int, int, int]:
    """Màu cuối của vòng `ring` sau khi gộp nhóm màu."""
    if int(ring) < CORE_PX:
        alpha = PEAK_ALPHA              # lõi đặc: luôn đúng đỉnh, không phụ thuộc bước gộp màu
    else:
        alpha = fade_alpha(_colour_level(ring, band, colours), band)
    return blend(backdrop, accent, alpha)


def paint_plan(width: int, height: int, band: int, backdrop: tuple[int, int, int],
               accent: tuple[int, int, int], *, colours: int = DRAWN_COLOURS
               ) -> list[tuple[tuple[int, int, int], list[tuple[int, int, int, int]]]]:
    """Kế hoạch vẽ: `[(màu, [hình chữ nhật])]` — gộp theo màu để mỗi màu tốn **một** lệnh vẽ.

    Thứ tự trả về là thứ tự vòng tăng dần, nên bên vẽ chỉ cần đổi màu GC rồi
    `poly_fill_rectangle` một lần cho cả nhóm.
    """
    groups: dict[tuple[int, int, int], list[tuple[int, int, int, int]]] = {}
    for ring in range(max(0, int(band))):
        rects = _ring_rectangles(width, height, ring)
        if not rects:
            continue
        groups.setdefault(ring_colour(ring, band, backdrop, accent, colours=colours), []).extend(rects)
    return list(groups.items())


def _as_bounds(bounds: Any) -> dict:
    """Chuẩn hoá `{x, y, width, height}` (bề rộng/cao tối thiểu 1 px) — ném `PlatformError` nếu thiếu."""
    try:
        return {'x': int(bounds['x']), 'y': int(bounds['y']),
                'width': max(1, int(bounds['width'])), 'height': max(1, int(bounds['height']))}
    except (TypeError, KeyError, ValueError, IndexError):
        raise PlatformError(
            CAPTURE_FAILED,
            'viền báo cần hình chữ nhật `{x, y, width, height}`; nhận được %r.' % (bounds,),
        )


# ---------------------------------------------------------------------------
# Cửa sổ viền
# ---------------------------------------------------------------------------


class X11OverlayWindow:
    """Cửa sổ viền trên X11, cùng hợp đồng bốn hàm với `win/windows_platform.CuaOverlayWindow`.

    Cửa sổ X11 phải được tạo và dùng **từ một kết nối duy nhất**, nên lớp này giữ một luồng riêng
    (`boxfox-cua-overlay`) với `Display` riêng; lệnh của tiến trình (hiện/đổi vùng/nguồn màu/ẩn/đóng)
    đi qua hàng đợi và **không bao giờ chặn đường CUA** quá `COMMAND_TIMEOUT_SEC`.

    Đây là lớp "hỏng êm": mọi lỗi nền tảng ném ra ngoài dưới dạng `PlatformError(CAPTURE_FAILED, …)`
    để `CuaOverlay` tự đếm và tắt viền sau ba lần, thay vì làm hỏng thao tác của agent.

    `platform` được giữ lại cho **đối xứng hợp đồng** với bản Windows (`build_cua_overlay` truyền
    `desktop.platform` cho cả hai); lớp này không dùng nó — nó nói chuyện thẳng với X server.
    `thickness` là bề dày băng (px) khi muốn ghim cứng, `None` ⇒ tính bằng :func:`band_width`.
    """

    def __init__(self, platform: Any = None, *, display: str | None = None,
                 thickness: int | None = None) -> None:
        self.platform = platform
        #: Tên display để mở; `None` ⇒ `python-xlib` tự đọc `$DISPLAY` như mọi chương trình X.
        self.display_name = display
        self.thickness = int(thickness) if thickness else None
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error = ''
        self._screen: tuple[int, int, int, int] | None = None
        self._xdisplay: Any = None
        self._root: Any = None
        self._depth = 0
        self._window: Any = None
        self._gc: Any = None
        self._bounds: tuple[int, int, int, int] | None = None
        self._band = 0
        self._accent = ACCENT_COLOR
        self._source = 0
        self._backdrop = FALLBACK_BACKDROP

    # -- API cho `CuaOverlay` (giống `CuaOverlayWindow` bên Windows) ----------
    def overlay_show(self, bounds: dict, color: tuple[int, int, int] | None = None) -> None:
        """Hiện viền quanh `bounds` (`{x, y, width, height}`, toạ độ vật lý)."""
        if color:
            self._accent = tuple(int(part) for part in color[:3])
        self._post('show', _as_bounds(bounds))

    def overlay_set_bounds(self, bounds: dict) -> None:
        """Đổi vùng viền (cửa sổ đích vừa di chuyển/đổi kích thước)."""
        self._post('bounds', _as_bounds(bounds))

    def overlay_hide(self) -> None:
        """Ẩn viền. Đường dọn dẹp: không ném (CuaOverlay đã tự xử lý viền hỏng)."""
        try:
            self._post('hide')
        except Exception:
            pass

    def overlay_close(self) -> None:
        """Đóng cửa sổ viền và kết thúc luồng. Không ném — đây là đường tắt tiến trình."""
        try:
            self._post('close')
        except Exception:
            pass
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=2.0)

    # -- chỉ X11 có ----------------------------------------------------------
    def overlay_source(self, hwnd: int | None) -> None:
        """Đọc màu nền từ cửa sổ `hwnd`; `0`/`None` ⇒ đọc ở root (đích "cả máy").

        Không chờ và không ném: đây là lời gọi **tuỳ chọn** của `CuaOverlay`, hỏng thì viền vẫn vẽ
        bằng màu nền dự phòng. Lệnh xếp hàng trước lệnh vẽ nên nguồn mới được áp dụng trước khi vẽ.
        """
        self._source = int(hwnd or 0)
        self._queue.put(('source', (self._source,), threading.Event()))

    def screen_bounds(self) -> tuple[int, int, int, int] | None:
        """`(0, 0, rộng, cao)` của màn hình ảo, hoặc `None` khi chưa mở được `Display`."""
        if not self._error:
            self._ensure_thread()
            self._ready.wait(timeout=COMMAND_TIMEOUT_SEC)
        return self._screen

    # -- nội bộ: hàng đợi lệnh ----------------------------------------------
    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None:
                return
            thread = threading.Thread(target=self._run, name='boxfox-cua-overlay', daemon=True)
            self._thread = thread
            thread.start()

    def _post(self, kind: str, *args) -> bool:
        """Xếp một lệnh rồi chờ nó xong. Lỗi nền tảng ⇒ `PlatformError(CAPTURE_FAILED, …)`."""
        if self._error:
            raise PlatformError(CAPTURE_FAILED, self._error)
        done = threading.Event()
        # Xếp lệnh TRƯỚC khi dựng luồng: luồng có thể mở `Display` hỏng rồi thoát ngay, và khi đó nó
        # phải thấy lệnh này trong hàng đợi để đánh thức người gọi (nếu xếp sau, người gọi chờ hết
        # hạn 0,5 s rồi nhận câu "không phản hồi" thay vì câu nói rõ X11 hỏng).
        self._queue.put((kind, args, done))
        self._ensure_thread()
        if not done.wait(timeout=COMMAND_TIMEOUT_SEC):
            if self._error:
                raise PlatformError(CAPTURE_FAILED, self._error)
            raise PlatformError(
                CAPTURE_FAILED,
                'viền báo không phản hồi trong %.1f giây — X server có thể đang treo.' % COMMAND_TIMEOUT_SEC,
            )
        if self._error:
            raise PlatformError(CAPTURE_FAILED, self._error)
        return True

    def _fail(self, message: str, wake: threading.Event | None = None) -> None:
        """Ghi lỗi nền tảng rồi đánh thức **mọi** lệnh đang chờ (không nuốt lỗi, không treo ai)."""
        self._error = str(message)
        if wake is not None:
            wake.set()
        while True:
            try:
                _kind, _args, done = self._queue.get_nowait()
            except queue.Empty:
                break
            done.set()
        self._ready.set()

    # -- nội bộ: luồng công nhân --------------------------------------------
    def _run(self) -> None:                          # pragma: no cover - cần X server thật
        try:
            xdisplay = open_display(self.display_name)
            screen = xdisplay.screen()
            self._xdisplay = xdisplay
            self._root = screen.root
            self._depth = int(screen.root_depth)
            self._screen = (0, 0, int(screen.width_in_pixels), int(screen.height_in_pixels))
        except Exception as exc:
            self._fail(
                'không mở được kết nối X11 cho viền báo (DISPLAY=%s, %s: %s)'
                % (self.display_name or os.environ.get('DISPLAY') or '(trống)', type(exc).__name__, exc)
            )
            return
        self._ready.set()
        try:
            self._loop()
        finally:
            self._destroy_window()
            try:
                self._xdisplay.close()
            except Exception:
                pass

    def _loop(self) -> None:                         # pragma: no cover - cần X server thật
        while True:
            try:
                kind, args, done = self._queue.get(timeout=REFRESH_SEC)
            except queue.Empty:
                # Nhịp rảnh: làm mới màu nền (đọc 4 điểm ảnh, 0,05 ms/điểm) và chỉ vẽ lại khi đổi màu.
                try:
                    self._refresh()
                except Exception as exc:
                    self._fail('làm mới viền báo hỏng (%s: %s)' % (type(exc).__name__, exc))
                    return
                continue
            try:
                if kind == 'close':
                    self._destroy_window()
                    done.set()
                    return
                if kind == 'show':
                    self._apply_bounds(args[0])
                    # `map()` TRƯỚC khi vẽ: X server **bỏ** mọi nét vẽ vào cửa sổ chưa mapped, nên
                    # vẽ trước rồi map chỉ còn lại `background_pixel=0` — một băng đen (đã đo trên
                    # `:1`: đọc `root` trong băng ra `(0,0,0)` dù đã vẽ).
                    self._map_window()
                    self._paint()
                elif kind == 'bounds':
                    self._apply_bounds(args[0])
                    self._paint()
                elif kind == 'source':
                    self._source = int(args[0] or 0)
                elif kind == 'hide':
                    self._unmap_window()
            except Exception as exc:
                self._fail('vẽ viền báo hỏng (%s: %s)' % (type(exc).__name__, exc), wake=done)
                return
            done.set()

    def _apply_bounds(self, bounds: dict) -> None:
        """Tạo cửa sổ (lần đầu) hoặc đổi vùng, rồi đặt lại shape Bounding/Input."""
        x, y = int(bounds['x']), int(bounds['y'])
        width, height = int(bounds['width']), int(bounds['height'])
        if self._window is None:
            # `override_redirect=True` + `event_mask=0`: WM không quản lý ⇒ không tiêu điểm, không
            # trang trí, không vào `_NET_CLIENT_LIST*` (đo được: danh sách vẫn 9 cửa sổ).
            self._window = self._root.create_window(
                x, y, width, height, 0, self._depth, X_INPUT_OUTPUT, X_COPY_FROM_PARENT,
                override_redirect=True, background_pixel=0, event_mask=0)
            self._gc = self._window.create_gc(foreground=0)
        else:
            self._window.configure(x=x, y=y, width=width, height=height)
        self._bounds = (x, y, width, height)
        screen = self._screen or (0, 0, 0, 0)
        self._band = self.thickness or band_width(width, height, screen[2], screen[3])
        self._window.shape_rectangles(SHAPE_SET, SHAPE_BOUNDING, SHAPE_UNSORTED, 0, 0,
                                      ring_rectangles(width, height, self._band))
        # Shape Input RỖNG: cú bấm xuyên qua viền (đo được: `xdotool getmouselocation` trả cửa sổ
        # bên dưới). Không có bước này thì viền chặn mọi cú bấm trong băng của chính nó.
        self._window.shape_rectangles(SHAPE_SET, SHAPE_INPUT, SHAPE_UNSORTED, 0, 0, [])

    def _map_window(self) -> None:
        self._window.map()
        self._window.configure(stack_mode=X_ABOVE)
        self._xdisplay.sync()

    def _unmap_window(self) -> None:
        if self._window is not None:
            self._window.unmap()
            self._xdisplay.sync()

    def _destroy_window(self) -> None:
        window, self._window = self._window, None
        self._gc = None
        if window is not None:
            try:
                window.unmap()
            except Exception:
                pass
            try:
                window.destroy()
            except Exception:
                pass

    def _paint(self, backdrop: tuple[int, int, int] | None = None) -> None:
        """Vẽ toàn bộ băng: một GC, đổi màu một lần cho mỗi nhóm màu, gộp lệnh theo nhóm."""
        if self._window is None or self._bounds is None:
            return
        _x, _y, width, height = self._bounds
        backdrop = self._sample_backdrop() if backdrop is None else backdrop
        self._backdrop = backdrop
        for colour, rects in paint_plan(width, height, self._band, backdrop, self._accent):
            self._gc.change(foreground=(colour[0] << 16) | (colour[1] << 8) | colour[2])
            self._window.poly_fill_rectangle(self._gc, rects)
        self._xdisplay.sync()

    def _refresh(self) -> None:
        """Nhịp rảnh: lấy lại màu nền, chỉ vẽ lại khi màu đổi ≥ `COLOUR_EPSILON` một kênh."""
        if self._window is None or self._bounds is None:
            return
        backdrop = self._sample_backdrop()
        if all(abs(backdrop[index] - self._backdrop[index]) < COLOUR_EPSILON for index in range(3)):
            return
        self._paint(backdrop)

    def _sample_backdrop(self) -> tuple[int, int, int]:
        """Màu nền = trung bình 4 điểm giữa-cạnh; đọc hỏng cả bốn ⇒ màu nền dự phòng."""
        if self._bounds is None:
            return FALLBACK_BACKDROP
        _x, _y, width, height = self._bounds
        drawable = self._sample_drawable()
        if drawable is None:
            return FALLBACK_BACKDROP
        points = (sample_points(width, height) if self._source
                  else sample_points(width, height, self._band + SAMPLE_INSET))
        samples: list[tuple[int, int, int]] = []
        for point_x, point_y in points:
            try:
                image = drawable.get_image(int(point_x), int(point_y), 1, 1, X_ZPIXMAP, X_ALL_PLANES)
                data = bytes(image.data)
            except Exception:
                continue                       # điểm này không đọc được: bỏ qua, không bỏ cả bảng
            if len(data) >= 3:
                # ZPixmap trên máy little-endian: B, G, R[, X] — đo được trên Xvnc 24-bit.
                samples.append((data[2], data[1], data[0]))
        if not samples:
            return FALLBACK_BACKDROP
        return tuple(                          # type: ignore[return-value]
            sum(pixel[index] for pixel in samples) // len(samples) for index in range(3)
        )

    def _sample_drawable(self):
        """Drawable để lấy mẫu: cửa sổ đích khi biết `hwnd`, ngược lại là root (đích "cả máy")."""
        if not self._source:
            return self._root
        try:
            return self._xdisplay.create_resource_object('window', int(self._source))
        except Exception:
            return None
