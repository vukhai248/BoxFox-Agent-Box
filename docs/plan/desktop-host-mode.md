# Kế hoạch — Host mode: chạy BoxFox trực tiếp trên máy người dùng

> **Cập nhật quyền 2026-10-10:** hợp đồng mới đã được owner duyệt ở [desktop-permission-levels-2026-10-10.md](desktop-permission-levels-2026-10-10.md), thay bảng 4 mode × Scope file riêng ở dưới. Ba mức, Network độc lập; CUA không tự đổi boundary/grants khi đổi mức file.

> **Trạng thái:** Đã được duyệt và đang triển khai. H1–H4 (động cơ quyền, HostExecutor, API) đã có
> trong `vorflux/desktop-host-mode`; H5–H7 (CUA Windows) và D1–D5 (app Electron, bộ cài) đang làm.
>
> **Ngày:** 2026-10-06. **Nhánh:** `vorflux/desktop-host-mode` (PR-1) → `vorflux/desktop-alpha` (PR-2).
>
> **Kế hoạch nguồn:** `docs/plan/v1-machine-environments-roadmap.md` §13.1, §15.1–§15.6, §17.1–§17.3
> (chặng D1–D4) + phần CUA §6.2, §6.3, §7, §8. Chỗ nào tài liệu này và kế hoạch nguồn lệch nhau thì
> **kế hoạch nguồn thắng**.
>
> **Hợp đồng CUA:** `docs/architecture/host-desktop-control.md`. **Cách chạy test:**
> `docs/testing/desktop-host-mode.md`.

---

## 1. Vì sao có host mode

Bản alpha phải cài được bằng **một tệp `.exe`** trên Windows 11 x64 và dùng được **ngay**: không cần
Node, không cần Python, không cần Conda, không cần checkout mã nguồn, **không cần Docker**. Đó là
điều kiện để chủ nhà và người dùng thử được sản phẩm mà không phải dựng cả một môi trường.

Hệ quả kỹ thuật: harness phải có **hai executor** sau cùng một hợp đồng `execute(...)`.

| Chế độ | Executor | Máy chạy lệnh | Khi nào dùng |
|---|---|---|---|
| `docker` (mặc định, hành vi cũ) | `sandbox/executor.py` | box Ubuntu/XFCE trong Docker | máy đã có Docker; giữ nguyên mọi thứ đang chạy |
| `host` | `sandbox/host_executor.py` | chính máy đang chạy harness | bản alpha trên máy người dùng, không Docker |
| `cloud` | — | — | **chưa cài đặt**: `BOXFOX_EXECUTION_MODE=cloud` báo lỗi rõ, không im lặng rơi về `docker` |

Chọn chế độ bằng biến `BOXFOX_EXECUTION_MODE`; giá trị lạ (gõ sai) ⇒ mặc định `docker`. Mặc định
**không đổi hành vi cũ**: ai chỉ cài bản cập nhật thì mọi thứ chạy y như trước.

### 1.1 Giới hạn đã biết — đọc trước khi bật

Host mode **không có sandbox cấp hệ điều hành**. Agent chạy bằng quyền của chính người dùng, nên một
lệnh sai có thể xoá tệp thật của người dùng. Ta **không** che giấu điều này; ta bù bằng chính sách
(§3): mặc định `ask`, sàn cứng, phạm vi ghi, và CUA tắt mặc định. Windows sandbox (restricted token +
ACL + WFP như Codex) là việc của đợt sau.

---

## 2. Hợp đồng `HostExecutor`

`HostExecutor` cài đúng hợp đồng mà `SandboxExecutor` đã hứa, nên `HarnessRuntime` và mọi chỗ gọi
không phải rẽ nhánh theo chế độ:

```
execute(name, args, session, turn=None, step=None, tool_call_id=None, root=None) -> dict
cleanup(session) -> None
visual_lock: asyncio.Lock      # giữ tên để chỗ gọi cũ không phải đổi
```

- **Công cụ v1:** `file_read`, `codebase_glob`, `codebase_grep`, `file_write`, `file_edit_block`,
  `terminal_exec`.
- **Công cụ chưa hỗ trợ** ⇒ kết quả có mã `UNSUPPORTED_IN_HOST_MODE` (không ném, không giả vờ thành
  công). Danh sách này gồm 15 công cụ của box (`browser_use`, `computer_screen_record`, `verify_exec`,
  `write_plan`, `dossier_write`, `design_*`, `session_ensure`, `journal_append`, `checkpoint_write`,
  `captures_prune`, `codebase_symbols`).
- **Khuôn payload y hệt `worker.py`** của box — cùng tên trường, cùng cách trả lỗi
  (`{'is_error': True, 'errorCode': ..., 'error': ...}`) — để model và frontend không phải học API thứ hai.
