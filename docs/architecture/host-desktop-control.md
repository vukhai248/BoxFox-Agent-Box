# Kiến trúc — Điều khiển desktop trên máy người dùng (host mode)

> **Trạng thái:** hợp đồng đã chốt (H1); nền tảng Windows đang được cài (H5–H7); nền tảng Linux/X11 có bản chạy được (xem §9).
> Những mục ghi *(đang cài)* là hợp đồng đã ký với phần còn lại của hệ thống, chưa phải mã đã xong.
>
> **Ngày:** 2026-10-06. **Quyết định liên quan:** ADR-0002 (đã chốt: kết hợp lựa chọn 1 + 2).
>
> **Tài liệu liên quan:** `docs/architecture/screen-capture.md` (hợp đồng chụp trong box),
> `docs/architecture/element-selector.md` (hợp đồng soi phần tử trong box),
> `docs/plan/desktop-host-mode.md` (kế hoạch host mode), ADR-0002.

---

## 1. Nguyên tắc

1. **Tái dùng hợp đồng dữ liệu đã có.** Frontend không được học một API thứ hai: host mode trả **cùng
   tên trường** như box, và gateway định tuyến `/__box/inspect-element`, `/__box/capture`,
   `/__box/record/*` sang đường host. Ba thứ **mới** trên Windows là: nhánh `uia`, toạ độ **vật lý** đa
   màn hình, và bộ luật điều khiển đồng thời giữa người và agent.
2. **Lớp nền tảng mỏng, logic thuần dày.** `sandbox/win/*.py` chỉ gọi `ctypes` (không có logic quyết
   định); lease, epoch, token, thang xác minh và chốt chặn nằm ở lớp thuần để **unit test tiêm được
   nền tảng giả**. Máy Linux không chạy được Windows, nên đây là cách duy nhất giữ được bằng chứng.
3. **Ảnh chụp là dữ liệu KHÔNG TIN ĐƯỢC.** Chữ trong ảnh/cửa sổ không bao giờ trở thành chỉ thị — đây
   là hàng rào chống prompt-injection qua màn hình.
4. **Không có "ok" đơn giản.** Mỗi hành động trả kết quả có cấu trúc: đã gửi ≠ đã thành công.
5. **Fail closed.** Đọc lease lỗi ⇒ về tay người. Không có approver ⇒ từ chối. Hook bàn phím cài
   không được ⇒ không cấp quyền điều khiển.

### 1.1 Bản đồ mô-đun

| Tệp | Việc | Thuần? |
|---|---|---|
| `backend/src/agentbox/sandbox/win/windows_platform.py` | nạp DLL, DPI awareness, phiên tương tác, `GetLastInputInfo`, hook `WH_MOUSE_LL`/`WH_KEYBOARD_LL`, mutex kernel, `SendInput` | chỉ `ctypes` |
| `backend/src/agentbox/sandbox/win/capture.py` | chuỗi GDI: `PrintWindow` → `BitBlt`, chốt chặn khung đen, kiểm tra bị che | chỉ `ctypes` |
| `backend/src/agentbox/sandbox/win/input.py` | chuột/phím bậc 2 (`SendInput`), chuẩn hoá toạ độ vật lý, nhả input bị giữ | chỉ `ctypes` |
| `backend/src/agentbox/sandbox/win/uia.py` | `IUIAutomation.ElementFromPoint`, registry phần tử, watchdog | `comtypes` + thuần |
| `backend/src/agentbox/sandbox/win/errors.py` | mã lỗi của lớp nền tảng | thuần |
| `backend/src/agentbox/agent_core/inspect_host.py` | ba nhánh `dom → uia → desktop`, shape kết quả, nhãn `label` | thuần (nhánh `dom` gọi CDP) |
| `backend/src/agentbox/agent_core/desktop_control.py` *(H7)* | lease + epoch + khoá kernel + token + thang xác minh | thuần |

---

## 2. Select element — ba nhánh `dom → uia → desktop`

