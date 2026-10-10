# Desktop 0.1.2 — chat dùng đúng cổng router của profile

## 1. Lỗi và phạm vi

Owner báo OpenCode hoạt động trên Ubuntu/cloud nhưng app Windows hiển thị
`UPSTREAM_UNREACHABLE / ConnectError: All connection attempts failed`; Settings ping vẫn được.

Đo trên app 0.1.1 đang chạy: gateway **64557**, router **64558**, harness **64559**.
Trước khi mở web, không có listener 3101. Desktop supervisor đã cấp
`BOXFOX_ROUTER_URL=http://127.0.0.1:64558` đúng cho harness, nhưng
`HarnessRuntime` tạo `RouterClient()` có mặc định cứng **3101**, bỏ qua biến này.
Settings đi qua gateway tới router đúng; chat và model metadata của harness đi nhầm tới cổng web.
Web/cloud dùng 3101 nên không bộc lộ lỗi tương tự. Mở web ở 3101 có thể che lỗi,
hoặc khiến app dùng connection ID không tồn tại ở profile web; không dùng việc đó làm cách sửa.

Sửa tại `backend/src/agentbox/agent_core/runtime.py`: ưu tiên URL truyền trực tiếp,
sau đó `BOXFOX_ROUTER_URL`, cuối cùng giữ default web 3101. Bỏ whitespace và slash cuối.
Constructor của runtime/API server không đổi; main, child và các lượt completion tiếp tục dùng
client chung hiện có. Các lớp legacy `BoxFoxAgent`/`AgentTurnExecutor` chỉ thấy caller trong
tests/export, không nằm trên đường server đang chạy; chưa đổi chúng.

Không sửa UI, provider adapter, model list, ngôn ngữ, quyền project hoặc DAG.
`JOURNAL_DEGRADED / PROJECT_TRUST_REQUIRED` là một lỗi riêng: executor từ chối ghi journal
khi project chưa được trust. Không tự cấp trust; cảnh báo này không phải lỗi kết nối model.

Source đóng gói: **`2e686820043f3408c577ebbe79f3b17556a99d05`**,
nhánh **`codex/desktop-startup-fix`**. Main không đổi; chưa push/merge.
Patch này kế thừa sửa lock/hook/startup của 0.1.1.

## 2. Kiểm thử và bằng chứng

- `pytest backend/tests/unit/test_router_client_endpoint.py -q`: **5 passed**.
  Bao gồm default web, env desktop, explicit URL ưu tiên, env rỗng và hai HTTP router
  ở cổng riêng: metadata và SSE chat tới đúng router; client desktop không đổi binding
  khi tạo client web mới. Runtime được tạo không inject client, giống server.main.
- Nhóm endpoint/context-window/stream/usage: **48 passed** (đã bao gồm 5 ca mới).
  Lệnh: `pytest backend/tests/unit/test_router_client_endpoint.py backend/tests/unit/test_context_window_heal.py backend/tests/unit/test_stream_delta_events.py backend/tests/unit/test_usage_surface.py backend/tests/unit/test_usage_allocation_route.py -q`.
- Hồi quy HTTP router/API, SSE rỗng và stream bị cắt: **3 passed**, 20 deselected.
  Lệnh: `pytest backend/tests/unit/test_harness_runtime.py -q -k "http_router_auth or empty_provider_stream or stream_cut or router_refusal or router_error or metadata"`.
- `npm.cmd test` trong desktop: **77 passed, 0 failed, 2 skipped**;
  skip là smoke/process group POSIX. Đây không phải Windows nghiệm thu thay thế.
- Probe model thật dùng source client đã sửa: OpenCode **mimo-v2.6-flash-free**
  tại router app 64558 và web 3101 đều có metadata, trả **OK**, finish `stop`, không stream error.
  Khoảng 2964/2884 ms. Không dùng credential khác hoặc đổi provider để làm đẹp kết quả.
- Probe Windows đọc **app.asar và resources của bộ đóng gói 0.1.2** dưới Electron 33.4.11,
  profile test riêng; web và app người dùng vẫn chạy. Gateway 62348 → harness 62350 →
  router 62349 → OpenCode MiMo → assistant **OK.**, session `completed`.
  Connection test chỉ có trong profile riêng; dùng credential free-tier công khai `public`,
  không copy API key/profile của owner.
