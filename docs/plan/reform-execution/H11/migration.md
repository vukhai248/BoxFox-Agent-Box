# H11 — Migration, tương thích và rollback

## Dữ liệu và schema

- **Không có bảng/cột mới.** H11 chỉ thêm cột hành vi vào đường đã có; `session_store.child_start`
  đổi từ chèn-một-lần sang `ON CONFLICT ... DO UPDATE` để MỞ LẠI được hàng con đã đóng
  (`status='started'`, `reason=NULL`, `finished=NULL`, `waiting_for='[]'`). Hàng cũ đọc nguyên trạng.
- Attempt của lần gọi lại đi qua đúng kho H3 (`task_surface.resume_attempt` → `TaskService.record_attempt`)
  với `invocation_id`/`admission_id` = `resume-<childId>-<attempt>`; không tạo bảng mới.
- Trần mới là hằng số trong `limits.py` (không phải dữ liệu): phiên cũ không có trạng thái lưu nào
  phụ thuộc số cũ, nên đổi trần không cần migration.

## Kill switch và rollback

| Công tắc | Ảnh hưởng H11 |
|---|---|
| `BOXFOX_PEER_MESH` | TẮT: `peer_read`/`await_children`/`child_resume` không được quảng cáo; `dispatch` từ chối `PEER_MESH_OFF`; hành vi uỷ thác về như trước H11 |
| `BOXFOX_TASK_SURFACE` | TẮT: `resume_attempt` no-op khi kho chưa từng có bảng; con vẫn gọi lại được (đường session store) nhưng không ghi attempt |
| các công tắc H4–H8 | Không đổi so với H10 (xem H10/migration.md) |

- **Rollback reference:** revert `0e9b6df` + `2bd3886` + `9a04c16` + `84022bf` là quay về trần cũ
  (120/400 bước, 1800 s, con 200/3600, watchdog 4500) và bỏ toàn bộ công cụ/đường H11; không có dữ
  liệu nào phải chuyển ngược.
- **Không replay mutation:** `child_resume` là công cụ mutation không nằm trong `REPLAY_SAFE`; khi
  công tắc tắt, `dispatch` từ chối trước khi chạm store.
- **Tương thích ngữ nghĩa:** `delegate_task` không khai `maxSteps`/`deadlineSeconds` giữ nguyên hành
  vi cũ; khai số âm/0/không nguyên bị từ chối (`must be a positive integer`); số vượt trần con bị
  kẹp + phát notice (`STEPS_CLAMP_NOTICE`/`DEADLINE_CLAMP_NOTICE`), không im lặng.

## Việc phải làm khi triển khai thật

1. Theo dõi tần suất `PEER_READ_CAPPED`/`PEER_WAIT_CAPPED`/`CHILD_RESUME_CAPPED` trong nhật ký phiên
   thật; nếu model chạm trần thường xuyên thì xem lại ngưỡng 3 (đọc lại) / 3 (chờ hạn) / 3 (gọi lại).
2. Con bị cắt bằng trần mới (1000 bước/7200 s) cần chủ nhà thấy cờ `timedOut`/`partial` trong UI
   trước khi quyết gọi lại — kiểm cùng lượt E2E thật.
3. Không nới trần con vượt `CHILD_MAX_STEPS`/`CHILD_DEADLINE_SECONDS` khi chưa có số đo mới; trần
   phiên `MAX_STEPS_MAX` là chặn cuối của admission.
