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
| 3 | `BOXFOX_TASK_SURFACE` | — | — | — | — | — | chưa chạy |
| 4 | `BOXFOX_CONTROLLER_JOBS` | — | — | — | — | — | chưa chạy |
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

## Trạng thái hiện tại của instance bật dần

`BOXFOX_RECOVERY_POLICY=on`, `BOXFOX_CONTEXT_SURFACE=on`; năm công tắc còn lại TẮT;
`BOXFOX_REFORM` chưa đặt (`default`). Bước kế tiếp: **bước 3 — `BOXFOX_TASK_SURFACE`**
(test `test_harness_task_service.py` + `test_tool_groups.py`, live `driver_task.py`).
