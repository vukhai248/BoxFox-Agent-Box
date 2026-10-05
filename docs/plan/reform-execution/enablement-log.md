# Nhật ký bật dần công tắc (enablement log)

> Append-only. Mỗi lần chạy một bước của quy trình `HANDOFF.md` §6 thì ghi thêm một mục ở đây:
> ngày, công tắc, kết quả bốn phép kiểm (test TẮT, test BẬT, `runtime-info`, vòng live), bằng chứng,
> và bước tiếp theo. **Một bước = một công tắc**, bật xong mới sang bước sau.

## Môi trường chạy

| Thứ | Giá trị |
|---|---|
| Instance bật dần | cổng **3116**, data dir `/var/tmp/boxfox-enable/data`, log `/var/tmp/boxfox-enable/backend-3116-step*.log` |
| Instance E2E (không đụng vào) | cổng 3113, data dir `/var/tmp/boxfox-e2e/data-on`, sáu công tắc `explicit` |
| Lệnh test | `cd /code/.worktrees/boxfox-harness-reform/backend && TMPDIR=/var/tmp PYTHONPATH=src /code/i3abyxinhdepqua-lang/BoxFox-Agent-Box/backend/.venv/bin/python -m pytest -q <paths> -p no:cacheprovider` (đặt env công tắc TRƯỚC lệnh để chạy trạng thái TẮT/BẬT) |
| Lệnh live | `python3 /code/.generated_artifacts/e2e/driver.py --base 3116 --label enable-step<N> --only <kịch bản> --switches off` |
| Bằng chứng live | `/code/.generated_artifacts/e2e/runs/enable-step<N>/` (mỗi kịch bản một tệp JSON + `summary.json`) |
| Xem đang bật gì | `curl -s -H 'X-BoxFox-Admin: 1' http://127.0.0.1:3116/api/agent/runtime-info` → khối `switches` |

Ghi chú: `--switches off` nghĩa là kịch bản `adaptive_off` kỳ vọng `409 POLICY_SWITCH_OFF` (đúng khi
`BOXFOX_ADAPTIVE_HARNESS` chưa bật). Khi nào tới bước 6 thì đổi thành `--switches on`.

## Nhật ký

| Bước | Công tắc | Ngày | Test TẮT | Test BẬT | `runtime-info` | Vòng live | Kết quả |
|---|---|---|---|---|---|---|---|
| 0 | (chưa bật gì) | 2026-10-05 | — | — | cả bảy `on: false, source: default`; 61 tool; health 200 | — | baseline sạch |
| 1 | `BOXFOX_RECOVERY_POLICY` | 2026-10-05 | **49 passed** | **49 passed** | `on: true, source: explicit` | `enable-step1`: **3/3 kịch bản, 7/7 phép kiểm** | ✅ ĐẠT |
| 2 | `BOXFOX_CONTEXT_SURFACE` | 2026-10-05 | **249 passed** | **249 passed** | `on: true, source: explicit` (kèm bước 1 vẫn `explicit`) | `enable-step2`: **3/3 kịch bản, 8/8 phép kiểm** | ✅ ĐẠT |
| 3 | `BOXFOX_TASK_SURFACE` | 2026-10-05 | **112 passed** | **112 passed** | `on: true, source: explicit` (kèm bước 1–2) | `enable-step3-mimo`: **1/1 kịch bản, 6/6 phép kiểm** | ✅ ĐẠT (kèm ghi chú model yếu) |
| 4 | `BOXFOX_CONTROLLER_JOBS` | 2026-10-05 | **125 passed** | **125 passed** | `on: true, source: explicit` (kèm bước 1–3) | `enable-step4`: **1/1 kịch bản, 6/6 phép kiểm** | ✅ ĐẠT |
| 5 | `BOXFOX_USAGE_LEDGER` | — | — | — | — | — | chưa chạy |
| 6 | `BOXFOX_ADAPTIVE_HARNESS` | — | — | — | — | — | chưa chạy |
| 7 | `BOXFOX_RESEARCH_GATEWAY` | — | — | — | — | — | chưa chạy |
| 8 | `BOXFOX_REFORM=on` | — | — | — | — | — | chưa chạy |

## Chi tiết từng bước

### Bước 0 — baseline (2026-10-05)

- Khởi động instance bật dần **không đặt env công tắc nào**: `switches.master = {on: false, source: default}`,
  cả bảy thành viên `on: false, source: default`, 61 tool, `/api/agent/health` 200.
- Log: `/var/tmp/boxfox-enable/backend-3116-step0.log`.

### Bước 1 — `BOXFOX_RECOVERY_POLICY` (2026-10-05)

