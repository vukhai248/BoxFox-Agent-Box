"""Nền tảng X11 (`sandbox/x11`) — phần đọc/ghi hệ điều hành, kiểm bằng công cụ giả.

Bài kiểm chạy được trên máy KHÔNG có X server: `X11Platform` nhận `runner` tiêm vào, nên mọi lời
gọi `xprop`/`xwininfo`/`xdotool`/`import` đều là đầu vào giả. Cái được kiểm là những chỗ dễ sai và
khó thấy: thứ tự Z-order, phân tích chuỗi của `xprop`/`xwininfo`, phép thử cửa sổ tại một điểm, khoá
liên tiến trình, và ba chốt chặn trước khi gửi input.
"""
from __future__ import annotations

import os
import subprocess

import pytest

from agentbox.sandbox.x11 import capture as xc
from agentbox.sandbox.x11 import input as xi
from agentbox.sandbox.x11 import platform as xp
from agentbox.sandbox.win.errors import PlatformError


class FakeTools:
    """Giả lập `xprop`/`xwininfo`/`xdotool`/`import`; ghi lại lệnh đã gọi để kiểm."""

    def __init__(self, *, windows=None, props=None, rects=None, screen=(0, 0, 1920, 1080),
                 foreground=None, raw=b'', raw_by_target=None, import_fails=False, visible=None):
        self.windows = list(windows or [])          # thứ tự DƯỚI → TRÊN, như EWMH
        self.props = dict(props or {})
        self.rects = dict(rects or {})
        self.screen = screen
        self.foreground = foreground
        self.raw = raw
        self.raw_by_target = dict(raw_by_target or {})
        self.import_fails = import_fails
        self.visible = dict(visible or {})
        self.calls: list[list[str]] = []

    # -- dựng đầu ra giả ---------------------------------------------------
    def _xprop_window(self, hwnd):
        values = self.props.get(int(hwnd))
        if values is None:
            return 1, '', 'Bad window'
        lines = []
        for name, value in values.items():
            lines.append('%s(CARDINAL) = %s' % (name, value))
        return 0, '\n'.join(lines) + '\n', ''

    def _xwininfo(self, hwnd):
        rect = self.rects.get(int(hwnd))
        if rect is None:
            return 1, '', 'Bad window'
        left, top, right, bottom = rect
        return 0, ('  Absolute upper-left X:  %d\n  Absolute upper-left Y:  %d\n'
                   '  Width: %d\n  Height: %d\n  Map State: %s\n'
                   % (left, top, right - left, bottom - top,
                      'IsViewable' if self.visible.get(int(hwnd), True) else 'IsUnMapped')), ''

    def _xwininfo_root(self):
        return 0, ('  -geometry %dx%d+0+0\n  Width: %d\n  Height: %d\n'
                   % (self.screen[2], self.screen[3], self.screen[2], self.screen[3])), ''

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        tool = os.path.basename(argv[0])
        if tool == 'xprop':
            if '-root' in argv:
                name = argv[argv.index('-root') + 1]
                if name == '_NET_CLIENT_LIST_STACKING':
                    ids = ', '.join('0x%x' % hwnd for hwnd in self.windows)
                    return xp._CommandResult(0, '_NET_CLIENT_LIST_STACKING(WINDOW): window id # %s\n' % ids)
                if name == '_NET_ACTIVE_WINDOW':
                    return xp._CommandResult(0, '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x%x\n'
                                             % (self.foreground or 0))
                return xp._CommandResult(1, '', 'unknown root property')
            hwnd = argv[argv.index('-id') + 1]
            code, out, err = self._xprop_window(hwnd)
            return xp._CommandResult(code, out, err)
        if tool == 'xwininfo':
            if '-root' in argv:
                code, out, err = self._xwininfo_root()
                return xp._CommandResult(code, out, err)
            hwnd = argv[argv.index('-id') + 1]
            code, out, err = self._xwininfo(hwnd)
            return xp._CommandResult(code, out, err)
        if tool == 'xdotool':
            return xp._CommandResult(0, 'WINDOW=%s\n' % (self.foreground or 0))
        if tool == 'import':
            target = argv[argv.index('-window') + 1] if '-window' in argv else ''
            if self.import_fails and target != 'root':
                return xp._CommandResult(1, '', 'unable to read X window image', b'')
            pixels = self.raw_by_target.get(target, self.raw)
            if '-crop' in argv:                      # `import` cắt ảnh trước khi ghi ra `bgra:-`
                geometry = argv[argv.index('-crop') + 1]
                size = geometry.split('+')[0].split('x')
                pixels = pixels[:int(size[0]) * int(size[1]) * 4]
            return xp._CommandResult(0, '', '', pixels)
        return xp._CommandResult(127, '', 'không có công cụ %s' % tool)


