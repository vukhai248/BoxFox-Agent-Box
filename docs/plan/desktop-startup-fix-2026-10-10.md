# Desktop: khóa phiên và độ trễ sau khi UI mở — 10/10/2026

## Phạm vi và điểm quay lại

- Baseline: `ff59af8f040cc18f335ffa45e768b962111c54c1`, nhánh `main`.
- Nhánh sửa local: `codex/desktop-startup-fix`; tag quay lại: `codex/desktop-before-startup-fix-20261010`.
- Bộ cài sửa: 0.1.1, Windows x64. Không tự cài, push hoặc merge.
- Giữ frontend, model, ngôn ngữ, chat, quyền và chính sách DAG. Không chuyển đổi lại desktop hoặc thay layout.
- WIP không thuộc patch được giữ nguyên. Profile người dùng chỉ được đọc để kiểm tra khóa và mode; mọi probe dùng dữ liệu riêng dưới `.tmp/desktop-startup-fix/`.

## 1. Lỗi “already running”: đã xác nhận và sửa

File thật `C:\Users\Admin\AppData\Local\BoxFoxDesktopAlpha\desktop.lock` chứa PID `29264`, thời điểm `2026-10-09T21:58:17.704Z`. Khi điều tra, PID này thuộc **TextInputHost.exe**, không phải BoxFox. Kiểm tra PID còn sống không chứng minh chủ sở hữu khóa còn sống sau reboot/PID reuse.

Các lỗi shutdown độc lập trong bản cũ:

- Tray Quit đặt `quitting` trước khi gọi `app.quit()`, khiến handler bỏ qua cleanup.
- `app.exit()` không phát `will-quit`; release khóa đặt ở đó không bảo đảm chạy.
- Startup failure trước khi gán `state` có thể bỏ sót tài nguyên đã mở.

Patch: dùng Electron native single-instance lock; file có token chỉ làm metadata. Nhấp lần hai đưa cửa sổ hiện có lên trước. Guard nâng cấp kiểm đúng tên và thời điểm tạo tiến trình của bản cũ, không giết PID tái sử dụng. Cleanup đăng ký từng tài nguyên, chạy một lần theo thứ tự ngược trên Quit và startup failure. Release không xóa record của chủ mới.

Đóng X vẫn ẩn vào tray theo thiết kế có sẵn; **Quit trong tray** mới thoát dịch vụ. Không thay chính sách này.

## 2. CUA Windows: lỗi đã xác nhận và sửa

HostExecutor đã chọn GDI/UIA/SendInput trên Windows, X11 trên Linux. Không cần sao chép lại CUA Ubuntu vào Windows. Điểm hỏng là hook input Windows:

- Bản cũ cài `WH_MOUSE_LL`/`WH_KEYBOARD_LL` trên thread aiohttp mà không pump Win32 messages.
- Callback đọc/ghi lease JSON cho từng sự kiện chuột/phím.
- Esc có đường gọi `CallNextHookEx` hai lần.

Patch: cài/pump/unhook trên thread sở hữu riêng; callback chỉ vô hiệu hóa token trong RAM và coalesce input. Persistence và emergency cleanup chạy ngoài callback. Esc có revision riêng để không bị mouse move ghi đè. Lease đọc/ghi có khóa thread; `CallNextHookEx` gọi đúng một lần. Watcher xử lý pending input mỗi 250 ms và fence kiểm ngay trước hành động. Không đổi grant hoặc cho phép agent tự giành quyền từ người.

Probe Windows thật xác nhận thread khác main, nhận private message và nhả cả hook khi stop; không tiêm input vào ứng dụng người dùng. Đây không phải nghiệm thu toàn bộ picker, capture và input CUA.

## 3. Lag sau UI: vẫn cần xác nhận trên bản cài của người dùng

Owner làm rõ: UI đã hiện, khoảng 5 giây sau mới lag chuột hoặc toàn máy; lúc đó vừa cài app, chưa chọn mode. **Không đánh đồng với thời gian chờ UI mở.**

Đã kiểm:

- Fresh install mặc định Host; CSDL bản đang cài cũng lưu `host`.
- Bản cũ vẫn probe Docker trong startup Host. Patch bỏ bước đó ở Host; Docker giữ đường xử lý hiện hữu.
- `useBoxState` hiện đã có guard mode Docker; không sửa frontend này.
- Hai lượt real Electron + router/harness + UI, profile mới, quan sát thêm 25 giây sau UI: không có request `/__box/*` hoặc `/__tty/*`; renderer phản hồi chậm nhất lần lượt 82 ms và 64 ms. Watchdog 15 giây cũng nằm trong khoảng đo.
- Không tái lập được lần đứng 5–7 giây ở hai lượt này. Chưa có bằng chứng quy lỗi cho Docker poll sau UI.
- RAM khả dụng có lúc xuống khoảng 0,30 GiB trong run10; CPU hệ thống và Defender có dao động. Tương quan này không chứng minh nguyên nhân. Phép đo CPU từng process dùng đơn vị 100%=một logical core, không phải toàn máy.
- Backend vừa được restage cần khoảng 11,5 giây import; các lượt sau dùng cache hiện UI khoảng 3,2–4,7 giây. Đây là thời gian nạp trước UI, không phải bằng chứng cho freeze sau UI. Không thêm tối ưu bytecode/build vào patch vì chưa giải quyết đúng triệu chứng.

