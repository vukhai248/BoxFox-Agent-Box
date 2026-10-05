# Bàn giao reform harness BoxFox — theo checkpoint (H0–H12)

> **Bản tổng nằm ở [`HANDOFF.md`](HANDOFF.md)** — đọc trước: đường dẫn gốc, kiến trúc, bảng công tắc,
> quy trình bật dần từng công tắc và rollback. Thư mục này giữ bản chi tiết theo từng checkpoint.

- **Phạm vi:** tài liệu bàn giao từng checkpoint của kế hoạch reform harness (plan_id 1257, duyệt qua Plan panel 2026-10-03), phục vụ H10–H11.
- **Nhánh / mốc:** `vorflux/boxfox-harness-reform`, base `346da06`, head `0a48282` (2026-10-04); lớp vòng chạy H4–H8 nối ở `802f51f`; chuỗi việc 2026-10-04: `79f024b`, `c6c88bb`, `fcc6819`, `b37dafb`, `82550cc`, `f7e4a9b`, `b219f57`, `17b146b`, `ad3b5f8`, `84022bf`, `9a04c16`, `2bd3886`, `0e9b6df`, `f7ebbc9`, `f6dbe2b` (H12 khóa tổng), `e7223ae` (bàn giao tổng), `0a48282` (chốt lại hợp đồng nới hạn chót lượt plan); tài liệu này đã commit ở `c6be87e`, `ed5d771`, `c3bee48` và cập nhật ở `c836822`, `8a4bc54`, `a95576d`; lần soát 2026-10-04 (H4–H11) nằm trong chính mốc này.
- **Nguồn chính:**
  - `/code/.plans/v1-boxfox-harness-reform.md` — kế hoạch đã duyệt (§17: yêu cầu handoff);
  - `/code/.plans/reform-execution-runbook.md` — §II.2 khung thư mục, §II.3 nghiệm thu, §II.4 ma trận kiểm, §II.6 rollback/migration drill;
  - `/code/.plans/reform-backlog-disposition.md` — ánh xạ backlog (PHẦN III);
  - `/code/.plans/reform-backlog-audit.md` — kiểm kê nguồn/evidence debt;
  - `docs/plan/reform-status.md` — bảng trạng thái theo dõi (nguồn số test, commit, dòng lỗi);
  - artifact thực tế: `/code/.generated_artifacts/h3h8/`, `/var/tmp/w10f-seq/`, `/var/tmp/boxfox-testing/results/`, `/code/.plans/reform-impl-pr-body.md`.

## Cấu trúc mỗi checkpoint

Mỗi thư mục `H0/` … `H11/` gồm đúng 5 file:

| File | Nội dung |
|---|---|
| `contract.md` | mục tiêu, phạm vi, non-goals, phụ thuộc, nghiệm thu (runbook §II.3) |
| `baseline.json` | pin code/schema/fixture/model/route/machine theo khung runbook §II.2 |
| `evidence.md` | lệnh/artifact thật, kết quả, mục **chưa kiểm** |
| `migration.md` | tương thích, dữ liệu legacy, rollback / kill switch |
| `handoff.md` | trạng thái, quyết định, blocker, việc tiếp |

**Nhật ký bật dần công tắc:** `enablement-log.md` (append-only; bước 1–2 đã ĐẠT 2026-10-05).

**H12 (khóa tổng) không tách thư mục** — nằm trọn trong `HANDOFF.md` §5 (bảng công tắc) và §6
(quy trình bật dần từng công tắc); bảng theo dõi vẫn có dòng H12.

