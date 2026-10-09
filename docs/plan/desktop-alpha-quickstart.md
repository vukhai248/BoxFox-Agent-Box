# Cài BoxFox Desktop (Alpha) trên Windows — bản nhanh

> **Dành cho ai:** người dùng cuối, người cài app lần đầu. Chỉ cần đọc và làm theo.
> **Bản tiếng Anh:** [desktop-alpha-quickstart.en.md](desktop-alpha-quickstart.en.md).
> Bản đầy đủ — kiến trúc, biến môi trường, cảnh báo chế độ host, checklist nghiệm thu 13 bước — ở
> [desktop-alpha-install.md](desktop-alpha-install.md) ([tiếng Anh](desktop-alpha-install.en.md)).
>
> **Bộ cài:** `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (Windows x64, **chưa ký Authenticode**).
> **SHA-256:** `fa2b965ca102e0797cc93048ce94750b5370f5828281b3a9d2b4938a0a4a077f`
> **Dựng từ:** commit `eba9aad`, nhánh `vorflux/host-mode-web-transport` (2026-10-09), kèm sẵn Node 24.9.0 và CPython 3.13.7.

## 0. Trước khi bắt đầu

| Bạn cần | Ghi chú |
|---|---|
| Windows 10 hoặc 11, bản **64-bit** | bộ cài chỉ có bản x64 |
| Quyền quản trị (admin) | **không cần** — bộ cài vào thẳng thư mục của bạn |
| Node, Python, npm, Conda | **không cần** — app mang sẵn runtime bên trong |
| Docker Desktop | chỉ cần khi bạn muốn chạy ở chế độ `docker` |

## 1. Kiểm tra file tải về

Mở PowerShell tại thư mục chứa file và chạy:

```powershell
Get-FileHash .\BoxFox-Desktop-Alpha-0.1.0-Setup.exe -Algorithm SHA256
```

Chuỗi in ra phải **giống hệt** chuỗi SHA-256 ở đầu trang này. Nếu khác, đừng chạy file — hãy tải lại.

## 2. Cài đặt — 4 bước

1. Nhấp đúp `BoxFox-Desktop-Alpha-0.1.0-Setup.exe`.
2. Windows hiện **"Windows protected your PC"** vì bản alpha chưa ký số. Bấm **More info** → **Run anyway**.
3. Chọn **Only for me**, bấm **Next**, rồi giữ nguyên thư mục cài mặc định và bấm **Next** lần nữa.
4. Bấm **Install** và đợi vài phút (file ~167 MB). Cài xong app **không tự mở** — bấm **Finish**.

Sau khi cài, bạn có:

- Ứng dụng ở `%LOCALAPPDATA%\Programs\boxfox-desktop` (bạn đổi được ở bước chọn thư mục)
- Shortcut ở Desktop và Start Menu, tên `BoxFox Desktop (Alpha)`
- Mục `BoxFox Desktop (Alpha)` trong **Settings → Apps → Installed apps**

## 3. Mở app lần đầu

1. Bấm Start → gõ `BoxFox` → chọn **BoxFox Desktop (Alpha)**.
2. Lần đầu mở mất vài giây: app tạo profile và cấp cổng nội bộ cho router và harness.
3. Cửa sổ app hiện giao diện web. Một icon **tray** cũng xuất hiện ở góc phải thanh tác vụ.
4. Gõ thử một câu hỏi vào khung chat. Có trả lời nghĩa là router + harness đã chạy.

Không có cửa sổ dòng lệnh nào mở ra, và bạn không phải cài thêm gì.

## 4. Chọn chế độ chạy: `host` hay `docker`

- **Mặc định là `host`**: chạy ngay, không cần Docker.
- Muốn dùng **Docker** (sandbox trong container): mở tệp
  `%LOCALAPPDATA%\BoxFoxDesktopAlpha\desktop-settings.json`, đổi `"executionMode": "host"` thành `"docker"`,
  lưu lại, rồi thoát và mở lại app. Docker Desktop phải đang chạy.
- Nếu Docker chưa sẵn sàng, app **tự quay về `host`** và ghi rõ lý do vào log và vào file chẩn đoán. App không bao giờ báo `docker` giả.

| Chế độ | Cần gì | Agent chạy ở đâu |
|---|---|---|
| `host` | không cần gì | Ngay trên Windows, bằng tài khoản của bạn |
| `docker` | Docker Desktop đang chạy | Trong container `boxfox-desktop-<profile>` |

## 5. Dữ liệu của bạn nằm ở đâu

Mọi thứ nằm trong **một** thư mục, không rải vào `Program Files` hay registry:

```
%LOCALAPPDATA%\BoxFoxDesktopAlpha\
  machine.json            cổng nội bộ + token riêng của máy này
  desktop-settings.json   chế độ chạy (host | docker)
  profile\                dữ liệu harness, router, UI (gồm lịch sử hội thoại)
  logs\                   log của router và harness
  diagnostics\            các file zip "Sao lưu chẩn đoán"
