# H10 — Migration, tương thích và rollback

## Dữ liệu và schema

- Bảng mới của reform là **additive**: `harness_tasks`, `harness_task_attempts`,
  `harness_task_messages`, `harness_invocations` (H3) và các bảng H4–H8 khi đường của chúng chạy.
  `SessionStore` không dùng `PRAGMA user_version`; drill xác nhận `user_version` giữ nguyên sau khi
  bật/tắt công tắc.
- Không có migration phá compatibility: không đổi cột/bảng cũ; chỉ mục unique của kho task là mới
  và có bước làm mới idempotent khi mở kho (`harness_task_active`, `harness_session_active`).
- Đọc dữ liệu legacy: fixture legacy (H1/H2) đọc qua code mới không đổi bảng, không tự tạo
  grant/verdict; hash/approval lịch sử không đổi.

## Kill switch và rollback

| Công tắc | Mặc định | Tắt thì |
|---|---|---|
| `BOXFOX_ADAPTIVE_HARNESS` | off | `guard_tool` giữ đường cũ (`work_scope.check_tool`), không owner check mới |
| `BOXFOX_TASK_SURFACE` | off | bốn công cụ `task_*` không được quảng cáo; `dispatch` từ chối `TASK_SURFACE_OFF`; hook `project_child` no-op khi bảng chưa từng có |
| `BOXFOX_PEER_MESH` | (hiện có) | giữ nguyên hành vi uỷ thác trước đợt 2 |

- **Rollback reference:** unset cả hai công tắc (hoặc không đặt) là quay về hành vi legacy; dữ liệu
  task đã ghi vẫn đọc được bằng `TaskService` (không mất hàng), nhưng model không thấy công cụ và
  không mutation nào replay — đã đo bằng drill 11/11.
- **Không replay mutation:** `task_*` là công cụ unsafe, không nằm trong `REPLAY_SAFE`; lời gọi lại
  khi công tắc tắt bị chặn ở `dispatch` trước khi chạm kho.
- **Phê duyệt/ngân sách:** kho task không tự tạo grant/verdict; drill xác nhận không bảng grant/verdict
  nào sinh ra khi chỉ dùng đường task.

## Việc phải làm khi triển khai thật

1. Bật theo run (từng phiên), không bật toàn cục; giữ `BOXFOX_TASK_SURFACE`/`BOXFOX_ADAPTIVE_HARNESS`
   off cho phiên cũ tới khi có parity + negative control trên code đích.
2. Nếu phải quay lui sau khi đã ghi task: tắt công tắc là đủ cho hành vi; dữ liệu `harness_*` giữ
   nguyên (không xoá) để còn đọc biên nhận.
3. Chưa có drill trên môi trường box thật với phiên đang chạy — chạy trước khi bật diện rộng.
