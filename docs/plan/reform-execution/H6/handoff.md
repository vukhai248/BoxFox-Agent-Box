# H6 — Bàn giao

- **Trạng thái:** partial — thư viện + probe đạt; chưa nối runtime; calibration chờ consent.
- **Quyết định:**
  - giá không biết = `None` (không phải 0) và giữ `unsettled` (H6.1/H6.4);
  - hold của con tính vào trần của cha; con phải lặp đúng `consent_ref` của cha (H6.2/H6.5);
  - idempotency theo từng allocation + hash invocation, chống áp dụng đúp A→B→A (H6.3).
- **Blocker:** calibration sống cần consent tài chính riêng — **không tự chạy**.
- **Việc tiếp:** khi có consent, chạy calibration trong envelope H9/H10.1 rồi mới chọn số mặc định; giữ nguyên hợp đồng ledger.
- **Tham chiếu:** `probes_962cd84.json` (P4); `docs/plan/reform-status.md` H6–H6.5.
