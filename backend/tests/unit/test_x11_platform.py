"""Nền tảng X11 (`sandbox/x11`) — phần đọc/ghi hệ điều hành, kiểm bằng công cụ giả.

Bài kiểm chạy được trên máy KHÔNG có X server: `X11Platform` nhận `runner` tiêm vào, nên mọi lời
gọi `xprop`/`xwininfo`/`xdotool`/`import` đều là đầu vào giả. Cái được kiểm là những chỗ dễ sai và
khó thấy: thứ tự Z-order, phân tích chuỗi của `xprop`/`xwininfo`, phép thử cửa sổ tại một điểm, khoá
liên tiến trình, và ba chốt chặn trước khi gửi input.
"""
from __future__ import annotations

import os
import subprocess
import time

import pytest

from agentbox.sandbox.x11 import capture as xc
from agentbox.sandbox.x11 import input as xi
from agentbox.sandbox.x11 import platform as xp
from agentbox.sandbox.win.errors import PlatformError


class FakeTools:
    """Giả lập `xprop`/`xwininfo`/`xdotool`/`import`; ghi lại lệnh đã gọi để kiểm."""

    def __init__(self, *, windows=None, props=None, rects=None, screen=(0, 0, 1920, 1080),
                 foreground=None, raw=b'', raw_by_target=None, import_fails=False, visible=None,
                 children=None):
        self.windows = list(windows or [])          # thứ tự DƯỚI → TRÊN, như EWMH
        self.props = dict(props or {})
        self.rects = dict(rects or {})
        self.screen = screen
        self.foreground = foreground
        self.raw = raw
        self.raw_by_target = dict(raw_by_target or {})
        self.import_fails = import_fails
        self.visible = dict(visible or {})
        #: Cửa sổ cấp cao nhất theo `xwininfo -root -children` — RỘNG HƠN `windows`: có cả cửa sổ
        #: override-redirect (viền báo của BoxFox, menu) vốn KHÔNG nằm trong EWMH.
        self.children = list(self.windows if children is None else children)
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
        if self.children:
            lines = ''.join('     0x%x "cửa sổ"\n' % hwnd for hwnd in self.children)
            return 0, ('xwininfo: Window id: 0x3a5 (the root window) (has no name)\n\n'
                       '  Root window id: 0x3a5 (the root window) (has no name)\n'
                       '  -geometry %dx%d+0+0\n  Width: %d\n  Height: %d\n'
                       '  Children:\n%s'
                       % (self.screen[2], self.screen[3], self.screen[2], self.screen[3], lines)), ''
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
                 frame='0, 0, 0, 0', owner=None, wtype=None):
    props = {
        '_NET_WM_PID': str(pid),
        'WM_CLASS': '"%s"' % cls,
        '_NET_WM_NAME': '"%s"' % title,
        'WM_NAME': '"%s"' % title,
        '_NET_WM_STATE': state,
        '_NET_FRAME_EXTENTS': frame,
    }
    if owner is not None:
        props['WM_TRANSIENT_FOR'] = '0x%x' % int(owner)
    if wtype is not None:
        props['_NET_WM_WINDOW_TYPE'] = wtype
    return props


#: Loại cửa sổ của hộp thoại thật (`_NET_WM_WINDOW_TYPE_DIALOG`) — `is_own_window` đòi hỏi điều này
#: ngoài `WM_TRANSIENT_FOR`: cửa sổ lạ cùng màn hình cũng đặt được `WM_TRANSIENT_FOR`.
_DIALOG = '_NET_WM_WINDOW_TYPE_DIALOG'


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


def test_the_border_window_never_counts_as_covering_the_target():
    """J0.4 — viền báo là cửa sổ override-redirect: có trong `-children`, KHÔNG có trong EWMH.

    Đo trên `DISPLAY=:1` (08/10/2026): `_NET_CLIENT_LIST_STACKING` liệt kê 9 cửa sổ, không có cửa
    sổ viền nào của BoxFox; `xwininfo -root -children` thì có nó. Vì `window_from_point` chỉ duyệt
    danh sách EWMH, viền phủ trên cửa sổ đích mà **không** bị coi là "cửa sổ đang che" — cú bấm
    xuyên qua viền vẫn thuộc về đích, đúng thứ tự mà `shape Input` rỗng đã lo ở phía vẽ.
    """
    border = 0x2300C3                              # cửa sổ viền giả, phủ đúng chỗ cửa sổ đích
    props = {0x10: window_props(pid=7)}
    rects = {0x10: (0, 0, 100, 100), border: (0, 0, 100, 100)}
    platform, tools = build(windows=[0x10], props=props, rects=rects,
                            children=[0x10, border], foreground=0x10)

    assert platform.window_from_point(50, 50) == 0x10
    xi.check_point_ownership(50, 50, 0x10, platform=platform)   # không ném: đích vẫn là chủ điểm bấm
    # Nếu ai đó đổi `window_from_point` sang duyệt `-children`, viền sẽ che đích và bài này đỏ:
    # viền nằm trong danh sách đó VÀ phủ đúng điểm bấm.
    assert border in tools.children
    assert platform.get_window_rect(border) == (0, 0, 100, 100)
    assert not any('-children' in call for call in tools.calls)


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


def test_the_black_frame_fallback_keeps_the_occlusion_verdict_and_drops_the_own_buffer_note():
    """Khung đen ⇒ chụp lại theo vùng màn hình: ảnh đó LÀ màn hình, nên phải giữ `occluded=True`.

    Lỗi cũ: nhánh compositor đặt `occluded = False` (đúng cho ảnh đọc từ bộ đệm riêng), rồi nhánh
    khung-đen trả ảnh vùng màn hình **kèm cờ đó** — ảnh của cửa sổ đang che mà nói là không bị che.
    """
    props = {0x10: window_props(pid=7), 0x20: window_props(pid=8)}
    rects = {0x10: (0, 0, 20, 20), 0x20: (0, 0, 20, 20)}
    black = bytes(4) * (20 * 20)                 # ảnh cửa sổ gần như đen
    screen = bytes([200, 100, 50, 255]) * (20 * 20)
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects,
                             raw_by_target={'16': black, 'root': screen})
    shot = xc.capture_window(0x10, platform=platform)
    assert shot.method == 'import_region'
    assert shot.occluded is True, 'ảnh vùng màn hình có thể là của cửa sổ đang che'
    assert not any('bộ đệm riêng' in note for note in shot.notes)


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
    monkeypatch.setattr(xp.shutil, 'which', lambda name: '/usr/bin/' + name)
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
    pressed = [call for call in xdotool if call[1] == 'click']
    assert pressed and pressed[0][-1] == '1'
    # Không để `xdotool click` dùng mặc định 100 ms: đó là gần một nửa giá thành của một cú bấm.
    assert pressed[0][2] == '--delay' and int(pressed[0][3]) <= 20


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


# ------------------------------------------------- người thật chạm máy (mẫu con trỏ)
def _tick_runner(state):
    """Runner giả có trạng thái: con trỏ, tiêu điểm — để kiểm bộ đếm của `last_input_tick`."""
    def runner(argv, timeout):
        tool, args = os.path.basename(argv[0]), argv[1:]
        if tool == 'xdotool' and args and args[0] == 'getmouselocation':
            return xp._CommandResult(0, 'X=%d\nY=%d\nSCREEN=0\nWINDOW=99\n' % state['pointer'])
        if tool == 'xdotool' and args and args[0] == 'mousemove':
            state['pointer'] = (int(args[1]), int(args[2]))
            return xp._CommandResult(0, '')
        if tool == 'xdotool' and args and args[0] == 'windowactivate':
            state['own_foreground_calls'] = state.get('own_foreground_calls', 0) + 1
            return xp._CommandResult(0, '')
        if tool == 'xprop':
            return xp._CommandResult(0, '_NET_ACTIVE_WINDOW(WINDOW): window id # 0x%x\n' % state['foreground'])
        return xp._CommandResult(127, '', 'không có công cụ %s' % tool)
    return runner