- **Giải đường dẫn:** mọi đường dẫn tương đối neo vào workspace; `..`, đường dẫn tuyệt đối ngoài
  workspace và **symlink trỏ ra ngoài** đều trả `PATH_OUTSIDE_WORKSPACE` sau `Path.resolve()`.
- **`terminal_exec`:** chạy trong process group riêng, timeout kẹp trong 1–120 giây, hết giờ thì giết
  **cả nhóm** (`COMMAND_TIMEOUT`); output > 20 000 ký tự tràn ra
  `.generated_artifacts/tools/<hash>.txt`, giữ 15 000 ký tự xem trước.
- **Shell:** Windows dùng `powershell.exe` (ưu tiên `pwsh.exe` nếu có) với
  `-NoProfile -NonInteractive -OutputFormat Text`; POSIX dùng `/bin/sh -c`. Biến con đặt
  `PYTHONIOENCODING=utf-8`, `PYTHONUTF8=1`.

---

## 3. Hợp đồng quyền

Động cơ nằm ở harness (`agent_core/permissions.py`), **không** ở model: model chỉ thấy kết quả
`allow` / `ask` / `deny` kèm lý do.

### 3.1 Bảng quyết định (mode × loại công cụ)

| `mode` | đọc | ghi | chạy lệnh | CUA |
|---|---|---|---|---|
| `plan` | cho | **không** | **không** | **không** |
| `ask` (mặc định) | cho | hỏi | hỏi | hỏi |
| `auto` | cho | cho | cho | hỏi |
| `trusted` | cho | cho | cho | cho |

`scope` (`workspace` | `machine`, mặc định `machine`) chỉ siết thêm: khi `scope=workspace`, **đọc**
và **ghi** ngoài workspace đều phải hỏi, bất kể `mode`.

Luật trong tệp **thắng bảng trên**, theo thứ tự **`deny` > `ask` > `allow`**, khớp đầu tiên thắng;
`deny` ở **bất kỳ tầng nào** cũng thắng `allow` ở tầng khác.

### 3.2 Ngữ pháp luật

```
Tool(specifier)
```

- `Tool` là tên công cụ (`terminal_exec`, `file_read`, `file_write`, `file_edit_block`, `codebase_glob`,
  `codebase_grep`, `web_fetch`, `computer_use`, `computer_screen_capture`, `inspect_element`).
- `specifier` tuỳ họ công cụ:
  - **lệnh:** khớp tiền tố theo từ, `npm run *` khớp `npm run build` nhưng **không** khớp `npm install`;
    `ls:*` là dạng tiền tố cũ; cả hai phía đều được chuẩn hoá (bóc wrapper `powershell -Command`,
    `cmd /c`, `bash -c`, `timeout`, `nice`; gộp khoảng trắng; bỏ đuôi `.exe/.cmd/.bat/.ps1/.com`; đổi
    alias PowerShell `ls→get-childitem`, `rm→remove-item`, `curl→invoke-webrequest`…).
  - **đường dẫn:** bốn neo — `//abs` (tuyệt đối), `~/`, `/nguồn` (tương đối gốc workspace), `cwd`;
    glob kiểu gitignore rút gọn; `..` bị triệt tiêu trước khi so.
  - **miền:** `domain:*.example.com` (wildcard chỉ ở giữa hai dấu chấm).
- **Ngoặc** trong specifier được hiểu là văn bản, không phải cú pháp.
- Lệnh ghép bị **tách** theo `|`, `;`, `&&`, `||`, `&`, xuống dòng (tôn trọng nháy) và mỗi lệnh con
  thành một luật riêng, tối đa **5**; quá 5 thì chỉ nhớ theo phiên.

### 3.3 Nơi lưu

| Tầng | Đường dẫn | Ghi chú |
|---|---|---|
| `managed` | `<thư mục cài>/managed-settings.json` | thắng tất cả; UI không sửa được |
| `profile` | `<profile>/permissions.json` | hồ sơ BoxFox (`BOXFOX_AGENT_DATA_DIR`) |
| `user` | `%USERPROFILE%\.boxfox\settings.json` | luật của riêng user; đích ghi của `PUT /api/agent/permissions` |
| `project` | `<workspace>\.boxfox\settings.local.json` | **đích auto-save** của "Cho phép và đừng hỏi lại" |

`deny > ask > allow`; tệp JSON hỏng ⇒ tầng đó coi như rỗng, lỗi đọc được báo trong `errors` của
snapshot, **không** làm hỏng quyết định. Ghi luật là ghi nguyên tử (`.tmp` + `os.replace`).

### 3.4 Kiểm tra phạm vi trước khi lưu (rào của Codex + Hermes)

Harness **từ chối** lưu luật `allow` vĩnh viễn nếu:

