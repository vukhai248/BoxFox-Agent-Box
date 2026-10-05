# W11.P0c + P1/P2/P3 — Thứ tự áp dụng chỉ dẫn và bản vá prompt cho các vai còn lại

> Nguồn yêu cầu: `docs/plan/Work-Graph-fix.md:2829` (P0c), `:2830` (P1), `:2831` (P2), `:2832` (P3).
> Đầu vào bắt buộc: `docs/plan/W11-p0b-inventory.md` (388 dòng) — §5 là danh sách xung đột; tài liệu
> này xử lý **§5.4, §5.5, §5.6, §5.7** cho **chín vai còn lại**: `explore, plan, plan-review, design,
> build, debug, review, testing, research`. Nhánh Simplify (§5.1) và hai văn bản vendor (§5.2 `AGENT.md`
> đã sửa, §5.3 skill `simplify-code` đã sửa) đã xong trước — không làm lại.
>
> Phương pháp: đọc mã tĩnh + test tất định trên prompt **ĐÃ LẮP**; không gọi model, không chạy mạng,
> không đo lường mới. Mọi khẳng định kèm `file:line`; câu trích giữ nguyên văn tiếng Anh trong code,
> văn xuôi quanh nó là tiếng Việt. Không có hidden reasoning, không có bí mật trong tài liệu này.

## 0. Source pin và trạng thái cây

- Repo: `/code/i3abyxinhdepqua-lang/BoxFox-Agent-Box`, nhánh `vorflux/w10-w12-completion`.
- HEAD khi làm bản vá: `4758fd6` — "docs(w6q): adjudication 60 dòng trên corpus đã lưu…". Cây còn thay
  đổi chưa commit của các phiên song song (`scripts/eval/work_acceptance_bench.py`,
  `scripts/eval/fixtures/work_acceptance/S09.json`, `backend/tests/unit/test_work_acceptance_bench.py`)
  — **không nằm trong phạm vi bản vá này** và không bị chạm tới.
- File trong phạm vi bản vá:

| File | SHA256 trước | SHA256 sau |
|---|---|---|
| `backend/src/agentbox/agent_core/roles.py` | `5eb92b26cb119ebf3b47cb21909c9cdff68aa4901e6c4ca21def14cc380c72f3` | `56dbfbeabe8069ccb7dd5c67ecafb80f961405ce6b21916e1c85678d3bf69b2d` |
| `backend/tests/unit/test_work_prompt_contracts.py` | `ebeff2b59c4607b381542ccc0491c4b3e5655956d9971d79522fb4276bd1874a` | `7ecca2b23ed58cb441748c35559fb5685db0636f49576576d5600723e8391c25` |
| `docs/plan/W11-p1-p2-report.md` | — (tệp mới) | tài liệu này |

- Kích thước diff: `roles.py` 11 dòng đổi (11 chèn / 11 xóa, không đổi số dòng), `test_work_prompt_contracts.py` +101 dòng.
- Không chạy lệnh ghi git nào; không commit; không đổi nhánh.

## 1. P0c — Thứ tự áp dụng chỉ dẫn (precedence audit)

### 1.0 Thang thứ tự và luật sửa

Năm lớp cùng nói với một phiên con, theo thứ tự mạnh → yếu **khi đã lắp vào prompt**:

| # | Lớp | Nơi phát ngôn | Ai sở hữu |
|---|---|---|---|
| 1 | **owner assignment** | phần `Deliverable`/rubric trong prompt con (`work_prompts.py:209-218`, `:226-263`) | chủ nhà / main |
| 2 | **backend decision** | harness tự làm: ghi tài liệu sau whole-plan review (`roles.py:248`), ép `verdict`, hạ finding không receipt | `work_graph.py`, `work_checks.py`, `runtime.py` |
| 3 | **runtime permission** | bộ công cụ hiệu lực (`roles.allowed_tools`, `roles.work_check_tools`), cổng dispatch (`runtime.py:4850`, `:4863-4866`, `:5781`), scope (`work_scope.py`) | `runtime.py` / `work_scope.py` |
| 4 | **role instruction** | `ROLES[vai].instructions` — protocol, output requirement, `STRICT PROHIBITION` | `roles.py` |
| 5 | **skill text** | nội dung skill vendor được nạp (danh sách, không phải hợp đồng) | `vendor/hermes/...` |

