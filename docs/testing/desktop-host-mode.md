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
