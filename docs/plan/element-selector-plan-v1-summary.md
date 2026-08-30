# Element Selector / DOM Inspector — Tóm tắt kế hoạch v1

> **TL;DR:** Thêm nút `Select Element` vào thanh công cụ khung ④ (Sandbox Machine). Khi bật, một overlay
> trong suốt **chặn** cú bấm không cho tới desktop ở xa, quy đổi toạ độ canvas → framebuffer, gọi
> `POST /__box/inspect-element`, rồi hiện kết quả trong drawer đáy: **nhánh `dom`** (selector, text,
> attributes, outerHTML, bounding box qua CDP) hoặc **nhánh `desktop`** (hình học + tiêu đề cửa sổ X11) khi
> điểm bấm nằm ngoài vùng nội dung web. `Add to Chat` gắn phần tử vào khung soạn tin dưới dạng **dữ liệu có
> nhãn `khong_tin_duoc`**, không phải văn bản nối vào lời người dùng.

**Kế hoạch chi tiết:** [`element-selector-plan-v1.md`](element-selector-plan-v1.md) (§1–§14)
**Đào sâu:** `box-side-detail.md` (1232 dòng) · `frontend-detail.md` (1641 dòng) · `research-competitive.md`
**Thiết kế:** 6 file HTML trong [`../design/element-selector/`](../design/element-selector/)

---

## Đã nghiên cứu Vorflux và Devin (yêu cầu của bạn) — §2

- **Vorflux là nguồn tham chiếu THẬT, không phải mockup.** 5 ảnh bạn gửi là giao diện Vorflux (dải tab
  `IDE / Canvas / Desktop / …` ở mép trên) — bạn đang chạy BoxFox *bên trong* sandbox Vorflux. Rút ra 8 quan
  sát hành vi, quan trọng nhất: CDP thất bại **suy biến mềm sang thông tin cửa sổ**, không trả 500; và biến
  thể selector trơn **mất hẳn khối `Attributes:`**.
- **Devin** dùng `Send element` → `@ mention` → **pending context** trong hộp soạn tin, chọn được **nhiều**
  phần tử, và gọi đó là ngữ cảnh **tất định**. → Đây là tiền lệ sản phẩm cho quyết định lệch khỏi đặc tả §4.3.
- **Cursor Design Mode** gửi **element identity + screenshot**, gồm cả **computed styles**. → `computed
  styles` là thứ đặc tả bạn thiếu, xếp Phase 3.
- **Cảnh báo đã xác minh:** Cursor đọc `_debugSource` từ **React fiber**, nhưng **React 19 đã bỏ trường
  đó** — repo dùng React 19, nên hướng đó là **đường chết**. Phase 2 dùng plugin build-time stamp thay thế.
- **Điều không sản phẩm nào làm, và BoxFox phải làm:** gắn **nhãn tin cậy** cho nội dung phần tử.

---

## Ba chỗ CỐ Ý lệch khỏi đặc tả của bạn — §4

| Đặc tả nói | Kế hoạch làm | Vì sao |
|---|---|---|
| §5: `POST /api/sandbox/inspect-element` | **`POST /__box/inspect-element`** | `backend/` **chưa có server/runtime nào** (chỉ package placeholder + README); namespace thật là `/__box/*` trên ide-proxy `:8081`; X server `:99` và CDP `:9222` **chỉ tới được từ trong container**; vào `_CAPTURE_ENDPOINTS` là thừa hưởng miễn phí Origin-gating + shared secret + CORS + cap body |
| §4.3: chèn blockquote Markdown vào **ô soạn tin** | **Chip có cấu trúc**, gửi qua trường `elements` của `user_message`; `text` giữ nguyên văn người dùng gõ | Nối HTML lạ vào `text` chính là **kênh tấn công A3 mà panel này đang demo**. Đi đường `elements` thì `integrity_floor` **tự sụt** xuống `khong_tin_duoc` bằng cơ chế `label_added` sẵn có. Vẫn sinh bản văn bản người đọc được (`ContextChunk.content`) — chỉ đổi **đường đi**, không bỏ |
| Mockup tô màu cả khối `HTML:` | `Attributes:` **được** tô màu, `HTML:` **không** | Tô màu HTML thô = phân tích HTML client-side trên nội dung kẻ tấn công kiểm soát. `HTML:` render qua `PlainText`; ESLint đã chặn cứng `dangerouslySetInnerHTML` |

**Bốn thứ bổ sung** (không phải lệch): khối nhãn/provenance trên cả hai nhánh · trường `reason` mã máy đi
cùng `message` để frontend dịch · `screenBox` (toạ độ X11) để vẽ khung sáng và làm cầu nối CUA · hàng
`Source:` ngay từ Phase 1.

---

