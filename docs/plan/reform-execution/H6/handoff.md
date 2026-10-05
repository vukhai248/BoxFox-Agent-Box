# H6 — Bàn giao

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`usage_surface.py` + seam `complete_model`); C1–C5/29 đạt trên `c836822`; phần giới hạn ngân sách hoãn tương lai theo #6531.
- **Quyết định:**
  - giá không biết = `None` (không phải 0) và giữ `unsettled` (H6.1/H6.4);
  - hold của con tính vào trần của cha; con phải lặp đúng `consent_ref` của cha (H6.2/H6.5);
  - idempotency theo từng allocation + hash invocation, chống áp dụng đúp A→B→A (H6.3);
  - một seam `complete_model` cho mọi request (retry/summary/repair); hết trần chặn TRƯỚC khi gọi model (H6.6); `/compact` cũng qua seam (H6.7).
- **Blocker:** không; calibration sống hoãn #6531 — **không tự chạy**.
- **Việc tiếp:** khi chủ nhà mở consent, chạy calibration trong envelope H9/H10.1 rồi mới chọn số mặc định; giữ nguyên hợp đồng ledger.
- **Bật dần:** công tắc của checkpoint này nằm trong nhóm bật dần H3–H8 — thứ tự, khuôn kiểm 5 bước và rollback ở `docs/plan/reform-execution/HANDOFF.md` §6.
- **Tham chiếu:** `probes_962cd84.json` (P4); nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`; demo giá giả `/code/.generated_artifacts/h4h8/free_model_mock_price_demo.py`; `docs/plan/reform-status.md` H6–H6.10.
