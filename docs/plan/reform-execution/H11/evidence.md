# H11 — Bằng chứng

## Đã chạy

- **Unit mới (H11)** — `84022bf`: `backend/tests/unit/test_child_management_h11.py` **20 ca xanh**
  (8.25 s), phủ: outcome flags (9 ca parametrize), event `child` mang cờ, `PEER_READ_CAPPED` +
  reset khi có dòng mới, nudge `PEER_WAIT_EXPIRED` + `PEER_WAIT_CAPPED`, con bị cắt hiện
  `resumable`, `child_resume` đòi note/con thật/con đã bị cắt/trần 3 lượt/mở lại transcript cũ,
  `delegate_task` chỉ siết + tôn trọng trần cha khai, khai báo/gating của `child_resume`.
- **Unit phủ nốt năm lỗ hổng (vòng kiểm thử chỉ ra)** — `2bd3886`: thêm 5 ca (6 lượt parametrize)
  vào cùng file, **30 ca xanh**: gọi lại con có task ghi attempt MỚI (`attempt_seq` 2) trên CÙNG
  session con và không sinh task thứ hai; watchdog cắt vì vượt trần tường mang cờ
  `timedOut/partial/resumable`; con `wait=false` tự xong (event `detached`) cũng mang cờ; lượt đóng
  thì ba bộ đếm theo lượt biến mất còn bộ đếm lượt khác nguyên; trần cha khai từ chối số âm, số
  thực, chuỗi, bool. Nhóm H11-adjacent 9 file (`test_child_management_h11`, `test_task_surface`,
  `test_harness_task_service`, `test_peer_watchdog`, `test_plan_deadline`, `test_delegation_contract`,
  `test_journal_tools`, `test_runtime_info`, `test_limits_notice`): **187 passed in 70.04s**.
- **Scoped suite (22 file)** — `84022bf`: **582 passed in 167.53s** (job `6d9409a3`), gồm H11 +
  các file bị ảnh hưởng bởi trần mới (`test_plan_deadline`, `test_delegation_contract`,
  `test_journal_tools`, `test_runtime_info`, `test_limits_notice`) và nhóm task/plan/research/peer.
- **Trần mới đọc được từ API** — backend 3113 restart bằng `84022bf`:
  `GET /api/agent/runtime-info` trả `maxStepsDefault=1000, maxStepsMax=1500, deadlineDefaultSeconds=7200,
  childMaxSteps=1000, childDeadlineSeconds=7200, peer.childWallMaxSeconds=8100`, `tools=61`
  (61 = union 14 nhóm, thêm `child_resume`).
- **E2E thật (đã chạy xong, PASS):** `driver_task.py` đã sửa hai lỗi cũ (cột `task_id` → `task_alias`/
  `task_key`; model phải mở run bằng `work_graph` trước để tránh `TASK_SURFACE_NO_RUN`/
  `TASK_RUN_UNKNOWN`), chạy nhãn `task-fix` trên 3113 (code `84022bf`): **1/1 kịch bản đạt, 6/6 check**
  — model sống gọi `work_graph` (run `w-418c6df26b`) rồi `delegate_task` với hợp đồng; kho có hàng
  thật `task-4f5cba59877b4782a86605a83f3998b4` (alias `e2e-durable-count`, revision 3, state
  `succeeded`) và attempt 1 gắn phiên con thật `25f8a2c37b3746bbabbd5c48474a8783` (status `succeeded`);
  lượt kết thúc `completed` — `/code/.generated_artifacts/e2e/runs/task-fix/summary.json`.
- **E2E thật cho `child_resume` (đã chạy xong, PASS)** — `driver_child.py` nhãn `child` trên 3113:
  **1/1 kịch bản, 8/8 check**. Model sống gọi `delegate_task` với `maxSteps=2`; con thật
  `8b4f6d93fd2c464281e78101d4323c01` bị cắt (`status='partial'`, `reason='STEP_BUDGET_EXHAUSTED'`,
  `steps_used=3`); cha gọi `child_resume` với `note`; brief `RESUME (attempt 1): ...` nằm trong
  CHÍNH transcript cũ của con; con chạy lại (`turn_count=2`, `completed`); event `child` mang
  `resumed=true`, `attempt=1`; lượt cha `completed` — `/code/.generated_artifacts/e2e/runs/child/summary.json`.
- **Review/simplify của checkpoint:** simplify đã xong (4 sửa đổi giữ nguyên hành vi, commit
  `9a04c16`; nhóm test 86 passed, riêng H11 + runtime_info + peer_watchdog 47 passed). Review
  (`h11-review`) xong trên `ad3b5f8..84022bf`: **risk 5/10, Medium, "ship with mitigations"**, bảy
  finding (1 High, 2 Medium, 3 Low, 1 Nit); ba finding nặng đã soi lại bằng script
  (`/var/tmp/h11check/check_findings.py`). Testing đang chạy; kết quả ghi bổ sung khi có.
