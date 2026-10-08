# Kiểm thử — Host mode và điều khiển desktop

> **Ngày:** 2026-10-06. **Kế hoạch nguồn:** `docs/plan/desktop-host-mode.md`.
> **Hợp đồng:** `docs/architecture/host-desktop-control.md`.

---

## 1. Chạy nhanh

Mọi lệnh chạy từ `backend/` của repo, dùng venv của máy:

```bash
cd backend
TMPDIR=/var/tmp PYTHONPATH=src python -m pytest -q -p no:cacheprovider \
  tests/unit/test_permissions.py tests/unit/test_host_executor.py tests/unit/test_permissions_api.py
```

Ba tệp đó phủ: động cơ quyền (47 ca), executor host (34 ca), API quyền (22 ca). Không ca nào chạm
`~/.boxfox` thật, không ca nào chạy lệnh phá hoại — mọi thứ nằm trong `tmp_path` của pytest.

**Đừng dùng `--timeout`**: plugin đó không có trong venv và sẽ làm cả lượt chạy đỏ vì lý do không liên
quan tới mã đang kiểm.

---

## 2. Kiểm thử tầng nền tảng Windows trên máy Linux

Máy phát triển là Linux, nên **không** chạy được `ctypes` của Windows. Cách giữ bằng chứng:

1. **Lớp nền tảng mỏng** (`sandbox/win/*.py`) chỉ gọi DLL; **logic thuần** (lease, epoch, token, thang
   xác minh, luật, chốt chặn) nằm ở `agent_core/`.
2. Unit test **tiêm nền tảng giả**: một lớp giả trả kết quả của `GetLastInputInfo`, `WindowFromPoint`,
   `ElementFromPoint`, `SendInput`… để kiểm **quyết định** thay vì kiểm DLL.
3. Những gì còn lại (chụp thật, tiêm thật, UIA thật) do **chủ nhà kiểm ở D4** trên máy Windows — checklist
   ở §5.

Nguyên tắc: nếu một hành vi chỉ chứng minh được bằng mắt trên Windows, nó **không** được coi là đã kiểm
trong PR; nó nằm trong checklist D4.

---

## 3. Kiểm thử động cơ quyền

`tests/unit/test_permissions.py` — dựng workspace/home/install/profile trong `tmp_path`, ghi luật bằng
`write_layer()`. Các nhóm ca:

| Nhóm | Ca đại diện |
|---|---|
| Ngữ pháp luật | ngoặc trong specifier là văn bản; `npm run *` khớp `npm run build`, **không** khớp `npm install`; `ls:*`; khớp toàn văn `git status` |
| Chuẩn hoá | alias PowerShell (`gci` ↔ `Get-ChildItem`); hoa/thường; bóc `powershell -Command`, `cmd /c`; `split_commands` giữ `|` trong nháy |
| Đường dẫn | bốn neo `//abs` / `~/` / `/nguồn` / `cwd`; `..` không thoát; wildcard `domain:` chỉ ở giữa hai dấu chấm |
| Thứ tự | `deny` > `ask` > `allow`; `deny` ở tầng nào cũng thắng; `managed` không bị `project` ghi đè; tệp thắng biến môi trường |
| Bảng mode × scope | `plan` chỉ đọc; `ask` hỏi ghi/chạy; `auto` cho trong workspace, hỏi ngoài; `trusted` cho `exec` nhưng vẫn chặn sàn cứng |
| Sàn cứng | 10 ca `parametrize`, chặn cả ở `trusted`; sống sót qua luật `allow` + wrapper; **không** bắn oan `npm run format`, `git commit -m "reformat"`, `echo shutdown /r` |
| Phiên | nhớ theo key; lệnh khác nhau không lây; ngắt mạch 3 lần; `once` không nhớ |
| Lưu luật | chặn trình thông dịch; chặn would-approve-all; lệnh ghép tách thành luật con; quá 5 phần ⇒ `COMPOUND_TOO_WIDE`; CUA ⇒ `CUA_NOT_PERSISTED`; thu hồi được |
| Audit | 2 dòng cho 2 quyết định; đĩa hỏng không làm hỏng quyết định; tầng JSON hỏng được báo mà không ném |

