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

## Chưa kiểm
- Chưa nối runtime (không có src importer): chưa kiểm "stop/revoke chặn admission + process tree" và "idle chat không làm job mồ côi" bằng vòng chạy thật.
- Chưa có E2E nhiều lượt với job nền; số liệu duy nhất hiện có là unit + probe.
