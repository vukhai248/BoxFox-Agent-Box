#!/usr/bin/env bash
# ==============================================================================
# BoxFox — bật SearXNG tự host và kiểm tra sẵn sàng (P0b / kế hoạch v1 web search).
#
# Dùng:
#   bash deploy/searxng/up.sh
#   SEARXNG_PORT=8899 bash deploy/searxng/up.sh              # instance thứ hai (tên riêng)
#   BOXFOX_SEARXNG_URL=http://127.0.0.1:8888 bash deploy/searxng/up.sh   # URL cho bước probe
#
# Việc làm: `docker compose up -d` → chờ `/healthz` trả "OK" (tối đa 30 s, dò bằng python3,
# KHÔNG cần curl) → chạy `probe.py` để lấy phán quyết sâu theo từng engine → in URL dùng được
# và các ghi chú cho harness.
# Thất bại (không lên được / không sẵn sàng / probe không kết nối được): in 40 dòng log cuối của
# compose rồi thoát khác 0.
# ==============================================================================
set -eu

DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
COMPOSE="$DIR/docker-compose.yml"
PORT="${SEARXNG_PORT:-8888}"
URL="${BOXFOX_SEARXNG_URL:-http://127.0.0.1:$PORT}"

# Instance thứ hai trên cùng máy: cổng 8888 giữ tên mặc định `boxfox-searxng`; cổng khác dùng
# `boxfox-searxng-<cổng>` để không đụng container mặc định (compose đọc biến này; đặt
# BOXFOX_SEARXNG_CONTAINER để tự chọn tên khác).
if [ "$PORT" != "8888" ] && [ -z "${BOXFOX_SEARXNG_CONTAINER:-}" ]; then
  BOXFOX_SEARXNG_CONTAINER="boxfox-searxng-$PORT"
  export BOXFOX_SEARXNG_CONTAINER
fi
# Export để compose nội suy ĐÚNG cổng này cho cả vế publish lẫn granian, kể cả khi biến được
# đặt mà chưa export ở shell gọi.
export SEARXNG_PORT="$PORT"

logs() {
  docker compose -f "$COMPOSE" logs --tail=40 2>&1 || true
}

echo "[searxng] bật container (cổng $PORT, tên ${BOXFOX_SEARXNG_CONTAINER:-boxfox-searxng})..."
if ! docker compose -f "$COMPOSE" up -d; then
  echo "[searxng] LỖI: 'docker compose up -d' thất bại. 40 dòng log cuối:" >&2
  logs >&2
  exit 1
fi

# Chờ /healthz trả "OK" — dò bằng python3 để không phụ thuộc curl trên máy chủ.
health_ok() {
  python3 - "$1" <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
        status = getattr(response, 'status', 200)
        body = response.read(64).decode('utf-8', 'replace').strip()
except Exception:
    sys.exit(1)
sys.exit(0 if status == 200 and body == 'OK' else 1)
PY
}

HEALTH_URL="http://127.0.0.1:$PORT/healthz"
ready=0
i=1
while [ "$i" -le 30 ]; do
  if health_ok "$HEALTH_URL"; then
    echo "[searxng] sẵn sàng sau ${i}s ($HEALTH_URL = OK)"
    ready=1
    break
  fi
  sleep 1
  i=$((i + 1))
done

if [ "$ready" != "1" ]; then
  echo "[searxng] LỖI: $HEALTH_URL không trả 'OK' trong 30 s. 40 dòng log cuối:" >&2
  logs >&2
  exit 1
fi

# Phán quyết sâu: số kết quả theo từng engine + engine bị chặn/hết giờ. Mã 0/2 = dùng được,
# 3 = không kết nối được.
set +e
python3 "$DIR/probe.py" --url "$URL"
PROBE_CODE=$?
set -e
case "$PROBE_CODE" in
  0 | 2) ;;
  *)
    echo "[searxng] LỖI: probe.py thoát $PROBE_CODE (không kết nối được $URL). 40 dòng log cuối:" >&2
    logs >&2
    exit "$PROBE_CODE"
    ;;
esac

cat <<EOF

[searxng] XONG. URL dùng được: $URL
  * Harness TỰ DÒ địa chỉ 127.0.0.1:8888 — KHÔNG cần đặt BOXFOX_SEARXNG_URL và KHÔNG cần khởi
    động lại harness (tự nhận trong ≤30 s). Tắt tự dò: BOXFOX_SEARXNG_AUTODETECT=off; đổi địa
    chỉ tự dò: BOXFOX_SEARXNG_AUTODETECT_URL.
  * Đường ống tìm 10 bước mặc định BOXFOX_SEARCH_PIPELINE=auto (chỉ chạy khi chưa có cấu hình
    khác và SearXNG sống). Ép bật: =on; tắt hẳn: =off.
  * Xem trạng thái: GET /api/agent/health (khối 'search') hoặc
    python3 deploy/searxng/probe.py --json
EOF
