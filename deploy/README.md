# Triển khai

Mọi thứ để chạy được dự án bằng một lệnh. Bản nộp đồ án yêu cầu **`docker compose up` là chạy được** (mục 14.5).

| Thư mục | Nội dung |
|---|---|
| `docker/` | `Dockerfile` cho backend, cho frontend, và **image sandbox** mà agent chạy lệnh bên trong |
| `compose/` | `docker-compose.yml` cho môi trường phát triển và cho bản nộp |

## Sáu quy tắc container — mục 7.4

Image sandbox ở đây là **ranh giới bảo mật thật** (nguyên tắc N4), không phải một tiện ích. Sáu quy tắc dưới đây phải cài đủ; **nếu không đủ thì phải loại `run_command` khỏi tuyên bố bảo mật và khỏi benchmark chính** — điều này đã ghi trong kế hoạch, không phải một lựa chọn tuỳ ý.

| # | Quy tắc |
|---|---|
| 1 | Mount theo **từng lần gọi**, đúng `:ro` hoặc `:rw` cần thiết — không mount sẵn cả workspace |
| 2 | `run_command` **luôn** chạy với `--network none` |
| 3 | Nhãn kết quả = **mức xấu nhất** của các input đã mount vào |
| 4 | Không mount tài nguyên `BÍ_MẬT` nếu không có cho phép |
| 5 | Không truyền env chứa khoá API vào container · DB audit nằm **ngoài** container · **không mount `$HOME`** |
| 6 | Hardening: chạy non-root · **không** mount Docker socket · `--cap-drop ALL` · `--security-opt no-new-privileges` · seccomp profile · `--memory` + `--cpus` + `--pids-limit` · timeout cứng |

Quy tắc 5 và 6 là chỗ dễ bỏ sót nhất. Mount Docker socket vào container là mở đường thoát sandbox trực tiếp, và nhiều ví dụ trên mạng làm đúng như vậy.

## Ba cảnh demo của bản nộp (mục 14.5)

`compose/` phải dựng được môi trường chạy đủ ba cảnh, và **cảnh 3 phải là cảnh cuối**:

1. Agent làm một việc coding bình thường.
2. Một `README.md` độc thử điều khiển agent và bị chặn.
3. **Một chỉ thị độc vẽ trên màn hình bị chặn, rồi mở sổ audit ra xem lại.** Đây là cảnh chứng minh đóng góp Đ3.
