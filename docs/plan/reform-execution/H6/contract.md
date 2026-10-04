# H6 — Phân bổ và hạch toán

- **Trạng thái:** đạt mức thư viện + probe; **chưa nối runtime**; số mặc định cho calibration **chưa chốt** (cần consent tài chính riêng).
- **Mục tiêu:** sổ usage từng call, price snapshot + độ chắc chắn, reservation/settlement nguyên tử, reconcile, tín hiệu effort/loop/progress.
- **Phạm vi:** `usage_ledger.py` (55 ca); sửa lỗi vòng review H6.1–H6.5.
- **Ngoài phạm vi:** gọi model thật để lấy giá/độ trễ (thuộc H9/H10.1, cần consent); nối composer runtime.
- **Phụ thuộc:** H3, H4; metadata đã có trên code đích.
- **Nghiệm thu (runbook §II.3):** retry/child/Research không double-count hoặc reset spend; giá lạ không thành 0; usage timeout còn unsettled; caller constraints và Stop có hiệu lực; defaults mới cần calibration, không tự chọn số hãng khác.
- **Nguồn:** `docs/plan/reform-status.md` H6–H6.5; probe P4 `probes_962cd84.json`.
