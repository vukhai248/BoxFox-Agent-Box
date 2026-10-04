# H10 — Bằng chứng

## Đã chạy

- **Drill rollback / kill switch (offline, không model, không tốn phí)** — `962cd84`:
  - Lệnh: `PYTHONPATH=backend/src TMPDIR=/var/tmp backend/.venv/bin/python /code/.generated_artifacts/h3h8/drill/rollback_drill.py`
  - Kết quả: **11/11 check PASS** — `/code/.generated_artifacts/h3h8/drill/rollback_drill_962cd84.log`
  - Nội dung: công tắc tắt (mặc định) → lượt không thấy công cụ `task_*`, `dispatch` từ chối
    `TASK_SURFACE_OFF`, **không bảng `harness_*` nào sinh ra**; bật công tắc → ghi thật 1 task +
    1 attempt + 1 message; tắt lại → dữ liệu còn nguyên (số hàng và payload hash không đổi,
    revision 2 → 2), mutation `task_abandon` bị từ chối trước khi chạm kho, schema các bảng cũ
    không đổi, `PRAGMA user_version` không đổi, không bảng grant/verdict nào sinh ra.
- **Toàn bộ unit suite** — `962cd84`: `backend/tests/unit` → **3 failed, 4060 passed, 12 skipped
  in 1131.01s** (log phiên chạy `/var/tmp/full_unit_962cd84.log`). Ba lỗi đỏ trùng khớp trên cây
  baseline `346da06`: `test_terminal_exec_echo`, `test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`,
  `test_revoked_grant_blocks_next_tool_call`.
- **E2E real-runtime + probe** (từ H3, nhãn `962cd84-final`): 9/9 scenario (110 check), P1–P6 71/71 —
  `/code/.generated_artifacts/h3h8/e2e/summary.json`, `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`.
- **Test Report 956 (v2, PASSED)** cho PR #3 — tiêu đề `H1–H2 — hợp đồng task, kernel admission và
  kho task bền vững (PR #3)` (báo cáo hội tụ một tiêu đề theo hướng dẫn).

## Artifact tham chiếu

- `/code/.generated_artifacts/h3h8/drill/rollback_drill.py`, `/code/.generated_artifacts/h3h8/drill/rollback_drill_962cd84.log`
- `/code/.generated_artifacts/h3h8/unit/scoped_suites_962cd84.log`
- `/code/.generated_artifacts/h3h8/e2e/summary.json`, `E1.json`–`E7.json`, `E3c.json`
- `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`
- `/code/.plans/reform-impl-pr-body.md` (thân PR #3), `docs/plan/reform-status.md` (bảng Hx.y)

## Chưa kiểm (không được ghi là đã đạt)

- Review toàn snapshot cuối sau `962cd84` (mới có review theo miền rủi ro ở vòng trước).
- Nghiệm thu mức vòng chạy cho H4–H8 (chưa nối runtime — không có src importer).
- H9: fixture lỗi offline, parity/shadow run, live pilot.
- H10.1: calibration sống (cần consent tài chính riêng; `financial_consent_ref: null`).
- Drill trên môi trường thật (docker/box) — drill này chạy offline trên SQLite tạm; chưa kiểm
  rollback khi có phiên đang chạy thật.
