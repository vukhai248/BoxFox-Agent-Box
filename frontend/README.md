# Frontend — giao diện web

React + Vite + TypeScript + Tailwind. Đây là **tầng 1** của kiến trúc bảy tầng.

Tài liệu: [`../docs/plan/agent-box-plan.md`](../docs/plan/agent-box-plan.md), **Phần XII**.

Quyết định đã chốt ở mục 12.1: **giao diện web, không làm CLI.**

## Năm khung — `src/panels/`

Bảng 12.2 của kế hoạch. Khung ⑤ là khung mà Devin và OpenHands đều không có.

| File đề xuất | Khung | Nội dung | Ghi chú bảo mật |
|---|---|---|---|
| `ChatPanel.tsx` | ① Hội thoại + Hỏi/Đáp | Dòng hội thoại, thẻ xin quyền hiện trong luồng này | — |
| `FileTreePanel.tsx` | ② Cây file + xem nội dung | Chấm màu cạnh mỗi file = nhãn của file đó | Nội dung file là dữ liệu bẩn — render **văn bản thuần** |
| `TerminalPanel.tsx` | ③ Terminal | `xterm.js` | **Chỉ đọc.** Người dùng không gõ được vào đây |
| `SandboxScreenPanel.tsx` | ④ Màn hình sandbox | `noVNC` | Người dùng **điều khiển được** (quy tắc V2, mục 12.3.1) — agent không bị dừng. Khung hình **luôn** mang integrity `khong_tin_duoc` (quy tắc M1, mục 8.5) |
| `LabelsLeasesPanel.tsx` | ⑤ Bảng Nhãn & Giấy phép | Nhãn đang có trong ngữ cảnh, các giấy phép còn hạn, phạm vi từng cái | Đây là khung làm cơ chế bảo mật **nhìn thấy được** |

## Hai thẻ quan trọng nhất — `src/components/`

| File đề xuất | Mục | Vì sao quan trọng |
|---|---|---|
| `PermissionCard.tsx` | 12.5 | Thẻ xin quyền. Phải hiện đủ **năm thứ**: việc gì · nội dung nguyên văn (diff cho `write_file`) · vì sao phải hỏi · nguồn gốc bấm được · các nút |
| `ModeSwitchCard.tsx` | **12.5.1** | Thẻ chuyển chế độ Plan → Act. Ít gặp hơn nhưng **nặng hơn**: một cú bấm cấp giấy phép trùm cả một phạm vi trong 30 phút |

### Ba luật tuyệt đối cho hai thẻ này

1. **Không có nút "luôn cho phép" hay "đừng hỏi lại".** Đây chính xác là lỗi mà arXiv 2510.26328 chỉ ra, và cơ chế của dự án tồn tại để chặn nó. Thêm nút đó là bỏ luôn đóng góp.
2. **Mọi nội dung bẩn render dạng văn bản thuần, không dựng thành HTML.** Nếu một chỉ thị độc trong `README.md` được render thành HTML trong giao diện thì đã mở thêm một kênh tấn công ngay trong công cụ bảo mật.
3. **Dòng phạm vi trên `ModeSwitchCard` phải khớp tuyệt đối** `canonical_resources` của giấy phép sẽ được cấp. Ca test **T7f** kiểm đúng điều này — lệch một đường dẫn cũng là lỗi, vì đó là thứ người dùng đọc để đồng ý.

## Các thư mục còn lại

| Thư mục | Nội dung |
|---|---|
| `src/hooks/` | `useWebSocket.ts` (kết nối lại thì hiện lại yêu cầu còn hạn, mục 12.4), `usePermissionRequests.ts` |
| `src/lib/` | Client gọi API, hàm định dạng, hàm map nhãn sang màu |
| `src/types/` | Kiểu TypeScript **sinh từ schema của backend**, không gõ tay lại — nhãn và giấy phép lệch kiểu giữa hai bên là một lớp bug rất khó thấy |
| `public/` | Tài nguyên tĩnh |

## Bốn quy tắc luồng không đồng bộ (mục 12.4)

Vòng lặp agent là đồng bộ, giao diện web thì không. Bốn quy tắc phải cài đúng:

1. Yêu cầu quyền có thời hạn **10 phút**; quá hạn tính là **từ chối**.
2. Trả lời phải kèm `request_id` và backend kiểm `task_epoch` còn khớp — chặn việc trả lời một thẻ của phiên cũ.
3. Agent **dừng thật** khi chờ, không chạy tiếp đoán trước câu trả lời.
4. Mất WebSocket rồi kết nối lại thì hiện lại các yêu cầu **còn hạn**.

## Xem màn hình box thật (khung ④, noVNC)

Khung ④ có hai nguồn khung hình, chọn bằng `VITE_SANDBOX_SCREEN_SOURCE`:

| Giá trị | Nguồn khung hình | Gói `@novnc/novnc` |
|---|---|---|
| không đặt, hoặc `mock` | màn hình **mô phỏng** dựng sẵn (cảnh demo VPI, mục 14.5) | **không nạp**, không mở socket nào |
| `novnc` | màn hình **máy thật** qua websockify của box | nạp động thành chunk riêng khi mở khung ④ |

Mặc định là `mock` có lý do: hook noVNC nối độc lập với transport của agent, nên
nếu cứ hễ mount là nối thì trên máy đang chạy box, màn hình thật sẽ chiếm chỗ
của khung hình mô phỏng và phá luôn kịch bản demo prompt-injection 8 bước.

Khi `VITE_TRANSPORT=live` thì `novnc` được bật ngầm (transport thật ⇒ hiển
nhiên là muốn xem máy thật). Đặt `VITE_SANDBOX_SCREEN_SOURCE=mock` để chặn kể
cả trong trường hợp đó.

### Chạy thử với box thật

```bash
# 1) Bật box (Xvnc + desktop XFCE + websockify + code-server)
cd ../deploy/docker && docker compose up -d

# 2) Bật giao diện với nguồn khung hình là máy thật
cd ../../frontend
VITE_SANDBOX_SCREEN_SOURCE=novnc npm run dev
```

Rồi mở **`http://localhost:3100`** — đúng `localhost`, không phải IP LAN, không
phải HTTPS. Ba lý do, cả ba đều làm kênh chết nếu bỏ qua:

1. `websockify` trong box chạy `--auth-plugin ExpectOrigin` và chỉ nhận
   `http://localhost:3100` / `http://127.0.0.1:3100`; Origin khác ⇒
   `403 Invalid Origin`. Đổi được qua biến `BOX_ALLOWED_ORIGINS` của container.
2. noVNC yêu cầu **ngữ cảnh an toàn**; `localhost` được tính là an toàn, IP LAN
   thì không. Panel phát hiện việc này và báo `insecureContext` thay vì để
   noVNC vỡ ở chỗ khó đọc.
3. Trang HTTPS + kênh `ws://` = mixed content, trình duyệt chặn thẳng
   (`mixedContent`).

Cổng `5900/6080/8080` của box chỉ bind `127.0.0.1` (mục 12.6), nên trình duyệt
phải chạy trên chính máy host.

Trong khung ④ sẽ hiện **một desktop bình thường** (XFCE): thanh taskbar, menu
ứng dụng, icon trên nền — Chromium và VS Code là các **ứng dụng** trong máy đó,
không phải toàn bộ màn hình. Box lúc mới bật không tự mở ứng dụng nào (triết lý
"máy trống"), nên màn hình đầu tiên bạn thấy là desktop trống — bấm icon
để mở, hoặc để agent tự mở.

Kích thước màn hình box đặt qua biến `BOX_SCREEN` của container (mặc định
`1280x800x24`); panel căn giữa và co giãn vừa khung nên tỷ lệ khác sẽ sinh
viền đen, không méo hình.

### Không nối được thì sao

Panel tự thử lại: 1 lần đầu + 3 lần, nghỉ 3s → 8s → 20s, mỗi lần chờ tối đa 5
giây. Hết lượt thì dừng và đợi người dùng bấm "Thử kết nối lại" — mỗi lần thất
bại trình duyệt tự ghi một dòng đỏ WebSocket vào console (không tắt được), nên
thử lại vô hạn là làm ô nhiễm console. Trong lúc đó khung ④ hiện màn hình mô
phỏng, có viền gạch chéo + thẻ "MÔ PHỎNG" để không ai nhìn nhầm là máy thật.