- Run2: UI 4946 ms; chat hoàn tất ở 10693 ms tính từ startup; quan sát thêm 25 giây,
  renderer latency tối đa 11 ms; không request `/__box` hoặc `/__tty` ở Host.
  X ẩn cửa sổ, second-instance khôi phục đúng một cửa sổ, Quit nhả lock và không còn orphan.
  Đây là packaged-path probe, **chưa chạy installer/upgrade trên profile owner hoặc máy Windows sạch**.
  CPU đo cùng đợt đóng gói có tải khác; không dùng kết quả này để tuyên bố hết lag toàn máy.
- Journal của session test vẫn degraded vì không cấp workspace trust; chat vẫn hoàn tất.

### Các lượt chưa đạt — giữ nguyên evidence

- Native run1 dừng ở setup connection HTTP 401 vì fixture tạo OpenCode với credential trống.
  Gateway đã inject admin header; nguyên nhân **không phải thiếu header admin**.
  Sửa fixture dùng `public`, không sửa auth/router; run2 đạt. Exit không để orphan.
- Web harness trên profile có sẵn nhận được phản hồi model, nhưng các fixture bị giới hạn
  **1 bước** không đạt oracle câu trả lời `OK`: lần 128 token báo `PROVIDER_OUTPUT_TRUNCATED`,
  lần 4096 token báo `STEP_BUDGET_EXHAUSTED` và trả bản tổng kết dừng.
  Lần có instructions riêng vẫn bị stop notice. Không sửa policy/prompt/giới hạn sản phẩm
  trong patch cổng này, không ghi các lượt đó thành kiểm thử chất lượng đạt.
  Web connectivity và provider trực tiếp đã đạt; hành vi stop/nudge với cấu hình web cũ
  cần tái lập riêng với ngân sách/thao tác người dùng bình thường nếu còn vấn đề.

Raw evidence: `.tmp/model-router-fix-20261010/` và
`.tmp/desktop-startup-fix/model-router-012-run{1,2}/`.
Không commit DB/profile/credential hoặc toàn bộ log người dùng.
Probe native: bật `BOXFOX_PROBE_CHAT=1`, `BOXFOX_PROBE_PACKAGED_RESOURCES=<resources>`,
`BOXFOX_PROBE_ELECTRON=<Electron 33.4.11 executable>`, `BOXFOX_PROBE_STEADY_MS=25000`,
rồi chạy `python desktop/test/probes/measure-startup.py <run-id-mới>`.

## 3. Bộ cài và web để owner kiểm tra

Web đang chạy tại **http://localhost:3100/**, router 3101, harness 3102.
UI, router và harness qua proxy Vite đều health HTTP 200.
PID khởi động: UI 23032, router 28880, harness 31700; đây chỉ là receipt của lượt hiện tại.
Giữ profile web và desktop riêng, không copy credentials hoặc DB giữa chúng.

Bộ cài:
`desktop/release/model-router-fix-0.1.2/BoxFox-Desktop-Alpha-0.1.2-Setup.exe`

- Size: **167428432 bytes**.
- SHA-256: `ab1fd74b63b60e3c3adcfaae231eb80636b43f92b2fa13d541279ec7d719be1f`.
- NSIS và payload `app-64.7z`: `7z t` đều **Everything is Ok**.
- Signature: **NotSigned**. Main.js trong asar khớp compiled source.
- UI/router/runtime/docker-context block hash không đổi so với 0.1.1.
  UI SHA-256: `00ca53c040f6e069f358f982f8eff155f3850a9ba59487a33fcc44fa456c5589`.
  Manifest/runtime lock/SHA256SUMS đặt cạnh bộ cài; `dirty=true` do file untracked owner được bảo toàn.

Để cập nhật: dùng **Quit** trong tray (X chỉ ẩn), chạy Setup 0.1.2 vào đúng vị trí app cũ,
rồi mở lại. Không xóa data/profile hoặc project. App 0.1.1 đang chạy chưa tự nhận code mới.
Owner kiểm tra chat với web tắt là ca xác nhận cuối để loại việc web che lỗi.
Giữ installer 0.1.1 và các commit trước làm điểm quay lại.
