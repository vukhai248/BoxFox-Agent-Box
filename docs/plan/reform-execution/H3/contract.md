# H3 — Bề mặt task và hồi phục

- **Trạng thái:** verified — bề mặt task đã nối runtime thật; E2E 9/9, probe 71/71, scoped 716 passed trên `962cd84`.
- **Mục tiêu:** lớp `task_list/get/send/abandon` trên child registry; alias cha ổn định, attempts, invocation dedupe; phân loại hồi phục provider/model/tool; giữ partials và biên nhận.
- **Phạm vi:** `task_surface.py` (40 ca), `recovery_policy.py` (39 ca), nối `runtime` (turn_profile gỡ công cụ khi tắt, dispatch từ chối, hook `project_child` ở 4 bộ đóng con, `delegate_task` tạo task + bind attempt); sửa H3.1–H3.10.
- **Ngoài phạm vi:** job nền (H4); nối `recovery_policy` vào vòng chạy thật (module độc lập, xem evidence); native isolation.
- **Phụ thuộc:** H1, H2.
- **Nghiệm thu (runbook §II.3):** `wait=false` vẫn dùng kernel cũ; duplicate message/spawn không tạo effect mới; terminal follow-up tạo attempt mới qua admission; mutation outcome unknown không replay; cancellation có receipt.
- **Nguồn:** `docs/plan/reform-status.md` H3–H3.11; `/code/.plans/reform-h3-seams.md`; artifact `/code/.generated_artifacts/h3h8/`.
