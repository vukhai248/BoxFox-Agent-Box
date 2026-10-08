"""Chụp màn hình / cửa sổ trên Linux/X11 bằng ImageMagick ``import``.

Vì sao không dùng GDI: ``sandbox/win/capture.py`` là một chuỗi ``PrintWindow``/``BitBlt`` — chỉ có
trên Windows. Ở đây giữ **nguyên hợp đồng** mà tầng trên đã gọi (``capture_screen``,
``capture_window``, ``encode_png``, ``list_windows``, ``Capture``), nên ``host_executor`` không phải
rẽ nhánh theo hệ điều hành.

Phần dùng chung được **tái dùng thẳng** từ ``win.capture`` (thuần Python, không chạm DLL):
``Capture``, ``list_windows``, ``window_at_point``, ``occlusion_count``, ``encode_png``,
``pixel_at``, ``save_capture``. Chỉ hai hàm chạm hệ điều hành được viết lại ở đây.

Ba khác biệt thật so với Windows, không giấu:

* **Không có ``PrintWindow``.** X11 không có cách lấy nội dung một cửa sổ đang bị cửa sổ khác che,
  nên ảnh chụp có thể là thứ đang che nó. Ảnh vẫn được trả về kèm ``occluded=True`` và một dòng
  ``notes`` — tầng trên đã có sẵn ngữ nghĩa đó cho đường ``BitBlt`` của Windows.
* **Ảnh là vùng khách**, không gồm thanh tiêu đề: WM vẽ thanh tiêu đề ở một cửa sổ riêng. Khớp đúng
  ``window.bounds`` nên viền báo và toạ độ bấm vẫn đúng.
* **Chụp là một tiến trình con** (``import`` ~100 ms cho 1920×1080). Cùng bậc với ``PrintWindow``
  trên máy yếu, và không chặn vòng lặp sự kiện vì mọi lời gọi đều chạy trong thread công cụ.
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

from ..win import capture as win_capture
from ..win.errors import CAPTURE_FAILED, WINDOW_MINIMIZED, PlatformError
from . import platform as x11_platform

#: Ảnh chụp bằng ``import`` — cùng bộ hằng với bên Windows để log/so sánh được với nhau.
METHOD_IMPORT_WINDOW = 'import_window'
METHOD_IMPORT_SCREEN = 'import_screen'
METHOD_IMPORT_REGION = 'import_region'

#: Định dạng thô: BGRA 8-bit, đúng thứ tự kênh mà ``encode_png`` chờ.
_RAW_FORMAT = 'bgra:-'

#: ``Capture`` của Windows dùng chung — cùng trường, cùng ``to_dict``.
Capture = win_capture.Capture

#: Những hàm thuần Python của ``win.capture`` không chạm DLL: dùng lại, đừng chép.
BLACK_FRAME_THRESHOLD = win_capture.BLACK_FRAME_THRESHOLD
black_ratio = win_capture.black_ratio
is_mostly_black = win_capture.is_mostly_black
occlusion_points = win_capture.occlusion_points
occlusion_count = win_capture.occlusion_count
is_occluded = win_capture.is_occluded
pixel_at = win_capture.pixel_at
encode_png = win_capture.encode_png
save_capture = win_capture.save_capture
capture_directory = win_capture.capture_directory
window_bounds = win_capture.window_bounds
window_at_point = win_capture.window_at_point


def _platform(platform: Any = None) -> Any:
    """Nền tảng X11 đang dùng; thiếu ⇒ lỗi có mã, không phải ``AttributeError``."""
    chosen = platform if platform is not None else x11_platform.get_platform()
    if chosen is None:
        raise PlatformError(CAPTURE_FAILED, 'máy này không có nền tảng X11 để chụp màn hình.')
    return chosen


# ---------------------------------------------------------------------------
# DPI: X11 không có DPI theo tiến trình — giữ đúng ba hàm để chỗ gọi cũ không đổi
# ---------------------------------------------------------------------------
def set_dpi_awareness(platform: Any = None, *, force: bool = False) -> str:
    """X11 luôn là pixel thật: không cần (và không có) API DPI awareness."""
    return 'not_applicable'


def dpi_awareness_state() -> str:
    return 'not_applicable'


def reset_dpi_awareness() -> None:
    return None


def virtual_screen_bounds(platform: Any = None) -> tuple[int, int, int, int]:
    return _platform(platform).virtual_screen_bounds()


def screen_size(platform: Any = None) -> tuple[int, int]:
    _x, _y, width, height = virtual_screen_bounds(platform)
    return width, height


# ---------------------------------------------------------------------------
# Chụp
# ---------------------------------------------------------------------------
def _import_raw(target: str, *, platform: Any, timeout: float = 10.0) -> bytes:
    """Gọi ``import -window <target> -depth 8 bgra:-`` và trả byte ảnh thô."""
    tool = shutil.which('import') if getattr(platform, '_runner', None) is None else 'import'
    if tool is None:
        raise PlatformError(
            CAPTURE_FAILED,
            'thiếu ImageMagick `import` — cài gói imagemagick để chụp màn hình trên Linux.',
            tool='import',
        )
    # Thứ tự cờ có ý nghĩa: `-depth 8` PHẢI đứng trước `-silent`, nếu không ImageMagick trả
    # 16-bit/kênh (8 byte/điểm ảnh) và ảnh sai gấp đôi kích thước. Đã đo bằng thực nghiệm.
    argv = [tool, '-window', str(target), '-depth', '8', '-silent', _RAW_FORMAT]
    result = platform.run_raw(argv, timeout=timeout)
    if result.code != 0 or not result.raw:
        raise PlatformError(
            CAPTURE_FAILED,
            'không chụp được `%s` bằng ImageMagick: %s' % (target, (result.err or '').strip()[:200]),
            target=str(target),
            exit_code=result.code,      # KHÔNG đặt tên `code`: nó trùng tham số đầu của PlatformError
        )
    return result.raw


def _shot(pixels: bytes, width: int, height: int, method: str, **kwargs: Any) -> Capture:
    if len(pixels) != width * height * 4:
        raise PlatformError(
            CAPTURE_FAILED,
            'kích thước ảnh không khớp: %d byte cho %dx%d' % (len(pixels), width, height),
            expected=width * height * 4,
            got=len(pixels),
        )
    return Capture(width=width, height=height, pixels=pixels, method=method, **kwargs)


def capture_region(x: int, y: int, width: int, height: int, *, platform: Any = None) -> Capture:
    """Chụp một vùng của màn hình ảo (gốc toạ độ là gốc màn hình ảo)."""
    p = _platform(platform)
    left, top = int(x), int(y)
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        raise PlatformError(CAPTURE_FAILED, 'vùng chụp rỗng.', bounds=(left, top, width, height))
    screen_x, screen_y, screen_w, screen_h = p.virtual_screen_bounds()
    # `import -window root` không cắt được: cắt bằng `-crop` để vùng nằm ngoài màn hình bị kẹp lại
    # thay vì trả ảnh sai kích thước.
    clip_left = max(left, screen_x)
    clip_top = max(top, screen_y)
    clip_right = min(left + width, screen_x + screen_w)
    clip_bottom = min(top + height, screen_y + screen_h)
    if clip_right <= clip_left or clip_bottom <= clip_top:
        raise PlatformError(CAPTURE_FAILED, 'vùng chụp nằm ngoài màn hình.',
                            bounds=(left, top, width, height))
    crop_w = clip_right - clip_left
    crop_h = clip_bottom - clip_top
    # Thứ tự cờ có ý nghĩa, đo bằng thực nghiệm trên ImageMagick 6.9.12: `-crop` PHẢI đứng trước
    # `-silent`. Nếu `-silent` đi trước, lệnh trả về NGUYÊN màn hình 1920×1080 (8 294 400 byte) chứ
    # không phải vùng đã cắt — người gọi tưởng vùng rộng 815×483 nên bị lệch ảnh.
    argv = ['import', '-window', 'root', '-depth', '8',
            '-crop', '%dx%d+%d+%d' % (crop_w, crop_h, clip_left - screen_x, clip_top - screen_y),
            '-silent', _RAW_FORMAT]
    tool = shutil.which('import') if getattr(p, '_runner', None) is None else 'import'
    if tool is None:
        raise PlatformError(CAPTURE_FAILED, 'thiếu ImageMagick `import`.', tool='import')
    argv[0] = tool
    result = p.run_raw(argv, timeout=10.0)
    if result.code != 0 or len(result.raw) != crop_w * crop_h * 4:
        raise PlatformError(CAPTURE_FAILED, 'không chụp được vùng màn hình.',
                            bounds=(clip_left, clip_top, crop_w, crop_h))
    return _shot(result.raw, crop_w, crop_h, METHOD_IMPORT_REGION,
                 bounds=(clip_left, clip_top, crop_w, crop_h), dpi=96)


def capture_screen(*, platform: Any = None) -> Capture:
    """Toàn bộ màn hình ảo X11 (mọi output), ở toạ độ vật lý."""
    p = _platform(platform)
    x, y, width, height = p.virtual_screen_bounds()
    if width <= 0 or height <= 0:
        raise PlatformError(CAPTURE_FAILED, 'không đọc được kích thước màn hình X11.')
    pixels = _import_raw('root', platform=p)
    return _shot(pixels, width, height, METHOD_IMPORT_SCREEN, bounds=(x, y, width, height), dpi=96)


def _pixels_are_the_screen(shot: Capture, *, platform: Any, samples: int = 64) -> bool:
    """Ảnh này có phải *những gì đang hiện trên màn hình* tại vùng đó không?

    Trên X server có compositor (XFCE, GNOME, KDE…), ``import -window <id>`` đọc pixmap riêng của
    cửa sổ nên ảnh vẫn đúng **dù cửa sổ bị che** — đo được: cửa sổ bị Chrome phủ vẫn cho 0,006% số
    điểm trùng với ảnh màn hình. Trên X server không compositor, drawable chỉ là vùng framebuffer,
    nên ảnh sẽ là của cửa sổ đang che (trùng khít ảnh màn hình).

    Vì vậy phép thử hình học "có cửa sổ nằm trên" chưa đủ để kết luận ảnh vô nghĩa; phải so điểm ảnh.
    Trả ``True`` khi ảnh *chỉ là* màn hình (tức là không đọc được nội dung riêng của cửa sổ).
    """
    x, y, width, height = shot.bounds
    try:
        region = capture_region(x, y, width, height, platform=platform)
    except PlatformError:
        return True                      # không so được thì giữ kết luận thận trọng
    if (region.width, region.height) != (width, height):
        return True
    total = width * height
    if total <= 0:
        return True
    step = max(1, total // max(1, samples))
    same = 0
    checked = 0
    for index in range(0, total, step):
        offset = index * 4
        checked += 1
        if shot.pixels[offset:offset + 4] == region.pixels[offset:offset + 4]:
            same += 1
    return checked > 0 and (same / checked) >= 0.9


def capture_window(hwnd: int, *, platform: Any = None) -> Capture:
    """Chụp một cửa sổ theo ``windowId``; gắn ``occluded`` khi cửa sổ bị che."""
    p = _platform(platform)
    window = p.describe_window(int(hwnd))
    if window.iconic:
        raise PlatformError(
            WINDOW_MINIMIZED,
            'cửa sổ đang thu nhỏ — X11 không vẽ nội dung của cửa sổ không hiển thị.',
            hwnd=int(hwnd),
        )
    x, y, width, height = window.bounds
    if width <= 0 or height <= 0:
        raise PlatformError(CAPTURE_FAILED, 'cửa sổ có kích thước rỗng.', hwnd=int(hwnd))
    notes: list[str] = []
    if not p.is_window_visible(int(hwnd)):
        notes.append('cửa sổ không ở trạng thái IsViewable — ảnh có thể là nền màn hình')
    occluded = win_capture.is_occluded(p, int(hwnd), (x, y, width, height))

    def _region(note: str) -> Capture:
        """Ảnh dự phòng chụp theo vùng màn hình, nhưng vẫn mang danh tính cửa sổ đích.

        Không có ``hwnd`` thì tầng trên tưởng đây là ảnh cả màn hình và mất liên hệ với cửa sổ
        người dùng đã chọn; ``notes`` nói rõ vì sao ảnh không phải bản đọc riêng của cửa sổ.
        """
        region = capture_region(x, y, width, height, platform=p)
        region.hwnd = int(hwnd)
        region.method = METHOD_IMPORT_REGION
        region.occluded = occluded
        region.notes = list(notes) + [note]
        return region

    try:
        pixels = _import_raw(int(hwnd), platform=p)
        if len(pixels) != width * height * 4:
            # `import` trả kích thước khác (cửa sổ đổi kích thước giữa hai lời gọi, hoặc X server
            # không cho đọc drawable) ⇒ chụp lại đúng vùng đó từ màn hình.
            return _region('ảnh của cửa sổ không khớp hình học — đã chụp lại theo vùng màn hình')
        shot = _shot(pixels, width, height, METHOD_IMPORT_WINDOW, hwnd=int(hwnd),
                     bounds=(x, y, width, height), dpi=96, occluded=occluded)
        if occluded and not _pixels_are_the_screen(shot, platform=p):
            # Compositor đã cho ta pixmap riêng của cửa sổ: ảnh dùng được, chỉ ghi chú lại.
            occluded = False
            shot.occluded = False
            notes.append('cửa sổ có cửa sổ khác nằm trên, nhưng ảnh đọc từ bộ đệm riêng của nó')
    except PlatformError:
        if occluded:
            notes.append('cửa sổ bị che nên không đọc được nội dung riêng của nó')
        return _region('X11 không đọc được drawable của cửa sổ — đã chụp lại theo vùng màn hình')
    if is_mostly_black(shot.pixels):
        # Khung gần như đen: X11 không có cờ "GPU composited" như Windows, nhưng cùng một hiện
        # tượng (cửa sổ chưa vẽ xong / bị che). Chụp lại vùng màn hình để có gì đó dùng được.
        notes.append('khung gần như đen — đã chụp lại theo vùng màn hình')
        try:
            region = capture_region(x, y, width, height, platform=p)
        except PlatformError:
            shot.notes.extend(notes)
            return shot
        region.hwnd = int(hwnd)
        region.occluded = occluded
        region.notes = list(notes)
        return region
    shot.notes.extend(notes)
    return shot


def list_windows(platform: Any = None, *, include_minimized: bool = False) -> list[dict[str, Any]]:
    """Cửa sổ cấp cao nhất để người dùng chọn đích (xem ``win.capture.list_windows``)."""
    return win_capture.list_windows(platform=_platform(platform),
                                    include_minimized=include_minimized)


def capture_time() -> float:
    return time.time()


def artifact_directory(root: str | os.PathLike[str] | None = None) -> Path:
    return win_capture.capture_directory(root)
