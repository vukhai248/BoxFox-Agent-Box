# Kết quả review + simplify — bàn giao 03/10

Nhánh `B`, PR https://github.com/nganngan99hy-coder/BoxFox-Agent-Box/pull/1 (base `main`, diff base `68ecdf0`).
Ba review vòng 2 chấm trên `46ed557`; simplify đọc trên `46ed557`. Mọi phát hiện của review đã được vá trong
`3b23fa3`, `5fabda9`, `c8b55ed`, `8f24be7` (xem §3). Báo cáo simplify là **chỉ đọc**: chưa sửa dòng nào, toàn bộ
là đề xuất cho một PR dọn dẹp riêng.

## 1. Ba review độc lập (vòng 2)

Mỗi review phụ trách một miền rủi ro. Điểm rủi ro do review agent chấm, giữ nguyên văn.

### 1.1 `review-core` — lõi Work Graph + cổng phạm vi

**Verdict: Block. Risk score: 7/10 — High.**

Tóm tắt: merge lớn nhưng test/evidence đầy đủ; rủi ro còn lại tập trung ở cổng phạm vi W8.A4.2 — bản vá vòng 1
mới bịt dạng dính liền (`-O` liền kề) mà chưa bịt ANSI-C quoting, nên cổng vẫn bị vượt bằng một biến thể cú pháp.

| # | Mức | Phát hiện | Trạng thái |
|---|---|---|---|
| F2.1 | **BLOCKING** | `$'…'`/`$"…"` vượt `classify_command()`: bash giải mã ANSI-C quoting còn `shlex.split` thì không, nên `git grep $'-O\040touch f' foo`, `find . $'-exec' touch f {} +`, `rg $'--pre=touch f' y .`, `tree $'--output=f' .` đều bị xếp `read` (đã tái lập sống: `PWNED_git2`, `PWNED_find`) | **Đã vá** (`3b23fa3`) |
| F2.2 | Low | Cờ ghi của lệnh đọc: `tree --output out.txt .` (dạng dài của `-o`), `file -C -m .` (ghi `..mgc`) | **Đã vá** (`3b23fa3`) |
| F2.3 | Low | Repair không có fallback "child mới" khi không resume được — `repairChildReason` là code không tới được | **Đã vá** (`3b23fa3`, test `test_unresumable_child_falls_back_to_a_fresh_child` ở `8f24be7`) |

### 1.2 `review-sandbox` — `verify_exec`, hợp đồng finding, deploy

**Verdict: Ship with mitigations. Risk score: 6/10 — Medium.**

Tóm tắt: thay đổi lớn, có bằng chứng đo, sandbox fail-closed, đánh đổi deploy đã ghi rõ — nhưng hai lỗi mức cao
nằm ở cổng review mới và trần tài nguyên: finding chặn đã kiểm có thể bị bỏ qua im lặng, và một snippet có thể
đẩy worker dùng chung lên ~1 GB RSS (node: nhiều GB) trong box không có `mem_limit`.

| # | Mức | Phát hiện | Trạng thái |
|---|---|---|---|
| F1 | HIGH | `apply_findings` chỉ suy lại status từ coverage + dòng `VERDICT:`, nên finding chặn hợp lệ + coverage toàn pass + `VERDICT: ok` ⇒ `status: pass` (đã tái lập) | **Đã vá** (`3b23fa3`, fixture `blocking-ignored-by-pass-verdict.json`); bản vá còn sót một đường — xem `1bd238f` |
| F2 | HIGH | `verify_exec` đệm stdout/stderr vô hạn qua `proc.communicate()`: VmHWM 20 MB → 920 MB từ snippet 3 dòng ghi 300 MB; `RLIMIT_FSIZE` không áp cho pipe | **Đã vá** (`3b23fa3`: trần 1 MiB, kill khi tràn, `outputOverflow`) |
| F3 | MED-HIGH | Snippet node vượt trần bộ nhớ: `RLIMIT_AS` chỉ áp cho python; `Buffer.alloc` 32 × 128 MiB chạy tới cùng (`DONE total MiB 4096`, exit 0) | **Đã vá** (`3b23fa3`: `RLIMIT_DATA` 2 GiB cho node) |
| F4 | MED | Blast radius của `security_opt` bị mô tả hẹp; `BOX_DEFAULT_NETWORK: "on"` đổi egress toàn box; comment "không mạng" cũ; bước 7 smoke-test báo lỗi giả sau rollback | **Đã vá** (`3b23fa3`: comment đầy đủ, smoke-test đọc biến môi trường) |
| F5 | LOW | `verify_exec` nằm trong `REPLAY_SAFE` dù có thể ra mạng | **Đã vá** (`3b23fa3`) |
| F6 | LOW | Cổng numeric nhận receipt timeout/rỗng là `computed` | **Đã vá** (`3b23fa3`, fixture `numeric-with-timed-out-verify.json`) |

