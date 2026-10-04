# H9 — Bàn giao

- **Trạng thái:** partial — lớp mapping/validation đã có và được ghim bằng test; phần đo (fixture lỗi offline, parity/shadow, live pilot) chưa làm.
- **Quyết định:**
  - suite v2 tách hẳn khỏi suite W10; không sửa bản cũ để pass;
  - `measured=false` cho tới khi có evidence gate; `livePilotRequiresConsent=true`;
  - giữ 4 disposition, trong đó `preserve_invariant` bảo vệ 40 safety oracle.
- **Blocker:** live calibration cần **consent tài chính riêng** (H10.1) — không tự chạy.
- **Việc tiếp:** bổ sung fixture lỗi offline + chạy parity/shadow; khi có consent thì chạy live pilot và ghi số kèm pins.
- **Tham chiếu:** `scripts/eval/suite-v2.json`, `scripts/eval/suite_v2.py`, `backend/tests/unit/test_suite_v2.py`; `docs/plan/reform-status.md` H9–H9.1.
