#!/usr/bin/env bash
# ==============================================================================
# Smoke-test cho agentbox-sandbox — 9 bài kiểm tra, mỗi bài ứng một bằng chứng
# thiết kế trong docs/plan/agent-box-plan.md.
#
# Dùng: bash smoke-test.sh
# Kết quả: in PASS/FAIL từng bài + tổng kết; exit != 0 nếu có FAIL.
#
# Bài số 7 và 8 chính là demo sống CÔNG TẮC MẠNG ②a/②b (mục 7.4.1):
# thất bại mạng khi tắt = ĐÚNG; thành công sau khi connect = công tắc chạy thật.
#
# Bài số 9 là bằng chứng sống cho AUTO-FIT khung ④: nếu ai đó quay về Xvfb
# (framebuffer cố định) thì bài này đỏ ngay, vì trần RandR tụt về đúng kích
# thước khởi tạo và không đổi được phân giải nữa.
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
U=$(docker exec "$CONTAINER" ps -o user= -C Xvnc 2>/dev/null)
[ "$U" = "agent" ] \
  && ok "Xvnc/code-server chạy với user agent (entrypoint đã gosu hạ quyền)" \
  || bad "dịch vụ đang chạy với user='$U' (mong đợi 'agent')"

head "3) X server Xvnc :99 đang sống (RFB tích hợp)"
if docker exec "$CONTAINER" pgrep -f "Xvnc :99" >/dev/null 2>&1; then
  # Phân giải giờ là BIẾN ĐỘNG (đổi theo khung ④) nên in giá trị đọc được,
  # không khẳng định một hằng số nào.
  CUR=$(DX 'DISPLAY=:99 xrandr 2>/dev/null | head -1')
  ok "Xvnc :99 running — $CUR"
else
  bad "không thấy tiến trình Xvnc"
fi

head "4) VNC lắng nghe :5900 → mở Viewer localhost:5900 sẽ thấy màn hình"
# Không còn tiến trình VNC riêng (Xvnc nói luôn RFB) nên kiểm CỔNG, không kiểm
# tên tiến trình. Đọc /proc/net/tcp vì image không có ss/netstat; 0x170C = 5900.
DX 'grep -qi ":170C" /proc/net/tcp' \
  && ok "Xvnc đang nghe RFB :5900" || bad "không thấy cổng 5900 nào đang nghe"

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

head "9) AUTO-FIT khung ④: desktop đổi được phân giải theo panel"
# (a) Trần RandR đã mở? Xvfb báo "maximum 1280 x 800" (= kích thước khởi tạo),
#     Xvnc báo "maximum 32768 x 32768".
if DX 'DISPLAY=:99 xrandr 2>/dev/null | head -1' | grep -q "maximum 32768 x 32768"; then
  ok "trần RandR mở tới 32768x32768 (Xvfb trước đây chỉ 1280x800)"
else
  bad "trần RandR chưa mở — X server vẫn có framebuffer cố định?"
fi
# (b) Đổi sang một kích thước LẺ rồi đọc lại — số lẻ đúng là thứ mà panel bị kéo
#     sinh ra, và là thứ Xvfb không bao giờ làm được.
#     CẠM BẪY: `xrandr --fb WxH` một mình KHÔNG dùng được (nó đổi screen mà không
#     đổi CRTC → output thành disconnected + BadValue). Phải đi qua
#     --newmode/--addmode/--output --mode.
#     Tên output suy ra từ dòng `connected` chứ không hardcode "VNC-0": nếu
#     TigerVNC đổi tên output, bài này phải nói "không tìm thấy output", không
#     phải nói sai thành "auto-fit hỏng".
OUT=$(DX 'DISPLAY=:99 xrandr 2>/dev/null' | awk '/ connected/{print $1; exit}')
if [ -z "$OUT" ]; then
  bad "không tìm thấy output RandR nào đang connected"
else
  DX "DISPLAY=:99 xrandr --newmode '1173x812' 60 1173 1174 1175 1176 812 813 814 815" >/dev/null 2>&1
  DX "DISPLAY=:99 xrandr --addmode $OUT 1173x812" >/dev/null 2>&1
  DX "DISPLAY=:99 xrandr --output $OUT --mode 1173x812" >/dev/null 2>&1
  if DX 'DISPLAY=:99 xrandr 2>/dev/null | head -1' | grep -q "current 1173 x 812"; then
    ok "đổi phân giải động sang 1173x812 (số lẻ) qua output $OUT"
  else
    bad "không đổi được phân giải sang 1173x812 — auto-fit sẽ không chạy"
  fi
  # (c) Trả lại phân giải khởi động cho gọn.
  #     LƯU Ý: KHÔNG bảo đảm sau bài này phân giải là 1280x800. Nếu đang có một
  #     client noVNC mở tab Machine, chính nó sẽ gửi `SetDesktopSize` theo kích
  #     thước panel và ghi đè ngay — đó là hành vi ĐÚNG của auto-fit, không phải
  #     lỗi. Đừng dùng "current 1280 x 800" làm điều kiện của bài kiểm nào.
  DX "DISPLAY=:99 xrandr --output $OUT --mode 1280x800" >/dev/null 2>&1
fi

