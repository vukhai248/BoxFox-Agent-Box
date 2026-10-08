"""F — viền báo vùng đang bị điều khiển: quyết định hiện/ẩn/bám cửa sổ.

Toàn bộ phần quyết định của overlay nằm ở `agent_core/cua_overlay.py` và chạy được trên Linux với
một nền tảng giả. Phần vẽ cửa sổ thật chỉ chạy trên desktop: Windows dùng `CuaOverlayWindow`
(nét đứt), Linux/X11 dùng `sandbox/x11/overlay.py` (băng mờ dần); ở đây chỉ kiểm hợp đồng mà cả
hai phải theo: `overlay_show(bounds, color)`, `overlay_set_bounds(bounds)`, `overlay_hide()`.

`rect`/`extended_bounds` của `WindowInfo` là **(left, top, right, bottom)** trên CẢ HAI nền tảng
(`sandbox/x11/platform.py::get_window_rect` ghi rõ "tuyệt đối"; `windows_platform.py` cũng vậy).
Đọc bốn số đó như `(x, y, w, h)` là lỗi đã đo được: `(96, 1039, 1824, 1080)` là cửa sổ 1728×41 ở
góc dưới-phải, không phải cửa sổ 1824×1080 ở góc trên-trái. Helper `window(box=…)` dưới đây nhận
`(x, y, w, h)` cho dễ đọc rồi tự đổi sang `rect` thật.
"""
from __future__ import annotations

import time

from agentbox.agent_core import cua_overlay
from agentbox.agent_core.cua_overlay import CuaOverlay, ScreenWindow
from win_fakes import make_window


class FakeOverlaySurface:
    """Nền tảng giả của cửa sổ viền: ghi lại lệnh thay vì vẽ."""

    def __init__(self, *, fail_on=None):
        self.calls = []
        self.fail_on = fail_on

    def _call(self, name, *args):
        if self.fail_on == name:
            raise RuntimeError('nền tảng từ chối')
        self.calls.append((name, args))

    def overlay_show(self, bounds, color=None):
        self._call('overlay_show', bounds, color)

    def overlay_set_bounds(self, bounds):
        self._call('overlay_set_bounds', bounds)

    def overlay_hide(self):
        self._call('overlay_hide')

    def overlay_close(self):
        self._call('overlay_close')


def window(hwnd=100, *, box=(10, 20, 300, 200), title='Notepad'):
    """Cửa sổ giả từ hộp `(x, y, width, height)`; `rect` thật là `(left, top, right, bottom)`."""
    x, y, width, height = box
    rect = (x, y, x + width, y + height)
    return make_window(hwnd=hwnd, title=title, rect=rect, extended_bounds=rect)


def test_note_shows_the_border_around_the_window():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    assert overlay.note(window()) is True
    assert surface.calls[0] == ('overlay_show',
                               ({'x': 10, 'y': 20, 'width': 300, 'height': 200},
                                cua_overlay.BORDER_COLOR),)
    assert overlay.snapshot()['visible'] is True
    assert overlay.snapshot()['windowId'] == 100


def test_a_second_note_moves_the_border_without_recreating_the_window():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    overlay.note(window())
    overlay.note(window(box=(50, 60, 400, 300)))
    assert [name for name, _args in surface.calls] == ['overlay_show', 'overlay_set_bounds']
    assert surface.calls[1][1][0] == {'x': 50, 'y': 60, 'width': 400, 'height': 300}


def test_the_window_rectangle_is_read_as_left_top_right_bottom():
    """Số đo thật trên X11 (`DISPLAY=:1`): `(96, 1039, 1824, 1080)` là cửa sổ 1728×41."""
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    rect = (96, 1039, 1824, 1080)
    assert overlay.note(make_window(hwnd=7, rect=rect, extended_bounds=rect)) is True
    assert surface.calls[0][1][0] == {'x': 96, 'y': 1039, 'width': 1728, 'height': 41}


def test_a_rect_that_ends_before_it_starts_is_never_drawn():
    """`right <= left` (cửa sổ co lại còn 0) ⇒ không có vùng nào để vẽ."""
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    rect = (300, 200, 300, 200)
    assert overlay.note(make_window(rect=rect, extended_bounds=rect)) is False
    assert surface.calls == []
    assert overlay.snapshot()['reason'] == 'no_window'


def test_a_window_without_geometry_is_never_drawn():
    """Không biết vùng thì KHÔNG vẽ — đoán bừa chỗ đang bị điều khiển còn tệ hơn không vẽ."""
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    assert overlay.note(None) is False
    assert overlay.note(make_window(rect=(0, 0, 0, 0), extended_bounds=(0, 0, 0, 0))) is False
    assert surface.calls == []
    assert overlay.snapshot()['reason'] == 'no_window'


def test_without_a_platform_the_border_is_a_no_op():
    overlay = CuaOverlay(None)
    assert overlay.enabled is False
    assert overlay.note(window()) is False
    assert overlay.snapshot()['reason'] == 'overlay_unavailable'