1. **Tiền tố bị cấm** — luật mở đường cho cả một trình thông dịch: `cmd`, `cmd /c`, `cmd.exe`,
   `powershell`, `powershell -Command`, `pwsh`, `pwsh -c`, `bash`, `bash -c`, `wsl`, `wsl.exe`,
   `node -e`, `python -c`, `python3 -c`. Kiểm **cả** dạng thô **lẫn** dạng đã bóc wrapper.
2. **Mô phỏng thấy quá rộng** — luật ứng viên chạy trên bộ lệnh mẫu; nếu nó phê duyệt ≥ 3 họ lệnh
   khác nhau ⇒ từ chối (`TOO_BROAD`).
3. **Lệnh ghép quá dài** ⇒ `COMPOUND_TOO_WIDE`, chỉ nhớ theo phiên.
4. Luật chỉ được phê duyệt **đúng thứ đã hiện trên thẻ duyệt** — không rộng hơn. Đường dẫn tuyệt đối
   lưu ở neo `//abs` vì lý do này.
5. **CUA không có luật vĩnh viễn** ⇒ `CUA_NOT_PERSISTED` (phạm vi chỉ `once` | `session` | `app_grant`).

### 3.5 Sàn cứng — không chế độ nào bỏ qua được

Chạy **trước** mọi danh sách luật, kể cả `trusted`; soi **từng lệnh con** với mẫu neo ở đầu lệnh nên
`echo shutdown /r` không bị chặn oan, còn `git status && shutdown /r` thì bị:

`format_drive` (`format`), `diskpart`, `bcdedit`, `delete_shadow_copies` (`vssadmin delete shadows`),
`delete_drive_root` (`Remove-Item -Recurse -Force` vào gốc ổ), `delete_windows_dir`, `write_hklm`
(ghi đè registry HKLM), `shutdown`, `disable_defender` (`Set-MpPreference -DisableRealtimeMonitoring`),
`disable_firewall` (`netsh advfirewall set * state off`), `fork_bomb`.

Mỗi mục có unit test riêng, chạy cả ở `trusted` (`tests/unit/test_permissions.py`).

### 3.6 Phiên, ngắt mạch, audit

- **Phạm vi nhớ:** `once` | `session` | `always` (ghi luật vào tầng `project`).
- **Key phiên:** `{tool}|{lệnh canonical}|{cwd}|{scope}|{mode}` — không phải tên công cụ.
- **Ngắt mạch:** 3 lần từ chối liên tiếp ⇒ dừng hỏi, trả mã `APPROVAL_DENIAL_BREAKER`.
- **Thu hồi:** `DELETE /api/agent/permissions/rules` (tab Settings → Quyền liệt kê từng luật **kèm tệp
  nguồn**), có hiệu lực từ lần gọi kế tiếp.
- **Audit:** `permissions-audit.jsonl` trong profile — mỗi dòng `{rule, scope, tool, command, decision,
  actor, timestamp, session_id}`; ghi best-effort, hỏng đĩa không làm hỏng quyết định.

---

## 4. API

| Route | Việc |
|---|---|
| `GET /api/agent/permissions` | snapshot: mode, scope, capabilities, 4 tầng + tệp, luật hợp nhất kèm nguồn, số mục sàn cứng, đếm va sàn cứng, tệp audit |
| `PUT /api/agent/permissions` | đổi `mode`/`scope`, ghi xuống `layer` (mặc định `user`) |
| `POST /api/agent/permissions/decide` | hỏi quyết định; kèm `decision` (`allow`/`allow_session`/`allow_always`/`deny`) để chốt |
| `GET /api/agent/permissions/pending` | thẻ duyệt đang chờ |
| `GET /api/agent/permissions/rules` | luật + tệp nguồn |
| `DELETE /api/agent/permissions/rules` | thu hồi một luật |
| `GET\|PUT\|DELETE /api/agent/machines/target` | đích CUA của phiên (§7.1 `host-desktop-control.md`): đọc/đặt/xoá, `consent`, `expectedRevision`, cổng `scope` |
| `POST /api/agent/machines/screen` | `{kind:'window'}` như cũ; `{kind:'machine'}` chụp cả màn hình ảo, trả `captureOrigin`/`captureSize` |
| `GET /api/agent/health` | thêm khối `execution`: `mode`, `configured`, `scope`, `permissionMode`, `policy`, `cuaEnabled`, `lease`, `hardlineHits`, `workspace` |

Mọi route đi qua đúng hàng rào sẵn có của harness: `Host` phải nằm trong allowlist **và** request phải
có `X-BoxFox-Admin: 1` cùng `Origin` hợp lệ. Chế độ `docker` không có động cơ quyền ⇒ các route trả
`409 PERMISSIONS_UNAVAILABLE` (lỗi có mã, không phải 500).