Bổ sung log pha startup, thời gian import Python, readiness API không phụ thuộc chẩn đoán search; chẩn đoán search chạy ngoài event loop. Bind endpoint search theo cổng router của đúng profile, không dùng cổng dev 3101.

**Còn mở:** cold boot trên máy người dùng và hiện tượng mất đáp ứng input toàn hệ thống sau UI. Không tick “hết lag” chỉ vì renderer không đứng. Nếu tái phát, đối chiếu thời điểm UI/lag với `logs/desktop.log`, `harness.stdout.log`, CPU/RAM/GPU/disk và hoạt động hook; không tắt Defender hoặc đổi model để che vấn đề.

## 4. Kiểm thử và cách tái lập

- `npm.cmd test` trong `desktop`: **77 passed, 0 failed, 2 skipped** (79 ca). Hai skip là smoke/process group POSIX, không thay thế Windows probe.
- Nhóm backend trực tiếp liên quan (desktop_control, win_platform_input, host_executor_cua, desktop_api, health_search_status): **137 passed**.
- Mở rộng thêm capture/input/UIA/overlay: lần đầu **238 passed, 1 failed** do ca Linux đòi Windows không có `ctypes.WinDLL`; đã đánh dấu đúng platform. Lần kế tiếp **237 passed, 1 skipped, 1 failed** ở timer tự ẩn viền; chạy riêng ca timer **1 passed**. Giữ failure này trong báo cáo, chưa quy cho patch hook và chưa sửa overlay ngoài phạm vi. Không báo toàn bộ bộ kiểm CUA là xanh.
- Native hook: PASS, thread riêng, private message được pump, thread dừng, handles được nhả, không gửi input.
- Lifecycle Windows: stale metadata được phục hồi, X ẩn, lần chạy thứ hai hiện đúng một cửa sổ, Quit xóa khóa và không còn router/harness orphan.
- `git diff --check`: đạt.

Probe có thể chạy lại trên Windows với Python + psutil của môi trường kiểm thử (không phải dependency của người dùng app):

```powershell
$env:PYTHONPATH = (Resolve-Path backend/src).Path
python desktop/test/probes/native-hook.py
$env:BOXFOX_PROBE_ELECTRON = '<electron.exe dùng cho kiểm thử>'
$env:BOXFOX_PROBE_STEADY_MS = '25000'
python desktop/test/probes/measure-startup.py <ID-lượt-mới>
```

Probe import bổ sung: `BOXFOX_PROBE_IMPORTTIME=1`. Probe shipped resources bổ sung: `BOXFOX_PROBE_PACKAGED_RESOURCES=<win-unpacked/resources>`, đọc `app.asar` và runtime thực của bộ đóng gói. Các biến này chỉ dùng trong test runner, không phải cấu hình sản phẩm.

Evidence tóm tắt: `desktop-startup-fix-evidence-2026-10-10.json`. Raw logs nằm trong `.tmp/desktop-startup-fix/`; không commit profile/credential/log hội thoại. Manifest, SHA256SUMS và receipt của bộ cài đặt cạnh installer trong `desktop/release/startup-fix-0.1.1/`.

## 5. Bàn giao

Đã sửa các đường khóa/cleanup và hook Windows có bằng chứng cụ thể. Bộ cài mới phục vụ kiểm chứng lại triệu chứng owner; không tuyên bố đã nghiệm thu toàn bộ Alpha. UI block hash giữ nguyên `00ca53c040f6e069f358f982f8eff155f3850a9ba59487a33fcc44fa456c5589`.

Nguồn hợp đồng OS: [Electron app lifecycle/single instance](https://www.electronjs.org/docs/latest/api/app), [Microsoft LowLevelMouseProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelmouseproc). Windows yêu cầu hook có message loop và callback ngắn. Test Linux/fake không chứng minh hành vi Windows thật.

## 6. Checkpoint đóng gói

- Source được đóng gói: `1d1ef5286133170c4e874a9499f8da9ee3304255`.
- `desktop/release/startup-fix-0.1.1/BoxFox-Desktop-Alpha-0.1.1-Setup.exe`: 167428303 bytes, SHA-256 `1e7af35507becca09beeeb86886c3e835b1522aee6dfec8a854eb9526f854e56`.
- NSIS và payload `app-64.7z`: `7z t` đều `Everything is Ok`; bộ cài **NotSigned**. Chưa chạy installer/giao dịch upgrade trên profile của owner.
- Run12 đọc chính `app.asar` và resources của `win-unpacked`, runtime/router/harness/UI thật, dưới Electron 33.4.11 và packaged-path test context. Không coi đây là đã tự cài trên máy Windows sạch.
- UI hiện 5823 ms; quan sát thêm 25000 ms; renderer chậm nhất 67 ms; không gọi sandbox/tty ở Host; second-instance đúng một cửa sổ; Quit không còn khóa hoặc orphan.
- Manifest `dirty=true` do các file untracked của owner được bảo toàn; không có sửa tracked source lúc package. Commit và hash từng block vẫn được ghi, UI giữ nguyên.
- Kết luận giữ nguyên: candidate cho owner kiểm chứng lại lag sau UI; chưa tuyên bố hết lag toàn máy.
