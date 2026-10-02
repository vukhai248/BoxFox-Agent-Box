# Bàn giao 03/10 — Work Graph W6–W10 (nhánh `B`, PR #1)

Tài liệu này là điểm vào cho agent local: trạng thái hiện tại, tiến độ, vướng mắc, việc còn lại và cách chạy lại.
Kết quả review + simplify chi tiết nằm ở [`review-simplify-03_10.md`](./review-simplify-03_10.md).

## 1. Trạng thái hiện tại (một khối)

- Repo: `/code/nganngan99hy-coder/BoxFox-Agent-Box`, nhánh `B`, HEAD `1bd238f`, đã push `origin/B`.
- PR: https://github.com/nganngan99hy-coder/BoxFox-Agent-Box/pull/1 — base `main`, diff base `68ecdf0`, đang OPEN (không draft).
- Kế hoạch đã duyệt: `/code/.plans/v2-work-graph-completion.md` (plan_id 1253). Design: `w8-exec-design.md`, `quality-recovery-design.md`.
- Đã gộp đủ 6 track: W8.A4.2, W8.A4.3–A4.5, W7.1/W7.2, W6.1.3/W6.2, W6.5.3, W9, W10 (harness), W1.P, W5.LEGACY.
- Review vòng 2 (3 miền) và simplify đã trả kết quả; **mọi phát hiện của review đã vá**; simplify là báo cáo chỉ đọc, **chưa áp dụng**.
- Đang chạy: (a) subagent `test-workgraph` (testing), (b) benchmark W10 thật — shard 1 và 6 còn chạy, shard 2/3/4/5 đã xong.
- Test nền: `python3 -m pytest backend/tests -q -k work` → **988 passed, 2 failed, 1 skipped** (2 lỗi là ca môi trường có tiền đề "host không có bwrap", tái hiện cả trên `68ecdf0`). Lượt chạy lại toàn bộ trên HEAD `8f24be7` đã xong với đúng con số đó (988/2/1); sau `1bd238f` cần chạy lại lần cuối trước khi chốt.

## 2. Tiến độ theo hạng mục kế hoạch

| Hạng mục | Trạng thái | Bằng chứng |
|---|---|---|
| W8.A4.2 cổng phạm vi theo lượt | Xong + vá vòng 1/2 | `work_scope.py`, 78 test cổng phạm vi (gồm ca `$'…'`) |
| W8.A4.3 worktree theo run | Xong | probe oracle true, `docs/plan/W8.A4.3-worktree-evidence.json` |
| W8.A4.4 snapshot/touch-set theo run | Xong | probe oracle true, `docs/plan/W8.A4.4-ship-scoped-evidence.json` |
| W8.A4.5 ship theo snapshot + repair | Xong (probe A4.5 oracle false — ghi trung thực) | `docs/plan/W8.A4.5-repair-loop-evidence.json`, `b9f2529` |
| W7.1 hợp đồng tool (API/CLI) | Xong | `tool_arg_errors.py`, `ACTION_FIELDS`; UI chưa đổi (ngoài phạm vi) |
| W7.2 phục hồi tool | Xong + vá F4 | `tool_recovery.py`, 9 test |
| W6.1.3/W6.2 chất lượng reviewer/producer | Xong | `verify_exec`, receipt, corpus finding; 87 test đích |
| W6.5.3 cap helper lookup 4096 → 16000 | Xong | đo 32 lượt, quyết định `(A or B) and C` |
| W9 recorder/CDP | Xong | `deploy/docker/tests` 516 passed; 40/40 file đọc được trong box |
| W10 harness + 24 lượt thật | Harness xong; **lượt thật chưa đủ** | 16/24 ô đã chấm (shard 2–5); shard 1, 6 còn chạy |
| W2.UI / W9.UI | Chỉ runbook | `docs/plan/W9.UI-runbook.md`; cần harness thật + xác nhận CUA mới tick được |
| W1.P preflight, W5.LEGACY | Xong | `docs/plan/W1.P-preflight-evidence.json`, `W5.LEGACY-evidence.json` |

## 3. Vướng mắc và rủi ro đang mở

1. **Cổng W10 gần như chắc chắn không đạt trong lần chạy này** — nguyên nhân chính: model `space-bunny-free` nhiều lượt **không gọi `work_graph(action='create')`** dù fixture đã đặt `workIntent`, nên ô chấm thành `no_run` (S01, S06–S09…). Đây là hành vi model + khoảng trống prompt, không phải lỗi oracle; kế hoạch đã chốt "ghi kết quả thật, kể cả khi chưa đạt".
2. **Ô `no_run` vẫn làm hỏng các bộ đếm cứng**: `same_child_continuation` fail khi không có continuation nào ⇒ `gate.sameChild` > 0 dù không có vi phạm an toàn thật. Giữ nguyên ngữ nghĩa theo thiết kế §10 ("100% same-child"), nhưng phải chú thích khi đọc kết quả.
3. **Lệch commit của bằng chứng**: 24 lượt chạy trên mã sản phẩm `46ed557`; các bản vá review vòng 2 (`3b23fa3` trở đi) chưa có trong mã đã chạy. Oracle thì được chấm lại bằng `--rescore` (không chạy lại model). Phải ghi rõ trong báo cáo W10.
4. **W8.A4.5 còn mở**: chưa có vòng probe khép kín sau bản vá trigger (`ac7a9a7`) và sau khi gộp `B`; đường repair ở node ảo `__integration__` chưa đo.
5. **F1 còn sót một đường** (đã vá `1bd238f`): cổng retry `status = error` áp cho cả `WORK_FINDING_IGNORED` — test-workgraph tái lập end-to-end và vá; cần review lại đường này khi rảnh.
6. **Chưa bump `work_policy.VERSION`** lên `work-checks/11` (xem mục Out-of-Scope trong PR).
7. **`security_opt` + `BOX_DEFAULT_NETWORK: "on"`** là đánh đổi đã được duyệt, gỡ 2 dòng là fail-closed trở lại.
8. **S09 restart**: bench cũ từng ném `Cannot operate on a closed database`; đã vá ở `8f24be7` (huỷ + await task cũ trước khi đóng DB) nhưng lượt S09 của lần chạy này vẫn dùng mã cũ.

