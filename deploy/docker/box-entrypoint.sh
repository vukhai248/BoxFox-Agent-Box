#!/usr/bin/env bash
# ==============================================================================
# Entrypoint của box — khởi động "thân máy" của agent:
#   Xvfb       : màn hình ảo :99 (1280x800) — nơi Chromium sẽ hiển thị
#   x11vnc     : server VNC trên :5900 — người dùng xem qua khung ④ (12.3.1)
#   code-server: VS Code web trên :8080 — editor cho người dùng
# Chạy với user `agent` (non-root — quy tắc ⑥). Không cần quyền đặc biệt vì
# các port đều > 1024.
# ==============================================================================
set -euo pipefail

# --- CÔNG TẮC MẠNG ②a/②b ------------------------------------------------------
# Entrypoint khởi động với root (compose user: "0") chỉ để: (1) đóng data plane
# mặc định bằng iptables, rồi (2) hạ quyền xuống `agent` cho toàn bộ dịch vụ.
# Tiến trình làm việc cuối cùng chạy non-root — đúng quy tắc ⑥.
if [ "$(id -u)" = "0" ]; then
  echo "[box-entrypoint] công tắc mạng: mặc định OFF (quy tắc ②a)..."
  box-firewall off
  exec gosu agent "$0" "$@"
fi
# ------------------------------------------------------------------------------

echo "[box-entrypoint] bật màn hình ảo Xvfb :99..."
Xvfb :99 -screen 0 1280x800x24 -nolisten tcp &
sleep 1

echo "[box-entrypoint] bật x11vnc :5900 (chỉ-xem theo cấu hình mặc định; -nopw chỉ dùng cho dev local)..."
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -bg -o /home/agent/x11vnc.log

echo "[box-entrypoint] bật websockify :6080 → localhost:5900 (cầu WebSocket cho noVNC)..."
websockify 6080 localhost:5900 >/home/agent/websockify.log 2>&1 &

echo "[box-entrypoint] bật code-server :8080..."
code-server --bind-addr 0.0.0.0:8080 --auth none \
  --user-data-dir /home/agent/.code-server \
  >/home/agent/code-server.log 2>&1 &

echo "[box-entrypoint] box sẵn sàng. Giữ container sống."
exec tail -f /dev/null
