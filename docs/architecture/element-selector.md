# Kiến trúc Element Selector / DOM Inspector cho khung ④

> **Cập nhật**: 2026-08-29.
> **Vị trí code**: `deploy/docker/capture.py`, `deploy/docker/browser_capture.py`,
> `deploy/docker/inspect_element.py`, route trong `deploy/docker/ide-proxy.py`;
> phía giao diện `frontend/src/lib/inspect/`, `frontend/src/lib/vnc/inspect.ts`,
> `frontend/src/hooks/useElementInspector.ts`, `frontend/src/components/sandbox/ElementInspectorOverlay.tsx`
> và `ElementInspectorDrawer.tsx`.
> **Kế hoạch nguồn**: `docs/plan/element-selector-plan-v1.md` (bản đã phê duyệt). Chỗ nào kế hoạch và
> tài liệu này lệch nhau thì **kế hoạch thắng**.

---

## 1. Tóm tắt

Thêm khả năng "chỉ tay vào phần tử trên màn hình desktop ảo rồi xem nó là gì": người dùng bật chế độ
chọn trong toolbar khung ④, **bấm một cái** vào canvas noVNC; điểm bấm CSS được quy đổi sang toạ độ
framebuffer/X11, gửi lên box dưới dạng `{x, y}`; box hit-test ngăn xếp cửa sổ X11 rồi — nếu điểm rơi vào
viewport trình duyệt Chromium — hỏi Chrome qua CDP để lấy node tại đúng điểm đó; ngược lại **suy biến mềm**
sang nhánh `desktop` (thông tin cửa sổ + một trong **11 mã `reason`**). Giao diện vẽ khung sáng, mở ngăn
kéo kết quả, và cho phép đính phần tử vào khung soạn tin như một chip.

| Method | Path | Ý nghĩa |
|---|---|---|
| POST | `/__box/inspect-element` | Nhận `{x, y}` framebuffer; trả nhánh `dom` hoặc `desktop` |

Đây là endpoint **chỉ-đọc**: nó không bao giờ tổng hợp sự kiện con trỏ hay cú bấm, nên việc bấm vào nút
`[X]` của Chrome trong lúc thanh tra **không đóng Chrome**.

---

## 2. Luồng từ đầu đến cuối

```
   (frontend)                      (box, agentbox-box)
   ┌─────────────────────────────┐      ┌──────────────────────────────────────────┐
   │ canvasPointToFramebuffer()  │      │ ide-proxy :8081  route /__box/inspect-element │
   │  CSS → framebuffer/X11      │ ──▶  │   │  _capture_allowed(): Origin + shared-secret │
   │  (null nếu ở dải đen)       │      │   ▼  inspect_element.dispatch_inspect_element(x,y)│
   └─────────────────────────────┘      │        ├─  semaphore (tối đa 2 đồng thời)       │
                                        │        ├─  1. xwininfo/xprop: hứng cửa sổ         │
                                        │        │        dưới điểm bấm (hit-test X11)       │
                                        │        ├─  2. frame_extents() trừ viền trang trí   │
                                        │        ├─  3. là Chromium?                         │
                                        │        │        └─ không → nhánh desktop not_chromium │
                                        │        ├─  4. CDP 127.0.0.1:9222/json/list          │
                                        │        │        ├─  chốt chặn 1: DevTools docked?   │
                                        │        │        ├─  chốt chặn 2: gốc viewport hợp lý?│
                                        │        │        └─  tìm target khớp cửa sổ X11       │
                                        │        ├─  5. browser_capture.py inspect_point      │
                                        │        │        └─  DOM.getNodeForLocation +        │
                                        │        │           Runtime.callFunctionOn (selector) │
                                        │        └─  6. dựng label + content_hash (3 bước)    │
                                        └──────────────────────────────────────────┘
```

Bất kỳ thất bại nào ở bước 4–5 **không bao giờ thành 500** — nó suy biến thành nhánh `desktop` với đúng
mã `reason` (§3), vẫn trả HTTP 200 để ngăn kéo hiện thông tin cửa sổ.

---

## 3. Bảng 11 mã `reason` (suất phát từ §5.2 của kế hoạch)

`reason` là union chuẩn, **bộ tên dưới đây thắng** mọi bộ tên cũ trong các bản nháp. Cả 11 mã đều trả
HTTP 200 + nhánh `desktop`.

