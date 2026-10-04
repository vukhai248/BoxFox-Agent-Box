# H8 — Migration / rollback

- Không thêm bảng mới; module là logic thuần (quyết định + tín hiệu), không ghi schema.
- Legacy adapter theo run pin giữ nguyên; chưa nối runtime nên không có di trú hành vi.
- Rollback: gỡ `adaptive_main.py` (chưa nối) — không mất dữ liệu.
- Kill switch: dùng công tắc H2 (`BOXFOX_ADAPTIVE_HARNESS`) khi nối; mặc định off giữ đường legacy.
- Không tiêu tài nguyên provider cho checkpoint này.
