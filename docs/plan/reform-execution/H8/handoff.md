# H8 — Bàn giao

- **Trạng thái:** partial — thư viện + probe đạt; chưa nối composer runtime.
- **Quyết định:**
  - mọi quyết định adaptive phải kèm `reason` + `evidenceRefs` (P6);
  - stop/revoke luôn thắng; cùng chữ ký lỗi + bằng chứng không đổi → chặn (H8.3);
  - không phát minh trần step/wall; trần chỉ đến từ policy/consent (H8.1/H8.5).
- **Blocker:** không; giới hạn là chưa nối runtime.
- **Việc tiếp:** khi nối, thêm E2E "một scheduler cho mỗi admission" + đo hiệu quả trong calibration; chạy lại P6 ở mức runtime.
- **Tham chiếu:** `probes_962cd84.json` (P6); `docs/plan/reform-status.md` H8–H8.5.