| `reason` | Khi nào |
|---|---|
| `not_chromium` | Cửa sổ dưới điểm bấm không phải Chromium (Terminal, code-server, Thunar…) |
| `outside_viewport` | Điểm bấm ở titlebar / tab strip / toolbar / scrollbar / vùng trang trí xfwm4 |
| `frame_extents_unknown` | Không đọc/parse được `_NET_FRAME_EXTENTS` và điểm bấm nằm trong dải nghi vấn quanh client area — fail-closed |
| `devtools_docked` | DevTools đang docked trong chính cửa sổ đó ⇒ không suy được gốc viewport — trạng thái **không hỗ trợ** ở Phase 1 |
| `viewport_origin_unknown` | Sai lệch còn lại vượt ngưỡng (side panel, chrome bất thường) |
| `no_cdp_target` | Không tìm được CDP target khớp cửa sổ X11 đã hit |
| `ambiguous_target` | Nhiều target khớp, không phân giải được |
| `cdp_unreachable` | `127.0.0.1:9222` không trả lời (Chromium chết / đang khởi động lại) |
| `cdp_timeout` | Vượt ngân sách CDP 5 s, ngân sách toàn cục 8 s, hoặc subprocess hết giờ (`TimeoutExpired`) |
| `no_node_at_point` | `DOM.getNodeForLocation` không trả `backendNodeId` |
| `extract_failed` | `Runtime.callFunctionOn` ném / trả hình dạng sai |

Chỉ 4 loại HTTP mới là lỗi thật: **400** (toạ độ ngoài màn hình / không phải số nguyên), **403** (thiếu
secret, thiếu Origin), **404** (không có cửa sổ nào dưới điểm bấm **và** không đọc được stacking order),
**500/504** (lỗi nội bộ / hết giờ toàn cục).

---

## 4. Hợp đồng phản hồi

### 4.1 Nhánh `dom`

```jsonc
{
  "type": "dom",
  "selector": "main > div#notice > span.text-sm",
  "url": "https://…",
  "title": "…",
  "tagName": "span",
  "text": "…",
  "attributes": { "class": "…", "data-role": "…" },
  "html": "<span …>…</span>",           // cắt ngắn, kèm truncated
  "truncated": false,
  "cssBox":  { "x": 0, "y": 0, "width": 0, "height": 0 },
  "screenBox": { "x": 0, "y": 0, "width": 0, "height": 0 },
  "notes": ["selector_not_unique"],
  "shadowHostSelector": null,
  "target": { "windowId": "0x02600003", "windowTitle": "…", "targetId": "…" },
  "label": { … }                          // xem §5
}
```

### 4.2 Nhánh `desktop`

```jsonc
{
  "type": "desktop",
  "reason": "not_chromium",              // một trong 11 mã §3
  "appName": "Xfce4-terminal",            // class phần sau dấu '.' cuối
  "windowClass": "xfce4-terminal.Xfce4-terminal",
  "windowTitle": "…",
  "windowId": "0x02600007",
  "position": { "x": 12, "y": 48 },
  "size": { "width": 800, "height": 600 },
  "pid": 9021,
  "label": { … }                          // xem §5
}
```

Quy tắc bỏ khoá: `appName` bỏ khi class rỗng; `pid` bỏ khi `None` (không trả `null`); `message`/`reason`
bỏ khi `reason == "not_chromium"` (không có gì *thất bại* cả) — khớp cách `_public_tab()` lọc khoá.

### 4.3 Bảo mật chuyển tiếp — `webSocketDebuggerUrl` không bao giờ xuất hiện

`webSocketDebuggerUrl` là handle điều khiển toàn quyền trình duyệt (mở WS tới `:9222` rồi `Page.navigate`,
`Runtime.evaluate`, đọc cookie). Lộ nó là **mất TCB**. Cho nên:

- Chỉ có **một chokepoint duy nhất** dựng target công khai: `capture.py::_public_inspect_target(win, tab)`
  với allow-list **đúng 3 khoá** `("windowId", "windowTitle", "targetId")`, nằm ngay cạnh `_public_tab()`.
- Mọi place khác dựng bằng **allow-list**, cấm deny-list theo tên.
- Test `SecretLeakTest` serialize toàn payload và tìm `webSocketDebuggerUrl` / `devtoolsFrontendUrl` / `ws://`
  ở mọi độ sâu, trên cả nhánh `dom`, nhánh `desktop`, lẫn đường lỗi.

---

## 5. Khối `label` — dữ liệu KHÔNG TIN ĐƯỢC, trên CẢ HAI nhánh

```jsonc
"label": {
  "integrity": "khong_tin_duoc",
  "confidentiality": "noi_bo",
  "source_kind": "screen_capture",
  "source_uri": "screen://element/0x02600003",   // KHÔNG nhúng selector
  "tool_name": "inspect_element",
  "content_hash": "sha256:9f2b…"
}
```

- **Cả hai nhánh** đều `khong_tin_duoc` — kể cả desktop, vì `windowTitle` bắt nguồn từ `document.title`,
  tức là kẻ tấn công ghi được.
- **`source_uri` không nhúng `selector`.** Selector là chuỗi do trang kiểm soát; nhúng nó vào một URI mà
  giao diện và log đều hiển thị là mở thêm kênh chèn nội dung. Chỉ dùng `windowId` (hex X11, do ta sinh).
