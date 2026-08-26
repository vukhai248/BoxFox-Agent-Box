# Scripts

## Các script điều khiển dự án

| Script | Làm gì |
|---|---|
| `start.bat` / `start.ps1` | **Khởi động 1-click & Tự động dọn dẹp**: Tự động kiểm tra Docker, tự build/cập nhật image sandbox nếu thiếu, khởi chạy `docker compose up -d`, kiểm tra `npm install`, khởi chạy Vite dev server và mở trình duyệt `http://localhost:3100`. Khi nhấn `Ctrl + C` hoặc đóng cửa sổ, script sẽ tự động tắt container Docker (`docker compose down`) giải phóng tài nguyên. |

## Các script dự kiến bổ sung sau

| Script | Làm gì |
|---|---|
| `dev.sh` | Chạy backend và frontend cùng lúc ở chế độ phát triển |
| `build-sandbox.sh` | Build image sandbox ở `deploy/docker/`, kiểm đủ sáu quy tắc mục 7.4 |
| `gen-types.sh` | Sinh kiểu TypeScript cho `frontend/src/types/` từ schema của backend |
| `run-benchmark.sh` | Chạy một nhóm ca với một cấu hình, ghi kết quả vào `benchmark/results/` |

## Một luật

Script ở đây chạy trên **máy chủ**, không chạy trong sandbox. Không script nào ở đây được agent gọi tới — agent chỉ có tám tool ở bảng 6.2, và `run_command` của nó chạy trong container với `--network none`.
