# 🤝 HANDOFF — BoxFox Agent Box

> **Tài liệu bàn giao công việc.** Đọc xong file này là đủ ngữ cảnh để làm việc,
> không cần hỏi lại ai. Thiết kế chi tiết nằm ở `docs/plan/agent-box-plan.md`
> (16 phần, tiếng Việt) — các mục liên quan được trích dẫn sẵn dưới đây.

---

## 1. Dự án là gì (30 giây)

**AI Computer tự host**: agent LLM làm việc bên trong một container Docker ("chiếc
máy" của nó), mọi hành động ra ngoài bị kiểm soát bởi nhãn provenance (IFC) +
giấy phép có thời hạn (lease). Người dùng xem/thao tác trực tiếp trên chiếc máy
này qua giao diện web.

**Đã có thật, đang chạy:** frontend React đầy đủ (mock demo 8 bước kịch bản bảo
mật) + sandbox Docker image đã build thành công và qua smoke-test 9/9 (trước khi
phát hiện bug script — xem §3).

## 2. Trạng thái git

```
6bcaf85  docs: rewrite README — professional structure + sandbox quickstart
c6a4553  feat(deploy): core sandbox image — blank-box AI Computer + network toggle
32036b5  docs(plan): 12.3.1 user direct control + 7.4.1 network toggle, sync numbers
aa6a12a  feat: initialize project and build core agent box frontend
```

Working tree **sạch**. Frontend đã được hoàn nguyên về bản `aa6a12a` (code hook
noVNC chưa test đã bị gỡ — thiết kế vẫn còn ở §4).

## 3. ✅ VIỆC 1 (ĐÃ XONG) — Fix bug `smoke-test.sh` bị TREO

> **Đã xử lý.** Nguyên nhân đúng như nghi vấn ⭐ bên dưới: `cleanup()` /
> `trap cleanup EXIT` còn tham chiếu `INTERNET_NET` đã bị xóa, gặp `set -u`.
> Trap đã được bỏ (xem comment đầu `smoke-test.sh`). Chạy trọn vẹn
> `bash smoke-test.sh` xong trong <60s, ra **10 PASS / 1 FAIL** — bài FAIL
> duy nhất là bài 8 (`box-firewall on` → `curl`), thất bại vì máy chạy thử
> không có internet ra ngoài, không phải lỗi script. Phần dưới giữ lại làm
> hồ sơ chẩn đoán.

**File:** `deploy/docker/smoke-test.sh`

| | |
|---|---|
| Triệu chứng | Chạy trọn vẹn `bash smoke-test.sh` → treo vĩnh viễn sau bài kiểm tra số 1 |
| Bằng chứng ngược | **Từng lệnh bên trong chạy RIÊNG đều tức thì**: `docker exec … echo/id/iptables -L/pgrep/curl` tất cả < 1s; container running, restarts=0; iptables OUTPUT policy DROP đúng |
| Đã xảy ra | 3/3 lần chạy gần nhất (Git Bash trực tiếp ×1, subprocess ×2) — trước đó từng đạt **9 PASS / 0 FAIL** một lần (bản trước khi thêm firewall) |

**Nghi vấn xếp theo độ khả tín:**
1. ⭐ **Hàm `cleanup()` + `trap cleanup EXIT` còn tham chiếu biến `INTERNET_NET`
   đã bị xóa** sau lần refactor — script chạy với `set -u`. Kiểm tra cuối file.
2. Buffering khi stdout là pipe: timeout kill làm mất buffer nên "vị trí treo"
   nhìn sai (thấy kẹt sau bài 1 nhưng có thể đang kẹt chỗ khác).
3. Tương tác MSYS/Git-Bash trên Windows (xem §6).

**Cách chẩn đoán gợi ý:** chạy `bash -x smoke-test.sh > trace.log 2>&1` rồi đọc
dòng cuối của `trace.log` sau khi kill — sẽ thấy đúng lệnh đang kẹt.

**Tiêu chí nghiệm thu:** `bash smoke-test.sh` → **9 PASS / 0 FAIL, exit = 0**,
kết thúc trong < 60s. Ý nghĩa từng bài kiểm tra nằm ngay comment trong script.

## 4. ✅ VIỆC 2 (ĐÃ XONG) — Hook màn hình box thật vào frontend (noVNC)

> **Đã xử lý.** Tab "Sandbox Machine" nối thật vào `websockify :6080` →
> `Xvnc :5900` qua `useVncScreen.ts`, có fallback mock khi box tắt. Khác
> một điểm so với thiết kế bên dưới: `rfb.resizeSession = true`
> (`frontend/src/lib/vnc/fit.ts`) để desktop đổi phân giải THẬT theo bề rộng
> khung ④, thay vì chỉ `scaleViewport` (scale ảnh → letterbox + chữ mờ).
> Phần dưới giữ lại làm hồ sơ thiết kế.

Hiện tab "Sandbox Machine" (`frontend/src/components/panels/SandboxScreenPanel.tsx`)
chỉ render mock. Mục tiêu: khi box Docker đang chạy → hiện **màn hình live**;
box tắt → tự fallback về mock (đừng mất kịch bản demo VPI — nó là cảnh chính
của đồ án, mục 14.5).

**Thiết kế đã duyệt (làm lại theo đây):**
- Cài `@novnc/novnc` (npm), import `RFB from '@novnc/novnc/lib/rfb'`.
- Kết nối tới `VITE_SANDBOX_VNC_URL` (mặc định `ws://localhost:6080/websockify`,
  đã ghi trong `.env.example`) — websockify :6080 → Xvnc :5900 **đã chạy sẵn
  trong box**, port 6080 đã publish và xác minh host chạm được (HTTP 405).
- 3 trạng thái: `connecting` (≤5s timeout) → `live` (canvas noVNC) /
  `offline` (fallback mock + thanh thông báo).
- `rfb.viewOnly = false` — người dùng thao tác được (quyết định 12.3.1);
  `scaleViewport = true`; dọn dẹp `rfb.disconnect()` khi unmount.
- Cần file khai báo kiểu `.d.ts` tối thiểu cho module (gói không ship types).
- Khi backend tích hợp computer-use của agent (tuần 8-9) mới thêm lớp
  V3/V4 quanh RFB này — **chưa phải bây giờ**.

**Tiêu chí nghiệm thu:** mở `npm run dev` → bấm tab Sandbox Machine → thấy
màn hình Ubuntu 1280×800 live, kéo chuột được; tắt container → tab hiện fallback
mock kèm thông báo.

## 5. 🔒 RÀNG BUỘC KHÔNG ĐƯỢC PHÁ

| # | Ràng buộc | Nguồn |
|---|---|---|
| 1 | **Ghim version**: `playwright==1.49.0`, `chromium-1148`, code-server 4.97.2. Nâng cấp = hành động có chủ ý + chạy lại toàn bộ smoke-test | tái lập thí nghiệm 13.6 |
| 2 | **Công tắc mạng = `box-firewall on/off` (iptables TRONG box)**. Tuyệt đối không quay lại `docker network connect/disconnect` — đã thử, Docker Desktop/WSL2 bỏ qua việc tắt NAT | quyết định 7.4.1 |
| 3 | **Mọi lần bật/tắt mạng phải ghi sổ audit `actor: user`** (②c) — backend sẽ implement, script/UI không được tự bấm mà không đi qua Controller | 7.4.1, 9.7 |
| 4 | **Không có nút "luôn cho phép"** trong UI quyền hạn — luật tuyệt đối | 12.5 |
| 5 | **Máy trống**: KHÔNG bake Node/JDK/Rust… vào image; Python hệ thống chỉ là máy chạy driver Playwright tại `/opt/pw-driver`. Agent tự cài SDK theo yêu cầu người dùng | 12.3.1 |
| 6 | Non-root: tiến trình dịch vụ phải chạy user `agent` (entrypoint root chỉ để set iptables rồi `gosu` hạ quyền) | quy tắc ⑥ |
| 7 | `controller/` + `security/` backend **không bao giờ gọi LLM**; mọi hành động ra ngoài đi qua đúng một Policy Engine | N1, N2 |

## 6. 🪤 Bẫy môi trường Windows (đã cắn thật — đừng cắn lại)

- **Git Bash (MSYS) tự dịch** `/opt/...` → `C:/Program Files/Git/opt/...` khi
  truyền vào `docker.exe`. Khắc phục: `MSYS_NO_PATHCONV=1 docker exec … sh -c '…'`
  (script smoke-test đã có helper `DX()` làm sẵn).
- **PowerShell**: `bash` trỏ về WSL relay → lỗi `execvpe(/bin/bash) failed`
  (chưa cài distro Linux). Chạy script bằng Git Bash hoặc đường dẫn đầy đủ
  `C:\Program Files\Git\bin\bash.exe`.
- **Docker Desktop/WSL2**: `internal: true` làm hỏng published ports; tắt NAT
  bridge (`enable_ip_masquerade=false`) cũng không cắt được internet của
  container. Cả hai đã thử và loại — cơ chế đúng là iptables trong box.
- Console có thể bị TUI khác (Grok Build…) chiếm — nếu log lạ, chạy lệnh ghi
  ra file rồi đọc file.

## 7. 🗺 Bản đồ nhanh + lệnh hay dùng

```
deploy/docker/
├── Dockerfile           # recipe image lõi (ghim version ở ARG đầu file)
├── docker-compose.yml   # user:"0", cap NET_ADMIN, masquerade-off bridge, 3 ports
├── box-entrypoint.sh    # root: firewall off → gosu agent → Xvnc/websockify/code-server
├── box-firewall         # CÔNG TẮC MẠNG (on|off)
└── smoke-test.sh        # 9 bài kiểm tra = bằng chứng nghiệm thu
```

```bash
cd deploy/docker
docker compose build && docker compose up -d     # dựng + chạy box
bash smoke-test.sh                               # nghiệm thu
docker exec --user root agentbox-box box-firewall on|off   # công tắc mạng
# Truy cập: VNC localhost:5900 · VS Code web localhost:8080
```

Frontend: `cd frontend && npm install && npm run dev` → http://localhost:3100
(transport mặc định = mock; typecheck/lint/test đều phải pass trước khi commit).

---

<div align="center"><sub>Hết handoff. Khi nghi ngờ, đọc plan — nó trả lời gần như mọi câu "tại sao".</sub></div>