**Ca âm quan trọng nhất:** `echo shutdown /r` và `git commit -m "reformat"` **phải** đi qua. Sàn cứng
khớp không neo từng làm hai lệnh này bị chặn oan — mỗi lần sửa `HARDLINE` phải chạy lại nhóm này.

---

## 4. Kiểm thử executor và API

`tests/unit/test_host_executor.py` — công cụ ngoài `HOST_TOOLS` trả `UNSUPPORTED_IN_HOST_MODE`; `plan` ⇒
`PERMISSION_DENIED`; sàn cứng ⇒ `layer='hardline'`; `ask` không có approver ⇒ **đóng**; `allow_session`
bỏ câu hỏi thứ hai; `allow_always` ghi luật vào tầng project; 3 lần từ chối ⇒ ngắt mạch; approver ném ⇒
từ chối. Kèm `file_read`/`file_write`/`file_edit_block`, chặn `..`/tuyệt đối ngoài workspace/symlink,
glob/grep, `terminal_exec` (timeout, spill artifact), `shell_argv` hai nền tảng, `cleanup`, `_child_env`.

`tests/unit/test_permissions_api.py` — gọi route THẬT qua aiohttp (`TestServer`):

- `execution_mode()`: mặc định `docker`; giá trị lạ ⇒ `docker`; `cloud` ⇒ `build_executor` **ném lỗi rõ**.
- health: `execution.mode`, `policy`, `hardlineHits`, `lease = null` khi chưa có H7.
- `GET/PUT /api/agent/permissions`: đọc snapshot; `PUT` ghi tầng `user` và có hiệu lực ngay; `mode` lạ ⇒
  `400 PERMISSION_MODE_UNKNOWN`; không có gì đổi ⇒ 400.
- `POST /decide`: trả `ask` + lý do; `allow_always` lưu luật và luật hiện ở `GET /rules`; `allow_session`
  bỏ câu hỏi thứ hai; `deny` 3 lần ⇒ `breaker = true`; `diskpart` ở `trusted` ⇒ `layer = 'hardline'`.
- `GET /pending`, `DELETE /rules` (thu hồi được, luật thiếu ⇒ 409).
- Chế độ `docker` (executor không có `policy`) ⇒ `409 PERMISSIONS_UNAVAILABLE`; thiếu header admin ⇒ 403.

`tests/unit/test_cua_target.py` (36 ca), `tests/unit/test_cua_overlay.py` (11 ca),
`tests/unit/test_host_executor_target.py` (26 ca), `tests/unit/test_machines_target_api.py` (14 ca) — lớp
đích CUA theo phiên:

```
.venv/bin/python -m pytest tests/unit/test_cua_target.py tests/unit/test_cua_overlay.py \
  tests/unit/test_host_executor_target.py tests/unit/test_machines_target_api.py -q
```

- `cua_target`: chuẩn hoá/`describe`; khớp `app`/`window` (chính xác trước, chuỗi con duy nhất, `.exe` hoa
  thường, 0 ⇒ `TARGET_UNKNOWN`, >1 ⇒ `TARGET_AMBIGUOUS` + `candidates`); `verify_window` tìm lại khi hwnd
  chết và **từ chối** hwnd bị tái dùng bởi pid khác; `resolve` theo thứ tự tham số → đích phiên → mặc định;
  `SessionTargetStore` ghi/đọc/xoá + `revision` + phiên con đi lên phiên gốc + chuỗi cha hỏng.
- `cua_overlay`: bám đúng `bounds` của cửa sổ, di chuyển không tạo lại cửa sổ, cửa sổ mất hình học ⇒ không
  vẽ, lease `human` ⇒ ẩn ngay và không tự hiện lại, tự ẩn sau 15 s, hoạt động mới giữ viền, nền tảng lỗi
  3 lần ⇒ tự tắt (`overlay_failed:*`), `auto_hide = 0` không hẹn giờ.
