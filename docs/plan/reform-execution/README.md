# Bàn giao reform harness BoxFox — theo checkpoint (H0–H9)

- **Phạm vi:** tài liệu bàn giao từng checkpoint của kế hoạch reform harness (plan_id 1257, duyệt qua Plan panel 2026-10-03), phục vụ H10.
- **Nhánh / mốc:** `vorflux/boxfox-harness-reform`, base `346da06`, head `962cd84` (cây sạch, 2026-10-04). Tài liệu trong thư mục này **chưa commit**.
- **Nguồn chính:**
  - `/code/.plans/v1-boxfox-harness-reform.md` — kế hoạch đã duyệt (§17: yêu cầu handoff);
  - `/code/.plans/reform-execution-runbook.md` — §II.2 khung thư mục, §II.3 nghiệm thu, §II.4 ma trận kiểm, §II.6 rollback/migration drill;
  - `/code/.plans/reform-backlog-disposition.md` — ánh xạ backlog (PHẦN III);
  - `/code/.plans/reform-backlog-audit.md` — kiểm kê nguồn/evidence debt;
  - `docs/plan/reform-status.md` — bảng trạng thái theo dõi (nguồn số test, commit, dòng lỗi);
  - artifact thực tế: `/code/.generated_artifacts/h3h8/`, `/var/tmp/w10f-seq/`, `/var/tmp/boxfox-testing/results/`, `/code/.plans/reform-impl-pr-body.md`.

## Cấu trúc mỗi checkpoint

Mỗi thư mục `H0/` … `H9/` gồm đúng 5 file:

| File | Nội dung |
|---|---|
| `contract.md` | mục tiêu, phạm vi, non-goals, phụ thuộc, nghiệm thu (runbook §II.3) |
| `baseline.json` | pin code/schema/fixture/model/route/machine theo khung runbook §II.2 |
| `evidence.md` | lệnh/artifact thật, kết quả, mục **chưa kiểm** |
| `migration.md` | tương thích, dữ liệu legacy, rollback / kill switch |
| `handoff.md` | trạng thái, quyết định, blocker, việc tiếp |

Quy ước trạng thái: `verified` (đủ bằng chứng theo nghiệm thu) · `partial` (đạt một phần, nêu rõ điều kiện chưa đạt) · `blocked` (chờ consent/quyết định).

## Danh sách checkpoint

| CP | Nội dung | Trạng thái | Ghi chú |
|---|---|---|---|
| H0 | Chốt baseline W10.F + parity `6adbe78` ≡ `346da06` | partial | dừng ở 31/34 cell theo lệnh chủ nhà; không có aggregate cuối |
| H1 | Hợp đồng + tương thích ngược (`orchestration_contracts.py`) | verified | 77 ca; PR #3; legacy read 8/8 |
| H2 | Một cửa admission (`execution_kernel.py`) + kho task (`task_service.py`) | verified | 34 + 60 ca; parity S4/S5 `failed=[]` |
| H3 | Bề mặt task + phân loại hồi phục | verified | E2E 9/9 (110 check), probe 71/71, scoped 716 passed; F5 chờ quyết |
| H4 | Job qua nhiều lượt (`harness_jobs.py`) | partial | 59 ca + P2 10/10; **chưa nối runtime** |
| H5 | Context + skills (`context_bundle.py`, `skill_spec.py`) | partial | 79 + 114 ca + P3 13/13; **chưa nối runtime** |
| H6 | Phân bổ & hạch toán (`usage_ledger.py`) | partial | 55 ca + P4 7/7; calibration chờ consent |
| H7 | Research ownership (`research_owner.py`) | partial | 52 ca + P5 8/8; **chưa nối runtime** |
| H8 | Main thích ứng (`adaptive_main.py`) | partial | 87 ca + P6 14/14; **chưa nối runtime** |
| H9 | Suite v2 + calibration | partial | 62 ca / 40 safety oracle / 38 test; fault corpus 33/33; shadow W10.F 34/34 cell, 0 verdict; `measured=false`; live pilot chờ consent |
| H10 | Khép harness + handoff | partial | tài liệu H0–H10 đã có; **drill rollback 11/11 PASS**; còn: review toàn snapshot cuối |
| H10.1 | Calibration sống | blocked | cần consent tài chính riêng — chưa tiêu |

## Ma trận yêu cầu → bằng chứng → nghiệm thu (tóm tắt)

