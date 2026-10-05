# H5 — Migration / rollback

- Bảng mới **additive** (`harness_skill_pins/skills/skill_reviews/skill_invocations`); `RECORD_SCHEMA_VERSION = 1` + `ALTER TABLE` idempotent (H5.3) — chạy lại an toàn.
- Dữ liệu legacy: không đụng bảng cũ; module độc lập nên cây legacy không đổi.
- Đã nối runtime ở `802f51f`; rollback: đặt `BOXFOX_CONTEXT_SURFACE` về off (mặc định) là đủ — không cần gỡ file; bảng để nguyên (gỡ pin sẽ mất epoch ghim).
- Kill switch: `BOXFOX_CONTEXT_SURFACE` (mặc định off); giữ luật "enable không đổi version đang ghim" của H5.1.
- Không import bộ skill tham khảo; không có migration dữ liệu bên ngoài.