Đầu vào: `POST /api/agent/desktop/inspect-element` với `{x, y}` — toạ độ **framebuffer vật lý**, đúng
như trong box. Gateway định tuyến `/__box/inspect-element` sang đây ở host mode.

Harness thử **lần lượt**, nhánh nào trả được dữ liệu thì dừng:

| # | Nhánh | Khi nào dùng | Cách làm |
|---|---|---|---|
| 1 | `dom` | cửa sổ dưới điểm là Chromium **và** có endpoint CDP loopback hợp lệ | `DOM.getNodeForLocation` + `Runtime.callFunctionOn` — y hệt trong box |
| 2 | `uia` | mọi ứng dụng còn lại (Notepad, Explorer, Office, Electron…) | `IUIAutomation.ElementFromPoint` (MTA, có watchdog) |
| 3 | `desktop` | UIA không trả phần tử nào | chỉ thông tin cửa sổ + toạ độ |

### 2.1 Dữ liệu trả về

- **`dom`** — **giữ nguyên** hợp đồng trong box: `{type:'dom', selector, url, title, tagName, text,
  attributes, html, truncated, cssBox, screenBox, notes, shadowHostSelector, target{windowId,
  windowTitle, targetId}, label}`. `target` chỉ có **đúng 3 khoá**; `webSocketDebuggerUrl` **không bao
  giờ** lộ ra.
- **`uia`** *(mới)*: `{type:'uia', name, controlType, automationId, className, helpText, isEnabled,
  isOffscreen, isPassword, bounds{screenBox, dpi}, patterns[], windowId, pid, processName,
  elementToken, label}`.
- **`desktop`** — **giữ nguyên** 11 mã `reason` đã có (`not_chromium`, `outside_viewport`,
  `frame_extents_unknown`, `devtools_docked`, `viewport_origin_unknown`, `no_cdp_target`,
  `ambiguous_target`, `cdp_unreachable`, `cdp_timeout`, `no_node_at_point`, `extract_failed`) và thêm 6
  mã cho Windows: `uia_unavailable`, `uia_timeout`, `uia_provider_hang`, `uia_no_element`,
  `no_window_at_point`, `window_identity_unavailable`.

**Nhãn `label`** giữ nguyên định dạng của box: `{integrity:'khong_tin_duoc',
confidentiality:'noi_bo', source_kind:'screen_capture', source_uri:'screen://element/<windowId>',
tool_name:'inspect_element', content_hash}`. `source_uri` **không nhúng selector**; `content_hash`
tính 3 bước như tài liệu element-selector.

### 2.2 Neo phiên bản

Mọi kết quả soi/click mang thêm `sourceId` (cửa sổ/trang), `frameId` (khung), `geometryRevision` (tăng
mỗi khi cửa sổ đổi vị trí/kích thước/DPI hoặc trang đổi layout) và `elementToken` (§4.1). Trước mỗi
hành động, executor **resolve lại** ref và kiểm grant / `sourceId` / epoch / geometry / focus; lệch ⇒
`ELEMENT_STALE` hoặc `SOURCE_CHANGED` — **không bao giờ** click theo toạ độ cũ.

---

## 3. Chụp màn hình (Windows, GDI thuần `ctypes`)

Không thêm phụ thuộc: `ctypes` là đủ cho bản alpha.

1. **Một lần lúc khởi động:** `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` (user32, Win10
   1703+; dự phòng `shcore.SetProcessDpiAwareness(2)`) — **trước khi** tạo cửa sổ nào. Không làm bước
   này thì mọi toạ độ bị ảo hoá và mọi cú click trượt.
2. **Chụp cửa sổ:** `PrintWindow(hwnd, memDC, PW_RENDERFULLCONTENT=0x2)` → `PrintWindow(hwnd, memDC, 0)`
   → `BitBlt` từ `GetWindowDC(hwnd)`.