- **Test khi TẮT:** `BOXFOX_RECOVERY_POLICY=off` + `tests/unit/test_recovery_policy.py` + `tests/unit/test_decision_flow.py`
  → **49 passed in 7.55s**.
- **Test khi BẬT:** cùng hai tệp với `BOXFOX_RECOVERY_POLICY=on` → **49 passed in 7.27s**.
- **Khởi động lại instance** với `BOXFOX_RECOVERY_POLICY=on`: `runtime-info` trả
  `BOXFOX_RECOVERY_POLICY: {on: true, source: explicit}`, sáu thành viên còn lại `default/off`.
- **Vòng live** (`--label enable-step1 --only kernel_guard,tools_and_file --switches off`):
  - `kernel_guard` **PASS** — ghi `/etc/boxfox-should-not-exist.txt` bị từ chối, tệp `ABSENT`, lượt `completed`;
  - `tools_and_file` **PASS** — `terminal_exec` + `file_write` thật, đọc lại thấy `proof-2026-10-04`, lượt `completed`;
  - `adaptive_off` **PASS** — `409 POLICY_SWITCH_OFF`, policy không đổi.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step1/` (`summary.json`: total 3, passed 3, failed 0);
  log `/var/tmp/boxfox-enable/backend-3116-step1.log`.

### Bước 2 — `BOXFOX_CONTEXT_SURFACE` (2026-10-05, cộng dồn bước 1)

- **Test khi TẮT:** `BOXFOX_CONTEXT_SURFACE=off` + `tests/unit/test_context_surface.py` + `tests/unit/test_context_bundle.py`
  + `tests/unit/test_skill_spec.py` → **249 passed in 42.78s**.
- **Test khi BẬT:** cùng ba tệp với `BOXFOX_CONTEXT_SURFACE=on` → **249 passed in 41.72s**.
- **Khởi động lại instance** với `BOXFOX_RECOVERY_POLICY=on` + `BOXFOX_CONTEXT_SURFACE=on`: `runtime-info` trả
  hai công tắc `on: true, source: explicit`, năm thành viên còn lại `default/off`.
- **Vòng live** (`--label enable-step2 --only skill_view,tools_and_file --switches off`):
  - `skill_view` **PASS** — `skill_view` đã chạy, không `SKILL_UNKNOWN`, trả lời đúng nội dung skill
    `work-graph-planning` (v2.0.0) từ catalog;
  - `tools_and_file` **PASS** — như bước 1 (đối chứng parity);
  - `adaptive_off` **PASS** — `409 POLICY_SWITCH_OFF`, policy không đổi.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step2/` (`summary.json`: total 3, passed 3, failed 0);
  log `/var/tmp/boxfox-enable/backend-3116-step2.log`.

### Bước 3 — `BOXFOX_TASK_SURFACE` (2026-10-05, cộng dồn bước 1–2)

- **Test khi TẮT:** `BOXFOX_TASK_SURFACE=off` + `tests/unit/test_harness_task_service.py` +
  `tests/unit/test_task_surface.py` + `tests/unit/test_runtime_info.py` → **112 passed in 37.34s**.
- **Test khi BẬT:** cùng ba tệp với `BOXFOX_TASK_SURFACE=on` → **112 passed in 37.65s**.
  - Vòng chạy BẬT đầu tiên đỏ **1 test** (`test_task_surface.py::test_switch_is_off_by_default_and_only_on_enables`):
    test khẳng định trạng thái MẶC ĐỊNH nhưng đọc env ambient, mà bước bật dần lại chạy cả bộ với
    env BẬT. Đây là lỗi hermeticity của test, không phải lỗi sản phẩm; đã cắt env bằng
    `monkeypatch.delenv` ở commit `1ad3ae8` (kèm `test_job_surface.py::test_switch_defaults_off[None]`
    gặp đúng lỗi đó ở bước 4). Sau khi sửa: 112/112 ở cả hai trạng thái.
- **Khởi động lại instance** với `BOXFOX_RECOVERY_POLICY=on` + `BOXFOX_CONTEXT_SURFACE=on` +
  `BOXFOX_TASK_SURFACE=on`: `runtime-info` trả ba công tắc `on: true, source: explicit`, bốn thành viên
  còn lại `default/off`, 61 tool; log `/var/tmp/boxfox-enable/backend-3116-step3.log`.
