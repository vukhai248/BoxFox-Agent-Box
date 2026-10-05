# H3 — Bằng chứng

## Kiểm thử thực tế trên `962cd84` (cây sạch)
- E2E qua `HarnessRuntime` + SQLite thật + model kịch bản: `/code/.generated_artifacts/h3h8/e2e/summary.json` — nhãn `962cd84-final`, commit `962cd8463ba67977b608a432df9a80891a15a71a`, `dirty=false`, **9/9 scenario PASS** (E1–E7 + E3a/E3b/E3c), tổng 110 check.
- E5 (huỷ nhánh của chủ nhà): `e2e/E5.json` 14/14 — attempt đóng `cancelled`/`OWNER_CANCELLED`, hàng sổ con `cancelled`/`OWNER_CANCELLED`, hàng phiên con về `cancelled` (kết thúc), biên nhận huỷ `cancelled`, sự kiện con `cancelledBy=owner`, nhả slot (`holders=[]`, `parent_running=0`).
- E3a (F6): hàng phiên của con bị từ chối về `cancelled` (kết thúc), không chạy, không rò slot.
- Probe mức thư viện: `/code/.generated_artifacts/h3h8/probes/probes_962cd84.json` — P1 19/19, P2 10/10, P3 13/13, P4 7/7, P5 8/8, P6 14/14 = **71/71**.
- Unit scoped 13 file: **716 passed in 100.46s** — `/code/.generated_artifacts/h3h8/unit/scoped_suites_962cd84.log`; nhóm 17 file H1–H9: **780 passed** — `/var/tmp/h3h8_group_run.log`.
- Test module: `test_task_surface.py` (36 hàm / 40 ca), `test_recovery_policy.py` (20 hàm / 39 ca).

## Vòng lỗi đã đóng
- H3.1–H3.10 sửa kèm test tái hiện (commit `2ac4dd4`, `04ea7da`, `962cd84`); F1 (mã lỗi sống rơi `unknown`) ghim bằng `recovery_policy_code_probe.log` trên `2ac4dd4` rồi sửa +19 test; F2 (spawn trùng rò con/slot), F4 (đua huỷ owner ghi `failed/TURN_CANCELLED`), F6 (hàng phiên con kẹt `idle`) đều có ca tái hiện.
- E5 từng fail trên `2ac4dd4` (bản ghi trong transcript kiểm thử); bản chạy lại cuối trên `962cd84` đã PASS và được báo cáo — không còn là blocker.

## Nối runtime (2026-10-04)
- `recovery_policy` đã nối runtime: `runtime.py` import module và gọi `decision/may_retry` khi công tắc `BOXFOX_RECOVERY_POLICY` bật (mặc định **off**); tắt giữ đường cũ.
- `fcc6819`: hợp đồng `delegate_task` khai thêm `task`/`runId` (không bắt buộc) để model sống gửi được hợp đồng task; `task_surface.open_delegate` đọc hai khoá này — bề mặt H3 chạm được từ lượt thật khi công tắc task bật.
- Nghiệm thu vòng chạy H4–H8 (29/29 trên `c836822`) chạy trên runtime đã nối các lớp này.

## Chưa kiểm
- F5 (`attemptSeq` theo phiên) là hạn chế đã ghi nhận, chưa sửa — **chưa kiểm** hành vi khi chủ nhà chọn đổi khoá sổ.
- Chưa có E2E phân loại hồi phục riêng với `BOXFOX_RECOVERY_POLICY` bật trong phiên thật dài ngày.
- Ba test đỏ có sẵn trên baseline `346da06` (`test_terminal_exec_echo`, `test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`, `test_revoked_grant_blocks_next_tool_call`) vẫn đỏ — không phải regression của H3.
