# H4 — Migration / rollback

- Bảng mới **additive**, tạo khi dùng; không đổi bảng cũ, không có `PRAGMA user_version` migration (cùng nợ kỹ thuật đã ghi ở H2).
- Dữ liệu legacy: không đọc/ghi vào bảng cũ; module độc lập nên không ảnh hưởng cây legacy.
- Đã nối runtime ở `802f51f`; rollback: đặt `BOXFOX_CONTROLLER_JOBS` về off (mặc định) là đủ — không cần gỡ file; bảng `harness_jobs*` để nguyên, không mất dữ liệu.
- Kill switch: `BOXFOX_CONTROLLER_JOBS` (mặc định off) — theo hợp đồng công tắc của H2/H3.
- Nợ đã biết: process job fail closed (`JOB_EXECUTOR_UNSUPPORTED`), resume theo checkpoint chưa hỗ trợ (H4.5).
