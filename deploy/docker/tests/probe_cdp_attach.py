#!/usr/bin/env python3
"""Probe W9: Chrome CDP attach timeout 15000ms — chạy TRONG box bằng user `agent`.

Chạy bằng `/opt/pw-driver/bin/python3` (có Playwright). Không phải unit test.

Mỗi lần attach ghi các mốc thời gian tách lớp (giây, tính từ đầu lần attach):
- `socketOpen`: cổng 9222 nhận TCP;
- `jsonVersion`: `GET /json/version` trả JSON (endpoint HTTP của browser đã sẵn);
- `jsonList`: `GET /json/list` (số target theo type);
- `connectOverCdp`: `connect_over_cdp` xong (timeout probe lớn hơn 15 s để đo thời lượng THẬT);
- `contexts0`: `contexts[0]` có mặt;
- `evaluate[i]`: `p.evaluate('window.name')` trên từng page, mỗi page có trần riêng.
Tổ hợp: số tab mở sẵn, có/không một tab bận CPU (vòng `while` JS), có/không recorder ffmpeg
đang quay, có/không tải CPU, khởi động lạnh (Chromium chưa chạy) hoặc ấm.

Kèm ca `worker`: gọi đúng `worker.py` (`browser_use`), như harness gửi qua `docker exec`, để đo
đường thật end-to-end với bản worker chỉ định (`--worker`). Kết quả gán cho đúng bước; không gán
cho mạng.
"""

from __future__ import annotations

import argparse
import asyncio
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


def port_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9222), timeout=0.2):
            return True
    except OSError:
        return False


def http_json(path: str, timeout: float = 2.0):
    with urllib.request.urlopen(CDP + path, timeout=timeout) as response:
        return json.loads(response.read().decode())


def kill_chromium() -> None:
    subprocess.run(["pkill", "-f", "box-chromium"], check=False)
    subprocess.run(["pkill", "-f", "--", "--remote-debugging-port=9222"], check=False)
    for _ in range(50):
        if not port_open():
            break
        time.sleep(0.1)
    time.sleep(0.5)


def launch_chromium() -> None:
    subprocess.Popen(["box-chromium", "about:blank"], env={**os.environ, "DISPLAY": ":99"},
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def ensure_chromium() -> None:
    if port_open():
        return
    launch_chromium()
    for _ in range(100):
        if port_open():
            break
        time.sleep(0.1)


def start_fixture_server(root: Path) -> subprocess.Popen:
    root.mkdir(parents=True, exist_ok=True)
    (root / "page.html").write_text(
        "<html><head><title>W9 fixture</title></head><body>"
        + "".join(f"<p>đoạn {i} <a href='#'>link {i}</a></p>" for i in range(200))
        + "</body></html>", encoding="utf-8")
    (root / "busy.html").write_text(
        "<html><head><title>W9 busy</title></head><body><script>"
        "setTimeout(() => { const end = Date.now() + (+location.hash.slice(1) || 60000);"
        " while (Date.now() < end) {} }, 200);</script>busy</body></html>", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(FIXTURE_PORT), "--bind", "127.0.0.1"],
                            cwd=str(root), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)
    return proc


def open_tab(url: str) -> None:
    request = urllib.request.Request(CDP + "/json/new?" + url, method="PUT")
    urllib.request.urlopen(request, timeout=10).read()


def close_extra_tabs() -> None:
    try:
        targets = http_json("/json/list")
    except Exception:
        return
    pages = [t for t in targets if t.get("type") == "page"]
    for target in pages[1:]:
        try:
            urllib.request.urlopen(CDP + "/json/close/" + target["id"], timeout=5).read()
        except Exception:
            pass
    time.sleep(0.5)


def start_load(cores: int) -> list[subprocess.Popen]:
    return [subprocess.Popen([sys.executable, "-c", "while True: pass"]) for _ in range(cores)]


