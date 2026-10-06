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
| Pull request | https://github.com/i3abyxinhdepqua-lang/BoxFox-Agent-Box/pull/3 (nhánh `vorflux/boxfox-harness-reform`, base `main` — đổi từ `vorflux/w10-w12-completion` theo quyết định #6598; xem mục phát hành ở nhật ký bật dần) |
| Kế hoạch v2 đã duyệt (Plan panel, 2026-10-05) | `/code/.plans/v2-boxfox-harness-reform.md` (tóm tắt: `/code/.plans/v2-boxfox-harness-reform-summary.md`) |
| Sổ quyết định đầy đủ | `/code/.plans/reform-decision-ledger.md` |
| Pull request v2 (ĐANG MỞ, base `main` = `c6fd6e9`) | https://github.com/i3abyxinhdepqua-lang/BoxFox-Agent-Box/pull/4 (nhánh `vorflux/boxfox-reform-v2-default-on`; PR #3 đã merge ở `c6fd6e9`) |
| **Nhánh legacy: hồ sơ xoá/giữ** + **nhật ký v2 đầy đủ (đã làm / chưa làm / vướng mắc)** | **§10 và §11 của chính file này** (kèm sổ quyết định rút gọn ở §12) |

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
| H12 | Khóa tổng `BOXFOX_REFORM` + khối `switches` trong `runtime-info` | commit H12 | 19 ca mới (`test_reform_master_switch.py`) | **đã xoá ở v4** (B5, `0404356`) |
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

**Trạng thái v4 (2026-10-06): NHÓM NÀY ĐÃ XOÁ HẲN.** Chủ nhà chốt xoá nốt bề mặt 7 rồi xoá hẳn khóa
tổng (§10.7). Không còn env nào của đợt cải tổ, và `GET /api/agent/runtime-info` không còn khối
`switches`. Bảng dưới là HỒ SƠ LỊCH SỬ của đợt bật dần — giữ để tra cứu cách tổ chức và cách kiểm
từng công tắc; đọc "đã xoá — `<commit>`" là commit xoá bề mặt đó.

**Nguyên tắc (v2, #6599):** mặc định **BẬT** — env trống nghĩa là cả nhóm chạy đường mới. Tắt là
hành động TƯỜNG MINH: một lệnh `BOXFOX_REFORM=off` (cả nhóm) hoặc `BOXFOX_<TÊN>=off` (một bề mặt),
rồi khởi động lại. Tắt thì hành vi y như trước đợt cải tổ; dữ liệu `harness_*` đã ghi vẫn đọc được,
không mutation nào replay. Công tắc được GIỮ làm lối thoát hiểm đã tổ chức — xem §6.4.

**Đợt xoá dần (v3, 2026-10-05):** chủ nhà chốt lựa chọn **B** của §10.2 và yêu cầu "xoá dần dần để
công tắc mặc định là bật". Sáu bề mặt H3–H6/H8 đã **xoá hẳn nhánh cũ** theo từng commit — B1 (bỏ pin
test), B2 (bỏ nhánh code `off`), B3 (bỏ tên env khỏi `feature_switches.MEMBERS`) làm CHUNG trong một
commit cho mỗi bề mặt, vì ba việc đó chỉ có nghĩa khi đi cùng nhau. Bề mặt 7 (RESEARCH_GATEWAY)
**chưa xoá** — lý do đo được ở §10.6. Bảng dưới là trạng thái THẬT của mã hôm nay:

| Công tắc | Nhóm | Trạng thái | Ghi chú |
|---|---|---|---|
| `BOXFOX_REFORM` | **khóa tổng** | **đã xoá** — `0404356` (B5) | xoá cùng `feature_switches.py` và khối `switches`; không còn lối thoát hiểm một lệnh (không còn nhánh legacy nào để thoát) |
| `BOXFOX_RESEARCH_GATEWAY` | H7 | **đã xoá** — `6c8fe6b` | công cụ gateway luôn mở cho main; main không còn đường uỷ thác `research` (`RESEARCH_MAIN_READ_ONLY`) — xem §10.7 |
| `BOXFOX_TASK_SURFACE` | H3 | **đã xoá** — `64f960d` | bốn công cụ `task_*` luôn mở; không còn `TASK_SURFACE_OFF` |
| `BOXFOX_CONTROLLER_JOBS` | H4 | **đã xoá** — `64f960d` | `start_job`/`get_job`/`subscribe_job`/`wait_jobs`/`cancel_job` luôn mở; `job_surface`/`job_wake` luôn sống |
| `BOXFOX_CONTEXT_SURFACE` | H5 | **đã xoá** — `42b337a` | context bundle + pin skill luôn chạy qua surface; `_active()` đã xoá |
| `BOXFOX_USAGE_LEDGER` | H6 | **đã xoá** — `64f960d` | mỗi request ghi một hàng usage; không còn `USAGE_LEDGER_DISABLED` |
| `BOXFOX_ADAPTIVE_HARNESS` | H8 | **đã xoá** — `f2fceb0` | mode `adaptive` chỉ cần một lệnh ghim policy; không còn công tắc riêng (`ADAPTIVE_DISABLED`/`POLICY_SWITCH_OFF` đã xoá) |
| `BOXFOX_RECOVERY_POLICY` | H8 | **đã xoá** — `4a4bdac` | phân loại theo lớp lỗi luôn sống; hai cổng trong `runtime.py` thành vô điều kiện |
| `BOXFOX_PEER_MESH` | có từ trước | còn — **không** thuộc khóa tổng | mặc định BẬT; đặt `off` thì bỏ `peer_read`/`await_children`/`child_resume` và uỷ thác về đường cũ |

**Giá trị nhận của công tắc:** `on` / `1` / `true` / `yes` (không phân biệt hoa thường) là BẬT; mọi
giá trị khác — kể cả chuỗi chỉ có khoảng trắng — là TẮT. Trước H12, năm module chỉ nhận đúng `on`,
nên nay chúng nhận rộng hơn cho khớp khóa tổng; muốn giữ y hành vi cũ thì chỉ đặt `on`.

