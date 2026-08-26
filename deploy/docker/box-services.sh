#!/bin/sh
# ==============================================================================
# box-services — khởi động các dịch vụ lâu dài của box (chạy với user `agent`).
# Được gọi bởi entrypoint lúc boot và bởi `box-power on` khi người dùng bật máy.
# ==============================================================================
set -eu

# HOME PHẢI đặt tường minh — đây là một cái bẫy có thật, đã đo trong container.
# `box-power on` gọi `gosu agent box-services.sh`, mà gosu KHÔNG đổi HOME: nó
# giữ nguyên HOME của tiến trình gọi, tức `/root` (compose chạy entrypoint với
# `user: "0"`). Hậu quả: `xfconfd` đi tìm cấu hình XFCE ở `/root/.config/...`
# — thư mục agent không có quyền đọc/ghi — nên nó bỏ qua toàn bộ cấu hình giao
# diện trong `/home/agent/.config` và rơi về mặc định (panel trắng, hai thanh,
# icon là ô vuông trống). Đã kiểm chứng: `xfconf-query -l` chỉ thấy các channel
# có file ở `/etc/xdg`, không thấy channel nào của người dùng.
# Đặt cả XDG_CONFIG_HOME cho khỏi phụ thuộc vào việc thư viện nào suy ra từ HOME.
export HOME=/home/agent
export XDG_CONFIG_HOME=/home/agent/.config
export XDG_CACHE_HOME=/home/agent/.cache
export XDG_DATA_HOME=/home/agent/.local/share

echo "[box-services] Xvnc :99 (${BOX_SCREEN:-1280x800x24})..."
# Xvnc (TigerVNC) = X server + VNC server trong MỘT tiến trình, thay cả Xvfb lẫn
# x11vnc. Điểm cốt lõi: RandR của nó mở tới 32768x32768 và nó nhận
# `SetDesktopSize` từ client, nên noVNC xin đổi phân giải cho khớp khung ④ được.
# Xvfb thì `maximum` BẰNG kích thước khởi tạo (đúng một mode) ⇒ đổi phân giải là
# bất khả, chỉ scale ảnh được ⇒ luôn sinh viền đen khi tỉ lệ panel khác 1.6.
#
# BOX_SCREEN theo cú pháp Xvfb là WxHxD, còn Xvnc tách -geometry và -depth.
# Nhận cả hai dạng để không phá cấu hình cũ của ai đang đặt biến này.
BOX_SCREEN="${BOX_SCREEN:-1280x800x24}"
case "$BOX_SCREEN" in
  *x*x*) BOX_GEOMETRY="${BOX_SCREEN%x*}"; BOX_DEPTH="${BOX_SCREEN##*x}" ;;
  *x*)   BOX_GEOMETRY="$BOX_SCREEN";      BOX_DEPTH=24 ;;
  *)     echo "[box-services] BOX_SCREEN='$BOX_SCREEN' không hợp lệ — dùng 1280x800x24" >&2
         BOX_GEOMETRY=1280x800; BOX_DEPTH=24 ;;
esac

# -SecurityTypes None : BẮT BUỘC. Mặc định của Xvnc là TLSVnc,VncAuth → nó đòi
#                       ~/.vnc/passwd rồi tự thoát. Tương đương `x11vnc -nopw`.
# -AcceptSetDesktopSize: cho client đổi phân giải — chính là cơ chế auto-fit.
#                       Mặc định đã bật, truyền tường minh để ai đọc script cũng
#                       thấy đây là hành vi có chủ ý, không phải tình cờ.
# -nolisten tcp       : tắt cổng X11 TCP (:6099), giữ đúng thế phòng thủ của
#                       `Xvfb -nolisten tcp` hôm nay. RFB :5900 không bị ảnh hưởng.
# KHÔNG dùng -localhost: x11vnc hôm nay cũng không dùng, và compose publish
#                       127.0.0.1:5900 để mở được VNC Viewer — thêm cờ này là phá
#                       đường đó (docker-proxy nối vào IP container, không phải
#                       loopback trong container).
Xvnc :99 \
  -geometry "$BOX_GEOMETRY" \
  -depth "$BOX_DEPTH" \
  -rfbport 5900 \
  -SecurityTypes None \
  -AlwaysShared \
  -AcceptSetDesktopSize \
  -desktop "BoxFox Agent Box" \
  -nolisten tcp \
  >/home/agent/xvnc.log 2>&1 &

# Xvnc mất ~1-2s biên dịch xkb. Chờ display SẴN SÀNG THẬT thay vì `sleep 1` mù:
# nếu XFCE khởi động trước khi X server nghe, cả session chết ngay.
i=0
while [ "$i" -lt 50 ]; do
  xset -display :99 q >/dev/null 2>&1 && break
  i=$((i + 1)); sleep 0.2
done

echo "[box-services] tty-bridge :7681 (tab Terminal)..."
# LƯU Ý: /usr/bin/python3 HỆ THỐNG — `python3` trong PATH là venv Playwright,
# không thấy gói aiohttp của dist-packages.
/usr/bin/python3 /usr/local/bin/tty-bridge.py >/home/agent/tty-bridge.log 2>&1 &

echo "[box-services] desktop XFCE trên :99..."
dbus-launch --exit-with-session xfce4-session >/home/agent/xfce.log 2>&1 &

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
