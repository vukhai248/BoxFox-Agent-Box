# H10 — Khép harness và chuyển roadmap: hợp đồng checkpoint

- **Mục tiêu:** đóng phần harness của reform bằng hồ sơ bàn giao đọc được trên máy khác, chứng minh
  rollback/kill switch không mất dữ liệu và không replay mutation, và để roadmap sau (desktop/native/
  update/mobile) ở trạng thái chưa triển khai.
- **Phạm vi:** tài liệu bàn giao `docs/plan/reform-execution/` (H0–H10), drill rollback/kill switch
  offline, đối chiếu plan ↔ code cuối, disposition backlog, xác nhận rollback reference.
- **Non-goals:** không triển khai native sandbox, desktop/update/mobile, không redesign UI, không
  calibration sống, không đóng các mục `defer` của roadmap.
- **Phụ thuộc:** H1–H9 (mọi blocker bắt buộc đã xử lý); plan duyệt plan_id 1257; runbook §II.2–§II.6.
- **Nghiệm thu:**
  1. Mỗi checkpoint H0–H9 có đủ 5 file `contract/baseline/evidence/migration/handoff`.
  2. Drill rollback/kill switch có artifact thật, chứng minh: công tắc tắt không tạo bảng mới; dữ liệu
     đã ghi vẫn đọc được; mutation không replay; schema cũ và `user_version` không đổi.
  3. Ma trận requirement → evidence → acceptance và disposition backlog có trong README.
  4. Rollback reference rõ (tắt công tắc + không có migration phá compatibility).
  5. Không tuyên bố nào vượt bằng chứng: không OS isolation, không "đã calibration", không nhận "đã
     chạy phiên thật" cho H4–H8 (đã nối runtime, mặc định off, nghiệm thu offline 29/29 trên `c836822`).
- **Điều kiện chưa đạt (tại thời điểm viết):** review toàn snapshot cuối đã chạy trên `ed5d771`/`c3bee48`
  (không phát hiện chặn); còn calibration sống chờ consent (#6531) và drill trên box thật.