3. **Chụp toàn màn hình:** `GetDC(NULL)` + `BitBlt` tại toạ độ **vật lý** của virtual screen.
4. **Kích thước buffer** lấy từ `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS=9)` (dự phòng
   `GetWindowRect`) — nếu không, ảnh crop dính viền đen của bóng DWM.
5. **Bỏ qua** cửa sổ `IsIconic` (thu nhỏ: cả hai đường đều trả đen) và cửa sổ `DWMWA_CLOAKED`.
6. **Chốt chặn khung đen:** lấy mẫu; nếu > 99,5 % điểm đen ⇒ chụp lại vùng màn hình bằng `BitBlt` và
   đánh dấu `occluded`. Không có tín hiệu này thì kết quả `BitBlt` gây hiểu nhầm một cách im lặng.
7. **Kiểm tra bị che:** `WindowFromPoint` tại tâm + 4 góc (lùi 2 px); ≥ 2/5 điểm trả về cửa sổ khác ⇒
   đánh dấu `occluded`.

**Dự phòng WGC** (chỉ khi một cửa sổ liên tục đen, hoặc cần chụp khi bị che): wheel
`windows-capture` 2.0.1 (`cp39-abi3-win_amd64`) hoặc `winrt-Windows.Graphics.Capture` 3.2.1 (`cp313`).
Đây là **phụ thuộc thêm** nên **mặc định không cài**; ghi trong `backend/requirements.runtime.txt`
dưới dạng extra tuỳ chọn.

---

## 4. Điều khiển chuột/phím — thang ba bậc

Mỗi hành động chọn bậc **thấp nhất còn hiệu quả**; bậc càng cao càng xâm lấn.

| Bậc | Cách làm | Ảnh hưởng tới người dùng | Đợt này |
|---|---|---|---|
| **1. UIA pattern** (mặc định) | `Invoke`/`Toggle`/`Value`/`SetValue` trên phần tử đã resolve | không cướp focus, không di chuyển con trỏ | làm |
| **2. `SendInput` foreground** | nâng đúng cửa sổ đích → gửi `[move, down, up]`/phím → khôi phục foreground + vị trí con trỏ | cướp focus trong tích tắc | làm, mỗi lần là một ranh giới takeover phải duyệt |
| **3. `PostMessage` nền** | gửi `WM_*` không cần focus | không | ngoài phạm vi |

Chi tiết bậc 2:

- **Chuột:** `MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK`; chuẩn hoá
  `(x − SM_XVIRTUALSCREEN) × 65535 / (SM_CXVIRTUALSCREEN − 1)` — **số học i64**, vì gốc ảo có thể **âm**;
  gửi một lô `[move, down, up]`.
- **Bàn phím:** `KEYEVENTF_UNICODE` cho từng đơn vị UTF-16 khi gõ văn bản; `MapVirtualKeyW` lấy scan code
  cho phím có tên.
- **Trước mỗi lô:** `GetForegroundWindow()` phải đúng cửa sổ đích; nếu không ⇒ dừng, trả `SOURCE_CHANGED`.
- **Sau mỗi lô:** khôi phục foreground cũ và vị trí con trỏ **của người dùng**.
- **Gửi hụt:** chỉ nhả đúng các phím/modifier **đã** chèn, theo thứ tự ngược; **không** nhả thứ chưa
  chèn và **không** gửi lại cú click/văn bản.
- **Nhả input bị giữ trên mọi đường thoát** (thành công, lỗi, huỷ): theo dõi modifier/button đang giữ và
  gửi sự kiện nhả khi kết thúc; `release_stuck_input()` gọi lúc dừng/khởi động lại để dọn trạng thái cũ.

**Chặn TRƯỚC khi gửi** (chạy trước cả cổng duyệt, không thể bỏ qua):

- `UIPI`: kiểm integrity token của tiến trình đích (`OpenProcess` + `OpenProcessToken` +
  `GetTokenInformation`); đích cao hơn ta ⇒ từ chối kèm thông báo rõ, **không** tự nâng quyền admin.
