# H8 — Migration / rollback

- Bảng mới `harness_adaptive_state` (additive; decision/loop/evidence bền) — không đổi bảng cũ.
- Legacy adapter theo run pin giữ nguyên; mode `legacy` là mặc định nên không có di trú hành vi khi chưa bật.
- Đã nối runtime ở `802f51f`; rollback: đặt `BOXFOX_ADAPTIVE_HARNESS` về off (mặc định) là đủ — không cần gỡ file; bảng để nguyên.
- Kill switch: `BOXFOX_ADAPTIVE_HARNESS` (+ `BOXFOX_USAGE_LEDGER` nếu bật mode `adaptive`); mặc định off giữ đường legacy.
- Không tiêu tài nguyên provider cho checkpoint này.