- `host_executor_target`: chụp/gõ vào cửa sổ của phiên; `app` thắng và được ghi lại với `setBy = 'agent'`;
  `TARGET_REQUIRED`/`CUA_MACHINE_SCOPE_REQUIRED`; đích cả máy chụp cả màn hình và trả `cuaTarget` +
  `captureOrigin`/`captureSize`; tự mở ứng dụng khi chưa chạy, **không** mở khi folder chưa tin cậy hoặc
  tên có dạng đường dẫn/`cmd /c ...`; mở hỏng ⇒ `LAUNCH_FAILED`, không ra cửa sổ ⇒ `launch_timeout`; thẻ
  duyệt có `approve-app`, **không** có `approve-always`; `resource_key` theo đích; viền nhận đúng `bounds`;
  `__target` giả mạo KHÔNG thành khoá duyệt (khoá vẫn theo đích thật — đường mở ứng dụng là chỗ hở, vì
  chưa có đích nào để ghi đè); hwnd đổi chủ giữa lúc thẻ duyệt còn mở và lúc chụp/gõ ⇒ `TARGET_UNKNOWN`
  với `reason = 'window_reused'`, không chụp và không gửi sự kiện nào.
- `machines_target_api`: gọi route THẬT qua `TestServer` — `consent`, `expectedRevision`,
  `TARGET_KIND_INVALID`, cửa sổ chết ⇒ `TARGET_UNKNOWN`, pid đổi ⇒ `TARGET_CHANGED`, `scope = workspace` +
  cả máy ⇒ `CUA_MACHINE_SCOPE_REQUIRED`, phiên Docker ⇒ `HOST_SESSION_REQUIRED`, phiên lạ ⇒
  `SESSION_NOT_FOUND`, ghi từ phiên con vào phiên gốc, danh sách cửa sổ cho picker ẩn cửa sổ thu nhỏ.

**Cách ly:** mọi ca dựng `BOXFOX_HOME_DIR` và `BOXFOX_INSTALL_DIR` trỏ vào `tmp_path`, nên không bao giờ
ghi vào `~/.boxfox` thật của máy chạy test. Ca nào quên hai biến này là một lỗi, không phải chuyện nhỏ.

---

## 5. Checklist cho chủ nhà trên Windows (D4)

Chạy trên Windows 11 x64, sau khi cài bộ `.exe`:

1. Mở app ⇒ harness ở host mode; health hiện `execution.mode = host`, `permissionMode = ask`.
2. Nhờ agent đọc một tệp trong workspace ⇒ không hỏi.
3. Nhờ agent ghi một tệp ⇒ **có** thẻ duyệt; bấm "Cho phép" ⇒ ghi được; thẻ hiện đúng đường dẫn.
4. Nhờ agent chạy `npm run build` (hoặc `dir`) ⇒ có thẻ duyệt; chọn "Cho phép và đừng hỏi lại" ⇒ lần sau
   không hỏi nữa; luật hiện ở Settings → Quyền **kèm tệp nguồn**; xoá luật ⇒ hỏi lại.
5. Nhờ agent chạy `format C:` ⇒ **bị chặn**, có mã, không hỏi.
6. Nhờ agent ghi ra `C:\Windows\test.txt` ⇒ bị chặn (`PATH_OUTSIDE_WORKSPACE`).
7. Bật CUA ⇒ phải qua bước xác nhận có văn bản cảnh báo; chụp màn hình ⇒ **có** thẻ duyệt.
8. Chọn phần tử trong Notepad ⇒ kết quả nhánh `uia` có `name`/`controlType`; trong Chrome ⇒ nhánh `dom`.
9. Đang khi agent thao tác, chạm chuột/bàn phím ⇒ app báo "Bạn đang điều khiển", agent nhả quyền; bấm
   "Trả quyền cho agent" ⇒ agent làm tiếp.
