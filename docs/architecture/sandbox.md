# Kiến trúc máy ảo (sandbox) của BoxFox

> **Cập nhật**: 2026-08-26 — thêm proxy bảo vệ code‑server (PR #2).  
> **Đọc trước nếu chưa quen thuật ngữ**: [Phần 0 của bản kế hoạch](../plan/agent-box-plan.md) — từ điển IFC, N1–N5, V1–V5.

Tài liệu này mô tả **mọi thứ chạy bên trong box** (container Docker `agentbox-box`), cách các kênh kết nối từ giao diện web vào box, và những lớp bảo vệ ở mỗi kênh.

---

## 1. Tổng quan — box chạy những gì?

Khi bạn gõ `docker compose up -d` trong `deploy/docker/`, container khởi động và chạy các tiến trình sau (theo thứ tự khởi động):

```
┌─────────────────────────────────────────────────────────┐
│  CONTAINER agentbox-box (Ubuntu 24.04)                  │
│                                                         │
│  ┌──────────┐  ┌───────────────────┐  ┌──────────────┐ │
│  │  Xvnc    │  │  XFCE desktop     │  │  code-server │ │
│  │  :99     │  │  (panel, cửa sổ,  │  │  :8080       │ │
│  │  màn ảo  │  │   icon, taskbar)  │  │  editor web  │ │
│  └────┬─────┘  └────────┬──────────┘  └──────┬───────┘ │
│       │                 │                     │         │
│       ▼                 │                     ▼         │
│  ┌──────────┐           │              ┌──────────────┐ │
│  │  (X+RFB) │◄──────────┘              │  ide-proxy   │ │
│  │  :5900   │                          │  :8081       │ │
│  │  server  │                          │  Python 35 d │ │
│  │  VNC     │                          │  +CSP frame- │ │
│  └────┬─────┘                          │   ancestors  │ │
│       │                                └──────┬───────┘ │
│       ▼                                        │         │
│  ┌──────────────┐                              │         │
│  │  websockify  │                              │         │
│  │  :6080       │                              │         │
│  │  WebSocket + │                              │         │
│  │  Origin check│                              │         │
│  └──────────────┘                              │         │
│                                                 │         │
│  ┌──────────────────────────────────────────────┘         │
│  │  Cả ba cổng (5900, 6080, 8080, 8081)                  │
│  │  bind loopback (127.0.0.1) — không ra mạng ngoài       │
│  └────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────┘
```

| Tiến trình | Cổng | Vai trò |
|---|---|---|
| **Xvnc** (TigerVNC — X server CÓ RFB tích hợp) | `:99` (X) + `5900` (RFB) | Vừa là "màn hình" trong RAM cho desktop vẽ lên, vừa là VNC server phát màn hình đó ra. MỘT tiến trình thay cho Xvfb + x11vnc trước đây. **Điểm quan trọng: RandR động tới 32768×32768 và nhận `SetDesktopSize` từ client** — nhờ vậy khi người dùng kéo panel khung ④, noVNC xin đổi phân giải và desktop khớp đúng kích thước panel, không sinh viền đen. Xvfb không làm được điều này: `maximum` của nó BẰNG kích thước khởi tạo. |
| **XFCE** (môi trường desktop) | Không có cổng, vẽ lên Xvnc `:99` | Tạo ra desktop giống một máy tính thật: MỘT thanh taskbar ở đáy (menu ứng dụng · danh sách cửa sổ · đồng hồ), icon trên màn hình, quản lý cửa sổ. Theme tối `Greybird-dark` + icon set `elementary-xfce-dark` để hòa với giao diện web và để icon có logo thật (XFCE trần dùng theme sáng và không có icon set nào ⇒ mọi icon thành ô vuông trống). Tự reflow khi Xvnc đổi phân giải — đã đo `_NET_WORKAREA` bám chính xác screen ở mọi khổ. |
| **websockify** (cầu nối TCP → WebSocket) | `6080` | Bọc VNC (`:5900`, giao thức TCP thuần) thành WebSocket để trình duyệt đọc được. **Kiểm tra header `Origin`**: chỉ nhận kết nối từ `localhost:3100` và `127.0.0.1:3100`. Từ chối tất cả Origin khác — kể cả request thiếu header Origin. |
| **code‑server** (VS Code bản web) | `8080` | Editor chạy trong box, mở sẵn `/home/agent/workspace`. Người dùng sửa file ở đây là sửa thật trong box. Chạy với `--auth none --disable-telemetry --disable-update-check`. |
| **ide‑proxy** (proxy bảo vệ code‑server) | `8081` | Ngồi giữa giao diện web và code‑server `:8080`. Forward mọi request, nhưng **chèn CSP `frame-ancestors`** vào response — chỉ `localhost:3100` và `127.0.0.1:3100` mới nhúng được editor vào iframe. |

---

## 2. Hai kênh kết nối từ giao diện web vào box

Giao diện BoxFox (chạy ở `localhost:3100`) kết nối với box qua **đúng hai kênh**. Mỗi kênh có cơ chế bảo vệ riêng.

### 2.1 Kênh 1: Màn hình box thật — khung ④ (qua noVNC)

```
TRÌNH DUYỆT                     │  BOX (loopback)
                                │
┌──────────────────────┐        │  ┌─────────┐    ┌──────────┐    ┌──────────┐
│  Khung ④             │        │  │ Xvnc :99│◄───│  XFCE    │    │  VS Code │
│  SandboxScreenPanel  │        │  │ 1280×800│    │ desktop  │    │  (Web)   │
│                      │        │  └────┬─────┘    └──────────┘    └──────────┘
│  useVncScreen        │        │       │
│  (hook React)        │        │       ▼
│                      │        │  ┌─────────┐
│  @novnc/novnc        │◄───────│──│ (X+RFB) │
│  (thư viện VNC)      │  WS    │  │ :5900   │
│                      │ :6080  │  └────┬─────┘
└──────────────────────┘        │       │
                                │       ▼
                                │  ┌──────────────┐
         Origin =               │  │ websockify   │ ← kiểm tra Origin:
         localhost:3100 ────────│──│ :6080        │   chỉ localhost:3100
                                │  └──────────────┘   và 127.0.0.1:3100
```

**Đường đi của dữ liệu**:

1. Người dùng mở tab "Sandbox Machine" trong giao diện web.
2. `useVncScreen` hook khởi tạo `RFB` (thư viện noVNC) — mở WebSocket tới `ws://localhost:6080/websockify`.
3. Websockify **kiểm tra header `Origin`** của request WebSocket:
   - `Origin: http://localhost:3100` → ✅ cho qua
   - `Origin: http://evil.example.com` → ❌ 403 Invalid Origin
   - Không có header `Origin` → ❌ 403 (chặn client thô không-phải-trình-duyệt)
4. Nếu Origin hợp lệ, websockify bắc cầu TCP tới Xvnc `:5900`.
5. Xvnc gửi các khung hình của display `:99` qua RFB. Chiều ngược lại: noVNC gửi `SetDesktopSize` khi panel đổi kích thước ⇒ Xvnc đổi phân giải thật, XFCE reflow, không có viền đen và chữ không bị nội suy.
6. noVNC giải mã RFB và vẽ lên `<canvas>` trong khung ④.

**Bảo vệ**:

| Lớp | Cơ chế |
|---|---|
| **Origin (nguồn gốc — trang web nào đang request)** | Websockify từ chối mọi Origin không phải `localhost:3100`. Ngay cả một tab khác trong cùng trình duyệt cũng không mở được WebSocket nếu Origin sai. |
| **Loopback (chỉ nhận kết nối từ chính máy này)** | Cả ba cổng (`5900`, `6080`, `8080`) đều bind `127.0.0.1`. Máy khác trong mạng LAN không vào được. |
| **M1 — integrity (tính toàn vẹn) khung hình** | Mọi pixel từ khung ④ đều mang nhãn `khong_tin_duoc` (untrusted — không đáng tin). Panel viết thẳng chữ này, không đọc từ dữ liệu. Agent không được dùng pixel làm nguồn sự thật. |

### 2.2 Kênh 2: Tab IDE — editor nhúng trong giao diện (qua proxy)

```
TRÌNH DUYỆT                     │  BOX (loopback)
                                │
┌──────────────────────┐        │  ┌──────────────┐    ┌──────────────┐
│  Tab IDE              │        │  │ ide-proxy    │    │ code-server  │
│  IdePanel             │        │  │ :8081        │───▶│ :8080        │
│                      │        │  │ Python       │    │ editor web   │
│  useIdeFrame         │        │  │ + CSP        │    └──────────────┘
│  (hook React)        │        │  │ frame-       │
│                      │        │  │ ancestors    │
│  <iframe>            │◄───────│──│              │
│                      │  HTTP  │  └──────────────┘
└──────────────────────┘        │
                                │
         Trình duyệt tự kiểm    │
         CSP frame-ancestors ───│── response chứa:
                                │   frame-ancestors localhost:3100
                                │   127.0.0.1:3100
```

**Đường đi của dữ liệu**:

1. Người dùng mở tab "IDE (VS Code Web)".
2. `useIdeFrame` hook **thăm dò trước**: gửi `fetch(mode:'no-cors')` tới `:8081`, đợi tối đa 4 giây.
   - Phản hồi → phase chuyển `probing` → `live`, mount `<iframe>`.
   - Không phản hồi → phase `offline`, hiện countdown thử lại (3s → 8s → 20s, tối đa 4 lượt).
3. Khi `live`, `<iframe src="http://localhost:8081/…">` nạp code‑server.
4. **Proxy (`:8081`)** nhận request, forward tới code‑server `:8080`, đọc response, **chèn header CSP** vào rồi trả về:
   ```
   Content-Security-Policy: …; frame-ancestors http://localhost:3100 http://127.0.0.1:3100
   ```
5. **Trình duyệt** đọc CSP này và tự thực thi: nếu trang đang mở iframe **không** phải từ `localhost:3100` hoặc `127.0.0.1:3100`, trình duyệt từ chối hiển thị iframe.

**Bảo vệ**:

| Lớp | Cơ chế |
|---|---|
| **CSP frame-ancestors (Content Security Policy — chính sách bảo mật nội dung, chỉ thị "tổ tiên của khung")** | Proxy chèn header CSP vào mọi response của code‑server. Trình duyệt chỉ hiển thị iframe nếu trang cha có origin khớp. |
| **Loopback** | Cả `:8080` và `:8081` đều bind `127.0.0.1`. |
| **sandbox iframe** | Thuộc tính `sandbox` trên `<iframe>` của tab IDE cho phép scripts/same-origin/forms/downloads/modals/popups nhưng **không** cấp `allow-top-navigation` — trang trong khung không thể redirect (điều hướng) cả tab BoxFox. |
| **Cross-origin (khác nguồn gốc)** | Giao diện (`:3100`) và code‑server (`:8081`) khác cổng → khác origin. Trang ngoài không đọc được DOM (cây tài liệu) của code‑server. |

---

## 3. Mô hình bảo vệ ba lớp

```
┌─────────────────────────────────────────────────────────────┐
│                     TRÌNH DUYỆT                              │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Lớp 3: Trình duyệt tự thực thi                        │  │
│  │ • CSP frame-ancestors — không nhúng nếu origin sai     │  │
│  │ • sandbox iframe — không redirect, không popup bừa     │  │
│  │ • Same-origin policy — không đọc DOM của trang khác   │  │
│  └───────────────────────────────────────────────────────┘  │
│                         │                                    │
│                         ▼                                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Lớp 2: Proxy + websockify trong box                   │  │
│  │ • Proxy kiểm tra và chèn CSP (kênh IDE)               │  │
│  │ • Websockify kiểm tra Origin (kênh VNC)               │  │
│  │ Cả hai đều từ chối request từ origin lạ              │  │
│  └───────────────────────────────────────────────────────┘  │
│                         │                                    │
│                         ▼                                    │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Lớp 1: Docker loopback                                │  │
│  │ • Tất cả cổng bind 127.0.0.1                          │  │
│  │ • Máy khác trong mạng LAN không vào được              │  │
│  │ • Kẻ tấn công từ xa không thấy cổng nào               │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Các cổng — tổng kết

| Cổng | Bind | Dịch vụ | Giao thức | Bảo vệ |
|---|---|---|---|---|
| `5900` | `127.0.0.1` | Xvnc (X server + RFB) | TCP/RFB | Loopback + websockify Origin check |
| `6080` | `127.0.0.1` | websockify | WebSocket | **Origin check** (chỉ `localhost:3100`, `127.0.0.1:3100`) |
| `8080` | `127.0.0.1` | code‑server | HTTP/WebSocket | Loopback + proxy CSP |
| `8081` | `127.0.0.1` | ide‑proxy | HTTP | **CSP `frame-ancestors`** (chỉ `localhost:3100`, `127.0.0.1:3100`) |

> **Ghi chú**: cổng `8080` không được giao diện web dùng trực tiếp nữa. Giao diện luôn đi qua proxy `:8081`. Người dùng vẫn có thể mở `http://localhost:8080` trực tiếp trên trình duyệt nếu muốn — `frame-ancestors` không chặn truy cập top‑level (trang mở trực tiếp, không qua iframe).

---

## 5. Đường vào từ bên trong box (desktop XFCE)

Người dùng mở khung ④, thấy desktop XFCE. Trên desktop có các icon:

| Icon | Mở ra | Ghi chú |
|---|---|---|
| **VS Code (Web)** | Chromium `--app` trỏ `http://localhost:8081/…` | Đi qua proxy — cùng cơ chế bảo vệ như tab IDE |
| **Chromium** | Trình duyệt đầy đủ | Agent dùng để đọc web, thao tác trang |
| **Xfce Terminal** | Terminal trong box | Chạy lệnh trực tiếp |
| **Thunar** | Trình duyệt file | Xem/sửa file trong `/home/agent/workspace` |

Lưu ý: **Không còn icon "Visual Studio Code" (bản Electron)** — đã bị xoá khỏi image ở PR #2. Editor duy nhất trong box là code‑server (bản web).

---

## 6. Quy tắc bảo mật liên quan (trích từ bản kế hoạch)

| Quy tắc | Nội dung | Áp dụng ở đâu |
|---|---|---|
| **N1** (single enforcement point — một điểm thực thi duy nhất) | Mọi quyết định bảo mật đi qua Controller. Không có đường tắt. | Editor trong box **không** bật extension AI — nếu có, extension đó là một kênh ra thứ hai không ai kiểm soát. |
| **N3** (only Controller issues leases — chỉ Controller cấp giấy phép) | Chỉ Controller được cấp giấy phép truy cập tài nguyên. | Cùng lý do — AI extension tự gọi API là tự cấp quyền cho chính nó. |
| **M1** (screen integrity — tính toàn vẹn màn hình) | Mọi pixel đều mang nhãn `khong_tin_duoc`. | Cả khung ④ (màn hình VNC) và tab IDE (editor web) đều hiển thị badge "Không tin được". Panel tự viết chữ này, không đọc từ dữ liệu. |
| **Quy tắc 12.6** (loopback) | Kênh điều khiển chỉ bind loopback. | Tất cả bốn cổng (`5900`, `6080`, `8080`, `8081`) đều bind `127.0.0.1`. |
| **V4** (caveat — lưu ý) | Người dùng gõ trực tiếp vào box thì đầu vào đó chưa vào sổ audit (nhật ký kiểm toán). | Tab IDE hiển thị rõ cảnh báo này trong dải nhãn. |

---

## 7. Số đo thực tế (đo ngày 2026-08-26, sau khi chuyển sang Xvnc)

Đo bằng `docker exec agentbox-box ps -eo rss=,args=` ngay sau `docker compose up -d`
(box vừa bật, chưa mở workspace lớn, chưa mở Chromium). Đây là **RSS** (Resident
Set Size — toàn bộ trang trong RAM, KỂ CẢ trang chia sẻ giữa các tiến trình), nên
cộng dồn từng dòng sẽ LỚN HƠN con số `docker stats` báo cho cả container. Không
dùng PSS vì image không có `smem`.

| Thành phần | RSS | Ghi chú |
|---|---|---|
| **Xvnc** (X server + RFB) | 43 MB | MỘT tiến trình thay cho cả `Xvfb` (45 MB) + `x11vnc` (15 MB) trước đây |
| XFCE desktop | 237 MB | `xfce4-session` 80 + `xfdesktop` 45 + `xfce4-panel` 32 + `xfwm4` 31 + `xfsettingsd` 26 + `Thunar` 23 |
| code‑server | 127 MB | 2 tiến trình `node` (server + extension host), không tính client |
| websockify (VNC → WS) | 69 MB | 2 tiến trình `python3` (parent + handler) |
| tty-bridge + ide-proxy | 52 MB | 2 tiến trình `python3` |
| Khác (dbus, xfconfd, gpg-agent) | 19 MB | Hạ tầng |
| **`docker stats` cho cả container** | **193 MiB** | Con số nên dùng khi tính chi phí máy chủ |
| Image size | 3.42 GB | `docker image ls agentbox-sandbox` |

> Đổi `Xvfb` + `x11vnc` → `Xvnc`: bớt 1 tiến trình, RSS phần màn hình giảm
> ~60 MB → 43 MB. Image tăng 3.37 GB → 3.42 GB (~+50 MB) vì thêm
> `tigervnc-standalone-server` + `xfonts-base` (~+10 MB) và bộ theme/icon
> `elementary-xfce-icon-theme` + `greybird-gtk-theme` (~+19 MB nén).
>
> Không so trực tiếp với bảng cũ trước PR #2 (box còn VS Code desktop Electron)
> nữa: bảng đó đo **PSS** (1132 MB), bảng này đo **RSS** — hai thang khác nhau,
> ghép lại sẽ ra kết luận sai. Mốc duy nhất so được là image: 3.96 GB → 3.42 GB.
