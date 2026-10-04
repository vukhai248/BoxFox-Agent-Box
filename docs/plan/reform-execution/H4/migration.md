# H4 — Migration / rollback

- Bảng mới **additive**, tạo khi dùng; không đổi bảng cũ, không có `PRAGMA user_version` migration (cùng nợ kỹ thuật đã ghi ở H2).
- Dữ liệu legacy: không đọc/ghi vào bảng cũ; module độc lập nên không ảnh hưởng cây legacy.
- Rollback: gỡ `harness_jobs.py` (chưa nối runtime) — bảng `harness_jobs*` để nguyên, không mất dữ liệu.
- Kill switch: chưa cần vì chưa nối; khi nối phải theo hợp đồng công tắc của H2/H3.
- Nợ đã biết: cần checkpoint wiring riêng để chạy reconcile/process-tree trên runtime thật.
