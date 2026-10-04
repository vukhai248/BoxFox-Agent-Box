# H4 — Bàn giao

- **Trạng thái:** verified — đã nối runtime ở `802f51f` (`job_surface.py`, `job_wake.py`); A1–A9/29 đạt trên `c836822`; 54 test `job_surface.py` + 12 test `job_wake.py`.
- **Quyết định:**
  - job có owner (turn hoặc controller); job của turn chết theo turn, job controller sống qua nhiều lượt;
  - mọi đánh thức đi qua outbox + cursor có sàn theo `(consumer, job)` (H4.1);
  - `reconcile` không spawn thay thế — chỉ đối chiếu trạng thái;
  - park ở mọi đường đóng batch, kể cả lượt chốt dở (trần bước/hạn chót); wake chỉ mở lại đúng chủ đã park (H4.7, `f3004ee`).
- **Blocker:** không; giới hạn đã ghi: process job `JOB_EXECUTOR_UNSUPPORTED`, resume theo checkpoint chưa hỗ trợ (H4.5 — fail closed).
- **Việc tiếp:** chạy phiên thật cần consent (H10.1); trước đó giữ công tắc off.
- **Tham chiếu:** `probes_962cd84.json` (P2); nghiệm thu vòng chạy `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`; `docs/plan/reform-status.md` H4–H4.8.
