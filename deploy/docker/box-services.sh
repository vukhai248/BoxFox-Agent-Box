#!/bin/sh
# ==============================================================================
# box-services — khởi động các dịch vụ lâu dài của box (chạy với user `agent`).
# Được gọi bởi entrypoint lúc boot và bởi `box-power on` khi người dùng bật máy.
# ==============================================================================
set -eu

echo "[box-services] Xvfb :99 (${BOX_SCREEN:-1280x800x24})..."
BOX_SCREEN="${BOX_SCREEN:-1280x800x24}"
Xvfb :99 -screen 0 "$BOX_SCREEN" -nolisten tcp &
sleep 1

echo "[box-services] tty-bridge :7681 (tab Terminal)..."
# LƯU Ý: /usr/bin/python3 HỆ THỐNG — `python3` trong PATH là venv Playwright,
# không thấy gói aiohttp của dist-packages.
/usr/bin/python3 /usr/local/bin/tty-bridge.py >/home/agent/tty-bridge.log 2>&1 &

echo "[box-services] desktop XFCE trên :99..."
dbus-launch --exit-with-session xfce4-session >/home/agent/xfce.log 2>&1 &

echo "[box-services] x11vnc :5900..."
x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -bg -o /home/agent/x11vnc.log

echo "[box-services] websockify :6080..."
BOX_ALLOWED_ORIGINS="${BOX_ALLOWED_ORIGINS:-http://localhost:3100 http://127.0.0.1:3100}"
websockify 6080 localhost:5900 \
  --auth-plugin websockify.auth_plugins.ExpectOrigin \
  --auth-source "$BOX_ALLOWED_ORIGINS" \
  >/home/agent/websockify.log 2>&1 &

echo "[box-services] code-server :8080..."
code-server --bind-addr 0.0.0.0:8080 --auth none \
  --disable-telemetry --disable-update-check \
  --user-data-dir /home/agent/.code-server \
  >/home/agent/code-server.log 2>&1 &

echo "[box-services] tất cả dịch vụ đã khởi động."
