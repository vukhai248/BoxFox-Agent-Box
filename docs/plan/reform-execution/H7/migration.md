# H7 — Migration / rollback

- Bảng mới **additive** (`harness_research_*`); không đổi bảng cũ.
- Dữ liệu legacy: read view/history của Research chưa migrate thật — khi migrate phải giữ nguyên kết quả cũ, chỉ thêm góc nhìn đọc.
- Đã nối runtime ở `802f51f`; rollback: đặt `BOXFOX_RESEARCH_GATEWAY` về off (mặc định) là đủ — không cần gỡ file; bảng để nguyên; kill switch giữ receipt đọc được.
- Kill switch: `BOXFOX_RESEARCH_GATEWAY` (mặc định off); giữ luật "main không ghi canonical/không điều khiển worker nội bộ".
- Chưa tiêu tài nguyên provider cho checkpoint này.
