"""Tầng nền tảng desktop Linux/X11 của BoxFox — anh em sinh đôi với ``sandbox/win``.

Ba module, cùng trách nhiệm như bản Windows, chỉ khác đường chạm hệ điều hành:

* :mod:`.platform` — ranh giới duy nhất chạm X11 (``xdotool``, ``xprop``, ``xwininfo``): danh sách
  cửa sổ, danh tính/hình học, tiêu điểm, mutex liên tiến trình, mở ứng dụng. Có ``runner`` tiêm được
  nên test chạy không cần X server.
* :mod:`.capture` — ảnh chụp qua ImageMagick ``import``; phần thuần Python (``list_windows``,
  ``occlusion_*``, ``encode_png``, ``Capture``) dùng lại từ ``win.capture``.
* :mod:`.input` — chuột/bàn phím qua XTEST (``xdotool``), giữ nguyên thứ tự bốn chốt chặn.

Cố ý **không** có module hook: X11 không phân biệt được input do agent tiêm với input của người thật,
và một hook luôn báo "người thật" sẽ tự huỷ quyền của agent sau mỗi cú bấm của chính nó.
"""
from __future__ import annotations

from .errors import PlatformError
from .platform import X11Platform, get_platform, reset_platform

__all__ = [
    "PlatformError",
    "X11Platform",
    "get_platform",
    "reset_platform",
]