def window_props(*, pid=4242, title='Untitled - Notepad', cls='notepad, Notepad', state='',
                 frame='0, 0, 0, 0'):
    return {
        '_NET_WM_PID': str(pid),
        'WM_CLASS': '"%s"' % cls,
        '_NET_WM_NAME': '"%s"' % title,
        'WM_NAME': '"%s"' % title,
        '_NET_WM_STATE': state,
        '_NET_FRAME_EXTENTS': frame,
    }


def build(**kwargs):
    tools = FakeTools(**kwargs)
    platform = xp.X11Platform(display=':1', runner=tools, env={'DISPLAY': ':1'})
    return platform, tools


# --------------------------------------------------------------- đọc chuỗi của xprop
def test_a_vietnamese_window_title_survives_the_octal_escapes_of_xprop():
    """`xprop` ghi byte UTF-8 thành escape bát phân; tiêu đề tiếng Việt phải đọc ra chữ thật."""
    raw = '"BoxFox\\342\\200\\224Agent Box \\341\\273\\247\\341\\273\\251\\342\\200\\224"'
    assert xp._unescape(raw) == 'BoxFox—Agent Box ủứ—'


def test_a_title_with_a_quote_and_a_backslash_is_read_correctly():
    assert xp._unescape('"C:\\\\Users\\"BoxFox\\""') == 'C:\\Users"BoxFox"'


def test_an_unquoted_value_is_returned_as_is():
    assert xp._unescape('4242') == '4242'


# --------------------------------------------------------------- danh sách cửa sổ
def test_enum_windows_lists_the_ewmh_stack_top_first():
    """`_NET_CLIENT_LIST_STACKING` xếp dưới → trên; `enum_windows` phải đảo lại thành trên → dưới."""
    platform, _tools = build(windows=[0x10, 0x20, 0x30], props={0x10: window_props(), 0x20: window_props(),
                                                               0x30: window_props()})
    assert platform.enum_windows() == [0x30, 0x20, 0x10]


def test_describe_window_reads_identity_and_geometry_in_two_calls():
    """Sáu thuộc tính của một cửa sổ phải đến từ MỘT lời gọi `xprop` (không phải sáu)."""
    platform, tools = build(windows=[0x10], props={0x10: window_props(pid=99, title='Chrome',
                                                                     cls='google-chrome, Google-chrome')},
                            rects={0x10: (5, 6, 105, 206)})
    platform.process_image_name = lambda pid: 'chrome' if pid == 99 else None
    info = platform.describe_window(0x10)
    assert (info.hwnd, info.title, info.class_name, info.pid) == (0x10, 'Chrome', 'Google-chrome', 99)
    assert info.bounds == (5, 6, 100, 200)          # (x, y, w, h) từ (left, top, right, bottom)
    assert info.process_name == 'chrome'
    xprop_calls = [call for call in tools.calls if os.path.basename(call[0]) == 'xprop' and '-id' in call]
    assert len(xprop_calls) == 1, 'phải gom mọi thuộc tính vào một lời gọi xprop'