```

## 6. Khi cần hỗ trợ

Bấm icon tray → **Sao lưu chẩn đoán**. App gom thông tin vào **một** file zip trong
`%LOCALAPPDATA%\BoxFoxDesktopAlpha\diagnostics\` rồi mở Explorer sẵn. Gửi file zip đó khi báo lỗi.
File này **không** chứa token hay API key (mọi dòng có `key`, `token`, `secret`, `authorization`, `password` đều bị thay bằng `[REDACTED]`).

## 7. Gỡ cài đặt

1. **Settings → Apps → Installed apps** → `BoxFox Desktop (Alpha)` → **Uninstall**.
2. Chương trình và shortcut biến mất. **Dữ liệu của bạn được giữ nguyên** trong `%LOCALAPPDATA%\BoxFoxDesktopAlpha`.
3. Cài lại sau này sẽ dùng lại đúng profile cũ.
4. Muốn xoá sạch mọi thứ: xoá thủ công thư mục `%LOCALAPPDATA%\BoxFoxDesktopAlpha`.

## 8. Bốn điều nên biết trước khi dùng

1. **Bản alpha, chưa ký số.** Windows SmartScreen sẽ cảnh báo; đây là điều đã biết. Bản này cũng chưa tự cập nhật.
2. **Chế độ `host` không có sandbox cấp hệ điều hành.** Agent chạy bằng tài khoản Windows của bạn: thứ gì bạn đọc/ghi được thì agent cũng đọc/ghi được. Lệnh chạy thật trên máy bạn; app để mức quyền mặc định là **hỏi trước**.
3. **CUA (chuột/phím/màn hình) mặc định TẮT.** Khi bạn tự bật, agent điều khiển chuột và bàn phím thật, và ảnh chụp màn hình được gửi cho nhà cung cấp model. Đừng để cửa sổ nhạy cảm mở khi bật CUA.
4. **Đường thoát:** tray → **Dừng khẩn** dừng hành động đang chờ và trả quyền về cho bạn.

## 9. Xử lý nhanh sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| SmartScreen chặn file Setup | **More info** → **Run anyway** |
| Không thấy icon tray | App vẫn chạy: mở lại từ Start Menu. Nếu log có dòng `[desktop] no tray; closing the window will quit the app.` thì đóng cửa sổ là thoát hẳn |
| App mở nhưng chat không trả lời | Mở `logs\harness.stderr.log`; gửi kèm file chẩn đoán khi báo lỗi |
| Muốn đổi chế độ chạy | Sửa `desktop-settings.json` rồi mở lại app (mục 4) |
| Đã cài mà máy vẫn đòi Node/Python | Không cần cài: runtime đã nằm trong `resources\runtime\`. Gửi file chẩn đoán nếu app báo thiếu |
| Cài lại cùng phiên bản | An toàn: bộ cài dùng lại profile cũ, không cấp lại cổng/token |
