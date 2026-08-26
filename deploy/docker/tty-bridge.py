#!/usr/bin/env python3
"""
tty-bridge — cầu nối WebSocket ⇄ PTY cho tab Terminal (xterm.js ⇄ bash).

Vì sao Popen + openpty thay vì pty.fork(): fork() trong tiến trình asyncio có
thể nhân bản trạng thái event loop sang shell con và gây chết yểu khó lường.
openpty() + Popen tách bạch: cha giữ master fd, con là tiến trình riêng.

Protocol: server→client = byte thuần (stdout). client→server = byte đầu 0x01
là JSON điều khiển (resize), còn lại = keystrokes. Chạy user `agent` (quy tắc ⑥).
"""
import asyncio
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios

from aiohttp import web, WSMsgType

LISTEN_HOST, LISTEN_PORT = "127.0.0.1", 7681
CWD = "/home/agent/workspace"
SHELL = os.environ.get("SHELL", "/bin/bash")
DEFAULT_ORIGINS = (
    "http://localhost:3100 http://127.0.0.1:3100 "
    "http://localhost:8081 http://127.0.0.1:8081"
)
CTRL_RESIZE = 0x01


def allowed_origins() -> set:
    return set(os.environ.get("BOX_ALLOWED_ORIGINS", DEFAULT_ORIGINS).split())


def set_winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(rows, 2), max(cols, 2), 0, 0))


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    if request.headers.get("Origin", "") not in allowed_origins():
        return web.Response(status=403, text="tty-bridge: Origin not allowed\n")

    ws = web.WebSocketResponse(max_msg_size=1 << 20)
    await ws.prepare(request)

    cwd = CWD if os.path.isdir(CWD) else os.path.expanduser("~")
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [SHELL, "-l"],
        stdin=slave, stdout=slave, stderr=slave,
        cwd=cwd, start_new_session=True,
        env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"},
    )
    os.close(slave)  # cha không cần đầu kia
    set_winsize(master, 80, 24)

    loop = asyncio.get_event_loop()
    dead = asyncio.Event()

    def on_master_read() -> None:
        try:
            data = os.read(master, 65536)
        except OSError:  # EIO = con đã thoát
            dead.set()
            return
        if data:
            asyncio.ensure_future(_safe_send(data))

    async def _safe_send(payload: bytes) -> None:
        try:
            await ws.send_bytes(payload)
        except (ConnectionError, RuntimeError):
            dead.set()

    loop.add_reader(master, on_master_read)

    try:
        async for msg in ws:
            if msg.type not in (WSMsgType.BINARY, WSMsgType.TEXT):
                continue
            data = msg.data if isinstance(msg.data, bytes) else msg.data.encode()
            if data[:1] == bytes([CTRL_RESIZE]):
                try:
                    ctrl = json.loads(data[1:].decode(errors="replace"))
                    if ctrl.get("type") == "resize":
                        set_winsize(master, int(ctrl["cols"]), int(ctrl["rows"]))
                        proc.send_signal(signal.SIGWINCH)
                except (ValueError, KeyError, OSError):
                    pass
            elif data:
                os.write(master, data)
    finally:
        try:
            loop.remove_reader(master)
        except (OSError, ValueError):
            pass
        if proc.poll() is None:
            proc.terminate()
        try:
            proc.wait(timeout=3)
        except Exception:
            proc.kill()
        os.close(master)

    return ws


def main() -> None:
    app = web.Application()
    app.router.add_route("GET", "/{tail:.*}", ws_handler)
    print(
        f"[tty-bridge] {LISTEN_HOST}:{LISTEN_PORT} — shell={SHELL} cwd={CWD}\n"
        f"[tty-bridge] origins={sorted(allowed_origins())}",
        flush=True,
    )
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, print=None)


if __name__ == "__main__":
    main()
