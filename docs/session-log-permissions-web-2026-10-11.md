# Nhật ký phiên 2026-10-10/11 — Hệ thống quyền (permissions) + sửa lỗi bản web

> Mục đích của tệp: ghi lại **chính xác** những gì đã đổi trong phiên này, đổi ở đâu, đã kiểm
> bằng cách nào, và còn gì chưa xong — để có thể làm lại từ đầu hoặc tiếp tục, không phải đoán.

---

## 0. Tóm tắt một đoạn

Phiên này làm 4 việc chính: (1) gộp 3 chế độ quyền rời rạc thành 4 chế độ có nghĩa rõ;
(2) vá 1 lỗ hổng bảo mật thật — trần host chỉ chặn lúc **đổi**, không chặn lúc **đọc**;
(3) dựng bản host cho 3 thao tác nhật ký để hết banner `JOURNAL_DEGRADED`;
(4) tách biệt `advance` và `full-machine` ở đúng chỗ lệnh rủi ro. Ngoài ra còn sửa 3 lỗi hạ tầng
dev khi nghiệm thu trên browser, trong đó **lỗi router proxy** là thủ phạm của triệu chứng
"đúng lúc đầu, mock sau ~1s".

**Trạng thái cuối: code chưa commit. Đã fallback về `origin/main` (`d4385abc`).**

---

## 1. Vì sao phải chạy backend từ source chứ không dùng app

Đây là bài học quan trọng nhất của phiên, và là thứ làm sai hướng nhiều lần.

App cài ở `D:\boxfox\boxfox-desktop` là bản **đã build** (0.1.4, commit `d5ad613`). Log của nó
cho thấy nó khởi động harness bằng:

```
resources\runtime\python\python.exe
D:\boxfox\boxfox-desktop\resources\harness\scripts\run-harness.py
```

Tức là nó nhồi sẵn `backend/src` **của bản build**. Chạy app ⇒ code mới trong repo **không**
được áp dụng ⇒ test cho kết quả sai mà không báo lỗi.

Cách đúng: đọc script app dùng, thấy nó chỉ có **một dòng quan trọng** là
`sys.path.insert(0, .../backend/src)`. Tái tạo lại nhưng trỏ vào `backend/src` **của repo**.

```python
# .tmp/run_harness_from_source.py
REPO = Path(r'D:/create/BoxFox-Agent-Box')
sys.path.insert(0, str(REPO / 'backend' / 'src'))
os.environ.setdefault('BOXFOX_DESKTOP_PROFILE', r'C:\Users\Admin\AppData\Local\BoxFoxDesktopAlpha')
```

**Rút ra:** khi test hệ thống có app desktop đã đóng gói, luôn xác định tiến trình đang chạy
**đọc code từ đâu** trước khi tin vào kết quả test.

---

## 2. Bốn chế độ quyền

Trước: `ask` / `auto` / `advance` (+ trần host). Sau: 4 chế độ có nghĩa tách biệt rõ.

| Chế độ | Phạm vi | Lệnh rủi ro | CUA | Set trust folder |
|---|---|---|---|---|
| `ask` | — | hỏi từng việc | hỏi | không |
| `auto` | trong folder | hỏi (hỏi thường) | hỏi | **có** |
| `advance` | cả máy | **hỏi → tab Decisions** | tự do | **có** |
| `full-machine` | cả máy | **không hỏi** | tự do | **có** |

File: `backend/src/agentbox/agent_core/permissions.py`

### 2.1 Lỗ hổng đã vá — trần host chỉ chặn lúc đổi, không chặn lúc đọc

**Đây là lỗi nghiêm trọng nhất của phiên.**

Trước đây `HOST_RESTRICTED` chỉ được kiểm ở `PUT /permissions`. Nghĩa là người dùng không **bật**
được `full-machine` sau khi host đặt trần — nhưng giá trị **đã lưu từ trước** trong
`~/.boxfox/settings.json` vẫn nằm nguyên và vẫn được đọc trọn vẹn.

Kịch bản thật: mở `full-machine` lúc dùng bản thường → sau đó bản công ty đặt trần và khởi động
lại → `full-machine` vẫn chạy. **Trần thành đồ trang trí.**

Cách vá: thêm `_host_ceiling()`, áp cho **mọi đường đọc** (`mode_value()`, `scope_value()`,
`network_value()`), hạ `full-machine` → `advance`. Không hạ thẳng xuống `ask` vì mất CUA tự do đã
đủ cho máy dùng chung, còn đẩy về hỏi-từng-việc là phạt oan.

### 2.2 Bug thiết kế — `full-machine` chẳng khác gì `advance`