- **Vòng soát H11 vòng 2 trên `0e9b6df`** — risk **3/10 (Low)**, "ship with mitigations": cả bảy
  sửa đổi đúng như mô tả; ba điểm còn hở của chính bản sửa (bộ dọn theo lượt vẫn xoá bộ đếm của
  phiên khác cùng số lượt — Medium; callback cũ vẫn nhả suất fan-out của lần chạy mới — Low; nốt
  một chỗ gọi `close_detached_child` thiếu `started` — Low). Siết cả ba ở `f7ebbc9` kèm hai ca mới;
  kịch bản soi lại của vòng soát (`/var/tmp/h11_repro_cleanup.py`) xác nhận ba bộ đếm của phiên
  khác cùng lượt sống sót. Đo sau `f7ebbc9`: `test_child_management_h11.py` **37 ca**, nhóm liên
  quan 18 file **271 passed in 122.29s`.
- **Bảy sửa đổi sau review** — `0e9b6df`: (1) `partial_turn` đọc hàng `finish` CUỐI của phiên
  (cờ `partial` + `code`) thay vì quét mọi notice bền — con được gọi lại chạy sạch không còn mang
  kết cục cắt của lần trước; (2) cửa sổ `peer_read` khoá theo người đọc `(turn, sid, target)`;
  (3) `child_resume` đếm attempt theo CẢ ĐỜI con (`child_resume_totals`) và id
  `resume-<con>-<lượt>-<n>` không trùng giữa các lượt (hết `TASK_INVOCATION_CONFLICT` im lặng);
  (4) callback done của lần chạy cũ không đóng được con vừa mở lại (so mốc `started`);
  (5) con research theo mức không bị nới hạn chót quá số cha khai (`min` với giá trị đã kẹp);
  (6) `child_resume` kiểm `deliverTo` như `delegate`; (7) `start` hỏng sau khi mở lại hàng sổ thì
  đóng ngay bằng `CHILD_RESUME_START_FAILED`. Kiểm: `test_child_management_h11.py` **35 ca xanh**
  (5 ca mới + 2 ca cũ đổi khoá); nhóm liên quan 18 file **269 passed in 120.49s**; script soi lại
  đi đúng đường sản xuất (`/var/tmp/h11check/check_findings_v2.py`) xác nhận cả ba finding nặng:
  con gọi lại chạy sạch ⇒ `completed`, hai lượt gọi lại ⇒ attempt 1/2/3 đơn điệu, phiên khác cùng
  lượt không bị trần `peer_read` của phiên này.
## Artifact tham chiếu

- `/code/.generated_artifacts/e2e/runs/task-fix/` (kịch bản delegate + task bền vững, model sống)
- `/code/.generated_artifacts/e2e/runs/{v1,v1-fix,off,folders2,folders3,folders4}/` (các vòng E2E trước)
- `/var/tmp/boxfox-e2e/backend-3113-h11.log` (backend 3113 với code H11)
- `/code/.plans/v1-boxfox-harness-reform.md` Phụ lục B — H11

## Đo lại toàn bộ unit suite (2026-10-04, sau H12)

Chạy `tests/unit` trên cây `f6dbe2b` (H12): **4356 passed, 12 skipped, 4 failed**. Ba lỗi đỏ là
lỗi có sẵn từ baseline `346da06` (`test_terminal_exec_echo`,
`test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`, `test_revoked_grant_blocks_next_tool_call`).
Lỗi thứ tư là **hồi quy thật do H11**:

- `test_plan_turn_gates.py::test_the_turn_deadline_extension_is_recorded_for_the_write` — H11 nâng
  `DEADLINE_DEFAULT_SECONDS` 1800 → 7200, mà `DEADLINE_MAX_SECONDS` đã là 7200, nên lượt chạy mặc
  định **chạm trần** và phần nới theo sự kiện `plan_written` (`PLAN_TURN_EXTENSION_SECONDS` = 420)
  không còn chỗ để nới ⇒ không có notice `TURN_EXTENDED`.
- **Cách xử lý:** giữ nguyên trần #6546 (7200 s) và giữ nguyên phần nới; chốt lại hợp đồng bằng hai
  bài: lượt có hạn chót **dưới trần** (`deadlineSeconds` 600) nới ĐÚNG một lần, lý do `plan_written`
  (thứ tự cũ giữ nguyên); lượt ở hạn chót **mặc định** không nới và **không bịa notice** — cổng F3
  vẫn chạy. Ghi chú tương ứng ở `limits.py` cạnh `PLAN_TURN_EXTENSION_SECONDS`.
- Sau khi sửa: `test_plan_turn_gates.py` + `test_write_plan.py` + `test_reform_master_switch.py`
  **67 passed**; lần chạy lại toàn bộ `tests/unit` ghi ở `reform-status.md`.

## Chưa kiểm (không được ghi là đã đạt)

- **E2E thật cho `child_resume`** đã chạy (xem trên); phần chưa kiểm là cờ `timedOut` (cắt vì HẠN
  CHÓT thật, không phải trần bước) và gọi lại nhiều lần trong cùng lượt tới trần 3.
- **UI thật** với cờ `timedOut`/`partial` hiển thị trên phiên con bị cắt (chưa chụp lại sau H11).
- H9 live pilot / H10.1 calibration: vẫn hoãn #6531; `financial_consent_ref: null`.
