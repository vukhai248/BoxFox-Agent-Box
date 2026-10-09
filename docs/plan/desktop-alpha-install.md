# BoxFox Desktop (Alpha) — cài đặt, chế độ chạy và checklist nghiệm thu

> **Người dùng cuối chỉ muốn cài và dùng:** đọc bản ngắn [desktop-alpha-quickstart.md](desktop-alpha-quickstart.md) trước. Tài liệu dưới đây là bản đầy đủ dành cho người nghiệm thu build. **Bản tiếng Anh:** [desktop-alpha-install.en.md](desktop-alpha-install.en.md).
>
> **Trạng thái:** Hướng dẫn cài + checklist 13 bước để chủ nhà tự nghiệm thu D4. Đây là tài liệu của đầu việc D3/D4 trong kế hoạch `desktop-alpha-packaging.md` (§6 PR-2, §8) và §17.3 của `v1-machine-environments-roadmap.md`.
>
> **Ngày:** 2026-10-06. **Nhánh:** `vorflux/desktop-alpha`. **Bộ cài:** `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (Windows x64, **chưa ký Authenticode**).
>
> **Chưa nghiệm thu:** tài liệu này là hướng dẫn để người thật chạy trên Windows 11 x64. Không có kết quả test nào trong đây được coi là đã đạt; các dòng "kết quả mong đợi" là tiêu chí, không phải biên bản.

## 1. Bộ cài có gì

- **NSIS per-user** — cài vào `%LOCALAPPDATA%\Programs\boxfox-desktop`, **không hỏi quyền admin**, không cài service, không ghi vào `Program Files`. (Tên thư mục mặc định lấy từ `name` trong `package.json`; `productName` có ngoặc đơn nên không dùng làm tên thư mục được. Người dùng đổi được ở trang "Choose Install Location".)
- **Runtime đi kèm** — Node 24.9.0 + CPython 3.13.7 + wheel đã khoá (`runtime.lock.json`). Máy đích **không cần** Node, Python, Conda hay npm.
- **Toàn bộ stack** — UI đã dựng sẵn, router, harness, và `docker-context/` để dựng image sandbox khi cần.
- **Shortcut** — Desktop + Start Menu, tên `BoxFox Desktop (Alpha)`.
- **Không tự chạy sau khi cài** (`runAfterFinish: false`) và **không bật autostart**: app chỉ chạy khi người dùng mở.
- **Gỡ cài đặt giữ dữ liệu** — xem §6.

SmartScreen sẽ cảnh báo vì bộ cài chưa ký: **More info → Run anyway**. Kiểm hash trước khi chạy:

```powershell
Get-FileHash .\BoxFox-Desktop-Alpha-0.1.0-Setup.exe -Algorithm SHA256
# hoặc: certutil -hashfile BoxFox-Desktop-Alpha-0.1.0-Setup.exe SHA256
```

Đối chiếu với `SHA256SUMS.txt` cạnh bộ cài. Bản dựng 2026-10-09:
`fa2b965ca102e0797cc93048ce94750b5370f5828281b3a9d2b4938a0a4a077f` (167.123.853 B).

## 2. Cài đặt

1. Chạy `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (bấm qua cảnh báo SmartScreen).
2. Chọn thư mục cài (mặc định ở trên), để nguyên tuỳ chọn shortcut.
3. Kết thúc trình cài: app **không** tự mở. Mở bằng Start Menu → `BoxFox Desktop (Alpha)`.
4. Lần đầu mở app mất vài giây vì phải tạo profile và cấp 4 cổng loopback.

Cài lại cùng version lên bản đang có là an toàn: trình cài giữ `%LOCALAPPDATA%\BoxFoxDesktopAlpha` và dùng lại đúng profile cũ.

## 3. Chọn chế độ chạy (host / docker)

**Mặc định lần đầu: `host`** — chạy không cần Docker (đúng quyết định "máy cài là dễ nhất" của kế hoạch).

Đổi chế độ:

1. Mở `%LOCALAPPDATA%\BoxFoxDesktopAlpha\desktop-settings.json`.
2. Đặt `"executionMode": "docker"` (hoặc `"host"`).
3. Khởi động lại app.

```json
{ "version": 1, "executionMode": "host", "updatedAt": "..." }
```

