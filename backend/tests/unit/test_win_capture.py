"""Test tầng chụp Windows (H5, §4.2) — chạy trên Linux bằng nền tảng giả."""
from __future__ import annotations

import ctypes
import struct
import sys
import zlib

import pytest
from win_fakes import BLACK, RED, WHITE, FakePlatform, make_window, reset_win_state, solid

from agentbox.sandbox.win import capture
from agentbox.sandbox.win.errors import CAPTURE_FAILED, WINDOW_CLOAKED, WINDOW_MINIMIZED, PlatformError
from agentbox.sandbox.win.windows_platform import (
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
    INPUT,
    KEYBDINPUT,
    MOUSEINPUT,
    POINT,
    PROCESS_PER_MONITOR_DPI_AWARE,
    RECT,
    get_platform,
    set_platform,
)


@pytest.fixture(autouse=True)
def _clean_state():
    reset_win_state()
    yield
    reset_win_state()


# ---------------------------------------------------------------------------
# Import trên Linux + struct
# ---------------------------------------------------------------------------
@pytest.mark.skipif(sys.platform == 'win32', reason='Checks the Linux-only absence of ctypes.WinDLL')
def test_package_imports_without_windll_on_linux():
    # Không có WinDLL trên Linux — gói vẫn phải import được và trả nền tảng giữ chỗ.
    assert hasattr(ctypes, "WinDLL") is False
    platform = get_platform()
    assert platform.name == "unavailable"


def test_set_platform_injects_fake():
    fake = FakePlatform()
    set_platform(fake)
    try:
        assert get_platform() is fake
    finally:
        set_platform(None)


def test_input_struct_is_x64_layout():
    assert ctypes.sizeof(POINT) == 8
    assert ctypes.sizeof(RECT) == 16
    assert ctypes.sizeof(MOUSEINPUT) == 32
    assert ctypes.sizeof(KEYBDINPUT) == 24
    assert ctypes.sizeof(INPUT) == 40
    assert INPUT.type.offset == 0
    assert INPUT.union.offset == 8
    assert MOUSEINPUT.dwExtraInfo.offset == 24


# ---------------------------------------------------------------------------
# DPI
# ---------------------------------------------------------------------------
def test_dpi_awareness_prefers_per_monitor_v2_and_is_one_shot():
    fake = FakePlatform()
    assert capture.set_dpi_awareness(fake) == "per_monitor_v2"
    assert capture.set_dpi_awareness(fake) == "per_monitor_v2"
    assert fake.called("set_process_dpi_awareness_context") == [
        (DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,)
    ]
    assert fake.called("set_process_dpi_awareness_shcore") == []


def test_dpi_awareness_falls_back_to_shcore():
    fake = FakePlatform(dpi_v2=False)
    assert capture.set_dpi_awareness(fake) == "per_monitor"
    assert fake.called("set_process_dpi_awareness_shcore") == [(PROCESS_PER_MONITOR_DPI_AWARE,)]


def test_dpi_awareness_unavailable_is_noted():
    fake = FakePlatform(dpi_v2=False, dpi_shcore=False)
    assert capture.set_dpi_awareness(fake) == "unavailable"
    assert fake.notes == ["dpi_awareness_unavailable"]


# ---------------------------------------------------------------------------
# Khung đen
# ---------------------------------------------------------------------------
def test_mostly_black_boundaries():
    assert capture.is_mostly_black(solid(100, 100, BLACK)) is True
    assert capture.is_mostly_black(b"") is True
    # 10/10000 điểm sáng = 0.999 đen > 0.995 ⇒ vẫn coi là khung đen.
    pixels = bytearray(solid(100, 100, BLACK))
    for index in range(10):
        pixels[index * 4 : index * 4 + 4] = bytes(WHITE)
    assert capture.is_mostly_black(bytes(pixels)) is True
    # 100/10000 điểm sáng = 0.99 đen < 0.995 ⇒ có nội dung.
    pixels = bytearray(solid(100, 100, BLACK))
    for index in range(100):
        pixels[index * 4 : index * 4 + 4] = bytes(WHITE)
    assert capture.is_mostly_black(bytes(pixels)) is False


