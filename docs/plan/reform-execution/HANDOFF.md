# HANDOFF — toàn bộ đợt cải tổ harness BoxFox (H0–H12)

> **Đọc file này trước mọi việc khác.** Đây là bản bàn giao TỔNG: một chỗ nói rõ đã làm gì, kiến trúc
> nào đang có, từng công tắc bật/tắt ra sao, và **quy trình bật dần từng công tắc** kèm cách kiểm.
> Bản theo từng checkpoint nằm ở `docs/plan/reform-execution/H0/ … H11/` (mỗi thư mục 5 file:
> `contract.md`, `baseline.json`, `evidence.md`, `migration.md`, `handoff.md`).

## 1. Đường dẫn gốc — đọc theo thứ tự này

| Việc | Đường dẫn |
|---|---|
| Kế hoạch đã duyệt (plan_id 1257) | `/code/.plans/v1-boxfox-harness-reform.md` |
| Runbook thực thi (khung thư mục §II.2, nghiệm thu §II.3, ma trận kiểm §II.4, rollback §II.6) | `/code/.plans/reform-execution-runbook.md` |
| Bảng trạng thái theo dõi (nguồn số test, commit, dòng lỗi) | `docs/plan/reform-status.md` |
| Kiến trúc BoxFox vs Vorflux | `docs/architecture/vorflux-vs-boxfox-orchestration.md` |
| Bàn giao từng checkpoint | `docs/plan/reform-execution/H0/ … H11/` |
| Ánh xạ backlog + kiểm kê nợ | `/code/.plans/reform-backlog-disposition.md`, `/code/.plans/reform-backlog-audit.md` |
| Pull request | https://github.com/i3abyxinhdepqua-lang/BoxFox-Agent-Box/pull/3 (nhánh `vorflux/boxfox-harness-reform`, base `vorflux/w10-w12-completion`) |

## 2. Bức tranh một trang — đợt này nhằm gì

BoxFox trước đây là một harness một-lượt: main chạy một mạch, con là lời gọi tạm, không có kho việc
bền, không có sổ chi, không có đường Research riêng. Vorflux (nền tảng đang chạy phiên này) làm khác:
việc được cấp phát qua kernel, có hợp đồng task, có sổ usage, có subagent gọi lại được. Đợt cải tổ
này kéo BoxFox lại gần mô hình đó — **nhưng giữ đường cũ chạy nguyên vẹn cho tới khi bật**.

