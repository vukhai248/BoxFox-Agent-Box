# H5 — Bằng chứng

## Kiểm tra thật
- `backend/tests/unit/test_skill_spec.py`: 63 hàm / **114 ca**; `test_context_bundle.py`: 21 hàm / **79 ca** (số ca theo bảng trạng thái/PR body).
- Probe P3 trong `probes_962cd84.json`: **13/13** —
  - `enable` không đổi version đang được attempt hoạt động ghim;
  - readiness trả `blocked`/`degraded` kèm lý do, không tự chế công cụ;
  - revalidate phát hiện thay đổi role/tool/adapter/source/epoch.
- Bảng mới (additive): `harness_skill_pins` (UNIQUE `(skill_id, attempt_id)`, `skill_spec.py:60`), `harness_skills` (dòng 421), `harness_skill_reviews` (dòng 428), `harness_skill_invocations` (dòng 433).
- Lỗi đã sửa: H5.1 nhiều hàng pin cho một `(skill, attempt)` → DDL UNIQUE + rebuild `_upgrade_pins()`, re-pin thay hàng và ghi `replacedVersion`; H5.2 JSON hỏng rò `JSONDecodeError` → `SKILL_RECORD_CORRUPT`; H5.3 thiếu cột phiên bản record → `RECORD_SCHEMA_VERSION = 1` + `ALTER TABLE` idempotent.

## Nối runtime (`802f51f` + `b37dafb`)
- `context_surface.py`: 56 test trên head (53 lúc nối `802f51f`); ghim ref canonical + hash cho nén tự động/`/compact`, `mode_skill`, `read_skill`, `handoff_to`; công tắc `BOXFOX_CONTEXT_SURFACE` mặc định off.
- Nghiệm thu vòng chạy B1–B5 nằm trong **29/29 PASS** trên `c836822` — `/code/.generated_artifacts/h4h8/runs/official-c836822/summary.json` (gồm "skill chưa admit bị chặn").
- `b37dafb`: khi kho đăng ký skill trống (không seed), fallback đọc catalog để bật công tắc không làm mọi `skill_view` ném `SKILL_UNKNOWN`; hàng tồn tại nhưng chưa enable vẫn bị chặn.

## Chưa kiểm
- Chưa có phiên thật dài ngày để đo recall sau compaction ngoài envelope nghiệm thu (cần consent H10.1).
- Đường tool thiếu trong executor thật: phủ ở mức unit/acceptance; chưa có số đo ngoài envelope.
