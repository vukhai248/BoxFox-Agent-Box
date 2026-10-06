"""Test ba primitive H7 trong ``windows_platform``: nhàn rỗi, hook, mutex.

Chạy trên Linux: phần DLL được thay bằng stub (``user32``/``kernel32`` giả) nên cả
đường gọi Win32 lẫn phần đọc struct đều được kiểm thử thật, không cần Windows.
"""
from __future__ import annotations

import ctypes
from typing import Any

import pytest
from win_fakes import FakePlatform, hook_event_dict, reset_win_state

from agentbox.sandbox.win import windows_platform as wp
from agentbox.sandbox.win.errors import UNSUPPORTED_IN_HOST_MODE, PlatformError
from agentbox.sandbox.win.windows_platform import (
    DESKTOP_INPUT_MUTEX_NAME,
    HOOK_MIN_POINTER,
    IDLE_TICK_MODULO,
    KBDLLHOOKSTRUCT,
    KEYBOARD_INJECTED_FLAGS,
    LASTINPUTINFO,
    LLKHF_ALTDOWN,
    LLKHF_EXTENDED,
    LLKHF_INJECTED,
    LLKHF_LOWER_IL_INJECTED,
    LLKHF_UP,
    LLMHF_INJECTED,
    LLMHF_LOWER_IL_INJECTED,
    MAX_IDLE_MS,
    MOUSE_INJECTED_FLAGS,
    MSLLHOOKSTRUCT,
    WAIT_ABANDONED,
    WAIT_FAILED,
    WAIT_OBJECT_0,
    WAIT_TIMEOUT,
    WH_KEYBOARD_LL,
    WH_MOUSE_LL,
    UnavailablePlatform,
    WindowsPlatform,
    clear_callback_refs,
    callback_ref_count,
)

MOUSE_MOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_KEYDOWN = 0x0100


@pytest.fixture(autouse=True)
def _clean_state():
    reset_win_state()
    clear_callback_refs()
    yield
    reset_win_state()
    clear_callback_refs()


# ---------------------------------------------------------------------------
# Stub DLL — chỉ đủ để chạy đường gọi thật của WindowsPlatform trên Linux
# ---------------------------------------------------------------------------
def _as_int(value: Any) -> int:
    """Handle có thể tới dưới dạng ``c_void_p`` (ctypes bọc) hoặc int trần."""
    if isinstance(value, ctypes.c_void_p):
        return int(value.value or 0)
    return int(value or 0)


class _StubUser32:
    def __init__(self, *, tick: int = 0, last_ok: bool = True, hook_handle: int = 0x1234) -> None:
        self.tick = int(tick)
        self.last_ok = last_ok
        self.hook_handle = int(hook_handle)
        self.last_input_calls = 0
        self.hook_calls: list[tuple] = []
        self.unhook_calls: list[int] = []

    def GetLastInputInfo(self, pointer) -> int:
        self.last_input_calls += 1
        if not self.last_ok:
            return 0
        pointer._obj.dwTime = self.tick
        return 1

    def SetWindowsHookExW(self, kind, proc, module, thread) -> int:
        self.hook_calls.append((kind, proc, module, thread))
        return self.hook_handle

    def UnhookWindowsHookEx(self, handle) -> int:
        self.unhook_calls.append(_as_int(handle))
        return 1


class _StubKernel32:
    def __init__(
        self,
        *,
        now: int = 0,
        wait_result: int = WAIT_OBJECT_0,
        mutex_handle: int = 0x777,
        release_ok: bool = True,
        close_ok: bool = True,
    ) -> None:
        self.now = int(now)
        self.wait_result = int(wait_result)
        self.mutex_handle = int(mutex_handle)
        self.release_ok = release_ok
        self.close_ok = close_ok
        self.mutex_names: list[str] = []
        self.waits: list[tuple[int, int]] = []
        self.releases: list[int] = []
        self.closed: list[int] = []
        self.module_calls = 0

    def GetTickCount64(self) -> int:
        return self.now

    def GetModuleHandleW(self, name) -> int:
        self.module_calls += 1
        return 0x400000

    def CreateMutexW(self, attrs, initial, name) -> int:
        self.mutex_names.append(name)
        return self.mutex_handle

    def WaitForSingleObject(self, handle, timeout) -> int:
        self.waits.append((_as_int(handle), int(timeout)))
        return self.wait_result

    def ReleaseMutex(self, handle) -> int:
        self.releases.append(_as_int(handle))
        return 1 if self.release_ok else 0

    def CloseHandle(self, handle) -> int:
        self.closed.append(_as_int(handle))
        return 1 if self.close_ok else 0