Luật áp dụng cho W11: **sửa lớp 4/5 cho khớp lớp 1–3 đã quyết, không nâng lớp 4 lên thành một system
prompt cạnh tranh** (`Work-Graph-fix.md:2829`: "ghi xung đột để sửa đúng lớp, không thêm một system
prompt cạnh tranh"), và **không đổi lớp 1–3 trong W này** (`:2831` P2). Vì vậy mọi xung đột mà bản sửa
đúng đắn nằm ở lớp 1–3 đều bị đánh dấu **OUT OF SCOPE** kèm lý do.

Ba câu hỏi kiểm tra bắt buộc của P0c (`:2829`) — "câu lệnh imperative từ role/skill có kéo dry-run
thành edit, review thành tự apply hoặc feedback thành consent không" — được trả lời ở §1.5.

### 1.1 §5.4 — Hai bộ heading cùng tồn tại trong một prompt

**Lớp sở hữu bản sửa: `role instruction` (lớp 4).** Trong phạm vi.

Trích dẫn (HEAD `4758fd6`, số dòng không đổi sau bản vá):

- `roles.py:246` (`WORK_PRODUCER_NOTE`): `"The task-specific deliverable overrides generic output headings."`
- `roles.py:56-60` (`EXPLORE_INSTRUCTIONS`): `"4. Output Requirement: Return a structured Markdown report with:"` + bốn heading chung `### Architecture & Key Files` / `### Dependencies & Contracts` / `### Findings & Evidence` / `### Unknowns & Risks`.
- `roles.py:155-159` (`TESTING_INSTRUCTIONS`): `"4. Output Requirement: Return a structured Markdown report with:"` + `### Test Execution Summary` / `### Detailed Test Case Logs` / `### Edge Cases & Failure Scenarios Tested` / `### Visual & Artifact Evidence`.
- Cùng khuôn ở `roles.py:71` (plan), `:85` (design), `:99` (build), `:113` (debug), `:127` (review), `:179` (research), và biến thể `roles.py:226` (plan-review, `"return a Markdown report"`).
- Không có cổng runtime nào kiểm hình dạng output theo deliverable: `work_graph.py`/`work_checks.py` chỉ chấm theo rubric chữ (`work_prompts.rubric`), không parse heading.

**Câu chữ cũ có thể khiến model làm gì:** nhận hai chuẩn trong cùng một prompt — mở báo cáo bằng bốn
heading chung (đúng như instruction ra lệnh) rồi mới ghép deliverable của node vào, hoặc bỏ luôn
deliverable vì heading chung được viết như mệnh lệnh không điều kiện. Đây đúng là "heading rỗng" mà
P1 cấm (`Work-Graph-fix.md:2830`: "tránh heading rỗng") và làm reviewer chấm thiếu mục.

**Bản sửa (lớp 4):** biến bộ heading chung thành **mặc định có điều kiện** — chỉ dùng khi assignment
không tự cấp deliverable. Bộ heading **không bị xóa** (không mất năng lực), `WORK_PRODUCER_NOTE` không đổi.

### 1.2 §5.5 — `DECISION` được quảng cáo nhưng runtime từ chối (mức con)

**Lớp sở hữu bản sửa: `runtime permission` (lớp 3).** **OUT OF SCOPE** cho W này.

Trích dẫn:

- `roles.py:9`: `DECISION = frozenset({'ask_user', 'request_approval'})`; `roles.py:14-15`: `READ = ... | DECISION | PEER` ⇒ **mọi vai con** (`explore, plan, plan-review, design, build, debug, review, simplify, testing, research`) được **liệt kê** hai công cụ này (`roles.py:277-298`).
- `runtime.py:5483-5490` — `decision()` từ chối mọi phiên con: `"DECISION_UNAVAILABLE: a delegated session cannot ask the user; decide from your own evidence"` (raise tại `:5489-5490`); bản sao thứ hai trong `interview()` tại `runtime.py:5851`.
- `roles.py:245` (`WORK_PRODUCER_NOTE`) đã nhắc đúng luật này cho đường Work Graph: `"You cannot delegate or call ask_user/interview directly..."`.

**Câu chữ cũ có thể khiến model làm gì:** ở **đường delegate thường** (không có `WORK_PRODUCER_NOTE`
trong prompt), con thấy `ask_user` trong danh sách công cụ, gọi nó, nhận lỗi `DECISION_UNAVAILABLE`,
mất một bước và có thể kết luận sai là "không hỏi được chủ" thay vì ghi câu hỏi vào kết quả
(`work_report needs_user`). Đây là lớp "quyền quảng cáo mạnh hơn quyền hiệu lực".

**Vì sao OUT OF SCOPE:** bản sửa đúng lớp là bỏ `DECISION` khỏi `READ` (hoặc khỏi bộ công cụ hiệu lực
của phiên con) — nhưng P2 cấm tường minh: *"no change to tool sets, `READ`/`WRITE`/`DECISION` membership,
scope gates…"* (`Work-Graph-fix.md:2831`). Bản sửa ở lớp 4 (thêm câu "bạn không hỏi được chủ" vào từng
instruction) bị hai lý do chặn: (a) nó **thêm một luật mới** ở lớp vai thay vì sửa luật sai lớp, đúng
thứ P0c cấm; (b) ở đường Work Graph — nơi luật này quan trọng — câu ấy **đã có** (`roles.py:245` và
khối `Bound Work Graph child` của `with_work_graph`, `roles.py:257`), nên nó chỉ vá được đường delegate
thường với giá là chép luật sang mười một chỗ. **Đề xuất riêng (cần chủ nhà duyệt):** một thay đổi lớp
quyền tách khỏi W11 — cắt `DECISION` khỏi `READ` và để `allowed_tools` cộng lại cho phiên chính, hoặc
đổi mô tả `ask_user`/`request_approval` trong `tool_contracts.py` để nói rõ phiên con bị từ chối.

