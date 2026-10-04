# H5 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_skill_spec.py`: 63 hàm / **114 ca**; `test_context_bundle.py`: 21 hàm / **79 ca** (số ca theo bảng trạng thái/PR body).
- Probe P3 trong `probes_962cd84.json`: **13/13** —
  - `enable` không đổi version đang được attempt hoạt động ghim;
  - readiness trả `blocked`/`degraded` kèm lý do, không tự chế công cụ;
  - revalidate phát hiện thay đổi role/tool/adapter/source/epoch.
- Bảng mới (additive): `harness_skill_pins` (UNIQUE `(skill_id, attempt_id)`, `skill_spec.py:60`), `harness_skills` (dòng 421), `harness_skill_reviews` (dòng 428), `harness_skill_invocations` (dòng 433).
- Lỗi đã sửa: H5.1 nhiều hàng pin cho một `(skill, attempt)` → DDL UNIQUE + rebuild `_upgrade_pins()`, re-pin thay hàng và ghi `replacedVersion`; H5.2 JSON hỏng rò `JSONDecodeError` → `SKILL_RECORD_CORRUPT`; H5.3 thiếu cột phiên bản record → `RECORD_SCHEMA_VERSION = 1` + `ALTER TABLE` idempotent.

## Chưa kiểm
- Chưa nối runtime: "sau compaction còn đúng intent/consent/pending task/conflict/unknown outcome" chưa exercise trong phiên thật (chỉ có unit của `context_bundle`).
- "Skill reload đúng epoch" mới đạt mức thư viện/probe; chưa có phiên thật nạp lại skill.
- Chưa kiểm đường tool thiếu trong ngữ cảnh executor thật (mức runtime).