Sáu ý chủ nhà chốt (#6490–#6499) và phần đã làm tương ứng:

| # | Ý | Điểm nối |
|---|---|---|
| #6490 | Main thích ứng, không graph cố định | H8 (`adaptive_main.py` → `adaptive_surface.py`) |
| #6491 | Ngân sách linh hoạt nhưng không vô hạn | H6 (`usage_ledger.py` → `usage_surface.py`) |
| #6492 | Quyền native, con không rộng hơn cha | H2 (kernel admission) |
| #6493 | Research là hệ độc lập | H7 (`research_owner.py` → `research_gateway.py`) |
| #6494 | Harness trước, môi trường sau | toàn bộ diff (không đụng desktop/update/mobile) |
| #6495 | Budget/loop signal, không cắt tuỳ tiện | H6 + H8 |
| #6498/#6499 | Đánh giá bằng mã/nguồn công khai, map suite legacy | H9 (`scripts/eval/suite_v2.py`) |
| #6545–#6548 | Quản lý con/subagent (trần, cờ kết cục, gọi lại con bị cắt) | H11 |

## 3. Đã làm gì — theo checkpoint

| CP | Nội dung | Commit chính | Bằng chứng | Trạng thái |
|---|---|---|---|---|
| H0 | Chốt baseline W10.F, parity `6adbe78` ≡ `346da06` | `346da06` | 31/34 cell theo lệnh chủ nhà | partial |
| H1 | Hợp đồng + tương thích ngược (`orchestration_contracts.py`) | `79f024b`… | 77 ca; legacy read 8/8 | verified |
| H2 | Một cửa admission (`execution_kernel.py`) + kho task (`task_service.py`) | — | 34 + 60 ca; parity S4/S5 `failed=[]` | verified |
| H3 | Bề mặt task (`task_surface.py`) + phân loại hồi phục | — | E2E 9/9 (110 check), probe 71/71, scoped 716 passed | verified |
| H4 | Job qua nhiều lượt (`harness_jobs.py` → `job_surface.py`, `job_wake.py`) | nối `802f51f` | 59 ca + P2 10/10; A1–A9/29 | verified |
| H5 | Context + skills (`context_bundle.py`, `skill_spec.py` → `context_surface.py`) | nối `802f51f` | 79 + 114 + 56 ca + P3 13/13 | verified |
| H6 | Phân bổ & hạch toán (`usage_ledger.py` → `usage_surface.py`) | nối `802f51f` | 55 + 22 ca + P4 7/7 | verified (phần trần chi hoãn #6531) |
| H7 | Research ownership (`research_owner.py` → `research_gateway.py`) | nối `802f51f` | 52 + 48 ca + P5 8/8 | verified (gateway mặc định off, #6536) |
| H8 | Main thích ứng (`adaptive_main.py` → `adaptive_surface.py`) | `c6c88bb`, `fcc6819` | 87 + 13 ca + P6 14/14; E1–E4/29 | verified |
| H9 | Suite v2 + calibration | `ed5d771`, `c3bee48` | 62 ca / 40 oracle / 38 test; fault corpus 33/33; shadow 34/34 cell | partial — live pilot chờ consent |
| H10 | Khép harness + handoff | `1253707`, `b219f57` | drill rollback 11/11; nghiệm thu vòng chạy 29/29 trên `c836822`; review cuối 2/10 | partial — pilot sống hoãn |
| H10.1/H10.2 | Calibration sống + phần giới hạn ngân sách | — | `financial_consent_ref = null`, `measured = false` | tương lai (#6531) |
| H11 | Quản lý con (#6545–#6548) | `84022bf`, `9a04c16`, `2bd3886`, `0e9b6df`, `f7ebbc9` | 37 ca H11; nhóm 18 file 271 passed; live 5/5 kịch bản 37/37 phép kiểm; chạy toàn bộ unit suite bắt một hồi quy của H11 (phần nới hạn chót lượt plan hết chỗ vì mặc định 7200 s đã chạm trần) — đã sửa kèm hai bài chốt lại hợp đồng | verified |
| H12 | Khóa tổng `BOXFOX_REFORM` + khối `switches` trong `runtime-info` | commit H12 | 19 ca mới (`test_reform_master_switch.py`) | verified |
| Vá #6535 | Phòng kế hoạch: kẹp `.plans`, thư mục con, schema `directory` | `79f024b`, `17b146b`, `ad3b5f8` | unit + live `folders2/3/4` | verified |

Ngoài ra: origin knobs (`82550cc`, `f7e4a9b`), phủ kiểm và soát tuân thủ (`c6c88bb`, `fcc6819`,
`b37dafb`), docs refresh (`1253707`, `b219f57`, `c9a775c`), E2E thật nhiều vòng
(`/code/.generated_artifacts/e2e/runs/`).

## 4. Kiến trúc đường mới

### 4.1 Module (tất cả nằm trong `backend/src/agentbox/agent_core/`)

| Lớp | Module | Vai trò |
|---|---|---|
| Hợp đồng | `orchestration_contracts.py` | validate/định danh chung; mọi lớp dưới nói cùng một từ vựng lỗi |
| Kernel | `execution_kernel.py` | một cửa admission: policy của run, mode `adaptive`/`legacy`, quyết định trước khi gọi model hay spawn con |
| Kho việc | `task_service.py`, `task_surface.py` | `harness_tasks` / `harness_task_attempts` / `harness_task_messages`; bốn công cụ `task_*` |
| Job nền | `harness_jobs.py`, `job_surface.py`, `job_wake.py` | job qua nhiều lượt; wake bằng sự kiện, không mở turn rỗng |
| Context/skill | `context_bundle.py`, `skill_spec.py`, `context_surface.py` | ref canonical, pin `(skill, attempt)`, epoch |
| Sổ usage | `usage_ledger.py`, `usage_surface.py` | reserve → settle → release; giá phải có nguồn, giá lạ là `None` chứ không phải 0 |
| Research | `research_owner.py`, `research_gateway.py`, `research_runtime.py` | chủ quyền kết luận thuộc Research; main chỉ gửi câu hỏi/đọc kết quả published |
| Main thích ứng | `adaptive_main.py`, `adaptive_surface.py`, `recovery_policy.py` | quyết định theo tiến triển; phân loại hồi phục theo lớp lỗi |
| Vòng đời con (H11) | `child_lifecycle.py`, `peer_watchdog.py`, `roles.py` | cờ `timedOut`/`partial`/`resumable`; watchdog; vai nào thấy công cụ nào |
| Công tắc | `feature_switches.py` | khóa tổng `BOXFOX_REFORM` + bảy thành viên; một chỗ đọc duy nhất |

### 4.2 Bảng dữ liệu mới (additive — không đổi bảng cũ)

`harness_tasks`, `harness_task_attempts`, `harness_task_messages`, `harness_invocations`,
`harness_jobs*`, `harness_context_*`, `harness_skills*`, `harness_usage`, `harness_allocations`,
`harness_adaptive_state`, `harness_research_gateway`. Khoá duy nhất `harness_task_active` /
`harness_session_active` chỉ áp khi trạng thái `running`/`waiting_input`, nên một attempt phải đóng
trước khi attempt mới mở. `SessionStore` không dùng `PRAGMA user_version`; drill xác nhận
`user_version` giữ nguyên sau khi bật/tắt công tắc.

### 4.3 Một lượt đi qua đâu

```
main turn → execution_kernel.admission (policy của run)
          → model (usage_surface ghi sổ nếu công tắc usage bật)
          → tool call:
               task_*        → task_surface → task_service → SQLite
               start_job/... → job_surface  → harness_jobs → job_wake ở lượt sau
               delegate_task → con (child_start ghi sổ) → peer_watchdog
               peer_read / await_children / child_resume → đọc trạng thái con
          → kết thúc lượt: finish payload mang cờ kết cục + số usage
```

## 5. Các công tắc — bảng đầy đủ

**Nguyên tắc:** mặc định TẮT hết. Tắt thì hành vi y như trước đợt cải tổ; dữ liệu `harness_*` đã ghi
vẫn đọc được, không mutation nào replay.

| Công tắc | Nhóm | Tắt thì | Bật thì | Test ghim |
|---|---|---|---|---|
| `BOXFOX_REFORM` | **khóa tổng** | mọi thành viên theo giá trị riêng/mặc định (TẮT) | bật cả bảy thành viên bằng một lệnh | `test_reform_master_switch.py` (19 ca) |
| `BOXFOX_TASK_SURFACE` | H3 | bốn công cụ `task_*` không được quảng cáo; `dispatch` từ chối `TASK_SURFACE_OFF` | model thấy `task_list`/`task_get`/`task_send`/`task_abandon` | `test_harness_task_service.py`, `test_tool_groups`, E2E `task-fix` |
| `BOXFOX_CONTROLLER_JOBS` | H4 | công cụ controller không mở; `job_surface`/`job_wake` không chạy | model thấy `start_job`/`get_job`/`subscribe_job`/`wait_jobs`/`cancel_job` | `test_harness_jobs*`, P2 10/10 |
| `BOXFOX_CONTEXT_SURFACE` | H5 | ref/`skill_view` đi đường cũ | context bundle + pin skill chạy qua surface | `test_context_surface.py`, P3 13/13 |
| `BOXFOX_USAGE_LEDGER` | H6 | không reserve/settle qua surface mới; hàng usage đã ghi còn nguyên | mỗi request ghi một hàng usage; trần chi (khi có allocation) có hiệu lực | `test_usage_ledger.py` (50 ca), `test_usage_surface.py` (19 ca) |
| `BOXFOX_RESEARCH_GATEWAY` | H7 | công cụ gateway ẩn; main giữ đường uỷ thác cũ | `research_job_*` mở; kết luận thuộc Research | `test_research_gateway*`, P5 8/8 |
| `BOXFOX_ADAPTIVE_HARNESS` | H8 | `guard_tool` giữ đường cũ (`work_scope.check_tool`) | owner-check mới + `adaptive_surface`; mode `adaptive` mới bật được (đòi thêm `BOXFOX_USAGE_LEDGER`) | `test_adaptive_main.py`, `test_adaptive_surface.py`, P6 14/14 |
| `BOXFOX_RECOVERY_POLICY` | H8 | phân loại hồi phục giữ đường cũ | phân loại theo lớp lỗi + quyết định retry/giữ | `test_recovery_policy*`, `test_decision_flow` |
| `BOXFOX_PEER_MESH` | có từ trước | **không** thuộc khóa tổng: mặc định BẬT; đặt `off` thì bỏ `peer_read`/`await_children`/`child_resume` và uỷ thác về đường cũ | mesh uỷ thác đầy đủ (H11 nằm trong này) | `test_peer_cost.py`, `test_child_management_h11.py` |

**Giá trị nhận của công tắc:** `on` / `1` / `true` / `yes` (không phân biệt hoa thường) là BẬT; mọi
giá trị khác — kể cả chuỗi chỉ có khoảng trắng — là TẮT. Trước H12, năm module chỉ nhận đúng `on`,
nên nay chúng nhận rộng hơn cho khớp khóa tổng; muốn giữ y hành vi cũ thì chỉ đặt `on`.

Kiểm tra đang bật gì, vì đâu: `GET /api/agent/runtime-info` → khối `switches` (khóa tổng + từng
thành viên kèm `source`: `explicit` / `master` / `default`). Không cần đọc env của tiến trình nữa.

## 6. Bật dần từng công tắc — quy trình và thứ tự

### 6.1 Khuôn chung cho MỘT công tắc (đừng bật hai cái cùng lúc)

1. **Chạy bộ test của checkpoint khi công tắc TẮT** — phải xanh (đây là bằng chứng "tắt thì như cũ").
2. **Chạy bộ test của checkpoint khi công tắc BẬT** — phải xanh; đây là phép kiểm âm/dương.
3. **Khởi động backend có công tắc** (`BOXFOX_<TÊN>=on`, giữ nguyên các env khác) và đọc
   `/api/agent/runtime-info`: thành viên đó phải hiện `on: true, source: "explicit"`.
4. **Chạy một vòng live** bằng driver tương ứng (mục 6.2). Vòng live phải đạt cùng mức như vòng
   TẮT trước đó; nếu thấp hơn thì lùi ngay.
5. **Ghi bằng chứng** vào `docs/plan/reform-status.md` (bảng công tắc) và, nếu cần, một tệp
   `docs/plan/reform-execution/H<n>/evidence.md` bổ sung: commit, env, lệnh, kết quả.
6. **Rollback = bỏ env rồi khởi động lại.** Không cần đổi code, không cần migration; dữ liệu
   `harness_*` đã ghi vẫn đọc được ở cả hai chiều.

Ghi chú vận hành: env đọc lúc gọi, nhưng tiến trình đang chạy không tự thấy env mới — **phải khởi
động lại backend** sau khi đổi env. `BOXFOX_PEER_MESH` (đang BẬT) giữ nguyên trong mọi bước; chỉ
đặt `off` khi điều tra sự cố mesh.

### 6.2 Thứ tự đề xuất (từ ít rủi ro đến nhiều rủi ro)

Nhật ký chạy thật (ngày, lệnh, bằng chứng, trạng thái từng bước): [`enablement-log.md`](enablement-log.md). Cột **Đã chạy** dưới đây chỉ ghi bước nào đã qua đủ 5 bước.

| Bước | Công tắc | Vì sao ở vị trí này | Test phải xanh | Vòng live | Đã chạy |
|---|---|---|---|---|---|
| 1 | `BOXFOX_RECOVERY_POLICY` | Chỉ đổi cách phân loại lỗi; không mở công cụ mới, không ghi sổ | `test_recovery_policy.py`, `test_decision_flow.py` | `driver.py` (kịch bản lỗi/hồi phục) | ✅ 2026-10-05 |
| 2 | `BOXFOX_CONTEXT_SURFACE` | Đổi đường ref/skill; chưa mở công cụ | `test_context_surface.py` | `driver.py` (context/skill) | ✅ 2026-10-05 |
| 3 | `BOXFOX_TASK_SURFACE` | Mở bốn công cụ task cho model; đã E2E 9/9 nhưng là bề mặt thấy được | `test_harness_task_service.py`, `test_task_surface.py`, `test_runtime_info.py` | `driver_task.py` | ✅ 2026-10-05 |
| 4 | `BOXFOX_CONTROLLER_JOBS` | Job nền nhiều lượt; cần bước 3 xong để hàng việc nhất quán | `test_harness_jobs.py`, `test_job_surface.py`, `test_job_wake.py` | `driver_job.py` | ✅ 2026-10-05 |
| 5 | `BOXFOX_USAGE_LEDGER` | Bắt đầu ghi sổ chi; chưa siết gì khi chưa có allocation | `test_usage_ledger.py`, `test_usage_surface.py`, `test_peer_cost.py` | `driver.py` (`delegate` + `ledger_rows`, `--db` của instance bật dần) | ✅ 2026-10-05 |
| 6 | `BOXFOX_ADAPTIVE_HARNESS` | Đổi owner-check + mở mode `adaptive`; **cần bước 5** vì mode adaptive đòi sổ usage | `test_adaptive_main.py`, `test_adaptive_surface.py` | `driver.py` (`--switches on`, kịch bản `adaptive_on`) + `driver_child_caps.py` (`peer_read_cap`) | ✅ 2026-10-05 |
| 7 | `BOXFOX_RESEARCH_GATEWAY` | Chạm chủ quyền Research — chủ nhà chốt bật ở #6597 | `test_research_gateway.py`, `test_research_gate_runtime.py`, `test_research_owner.py`, `test_research_switches.py` | `driver.py` (`research`, `research_gateway`, `research_main_tools`) | ✅ 2026-10-05 |
| 8 | `BOXFOX_REFORM=on` | Khi cả bảy đã xanh riêng lẻ: một lệnh chạy cả cụm | toàn bộ nhóm trên | cả bốn driver | ✅ 2026-10-05 |

Sau bước 8 mới tính chuyện xoá nhánh legacy; **chưa xoá gì trong đợt này** — đó là việc của một
checkpoint riêng, phải có bằng chứng chạy thật dài ngày.

### 6.3 Cách kiểm từng bước bằng dữ liệu

- `GET /api/agent/runtime-info` → `switches` + `limits` + `toolGroups`: biết chắc đang bật gì.
- SQLite (`sessions.db`, bảng `events`): mỗi lượt kết bằng một hàng `finish` mang cờ kết cục; job/
  task/con đều có hàng trong `harness_*` để đối chiếu với UI.
- Driver live in ra `summary.json` theo từng vòng; giữ cả vòng TẮT và vòng BẬT để so cặp.

## 7. Đầu việc còn lại (không nằm trong H12)

| Việc | Trạng thái | Chờ gì |
|---|---|---|
| H9/H10.1 calibration sống (đo chi thật, đo chất lượng) | hoãn #6531 | consent tài chính riêng của chủ nhà; `financial_consent_ref` còn `null` |
| H10.2 giới hạn ngân sách cứng theo allocation | hoãn #6531 | cùng consent trên |
| H7 gateway Research bật mặc định | hoãn #6536 | quyết định chủ nhà về chủ quyền Research |
| Bật dần bảy công tắc | **chưa bắt đầu** | theo mục 6; mỗi bước cần một vòng chạy thật |
| Xoá nhánh legacy (khi mọi công tắc đã bật ổn định) | chưa mở | checkpoint riêng + bằng chứng dài ngày |
| `attemptSeq` của H3 giới hạn theo phiên (H3.11) | ghi nhận | thiết kế sau nếu cần nhiều phiên |
| Tab Plan hiện tệp kế hoạch trong UI | chờ | UI; hiện chỉ đọc qua API |
| `harnessAllocationId` trong `runtime-info` | chờ | mở khi làm H10.2 |
| Ngân sách/thời gian của chính main (không chỉ con) | chưa mở | cùng họ #6546 |

## 8. Bằng chứng và artifact

| Thứ | Đường dẫn |
|---|---|
| Vòng E2E thật (mọi nhãn) | `/code/.generated_artifacts/e2e/runs/` (`v1/`, `v1-fix/`, `off/`, `folders*/`, `task-fix/`, `child/`, `h11-*/`) |
| Driver live | `/code/.generated_artifacts/e2e/driver.py`, `driver_task.py`, `driver_folder.py`, `driver_child.py`, `driver_child_caps.py` |
| Probe H3–H8, drill rollback, H9 shadow | `/code/.generated_artifacts/h3h8/` |
| UI thật qua preview | `/code/.generated_artifacts/images/boxfox-e2e-ui-*.png`, `/code/.generated_artifacts/recordings/boxfox-e2e-ui-flow.webm` |
| Ảnh gốc chủ nhà (động cơ H11) | `/code/.uploaded_artifacts/3287.png` |
| Báo cáo kiểm thử (một bản duy nhất) | Test Report "H1–H2 — hợp đồng task, kernel admission và kho task bền vững (PR #3)" |

## 9. Rollback tổng (khi cần dừng cả đợt)

1. Bỏ `BOXFOX_REFORM` và bảy env thành viên; giữ `BOXFOX_PEER_MESH` nguyên trạng.
2. Khởi động lại backend; đọc `/api/agent/runtime-info` xác nhận mọi thành viên `on: false`.
3. Không xoá bảng `harness_*`, không sửa `sessions.db`; hàng đã ghi vô hại với đường cũ.
4. Drill đã chạy: `/code/.generated_artifacts/h3h8/drill/rollback_drill_962cd84.log` — 11/11 PASS
   (không mất data/approval, không replay mutation, `user_version` giữ nguyên).
5. Nếu chỉ một công tắc gây sự cố: chỉ bỏ env của công tắc đó (các bước ở mục 6 vốn đã tách rời).