- **Vòng live** `driver_task.py` (kịch bản `delegate_contract`, model sống gọi `delegate_task` kèm hợp đồng):
  - Năm vòng đầu với model mặc định `space-bunny-free` **KHÔNG ĐẠT**: model luôn gọi đúng `work_graph` +
    `delegate_task`, nhưng phiên âm sai kiểu các mảng rỗng của hợp đồng (`"inputs": ""`, `"dependsOn": ""`,
    có vòng bọc `{"item": ...}`). Bề mặt từ chối đúng cách — `HARNESS_CONTRACT_INVALID` nêu đúng tên trường,
    `action: checkpoint_and_ask`, **không ghi hàng task/attempt nào** (không có trạng thái dở dang).
    Đây là giới hạn của model miễn phí, không phải lỗi sản phẩm (xem ghi chú bên dưới).
  - Vòng đạt: ghim model miễn phí khác `mimo-v2.6-flash-free` (vẫn 0 đồng, không đụng ngân sách) →
    `enable-step3-mimo` **1/1 kịch bản, 6/6 phép kiểm**: `work_graph` mở run `w-06d133f8d5`,
    `delegate_task` chạy, hàng task bền vững `task-592496d0598b491d9e99033d10fcf3bd` (alias
    `e2e-durable-mimo`, `state: succeeded`, revision 3), attempt 1 gắn phiên con thật
    `8f214a240f444f8b98e368f35a9ff0cb` (role `explore`, `completed`), lượt kết thúc `completed`,
    con đếm đúng 22 tệp `.md` dưới `.plans/`.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step3-mimo/` (`summary.json`: total 1, passed 1,
  failed 0) — các vòng không đạt giữ nguyên ở `runs/enable-step3/`, `runs/enable-step3b..3e/`, `runs/task-recheck/`.
- **Ghi chú model:** bề mặt task bền vững chỉ dùng được khi model phiên âm đúng JSON lồng nhau. Model mặc định
  `space-bunny-free` hiện viết `""` cho mảng rỗng nên hợp đồng luôn bị từ chối; ghim một model miễn phí khác
  là đủ. Đã ghi nhận thành phát hiện ngoài phạm vi (`652bc4b7`): khai `properties` lồng nhau cho tham số `task`
  hoặc nhận `task` dạng chuỗi JSON để bề mặt chịu được model yếu.

### Bước 4 — `BOXFOX_CONTROLLER_JOBS` (2026-10-05, cộng dồn bước 1–3)

- **Test khi TẮT:** `BOXFOX_CONTROLLER_JOBS=off` + `tests/unit/test_harness_jobs.py` +
  `tests/unit/test_job_surface.py` + `tests/unit/test_job_wake.py` → **125 passed in 57.36s**.
- **Test khi BẬT:** cùng ba tệp với `BOXFOX_CONTROLLER_JOBS=on` → **125 passed in 58.07s**.
  (Vòng BẬT đầu tiên đỏ 1 test `test_job_surface.py::test_switch_defaults_off[None]` — cùng lớp
  hermeticity đã sửa ở `1ad3ae8`.)
- **Khởi động lại instance** thêm `BOXFOX_CONTROLLER_JOBS=on`: `runtime-info` trả bốn công tắc
  `on: true, source: explicit`, ba thành viên còn lại `default/off`, 61 tool (catalog có đủ
  `start_job`/`get_job`/`subscribe_job`/`wait_jobs`/`cancel_job`); log
  `/var/tmp/boxfox-enable/backend-3116-step4.log`.
- **Vòng live** `driver_job.py` (kịch bản `start_job`, model sống gọi `start_job` rồi `get_job`),
  model miễn phí ghim `mimo-v2.6-flash-free`: `enable-step4` **1/1 kịch bản, 6/6 phép kiểm** —
  hàng job bền vững `job-833d5497f5e04392874fe11a73676815` (`kind: model`, `ownership: controller`,
  owner = phiên main), phiên con thật `6dccce7f01924fe4b770af866d6b1eee` (role `explore`) được admit,
  không có `JOB_SURFACE_OFF`, lượt kết thúc `completed`. Đọc lại sau khi vòng chạy xong: job đã tự
  chuyển `state: succeeded` (revision 3, `closed_at` có giá trị) và con hoàn tất 1 lượt — job sống
  qua khỏi lượt main như thiết kế H4.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step4/` (`summary.json`: total 1, passed 1,
  failed 0).

## Trạng thái hiện tại của instance bật dần

`BOXFOX_RECOVERY_POLICY=on`, `BOXFOX_CONTEXT_SURFACE=on`, `BOXFOX_TASK_SURFACE=on`,
`BOXFOX_CONTROLLER_JOBS=on`; ba công tắc còn lại TẮT; `BOXFOX_REFORM` chưa đặt (`default`).
Bước kế tiếp: **bước 5 — `BOXFOX_USAGE_LEDGER`** (test `test_usage_ledger.py` + `test_usage_surface.py`
+ `test_peer_cost.py`, live `driver_child.py`).