Nhóm lệnh luôn-hỏi (`GUARDED`) chạy **trước** mọi mode, nên `full-machine` vẫn hỏi
`git push --force`, `curl | sh`. Hai chế độ được tách riêng thì hành xử y như nhau ở đúng chỗ
lẽ ra phải khác.

Cách vá:

```python
guard = self.guardian_reason(command)
# Nhóm luôn hỏi chỉ áp cho ba mức CÒN HỎI. full-machine nghĩa là "đừng hỏi gì nữa".
if guard and self.mode_value() != MODE_FULL_MACHINE:
    ...
```

Sàn cứng (`hardline_reason`) ở **trên** và `return` ngay, nên nó thắng guardian ở **mọi** mức —
kể cả `full-machine`. Đúng ý người dùng: "mode 4 chỉ chặn lệnh quá quá rủi ro".

### 2.3 `guardian_target()` — điểm `advance` khác `auto`

```python
def guardian_target(self):
    return 'decisions' if self.mode_value() == MODE_ADVANCE else ''
```

Trước đây `advance` đi cùng đường `guarded` với `auto` nên hai mức đó hành xử y hệt. Giờ chỉ
`advance` đưa câu hỏi về lệnh rủi ro vào **tab Decisions** kèm lệnh đầy đủ.

---

## 3. Cổng xác nhận 428 cho `full-machine`

`PUT /permissions` không tự bật mức cao nhất. Luồng:

1. Gửi `{mode: 'full-machine'}` **không** có `confirmed` → **428**
   `PERMISSION_CONFIRMATION_REQUIRED`
2. Gửi lại `{mode: 'full-machine', confirmed: true}` → **200**, mode thực sự đổi

Field là `confirmed` (chú ý: không phải `confirm`).

File: `backend/src/agentbox/api/server.py:1087`

### 3.1 Lỗi frontend tìm được khi nghiệm thu browser — trang Settings không mở popup

`PermissionModePicker` (trong khung chat) **đã có** nhánh bắt 428 để mở popup, nhưng
`MachinePermissionsView` (Settings → Machine & Permissions) thì **không** — `changeMode` của nó
đi qua `runAction`, coi 428 là lỗi thường rồi hiện dòng đỏ.

Hệ quả: người dùng **không có cách nào** bật `full-machine` từ trang Settings.

Cách sửa: thêm state `pendingMode`, nhánh `isConfirmationRequired(err)`, hàm `confirmMode`
gửi lại kèm `confirmed: true`, và render `<FullMachineConfirmModal>` (dùng lại component có sẵn).

---

## 4. Set folder trust khi chọn chế độ

Chọn `auto`/`advance`/`full-machine` thì **đồng thời** set folder trust qua `registry.trust()`
— cùng đường mà route `/machines/trust` dùng, không tạo đường thứ hai.

Quy tắc:
- Chỉ **chọn** mức mới set. Hạ mức **không** tự gỡ trust (bỏ tin cậy là quyết định riêng).
- Registry lỗi thì **không** làm hỏng việc đổi mức — ghi log `permissions.trust_grant_failed`
  rồi đi tiếp.

---

## 5. Bản host cho 3 thao tác nhật ký (hết banner `JOURNAL_DEGRADED`)

Trước đây `session_ensure` / `journal_append` / `checkpoint_write` nằm trong `DEFERRED_TOOLS`
— host mode không có bản nào nên **luôn** trả `UNSUPPORTED_IN_HOST_MODE`. Đó là nguồn của banner
đỏ hiện ở mọi tin nhắn.

Đã làm:

- Thêm `JOURNAL_TOOLS` vào `HOST_TOOLS`, gỡ khỏi `DEFERRED_TOOLS`
- Viết `_journal_op()` ghi vào `<workspace>/.session-history/<sid8>/` — thư mục của **chính phiên**
- Xử lý đúng 3 op: tạo thư mục + `meta.json` (idempotent), append `journal.jsonl`, ghi
  `checkpoint-N.json` (hai lần ra **hai tệp**, không đè)
- Đường lỗi trả `ok: False` + `errorCode` rõ ràng, không ghi dòng rác
- Gỡ cổng trust chặn oan 3 op này ở `machine_router.py:471`

**Bằng chứng then chốt:** qua `session_journal.ensure_session()` thì **0 notice
`JOURNAL_DEGRADED`** ⇒ banner hết hoàn toàn.

---

## 6. Ba lỗi hạ tầng dev tìm được khi nghiệm thu browser

Đây là phần tốn thời gian nhất, và cả ba đều là lỗi **môi trường/đấu dây**, không phải lỗi logic.

### 6.1 vite proxy rewrite `Origin` sai ⇒ `PUT` bị 403

