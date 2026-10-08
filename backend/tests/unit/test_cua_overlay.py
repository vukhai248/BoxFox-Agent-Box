"""F — viền báo vùng đang bị điều khiển: quyết định hiện/ẩn/bám cửa sổ.

Toàn bộ phần quyết định của overlay nằm ở `agent_core/cua_overlay.py` và chạy được trên Linux với
một nền tảng giả. Phần vẽ cửa sổ thật (`CuaOverlayWindow`) chỉ chạy trên Windows; ở đây chỉ kiểm
hợp đồng mà nó phải theo: `overlay_show(bounds, color)`, `overlay_set_bounds(bounds)`, `overlay_hide()`.
"""
from __future__ import annotations

import time

from agentbox.agent_core import cua_overlay
from agentbox.agent_core.cua_overlay import CuaOverlay
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


def window(hwnd=100, *, rect=(10, 20, 300, 200), title='Notepad'):
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
    overlay.note(window(rect=(50, 60, 400, 300)))
    assert [name for name, _args in surface.calls] == ['overlay_show', 'overlay_set_bounds']
    assert surface.calls[1][1][0] == {'x': 50, 'y': 60, 'width': 400, 'height': 300}


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
        overlay.note(window(rect=(1, 1, 100, 100)))
    assert overlay.snapshot()['visible'] is True


def test_a_failing_platform_disables_the_border_instead_of_blocking_cua():
    surface = FakeOverlaySurface(fail_on='overlay_show')
    overlay = CuaOverlay(surface)
    for _ in range(3):
        assert overlay.note(window()) is False
    assert overlay.enabled is False
    assert overlay.snapshot()['reason'].startswith('overlay_failed:')
    assert overlay.note(window()) is False


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
