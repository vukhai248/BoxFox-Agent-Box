# H9 — Bàn giao

- **Trạng thái:** partial — lớp mapping/validation + **fixture lỗi offline (33/33)** + **shadow legacy (34/34 cell, 0 verdict)** đã có và được ghim bằng test; phần **đo live** chưa làm.
- **Quyết định:**
  - suite v2 tách hẳn khỏi suite W10; không sửa bản cũ để pass;
  - `measured=false` cho tới khi có evidence gate; `livePilotRequiresConsent=true`;
  - giữ 4 disposition, trong đó `preserve_invariant` bảo vệ 40 safety oracle.
- **Blocker:** live calibration cần **consent tài chính riêng** (H10.1) — không tự chạy.
- **Việc tiếp:** khi có consent thì chạy live pilot và ghi số kèm pins; mở rộng shadow khi các nhóm R/Q/RV2/seeded có receipt dạng cell.
- **Tham chiếu:** `scripts/eval/suite-v2.json`, `scripts/eval/suite_v2.py`, `scripts/eval/fixtures/suite-v2-faults.json`, `backend/tests/unit/test_suite_v2.py` (38 test); shadow report `/code/.generated_artifacts/h3h8/h9/shadow_w10f.json`; `docs/plan/reform-status.md` H9–H9.1.