`changeOrigin: true` đổi `Host` thành host upstream **trước** khi hook `proxyReq` chạy, nên phép
so `origin === http://${host}` khớp sai và `Origin` bị đổi thành giá trị ngoài
`BOXFOX_UI_ORIGINS`.

Triệu chứng đặc trưng: `GET /permissions` → 200 nhưng `PUT /permissions` → 403
"Local administration required". Rất khó đoán vì GET và PUT đi cùng một middleware.

Cách sửa: bỏ rewrite `Origin`, để nguyên `Origin` của trình duyệt (đó là giá trị server cần
kiểm với `allowed_origins()`).

### 6.2 `127.0.0.1` và `localhost` là **hai origin khác nhau**

Trình duyệt mở trang ở `http://127.0.0.1:3210` mà danh sách chỉ có `localhost:3210` ⇒ 403.
Phải mở **cả hai**.

### 6.3 Router là service riêng — thủ phạm của "đúng lúc đầu, mock sau ~1s"

Đây là lỗi cuối và là lỗi giải thích được triệu chứng bạn thấy.

Chuỗi nhân quả:

1. Router là **service Node riêng** (thư mục `router/` của repo), nghe cổng **3101**
2. `vite.config.ts` map `/api/router` → `3101` (đúng)
3. Nhưng khi đặt `BOXFOX_DESKTOP_GATEWAY`, `desktopGatewayProxy()` **thay thế toàn bộ** proxy
   map, và map `/api/router` về **gateway** (cổng harness) chứ không phải 3101
4. ⇒ mọi lời gọi router nhận **502**
5. ⇒ `providerStore.load()` rơi vào nhánh `catch` ⇒ `set({snapshot: null})`
6. ⇒ `HarnessModelPicker` tính `hasLive = false`
7. ⇒ tab "Single Models" rơi về `AVAILABLE_MODELS` — danh sách mock **cứng** trong
   `frontend/src/store/harnessStore.ts:7`

Cách sửa: tách `/api/router` ra proxy riêng trỏ đúng 3101, và forward `X-BoxFox-Admin: 1` cho
nó (router cũng đứng sau cổng local-admin).

```ts
const routerOrigin = process.env.BOXFOX_ROUTER_ORIGIN || 'http://127.0.0.1:3101'
return {
  ...Object.fromEntries(['/api/agent', '/api/desktop', '/v1', '/__box', '/__tty']
    .map((route) => [route, proxy])),
  '/api/router': routerProxy,
}
```

Sau khi sửa: `/api/router/state` qua proxy → **200** (trước đó 502), và router state **có**
opencode.

**Bài học:** khi thấy "đúng lúc đầu rồi sai", nghĩ ngay đến một lần fetch/poll **ghi đè** state
bằng dữ liệu dự phòng. Đừng sửa chỗ hiển thị — sửa chỗ **nguồn dữ liệu** bị hỏng.

---

## 7. Danh sách file đã đổi

### Backend
| File | Đổi gì |
|---|---|
| `agent_core/permissions.py` | `_host_ceiling()`, `guardian_reason()` + `guardian_target()`, `TRUST_IMPLYING_MODES`, `GUARDED` bỏ qua khi `full-machine` |
| `api/server.py` | cổng 428/`confirmed`, `_grant_project_trust()` |
| `sandbox/host_executor.py` | `JOURNAL_TOOLS`, `_journal_op()` |
| `sandbox/machine_router.py` | gỡ cổng trust chặn oan 3 op nhật ký |

### Frontend
| File | Đổi gì |
|---|---|
| `dev/desktopProxy.ts` | bỏ rewrite `Origin`; tách proxy `/api/router` → 3101; forward admin header theo `BOXFOX_DEV_ADMIN` |
| `settings/MachinePermissionsView.tsx` | nhánh 428 → popup, `confirmMode()` |
| `chat/HarnessModelPicker.tsx` | (đã có sẵn nhánh 428) |

---

## 8. Đã kiểm bằng cách nào

| Việc | Kết quả |
|---|---|
| Logic backend — 19 ca lệnh | 19/19 |
| Cổng 428/403 — 13 ca | 13/13 |
| Review sâu — 8 kịch bản nguy hiểm | 8/8 |
| Trần host không rò | PASS |
| Snapshot khớp mode | PASS |
| Trust grant — 5 kịch bản | PASS |
| 3 op nhật ký — 8 mục (0 notice DEGRADED) | 8/8 |
| Guardian — 16 ca | 16/16 |
| Cổng 428 trên HTTP thật | đúng |
| Cổng bảo mật origin | đúng (cho phép→200, lạ→403) |
| UI thật — trang Machine & Permissions | hiện đúng 4 mức + bảng năng lực |
| Frontend test | 1716 pass / 3 fail |
| Build (`npm run build`) | ✓ |

