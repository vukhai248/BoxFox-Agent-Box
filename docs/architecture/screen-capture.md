# Kiến trúc chụp màn hình & quay video theo từng app/cửa sổ

> **Cập nhật**: 2026-08-28.  
> **Vị trí code**: `deploy/docker/capture.py`, `deploy/docker/browser_capture.py`, route trong `deploy/docker/ide-proxy.py`.  
> **Mục đích**: thay thế "chụp toàn màn hình" (dễ bị sai khi agent mở 4 cửa sổ Chrome) bằng chụp/quay **đúng một** cửa sổ X11, **một tab** Chromium (CDP) hoặc full-screen dự phòng.

---

## 1. Tóm tắt

Trong box (`agentbox-box`), ta thêm một "capture service" nằm trong `ide-proxy :8081`, mở rộng nhóm endpoint `/__box/*`:

| Method | Path | Ý nghĩa |
|---|---|---|
| GET | `/__box/windows` | Liệt kê cửa sổ X11 (id/class/pid/title/geometry) |
| GET | `/__box/browser/tabs` | Liệt kê tab Chromium (qua CDP `/json/list`) |
| POST | `/__box/capture` | Chụp ảnh theo `target` (window/tab/screen) |
| POST | `/__box/record/start` | Bắt đầu quay video |
| POST | `/__box/record/stop` | Dừng quay, trả đường dẫn + thời lượng |
| GET | `/__box/record/status` | Danh sách bản ghi đang chạy |

Ảnh/video ghi vào `/home/agent/workspace/.generated_artifacts/captures/` (thuộc user `agent`, giống mọi artifact khác của box).

---

## 2. Kiến trúc bên trong box

```
ide-proxy :8081 (root, http.server đa luồng)
   │  route /__box/capture, /__box/record/* ...
   ▼
capture.py (stdlib only, do ide-proxy import trực tiếp)
   ├─ window/screen : gosu agent env DISPLAY=:99 → wmctrl / xprop / xdotool / import / ffmpeg
   └─ tab           : subprocess gosu agent → /opt/pw-driver/bin/python3 browser_capture.py
                        └─ WebSocket CDP tới webSocketDebuggerUrl của tab (127.0.0.1:9222)
```

Quy tắc quan trọng:

1. **`capture.py` thuần stdlib** — không import Playwright. Lý do là **cách ly crash**: một lỗi CDP/Playwright chỉ làm chết tiến trình con `browser_capture.py`, không kéo chết `ide-proxy` (control plane của box).
2. **Mọi thao tác X11 chạy bằng `gosu agent`** + `DISPLAY=:99` + `HOME=/home/agent` — để file sinh ra thuộc `agent:agent` và chạm đúng X server của agent (không cần `XAUTHORITY`, socket `/tmp/.X11-unix/X99` đã `srwxrwxrwx`).
3. **Tab Chromium chụp bằng CDP WebSocket trực tiếp tới `webSocketDebuggerUrl`** của target, không qua Playwright. Vì sao: địa chỉ đích theo đúng `targetId` nên không phải ánh xạ targetId ↔ Playwright `Page` (mong manh), và không nạp cả Playwright vào process dài hạn.

---

## 3. Các gói hệ thống đã thêm vào image

Trong `Dockerfile` (lớp 1) có thêm: `xdotool wmctrl imagemagick ffmpeg x11-utils`.

- `xdotool` → `windowactivate`/`windowraise` (raise cửa sổ trước khi chụp).
- `wmctrl` → `-lx` liệt kê cửa sổ (id/desktop/class/host/title), `-ia` activate. Hình học lấy riêng bằng `xwininfo -id <id>` vì cột của `-lxG` không ổn định (title có dấu cách dễ lẫn với vị trí/kích thước).
- `imagemagick` → lệnh `import` chụp ảnh X11.
- `ffmpeg` → `x11grab -window_id` quay video (Ubuntu 24.04 build sẵn `libx264`, đã xác minh).
- `x11-utils` → `xprop` (đọc `_NET_WM_PID`, `_NET_WM_STATE`), `xwininfo`, ...

---

## 4. Target spec (một spec duy nhất cho mọi endpoint)

Mọi endpoint nhận `target` là một JSON object:

```jsonc
{
  "kind": "window" | "tab" | "screen",

  // kind=window — chọn 1 là đủ, ưu tiên windowId > pid > class > title
  "windowId": "0x02400002",          // id hex từ /__box/windows
  "pid": 1234,                       // PID của tiến trình tạo cửa sổ
  "class": "chromium-playwright",    // WM_CLASS (instance hoặc Class), không phân biệt hoa/thường
  "title": "Trang cần fix",          // chuỗi con, không phân biệt hoa/thường

  // kind=tab — ưu tiên tabId > url > title
  "tabId": "CDC...",                 // target id từ /__box/browser/tabs
  "url": "https://example.com",      // chuỗi con
  "title": "Example",                // chuỗi con

  // chung
  "format": "png" | "jpg",           // capture (mặc định png)
  "fullPage": true,                  // tab: capture toàn trang (mặc định: viewport)
  "framerate": 15,                   // record
  "maxDurationSec": 600              // record, cận trên an toàn
}
```