def test_a_dead_window_raises_a_coded_error_not_an_attribute_error():
    platform, _tools = build(windows=[], props={})
    with pytest.raises(PlatformError) as caught:
        platform.describe_window(0x10)
    assert caught.value.code == 'CAPTURE_FAILED'


def test_is_iconic_reads_the_ewmh_hidden_state():
    platform, _tools = build(windows=[0x10],
                             props={0x10: window_props(state='_NET_WM_STATE_HIDDEN')},
                             rects={0x10: (0, 0, 10, 10)})
    assert platform.is_iconic(0x10) is True
    platform2, _ = build(windows=[0x10], props={0x10: window_props()}, rects={0x10: (0, 0, 10, 10)})
    assert platform2.is_iconic(0x10) is False


def test_window_from_point_picks_the_topmost_window_and_skips_the_rest():
    """Cửa sổ trên cùng thắng; điểm ngoài mọi cửa sổ trả `None` (không đoán bừa)."""
    props = {0x10: window_props(title='below'), 0x20: window_props(title='above')}
    rects = {0x10: (0, 0, 100, 100), 0x20: (0, 0, 100, 100)}
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects)
    assert platform.window_from_point(50, 50) == 0x20
    assert platform.window_from_point(500, 500) is None


def test_window_from_point_ignores_an_unmapped_window():
    props = {0x10: window_props(), 0x20: window_props()}
    rects = {0x10: (0, 0, 100, 100), 0x20: (0, 0, 100, 100)}
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects,
                             visible={0x20: False})
    assert platform.window_from_point(50, 50) == 0x10


# --------------------------------------------------------------- mutex
def test_the_mutex_is_held_across_handles_and_released_cleanly(tmp_path):
    """`flock` theo *open file description*: hai handle khác nhau phải tranh nhau thật."""
    platform, _tools = build()
    first = platform.create_mutex('Local\\BoxFoxDesktopInput-v1')
    second = platform.create_mutex('Local\\BoxFoxDesktopInput-v1')
    try:
        assert platform.acquire_mutex(first, 0) is True
        assert platform.acquire_mutex(second, 0) is False, 'tiến trình thứ hai không được vào'
        platform.release_mutex(first)
        assert platform.acquire_mutex(second, 0) is True
    finally:
        platform.release_mutex(first)
        platform.release_mutex(second)
        platform.close_handle(first)
        platform.close_handle(second)


# --------------------------------------------------------------- chụp
def test_capture_screen_returns_bgra_pixels_matching_the_screen_size():
    pixels = bytes([1, 2, 3, 4]) * (4 * 3)
    platform, tools = build(windows=[], screen=(0, 0, 4, 3), raw=pixels)
    shot = xc.capture_screen(platform=platform)
    assert (shot.width, shot.height) == (4, 3)
    assert shot.pixels == pixels and shot.method == 'import_screen'
    argv = [call for call in tools.calls if os.path.basename(call[0]) == 'import'][0]
    assert argv[1:3] == ['-window', 'root']
    # Thứ tự cờ là hợp đồng: `-depth 8` trước `-silent`, nếu không ImageMagick trả 16-bit/kênh.
    assert argv.index('-depth') < argv.index('-silent')
    assert argv[-1] == 'bgra:-'


def test_capture_screen_refuses_pixels_of_the_wrong_size():
    platform, _tools = build(windows=[], screen=(0, 0, 4, 3), raw=b'\x00' * 10)
    with pytest.raises(PlatformError) as caught:
        xc.capture_screen(platform=platform)
    assert caught.value.code == 'CAPTURE_FAILED'


