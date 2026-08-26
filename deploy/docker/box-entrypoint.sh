#!/usr/bin/env bash
# ==============================================================================
# Entrypoint của box.
# Root chỉ làm 3 việc rồi ở lại giữ PID1:
#   1. công tắc mạng mặc định (②a) — iptables
#   2. ide-proxy (root) — phục vụ /__box/* điều khiển từ giao diện
#   3. box-power on — gosu `agent` khởi động toàn bộ dịch vụ (quy tắc ⑥)
# Toàn bộ dịch vụ dài hạn nằm trong box-services.sh để box-power on/off tái dùng.
# ==============================================================================
set -euo pipefail

if [ "$(id -u)" = "0" ]; then
  # ②a: data plane mặc định ĐÓNG; người dùng bật bằng nút Mạng trên giao diện.
  echo "[box-entrypoint] công tắc mạng: mặc định ${BOX_DEFAULT_NETWORK:-off}..."
  box-firewall "${BOX_DEFAULT_NETWORK:-off}"

  echo "[box-entrypoint] ide-proxy :8081 (/__box/* + /__tty/*)..."
  python3 /usr/local/bin/ide-proxy.py >/home/agent/ide-proxy.log 2>&1 &

  echo "[box-entrypoint] điện máy: ${BOX_DEFAULT_POWER:-on}..."
  box-power "${BOX_DEFAULT_POWER:-on}"

  echo "[box-entrypoint] box sẵn sàng. Giữ container sống."
  exec tail -f /dev/null
fi
