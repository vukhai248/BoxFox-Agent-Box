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
| `BOXFOX_REFORM` (khóa tổng, H12) | off | cả nhóm H3–H8 chạy theo giá trị riêng/mặc định; `on` = bật cả nhóm bằng một lệnh; công tắc thành viên tường minh luôn thắng khóa tổng |
| `BOXFOX_TASK_SURFACE` | off | bốn công cụ `task_*` không được quảng cáo; `dispatch` từ chối `TASK_SURFACE_OFF`; hook `project_child` no-op khi bảng chưa từng có |
| `BOXFOX_CONTROLLER_JOBS` | off | công cụ controller không mở; đường `job_surface`/`job_wake` không chạy (dữ liệu `harness_jobs*` để nguyên, còn đọc được) |
| `BOXFOX_CONTEXT_SURFACE` | off | ref/`skill_view` không đi qua surface; đường context cũ giữ nguyên |
| `BOXFOX_USAGE_LEDGER` | off | không reserve/settle qua surface mới; hàng usage đã ghi còn nguyên |
| `BOXFOX_RESEARCH_GATEWAY` | off | công cụ gateway ẩn qua `apply_profile`; main giữ đường uỷ thác cũ; receipt cũ đọc được |
| `BOXFOX_ADAPTIVE_HARNESS` | off | `guard_tool` giữ đường cũ (`work_scope.check_tool`), không owner check mới; `adaptive_surface` không chạy; mode `adaptive` không bật được (đòi thêm `BOXFOX_USAGE_LEDGER`) |
| `BOXFOX_RECOVERY_POLICY` | off | phân loại hồi phục giữ đường cũ; checkpoint vẫn đọc được |
| `BOXFOX_PEER_MESH` | (hiện có) | giữ nguyên hành vi uỷ thác trước đợt 2 |

- **Bật dần (chủ nhà chốt 2026-10-04):** mặc định vẫn TẮT; bật từng công tắc theo thứ tự và khuôn kiểm ở
  `docs/plan/reform-execution/HANDOFF.md` §6; khóa tổng `BOXFOX_REFORM` chỉ là tay nắm cuối cùng.
- **Rollback reference:** unset các công tắc H2–H8 (hoặc không đặt) là quay về hành vi legacy; dữ liệu
  task/job đã ghi vẫn đọc được (không mất hàng), nhưng model không thấy công cụ và không mutation nào
  replay — đo bằng drill 11/11 (H3) và nghiệm thu vòng chạy 29/29 trên `c836822` (H4–H8).
- **Không replay mutation:** `task_*` là công cụ unsafe, không nằm trong `REPLAY_SAFE`; lời gọi lại
  khi công tắc tắt bị chặn ở `dispatch` trước khi chạm kho.
- **Phê duyệt/ngân sách:** kho task không tự tạo grant/verdict; drill xác nhận không bảng grant/verdict
  nào sinh ra khi chỉ dùng đường task. Phần giới hạn ngân sách cho phiên thật hoãn tương lai (#6531).

## Việc phải làm khi triển khai thật

1. Bật theo run (từng phiên), không bật toàn cục; giữ các công tắc H2–H8 off cho phiên cũ tới khi có
   parity + negative control trên code đích.
2. Nếu phải quay lui sau khi đã ghi task/job: tắt công tắc là đủ cho hành vi; dữ liệu `harness_*` giữ
   nguyên (không xoá) để còn đọc biên nhận.
3. Chưa có drill trên môi trường box thật với phiên đang chạy — chạy trước khi bật diện rộng.
4. Mở lại calibration sống (H10.1) khi có consent tài chính hoặc chạy bằng model miễn phí có kiểm soát (#6531).