def test_capture_window_marks_occlusion_when_another_window_covers_it():
    props = {0x10: window_props(pid=7), 0x20: window_props(pid=8)}
    rects = {0x10: (0, 0, 100, 100), 0x20: (0, 0, 100, 100)}
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects, raw=b'\xff' * (100 * 100 * 4))
    shot = xc.capture_window(0x10, platform=platform)
    assert shot.occluded is True, 'cửa sổ 0x20 nằm trên và phủ kín 0x10'
    assert shot.hwnd == 0x10 and shot.bounds == (0, 0, 100, 100)


def test_a_covered_window_with_its_own_pixels_readable_is_not_reported_as_occluded():
    """Compositor cho pixmap riêng: cửa sổ có cửa sổ khác nằm trên nhưng ảnh vẫn đúng nội dung.

    Đo trên XFCE thật: ảnh cửa sổ bị Chrome phủ chỉ trùng 0,006% số điểm với ảnh màn hình, tức là
    ta đang đọc bộ đệm riêng của cửa sổ — báo `occluded` lúc đó là chặn oan người dùng.
    """
    props = {0x10: window_props(pid=7), 0x20: window_props(pid=8)}
    rects = {0x10: (0, 0, 20, 20), 0x20: (0, 0, 20, 20)}
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects,
                             raw_by_target={'16': bytes([9, 9, 9, 9]) * (20 * 20),
                                            'root': bytes([1, 1, 1, 1]) * (20 * 20)})
    shot = xc.capture_window(0x10, platform=platform)
    assert shot.occluded is False and shot.method == 'import_window'
    assert any('bộ đệm riêng' in note for note in shot.notes)


def test_a_covered_window_that_only_shows_the_screen_is_still_reported_as_occluded():
    """Không compositor: drawable chỉ là framebuffer ⇒ ảnh là của cửa sổ đang che, phải báo `occluded`."""
    props = {0x10: window_props(pid=7), 0x20: window_props(pid=8)}
    rects = {0x10: (0, 0, 20, 20), 0x20: (0, 0, 20, 20)}
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects,
                             raw_by_target={'16': bytes([1, 1, 1, 1]) * (20 * 20),
                                            'root': bytes([1, 1, 1, 1]) * (20 * 20)})
    shot = xc.capture_window(0x10, platform=platform)
    assert shot.occluded is True


def test_the_region_capture_crops_before_it_silences_the_tool():
    """`-crop` phải đứng trước `-silent`: đảo lại thì ImageMagick trả nguyên màn hình (đã đo)."""
    platform, tools = build(windows=[], screen=(0, 0, 20, 20), raw=bytes(4) * (20 * 20))
    xc.capture_region(4, 4, 8, 8, platform=platform)
    argv = [call for call in tools.calls if os.path.basename(call[0]) == 'import'][-1]
    assert argv.index('-crop') < argv.index('-silent')
    assert argv[argv.index('-crop') + 1] == '8x8+4+4'


def test_capture_window_refuses_a_minimized_window_with_a_coded_error():
    platform, _tools = build(windows=[0x10], props={0x10: window_props(state='_NET_WM_STATE_HIDDEN')},
                             rects={0x10: (0, 0, 10, 10)})
    with pytest.raises(PlatformError) as caught:
        xc.capture_window(0x10, platform=platform)
    assert caught.value.code == 'WINDOW_MINIMIZED'


def test_capture_window_falls_back_to_the_screen_region_when_import_fails():
    """`import -window <id>` hỏng (cửa sổ lạ) ⇒ chụp vùng màn hình tương ứng, không trả lỗi rỗng."""
    platform, tools = build(windows=[0x10], props={0x10: window_props(pid=7)},
                            rects={0x10: (10, 20, 30, 40)}, import_fails=True,
                            raw=b'\x01' * (20 * 20 * 4))
    shot = xc.capture_window(0x10, platform=platform)
    assert (shot.width, shot.height) == (20, 20)
    assert shot.method == 'import_region' and shot.hwnd == 0x10


