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
| 5 | `BOXFOX_USAGE_LEDGER` | 2026-10-05 | **92 passed** | **92 passed** | `on: true, source: explicit` (kèm bước 1–4) | `enable-step5`: **3/3 kịch bản, 9/9 phép kiểm** | ✅ ĐẠT |
| 6 | `BOXFOX_ADAPTIVE_HARNESS` | 2026-10-05 | **100 passed** | **100 passed** | `on: true, source: explicit` (kèm bước 1–5) | `enable-step6`: **3/3 kịch bản, 9/9 phép kiểm** + `enable-step6-caps`: **1/1 kịch bản, 7/7 phép kiểm** | ✅ ĐẠT |
| 7 | `BOXFOX_RESEARCH_GATEWAY` | 2026-10-05 | **115 passed** | **115 passed** | `on: true, source: explicit` (kèm bước 1–6) | `enable-step7`: **4/4 kịch bản, 11/11 phép kiểm** | ✅ ĐẠT (quyết định #6597 của chủ nhà) |
| 8 | `BOXFOX_REFORM=on` (khóa tổng) | 2026-10-05 | (dùng lại bộ test của bước 1–7) | (như trên) | **cả bảy `on: true, source: master`** | `enable-step8` 5/5 kịch bản 16/16 phép kiểm; `enable-step8-task` 1/1–6/6; `enable-step8-job` 1/1–6/6; `enable-step8-caps` 1/1–7/7 | ✅ ĐẠT |

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

### Bước 5 — `BOXFOX_USAGE_LEDGER` (2026-10-05, cộng dồn bước 1–4)

- **Test khi TẮT:** `BOXFOX_USAGE_LEDGER=off` + `tests/unit/test_usage_ledger.py` +
  `tests/unit/test_usage_surface.py` + `tests/unit/test_peer_cost.py` → **92 passed in 32.02s**.
- **Test khi BẬT:** cùng ba tệp với `BOXFOX_USAGE_LEDGER=on` → **92 passed in 32.45s**.
- **Khởi động lại instance** thêm `BOXFOX_USAGE_LEDGER=on`: `runtime-info` trả năm công tắc
  `on: true, source: explicit`, hai thành viên còn lại (`ADAPTIVE_HARNESS`, `RESEARCH_GATEWAY`)
  `default/off`, 61 tool; log `/var/tmp/boxfox-enable/backend-3116-step5.log`.
- **Vòng live** `driver.py --only delegate,ledger_rows --switches off --db /var/tmp/boxfox-enable/data/sessions.sqlite`:
  - `delegate` **PASS** — main gọi `delegate_task` thật, con `explore` `65380d9d46844fbf8126297de8a38952`
    hoàn tất, main trả lời bằng số của con (22 tệp `.md`), lượt `completed`;
  - `ledger_rows` **PASS** — bảng `harness_usage` có thật, 5 hàng gần nhất đủ cột hợp đồng
    (`call_key`, `certainty`, `price_snapshot_json`, `input_tokens`, `output_tokens`…), token thật
    đã ghi (ví dụ 26804/1006, 26505/88, 12103/4096);
  - `adaptive_off` **PASS** — `409 POLICY_SWITCH_OFF`; `switches` trả về cho thấy
    `BOXFOX_USAGE_LEDGER: true` mà policy vẫn không đổi.
- **Sổ ghi chi của con (peer cost):** hàng usage ghi theo **root** (`owner_id` = phiên main) và
  `run_id` = phiên gọi thật, nên chi của con nằm chung sổ với cha mà vẫn tách được theo phiên:
  con `65380d9d46844fbf8126297de8a38952` có **14 hàng**, `owner_id` = main `92c519be55c94d19907ca4837a66ea22`
  (cùng sổ: 3 hàng của main). Tổng 44 hàng cho 6 `run_id`.
- **Thứ tự chạy quan trọng:** `ledger_rows` chỉ đọc DB, nên phải chạy một lượt model thật TRƯỚC
  (`delegate`) mới có hàng để kiểm. Vòng đầu chạy `ledger_rows` trước nên bảng còn rỗng và đỏ 4/4 —
  bằng chứng của vòng đó giữ ở `runs/enable-step5-scratch/`.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step5/` (`summary.json`: total 3, passed 3,
  failed 0) — `delegate.json`, `ledger_rows.json`, `adaptive_off.json` (kèm `attempts: 1`).

### Sửa lỗi phát hiện khi bật bước 3 — lời khuyên sai cho lỗi hợp đồng (commit `8aa0e70`)

- **Triệu chứng:** model gọi `delegate_task` kèm hợp đồng sai kiểu mảng, nhận `HARNESS_CONTRACT_INVALID`,
  rồi DỪNG và hỏi chủ nhà thay vì sửa trường. Mã lỗi này chưa có trong bảng phân loại của
  `recovery_policy` nên rơi `unknown` ⇒ `checkpoint_and_ask`.
- **Sửa:** khai lớp cho 18 mã bề mặt H3–H4 — hợp đồng/schema/role/decision và id không tồn tại ⇒
  `tool_validation` (`fix_input`: sửa trường rồi gọi lại, không replay tool); `JOB_ADMISSION_REQUIRED`,
  `TASK_OWNER_MISMATCH`, `TASK_REVISION_CONFLICT` ⇒ `rights_budget` (không tự retry để vượt quyền);
  mã toàn vẹn vẫn `unknown` (fail closed). Test: `test_recovery_policy.py` + `test_decision_flow.py`
  **73 passed**; nhóm 8 tệp bề mặt với `BOXFOX_RECOVERY_POLICY=on` **336 passed**.
- **Kiểm chứng sống lại bước 3 với model mặc định:** `driver_task.py --label retry-check
  --model space-bunny-free --attempts 2` → **1/1 kịch bản, 6/6 phép kiểm, `attempts: 1`** — model yếu
  nay đi hết một mạch (prompt đã thêm đoạn nhắc kiểu dữ liệu mảng), không cần tới lần chạy lại.
  Bằng chứng: `/code/.generated_artifacts/e2e/runs/retry-check/`.
- **Cơ chế chạy lại của driver:** `driver.py`, `driver_task.py`, `driver_job.py` nhận `--attempts`
  (mặc định 2); vòng hỏng được giữ nguyên dưới tên `<kịch bản>.attempt<N>.json` trước khi chạy lại,
  và `evidence.attempts` ghi lại lần chạy đã đạt.

### Bước 6 — `BOXFOX_ADAPTIVE_HARNESS` (2026-10-05, cộng dồn bước 1–5)

- **Test khi TẮT:** `BOXFOX_ADAPTIVE_HARNESS=off` + `tests/unit/test_adaptive_main.py` +
  `tests/unit/test_adaptive_surface.py` → **100 passed in 7.59s**.
- **Test khi BẬT:** cùng hai tệp với `BOXFOX_ADAPTIVE_HARNESS=on` → **100 passed in 7.50s**.
- **Khởi động lại instance** thêm `BOXFOX_ADAPTIVE_HARNESS=on`: `runtime-info` trả sáu công tắc
  `on: true, source: explicit`; chỉ còn `BOXFOX_RESEARCH_GATEWAY` TẮT; khóa tổng `BOXFOX_REFORM`
  vẫn `default/off`; log `/var/tmp/boxfox-enable/backend-3116-step6.log`.
- **Vòng live chính** `driver.py --only kernel_guard,delegate --switches on --db /var/tmp/boxfox-enable/data/sessions.sqlite`:
  - `kernel_guard` **PASS** — tệp ngoài phạm vi vẫn `ABSENT`, lượt `completed` (đối chứng owner-check mới
    không nới quyền);
  - `delegate` **PASS** (lần 1 hỏng vì câu trả lời rỗng — driver chạy lại và đạt ở lần 2; bản hỏng giữ ở
    `delegate.attempt1.json`): con `explore` `c8002498c2c548d9b599615eb79612ad` hoàn tất, main đối chiếu
    lại bằng `terminal_exec` và ra đúng 22 tệp `.md`;
  - `adaptive_on` **PASS** — `PUT execution-policy {mode: adaptive}` trả **200**, policy ghim `adaptive`,
    một lượt thật chạy trên route miễn phí kết thúc `completed`, sổ usage ghi hàng cho lượt
    (`amount 0.0`, `certainty: estimated`).
- **Vòng live phụ** `driver_child_caps.py --only peer_read_cap`: **1/1 kịch bản, 7/7 phép kiểm** — lần đọc
  đầu trả cửa sổ thật (64 sự kiện), 4 lần đọc được phép rồi lần thứ 5 bị `PEER_READ_CAPPED`, sau khi bị
  chặn không còn lần đọc nào thành công, lượt cha `completed`.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step6/` (`summary.json`: total 3, passed 3,
  failed 0) và `/code/.generated_artifacts/e2e/runs/enable-step6-caps/` (total 1, passed 1, failed 0).

### Bước 7 — `BOXFOX_RESEARCH_GATEWAY` (2026-10-05, cộng dồn bước 1–6; chủ nhà chốt ở #6597)

- **Sửa hermeticity trước khi bật (`84065cf`):** `test_research_gate_runtime.py` kiểm ĐƯỜNG CŨ
  (`BOXFOX_RESEARCH_GATE`) mà không ghim công tắc gateway, nên khi môi trường máy chạy đặt
  `BOXFOX_RESEARCH_GATEWAY=on` thì 11/12 ca đỏ (`RESEARCH_MAIN_READ_ONLY`). Thêm fixture autouse ghim
  gateway TẮT tường minh cho cả tệp — lỗi hermeticity, không phải lỗi sản phẩm.
- **Test:** `test_research_gateway.py` + `test_research_gate_runtime.py` + `test_research_owner.py` +
  `test_research_switches.py` → **115 passed in 44.42s khi TẮT** và **115 passed in 44.17s khi BẬT**
  (trước khi sửa: 115 / 11 failed).
- **Khởi động lại instance** thêm `BOXFOX_RESEARCH_GATEWAY=on`: `runtime-info` trả **bảy** công tắc
  `on: true, source: explicit`; `BOXFOX_REFORM` vẫn `default/off`; 61 tool, trong đó bốn công cụ cổng
  (`research_job_submit`, `research_job_get`, `research_job_result`, `research_job_control`);
  log `/var/tmp/boxfox-enable/backend-3116-step7.log`.
- **Vòng live** `driver.py --only research,research_gateway,research_main_tools --switches on
  --model mimo-v2.6-flash-free --db /var/tmp/boxfox-enable/data/sessions.sqlite` → **4/4 kịch bản,
  11/11 phép kiểm**:
  - `research` **PASS** — main vẫn `web_search` bình thường, câu trả lời kèm URL nguồn;
  - `research_gateway` **PASS** — `research_job_submit` thật tạo hàng cổng
    `research-3f2cd73e…` (`state: needs_consent`, revision 1, có `controller_id` là principal
    `research-lead` riêng) rồi `research_job_get` đọc receipt; không có chi nào được cấp;
  - `research_main_tools` **PASS** — main gọi `delegate_task role="research"` và bị **GUARD** chặn bằng
    `RESEARCH_MAIN_READ_ONLY` (lần gọi đó là lần lỗi), lượt vẫn `completed`. Ghi chú đo được: khi gateway
    BẬT, công cụ nội bộ VẪN nằm trong bộ lược đồ của main (chặn ở GUARD, không chặn ở bề mặt) — đúng
    thiết kế H7 "main không sửa internals"; hai model miễn phí từ chối gọi thẳng `source_add` (chúng nói
    công cụ "không tồn tại" — chép nguyên văn, đó là hành vi model, không phải bề mặt bị lọc: đã kiểm
    bằng `schemas_for` trên chính config sống: `source_add` CÓ trong 52 lược đồ hiệu lực).
  - `adaptive_on` **PASS** — công tắc adaptive vẫn nguyên sau khi gateway bật.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step7/` (`summary.json`: total 4, passed 4,
  failed 0). Vòng nháp giữ ở `enable-step7-scratch*/`.

### Bước 8 — `BOXFOX_REFORM=on`, một biến bật cả nhóm (2026-10-05)

- **Instance riêng cổng 3117, data dir mới `/var/tmp/boxfox-enable/data-master`, CHỈ đặt một biến**
  `BOXFOX_REFORM=on` (không đặt env thành viên nào); log `/var/tmp/boxfox-enable/backend-3117-step8.log`.
- **`runtime-info`:** khóa tổng `BOXFOX_REFORM: on, source: explicit`; **cả bảy thành viên
  `on: true, source: master`**; 61 tool — đúng hợp đồng "một lệnh bật cả nhóm".
- **Bốn driver trên chính instance đó** (model miễn phí `mimo-v2.6-flash-free`, DB của instance):
  - `driver.py --only delegate,kernel_guard,ledger_rows,research_gateway --switches on`
    → **5/5 kịch bản, 16/16 phép kiểm** (kèm `adaptive_on` chạy tự động ở cuối): con `explore` thật
    `fc84f8d2…` báo 22 tệp `.md`; ghi `/etc/...` vẫn `ABSENT`; sổ usage có hàng đủ cột với token thật;
    `research_job_submit` tạo hàng cổng `research-64984f0e…` (`needs_consent`); adaptive ghim được
    và lượt thật chạy với giá 0.
  - `driver_task.py` (`e2e-master-task`/`e2e-master-inv`) → **1/1 kịch bản, 6/6 phép kiểm**: hàng task
    `task-50ec2e69…` (`succeeded`, revision 3, run `w-b508aac76d`) + attempt 1 gắn con `8287ec8d…`.
  - `driver_job.py` → **1/1 kịch bản, 6/6 phép kiểm**: hàng job `job-e991f581…` (`kind: model`,
    `ownership: controller`); đọc lại sau lượt: `state: succeeded`, revision 3, có `closed_at`.
  - `driver_child_caps.py --only peer_read_cap` → **1/1 kịch bản, 7/7 phép kiểm**: 4 lần đọc được phép
    rồi lần thứ 5 bị `PEER_READ_CAPPED`, lượt cha `completed`.
- Bằng chứng: `/code/.generated_artifacts/e2e/runs/enable-step8/` (5/5), `enable-step8-task/`,
  `enable-step8-job/`, `enable-step8-caps/` — mỗi thư mục có `summary.json` + JSON từng kịch bản.

### Sửa hermeticity cho trạng thái "cả nhóm BẬT" (2026-10-05, sau bước 8)

Chạy nhóm 22 tệp liên quan với `BOXFOX_REFORM=on` phát hiện **16 ca đỏ** — cùng một lớp lỗi như
`1ad3ae8`: bài kiểm khẳng định hành vi MẶC ĐỊNH nhưng chỉ cắt env **thành viên**, không cắt **khóa tổng**,
nên khi khóa tổng BẬT thì giá trị hiệu lực là BẬT và khẳng định mặc định sai.

- Thêm `tests/unit/switch_isolation.py` với `isolate_default(monkeypatch, *switches)`: cắt cả env thành
  viên lẫn `BOXFOX_REFORM`, để giá trị hiệu lực thật sự là mặc định.
- Áp cho 16 ca ở sáu tệp: `test_task_surface.py` (9), `test_job_surface.py` (2), `test_usage_surface.py` (2),
  `test_runtime_info.py` (1), `test_research_gateway.py` (1), `test_context_surface.py` (1). Chỉ đụng test,
  không đổi sản phẩm.
- **Kết quả:** nhóm 22 tệp với `BOXFOX_REFORM=on` → **846 passed in 237.63s** (trước khi sửa: 16 failed,
  830 passed); chạy lại ở trạng thái mặc định (không env nào) → **846 passed in 232.98s**.

## Kiểm thử sau merge (2026-10-05, head `699ab8d`)

- Nhóm 22 tệp liên quan với `BOXFOX_REFORM=on`: **846 passed in 238.95s**.
- Toàn bộ `backend/tests/unit/` trên cây sau merge: **3 failed, 4382 passed, 12 skipped in 1262.91s** — đúng ba
  lỗi đỏ có sẵn từ baseline `346da06` (`test_terminal_exec_echo`,
  `test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`,
  `test_revoked_grant_blocks_next_tool_call`), không do PR này.
- Log: `/var/tmp/post-merge-tests.log`.

## Trạng thái hiện tại của instance bật dần

`BOXFOX_RECOVERY_POLICY=on`, `BOXFOX_CONTEXT_SURFACE=on`, `BOXFOX_TASK_SURFACE=on`,
`BOXFOX_CONTROLLER_JOBS=on`, `BOXFOX_USAGE_LEDGER=on`, `BOXFOX_ADAPTIVE_HARNESS=on`;
cả bảy thành viên đều `on: true, source: explicit`; `BOXFOX_REFORM` vẫn `default/off`.
**Bước 8 đã chạy xong** trên instance riêng cổng 3117 (`/var/tmp/boxfox-enable/data-master`) với đúng một
biến `BOXFOX_REFORM=on`: cả bảy thành viên `source: master` và bốn driver đều đạt.
**Bật dần đã hết tám bước.** Việc còn lại là quyết định phát hành (#6531/#6536) — không nằm trong nhóm
công tắc này.

## Phát hành: PR #3 đổi nhánh nền sang `main` (2026-10-05, quyết định #6598)

Chủ nhà giao agent quyết định (#6598: *"Tôi chưa hiểu lắm phần này, bạn có thể quyết định tốt nhất"*). Quyết
định: **PR #3 lấy `main` làm nhánh nền**, để một lần merge đưa được cả bản cải tổ vào `main` (trước đó base là
`vorflux/w10-w12-completion`, nhánh khảo sát chưa nằm trên `main`).

- Lý do chính: bản cải tổ dựng trên đầu nhánh khảo sát tại `346da06`, mà **PR #1 chỉ merge một phần** nhánh
  này — 15 commit còn lại (W6.Q/W6.2/W10/W11/W12 + tài liệu kiến trúc §1–§15) chưa từng nằm trên `main`.
  Giữ base cũ thì bản cải tổ không có đường vào `main`; đổi base là một cửa duy nhất.
- Hệ quả đã báo rõ trong PR: diff của PR #3 gồm cả 15 commit ấy (khoảng 35 tệp) bên cạnh H1–H12; phần đó
  không thuộc phạm vi review của đợt này. Muốn tách thì mở PR riêng `vorflux/w10-w12-completion → main` trước.
- Đã gộp `main` vào nhánh cải tổ (merge commit `699ab8d`) để PR hết xung đột: xung đột duy nhất là
  `docs/architecture/vorflux-vs-boxfox-orchestration.md` (add/add) và đã lấy bản đầy đủ hơn của `main`
  (bản trên nhánh là tập con thật sự). Ba tệp mang vào từ `main`: tài liệu kiến trúc nói trên,
  `docs/plan/BoxFox-reform-master.md`, `docs/plan/v1-boxfox-harness-reform.md`.
- Kiểm thử lại trên cây sau merge: xem `## Kiểm thử sau merge` bên dưới.

## v2 — bật mặc định (2026-10-05, quyết định #6599)

Chủ nhà chốt: *"tôi muốn bật lên hoàn toàn"* nhưng **giữ công tắc** để agent sau còn biết cách tổ chức
(#6599). v2 đổi mặc định của khóa tổng từ TẮT sang **BẬT**: vận hành không cần env nào; công tắc trở thành
lối thoát hiểm có tổ chức (`BOXFOX_REFORM=off` một lệnh cho cả nhóm, hoặc từng thành viên `off`).
Quyết định xoá hay giữ nhánh legacy thuộc checkpoint sau, cần bằng chứng chạy thật dài ngày — ghi ở
`HANDOFF.md` §6.4.

### Mã và test (commit `96f158e`)

- `backend/src/agentbox/agent_core/feature_switches.py`: `MASTER_DEFAULT = False` → **`True`** + docstring
  viết lại theo nghĩa v2 (giá trị hiệu lực = tường minh > khóa tổng > mặc định).
- 13 ghi chú "mặc định TẮT (bật dần từng công tắc)" ở bảy module lõi đổi thành "mặc định BẬT từ v2 (#6599),
  tắt tường minh bằng `off`" (`context_surface.py`, `job_surface.py`, `research_gateway.py`,
  `task_surface.py`, `tool_contracts.py`, `usage_ledger.py`, `recovery_policy.py`). Chỉ đổi chú thích, không
  đổi hành vi đọc công tắc.
- Đảo mặc định làm ~35 tệp test chốt hành vi cũ đỏ. Cách xử lý có tổ chức thay vì sửa từng bài:
  - `backend/tests/unit/switch_isolation.py` thêm `isolate_off(monkeypatch, *switches)` (cạnh
    `isolate_default`): cắt env khóa tổng + đặt tường minh các thành viên được nêu là `off`.
  - `backend/tests/unit/conftest.py` (MỚI): marker `legacy_path` + fixture autouse đặt `BOXFOX_REFORM=off`
    cho mọi bài mang marker.
  - **35 tệp** chốt hành vi TRƯỚC v2 được gắn `pytestmark = pytest.mark.legacy_path` (khối chú thích 2 dòng
    nêu lý do). Ba tệp đỏ có sẵn từ baseline **không** gắn (không phải ca legacy): `test_terminal_tools.py`,
    `test_web_tools.py`, `test_work_tool_replay.py`.
  - Sáu tệp khẳng định MẶC ĐỊNH chuyển sang `isolate_off` (cắt cả khóa tổng) hoặc sang khẳng định mới của v2
    (`test_context_surface.py`, `test_job_surface.py`, `test_research_gateway.py`, `test_usage_surface.py`,
    `test_task_surface.py`, `test_reform_master_switch.py`).
  - `test_reform_master_switch.py` thêm ca `test_master_default_constant_is_true_after_the_v2_flip` và ca
    "không env nào ⇒ cả nhóm BẬT, `source: default`"; `test_runtime_info.py` thêm ca khối `switches` hiện
    mặc định v2 của cả nhóm.

### Bốn con số kiểm thử

| Lần chạy | Kết quả | Log |
|---|---|---|
| Toàn bộ `backend/tests/unit/` **không env** (lần chạy HỖN HỢP: 35 tệp legacy chạy dưới pin `legacy_path`, phần còn lại chạy mặc định mới) | **3 failed, 4384 passed, 12 skipped** trong 1292.85s — đúng ba lỗi đỏ baseline `346da06`, không phát sinh đỏ mới | `/var/tmp/v2-full-unit-2.log` |
| Nhóm 22 tệp liên quan, mặc định mới | **747 passed** trong 236.49s (EXIT=0) | `/var/tmp/v2-default-group.log` |
| Cùng nhóm 22 tệp, `BOXFOX_REFORM=off` | **747 passed** trong 237.16s (EXIT=0) — đường rollback một lệnh vẫn xanh | `/var/tmp/v2-off-group.log` |
| Mẫu 7 tệp chẩn đoán (đối chứng) | `off` → 128 passed; mặc định mới → 66 failed, 62 passed ⇒ đỏ do ĐẢO MẶC ĐỊNH, không do lỗi sản phẩm | `/var/tmp/v2-sample-off.log`, `/var/tmp/v2-sample.log` |

### Bằng chứng sống trên instance 3118

Instance mới (`BOXFOX_AGENT_DATA_DIR=/var/tmp/boxfox-enable/data-v2`, cổng 3118) chạy **không env công tắc
nào**; `GET /api/agent/runtime-info`:

- `switches.master` = `{'name': 'BOXFOX_REFORM', 'on': True, 'source': 'default'}`;
- cả bảy thành viên `{'on': True, 'source': 'default'}`;
- `tools: 61`.

Ảnh đầy đủ: `/code/.generated_artifacts/v2/runtime-info-default-3118.json`. (Trước v2 cùng khối này hiện
`on: false, source: default` — xem mục bước 8 ở trên.)

### Bốn driver trên 3118 (mặc định mới)

Bốn driver live, tất cả trên 3118 (mặc định mới, không env công tắc), model miễn phí như mọi vòng E2E:

| Driver | Nhãn | Kết quả | Bằng chứng / ghi chú |
|---|---|---|---|
| `driver.py` (11 kịch bản) | `v2-default` | **11/11 PASSED** (EXIT=0) | `kernel_guard` lần 1 đỏ rồi tự chạy lại lần 2 xanh; `/code/.generated_artifacts/e2e/runs/v2-default/` |
| `driver_job.py` | `v2-default-job` | **1/1 PASSED**, 6/6 check (EXIT=0) | job `job-c30b4f1e` kind `model`, ownership `controller`; phiên con `7319bd6722e3` role `explore`; `/code/.generated_artifacts/e2e/runs/v2-default-job/` |
| `driver_child_caps.py` (5 kịch bản) | `v2-default-caps` | **5/5 PASSED** (EXIT=0) | `await_nudge_cap` (3/3 timeout rồi `PEER_WAIT_CAPPED`), `peer_read_cap` (4 lần đọc OK rồi `PEER_READ_CAPPED`), `resume_not_cut` (`CHILD_RESUME_NOT_CUT`), `resume_second_turn` (attempt 1→2), `resume_wait_false`; `/code/.generated_artifacts/e2e/runs/v2-default-caps/` |
| `driver_task.py` | `v2-default-task` | **0/1 — model MIỄN PHÍ làm hỏng hợp đồng task** | Không phải hồi quy sản phẩm: cùng driver **đã PASS 1/1** ở `enable-step8-task` (3117, công tắc bật). Transcript: model nâng `acceptance` lên gốc (bị từ chối), rồi gửi `inputs: []`, `inputs: ""`, `dependsOn: ""` — không lần nào đủ hợp đồng. Bằng chứng: `/code/.generated_artifacts/e2e/runs/v2-default-task/delegate_contract.json` |


### Drill rollback một lệnh

Hai lệnh trên CHÍNH instance 3118 + data dir `data-v2` (không đổi code, không migration, không mất dữ liệu):

1. Restart với `BOXFOX_REFORM=off` → `GET /api/agent/runtime-info`: `switches.master = {'on': False, 'source': 'explicit'}`,
   **cả bảy thành viên `{'on': False, 'source': 'master'}`** (`/code/.generated_artifacts/v2/runtime-info-reform-off-3118.json`).
2. `driver.py --only kernel_guard,tools_and_file --switches off` → **3/3 PASSED** (EXIT=0): hai kịch bản đường cũ giữ
   nguyên hành vi, kịch bản `adaptive_off` xác nhận đường mới bị TỪ CHỐI đúng trạng thái TẮT (`POLICY_SWITCH_OFF`) —
   `/code/.generated_artifacts/e2e/runs/v2-rollback-off/`.
3. Restart bỏ env → cả nhóm lại `{'on': True, 'source': 'default'}`
   (`/code/.generated_artifacts/v2/runtime-info-back-on-3118.json`).

Một env `off` là đủ để về hành vi trước v2; **bỏ env KHÔNG phải rollback** (env trống = BẬT).


## v2 — trần chi (mock $4/$20) — 2026-10-05 (quyết định #6600)

Mở lại phần **giới hạn ngân sách** của H10.2 (đã hoãn ở #6531) và kiểm chứng nó **sống**, bằng đúng cách
chủ nhà cho phép: model **MIỄN PHÍ** + **giá giả** trên **router bản sao**; **tuyệt đối không gọi model trả
phí**. Trước v2, `harnessAllocationId` không có nơi ghi trong `backend/src` (H6.9) nên đường reserve chỉ
sống khi test ghim tay.

### Mã mới (commit `96f158e`)

- `backend/src/agentbox/api/server.py`: route vận hành `GET|PUT|DELETE /api/agent/sessions/{sid}/usage-allocation`
  (sau ranh giới admin/Origin như mọi route khác). PUT đòi `consentRef` (thiếu → `USAGE_NO_CONSENT` 400) và
  `ceiling` dương (thiếu/sai → `USAGE_FIELD_INVALID` 400), mở reservation với
  `policyRevision = capability_epoch(...)` rồi ghim `harnessAllocationId` vào config gốc; đã gắn thì PUT lần
  hai trả **409 `ALLOCATION_ALREADY_ATTACHED`**. DELETE gỡ pointer trước rồi `ledger.release(...)`.
  `runtime-info` thêm khối `usage.allocations` (đọc `usage_ledger.open_allocations()`).
- `backend/src/agentbox/agent_core/usage_ledger.py`: `open_allocations(limit=20)` — hàng `reserved` mới nhất
  trước; bảng thiếu → `[]`; `limit` sai → `USAGE_FIELD_INVALID`.
- Test: `backend/tests/unit/test_usage_allocation_route.py` (MỚI, 8 ca: 403 thiếu admin; 400 thiếu
  ceiling/consent; ghim root + `policyRevision`; con ghim root; PUT lần hai 409; GET còn lại + DELETE release;
  view route = `ledger.get_allocation`; không tool nào mở được trần) + 2 ca `open_allocations` trong
  `test_usage_ledger.py` + `test_the_usage_block_lists_open_allocations` trong `test_runtime_info.py`.
  Chạy: **64 passed** (ledger + route), **14 passed** (runtime-info); sau hậu kiểm v2: **68 passed** (ledger + route), **15 passed** (runtime-info).

### Giao thức (bằng chứng: `/code/.generated_artifacts/h10/mock-price-20261005/`)

1. Chụp router thật (`snapshot-real-router-before.json`): `space-bunny-free` giá 0/0, context `null`;
   sha256 `router.sqlite` = `f50bbe3551f33425116a99d4fbf22f97642a553be0c1ba71b028729242ef8d8a`.
2. Bản sao WAL-safe bằng Python `sqlite3` `source.backup(target)` → `/var/tmp/boxfox-budget/router-data/`
   (kèm `master.key`), chạy `node src/main.mjs` cổng 3211
   (`BOXFOX_ROUTER_DATA_DIR=/var/tmp/boxfox-budget/router-data BOXFOX_ROUTER_PORT=3211 BOXFOX_OAUTH_PORT=52121`).
3. Giá giả:
   `curl -s -X PATCH -H 'x-boxfox-admin: 1' -H 'content-type: application/json' -d '{"modelPricing":{"modelId":"space-bunny-free","input":4,"output":20}}' http://127.0.0.1:3211/api/router/connections/d7e26488-65b0-4012-8009-589cd94b324b`
   rồi `modelContextWindow` 1 000 000 ⇒ `pricing.source='manual'` (`snapshot-copy-mocked.json`).
4. Tầm nhìn harness: `_price` = `{input: 4, output: 20, source: 'manual'}`; `_bound(rows, 4096)` = **4.08192**
   (= (1 000 000×4 + 4 096×20)/1 000 000) — đúng con số plan dự đoán.
5. Bốn ca (driver `/code/.generated_artifacts/h10/mock_price_ceiling_v2.py`: runtime thật trong tiến trình +
   `aiohttp` TestServer cho route thật):
   - **A — không allocation** (`case-A-no-consent.json`): `USAGE_NO_CONSENT`, `modelCalls: 0`, 0 hàng allocation.
   - **B — trần hẹp hơn bound** (`case-B-ceiling-exceeded.json`): ceiling 1.00 < 4.08192 →
     `USAGE_CEILING_EXCEEDED`, `modelCalls: 0`, hàng allocation vẫn `reserved` (`consumed.amount: null`).
   - **C — trong trần** (`case-C-within-ceiling.json`): ceiling 10.00 → reserve 4.08192 → gọi model free thật
     (12.19 s, trả `pong`) → hàng `harness_usage` `amount 0.001272` (= (163×4 + 31×20)/1e6),
     `price_snapshot.source='manual'`; reservation chuyển `released`, `releasedAmount 4.080648`.
   - **D — route miễn phí** (`case-D-free-route.json`): PATCH giá về 0/0 ⇒ adaptive **không** allocation đi
     qua, `amount 0.0`, `certainty: estimated`, `bound 0.0`.
6. Revert + chứng minh mock biến mất: PATCH bản sao về 0/0 (`snapshot-copy-after-revert.json`); kill tiến
   trình 3211 (cổng trống); `rm -rf /var/tmp/boxfox-budget` (xoá cả bản sao chứa `master.key`); router thật
   vẫn 0/0/context `null` và **sha256 không đổi** (`snapshot-real-router-after.json`).

**Kết luận:** đường trần chi chạy sống đúng hợp đồng; cả hai đường từ chối đều chặn **TRƯỚC** khi gọi model
(`modelCalls: 0`); **không có chi phí thật nào phát sinh**. H10.1 (calibration sống) **vẫn hoãn**.


## v2 — hậu kiểm: ba vòng review độc lập + sửa (commit `4c4c5dc`, `9da988f`)

Hai review độc lập (`v2-review-switches` rủi ro 5/10, `v2-review-usage` rủi ro 3/10) và một simplify chạy
trên `c6fd6e9..96f158e`; mọi phát hiện trong tầm được sửa trong commit này — không đổi mặc định, không đổi
hợp đồng công khai.

### Miền công tắc (review 1)

- **Chốt lại: spawn research của Work Graph dừng dưới mặc định BẬT là CÓ CHỦ ĐÍCH, không phải hồi quy.**
  `research_gateway.guard_delegate` chạy trước nhánh `work=`, đúng H7.1/P5 ("intent của main là đầu vào,
  không bao giờ canonical"); luồng `research` của Work Graph là đường legacy, thay bằng biên Research độc lập.
  Đã ghi `HANDOFF.md` §6.5, sửa docstring `runtime.delegate`, khoá bằng test mặc định
  `test_engine_work_spawns_cannot_bypass_the_gateway_either`. Hai lối thoát hiểm giữ nguyên:
  `BOXFOX_RESEARCH_GATEWAY=off`, hoặc binding research legacy của phiên cũ.
- **Marker `legacy_path` nay KÍN**: fixture pin cả khóa tổng LẪN bảy thành viên `off`. Trước đó
  `BOXFOX_REFORM=off BOXFOX_RESEARCH_GATEWAY=on` vẫn lọt vào đường cũ (9 bài đỏ) — nay 9/9 xanh.
- **Sửa chỉ dẫn rollback tự mâu thuẫn**: `HANDOFF.md` §6.1 bước 6 và §9 mục 5 nay nói rõ "đặt tường minh
  `BOXFOX_<TÊN>=off`" — bỏ env là BẬT, không phải rollback.
- `test_journal_tools.py` bỏ marker (không nằm trong danh sách đỏ, không cần pin) → đúng **35 tệp** như
  tài liệu; sửa luôn dòng trống thừa.
- Số liệu tài liệu sửa cho khớp: `test_reform_master_switch.py` **20 ca**, `H6.8` trỏ đúng
  `H6/evidence.md`, hàng full-suite ghi rõ là lần chạy HỖN HỢP (35 tệp legacy pin `off`).

### Miền trần chi H10.2 (review 2)

- **PUT song song**: `attached` được đọc lại SAU `await request.json()` (trước đây hai PUT song song cùng
  reserve → con trỏ ghi đè, một hàng `reserved` mồ côi vĩnh viễn). Test:
  `test_two_concurrent_puts_attach_exactly_one`.
- **Gỡ trần khi con còn giữ chỗ**: luật đóng đổi từ `consumed + released >= amount` sang `remaining == 0`,
  và phần con trả lại sau đó chảy tiếp vào `releasedAmount` của cha (`_cascade_release_to_parent`). Trước
  đây mọi trần từng có con tiêu tiền nằm `reserved` VĨNH VIỄN (không API nào gỡ được, vẫn hiện trong
  `usage.allocations`). Test: `test_delete_closes_a_ceiling_even_when_a_child_already_spent`; ca cũ
  `test_parent_release_cannot_free_held_child_budget` cập nhật theo luật mới.
- **`runtime-info` chỉ đọc THẬT**: `_open_allocations` kiểm `sqlite_master` trước khi dựng sổ — trước đây
  một GET tạo bảng `harness_usage`/`harness_allocations` kể cả khi cả nhóm TẮT (rollback vẫn ghi schema).
  Test: `test_the_usage_read_never_creates_the_ledger_tables`.
- **Ceiling số nguyên khổng lồ** (`10**400`) trả 400 `USAGE_FIELD_INVALID` thay vì 500. Test:
  `test_an_absurd_integer_ceiling_is_refused_not_a_crash`.
- Ghi nhận KHÔNG sửa (đã cân nhắc): `except Exception` quanh khối `usage` là cố ý — tab Harness không đỏ
  vì sổ hỏng, chỉ ghi log; lệch status 409/400 khi con trỏ trỏ vào allocation đã mất là nit đã biết.

### Kiểm chứng sống sau khi sửa (3118 + code mới)

- `live_allocation_check.py --base 3118` → **9/9 PASSED**: PUT 200 (`reserved`, `policyRevision 1`,
  `remaining = ceiling`), runtime-info thấy allocation, GET `attached: true`, PUT lần hai 409
  `ALLOCATION_ALREADY_ATTACHED`, DELETE `detached: true` + trả đúng ceiling, runtime-info sạch sau DELETE,
  DELETE lần hai `detached: false`. Bằng chứng `/code/.generated_artifacts/v2/live-allocation.json`.
- Bốn tệp test liên quan sau khi sửa: **132 passed** (route 11 + ledger 57 + runtime-info 15 + gateway 49).

### Vòng hai: review delta `4c4c5dc` + sửa (`9da988f`)

Review delta tìm thêm hai ca; cả hai đã sửa ngay:

- **(F1, Medium) DELETE khi con đang giữ TRỌN trần**: `remaining` của cha đúng bằng `0.0`, nên `if released:`
  bỏ qua lệnh release — con trỏ gỡ rồi mà hàng nằm `reserved` vĩnh viễn, rồi hiện lại trong
  `usage.allocations` khi con tiêu/trả lại, không còn đường gỡ. Nay `if released is not None:` để luật đóng
  `remaining == 0` chốt hàng. Test mới: `test_delete_closes_a_ceiling_when_a_child_holds_all_of_it`.
- **(F2, nit) `_open_allocations` chỉ dò `harness_allocations`**: schema dở dang (thiếu `harness_usage`) vẫn
  bị lượt đọc vá thêm bảng. Nay dò ĐỦ hai tên. Test mới: `test_a_half_built_ledger_schema_is_left_alone`.
- Cả hai bài mới đều **đỏ khi lùi mã nguồn** (kiểm chứng bằng mutation tại chỗ) — tức chúng thật sự khoá
  bản sửa, không phải test trang trí.
- `d4bd374` chỉ khôi phục xuống dòng CRLF cho `test_runtime_info.py` (bài mới ở `9da988f` vô tình ghi cả
  tệp bằng LF) — diff so với bản trước còn đúng 27 dòng thêm, nội dung không đổi.
- Chạy lại sau vòng hai: **134 passed** (route 12 + ledger 57 + runtime-info 16 + gateway 49);
  **sweep hồi quy 152 passed** (chạy hai lần, EXIT=0); `live_allocation_check.py --base 3118` trên instance
  khởi động lại với code mới: vẫn **9/9**.

## v3 — xoá dần 6/7 bề mặt legacy (2026-10-05)

Chủ nhà chốt lựa chọn B của `HANDOFF.md` §10.2 ("xoá dần dần để công tắc mặc định là bật"). Mỗi bề
mặt một commit, mỗi commit làm trọn B1–B3 (bỏ pin test + bỏ nhánh code `off` + bỏ tên env khỏi
`feature_switches.MEMBERS`). Nhánh `vorflux/boxfox-legacy-surface-removal` (worktree
`/var/tmp/boxfox-legacy-wt`), nền `main` @ `f8f33b3`.

| Bề mặt | Commit | Quy mô | Test tại chỗ | Live |
|---|---|---|---|---|
| `BOXFOX_RECOVERY_POLICY` | `4a4bdac` | `recovery_policy.py` mất `SWITCH`/`enabled()`; 2 cổng `runtime.py` vô điều kiện | 95 + 26 passed | — |
| `BOXFOX_CONTEXT_SURFACE` | `42b337a` | mất `SWITCH`/`enabled()`/`_active()`; 4 bài legacy-off xoá | 93 passed | — |
| `BOXFOX_TASK_SURFACE` + `BOXFOX_CONTROLLER_JOBS` + `BOXFOX_USAGE_LEDGER` | `64f960d` | 25 tệp, +89/−381; `tool_groups` → `alwaysOn: True` | 34 + 219 + 122 passed | — |
| `BOXFOX_ADAPTIVE_HARNESS` | `f2fceb0` | 14 tệp, +39/−166; giữ mode `adaptive`/`legacy` | 105 + 243 + 12 passed | — |

- `feature_switches.MEMBERS` còn đúng một tên: `BOXFOX_RESEARCH_GATEWAY`.
- **Bề mặt 7 (RESEARCH_GATEWAY) cố ý chưa xoá.** Số đo trên 35 tệp ghim `legacy_path` khi pin bị gỡ
  (`strip_legacy_pin`): trước đợt `232 failed / 416 passed / 7 errors`; sau 6 bề mặt
  `231 failed / 405 passed / 7 errors`; thêm `BOXFOX_RESEARCH_GATEWAY=off` → **`643 passed` (0 đỏ)**.
  Nghĩa là mọi số đỏ còn lại thuộc đúng bề mặt 7, và xoá nó cần chủ nhà chốt luồng `research` của
  Work Graph + chuyển phiên cũ khỏi `researchId` (`HANDOFF.md` §10.6).
- Bằng chứng: `/var/tmp/wt-strip.log` (sau 6 bề mặt), `/var/tmp/wt-strip-gwoff.log` (đối chứng gateway
  off), `/var/tmp/pin-strip-A.log` (trước đợt), plugin `/var/tmp/strip_legacy_pin.py`.
