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
  # Khởi tạo 7 thư mục nền tảng trong workspace của agent
  WORKSPACE_ROOT="/home/agent/workspace"
  WORKSPACE_DIRS=".generated_artifacts .plans .session-history .skills .trimmed-tool-output .uploaded_artifacts .virtual_views"
  for dir_name in $WORKSPACE_DIRS; do
    target_dir="$WORKSPACE_ROOT/$dir_name"
    if [ ! -d "$target_dir" ]; then
      mkdir -p "$target_dir"
      chmod 0750 "$target_dir"
      chown 1000:1000 "$target_dir"
    fi
  done

  # Nạp các file kế hoạch mẫu vào .plans nếu chưa có
  if [ -d /opt/agentbox/bootstrap-plans ] && [ -d "$WORKSPACE_ROOT/.plans" ]; then
    for plan_file in /opt/agentbox/bootstrap-plans/*.md; do
      if [ -f "$plan_file" ]; then
        dest="$WORKSPACE_ROOT/.plans/$(basename "$plan_file")"
        if [ ! -f "$dest" ]; then
          cp "$plan_file" "$dest"
          chmod 0640 "$dest"
          chown 1000:1000 "$dest"
        fi
      fi
    done
  fi

  # ②a/②b: trạng thái mạng lúc boot lấy từ BOX_DEFAULT_NETWORK (compose đặt "on" từ 02/10/2026 —
  # quyết định chủ máy cho verify_exec); người dùng vẫn bật/tắt được bằng nút Mạng trên giao diện.
  echo "[box-entrypoint] công tắc mạng: mặc định ${BOX_DEFAULT_NETWORK:-off}..."
  box-firewall "${BOX_DEFAULT_NETWORK:-off}"

  echo "[box-entrypoint] ide-proxy :8081 (/__box/* + /__tty/*)..."
  python3 /usr/local/bin/ide-proxy.py >/home/agent/ide-proxy.log 2>&1 &

  # Container vừa khởi động ⇒ CHẮC CHẮN không dịch vụ nào đang chạy. Dấu vết
  # "đang ON" của lần chạy trước còn nằm trong /run (lớp ghi của container, không
  # phải tmpfs) nên sống qua `docker restart`; không xoá thì `box-power on` đọc
  # thấy "on" cũ và bỏ qua việc khởi động — box "ON" mà IDE/Terminal/Machine chết
  # câm (xem khối BUG ở đầu deploy/docker/box-power).
  rm -f /run/box-power-state

  echo "[box-entrypoint] điện máy: ${BOX_DEFAULT_POWER:-on}..."
  box-power "${BOX_DEFAULT_POWER:-on}"

  echo "[box-entrypoint] box sẵn sàng. Giữ container sống."
  exec tail -f /dev/null
fi