def _platform(monkeypatch, user32=None, kernel32=None) -> WindowsPlatform:
    """``WindowsPlatform`` thật với hai DLL được thay bằng stub."""
    platform = WindowsPlatform()
    if user32 is not None:
        monkeypatch.setattr(WindowsPlatform, "user32", property(lambda self: user32))
    if kernel32 is not None:
        monkeypatch.setattr(WindowsPlatform, "kernel32", property(lambda self: kernel32))
    return platform


# ---------------------------------------------------------------------------
# Struct + hằng số
# ---------------------------------------------------------------------------
def test_struct_layouts_are_x64():
    assert ctypes.sizeof(LASTINPUTINFO) == 8
    assert LASTINPUTINFO.cbSize.offset == 0
    assert LASTINPUTINFO.dwTime.offset == 4

    assert ctypes.sizeof(MSLLHOOKSTRUCT) == 32
    assert MSLLHOOKSTRUCT.pt.offset == 0
    assert MSLLHOOKSTRUCT.mouseData.offset == 8
    assert MSLLHOOKSTRUCT.flags.offset == 12
    assert MSLLHOOKSTRUCT.time.offset == 16
    assert MSLLHOOKSTRUCT.dwExtraInfo.offset == 24

    assert ctypes.sizeof(KBDLLHOOKSTRUCT) == 24
    assert KBDLLHOOKSTRUCT.vkCode.offset == 0
    assert KBDLLHOOKSTRUCT.scanCode.offset == 4
    assert KBDLLHOOKSTRUCT.flags.offset == 8
    assert KBDLLHOOKSTRUCT.time.offset == 12
    assert KBDLLHOOKSTRUCT.dwExtraInfo.offset == 16


def test_flag_constants_are_the_documented_values():
    assert WH_MOUSE_LL == 14
    assert WH_KEYBOARD_LL == 13
    assert LLMHF_INJECTED == 0x1
    assert LLMHF_LOWER_IL_INJECTED == 0x2
    assert LLKHF_INJECTED == 0x10
    assert LLKHF_LOWER_IL_INJECTED == 0x2
    assert LLKHF_EXTENDED == 0x1
    assert LLKHF_ALTDOWN == 0x20
    assert LLKHF_UP == 0x80
    assert MOUSE_INJECTED_FLAGS == 0x3
    assert KEYBOARD_INJECTED_FLAGS == 0x12
    assert DESKTOP_INPUT_MUTEX_NAME == "Local\\BoxFoxDesktopInput-v1"
    assert DESKTOP_INPUT_MUTEX_NAME.startswith("Local\\")
    assert (WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT) == (0x0, 0x80, 0x102)
    assert WAIT_FAILED == 0xFFFFFFFF


# ---------------------------------------------------------------------------
# 1. Thời gian nhàn rỗi
# ---------------------------------------------------------------------------
def test_last_input_tick_reads_dwtime(monkeypatch):
    user32 = _StubUser32(tick=12_345)
    platform = _platform(monkeypatch, user32=user32)
    assert platform.last_input_tick() == 12_345
    assert user32.last_input_calls == 1


def test_last_input_tick_is_zero_on_failure(monkeypatch):
    platform = _platform(monkeypatch, user32=_StubUser32(tick=999, last_ok=False))
    assert platform.last_input_tick() == 0


def test_idle_seconds_is_none_when_tick_unknown(monkeypatch):
    platform = _platform(
        monkeypatch, user32=_StubUser32(last_ok=False), kernel32=_StubKernel32(now=50_000)
    )
    assert platform.idle_seconds() is None