**Luật chọn khi trùng khớp**: cửa sổ phải `selectable` (không `SKIP_TASKBAR`, không `HIDDEN`); nếu vẫn nhiều → trả `409` kèm danh sách để gọi lại chính xác hơn. Tab/tabId là duy nhất; url/title khớp nhiều → `409`.

**Phạm vi CDP (quan trọng)**: CDP :9222 chỉ thấy Chromium được khởi động **qua wrapper `box-chromium`** (profile cố định `~/.config/box-chromium` + `--remote-debugging-port=9222`). Chromium tạm do agent tự `playwright.chromium.launch()` (profile tạm, port tuỳ ý) **không** xuất hiện trong `/json/list`. Nếu sau này cần chụp cả các Chromium tạm đó, phải thêm cơ chế đăng ký port riêng.

---

## 5. Hợp đồng HTTP (để viết tool computer-use)

### 5.1 Quyền gọi (bảo mật)

Nhóm endpoint capture/record dùng quyền riêng (không phải chỉ Origin). Một request được phép khi **một trong hai** đúng:

1. **Shared secret**: header `X-BoxFox-Api-Key` khớp `BOXFOX_API_KEY` (đặt qua `docker-compose.yml` / `.env`). Đây là đường dành cho **agent backend** gọi server-to-server (không gửi `Origin`).
2. **Origin hợp lệ**: `Origin` ∈ `{http://localhost:3100, http://127.0.0.1:3100, ...}` — đường dành cho **web UI** (:3100) và editor trong box (:8081).

Nếu `BOXFOX_API_KEY` để rỗng: chỉ đường Origin được dùng; process lạ trên host không có secret sẽ bị `403` (fail-closed).

**Vì sao không dùng "loopback trust theo `client_address`"**: `ide-proxy` bind `0.0.0.0` (Docker DNAT), compose publish `127.0.0.1:8081:8081`. Agent backend trên host gọi `127.0.0.1:8081` → đi Docker NAT → trong container `client_address` là IP gateway bridge (vd `172.x.0.1`), **không** phải `127.0.0.1`. Nên kiểm `client_address == 127.0.0.1` sẽ chặn nhầm chính agent backend.

### 5.2 Endpoint chi tiết

#### `GET /__box/windows`

```jsonc
{
  "windows": [
    {"id":"0x02400002","desktop":"0","pid":111,"class":"chromium-playwright.Chromium",
     "title":"Trang cần fix","x":0,"y":0,"w":800,"h":600,
     "state":[],"selectable":true}
  ]
}
```

#### `GET /__box/browser/tabs`

```jsonc
{
  "tabs": [
    {"id":"CDC...","url":"https://example.com","title":"Example","type":"page"}
  ]
}
```

`webSocketDebuggerUrl` là chi tiết nội bộ — KHÔNG lộ ra endpoint public; service tự nối WebSocket CDP khi `capture`/`kind=tab` nhận `tabId`.

#### `POST /__box/capture`

Body: `{"target": {...}, "output": "file" | "base64"}`. Mặc định `output="file"`.

```jsonc
// output=file (mặc định)
{
  "ok": true,
  "path": "/home/agent/workspace/.generated_artifacts/captures/window/...png",
  "width": 800, "height": 600,
  "format": "png", "kind": "window", "method": "x11",
  "sha256": "<sha256 của file>"
}
// output=base64: thêm "data": "<base64 của ảnh>"
```

`method` ∈ `x11` | `cdp`. `sha256` chỉ có ở ảnh (không ở record).

#### `POST /__box/record/start`

Body: `{"target": {"kind":"window"|"screen", ...}}`.

```jsonc
{"ok":true,"recordingId":"rec-1724...","path":".../window/....mp4",
 "format":"mp4","framerate":15,"startedAt":1724... }
```

- Record **v1 KHÔNG hỗ trợ `kind=tab`** (CDP screencast là milestone sau) → trả `501`.
- Tối đa `MAX_CONCURRENT_RECORDS = 2` bản ghi đồng thời; vượt → `409`.
- `maxDurationSec` mặc định 600. Giá trị này được **thực thi** bằng flag `-t` của ffmpeg: bản ghi TỰ dừng khi hết hạn kể cả nếu agent quên gọi `record/stop` hay ide-proxy chết giữa chừng.

#### `POST /__box/record/stop`

Body: `{"recordingId": "rec-..."}`.

```jsonc
{"ok":true,"recordingId":"rec-...","kind":"screen","target":{...},
 "path":".../....mp4","durationSec":2.34,"sizeBytes":12345,"finished":true}
```

Stop bằng SIGINT (ffmpeg finalize `moov`); nếu không dừng sau 20s thì SIGKILL. `gosu` dùng `exec` nên PID ghi lại chính là PID ffmpeg — SIGINT đi thẳng vào ffmpeg.

#### `GET /__box/record/status`

