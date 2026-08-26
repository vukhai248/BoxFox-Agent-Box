#!/usr/bin/env python3
"""
Proxy bảo vệ code-server khỏi clickjacking + đường hầm WebSocket.

Vấn đề 1 — clickjacking: code-server (4.97.2) chạy với --auth none, không gửi
header X-Frame-Options hay CSP frame-ancestors. Bất kỳ trang HTTP nào mở trong
trình duyệt của người dùng, nếu tới được cổng này, đều nhúng được editor vào
iframe và dụ người dùng bấm vào terminal trong box.

Cách chữa: proxy chèn header Content-Security-Policy frame-ancestors vào mọi
HTTP response, chỉ cho phép giao diện BoxFox (localhost:3100 / 127.0.0.1:3100)
nhúng. Giống cách websockify kiểm tra Origin cho kênh VNC, chỉ khác: HTTP dùng
frame-ancestors vì không có pha bắt tay như WebSocket.

Vấn đề 2 — WebSocket (fix lỗi 1006): workbench của VS Code web mở kết nối
WebSocket tới cùng origin. Request/response proxy bằng urllib KHÔNG chuyển
được pha "101 Switching Protocols" (sau 101, chính socket TCP biến thành đường
hầm hai chiều). Vì vậy mọi request mang header `Upgrade: websocket` được tách
sang ĐƯỜNG HÀM RAW SOCKET: forward nguyên bản handshake tới upstream, trả lời
nguyên bản về client (kèm cả byte dữ liệu đến liền sau header), rồi relay byte
hai chiều cho đến khi một bên đóng.

Bảo mật kênh hầm: request WebSocket phải mang `Origin` thuộc danh sách được
phép — chặn trang lạ mở ws://localhost:8081 điều khiển box (tương đương
ExpectOrigin của websockify).

Endpoint điều khiển công tắc mạng (②b, mục 12.3.1):
    GET  /__box/status   → {"network": "on"|"off"}
    POST /__box/network  body "on"|"off" → chạy box-firewall (proxy chạy root)
"""

import http.server
import json
import select
import socket
import socketserver
import subprocess
import sys
import urllib.error
import urllib.request


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    """HTTPServer đa luồng — code-server mở nhiều kết nối song song
    (HTML, JS, CSS, WebSocket cho terminal). Đơn luồng sẽ nghẽn."""

    daemon_threads = True
    allow_reuse_address = True


LISTEN_HOST = "0.0.0.0"   # Phải bind 0.0.0.0 vì Docker port mapping (DNAT) đổi
                          # dest IP thành IP của container trên bridge, không
                          # phải 127.0.0.1. Loopback vẫn an toàn vì bản thân
                          # compose map 127.0.0.1:8081:8081 — không ai từ xa
                          # tới được.
LISTEN_PORT = 8081
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 8080

# Header CSP mà code-server tự gửi ra (bản 4.97.2). Ta nối frame-ancestors
# vào chuỗi này thay vì ghi đè, để không làm mất các chỉ thị khác.
CSP_HEADER = "Content-Security-Policy"

# Grammar CSP frame-ancestors phân tách nguồn bằng DẤU CÁCH (khác websockify
# ExpectOrigin của Ubuntu 24.04 vốn tách bằng dấu cách — hai grammar khác nhau,
# đừng nhầm).
ALLOWED_ANCESTORS = (
    "http://localhost:3100 http://127.0.0.1:3100"
)

# Origin được phép MỞ KÊNH WebSocket: ngoài trang cha (:3100) còn gồm origin
# CỦA CHÍNH editor trong iframe (:8081) — workbench nối WS về cùng origin của nó.
ALLOWED_WS_ORIGINS = (
    "http://localhost:3100 http://127.0.0.1:3100 "
    "http://localhost:8081 http://127.0.0.1:8081"
).split()

NET_STATE_FILE = "/run/box-net-state"
FIREWALL_BIN = "/usr/local/sbin/box-firewall"