10. Bấm Esc (phím thật) ⇒ hành động đang chờ bị huỷ; không phím/chuột nào bị giữ.
11. Khoá máy (Win+L) rồi nhờ agent chụp ⇒ từ chối `DESKTOP_LOCKED`, không có ảnh đen nào được lưu.
12. Kiểm `permissions-audit.jsonl` trong profile ⇒ mỗi quyết định một dòng, có `actor`.
13. Đóng app giữa lúc chạy lệnh ⇒ tiến trình con dừng theo, không còn tiến trình mồ côi.

---

## 6. Checklist đích CUA và viền báo (Windows, chưa nghiệm thu)

Chạy trên Windows 11 x64. Các mục dưới đây **chỉ** Windows mới chứng minh được; kết quả trên Linux (quyết
định thuần + route + nền tảng giả) không thay thế được. Chưa mục nào được tick ⇒ DA7 giữ `[ ]`.

1. Panel Máy: chưa chọn gì, `scope = machine` ⇒ ảnh là cả màn hình; `scope = workspace` ⇒ câu
   `TARGET_REQUIRED` và nút chọn cửa sổ.
2. Chọn Notepad trong danh sách ⇒ thẻ đích hiện `Untitled - Notepad` + `notepad.exe`; agent chụp ⇒ ảnh chỉ
   có cửa sổ đó; gõ chữ ⇒ chữ vào đúng Notepad dù cửa sổ không ở tiền cảnh.
3. Đổi phạm vi sang `workspace` rồi xin đích cả máy ⇒ `CUA_MACHINE_SCOPE_REQUIRED`; quay lại `machine` ⇒
   chọn được.
4. Nhờ agent làm việc với `app: notepad` khi Notepad **chưa** chạy ⇒ agent tự mở (ShellExecuteW) rồi thao
   tác; đổi tên thành `..\..\evil.exe` ⇒ **không** mở gì.
5. Hai cửa sổ Notepad cùng mở, nhờ agent `app: notepad` ⇒ `TARGET_AMBIGUOUS` kèm `candidates`; agent chọn
   một cửa sổ rồi làm tiếp.
6. Đóng cửa sổ đích giữa lúc làm ⇒ `TARGET_UNKNOWN` + `reason = window_gone`, **không** gõ vào cửa sổ khác.
7. Thẻ duyệt CUA có đúng bốn lựa chọn (`Cho phép` / `Cho phép trong phiên` / `Theo ứng dụng này` /
   `Từ chối`), **không** có "luôn cho phép"; chọn "Theo ứng dụng này" ⇒ lời gọi sau cùng app không hỏi lại,
   app khác vẫn hỏi; `resource_key` trong audit là `cua:app:notepad` / `cua:machine`.
8. Viền xanh: hiện quanh cửa sổ đang bị điều khiển (đúng khung, không che chuột — cửa sổ click-through), tự
   ẩn sau 15 s không hoạt động, hiện lại khi agent làm tiếp.
9. Đang khi agent thao tác, người dùng chạm chuột/phím ⇒ viền **ẩn ngay** và agent nhận `HUMAN_HAS_CONTROL`;
   bấm "Trả quyền cho agent" ⇒ viền hiện lại, agent làm tiếp.
10. Xoá đích trong panel ⇒ viền ẩn ngay, `revision` tăng; đặt lại đích khác ⇒ panel chụp lại ảnh mới,
    không hiện ảnh cũ.
11. Đóng app giữa lúc CUA chạy ⇒ phiên dọn dẹp, viền ẩn, không còn cửa sổ mồ côi trong Task Manager.
12. Đặt `BOXFOX_CUA_OVERLAY=0` ⇒ không có viền nào, CUA vẫn chạy bình thường.
13. Select Element trên cửa sổ host: Notepad ⇒ nhánh `uia` có `name`/`controlType`; Chrome ⇒ nhánh `dom`;
    cửa sổ không có UIA ⇒ nhánh `desktop` (ảnh chụp), và khi người dùng đang giữ quyền ⇒ nút bị khoá kèm
    lời mời "Trả quyền cho agent".
