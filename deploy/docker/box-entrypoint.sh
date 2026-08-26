#!/usr/bin/env bash
# ==============================================================================
# Entrypoint của box — khởi động "thân máy" của agent:
#   Xvfb       : màn hình ảo :99 — nơi desktop và các ứng dụng hiển thị
#   XFCE       : môi trường desktop (taskbar, quản lý cửa sổ, icon) — mở khung ④
#                ra là thấy một máy tính bình thường, không phải màn hình đen
#   x11vnc     : server VNC trên :5900 — người dùng xem qua khung ④ (12.3.1)
#   code-server: VS Code bản WEB trên :8080 — editor duy nhất trong box. Giao
#                diện web nhúng thẳng nó vào tab IDE, và trên desktop của box có
#                icon "VS Code (Web)" mở đúng địa chỉ này (không phải gõ tay).
# Chạy với user `agent` (non-root — quy tắc ⑥). Không cần quyền đặc biệt vì
# các port đều > 1024.
# ==============================================================================
set -euo pipefail

# --- CÔNG TẮC MẠNG ②a/②b ------------------------------------------------------
# Entrypoint khởi động với root (compose user: "0") chỉ để: (1) đóng data plane
# mặc định bằng iptables, rồi (2) hạ quyền xuống `agent` cho toàn bộ dịch vụ.
# Tiến trình làm việc cuối cùng chạy non-root — đúng quy tắc ⑥.
if [ "$(id -u)" = "0" ]; then
  # Mặc định mạng của box: BOX_DEFAULT_NETWORK = "off" (quy tắc ②a — an toàn
  # mặc định) hoặc "on". Người dùng bật/tắt tại chỗ bằng nút trên giao diện
  # (endpoint /__box/network của ide-proxy), không cần restart container.
  echo "[box-entrypoint] công tắc mạng: mặc định ${BOX_DEFAULT_NETWORK:-off}..."
  box-firewall "${BOX_DEFAULT_NETWORK:-off}"
  # ide-proxy cần root để phục vụ endpoint bật/tắt iptables cho giao diện.
  python3 /usr/local/bin/ide-proxy.py >/home/agent/ide-proxy.log 2>&1 &
  exec gosu agent "$0" "$@"
fi
# ------------------------------------------------------------------------------

echo "[box-entrypoint] bật màn hình ảo Xvfb :99..."
# Kích thước màn hình đổi được mà không phải build lại image.
BOX_SCREEN="${BOX_SCREEN:-1280x800x24}"
Xvfb :99 -screen 0 "$BOX_SCREEN" -nolisten tcp &
sleep 1

# --- Desktop -----------------------------------------------------------------
# XFCE cần một session D-Bus riêng; `dbus-launch --exit-with-session` gắn vòng
# đời bus vào vòng đời session nên không để lại bus mồ côi khi desktop chết.
# Không `exec` và không chờ: nếu desktop có sập thì x11vnc/websockify vẫn sống,
# người dùng vẫn nhìn được máy (dù chỉ là nền trống) thay vì mất luôn khung ④.
echo "[box-entrypoint] bật desktop XFCE trên :99..."
dbus-launch --exit-with-session xfce4-session \
  >/home/agent/xfce.log 2>&1 &

echo "[box-entrypoint] bật x11vnc :5900 (chỉ-xem theo cấu hình mặc định; -nopw chỉ dùng cho dev local)..."
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -bg -o /home/agent/x11vnc.log

# Quy tắc 12.6 — websockify là kênh GHI (chuột/bàn phím) nên phải kiểm tra
# Origin: nếu không, một trang web bất kỳ mà người dùng đang mở cũng có thể mở
# ws://localhost:6080 và điều khiển box (CSRF qua WebSocket). ExpectOrigin từ
# chối cả request thiếu header Origin, tức là chặn luôn client thô không-phải-trình-duyệt.
# Grammar ExpectOrigin của websockify (Ubuntu 24.04): src.split() = PHÂN TÁCH
# DẤU CÁCH. Đừng đổi sang dấu phẩy — bản đóng gói này không tách phẩy.
BOX_ALLOWED_ORIGINS="${BOX_ALLOWED_ORIGINS:-http://localhost:3100 http://127.0.0.1:3100}"
echo "[box-entrypoint] bật websockify :6080 → localhost:5900 (chỉ nhận Origin: ${BOX_ALLOWED_ORIGINS})..."
websockify 6080 localhost:5900 \
  --auth-plugin websockify.auth_plugins.ExpectOrigin \
  --auth-source "$BOX_ALLOWED_ORIGINS" \
  >/home/agent/websockify.log 2>&1 &

# code-server là editor duy nhất trong box (không có bản Electron nào).
# `--disable-telemetry` và `--disable-update-check`: editor bên trong box không
# được tự mở kết nối ra ngoài. Mọi lối ra internet phải đi qua công tắc mạng
# ②a/②b và giấy phép do Controller cấp (bất biến N1/N3); một editor tự gọi máy
# chủ telemetry là một kênh ra không ai duyệt.
echo "[box-entrypoint] bật code-server :8080..."
code-server --bind-addr 0.0.0.0:8080 --auth none \
  --disable-telemetry --disable-update-check \
  --user-data-dir /home/agent/.code-server \
  >/home/agent/code-server.log 2>&1 &

echo "[box-entrypoint] box sẵn sàng. Giữ container sống."
exec tail -f /dev/null