### 1.3 `review-contracts` — hợp đồng tool, phục hồi, phỏng vấn bền, oracle W10

**Verdict: Ship with mitigations. Risk score: 5/10 — Medium.**

Tóm tắt: phần runtime (hợp đồng tool/phục hồi, phỏng vấn chủ nhà bền, phân trang event, preflight) chắc và ít
rủi ro; rủi ro thật nằm ở harness nghiệm thu W10 — oracle chưa nhận ra bằng chứng test thật và các chốt auto-pass
/ no-run chưa hiệu lực, nên lượt chạy 24 ca đang chạy **không thể tự nó chứng nhận** luồng cho tới khi vá F1–F3.

| # | Mức | Phát hiện | Trạng thái |
|---|---|---|---|
| F1 | HIGH | `_tests_proof` đọc `data.get('exitCode')`/`data.get('command')` ở đỉnh `tool_end`, nhưng payload thật là `{id,name,args,result}` với exit code ở `result.exit_code` và command ở `args.command` ⇒ S01/S02/S12 không bao giờ đạt | **Đã vá** (`5fabda9`, test `test_tests_proof_reads_the_real_tool_end_payload`) |
| F2 | MED-HIGH | `no_auto_pass` lọc `doc.get('stage') == 'tests'`, nhưng check doc thật có `stage ∈ {produce, execute}` + `kind == 'tests'` ⇒ `gate['autoPass']` không bao giờ > 0 | **Đã vá** (`5fabda9`) |
| F3 | MED | `state_matches('no_run', '!verified')` trả True và `classify_validity({'status': None, 'errorCode': 'NO_RUN'})` trả `quality-valid` ⇒ S11/V10 (4 ô) có thể tính là đạt dù không có run; `_missing_bundle` là code chết | **Đã vá** (`5fabda9`) |
| F4 | LOW | `tool_recovery.step_seq` chặn receipt theo `MAX(seq)` của `usage`; hard kill giữa lúc lưu transcript và emit `usage` có thể dùng lại `tool_end` cũ nếu provider dùng lại call id | **Đã vá** (`5fabda9`: so `argsHash`, test `test_reused_call_id_does_not_reuse_an_older_receipt`) |
| F5 | LOW | Docstring `shard_cells` nói quá: hai lần lặp không phải lúc nào cũng cùng một shard | **Đã vá** (`5fabda9`) |

## 2. Simplify (chỉ đọc — chưa áp dụng)

Baseline đo lại trên `46ed557`: `python3 -m pytest backend/tests -q -k work` → 970 passed, 2 failed, 1 skipped
(2 lỗi là ca môi trường `test_claude_worker_router.py`, giống baseline). Toàn bộ mục dưới đây là **đề xuất**,
không dòng nào đã bị sửa.

### 2.1 Xoá — code chết (đã kiểm: không nơi gọi, không nơi đọc)

1. `work_repair.py:80-82` — `adjudicate()`: stub identity, hook W6 chưa từng nối dây (`work_checks.validate_findings` tự hạ nhãn).
2. `work_scope.py:83` — `scope()` ghi `'root': None, 'touchSet': None`, và `:434` truyền `admission=`; cả ba khóa không nơi đọc (root thật đi qua `config.workBinding.workspace.root`).
3. `work_scope.py:521` — `apply_profile` trả thêm khóa `'workScope'`; chỉ `tools` và `promptBlock` được dùng.
4. `work_policy.py:39-42` — `git_isolated()` trùng `work_worktrees.git_mode()`; một caller ở `:101`.
5. `deploy/docker/capture.py:1044-1051` — `_video_duration_sec()` không còn ai gọi; xoá kèm test `test_capture.py:343-347`.
6. `scripts/eval/work_acceptance_bench.py:524-528 _missing_bundle` và `:846-855 _tool_names` — không nơi gọi.
7. `scripts/eval/work_finding_probe.py:79-80 digest` — không nơi gọi; `:157` tự viết lại sha256.

Tổng khoảng 40 dòng xoá thuần, không đổi hành vi.

### 2.2 Gộp — trùng lặp bỏ được mà không đổi hành vi

