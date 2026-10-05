# H4 — Job qua nhiều lượt

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`job_surface.py`, `job_wake.py`); nghiệm thu mức vòng chạy A1–A9 nằm trong **29/29 PASS** trên `c836822`.
- **Mục tiêu:** ownership của controller, process handle, subscription/outbox bền, cursor, wake lock, reconcile sau restart; con do turn sở hữu vẫn dọn theo hợp đồng cũ.
- **Phạm vi:** `harness_jobs.py` + `job_surface.py` + `job_wake.py` và test tương ứng; nối runtime (công cụ controller, park/wake); sửa lỗi vòng review H4.1–H4.8.
- **Ngoài phạm vi:** UI/desktop; job tiến trình ngoài harness (fail closed — H4.5); scheduler thứ hai (không thêm).
- **Phụ thuộc:** H2, H3.
- **Nghiệm thu (runbook §II.3):** heartbeat/log không mở model turn; completion out-of-order/duplicate/late có một hiệu lực; idle chat không làm job mồ côi; stop/revoke chặn admission và kiểm process tree.
- **Nguồn:** `docs/plan/reform-status.md` H4–H4.8; probe P2 `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`; nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`.
