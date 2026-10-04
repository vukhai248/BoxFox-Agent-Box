# H5 — Bàn giao

- **Trạng thái:** partial — thư viện + probe đạt; chưa nối runtime.
- **Quyết định:**
  - pin skill theo `(skill_id, attempt_id)` là duy nhất; epoch pin là nguồn sự thật (H5.1);
  - record có cột phiên bản + decode lỗi trả mã `SKILL_RECORD_CORRUPT` (H5.2/H5.3);
  - không import/nhúng bộ skill tham khảo bên ngoài.
- **Blocker:** không; giới hạn là phạm vi nối runtime.
- **Việc tiếp:** khi nối composer/loader, chạy lại P3 ở mức runtime + thêm ca compaction thật; giữ hợp đồng epoch đã ghim.
- **Tham chiếu:** `probes_962cd84.json` (P3); `docs/plan/reform-status.md` H5–H5.3.