- `DESKTOP_LOCKED`: `OpenInputDesktop` trả tên khác `"Default"` (màn hình khoá / UAC / secure desktop) ⇒
  từ chối; **không** cố chụp.
- `SESSION_NOT_INTERACTIVE`: tiến trình không ở phiên tương tác của người dùng (Session 0) ⇒ từ chối.
- Ô mật khẩu: UIA `IsPassword` = true ⇒ **từ chối**.
- `_BLOCKED_KEY_COMBOS` + `_BLOCKED_TYPE_PATTERNS` (§7).

### 4.1 Định danh phần tử và chống stale

- **Token phần tử:** `s{snapshot_id:08x}:{index}` — mint theo từng lần snapshot; hành động phải gửi kèm
  token; token thuộc snapshot cũ ⇒ từ chối tường minh `ELEMENT_STALE` kèm hướng dẫn chụp lại, **không
  bao giờ** tự resolve index sang phần tử khác.
- **Registry UIA:** giữ `RuntimeId` + `generation`; ref chỉ hết hạn khi **vắng mặt ở HAI snapshot liên
  tiếp**; `fingerprint = hash(role, label)`; trần **5 000** phần tử.
- **`geometryRevision`** theo cửa sổ/khung; input mang revision cũ ⇒ `SOURCE_CHANGED`.
- **Kiểm tra bị che trước khi click** (bậc 2): `WindowFromPoint` tại đúng điểm phải thuộc cửa sổ đích;
  nếu không ⇒ `SOURCE_CHANGED` lý do `occluded`, **không** gửi input.

---

## 5. Người và agent cùng điều khiển (ADR-0002)

**Quyết định: kết hợp lựa chọn 1 + 2.** "Người chạm ⇒ agent nhả quyền" là hành vi **nhìn thấy được**;
"revision + kiểm lại ngay trước hành động" là hàng rào **kỹ thuật** bên dưới. Một cái cho UX, một cái
cho tính đúng.

1. **Lease có epoch, lưu trên đĩa** — `desktop_lease.json` trong profile:
   `{holder: 'human'|'agent', viewer_id, since, reason, epoch}`. Mọi chuyển chủ **tăng `epoch`**. Đọc
   lỗi/không đọc được ⇒ **fail-closed về `human`** (không có tệp = agent đang giữ; tệp có mà không đọc
   được = về tay người).
2. **Agent phải được cấp lease** trước mọi thao tác, **kể cả chụp màn hình** (người dùng có thể đang gõ
   mật khẩu). Từ chối ⇒ `HUMAN_HAS_CONTROL`.
3. **Hàng rào epoch:** mỗi hành động đã nhận ghi lại `epoch`; **trước khi** gửi input và **trước khi**
   lưu ảnh chụp, kiểm lại `epoch`; lệch ⇒ **vứt bỏ kết quả** với `HUMAN_TOOK_OVER`.
4. **Phát hiện người dùng thật sự chạm máy:**
   - `GetLastInputInfo` (idle toàn hệ thống) lấy mẫu mỗi 250 ms — rẻ, không cần hook;
   - hook `WH_MOUSE_LL` + `WH_KEYBOARD_LL` lọc cờ `LLMHF_INJECTED`/`LLKHF_INJECTED` để **bỏ qua input do
     chính ta tiêm**; sự kiện **không** có cờ injected ⇒ người thật ⇒ tự động chuyển lease về `human`,
     hiện băng "Bạn đang điều khiển" + nút **"Trả quyền cho agent"**;
   - hook `WH_KEYBOARD_LL` bắt `VK_ESCAPE` không-injected ⇒ **huỷ khẩn cấp**; hook **luôn** gọi
     `CallNextHookEx` (không bao giờ nuốt phím Esc của người dùng); cài hook thất bại ⇒ **fail-closed**,
     không cấp quyền điều khiển.
