# H5 — Migration / rollback

- Bảng mới **additive** (`harness_skill_pins/skills/skill_reviews/skill_invocations`); `RECORD_SCHEMA_VERSION = 1` + `ALTER TABLE` idempotent (H5.3) — chạy lại an toàn.
- Dữ liệu legacy: không đụng bảng cũ; module độc lập nên cây legacy không đổi.
- Rollback: gỡ `skill_spec.py` + `context_bundle.py` (chưa nối runtime) — bảng để nguyên; gỡ pin sẽ mất epoch ghim, chấp nhận được vì chưa dùng trong phiên thật.
- Kill switch: chưa cần (chưa nối); khi nối phải giữ luật "enable không đổi version đang ghim" của H5.1.
- Không import bộ skill tham khảo; không có migration dữ liệu bên ngoài.
