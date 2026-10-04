# H10 — Handoff

- **Trạng thái:** `partial`. Tài liệu bàn giao H0–H9 + H10 đã có; drill rollback/kill switch đạt
  11/11; toàn bộ unit suite trên `c836822` chỉ còn 3 lỗi có sẵn của baseline; H4–H8 đã nối runtime và
  nghiệm thu mức vòng chạy **29/29 PASS** trên `c836822`; review toàn snapshot cuối đã chạy trên
  `ed5d771`/`c3bee48` (không phát hiện chặn; should-fix tài liệu đã sửa). Còn thiếu: H9 live pilot +
  calibration sống (H10.1 — hoãn #6531), các quyết định của chủ nhà.
- **Head bàn giao:** `f7e4a9b` trên `vorflux/boxfox-harness-reform` (PR #3, base
  `vorflux/w10-w12-completion`); chuỗi việc 2026-10-04: `79f024b`, `c6c88bb`, `fcc6819`, `b37dafb`,
  `82550cc`; lần soát tài liệu này nằm trong chính mốc này.
- **Quyết định đã ghi:**
  - PR #3 giữ base là nhánh khảo sát; retarget về `main` chỉ sau khi nhánh khảo sát merge — chờ chủ nhà.
  - Ngữ nghĩa gọi lại `delegate_task`: cùng `invocationId` = thử lại (attempt mới nếu attempt cũ đã
    đóng); khác `invocationId` cùng `taskId` bị kho từ chối. Cách đọc trong seam map H3 mục (b) chặt
    hơn — chờ chủ nhà xác nhận.
  - `attemptSeq` theo phiên (F5) giữ nguyên, ghi nhận là hạn chế; đổi sang seq theo task cần migration
    chỉ mục.
  - Không tiêu tiền cho calibration sống khi chưa có consent riêng; phần giới hạn ngân sách hoãn
    tương lai (#6531).
- **Blocker:** không có blocker kỹ thuật đang chặn; H10.1 hoãn #6531 (consent tài chính riêng).
- **Việc tiếp theo (thứ tự đề xuất):**
  1. Chủ nhà quyết retarget PR #3 và cách đọc ngữ nghĩa follow-up.
  2. H9: live pilot + calibration (H10.1) chỉ khi có consent tài chính riêng; mở rộng shadow khi có
     receipt dạng cell cho R/Q/RV2/seeded.
  3. Ghi lại kết quả review toàn snapshot cuối + cách đếm test khi khép H10.
- **Rollback:** xem `migration.md`; drill `rollback_drill_962cd84.log` (11/11).