5. **Loại trừ lẫn nhau ở mức HĐH:** mutex kernel đặt tên `Local\BoxFoxDesktopInput-v1` +
   `WaitForSingleObject(handle, 0)`; `WAIT_TIMEOUT` ⇒ `CONTROL_BUSY` (không xếp hàng, không gửi input).
   Mutex chỉ giữ **trong lúc hành động + dọn dẹp**, không giữ suốt hội thoại — mục đích là để hai tiến
   trình BoxFox không tiêm xen kẽ vào nhau.
6. **Huỷ lan tới hành động đang chờ:** nút Dừng / Esc / hết phiên ⇒ tăng `epoch` + `generation`; mọi
   hành động đang chờ kiểm lại trước và sau khi biến đổi; **nhả phím/chuột đang giữ** rồi mới thoát.
7. **Audit phân biệt actor:** mỗi dòng ghi `actor: 'user'|'agent'`, `lease_epoch`, `target`, `revision`,
   `outcome`, `verified`. UI hiện nhật ký này.
8. **UI:** băng trạng thái quyền, nút Dừng khẩn, nút Trả quyền, cảnh báo khi lease đang ở `human` mà
   agent xin lại quyền.

---

## 6. Thang xác minh và mã lỗi

### 6.1 Kết quả một hành động

```
{ ok: bool,            # chỉ nghĩa "đã gửi được", KHÔNG phải "đã thành công"
  action, target, route: 'uia_pattern'|'send_input'|'refused',
  effect: 'confirmed'|'partial'|'unverifiable'|'suspected_noop'|'refused',
  verified: true|false|null,     # đọc lại trạng thái qua UIA/AX
  escalation: {recommended: 'none'|'foreground'|'manual', reason},
  code, note, lease_epoch, geometry_revision }
```

- **Xác minh là công cụ riêng:** `verify_state(target, expect)` — **2 mẫu ổn định liên tiếp**; chỉ thoả ở
  mẫu cuối ⇒ `unknown`.
- **Không bao giờ tự thử lại** hành động `partial`/`unverifiable`/`suspected_noop`: phải quan sát lại
  trạng thái mới.
- **Chụp lại chỉ khi hành động thành công** — ảnh chụp sau một hành động hỏng trông vẫn bình thường và
  sẽ gợi ý sai rằng nó đã thành công.
- **Chống lặp ảnh:** băm sha256 theo (phiên, đích); trùng liên tiếp ≤ 2 lần ⇒ gắn `screen_unchanged`.

### 6.2 Mã lỗi

`ELEMENT_STALE`, `SOURCE_CHANGED`, `SOURCE_IDENTITY_UNAVAILABLE`, `CONTROL_BUSY`, `DESKTOP_LOCKED`,
`OS_PERMISSION_REQUIRED`, `HUMAN_HAS_CONTROL`, `HUMAN_TOOK_OVER`, `UIA_UNAVAILABLE`, `UIA_TIMEOUT`,
`UIPI_BLOCKED`, `SESSION_NOT_INTERACTIVE`, `APPROVAL_DENIED`, `APPROVAL_DENIAL_BREAKER`,
`UNSUPPORTED_IN_HOST_MODE`.

---

## 7. Cổng an toàn CUA

1. `computer_use` **tắt mặc định**; bật phải qua một bước xác nhận riêng, có văn bản nói rõ rủi ro.
2. **Mặc định duyệt từng hành động.** Phạm vi nhớ: `once` | `session` | `theo ứng dụng này` (`app_grant`
   lưu `exe` + `aumid`). **Không có "luôn cho phép" vĩnh viễn cho CUA** — khác luật shell/tệp. `session`
   không còn nghĩa "cả phiên với mọi cửa sổ": `resource_key` hẹp theo **đích của phiên** (§7.1), nên
   "cho phép trong phiên" cho Notepad không mở đường cho Chrome. Xoá đích ⇒ quên grant của phiên.
3. **Chặn cứng tổ hợp phím** (`_BLOCKED_KEY_COMBOS`): khoá máy/đăng xuất (`Win+L`), Task Manager
   (`Ctrl+Shift+Esc`), `Ctrl+Alt+Del`, `Alt+F4` khi đích là hộp thoại hệ thống; và **không bao giờ** tương
   tác với `consent.exe` (UAC) hay cửa sổ bảo mật của HĐH.
