# H6 — Migration / rollback

- Bảng mới **additive** (`harness_usage`, `harness_allocations`); không đổi bảng cũ, không có `user_version` migration (nợ chung đã ghi ở H2).
- Dữ liệu legacy: không đọc/ghi bảng cũ; module độc lập.
- Rollback: gỡ `usage_ledger.py` (chưa nối runtime) — bảng để nguyên; reservation chưa dùng trong phiên thật nên không có nợ treo cần xử lý.
- Kill switch: chưa cần khi chưa nối; khi nối phải giữ luật "không tự chọn số mặc định khi chưa calibration".
- Tiền tệ: chưa tiêu đồng nào cho checkpoint này (không gọi provider).