head "10) Workspace có đủ thư mục plan và API chỉ-đọc"
WORKSPACE_DIRS='.generated_artifacts .plans .session-history .skills .trimmed-tool-output .uploaded_artifacts .virtual_views'
if DX "for d in $WORKSPACE_DIRS; do [ -d /home/agent/workspace/\$d ] && [ ! -L /home/agent/workspace/\$d ] && [ \"\$(stat -c '%u:%g:%a' /home/agent/workspace/\$d)\" = '1000:1000:750' ] || exit 1; done"; then
  ok "bảy thư mục workspace là thư mục thường của agent:agent với mode 0750"
else
  bad "thiếu thư mục workspace, owner/mode sai hoặc có liên kết tượng trưng"
fi
if DX '[ -z "$(find /home/agent/workspace/.skills /home/agent/workspace/.session-history -mindepth 1 -print -quit)" ]'; then
  ok ".skills và .session-history vẫn rỗng"
else
  bad ".skills hoặc .session-history có dữ liệu được seed ngoài ý muốn"
fi
if DX '[ "$(find /home/agent/workspace/.plans -maxdepth 1 -type f -printf "%f\\n" | sort)" = "v1-plan-browser-demo.md" ]'; then
  ok ".plans mới chỉ có đúng plan khởi đầu"
else
  bad ".plans không chỉ có plan khởi đầu trên volume fresh"
fi
if docker exec "$CONTAINER" python3 - <<'PY'
import json
import urllib.request

request = urllib.request.Request(
    "http://127.0.0.1:8081/__box/plans",
    headers={"Origin": "http://localhost:3100"},
)
with urllib.request.urlopen(request) as response:
    assert response.headers["Cache-Control"] == "no-store"
    plans = json.load(response)["plans"]
assert plans == [
    {
        "identity": "plan-browser-demo",
        "relativeDirectory": "",
        "slug": "plan-browser-demo",
        "versions": [plans[0]["versions"][0]],
    }
]
request = urllib.request.Request(
    "http://127.0.0.1:8081/__box/plans/content?identity=plan-browser-demo&version=1",
    headers={"Origin": "http://localhost:3100"},
)
with urllib.request.urlopen(request) as response:
    content = json.load(response)
assert "# Kế hoạch kiểm chứng trình duyệt plan" in content["markdown"]
PY
then
  ok "API plan tìm và đọc được plan khởi đầu thật"
else
  bad "API plan không trả đúng plan khởi đầu"
fi

head "11) Nhiều phiên bản, summary và file sai quy tắc"
if docker exec --user agent "$CONTAINER" sh -eu -c '
  cp /opt/agentbox/test-fixtures/plans/v2-plan-browser-demo.md /home/agent/workspace/.plans/
  printf "%s\\n" "# Tóm tắt" > /home/agent/workspace/.plans/v3-plan-browser-demo-summary.md
  printf "%s\\n" "# Sai" > /home/agent/workspace/.plans/v01-plan-browser-demo.md
' \
  && docker exec "$CONTAINER" python3 - <<'PY'
import json
import urllib.request

headers = {"Origin": "http://localhost:3100"}
with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8081/__box/plans", headers=headers)) as response:
    manifest = json.load(response)
assert manifest["ignoredCount"] == 1, manifest
assert len(manifest["warnings"]) == 1, manifest
plan = manifest["plans"][0]
assert plan["identity"] == "plan-browser-demo", plan
assert [(item["version"], item["label"], item["status"]) for item in plan["versions"]] == [
    (2, "v2", "draft"),
    (1, "v1", "approved"),
], plan
with urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8081/__box/plans/content?identity=plan-browser-demo&version=2", headers=headers)) as response:
    content = json.load(response)
assert content["label"] == "v2", content
assert "phiên bản 2" in content["markdown"], content
PY
  && docker exec --user agent "$CONTAINER" sh -eu -c '
    rm /home/agent/workspace/.plans/v2-plan-browser-demo.md
    rm /home/agent/workspace/.plans/v3-plan-browser-demo-summary.md
    rm /home/agent/workspace/.plans/v01-plan-browser-demo.md
    test "$(find /home/agent/workspace/.plans -maxdepth 1 -type f -printf "%f\\n" | sort)" = "v1-plan-browser-demo.md"
  '; then
  ok "API gom/sắp version đúng, bỏ summary bình thường và cleanup chỉ giữ v1"
else
  bad "API plan không xử lý đúng version, summary, file sai quy tắc hoặc cleanup"
fi

if [ "${SMOKE_TEST_PERSISTENCE:-0}" = "1" ]; then
  head "12) Restart giữ marker và không seed lại plan đã xóa"
  if docker exec --user agent "$CONTAINER" sh -c 'touch /home/agent/workspace/.generated_artifacts/smoke-marker && rm /home/agent/workspace/.plans/v1-plan-browser-demo.md' \
    && docker restart "$CONTAINER" >/dev/null \
    && sleep 3 \
    && DX '[ -f /home/agent/workspace/.generated_artifacts/smoke-marker ] && [ ! -e /home/agent/workspace/.plans/v1-plan-browser-demo.md ]'; then
    ok "restart giữ dữ liệu người dùng và tôn trọng plan bị xóa"
  else
    bad "restart làm mất marker hoặc seed lại plan đã xóa"
  fi
else
  echo "  BỎ QUA — đặt SMOKE_TEST_PERSISTENCE=1 trên volume test riêng để kiểm persistence phá hủy."
fi

echo ""
echo "==============================================="
echo "  KẾT QUẢ: $PASS PASS / $FAIL FAIL"
echo "==============================================="
[ "$FAIL" -eq 0 ] || exit 1
