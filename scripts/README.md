# Scripts

Script tiện dụng cho phát triển. Chưa có gì — thư mục này để sẵn.

Dự kiến sẽ cần:

| Script | Làm gì |
|---|---|
| `dev.sh` | Chạy backend và frontend cùng lúc ở chế độ phát triển |
| `build-sandbox.sh` | Build image sandbox ở `deploy/docker/`, kiểm đủ sáu quy tắc mục 7.4 |
| `gen-types.sh` | Sinh kiểu TypeScript cho `frontend/src/types/` từ schema của backend — **không gõ tay lại**, vì nhãn và giấy phép lệch kiểu giữa hai bên là một lớp bug rất khó thấy |
| `run-benchmark.sh` | Chạy một nhóm ca với một cấu hình, ghi kết quả vào `benchmark/results/` |

## Một luật

Script ở đây chạy trên **máy chủ**, không chạy trong sandbox. Không script nào ở đây được agent gọi tới — agent chỉ có tám tool ở bảng 6.2, và `run_command` của nó chạy trong container với `--network none`.