def test_idle_seconds_uses_supplied_now_tick(monkeypatch):
    platform = _platform(monkeypatch, user32=_StubUser32(tick=100_000))
    assert platform.idle_seconds(now_tick=103_500) == 3.5


def test_idle_seconds_reads_the_clock_when_now_tick_is_falsy(monkeypatch):
    platform = _platform(
        monkeypatch, user32=_StubUser32(tick=100_000), kernel32=_StubKernel32(now=102_000)
    )
    assert platform.idle_seconds() == 2.0
    assert platform.idle_seconds(now_tick=0) == 2.0  # 0 = "không truyền", đọc đồng hồ thật


def test_idle_seconds_survives_32_bit_wrap(monkeypatch):
    # dwTime tràn sau ~49,7 ngày: 0xFFFFFFF0 → 0x00000010 là 32 ms, không phải số âm.
    platform = _platform(monkeypatch, user32=_StubUser32(tick=0xFFFFFFF0))
    assert platform.idle_seconds(now_tick=0x00000010) == pytest.approx(0.032)
    assert platform.idle_seconds(now_tick=0x1_0000_0010) == pytest.approx(0.032)


def test_idle_seconds_refuses_absurd_values(monkeypatch):
    platform = _platform(monkeypatch, user32=_StubUser32(tick=1))
    # Ngay trên trần thì vẫn đo được (biên là "> MAX_IDLE_MS"), quá xa thì thôi.
    assert platform.idle_seconds(now_tick=MAX_IDLE_MS + 1) == pytest.approx(MAX_IDLE_MS / 1000.0)
    assert platform.idle_seconds(now_tick=MAX_IDLE_MS + 2) is None
    # Trần tuyệt đối của một DWORD vẫn phải là số dương, không bao giờ âm.
    assert platform.idle_seconds(now_tick=IDLE_TICK_MODULO - 1) is None


def test_idle_seconds_never_returns_a_negative_number(monkeypatch):
    platform = _platform(
        monkeypatch, user32=_StubUser32(tick=500_000), kernel32=_StubKernel32(now=500_000)
    )
    for now in (0, 1, 499_999, 500_000, 500_001, 0xFFFFFFFF, 0x1_0000_0000):
        value = platform.idle_seconds(now_tick=now)
        assert value is None or value >= 0


# ---------------------------------------------------------------------------
# 2. Hook + cờ injected
# ---------------------------------------------------------------------------
def test_hook_event_parses_mouse_struct():
    data = MSLLHOOKSTRUCT()
    data.pt.x, data.pt.y = 640, 480
    data.flags = LLMHF_INJECTED
    event = WindowsPlatform().hook_event("mouse", MOUSE_MOVE, ctypes.addressof(data))
    assert event == {
        "injected": True,
        "vkey": None,
        "scanCode": None,
        "flags": LLMHF_INJECTED,
        "point": (640, 480),
        "message": MOUSE_MOVE,
    }


def test_hook_event_parses_keyboard_struct():
    data = KBDLLHOOKSTRUCT()
    data.vkCode, data.scanCode = 0x41, 0x1E
    data.flags = LLKHF_INJECTED | LLKHF_EXTENDED
    event = WindowsPlatform().hook_event("keyboard", WM_KEYDOWN, ctypes.addressof(data))
    assert event == {
        "injected": True,
        "vkey": 0x41,
        "scanCode": 0x1E,
        "flags": LLKHF_INJECTED | LLKHF_EXTENDED,
        "point": None,
        "message": WM_KEYDOWN,
    }


def test_hook_event_treats_lower_integrity_injection_as_injected():
    mouse = MSLLHOOKSTRUCT()
    mouse.flags = LLMHF_LOWER_IL_INJECTED
    assert WindowsPlatform().hook_event("mouse", MOUSE_MOVE, ctypes.addressof(mouse))["injected"] is True

    keyboard = KBDLLHOOKSTRUCT()
    keyboard.flags = LLKHF_LOWER_IL_INJECTED
    assert (
        WindowsPlatform().hook_event("keyboard", WM_KEYDOWN, ctypes.addressof(keyboard))["injected"]
        is True
    )