# ---------------------------------------------------------------------------
# Chuỗi chụp cửa sổ
# ---------------------------------------------------------------------------
def test_window_capture_prefers_render_full_content():
    fake = FakePlatform()
    result = capture.capture_window(100, platform=fake)
    assert result.method == capture.METHOD_PRINT_WINDOW_FULL
    assert [args[2] for args in fake.called("print_window")] == [capture.PW_RENDERFULLCONTENT]
    assert fake.called("bit_blt") == []
    assert result.occluded is False
    assert (result.width, result.height) == (800, 600)


def test_window_capture_falls_back_to_plain_print_window():
    fake = FakePlatform(print_ok={capture.PW_RENDERFULLCONTENT: False})
    result = capture.capture_window(100, platform=fake)
    assert result.method == capture.METHOD_PRINT_WINDOW
    assert [args[2] for args in fake.called("print_window")] == [
        capture.PW_RENDERFULLCONTENT,
        0,
    ]


def test_window_capture_falls_back_to_bitblt_from_window_dc():
    fake = FakePlatform(print_ok={capture.PW_RENDERFULLCONTENT: False, 0: False})
    result = capture.capture_window(100, platform=fake)
    assert result.method == capture.METHOD_BITBLT_WINDOW
    assert fake.called("get_window_dc") == [(100,)]
    assert (100, 2) in fake.called("release_dc")


def test_window_capture_raises_when_all_steps_fail():
    fake = FakePlatform(print_ok={capture.PW_RENDERFULLCONTENT: False, 0: False}, blit_ok=False)
    with pytest.raises(PlatformError) as error:
        capture.capture_window(100, platform=fake)
    assert error.value.code == CAPTURE_FAILED


def test_window_capture_refuses_iconic_and_cloaked():
    iconic = FakePlatform(windows=[make_window(iconic=True)])
    with pytest.raises(PlatformError) as error:
        capture.capture_window(100, platform=iconic)
    assert error.value.code == WINDOW_MINIMIZED

    cloaked = FakePlatform(windows=[make_window(cloaked=True)])
    with pytest.raises(PlatformError) as error:
        capture.capture_window(100, platform=cloaked)
    assert error.value.code == WINDOW_CLOAKED


def test_window_capture_uses_extended_frame_bounds():
    window = make_window(rect=(0, 0, 820, 620), extended_bounds=(10, 40, 800, 600))
    fake = FakePlatform(windows=[window])
    result = capture.capture_window(100, platform=fake)
    assert result.bounds == (10, 40, 790, 560)


# ---------------------------------------------------------------------------
# Chốt chặn khung đen ⇒ chụp lại vùng màn hình
# ---------------------------------------------------------------------------
def test_black_frame_guard_recaptures_screen_region_and_marks_occluded():
    def print_pixels(hwnd, flags, width, height):
        return solid(width, height, BLACK)  # PrintWindow "thành công" nhưng rỗng

    def blit_pixels(src, src_x, src_y, width, height):
        if src == 1:  # desktop DC ⇒ có nội dung thật
            return solid(width, height, RED)
        return solid(width, height, BLACK)

    fake = FakePlatform(print_pixels=print_pixels, blit_pixels=blit_pixels, point_map={(400, 300): 200})
    result = capture.capture_window(100, platform=fake)
    assert result.method == capture.METHOD_BITBLT_SCREEN
    assert result.occluded is True
    assert "black_frame_fallback" in result.notes
    # BitBlt vùng màn hình chạy tại đúng toạ độ vật lý của cửa sổ.
    screen_blits = [args for args in fake.called("bit_blt") if args[5] == 1]
    assert screen_blits == [(12, 0, 0, 800, 600, 1, 0, 0)]
    assert result.pixels[:4] == bytes(RED)


# ---------------------------------------------------------------------------
# Chốt chặn bị che (2/5 điểm)
# ---------------------------------------------------------------------------
def test_occlusion_threshold_is_two_of_five():
    bounds = (0, 0, 800, 600)
    one = FakePlatform(point_map={(2, 2): 200})
    assert capture.occlusion_count(one, 100, bounds) == 1
    assert capture.is_occluded(one, 100, bounds) is False

    two = FakePlatform(point_map={(2, 2): 200, (797, 2): 200})
    assert capture.occlusion_count(two, 100, bounds) == 2
    assert capture.is_occluded(two, 100, bounds) is True