---

## 5. Đầu việc

| Mã | Việc | Tệp chính | Trạng thái |
|---|---|---|---|
| H1 | Tài liệu thiết kế + hợp đồng + ADR-0002 | `docs/plan/desktop-host-mode.md`, `docs/architecture/host-desktop-control.md`, `docs/testing/desktop-host-mode.md`, ADR-0002 | xong |
| H2 | Động cơ quyền | `agent_core/permissions.py`, `tests/unit/test_permissions.py` | xong |
| H3 | HostExecutor | `sandbox/host_executor.py`, `tests/unit/test_host_executor.py` | xong |
| H4 | Chọn chế độ + API quyền | `api/server.py`, `tests/unit/test_permissions_api.py` | xong |
| H5 | Nền tảng Windows: capture/input/UIA | `sandbox/win/*.py` | đang làm |
| H6 | Select element ba nhánh | `agent_core/inspect_host.py` | đang làm |
| H7 | Lease/epoch/mutex/token/thang xác minh | `agent_core/desktop_control.py` | chờ H5/H6 |
| H5b | Đích CUA theo phiên: kiểu, kiểm lại hwnd, phân giải `app`/`window`, khởi chạy ứng dụng | `agent_core/cua_target.py`, `sandbox/win/windows_platform.py` | xong (kiểm trên Linux) |
| H6b | Route đích + ảnh cả máy cho panel | `sandbox/machine_router.py`, `api/server.py` | xong (kiểm trên Linux) |
| H7b | Viền báo vùng đang bị điều khiển | `agent_core/cua_overlay.py`, `sandbox/win/windows_platform.py` | xong (kiểm trên Linux) |
| D1 | Khung Electron + bundle runtime | `desktop/**` | đang làm |
| D2 | Supervisor + gateway + profile | `desktop/src/**` | đang làm |
| D3 | Tray + diagnostics + bộ cài NSIS | `desktop/**` | chờ D1/D2 |
| D4 | Tài liệu + checklist nghiệm thu cho chủ nhà | `docs/plan/*`, README bộ cài | chờ |
| D5 | UI chọn chế độ + quyền + CUA | `frontend/src/**` | chờ |

---

## 6. Tiêu chí nghiệm thu (PR-1)

1. `BOXFOX_EXECUTION_MODE` không đặt hoặc gõ sai ⇒ chạy `docker` y như trước; `=cloud` ⇒ lỗi rõ.
2. `=host` ⇒ health trả `execution.mode = 'host'` và `policy = true`.
3. Ở `plan`, mọi lệnh ghi/chạy bị từ chối **có mã**; ở `ask`, không có `approver` thì **đóng**
   (fail closed), không tự cho qua.
4. Sàn cứng chặn được cả khi `trusted`, và **không** chặn oan `npm run format` / `echo shutdown /r`.
5. Luật `allow` không lưu được nếu mở đường cho trình thông dịch, quá rộng, hoặc rộng hơn thẻ đã hiện.
6. `..`/symlink không thoát được workspace.
7. Ba lần từ chối liên tiếp ⇒ `APPROVAL_DENIAL_BREAKER`.
8. `permissions-audit.jsonl` có dòng cho mỗi quyết định, phân biệt `actor` user/agent.
9. Test: `test_permissions.py` (47 ca), `test_host_executor.py` (34 ca), `test_permissions_api.py` (22 ca)
   — tất cả xanh; không ca nào chạm `~/.boxfox` thật.
10. Đích CUA của phiên: `scope = machine` + chưa chọn ⇒ cả máy; `scope = workspace` + chưa chọn ⇒
   `TARGET_REQUIRED`; đặt cả máy ở `workspace` ⇒ `CUA_MACHINE_SCOPE_REQUIRED`; `PUT` thiếu `consent` ⇒
   `TARGET_CONSENT_REQUIRED`; xoá đích ⇒ grant của phiên bị quên; thẻ duyệt CUA **không** có "luôn cho phép".
11. Viền xanh: hiện quanh cửa sổ agent thao tác, ẩn khi người dùng giữ quyền / hết 15 s / xoá đích / phiên
   dọn dẹp; lỗi cửa sổ viền ⇒ tắt êm, CUA vẫn chạy.

---

## 7. Điều **không** làm ở đợt này

- **Sandbox cấp HĐH trên Windows** (restricted token + ACL + WFP) — bù bằng chính sách §3, ghi rõ là
  giới hạn đã biết.
- **Nhúng terminal ConPTY** — đợt này dùng nút mở PowerShell thật.
- **`browser_use` trên host** — cần bridge tới trình duyệt của user.
- **Bậc 3 của tiêm input** (`PostMessage` nền) — ma trận "silent drop" quá rộng.
- **Chế độ `cloud`.**