### 1.3 §5.6 — `plan` được cấp `write_plan` nhưng bị cấm gọi trong Work Graph

**Lớp sở hữu bản sửa: `role instruction` (lớp 4) + xác nhận `backend decision` (lớp 2).** Trong phạm vi.

Trích dẫn:

- Cấp quyền: `roles.py:279` — `Role('plan', 'Plan', PLAN_INSTRUCTIONS, READ | {'write_plan'})`.
- Cấm: `roles.py:248` (`WORK_PLAN_NOTE`) — `"Do NOT call `write_plan` for a Work Graph node — the harness writes the documents after the whole-plan review."`
- Bước 5 cũ: `roles.py:76` — `"5. Document Gate: `write_plan` refuses a plan without those sections and writes NOTHING on refusal; fix the markdown it names and call it again."` — **không có ngoại lệ nào**, nên nó mời gọi gọi `write_plan` ngay trong node.
- Cổng dispatch: `runtime.py:4863-4864` chặn cứng node **check** (`'WORK_CHECK_READ_ONLY: checker cannot modify source or delegate'`), nhưng **không có nhánh nào chặn `write_plan` ở node produce/execute** (đã quét `write_plan` trong `runtime.py`/`work_scope.py`; chỉ có nhánh `plan_workflow` nội bộ). Ở đường legacy, `plan_workflow.validate_write()` (`plan_workflow.py:711-740`) từ chối con bằng `PLAN_ROOT_WRITER_REQUIRED` — cũng không phải đường Work Graph.

**Câu chữ cũ có thể khiến model làm gì:** node produce `plan` gọi `write_plan`, ghi một tài liệu do con
viết trong khi harness cũng ghi tài liệu sau whole-plan review (`roles.py:248`) ⇒ hai bản tài liệu,
lệch identity/version, và tài liệu con ghi không đi qua cổng duyệt.

**Bản sửa (lớp 4):** giữ nguyên đường cũ (câu mô tả Document Gate vẫn còn) và thêm ngoại lệ tường minh
cho node Work Graph — cùng nội dung với `WORK_PLAN_NOTE`, ở đúng chỗ phát ngôn ra mệnh lệnh. Quyền
`READ | {'write_plan'}` **không đổi**; `WORK_PLAN_NOTE` **không đổi**.

### 1.4 §5.7 — Testing phải viết test, note lại phán "Do NOT edit source files"

**Lớp sở hữu bản sửa: `role instruction` (lớp 4 — định nghĩa đối tượng bị cấm).** Trong phạm vi.