| Yêu cầu (nguồn) | Điểm nối | Bằng chứng | Nghiệm thu | Chưa chắc |
|---|---|---|---|---|
| #6490 main thích ứng, không fixed graph | H8 (+H2 kernel) | P6 14/14; 87 ca | stop/revoke thắng; reason+evidenceRefs | chưa nối runtime |
| #6491 ngân sách linh hoạt, không vô hạn | H6 | P4 7/7; 55 ca | không double-count; giá lạ `None`; thiếu trần → từ chối | calibration sống |
| #6492 thiết kế quyền native, child không rộng hơn parent | H2 | parity S4/S5; test guard | enforcement `application`; không claim OS isolation | native sandbox ngoài phạm vi |
| #6493 Research độc lập | H7 | P5 8/8; 52 ca | intent main không thành canonical | chưa nối runtime |
| #6494 harness trước, môi trường sau | toàn bộ | diff không có desktop/update/mobile | giữ roadmap | — |
| #6495 budget/loop signals | H6 + H8 | P4/P6 | trần chỉ từ policy; loop guard toàn bộ chữ ký | chưa nối runtime |
| #6496 native fallback | H2 | `permission_view` | chưa chọn primitive OS (đúng: mới là khuyến nghị) | — |
| #6497 Research API judgment | H7 | gateway envelope | publication/review bind version | chưa có phiên thật |
| #6498 đánh giá bằng mã/nguồn công khai | H9 | suite v2 mapping | safety oracle giữ nguyên | chưa đo |
| #6499 mapping suite legacy | H9 | 62 ca / 4 disposition | trajectory-only không ép adaptive | chưa đo |
| Task list/send/abandon + receipt huỷ | H3 | E2E 9/9; E5 14/14 | duplicate không effect mới; cancel có receipt | F5 attemptSeq |
| Job nền nhiều lượt | H4 | P2 10/10 | heartbeat không mở turn; reconcile không spawn | chưa nối runtime |
| Context/skill epoch | H5 | P3 13/13 | pin `(skill, attempt)` duy nhất; không import skill ngoài | recall compaction chưa kiểm |
| Kill switch mặc định off | H2/H3 | test switch off; `BOXFOX_ADAPTIVE_HARNESS`, `BOXFOX_TASK_SURFACE` | đường legacy giữ nguyên | — |
| Rollback/migration drill (H10) | H2/H3 | `/code/.generated_artifacts/h3h8/drill/rollback_drill_962cd84.log`: 11/11 | rollback không mất data/approval, không replay mutation | chưa drill trên box thật |

## Ánh xạ backlog (tóm tắt)

Nguồn: `/code/.plans/reform-backlog-disposition.md` (§III.1–III.2). Từ vựng disposition: `carry` / `revalidate` / `redesign` / `defer` / `historical` — bản ghi trong doc là **kiến nghị của bản cải tổ, chưa phải owner duyệt tất cả**; khi khép mục phải thêm receipt/evidence trước đổi trạng thái.

- **`carry` (giữ mục tiêu + evidence debt):** W6.1 C4/C5 → H0/H2/H9; W6.2.BIND → H2/H5/H9; W6.Q FU1 → H0/H9; W7.1; W2.UI/W9.UI; W10.F → H0; W12 T6 → H10; Research C-7/R1–R12 → H7/H9; v29 keyring E; Plan-mode P5, P6/P7 → H9/H10; Agent output quality; B1–B7; C1/C2; C7/C8 (một phần `redesign`).
- **`revalidate` (kiểm lại code/fixture hiện tại trước sửa):** element selector phase 1; BUG-30/Nợ-2; BUG-66/67; BUG-68/69; Research branch criteria (kèm `redesign`); Research providers/blocked sources; Round7/E2E; A3/A4/A5 (kèm `redesign`); C3/C4/C5; dev log N-4 (kèm `historical`).
- **`redesign` (thay cơ chế, giữ outcome/invariant):** W6.5.2 + #6457 → H6; A2 → H3; A6 → H3; A7 → H4; A1/C6 (kèm `revalidate`) → H6/H9.
- **`defer` (giữ roadmap, không đóng):** Research benchmark 12×3/M6; element selector phase 2/3; CUA benchmark; completion email; v22 T14/D-13; A8 (todo UX); Product phase7/§9.3/§214; Machine D1–D4/M1–M7/U1–U4/R0–R3 (**sau H10**).
- **`historical` (giữ hồ sơ, không thi công lại):** W6.Q FU2–FU10; W7.2; W10.M1–M3; W11 P0–P3; W12 T2–T5; Plan-mode P1–P4; Frozen round4; v21/v22; plan migration.
- **Lưu ý H10:** mục `defer` vẫn phải xuất hiện trong handoff; không dùng "reform xong" để đóng UI/Research deep benchmark/native/mobile.

## Nợ và điểm chưa kiểm chung

- **Live calibration (H10.1) chưa chạy** — cần consent tài chính riêng; `financial_consent_ref` để `null`, không ghi là đã có quyền.
- **H4–H8 + recovery_policy chưa nối runtime** (không có src importer): nghiệm thu mức thư viện + probe đạt; điều kiện mức vòng chạy **chưa kiểm**.
- **H9 chưa đo:** live pilot (cần consent riêng); fixture lỗi offline + shadow W10.F đã làm offline (33/33, 34/34 cell, 0 verdict).
- **Rollback/migration drill của H10 đã chạy offline (11/11, `962cd84`)** — chưa drill trên box thật với phiên đang chạy.
- **F5/H3.11:** `attemptSeq` theo phiên; đổi khoá cần migration chỉ mục — chờ chủ nhà quyết.
- **Ba test đỏ có sẵn trên `346da06`** (`test_terminal_exec_echo`, `test_the_dispatcher_sends_web_tools_to_the_host_not_the_box`, `test_revoked_grant_blocks_next_tool_call`) — không phải regression.
- **Cách đếm test:** số trong tài liệu này là **số ca thu thập** (parametrize mở rộng) theo `docs/plan/reform-status.md` / PR body; test plan H3–H8 dùng **số hàm `def test_`** (thấp hơn, ví dụ `orchestration_contracts` 15 hàm / 77 ca). Cả hai đều ghi được nguồn.
- **W10.F không có aggregate cuối** (31/34 cell); không dùng số baseline làm kết quả reform.
