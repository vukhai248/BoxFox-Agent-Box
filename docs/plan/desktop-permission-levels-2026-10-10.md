# Desktop permissions — checkpoint 2026-10-10

## Quyết định owner và phạm vi

Thay 4 mức bằng 3 mức, app tiếng Anh; bỏ Scope riêng ở chat và Settings. Internet giữ hai lựa chọn độc lập. Nhánh `codex/desktop-startup-fix`, không merge/push. Neo trước sửa: tag `codex/desktop-before-permission-simplification-20261010` tại `4871791f`. Main giữ `ff59af8f040cc18f335ffa45e768b962111c54c1`.

| Nhãn UI | Giá trị lưu | Mặc định khi không có luật riêng |
|---|---|---|
| Request approval | `ask` | Đọc project và lệnh khảo sát được nhận diện tự chạy; sửa file, lệnh khác, mục tiêu ngoài project hỏi. |
| Auto approve | `auto` | Công việc trong project tự chạy; ngoài project, CUA và nhóm rủi ro đã định hỏi. |
| Full access | `trusted` | File ngoài project được đọc/ghi/sửa theo quyền OS; vẫn giữ deny, sàn cứng, nhóm luôn hỏi, trust project và hàng rào CUA. |

Network giữ `Ask before network access` / `Allow network access`. Restricted hỏi các **lệnh mạng được nhận diện** cả ở Full access. Enabled không duyệt thay mức quyền hay luật khác. Đây là danh sách hỏi, không phải firewall; không thay đường gọi provider/research host. Các luật allow và duyệt tài nguyên cụ thể hiện có giữ thứ tự áp dụng.

## Thay đổi

- Policy còn 3 mức. Legacy `plan` đọc thành `ask` qua constructor/file/env/API; không nâng Auto/Full. Scope file suy từ mức; snapshot giữ trường tương thích và thêm `scopeDerived`.
- Khảo sát nhận diện: `git status`, `git ls-files`, `pwd`/`Get-Location`, `Get-ChildItem`, `Get-Content`, `Get-Item`, `Test-Path`, cùng cờ đã kiểm. Path phải nằm trong project sau resolve. Shell ghép/redirect/scripts/cờ lạ hỏi. Không tuyên bố phân tích được mọi tác dụng của lệnh.
- Host file tools resolve đích trước policy/thẻ duyệt; ngoài project chỉ chạy sau approval hoặc Full access. Key/rule dùng đích chuẩn; kiểm junction và thay đích sau duyệt. Root riêng của child vẫn giới hạn mọi mức. Không coi kiểm path là sandbox OS hoặc chứng minh chống mọi TOCTOU.
- Windows paths so hoa/thường đúng trong project; rule file dùng neo tuyệt đối với drive Windows.
- PUT Scope riêng trả `PERMISSION_SCOPE_DERIVED`, không ghi dở mode. API ưu tiên policy project của machine router thay vì workspace mặc định ở executor legacy.
- **CUA riêng:** `cua_scope_value()` giữ boundary cũ; snapshot thêm `cuaScope`. Scope legacy chỉ còn dùng cho boundary CUA, không mở file. Target/launch/API dùng boundary này; consent, grants, lease, Stop không đổi. Đổi mức file không viết lại scope CUA cũ hoặc tự cấp grant máy toàn cục.
- Chat/Settings cùng 3 nhãn tiếng Anh. Không đổi model/provider/ngôn ngữ trả lời/layout khác/DAG.

## Kiểm chứng

| Bộ kiểm | Kết quả |
|---|---|
| Permission levels, policy, HTTP API | 165 passed; có file IO, PowerShell và junction thật trên Windows; mode/network, migration, deny, child root. |
| Host/Docker, CUA executor/target, target API, desktop API, router endpoint | 137 passed; CUA dùng fake platform, không thay nghiệm thu Win32 input. |
| Host executor nhóm file/policy không dùng POSIX shell | 35 passed, 13 deselected qua bộ lọc rõ; shell Windows kiểm bằng ca native mới. |
| Chat picker, Settings, i18n | 43 passed. |
| Frontend typecheck + production build | Đạt. |
| ESLint file permission sửa | Đạt. |
| Desktop | 77 passed, 2 POSIX skips. |

Không ghi toàn suite xanh:

- Frontend toàn bộ: **1681 passed, 3 failed** ở ConnectionKeyRing (2) và ProviderConnectionCard (1), kỳ vọng chuỗi key/model/latency cũ. Source/test các component đó không đổi. ESLint toàn frontend còn 10 lỗi ở file không sửa.
- Host suite cũ có ca `/bin/sh`, encoding mặc định, kỳ vọng `powershell.exe` khi máy chọn `pwsh.exe`. Baseline `4871791f` chạy riêng có 16 failures. Không sửa shell sản phẩm hoặc gọi các ca này đã đạt.
- Fixture web mode cô lập HOME/INSTALL, mô phỏng user từ chối legacy `plan` đã thành Request approval, ghi LF rõ để tương đương Windows. Timeout không là chấp thuận.

Raw logs: `.tmp/permissions-20261010/`. Không commit profile, credential, DB owner.

## Việc còn riêng

`PROJECT_TRUST_REQUIRED` là trust folder, độc lập mức duyệt; không tự trust project thật. Host journal vẫn thiếu `session_ensure`/`journal_append`/`checkpoint_write`; Full access không chữa thiếu tool. Không thay workflow/DAG hay tick toàn Desktop Alpha.

## Bộ cài

Target 0.1.3. Hash/probe sẽ bổ sung sau chạy thật; giữ 0.1.2 để rollback. Quit ở tray trước cập nhật (X chỉ ẩn), cài vào nơi cũ; giữ profile/data/project. Không tự cài lên app owner.