def _tick_platform(state):
    return xp.X11Platform(display=':1', runner=_tick_runner(state), env={'DISPLAY': ':1'})


def test_a_pointer_move_we_did_not_cause_counts_as_a_person():
    """Đây là toàn bộ tín hiệu "người thật" trên X11: con trỏ đổi chỗ mà không phải do ta."""
    state = {'pointer': (100, 100), 'foreground': 0x1001}
    platform = _tick_platform(state)
    baseline = platform.last_input_tick()
    assert baseline > 0, 'mốc 0 có nghĩa "chưa có mốc" trong `poll_idle`, nên phải khác 0'
    state['pointer'] = (300, 400)
    assert platform.last_input_tick() == baseline + 1


def test_the_agents_own_pointer_move_does_not_count_as_a_person():
    """Cú bấm của agent tự di chuyển con trỏ rồi trả về chỗ cũ — không lần nào được tính."""
    state = {'pointer': (100, 100), 'foreground': 0x1001}
    platform = _tick_platform(state)
    baseline = platform.last_input_tick()
    assert platform.set_cursor_pos(700, 700) is True
    assert platform.last_input_tick() == baseline
    assert platform.set_cursor_pos(100, 100) is True
    assert platform.last_input_tick() == baseline


def test_a_focus_change_we_did_not_cause_counts_as_a_person():
    state = {'pointer': (100, 100), 'foreground': 0x1001}
    platform = _tick_platform(state)
    baseline = platform.last_input_tick()
    state['foreground'] = 0x2002
    assert platform.last_input_tick() == baseline + 1


def test_the_window_we_activated_ourselves_does_not_count_as_a_person():
    state = {'pointer': (100, 100), 'foreground': 0x1001}
    platform = _tick_platform(state)
    baseline = platform.last_input_tick()
    state['foreground'] = 0x3003
    assert platform.set_foreground_window(0x3003) is True
    assert platform.last_input_tick() == baseline


def test_idle_seconds_is_none_until_the_first_sample():
    state = {'pointer': (100, 100), 'foreground': 0x1001}
    platform = _tick_platform(state)
    assert platform.idle_seconds() is None
    platform.last_input_tick()
    assert platform.idle_seconds() is not None


def test_a_machine_whose_x_server_does_not_answer_has_no_platform(monkeypatch):
    """`DISPLAY` có mà X server chết ⇒ kích thước 0×0 ⇒ KHÔNG có nền tảng (đừng nhận máy hỏng).

    Lỗi cũ: `bool(bounds[2:])` — tuple `(0, 0)` vẫn là truthy, nên phép thử không bao giờ từ chối.
    """
    tools = FakeTools(screen=(0, 0, 0, 0))
    real = xp.X11Platform
    monkeypatch.setenv('DISPLAY', ':1')
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    monkeypatch.setattr(xp, 'X11Platform', lambda *a, **k: real(display=':1', runner=tools))
    xp.reset_platform()
    try:
        assert xp.get_platform() is None
    finally:
        xp.reset_platform()


def test_a_wayland_session_says_that_only_x11_windows_are_reachable():
    platform = xp.X11Platform(display=':1', runner=FakeTools(),
                              env={'DISPLAY': ':1', 'WAYLAND_DISPLAY': 'wayland-0'})
    assert any('wayland' in note.casefold() for note in platform.notes())


