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
- **Toàn bộ unit suite** — `962cd84`: **3 failed, 4060 passed, 12 skipped in 1131.01s**
  (`/var/tmp/full_unit_962cd84.log`); đo lại trên `c836822` (cây sạch, sau khi nối H4–H8):
  **3 failed, 4277 passed, 12 skipped in 1273.91s** (`/code/.generated_artifacts/h4h8/unit/full_unit_c836822.log`).
  Ba lỗi đỏ trùng khớp baseline `346da06`: `test_terminal_exec_echo`,
  `test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`, `test_revoked_grant_blocks_next_tool_call`.
- **Nghiệm thu mức vòng chạy H4–H8 (official, head `c836822`, offline)**: **29/29 PASS** — parity P1/P2 +
  H4 A1–A9, H5 B1–B5, H6 C1–C5, H7 D1–D4, H8 E1–E4 (`/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json`).
- **E2E real-runtime + probe** (từ H3, nhãn `962cd84-final`): 9/9 scenario (110 check), P1–P6 71/71 —
  `/code/.generated_artifacts/h3h8/e2e/summary.json`, `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`.
- **H9 offline (từ H9, độc lập kiểm lại trên `ed5d771`):** `--faults` 33/33 lỗi bắt đúng mã;
  `--shadow /code/.plans/w10f-adjudication-working.json` 34/34 cell (17 ca × 2 repeat), `verdictsProduced=0`;
  `test_suite_v2.py` 38 passed — `/code/.generated_artifacts/h9/verification_summary.json`.
- **Review toàn snapshot cuối (H10) trên `ed5d771`/`c3bee48`:** không phát hiện chặn; 1 should-fix về
  tài liệu (tham chiếu snapshot cũ — đã sửa); risk **2/10** (ngưỡng 6). Sau đó: `c836822`/`8a4bc54`/
  `a95576d` ghi nhận bằng chứng, và việc 2026-10-04 (`79f024b`, `c6c88bb`, `fcc6819`, `b37dafb`, `82550cc`).
- **Test Report 956 (v3, PASSED)** cho PR #3 — tiêu đề `H1–H2 — hợp đồng task, kernel admission và
  kho task bền vững (PR #3)` (báo cáo hội tụ một tiêu đề theo hướng dẫn; v3 bổ sung vòng H9 offline).

## Artifact tham chiếu

- `/code/.generated_artifacts/h3h8/drill/rollback_drill.py`, `/code/.generated_artifacts/h3h8/drill/rollback_drill_962cd84.log`
- `/code/.generated_artifacts/h3h8/unit/scoped_suites_962cd84.log`
- `/code/.generated_artifacts/h3h8/e2e/summary.json`, `E1.json`–`E7.json`, `E3c.json`
- `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json`
- `/code/.plans/reform-impl-pr-body.md` (thân PR #3), `docs/plan/reform-status.md` (bảng Hx.y)

## Chưa kiểm (không được ghi là đã đạt)

- Phiên thật dài ngày cho H4–H8 (đã nối runtime, mặc định off; mới có nghiệm thu offline 29/29 trên `c836822`).
- H9: live pilot + calibration sống (H10.1); shadow cho R/Q/RV2/seeded khi có receipt dạng cell.
- H10.1: calibration sống (cần consent tài chính riêng; `financial_consent_ref: null`).
- Drill trên môi trường thật (docker/box) — drill này chạy offline trên SQLite tạm; chưa kiểm
  rollback khi có phiên đang chạy thật.