Trích dẫn:

- `roles.py:150` (`TESTING_INSTRUCTIONS`): `"Your mission is to write and execute rigorous automated tests, visual browser checks, and terminal verifications."`
- `roles.py:289`: `Role('testing', 'Testing', TESTING_INSTRUCTIONS, WRITE | VISUAL, ('test-driven-development',))` — `WRITE` gồm `file_write`, `file_edit_block` (`roles.py:16`).
- `roles.py:252` (`WORK_EXEC_REVIEWER_NOTE`): `"Do NOT edit source files; END with exactly one line `VERDICT: ok` or `VERDICT: revise`."`
- Cổng dispatch: node check bị `WORK_CHECK_READ_ONLY` cấm ghi (`runtime.py:4863-4864`); node produce/execute của `testing` **mở** `file_write` thật.

**Câu chữ cũ có thể khiến model làm gì:** prompt không định nghĩa "source file", nên hai lượt đọc cùng
một câu theo hai cách trái ngược — (a) lượt testing (nhất là lượt kiểm, nơi công cụ ghi đã bị cắt) hiểu
là cấm cả **file test** ⇒ không viết test, đúng thứ vai phải làm; (b) lượt sản xuất hiểu "source file"
chỉ là file không phải test ⇒ sửa mã nguồn sản xuất để cho test xanh. (b) không có cổng nào chặn ở node
produce.

**Bản sửa (lớp 4):** chỉ định rõ đối tượng — `"Do NOT edit the production source under test"` — nên câu
vẫn cấm đúng thứ cần cấm (mã nguồn sản xuất) mà không cấm việc viết/sửa file test. Không đổi bộ công
cụ, không thêm cấm đoán mới, không đụng `WORK_CHECK_READ_ONLY`.

### 1.5 Ba câu hỏi biến dạng bắt buộc của P0c

| Biến dạng | Kết quả kiểm trên chín vai | Xử lý |
|---|---|---|
| **dry-run → edit** | `TESTING`/`SIMPLIFY` từng ra lệnh sửa bất kể nhiệm vụ (Simplify đã sửa trước; Testing chỉ còn §5.7). `DEBUG` bước 3 `"Apply the smallest necessary fix"` (`roles.py:111`) không có điều kiện, nhưng đường Work Graph đã có **ba lớp mạnh hơn**: `WORK_PRODUCER_NOTE` (`roles.py:245` — "Diagnosis-only debug does not authorize a patch"), deliverable `work_prompts.deliverable('debug')` ("diagnosis-only assignments must not edit files"), và cổng dispatch `WORK_DIAGNOSTIC_READ_ONLY` (`runtime.py:4865-4866`). `EXPLORE`/`REVIEW`/`PLAN-REVIEW`/`RESEARCH-REVIEW` là READ-ONLY ở cả text lẫn quyền. | **Không sửa thêm** (xem §4): đã có luật ở lớp 1–3; thêm câu nữa là lớp thứ ba, ngoài danh sách xung đột §5. |
| **review → self-apply** | `REVIEW_INSTRUCTIONS` (`roles.py:134`) và `PLAN_REVIEW_INSTRUCTIONS` (`roles.py:237`) đều kết bằng `STRICT PROHIBITION` cấm sửa file; `RESEARCH_REVIEW_INSTRUCTIONS` cấm sửa dossier và cấm `source_add` (`roles.py:190`). Không vai phản biện nào có `file_write` trong bộ công cụ. | **Không có xung đột** — không sửa. |
| **feedback → consent** | Không instruction nào của chín vai nói rằng phản hồi/duyệt của reviewer hay câu trả lời cũ là **quyền tiếp tục**: luật đó nằm ở `WORK_PRODUCER_NOTE` ("On `revise` you are run again with the findings") và ở khối `Bound Work Graph child` (`roles.py:257` — "Main owns interviewing/routing; an explicit matching grant lets the backend publish your questions…"). `BUILD` bước 5 giữ đúng luật trung thực (`"Never claim that unrun tests have passed"`, `roles.py:104`). | **Không có xung đột** — không sửa. |

## 2. P1 — Bảng current → proposed → lý do → test

