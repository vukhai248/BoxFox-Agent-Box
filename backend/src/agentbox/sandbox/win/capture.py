"""Chụp màn hình / cửa sổ trên Windows bằng GDI thuần (H5, kế hoạch §4.2).

Không dùng Pillow: PNG được mã hoá bằng ``zlib`` của thư viện chuẩn. Toàn bộ
toạ độ ở đây là **physical pixel** — nếu tiến trình chưa DPI-aware thì Windows
ảo hoá toạ độ và mọi cú bấm sẽ lệch, nên :func:`set_dpi_awareness` phải chạy
trước khi cửa sổ đầu tiên được tạo.

Thứ tự chuỗi chụp cửa sổ (dừng ở bước đầu tiên cho ra pixel):

1. ``PrintWindow(hwnd, dc, PW_RENDERFULLCONTENT=0x2)`` — đường chính, vẽ được cả
   cửa sổ bị che.
2. ``PrintWindow(hwnd, dc, 0)`` — driver cũ không hiểu cờ mới.
3. ``BitBlt`` từ ``GetWindowDC(hwnd)`` — cửa sổ đang hiển thị thật.

Sau đó còn hai chốt chặn, vì kết quả GDI có thể "thành công" mà vẫn vô nghĩa:

* **Khung gần như đen**: ``PrintWindow`` trả về TRUE nhưng nội dung rỗng (cửa sổ
  GPU-composited). >99.5% điểm ảnh đen ⇒ chụp lại bằng vùng màn hình và đánh dấu
  ``occluded``. Không có tín hiệu này thì kết quả BitBlt gây hiểu nhầm im lặng.
* **Bị che**: lấy mẫu ``WindowFromPoint`` tại tâm + 4 góc (lùi vào 2 px); từ 2/5
  điểm thuộc cửa sổ khác ⇒ ``occluded`` (ảnh vẫn đúng, nhưng cú bấm sẽ rơi vào
  cửa sổ khác).
"""
from __future__ import annotations

import os
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .errors import (
    CAPTURE_FAILED,
    WINDOW_CLOAKED,
    WINDOW_MINIMIZED,
    PlatformError,
)
from .windows_platform import (
    DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2,
    PROCESS_PER_MONITOR_DPI_AWARE,
    SRCCOPY,
    PW_RENDERFULLCONTENT,
    WindowInfo,
    WindowsPlatform,
    get_platform,
)

#: Ngưỡng "khung đen" — tỉ lệ điểm ảnh đen mà từ đó coi như GDI không vẽ được gì.
BLACK_FRAME_THRESHOLD = 0.995
#: Số điểm ảnh tối đa lấy mẫu khi kiểm tra khung đen (đủ nhanh trong Python).
BLACK_FRAME_SAMPLE = 50_000
#: Số điểm bị che (trên 5 điểm mẫu) để coi là cửa sổ bị che.
OCCLUSION_THRESHOLD = 2
#: Lùi vào bao nhiêu pixel khi lấy mẫu 4 góc (tránh viền/bóng đổ của DWM).
OCCLUSION_INSET_PX = 2
#: Giới hạn số cửa sổ trả về khi liệt kê (tránh payload phình).
MAX_WINDOWS = 200

METHOD_PRINT_WINDOW_FULL = "print_window_full"
METHOD_PRINT_WINDOW = "print_window"
METHOD_BITBLT_WINDOW = "bitblt_window"
METHOD_BITBLT_SCREEN = "bitblt_screen"

_dpi_state: str | None = None


@dataclass
class Capture:
    """Một khung ảnh BGRA top-down kèm metadata."""

    width: int
    height: int
    pixels: bytes
    method: str
    hwnd: int | None = None
    bounds: tuple[int, int, int, int] | None = None
    dpi: int | None = None
    occluded: bool = False
    notes: list[str] = field(default_factory=list)
    captured_at: float = field(default_factory=time.time)

    @property
    def byte_size(self) -> int:
        return len(self.pixels)

    def to_dict(self) -> dict[str, Any]:
        """Metadata (không kèm pixel) — dùng cho payload API/log."""
        payload: dict[str, Any] = {
            "width": self.width,
            "height": self.height,
            "byteSize": self.byte_size,
            "method": self.method,
            "occluded": self.occluded,
        }
        if self.hwnd is not None:
            payload["windowId"] = self.hwnd
        if self.bounds is not None:
            payload["bounds"] = {
                "x": self.bounds[0],
                "y": self.bounds[1],
                "width": self.bounds[2],
                "height": self.bounds[3],
            }
        if self.dpi is not None:
            payload["dpi"] = self.dpi
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