## 4. Việc còn lại (theo thứ tự)

1. **Chờ `test-workgraph`** → chuyển kết quả thành **một** Test Report (`vflux_exec test-report submit --report-file-path /code/.generated_artifacts/test_report.md --status <passed|partial|blocked> --coverage <x>/<y>`); trạng thái lấy từ dòng `OVERALL STATUS:` của subagent.
2. **Chờ shard 1 và 6** → gộp 24 ô:
   `python3 scripts/eval/work_acceptance_bench.py --merge /var/tmp/w10-s1,/var/tmp/w10-s2,/var/tmp/w10-s3,/var/tmp/w10-s4,/var/tmp/w10-s5,/var/tmp/w10-s6 --rescore --out /var/tmp/w10-merged`
3. Viết `docs/plan/W10-acceptance-evidence.json` (model, commit, configHash, attempts, budget, token/latency theo lượt và theo vai, **mọi failure trong mẫu số**) và `docs/plan/W10-acceptance-report.md` (kết luận trung thực: cổng đạt/không đạt, lý do, ảnh hưởng).
4. Tick các mục còn lại trong `docs/plan/Work-Graph-fix.md` (W2.UI/W9.UI chỉ khi có bằng chứng thật).
5. Khi test xong: tạo PR mới / cập nhật PR #1 với kết quả test + W10 (theo yêu cầu chủ nhà).
6. (Tuỳ chọn) PR dọn dẹp riêng cho danh sách simplify ở `review-simplify-03_10.md` §2.

## 5. Cách chạy lại (lệnh thật)

```bash
cd /code/nganngan99hy-coder/BoxFox-Agent-Box

# test nền (khoảng 7 phút)
python3 -m pytest backend/tests -q -k work

# các suite đích của bản vá
python3 -m pytest backend/tests/unit/test_work_scope_terminal_classifier.py \
  backend/tests/unit/test_work_scope_gate.py backend/tests/unit/test_work_scope_delegate_command.py \
  backend/tests/unit/test_sandbox_verify_exec.py backend/tests/unit/test_sandbox_verify_capture.py \
  backend/tests/unit/test_work_review_scope_w611.py backend/tests/unit/test_work_reviewer_fairness.py \
  backend/tests/unit/test_work_verify_exec.py backend/tests/unit/test_work_acceptance_bench.py \
  backend/tests/unit/test_work_repair_w8.py backend/tests/unit/test_work_tool_replay.py -q

# gộp + chấm lại benchmark (không gọi model)
python3 scripts/eval/work_acceptance_bench.py --merge <dir1,...> --rescore --out <dir-gộp>
```

Router dùng cho bench: `node scripts/eval/work_budget_router.mjs .tmp/work-checks/shared-router` (cổng `http://127.0.0.1:36219`,
model `opencode/space-bunny-free`, connectionId `72c7ed8d-675f-4b49-b038-a1598ed228c7`). Log shard: `/var/tmp/w10-s{1..6}.log`;
kết quả: `/var/tmp/w10-s{1..6}/results.json` + `runs/<ca>-r<n>/bundle.json` (nguồn để `--rescore`).

## 6. Bản đồ commit (nhánh `B`)

```
1bd238f fix(work-graph): WORK_FINDING_IGNORED không đi qua đường retry 'error' (F1 còn sót, test-workgraph tìm)
8f24be7 test(w8-repair): con không resume được thì rơi về con mới; bench dừng lượt cũ trước khi restart
c8b55ed feat(w10-bench): --rescore chấm lại từ bundle đã lưu
5fabda9 fix(w10-bench): oracle đọc đúng payload tool_end, no_auto_pass theo kind, no_run không đạt '!verified'
3b23fa3 fix(work-graph): bịt lỗ $'…' của cổng phạm vi + 5 phát hiện review vòng 2
46ed557 merge(w8-isolation): worktree theo run, ship theo snapshot, repair hội tụ (W8.A4.3–A4.5)
545b1ec merge(B): W6.1.3/W6.2, W6.5.3, W7, W8.A4.2, W9, W10
```

Mốc tick kế hoạch: `90b49b2` (W8.A4.2), `ab2a7e9` (W7.2/W7.1/W1.P/W5.LEGACY), `74ee8c3` (W9), `786a488` (W6.5.3), `a3498d2` (W6.1.3/W6.2).

## 7. Kết quả subagent (tóm tắt)

| Subagent | Kết quả | Ghi chú |
|---|---|---|
| `review-core` | Block, 7/10 High | F2.1 blocking (`$'…'`), F2.2, F2.3 — đã vá hết |
| `review-sandbox` | Ship with mitigations, 6/10 Medium | F1–F6 — đã vá hết |
| `review-contracts` | Ship with mitigations, 5/10 Medium | F1–F5 — đã vá hết |
| `simplify-workgraph` | Báo cáo chỉ đọc | ~40 dòng xoá + 5 mục gộp; chưa áp dụng |
| `test-workgraph` | **Đang chạy** (đã tìm + vá một lỗ còn sót của F1) | e2e 8/12 → 12/12; full suite 988/2/1; xem `1bd238f` |

Chi tiết đầy đủ (từng finding, mức, trạng thái, commit vá): [`review-simplify-03_10.md`](./review-simplify-03_10.md).
