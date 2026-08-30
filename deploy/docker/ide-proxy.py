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

Endpoint điều khiển box (②b, mục 12.3.1):
    GET  /__box/status   → {"network": "on"|"off", "power": ...}  (Origin hợp lệ)
    POST /__box/network  body "on"|"off" → chạy box-firewall (proxy chạy root)
    POST /__box/power    body "on"|"off" → chạy box-power
  network/power LÀ endpoint CẦN QUYỀN: yêu cầu header X-BoxFox-Api-Key khớp
  BOXFOX_API_KEY (shared secret). Origin KHÔNG đủ — ngăn process trong box tự mở mạng.
"""

import hmac
import http.server
import json
import os
from pathlib import Path
import select
import socket
import socketserver
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    import plan_files
except ImportError:
    from . import plan_files

try:
    import capture
except ImportError:
    from . import capture

try:
    import workspace_files
except ImportError:
    from . import workspace_files

try:
    import inspect_element
except ImportError:
    from . import inspect_element

PLAN_ROOT = os.environ.get("PLAN_ROOT", os.environ.get("PLANS_ROOT", "/home/agent/workspace/.plans"))
PLANS_ROOT = PLAN_ROOT


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
POWER_STATE_FILE = "/run/box-power-state"
POWER_BIN = "/usr/local/sbin/box-power"
TTY_UPSTREAM_PORT = 7681   # tty-bridge — tab Terminal (loopback, không publish)

# Shared secret cho nhóm endpoint capture/record (§5.1). Agent backend trên host
# gọi server-to-server (không có Origin) phải gửi header X-BoxFox-Api-Key khớp
# giá trị này mới được phép. Rỗng = chưa cấu hình secret → chỉ Origin của giao
# diện web (:3100) / editor (:8081) được dùng (fail-closed với process lạ trên host).
BOXFOX_API_KEY = os.environ.get("BOXFOX_API_KEY", "")


def read_net_state() -> str:
    try:
        with open(NET_STATE_FILE, encoding="utf-8") as fh:
            state = fh.read().strip()
            return state if state in ("on", "off") else "off"
    except OSError:
        return "off"


def read_power_state() -> str:
    try:
        with open(POWER_STATE_FILE, encoding="utf-8") as fh:
            state = fh.read().strip()
            return state if state in ("on", "off") else "on"
    except OSError:
        return "on"


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

    def _send_cors_preflight(self) -> None:
        self.send_response(204)
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_WS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-BoxFox-Api-Key")
            self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    # ------------------------------------------------------------------
    # Endpoint capture/record (§5) — quyền riêng, tách khỏi /__box còn lại
    # ------------------------------------------------------------------
    _CAPTURE_ENDPOINTS = (
        "/__box/windows",
        "/__box/browser/tabs",
        "/__box/capture",
        "/__box/record/start",
        "/__box/record/stop",
        "/__box/record/status",
        "/__box/inspect-element",
    )

    def _is_capture_endpoint(self) -> bool:
        return self.path in self._CAPTURE_ENDPOINTS

    def _capture_allowed(self) -> bool:
        """Cho phép qua (1) shared-secret header hoặc (2) Origin hợp lệ."""
        if BOXFOX_API_KEY:
            provided = self.headers.get("X-BoxFox-Api-Key", "")
            if hmac.compare_digest(provided, BOXFOX_API_KEY):
                return True
        return self._origin_ok_for_box_api()

    def _secret_ok(self) -> bool:
        """Endpoint CẦN quyền (network/power) chỉ nhận shared-secret — không Origin."""
        if not BOXFOX_API_KEY:
            return False  # fail-closed: chưa cấu hình secret thì không ai tắt/bật được
        provided = self.headers.get("X-BoxFox-Api-Key", "")
        return hmac.compare_digest(provided, BOXFOX_API_KEY)

    def _read_toggle_state(self) -> str | None:
        """Đọc body "on"|"off" an toàn; None nghĩa là request không hợp lệ."""
        raw_length = self.headers.get("Content-Length", "0") or "0"
        try:
            length = int(raw_length)
        except ValueError:
            return None
        if length <= 0 or length > 16:
            return None
        raw = self.rfile.read(length)
        try:
            state = raw.decode("utf-8").strip().lower()
        except UnicodeDecodeError:
            return None
        return state if state in ("on", "off") else None

    def _read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError:
            raise capture._invalid("Content-Length không hợp lệ")
        if length <= 0 or length > 64 * 1024:
            raise capture._invalid("Body JSON rỗng hoặc vượt 64KB")
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise capture._invalid(f"Body không phải JSON hợp lệ: {error}")
        if not isinstance(data, dict):
            raise capture._invalid("Body JSON phải là object")
        return data

    def _handle_capture_api(self) -> None:
        if self.command == "OPTIONS":
            # CORS preflight: trả 204 trước, không cần auth (preflight chưa gửi header bí mật).
            self._send_cors_preflight()
            return
        if not self._capture_allowed():
            self._send_json_cors(403, json.dumps({"error": "Không được phép capture/record"}))
            return

        try:
            if self.path == "/__box/windows":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                    return
                self._send_json_cors(200, json.dumps(capture.dispatch_list_windows(), default=str))
                return

            if self.path == "/__box/browser/tabs":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                    return
                self._send_json_cors(200, json.dumps(capture.dispatch_list_tabs(), default=str))
                return

            if self.path == "/__box/capture":
                if self.command != "POST":
                    self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                    return
                body = self._read_json_body()
                target = body.get("target") or {}
                output = body.get("output", "file")
                if output not in ("file", "base64"):
                    raise capture._invalid("output phải là file hoặc base64")
                self._send_json_cors(200, json.dumps(capture.dispatch_capture(target, output), default=str))
                return

            if self.path == "/__box/record/start":
                if self.command != "POST":
                    self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                    return
                body = self._read_json_body()
                target = body.get("target") or {}
                self._send_json_cors(200, json.dumps(capture.dispatch_record_start(target), default=str))
                return

            if self.path == "/__box/record/stop":
                if self.command != "POST":
                    self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                    return
                body = self._read_json_body()
                recording_id = body.get("recordingId")
                if not recording_id:
                    raise capture._invalid("record/stop cần recordingId")
                self._send_json_cors(200, json.dumps(capture.dispatch_record_stop(str(recording_id)), default=str))
                return

            if self.path == "/__box/record/status":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                    return
                self._send_json_cors(200, json.dumps(capture.dispatch_record_status(), default=str))
                return

            if self.path == "/__box/inspect-element":
                if self.command != "POST":
                    self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                    return
                body = self._read_json_body()
                result = inspect_element.dispatch_inspect_element(body.get("x"), body.get("y"))
                self._send_json_cors(200, json.dumps(result, default=str))
                return

            self._send_json_cors(404, json.dumps({"error": "Not Found"}))
        except capture.CaptureError as error:
            self._send_json_cors(error.status_code, json.dumps({"error": error.public_message}))
        except Exception as error:  # lưới an toàn — không để request capture làm chết thread
            # Không nội suy str(error) — có thể mang debugger URL/đường dẫn nội bộ (§10.2).
            print(f"[ide-proxy] lỗi capture: {error!r}", file=sys.stderr)
            self._send_json_cors(500, json.dumps({"error": "Lỗi nội bộ."}))

    # ------------------------------------------------------------------
    # Endpoint workspace files (§Workspace Files)
    # ------------------------------------------------------------------
    def _is_workspace_endpoint(self) -> bool:
        return self.path.startswith("/__box/files") or self.path.startswith("/__box/file/")

    def _send_stream_response(
        self, status: int, headers: dict[str, str], chunk_iter
    ) -> None:
        """Phản hồi binary (media/download/thumbnail/zip) với CORS phản chiếu; không qua do_one."""

        self.send_response(status)
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_WS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        for key, value in headers.items():
            self.send_header(key, value)
        self.end_headers()
        try:
            for chunk in chunk_iter:
                self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _content_disposition(disposition: str, name: str) -> str:
        """Dựng Content-Disposition an toàn: ASCII fallback + RFC 5987 cho tên Unicode."""

        ascii_name = name.encode("ascii", "ignore").decode("ascii").strip() or "file"
        ascii_name = ascii_name.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
        quoted = urllib.parse.quote(name, safe="")
        return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"

    def _serve_media(self, rel: str, disposition: str) -> None:
        size, mtime, content_type, name = workspace_files.media_stat(rel)
        range_header = self.headers.get("Range")
        try:
            parsed_range = workspace_files.parse_range(range_header, size)
        except workspace_files.WorkspaceRangeNotSatisfiable:
            self._send_stream_response(416, {
                "Content-Type": content_type,
                "Content-Range": f"bytes */{size}",
                "Content-Length": "0",
                "Accept-Ranges": "bytes",
                "Cache-Control": "private, max-age=0, must-revalidate",
            }, iter(()))
            return
        if parsed_range is not None:
            start, end = parsed_range
            status = 206
        else:
            start, end = 0, size - 1
            status = 200
        length = end - start + 1
        headers = {
            "Content-Type": content_type,
            "Content-Length": str(length),
            "Content-Disposition": self._content_disposition(disposition, name),
            "Accept-Ranges": "bytes",
            "Last-Modified": self.date_time_string(mtime),
            "Cache-Control": "private, max-age=0, must-revalidate",
        }
        if status == 206:
            headers["Content-Range"] = f"bytes {start}-{end}/{size}"
        self._send_stream_response(
            status, headers, workspace_files.iter_file_chunks(rel, start, end)
        )

    def _serve_thumbnail(self, rel: str) -> None:
        data = workspace_files.make_thumbnail(rel)
        if data is None:
            self._send_json_cors(404, json.dumps({"error": "Không tạo được thumbnail"}))
            return
        self._send_stream_response(200, {
            "Content-Type": "image/jpeg",
            "Content-Length": str(len(data)),
            "Cache-Control": "private, max-age=3600",
        }, iter([data]))

    def _handle_workspace_api(self) -> None:
        if self.command == "OPTIONS":
            self._send_cors_preflight()
            return
        parsed = urllib.parse.urlsplit(self.path)
        path_only = parsed.path
        try:
            if path_only == "/__box/files":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                if not self._origin_ok_for_box_api():
                    self._send_json_cors(403, json.dumps({"error": "Không được phép truy cập"}))
                    return
                params = urllib.parse.parse_qs(parsed.query)
                rel = params.get("path", [""])[0]
                listing = workspace_files.list_directory(rel)
                self._send_json_cors(200, json.dumps(listing))
                return

            if path_only == "/__box/file/content":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                if not self._origin_ok_for_box_api():
                    self._send_json_cors(403, json.dumps({"error": "Không được phép truy cập"}))
                    return
                params = urllib.parse.parse_qs(parsed.query)
                rel = params.get("path", [""])[0]
                content = workspace_files.read_content(rel)
                self._send_json_cors(200, json.dumps(content))
                return

            if path_only == "/__box/file/media":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                params = urllib.parse.parse_qs(parsed.query)
                rel = params.get("path", [""])[0]
                self._serve_media(rel, "inline")
                return

            if path_only == "/__box/file/thumbnail":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                params = urllib.parse.parse_qs(parsed.query)
                rel = params.get("path", [""])[0]
                self._serve_thumbnail(rel)
                return

            if path_only == "/__box/file/download":
                if self.command != "GET":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                params = urllib.parse.parse_qs(parsed.query)
                rel = params.get("path", [""])[0]
                self._serve_media(rel, "attachment")
                return

            if path_only == "/__box/files/zip":
                if self.command != "POST":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                if not self._origin_ok_for_box_api():
                    self._send_json_cors(403, json.dumps({"error": "Không được phép truy cập"}))
                    return
                body = self._read_json_body()
                paths = body.get("paths")
                data = workspace_files.build_zip(paths)
                self._send_stream_response(200, {
                    "Content-Type": "application/zip",
                    "Content-Disposition": 'attachment; filename="boxfox-workspace.zip"',
                    "Content-Length": str(len(data)),
                    "Cache-Control": "no-store",
                }, iter([data]))
                return

            if path_only == "/__box/file/upload":
                if self.command != "POST":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                if not self._secret_ok():
                    self._send_json_cors(403, json.dumps({"error": "Cần X-BoxFox-Api-Key hợp lệ"}))
                    return
                params = urllib.parse.parse_qs(parsed.query)
                target_dir = params.get("path", [""])[0]
                filename = params.get("name", [""])[0]
                try:
                    size_hint = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    size_hint = 0

                def body_chunks() -> bytes:
                    # Stream từ rfile theo chunk 64 KiB — không nạp cả body vào bộ nhớ.
                    # size_hint đã được write_upload kiểm tra giới hạn trước khi ghi.
                    remaining = size_hint
                    while remaining > 0:
                        chunk = self.rfile.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        remaining -= len(chunk)
                        yield chunk

                result = workspace_files.write_upload(target_dir, filename, body_chunks(), size_hint)
                self._send_json_cors(200, json.dumps(result))
                return

            if path_only == "/__box/file/unzip":
                if self.command != "POST":
                    self._send_json_cors(405, json.dumps({"error": "Phương thức không được phép"}))
                    return
                if not self._secret_ok():
                    self._send_json_cors(403, json.dumps({"error": "Cần X-BoxFox-Api-Key hợp lệ"}))
                    return
                params = urllib.parse.parse_qs(parsed.query)
                rel = params.get("path", [""])[0]
                result = workspace_files.extract_zip(rel)
                self._send_json_cors(200, json.dumps(result))
                return

            self._send_json_cors(404, json.dumps({"error": "Không tìm thấy endpoint."}))
        except workspace_files.WorkspaceFileError as error:
            self._send_json_cors(error.status_code, json.dumps({"error": error.public_message}))
        except capture.CaptureError as error:
            # Body JSON sai (zip) — trả đúng 4xx thay vì rơi vào lưới an toàn 500.
            self._send_json_cors(error.status_code, json.dumps({"error": error.public_message}))
        except Exception as error:  # lưới an toàn cho thread
            # Không đưa `str(error)` ra ngoài — có thể rò đường dẫn/internal; chỉ ghi log.
            print(f"[ide-proxy] lỗi workspace: {error!r}", file=sys.stderr)
            self._send_json_cors(500, json.dumps({"error": "Lỗi nội bộ."}))


    def _handle_box_api(self) -> None:
        if self._is_capture_endpoint():
            self._handle_capture_api()
            return

        # Endpoint workspace files (§Workspace Files) — nhóm đọc/ghi file riêng,
        # đặt ngay sau capture và trước network/power để khối files tự chứa.
        if self._is_workspace_endpoint():
            self._handle_workspace_api()
            return

        # Endpoint điều khiển CẦN quyền (②b / Máy): chỉ nhận shared-secret.
        # Đặt TRƯỚC khối Origin để Origin header (giả mạo được bởi process trong
        # box) không bao giờ đủ điều kiện bật/tắt mạng hay điện.
        if self.path in ("/__box/network", "/__box/power"):
            if self.command == "OPTIONS":
                self._send_cors_preflight()
                return
            if self.command != "POST":
                self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                return
            if not self._secret_ok():
                self._send_json_cors(403, json.dumps({"error": "Cần X-BoxFox-Api-Key hợp lệ"}))
                return
            state = self._read_toggle_state()
            if state is None:
                self._send_json_cors(400, json.dumps({"error": "Body phải là 'on' hoặc 'off'"}))
                return
            if self.path == "/__box/network":
                subprocess.run([FIREWALL_BIN, state], check=False)
                self._send_json_cors(200, json.dumps({"network": read_net_state()}))
            else:
                subprocess.run([POWER_BIN, state], check=False)
                self._send_json_cors(200, json.dumps({"power": read_power_state()}))
            return

        if not self._origin_ok_for_box_api():
            self.send_response(403)
            self.end_headers()
            return
        if self.path == "/__box/status" and self.command == "GET":
            payload = json.dumps(
                {"network": read_net_state(), "power": read_power_state()}
            )
            self._send_json_cors(200, payload)
            return

        parsed = urllib.parse.urlsplit(self.path)
        path_only = parsed.path

        if path_only in ("/__box/plans", "/__box/plans/content"):
            if self.command != "GET":
                self._send_json_cors(405, json.dumps({"error": "Method Not Allowed"}))
                return

        if path_only == "/__box/plans" and self.command == "GET":
            if parsed.query:
                self._send_json_cors(400, json.dumps({"error": "Unexpected query parameters"}))
                return
            try:
                manifest = plan_files.scan_plans(PLAN_ROOT)
                payload = json.dumps(manifest.to_payload())
                self._send_json_cors(200, payload)
            except plan_files.PlanFileError as error:
                self._send_json_cors(error.status_code, json.dumps({"error": error.public_message}))
            return

        if path_only == "/__box/plans/content" and self.command == "GET":
            params = urllib.parse.parse_qs(parsed.query)
            identity = params.get("identity", [""])[0]
            version = params.get("version", [""])[0]
            try:
                document = plan_files.read_plan(PLAN_ROOT, identity, version)
                payload = json.dumps(document.to_payload())
                self._send_json_cors(200, payload)
            except plan_files.PlanFileError as error:
                self._send_json_cors(error.status_code, json.dumps({"error": error.public_message}))
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

    def _relay_websocket(
        self, upstream_port: int = UPSTREAM_PORT, forward_path: str | None = None
    ) -> None:
        if not self._origin_allowed():
            self.send_response(403)
            self.end_headers()
            self.wfile.write(b"ide-proxy: Origin not allowed\n")
            return

        try:
            upstream = socket.create_connection(
                (UPSTREAM_HOST, upstream_port), timeout=30
            )
        except OSError:
            self.send_response(502)
            self.end_headers()
            self.wfile.write(b"ide-proxy: cannot reach code-server\n")
            return

        # Forward NGUYÊN BẢN handshake — kể cả header Host. KHÔNG được ghi đè
        # Host sang 127.0.0.1:8080: code-server từ chối WS khi Origin lệch Host
        # (403 → trình duyệt nhận 1006). Giữ Host gốc = proxy trong suốt.
        lines = [f"{self.command} {forward_path or self.path} HTTP/1.1"]
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
        if self.path.startswith("/__tty/"):
            # Tab Terminal: đường hầm tới tty-bridge (:7681), bỏ prefix /__tty.
            self._relay_websocket(
                upstream_port=TTY_UPSTREAM_PORT,
                forward_path=self.path[len("/__tty"):],
            )
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
        f"[ide-proxy] Box API: GET /__box/status · POST /__box/network|power on|off (cần secret)\n"
        f"[ide-proxy] Capture API: /__box/windows · /__box/browser/tabs · "
        f"/__box/capture · /__box/record/start|stop|status · /__box/inspect-element\n"
        f"[ide-proxy] Workspace API: GET /__box/files · /__box/file/content|media|thumbnail|download · "
        f"POST /__box/files/zip · /__box/file/upload|unzip",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