def test_capture_window_reports_a_failure_when_even_the_region_fallback_fails(monkeypatch):
    platform, _tools = build(windows=[0x10], props={0x10: window_props(pid=7)},
                             rects={0x10: (10, 20, 30, 40)}, import_fails=True)
    platform._runner = None                     # tắt runner giả để đường `import` chạy thật
    monkeypatch.setattr(xc.shutil, 'which', lambda name: '/usr/bin/' + name)
    monkeypatch.setattr(platform, 'run_raw',
                        lambda argv, timeout: xp._CommandResult(1, '', 'boom', b''))
    with pytest.raises(PlatformError) as caught:
        xc.capture_window(0x10, platform=platform)
    assert caught.value.code == 'CAPTURE_FAILED'


def test_list_windows_skips_a_window_without_geometry():
    props = {0x10: window_props(), 0x20: window_props(title='ghost')}
    rects = {0x10: (0, 0, 100, 100)}        # 0x20 không có hình học
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects)
    entries = xc.list_windows(platform=platform)
    assert [entry['windowId'] for entry in entries] == [0x10]


# --------------------------------------------------------------- input
def test_click_refuses_when_the_point_belongs_to_another_window():
    """Chốt `check_point_ownership`: bấm vào chỗ đã bị cửa sổ khác che là `SOURCE_CHANGED`."""
    props = {0x10: window_props(pid=7), 0x20: window_props(pid=8)}
    rects = {0x10: (0, 0, 100, 100), 0x20: (0, 0, 100, 100)}
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects, foreground=0x10)
    window = platform.describe_window(0x10)
    with pytest.raises(PlatformError) as caught:
        xi.click(50, 50, window=window, platform=platform)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert caught.value.details['reason'] == 'occluded'


def test_click_moves_and_presses_through_xtest():
    platform, tools = build(windows=[0x10], props={0x10: window_props(pid=7)},
                            rects={0x10: (0, 0, 100, 100)}, foreground=0x10)
    window = platform.describe_window(0x10)
    outcome = xi.click(30, 40, window=window, platform=platform, restore=False)
    assert outcome['route'] == 'xtest' and outcome['windowId'] == 0x10
    xdotool = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool']
    assert any(call[1:3] == ['mousemove', '--sync'] and call[3:5] == ['30', '40'] for call in xdotool)
    assert any(call[1:3] == ['click', '1'] for call in xdotool)


def test_click_on_a_window_that_lost_the_foreground_is_refused():
    props = {0x10: window_props(pid=7), 0x20: window_props(pid=8)}
    rects = {0x10: (0, 0, 100, 100), 0x20: (100, 0, 200, 100)}
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects, foreground=0x20)
    window = platform.describe_window(0x10)
    with pytest.raises(PlatformError) as caught:
        xi.click(30, 40, window=window, platform=platform, timeout=0.05)
    assert caught.value.code == 'SOURCE_CHANGED'


def test_type_text_refuses_a_password_element():
    platform, _tools = build(windows=[0x10], props={0x10: window_props()},
                             rects={0x10: (0, 0, 10, 10)}, foreground=0x10)
    window = platform.describe_window(0x10)
    with pytest.raises(PlatformError) as caught:
        xi.type_text('secret', window=window, element={'isPassword': True}, platform=platform)
    assert caught.value.code == 'PASSWORD_FIELD_REFUSED'


def test_type_text_sends_the_text_as_one_argument_without_a_shell():
    platform, tools = build(windows=[0x10], props={0x10: window_props(pid=7)},
                            rects={0x10: (0, 0, 100, 100)}, foreground=0x10)
    window = platform.describe_window(0x10)
    outcome = xi.type_text('a b; rm -rf /', window=window, platform=platform)
    assert outcome['chars'] == 13
    typed = [call for call in tools.calls if 'type' in call][-1]
    assert typed[-1] == 'a b; rm -rf /', 'văn bản phải là MỘT đối số, không qua shell'