## Năm quyết định tôi tự chốt (bác bỏ được ở lúc duyệt) — §6

| # | Chốt | Chi phí đổi ý |
|---|---|---|
| Q1 | `message` **tiếng Việt** + `reason` mã máy, frontend dịch theo `reason` | 1 bảng `MSG` |
| Q2 | `ambiguous_target` → **HTTP 200 + nhánh desktop** (không phải 409) | 3 dòng |
| Q3 | **Có** thêm smoke-test mục 20, baseline **23/5 → 29/5** | bỏ 1 khối |
| Q4 | `confidentiality` của chunk = **`'noi_bo'`** | 1 hằng số |
| Q5 | Chọn xong **tự tắt** chế độ chọn (theo bản thiết kế, khác Vorflux) | 1 dòng |

Ngoài ra bản này **chốt 10 chỗ hai kế hoạch con lệch nhau** (§5.6, có bảng thay thế; hai bản chi tiết đã
được chèn khối "SUPERSEDED" ở đầu file): nhãn **lồng trong `label`** · box **có** trả `confidentiality` ·
một bộ mã `reason` duy nhất (11 mã) · `notes` · `source_uri` **không nhúng selector** · thuật toán
`content_hash` 3 bước chống tự tham chiếu · tự tắt sau khi chọn · tên env · `Add to Chat` khi đang tải ·
kiểu chip composer.

---

## Chín điểm thiết kế đã sửa sau hai vòng review nội bộ

| Vấn đề | Sửa |
|---|---|
| Hit-test dùng geometry **client** nên bấm titlebar/nút `[X]` sẽ **trượt** — `_NET_CLIENT_LIST_STACKING` chỉ liệt kê client id, còn trang trí xfwm4 là frame window bên ngoài | Đọc `_NET_FRAME_EXTENTS`, giữ **hai** hình học: `frameGeom` để hit-test, `clientGeom` để suy vùng nội dung. Không còn fallback "đoán cửa sổ trên cùng" (wmctrl không mang stacking order) → trả 404 rõ ràng |
| Coi **lỗi đọc** `_NET_FRAME_EXTENTS` như `extents = 0` là sai âm thầm: cửa sổ có trang trí thật mà `xprop` lỗi ⇒ bấm titlebar **rơi xuống cửa sổ dưới** và trả phần tử của cửa sổ khác | `frame_extents()` phân biệt "vắng mặt hợp lệ" (⇒ `{0,0,0,0}`) với "lỗi đọc" (⇒ `None`). `None` ⇒ **fail-closed**: điểm trong dải nghi vấn quanh client area trả nhánh desktop với mã mới `frame_extents_unknown`, **không** rơi xuống cửa sổ dưới |
| Công thức gốc viewport giả định viewport **sát đáy** và **căn giữa** → **sai** khi DevTools/side panel docked, và scrollbar không chia đều | Thêm phép kiểm hợp lý (`slackX ≤ 24`, `slackY ≤ 200`); vượt ngưỡng ⇒ mã mới `viewport_origin_unknown` + nhánh desktop, **không** trả phần tử sai |
| Ngưỡng `slackY ≤ 200` **không** loại được DevTools docked mỏng (≈150 px + chrome vẫn < 200 px) ⇒ viewport bị neo vào đáy DevTools và trả phần tử **sai** | Thêm phép **phát hiện tất định**: so `Browser.getWindowForTarget` của target `devtools://` với của page; cùng `windowId` ⇒ docked ⇒ mã mới `devtools_docked` (trạng thái **không hỗ trợ** ở Phase 1). Đọc lỗi ⇒ vẫn coi là docked (fail-closed). Undocked không ảnh hưởng |
| Ngân sách 8 s **không áp được**: `list_windows()` chạy `wmctrl` 15 s + mỗi cửa sổ `xwininfo` 10 s + `xprop` 10 s → một request có thể chạy hàng trăm giây | `window_at_point()` **không** gọi `list_windows()`; probe theo stacking order và **dừng ở cửa sổ đầu tiên khớp**; mọi helper nhận timeout = thời gian còn lại; semaphore 2 request đồng thời |
| `data-boxfox-src` là **dữ liệu web không tin được**, mà `openFileInIde` **không validate** (`lib/ide/config.ts:75–93`, `uiStore.ts:207–210`) → `../../../../etc/passwd` là đường từ trang lạ tới mở file nội bộ | **Hoãn `source` + `Open in IDE` sang Phase 2**, và Phase 2 phải có 4 lớp kiểm tra đường dẫn ở phía box |
| Kể cả một nhánh `if (result.source)` **ngủ đông** ở Phase 1 vẫn là đường mở file chưa validate — chỉ cần một mock trả `source` là nó chạy | Phase 1 **không** khai `InspectSource`, **không** viết nhánh UI nào. Kiểu + validation + UI ra đời **cùng lúc** ở Phase 2 |
| Subprocess vẫn ghi timeout cố định **10 s** trong khi ngân sách toàn cục là **8 s** ⇒ ngân sách vô nghĩa, frontend `abort()` trước và subprocess treo trong container | Ngân sách toàn cục là **trần duy nhất**: subprocess nhận `_remaining(deadline)`; hết giờ ⇒ không spawn |
| `TimeoutExpired` bị bắt chung dưới `subprocess.SubprocessError` ⇒ báo sai `cdp_unreachable` | Bắt `TimeoutExpired` **trước** (nó là lớp con) và ánh xạ thành `cdp_timeout`; có test khẳng định |
| Lưới an toàn `ide-proxy.py:292–293` nội suy `str(exception)` ra response | Đổi sang khuôn an toàn đã có ở nhánh workspace (`:503–505`): log `{error!r}`, trả `"Lỗi nội bộ."` — sửa một dòng, đóng kênh rò cho cả 6 endpoint capture hiện có |