# ---------------------------------------------------------------------------
# DPI
# ---------------------------------------------------------------------------
def set_dpi_awareness(platform: WindowsPlatform | None = None, *, force: bool = False) -> str:
    """Bật per-monitor-v2 cho tiến trình; trả về chế độ đang áp dụng.

    Chỉ chạy một lần cho mỗi tiến trình (``force=True`` để chạy lại trong test).
    """
    global _dpi_state
    if _dpi_state is not None and not force:
        return _dpi_state
    p = platform or get_platform()
    state = "unavailable"
    if p.set_process_dpi_awareness_context(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
        state = "per_monitor_v2"
    elif p.set_process_dpi_awareness_shcore(PROCESS_PER_MONITOR_DPI_AWARE):
        state = "per_monitor"
    if state == "unavailable":
        p.note("dpi_awareness_unavailable")
    _dpi_state = state
    return state


def dpi_awareness_state() -> str | None:
    return _dpi_state


def reset_dpi_awareness() -> None:
    """Chỉ dùng trong test."""
    global _dpi_state
    _dpi_state = None


# ---------------------------------------------------------------------------
# Hình học màn hình
# ---------------------------------------------------------------------------
def virtual_screen_bounds(platform: WindowsPlatform | None = None) -> tuple[int, int, int, int]:
    p = platform or get_platform()
    return p.virtual_screen_bounds()


def screen_size(platform: WindowsPlatform | None = None) -> tuple[int, int]:
    x, y, width, height = virtual_screen_bounds(platform)
    return width, height


# ---------------------------------------------------------------------------
# Chụp
# ---------------------------------------------------------------------------
def _render_bitmap(
    platform: WindowsPlatform,
    reference_dc: int,
    width: int,
    height: int,
    draw: Callable[[int], bool],
) -> bytes | None:
    """Tạo bitmap tương thích, cho ``draw(mem_dc)`` vẽ vào, rồi đọc ra BGRA."""
    mem_dc = platform.create_compatible_dc(reference_dc)
    if mem_dc is None:
        return None
    bitmap = platform.create_compatible_bitmap(reference_dc, width, height)
    if bitmap is None:
        platform.delete_dc(mem_dc)
        return None
    previous: int | None = None
    try:
        previous = platform.select_object(mem_dc, bitmap)
        if not draw(mem_dc):
            return None
        return platform.read_bitmap_bgra(mem_dc, bitmap, width, height)
    finally:
        if previous is not None:
            platform.select_object(mem_dc, previous)
        platform.delete_object(bitmap)
        platform.delete_dc(mem_dc)


def is_mostly_black(pixels: bytes, threshold: float = BLACK_FRAME_THRESHOLD) -> bool:
    """>``threshold`` điểm ảnh đen (mọi kênh ≤ 8) ⇒ khung vô nghĩa."""
    if not pixels:
        return True
    total = len(pixels) // 4
    if total <= 0:
        return True
    stride = max(1, total // BLACK_FRAME_SAMPLE)
    black = 0
    sampled = 0
    view = memoryview(pixels)
    for index in range(0, total, stride):
        offset = index * 4
        pixel = view[offset : offset + 4]
        if pixel[0] <= 8 and pixel[1] <= 8 and pixel[2] <= 8:
            black += 1
        sampled += 1
    if sampled == 0:
        return True
    return (black / sampled) > threshold


def black_ratio(pixels: bytes) -> float:
    """Tỉ lệ điểm ảnh đen (chỉ để chẩn đoán)."""
    if not pixels:
        return 1.0
    total = len(pixels) // 4
    stride = max(1, total // BLACK_FRAME_SAMPLE)
    black = 0
    sampled = 0
    view = memoryview(pixels)
    for index in range(0, total, stride):
        offset = index * 4
        pixel = view[offset : offset + 4]
        if pixel[0] <= 8 and pixel[1] <= 8 and pixel[2] <= 8:
            black += 1
        sampled += 1
    return black / sampled if sampled else 1.0


def capture_region(
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    platform: WindowsPlatform | None = None,
) -> Capture:
    """BitBlt từ desktop DC tại toạ độ **vật lý** (gốc desktop ảo có thể âm)."""
    p = platform or get_platform()
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise PlatformError(CAPTURE_FAILED, "Vùng chụp rỗng.", width=width, height=height)
    screen_dc = p.get_dc(None)
    if screen_dc is None:
        raise PlatformError(CAPTURE_FAILED, "GetDC(NULL) thất bại.")
    try:
        pixels = _render_bitmap(
            p,
            screen_dc,
            width,
            height,
            lambda mem_dc: p.bit_blt(mem_dc, 0, 0, width, height, screen_dc, int(x), int(y), SRCCOPY),
        )
    finally:
        p.release_dc(None, screen_dc)
    if pixels is None:
        raise PlatformError(CAPTURE_FAILED, "BitBlt vùng màn hình thất bại.", x=x, y=y, width=width, height=height)
    return Capture(
        width=width,
        height=height,
        pixels=pixels,
        method=METHOD_BITBLT_SCREEN,
        bounds=(int(x), int(y), width, height),
    )


def capture_screen(*, platform: WindowsPlatform | None = None) -> Capture:
    """Toàn bộ desktop ảo (mọi màn hình), ở toạ độ vật lý."""
    p = platform or get_platform()
    x, y, width, height = p.virtual_screen_bounds()
    return capture_region(x, y, width, height, platform=p)


def window_bounds(window: WindowInfo) -> tuple[int, int, int, int]:
    """(x, y, w, h) ưu tiên DWMWA_EXTENDED_FRAME_BOUNDS để tránh vệt đen của bóng đổ."""
    return window.bounds


def capture_window(hwnd: int, *, platform: WindowsPlatform | None = None) -> Capture:
    """Chuỗi chụp 3 bước + hai chốt chặn (xem docstring module)."""
    p = platform or get_platform()
    window = p.describe_window(hwnd)
    if window.iconic:
        raise PlatformError(
            WINDOW_MINIMIZED,
            "Cửa sổ đang thu nhỏ — cả PrintWindow lẫn BitBlt đều trả về khung đen.",
            hwnd=hwnd,
        )
    if window.cloaked:
        raise PlatformError(
            WINDOW_CLOAKED,
            "Cửa sổ bị DWM cloak (không còn vẽ trên màn hình).",
            hwnd=hwnd,
        )
    x, y, width, height = window.bounds
    if width <= 0 or height <= 0:
        raise PlatformError(CAPTURE_FAILED, "Cửa sổ có kích thước rỗng.", hwnd=hwnd)
    notes: list[str] = []
    if not p.is_window_visible(hwnd):
        notes.append("window_not_visible")
    screen_dc = p.get_dc(None)
    if screen_dc is None:
        raise PlatformError(CAPTURE_FAILED, "GetDC(NULL) thất bại.")
    try:
        pixels, method = _window_pixels(p, screen_dc, hwnd, width, height)
    finally:
        p.release_dc(None, screen_dc)
    if pixels is None:
        raise PlatformError(CAPTURE_FAILED, "Cả ba bước chụp cửa sổ đều thất bại.", hwnd=hwnd)
    occluded = False
    if is_mostly_black(pixels):
        notes.append("black_frame_fallback")
        try:
            region = capture_region(x, y, width, height, platform=p)
        except PlatformError:
            region = None
        if region is not None:
            pixels = region.pixels
            method = METHOD_BITBLT_SCREEN
            occluded = True
    if not occluded and is_occluded(p, hwnd, (x, y, width, height)):
        notes.append("window_occluded")
        occluded = True
    return Capture(
        width=width,
        height=height,
        pixels=pixels,
        method=method,
        hwnd=hwnd,
        bounds=(x, y, width, height),
        dpi=p.get_dpi_for_window(hwnd),
        occluded=occluded,
        notes=notes,
    )


def _window_pixels(
    p: WindowsPlatform, screen_dc: int, hwnd: int, width: int, height: int
) -> tuple[bytes | None, str]:
    """Ba bước chụp cửa sổ; trả về (pixel, tên phương thức đã dùng)."""
    for flags, method in ((PW_RENDERFULLCONTENT, METHOD_PRINT_WINDOW_FULL), (0, METHOD_PRINT_WINDOW)):
        pixels = _render_bitmap(
            p, screen_dc, width, height, lambda mem_dc, f=flags: p.print_window(hwnd, mem_dc, f)
        )
        if pixels is not None:
            return pixels, method
    window_dc = p.get_window_dc(hwnd)
    if window_dc is None:
        return None, METHOD_BITBLT_WINDOW
    try:
        pixels = _render_bitmap(
            p,
            screen_dc,
            width,
            height,
            lambda mem_dc: p.bit_blt(mem_dc, 0, 0, width, height, window_dc, 0, 0, SRCCOPY),
        )
    finally:
        p.release_dc(hwnd, window_dc)
    return pixels, METHOD_BITBLT_WINDOW


# ---------------------------------------------------------------------------
# Chốt chặn bị che
# ---------------------------------------------------------------------------
def occlusion_points(bounds: tuple[int, int, int, int]) -> list[tuple[int, int]]:
    """Tâm + 4 góc (lùi vào ``OCCLUSION_INSET_PX``) theo toạ độ vật lý."""
    x, y, width, height = bounds
    inset = OCCLUSION_INSET_PX
    left = x + inset
    top = y + inset
    right = x + max(inset, width - 1 - inset)
    bottom = y + max(inset, height - 1 - inset)
    return [(x + width // 2, y + height // 2), (left, top), (right, top), (left, bottom), (right, bottom)]


def occlusion_count(
    platform: WindowsPlatform, hwnd: int, bounds: tuple[int, int, int, int]
) -> int:
    """Số điểm mẫu đang thuộc cửa sổ khác (0..5)."""
    count = 0
    for px, py in occlusion_points(bounds):
        top = platform.window_from_point(px, py)
        if not top:
            continue
        root = platform.get_ancestor_root(top) or top
        if root != hwnd:
            count += 1
    return count


def is_occluded(
    platform: WindowsPlatform, hwnd: int, bounds: tuple[int, int, int, int]
) -> bool:
    return occlusion_count(platform, hwnd, bounds) >= OCCLUSION_THRESHOLD


# ---------------------------------------------------------------------------
# Liệt kê cửa sổ + danh tính cửa sổ tại một điểm
# ---------------------------------------------------------------------------
def list_windows(platform: WindowsPlatform | None = None, *,
                 include_minimized: bool = False) -> list[dict[str, Any]]:
    """Cửa sổ cấp cao nhất đang thực sự vẽ được, theo Z-order từ trên xuống.

    `include_minimized=True` dùng cho đường PHÂN GIẢI đích CUA: một cửa sổ đang thu nhỏ vẫn là đích
    hợp lệ (tầng chụp/tiêm tự đưa nó lên trước). Danh sách cho picker giữ mặc định `False` — người
    dùng chỉ chọn được thứ họ đang nhìn thấy.
    """
    p = platform or get_platform()
    windows: list[dict[str, Any]] = []
    for index, hwnd in enumerate(p.enum_windows()):
        if len(windows) >= MAX_WINDOWS:
            break
        if not p.is_window_visible(hwnd):
            continue
        if p.is_iconic(hwnd) and not include_minimized:
            continue
        if p.is_cloaked(hwnd):
            continue
        try:
            window = p.describe_window(hwnd)
        except PlatformError:
            continue
        x, y, width, height = window.bounds
        if width <= 0 or height <= 0:
            continue
        windows.append(
            {
                "windowId": hwnd,
                "zOrder": index,
                "title": window.title,
                "windowClass": window.class_name,
                "pid": window.pid,
                "processName": window.process_name,
                "position": {"x": x, "y": y},
                "size": {"width": width, "height": height},
                "dpi": p.get_dpi_for_window(hwnd),
            }
        )
    return windows


def window_at_point(
    x: int, y: int, *, platform: WindowsPlatform | None = None
) -> WindowInfo | None:
    """Cửa sổ gốc (top-level) tại điểm, hoặc ``None`` nếu không có."""
    p = platform or get_platform()
    hwnd = p.window_from_point(int(x), int(y))
    if not hwnd:
        return None
    root = p.get_ancestor_root(hwnd) or hwnd
    try:
        return p.describe_window(root)
    except PlatformError:
        return None


# ---------------------------------------------------------------------------
# Neo phiên bản hình học (§4.5) — revision tăng khi cửa sổ đổi vị trí/kích thước/DPI
# ---------------------------------------------------------------------------
_geometry_state: dict[str, dict[str, Any]] = {}
_geometry_lock = threading.Lock()


def window_geometry_fingerprint(window: Any, dpi: int | None = None) -> tuple:
    """Vân tay hình học của cửa sổ: vị trí/kích thước/DPI."""
    x, y, width, height = getattr(window, "bounds", (0, 0, 0, 0))
    return (int(x), int(y), int(width), int(height), None if dpi is None else int(dpi))


def geometry_revision(source_id: str, fingerprint: Any, layout: Any = None) -> int:
    """Revision của ``source_id``; tăng khi hình học cửa sổ hoặc layout trang đổi.

    ``layout`` chỉ có ở nhánh DOM (khung nhìn/dpr). Lần đầu thấy layout thì ghi
    nhận mà không tăng revision, để nhánh UIA (không biết layout) không đẩy
    revision lên một cách giả tạo.
    """
    key = str(source_id)
    with _geometry_lock:
        state = _geometry_state.get(key)
        if state is None:
            _geometry_state[key] = {"window": fingerprint, "layout": layout, "revision": 1}
            return 1
        changed = state["window"] != fingerprint
        if not changed and layout is not None and state["layout"] is not None:
            changed = state["layout"] != layout
        state["window"] = fingerprint
        if layout is not None:
            state["layout"] = layout
        if changed:
            state["revision"] += 1
        return state["revision"]


def current_geometry_revision(source_id: str) -> int | None:
    """Revision đang ghi nhận cho ``source_id`` (``None`` nếu chưa từng soi)."""
    with _geometry_lock:
        current = _geometry_state.get(str(source_id))
        return None if current is None else current["revision"]


def reset_geometry_state() -> None:
    """Chỉ dùng trong test."""
    with _geometry_lock:
        _geometry_state.clear()


# ---------------------------------------------------------------------------
# PNG (thư viện chuẩn, không Pillow)
# ---------------------------------------------------------------------------
def _png_chunk(kind: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + kind
        + payload
        + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
    )


def bgra_to_rgba(pixels: bytes) -> bytes:
    """Đổi kênh BGRA → RGBA (PNG yêu cầu RGBA)."""
    view = bytearray(pixels)
    view[0::4], view[2::4] = view[2::4], view[0::4]
    return bytes(view)


def encode_png(capture: Capture, *, compress_level: int = 6) -> bytes:
    """Mã hoá BGRA thành PNG 8-bit RGBA (filter 0 cho mọi hàng)."""
    if capture.width <= 0 or capture.height <= 0:
        raise PlatformError(CAPTURE_FAILED, "Không thể mã hoá ảnh rỗng.")
    rgba = bgra_to_rgba(capture.pixels)
    stride = capture.width * 4
    rows = bytearray()
    for line in range(capture.height):
        start = line * stride
        rows.append(0)
        rows.extend(rgba[start : start + stride])
    header = struct.pack(">IIBBBBB", capture.width, capture.height, 8, 6, 0, 0, 0)
    body = zlib.compress(bytes(rows), compress_level)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", header)
        + _png_chunk(b"IDAT", body)
        + _png_chunk(b"IEND", b"")
    )


def capture_directory(root: str | os.PathLike[str] | None = None) -> Path:
    """``.generated_artifacts/captures`` — như trong box, ghi đè bằng env."""
    override = os.environ.get("AGENTBOX_ARTIFACT_DIR")
    if root is None and override:
        root = override
    base = Path(root) if root is not None else Path.cwd()
    return base / ".generated_artifacts" / "captures"


def save_capture(
    capture: Capture,
    name: str | None = None,
    *,
    directory: str | os.PathLike[str] | None = None,
) -> str:
    """Ghi PNG và trả về đường dẫn tuyệt đối."""
    target_dir = capture_directory(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    if not name:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(capture.captured_at))
        suffix = f"-{capture.hwnd}" if capture.hwnd is not None else ""
        name = f"capture-{stamp}{suffix}.png"
    if not name.endswith(".png"):
        name = f"{name}.png"
    path = target_dir / name
    path.write_bytes(encode_png(capture))
    return str(path)


def pixel_at(capture: Capture, x: int, y: int) -> tuple[int, int, int, int] | None:
    """(B, G, R, A) tại toạ độ trong ảnh — tiện cho test và chẩn đoán."""
    if not (0 <= x < capture.width and 0 <= y < capture.height):
        return None
    offset = (y * capture.width + x) * 4
    return tuple(capture.pixels[offset : offset + 4])  # type: ignore[return-value]


def iter_pixels(pixels: bytes) -> Iterable[bytes]:
    """Duyệt từng điểm ảnh 4 byte (chỉ dùng cho test nhỏ)."""
    for offset in range(0, len(pixels) - 3, 4):
        yield pixels[offset : offset + 4]
