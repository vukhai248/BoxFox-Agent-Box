# H4 — Job qua nhiều lượt

- **Trạng thái:** đạt mức thư viện + probe; **chưa nối runtime** nên các điều kiện mức vòng chạy chưa kiểm.
- **Mục tiêu:** ownership của controller, process handle, subscription/outbox bền, cursor, wake lock, reconcile sau restart; con do turn sở hữu vẫn dọn theo hợp đồng cũ.
- **Phạm vi:** `harness_jobs.py` + `backend/tests/unit/test_harness_jobs.py`; sửa lỗi vòng review H4.1–H4.3.
- **Ngoài phạm vi:** nối vào runtime/composer (chưa làm); UI/desktop; job cho môi trường ngoài harness.
- **Phụ thuộc:** H2, H3.
- **Nghiệm thu (runbook §II.3):** heartbeat/log không mở model turn; completion out-of-order/duplicate/late có một hiệu lực; idle chat không làm job mồ côi; stop/revoke chặn admission và kiểm process tree.
- **Nguồn:** `docs/plan/reform-status.md` H4–H4.3; probe P2 `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`.