| Chế độ | Cần gì | Agent chạy ở đâu | Ghi chú |
|---|---|---|---|
| `host` | không cần gì | Trực tiếp trên Windows, bằng tài khoản người dùng | Không có sandbox cấp HĐH — xem §5 |
| `docker` | Docker Desktop đang chạy | Trong container `boxfox-desktop-<profile>` | Dùng image `agentbox-sandbox:latest` |

- `docker` chỉ được chọn khi **cả ba** điều kiện đúng: có CLI `docker`, engine sống, và image có sẵn. Thiếu bất kỳ điều kiện nào ⇒ app **rơi về `host` và ghi rõ lý do** trong log + file chẩn đoán; không bao giờ báo `docker` giả.
- Image chưa có thì app dựng một lần từ `docker-context/` đi kèm (bản alpha chưa có registry — đây là điểm lệch §15.5 của roadmap, có chủ ý).
- Bản alpha **chưa có tab Settings → Chế độ chạy** (đó là việc frontend D4); cách đổi duy nhất hiện tại là sửa `desktop-settings.json` rồi khởi động lại.
- Lý do chọn chế độ luôn hiện trong `summary.txt` của file chẩn đoán và trong log dòng `[desktop] mode: ...`.

## 4. Biến môi trường

App **xoá sạch mọi `BOXFOX_*` thừa hưởng** rồi mới đặt biến cho hai tiến trình con (router, harness). Nghĩa là: đặt các biến dưới đây trong Environment Variables của Windows **không có tác dụng** — chúng là đầu ra của app, không phải nút chỉnh. Nguồn sự thật là `machine.json` + `desktop-settings.json`.

| Biến | Do app đặt cho | Ý nghĩa |
|---|---|---|
| `BOXFOX_EXECUTION_MODE` | cả hai | `host` hoặc `docker` — chế độ đã chốt cho phiên chạy này |
| `BOXFOX_DESKTOP_PROFILE` | cả hai | Thư mục profile (`%LOCALAPPDATA%\BoxFoxDesktopAlpha`) |
| `BOXFOX_API_KEY` | cả hai | Token admin **riêng của máy này** (`machine.json`, `crypto.randomBytes(32)`) |
| `BOXFOX_AGENT_DATA_DIR` | harness | `<profile>\profile\harness` — dữ liệu/session của harness |
| `BOXFOX_ROUTER_DATA_DIR` | router | `<profile>\profile\router` — dữ liệu router |
| `BOXFOX_HARNESS_PORT`, `BOXFOX_ROUTER_PORT` | harness / router | Cổng loopback đã cấp trong `machine.json` |
| `BOXFOX_UI_ORIGINS` | harness | Allowlist origin của gateway (không wildcard) |
| `BOXFOX_ROUTER_URL`, `BOXFOX_BOX_URL` | harness | Địa chỉ router và box/sandbox |

Hai tên trong kế hoạch là `BOXFOX_HOST_WORKSPACE` và `BOXFOX_PROFILE_DIR`: **không tồn tại trong mã hiện tại** (không file nào đọc chúng). Đừng đặt rồi mong có tác dụng; tên thật là bảng trên.

## 5. Dữ liệu, log và chẩn đoán nằm ở đâu

Tất cả trong **một** thư mục, không rải vào registry hay `Program Files`:

```
%LOCALAPPDATA%\BoxFoxDesktopAlpha\
  machine.json            cổng gateway/router/harness/box + token admin (chmod 0600)
  desktop-settings.json   executionMode (host|docker)
  desktop.lock            pid của instance đang chạy (chống mở trùng)
  profile\
    harness\              dữ liệu harness (session, history)
    router\               dữ liệu router
    ui\                   dữ liệu phụ trợ của UI
  logs\                   router.stdout.log, router.stderr.log,
                          harness.stdout.log, harness.stderr.log
  diagnostics\            các file .zip của "Sao lưu chẩn đoán"
  recovery\               machine.json hỏng được cách ly ở đây (không ghi đè im lặng)
  updates\                chỗ dành cho auto-update (alpha chưa dùng)
  permissions\ audit\     chỗ dành cho luật quyền + audit (khi lớp quyền có mặt)
```

## 6. Sao lưu chẩn đoán