def test_hook_event_reports_a_real_human_when_no_injected_flag():
    mouse = MSLLHOOKSTRUCT()
    mouse.pt.x, mouse.pt.y = 10, 20
    mouse.flags = 0
    event = WindowsPlatform().hook_event("mouse", WM_LBUTTONDOWN, ctypes.addressof(mouse))
    assert event["injected"] is False
    assert event["point"] == (10, 20)
    assert event["message"] == WM_LBUTTONDOWN


def test_our_own_send_input_events_are_flagged_injected():
    """Sự kiện do ta gửi đi qua ``SendInput`` ⇒ Windows bật cờ injected cho chúng.

    Đây là chỗ duy nhất phân biệt "bàn tay máy" với "người thật": mọi sự kiện
    ``input.py`` gửi (``_send_batch`` → ``platform.send_input``) đều mang cờ, nên
    ``injected is False`` mới là người thật. Test khoá cả hai nửa.
    """
    ours = MSLLHOOKSTRUCT()
    ours.flags = LLMHF_INJECTED  # đúng cờ Windows đặt cho sự kiện SendInput
    assert WindowsPlatform().hook_event("mouse", MOUSE_MOVE, ctypes.addressof(ours))["injected"] is True

    theirs = MSLLHOOKSTRUCT()
    theirs.flags = 0  # bàn tay người: không cờ nào
    assert WindowsPlatform().hook_event("mouse", MOUSE_MOVE, ctypes.addressof(theirs))["injected"] is False


def test_hook_event_guards_null_and_short_pointers():
    platform = WindowsPlatform()
    for pointer in (0, 1, 0x10, HOOK_MIN_POINTER - 1, -1):
        assert platform.hook_event("mouse", MOUSE_MOVE, pointer) == {}
        assert platform.hook_event("keyboard", WM_KEYDOWN, pointer) == {}


def test_hook_event_returns_empty_for_unknown_kind_or_wparam():
    platform = WindowsPlatform()
    data = MSLLHOOKSTRUCT()
    assert platform.hook_event("touch", MOUSE_MOVE, ctypes.addressof(data)) == {}
    assert platform.hook_event(None, MOUSE_MOVE, ctypes.addressof(data)) == {}
    # wparam rỗng vẫn đọc được struct (message = 0).
    event = platform.hook_event("mouse", 0, ctypes.addressof(data))
    assert event["message"] == 0


class _ProcFactory:
    """Giả ``ctypes.WINFUNCTYPE`` (Linux không có) để kiểm tra luật giữ tham chiếu."""

    def __init__(self) -> None:
        self.made: list[tuple] = []

    def __call__(self, *argtypes):
        def wrap(callback):
            proc = ("proc", callback, argtypes)
            self.made.append(proc)
            return proc

        return wrap


def test_set_mouse_hook_wires_wh_mouse_ll_and_keeps_the_callback_alive(monkeypatch):
    factory = _ProcFactory()
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", factory, raising=False)
    user32, kernel32 = _StubUser32(hook_handle=0x2222), _StubKernel32()
    platform = _platform(monkeypatch, user32=user32, kernel32=kernel32)

    callback = lambda code, wparam, lparam: 0  # noqa: E731 - callback hook thật
    handle = platform.set_mouse_hook(callback)

    assert handle == 0x2222
    assert user32.hook_calls[0][0] == WH_MOUSE_LL
    assert user32.hook_calls[0][2] == 0x400000  # GetModuleHandleW(None)
    assert callback_ref_count() == 1  # callback không được để bị thu gom rác
    assert factory.made[0][2][0] is ctypes.c_ssize_t


def test_set_mouse_hook_returns_none_when_windows_refuses(monkeypatch):
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", _ProcFactory(), raising=False)
    platform = _platform(
        monkeypatch, user32=_StubUser32(hook_handle=0), kernel32=_StubKernel32()
    )
    assert platform.set_mouse_hook(lambda *args: 0) is None


