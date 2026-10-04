# H4 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_harness_jobs.py`: 56 hàm / **59 ca** (số ca theo bảng trạng thái/PR body).
- Probe P2 trong `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`: **10/10** —
  - heartbeat/log/progress **không** đánh thức model; `result`/`blocker`/`owner_subscribed` đánh thức;
  - completion trùng/đến muộn có một hiệu lực; `reconcile` không spawn thay thế (`spawned==0`);
  - job do turn sở hữu chết theo turn; job do controller sở hữu sống qua turn;
  - wake lock chỉ một người đọc.
- Bảng mới (additive): `harness_jobs`, `harness_wake_outbox`, `harness_wake_cursors`, `harness_wake_locks`, `harness_job_invocations` (`harness_jobs.py` dòng 71–100). `HarnessJobs(store, confirm_executor=None)` fail closed khi thiếu executor xác nhận.
- Lỗi đã sửa: H4.1 cursor `wait` toàn cục bỏ sót sự kiện khi tập watch lớn lên (LEFT JOIN cursor + sàn theo `(consumer, job)`); H4.2 replay append với `expected_revision` cũ bị trả `JOB_REVISION_CONFLICT` oan; H4.3 JSON hỏng rò `JSONDecodeError` → `JOB_RECORD_CORRUPT`.

## Nối runtime (`802f51f` + follow-up)
- `job_surface.py` (54 test) + `job_wake.py` (12 test): 5 công cụ controller + park/wake qua `rt.start` hiện hữu; `park_after_batch` ở mọi đường đóng batch, kể cả lượt chốt dở vì trần bước/hạn chót (`f3004ee`); wake chỉ mở lại đúng chủ đã park.
- Ghim số công cụ orchestrator 51 → 60 (`c1de24f`): 5 công cụ job + 4 công cụ Research gateway; công tắc `BOXFOX_CONTROLLER_JOBS` mặc định off.
- Nghiệm thu vòng chạy A1–A9 nằm trong **29/29 PASS** trên `c836822` — `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`.

## Chưa kiểm
- Process job (`JOB_EXECUTOR_UNSUPPORTED`) và resume theo checkpoint attempt chưa hỗ trợ — fail closed (H4.5, giới hạn đã biết).
- Chưa có phiên thật chạy dài ngày (cần consent H10.1) để đo ngoài envelope nghiệm thu offline.
