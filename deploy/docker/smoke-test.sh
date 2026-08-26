#!/usr/bin/env bash
# ==============================================================================
# Smoke-test cho agentbox-sandbox — 8 bài kiểm tra, mỗi bài ứng một bằng chứng
# thiết kế trong docs/plan/agent-box-plan.md.
#
# Dùng: bash smoke-test.sh
# Kết quả: in PASS/FAIL từng bài + tổng kết; exit != 0 nếu có FAIL.
#
# Bài số 7 và 8 chính là demo sống CÔNG TẮC MẠNG ②a/②b (mục 7.4.1):
# thất bại mạng khi tắt = ĐÚNG; thành công sau khi connect = công tắc chạy thật.
# ==============================================================================
set -u

CONTAINER="agentbox-box"
PASS=0; FAIL=0

# Git Bash trên Windows (MSYS) tự dịch "/opt/..." thành "C:/Program Files/Git/opt/..."
# khi gọi docker.exe → mọi docker exec có đường dẫn tuyệt đối phải bọc bằng
# sh -c bên trong container + tắt conversion.
DX() { MSYS_NO_PATHCONV=1 docker exec "$CONTAINER" sh -c "$1"; }

ok()   { echo "  ✅ PASS — $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ FAIL — $1"; FAIL=$((FAIL+1)); }
head() { echo ""; echo "== $1 =="; }

# (đã bỏ trap cleanup/INTERNET_NET — công tắc mạng giờ là box-firewall trong
#  container, không còn network connect/disconnect nào cần dọn dẹp)

head "1) Container đang chạy"
[ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER" 2>/dev/null)" = "true" ] \
  && ok "container $CONTAINER running" || bad "chưa chạy? Chạy: docker compose up -d"

head "2) Tiến trình dịch vụ chạy non-root agent (quy tắc ⑥)"
U=$(docker exec "$CONTAINER" ps -o user= -C Xvfb 2>/dev/null)
[ "$U" = "agent" ] \
  && ok "Xvfb/code-server chạy với user agent (entrypoint đã gosu hạ quyền)" \
  || bad "dịch vụ đang chạy với user='$U' (mong đợi 'agent')"

head "3) Màn hình ảo Xvfb :99 đang sống"
docker exec "$CONTAINER" pgrep -f "Xvfb :99" >/dev/null 2>&1 \
  && ok "Xvfb :99 running (1280x800)" || bad "không thấy tiến trình Xvfb"

head "4) VNC lắng nghe :5900 → mở Viewer localhost:5900 sẽ thấy màn hình"
docker exec "$CONTAINER" pgrep x11vnc >/dev/null 2>&1 \
  && ok "x11vnc running" || bad "x11vnc không chạy"

head "5) code-server (VS Code web) :8080"
docker exec "$CONTAINER" pgrep -f code-server >/dev/null 2>&1 \
  && ok "code-server running → http://localhost:8080" || bad "code-server không chạy"

head "6) Chromium ghim phiên bản qua Playwright"
V=$(docker exec "$CONTAINER" playwright --version 2>/dev/null)
CH=$(DX 'ls /opt/ms-playwright 2>/dev/null | grep -i chromium | head -1')
[ -n "$V" ] && [ -n "$CH" ] \
  && ok "$V · browser: $CH" || bad "playwright/chromium thiếu ($V / '$CH')"

head "7) Quy tắc ②a: mạng mặc định TẮT → curl phải THẤT BẠI"
if docker exec "$CONTAINER" curl -m 4 -sI https://example.com >/dev/null 2>&1; then
  bad "curl THÀNH CÔNG khi mạng phải tắt — vi phạm ②a!"
else
  ok "curl thất bại như mong đợi (biên đóng)"
fi

head "8) Công tắc ②b: box-firewall on → curl thành công → off → thất bại lại"
docker exec --user root "$CONTAINER" box-firewall on >/dev/null 2>&1
sleep 1
if docker exec "$CONTAINER" curl -m 6 -sI https://example.com >/dev/null 2>&1; then
  ok "BẬT: data plane mở — có internet"
else
  bad "BẬT rồi mà vẫn không ra mạng — kiểm tra NET_ADMIN/box-firewall"
fi
docker exec --user root "$CONTAINER" box-firewall off >/dev/null 2>&1
sleep 1
docker exec "$CONTAINER" curl -m 4 -sI https://example.com >/dev/null 2>&1 \
  && bad "TẮT rồi mà vẫn ra mạng?" || ok "TẮT: biên đóng lại ngay lập tức"

echo ""
echo "==============================================="
echo "  KẾT QUẢ: $PASS PASS / $FAIL FAIL"
echo "==============================================="
[ "$FAIL" -eq 0 ] || exit 1