**Một giới hạn nói thẳng:** ở chế độ **live** chưa có ai tiêu thụ `elements` — `backend/` chưa có runtime.
Phase 1 giao hợp đồng truyền tải + demo đầy đủ ở **chế độ mock**; Định nghĩa "xong" chỉ khẳng định ở mock, và
giao diện hiện một dòng ghi chú khi chạy live.

---

## Khối lượng & rủi ro

| | Sửa | Thêm mới |
|---|---|---|
| Box | `capture.py`, `browser_capture.py`, `ide-proxy.py`, `Dockerfile`, `smoke-test.sh` | `inspect_element.py`, `tests/test_inspect_element.py`, `docs/architecture/element-selector.md` |
| Frontend | `SandboxScreenPanel.tsx`, `ChatInputBar.tsx`, `types/transport.ts`, `lib/transport/mock.ts`, `i18n/{vi,en}.ts`, `.env.example` | 13 file mã + 10 file test |

**Không thêm apt package. Không thêm npm dependency** (kể cả `@testing-library/react` — repo đã có 7 file
test React dùng bộ dụng cụ tự viết `createRoot` + `act`, dùng lại nó).

**Rủi ro cao nhất, đã có chốt chặn:**

1. **Lộ `webSocketDebuggerUrl`** = mất TCB. Một sanitizer duy nhất `_public_inspect_target()` cạnh
   `_public_tab()`, allow-list đúng 3 khoá, cấm `{**tab}` theo tên, và `SecretLeakTest` khẳng định trên
   **body đã serialize** (nhắm sentinel + khoá + `/devtools/page/`, **không** quét `ws://` vì `title`/`url`
   do trang kiểm soát nên sẽ đỏ giả).
2. **Cạm bẫy P1:** `_NET_CLIENT_LIST_STACKING` in `0x2600003` còn `wmctrl -lx` in `0x02600003` → **mọi** cú
   bấm rơi về desktop. Chuẩn hoá bằng `int(id, 16)` ở cả hai phía.
3. **Drawer đẩy canvas** → `resizeSession` → desktop trong box dàn lại → `screenBox` vừa nhận thành rác.
   Drawer và overlay **phủ lên**, không đẩy.

---

## Xác minh

- Frontend: `npm run typecheck && npm run lint && npm run test` — nền **33 file / 251 test**, kỳ vọng ~345.
- Box: `python3 -m unittest discover -s tests` — chạy được **không cần X server, không cần browser**
  (fake `_run_as_agent` + `FakeWebSocket`).
- Tích hợp: `bash smoke-test.sh` → **29 PASS / 5 FAIL**. **5 FAIL là lỗi sẵn có** (bootstrap-plans lệch
  tên, `test-fixtures/` không được `COPY` vào image), **không sửa trong phạm vi này**, và con số phải **không đổi**.
- "Không làm bẩn desktop": `xdotool getmouselocation` và `getactivewindow` **không đổi** sau 20 lần gọi.

---

## Phase 2 / Phase 3 — phác thảo, không cam kết lần này

- **Phase 2:** Vite plugin **dev-only** stamp `data-boxfox-src="path:LINE:COL"`, **cộng 4 lớp kiểm tra đường
  dẫn**, rồi mới bật hàng `Source:` + `Open in IDE`. (Đọc React fiber là đường chết với React 19.)
- **Phase 3:** `POST /__box/query-element {selector}` → `screenBox` hiện tại + tâm — **đây là câu trả lời
  cho §1.1.2 đặc tả của bạn**: agent CUA click theo selector thay vì pixel dễ lệch. Cộng đa chọn, ghép
  screenshot, `computed styles`, console errors.
