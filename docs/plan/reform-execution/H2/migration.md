# H2 — Migration / rollback

- Bảng mới **additive**: `harness_tasks`, `harness_task_attempts`, `harness_task_messages`, `harness_invocations` (task_service.py dòng 71/81/94/101). Không đổi bảng cũ; legacy read xác nhận `legacy_tables_unchanged` và `user_version_unchanged`.
- `SessionStore` **không có `PRAGMA user_version` migration** — bảng mới tự tạo khi dùng; đây là điểm cần lưu ý nếu sau này cần versioning chính thức (chưa quyết).
- Kill switch: `BOXFOX_ADAPTIVE_HARNESS` (`execution_kernel.py:16`), mặc định **off** → hành vi legacy; bật `1/on/true` mới mở kernel mới.
- Rollback: unset switch + gỡ 2 dòng nối `dispatch`; bảng `harness_*` để nguyên (không phá dữ liệu, không replay mutation — kernel chỉ đọc/ghi admission metadata).
- Không có migration dữ liệu cũ cần chạy; không có thao tác phá huỷ.
