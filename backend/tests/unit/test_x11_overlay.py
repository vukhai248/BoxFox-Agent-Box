"""Viền báo CUA trên Linux/X11 (`sandbox/x11/overlay.py`) + hai lỗi hình học của tầng dùng chung.

Ba nhóm ca, chạy được trên máy **không có X server**:

1. **Phần thuần** — hình dạng băng (`band_width`, `ring_rectangles`, `sample_points`), đường mờ dần
   (`fade_alpha`, `ring_alpha`) và phép pha màu (`blend`, `ring_colour`, `paint_plan`). Đây là chỗ dễ
   sai mà mắt thường không thấy: băng dày sai, điểm lấy mẫu rơi ngoài hộp, màu không đơn điệu.
2. **Phần cửa sổ với display giả** (bơm qua `overlay.open_display`): cửa sổ `override_redirect`,
   shape Bounding đúng bằng các vòng, shape Input **rỗng**, `map` rồi nâng lên trên cùng, và **không**
   bao giờ gọi `set_input_focus`. Display giả ném lỗi ⇒ lời gọi sau phải **ném**
   `PlatformError(CAPTURE_FAILED)` để `CuaOverlay` đếm và tự tắt sau ba lần.
3. **Nối dây**: `build_cua_overlay` chọn mặt viền theo nền tảng và nói được lý do khi thiếu gói;
   `machine_router.window_rect_payload` đọc đúng `(left, top, right, bottom)`; đích CUA "cả máy" cũng
   được gọi viền (cửa sổ tổng hợp `hwnd = 0`).
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentbox.agent_core.cua_overlay import CuaOverlay
from agentbox.sandbox.x11 import overlay as ov
from agentbox.sandbox.win.errors import CAPTURE_FAILED, PlatformError
from test_cua_overlay import FakeOverlaySurface

# ---------------------------------------------------------------------------
# 1. Phần thuần
# ---------------------------------------------------------------------------


def test_band_width_follows_the_eighth_of_the_screen_with_a_one_third_ceiling():
    """Số đo trên máy này: màn 1920×1080 ⇒ 135 px; cửa sổ 600×400 ⇒ 133; cửa sổ 200×150 ⇒ 50."""
    assert ov.band_width(1920, 1080, 1920, 1080) == 135
    assert ov.band_width(600, 400, 1920, 1080) == 133
    assert ov.band_width(200, 150, 1920, 1080) == 50
    # Cửa sổ nhỏ hơn nữa: trần 1/3 vẫn giữ, không bao giờ trả 0 cho một vùng có kích thước thật.
    assert ov.band_width(30, 30, 1920, 1080) == 10
    assert ov.band_width(0, 100, 1920, 1080) == 0
    # Chưa biết màn hình: lấy chính vùng viền làm mốc, không vẽ băng dày 0.
    assert ov.band_width(800, 600) == 75


def test_ring_rectangles_are_one_pixel_thick_and_inside_the_box():
    width, height, band = 200, 120, 5
    rects = ov.ring_rectangles(width, height, band)
    assert len(rects) == 4 * band
    for x, y, w, h in rects:
        assert w >= 1 and h >= 1
        assert x >= 0 and y >= 0 and x + w <= width and y + h <= height
        assert w == 1 or h == 1, 'mỗi hình phải dày đúng 1 px'
    for ring in range(band):
        ring_rects = rects[ring * 4:(ring + 1) * 4]
        assert ring_rects == [
            (ring, ring, width - 2 * ring, 1),
            (ring, height - ring - 1, width - 2 * ring, 1),
            (ring, ring, 1, height - 2 * ring),
            (width - ring - 1, ring, 1, height - 2 * ring),
        ]


def test_two_rings_never_cover_the_same_pixel():
    """Vòng `t` nằm sát đúng mép `t`, nên hai vòng khác nhau không chồng lên nhau."""
    width, height, band = 40, 30, 6
    rects = ov.ring_rectangles(width, height, band)
    pixels: dict[tuple[int, int], int] = {}
    for ring in range(band):
        for x, y, w, h in rects[ring * 4:(ring + 1) * 4]:
            for px in range(x, x + w):
                for py in range(y, y + h):
                    key = (px, py)
                    assert key not in pixels or pixels[key] == ring, 'vòng %d đè lên vòng %d' % (
                        ring, pixels.get(key))
                    pixels[key] = ring


def test_an_empty_band_draws_nothing():
    assert ov.ring_rectangles(100, 100, 0) == []
    assert ov.ring_rectangles(100, 100, -3) == []
    assert ov.band_width(-1, 10, 1920, 1080) == 0


def test_sample_points_stay_inside_the_box_even_for_tiny_windows():
    for width, height, inset in ((1920, 1080, 2), (10, 4, 2), (3, 3, 9), (1, 1, 0), (2, 5, 137)):
        points = ov.sample_points(width, height, inset)
        assert len(points) == 4
        for x, y in points:
            assert 0 <= x < width and 0 <= y < height


def test_sample_points_sit_at_the_mid_edges():
    assert ov.sample_points(100, 50, 2) == [(2, 24), (97, 24), (49, 2), (49, 47)]


def test_fade_alpha_starts_at_the_peak_and_never_grows():
    band = 135
    assert ov.fade_alpha(0, band) == ov.PEAK_ALPHA
    values = [ov.fade_alpha(ring, band) for ring in range(band + 1)]
    assert values == sorted(values, reverse=True)
    assert values[-1] == 0.0
    assert ov.fade_alpha(5, 0) == 0.0


def test_the_core_stays_at_peak_alpha():
    assert ov.ring_alpha(0, 135) == ov.PEAK_ALPHA
    assert ov.ring_alpha(1, 135) == ov.PEAK_ALPHA
    assert ov.ring_alpha(2, 135) < ov.PEAK_ALPHA


def test_blend_hits_both_ends():
    backdrop, accent = (238, 244, 249), (0x38, 0xBD, 0xF8)
    assert ov.blend(backdrop, accent, 0) == backdrop
    assert ov.blend(backdrop, accent, 1) == accent
    assert ov.blend(backdrop, accent, -1) == backdrop
    assert ov.blend(backdrop, accent, 2) == accent
    # Số đo của spike: alpha 0,5 trên nền sáng cho (147, 216, 248).
    assert ov.blend(backdrop, accent, 0.5) == (147, 216, 248)


def test_the_fade_never_darkens_towards_the_middle():
    """Alpha giảm theo vòng ⇒ màu trên nền xám phải đơn điệu nhạt dần (không nhấp nhô)."""
    values = [ov.ring_colour(ring, 135, (0, 0, 0), (255, 255, 255))[0] for ring in range(135)]
    assert values == sorted(values, reverse=True)
    assert values[0] == 128          # PEAK_ALPHA = 0,5 trên nền đen
    assert values[1] == 128          # lõi đặc CORE_PX = 2


def test_painting_reuses_at_most_drawn_colours_and_stays_within_two_levels():
    backdrop, accent = (238, 244, 249), (0x38, 0xBD, 0xF8)
    for band in (1, 8, 50, 133):          # 133 = trần 1/3 của cửa sổ 600×400
        plan = ov.paint_plan(600, 400, band, backdrop, accent)
        assert len(plan) <= ov.DRAWN_COLOURS
        drawn = sum(len(rects) for _colour, rects in plan)
        assert drawn == 4 * band, 'không được bỏ vòng nào'
        for ring in range(band):
            colour = ov.ring_colour(ring, band, backdrop, accent)
            exact = ov.blend(backdrop, accent, ov.ring_alpha(ring, band))
            assert all(abs(colour[index] - exact[index]) <= 2 for index in range(3)), ring


def test_unavailable_reason_names_the_package_only_when_xlib_is_missing(monkeypatch):
    monkeypatch.setattr(ov, '_load_xlib', lambda: SimpleNamespace(display=SimpleNamespace()))
    assert ov.unavailable_reason() == ''

    def missing():
        raise ImportError('No module named Xlib')

    monkeypatch.setattr(ov, '_load_xlib', missing)
    reason = ov.unavailable_reason()
    assert 'python-xlib' in reason and 'python3-xlib' in reason
    assert reason.startswith('thiếu `')


def test_the_module_imports_without_xlib():
    """Mô-đun phải nhập được khi máy chưa cài gói: hằng số giao thức khai tại chỗ, `Xlib` nạp lười.

    `python-xlib` **đã có** trong venv này (từ J3), nên tiến trình đang chạy không còn chứng minh
    được cảnh "chưa cài gói": `agentbox.sandbox.x11.overlay` đã nhập xong từ trước. Phải dựng một
    tiến trình con với `Xlib` bị **chặn** ở `sys.meta_path`.

    Bộ chặn được kiểm là **có tác dụng** (`open_display()` phải ném `ImportError`) — thiếu bước đó
    thì một bộ chặn hỏng vẫn cho ca này xanh, và nó lại thành câu khẳng định rỗng lần nữa.
    """
    root = Path(__file__).resolve().parents[2]         # backend/ (pytest.ini trỏ `pythonpath` vào src)
    program = textwrap.dedent(
        """
        import sys


        class ChanXlib:
            '''Chặn `Xlib` và `Xlib.*` như thể gói chưa được cài.'''

            def find_spec(self, name, path=None, target=None):
                if name == 'Xlib' or name.startswith('Xlib.'):
                    raise ImportError('No module named %r (bị chặn để kiểm tra)' % name)
                return None


        sys.meta_path.insert(0, ChanXlib())

        from agentbox.sandbox.x11 import overlay as ov

        assert 'Xlib' not in sys.modules, 'nhập mô-đun mà đã nạp `Xlib` là sai (phải nạp lười)'
        assert ov.X_INPUT_OUTPUT == 1 and ov.SHAPE_INPUT == 2 and ov.SHAPE_BOUNDING == 0
        try:
            ov.open_display()
        except ImportError:
            pass
        else:
            raise AssertionError('bộ chặn `Xlib` không có tác dụng — ca kiểm này vô nghĩa')
        assert 'python-xlib' in ov.unavailable_reason(), 'thiếu gói phải nói ra tên gói'
        print('OK_KHONG_XLIB')
        """
    )
    env = dict(os.environ)
    env['PYTHONPATH'] = os.pathsep.join(
        [str(root / 'src')] + [part for part in (env.get('PYTHONPATH') or '').split(os.pathsep) if part])
    done = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True, env=env,
                          cwd=str(root), timeout=120)
    assert done.returncode == 0 and 'OK_KHONG_XLIB' in done.stdout, done.stderr or done.stdout


# ---------------------------------------------------------------------------
# 2. Cửa sổ viền với display giả
# ---------------------------------------------------------------------------


class FakeImage:
    def __init__(self, data: bytes):
        self.data = data


class FakeGc:
    def __init__(self):
        self.colours = []

    def change(self, **keys):
        self.colours.append(keys.get('foreground'))


class FakeWindow:
    """Cửa sổ X11 giả: ghi lại mọi lời gọi mà lớp viền phải thực hiện."""

    def __init__(self, *, fail_on=None, pixel=(0, 0, 0), window_id=42):
        self.id = window_id
        self.calls = []
        self.shapes = []
        self.painted = []
        self.gc = None
        self.fail_on = fail_on
        self.pixel = pixel
        self.focused = False

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.fail_on == name:
            raise RuntimeError('X server từ chối `%s`' % name)

    def create_gc(self, **keys):
        self.gc = FakeGc()
        return self.gc

    def shape_rectangles(self, operation, destination_kind, ordering, x_offset, y_offset, rectangles):
        self._record('shape_rectangles', operation, destination_kind, ordering, x_offset, y_offset,
                     list(rectangles))
        self.shapes.append((destination_kind, list(rectangles)))

    def configure(self, **keys):
        self._record('configure', **keys)

    def map(self):
        self._record('map')

    def unmap(self):
        self._record('unmap')

    def destroy(self):
        self._record('destroy')

    def poly_fill_rectangle(self, gc, rectangles):
        self._record('poly_fill_rectangle', gc, list(rectangles))
        self.painted.extend(rectangles)

    def set_input_focus(self, *args, **kwargs):     # pragma: no cover - phải KHÔNG bao giờ được gọi
        self.focused = True
        self._record('set_input_focus', *args, **kwargs)

    def get_image(self, x, y, width, height, image_format, plane_mask):
        self._record('get_image', x, y, width, height, image_format, plane_mask)
        red, green, blue = self.pixel
        return FakeImage(bytes((blue, green, red, 255)))


class FakeRoot(FakeWindow):
    def create_window(self, x, y, width, height, border_width, depth, window_class, visual, **keys):
        self._record('create_window', x, y, width, height, border_width, depth, window_class,
                     visual, **keys)
        self.child = FakeWindow(fail_on=self.fail_on, pixel=self.pixel, window_id=43)
        return self.child


class FakeScreen:
    def __init__(self, root, width, height):
        self.root = root
        self.root_depth = 24
        self.width_in_pixels = width
        self.height_in_pixels = height


class FakeDisplay:
    def __init__(self, *, width=1920, height=1080, pixel=(0, 0, 0), fail_on=None):
        self.root = FakeRoot(fail_on=fail_on, pixel=pixel)
        self.screen_obj = FakeScreen(self.root, width, height)
        self.closed = False
        self.synced = 0
        self.resources = []

    def screen(self):
        return self.screen_obj

    def create_resource_object(self, kind, resource_id):
        window = FakeWindow(pixel=self.root.pixel, window_id=int(resource_id))
        self.resources.append((kind, resource_id, window))
        return window

    def sync(self):
        self.synced += 1

    def close(self):
        self.closed = True


@pytest.fixture
def fake_display(monkeypatch):
    """Bơm display giả vào luồng công nhân (venv này KHÔNG có `python-xlib`)."""
    return install_display(monkeypatch)


def install_display(monkeypatch, **kwargs):
    display = FakeDisplay(**kwargs)

    def open_fake(name=None):
        return display

    monkeypatch.setattr(ov, 'open_display', open_fake)
    return display


BOUNDS = {'x': 300, 'y': 200, 'width': 900, 'height': 600}


def test_overlay_show_creates_a_click_through_override_redirect_window(fake_display):
    overlay = ov.X11OverlayWindow()
    overlay.overlay_show(BOUNDS, (0x38, 0xBD, 0xF8))

    created = [call for call in fake_display.root.calls if call[0] == 'create_window']
    assert len(created) == 1
    _name, args, keys = created[0]
    assert args[:8] == (300, 200, 900, 600, 0, 24, ov.X_INPUT_OUTPUT, ov.X_COPY_FROM_PARENT)
    assert keys['override_redirect'] is True
    assert keys['event_mask'] == 0

    window = fake_display.root.child
    shapes = dict(window.shapes)
    band = ov.band_width(900, 600, 1920, 1080)
    assert band == 135
    assert shapes[ov.SHAPE_BOUNDING] == ov.ring_rectangles(900, 600, band)
    assert shapes[ov.SHAPE_INPUT] == [], 'shape Input phải RỖNG thì cú bấm mới xuyên qua viền'

    names = [call[0] for call in window.calls]
    assert 'map' in names
    assert ('configure', (), {'stack_mode': ov.X_ABOVE}) in window.calls
    assert 'set_input_focus' not in names
    assert window.focused is False
    assert window.painted, 'phải vẽ băng viền'
    overlay.overlay_close()


def test_the_band_narrows_to_a_third_of_a_small_window(fake_display):
    """Cửa sổ 600×400 ⇒ băng 133 px (trần 1/3), không phải 135 px của màn hình."""
    overlay = ov.X11OverlayWindow()
    overlay.overlay_show({'x': 0, 'y': 0, 'width': 600, 'height': 400})
    window = fake_display.root.child
    assert window.shapes[-2][1] == ov.ring_rectangles(600, 400, 133)
    overlay.overlay_close()


def test_the_border_repaints_when_the_window_moves(fake_display):
    overlay = ov.X11OverlayWindow()
    overlay.overlay_show(BOUNDS)
    window = fake_display.root.child
    before = len(window.shapes)
    overlay.overlay_set_bounds({'x': 0, 'y': 0, 'width': 400, 'height': 300})
    assert len(window.shapes) > before, 'đổi vùng phải đặt lại shape'
    created = [call for call in fake_display.root.calls if call[0] == 'create_window']
    assert len(created) == 1, 'không được tạo cửa sổ thứ hai'
    assert window.shapes[-2][1] == ov.ring_rectangles(400, 300, ov.band_width(400, 300, 1920, 1080))
    overlay.overlay_close()


def raised(window):
    """Số lần cửa sổ viền được đặt lại lên trên cùng."""
    return len([call for call in window.calls
                if call[0] == 'configure' and call[2].get('stack_mode') == ov.X_ABOVE])


def test_the_border_is_raised_again_on_every_region_change(fake_display):
    """`override_redirect` giữ nguyên chỗ trong chồng cửa sổ: nâng ở lúc `map()` là chưa đủ.

    WM nâng một cửa sổ khác lên trên thì viền bị che **giữa lượt CUA** — mà lúc đó `CuaOverlay`
    chỉ gọi `overlay_set_bounds`. Đo trên `:1`: cửa sổ che phủ làm cả băng biến mất cho tới lần
    `show` sau (tới 15 s auto-hide) trong khi CUA vẫn chạy.
    """
    overlay = ov.X11OverlayWindow()
    overlay.overlay_show(BOUNDS)
    window = fake_display.root.child
    after_show = raised(window)
    assert after_show >= 1, 'lần `show` đầu phải nâng viền'
    overlay.overlay_set_bounds({'x': 0, 'y': 0, 'width': 400, 'height': 300})
    assert raised(window) == after_show + 1, 'lệnh đổi vùng phải nâng lại viền'
    overlay.overlay_set_bounds({'x': 0, 'y': 0, 'width': 400, 'height': 300})
    assert raised(window) == after_show + 2, 'lần đổi vùng nào cũng phải nâng lại'
    overlay.overlay_close()


def test_the_idle_tick_raises_the_border_back_above(fake_display):
    """Nhịp rảnh 1 Hz cũng nâng lại (và **không** vẽ lại khi màu nền không đổi — giá phải rẻ)."""
    overlay = ov.X11OverlayWindow()
    overlay.overlay_show(BOUNDS)
    window = fake_display.root.child
    after_show, painted = raised(window), len(window.painted)
    overlay._refresh()                       # nhịp rảnh: `_loop` gọi hàm này mỗi `REFRESH_SEC`
    assert raised(window) == after_show + 1, 'nhịp rảnh phải nâng lại viền'
    assert len(window.painted) == painted, 'màu nền không đổi thì không được vẽ lại'
    overlay.overlay_hide()
    hidden = raised(window)
    overlay._refresh()                       # đang ẩn: không có gì để nâng
    assert raised(window) == hidden, 'viền đang ẩn thì không nâng'
    overlay.overlay_close()


def test_hide_and_close_never_raise(fake_display):
    overlay = ov.X11OverlayWindow()
    overlay.overlay_show(BOUNDS)
    overlay.overlay_hide()
    assert ('unmap', (), {}) in fake_display.root.child.calls
    overlay.overlay_close()
    assert ('destroy', (), {}) in fake_display.root.child.calls
    assert fake_display.closed is True
    overlay.overlay_hide()          # sau khi đóng: vẫn không ném


def test_a_broken_display_makes_the_next_show_raise_a_coded_error(monkeypatch):
    install_display(monkeypatch, fail_on='map')
    overlay = ov.X11OverlayWindow()
    with pytest.raises(PlatformError) as first:
        overlay.overlay_show(BOUNDS)
    assert first.value.code == CAPTURE_FAILED
    with pytest.raises(PlatformError) as second:
        overlay.overlay_set_bounds(BOUNDS)
    assert second.value.code == CAPTURE_FAILED
    with pytest.raises(PlatformError):
        overlay.overlay_show(BOUNDS)
    overlay.overlay_close()          # đường dọn dẹp vẫn không ném


def test_a_display_that_cannot_open_reports_the_reason(monkeypatch):
    def refuse(name=None):
        raise OSError('không kết nối được X server')

    monkeypatch.setattr(ov, 'open_display', refuse)
    overlay = ov.X11OverlayWindow(display=':77')
    with pytest.raises(PlatformError) as excinfo:
        overlay.overlay_show(BOUNDS)
    assert excinfo.value.code == CAPTURE_FAILED
    assert 'X11' in str(excinfo.value)
    assert ':77' in str(excinfo.value)
    assert overlay.screen_bounds() is None
    overlay.overlay_close()
    overlay.overlay_close()


def test_the_backdrop_comes_from_the_target_window_and_falls_back_when_unreadable(fake_display):
    overlay = ov.X11OverlayWindow()
    overlay.overlay_source(23068675)
    overlay.overlay_show(BOUNDS)
    assert fake_display.resources, 'phải đọc màu nền từ chính cửa sổ đích'
    assert fake_display.resources[0][0] == 'window'
    assert fake_display.resources[0][1] == 23068675
    source_window = fake_display.resources[0][2]
    # Điểm lấy mẫu cách mép `SAMPLE_INSET` px và nằm giữa-cạnh.
    reads = [(call[1][0], call[1][1]) for call in source_window.calls if call[0] == 'get_image']
    assert reads == ov.sample_points(900, 600)
    overlay.overlay_close()


def test_the_machine_target_reads_the_root_outside_the_band(fake_display):
    overlay = ov.X11OverlayWindow()
    overlay.overlay_source(0)
    overlay.overlay_show({'x': 0, 'y': 0, 'width': 1920, 'height': 1080})
    band = ov.band_width(1920, 1080, 1920, 1080)
    reads = [(call[1][0], call[1][1]) for call in fake_display.root.calls if call[0] == 'get_image']
    assert reads == ov.sample_points(1920, 1080, band + ov.SAMPLE_INSET)
    assert fake_display.resources == []
    overlay.overlay_close()


def test_screen_bounds_are_read_once_the_display_is_open(fake_display):
    overlay = ov.X11OverlayWindow()
    assert overlay.screen_bounds() == (0, 0, 1920, 1080)
    overlay.overlay_close()


# ---------------------------------------------------------------------------
# 3. Nối dây: `build_cua_overlay`, hình chữ nhật cho panel, đích "cả máy"
# ---------------------------------------------------------------------------


def test_build_cua_overlay_is_off_with_the_env_switch():
    from agentbox.api import server

    desktop = SimpleNamespace(platform=object())
    assert server.build_cua_overlay({'BOXFOX_CUA_OVERLAY': '0'}, desktop) is None
    assert server.build_cua_overlay({'BOXFOX_CUA_OVERLAY': 'off'}, desktop) is None
    assert server.build_cua_overlay({}, None) is None


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='nhánh Linux')
def test_build_cua_overlay_builds_the_x11_surface_on_linux(monkeypatch):
    from agentbox.api import server

    monkeypatch.setattr(ov, 'unavailable_reason', lambda: '')
    overlay = server.build_cua_overlay({}, SimpleNamespace(platform=object()))
    assert overlay is not None
    assert overlay.snapshot()['enabled'] is True
    assert isinstance(overlay.platform, ov.X11OverlayWindow)


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='nhánh Linux')
def test_build_cua_overlay_matches_this_machine():
    """Không monkeypatch: venv này **thiếu** `python-xlib`, nên viền phải tắt kèm lý do có tên gói."""
    from agentbox.api import server

    overlay = server.build_cua_overlay({}, SimpleNamespace(platform=object()))
    assert overlay is not None
    reason = ov.unavailable_reason()
    if reason:
        assert overlay.snapshot()['enabled'] is False
        assert overlay.snapshot()['reason'] == reason
        assert 'python-xlib' in reason
    else:
        assert overlay.snapshot()['enabled'] is True


@pytest.mark.skipif(not sys.platform.startswith('linux'), reason='nhánh Linux')
def test_build_cua_overlay_says_why_the_border_is_off(monkeypatch):
    from agentbox.api import server

    monkeypatch.setattr(ov, 'unavailable_reason', lambda: 'thiếu `python-xlib` — cài gói python3-xlib.')
    overlay = server.build_cua_overlay({}, SimpleNamespace(platform=object()))
    assert overlay is not None
    assert overlay.snapshot()['enabled'] is False
    assert overlay.snapshot()['reason'] == 'thiếu `python-xlib` — cài gói python3-xlib.'


def test_the_panel_gets_a_real_width_and_height_not_the_right_and_bottom_edges():
    """Số đo trên máy này: thanh tác vụ XFCE `(96, 1039, 1824, 1080)` ⇒ 1728 × 41, không phải 1824 × 1080."""
    from agentbox.sandbox import machine_router

    window = SimpleNamespace(bounds=(96, 1039, 1728, 41), rect=(96, 1039, 1824, 1080),
                             extended_bounds=(96, 1039, 1824, 1080))
    assert machine_router.window_rect_payload(window) == {'x': 96, 'y': 1039, 'width': 1728,
                                                          'height': 41}
    # Không có `.bounds` (đối tượng chỉ khai `rect`) ⇒ vẫn phải đổi đúng hai cạnh thành rộng/cao.
    plain = SimpleNamespace(rect=(0, 0, 1920, 1080), extended_bounds=(0, 0, 1920, 1080))
    assert machine_router.window_rect_payload(plain) == {'x': 0, 'y': 0, 'width': 1920,
                                                         'height': 1080}
    # Mapping của danh sách cửa sổ (`position`/`size`) đã đúng sẵn: giữ nguyên kết quả cũ.
    entry = {'position': {'x': 10, 'y': 20}, 'size': {'width': 300, 'height': 200}}
    assert machine_router.window_rect_payload(entry) == {'x': 10, 'y': 20, 'width': 300,
                                                         'height': 200}
    assert machine_router.window_rect_payload(None) is None
    assert machine_router.window_rect_payload({'windowId': 7}) is None


def test_the_screen_window_has_no_window_id_and_the_screen_box():
    from agentbox.agent_core import cua_overlay

    window = cua_overlay.screen_window((0, 0, 1920, 1080))
    assert window.hwnd == 0 and window.title == ''
    assert window.bounds == (0, 0, 1920, 1080)
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    assert overlay.note(window) is True
    assert surface.calls[0][1][0] == {'x': 0, 'y': 0, 'width': 1920, 'height': 1080}
    assert overlay.snapshot()['windowId'] is None
    assert cua_overlay.screen_window(('0', '0', '1920', '1080')).bounds == (0, 0, 1920, 1080)
    assert cua_overlay.screen_window((0, 0, -5, 10)).bounds == (0, 0, 0, 10)


def _executor(tmp_path, platform):
    """`HostExecutor` tối thiểu cho đường chụp màn hình (không cần quyền/lease).

    `platform='win32'` chỉ để đường chụp dùng bộ giả `FakePlatform` sẵn có; nhánh "cả máy" của J4
    gọi thẳng `desktop.platform.virtual_screen_bounds()` nên không phụ thuộc tên nền tảng này.
    """
    from agentbox.agent_core import desktop_control as dc
    from agentbox.agent_core import permissions as permissions_module
    from agentbox.sandbox import host_executor as host_module

    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    control = dc.DesktopControl(profile_dir=profile, platform=platform)
    policy = permissions_module.PermissionPolicy(str(tmp_path / 'ws'), env={}, home=tmp_path)
    return host_module.HostExecutor(workspace=tmp_path / 'workspace', policy=policy,
                                    platform='win32', desktop=control,
                                    artifacts_dir=tmp_path / 'artifacts')


def test_a_machine_target_also_gets_the_border(tmp_path):
    """Đích "cả máy" không có `hwnd` nào để bám ⇒ viền dùng cửa sổ tổng hợp phủ màn hình ảo."""
    from win_fakes import FakePlatform

    platform = FakePlatform(virtual_screen=(0, 0, 1920, 1080))
    executor = _executor(tmp_path, platform)
    surface = FakeOverlaySurface()
    executor.overlay = CuaOverlay(surface)

    payload = executor._capture_screen({}, 'sess-1', target={'kind': 'machine'})
    assert payload.get('is_error') is not True
    assert surface.calls[0] == ('overlay_show',
                                ({'x': 0, 'y': 0, 'width': 1920, 'height': 1080},
                                 (0x38, 0xBD, 0xF8)),)
    assert executor.overlay.snapshot()['windowId'] is None


def test_an_unreadable_screen_size_only_skips_the_border(tmp_path, monkeypatch):
    """Đọc kích thước màn hình hỏng ⇒ `_screen_window()` trả `None` trong im lặng (viền là phụ)."""
    from win_fakes import FakePlatform

    platform = FakePlatform(virtual_screen=(0, 0, 1920, 1080))

    def broken():
        raise RuntimeError('xwininfo không trả lời')

    monkeypatch.setattr(platform, 'virtual_screen_bounds', broken)
    executor = _executor(tmp_path, platform)
    surface = FakeOverlaySurface()
    executor.overlay = CuaOverlay(surface)

    assert executor._screen_window() is None

    monkeypatch.setattr(platform, 'virtual_screen_bounds', lambda: (0, 0, 0, 0))
    assert executor._screen_window() is None, 'màn hình 0×0 thì không có vùng nào để vẽ'

    monkeypatch.setattr(platform, 'virtual_screen_bounds', lambda: None)
    assert executor._screen_window() is None

    assert executor.overlay.note(executor._screen_window()) is False
    assert surface.calls == [], 'không được vẽ viền khi không biết màn hình'


def test_a_capture_that_succeeds_is_never_broken_by_the_border_read(tmp_path, monkeypatch):
    """Chụp xong rồi mới hỏng phần đọc kích thước cho viền ⇒ ảnh chụp vẫn `is_error` không bật."""
    from win_fakes import FakePlatform

    platform = FakePlatform(virtual_screen=(0, 0, 1920, 1080))
    real = platform.virtual_screen_bounds
    seen = {'count': 0}

    def flaky():
        seen['count'] += 1
        if seen['count'] > 1:            # lần 1 là của đường chụp (phải chạy được), lần 2 là của viền
            raise RuntimeError('xwininfo không trả lời')
        return real()

    monkeypatch.setattr(platform, 'virtual_screen_bounds', flaky)
    executor = _executor(tmp_path, platform)
    surface = FakeOverlaySurface()
    executor.overlay = CuaOverlay(surface)

    payload = executor._capture_screen({}, 'sess-1', target={'kind': 'machine'})
    assert payload.get('is_error') is not True
    assert payload['cuaTarget'] == {'kind': 'machine'}
    assert seen['count'] > 1, 'viền phải thử đọc kích thước màn hình'
    assert surface.calls == [], 'không được vẽ viền khi không biết màn hình'