```jsonc
{
  "active":[
    {"recordingId":"rec-...","kind":"window","target":{...},
     "path":"...","pid":123,"startedAt":1724...}
  ],
  "finished":[
    {"recordingId":"rec-...","kind":"screen","target":{...},
     "path":"...","durationSec":2.34,"sizeBytes":12345,"finished":true}
  ]
}
```

`active` = đang chạy; `finished` = đã dừng (do `record/stop` hoặc tự hết `-t`), giữ tối đa 20 bản ghi gần nhất để agent tra lại kết quả.

---

## 6. Mã lỗi

| Mã | Ý nghĩa |
|---|---|
| 400 | target/body không hợp lệ (thiếu selector, format/kind sai, ...) |
| 403 | không được phép (không Origin hợp lệ + không secret) |
| 404 | không tìm thấy cửa sổ/tab/recordingId khớp |
| 405 | method sai |
| 409 | khớp mơ hồ **hoặc** record X11 đang chạy chặn chụp cửa sổ, **hoặc** quá số bản ghi |
| 413 | kích thước vượt trần an toàn (4096×4096 ≈ 16.7 MPx) |
| 500 | lỗi subprocess (wmctrl/import/ffmpeg/browser_capture) |
| 501 | chưa hỗ trợ (record theo tab) |
| 502 | CDP :9222 chưa sẵn sàng (Chromium desktop chưa mở) |

Response lỗi luôn: `{"error": "<chuỗi tiếng Việt>"}`.

---

## 7. Cách viết tool cho agent (computer-use) — phần bạn sẽ tự làm

Đây KHÔNG phải là "guide để agent tự gõ lệnh shell". Cách đúng là **đăng ký capture thành tool** (function calling) trong registry tool của agent, rồi gọi HTTP tới box API. Mô hình:

1. **Backend (FastAPI trên host)** giữ hai cấu hình trong `config`:
   - `box_api_url` (mặc định `http://127.0.0.1:8081`)
   - `box_api_key` (tuỳ chọn, = `BOXFOX_API_KEY` đã cấu hình cho box)
2. Mỗi hàm tool = một HTTP call:
   - `list_windows()` → `GET /__box/windows`
   - `list_tabs()` → `GET /__box/browser/tabs`
   - `capture(target, output="file")` → `POST /__box/capture`
   - `record_start(target)` / `record_stop(recordingId)` / `record_status()`
3. Khi gọi, gắn header `X-BoxFox-Api-Key: <box_api_key>` nếu có secret (server-to-server không có `Origin`).
4. Kết quả trả cho model: đường dẫn file trong workspace (mặc định) hoặc `base64` (nếu cần nhìn ảnh trực tiếp trong ngữ cảnh).
5. Gắn nhãn policy cho tool: mức `EXEC`, nhãn IFC M1 `KHÔNG_TIN_ĐƯỢC` (mọi pixel màn hình đều không tin được — đúng mục 8.5 của `agent-box-plan.md`).

**Còn một guide/Skill ngắn** (bổ trợ, không thay tool): dạy agent *khi nào* dùng — "khi xác minh UI đã sửa, chụp đúng app/cửa sổ/tab đang thao tác; ưu tiên `tab` nếu mục tiêu là Chrome, fallback `window`, cuối cùng `screen`". Guide chỉ mô tả ngữ nghĩa, không liệt kê lệnh shell.

> Ghi chú: `backend/src/agentbox/computer_use/capture.py` + `ToolSpec` nằm trong kế hoạch nhưng **Chưa implement** trong nhánh này — để bạn tự viết theo hợp đồng trên.

---

## 8. Giới hạn & hướng mở rộng

- **Occlusion (bị che)**: X11 không có compositor → trước khi chụp/quay cửa sổ, service tự `raise` cửa sổ. Video `-window_id` vẫn nhiễm nếu bị đè *giữa chừng* — chấp nhận ở v1. Có một mutex toàn cục: khi record X11 đang chạy, chụp ảnh cửa sổ (phải raise) bị từ chối `409` để không phá bản ghi.
- **Video theo tab (CDP screencast)**: chưa làm (`501`). Hiện tại video tab dùng đường X11 `-window_id`; bù lại tab chụp ảnh thì sạch (CDP).
- **Full-page tab**: hỗ trợ qua `fullPage: true` (CDP `Page.getLayoutMetrics` + clip + `captureBeyondViewport`). Mặc định chụp **viewport** (đúng thứ đang hiển thị).
- **Kích thước**: trần an toàn 4096×4096; vượt → `413` buộc chụp nhỏ hơn (tránh OOM vì RandR cho phép tới 32768×32768).
- **Không thu âm thanh**, không gộp nhiều cửa sổ, không tối ưu vùng thay đổi — ngoài phạm vi v1.

---

## 9. Liên quan: Element Selector / DOM Inspector

Endpoint **`POST /__box/inspect-element`** (chọn phần tử trên màn hình rồi đọc node qua CDP) dùng lại
`capture.py` cho hit-test X11 và CDP. Kiến trúc riêng của nó nằm ở
[`element-selector.md`](element-selector.md).