Mười một dòng cho chín vai (cùng khuôn với bảng Simplify ở `Work-Graph-fix.md:2836-2841`). Cột
"Current" là văn bản tại HEAD `4758fd6`; số dòng không đổi sau bản vá nên `proposed` nằm đúng dòng cũ.

| # | Current (`roles.py`, HEAD `4758fd6`) | Proposed | Lý do | Test |
|---|---|---|---|---|
| 1 | `"4. Output Requirement: Return a structured Markdown report with:"` (Explore, `:56`) | `"4. Output Requirement: Unless the assignment supplies its own deliverable, return a structured Markdown report with:"` | §5.4 — bộ heading chung không được là mặc định duy nhất khi assignment đã cấp deliverable (P1: "tránh heading rỗng") | `test_w11_generic_headings_yield_to_the_assignment_in_the_assembled_prompt` |
| 2 | `"4. Output Requirement: Return a structured Markdown report with:"` (Plan, `:71`) | như #1 | như #1 | như #1 |
| 3 | `"5. Document Gate: `write_plan` refuses a plan without those sections and writes NOTHING on refusal; fix the markdown it names and call it again."` (Plan, `:76`) | thêm câu: `"In a Work Graph node you must NOT call `write_plan` at all: the harness writes the documents after the whole-plan review."` | §5.6 — bước 5 mời gọi `write_plan` không ngoại lệ, mâu thuẫn `WORK_PLAN_NOTE`; không cổng dispatch nào chặn ở node produce | `test_w11_plan_forbids_write_plan_inside_a_work_graph_node_only` |
| 4 | `"5. Output Requirement: return a Markdown report. For a plan target use these sections:"` (Plan-review, `:226`) | `"5. Output Requirement: unless the assignment supplies its own deliverable or rubric, return a Markdown report. For a plan target use these sections:"` | §5.4 — cùng lớp; bản plan-review có rubric riêng nên điều kiện nêu cả rubric | như #1 |
| 5 | `"4. Output Requirement: Return a structured Markdown report with:"` (Design, `:85`) | như #1 | như #1 | như #1 |
| 6 | `"5. Output Requirement: Return a structured Markdown report with:"` (Build, `:99`) | như #1 | như #1 | như #1 |
| 7 | `"5. Output Requirement: Return a structured Markdown report with:"` (Debug, `:113`) | như #1 | như #1 | như #1 |
| 8 | `"3. Output Requirement: Return a structured Markdown report with:"` (Review, `:127`) | như #1 | như #1 | như #1 |
| 9 | `"4. Output Requirement: Return a structured Markdown report with:"` (Testing, `:155`) | như #1 | như #1 | như #1 |
| 10 | `"Do NOT edit source files; END with exactly one line…"` (`WORK_EXEC_REVIEWER_NOTE`, `:252`) | `"Do NOT edit the production source under test; END with exactly one line…"` | §5.7 — prompt không định nghĩa "source file"; lượt kiểm có thể tưởng bị cấm viết file test, lượt sản xuất có thể tưởng được sửa mã nguồn | `test_w11_testing_review_names_the_source_it_must_not_edit` |
| 11 | `"9. Output Requirement: Return a structured Markdown report with:"` (Research, `:179`) | như #1 | như #1 | như #1 |

Bất biến đã giữ (không có dòng nào trong bảng đụng tới):

- Không đổi tool set, `READ`/`WRITE`/`DECISION` membership, `ROLE_SKILLS`, scope gate, budget, scheduler,
  contract, DAG, interview grant hay `work_policy` — đúng ranh giới P2 (`Work-Graph-fix.md:2831`).
- Không sửa vendor skill (`simplify-code/SKILL.md`) hay `AGENT.md` (đã xong ở §5.2/§5.3).
- Không đổi cơ chế `with_work_graph()` (`roles.py:255-261`): note vẫn được chèn TRƯỚC dòng
  `STRICT PROHIBITION` cuối (hoặc nối vào cuối khi vai không có câu chốt — `debug`).
- Không xóa bộ heading chung nào; không xóa capability nào; không nâng token/time.

## 3. P2 — Bản vá đã thi công (chỉ text prompt)

Mười một dòng đổi trong `roles.py`, không đổi số dòng, không đổi cấu trúc:

