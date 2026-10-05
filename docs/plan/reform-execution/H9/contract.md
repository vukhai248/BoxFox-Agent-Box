# H9 — Suite v2 và calibration

- **Trạng thái:** partial — lớp mapping/validation + fixture lỗi offline (33/33) + shadow W10.F (34/34 cell, 0 verdict) đã có và ghim bằng test; **calibration sống chưa làm** (cần consent riêng).
- **Mục tiêu:** map oracle legacy; fixture lỗi offline, parity/shadow, live pilot trong consent riêng; rubric outcome/invariant có version.
- **Phạm vi:** `scripts/eval/suite_v2.py`, `scripts/eval/suite-v2.json`, `scripts/eval/fixtures/suite-v2-faults.json`, `backend/tests/unit/test_suite_v2.py` (38 ca).
- **Ngoài phạm vi:** chạy sống (cần consent tài chính riêng — H10.1); sửa suite/W10 cũ để pass; rollout trước evidence gate.
- **Phụ thuộc:** H0, H2–H8.
- **Nghiệm thu (runbook §II.3):** safety oracles giữ nguyên; trajectory-only không ép mode adaptive; báo valid/invalid + quality/cost/latency/interruptions kèm pins; không sửa W10 cũ để pass; không rollout trước evidence gate.
- **Nguồn:** `docs/plan/reform-status.md` H9–H9.2; `scripts/eval/suite-v2.json`; `scripts/eval/suite_v2.py`; shadow report `/code/.generated_artifacts/h3h8/h9/shadow_w10f.json`.