4. **Không bao giờ gõ** mật khẩu/khoá API/số thẻ (chặn bằng UIA `IsPassword` + `_BLOCKED_TYPE_PATTERNS`),
   không bấm hộp thoại xin quyền — luật này nằm trong system prompt của vai trò **và** trong sàn cứng của
   công cụ.
5. **Ảnh chụp là dữ liệu không tin được** (`integrity: khong_tin_duoc`) — hàng rào chống
   prompt-injection qua màn hình.
6. **Nút Dừng khẩn** (UI + tray + Esc vật lý) — dừng hành động đang chờ, nhả phím/chuột đang giữ, đưa
   lease về `human`.
7. **Nói thẳng trong tài liệu:** bật CUA nghĩa là agent có quyền chuột/phím của người dùng; ảnh chụp đi
   vào hội thoại nên có thể chứa dữ liệu nhạy cảm.

### 7.1 Đích CUA của phiên (một máy, một đích)

Người dùng chọn đích **một lần cho cả phiên** ở panel Máy, không phải theo từng lời gọi. Đích là một
trong hai:

| Đích | Khi nào | Hệ quả |
|---|---|---|
| `{kind:'window', windowId, pid, title, processName}` | `scope = workspace` mà chưa chọn gì ⇒ `TARGET_REQUIRED`; hoặc người dùng chọn một cửa sổ | agent chụp/gõ vào **đúng cửa sổ đó**; hwnd chết hoặc bị tái dùng (pid khác) ⇒ tìm lại theo `processName` + tiêu đề, không thấy ⇒ `TARGET_UNKNOWN` |
| `{kind:'machine'}` | chỉ khi `scope = machine` | agent chụp cả màn hình ảo và được **tự mở ứng dụng** khi `app` chưa chạy (folder tin cậy, chờ ≤ 10 s) |

- Lưu ở `sessions.config`: `cuaTarget`, `cuaTargetRevision`, `cuaTargetSetBy`, `cuaTargetAt`. **Phiên con
  đọc và ghi cùng hàng với phiên gốc** — subagent không có đích riêng, cả hai không bao giờ lệch nhau.
- Ba route: `GET|PUT|DELETE /api/agent/machines/target`. `PUT` đòi `consent: true` (người dùng tự chọn),
  nhận `expectedRevision` để chống ghi đè, và trả `CUA_MACHINE_SCOPE_REQUIRED` khi `scope = workspace` mà
  xin đích cả máy.
- Chưa chọn gì: `scope = machine` ⇒ cả máy (giữ nguyên hành vi cũ); `scope = workspace` ⇒ `TARGET_REQUIRED`.
- Lời gọi có `app`/`window` dùng đè cho **một lời gọi đó** rồi ghi lại vào phiên với `cuaTargetSetBy =
  'agent'`; panel thấy `requestedBy = agent` và đi theo. Hai cửa sổ cùng khớp ⇒ `TARGET_AMBIGUOUS` kèm
  `candidates` để model tự chọn, **không** mở thêm bản sao của ứng dụng đang chạy.
- Đích cả máy không ghim cửa sổ nào (`_input_target` dùng toạ độ trong ảnh chụp); đích cửa sổ thì ghim.
- **Viền xanh** (`cua_overlay.py`): hiện quanh cửa sổ agent đang thao tác, tự ẩn sau 15 s không hoạt động,
  ẩn ngay khi người dùng giữ quyền (§5), khi xoá đích hoặc khi phiên dọn dẹp. Nền tảng lỗi ⇒ **tắt êm**,
  không chặn CUA; `BOXFOX_CUA_OVERLAY=0` để tắt hẳn.

---

## 8. Giới hạn đã biết của bản alpha

