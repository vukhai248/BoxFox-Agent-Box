#!/usr/bin/env python3
"""Probe W9: recorder `moov atom not found` — chạy TRONG box (root, như ide-proxy).

Không phải unit test (pytest không gom file `probe_*`). Probe gọi đúng `capture.record_start`
/ `capture.record_stop` của module chỉ định (`--capture-dir`), nên cùng một probe đo được bản
cũ (image) và bản sửa (copy vào box) mà không đổi argv ffmpeg.

Mỗi lần chạy ghi lại:
- `popenPid` so với PID thật của ffmpeg (`/proc/<pid>/cmdline`, `Uid`) — gosu/env có exec không;
- mọi tín hiệu `record_stop` gửi (thời điểm tương đối), thời gian tới exit, mã thoát;
- `ffprobe` thành công hay lỗi (stderr nguyên văn), kích thước file, kết quả `record_stop`;
- stderr của ffmpeg (bản cũ để DEVNULL nên probe chuyển hướng stderr vào file log; argv giữ nguyên).

Ma trận: tải CPU {0, N lõi bận} × cách dừng {stop sau 3 s, stop sau 60 s, để `-t` tự hết} × lặp.
Thêm ca `hang`: SIGSTOP ffmpeg trước stop để dựng lại chữ ký lỗi (SIGINT không được xử lý → SIGKILL).
Kết quả JSON ra stdout (hoặc `--out`). Không suy luận nguyên nhân trong probe: chỉ đo.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def load_capture(capture_dir: str):
    path = Path(capture_dir) / "capture.py"
    sys.path.insert(0, str(Path(capture_dir)))
    spec = importlib.util.spec_from_file_location("capture", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["capture"] = module
    spec.loader.exec_module(module)
    return module


def proc_identity(pid: int) -> dict:
    info = {"pid": pid}
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        argv = [part.decode(errors="replace") for part in raw.split(b"\0") if part]
        info["argv0"] = argv[0] if argv else None
        info["isFfmpeg"] = bool(argv) and os.path.basename(argv[0]) == "ffmpeg"
        info["hasFragFlags"] = "-movflags" in argv
    except OSError as exc:
        info["error"] = str(exc)
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith(("Uid:", "SigIgn:", "SigCgt:")):
                key, _, value = line.partition(":")
                info[key] = value.split()[0] if key == "Uid" else value.strip()
    except OSError:
        pass
    return info


def sig_caught(mask_hex: str | None, signum: int) -> bool | None:
    if not mask_hex:
        return None
    return bool(int(mask_hex, 16) & (1 << (signum - 1)))


def ffprobe(path: str) -> dict:
    started = time.monotonic()
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=width,height,nb_frames",
         "-of", "json", path],
        capture_output=True, text=True, timeout=30,
    )
    result = {"exitCode": proc.returncode, "stderr": proc.stderr.strip()[:400],
              "elapsedSec": round(time.monotonic() - started, 3)}
    try:
        data = json.loads(proc.stdout or "{}")
        result["duration"] = float((data.get("format") or {}).get("duration") or 0) or None
        streams = data.get("streams") or []
        if streams:
            result["width"] = streams[0].get("width")
            result["height"] = streams[0].get("height")
    except (ValueError, TypeError):
        pass
    result["ok"] = proc.returncode == 0 and bool(result.get("width"))
    return result


def start_load(cores: int) -> list[subprocess.Popen]:
    procs = []
    for _ in range(cores):
        procs.append(subprocess.Popen(
            ["gosu", "agent", "python3", "-c", "while True: pass"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    return procs


def stop_load(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        proc.kill()
    for proc in procs:
        proc.wait()


def patch_stderr_log(capture, log_dir: Path):
    """Bản cũ để stderr=DEVNULL: probe chuyển stderr vào file, GIỮ nguyên argv của `_spawn_ffmpeg`."""
    log_dir.mkdir(parents=True, exist_ok=True)
    if getattr(capture, "FFMPEG_LOG_DIR", None) is not None:
        capture.FFMPEG_LOG_DIR = log_dir  # bản sửa tự ghi log; chỉ đổi thư mục
        return None
    original = capture.subprocess.Popen
    holder = {}

    def popen(argv, *args, **kwargs):
        if "ffmpeg" in argv:
            handle = open(log_dir / f"ffmpeg-{int(time.time() * 1000)}.log", "wb")
            holder["log"] = handle.name
            kwargs["stderr"] = handle
        return original(argv, *args, **kwargs)

    capture.subprocess = type("SubprocessShim", (), {
        **{name: getattr(subprocess, name) for name in dir(subprocess) if not name.startswith("__")},
        "Popen": staticmethod(popen),
    })
    return holder


def run_once(capture, *, mode: str, wait_sec: float, auto_sec: int, session: str, log_dir: Path) -> dict:
    holder = patch_stderr_log(capture, log_dir)
    spec = {"kind": "screen"}
    if mode == "auto":
        spec["maxDurationSec"] = auto_sec
    t0 = time.monotonic()
    started = capture.record_start(spec, session=session)
    record_id = started["recordingId"]
    entry = capture._RECORDS[record_id]
    proc = entry["process"]
    signals: list[dict] = []
    original_send = proc.send_signal

    def send_signal(sig):
        signals.append({"signal": signal.Signals(sig).name, "atSec": round(time.monotonic() - t0, 3)})
        return original_send(sig)

    proc.send_signal = send_signal
    time.sleep(0.5)
    identity = proc_identity(proc.pid)
    identity["sigintCaught"] = sig_caught(identity.get("SigCgt"), signal.SIGINT)
    identity["sigintIgnored"] = sig_caught(identity.get("SigIgn"), signal.SIGINT)
    sleep_for = auto_sec + 3 if mode == "auto" else wait_sec
    time.sleep(max(0.0, sleep_for - 0.5))
    exited_before_stop = proc.poll() is not None
    if mode == "hang":
        # Mô phỏng ffmpeg không xử lý được SIGINT (treo trong I/O X11/encoder): SIGSTOP trước khi
        # stop, nên SIGINT bị giữ chờ và chỉ SIGKILL có tác dụng. Đây là ca dựng lại CHỮ KÝ lỗi,
        # không phải nguyên nhân gốc.
        os.kill(proc.pid, signal.SIGSTOP)
    stop_started = time.monotonic()
    stop_result = None
    stop_error = None
    try:
        stop_result = capture.record_stop(record_id)
    except Exception as exc:  # CaptureError (404 khi `-t` đã tự hết và bị reap) hoặc lỗi khác
        stop_error = {"type": type(exc).__name__, "message": str(exc),
                      "status": getattr(exc, "status_code", None)}
        if mode == "auto":
            capture._reap_finished_records()
            stop_result = capture._FINISHED_RECORDS.get(record_id)
    stop_elapsed = round(time.monotonic() - stop_started, 3)
    log_path = (holder or {}).get("log") or str(log_dir / f"{record_id}.log")
    try:
        log_text = Path(log_path).read_text(errors="replace")[-1200:]
    except OSError:
        log_text = None
    probe = ffprobe(started["path"])
    try:
        size = os.path.getsize(started["path"])
    except OSError:
        size = None
    return {
        "mode": mode,
        "recordingId": record_id,
        "path": started["path"],
        "popenPid": proc.pid,
        "processIdentity": identity,
        "signals": signals,
        "exitedBeforeStop": exited_before_stop,
        "returncode": proc.returncode,
        "killed": proc.returncode == -signal.SIGKILL,
        "stopElapsedSec": stop_elapsed,
        "stopResult": stop_result,
        "stopError": stop_error,
        "ffprobe": probe,
        "sizeBytes": size,
        "ffmpegStderrTail": log_text,
        "oracle": {
            # Mechanism oracle: khi stop báo ok thì file PHẢI probe được; khi file không probe được
            # thì stop KHÔNG được báo ok.
            "honestStop": bool(stop_result and stop_result.get("ok")) == probe["ok"] if mode != "auto"
            else (stop_result is not None and bool(stop_result.get("ok", True)) == probe["ok"]),
            "playable": probe["ok"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", default="/usr/local/bin")
    parser.add_argument("--label", default="current")
    parser.add_argument("--loads", default="0,4", help="danh sách số lõi bận, ví dụ 0,4")
    parser.add_argument("--modes", default="stop3,stop60,auto")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--auto-sec", type=int, default=5)
    parser.add_argument("--out")
    args = parser.parse_args()

    capture = load_capture(args.capture_dir)
    log_dir = Path("/tmp/boxfox-probe-ffmpeg")
    runs = []
    modes = {"stop3": ("stop", 3.0), "stop60": ("stop", 60.0), "auto": ("auto", 0.0),
             "hang": ("hang", 3.0)}
    for load in [int(x) for x in args.loads.split(",") if x != ""]:
        hogs = start_load(load)
        try:
            for mode_name in [m for m in args.modes.split(",") if m]:
                mode, wait_sec = modes[mode_name]
                for rep in range(args.reps):
                    session = f"{abs(hash((args.label, load, mode_name, rep))) % (16 ** 12):012x}"
                    try:
                        item = run_once(capture, mode=mode, wait_sec=wait_sec, auto_sec=args.auto_sec,
                                        session=session, log_dir=log_dir)
                    except Exception as exc:
                        item = {"mode": mode, "error": f"{type(exc).__name__}: {exc}"}
                    item.update({"load": load, "modeName": mode_name, "rep": rep})
                    runs.append(item)
                    print(json.dumps({k: item.get(k) for k in (
                        "load", "modeName", "rep", "returncode", "stopElapsedSec", "sizeBytes",
                        "killed")} | {"ffprobeOk": (item.get("ffprobe") or {}).get("ok"),
                                      "stopOk": (item.get("stopResult") or {}).get("ok")}),
                          file=sys.stderr, flush=True)
        finally:
            stop_load(hogs)
    out = {
        "probe": "probe_recorder",
        "label": args.label,
        "captureDir": args.capture_dir,
        "ffmpegVersion": subprocess.run(["ffmpeg", "-version"], capture_output=True,
                                        text=True).stdout.splitlines()[0],
        "nproc": os.cpu_count(),
        "runs": runs,
        "summary": {
            "total": len(runs),
            "playable": sum(1 for r in runs if (r.get("ffprobe") or {}).get("ok")),
            "killed": sum(1 for r in runs if r.get("killed")),
            "honestStop": sum(1 for r in runs if (r.get("oracle") or {}).get("honestStop")),
            "maxStopSec": max([r.get("stopElapsedSec") or 0 for r in runs] or [0]),
        },
    }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
