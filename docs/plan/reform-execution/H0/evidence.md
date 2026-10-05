# H0 — Bằng chứng

## Kiểm tra thật (2026-10-04)
- `git diff --stat 6adbe78 346da06 -- backend/src backend/tests scripts` → **rỗng**; `git diff --stat 6adbe78 346da06` chỉ khác 2 file docs (`docs/architecture/vorflux-vs-boxfox-orchestration.md`, `docs/plan/Work-Graph-fix.md`).
- `/var/tmp/w10f-seq/owner-stop.json` → `status: stopped`, `completedCells: 31`, `plannedCells: 34`, `freezeCommit: 6adbe78f…`, `pid: 320151`, `autoResume: false`, `finalAggregateAvailable: false`; lý do dừng lúc 2026-10-03T16:56:30Z (ưu tiên plan 1257).
- `/var/tmp/w10f-seq/freeze.txt` → `commit=6adbe78f…`, `run exit=130` (SIGINT theo lệnh dừng), `done=2026-10-03T16:56:31Z`.
- `/var/tmp/w10f-seq/plan.json` → 17 case × 2 repeat = 34 cell; provider `opencode`, model `space-bunny-free`, `configHash e1a3791b…` (policyVersion `work-checks/10`), tạo lúc 2026-10-03T10:00:58Z.
- `/code/.plans/w10f-input-pins.json` → sha256 của driver/rubric/guard/runner/net/manifest + 17 fixture, tất cả `matchesCurrent: true`.

## Kết quả
- 31/34 cell chạy xong; cell cuối hoàn tất: V10-r1/r2 (quality-valid), V13-r1 (needs_revision, quality-valid, 1.800.314 ms); V13-r2 bị dừng theo chủ nhà; V14-r1/r2 chưa chạy.
- 1/31 cell đạt đúng kịch bản (S03-r2) theo oracle đóng băng; subset gate cũ `minPassed=22` không đạt — gate của suite cũ, không phải tiêu chí reform.
- Báo cáo phát hành: Test Report **W8.A4.5.N** — "W8.A4.5.N — hàng rào xung đột đầu vào, ngân sách #6457, vòng sửa native" (report 956).
- Phân tích staging: `/code/.plans/w10f-sequential-report-stage.md` (working note, không phải báo cáo đã phát hành).

## Chưa kiểm / không có trên máy này
- Không có aggregate cuối cho 34 cell (`finalAggregateAvailable=false`); 3 cell không có điểm — **chưa kiểm**.
- Không đọc lại được nội dung report 956 từ artifact trên máy này (chỉ có dòng trong bảng trạng thái) — **chưa kiểm**.
- Phân loại product/provider/measurement/unknown theo từng cell chỉ nằm trong report đã phát hành; staging nêu các khoảng trống đo lường nhưng không thay thế báo cáo.