| Giới hạn | Hệ quả | Ghi chú |
|---|---|---|
| Không có sandbox HĐH | agent có quyền của người dùng | bù bằng chính sách + §7 |
| Màn hình khoá / UAC / secure desktop | từ chối | `DESKTOP_LOCKED`; **không** cố chụp |
| Session 0 (chạy qua SSH) | không có desktop tương tác | `SESSION_NOT_INTERACTIVE`; app luôn chạy trong phiên người dùng |
| Tiêm nền `PostMessage` | chưa có | bậc 3 ngoài phạm vi |
| Cửa sổ DirectComposition/UWP/WinUI3 | có thể đen | chốt chặn khung đen + dự phòng WGC tuỳ chọn |
| DRM / HDR / đổi virtual desktop | không hỗ trợ | ngoài phạm vi |
| Console ARM64 | gõ chữ có thể không tới | `text_input_unsupported` |
| UIA provider treo (SAL/VCL/Chromium) | treo cả lần soi | watchdog mỗi lời gọi UIA, không chạy trên luồng input |
| Nhiều màn hình, DPI khác nhau | toạ độ sai nếu ảo hoá | pixel vật lý end-to-end + gốc ảo có dấu |

---

## 9. Nền tảng thứ hai: Linux/X11 (bổ sung 08/10/2026)

Trước mục này, `build_desktop_control()` chỉ dựng nền tảng khi `sys.platform == 'win32'`, nên **mọi
công cụ CUA trả `CUA_UNAVAILABLE` trên Linux** và bảng "Machine screen" không có gì để hiện. Gói
`sandbox/x11` bổ sung nền tảng thứ hai; hợp đồng duck-typed của `desktop_control` không đổi.

### 9.1 Bản đồ mô-đun

| Tệp | Việc | Công cụ ngoài |
|---|---|---|
| `backend/src/agentbox/sandbox/x11/platform.py` | liệt kê cửa sổ (EWMH), hình học, danh tính, tiêu điểm, mutex `flock`, `launch_app` | `xprop`, `xwininfo`, `xdotool` |
| `backend/src/agentbox/sandbox/x11/capture.py` | `import -window <id>` → `bgra:-`; dự phòng chụp theo vùng màn hình; dùng lại toàn bộ hàm thuần của `win/capture.py` | ImageMagick `import` |
| `backend/src/agentbox/sandbox/x11/input.py` | chuột/phím qua XTEST, bốn chốt chặn như bản Windows | `xdotool` |
| `backend/src/agentbox/sandbox/x11/__init__.py` | xuất `PlatformError` **từ `win/errors.py`** — Linux dùng chung bộ mã lỗi, không có mã riêng | — |

`X11Platform` nhận `runner` tiêm vào, nên bài kiểm chạy được trên máy không có X server
(`backend/tests/unit/test_x11_platform.py`).

### 9.2 Chọn nền tảng

`HostExecutor._desktop_family()` trả `'windows'`/`'x11'` theo **`self.platform`** (chuỗi tiêm được),
không theo `sys.platform` — nhờ vậy bộ test giả-Windows vẫn chạy trên Linux. `api/server.py` chọn
`win.windows_platform` hay `x11.platform` theo `sys.platform` thật.

### 9.3 Khác biệt so với Windows (có chủ đích)

