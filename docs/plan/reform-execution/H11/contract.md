# H11 — Quản lý con/subagent theo #6545–#6548: hợp đồng checkpoint

- **Mục tiêu:** đóng bốn việc chủ nhà chọn ở #6545 thành một checkpoint mới trên cùng nhánh reform
  (#6548): (1) nhắc khi hết hạn chờ + trần đọc lại `peer_read`; (2) con bị cắt vì hết hạn gọi lại
  được với nguyên ngữ cảnh; (3) trạng thái cuối nhìn thấy được (`timedOut`/`partial`); (4) cha khai
  được trần bước/thời gian trong `delegate_task`. Trần số theo #6546: phiên 1000 bước (tối đa 1500)
  và 7200 s; con 1000 bước / 7200 s.
- **Phạm vi:** `limits.py` (trần mới + hằng H11), `child_lifecycle.py` (một cách đọc status+reason),
  `runtime.py` (`_guard_peer_read`, nudge/cap chờ hạn, `resume_child`, `_declared_child_budget`,
  cờ kết cục trong bốn payload, dọn state theo lượt), `task_surface.resume_attempt`, `session_store`
  (mở lại hàng con đã đóng), schema/mô tả `child_resume` + `maxSteps`/`deadlineSeconds`, gating
  `roles`/`tool_groups`/`tool_contracts`, test mới + 5 file test chỉnh theo trần mới.
- **Non-goals:** không đổi ngữ nghĩa `delegate_task` hiện có khi không khai trần (chỉ siết thêm);
  không tự chạy lại con (cha phải quyết định — #6547); không đổi SOP mặc định; không calibration
  sống; không phần giới hạn ngân sách (#6531 vẫn hoãn).
- **Phụ thuộc:** H1–H10 (đã xong phần offline); quyết định chủ nhà #6545–#6548 (2026-10-04); nguồn đo
  là hai phiên thật đi vòng `peer_read` 14–20 lần và một subagent bị cắt ở 7200 s.
- **Nghiệm thu:**
  1. Trần mới đọc được từ `runtime-info` (`maxStepsDefault` 1000, `maxStepsMax` 1500,
     `deadlineDefaultSeconds` 7200, `childMaxSteps` 1000, `childDeadlineSeconds` 7200,
     `childWallMaxSeconds` 8100) và không lệch giữa khai báo và hành vi.
  2. Bốn payload mang cờ kết cục thống nhất `{timedOut, partial, resumable}` do
     `child_lifecycle.outcome()` sinh — một nguồn duy nhất.
  3. `peer_read` bị từ chối bằng `PEER_READ_CAPPED` khi cửa sổ `(lượt, target)` không có dòng mới
     quá `PEER_READ_IDLE_MAX` lần; dòng mới đặt lại bộ đếm.
  4. `await_children` trả `nudge` với `PEER_WAIT_EXPIRED` khi hết hạn chờ, và từ chối chờ tiếp bằng
     `PEER_WAIT_CAPPED` sau `PEER_WAIT_EXPIRED_MAX_PER_TURN` lần trong cùng lượt.
  5. `child_resume` chỉ cha gọi được; bắt buộc `note` (≤ 500 ký tự); chỉ nhận con bị cắt thuộc cha;
     tối đa 3 lần/lượt; mở lại ĐÚNG con đó, giữ nguyên transcript cũ, ghi attempt mới vào kho task;
     con đang chạy / kết thúc bình thường / không thuộc cha bị từ chối bằng mã hợp đồng.
  6. `delegate_task` nhận `maxSteps`/`deadlineSeconds` dương; chỉ siết (kẹp về trần con + phát
     notice), không nới trần.
  7. Toàn bộ test cũ bị ảnh hưởng bởi trần mới được cập nhật; suite scoped 22 file xanh.
- **Điều kiện chưa đạt (tại thời điểm viết):** E2E thật với model sống trên backend 3113 đã chạy
  PASS (`task-fix` 1/1, `child` 1/1) và review đã chạy xong (risk 5/10) — bảy sửa đổi sau review ở
  `0e9b6df`; kết quả testing của checkpoint ghi ở `evidence.md` khi có.
