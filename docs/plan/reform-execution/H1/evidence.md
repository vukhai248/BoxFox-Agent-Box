# H1 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_orchestration_contracts.py`: **77 ca** (số ca thu thập theo bảng trạng thái/PR body; 15 hàm `def test_`, phần lớn dùng parametrize).
- Nhóm 17 file H1–H9 chạy trên cây sửa review: **780 passed in 119.25s** — `/var/tmp/h3h8_group_run.log`.
- Bộ 13 file phạm vi H3–H9 trên head `962cd84`: **716 passed in 100.46s** — `/code/.generated_artifacts/h3h8/unit/scoped_suites_962cd84.log`.
- Đọc dữ liệu cũ: `/var/tmp/boxfox-testing/results/legacy_read_3975ab6.json` → 8/8 kiểm tra đạt (không tạo grant/verdict mới khi đọc record legacy).

## Theo nghiệm thu
- **Fixtures đọc dữ liệu cũ không tự tạo grant/verdict:** đạt — legacy read 8/8; module chỉ parse/validate, không ghi.
- **Alias trùng / ID reuse khác payload / stale revision / schema unsupported bị từ chối:** đạt — `test_snapshot_severs_caller_and_reader_mutations`, `test_invalid_model_fields_fail_closed`, `test_unsupported_schema_has_specific_code`; lỗi H1.3 sửa ở `3975ab6` (thiếu cột bắt buộc → `TASK_SCHEMA_UNSUPPORTED`, không chỉ theo `schema_version`).
- **Hash/approval lịch sử không đổi:** đạt — không có thay đổi trên bảng approval/verdict; `test_revision_does_not_coerce_boolean_string_or_float` ghim quy ước revision (H1.2).
- **Trần độ dài trường text:** đạt — `test_unbounded_contract_text_fails_closed` + `test_contract_text_at_the_limit_is_accepted` (H1.1, `ab26776`).

## Chưa kiểm
- Chưa có log riêng của lần chạy từng file trên `962cd84`; số 77 lấy từ bảng trạng thái + `/code/.plans/reform-impl-pr-body.md` dòng 55.