| Điểm | Windows | Linux/X11 | Vì sao |
|---|---|---|---|
| Phát hiện người chạm chuột/phím | hook `WH_MOUSE_LL`/`WH_KEYBOARD_LL`, `LLMHF_INJECTED` | **lấy mẫu** con trỏ + cửa sổ có tiêu điểm mỗi 1 s | X11 không có cờ "do XTEST sinh ra"; hook luôn báo "người" sẽ tự nhả lease ngay sau cú bấm của agent |
| Nhả lease khi người chen vào | tự động, tức thời | tự động, chậm ≤ 1 s; **không thấy bàn phím** | hệ quả của dòng trên — xem §9.4 |
| `poll_idle()` | `GetLastInputInfo` | `X11Platform.last_input_tick()` — bộ đếm của chính ta | không có nguồn "lần cuối người tương tác" của hệ thống |
| Cửa sổ tại một điểm | `WindowFromPoint` | thử hình học theo Z-order của `_NET_CLIENT_LIST_STACKING` | không cần thêm thư viện; viền báo của BoxFox (override-redirect) không nằm trong danh sách nên không che đích |
| Menu/tooltip override-redirect ngay trên điểm bấm | `WindowFromPoint` thấy | **không thấy** | chúng không có trong `_NET_CLIENT_LIST_STACKING`, nên `check_point_ownership` vẫn cho qua. Lỗ đã biết; vá cần phép thử điểm ảnh theo cây cửa sổ (`xwininfo -root -children`) |
| Cửa sổ bị che | `PrintWindow` đọc được pixel riêng | chụp vùng màn hình, gắn `occluded=True` + `notes` | X11 không có tương đương `PrintWindow` |
| Màn hình khoá | `DESKTOP_LOCKED` | luôn `False` | X11 không có khái niệm tương đương ở tầng này |
| DPI / nhiều màn hình | pixel vật lý, DPI theo cửa sổ | một màn hình ảo, DPI luôn 96 | X11 hợp nhất mọi output thành một toạ độ |
| Viền báo vùng bị điều khiển | cửa sổ overlay riêng | **chưa có** trên desktop; viền trong panel vẫn hiện | ngoài phạm vi đợt này |

Viền báo trên desktop là việc còn lại của nền tảng Linux, không phải "đã xong".

### 9.4 Người thật chạm máy (quyết định #6785)

Windows biết người vừa chạm máy nhờ cờ `LLMHF_INJECTED` của hook. X11 không có tín hiệu đó, nên
`X11Platform.last_input_tick()` **lấy mẫu** hai thứ, mỗi lần `poll_idle()` gọi:

* vị trí con trỏ (`xdotool getmouselocation`), và
* cửa sổ đang có tiêu điểm (`xprop -root _NET_ACTIVE_WINDOW`).

Bộ đếm tăng khi một trong hai đổi **mà không phải do ta vừa đặt** (`note_own_pointer()`,
`set_foreground_window()`, `set_cursor_pos()` đều ghi lại việc của chính mình). Nhờ vậy cú bấm của
agent không tự huỷ quyền của nó — điều tệ nhất có thể xảy ra với một cơ chế tự nhả quyền.

Harness chạy vòng lấy mẫu này (`api/server.py`, `idle_watch`, nhịp 1 s, trong luồng riêng) **chỉ khi**
nền tảng khai báo `supports_idle_watch` — X11 khai báo, Windows thì không, nên hành vi Windows đang
chạy thật không đổi.

Giới hạn phải nói rõ: **không thấy bàn phím** (gõ phím mà không đụng chuột thì không phát hiện được),
và **có thể báo nhầm** khi một ứng dụng khác tự đổi tiêu điểm (cửa sổ mới mở đòi focus, thông báo,
trình quản lý cửa sổ). Hướng báo nhầm là hướng an toàn: quyền về tay người, agent phải xin lại.

### 9.5 Gói phải cài trên máy Linux

`xdotool`, `xprop`, `xwininfo` (gói `x11-utils`), ImageMagick (`import`). Thiếu gói nào thì lời gọi
trả lỗi **nêu đúng tên gói** (`CUA_UNAVAILABLE` / `CAPTURE_FAILED` với `details.tool`), không im lặng
trả ảnh rỗng. `get_platform()` trả `None` khi không có `DISPLAY`/`WAYLAND_DISPLAY`, **hoặc** khi X
server không trả lời (kích thước màn hình ảo 0×0) — máy không có desktop thì CUA tắt, đúng như trước.

Phiên **Wayland**: nếu có `WAYLAND_DISPLAY`, `notes()` nói thẳng rằng chỉ thấy được cửa sổ
X11/XWayland; ứng dụng Wayland thuần không hiện trong danh sách và không nhận được XTEST.