def test_unhook_mouse_releases_the_handle_once(monkeypatch):
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", _ProcFactory(), raising=False)
    user32 = _StubUser32(hook_handle=0x3333)
    platform = _platform(monkeypatch, user32=user32, kernel32=_StubKernel32())

    platform.set_mouse_hook(lambda *args: 0)
    platform.unhook_mouse()
    assert user32.unhook_calls == [0x3333]

    platform.unhook_mouse()  # lần hai là no-op, không gọi thêm
    assert user32.unhook_calls == [0x3333]


def test_call_next_hook_uses_the_installed_hook_handle(monkeypatch):
    class _StubNext:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def CallNextHookEx(self, handle, code, wparam, lparam) -> int:
            self.calls.append((_as_int(handle), code, wparam, lparam))
            return 7

    monkeypatch.setattr(ctypes, "WINFUNCTYPE", _ProcFactory(), raising=False)
    user32 = _StubNext()
    monkeypatch.setattr(WindowsPlatform, "user32", property(lambda self: user32))
    platform = WindowsPlatform()
    monkeypatch.setattr(
        WindowsPlatform, "kernel32", property(lambda self: _StubKernel32())
    )

    # Chỉ có hook chuột: vẫn phải chuyền đúng handle, không được để NULL.
    platform._mouse_hook = 0x9999
    assert platform.call_next_hook(0, 0x200, 0x10000) == 7
    assert user32.calls[0][0] == 0x9999

    platform._hook = 0x8888
    assert platform.call_next_hook(0, 0x100, 0x10000) == 7
    assert user32.calls[1][0] == 0x8888  # hook bàn phím được ưu tiên khi cả hai cùng sống
    assert platform.call_next_hook(0, 0x100, 0x10000, hook=0x7777) == 7
    assert user32.calls[2][0] == 0x7777


def test_mouse_and_keyboard_hooks_are_independent(monkeypatch):
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", _ProcFactory(), raising=False)
    user32 = _StubUser32(hook_handle=0x4444)
    platform = _platform(monkeypatch, user32=user32, kernel32=_StubKernel32())

    platform.set_keyboard_hook(lambda *args: 0)
    platform.set_mouse_hook(lambda *args: 0)
    assert [call[0] for call in user32.hook_calls] == [WH_KEYBOARD_LL, WH_MOUSE_LL]

    platform.unhook_mouse()
    assert platform._hook == 0x4444  # hook bàn phím vẫn còn
    platform.unhook_keyboard()
    assert platform._hook is None


# ---------------------------------------------------------------------------
# 3. Mutex liên tiến trình
# ---------------------------------------------------------------------------
def test_create_mutex_passes_the_documented_name(monkeypatch):
    kernel32 = _StubKernel32(mutex_handle=0x5555)
    platform = _platform(monkeypatch, kernel32=kernel32)
    assert platform.create_mutex(DESKTOP_INPUT_MUTEX_NAME) == 0x5555
    assert kernel32.mutex_names == [DESKTOP_INPUT_MUTEX_NAME]


def test_create_mutex_returns_none_when_windows_refuses(monkeypatch):
    platform = _platform(monkeypatch, kernel32=_StubKernel32(mutex_handle=0))
    assert platform.create_mutex(DESKTOP_INPUT_MUTEX_NAME) is None


@pytest.mark.parametrize(
    "wait_result,expected",
    [
        (WAIT_OBJECT_0, True),
        (WAIT_ABANDONED, True),
        (WAIT_TIMEOUT, False),
        (WAIT_FAILED, False),
    ],
)
def test_acquire_mutex_maps_wait_results(monkeypatch, wait_result, expected):
    kernel32 = _StubKernel32(wait_result=wait_result)
    platform = _platform(monkeypatch, kernel32=kernel32)
    assert platform.acquire_mutex(0x5555, timeout_ms=250) is expected
    assert kernel32.waits == [(0x5555, 250)]


def test_acquire_mutex_defaults_to_no_wait(monkeypatch):
    kernel32 = _StubKernel32()
    platform = _platform(monkeypatch, kernel32=kernel32)
    assert platform.acquire_mutex(0x5555) is True
    assert kernel32.waits == [(0x5555, 0)]