Kiểm tra đang bật gì, vì đâu (hồ sơ): `GET /api/agent/runtime-info` từng trả khối `switches` (khóa
tổng + từng thành viên kèm `source`: `explicit` / `master` / `default`). Khối đó đã bị xoá ở B5 cùng
khóa tổng (`0404356`); env của tiến trình nay không còn công tắc nào của đợt cải tổ.

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
6. **Rollback = đặt `BOXFOX_\<TÊN\>=off` rồi khởi động lại.** Từ v2 (#6599) **bỏ env KHÔNG còn là
   rollback**: env trống nghĩa là BẬT, nên phải khai tường minh `off`. Không cần đổi code, không
   cần migration; dữ liệu `harness_*` đã ghi vẫn đọc được ở cả hai chiều.

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

**Từ v2 (#6599) bảng này là NHẬT KÝ LỊCH SỬ, không phải việc phải làm:** không cần bật env nào nữa —
env trống đã là BẬT. Giữ bảng để tra cứu cách tổ chức (thứ tự nào an toàn, mỗi bước kiểm bằng gì,
vòng live nào đã đạt) khi cần tắt riêng một bề mặt để điều tra, hoặc khi một agent sau muốn quyết
định xoá hay giữ nhánh legacy.

### 6.3 Cách kiểm từng bước bằng dữ liệu

- `GET /api/agent/runtime-info` → `switches` + `limits` + `toolGroups`: biết chắc đang bật gì.
- SQLite (`sessions.db`, bảng `events`): mỗi lượt kết bằng một hàng `finish` mang cờ kết cục; job/
  task/con đều có hàng trong `harness_*` để đối chiếu với UI.
- Driver live in ra `summary.json` theo từng vòng; giữ cả vòng TẮT và vòng BẬT để so cặp.

### 6.4 Vì sao GIỮ công tắc + quyết định tương lai (v2, #6599)

Chủ nhà chốt 2026-10-05 (#6599): **bật mặc định, GIỮ công tắc và giữ nhánh legacy**; ghi cả cách tổ
chức lẫn quyết định tương lai vào handoff này. Lý do (ý chủ nhà): công tắc là cách để một agent sau
hiểu đợt này đã được tổ chức thế nào — tắt riêng một bề mặt để điều tra, và so cặp TẮT/BẬT khi
nghi ngờ. Việc xoá legacy thuộc một checkpoint sau, phải có bằng chứng chạy thật dài ngày.

Ba tầng của cùng một lối thoát hiểm, từ rộng đến hẹp:

| Tầng | Lệnh / cách | Tác dụng | Ghi chú |
|---|---|---|---|
| Cả nhóm | `BOXFOX_REFORM=off` | Tắt cả bảy thành viên bằng MỘT env, restart backend | Lối thoát hiểm một lệnh; env tường minh của thành viên vẫn thắng khóa tổng |
| Một bề mặt | `BOXFOX_<TÊN>=off` | Tắt đúng một thành viên, các thành viên khác giữ mặc định | Dùng khi điều tra một bề mặt |
| Trong test | `@pytest.mark.legacy_path` | Pin cả `BOXFOX_REFORM=off` LẪN bảy thành viên `off` cho cả tệp test chốt đường TRƯỚC v2 | `backend/tests/unit/conftest.py`; phải pin cả thành viên vì env thành viên tường minh thắng khóa tổng (shell đang có `BOXFOX_X=on` sẽ lọt vào "đường cũ"). Tệp KHÔNG khai báo chạy đúng mặc định mới (BẬT) |

Điều KHÔNG được làm ở v2: không xoá nhánh legacy, không xoá công tắc, không đổi tên env, không hạ
mặc định của bất kỳ thành viên nào. Điều kiện để một checkpoint sau xoá: (1) đủ bằng chứng chạy thật
dài ngày trên mặc định BẬT; (2) không còn tệp test nào cần `legacy_path`; (3) chủ nhà chốt.


### 6.5 Hệ quả ĐÃ CHỐT của mặc định BẬT: spawn research của Work Graph (v2)

Hậu kiểm v2 soi đúng chỗ này: `research_gateway.guard_delegate` chạy TRƯỚC nhánh `work=` của
`runtime.delegate`, nên khi gateway BẬT (mặc định v2) **chính engine Work Graph cũng không spawn
được producer `research`/`research-review`**: mọi lượt như vậy dừng với `RESEARCH_MAIN_READ_ONLY`,
node của run đóng `failed` (44 bài test cũ đỏ nếu bỏ pin `legacy_path`; chỉ cần
`BOXFOX_RESEARCH_GATEWAY=off` là 94/94 xanh lại).

Đây là **hệ quả có chủ đích, không phải lỗi sản phẩm**: H7.1/P5 chốt "intent của main là đầu vào,
không bao giờ canonical" và main không điều khiển worker Research nội bộ — luồng `research` của
Work Graph là đường legacy thay thế bằng biên Research độc lập (`research_job_submit` →
`research_job_get|control|result`). Hai lối thoát hiểm giữ nguyên:

- `BOXFOX_RESEARCH_GATEWAY=off` — trả lại hành vi trước v2 cho luồng này;
- phiên main còn binding research legacy (`researchId` trong `research_config`) — đường cũ vẫn chạy.

Đã khoá bằng test mặc định: `tests/unit/test_research_gateway.py::test_engine_work_spawns_cannot_bypass_the_gateway_either`.
Điều KHÔNG làm ở v2: miễn `work=` khỏi gateway (đó sẽ là cửa sau cho main tự spawn research) hoặc
viết lại luồng `research` của Work Graph đi qua envelope (việc của checkpoint sau, nếu chủ nhà muốn).


## 7. Đầu việc còn lại (không nằm trong H12)

| Việc | Trạng thái | Chờ gì |
|---|---|---|
| H9/H10.1 calibration sống (đo chi thật, đo chất lượng) | hoãn #6531 | consent tài chính riêng của chủ nhà; `financial_consent_ref` còn `null` |
| H10.2 giới hạn ngân sách cứng theo allocation | ✅ writer + kiểm chứng mock xong ở v2 (`PUT|GET|DELETE /api/agent/sessions/{sid}/usage-allocation`); H10.1 (đo chi thật) vẫn hoãn | chỉ còn consent tài chính cho H10.1 |
| H7 gateway Research bật mặc định | ✅ bật mặc định từ v2 (#6599) — spawn research của Work Graph dừng với `RESEARCH_MAIN_READ_ONLY`, xem §6.5 | không còn phải bật env; quyết định chủ quyền Research đã chốt ở #6599 |
| Bật dần bảy công tắc | ✅ xong 2026-10-05 (đủ tám bước) | không còn phải bật env: v2 đổi mặc định sang BẬT (#6599) |
| Xoá nhánh legacy (khi mọi công tắc đã bật ổn định) | chưa mở — v2 cố ý giữ, xem §6.4 | checkpoint riêng + bằng chứng dài ngày + chủ nhà chốt |
| `attemptSeq` của H3 giới hạn theo phiên (H3.11) | ghi nhận | thiết kế sau nếu cần nhiều phiên |
| Tab Plan hiện tệp kế hoạch trong UI | chờ | UI; hiện chỉ đọc qua API |
| `harnessAllocationId` trong `runtime-info` | ✅ xong ở v2 — khối `usage.allocations` (trần 20 hàng, chỉ đọc) | không |
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

1. Đặt `BOXFOX_REFORM=off` (một lệnh, áp cho cả bảy thành viên); giữ `BOXFOX_PEER_MESH` nguyên
   trạng. Từ v2, **bỏ env không còn là rollback** — env trống nghĩa là BẬT.
2. Khởi động lại backend; đọc `/api/agent/runtime-info` xác nhận mọi thành viên `on: false`.
3. Không xoá bảng `harness_*`, không sửa `sessions.db`; hàng đã ghi vô hại với đường cũ.
4. Drill đã chạy: `/code/.generated_artifacts/h3h8/drill/rollback_drill_962cd84.log` — 11/11 PASS
   (không mất data/approval, không replay mutation, `user_version` giữ nguyên).
5. Nếu chỉ một công tắc gây sự cố: **đặt tường minh `BOXFOX_<TÊN>=off`** cho công tắc đó rồi khởi
   động lại (các bước ở mục 6 vốn đã tách rời). Từ v2, bỏ env của công tắc đó là BẬT nó — không
   phải rollback.

## 10. Nhánh legacy — hồ sơ để chốt "xoá hay giữ" (v2; v3 đã xoá 6/7 bề mặt — xem §10.6)

> Chủ nhà hỏi 2026-10-05: *"phần nhánh legacy để xoá hay tất cả các phần?"*. Mục này là HỒ SƠ để chốt,
> **không phải quyết định**: v2 cố ý chưa xoá gì (§6.4). Đọc §10.1 để biết "legacy" gồm đúng những
> phần nào, §10.2 để chọn giữa ba lựa chọn, §10.3 để biết thứ tự an toàn nếu chọn xoá từng phần.

### 10.1 "Legacy" gồm đúng những phần nào

| # | Phần | Nằm ở đâu | Xoá phần này nghĩa là | Xoá thì mất gì |
|---|---|---|---|---|
| 1 | **Nhóm 8 env công tắc** (khóa tổng `BOXFOX_REFORM` + 7 thành viên) | `backend/src/agentbox/agent_core/feature_switches.py` (một chỗ đọc duy nhất) | bỏ hẳn tên env + hàm `master()`/`member_switch()`; `runtime-info` không còn khối `switches` (hoặc chỉ còn khối rỗng) | lối thoát hiểm MỘT LỆNH khi mặc định mới có sự cố; khả năng so cặp TẮT/BẬT |
| 2 | **Bảy nhánh code sau công tắc** | mỗi bề mặt một hàm `..._enabled()`: `task_surface.py:63`, `context_surface.py:30`, `job_surface.py:28` + `tool_contracts.py:23/30`, `usage_ledger.py:106`, `research_gateway.py:33`, `recovery_policy.py:183`, `execution_kernel.py:24` | xoá nhánh `if not enabled(): <đường cũ>` trong từng module — mỗi bề mặt một commit riêng | đường cũ của riêng bề mặt đó; không thể tắt riêng một bề mặt để điều tra |
| 3 | **35 tệp test ghim `legacy_path`** + fixture pin 8 env | `backend/tests/unit/conftest.py` + 35 tệp (danh sách đỏ trước khi gắn: `/var/tmp/v2-failing-files.txt`) | bỏ marker khỏi từng tệp khi bề mặt tương ứng đã ổn định; tệp quay về khẳng định mặc định BẬT | bằng chứng "tắt thì y như cũ" cho bề mặt đó |
| 4 | **Binding research legacy (`researchId`)** | `research_gateway.py:448,554` + `research_runtime.research_config` | bỏ nhánh cho phiên main CŨ còn `researchId` trong config | phiên cũ (tạo trước đợt cải tổ) mất đường research; phải chuyển hết sang `research_job_*` trước |
| 5 | **Luồng `research` của Work Graph** (nhánh `work=`) | `work_graph.py:1274` → `runtime.delegate` → gateway chặn | xoá producer `research`/`research-review` của Work Graph | luồng legacy đó (đã bị gateway chặn ở mặc định v2 — §6.5); muốn có lại phải viết qua envelope Research độc lập |
| 6 | **Công tắc NGOÀI nhóm**: `BOXFOX_PEER_MESH`, `BOXFOX_WORK_GRAPH` | `limits.peer_mesh_enabled`, `work_graph.py:102` | **không thuộc quyết định này** — có từ trước đợt cải tổ, mặc định BẬT, không phải "nhánh legacy của đợt" | — (giữ nguyên) |
| 7 | **Bảng dữ liệu `harness_*`** | `sessions.db` (additive, §4.2) | **KHÔNG xoá ở bất kỳ lựa chọn nào** — dữ liệu đã ghi đọc được ở CẢ HAI chiều; muốn dọn thì là migration riêng, cần kế hoạch riêng | — (giữ nguyên) |
| 8 | **Nhánh git + worktree của đợt** | xem §10.5 | xoá nhánh/worktree đã merge hết vào `origin/main` | không mất commit nào (đã nằm trong `origin/main`) |

### 10.2 Ba lựa chọn

**A. Giữ tất cả (hiện trạng v2).** Chi phí: 8 env + 35 tệp pin + nhánh `if enabled()` ở 7 bề mặt. Lợi:
lối thoát hiểm một lệnh, tắt riêng một bề mặt khi điều tra, so cặp TẮT/BẬT khi nghi ngờ. Phù hợp khi
mặc định BẬT còn mới.

**B. Xoá TỪNG PHẦN theo bề mặt (khuyến nghị kỹ thuật — chủ nhà chốt).** Mỗi bước nhỏ, rollback
bằng `git revert` một commit; không "big bang". Thứ tự ở §10.3. Điểm mấu chốt: xoá bề mặt nào thì xoá
CẢ BA thứ của bề mặt đó (test pin → nhánh code → tên env), không để trạng thái nửa vời.

**C. Xoá TẤT CẢ một lần.** Chỉ nên làm khi: (1) đã có bằng chứng chạy thật DÀI NGÀY trên mặc định BẬT;
(2) không còn tệp test nào cần `legacy_path`; (3) chủ nhà chốt. Rủi ro: mất lối thoát hiểm duy nhất nếu
mặc định mới có sự cố muộn.

Điều kiện tiên quyết và điều KHÔNG được làm: giữ nguyên như §6.4 (không xoá nhánh legacy, không xoá
công tắc, không đổi tên env, không hạ mặc định của thành viên nào khi chưa có checkpoint riêng).

### 10.3 Thứ tự an toàn nếu chọn B (mỗi dòng là một checkpoint nhỏ)

**Trạng thái 2026-10-06 (v4):** B1–B5 đã xong — bảy bề mặt và cả khóa tổng đã xoá hẳn (§10.6, §10.7);
B6 (dọn hạ tầng) xong phần còn lại trên máy này (§10.5). Bảng dưới giữ nguyên như hồ sơ thứ tự đã đi.

| Bước | Việc | Điều kiện để bắt đầu | Cách kiểm sau khi làm |
|---|---|---|---|
| B1 | Bỏ pin `legacy_path` ở nhóm tệp của MỘT bề mặt | bề mặt đó chạy ổn định dài ngày trên mặc định BẬT; không còn sự cố mở | chạy nhóm tệp đó ở mặc định BẬT (không env) phải xanh; chạy lại với `BOXFOX_<TÊN>=off` để chắc đường cũ vẫn còn code |
| B2 | Xoá nhánh code cũ của bề mặt đó (bỏ hàm `..._enabled()` + mọi `if not enabled()`) | B1 xong, không còn tệp pin cho bề mặt này | toàn bộ test của bề mặt xanh ở mặc định BẬT; `runtime-info` vẫn trả khối `switches` (chưa xoá env) |
| B3 | Bỏ tên env của bề mặt khỏi `feature_switches.py` + bỏ dòng trong bảng §5 | B2 xong | `runtime-info` không còn thành viên đó; không còn ai đọc env cũ (`rg BOXFOX_<TÊN>`) |
| B4 | Lặp B1–B3 cho 7 bề mặt | — | — |
| B5 | Xoá khóa tổng + khối `switches` (hoặc để khối rỗng cho UI) | B4 xong; không còn tệp pin nào; chủ nhà chốt | `runtime-info` không lỗi; UI không đỏ |
| B6 | Dọn hạ tầng (§10.5) | — | `git branch` không còn nhánh chết |

### 10.4 Việc chưa mở nhưng đã biết trước

- **Viết lại luồng `research` của Work Graph đi qua envelope Research độc lập** (nếu chủ nhà muốn có
  lại luồng đó). Hiện tại nó bị gateway chặn CÓ CHỦ ĐÍCH (§6.5); việc này thuộc checkpoint sau.
- **Chuyển hết phiên cũ khỏi `researchId`** trước khi xoá phần #4 (nếu chọn xoá) — nếu không, phiên cũ
  mất đường research giữa chừng.
- **Migration dọn `harness_*`** (nếu muốn) — việc riêng, không nằm trong đợt này.

### 10.5 Hạ tầng git/worktree của đợt — trạng thái dọn dẹp

| Thứ | Trạng thái | Xoá được? |
|---|---|---|
| `vorflux/boxfox-harness-reform` (PR #3, merge `c6fd6e9`) | 0 commit ngoài `origin/main`; nhánh trên origin đã bị xoá sau merge | ✅ xoá local bất kỳ lúc nào |
| `vorflux/boxfox-harness-reform-docs`, `vorflux/boxfox-harness-reform-plan` | 0 commit ngoài `origin/main` (đã gộp hết) | ✅ xoá local |
| `vorflux/w10-w12-completion` | 0 commit ngoài `origin/main`; vẫn còn trên origin | ⚠️ xoá local được; nhánh origin để chủ nhà quyết |
| Worktree `/code/.worktrees/boxfox-harness-reform` | nhánh v2 (`vorflux/boxfox-reform-v2-default-on`, PR #4) | ❌ giữ tới khi PR #4 merge |
| Worktree `/code/.worktrees/boxfox-harness-reform-docs` (`78c5704`) | việc tài liệu đã xong | ✅ xoá được |
| Worktree `/code/.worktrees/boxfox-baseline-346da06` (detached `346da06`) | baseline đối chứng H0 | ⚠️ giữ nếu còn muốn so baseline; xoá được nếu không |
| `/tmp/wt-b9c0b25`, `/tmp/wt-parent` | worktree tạm | ✅ xoá được |
| `main` local (`ce71579`) | LÀ BẢN CŨ, sau `origin/main` 108 commit (là tổ tiên của `origin/main`) | ⚠️ `git fetch` rồi fast-forward, ĐỪNG dùng để so sánh |

**Tuyệt đối không xoá:** `origin/main` (`c6fd6e9`), nhánh v2 đang mở PR #4, và dữ liệu `harness_*`
trong `sessions.db`.


### 10.6 Xoá dần 6/7 bề mặt — việc đã làm, số đo phần còn lại (v3, 2026-10-05)

**Bối cảnh:** chủ nhà chốt lựa chọn B (§10.2) và yêu cầu "xoá dần dần để công tắc mặc định là bật".
Mỗi bề mặt MỘT commit, B1–B3 gộp làm một lượt (bỏ pin test + bỏ nhánh code `off` + bỏ tên env khỏi
`feature_switches.MEMBERS`) — ba việc đó chỉ có nghĩa khi đi cùng nhau, tách ra sẽ để lại trạng thái
nửa vời. Nhánh: `vorflux/boxfox-legacy-surface-removal`.

| Bề mặt | Commit | Quy mô | Kiểm chứng tại chỗ |
|---|---|---|---|
| RECOVERY_POLICY (H8) | `4a4bdac` | bỏ `SWITCH`/`enabled()`; hai cổng trong `runtime.py` thành vô điều kiện | 95 + 26 ca xanh |
| CONTEXT_SURFACE (H5) | `42b337a` | bỏ `SWITCH`/`enabled()`/`_active()`; bỏ guard ở `checkpoint`/`handoff_to`/`read_skill`/`mode_skill`; xoá 4 bài legacy-off | 93 ca xanh |
| TASK_SURFACE + CONTROLLER_JOBS + USAGE_LEDGER (H3/H4/H6) | `64f960d` | 25 tệp, +89/−381; bỏ ba công tắc, `visible_tools()`, `has_receipts()`, tham số `job_receipts`; `tool_groups` chuyển `alwaysOn: True` | 34 + 219 + 122 ca xanh |
| ADAPTIVE_HARNESS (H8) | `f2fceb0` | 14 tệp, +39/−166; bỏ `ADAPTIVE_SWITCH`/`enabled()`/`_switch()`, `ADAPTIVE_DISABLED`, `POLICY_SWITCH_OFF`; GIỮ mode `adaptive`/`legacy` (mode là dữ liệu, không phải công tắc) | 105 + 243 + 12 ca xanh |

`feature_switches.MEMBERS` nay chỉ còn `BOXFOX_RESEARCH_GATEWAY`; khối `switches` trong `runtime-info`
chỉ còn khóa tổng + một thành viên (khối biến mất ở B5).

**Vì sao bề mặt 7 chưa xoá — số đo, không phải phỏng đoán.** Chạy 35 tệp còn ghim `legacy_path` với pin
bị gỡ (plugin `strip_legacy_pin`, `PYTHONPATH=/var/tmp`):

| Cây | Kết quả | Log |
|---|---|---|
| trước đợt xoá (`f8f33b3`) | 232 failed / 416 passed / 7 errors (655 ca) | `/var/tmp/pin-strip-A.log` |
| sau 6 bề mặt (`f2fceb0`) | **231 failed / 405 passed / 7 errors** (643 ca) | `/var/tmp/wt-strip.log` |
| sau 6 bề mặt + `BOXFOX_RESEARCH_GATEWAY=off` | **0 failed — 643 passed** | `/var/tmp/wt-strip-gwoff.log` |

231 đỏ trải trên 33 tệp: 148 bài `work_*` (Work Graph), 49 bài thuộc sáu tệp research + 7 errors
`test_research_verify_source`, 27 bài delegation/peer/dossier, 1 bài session-length. Dòng đối chứng
cuối bảng cho thấy **toàn bộ** số đỏ còn lại thuộc bề mặt 7 — nên đây là bề mặt DUY NHẤT còn chặn việc
xoá nốt. Xoá nó cần hai việc không cơ học: (a) chuyển phiên cũ khỏi `researchId` (§10.1 #4);
(b) chốt luồng `research` của Work Graph (§10.4, §6.5) — quyết định chủ nhà; rồi (c) viết lại 35 tệp
test ghim theo hành vi mới. Vì vậy B4 dừng ở đây thay vì xoá nửa vời; B5–B6 cũng chờ theo.

### 10.7 Xoá nốt bề mặt 7 + khóa tổng (v4, 2026-10-06)

**Bối cảnh:** chủ nhà chốt bốn điểm (2026-10-06): (1) xoá nốt bề mặt 7 **theo biến thể b1** — bỏ công
tắc, nút `research` của Work Graph đóng `needs_user` kèm chỉ dẫn thay vì `failed`, sửa lời nhắc
`/research`, viết lại nhóm test ghim; (2) xoá hẳn khóa tổng SAU khi xoá xong bề mặt 7; (3) **không**
cần migration `researchId` (box này chỉ là môi trường thử, không có phiên sản xuất cần chuyển);
(4) chạy nốt 5 driver E2E còn thiếu.

| Bước | Commit | Quy mô | Kiểm chứng tại chỗ |
|---|---|---|---|
| Bề mặt 7/7 RESEARCH_GATEWAY (B1–B3) | `6c8fe6b` | 40 tệp, +565/−419: bỏ `SWITCH`/`enabled()`/`has_receipts()` + mọi cổng `RESEARCH_GATEWAY_OFF`; bỏ toàn bộ lối thoát legacy `researchId`; nút `research` của Work Graph → `needs_user` / `RESEARCH_NEEDS_MAIN`; `MEMBERS = ()`; viết lại 33 tệp test | 169 + 155 + 105 + 204 + 121 + 59 ca xanh |
| B5 — xoá hẳn khóa tổng | `0404356` | 41 tệp: xoá `feature_switches.py` + khối `switches` khỏi `runtime-info`; bỏ pin `legacy_path` ở `conftest.py`; xoá `test_reform_master_switch.py` (10 ca) + `switch_isolation.py`; sửa comment đầu 35 tệp | 16 + 24 + 169 ca xanh; collect 4372 ca, không tệp nào vỡ import |
| Bản sửa sau full suite | `762b159`, `a6a5881` | Feedback simplify/review (F1–F4); **9 bài đỏ còn sót** ở ba tệp KHÔNG mang nhãn `legacy_path` (`test_research_job_v2` 2, `test_research_phase_ledger` 2, `test_research_task_kinds` 5) — chúng tự khai `config['research']['researchId']` để main gọi `delegate_task role=research`, tức xanh nhờ đúng lối thoát đã xoá; nay dựng lead THẬT qua `research_intake.admit_lead` (`research_job_submit` → `resume`) | 21 + 8 + 12 ca xanh; nhóm research 196 ca xanh |

**Blast radius đã về 0.** Phép đo cũ (gỡ pin ở 35 tệp ghim) cho 231 đỏ trên 33 tệp; nay không còn pin
nào để gỡ — chính nhóm tệp đó chạy ở mặc định mới trong toàn bộ suite (số ở dòng dưới) và xanh.
**Toàn bộ unit suite trên head cuối `a6a5881`:** `3 failed, 4357 passed, 12 skipped` (20:33) — ba ca đỏ
là **baseline có sẵn** (`test_terminal_exec_echo`,
`test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`,
`test_revoked_grant_blocks_next_tool_call`), đã đối chứng trên `346da06`/`f6dbe2b`. Đợt suite đầu trên
`762b159` cho 12 đỏ: 3 ca baseline + đúng 9 ca nói trên, không ca nào khác.

**Việc còn lại của đợt (B6, §10.5):** các nhánh chết của đợt (`vorflux/boxfox-harness-reform`,
`-docs`, `-plan`, `vorflux/w10-w12-completion`) và các worktree tạm (`/code/.worktrees/*`,
`/tmp/wt-*`) đã không còn trên máy này; chỉ còn worktree tạm của phép đo driver E2E
(`/var/tmp/boxfox-drivers-wt`, detached `544305b`) và nó bị xoá sau khi đo xong. KHÔNG xoá:
`origin/main`, nhánh đang mở PR (`vorflux/boxfox-legacy-surface-removal`), dữ liệu `harness_*`.

**Vì sao không cần migration `researchId`:** quyết định (3) ở trên — box này là môi trường thử, không
có phiên sản xuất nào giữa chừng cần đường research cũ; phiên cũ vẫn đọc được dữ liệu đã ghi, chỉ
không còn đường gọi công cụ research nội bộ từ main (`RESEARCH_MAIN_READ_ONLY`).


## 11. Nhật ký v2 (2026-10-05): đã làm / chưa làm / vướng mắc

Mục này là bản đầy đủ của v2 — phần "đã làm" để tra cứu, phần "chưa làm" và "vướng mắc" để một agent
sau không phải đoán lại. Nhật ký chi tiết theo ngày nằm ở [`enablement-log.md`](enablement-log.md).

### 11.1 Đã làm

| Việc | Kết quả | Bằng chứng |
|---|---|---|
| **Bật mặc định cả nhóm** (#6599): `MASTER_DEFAULT = True`, 13 ghi chú "mặc định TẮT" đổi thành "mặc định BẬT từ v2" | env trống = 7/7 BẬT; `BOXFOX_REFORM=off` là lối thoát một lệnh; công tắc + legacy GIỮ nguyên | `/code/.generated_artifacts/v2/runtime-info-default-3118.json`; commit `96f158e` |
| **Test chốt đường cũ**: 35 tệp gắn marker `legacy_path` + fixture pin cả 8 env | full suite mặc định mới: `3 failed, 4384 passed, 12 skipped` (đúng 3 bài đỏ baseline); nhóm 22 tệp: `747 passed` ở CẢ HAI chiều | `/var/tmp/v2-full-unit-2.log`, `/var/tmp/v2-default-group.log`, `/var/tmp/v2-off-group.log` |
| **Writer trần chi H10.2** (#6600): route vận hành `GET\|PUT\|DELETE /api/agent/sessions/{sid}/usage-allocation` + khối `usage.allocations` trong `runtime-info` | PUT ghim `policyRevision` từ kernel; thiếu consent → `USAGE_NO_CONSENT`; đã gắn → 409; DELETE trả phần chưa tiêu; không tool nào của model chạm được trần | 12 ca route + 16 ca runtime-info + 57 ca ledger; `/code/.generated_artifacts/v2/live-allocation.json` (9/9 sống trên 3118) |
| **Kiểm chứng giá giả $4/$20 trên router bản sao** (model MIỄN PHÍ) | 4 ca A–D PASS: A thiếu allocation chặn; B vượt trần chặn; C trong trần gọi model + ghi `amount` thật; D route miễn phí `amount 0.0`. Đã revert; sha256 router thật không đổi | `/code/.generated_artifacts/h10/mock-price-20261005/` (`CONCLUSION.json`, `case-A..D`, `snapshot-real-router-{before,after}.json`) |
| **Bốn driver live trên 3118** | `driver.py` 11/11; `driver_job.py` 1/1; `driver_child_caps.py` 5/5; `driver_task.py` 0/1 (model miễn phí làm hỏng hợp đồng — xem 11.3) | `/code/.generated_artifacts/e2e/runs/v2-default*/summary.json` |
| **Drill rollback một lệnh** | `BOXFOX_REFORM=off` → master `{on:false, source:'explicit'}`, 7 thành viên `{on:false, source:'master'}`; driver `--switches off` 3/3 (đường mới bị TỪ CHỐI bằng `POLICY_SWITCH_OFF`); bỏ env → về mặc định BẬT | `/code/.generated_artifacts/v2/runtime-info-reform-off-3118.json`, `runtime-info-back-on-3118.json` |
| **Hậu kiểm: simplify + 3 vòng review độc lập + sửa** | 8 phát hiện trong tầm đã sửa (race PUT song song, đóng trần khi con đã tiêu/giữ trọn trần, runtime-info ghi schema khi chỉ đọc, ceiling khổng lồ 500→400, marker không kín, chỉ dẫn rollback tự mâu thuẫn, số liệu tài liệu) | commit `4185393`, `4c4c5dc`, `9da988f`, `d4bd374` |
| **Testing độc lập** (instance riêng 3119, chỉ model miễn phí) | PASSED 4/4 hạng mục sống; route 35/35 kiểm tra sống; sweep 36 tệp marker `655 passed`; tệp trọng tâm 105/154 passed | `/code/.generated_artifacts/images/01-…`, `02-…`, `15-…`, `18-…`, `21-…` |
| **Tài liệu + phát hành** | HANDOFF §6.4/§6.5, `enablement-log.md` (mục "v2 — bật mặc định", "v2 — trần chi (mock $4/$20)", "v2 — hậu kiểm"), `reform-status.md`, PR #4 mở với Risk Assessment 5/10 | https://github.com/i3abyxinhdepqua-lang/BoxFox-Agent-Box/pull/4 |

### 11.2 Chưa làm được (và vì sao)

| Việc | Vì sao chưa | Cần gì để mở |
|---|---|---|
| H9/H10.1 — calibration SỐNG (đo chi thật, đo chất lượng trên provider trả phí) | #6531 hoãn; `financial_consent_ref = null`, `measured = false` | consent tài chính riêng của chủ nhà |
| Xoá nhánh legacy | **v3: chủ nhà đã chốt B (2026-10-05) và 6/7 bề mặt đã xoá** (`4a4bdac`, `42b337a`, `64f960d`, `f2fceb0` — §10.6) | bề mặt 7: chốt luồng `research` của Work Graph + chuyển phiên cũ khỏi `researchId` |
| Viết lại luồng `research` của Work Graph qua envelope Research độc lập | luồng đó đang bị gateway chặn có chủ đích (§6.5) | quyết định của chủ nhà; không có trong v2 |
| `attemptSeq` của H3 giới hạn theo phiên (H3.11) | thiết kế để sau | nếu cần nhiều phiên cùng lúc |
| Tab Plan hiện tệp kế hoạch trong UI | chờ UI; hiện chỉ đọc qua API | việc UI |
| Ngân sách/thời gian của CHÍNH main (không chỉ con) | cùng họ #6546, chưa mở | thiết kế sau |
| UI/UX cho trần chi (mở/gỡ allocation bằng tay) | cố ý: trần là quyết định của người vận hành, chỉ có API | việc UI, nếu chủ nhà muốn |
| Merge PR #4 | chờ chủ nhà duyệt | chủ nhà |

### 11.3 Vướng mắc đã gặp & cách xử lý

| Vướng mắc | Cách xử lý | Trạng thái |
|---|---|---|
| Đảo mặc định làm ~35 tệp test chốt đường TRƯỚC v2 đỏ (lần chạy đầu: `235 failed`) | marker `legacy_path` + fixture pin 8 env; ba bài đỏ CÓ SẴN từ baseline KHÔNG gắn marker | xong |
| Marker không kín: `BOXFOX_REFORM=off BOXFOX_RESEARCH_GATEWAY=on` từ ngoài vẫn lọt vào "đường cũ" (9 bài đỏ) | fixture pin cả khóa tổng LẪN bảy thành viên `off` | xong |
| Gateway chặn spawn research của Work Graph dưới mặc định BẬT (44 bài cũ đỏ nếu bỏ pin) | chốt là hệ quả CÓ CHỦ ĐÍCH (H7.1/P5) → §6.5 + test mặc định `test_engine_work_spawns_cannot_bypass_the_gateway_either` | xong |
| `harnessAllocationId` KHÔNG có writer nào trong `backend/src` (H6.9) | thêm route vận hành trần chi | xong |
| PUT song song: hai request cùng reserve, con trỏ bị ghi đè, hàng `reserved` mồ côi vĩnh viễn | đọc lại `attached` SAU `await request.json()`; test `test_two_concurrent_puts_attach_exactly_one` | xong |
| DELETE để lại hàng `reserved` không API nào gỡ được (khi con đã tiêu, và biến thể con giữ TRỌN trần) | luật đóng theo `remaining == 0` + `_cascade_release_to_parent`; `if released is not None:` | xong |
| `runtime-info` (đáng lẽ chỉ đọc) ghi schema `harness_*` kể cả khi cả nhóm TẮT | dò `sqlite_master` đủ HAI bảng trước khi dựng sổ | xong |
| Ceiling số nguyên khổng lồ (`10**400`) trả 500 | bắt `OverflowError` → 400 `USAGE_FIELD_INVALID` | xong |
| Không được phép chi tiền thật khi kiểm chứng trần chi | router BẢN SAO + giá giả $4/$20 + model miễn phí; revert và chứng minh sha256 router thật không đổi | xong |
| `driver_task.py` 0/1 ở v2 | model MIỄN PHÍ làm hỏng hợp đồng task (nâng `acceptance` lên gốc rồi gửi `inputs: []`); cùng driver PASS 1/1 ở `enable-step8-task`/3117 ⇒ không phải hồi quy | ghi nhận |
| Ba bài đỏ CÓ SẴN từ baseline `346da06`: `test_terminal_tools::test_terminal_exec_echo`, `test_web_tools::test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`, `test_work_tool_replay::test_revoked_grant_blocks_next_tool_call` | không thuộc đợt này; không gắn marker, không sửa | ghi nhận |
| `pr report-risk` trả `not_tracked` (PR không nằm trong sổ review của hệ thống) | điểm 5/10 ghi trong thân PR (mục `## Risk Assessment`) + thẻ review; không lưu được vào ledger review | ghi nhận |
| `vflux_exec pr edit` từ chối thân PR có đường dẫn THƯ MỤC trần | dùng đường dẫn TỆP cụ thể trong mọi mục bằng chứng | xong |
| Lượt testing độc lập bị mất instance 3119 giữa chừng (thao tác `pkill` quá rộng của agent chính) | báo ngay cho testing; testing tự khởi động lại, không mất dữ liệu | xong |

### 11.4 Bằng chứng v2 (đường dẫn cụ thể)

| Thứ | Đường dẫn |
|---|---|
| Ảnh `switches` mặc định BẬT | `/code/.generated_artifacts/v2/runtime-info-default-3118.json`, `runtime-info-default-3118b.json` |
| Ảnh drill rollback | `/code/.generated_artifacts/v2/runtime-info-reform-off-3118.json`, `runtime-info-back-on-3118.json` |
| Kiểm chứng sống route trần chi | `/code/.generated_artifacts/v2/live-allocation.json`, driver `/code/.generated_artifacts/v2/live_allocation_check.py` |
| Giao thức giá giả $4/$20 | `/code/.generated_artifacts/h10/mock-price-20261005/CONCLUSION.json` (kèm `case-A..D`, `ledger-dump.json`, `snapshot-*`) |
| Bốn driver v2 | `/code/.generated_artifacts/e2e/runs/v2-default/summary.json`, `v2-default-job/summary.json`, `v2-default-caps/summary.json`, `v2-default-task/summary.json` |
| Testing độc lập | `/code/.generated_artifacts/images/01-runtime-info-default-on.json`, `02-usage-allocation-route.json`, `07-race-repro-before-fix.txt`, `15-runtime-info-head-states.txt`, `18-route-driver-at-head.log`, `21-delete-test-fails-on-old-code.txt`, `05-focused-unit-tests.txt` |
| Nhật ký chạy theo ngày | `docs/plan/reform-execution/enablement-log.md` |
| Báo cáo kiểm thử (một bản duy nhất) | Test Report "H1–H2 — hợp đồng task, kernel admission và kho task bền vững (PR #3)" |

### 11.5 Chạy lại nhanh (không cần đọc lại cả nhật ký)

```bash
# 1) Backend mặc định mới (env trống = BẬT), data dir riêng, cổng riêng
cd /code/.worktrees/boxfox-harness-reform
BOXFOX_AGENT_DATA_DIR=/var/tmp/boxfox-<tên>/data BOXFOX_HARNESS_PORT=31NN \
  nohup /code/i3abyxinhdepqua-lang/BoxFox-Agent-Box/backend/.venv/bin/python scripts/run-harness.py > /var/tmp/boxfox-<tên>.log 2>&1 &

# 2) Đọc công tắc đang có hiệu lực (nguồn duy nhất, không cần xem env tiến trình)
curl -s -H 'X-BoxFox-Admin: 1' -H 'Host: 127.0.0.1:31NN' http://127.0.0.1:31NN/api/agent/runtime-info

# 3) Driver live (đổi --base cho khớp cổng); --switches off để so cặp TẮT/BẬT
python3 /code/.generated_artifacts/e2e/driver.py --base 31NN --label <nhãn> --db <đường dẫn sessions.db>

# 4) Kiểm chứng sống route trần chi
python3 /code/.generated_artifacts/v2/live_allocation_check.py --base 31NN --out /code/.generated_artifacts/v2

# 5) Unit test (KHÔNG dùng --timeout: pytest-timeout không được cài)
cd backend && TMPDIR=/var/tmp PYTHONPATH=src /code/i3abyxinhdepqua-lang/BoxFox-Agent-Box/backend/.venv/bin/python \
  -m pytest -q -p no:cacheprovider tests/unit/<tệp>
```


## 12. Sổ quyết định & câu hỏi còn mở (v2)

Bản đầy đủ: `/code/.plans/reform-decision-ledger.md`. Bảng dưới là bản rút gọn để tra nhanh trong handoff.

| # | Nội dung | Trạng thái |
|---|---|---|
| #6597 | Bật `BOXFOX_RESEARCH_GATEWAY` ở bước 7 (trả lời #6536) | đã làm |
| #6598 | PR #3 đổi nhánh nền sang `main` | đã merge (`c6fd6e9`) |
| #6599 | Bật mặc định cả nhóm công tắc + GIỮ công tắc/legacy + ghi tổ chức vào handoff | đã làm ở v2 |
| #6600 | Mở đường trần chi H10.2 + kiểm chứng bằng giá giả $4/$20, không chi thật | đã làm ở v2 |
| #6601 | (đề xuất cũ) — bỏ | thay bằng #6600 |
| #6602 | Xoá dần nhánh legacy theo bề mặt (lựa chọn B) — yêu cầu chủ nhà 2026-10-05 | **đã làm 6/7** (`4a4bdac`, `42b337a`, `64f960d`, `f2fceb0`); bề mặt 7 (RESEARCH_GATEWAY) chờ chốt — §10.6 |
| #6531 | Calibration sống H9/H10.1 | CÒN HOÃN — chờ consent tài chính |
| #6536 | Câu hỏi gateway Research | đã trả lời bằng #6597 |
| **Câu hỏi MỞ** | Xoá nhánh legacy: từng phần (B) hay tất cả (C)? | **đã chốt B (2026-10-05)**; 6/7 bề mặt xong (#6602) — còn bề mặt 7 (§10.6) |
| **Câu hỏi MỞ** | Viết lại luồng `research` của Work Graph qua envelope Research độc lập? | chờ chủ nhà — §6.5, §10.4 |
| **Câu hỏi MỞ** | Có cần UI cho trần chi (mở/gỡ allocation) không? | chờ chủ nhà — hiện chỉ API |