Quy ước trạng thái: `verified` (đủ bằng chứng theo nghiệm thu) · `partial` (đạt một phần, nêu rõ điều kiện chưa đạt) · `blocked` (chờ consent/quyết định) · `tương lai` (hoãn có mác, theo #6531).

## Danh sách checkpoint

| CP | Nội dung | Trạng thái | Ghi chú |
|---|---|---|---|
| H0 | Chốt baseline W10.F + parity `6adbe78` ≡ `346da06` | partial | dừng ở 31/34 cell theo lệnh chủ nhà; không có aggregate cuối |
| H1 | Hợp đồng + tương thích ngược (`orchestration_contracts.py`) | verified | 77 ca; PR #3; legacy read 8/8 |
| H2 | Một cửa admission (`execution_kernel.py`) + kho task (`task_service.py`) | verified | 34 + 60 ca; parity S4/S5 `failed=[]` |
| H3 | Bề mặt task + phân loại hồi phục | verified | E2E 9/9 (110 check), probe 71/71, scoped 716 passed; F5 chờ quyết |
| H4 | Job qua nhiều lượt (`harness_jobs.py` → `job_surface.py`, `job_wake.py`) | verified | 59 ca + P2 10/10; nối runtime `802f51f`; A1–A9/29 đạt trên `c836822`; process job fail closed |
| H5 | Context + skills (`context_bundle.py`, `skill_spec.py` → `context_surface.py`) | verified | 79 + 114 + 56 ca + P3 13/13; nối runtime `802f51f`; B1–B5/29 đạt trên `c836822` |
| H6 | Phân bổ & hạch toán (`usage_ledger.py` → `usage_surface.py`) | verified | 55 + 22 ca + P4 7/7; nối runtime `802f51f`; C1–C5/29 đạt trên `c836822`; phần giới hạn ngân sách hoãn #6531 |
| H7 | Research ownership (`research_owner.py` → `research_gateway.py`) | verified | 52 + 48 ca + P5 8/8; nối runtime `802f51f`; D1–D4/29 đạt trên `c836822`; gateway giữ mã, mặc định off (#6536) |
| H8 | Main thích ứng (`adaptive_main.py` → `adaptive_surface.py`) | verified | 87 + 13 ca + P6 14/14; nối runtime `802f51f`; E1–E4/29 đạt trên `c836822`; route policy vận hành `c6c88bb` |
| H9 | Suite v2 + calibration | partial | 62 ca / 40 safety oracle / 38 test; fault corpus 33/33; shadow W10.F 34/34 cell, 0 verdict; `measured=false`; live pilot chờ consent |
| H10 | Khép harness + handoff | partial | tài liệu H0–H10 đã có; **drill rollback 11/11 PASS**; nghiệm thu mức vòng chạy H4–H8 **29/29 PASS** trên `c836822`; review toàn snapshot cuối (không phát hiện chặn, 2/10); còn: H9 live pilot, quyết định chủ nhà |
| H10.1 | Calibration sống | tương lai | hoãn theo #6531 — cần consent tài chính riêng; mã giữ nguyên, công tắc TẮT; chưa tiêu |
| H11 | Quản lý con/subagent (#6545–#6548): trần 1000/1500 + 7200 s, cờ kết cục, chặn đọc lại, nhắc/trần chờ hạn, `child_resume`, cha khai trần | partial | code `84022bf` + simplify `9a04c16` + phủ kiểm `2bd3886` + bảy sửa đổi sau review `0e9b6df` + ba siết sau vòng soát 2 `f7ebbc9`; `test_child_management_h11.py` **37 ca**, nhóm liên quan 18 file **271 passed**, scoped 22 file **582 passed** trên `84022bf`; trần mới đọc được từ `runtime-info` trên 3113; E2E thật `task-fix` 1/1 + `child` 1/1 (PASS); review risk 5/10 đã xử lý; testing chạy nốt |
| H12 | Khóa tổng `BOXFOX_REFORM` + khối `switches` trong `runtime-info` | verified | `feature_switches.py` (một chỗ đọc duy nhất), bảy read-site đổi sang đó, `runtime-info` thêm `switches`; `test_reform_master_switch.py` **19 ca**; mặc định giữ TẮT để bật dần |

## Ma trận yêu cầu → bằng chứng → nghiệm thu (tóm tắt)

| Yêu cầu (nguồn) | Điểm nối | Bằng chứng | Nghiệm thu | Chưa chắc |
|---|---|---|---|---|
| #6490 main thích ứng, không fixed graph | H8 (+H2 kernel) | P6 14/14; 87 + 13 ca; E1–E4/29 | stop/revoke thắng; reason+evidenceRefs | chạy thật (calibration) |
| #6491 ngân sách linh hoạt, không vô hạn | H6 | P4 7/7; 55 + 22 ca; C1–C5/29 | không double-count; giá lạ `None`; thiếu trần → từ chối | calibration sống (hoãn #6531) |
| #6492 thiết kế quyền native, child không rộng hơn parent | H2 | parity S4/S5; test guard | enforcement `application`; không claim OS isolation | native sandbox ngoài phạm vi |
| #6493 Research độc lập | H7 | P5 8/8; 52 + 48 ca; D1–D4/29 | intent main không thành canonical | chạy Research sống (hoãn #6531) |
| #6494 harness trước, môi trường sau | toàn bộ | diff không có desktop/update/mobile | giữ roadmap | — |
| #6495 budget/loop signals | H6 + H8 | P4/P6; C1–C5 + E1–E4/29 | trần chỉ từ policy; loop guard toàn bộ chữ ký | — |
| #6496 native fallback | H2 | `permission_view` | chưa chọn primitive OS (đúng: mới là khuyến nghị) | — |
| #6497 Research API judgment | H7 | gateway envelope; D1–D4/29 | publication/review bind version | chưa có phiên thật |
| #6498 đánh giá bằng mã/nguồn công khai | H9 | suite v2 mapping | safety oracle giữ nguyên | chưa đo |
| #6499 mapping suite legacy | H9 | 62 ca / 4 disposition | trajectory-only không ép adaptive | chưa đo |
| Task list/send/abandon + receipt huỷ | H3 | E2E 9/9; E5 14/14 | duplicate không effect mới; cancel có receipt | F5 attemptSeq |
| Job nền nhiều lượt | H4 | P2 10/10; A1–A9/29 | heartbeat không mở turn; reconcile không spawn | — |
| Context/skill epoch | H5 | P3 13/13; B1–B5/29 | pin `(skill, attempt)` duy nhất; không import skill ngoài | — |
| Kill switch mặc định off | H2/H3 | test switch off; 7 công tắc H4–H8: `BOXFOX_TASK_SURFACE`, `BOXFOX_CONTROLLER_JOBS`, `BOXFOX_ADAPTIVE_HARNESS`, `BOXFOX_USAGE_LEDGER`, `BOXFOX_CONTEXT_SURFACE`, `BOXFOX_RESEARCH_GATEWAY`, `BOXFOX_RECOVERY_POLICY` (+ `BOXFOX_PEER_MESH` riêng) | đường legacy giữ nguyên | — |
| Rollback/migration drill (H10) | H2/H3 | `/code/.generated_artifacts/h3h8/drill/rollback_drill_962cd84.log`: 11/11 | rollback không mất data/approval, không replay mutation | chưa drill trên box thật |

## Ánh xạ backlog (tóm tắt)

Nguồn: `/code/.plans/reform-backlog-disposition.md` (§III.1–III.2). Từ vựng disposition: `carry` / `revalidate` / `redesign` / `defer` / `historical` — bản ghi trong doc là **kiến nghị của bản cải tổ, chưa phải owner duyệt tất cả**; khi khép mục phải thêm receipt/evidence trước đổi trạng thái.

- **`carry` (giữ mục tiêu + evidence debt):** W6.1 C4/C5 → H0/H2/H9; W6.2.BIND → H2/H5/H9; W6.Q FU1 → H0/H9; W7.1; W2.UI/W9.UI; W10.F → H0; W12 T6 → H10; Research C-7/R1–R12 → H7/H9; v29 keyring E; Plan-mode P5, P6/P7 → H9/H10; Agent output quality; B1–B7; C1/C2; C7/C8 (một phần `redesign`).
- **`revalidate` (kiểm lại code/fixture hiện tại trước sửa):** element selector phase 1; BUG-30/Nợ-2; BUG-66/67; BUG-68/69; Research branch criteria (kèm `redesign`); Research providers/blocked sources; Round7/E2E; A3/A4/A5 (kèm `redesign`); C3/C4/C5; dev log N-4 (kèm `historical`).
- **`redesign` (thay cơ chế, giữ outcome/invariant):** W6.5.2 + #6457 → H6; A2 → H3; A6 → H3; A7 → H4; A1/C6 (kèm `revalidate`) → H6/H9.
- **`defer` (giữ roadmap, không đóng):** Research benchmark 12×3/M6; element selector phase 2/3; CUA benchmark; completion email; v22 T14/D-13; A8 (todo UX); Product phase7/§9.3/§214; Machine D1–D4/M1–M7/U1–U4/R0–R3 (**sau H10**).
- **`historical` (giữ hồ sơ, không thi công lại):** W6.Q FU2–FU10; W7.2; W10.M1–M3; W11 P0–P3; W12 T2–T5; Plan-mode P1–P4; Frozen round4; v21/v22; plan migration.
- **Lưu ý H10:** mục `defer` vẫn phải xuất hiện trong handoff; không dùng "reform xong" để đóng UI/Research deep benchmark/native/mobile.
- **Lưu ý H11:** bốn việc của #6545 gộp vào MỘT checkpoint (đúng #6545/#6548); trần mới theo #6546; gọi lại con theo #6547 (cha quyết định, không tự chạy lại). E2E thật `child_resume` đã chạy PASS (`runs/child/`); phần chưa đo là cờ `timedOut` vì hạn chót thật và gọi lại tới trần 3 lần/lượt — không ghi là đã đạt.

## Nợ và điểm chưa kiểm chung

- **Live calibration (H10.1) hoãn #6531** — cần consent tài chính riêng; `financial_consent_ref` để `null`, không ghi là đã có quyền; mã giữ nguyên, công tắc TẮT.
- **H4–H8 + `recovery_policy` đã nối runtime** (`802f51f`; bảy công tắc mặc định off): nghiệm thu mức vòng chạy **29/29 PASS** trên `c836822`; nợ riêng từng checkpoint ghi ở H4.5, H6.8/H6.9.
- **H9 chưa đo:** live pilot (cần consent riêng); fixture lỗi offline + shadow W10.F đã làm offline (33/33, 34/34 cell, 0 verdict).
- **Rollback/migration drill của H10 đã chạy offline (11/11, `962cd84`)** — chưa drill trên box thật với phiên đang chạy.
- **Review toàn snapshot cuối (H10) đã chạy** trên `ed5d771`/`c3bee48`: không phát hiện chặn; 1 should-fix về tài liệu (đã sửa trong `c3bee48`+); risk 2/10; tiếp nối bằng việc 2026-10-04 (`79f024b`, `c6c88bb`, `fcc6819`, `b37dafb`, `82550cc`, `f7e4a9b`).
- **F5/H3.11:** `attemptSeq` theo phiên; đổi khoá cần migration chỉ mục — chờ chủ nhà quyết.
- **Ba test đỏ có sẵn trên `346da06`** (`test_terminal_exec_echo`, `test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`, `test_revoked_grant_blocks_next_tool_call`) — không phải regression.
- **Cách đếm test:** số trong tài liệu này là **số ca thu thập** (parametrize mở rộng) theo `docs/plan/reform-status.md` / PR body; test plan H3–H8 dùng **số hàm `def test_`** (thấp hơn, ví dụ `orchestration_contracts` 15 hàm / 77 ca). Cả hai đều ghi được nguồn.
- **W10.F không có aggregate cuối** (31/34 cell); không dùng số baseline làm kết quả reform.