def test_mutex_helpers_refuse_a_null_handle_without_calling_the_dll(monkeypatch):
    kernel32 = _StubKernel32()
    platform = _platform(monkeypatch, kernel32=kernel32)
    assert platform.acquire_mutex(0) is False
    assert platform.release_mutex(0) is False
    assert platform.close_handle(0) is False
    assert (kernel32.waits, kernel32.releases, kernel32.closed) == ([], [], [])


def test_release_and_close_handle(monkeypatch):
    kernel32 = _StubKernel32()
    platform = _platform(monkeypatch, kernel32=kernel32)
    assert platform.release_mutex(0x5555) is True
    assert platform.close_handle(0x5555) is True
    assert kernel32.releases == [0x5555]
    assert kernel32.closed == [0x5555]

    failing = _platform(monkeypatch, kernel32=_StubKernel32(release_ok=False, close_ok=False))
    assert failing.release_mutex(0x5555) is False
    assert failing.close_handle(0x5555) is False


# ---------------------------------------------------------------------------
# Ngoài Windows: cả ba primitive phải từ chối
# ---------------------------------------------------------------------------
def test_unavailable_platform_refuses_all_three_primitives():
    platform = UnavailablePlatform()
    assert platform.available is False

    calls = {
        "last_input_tick": lambda: platform.last_input_tick(),
        "idle_seconds": lambda: platform.idle_seconds(),
        "set_mouse_hook": lambda: platform.set_mouse_hook(lambda *args: 0),
        "unhook_mouse": lambda: platform.unhook_mouse(),
        "hook_event": lambda: platform.hook_event("mouse", MOUSE_MOVE, 0x10000),
        "create_mutex": lambda: platform.create_mutex(DESKTOP_INPUT_MUTEX_NAME),
        "acquire_mutex": lambda: platform.acquire_mutex(1),
        "release_mutex": lambda: platform.release_mutex(1),
        "close_handle": lambda: platform.close_handle(1),
    }
    for name, call in calls.items():
        with pytest.raises(PlatformError) as error:
            call()
        assert error.value.code == UNSUPPORTED_IN_HOST_MODE, name


def test_unavailable_platform_is_what_linux_gets():
    wp.set_platform(None)
    try:
        assert wp.get_platform().name == "unavailable"
    finally:
        wp.set_platform(None)


# ---------------------------------------------------------------------------
# Nền tảng giả (H7 dùng) phải có đủ ba primitive
# ---------------------------------------------------------------------------
def test_fake_platform_exposes_the_three_primitives():
    fake = FakePlatform(input_tick=100_000, now_tick=104_000)
    assert fake.last_input_tick() == 100_000
    assert fake.tick_count() == 104_000
    assert fake.idle_seconds() == 4.0
    assert fake.idle_seconds(now_tick=100_500) == 0.5
    assert FakePlatform(idle_value=12.5).idle_seconds() == 12.5
    assert FakePlatform(input_tick=0).idle_seconds() is None

    assert fake.set_mouse_hook(lambda *args: 0) == fake.mouse_hook_handle
    assert fake.mouse_callback is not None
    fake.unhook_mouse()
    assert fake.mouse_callback is None
    assert FakePlatform(hook_ok=False).set_mouse_hook(lambda *args: 0) is None

    assert fake.create_mutex(DESKTOP_INPUT_MUTEX_NAME) == fake.mutex_handle
    assert fake.acquire_mutex(fake.mutex_handle) is True
    assert FakePlatform(mutex_acquired=False).acquire_mutex(1) is False
    assert fake.acquire_mutex(0) is False
    assert fake.release_mutex(fake.mutex_handle) is True
    assert fake.close_handle(fake.mutex_handle) is True


def test_fake_platform_serves_scripted_hook_events():
    fake = FakePlatform(
        hook_events=[hook_event_dict(injected=True, message=MOUSE_MOVE), hook_event_dict()]
    )
    assert fake.hook_event("mouse", MOUSE_MOVE, 0x10000)["injected"] is True
    assert fake.hook_event("mouse", MOUSE_MOVE, 0x10000)["injected"] is False
    assert fake.hook_event("mouse", MOUSE_MOVE, 0x10000) == {}
    assert fake.called("hook_event")[0] == ("mouse", MOUSE_MOVE, 0x10000)