# ----------------------------------------------------------------- gõ theo khối
def test_type_text_sends_one_chunk_at_a_time_and_keeps_the_text_whole():
    """Văn bản dài phải đi thành nhiều khối, mỗi khối nguyên vẹn và đúng thứ tự."""
    text = 'a' * 200
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: (0, 0, 100, 100)}, foreground=0x11)
    xi.type_text(text, window=0x11, platform=platform)
    typed = [call[call.index('type') + 1:] for call in tools.calls
             if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    chunks = [call[call.index('--') + 1] for call in typed]
    assert len(chunks) == 4                      # 200 ký tự / 64
    assert ''.join(chunks) == text
    assert all(len(chunk) <= xi.TEXT_CHUNK_CHARS for chunk in chunks)


def test_type_text_stops_when_the_target_loses_focus_between_chunks():
    """Mất tiêu điểm giữa chừng ⇒ dừng ngay, phần còn lại không rơi vào cửa sổ của người."""
    platform, tools = build(windows=[0x11, 0x22], props={0x11: window_props(), 0x22: window_props()},
                            rects={0x11: (0, 0, 100, 100), 0x22: (0, 0, 100, 100)}, foreground=0x11)
    typed: list[int] = []

    class ChunkWatcher:
        """Đổi tiêu điểm ngay sau khối đầu tiên — như người dùng bấm sang cửa sổ khác."""

        def __call__(self, argv, timeout):
            if os.path.basename(argv[0]) == 'xdotool' and 'type' in argv:
                typed.append(1)
                if len(typed) == 1:
                    tools.foreground = 0x22
            return tools(argv, timeout)

    platform._runner = ChunkWatcher()
    with pytest.raises(PlatformError) as caught:
        xi.type_text('b' * 200, window=0x11, platform=platform)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert len(typed) == 1                       # khối thứ hai không bao giờ được gửi


# ------------------------------------------------- hộp thoại của chính ứng dụng đích
# Đo trên máy thật (VS Code, 08/10/2026): khi ứng dụng mở hộp thoại modal, hộp thoại là một cửa sổ
# X11 riêng có `WM_TRANSIENT_FOR` trỏ vào cửa sổ chính. WM giữ tiêu điểm ở hộp thoại và **từ chối**
# kích hoạt cửa sổ chính, nên chốt "đích phải có tiêu điểm" làm mọi thao tác vào ứng dụng hỏng, còn
# chốt "điểm bấm phải thuộc đích" thì không cho bấm nút của hộp thoại — agent chết cứng.
def _app_with_dialog(*, dialog_owner=0x10, foreground=0x10):
    """Ứng dụng 0x10 + hộp thoại 0x20 (mặc định là hộp thoại CỦA chính nó)."""
    props = {0x10: window_props(pid=7, title='Code'),
             0x20: window_props(pid=7, title='Replace?', owner=dialog_owner, wtype=_DIALOG)}
    rects = {0x10: (0, 0, 100, 100), 0x20: (20, 20, 80, 60)}
    platform, tools = build(windows=[0x10, 0x20], props=props, rects=rects, foreground=foreground)
    return platform, tools


def test_a_click_lands_on_a_dialog_of_the_target_window():
    """Nút nằm trong hộp thoại của chính ứng dụng đích: bấm được, và vẫn gắn với cửa sổ đích."""
    platform, _tools = _app_with_dialog()
    window = platform.describe_window(0x10)
    outcome = xi.click(50, 40, window=window, platform=platform, restore=False)
    assert outcome['windowId'] == 0x10 and outcome['point'] == {'x': 50, 'y': 40}


def test_a_click_on_a_dialog_of_another_application_is_still_refused():
    """Hộp thoại của ứng dụng KHÁC thì vẫn là che khuất — không được bấm vào."""
    platform, _tools = _app_with_dialog(dialog_owner=0x30)
    window = platform.describe_window(0x10)
    with pytest.raises(PlatformError) as caught:
        xi.click(50, 40, window=window, platform=platform)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert caught.value.details['window_at_point'] == 0x20


def test_a_foreign_window_claiming_the_target_as_owner_is_refused_without_a_dialog_type():
    """`WM_TRANSIENT_FOR` một mình KHÔNG đủ để nhận input.

    Trên X11 không có ranh giới quyền giữa các ứng dụng cùng màn hình: một công cụ lạ "bám theo cửa
    sổ đang hoạt động" cũng đặt được `WM_TRANSIENT_FOR` trỏ vào cửa sổ đích. Nếu chỉ tin thuộc tính
    đó thì cú bấm của agent rơi thẳng vào cửa sổ của công cụ lạ — đúng thứ chốt này sinh ra để chặn.
    """
    props = {0x10: window_props(pid=7, title='Code'),
             # `owner=0x10` nhưng KHÔNG khai `_NET_WM_WINDOW_TYPE` (loại mặc định là NORMAL).
             0x20: window_props(pid=99, title='Bảng chọn nhanh', cls='helper, Helper', owner=0x10)}
    platform, _tools = build(windows=[0x10, 0x20], props=props,
                             rects={0x10: (0, 0, 100, 100), 0x20: (20, 20, 80, 60)}, foreground=0x10)
    window = platform.describe_window(0x10)
    with pytest.raises(PlatformError) as caught:
        xi.click(50, 40, window=window, platform=platform)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert caught.value.details['window_at_point'] == 0x20


def test_a_foreign_window_with_a_dialog_type_still_cannot_take_the_keyboard():
    """Cùng cửa sổ đó khai `_NET_WM_WINDOW_TYPE_DIALOG`: tiêu điểm vẫn không phải của nó."""
    props = {0x10: window_props(pid=7, title='Code'),
             0x20: window_props(pid=99, title='Bảng chọn nhanh', owner=0x10, wtype=_DIALOG)}
    platform, _tools = build(windows=[0x10, 0x20], props=props,
                             rects={0x10: (0, 0, 100, 100), 0x20: (20, 20, 80, 60)}, foreground=0x20)
    # Hộp thoại "của" đích theo thuộc tính thì chốt tiêu điểm nhận — đúng như hộp thoại thật của
    # ứng dụng; thứ bị chặn là trường hợp KHÔNG khai loại hộp thoại (bài kiểm trên).
    assert platform.is_own_window(0x10, 0x20) is True
    assert platform.is_dialog_window(0x20) is True


def test_a_same_process_window_claiming_the_target_as_owner_is_accepted():
    """Cửa sổ CÙNG TIẾN TRÌNH khai `WM_TRANSIENT_FOR` về đích thì vẫn là cửa sổ của ứng dụng.

    Đo trên máy thật (08/10/2026, mtPaint 3.50): hộp thoại "Save Image File" và cửa sổ "Settings
    Toolbar" đều khai `WM_TRANSIENT_FOR` trỏ về cửa sổ chính nhưng tự khai
    `_NET_WM_WINDOW_TYPE_NORMAL`. Chốt cũ đòi loại hộp thoại nên từ chối: không gõ được tên tệp để
    lưu. `_NET_WM_PID` giống nhau là bằng chứng mạnh hơn `WM_TRANSIENT_FOR` — tiến trình khác không
    tạo được cửa sổ mang PID của ứng dụng đích.
    """
    props = {0x10: window_props(pid=656623, title='mtPaint 3.50 - Untitled'),
             # Cùng PID, `owner=0x10`, KHÔNG khai `_NET_WM_WINDOW_TYPE` (mặc định là NORMAL).
             0x20: window_props(pid=656623, title='Save Image File', owner=0x10)}
    platform, tools = build(windows=[0x10, 0x20], props=props,
                            rects={0x10: (0, 0, 100, 100), 0x20: (20, 20, 80, 60)},
                            foreground=0x20)
    assert platform.is_dialog_window(0x20) is False
    assert platform.same_process(0x20, 0x10) is True
    assert platform.is_own_window(0x10, 0x20) is True
    outcome = xi.type_text('anh.png', window=0x10, platform=platform)
    assert outcome['chars'] == 7
    typed = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    assert typed, 'phím phải được gửi thật'


def test_a_same_process_window_still_needs_the_transient_chain():
    """Cùng tiến trình nhưng KHÔNG khai `WM_TRANSIENT_FOR`: không phải hộp thoại của đích.

    mtPaint có nhiều cửa sổ cấp cao nhất cùng tiến trình; chỉ nhận theo PID là quá rộng — cửa sổ
    không nằm trong chuỗi `WM_TRANSIENT_FOR` vẫn có thể là một cửa sổ khác của người dùng.
    """
    props = {0x10: window_props(pid=656623, title='mtPaint 3.50 - Untitled'),
             0x20: window_props(pid=656623, title='Ảnh khác')}
    platform, _tools = build(windows=[0x10, 0x20], props=props,
                             rects={0x10: (0, 0, 100, 100), 0x20: (20, 20, 80, 60)},
                             foreground=0x10)
    assert platform.is_own_window(0x10, 0x20) is False


def test_a_dialog_of_a_dialog_is_painted_into_the_capture_too():
    """Hộp thoại LỒNG NHAU cũng phải có trong ảnh: chốt input đã nhận nó thì ảnh cũng phải thấy nó."""
    props = {0x10: window_props(pid=7, title='Code'),
             0x20: window_props(pid=7, title='Replace?', owner=0x10, wtype=_DIALOG),
             0x30: window_props(pid=7, title='Xác nhận', owner=0x20, wtype=_DIALOG)}
    rects = {0x10: (0, 0, 100, 100), 0x20: (20, 20, 80, 60), 0x30: (30, 30, 60, 50)}
    platform, _tools = build(windows=[0x10, 0x20, 0x30], props=props, rects=rects, foreground=0x30)
    assert platform.transient_windows(0x10) == [0x20, 0x30]


def test_typing_goes_ahead_while_the_targets_own_dialog_holds_the_focus():
    platform, tools = _app_with_dialog(foreground=0x20)
    outcome = xi.type_text('y', window=0x10, platform=platform)
    assert outcome['chars'] == 1
    typed = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    assert typed, 'phím phải được gửi thật'


def test_typing_still_stops_when_an_unrelated_window_holds_the_focus():
    platform, _tools = _app_with_dialog(foreground=0x30)
    with pytest.raises(PlatformError) as caught:
        xi.type_text('y', window=0x10, platform=platform, timeout=0.05)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert caught.value.details['foreground'] == 0x30


def test_a_dialog_chain_is_followed_up_to_a_few_levels():
    """Hộp thoại của hộp thoại vẫn thuộc ứng dụng đích."""
    props = {0x10: window_props(pid=7), 0x20: window_props(pid=7, owner=0x10, wtype=_DIALOG),
             0x30: window_props(pid=7, owner=0x20, wtype=_DIALOG)}
    platform, _tools = build(windows=[0x10, 0x20, 0x30], props=props,
                             rects={0x10: (0, 0, 100, 100), 0x20: (0, 0, 100, 100),
                                    0x30: (0, 0, 100, 100)}, foreground=0x30)
    assert platform.is_own_window(0x10, 0x30) is True


# ------------------------------------------------- kích hoạt cửa sổ không chặn
def test_activation_never_asks_xdotool_to_wait_for_the_window_manager():
    """`--sync` chặn tới hết thời gian chờ khi WM từ chối kích hoạt (đo được > 12 s một lời gọi)."""
    platform, tools = build(windows=[0x10], props={0x10: window_props()},
                            rects={0x10: (0, 0, 10, 10)}, foreground=0x10)
    assert platform.set_foreground_window(0x10) is True
    calls = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool']
    assert calls and calls[0][1:3] == ['windowactivate', '16']
    assert '--sync' not in calls[0]


def test_activation_reports_failure_instead_of_blocking_when_the_manager_refuses():
    platform, _tools = build(windows=[0x10, 0x20], props={0x10: window_props(), 0x20: window_props()},
                             rects={0x10: (0, 0, 10, 10), 0x20: (0, 0, 10, 10)}, foreground=0x20)
    started = time.monotonic()
    assert platform.set_foreground_window(0x10, wait=0.05) is False
    assert time.monotonic() - started < 1.0


# ------------------------------------------------- hình học đọc một lần
def test_repeated_geometry_reads_use_a_single_xwininfo():
    """Một lần soi duyệt chồng cửa sổ năm lần; mỗi cửa sổ chỉ được đọc `xwininfo` một lần."""
    platform, tools = build(windows=[0x10], props={0x10: window_props()},
                            rects={0x10: (0, 0, 10, 10)})
    assert platform.get_window_rect(0x10) == (0, 0, 10, 10)
    assert platform.is_window_visible(0x10) is True
    assert platform.get_window_rect(0x10) == (0, 0, 10, 10)
    calls = [call for call in tools.calls if os.path.basename(call[0]) == 'xwininfo' and '-id' in call]
    assert len(calls) == 1


def test_a_fresh_geometry_read_bypasses_the_cache():
    """Sau khi cửa sổ bị di chuyển, `fresh=True` phải đọc lại — nếu không thì bấm sai chỗ."""
    platform, tools = build(windows=[0x10], props={0x10: window_props()},
                            rects={0x10: (0, 0, 10, 10)})
    assert platform.get_window_rect(0x10) == (0, 0, 10, 10)
    tools.rects[0x10] = (100, 100, 110, 110)
    assert platform.get_window_rect(0x10) == (0, 0, 10, 10), 'bản còn hạn thì dùng lại'
    assert platform.get_window_rect(0x10, fresh=True) == (100, 100, 110, 110)


# ------------------------------------------------- ghép hộp thoại vào ảnh cửa sổ
def _capture_with_dialog(*, dialog_owner=0x10, foreground=0x20, wtype=_DIALOG):
    base = bytes([200, 200, 200, 255]) * (100 * 100)
    patch = bytes([40, 40, 40, 255]) * (60 * 40)
    props = {0x10: window_props(pid=7, title='Code'),
             0x20: window_props(pid=7, title='Replace?', owner=dialog_owner, wtype=wtype)}
    rects = {0x10: (0, 0, 100, 100), 0x20: (20, 20, 80, 60)}
    # Mặc định: hộp thoại modal đang giữ tiêu điểm — trạng thái đo được trên máy thật.
    platform, _tools = build(windows=[0x10, 0x20], props=props, rects=rects, foreground=foreground,
                             raw_by_target={'16': base, '32': patch, 'root': base})
    return platform, base, patch


def test_the_targets_own_dialog_is_painted_into_the_window_capture():
    """Agent phải NHÌN THẤY hộp thoại: ảnh cửa sổ được ghép hộp thoại đúng vị trí tuyệt đối."""
    platform, base, patch = _capture_with_dialog()
    shot = xc.capture_window(0x10, platform=platform)
    assert shot.method == 'import_window' and len(shot.pixels) == len(base)
    inside = (40 * 100 + 60) * 4          # điểm (60, 40) nằm trong hộp thoại (20,20)-(80,60)
    outside = (10 * 100 + 10) * 4
    assert shot.pixels[inside:inside + 4] == patch[:4], 'hộp thoại phải được dán vào ảnh'
    assert shot.pixels[outside:outside + 4] == base[:4], 'phần còn lại giữ nguyên ảnh cửa sổ'
    assert any('hộp thoại của chính ứng dụng' in note for note in shot.notes)


def test_the_targets_own_dialog_is_painted_even_when_the_target_holds_the_focus():
    """Hộp thoại KHÔNG modal: cửa sổ đích vẫn giữ tiêu điểm, nhưng hộp thoại vẫn phải có trong ảnh.

    Đây là ca lọt lưới của bản đầu: cổng cũ chỉ dò `transient_windows` khi cửa sổ bị che hoặc khi
    tiêu điểm không còn ở đích, vì đoán "hộp thoại modal luôn giữ tiêu điểm". Đoán đó sai với
    ``UTILITY``/``POPUP_MENU``/``TOOLTIP``/``NOTIFICATION`` — đích giữ tiêu điểm, phép thử che khuất
    theo tỉ lệ bỏ qua hộp thoại nhỏ, nên ảnh trả về **thiếu đúng thứ đang che cửa sổ**: agent nhìn
    hụt rồi bấm vào chỗ nó không thấy. `import -window` đọc bộ đệm riêng của cửa sổ nên hộp thoại
    chỉ vào ảnh khi ta ghép — không có cổng đoán nào là đúng.
    """
    platform, base, patch = _capture_with_dialog(foreground=0x10)
    assert platform.get_foreground_window() == 0x10, 'đích phải đang giữ tiêu điểm'
    shot = xc.capture_window(0x10, platform=platform)
    inside = (40 * 100 + 60) * 4
    assert shot.pixels[inside:inside + 4] == patch[:4], 'hộp thoại vẫn phải được dán vào ảnh'
    assert any('hộp thoại của chính ứng dụng' in note for note in shot.notes)


def test_a_non_modal_dialog_type_is_composited_too():
    """`UTILITY` cũng là hộp thoại của ứng dụng (bảng chọn, cửa sổ phụ) — cũng phải ghép."""
    platform, base, patch = _capture_with_dialog(foreground=0x10, wtype='_NET_WM_WINDOW_TYPE_UTILITY')
    shot = xc.capture_window(0x10, platform=platform)
    inside = (40 * 100 + 60) * 4
    assert shot.pixels[inside:inside + 4] == patch[:4]


def test_a_dialog_of_another_application_is_not_painted_into_the_capture():
    platform, base, _patch = _capture_with_dialog(dialog_owner=0x30)
    shot = xc.capture_window(0x10, platform=platform)
    inside = (40 * 100 + 60) * 4
    assert shot.pixels[inside:inside + 4] == base[:4]
    assert not any('hộp thoại của chính ứng dụng' in note for note in shot.notes)


# ------------------------------------------------- locale UTF-8 cho tiến trình con
# Đo trên máy thật (08/10/2026): `xfce4-terminal` mở bằng `env -i` (không LANG) **nuốt sạch dấu** khi
# nhận input XTEST — "Xin chào Cửa sổ! áàảãạ" nhận về "Xin cho Ca s!"; mở kèm `LANG=C.UTF-8` thì nhận
# đủ từng byte, còn `LC_ALL=C` thì lại mất. Lệnh gõ vẫn báo thành công, nên đây là lỗi im lặng: ứng
# dụng do BoxFox mở phải có locale UTF-8, và chính `xdotool` cũng giải mã đối số theo locale.
def test_a_child_process_gets_a_utf8_locale_when_the_host_has_none():
    platform = xp.X11Platform(display=':1', runner=FakeTools(), env={'DISPLAY': ':1', 'PATH': '/usr/bin'})
    env = platform._child_env()
    assert xp.has_utf8_locale(env), env
    assert env['LANG'] == xp.utf8_locale()


def test_a_utf8_locale_from_the_host_is_kept_untouched():
    platform = xp.X11Platform(display=':1', runner=FakeTools(),
                              env={'DISPLAY': ':1', 'LANG': 'vi_VN.UTF-8'})
    assert platform._child_env()['LANG'] == 'vi_VN.UTF-8'


def test_a_non_utf8_locale_is_replaced_for_child_processes():
    """`LC_ALL=C` làm mất dấu: tiến trình con phải được cấp lại locale UTF-8."""
    platform = xp.X11Platform(display=':1', runner=FakeTools(),
                              env={'DISPLAY': ':1', 'LC_ALL': 'C', 'LANG': 'C'})
    env = platform._child_env()
    assert 'LC_ALL' not in env and xp.has_utf8_locale(env)


def test_has_utf8_locale_follows_the_libc_order():
    assert xp.has_utf8_locale({'LANG': 'C.UTF-8'})
    assert not xp.has_utf8_locale({'LANG': 'C'})
    assert not xp.has_utf8_locale({})
    # LC_ALL thắng LANG — đúng thứ tự libc
    assert not xp.has_utf8_locale({'LANG': 'C.UTF-8', 'LC_ALL': 'C'})
    assert xp.has_utf8_locale({'LANG': 'C', 'LC_ALL': 'C.utf8'})


def _fake_locale_a(monkeypatch, names):
    """Giả lập `locale -a` trả về đúng danh sách này."""
    class Done:
        returncode = 0
        stdout = '\n'.join(names) + '\n'

    monkeypatch.setattr(xp.subprocess, 'run', lambda *a, **k: Done())
    monkeypatch.setattr(xp, '_installed_utf8_cache', None, raising=False)
    monkeypatch.setattr(xp, '_installed_utf8_probed', False, raising=False)
    monkeypatch.setattr(xp, '_utf8_locale_cache', None, raising=False)


def test_installed_utf8_locale_reports_none_when_the_machine_has_no_utf8_locale(monkeypatch):
    """Máy không cài locale UTF-8 nào: phải nói THẬT là `None`, không hứa hão."""
    _fake_locale_a(monkeypatch, ['C', 'POSIX', 'en_US.iso88591'])
    assert xp.installed_utf8_locale() is None
    assert xp.utf8_locale() == 'C.UTF-8'      # nỗ lực tốt nhất cho tiến trình con


def test_installed_utf8_locale_accepts_any_utf8_name_not_only_the_usual_four(monkeypatch):
    """`vi_VN.UTF-8` (rất hợp với người dùng này) cũng phải được dùng, không chỉ bốn tên quen thuộc."""
    _fake_locale_a(monkeypatch, ['C', 'POSIX', 'vi_VN.UTF-8'])
    assert xp.installed_utf8_locale() == 'vi_VN.UTF-8'
    assert xp.utf8_locale() == 'vi_VN.UTF-8'


def test_the_usual_names_win_over_an_arbitrary_utf8_locale(monkeypatch):
    _fake_locale_a(monkeypatch, ['vi_VN.UTF-8', 'C.utf8'])
    assert xp.installed_utf8_locale() == 'C.utf8'


def test_the_locale_note_does_not_promise_a_locale_the_machine_lacks(monkeypatch):
    """Ghi chú cũ nói "ứng dụng do BoxFox mở thì đã được cấp locale" cả khi máy không có locale nào."""
    _fake_locale_a(monkeypatch, ['C', 'POSIX'])
    platform = xp.X11Platform(display=':1', runner=FakeTools(), env={'DISPLAY': ':1', 'LANG': 'C'})
    notes = ' '.join(platform.notes())
    assert 'không cài' in notes, notes
    assert 'đã được cấp locale' not in notes, 'đừng hứa một locale mà máy không có'


def test_utf8_locale_names_a_locale_that_exists_on_this_machine():
    name = xp.utf8_locale()
    assert name and ('utf-8' in name.lower() or 'utf8' in name.lower())


def test_the_platform_warns_that_a_non_utf8_session_drops_accented_text():
    platform = xp.X11Platform(display=':1', runner=FakeTools(), env={'DISPLAY': ':1', 'LANG': 'C'})
    notes = ' '.join(platform.notes())
    assert 'không có locale UTF-8' in notes and 'nuốt' in notes


def test_a_utf8_session_gets_no_locale_warning():
    platform = xp.X11Platform(display=':1', runner=FakeTools(),
                              env={'DISPLAY': ':1', 'LANG': 'C.UTF-8'})
    assert not any('locale UTF-8' in note for note in platform.notes())


def test_launch_app_hands_the_utf8_locale_to_the_application(monkeypatch):
    """Ứng dụng do BoxFox mở phải nhận locale UTF-8, nếu không chữ có dấu gõ vào sẽ biến mất."""
    platform = xp.X11Platform(display=':1', env={'DISPLAY': ':1', 'LANG': 'C'})
    seen = {}

    class FakeProcess:
        pid = 4242

    def fake_popen(args, **kwargs):
        seen['args'] = args
        seen['env'] = kwargs.get('env')
        return FakeProcess()

    monkeypatch.setattr(xp.shutil, 'which', lambda name: '/usr/bin/%s' % name)
    monkeypatch.setattr(xp.subprocess, 'Popen', fake_popen)
    assert platform.launch_app('xfce4-terminal') == 4242
    assert xp.has_utf8_locale(seen['env']), seen['env']
    assert seen['env']['DISPLAY'] == ':1'


# ------------------------------------------------- bấm hai lần vào cùng một điểm
# Đo trên máy thật (08/10/2026, xfce4-terminal): `xdotool mousemove --sync <x> <y>` **chờ một sự kiện
# MotionNotify tới đúng toạ độ**; con trỏ đã đứng đúng chỗ thì X server không sinh sự kiện nào, nên
# lệnh chờ tới hết thời gian chờ (5 s) rồi hỏng. Hệ quả: cú bấm thứ hai vào cùng một điểm treo 5 s và
# báo `SOURCE_CHANGED` — agent thấy như "cửa sổ đổi chỗ", còn người dùng thấy agent đứng hình.
def test_clicking_the_same_point_twice_does_not_hang_and_keeps_the_cursor_on_target():
    """Bấm hai lần vào cùng một điểm: lần thứ hai KHÔNG được dùng `mousemove --sync`.

    Đo trên máy thật: `xdotool mousemove --sync` chờ một sự kiện MotionNotify tới đúng toạ độ; con
    trỏ đã ở đúng chỗ thì X server không sinh sự kiện nào, nên lệnh chờ hết thời gian chờ công cụ
    (5 s) rồi báo `SOURCE_CHANGED` — cú bấm thứ hai vào cùng một điểm không bao giờ tới nơi. Nhưng
    vẫn phải gửi `mousemove` KHÔNG đồng bộ: nếu người thật vừa di chuột trong lúc chờ tiêu điểm thì
    đó là cách kéo con trỏ về đúng điểm đã kiểm quyền trước khi bấm.
    """
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: (0, 0, 100, 100)}, foreground=0x11)
    pointer = {'at': (50, 50)}

    class CursorAware:
        """Giả lập đúng hành vi thật: chỉ `mousemove --sync` tới chỗ con trỏ đang đứng mới hết giờ."""

        def __call__(self, argv, timeout):
            tool, args = os.path.basename(argv[0]), argv[1:]
            if tool == 'xdotool' and args and args[0] == 'getmouselocation':
                return xp._CommandResult(0, 'X=%d\nY=%d\nSCREEN=0\nWINDOW=17\n' % pointer['at'])
            if tool == 'xdotool' and args and args[0] == 'mousemove':
                target = (int(args[-2]), int(args[-1]))
                if target == pointer['at'] and '--sync' in args:
                    return xp._CommandResult(124, '', 'hết thời gian chờ xdotool')
                pointer['at'] = target
            return tools(argv, timeout)

    platform._runner = CursorAware()
    window = platform.describe_window(0x11)
    for _ in range(2):
        outcome = xi.click(50, 50, window=window, platform=platform, restore=False)
    assert outcome['point'] == {'x': 50, 'y': 50}
    moves = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool' and 'mousemove' in call]
    presses = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool' and 'click' in call]
    assert len(moves) == 2 and len(presses) == 2, 'mỗi cú bấm gửi một lần di chuột rồi một lần bấm'
    assert all('--sync' not in call for call in moves), 'con trỏ đã đúng chỗ thì không được chờ đồng bộ'
    assert pointer['at'] == (50, 50), 'con trỏ vẫn phải ở đúng điểm đã kiểm quyền'


