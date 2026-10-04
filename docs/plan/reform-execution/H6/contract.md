# H6 — Phân bổ và hạch toán

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`usage_surface.py`, seam `complete_model`); nghiệm thu mức vòng chạy C1–C5 nằm trong **29/29 PASS** trên `c836822`. Phần **giới hạn ngân sách** (allocation + trần chi + `BOXFOX_USAGE_LEDGER` cho phiên thật) hoãn tương lai theo #6531.
- **Mục tiêu:** sổ usage từng call, price snapshot + độ chắc chắn, reservation/settlement nguyên tử, reconcile, tín hiệu effort/loop/progress.
- **Phạm vi:** `usage_ledger.py` (55 ca), `usage_surface.py` (22 ca); nối runtime (seam `complete_model`, `/compact`); sửa lỗi vòng review H6.1–H6.7.
- **Ngoài phạm vi:** gọi model thật để lấy giá/độ trễ (thuộc H9/H10.1 — hoãn #6531); ghim allocation cho phiên thật.
- **Phụ thuộc:** H3, H4; metadata đã có trên code đích.
- **Nghiệm thu (runbook §II.3):** retry/child/Research không double-count hoặc reset spend; giá lạ không thành 0; usage timeout còn unsettled; caller constraints và Stop có hiệu lực; defaults mới cần calibration, không tự chọn số hãng khác.
- **Nguồn:** `docs/plan/reform-status.md` H6–H6.10; probe P4 `probes_962cd84.json`; nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`.
