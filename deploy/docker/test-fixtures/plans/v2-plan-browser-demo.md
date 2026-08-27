# Kế hoạch kiểm chứng trình duyệt plan — phiên bản 2

## Mục đích kiểm thử phiên bản

File này chỉ dùng cho smoke test để chứng minh cùng identity `plan-browser-demo` có thể chứa nhiều version thật. Khi test kết thúc, script phải xóa file này và giữ nguyên plan khởi đầu `v1`.

- `v2` phải đứng trước `v1` trong manifest.
- `v2` có trạng thái trình bày `draft`.
- `v1` chuyển thành `approved`.

| Phiên bản | Trạng thái mong đợi |
| --- | --- |
| v2 | draft |
| v1 | approved |