def test_a_missing_package_is_said_out_loud():
    """Thiếu `python-xlib` ⇒ viền tắt nhưng `snapshot()['reason']` nói rõ thiếu gì (J3)."""
    sentence = 'thiếu `python-xlib` — cài gói python3-xlib (hoặc `pip install python-xlib`) để BoxFox vẽ viền báo trên desktop.'
    overlay = CuaOverlay(None, reason=sentence)
    assert overlay.enabled is False
    assert overlay.snapshot()['enabled'] is False
    assert overlay.snapshot()['reason'] == sentence
    assert overlay.note(window()) is False
    # Lượt CUA đầu tiên KHÔNG được xoá câu nói tên gói: panel (J8) đọc chính `reason` này để hiện
    # một dòng cảnh báo — "overlay_unavailable" thì người dùng không biết cài gì.
    assert overlay.snapshot()['reason'] == sentence
    overlay.hide('session_cleanup')
    assert overlay.snapshot()['reason'] == 'session_cleanup'
    overlay.note(window())
    assert overlay.snapshot()['reason'] == sentence


def test_the_machine_target_uses_the_virtual_screen_and_has_no_window_id():
    """Đích "cả máy" (`hwnd = 0`) ⇒ viền phủ màn hình ảo, `windowId` là `None` (không bịa số 0)."""
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    assert overlay.note(ScreenWindow(bounds=(0, 0, 1920, 1080))) is True
    assert surface.calls[0] == ('overlay_show',
                                ({'x': 0, 'y': 0, 'width': 1920, 'height': 1080},
                                 cua_overlay.BORDER_COLOR),)
    assert overlay.snapshot()['windowId'] is None
    assert overlay.snapshot()['visible'] is True


def test_a_surface_that_can_read_the_backdrop_gets_the_window_id():
    """Mặt viền nào biết đọc màu nền (X11) thì nhận `hwnd`; `0` = đọc ở cửa sổ gốc."""
    class SurfaceWithSource(FakeOverlaySurface):
        def overlay_source(self, hwnd):
            self._call('overlay_source', hwnd)

    surface = SurfaceWithSource()
    overlay = CuaOverlay(surface)
    overlay.note(window(hwnd=42))
    assert ('overlay_source', (42,)) in surface.calls
    overlay.note(ScreenWindow(bounds=(0, 0, 800, 600)))
    assert ('overlay_source', (0,)) in surface.calls


def test_a_surface_without_the_backdrop_hook_is_not_a_failure():
    """`overlay_source` là tuỳ chọn: thiếu nó KHÔNG tính là lỗi (không đếm vào `_failures`)."""
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    for _ in range(5):
        assert overlay.note(window()) is True
    assert overlay.enabled is True
    assert overlay._failures == 0
    assert overlay.snapshot()['reason'] != 'overlay_unavailable'


def test_screen_window_reads_a_four_number_box_and_survives_junk():
    assert cua_overlay.screen_window((0, 0, 1920, 1080)).bounds == (0, 0, 1920, 1080)
    assert cua_overlay.screen_window((0, 0, -5, 10)).bounds == (0, 0, 0, 10)
    assert cua_overlay.screen_window(None) == ScreenWindow()
    assert cua_overlay.screen_window((1, 2)) == ScreenWindow()
    assert cua_overlay.screen_window('bậy') == ScreenWindow()


def test_a_human_taking_the_lease_hides_the_border_at_once():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    overlay.note(window())
    overlay.pause('human_has_control')
    assert surface.calls[-1][0] == 'overlay_hide'
    assert overlay.snapshot()['visible'] is False
    assert overlay.snapshot()['paused'] == 'human_has_control'


def test_a_paused_border_does_not_come_back_on_its_own():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    overlay.pause('target_cleared')
    assert overlay.note(window()) is False
    assert 'overlay_show' not in [name for name, _ in surface.calls]
    overlay.resume()
    assert overlay.note(window()) is True
    assert surface.calls[-1][0] == 'overlay_show'


def test_the_border_hides_itself_after_the_idle_timeout():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface, auto_hide=0.02)
    overlay.note(window())
    deadline = time.monotonic() + 2
    while overlay.snapshot()['visible'] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert overlay.snapshot()['visible'] is False
    assert overlay.snapshot()['reason'] == 'idle'
    assert surface.calls[-1][0] == 'overlay_hide'


def test_fresh_activity_keeps_the_border_alive_past_the_timeout():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface, auto_hide=0.2)
    overlay.note(window())
    for _ in range(4):
        time.sleep(0.08)
        overlay.note(window(box=(1, 1, 100, 100)))
    assert overlay.snapshot()['visible'] is True


def test_a_failing_platform_disables_the_border_instead_of_blocking_cua():
    surface = FakeOverlaySurface(fail_on='overlay_show')
    overlay = CuaOverlay(surface)
    for _ in range(3):
        assert overlay.note(window()) is False
    assert overlay.enabled is False
    assert overlay.snapshot()['reason'].startswith('overlay_failed:')
    assert overlay.note(window()) is False
    # Lý do "mặt viền chết" cũng là câu nói được việc cần làm: giữ nó qua các lượt CUA sau.
    assert overlay.snapshot()['reason'].startswith('overlay_failed:')


def test_close_hides_and_closes_the_border():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface)
    overlay.note(window())
    overlay.close()
    assert 'overlay_hide' in [name for name, _ in surface.calls]
    assert 'overlay_close' in [name for name, _ in surface.calls]


def test_zero_auto_hide_keeps_the_border_until_something_hides_it():
    surface = FakeOverlaySurface()
    overlay = CuaOverlay(surface, auto_hide=0)
    overlay.note(window())
    assert overlay.snapshot()['visible'] is True
    assert overlay._timer is None
