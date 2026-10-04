# H7 — Bàn giao

- **Trạng thái:** partial — thư viện + probe đạt; chưa nối runtime.
- **Quyết định:**
  - Research là hệ chuyên gia độc lập: intent của main là **đầu vào**, không bao giờ canonical (H7.1/P5);
  - publication/review bind theo version; refresh/revision không sửa kết quả cũ;
  - các điểm vào chưa xác thực phải gọi `authorize(...)` khi nối (H7.2).
- **Blocker:** không; giới hạn là chưa nối runtime + chưa có Research sống.
- **Việc tiếp:** khi wiring, thêm E2E main↔Research qua envelope và migrate read view trên dữ liệu thật; chạy P5 lại ở mức runtime.
- **Tham chiếu:** `probes_962cd84.json` (P5); `docs/plan/reform-status.md` H7–H7.2.
