"""Test tầng gửi input Windows (H5, §4.3) — chạy trên Linux bằng nền tảng giả."""
from __future__ import annotations

import pytest
from win_fakes import FakePlatform, decode_events, make_window, reset_win_state

from agentbox.sandbox.win import capture, input as win_input, uia
from agentbox.sandbox.win.errors import (
    DESKTOP_LOCKED,
    ELEMENT_STALE,
    INPUT_SHORT_SEND,
    PASSWORD_FIELD_REFUSED,
    POST_MESSAGE_UNSUPPORTED,
    SESSION_NOT_INTERACTIVE,
    SOURCE_CHANGED,
    UIPI_BLOCKED,
    PlatformError,
)
from agentbox.sandbox.win.windows_platform import (
    KEYEVENTF_KEYUP,
    KEYEVENTF_UNICODE,
    MOUSEEVENTF_ABSOLUTE,
    MOUSEEVENTF_LEFTDOWN,
    MOUSEEVENTF_LEFTUP,
    MOUSEEVENTF_MOVE,
    MOUSEEVENTF_VIRTUALDESK,
    SECURITY_MANDATORY_HIGH_RID,
)


@pytest.fixture(autouse=True)
def _clean_state():
    reset_win_state()
    yield
    reset_win_state()


# ---------------------------------------------------------------------------
# Toạ độ — gốc desktop ảo có thể âm
# ---------------------------------------------------------------------------
def test_normalize_coordinates_with_negative_virtual_origin():
    fake = FakePlatform(virtual_screen=(-1920, 0, 3840, 1080))
    assert win_input.normalize_coordinates(-1920, 0, platform=fake) == (0, 0)
    assert win_input.normalize_coordinates(1919, 1079, platform=fake) == (65535, 65535)
    # 0 nằm chính giữa desktop ảo ⇒ ~32767/32768, không phải giá trị bị cắt 32 bit.
    middle_x, _ = win_input.normalize_coordinates(0, 0, platform=fake)
    assert 32700 <= middle_x <= 32800


def test_normalized_coordinates_round_trip_within_one_pixel():
    fake = FakePlatform(virtual_screen=(-1920, -200, 3840, 1280))
    for x in (-1920, -1000, -1, 0, 1, 960, 1919):
        for y in (-200, -50, 0, 640, 1079):
            nx, ny = win_input.normalize_coordinates(x, y, platform=fake)
            assert 0 <= nx <= 65535 and 0 <= ny <= 65535
            back_x, back_y = win_input.denormalize_coordinates(nx, ny, platform=fake)
            assert abs(back_x - x) <= 1
            assert abs(back_y - y) <= 1


def test_normalize_coordinates_clamps_outside_desktop():
    fake = FakePlatform(virtual_screen=(0, 0, 1920, 1080))
    assert win_input.normalize_coordinates(-500, -500, platform=fake) == (0, 0)
    assert win_input.normalize_coordinates(99999, 99999, platform=fake) == (65535, 65535)


# ---------------------------------------------------------------------------
# Gửi hụt — chỉ nhả phím đã chèn, theo thứ tự ngược
# ---------------------------------------------------------------------------
def test_pending_releases_releases_only_inserted_modifiers_in_reverse_order():
    batch = win_input.EventBatch(label="press_key")
    batch.combo(
        [0x11, 0x10],  # ctrl, shift
        win_input.key_input(0x41),
        win_input.key_input(0x41, 0, KEYEVENTF_KEYUP),
    )
    assert len(batch) == 6  # ctrl↓ shift↓ a↓ a↑ shift↑ ctrl↑

    # Windows chỉ chèn 3 sự kiện đầu: ctrl↓, shift↓, 'A'↓.
    releases = win_input.pending_releases(batch.events, batch.pairs, 3)
    decoded = decode_events(releases)
    assert [(item["vk"], item["flags"]) for item in decoded] == [
        (0x41, KEYEVENTF_KEYUP),
        (0x10, KEYEVENTF_KEYUP),
        (0x11, KEYEVENTF_KEYUP),
    ]