def test_press_key_maps_windows_key_names_to_x11_keysyms():
    platform, tools = build(windows=[0x10], props={0x10: window_props(pid=7)},
                            rects={0x10: (0, 0, 100, 100)}, foreground=0x10)
    window = platform.describe_window(0x10)
    outcome = xi.press_key('Enter', modifiers=['Ctrl', 'Shift'], window=window, platform=platform)
    assert outcome['combo'] == 'ctrl+shift+Return'
    pressed = [call for call in tools.calls if 'key' in call][-1]
    assert pressed[-1] == 'ctrl+shift+Return'


def test_an_unknown_modifier_is_refused_before_anything_is_sent():
    platform, _tools = build(windows=[0x10], props={0x10: window_props(pid=7)},
                             rects={0x10: (0, 0, 100, 100)}, foreground=0x10)
    window = platform.describe_window(0x10)
    with pytest.raises(PlatformError) as caught:
        xi.press_key('a', modifiers=['hyper'], window=window, platform=platform)
    assert caught.value.code == 'SOURCE_CHANGED'


# --------------------------------------------------------------- mở ứng dụng
def test_launch_app_refuses_a_name_that_is_not_on_the_machine():
    platform, _tools = build()
    with pytest.raises(PlatformError) as caught:
        platform.launch_app('khong-co-app-nay-2026')
    assert caught.value.code == 'LAUNCH_FAILED'


def test_launch_app_starts_a_real_process_in_its_own_session():
    platform, _tools = build()
    platform._runner = None                 # đường thật: `shutil.which` + `Popen`
    pid = platform.launch_app('true')
    assert isinstance(pid, int) and pid > 0


def test_a_machine_without_display_has_no_platform(monkeypatch):
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    xp.reset_platform()
    assert xp.get_platform() is None
    xp.reset_platform()


def test_the_platform_reports_a_missing_tool_instead_of_crashing(monkeypatch):
    """Thiếu `import` (ImageMagick) ⇒ lỗi có mã nói rõ thiếu gì, không phải `FileNotFoundError`."""
    monkeypatch.setattr(xp.shutil, 'which', lambda name: '/usr/bin/xwininfo' if name == 'xwininfo' else None)
    platform = xp.X11Platform(display=':1', env={'DISPLAY': ':1'})
    with pytest.raises(PlatformError) as caught:
        xc.capture_screen(platform=platform)
    assert caught.value.code == 'CAPTURE_FAILED'
    assert caught.value.details['tool'] == 'import'
    assert 'imagemagick' in str(caught.value).casefold()


def test_a_missing_tool_is_named_in_the_notes(monkeypatch):
    monkeypatch.setattr(xp.shutil, 'which', lambda name: None)
    platform = xp.X11Platform(display=':1', env={'DISPLAY': ':1'})
    platform.enum_windows()
    assert 'xprop' in platform.notes()


def test_xdotool_missing_is_reported_with_its_name(monkeypatch):
    """Thiếu `xdotool` phải nói tên gói, không được đội lốt "cửa sổ mất tiêu điểm"."""
    monkeypatch.setattr(xp.shutil, 'which', lambda name: None)
    platform = xp.X11Platform(display=':1', env={'DISPLAY': ':1'})
    with pytest.raises(PlatformError) as caught:
        xi.ensure_foreground(1, platform=platform, timeout=0.01)
    assert caught.value.code == 'CUA_UNAVAILABLE' and caught.value.details['tool'] == 'xdotool'


def test_subprocess_output_is_decoded_and_errors_are_kept(monkeypatch):
    """Đường thật của `_run`: lệnh trả mã 0/khác 0 đều không ném ra ngoài."""
    platform = xp.X11Platform(display=':1', env={'DISPLAY': ':1'})
    done = subprocess.CompletedProcess(['/bin/echo', 'hi'], 0, b'hi\n', b'')
    monkeypatch.setattr(xp.subprocess, 'run', lambda *a, **k: done)
    assert platform._run(['echo', 'hi']).out.strip() == 'hi'
