#!/usr/bin/env python3
"""Vẽ lại `chromium.png` — icon trình duyệt trên desktop của box.

Vì sao có script này thay vì chỉ commit file PNG: PNG là binary, đọc diff không
biết nó là gì và không ai sửa lại được. Script này là "source" của icon; file
PNG cạnh nó chỉ là bản build đã commit để `docker compose build` không cần
ImageMagick.

Logo Chromium gốc chỉ một sắc xanh nhạt — ở cỡ 48px trên nền tối #0f172a nó
nhoè thành khối xám, người dùng không nhận ra là trình duyệt. Bản này là bánh xe
4 màu, tương phản rõ ở cỡ nhỏ.

Chạy lại (cần ImageMagick):
    python3 deploy/docker/assets/icons/make-chromium-icon.py
"""

import math
import pathlib
import subprocess

SIZE = 512          # vẽ lớn rồi thu nhỏ để mép cong không bị răng cưa
RADIUS = 248
OUT_SIZE = 330      # khớp cỡ các icon khác trong assets/icons/
CENTER = SIZE / 2

# 3 múi 120°, ranh giới toả ra ở 30° / 150° / 270° (đo ngược chiều kim đồng hồ
# từ trục x) — chính là bố cục bánh xe quen thuộc: đỏ trên, lục dưới-trái,
# vàng dưới-phải.
SECTORS = [("#EA4335", 30, 150), ("#34A853", 150, 270), ("#FBBC05", 270, 390)]
HUB_COLOR = "#4285F4"


def point(angle_deg: float, radius: float) -> tuple[float, float]:
    # Trục y của ảnh hướng xuống, nên đảo dấu góc.
    phi = -math.radians(angle_deg)
    return CENTER + radius * math.cos(phi), CENTER + radius * math.sin(phi)


def main() -> None:
    here = pathlib.Path(__file__).resolve().parent
    args: list[str] = ["convert", "-size", f"{SIZE}x{SIZE}", "xc:none"]

    for color, start, end in SECTORS:
        x1, y1 = point(start, RADIUS)
        x2, y2 = point(end, RADIUS)
        path = (
            f"M {CENTER},{CENTER} L {x1:.2f},{y1:.2f} "
            f"A {RADIUS},{RADIUS} 0 0,0 {x2:.2f},{y2:.2f} Z"
        )
        args += ["-fill", color, "-stroke", "none", "-draw", f"path '{path}'"]

    # Khe trắng giữa các múi.
    for angle in (30, 150, 270):
        x, y = point(angle, RADIUS)
        args += [
            "-stroke", "white", "-strokewidth", "16",
            "-draw", f"line {CENTER},{CENTER} {x:.2f},{y:.2f}",
        ]

    args += [
        "-stroke", "none", "-fill", "white",
        "-draw", f"circle {CENTER},{CENTER} {CENTER},{CENTER - 104}",
        "-fill", HUB_COLOR,
        "-draw", f"circle {CENTER},{CENTER} {CENTER},{CENTER - 86}",
        "-resize", f"{OUT_SIZE}x{OUT_SIZE}",
        f"PNG32:{here / 'chromium.png'}",
    ]

    subprocess.run(args, check=True)
    print(f"đã ghi {here / 'chromium.png'}")


if __name__ == "__main__":
    main()