def test_pending_releases_never_releases_uninserted_keys():
    batch = win_input.EventBatch(label="press_key")
    batch.combo(
        [0x11, 0x10],
        win_input.key_input(0x41),
        win_input.key_input(0x41, 0, KEYEVENTF_KEYUP),
    )
    # Chỉ ctrl↓ được chèn ⇒ chỉ nhả ctrl; shift và A chưa từng được nhấn.
    decoded = decode_events(win_input.pending_releases(batch.events, batch.pairs, 1))
    assert [item["vk"] for item in decoded] == [0x11]


def test_pending_releases_skips_pairs_that_already_landed():
    batch = win_input.EventBatch(label="press_key")
    batch.combo([0x11], win_input.key_input(0x41), win_input.key_input(0x41, 0, KEYEVENTF_KEYUP))
    # Cả ctrl↓, A↓, A↑, ctrl↑ đều đã được chèn ⇒ không nhả lại gì.
    assert win_input.pending_releases(batch.events, batch.pairs, 4) == []
    # Chỉ tới A↑ ⇒ còn ctrl đang giữ.
    assert [item["vk"] for item in decode_events(win_input.pending_releases(batch.events, batch.pairs, 3))] == [0x11]


def test_short_send_raises_and_releases_in_reverse_order():
    fake = FakePlatform(accept_events=3, foreground=100)
    with pytest.raises(PlatformError) as error:
        win_input.press_key("a", window=100, modifiers=["ctrl", "shift"], platform=fake)
    assert error.value.code == INPUT_SHORT_SEND
    assert error.value.details["sent"] == 3
    assert error.value.details["stage"] == "press_key"
    # `sent_events` là mọi sự kiện ĐÃ ĐƯA VÀO SendInput: 6 của lô gốc + 3 sự kiện nhả.
    assert len(fake.sent_events) == 9
    releases = decode_events(fake.sent_events[6:])
    assert [(item["vk"], item["scan"], item["flags"]) for item in releases] == [
        (0, ord("a"), KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
        (0x10, 0, KEYEVENTF_KEYUP),
        (0x11, 0, KEYEVENTF_KEYUP),
    ]
    assert [item["vk"] for item in decode_events(fake.sent_events[:3])] == [0x11, 0x10, 0]


def test_stuck_input_is_recorded_when_release_also_fails():
    fake = FakePlatform(accept_events=1, foreground=100)
    with pytest.raises(PlatformError):
        win_input.press_key("a", window=100, modifiers=["ctrl"], platform=fake)
    assert win_input.stuck_input_count() == 1

    clean = FakePlatform(foreground=100)
    assert win_input.release_stuck_input(platform=clean) == 1
    assert win_input.stuck_input_count() == 0
    assert [item["vk"] for item in decode_events(clean.sent_events)] == [0x11]
    assert decode_events(clean.sent_events)[0]["flags"] == KEYEVENTF_KEYUP


# ---------------------------------------------------------------------------
# Từ chối trước khi gửi
# ---------------------------------------------------------------------------
def test_uipi_blocked_when_target_has_higher_integrity():
    fake = FakePlatform(integrity_by_pid={1000: SECURITY_MANDATORY_HIGH_RID})
    with pytest.raises(PlatformError) as error:
        win_input.click(10, 10, window=100, platform=fake)
    assert error.value.code == UIPI_BLOCKED
    assert fake.sent_events == []


def test_desktop_locked_refuses_before_sending():
    fake = FakePlatform(desktop="Winlogon")
    with pytest.raises(PlatformError) as error:
        win_input.click(10, 10, window=100, platform=fake)
    assert error.value.code == DESKTOP_LOCKED
    assert fake.sent_events == []


def test_non_interactive_session_refuses():
    fake = FakePlatform(interactive=False, session=0)
    with pytest.raises(PlatformError) as error:
        win_input.type_text("hello", window=100, platform=fake)
    assert error.value.code == SESSION_NOT_INTERACTIVE
    assert fake.sent_events == []


def test_password_field_is_refused():
    fake = FakePlatform()
    with pytest.raises(PlatformError) as error:
        win_input.type_text("secret", window=100, element={"isPassword": True}, platform=fake)
    assert error.value.code == PASSWORD_FIELD_REFUSED
    assert fake.sent_events == []


def test_geometry_change_refuses_with_source_changed():
    fake = FakePlatform()
    capture.geometry_revision("win:100:1000", (0, 0, 800, 600, 96))
    with pytest.raises(PlatformError) as error:
        win_input.click(
            10, 10, window=100, platform=fake, source_id="win:100:1000", geometry_revision=99
        )
    assert error.value.code == SOURCE_CHANGED
    assert error.value.details["reason"] == "geometry_changed"


def test_stale_element_token_is_refused_by_uia():
    session = uia.UiaSession(accessor=uia.UiaAccessor())
    with pytest.raises(PlatformError) as error:
        win_input.click_element("s00000001:0", window=100, platform=FakePlatform(), session=session)
    assert error.value.code == ELEMENT_STALE


# ---------------------------------------------------------------------------
# Bị che (§4.5)
# ---------------------------------------------------------------------------
def test_occluded_point_refuses_before_sending():
    fake = FakePlatform(point_map={(10, 10): 200})
    with pytest.raises(PlatformError) as error:
        win_input.click(10, 10, window=100, platform=fake)
    assert error.value.code == SOURCE_CHANGED
    assert error.value.details["reason"] == "occluded"
    assert fake.sent_events == []


# ---------------------------------------------------------------------------
# Chuột — một lô [move, down, up]
# ---------------------------------------------------------------------------
def test_click_sends_single_batch_and_restores_cursor_and_foreground():
    fake = FakePlatform(foreground=100, cursor=(7, 9))
    result = win_input.click(400, 300, window=100, platform=fake)
    assert result["route"] == "send_input"
    assert result["events"] == 3
    decoded = decode_events(fake.sent_events)
    assert decoded[0]["flags"] == MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    assert decoded[1]["flags"] == MOUSEEVENTF_LEFTDOWN
    assert decoded[2]["flags"] == MOUSEEVENTF_LEFTUP
    # Con trỏ và foreground được trả về trạng thái trước thao tác.
    assert fake.called("set_cursor_pos") == [(7, 9)]
    assert fake.called("set_foreground_window")[-1] == (100,)


def test_click_raises_source_changed_when_foreground_is_another_window():
    fake = FakePlatform(foreground=200, windows=[make_window(100), make_window(200)])
    with pytest.raises(PlatformError) as error:
        win_input.click(400, 300, window=100, platform=fake, timeout=0)
    assert error.value.code == SOURCE_CHANGED
    assert fake.sent_events == []


def test_click_rejects_unknown_button():
    with pytest.raises(PlatformError):
        win_input.click(1, 1, window=100, button="thumb", platform=FakePlatform())


# ---------------------------------------------------------------------------
# Bàn phím
# ---------------------------------------------------------------------------
def test_type_text_uses_unicode_events_and_foreground_check():
    fake = FakePlatform(foreground=100)
    result = win_input.type_text("Box", window=100, platform=fake)
    assert result["chars"] == 3
    decoded = decode_events(fake.sent_events)
    assert [item["scan"] for item in decoded] == [ord("B"), ord("B"), ord("o"), ord("o"), ord("x"), ord("x")]
    assert decoded[0]["flags"] == KEYEVENTF_UNICODE
    assert decoded[1]["flags"] == KEYEVENTF_UNICODE | KEYEVENTF_KEYUP


def test_type_text_encodes_non_bmp_as_surrogate_pair():
    fake = FakePlatform(foreground=100)
    win_input.type_text("\U0001f600", window=100, platform=fake)
    decoded = decode_events(fake.sent_events)
    assert len(decoded) == 4  # 2 đơn vị UTF-16 × (down + up)
    assert [item["scan"] for item in decoded[::2]] == [0xD83D, 0xDE00]


def test_type_text_stops_when_foreground_changes_between_chunks():
    fake = FakePlatform(foreground=100)
    original = fake.send_input

    def send_input(events):
        result = original(events)
        fake.foreground = 200  # người dùng chuyển cửa sổ giữa hai lô
        return result

    fake.send_input = send_input
    text = "a" * (win_input.TEXT_CHUNK_UNITS + 5)
    with pytest.raises(PlatformError) as error:
        win_input.type_text(text, window=100, platform=fake)
    assert error.value.code == SOURCE_CHANGED
    # Chỉ lô đầu tiên được gửi — không bao giờ gõ tiếp vào cửa sổ khác.
    assert len(fake.sent_events) == win_input.TEXT_CHUNK_UNITS * 2


def test_type_text_rejects_overlong_text():
    fake = FakePlatform()
    with pytest.raises(PlatformError) as error:
        win_input.type_text("x" * (win_input.MAX_TEXT_CHARS + 1), window=100, platform=fake)
    assert error.value.code == SOURCE_CHANGED


def test_press_key_named_key_with_modifiers():
    fake = FakePlatform(foreground=100)
    result = win_input.press_key("enter", window=100, modifiers=["ctrl"], platform=fake)
    assert result["key"] == "enter"
    decoded = decode_events(fake.sent_events)
    assert [(item["vk"], item["flags"]) for item in decoded] == [
        (0x11, 0),
        (0x0D, 0),
        (0x0D, KEYEVENTF_KEYUP),
        (0x11, KEYEVENTF_KEYUP),
    ]
    assert decoded[0]["vk"] == 0x11 and decoded[1]["vk"] == 0x0D


def test_press_key_rejects_unknown_name_and_modifier():
    fake = FakePlatform()
    with pytest.raises(PlatformError):
        win_input.press_key("frobnicate", window=100, platform=fake)
    with pytest.raises(PlatformError):
        win_input.press_key("a", window=100, modifiers=["hyper"], platform=fake)


# ---------------------------------------------------------------------------
# Thang ba bậc
# ---------------------------------------------------------------------------
class _FakeAccessor(uia.UiaAccessor):
    name = "fake"

    def __init__(self, patterns, bounds=(0, 0, 100, 50)):
        self.patterns = patterns
        self.bounds = bounds
        self.invoked: list[str] = []

    def initialize(self):
        return "mta"

    def element_from_point(self, x, y):
        return "element"

    def build_subtree(self, element):
        return [
            {
                "runtime_id": "42.1",
                "name": "OK",
                "control_type": 50000,
                "control_type_name": "Button",
                "bounds": {
                    "x": self.bounds[0],
                    "y": self.bounds[1],
                    "width": self.bounds[2],
                    "height": self.bounds[3],
                },
                "patterns": list(self.patterns),
                "pid": 1000,
                "payload": {"name": "OK", "patterns": list(self.patterns), "isPassword": False},
                "handle": "element",
            }
        ]

    def invoke(self, handle, pattern):
        self.invoked.append(pattern)
        return True


def test_click_element_prefers_uia_pattern_rung():
    accessor = _FakeAccessor(["Invoke"])
    session = uia.UiaSession(accessor=accessor)
    node = session.snapshot(10, 10)[0]
    fake = FakePlatform()
    result = win_input.click_element(node.token, window=100, platform=fake, session=session)
    assert result["route"] == "uia_pattern"
    assert result["pattern"] == "Invoke"
    assert accessor.invoked == ["Invoke"]
    assert fake.sent_events == []  # không cướp focus, không di con trỏ


def test_click_element_falls_back_to_send_input_without_patterns():
    accessor = _FakeAccessor([], bounds=(100, 200, 60, 40))
    session = uia.UiaSession(accessor=accessor)
    node = session.snapshot(10, 10)[0]
    fake = FakePlatform(foreground=100, point_map={(130, 220): 100})
    result = win_input.click_element(node.token, window=100, platform=fake, session=session)
    assert result["route"] == "send_input"
    assert result["point"] == {"x": 130, "y": 220}
    assert result["elementToken"] == node.token


def test_post_message_rung_is_not_implemented():
    with pytest.raises(PlatformError) as error:
        win_input.post_message_background(100, "WM_LBUTTONDOWN")
    assert error.value.code == POST_MESSAGE_UNSUPPORTED