def test_occlusion_points_use_inset_2px():
    assert capture.occlusion_points((0, 0, 800, 600)) == [
        (400, 300),
        (2, 2),
        (797, 2),
        (2, 597),
        (797, 597),
    ]


def test_capture_window_marks_occluded_without_black_frame():
    fake = FakePlatform(point_map={(400, 300): 200, (2, 2): 200})
    result = capture.capture_window(100, platform=fake)
    assert result.method == capture.METHOD_PRINT_WINDOW_FULL
    assert result.occluded is True
    assert "window_occluded" in result.notes


# ---------------------------------------------------------------------------
# Chụp màn hình — toạ độ vật lý, gốc âm
# ---------------------------------------------------------------------------
def test_capture_region_uses_physical_coordinates_with_negative_origin():
    fake = FakePlatform(virtual_screen=(-1920, 0, 3840, 1080))
    result = capture.capture_region(-1920, 0, 3840, 1080, platform=fake)
    assert result.bounds == (-1920, 0, 3840, 1080)
    assert (result.width, result.height) == (3840, 1080)
    assert fake.called("bit_blt")[0][6:8] == (-1920, 0)


def test_capture_screen_covers_virtual_desktop():
    fake = FakePlatform(virtual_screen=(-1920, -200, 3840, 1280))
    result = capture.capture_screen(platform=fake)
    assert (result.width, result.height) == (3840, 1280)
    assert result.bounds[:2] == (-1920, -200)


def test_capture_region_rejects_empty_rect():
    with pytest.raises(PlatformError) as error:
        capture.capture_region(0, 0, 0, 10, platform=FakePlatform())
    assert error.value.code == CAPTURE_FAILED


# ---------------------------------------------------------------------------
# Liệt kê cửa sổ
# ---------------------------------------------------------------------------
def test_list_windows_skips_iconic_cloaked_and_invisible():
    windows = [
        make_window(100, title="visible"),
        make_window(200, title="iconic", iconic=True),
        make_window(300, title="cloaked", cloaked=True),
    ]
    fake = FakePlatform(windows=windows)
    listed = capture.list_windows(fake)
    assert [item["windowId"] for item in listed] == [100]
    assert listed[0]["title"] == "visible"
    assert listed[0]["size"] == {"width": 800, "height": 600}


def test_window_at_point_returns_root_window():
    fake = FakePlatform(point_map={(5, 5): 100})
    window = capture.window_at_point(5, 5, platform=fake)
    assert window is not None and window.hwnd == 100
    assert capture.window_at_point(5000, 5000, platform=fake) is None


# ---------------------------------------------------------------------------
# PNG
# ---------------------------------------------------------------------------
def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks = []
    offset = 8
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length : offset + 12 + length])[0]
        assert crc == zlib.crc32(kind + payload) & 0xFFFFFFFF
        chunks.append((kind, payload))
        offset += 12 + length
    return chunks


def test_encode_png_swaps_bgra_to_rgba():
    pixels = bytes([1, 2, 3, 4]) * 4  # BGRA (1,2,3) × 4 điểm ảnh
    frame = capture.Capture(width=2, height=2, pixels=pixels, method="test")
    data = capture.encode_png(frame)
    chunks = dict(_png_chunks(data))
    width, height, depth, color = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
    assert (width, height, depth, color) == (2, 2, 8, 6)
    raw = zlib.decompress(chunks[b"IDAT"])
    assert raw[0] == 0  # filter byte của hàng đầu
    assert raw[1:5] == bytes([3, 2, 1, 4])  # RGBA sau khi đổi kênh


def test_save_capture_writes_png(tmp_path):
    frame = capture.Capture(width=1, height=1, pixels=bytes(WHITE), method="test")
    path = capture.save_capture(frame, "shot", directory=tmp_path)
    assert path.endswith("shot.png")
    assert open(path, "rb").read(8) == b"\x89PNG\r\n\x1a\n"
    assert capture.capture_directory(tmp_path).name == "captures"


def test_pixel_at_bounds():
    frame = capture.Capture(width=2, height=1, pixels=bytes(WHITE) + bytes(RED), method="test")
    assert capture.pixel_at(frame, 0, 0) == WHITE
    assert capture.pixel_at(frame, 1, 0) == RED
    assert capture.pixel_at(frame, 2, 0) is None
