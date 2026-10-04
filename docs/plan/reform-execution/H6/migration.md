# H6 — Migration / rollback

- Bảng mới **additive** (`harness_usage`, `harness_allocations`); không đổi bảng cũ, không có `user_version` migration (nợ chung đã ghi ở H2).
- Dữ liệu legacy: không đọc/ghi bảng cũ; module độc lập.
- Đã nối runtime ở `802f51f`; rollback: đặt `BOXFOX_USAGE_LEDGER` về off (mặc định) là đủ — không cần gỡ file; bảng để nguyên.
- Kill switch: `BOXFOX_USAGE_LEDGER` (mặc định off); giữ luật "không tự chọn số mặc định khi chưa calibration".
- #6531: phần giới hạn ngân sách (allocation + trần chi cho phiên thật) hoãn tương lai; mã giữ nguyên, công tắc off.
- Tiền tệ: chưa tiêu đồng nào cho checkpoint này (không gọi provider).
