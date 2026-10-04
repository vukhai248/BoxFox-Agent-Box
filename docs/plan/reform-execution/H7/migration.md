# H7 — Migration / rollback

- Bảng mới **additive** (`harness_research_*`); không đổi bảng cũ.
- Dữ liệu legacy: read view/history của Research chưa migrate thật (chưa nối runtime) — khi migrate phải giữ nguyên kết quả cũ, chỉ thêm góc nhìn đọc.
- Rollback: gỡ `research_owner.py` (chưa nối runtime) — bảng để nguyên.
- Kill switch: chưa cần khi chưa nối; khi nối phải giữ luật "main không ghi canonical/không điều khiển worker nội bộ".
- Chưa tiêu tài nguyên provider cho checkpoint này.