- **`content_hash` — 3 bước chốt cứng, tránh tự tham chiếu:** (1) dựng response ngữ nghĩa **chưa có `label`**;
  (2) `sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True))`; (3) mới gắn
  `label` (kèm `content_hash`).
- Phía frontend **ghi đè cứng** `integrity = 'khong_tin_duoc'` bất kể box trả gì (quy tắc M1), dùng hằng
  `INSPECTED_ELEMENT_CONFIDENTIALITY = 'noi_bo'` làm dự phòng khi giá trị nhận về ngoài enum.

---

## 6. Hai chốt chặn bắt buộc trước khi hỏi CDP

Trước khi gọi `DOM.getNodeForLocation`, trên cùng một kết nối CDP:

1. **Chốt chặn 1 — phát hiện DevTools docked** (dùng lại kết quả `GET /json/list`, không fetch lại): tìm
   target `url` bắt đầu `devtools://` mà query chứa `targetId` của trang; so
   `Browser.getWindowForTarget().windowId` với windowId của trang — **trùng ⇒ DOCKED** ⇒ nhánh desktop với
   `reason="devtools_docked"`, **không bao giờ gọi `getNodeForLocation`**; khác ⇒ UNDOCKED, đi tiếp; đọc
   windowId **lỗi** ⇒ coi như DOCKED (fail-closed).
2. **Chốt chặn 2 — gốc viewport hợp lý**: `slackX ≤ 24` và `slackY ≤ 200`; không thì
   `reason="viewport_origin_unknown"`.

Cả hai chốt chặn tồn tại vì một DevTools docked mỏng (≈150 px + chrome) vẫn nhỏ hơn ngưỡng `slackY`, nên
ngưỡng không đủ để loại; và ngược lại, side panel / chrome bất thường chỉ có thể loại bằng ngưỡng.

---

## 7. Ngân sách thời gian

Ngân sách toàn cục `REQUEST_BUDGET_SEC = 8.0` là **trần duy nhất**. Mọi thao tác con (thăm dò X11, CDP,
subprocess `inspect_point`) nhận một deadline tính bằng `max(0.05, deadline − now)` và một `cap` riêng; vì
thế `timeout` truyền cho subprocess **không bao giờ vượt** ngân sách toàn cục. `subprocess.TimeoutExpired`
được map thành `cdp_timeout` (đặt `except` **trước** nhánh `SubprocessError`, vì nó là lớp con), không phải
`cdp_unreachable`. Hết ngân sách ⇒ không spawn subprocess nữa, trả `cdp_timeout`.

---

## 8. Giới hạn đã biết

- **`MAX_SIDE_SLACK_PX = 24`** và **`MAX_CHROME_HEIGHT_PX = 200`** là hai ngưỡng chốt ở trên
  (`inspect_element.py`). Side panel Chrome hoặc chrome bất thường vượt ngưỡng này ⇒ bị chặn thẳng với
  `viewport_origin_unknown` thay vì đoán (một lần đoán sai là trả đúng phần tử *sai* cho người dùng).
  **Trị đo thực tế trên image `agentbox-sandbox` (Chromium-1148 của Playwright, Xvnc 1280×800, DPI 96):**
  với profile sạch + `--no-first-run` browser chrome ≈ **196 px** (`slackY`), còn với profile dính
  `box-chromium` (bookmark bar + trạng thái khôi phục) lên ~**249 px** ⇒ vượt ngưỡng. Ngưỡng 200 cố ý nằm
  đúng giữa hai mức này: nhận cửa sổ Chromium bình thường (196), chặn cửa sổ có chrome tích luỹ (249) và
  mọi side panel / theme dày hơn.
- **DevTools docked (đáy hoặc phải) là trạng thái không hỗ trợ ở Phase 1** và trả `devtools_docked`; DevTools
  ở cửa sổ riêng (undocked) vẫn cho kết quả đúng.
- **Không có `source` / "Open in IDE" ở Phase 1.** Vị trí trong mã nguồn (`{file, line, column}`) hoãn sang
  Phase 2 vì `data-boxfox-src` là thuộc tính do **trang web bất kỳ** tự đặt, và mở file theo đường dẫn đó mà
  chưa validate là một đường đi trọn vẹn từ dữ liệu web không tin được tới thao tác mở file nội bộ. Bản kế
  hoạch §10.3 quy định thêm **cùng lúc**: kiểu, 4 lớp validate phía box, nhánh UI.
- **Phase 1 giao hợp đồng truyền tải + demo đầy đủ ở chế độ mock.** Việc tiêu thụ `elements` ở backend thật
  (agent live) là ngoài phạm vi Phase 1 — `backend/` chưa có runtime nào.