| Dòng (sau bản vá) | Vai / khối | Nội dung |
|---|---|---|
| `:56` | Explore | `Output Requirement` có điều kiện |
| `:71` | Plan | `Output Requirement` có điều kiện |
| `:76` | Plan | ngoại lệ Work Graph cho `write_plan` |
| `:85` | Design | `Output Requirement` có điều kiện |
| `:99` | Build | `Output Requirement` có điều kiện |
| `:113` | Debug | `Output Requirement` có điều kiện |
| `:127` | Review | `Output Requirement` có điều kiện |
| `:155` | Testing | `Output Requirement` có điều kiện |
| `:179` | Research | `Output Requirement` có điều kiện |
| `:226` | Plan-review | `Output Requirement` có điều kiện (kèm "or rubric") |
| `:252` | `WORK_EXEC_REVIEWER_NOTE` | `production source under test` thay cho `source files` |

Câu điều kiện dùng chung một câu chữ cho cả chín vai (riêng plan-review hạ chữ đầu vì câu gốc viết
thường): `"Unless the assignment supplies its own deliverable, return a structured Markdown report with:"`.
Bộ heading theo sau **không đổi một ký tự**.

## 4. Việc cố ý KHÔNG làm, kèm lý do

| Việc | Lý do |
|---|---|
| Bỏ `DECISION` khỏi `READ` / khỏi bộ công cụ hiệu lực của phiên con (§5.5) | **OUT OF SCOPE**: sửa lớp `runtime permission`, P2 cấm đổi tool set và `READ`/`WRITE`/`DECISION` membership. Ở đường Work Graph luật đã có (`roles.py:245`); đề xuất một thay đổi lớp quyền riêng, cần chủ nhà duyệt. |
| Thêm câu "con không hỏi được chủ" vào từng instruction | Cùng lý do trên, cộng luật P0c "không thêm một system prompt cạnh tranh" và luật P2 "không xóa capability" — bản sửa đúng nằm ở lớp quyền. |
| Sửa `RESEARCH_REVIEW_INSTRUCTIONS` (cùng lớp §5.4) | Ngoài danh sách chín vai được duyệt cho bản vá này (`explore, plan, plan-review, design, build, debug, review, testing, research`). Rủi ro thấp hơn vì hợp đồng đầu ra của vai đã do `WORK_REVIEWER_NOTE` + dòng `VERDICT` chốt; nếu chủ nhà muốn đồng bộ, đây là **một dòng P1 bổ sung**, không phải việc của bản vá này. |
| Sửa `SIMPLIFY_INSTRUCTIONS` | Nhánh đã xong trước (`test_work_simplify_prompt.py`); câu `Output Requirement` của Simplify đã mang sẵn ngoặc điều kiện "(or Findings for a survey-only assignment; …)". |
| Sửa `AGENT.md` và `vendor/hermes/.../simplify-code/SKILL.md` | §5.2/§5.3 đã sửa và có test ghim (`test_agent_identity_text_matches_the_current_policy`, `test_simplify_skill_keeps_dropped_findings_visible`). |
| Đổi `DEBUG_INSTRUCTIONS` bước 3 (`"Apply the smallest necessary fix"`) | Không nằm trong §5; trên đường Work Graph đã có **ba lớp mạnh hơn** cùng chặn: `WORK_PRODUCER_NOTE` (`roles.py:245`), deliverable `work_prompts.deliverable('debug')`, và cổng dispatch `WORK_DIAGNOSTIC_READ_ONLY` (`runtime.py:4865-4866`). Thêm câu ở lớp 4 sẽ là lớp thứ ba. |
| Đổi `WORK_PRODUCER_NOTE` / `WORK_PLAN_NOTE` / `WORK_REVIEWER_NOTE` | Ba note đang nói **đúng** chính sách đã quyết; lỗi nằm ở instruction của vai, nên bản vá đặt ở đó. |
| Đổi `with_work_graph()` hay `plan_workflow.validate_write()` | Là cơ chế/backend decision, không phải xung đột chỉ dẫn; P2 cấm đổi contract/DAG. |
| Bất cứ thứ gì cần đổi scheduler, budget, scope gate, contract, interview grant | P2 cấm tường minh; không mục nào của §5.4/§5.6/§5.7 cần tới chúng. |

## 5. P3 — Test tất định trên prompt ĐÃ LẮP