def test_a_click_after_a_drifted_cursor_is_pulled_back_to_the_checked_point():
    """Người thật di chuột trong lúc chờ tiêu điểm: cú bấm vẫn phải rơi vào điểm đã kiểm quyền."""
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: (0, 0, 100, 100)}, foreground=0x11)
    pointer = {'at': (50, 50)}

    class Drifting:
        """Lần đọc thứ hai trả về chỗ khác — đúng lúc người thật vừa di chuột."""

        def __init__(self):
            self.reads = 0

        def __call__(self, argv, timeout):
            tool, args = os.path.basename(argv[0]), argv[1:]
            if tool == 'xdotool' and args and args[0] == 'getmouselocation':
                self.reads += 1
                at = (50, 50) if self.reads == 1 else (10, 10)
                return xp._CommandResult(0, 'X=%d\nY=%d\n' % at)
            if tool == 'xdotool' and args and args[0] == 'mousemove':
                pointer['at'] = (int(args[-2]), int(args[-1]))
            return tools(argv, timeout)

    platform._runner = Drifting()
    window = platform.describe_window(0x11)
    xi.click(50, 50, window=window, platform=platform, restore=False)
    moves = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool' and 'mousemove' in call]
    assert moves, 'con trỏ lệch thì vẫn phải kéo về'
    assert pointer['at'] == (50, 50)


