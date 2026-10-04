# H10 — Handoff

- **Trạng thái:** `partial`. Tài liệu bàn giao H0–H9 + H10 đã có; drill rollback/kill switch đạt
  11/11; toàn bộ unit suite trên `962cd84` chỉ còn 3 lỗi có sẵn của baseline. Còn thiếu: review toàn
  snapshot cuối, nghiệm thu mức vòng chạy cho H4–H8, H9 offline/parity, calibration sống (H10.1).
- **Head bàn giao:** `962cd84` trên `vorflux/boxfox-harness-reform` (PR #3, base
  `vorflux/w10-w12-completion`).
- **Quyết định đã ghi:**
  - PR #3 giữ base là nhánh khảo sát; retarget về `main` chỉ sau khi nhánh khảo sát merge — chờ chủ nhà.
  - Ngữ nghĩa gọi lại `delegate_task`: cùng `invocationId` = thử lại (attempt mới nếu attempt cũ đã
    đóng); khác `invocationId` cùng `taskId` bị kho từ chối. Cách đọc trong seam map H3 mục (b) chặt
    hơn — chờ chủ nhà xác nhận.
  - `attemptSeq` theo phiên (F5) giữ nguyên, ghi nhận là hạn chế; đổi sang seq theo task cần migration
    chỉ mục.
  - Không tiêu tiền cho calibration sống khi chưa có consent riêng.
- **Blocker:** không có blocker kỹ thuật đang chặn; H10.1 blocked theo consent tài chính.
- **Việc tiếp theo (thứ tự đề xuất):**
  1. Chủ nhà quyết retarget PR #3 và cách đọc ngữ nghĩa follow-up.
  2. Review toàn snapshot sau `962cd84` (một vòng, miền: nối runtime + khoá sổ).
  3. H9: fixture lỗi offline + parity/shadow run (offline, không tốn phí).
  4. H4–H8: nối runtime theo run, kèm parity + negative control trước khi bật.
  5. H10.1: chỉ khi có consent tài chính riêng.
- **Rollback:** xem `migration.md`; drill `rollback_drill_962cd84.log` (11/11).
