#!/usr/bin/env python3
"""W9 validation trong box: `wait_for_function` có trần thật không, và attach thử lại được không.

Chạy bằng `/opt/pw-driver/bin/python3` (sync Playwright, đúng như `worker.py`). Không phải unit test.
Kịch bản: mở MỘT tab bận JS (busy.html#<ms>) rồi
  1. attach với trần 3 s  -> phải nổ gần đúng 3 s (bounded, không treo tới ~59 s);
  2. attach lại với trần 90 s -> đo thời lượng thật (kỳ vọng ~59 s như probe) và xác nhận thử lại
     sau một lần timeout vẫn dùng được Playwright;
  3. `page.wait_for_function` trên từng trang -> trang bận phải hết trần đúng 3 s, trang thường trả về;
  4. `page.wait_for_function` dạng GHI marker (`window.name = value`) -> đặt được trên trang thường và
     bị chặn có trần trên trang bận.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

CDP = "http://127.0.0.1:9222"
FIXTURE_PORT = 8899
FIXTURE = Path("/tmp/w9-cdp-fixture")


def port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=0.2):
            return True
    except OSError:
        return False


def ensure_fixture() -> None:
    FIXTURE.mkdir(parents=True, exist_ok=True)
    (FIXTURE / "page.html").write_text("<html><head><title>w9 validate</title></head><body>ok</body></html>",
                                       encoding="utf-8")
    (FIXTURE / "busy.html").write_text(
        "<html><head><title>busy</title></head><body><script>"
        "setTimeout(() => { const end = Date.now() + (+location.hash.slice(1) || 60000);"
        " while (Date.now() < end) {} }, 200);</script>busy</body></html>", encoding="utf-8")
    if not _port_open(FIXTURE_PORT):
        subprocess.Popen([sys.executable, "-m", "http.server", str(FIXTURE_PORT), "--bind", "127.0.0.1"],
                         cwd=str(FIXTURE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.5)


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            return True
    except OSError:
        return False


def ensure_chromium() -> None:
    if port_open():
        return
    subprocess.Popen(["box-chromium", "about:blank"], env={**os.environ, "DISPLAY": ":99"},
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    for _ in range(100):
        if port_open():
            break
        time.sleep(0.1)


def open_tab(url: str) -> None:
    urllib.request.urlopen(urllib.request.Request(CDP + "/json/new?" + url, method="PUT"), timeout=10).read()


def main() -> int:
    busy_ms = int(sys.argv[1]) if len(sys.argv) > 1 else 30000
    ensure_fixture()
    ensure_chromium()
    time.sleep(1.0)
    open_tab(f"http://127.0.0.1:{FIXTURE_PORT}/busy.html#{busy_ms}")
    time.sleep(1.5)  # vòng bận đã bắt đầu (setTimeout 200 ms)
    out: dict = {"busyMs": busy_ms, "pagesAtStart": len(json.loads(
        urllib.request.urlopen(CDP + "/json/list", timeout=5).read()))}

    from playwright.sync_api import sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    started = time.monotonic()
    with sync_playwright() as pw:
        # (1) attach có trần ngắn: phải bị cắt đúng lúc, không treo tới hết vòng lặp.
        first = time.monotonic()
        try:
            pw.chromium.connect_over_cdp(CDP, timeout=3000)
            out["shortAttach"] = {"ok": True, "sec": round(time.monotonic() - first, 3)}
        except Exception as exc:  # noqa: BLE001
            out["shortAttach"] = {"ok": False, "sec": round(time.monotonic() - first, 3),
                                  "error": type(exc).__name__ + ": " + str(exc)[:160]}
        # (2) attach lại với trần rộng: thử lại sau timeout có dùng được không, và mất bao lâu.
        second = time.monotonic()
        client = None
        try:
            client = pw.chromium.connect_over_cdp(CDP, timeout=90000)
            out["longAttach"] = {"ok": True, "sec": round(time.monotonic() - second, 3)}
        except Exception as exc:  # noqa: BLE001
            out["longAttach"] = {"ok": False, "sec": round(time.monotonic() - second, 3),
                                 "error": type(exc).__name__ + ": " + str(exc)[:160]}
        # (3)/(4) trần của `wait_for_function` khi ĐỌC và khi GHI marker.
        if client is not None:
            context = client.contexts[0]
            reads, writes = [], []
            for page in context.pages:
                read_started = time.monotonic()
                try:
                    page.wait_for_function("(value) => window.name === value", arg="w9-marker", timeout=3000)
                    status = "ok"
                except PlaywrightTimeoutError:
                    status = "timeout"
                except Exception as exc:  # noqa: BLE001
                    status = type(exc).__name__
                reads.append({"url": page.url[:70], "status": status,
                              "sec": round(time.monotonic() - read_started, 3)})
                write_started = time.monotonic()
                try:
                    page.wait_for_function("(value) => { window.name = value; return true; }",
                                           arg="w9-marker", timeout=3000)
                    status = "ok"
                except PlaywrightTimeoutError:
                    status = "timeout"
                except Exception as exc:  # noqa: BLE001
                    status = type(exc).__name__
                writes.append({"url": page.url[:70], "status": status,
                               "sec": round(time.monotonic() - write_started, 3)})
            out["markerRead"] = reads
            out["markerWrite"] = writes
            # Đọc lại ngay sau khi ghi để xác nhận giá trị THẬT SỰ vào trang.
            for page in context.pages:
                try:
                    value = page.evaluate("window.name")
                except Exception as exc:  # noqa: BLE001
                    value = type(exc).__name__
                out.setdefault("windowNameAfter", []).append({"url": page.url[:70], "name": value})
    out["totalSec"] = round(time.monotonic() - started, 3)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    Path("/tmp/w9-validate.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