def start_recorder() -> subprocess.Popen:
    return subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-framerate", "15",
         "-video_size", "1280x800", "-i", ":99", "-c:v", "libx264", "-preset", "ultrafast",
         "-pix_fmt", "yuv420p", "-t", "600", "/tmp/w9-cdp-probe-recorder.mp4"],
        env={**os.environ, "DISPLAY": ":99"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def attach_once(connect_timeout_ms: int, evaluate_timeout_s: float) -> dict:
    from playwright.async_api import async_playwright
    t0 = time.monotonic()
    marks: dict = {}

    def mark(name):
        marks[name] = round(time.monotonic() - t0, 3)

    while not port_open():
        if time.monotonic() - t0 > 30:
            return {"marks": marks, "error": "SOCKET_NEVER_OPEN"}
        await asyncio.sleep(0.05)
    mark("socketOpen")
    version_error = None
    while True:
        try:
            http_json("/json/version", timeout=1)
            mark("jsonVersion")
            break
        except Exception as exc:
            version_error = f"{type(exc).__name__}: {exc}"
            if time.monotonic() - t0 > 30:
                return {"marks": marks, "error": "JSON_VERSION_NEVER_READY", "detail": version_error}
            await asyncio.sleep(0.1)
    targets = http_json("/json/list", timeout=5)
    mark("jsonList")
    kinds: dict = {}
    for target in targets:
        kinds[target.get("type")] = kinds.get(target.get("type"), 0) + 1
    result = {"marks": marks, "targets": kinds}
    async with async_playwright() as pw:
        try:
            browser = await pw.chromium.connect_over_cdp(CDP, timeout=connect_timeout_ms)
        except Exception as exc:
            mark("connectFailed")
            result["error"] = "CONNECT_OVER_CDP"
            result["detail"] = str(exc)[:600]
            return result
        mark("connectOverCdp")
        result["wouldTimeout15s"] = marks["connectOverCdp"] - marks["jsonList"] > 15.0
        context = browser.contexts[0] if browser.contexts else None
        mark("contexts0")
        evaluations = []
        for page in (context.pages if context else []):
            started = time.monotonic()
            try:
                await asyncio.wait_for(page.evaluate("window.name"), timeout=evaluate_timeout_s)
                status = "ok"
            except asyncio.TimeoutError:
                status = "timeout"
            except Exception as exc:
                status = f"error: {type(exc).__name__}"
            evaluations.append({"url": page.url[:80], "status": status,
                                "sec": round(time.monotonic() - started, 3)})
        mark("evaluateAll")
        result["evaluations"] = evaluations
        await browser.close()  # với connect_over_cdp: chỉ ngắt kết nối, không tắt Chromium
    return result


def run_worker(worker: str, payload: dict, timeout: float = 140.0) -> dict:
    started = time.monotonic()
    try:
        proc = subprocess.run(["/opt/pw-driver/bin/python3", worker], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=timeout,
                              cwd="/home/agent/workspace")
        out = json.loads(proc.stdout or "{}")
    except subprocess.TimeoutExpired:
        out = {"is_error": True, "error": "WORKER_TIMEOUT"}
    except ValueError:
        out = {"is_error": True, "error": "BAD_JSON"}
    error = out.get("error") or ""
    # `worker.py` chỉ trả `is_error` + `error`; mã bước nằm ở đầu chuỗi (`BROWSER_CDP_ATTACH_TIMEOUT: ...`).
    code = out.get("errorCode") or (error.split(":", 1)[0] if error[:1].isupper() and "_" in error.split(":", 1)[0] else None)
    return {"sec": round(time.monotonic() - started, 3), "isError": bool(out.get("is_error")),
            "error": error[:600], "errorCode": code, "title": out.get("title"),
            "attach": out.get("attach"), "url": out.get("url")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="current")
    parser.add_argument("--scenarios", default="cold,warm,tabs20,busy,recorder,load4,busy+recorder+load4")
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--connect-timeout-ms", type=int, default=60000)
    parser.add_argument("--evaluate-timeout", type=float, default=20.0)
    parser.add_argument("--busy-ms", type=int, default=40000)
    parser.add_argument("--worker", default="", help="đường dẫn worker.py; rỗng = bỏ ca worker")
    parser.add_argument("--out")
    args = parser.parse_args()

    fixture = start_fixture_server(Path("/tmp/w9-cdp-fixture"))
    runs = []
    try:
        for scenario in [s for s in args.scenarios.split(",") if s]:
            parts = set(scenario.split("+"))
            for rep in range(args.reps):
                extras: list = []
                recorder = None
                hogs: list = []
                try:
                    if "cold" in parts:
                        kill_chromium()
                        launch_chromium()
                    else:
                        ensure_chromium()
                        for _ in range(100):
                            if port_open():
                                break
                            time.sleep(0.1)
                        time.sleep(1.0)
                        close_extra_tabs()
                    if "tabs20" in parts:
                        for i in range(20):
                            open_tab(f"http://127.0.0.1:{FIXTURE_PORT}/page.html?{i}")
                    if "busy" in parts:
                        open_tab(f"http://127.0.0.1:{FIXTURE_PORT}/busy.html#{args.busy_ms}")
                        time.sleep(1.0)  # để vòng bận bắt đầu (setTimeout 200 ms)
                    if "recorder" in parts:
                        recorder = start_recorder()
                        time.sleep(1.0)
                    for part in parts:
                        if part.startswith("load"):
                            hogs = start_load(int(part[4:]))
                    if args.worker and "worker" in parts:
                        session = f"w9probe{rep:02d}{abs(hash(scenario)) % 10**6:06d}"
                        item = {"kind": "worker", **run_worker(args.worker, {
                            "name": "browser_use", "session": session,
                            "args": {"action": "navigate",
                                     "url": f"http://127.0.0.1:{FIXTURE_PORT}/page.html"}})}
                    else:
                        item = {"kind": "attach", **asyncio.run(
                            attach_once(args.connect_timeout_ms, args.evaluate_timeout))}
                except Exception as exc:
                    item = {"error": f"{type(exc).__name__}: {exc}"}
                finally:
                    for hog in hogs:
                        hog.kill()
                    if recorder is not None:
                        recorder.kill()
                        recorder.wait()
                item.update({"scenario": scenario, "rep": rep})
                runs.append(item)
                print(json.dumps({k: item.get(k) for k in (
                    "scenario", "rep", "kind", "marks", "targets", "error", "sec", "wouldTimeout15s")}),
                      file=sys.stderr, flush=True)
                if "busy" in parts:
                    close_extra_tabs()
    finally:
        fixture.kill()
    out = {"probe": "probe_cdp_attach", "label": args.label, "runs": runs}
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