Bốn bài kiểm mới trong `backend/tests/unit/test_work_prompt_contracts.py` (mục cuối tệp). Chúng dựng
**system prompt thật** của từng vai con qua `HarnessRuntime` + `SessionStore` (dùng lại
`Executor`/`Model`/`system_prompt` của `test_runtime_prompt.py`) rồi khẳng định trên chuỗi đã lắp —
không chỉ tìm một chuỗi trong template:

| Test | Khẳng định trên prompt đã lắp |
|---|---|
| `test_w11_generic_headings_yield_to_the_assignment_in_the_assembled_prompt` | Mỗi vai trong chín vai có câu điều kiện; **không** vai nào còn câu `Output Requirement` không điều kiện; bộ heading cũ vẫn còn (Explore/Debug/Plan-review/Research) |
| `test_w11_plan_forbids_write_plan_inside_a_work_graph_node_only` | Prompt của `plan` chứa cả ngoại lệ mới, cả `WORK_PLAN_NOTE`, cả câu Document Gate cũ; quyền `READ \| {'write_plan'}` không đổi |
| `test_w11_testing_review_names_the_source_it_must_not_edit` | Prompt của `testing` còn mission viết test, note nói `production source under test`, câu cũ `Do NOT edit source files` đã biến mất, `file_write`/`file_edit_block` vẫn thuộc vai |
| `test_w11_work_graph_note_never_lands_after_the_roles_closing_prohibition` | Mỗi vai nhận ít nhất một note Work Graph; note nằm TRƯỚC câu `STRICT PROHIBITION` cuối (vai `debug` không có câu chốt ⇒ note nằm sau phần protocol) |

Không assertion cũ nào bị nới, sửa hay xóa; hai bài của đợt P0c trước
(`test_agent_identity_text_matches_the_current_policy`, `test_simplify_skill_keeps_dropped_findings_visible`)
giữ nguyên. Marker parser (`## Knowledge requests`, `VERDICT: ok`, `REVISE <nodeId>:`), đường
read-only của checker, output tiếng Việt và đường resume không bị chạm (không test nào trong ba nhóm
đó phải sửa để xanh).

**Kết quả chạy (nguyên văn):**

```
$ cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_work_prompt_contracts.py tests/unit/test_runtime_prompt.py tests/unit/test_work_simplify_prompt.py tests/unit/test_work_producer_quality.py tests/unit/test_work_checks.py -q
........................................................................ [ 52%]
.................................................................        [100%]
137 passed in 53.57s
```

Lần chạy đầu của cùng lệnh cho `135 passed in 51.34s`; hiệu số 2 bài là do một phiên song song thêm
test vào `backend/tests/unit/test_work_producer_quality.py` **trong lúc tôi chạy** (cùng đợt đang sửa
`runtime.py`/`work_graph.py` cho #6474 — ngoài phạm vi bản vá này, không file nào của tôi bị chạm).

```
$ cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_plan_review_role.py tests/unit/test_research_review_role.py tests/unit/test_work_finding_citations.py tests/unit/test_design_prompt_resume.py tests/unit/test_work_graph.py -q
........................................................................ [ 77%]
.....................                                                    [100%]
93 passed in 48.08s
```

```
$ cd backend && PYTHONPATH=src .venv/bin/python -m pytest tests/unit/test_work_prompt_contracts.py -q
................................................                         [100%]
48 passed in 6.97s
```

## 6. Ghi chú tuân thủ và phần còn lại

- Tài liệu chỉ chứa: vị trí mã, chuỗi prompt (văn bản dành cho model), hash nguồn, kết quả test. Không
  có hidden reasoning, không có bí mật (không token/key/nội dung riêng tư).
- Không gọi model, không chạy mạng, không đo lường mới; không lệnh ghi git nào; mọi thay đổi nằm trong
  working tree chưa commit.
- Phần còn lại (không thuộc bản vá này): P4 (đánh giá đầu ra trên corpus/pilot cùng nguồn–tools–ngân
  sách) và P5 (chốt checkpoint) của `Work-Graph-fix.md:2833-2834`; mục §5.5 nếu chủ nhà duyệt một thay
  đổi lớp quyền; và dòng P1 bổ sung cho `research-review` nếu muốn đồng bộ §5.4.