def test_a_click_at_another_point_still_moves_the_pointer_first():
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: (0, 0, 100, 100)}, foreground=0x11)
    pointer = {'at': (10, 10)}

    class CursorAware:
        def __call__(self, argv, timeout):
            tool, args = os.path.basename(argv[0]), argv[1:]
            if tool == 'xdotool' and args and args[0] == 'getmouselocation':
                return xp._CommandResult(0, 'X=%d\nY=%d\n' % pointer['at'])
            if tool == 'xdotool' and args and args[0] == 'mousemove':
                pointer['at'] = (int(args[-2]), int(args[-1]))
            return tools(argv, timeout)

    platform._runner = CursorAware()
    window = platform.describe_window(0x11)
    xi.click(70, 80, window=window, platform=platform, restore=False)
    moves = [call for call in tools.calls if os.path.basename(call[0]) == 'xdotool' and 'mousemove' in call]
    assert moves and (int(moves[-1][-2]), int(moves[-1][-1])) == (70, 80)


# ------------------------------------------------- ký tự ngoài ASCII đi một mình một lệnh
# Đo trên máy thật (Chrome, 08/10/2026, X server có tải): gõ cả câu trong một lệnh `xdotool type`
# làm MẤT 1–2 ký tự có dấu ở 3/6 lượt (`ăơ`, `ãơ`, `ử` biến mất), trong khi mỗi ký tự ngoài ASCII
# một lệnh thì 6/6 lượt đủ. `xdotool` ánh xạ tạm một keycode trống cho mỗi ký tự ngoài ASCII rồi
# trả lại; máy bận thì ứng dụng đọc sự kiện sau lúc ánh xạ đã bị trả lại. Ký tự ASCII không dính lỗi.
def test_non_ascii_characters_go_one_command_each():
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: (0, 0, 100, 100)}, foreground=0x11)
    xi.type_text('chào bạn', window=0x11, platform=platform)
    chunks = [call[call.index('--') + 1] for call in tools.calls
              if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    assert chunks == ['ch', 'à', 'o b', 'ạ', 'n'], chunks
    assert ''.join(chunks) == 'chào bạn'


def test_ascii_text_still_travels_in_one_command():
    """Đường nhanh không được đổi: văn bản ASCII thuần vẫn là một lệnh duy nhất."""
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: (0, 0, 100, 100)}, foreground=0x11)
    xi.type_text('a = 2\nb = 3\nprint(a + b)\n', window=0x11, platform=platform)
    calls = [call for call in tools.calls
             if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    assert len(calls) == 1
    assert calls[0][calls[0].index('--') + 1] == 'a = 2\nb = 3\nprint(a + b)\n'


def test_typing_chunks_keeps_order_and_splits_only_non_ascii():
    assert xi.typing_chunks('') == []
    assert xi.typing_chunks('abc') == ['abc']
    assert xi.typing_chunks('aábc') == ['a', 'á', 'bc']
    assert xi.typing_chunks('á') == ['á']
    assert xi.typing_chunks('a' * 70) == ['a' * 64, 'a' * 6]
    assert ''.join(xi.typing_chunks('Xin chào Cửa sổ!')) == 'Xin chào Cửa sổ!'


# ------------------------------------------------- ánh xạ sẵn keysym cho ký tự ngoài ASCII
# Đo trên máy thật (08/10/2026): `xdotool type` ánh xạ rồi TRẢ LẠI ngay cho từng ký tự, nên máy bận
# thì ký tự mất (3/6 lượt sạch) và chữ hoa Latin-1/2 bị gửi nhầm thành chữ thường (Á → á). Ánh xạ
# sẵn vào keycode trống, giữ nguyên trong suốt lần gõ, cho `ÁÀẢĐÊÔƠƯỔỢ` đi đúng từng ký tự.
def _xmodmap_runner(*, spare=(250, 249, 248), fail_map=False, fail_key=False):
    """Runner giả có `xmodmap`: nhớ ánh xạ đã đặt để kiểm cả lúc trả lại."""
    state = {'map': {}, 'calls': []}

    def runner(argv, timeout):
        tool, args = os.path.basename(argv[0]), argv[1:]
        state['calls'].append(list(argv))
        if tool == 'xmodmap':
            if args and args[0] == '-pke':
                lines = ['keycode %d =' % code for code in spare]
                lines += ['keycode 38 = a A a A', 'keycode 39 = s S s S']
                return xp._CommandResult(0, '\n'.join(lines) + '\n')
            for index, flag in enumerate(args):
                if flag != '-e':
                    continue
                fields = args[index + 1].split()
                if len(fields) >= 4 and fields[0] == 'keycode' and fields[2] == '=':
                    code = int(fields[1])
                    if fields[3] == 'NoSymbol':
                        state['map'].pop(code, None)
                    elif fail_map:
                        return xp._CommandResult(1, '', 'xmodmap: không đặt được')
                    else:
                        state['map'][code] = fields[3]
            return xp._CommandResult(0, '')
        if tool == 'xdotool' and args and args[0] == 'key' and fail_key:
            return xp._CommandResult(1, '', 'xdotool: không gửi được phím')
        return None

    return runner, state


def _platform_with_xmodmap(runner):
    """Nền tảng giả có thêm `xmodmap`; mọi công cụ khác vẫn do `FakeTools` trả lời."""
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: (0, 0, 100, 100)}, foreground=0x11)
    inner = platform._runner

    def dispatch(argv, timeout):
        got = runner(argv, timeout)
        return inner(argv, timeout) if got is None else got

    platform._runner = dispatch
    return platform, tools