**Tray → Sao lưu chẩn đoán.** App gom mọi thứ vào **một** file zip trong `diagnostics\` và mở Explorer với file được chọn sẵn:

```
%LOCALAPPDATA%\BoxFoxDesktopAlpha\diagnostics\boxfox-diagnostics-<YYYY-MM-DDTHH-MM-SS-mmmZ>.zip
  manifest.json   version app, commit build, chế độ + lý do, cổng, đường dẫn profile/data/logs,
                  runtimeBundle (target, artifact, danh sách file runtime kèm size + sha256),
                  health, services, danh tính Docker
  health.json     nguyên văn JSON của GET /api/agent/health
  summary.txt     bản tóm tắt dạng người đọc
  logs\*          200 dòng cuối của MỖI file trong logs\
```

Gửi kèm zip này khi báo lỗi. **Không đưa API key/token vào đó**: mọi khoá và mọi dòng log đi qua bộ lọc theo từ khoá `key`, `token`, `secret`, `authorization`, `password` (không phân biệt hoa thường) và bị thay bằng `[REDACTED]` trước khi ghi.

## 7. Cảnh báo thẳng về chế độ host

Đọc trước khi bật. Không có cách nói nhẹ đi:

- **Agent chạy bằng tài khoản Windows của bạn.** Chế độ host không có sandbox cấp HĐH (restricted token/AppContainer/WFP — Codex có, bản alpha này **chưa**). Mọi thứ tài khoản của bạn đọc/ghi được thì agent cũng đọc/ghi được, kể cả file ngoài thư mục dự án.
- **Lệnh chạy thật trên máy bạn.** Không có container đỡ. Bản alpha để chế độ quyền mặc định là **hỏi trước** (`ask`), và **hardline floor** là danh sách bị từ chối kể cả khi bạn đã cấp toàn quyền.
- **CUA (chuột/phím/màn hình) mặc định TẮT.** Khi bạn tự bật, agent điều khiển **chuột và bàn phím thật** của bạn: nó có thể bấm vào cửa sổ bạn đang mở, gõ vào ô đang focus, và **mọi ảnh chụp màn hình agent chụp đều đi vào lượt hội thoại và được gửi cho nhà cung cấp model**. Đừng để cửa sổ có dữ liệu nhạy cảm (ngân hàng, mật khẩu, chat riêng) mở khi bật CUA.
- **Dừng khẩn** (tray → `Dừng khẩn`) là đường thoát: dừng hành động đang chờ, nhả phím/chuột đang giữ, đưa quyền về người dùng. `Trả quyền cho agent` là chiều ngược lại.
- Bản alpha **chưa có** lớp CUA/host-mode trong harness nếu PR-1 (H5–H7) chưa vào build. Khi đó các bước 5–11 của checklist **phải báo "chưa hỗ trợ" rõ ràng** — không được giả vờ thành công.

## 8. Checklist nghiệm thu 13 bước

Điều kiện: Windows 11 x64, **không** cài Node/Python/Conda; máy **không** bật Docker ở bước 1–7. Ghi lại version/commit của build khi chạy.

| bước | cách làm | kết quả mong đợi |
|---|---|---|
| 1. Cài bộ cài | Chạy `BoxFox-Desktop-Alpha-0.1.0-Setup.exe` (qua cảnh báo SmartScreen), giữ thư mục mặc định | Cài xong dưới `%LOCALAPPDATA%\Programs\boxfox-desktop` (tên mặc định của trình cài); có shortcut Desktop + Start Menu; mục `BoxFox Desktop (Alpha)` trong Apps & features; `%LOCALAPPDATA%\BoxFoxDesktopAlpha\` được tạo; app **không** tự mở sau khi cài |
| 2. Mở app | Start Menu → `BoxFox Desktop (Alpha)` | Cửa sổ hiện đúng UI web; icon tray xuất hiện; `logs\router.stdout.log` và `logs\harness.stdout.log` có dòng mới; **không** đòi Node/Python/Docker; không mở terminal nào |
| 3. Chọn chế độ chạy | Mở `desktop-settings.json`, đổi `executionMode`, khởi động lại; xem dòng `[desktop] mode:` trong log | `host` chạy được khi máy **không** có Docker; `docker` chỉ nhận khi Docker Desktop đang chạy; Docker thiếu ⇒ rơi về host **kèm lý do rõ** trong log + chẩn đoán, không hiện sandbox giả |
| 4. Chạy một lượt hội thoại | Gõ một yêu cầu đơn giản trong khung chat, đợi trả lời, rồi Ctrl+R | Trả lời từ backend thật (không mock); session/history còn sau reload; status dịch vụ phản ánh đúng tiến trình đang chạy |
| 5. Xem tab Quyền | Mở panel **Quyết định** (tab `Quyết định` / `Decisions`) — nơi liệt kê yêu cầu phê duyệt quyền | Danh sách đọc thẳng từ `decision_requested` / `decision_resolved` thật; hàng chờ phân biệt với hàng đã xử lý; **không** có dữ liệu demo hay hạn tự bịa |
| 6. Lệnh nằm trong hardline floor | Yêu cầu agent chạy một lệnh thuộc danh sách chặn cứng (ví dụ thao tác khoá phiên/secure desktop) | Bị **từ chối kèm mã lý do**, kể cả khi đã cấp mức quyền rộng nhất; không có gì được thực thi; sự việc vào audit log |
| 7. Từ chối thẻ phê duyệt | Bấm **từ chối** trên một thẻ duyệt quyền đang chờ | Hàng chuyển trạng thái "đã từ chối"; agent nhận kết quả từ chối và **không** chạy hành động; từ chối 3 lần liên tiếp ⇒ ngắt mạch, agent ngừng hỏi (mã `APPROVAL_DENIAL_BREAKER`) |
| 8. Bật chế độ host (CUA) | Vào **Settings → CUA**, bật công tắc và xác nhận riêng | Trước đó CUA **tắt**; bật phải qua xác nhận riêng; băng trạng thái quyền đổi sang "Agent đang điều khiển"; lease hiện rõ ai đang giữ |
| 9. Chụp màn hình | Yêu cầu agent chụp màn hình | Ảnh vào đúng lượt hội thoại và được gửi cho model; nếu CUA đang tắt ⇒ từ chối rõ ràng thay vì ảnh giả; ghi nhận rằng ảnh chứa mọi thứ trên màn hình |
| 10. Inspect element | Trong preview Machine screen, chọn một element → **Add to Chat** | Selector đúng nguồn và toạ độ; dữ liệu giữ trong chat sau khi gửi; element đổi/toạ độ đổi ⇒ `ELEMENT_STALE`/`SOURCE_CHANGED`, **không** resolve sang phần tử khác |
| 11. Dừng khẩn | Tray → **Dừng khẩn** | Hành động đang chờ dừng; mọi phím/chuột đang giữ được nhả; lease về người dùng; app báo rõ kết quả gửi tới harness; ở chế độ docker giữ quyền trong container thì báo rõ **409** thay vì im lặng |
| 12. Sao lưu chẩn đoán | Tray → **Sao lưu chẩn đoán** | ZIP mới trong `diagnostics\`, Explorer mở sẵn; có `manifest.json`, `health.json`, `summary.txt`, 200 dòng cuối mỗi log, inventory runtime kèm sha256; **không** chứa API key/token |
| 13. Gỡ cài đặt | Apps & features → `BoxFox Desktop (Alpha)` → Uninstall | Chương trình + shortcut biến mất; `%LOCALAPPDATA%\BoxFoxDesktopAlpha` **giữ nguyên** (machine.json, session, log); cài lại nhận lại đúng profile cũ, không cấp lại cổng/token mới |

Các bước 5–11 cần lớp host-mode/CUA của PR-1 (H5–H7) trong build; nếu build chưa có, kết quả đúng là **báo chưa hỗ trợ**, và ghi rõ như vậy thay vì đánh dấu đạt.

## 9. Giới hạn đã biết của bản alpha

- Bộ cài **chưa ký** (SmartScreen cảnh báo); chưa có auto-update.
- Chỉ có bộ cài **Windows x64**; runtime bundle là `win-x64`.
- **Không có sandbox cấp HĐH** ở chế độ host (xem §7).
- Chưa có **ghi hình màn hình host** (`computer_screen_record`) — cần `ffmpeg`; trong box thì vẫn chạy.
- Tray là tuỳ chọn: nếu môi trường không tạo được tray, app ghi log `[desktop] no tray; closing the window will quit the app.` và đóng cửa sổ là thoát — không có tray ẩn.
- `build/icon.ico` vẫn là icon tạm; icon tray là `build/tray.png` (32×32).
- Gỡ cài đặt **không** xoá profile: muốn xoá sạch phải xoá tay `%LOCALAPPDATA%\BoxFoxDesktopAlpha`.