def read_net_state() -> str:
    try:
        with open(NET_STATE_FILE, encoding="utf-8") as fh:
            state = fh.read().strip()
            return state if state in ("on", "off") else "off"
    except OSError:
        return "off"


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """HTTP thường: forward + chèn CSP. WebSocket: đường hầm raw socket."""

    # ------------------------------------------------------------------
    # Endpoint công tắc mạng ②b (mục 12.3.1)
    # ------------------------------------------------------------------
    def _origin_ok_for_box_api(self) -> bool:
        return self.headers.get("Origin", "") in ALLOWED_WS_ORIGINS

    def _send_json_cors(self, code: int, payload: str) -> None:
        self.send_response(code)
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_WS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload.encode())

    def _handle_box_api(self) -> None:
        if not self._origin_ok_for_box_api():
            self.send_response(403)
            self.end_headers()
            return
        if self.path == "/__box/status" and self.command == "GET":
            self._send_json_cors(200, json.dumps({"network": read_net_state()}))
            return
        if self.path == "/__box/network" and self.command == "POST":
            length = int(self.headers.get("Content-Length", "0"))
            state = self.rfile.read(length).decode(errors="replace").strip().lower()
            if state in ("on", "off"):
                subprocess.run([FIREWALL_BIN, state], check=False)
            self._send_json_cors(200, json.dumps({"network": read_net_state()}))
            return
        self.send_response(404)
        self.end_headers()

    # ------------------------------------------------------------------
    # WebSocket tunneling (fix lỗi 1006)
    # ------------------------------------------------------------------
    def _is_websocket_upgrade(self) -> bool:
        return self.headers.get("Upgrade", "").lower() == "websocket"

    def _origin_allowed(self) -> bool:
        return self.headers.get("Origin", "") in ALLOWED_WS_ORIGINS

    def _relay_websocket(self) -> None:
        if not self._origin_allowed():
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"ide-proxy: Origin not allowed\n")
            return

        try:
            upstream = socket.create_connection(
                (UPSTREAM_HOST, UPSTREAM_PORT), timeout=30
            )
        except OSError:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"ide-proxy: cannot reach code-server\n")
            return

        # Forward NGUYÊN BẢN handshake — kể cả header Host. KHÔNG được ghi đè
        # Host sang 127.0.0.1:8080: code-server từ chối WS khi Origin lệch Host
        # (403 → trình duyệt nhận 1006). Giữ Host gốc = proxy trong suốt.
        lines = [f"{self.command} {self.path} HTTP/1.1"]
        for key, value in self.headers.items():
            lines.append(f"{key}: {value}")
        try:
            upstream.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        except OSError:
            upstream.close()
            return

        # Chuyển tiếp nguyên văn phần handshake phản hồi (101 + headers) —
        # không chèn CSP vào đây: sau 101 không còn khái niệm HTTP header.
        client_sock = self.connection
        handshake = b""
        while b"\r\n\r\n" not in handshake:
            chunk = upstream.recv(65536)
            if not chunk:
                upstream.close()
                self.send_response(502)
                self.end_headers()
                return
            handshake += chunk
        head, _, rest = handshake.partition(b"\r\n\r\n")
        try:
            # QUAN TRỌNG: `rest` là dữ liệu WS đã tới ngay sau header — vứt nó
            # là làm rơi frame đầu tiên của code-server (nguyên nhân 1006).
            client_sock.sendall(head + b"\r\n\r\n" + rest)
        except OSError:
            upstream.close()
            return

        # Vòng lặp relay — mỗi chiều chết thì cả cặp được thu hồi.
        sockets = [client_sock, upstream]
        try:
            while True:
                readable, _, _ = select.select(sockets, [], [])
                for sock in readable:
                    data = sock.recv(65536)
                    if not data:
                        raise ConnectionResetError
                    other = upstream if sock is client_sock else client_sock
                    other.sendall(data)
        except OSError:
            pass
        finally:
            try:
                upstream.close()
            except OSError:
                pass

    # ------------------------------------------------------------------
    # HTTP thường: forward + CSP frame-ancestors
    # ------------------------------------------------------------------
    def do_one(self, method: str) -> None:
        url = f"http://{UPSTREAM_HOST}:{UPSTREAM_PORT}{self.path}"
        body = None
        if method in ("POST", "PUT", "PATCH"):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length else None

        req = urllib.request.Request(url, data=body, method=method)
        for key, value in self.headers.items():
            if key.lower() in ("host",):
                continue
            req.add_header(key, value)

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                self.send_response(resp.status)

                for key, value in resp.headers.items():
                    if key == CSP_HEADER:
                        value = f"{value}; frame-ancestors {ALLOWED_ANCESTORS}"
                    self.send_header(key, value)

                if CSP_HEADER not in resp.headers:
                    self.send_header(
                        CSP_HEADER,
                        f"default-src 'self'; frame-ancestors {ALLOWED_ANCESTORS}",
                    )

                self.end_headers()
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            for key, value in e.headers.items():
                if key == CSP_HEADER:
                    value = f"{value}; frame-ancestors {ALLOWED_ANCESTORS}"
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(e.read())
        except Exception as e:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(f"Proxy error: {e}".encode())

    def _dispatch(self) -> None:
        if self.path.startswith("/__box/"):
            self._handle_box_api()
            return
        if self._is_websocket_upgrade():
            self._relay_websocket()
            return
        self.do_one(self.command)

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PUT(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_OPTIONS(self) -> None:
        self._dispatch()

    def do_HEAD(self) -> None:
        self._dispatch()

    def log_message(self, format, *args):
        """Ghi log ra stderr để docker logs đọc được."""
        sys.stderr.write(f"[ide-proxy] {self.client_address[0]} - {format % args}\n")


def main():
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), ProxyHandler)
    print(
        f"[ide-proxy] Lắng nghe {LISTEN_HOST}:{LISTEN_PORT} → "
        f"{UPSTREAM_HOST}:{UPSTREAM_PORT}\n"
        f"[ide-proxy] frame-ancestors = {ALLOWED_ANCESTORS}\n"
        f"[ide-proxy] WebSocket tunneling: BẬT (fix lỗi 1006)\n"
        f"[ide-proxy] Box API: GET /__box/status · POST /__box/network on|off",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