**3 test fail** là `ConnectionKeyRing` (2) + `ProviderConnectionCard` (1). Đã stash xác nhận:
**fail sẵn trên main**, không do thay đổi này.

---

## 9. Chưa xong / cần làm tiếp

1. **Nghiệm thu popup xác nhận trên browser** — code đã sửa nhưng chưa kịp F5 xem popup hiện và
   bấm Confirm có đổi mode thật không.
2. **Chưa build/test lại frontend** sau khi sửa `MachinePermissionsView.tsx`.
3. **pytest chưa chạy** — môi trường Windows này không có pytest. Verify bằng script Python thuần
   (52/52 ca) nhưng đó là **bản sao logic**, chưa phải test khoá regression. Cần chạy pytest ở
   máy có venv.
4. **Danh sách model trong UI vẫn chưa chắc đã lấy từ router** sau khi sửa proxy — đúng lúc ghi
   tài liệu thì menu selector không mở được bằng script nên chưa xác nhận trực tiếp được.
   Đã xác nhận `/api/router/state` qua proxy trả 200 và **có** opencode.
5. **`guardian_reason()` → Decision tab cho `advance`** — chạm `runtime.py`, chưa làm.
   `advance` đã có bảng quyền đúng nhưng lệnh rủi ro vẫn đi đường `GUARDED` cũ.

---

## 10. Cách chạy lại từ đầu

Cần **3 tiến trình**, mỗi cái một cổng:

```bash
# 1) Router (Node) — cổng 3101
cd D:/create/BoxFox-Agent-Box/router && node src/main.mjs

# 2) Harness từ SOURCE — cổng 3102
cd D:/create/BoxFox-Agent-Box
BOXFOX_HARNESS_PORT=3102 \
BOXFOX_UI_ORIGINS="http://localhost:3100,http://127.0.0.1:3100" \
python .tmp/run_harness_from_source.py

# 3) Vite — cổng 3100 (cổng duy nhất bạn mở trên browser)
cd D:/create/BoxFox-Agent-Box/frontend
BOXFOX_DESKTOP_GATEWAY=http://127.0.0.1:3102 \
BOXFOX_DEV_ADMIN=1 \
node node_modules/vite/bin/vite.js --port 3100 --strictPort
```

Mở: **http://127.0.0.1:3100**

**Ba điều bắt buộc, thiếu một cái là hỏng:**

1. Phải khởi động **router** (3101) trước, nếu không `/api/router/state` → 502 ⇒ UI rơi về mock
2. `BOXFOX_HARNESS_PORT` và `BOXFOX_UI_ORIGINS` phải **khớp nhau** — mặc định chỉ có 3100/3102
3. Phải dùng `node node_modules/vite/bin/vite.js`, **không** dùng `npx vite` — `npx` không truyền
   env `BOXFOX_*` xuống tiến trình con

### Cách dọn sạch mọi cổng (khi bị rối như đã từng)

```bash
export MSYS_NO_PATHCONV=1
powershell -NoProfile -Command "Get-NetTCPConnection -State Listen | \
  Where-Object { \$_.LocalPort -in 3100,3101,3102,3110,3210,64557,64558,64559,64700 } | \
  Select-Object -ExpandProperty OwningProcess -Unique | \
  ForEach-Object { Stop-Process -Id \$_ -Force }"
```

Phải có `MSYS_NO_PATHCONV=1`, nếu không MSYS sẽ đổi path của PowerShell.

---

## 11. Bài học rút ra (để khỏi lặp lại)

1. **Xác định tiến trình đọc code từ đâu trước khi test.** App đã build nhồi backend riêng;
   test trên nó cho kết quả sai mà không báo lỗi.
2. **"Đúng lúc đầu rồi sai" = có fetch/poll ghi đè bằng dữ liệu dự phòng.** Sửa chỗ **nguồn**,
   đừng sửa chỗ hiển thị.
3. **`GET` qua mà `PUT` 403** thì nghi `Origin`/CORS, dù cả hai đi cùng một middleware.
4. **`127.0.0.1` ≠ `localhost`** trong mắt CORS. Luôn mở cả hai khi dev.
5. **Một cổng duy nhất cho dev.** Nhiều cổng làm mỗi lần fix bug phải đoán "cổng nào đang chạy
   bản nào" — đúng chỗ đã làm mất nhiều thời gian nhất.
6. **Env không tự tới tiến trình nền trên Windows.** Đừng đuổi theo env của background process;
   ghim vào script hoặc chạy foreground.
7. **`npx` không truyền env** `BOXFOX_*` xuống tiến trình con — dùng `node` trực tiếp.
8. **Cổng bảo mật phải chặn cả đường đọc, không chỉ đường đổi.** Lỗ hổng trần host là bài học này.
