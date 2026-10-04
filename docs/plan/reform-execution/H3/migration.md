# H3 — Migration / rollback

- Dữ liệu: dùng lại bảng additive của H2 (`harness_tasks`, `harness_task_attempts`, `harness_task_messages`, `harness_invocations`); không thêm DDL mới cho bề mặt task.
- Tương thích legacy: `project_child` không dựng DDL khi công tắc tắt và cây chưa từng có bảng (H3.8); khi bảng đã tồn tại thì vẫn chiếu (đọc) mà không mở công cụ.
- Kill switch: `BOXFOX_TASK_SURFACE` (`task_surface.py:45`), mặc định **off**; `TASK_TOOLS = {task_list, task_get, task_send, task_abandon}` (`task_surface.py:43`). Tắt → schema/công cụ biến mất, dispatch từ chối, đường legacy giữ nguyên.
- Rollback: unset switch; các hook `project_child`/`close_attempt` trở thành no-op với cây chưa có bảng; không mất dữ liệu, không replay mutation (chỉ chiếu trạng thái).
- Nợ migration đã biết: F5 — muốn `attemptSeq` theo task phải migration chỉ mục; chưa làm, chờ chủ nhà quyết.
