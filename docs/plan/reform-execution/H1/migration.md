# H1 — Migration / rollback

- Migration **additive**: chỉ thêm module/không đổi bảng cũ; dữ liệu legacy đọc qua lớp parse mới.
- Dữ liệu cũ: fixture legacy read 8/8 xác nhận không tạo grant/verdict mới; schema cũ thiếu cột bắt buộc bị từ chối kèm mã `TASK_SCHEMA_UNSUPPORTED` (H1.3), không tự "nâng cấp" ngầm.
- Rollback: gỡ `orchestration_contracts.py` + test; không có di trú dữ liệu cần hoàn tác.
- Kill switch: không cần — module chưa được nối vào runtime ở checkpoint này.
- Rủi ro tồn: alias/ID/revision là hợp đồng mới; bên gọi cũ chưa dùng nên chưa có xung đột.