8. `work_checks.py:485-493 preflight` tự dựng lại thông điệp mà `capability_preflight` đã tạo; xoá 2 dòng, test hiện có vẫn khớp.
9. `work_scope.CLOSED_STATUSES` trùng `work_graph.TERMINAL_STATUSES` — import lazy hoặc giữ một bản chuẩn.
10. `work_graph.py` — hai closure `sh()` 8 dòng giống hệt (`ship_isolated` :2211-2217, `ship_legacy` :2320-2327) và hai lần kiểm nhánh giống nhau (:2202, :2294); gom thành một `_ship_sh()` + một `branch_ok()`. Lưu ý `BRANCH_RE` là `{1,120}` — đừng dùng thay cho regex ship `{1,100}`.
11. `runtime.py:6447-6457 final_claim_notices` — hai `except Exception: return []` quanh thân 3 dòng; gộp còn một.
12. `work_checks.SNAPSHOT_SCRIPT` — lọc `paths` một lần rồi lặp lại `if junk(path): continue` trong vòng hash; bộ lọc thứ hai không tới được.

### 2.3 Ghi chú — cần quyết định, không sửa tay

13. **Danh sách junk-path đã trôi lệch**: `work_worktrees.JUNK_PARTS`, `JUNK` trong `work_checks.SNAPSHOT_SCRIPT` (thêm `.venv`/`venv`, thiếu `.generated_artifacts`) và `SKIP` của `DIRTY_SCRIPT` (thiếu `test-results`/`coverage`) không còn khớp nhau, trong khi docstring `junk()` vẫn nói "snapshot() bỏ qua đúng những đường dẫn này" — docstring đã sai. Gộp chúng đổi hash snapshot/dirty của run cũ ⇒ cần quyết định + test riêng.
14. `runtime.py:3329` thay chuỗi `'cd /home/agent/workspace '` trong `evidence_gate.EVIDENCE_PROBE_COMMAND`; nếu hằng số đó bị đổi chữ, phép thay im lặng vô hiệu và cổng lại đo workspace chung. Nên dùng placeholder `{root}`.
15. `work_worktrees.py:565 orphans()` giữ bản sao thứ ba của regex worktree (`{1,72}`) cạnh `ROOT_RE` (`{1,64}`) — dùng lại `ROOT_RE`.

### 2.4 Cố ý giữ nguyên (có lý do, đã ghi chú)

- `sandbox/worker.py` tự kiểm lại `verify_exec` + `WORKTREE_ROOT_RE` — worker đi qua `docker exec`, không import được `agent_core`: đây là ranh giới box, không phải sơ suất.
- `work_scope` giữ cả `_work_turn_scopes` trong bộ nhớ lẫn `config.workTurnScope` — có chủ đích (bản trong bộ nhớ thắng) để chống ghi config cũ.
- `apply_profile` vừa nhét prompt block vừa kiểm ở dispatch — belt-and-braces có chủ đích.
- Các hằng số hợp đồng `verify_exec` lặp giữa `verify_exec.py` và `worker.py` — cùng lý do ranh giới box.

## 3. Đã vá sau review (commit)

| Commit | Nội dung |
|---|---|
| `3b23fa3` | Bịt `$'…'`/`$"…"` + cờ ghi của lệnh đọc; finding chặn không bị hạ về `pass`; trần output 1 MiB + kill khi tràn; `RLIMIT_DATA` 2 GiB cho node; `verify_exec` ra khỏi `REPLAY_SAFE`; receipt timeout không tính `computed`; comment `security_opt` + smoke-test; repair rơi về child mới |
| `5fabda9` | Oracle W10 đọc đúng payload `tool_end`, `no_auto_pass` theo `kind`, `no_run` không khớp `!verified`, `_missing_bundle` được dùng, `tool_recovery` so `argsHash`, sửa docstring `shard_cells` |
| `c8b55ed` | `--rescore`: chấm lại 24 lượt từ `bundle.json` đã lưu, không chạy lại model |
| `8f24be7` | Test fallback child mới của repair; bench dừng hẳn task runtime cũ trước khi restart (S09 từng ném `Cannot operate on a closed database`) |
| `1bd238f` | **F1 còn sót** (do `test-workgraph` tìm khi kiểm chứng lại): cổng retry `status = error` áp cho cả `WORK_FINDING_IGNORED`, nên lượt thử mới có thể bỏ finding đã kiểm rồi cho artifact pass (tái lập end-to-end, e2e 8/12 → 12/12). Nay chỉ `WORK_FINDING_UNCITED` mới retry; kèm test `test_retry_gate_only_fires_for_an_uncited_report` |

Mọi phát hiện của ba review đều ở trạng thái **đã vá**; các mục §2 của simplify vẫn **chưa áp dụng** (đề xuất PR riêng).
