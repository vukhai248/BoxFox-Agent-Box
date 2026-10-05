# H11 — Handoff

- **Trạng thái:** `partial` (code + unit xanh; E2E thật đã PASS, review đã xong và đã sửa bảy
  điểm; testing đã chạy xong và ghi ở `evidence.md`).
  Đo lại toàn bộ `tests/unit` (2026-10-04) bắt được MỘT hồi quy của H11 — phần nới hạn chót
  lượt plan hết chỗ vì mặc định 7200 s đã chạm trần — đã sửa ở nhánh H12 (`limits.py` ghi
  chú + hai bài chốt lại hợp đồng); xem `evidence.md` §"Đo lại toàn bộ unit suite".
  Bốn việc #6545 đã có mã và test: trần mới #6546, cờ kết cục, chặn đọc lại + nhắc/trần chờ hạn,
  `child_resume` giữ nguyên ngữ cảnh con bị cắt, cha khai trần trong `delegate_task`.
- **Head bàn giao:** `f7ebbc9` trên `vorflux/boxfox-harness-reform` (PR #3, base
  `vorflux/w10-w12-completion`); base checkpoint `ad3b5f8`. Chuỗi H11: `84022bf` (code) →
  `9a04c16` (simplify) → `2bd3886` (phủ kiểm) → `0e9b6df` (bảy sửa đổi sau review) →
  `f7ebbc9` (ba siết sau vòng soát thứ hai).
- **Quyết định đã ghi (chủ nhà, 2026-10-04):**
  - #6545: chọn cả bốn đề xuất quản lý con, gộp thành MỘT checkpoint mới.
  - #6546: trần cao lên 1k/1k5 bước và 7200 s (giống Vorflux); con chạm trần thì hoặc tổng hợp rồi
    báo main, hoặc dừng — main nhìn thấy rồi quyết định nhập prompt tiếp.
  - #6547: gọi lại CHÍNH con đó, giữ ngữ cảnh cũ; cha phải xem xét và quyết định.
  - #6548: cùng nhánh reform, checkpoint mới, tổng hợp vào; tiếp tục hoàn thiện việc đang giở.
- **Blocker:** không có blocker kỹ thuật; các mục chờ quyết định giữ nguyên từ H10 (retarget PR #3,
  cách đọc ngữ nghĩa follow-up `delegate_task`), và H9/H10.1 vẫn hoãn #6531.
- **Việc tiếp theo (thứ tự đề xuất):**
  1. Đọc kết quả E2E thật (`runs/task-fix/`) + review/simplify/testing của checkpoint; xử lý phát
     hiện nếu có rồi cập nhật `evidence.md`.
  2. Kịch bản E2E thật cho `child_resume` (con bị cắt bằng trần cha khai thấp → gọi lại) khi có
     ngân sách model phù hợp.
  3. Đo lại toàn bộ unit suite trên `f7ebbc9` trước khi khép checkpoint (mới có nhóm liên quan
     18 file **271 passed** và scoped 22 file **582 passed** trên `84022bf`).
- **Rollback:** xem `migration.md`; revert `f7ebbc9` + `0e9b6df` + `2bd3886` + `9a04c16` +
  `84022bf` là đủ (không có dữ liệu phải chuyển ngược).