def test_the_keysym_plan_maps_spare_keycodes_and_releases_them():
    runner, state = _xmodmap_runner()
    platform, _tools = _platform_with_xmodmap(runner)
    plan = xi.keysym_plan(platform, ['đ', 'ổ', 'đ'])
    assert plan == {'đ': 250, 'ổ': 249}
    assert state['map'] == {250: 'U0111', 249: 'U1ED5'}
    xi.release_keycodes(platform, plan.values())
    assert state['map'] == {}


def test_typing_uses_the_keysym_path_for_non_ascii_characters():
    runner, state = _xmodmap_runner()
    platform, tools = _platform_with_xmodmap(runner)
    xi.type_text('ađb', window=0x11, platform=platform)
    keys = [call for call in tools.calls
            if os.path.basename(call[0]) == 'xdotool' and 'key' in call]
    assert keys and keys[-1][-1] == 'U0111', keys
    typed = [call for call in tools.calls
             if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    assert [call[call.index('--') + 1] for call in typed] == ['a', 'b'], typed
    assert state['map'] == {}, 'keycode phải được trả lại sau khi gõ'


def test_the_keysym_path_is_skipped_when_there_are_not_enough_spare_keycodes():
    runner, _state = _xmodmap_runner(spare=(250,))
    platform, tools = _platform_with_xmodmap(runner)
    xi.type_text('đổ', window=0x11, platform=platform)
    keys = [call for call in tools.calls
            if os.path.basename(call[0]) == 'xdotool' and 'key' in call]
    assert not keys, 'thiếu chỗ thì không được ánh xạ dở dang'
    typed = [call for call in tools.calls
             if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    assert [call[call.index('--') + 1] for call in typed] == ['đ', 'ổ']


def test_a_failed_mapping_falls_back_to_one_command_per_character():
    runner, _state = _xmodmap_runner(fail_map=True)
    platform, tools = _platform_with_xmodmap(runner)
    xi.type_text('đ', window=0x11, platform=platform)
    keys = [call for call in tools.calls
            if os.path.basename(call[0]) == 'xdotool' and 'key' in call]
    assert not keys
    typed = [call for call in tools.calls
             if os.path.basename(call[0]) == 'xdotool' and 'type' in call]
    assert [call[call.index('--') + 1] for call in typed] == ['đ']


def test_keycodes_are_released_even_when_the_keystroke_fails():
    runner, state = _xmodmap_runner(fail_key=True)
    platform, _tools = _platform_with_xmodmap(runner)
    with pytest.raises(PlatformError):
        xi.type_text('đ', window=0x11, platform=platform)
    assert state['map'] == {}, 'lỗi giữa chừng vẫn phải trả keycode về trống'


# ------------------------------------------- cuộn, kéo, giữ, vẽ nét (08/10/2026)
# Bốn thao tác cử chỉ dùng chung bốn chốt chặn của `click`, nhưng khác ở chỗ chúng giữ chuột qua
# NHIỀU lệnh. Ba chỗ dễ sai được kiểm ở đây: thứ tự lệnh, việc NHẢ chuột khi bước giữa hỏng (một nút
# còn giữ là cả máy không dùng được), và việc ghi lại từng bước là "con trỏ của chính ta" (bộ theo dõi
# người thật lấy mẫu ở luồng khác, đọc cú kéo của ta thành người thật là nó nhả quyền giữa cú kéo).
class CursorFake:
    """`xdotool` giả có con trỏ thật: `mousemove` cập nhật vị trí, `getmouselocation` đọc lại."""

    def __init__(self, tools, at=(0, 0), fail_move_to=None, fail_verb=None):
        self.tools = tools
        self.at = tuple(at)
        self.fail_move_to = fail_move_to
        self.fail_verb = fail_verb

    def __call__(self, argv, timeout):
        tool, args = os.path.basename(argv[0]), argv[1:]
        if tool == 'xdotool' and args and args[0] == 'getmouselocation':
            return xp._CommandResult(0, 'X=%d\nY=%d\n' % self.at)
        if tool == 'xdotool' and args and args[0] == 'mousemove':
            target = (int(args[-2]), int(args[-1]))
            if self.fail_move_to is not None and target == self.fail_move_to:
                return xp._CommandResult(1, '', 'XGetGeometry: BadWindow')
            self.at = target
        if tool == 'xdotool' and args and args[0] == self.fail_verb:
            # `_xdotool` KHÔNG ném lỗi khi lệnh thoát khác 0 — nó trả một kết quả hỏng. Đây là ca
            # "chính lệnh nhả chuột hỏng", thứ mà `finally` cũ bỏ qua vì `released` khác `None`.
            self.tools.calls.append(list(argv))
            return xp._CommandResult(1, '', 'XTestFakeButtonEvent: BadValue')
        return self.tools(argv, timeout)


def _gesture_platform(*, at=(0, 0), fail_move_to=None, rect=(0, 0, 100, 100), fail_verb=None):
    platform, tools = build(windows=[0x11], props={0x11: window_props()},
                            rects={0x11: rect}, foreground=0x11)
    platform._runner = CursorFake(tools, at=at, fail_move_to=fail_move_to, fail_verb=fail_verb)
    window = platform.describe_window(0x11)
    return platform, tools, window


def _xdotool_calls(tools, verb):
    return [call for call in tools.calls
            if os.path.basename(call[0]) == 'xdotool' and verb in call]


def test_scroll_moves_the_pointer_onto_the_window_then_rolls_the_wheel():
    platform, tools, window = _gesture_platform(at=(1, 1))
    outcome = xi.scroll(50, 50, window=window, direction='down', steps=5, platform=platform,
                        restore=False)
    assert outcome['steps'] == 5 and outcome['direction'] == 'down'
    rolls = _xdotool_calls(tools, 'click')
    assert len(rolls) == 1, 'cả loạt nấc đi trong MỘT lệnh `xdotool`'
    assert rolls[0][1:] == ['click', '--repeat', '5', '--delay', str(xi.SCROLL_STEP_DELAY_MS), '5']
    assert _xdotool_calls(tools, 'mousemove'), 'phải đưa con trỏ vào cửa sổ đích trước khi cuộn'


def test_scroll_maps_every_direction_to_the_x11_wheel_button():
    for direction, button in (('up', '4'), ('down', '5'), ('left', '6'), ('right', '7')):
        platform, tools, window = _gesture_platform()
        xi.scroll(50, 50, window=window, direction=direction, steps=1, platform=platform,
                  restore=False)
        assert _xdotool_calls(tools, 'click')[0][-1] == button, direction


def test_scroll_clamps_the_step_count_and_refuses_an_unknown_direction():
    platform, tools, window = _gesture_platform()
    outcome = xi.scroll(50, 50, window=window, direction='down', steps=999, platform=platform,
                        restore=False)
    assert outcome['steps'] == xi.MAX_SCROLL_STEPS
    assert _xdotool_calls(tools, 'click')[0][1:] == [
        'click', '--repeat', str(xi.MAX_SCROLL_STEPS), '--delay', str(xi.SCROLL_STEP_DELAY_MS), '5']
    with pytest.raises(PlatformError) as caught:
        xi.scroll(50, 50, window=window, direction='sideways', platform=platform, restore=False)
    assert caught.value.code == 'SOURCE_CHANGED'


def test_scroll_refuses_when_the_point_is_covered_before_sending_anything():
    platform, tools, window = _gesture_platform(rect=(0, 0, 10, 10))
    with pytest.raises(PlatformError) as caught:
        xi.scroll(50, 50, window=window, direction='down', platform=platform, restore=False)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert _xdotool_calls(tools, 'click') == [], 'không được cuộn khi chưa chứng minh điểm thuộc đích'


def test_drag_presses_moves_in_steps_and_releases():
    platform, tools, window = _gesture_platform(at=(10, 10))
    outcome = xi.drag(20, 20, 80, 60, window=window, steps=4, platform=platform, restore=False)
    verbs = [call[1] for call in tools.calls if os.path.basename(call[0]) == 'xdotool'
             and call[1] in ('mousemove', 'mousedown', 'mouseup')]
    assert verbs == ['mousemove', 'mousedown', 'mousemove', 'mousemove', 'mousemove', 'mousemove',
                     'mouseup'], verbs
    assert outcome['from'] == {'x': 20, 'y': 20} and outcome['to'] == {'x': 80, 'y': 60}
    assert platform.get_cursor_pos() == (80, 60), 'cú kéo kết thúc ở điểm đích'


def test_a_drag_releases_the_button_even_when_a_step_in_the_middle_fails():
    """Nút còn giữ là cả máy không dùng được nữa — kể cả khi bước giữa của cú kéo hỏng."""
    platform, tools, window = _gesture_platform(at=(10, 10), fail_move_to=(50, 40))
    with pytest.raises(PlatformError):
        xi.drag(20, 20, 80, 60, window=window, steps=4, platform=platform, restore=False)
    assert _xdotool_calls(tools, 'mousedown'), 'cú kéo đã bắt đầu'
    assert _xdotool_calls(tools, 'mouseup'), 'nút chuột PHẢI được nhả dù bước giữa hỏng'


def test_a_drag_out_of_a_pinned_window_is_refused_before_anything_is_sent():
    """Đích là một cửa sổ: cả điểm đầu lẫn điểm cuối phải nằm trong cửa sổ đó."""
    platform, tools, window = _gesture_platform(rect=(0, 0, 100, 100))
    with pytest.raises(PlatformError) as caught:
        xi.drag(20, 20, 900, 900, window=window, steps=4, platform=platform, restore=False,
                guard_end=True)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert tools.calls and not _xdotool_calls(tools, 'mousedown'), 'chưa gửi gì thì chưa được nhấn'


def test_a_drag_may_leave_the_window_when_the_target_is_the_whole_machine():
    """Đích là cả máy: kéo từ cửa sổ này sang cửa sổ khác là việc hợp lệ (thả tệp sang app khác)."""
    platform, tools, window = _gesture_platform(at=(10, 10))
    outcome = xi.drag(20, 20, 900, 900, window=window, steps=3, platform=platform, restore=False,
                      guard_end=False)
    assert outcome['to'] == {'x': 900, 'y': 900}
    assert _xdotool_calls(tools, 'mouseup')


def test_hold_keeps_the_button_down_and_clamps_the_duration():
    platform, tools, window = _gesture_platform(at=(10, 10))
    outcome = xi.hold(50, 50, window=window, seconds=99, platform=platform, restore=False)
    verbs = [call[1] for call in tools.calls if os.path.basename(call[0]) == 'xdotool'
             and call[1] in ('mousedown', 'mouseup')]
    assert verbs == ['mousedown', 'mouseup']
    assert outcome['seconds'] == xi.MAX_HOLD_SEC


def test_a_hold_releases_the_button_when_the_press_itself_fails():
    platform, tools, window = _gesture_platform(at=(10, 10), fail_move_to=(50, 50))
    with pytest.raises(PlatformError):
        xi.hold(50, 50, window=window, seconds=0.2, platform=platform, restore=False)
    assert _xdotool_calls(tools, 'mouseup'), 'nhấn hụt vẫn phải nhả (lệnh nhả là vô hại)'


def test_a_stroke_walks_every_point_of_the_path():
    platform, tools, window = _gesture_platform(at=(5, 5))
    outcome = xi.stroke([(10, 10), (30, 20), (60, 40), (90, 90)], window=window, platform=platform,
                        restore=False)
    moves = [call[-2:] for call in tools.calls if os.path.basename(call[0]) == 'xdotool'
             and 'mousemove' in call]
    assert moves == [['10', '10'], ['30', '20'], ['60', '40'], ['90', '90']], moves
    assert outcome['points'] == 4
    verbs = [call[1] for call in tools.calls if os.path.basename(call[0]) == 'xdotool'
             and call[1] in ('mousedown', 'mouseup')]
    assert verbs == ['mousedown', 'mouseup']


def test_a_stroke_needs_two_points_and_has_a_cap():
    platform, _tools, window = _gesture_platform()
    with pytest.raises(PlatformError) as caught:
        xi.stroke([(10, 10)], window=window, platform=platform, restore=False)
    assert caught.value.code == 'SOURCE_CHANGED'
    with pytest.raises(PlatformError) as too_long:
        xi.stroke([(10, 10)] * (xi.MAX_STROKE_POINTS + 1), window=window, platform=platform,
                  restore=False)
    assert too_long.value.code == 'SOURCE_CHANGED'
    with pytest.raises(PlatformError):
        xi.stroke([(10, 10), ('x', 'y')], window=window, platform=platform, restore=False)


def test_every_step_of_a_gesture_is_recorded_as_our_own_pointer():
    """Bộ theo dõi "người thật chạm máy" lấy mẫu ở luồng khác: đọc cú kéo của chính ta là người thật
    thì nó nhả quyền GIỮA cú kéo. Nên từng bước phải được ghi vào sổ con trỏ của ta."""
    platform, _tools, window = _gesture_platform(at=(10, 10))
    before = platform.last_input_tick()
    xi.drag(20, 20, 80, 60, window=window, steps=4, platform=platform, restore=False)
    # Con trỏ đang ở điểm cuối của cú kéo (do CHÍNH TA đặt) — không được tính là người thật.
    assert platform.last_input_tick() == before, 'cú kéo của ta bị đọc thành người thật'
    assert platform._own_pointer == (80, 60)


def test_a_stroke_leaves_the_pointer_at_the_last_point_of_the_path():
    platform, _tools, window = _gesture_platform(at=(5, 5))
    before = platform.last_input_tick()
    xi.stroke([(10, 10), (40, 25), (70, 55)], window=window, platform=platform, restore=False)
    assert platform.get_cursor_pos() == (70, 55)
    assert platform.last_input_tick() == before, 'nét vẽ của ta không được tính là người thật'


def test_a_pinned_stroke_refuses_a_path_that_ends_outside_the_target():
    """Nét vẽ là cú kéo nhiều điểm: nét cụt ra ngoài cửa sổ đích là một cú thả vào cửa sổ khác.

    Vòng soát mã đợt cử chỉ: `drag` đã canh điểm cuối từ đầu, còn `stroke` thì chỉ canh điểm đầu —
    nên một nét vẽ chạy quá mép cửa sổ đích vẫn nhấn, đi rồi thả ở cửa sổ bên kia, đúng thứ mà
    chốt của `drag` sinh ra để chặn.
    """
    platform, tools, window = _gesture_platform(at=(10, 10))
    with pytest.raises(PlatformError) as caught:
        xi.stroke([(10, 10), (50, 50), (300, 300)], window=window, platform=platform,
                  restore=False)
    assert caught.value.code == 'SOURCE_CHANGED'
    assert _xdotool_calls(tools, 'mousedown') == [], 'chưa chứng minh được điểm cuối thì chưa nhấn'


def test_a_machine_scope_stroke_may_end_outside_the_target():
    """Đích là CẢ MÁY thì nét vẽ được đi ra ngoài cửa sổ — cùng luật với `drag`."""
    platform, tools, window = _gesture_platform(at=(10, 10))
    outcome = xi.stroke([(10, 10), (50, 50), (300, 300)], window=window, platform=platform,
                        guard_end=False, restore=False)
    assert outcome['to'] == {'x': 300, 'y': 300}
    verbs = [call[1] for call in tools.calls if os.path.basename(call[0]) == 'xdotool'
             and call[1] in ('mousedown', 'mouseup')]
    assert verbs == ['mousedown', 'mouseup']


def test_a_failed_release_command_is_retried_because_the_button_may_still_be_down():
    """`_xdotool` trả kết quả hỏng chứ không ném lỗi, nên `released is not None` chưa là đã nhả.

    Đo trên máy thật: một lệnh `xdotool mouseup` hỏng để lại nút chuột đang giữ, và mọi cú bấm sau
    đó thành cú kéo. `finally` phải nhìn vào `ok` của kết quả, không chỉ nhìn vào `None`.
    """
    platform, tools, window = _gesture_platform(at=(10, 10), fail_verb='mouseup')
    with pytest.raises(PlatformError):
        xi.hold(50, 50, window=window, seconds=0.1, platform=platform, restore=False)
    assert len(_xdotool_calls(tools, 'mouseup')) == 2, 'lệnh nhả hỏng phải được nhả lại một lần nữa'
