# W11.P0b — Inventory thực: prompt lắp cuối, role instructions, skill đã nạp, tools và scope hiệu lực

> Yêu cầu nguồn: `docs/plan/Work-Graph-fix.md:2828` — "**P0b — inventory thực:** ghi source pin, prompt lắp cuối cùng của các đường Work Graph/delegate/custom/resume/check, role instructions, skill đã nạp, tools và scope hiệu lực. Bảo vệ bí mật; không lưu hidden reasoning. Nêu từng chỉ dẫn trùng/xung đột và bằng chứng đường gọi, tránh suy từ tên skill."
>
> Phương pháp: đọc tĩnh mã nguồn (read-only, không chạy runtime, không gọi model). Mọi khẳng định đều kèm `file:line`. Các câu trích giữ nguyên văn tiếng Anh trong code; văn xuôi quanh nó là tiếng Việt. Không ghi lại hidden reasoning; không có bí mật nào bị đưa vào tài liệu này (không chứa API key, token, hay nội dung riêng tư của người dùng).

## 0. Source pin

- Repo: `/code/i3abyxinhdepqua-lang/BoxFox-Agent-Box`
- Branch: `vorflux/w10-w12-completion`
- HEAD: `4e0923dae902c50906651773c584bfa8ccaaf3c2` — "docs(plan): add adaptive W12 and unified cloud handoff prompt"
- Working tree: HEAD cộng thay đổi chưa commit. Trạng thái tại thời điểm chốt inventory (2026-10-02, ~20:45Z):
  - Modified: `backend/src/agentbox/agent_core/roles.py` (⚠ bị sửa GIỮA PHIÊN đọc — xem §0.1), `backend/tests/unit/test_work_acceptance_bench.py`, `frontend/src/types/provider.ts`, `router/src/providers/opencode.mjs`, `router/tests/model-metadata.test.mjs`, `router/tests/opencode.test.mjs`, `router/tests/thinking-mapping.test.mjs`, `scripts/eval/fixtures/work_acceptance/S04.json`, `scripts/eval/fixtures/work_acceptance/S05.json`, `scripts/eval/work_acceptance_bench.py`
  - Untracked: `backend/tests/unit/test_work_simplify_prompt.py`, `docs/plan/W12-metadata-inventory.md`, `router/package-lock.json`, `router/src/providers/opencode-capabilities.mjs`
- SHA256 các file được trích dẫn trực tiếp (trạng thái working tree lúc đọc):

| File | SHA256 |
|---|---|
| `AGENT.md` | `eae22c541c7e86ea1aa82d578d878d1c6226f700f2845032bc840d795c1f9b29` |
| `backend/src/agentbox/agent_core/work_prompts.py` | `3da58b4312ee55b56b5372b7bcb534630f1728410b8929be035ed7c7e240b67d` |
| `backend/src/agentbox/agent_core/work_graph.py` | `304001f8c51fe9a1c71a1da81bd313b42c78ecff9e35e0ebd95eda785d2abd7e` |
| `backend/src/agentbox/agent_core/roles.py` | `5eb92b26cb119ebf3b47cb21909c9cdff68aa4901e6c4ca21def14cc380c72f3` |
| `backend/src/agentbox/agent_core/runtime.py` | `ada990fc1fe336d11eaa1f4e026499181e36236ebd90fe67a8ac95f862062c4a` |
| `backend/src/agentbox/agent_core/tool_groups.py` | `5f0da30815b4697e7e8eab6aab8fbf5951fae343667eab343410fb0db70d4e4e` |
| `backend/src/agentbox/agent_core/work_scope.py` | `08213245926cef28c6fc0b8857440c3d109096496737f7b46ea13aeac1317259` |
| `backend/src/agentbox/agent_core/work_policy.py` | `3bf662636406847aa35d5442697ba0acebaff781a3ede3a37bfc69d0d0fb2979` |
| `backend/src/agentbox/agent_core/work_checks.py` | `b457d5078aa718c2d4f3cf303b192a95ddb25a265b0c83ccad22151eff28e3f5` |
| `backend/src/agentbox/agent_core/work_feedback.py` | `98feff7893571821c4d6fac3ff9d4320d25f894866986a8ec72e125a4ad1099e` |
| `backend/src/agentbox/agent_core/tool_contracts.py` | `7e87d70e588575362f04b1d36f0a4431cedaffae6a6c30a3755528da7ccfac94` |
| `backend/src/agentbox/skills/commands.py` | `bd31075df0845b7d96637f2f7e493cc99689cb73c97a543a14177da939d19173` |
| `backend/src/agentbox/skills/catalog.py` | `eddef1a6e48588cb6174665711c9000b7d796eef7f333266059580084c965057` |
| `backend/src/agentbox/skills/runtime_commands.py` | `0cbf0d5c0d0d84a815d697e2ed71a61df26cb5ee04dec18da9c6b20b3dd11146` |
| `backend/src/agentbox/vendor/hermes/skills/software-development/simplify-code/SKILL.md` | `1a1937535557c38c57c82cb8d9aea12b77cb59d31d14d3af2731f2a08fc3f108` |

- Số dòng các file lõi (để định vị nhanh): `work_prompts.py` 333, `work_graph.py` 2458, `roles.py` 359 (hậu sửa), `runtime.py` 7257, `tool_groups.py` 68, `work_scope.py` 535, `work_policy.py` 126, `AGENT.md` 64.

### 0.1 Cảnh báo trạng thái sống: `roles.py` bị sửa giữa phiên đọc

- Lúc bắt đầu phiên inventory, `git status` **chưa** liệt kê `roles.py`; bản đọc đầu tiên thấy `SIMPLIFY_INSTRUCTIONS` bản cũ ("guarantee zero behavioral regressions" / "100% passing tests").
- Trong phiên, file được một tiến trình khác sửa: mtime `2026-10-02 20:44:17Z` cho `roles.py` và `2026-10-02 20:44:44Z` cho file test mới `backend/tests/unit/test_work_simplify_prompt.py` (file test tự mô tả là "W11.PROMPT (P1/P3)"). Đây là công việc W11.P1 đang triển khai song song, chưa commit.
- Hệ quả cho tài liệu này: mọi trích dẫn `roles.py` dùng **số dòng của working tree hiện tại (hậu sửa)**. Chỗ nào liên quan bản cũ sẽ ghi rõ `HEAD:roles.py:<dòng>` (đọc bằng `git show HEAD:...`).
- Lead §37.2 #1 vì vậy có hai trạng thái — xem §5.1.

## 1. Prompt lắp cuối cùng theo từng đường

### 1.0 Bảng định tuyến đường → hàm lắp prompt

| Đường | Hàm lắp prompt | Vị trí |
|---|---|---|
| System prompt mọi phiên | `create()` — prompt = identity + role + required skills + enabled skills + answer length (+ directives) | `runtime.py:1965-1977` |
| Work Graph producer (produce/execute) | `work_graph.spawn()` → `producer_goal()`; `run_stage()` chọn deliverable | `work_graph.py:1106-1185`, `1212-1250`, `1319-1502` |
| Work Graph reviewer (node/whole) | `reviewer_goal()` + `work_checks.judge()` / `whole_review_goal()` | `work_graph.py:1252-1271`; `work_checks.py:715-918` |
| Knowledge (helper lookup) | `answer_knowledge()` | `work_graph.py:1273-1317` |
| Delegate thường (không Work Graph) | `runtime.delegate()` — child user prompt parts + contract | `runtime.py:6808+`, parts `7052-7076` |
| Resume | nhánh resume trong `spawn()`; `work_feedback.resume_child` | `work_graph.py:1152-1157`; `work_feedback.py` |
| Custom command (`/explore`…) | `_command_task()` trong `runtime_commands.py` | `runtime_commands.py:608-695` |
| Check/retest | `work_checks.judge()` (checkId/retestOf/resumeChildId) | `work_checks.py:715-918`, `660-691` |

### 1.1 System prompt của mọi phiên — thứ tự ghép cố định

Thứ tự nối chuỗi tại `runtime.py:1965-1977`:

1. `get_agent_identity()` — `runtime.py:291-303`; đọc toàn văn `AGENT.md` từ `Path.cwd()/'AGENT.md'` hoặc `Path(__file__).resolve().parents[4]/'AGENT.md'`, fallback hằng `IDENTITY` (`runtime.py:291-303`). Nghĩa là AGENT.md hiện hành được nhét nguyên văn vào đầu system prompt của **mọi** phiên (kể cả con).
2. `=== ASSIGNED ROLE: {role.upper()} ===` + `ROLES[role].instructions`, hoặc `orchestrator_guidance()` khi role không nằm trong `ROLES` (root) — `runtime.py:1954`, `1967-1969`.
3. `required_text` — nội dung **đầy đủ** (không chỉ mô tả) của một số skill bắt buộc: `research` → `research-search`, `research-reading`, `research-evidence`; `research-review` → `research-critique`, `research-evidence` (`runtime.py:1955-1960`). Đọc qua `catalog.read()` (full content, `catalog.py:76+`).
4. `=== ENABLED SKILLS (Load full content via skill_view before executing complex workflows) ===` + `catalog.prompt(skills)` — chỉ **danh sách** `- {id}: {description}`, KHÔNG phải nội dung skill (`runtime.py:1970-1971`; `catalog.py:90+`).
5. `=== ANSWER LENGTH ===` + `ANSWER_LENGTH_HINT` (`runtime.py:1972`).
6. `evidence_line` — bằng `''` khi role ∈ `ROLES`; phiên root (orchestrator) nhận `ANSWER_EVIDENCE_LINE` (`runtime.py:1117`, `1964`). Comment tại chỗ nói rõ: phiên con không nhận dòng này vì chúng trả theo `CHILD_RESULT_CONTRACT` (`runtime.py:1961-1963`).
7. Tùy chọn `=== OWNER-CONFIGURED DIRECTIVES ===` + `config['instructions']` (owner cấu hình) (`runtime.py:1975-1976`).

Lưu ý cấu trúc: role instructions là văn bản tĩnh trong `roles.py`, được bọc thêm khối Work Graph nếu vai là node của graph — xem §1.2/§2. Còn `AGENT.md` là văn bản repo có thể cũ hơn thiết kế hiện tại — xem §5.3.

### 1.2 Đường Work Graph — producer (stage `produce`/`execute`)

Chuỗi gọi: `work_run` → `run()` → `run_stage()` → `spawn(role, goal, context, expect, work)` → `runtime.delegate(..., work=...)`.

- `spawn()` `work_graph.py:1106-1185`:
  - `work` dict gửi kèm: `{runId, nodeId, stage, purpose, attempt, taskKind}` (`work_graph.py:1114-1117`).
  - `args = {role, goal, context (cắt trần 16000), expect}` (`work_graph.py:1127`).
  - `lang = work_prompts.language(run['goal'])` (`work_graph.py:1128`) — suy ngôn ngữ từ goal của owner; regex nhận cả `Overall owner goal|Owner goal|Mục tiêu của người dùng:` (`work_prompts.py:10-24`).
  - Quyền hỏi owner gắn thêm khi có grant (`work_graph.py:1129-1137`).
  - Nhánh resume: `prompt = goal + '\n' + args['context']` (`work_graph.py:1152`) kèm chỉ dẫn đọc `work_report` (`work_graph.py:1154-1157`).
- `producer_goal(run, node, stage, feedback, knowledge)` `work_graph.py:1212-1250` — thân prompt producer, thứ tự khối:
  1. Heading `Work Graph run "{title}" — node {id} ({kind}, {stage}).` (`work_graph.py:1216-1217`).
  2. `Overall owner goal:` (`work_graph.py:1218`).
  3. `Your assignment:` (`work_graph.py:1219`).
  4. Acceptance bullets (`work_graph.py:1220-1221`).
  5. Required tests (`work_graph.py:1222-1224`).
  6. `Expected touch list:` (`work_graph.py:1225-1226`).
  7. `Depends on:` (`work_graph.py:1227-1228`).
  8. **Khối điều kiện** khi `stage == 'execute' and kind == 'build'`: "Implement the sub-plan completely, write the tests it names, run them..." (`work_graph.py:1229-1231`).
  9. Feedback (hai cách mở đầu: bản đã review vs ngữ cảnh) (`work_graph.py:1232-1237`).
  10. Knowledge artifacts (`work_graph.py:1238-1244`).
  11. Sibling sub-plans khi kind `plan` (`work_graph.py:1245-1249`).
  - Trả về `(role, goal)`; role = `node['kind']` ở stage produce, ngược lại `EXECUTE_ROLE[node['kind']]` (`work_graph.py:1215`, map tại `work_graph.py:54-56`).
- `run_stage()` `work_graph.py:1319-1502`: gọi `producer_goal` (`:1354`); `context = interview_context + dependency_context` (`:1355`); **chọn deliverable** (`:1356-1358`):

  ```python
  expect = work_prompts.deliverable(node['kind'] if stage == 'produce' else role,
                                    language, node.get('taskKind'), node.get('depth'))
  ```

  spawn produce (`:1378`); vòng hỏi-đáp knowledge: đọc `## Knowledge requests` → chạy helper → gọi lại `producer_goal` lần hai với câu trả lời (`:1392-1424`, gọi lại tại `:1408`).
- `deliverable(kind, lang, task_kind, depth)` `work_prompts.py:209-218` — các nhánh điều kiện:
  - `task_kind == 'lookup'` → `DELIVERABLE_LOOKUP` (`work_prompts.py:211-212`, định nghĩa `:181-192`, trần `LOOKUP_ANSWER_WORDS = 120` `:179`).
  - `kind == 'research' and depth == 'brief'` → `DELIVERABLE_RESEARCH_BRIEF` (`work_prompts.py:213-214`, định nghĩa `:193-204`, trần `RESEARCH_BRIEF_WORDS = 400` `:180`).
  - `kind in ('plan','design')` → nối thêm `PROPORTIONAL_NOTE` (`work_prompts.py:216-217`, `:205-208`).
  - Còn lại → `DELIVERABLES_EN/VI[kind]` (`work_prompts.py:45-91` / `:93-139`).
- Node kind và routing: `DISCOVERY_KINDS=('explore','research','design')`, `PLAN_KIND='plan'`, `EXECUTION_KINDS=('build','debug','testing','simplify')` (`work_graph.py:45-49`); `stages_for(kind)` (`work_graph.py:255+`): discovery → `('produce',)`, plan → `('produce','execute')`, execution → `('execute',)`.
- Sau spawn, `runtime.delegate` ghép user prompt con theo §1.5; `work` khác None kích hoạt nhánh engine (`runtime.py:6819`).

### 1.3 Đường Work Graph — reviewer/check

Ba biến thể:

1. **Node review (produce/execute)** — `work_checks.judge()` `work_checks.py:715-918`:
   - `whole=False` → `graph.reviewer_goal(run, node, stage, ...)` + `node_review_scope(...)` (`work_checks.py:740-741`).
   - `reviewer_goal()` `work_graph.py:1252-1271`: heading `Independent review of Work Graph node ...` (`:1256-1257`); owner goal; node assignment; acceptance; tests; `Budget: {n} model steps...` (`:1265-1266`); `Rubric: {rubric(kind)}` (`:1267`); `The output to review is in the context below.` (`:1268`); `review_tail(lang)` (`:1269`). Context kèm = `### {heading}\n{bounded(output, 14000)}` (`:1271`).
   - `work_prompts.rubric(kind)` `work_prompts.py:221+` → `RUBRICS_EN/VI` (`:141-160`).
   - `work_prompts.review_tail(lang)` `work_prompts.py:226-263` — kết thúc bằng giao thức `VERDICT: ok` / `VERDICT: revise`, luật ≤8 findings, mỗi finding ≤300 chars (theo bản đọc trước).
   - `node_review_scope()` `work_prompts.py:289-305` — phạm vi "chỉ trong nút".
2. **Whole-plan review** — `work_graph.verify()` `work_graph.py:1968-2042`: tạo `master_document(run)` + metas của mọi node produce; `spec = {'id':'whole','executorRole': FLOW_REVIEWER.get(run['flow'],'plan-review')}` (`:2009`); criteria G1–G3 + từng acceptance (`:2011-2023`); gọi `checks.judge(..., whole=True)` tại `work_graph.py:2025` → trong `judge()` dùng `whole_review_goal()` (`work_checks.py:737-738`; định nghĩa `work_prompts.py:308-333`, có nhánh research_only).
3. **Check/retest** — `judge()` với `checkId`, `checkKind`, `budgetHints`, tùy chọn `resumeChildId`/`retestOf`/`inputManifestId`/`workspace` (`work_checks.py:861-870`); `retest_candidate()` chỉ tái dùng con cho `checkKind == 'tests'`, purpose `review` (`work_checks.py:660-691`).

Hợp đồng đầu ra của con reviewer: `work_prompts.child_contract(purpose, lang)` (`work_prompts.py:266-286`): `'review'` → phản biện độc lập + khối `json` coverage có fence + dòng `VERDICT` cuối (`:269-276`). Trong đường check còn có `work_checks.contract(lang, criteria)` (`work_checks.py:405-475`): đọc HẾT snapshot, findings ≤600 từ, coverage json + VERDICT.

Hai lớp text phụ trong `judge()`: chỉ dẫn "checker duty" cho checkKind tests (`work_checks.py:761-779`), phạm vi `reviewTargetArtifactIds` (`:783-791`), phủ đầy `inputManifest` (`:810-832`), retest (`:848-854`).

`wrap_up_note()` `work_graph.py:203-209` — chỉ áp cho purpose `review`: "write your review NOW ... `VERDICT: ok` or `VERDICT: revise`".

### 1.4 Đường knowledge (helper)

- `answer_knowledge()` `work_graph.py:1273-1317`: spawn với `purpose='knowledge'`, `extra_binding={'helperRole','lookupQuestion',...}` (`:1281-1284`).
- Contract: `child_contract('knowledge')` → deliverable lookup (`work_prompts.py:277-281`; `DELIVERABLE_LOOKUP` `:181-192`).
- `producer_need()` `work_checks.py:512-514`: `need = {'role': role, 'check': purpose == 'review', 'readTool': purpose == 'knowledge'}` — dùng để chọn đường đọc artifact khi chạy check.

### 1.5 Đường delegate thường + resume — `runtime.delegate()`

- `delegate()` `runtime.py:6808+`: docstring nói rõ `work` "is set only by the Work Graph engine (never by the model)" (`:6809-6811`); chặn lá: `PermissionError('Leaf agents cannot delegate')` (`:6812-6813`); nhánh engine kiểm `work_scope.check_execute_binding` (`:6819`); nhánh thường kiểm `work_scope.check_delegate` (`:6823`).
- Cấu hình con: `'skills': sorted(set(config['skills']) & ROLE_SKILLS[role])` (`runtime.py:6992`); `'instructions': configured.get('systemPromptAppended','')` (`:6997`); `workBinding` (`:7020`); tools ∪ `{'work_artifact_read','work_report'}` (`:7023`); **strip khi check/diagnostic**: bỏ `('file_write','file_edit_block','write_plan')` nếu `work.get('checkId') or work.get('diagnosticOnly')` (`:7024-7025`); nếu có checkId thì dùng `work_check_tools(role, config['tools'])` (`:7026-7028`).
- User prompt con, thứ tự nối tại `runtime.py:7052-7076`:
  1. `[branch_brief['text']] or [goal]` (`:7052`).
  2. Dòng binding review-target nếu có (`:7055-7060`).
  3. Khối context — nhãn `Ngữ cảnh từ phiên chính (dữ liệu):` / `Parent-supplied context (data):` (`:7061-7063`).
  4. Khối expect — nhãn `Đầu ra và bằng chứng phiên chính yêu cầu:` / `Parent-required deliverable and evidence (result shape):` (`:7064-7066`).
  5. Planning snapshot (`:7067-7074`).
  6. `contract = work_graph.work_child_contract(work.get('purpose'), work_language) if work else None`; `child_prompt = '\n'.join(prompt_parts) + (contract or CHILD_RESULT_CONTRACT)` (`:7075-7076`).
- `work_child_contract(purpose, language='en')` `work_graph.py:562+`: `'review'` → `REVIEW_CONTRACT` (= `work_prompts.child_contract('review')`, `work_graph.py:559`); `'produce'` → `WORK_NODE_CONTRACT` (`work_graph.py:558`); `'knowledge'` → lookup; mặc định `CHILD_RESULT_CONTRACT` (`runtime.py:1415+` — bốn phần Findings/Evidence/Verification/Limitations).
- Resume: nhánh trong `spawn()` (`work_graph.py:1152-1157`) + `work_feedback.resume_child`/pump; con resume nhận lại goal + context + chỉ dẫn đọc `work_report`; check retest có thể tái dùng con qua `resumeChildId` (`work_checks.py:861-870`).

### 1.6 Đường custom command

- `resolve()` (`skills/commands.py:184+`): giao skills = `set(enabled) & ROLE_SKILLS[role]` (`:238`, `:241`); nhánh custom commands từ `:259+`.
- `_command_task()` `runtime_commands.py:608-695`: kiểm quyền `check_command` (`:618`); tạo child với `resolved.skills` (`:645`, `:651`); **nội dung đầy đủ** của skill được nối thẳng vào payload với nhãn "Skills for this task only (role/tool restrictions take priority):" (`:662`).
- `_next_turn_skills()` `runtime_commands.py:560+`: reset WORK SCOPE; viết lại khối `=== ENABLED SKILLS ... ===` mỗi lượt; thêm skill theo mode design/plan (`:576-579`).

### 1.7 Marker/cấu trúc chung của prompt

- Marker phiên chính: `=== WORK GRAPH ===` / `=== END WORK GRAPH ===` (`work_graph.py:39-40`; block chỉ root, dựng tại `prompt_block()` `work_graph.py:2409-2458`: intent flow `:2418-2430`, trạng thái run `:2431-2442`, isolation lines (git branch/worktree/touchset) `:2443-2450`, `Next:` `:2451`, "Keep this turn going..." `:2452-2454`).
- Marker scope: `=== WORK SCOPE ===` (`work_scope.py:34`; dựng tại `prompt_block()` `work_scope.py:528-535`, chèn mỗi lượt qua `apply_profile()` `:510-525`; đồng bộ lại trong `runtime_commands.py:343`).
- Marker system prompt con/cha: `=== ASSIGNED ROLE: ... ===`, `=== ENABLED SKILLS ... ===`, `=== ANSWER LENGTH ===`, `=== OWNER-CONFIGURED DIRECTIVES ===` (§1.1).
- Marker user prompt con: các heading trong `producer_goal`/`reviewer_goal`; nhãn context/expect (§1.5); khối fenced `json` coverage + `VERDICT:` cuối.

## 2. Role instructions theo vai (working tree hậu sửa)

Nguồn: `roles.py`. Các vai có trong `ROLES` (`roles.py:277-298`); vai root không có entry, nhận `orchestrator_guidance()` (`runtime.py:1954`).

| Role id | Instructions (dòng bắt đầu) | Notes Work Graph gắn thêm (dòng wrap) | Tools (roles.py) | Skills mặc định của vai (roles.py) |
|---|---|---|---|---|
| `explore` | `EXPLORE_INSTRUCTIONS` `roles.py:50` | `:264` + `WORK_PRODUCER_NOTE` | `READ` | `('codebase-inspection',)` |
| `plan` | `PLAN_INSTRUCTIONS` `roles.py:63` | `:265` + `WORK_PRODUCER_NOTE` + `WORK_PLAN_NOTE` | `READ | {'write_plan'}` | — |
| `plan-review` | `PLAN_REVIEW_INSTRUCTIONS` `roles.py:219` | `:275` + `WORK_REVIEWER_NOTE` | `READ | VERIFY` | `('codebase-inspection',)` |
| `design` | `DESIGN_INSTRUCTIONS` `roles.py:79` | `:266` + `WORK_PRODUCER_NOTE` | `READ` | `('design-md',)` |
| `build` | `BUILD_INSTRUCTIONS` `roles.py:92` | `:267` + `WORK_PRODUCER_NOTE` | `WRITE` | — |
| `debug` | `DEBUG_INSTRUCTIONS` `roles.py:106` | `:268` + `WORK_PRODUCER_NOTE` | `WRITE` | `('systematic-debugging',)` |
| `review` | `REVIEW_INSTRUCTIONS` `roles.py:119` | `:272` + `WORK_REVIEWER_NOTE` + "(`ok` means [APPROVED], `revise` means [CHANGES REQUESTED])." | `READ | VERIFY` | `('requesting-code-review',)` |
| `simplify` | `SIMPLIFY_INSTRUCTIONS` `roles.py:136` (bản mới) | `:269` + `WORK_PRODUCER_NOTE` | `WRITE` | `('simplify-code',)` |
| `testing` | `TESTING_INSTRUCTIONS` `roles.py:149` | `:270` + `WORK_PRODUCER_NOTE` + `WORK_EXEC_REVIEWER_NOTE` | `WRITE | VISUAL` | `('test-driven-development',)` |
| `research` | `RESEARCH_INSTRUCTIONS` `roles.py:162` | `:271` + `WORK_PRODUCER_NOTE` | `RESEARCH` | `('grounded-citations','research-team')` |
| `research-review` | `RESEARCH_REVIEW_INSTRUCTIONS` `roles.py:187` | `:274` + `WORK_REVIEWER_NOTE` | `READ | SOURCE_READ | VERIFY | {web_search, web_fetch, read_source, paper_citations, claim_assess}` | — |

Cơ chế chèn note: `with_work_graph(text, *notes)` `roles.py:255-261` — chèn khối note **trước đoạn `STRICT PROHIBITION` cuối cùng** (`marker = text.rfind('STRICT PROHIBITION')` `:257`; nếu không có thì append), để phần cấm nghiêm ngặt vẫn là đoạn cuối của prompt. Khối kèm binding text về `work_report` là "safety fallback" và quyền grant (`roles.py:256-258`).

Bốn note Work Graph (bản hiện tại):
- `WORK_PRODUCER_NOTE` `roles.py:243-246` — giao đúng deliverable của node; `ok`/`revise`; "You cannot delegate or call ask_user/interview directly." (`:245`); "save 1-3 questions via work_report needs_user; root owns publication and grants any automatic continuation." (`:245`); "The task-specific deliverable overrides generic output headings." (`:246`); luật `## Knowledge requests` ≤3 dòng (`:245`).
- `WORK_PLAN_NOTE` `roles.py:248` — chuẩn sub-plan; "Do NOT call `write_plan` for a Work Graph node" (`:248`).
- `WORK_REVIEWER_NOTE` `roles.py:250` — rubric + VERDICT override heading chung; "Run tests only if tools and task permit; otherwise report NOT RUN."; `verify_exec` là để kiểm claim, không phải chạy test dự án; blocking finding phải cite toolCallId/`verify:<codeHash>`; kết thúc đúng một dòng `VERDICT: ok|revise`.
- `WORK_EXEC_REVIEWER_NOTE` `roles.py:252` — "Do NOT edit source files"; VERDICT.

Với vai root: không nằm trong bảng trên; identity + `orchestrator_guidance()` + `=== WORK GRAPH ===` block theo lượt + `=== WORK SCOPE ===` block theo mode (§1.7). Orchestrator tools: `ORCHESTRATOR_TOOLS` `roles.py:299-319` (46→47 công cụ theo comment `:319`).

## 3. Skill đã nạp theo vai

### 3.1 Mapping tĩnh — `ROLE_SKILLS`

Nguồn: `skills/commands.py:40-58` (nguyên văn):

- `explore`: `{'codebase-inspection', 'ast-grep'}`
- `plan`: `{'codebase-inspection', 'planning', 'grill-me', 'work-graph-planning'}`
- `plan-review`: `{'codebase-inspection'}`
- `design`: `{'design-md', 'claude-design', 'popular-web-designs', 'architecture-diagram'}`
- `build`: `{'codebase-inspection', 'test-driven-development', 'claude-design', 'popular-web-designs', 'design-md'}`
- `debug`: `{'systematic-debugging', 'codebase-inspection', 'test-driven-development'}`
- `review`: `{'requesting-code-review', 'codebase-inspection'}`
- `simplify`: `{'simplify-code', 'codebase-inspection'}`
- `testing`: `{'test-driven-development', 'dogfood', 'claude-design'}`
- `research`: `{'research-team', 'research-search', 'research-reading', 'research-evidence', 'grounded-citations', 'arxiv', 'blocked-page-recovery', 'codebase-inspection'}`
- `research-review`: `{'codebase-inspection', 'research-critique', 'research-evidence', 'research-search', 'research-reading'}`

### 3.2 Cổng gác (gating) — skill con thực nhận

- Con nhận `set(config['skills']) & ROLE_SKILLS[role]` — tức **giao của hai tập**: (a) owner đã bật trong Settings, (b) mapping vai ở §3.1 (`runtime.py:6992`).
- `resolve()` cho custom command cũng giao tương tự (`commands.py:238`, `:241`).
- `validate_skills()` `commands.py:131-146`: `SKILL_DISABLED` nếu bật skill chưa enable (`:141-142`); `ROLE_SKILL_CONFLICT` cho `explore/plan/review/research` khi đòi skill ngoài mapping (`:143-145`); `EXTERNAL = {'claude-code','codex','opencode'}` (`commands.py:27`).
- `skill_view` bị cổng `PermissionError('Skill is not enabled for this session')` (`runtime.py:4899-4900`), kèm auto-add `WORK_SKILL` (`runtime.py:4894-4898`); `WORK_SKILL='work-graph-planning'` (`work_graph.py:72`).
- `catalog.prompt()` chỉ in danh sách `- id: description` (`catalog.py:90+`); `catalog.read()` đọc full text và trả `basePath` (`catalog.py:76-88`). `DEFAULT_SKILLS` (bật mặc định cho phiên mới) tại `catalog.py:7-24`, gồm `work-graph-planning` (`:16`) và bộ research (`:19-24`).
- Đường custom command khác biệt: **nội dung đầy đủ** skill được nhét thẳng vào payload con (`runtime_commands.py:662`) — trong khi đường thường chỉ có danh sách + `skill_view`.

### 3.3 File skill thực tế (đường dẫn tương đối `backend/src/agentbox/vendor/hermes/`) và số dòng

| Skill | Đường dẫn | Dòng |
|---|---|---|
| codebase-inspection | `skills/software-development/codebase-inspection/SKILL.md` | 116 |
| ast-grep | `optional-skills/software-development/ast-grep/SKILL.md` | 288 |
| planning | `skills/software-development/planning/SKILL.md` | 57 |
| grill-me | `optional-skills/software-development/grill-me/SKILL.md` | 117 |
| work-graph-planning | `skills/software-development/work-graph-planning/SKILL.md` | 120 |
| design-md | `skills/creative/design-md/SKILL.md` | 220 |
| claude-design | `skills/creative/claude-design/SKILL.md` | 650 |
| popular-web-designs | `skills/creative/popular-web-designs/SKILL.md` | 213 |
| architecture-diagram | `skills/creative/architecture-diagram/SKILL.md` | 148 |
| systematic-debugging | `skills/software-development/systematic-debugging/SKILL.md` | 411 |
| test-driven-development | `skills/software-development/test-driven-development/SKILL.md` | 362 |
| requesting-code-review | `skills/software-development/requesting-code-review/SKILL.md` | 280 |
| simplify-code | `skills/software-development/simplify-code/SKILL.md` | 270 |
| dogfood | `skills/software-development/dogfood/SKILL.md` | 164 |
| research-team | `skills/research/research-team/SKILL.md` | 26 |
| research-search | `skills/research/research-search/SKILL.md` | 40 |
| research-reading | `skills/research/research-reading/SKILL.md` | 41 |
| research-evidence | `skills/research/research-evidence/SKILL.md` | 39 |
| grounded-citations | `skills/research/grounded-citations/SKILL.md` | 231 |
| arxiv | `skills/research/arxiv/SKILL.md` | 266 |
| blocked-page-recovery | `skills/web/blocked-page-recovery/SKILL.md` | 137 |
| research-critique | `skills/research/research-critique/SKILL.md` | 39 |
| research-scoping | `skills/research/research-scoping/SKILL.md` | 40 |
| research-synthesis | `skills/research/research-synthesis/SKILL.md` | 40 |
| research-to-plan | `skills/research/research-to-plan/SKILL.md` | 39 |
| final-report | `skills/software-development/final-report/SKILL.md` | 95 |

Nội dung đầy đủ của `research-search`, `research-reading`, `research-evidence`, `research-critique` còn được nhét thẳng vào system prompt của vai research/research-review (§1.1 mục 3) — không cần `skill_view`.

## 4. Tools và scope hiệu lực theo đường

### 4.1 Định nghĩa bộ công cụ — `roles.py`

- Hằng bộ công cụ: `DECISION` `:9` (`ask_user`, `request_approval`); `PEER` `:13` (`peer_read`, `await_children`); `READ` `:14-15` (= `file_read, codebase_glob, codebase_grep, skills_list, skill_view` | `DECISION` | `PEER`); `WRITE` `:16` (= `READ | {file_write, file_edit_block, terminal_exec}`); `VISUAL` `:17`; `SOURCE_TOOLS` `:22`; `SOURCE_READ` `:26`; `BRANCH_REPORT` `:31`; `VERIFY` `:35` (`verify_exec`); `RESEARCH` `:36-37`.
- Gán theo vai trong `ROLES` `:277-298` (xem bảng §2).
- `ORCHESTRATOR_TOOLS` `:299-319` — tập root, gồm `delegate_task`, `interview`, `work_graph/work_run/work_ship/work_check/work_report/work_artifact_read`, `write_plan`... Comment `:319` nói rõ đây là 46→47 công cụ và thiếu `VERIFY` ở cha sẽ cắt mất của reviewer con qua `allowed_tools`.
- `allowed_tools(role, parent)` `:322-343`:
  - `names = ORCHESTRATOR_TOOLS if role == 'orchestrator' else ROLES[role].tools` (`:329`).
  - Là con thì giao với công cụ CHA: `names = names & inherited` (`:340`); thêm lại `claim_assess` cho `research-review` (`:332-335`) và `research_branch_report` cho `research` (`:336-339`) khi cha có nguồn tương ứng.
  - Công tắc giết mesh: `if not peer_mesh_enabled(): names = set(names) - PEER` (`:341-342`).
- `work_check_tools(role, parent)` `:346-359`: nền là `allowed_tools` (`:352`); thêm lại web tools của cha (`:353`); thêm lại `VERIFY` của cha cho `review/plan-review/research-review` (`:354-356`); thêm `work_artifact_read`, `work_report` (`:357-358`); **trừ** `{'file_write','file_edit_block','write_plan'}` (`:359`).

### 4.2 Cổng gác ở runtime — nơi quyền thực thi được quyết định

- `delegate()` `runtime.py:6808+`: lá không delegate được — `PermissionError('Leaf agents cannot delegate')` (`:6812-6813`); nhánh engine: `work_scope.check_execute_binding` (`:6819`); nhánh thường: `work_scope.check_delegate` (`:6823`).
- Cấu hình con khi tạo: skills giao mapping (`:6992`); tools ∪ work tools (`:7023`); strip write khi check/diagnostic (`:7024-7025`); `work_check_tools` khi checkId (`:7026-7028`).
- Dispatch tool: `work_scope.check_tool` gọi trước khi chạy (`runtime.py:4850`); **cổng bind check**: `if binding.get('checkId') and name in ('file_write','file_edit_block','write_plan','delegate_task'): raise PermissionError('WORK_CHECK_READ_ONLY: checker cannot modify source or delegate')` (`runtime.py:4863-4864`); **cổng diagnostic**: `diagnosticOnly` + `file_write/file_edit_block` → `WORK_DIAGNOSTIC_READ_ONLY: diagnosis is not authorization to patch` (`runtime.py:4865-4866`); `skill_view` cổng enabled (`:4899-4900`); `delegate_task` → `self.delegate` (`:4915-4916`); `work_tool()` chỉ root — `PermissionError('WORK_ROOT_ONLY: only main drives the Work Graph...')` (`:5783-5785`); `work_check` → `service.checks.tool` (`:5789`).
- `decision()` `runtime.py:5483-5490`: phiên con bị chặn — `raise ValueError('DECISION_UNAVAILABLE: a delegated session cannot ask the user; decide from your own evidence')` (`:5488-5490`), lý do ghi trong comment `:5486-5488` (con chạy trong lượt cha, không có chat riêng).

### 4.3 Scope hiệu lực — `work_scope.py`

- Hằng: `MUTATING_TOOLS = {'file_write','file_edit_block'}` `:25`; `WRITE_ROLES` `:30`; `BLOCK_MARKER='=== WORK SCOPE ==='` `:34`; `MODES` `:37` (`legacy, artifact_only, approval_pending, root_delegates, run_execute, read_only_check, closed`); `OPEN_MODES=('legacy','run_execute')` `:39`; `EXECUTE_NODE_KINDS` `:45`.
- `run_reason()` `:329+`: `closed` → closed; chưa `executionRequested` → `artifact_only`; approved → `root_delegates`; còn lại `approval_pending`.
- `binding_scope()` `:396+`: `checkId`/`diagnosticOnly` → `read_only_check` (`:399-400`); điều kiện execute (`produce`+`execute`+kind ∈ `EXECUTE_NODE_KINDS`, debug chỉ khi `taskKind == 'implementation'`) (`:420-422`); paused → `closed` REVOKED (`:430-431`); không trong `EXECUTE_STATUSES` → `approval_pending` (`:432-434`); admission không còn sống → `closed` REVOKED (`:435-437`); còn lại `run_execute` (`:438-439`).
- `resolve()` `:442+`; `origin_for_child()` `:308+` — con KHÔNG thừa hưởng `run_execute`; con không bind = `artifact_only`.
- `check_tool()` `:470-480`: legacy/run_execute/read_only_check cho qua; `MUTATING_TOOLS`/`DESIGN_MUTATING` bị chặn (`:475`); terminal bị chặn trừ allowlist đọc-only (`work_scope.py:100-116`: `pwd, ls, cat, head, tail, wc, stat, file, du, tree, which`..., git read-only).
- `check_delegate()` `:483-486`: non-legacy + vai ghi → `WORK_SCOPE_DELEGATE_ROLE` deny.
- `check_command()` `:489-496`: non-legacy + vai ghi/claude-code → `WORK_SCOPE_COMMAND_ROLE` deny.
- `check_execute_binding()` `:499-507`.
- `apply_profile()` `:510-525`: mode không mở thì bỏ `MUTATING_TOOLS`/`DESIGN_MUTATING` khỏi tools từng lượt (`:520`) và nối `prompt_block()` (`:528-535`: "Run {run} does not let main change code in this turn... file_write/file_edit_block are off and terminal_exec only accepts read-only commands").

Bảng scope hiệu lực theo đường:

| Đường / trạng thái | Quyền ghi hiệu lực | Căn cứ |
|---|---|---|
| Root, legacy | Đầy đủ theo `ORCHESTRATOR_TOOLS` | `work_scope.py:37-39` |
| Root, run đã gắn, chưa executionRequested (`artifact_only`) | Mất `file_write/file_edit_block` theo lượt; terminal chỉ đọc | `work_scope.py:510-525`, `:470-480` |
| Root, approved (`root_delegates`) | Giao được cho vai ghi; bản thân vẫn theo profile | `work_scope.py:329+`, `:483-486` |
| Root, `run_execute` | Mở (điều kiện execute sống) | `work_scope.py:396-439` |
| Child bind execute node | Quyền theo vai, kiểm `check_execute_binding` | `runtime.py:6819`, `work_scope.py:499-507` |
| Child không bind | `artifact_only` (không kế thừa run_execute) | `work_scope.py:308+` |
| Check/diagnostic child | `read_only_check`; strip write ở runtime; `work_check_tools` | `work_scope.py:399-400`, `runtime.py:7024-7028` |
| Run paused / admission chết | `closed` REVOKED | `work_scope.py:430-437` |

### 4.4 `tool_groups.py` — nguồn dữ liệu nhóm công cụ UI/settings

- 10 nhóm; docstring `:3-7` nói hợp của 10 nhóm phải bằng `ORCHESTRATOR_TOOLS` (47 công cụ) và chỉ `runtime.py` quyết định bộ công cụ thật.
- Nhóm `workGraph` `:55-58` = `['work_graph','work_run','work_ship','work_check','work_report','work_artifact_read','verify_exec']`.
- Nhóm `questionsApprovals` alwaysOn `:59-61`.

## 5. Chỉ dẫn trùng/xung đột — bằng chứng nguyên văn

### 5.1 Lead §37.2 #1 — vai Simplify (roles.py:136–146)

**Trạng thái HEAD (4e0923d) — xung đột CÓ thật:**

- `HEAD:roles.py:142` (tức dòng 142 bản HEAD): `"4. Verify Tests: Run the existing test suite via `terminal_exec` to guarantee zero behavioral regressions."`
- `HEAD:roles.py:146`: `"### Verification Proof (test run output demonstrating 100% passing tests)"`
- Đối chiếu ngay trong cùng repo: `work_prompts.py:149` (rubric cho chính kind simplify, phía reviewer): `"Read changes and before/after evidence that behavior is unchanged. Run tests only when tools and scope permit, otherwise report NOT RUN; do not edit files."`; và deliverable `work_prompts.py:87-90`: `"## Behavior proof — before/after commands and actual output; unrun tests remain NOT RUN."` → hai mệnh lệnh không tương thích (một bên đòi "100% passing", một bên cho phép "NOT RUN").
- Plan §37.2 ghi đúng hiện trạng này tại `docs/plan/Work-Graph-fix.md:2773`.

**Trạng thái working tree hiện tại (hậu sửa, chưa commit) — đã thay thế:**

- `roles.py:137`: `"Your mission is to reduce complexity in the code under review while keeping the external behaviour that callers and contracts actually require."`
- `roles.py:141`: `"3. Mode Follows The Assignment: apply edits with `file_edit_block` only when the assignment grants a write scope; a survey-only assignment reports findings with `file:line` and leaves the tree untouched."`
- `roles.py:142`: `"4. Verify Honestly: run the targeted tests for the behaviour you touched when the tools and the environment allow; report the exact command, the before/after result, and every failure, skip or NOT RUN. A green suite does not prove zero regressions."`
- `roles.py:147`: `"Do not silently drop a blocking finding that carries evidence: adjudicate it with a reason and its source. An optional cleanup idea may be dropped when you say why."`
- Bằng chứng thay đổi: `git diff` cho thấy hunk `@@ -134,16 +134,17 @@` (9 insertions, 8 deletions); mtime `roles.py` 2026-10-02 20:44:17Z; test ghim mới `backend/tests/unit/test_work_simplify_prompt.py` (untracked, mtime 20:44:44Z) khẳng định các câu cũ đã biến mất và câu mới phải có.
- Lưu ý thẩm quyền: việc sửa nằm ở tầng **prompt**; vai `simplify` vẫn giữ tool set `WRITE` (`roles.py:288`) và runtime không có cổng riêng theo assignment cho simplify (ngoài các strip chung §4.2) — nên câu "only when the assignment grants a write scope" là ràng buộc mức chỉ dẫn, không phải mức dispatch.

### 5.2 Lead §37.2 #2 — skill vendor `simplify-code` (270 dòng)

Các câu nguồn (nguyên văn, `vendor/hermes/skills/software-development/simplify-code/SKILL.md`):

- `:84-95`: `"### Phase 2 — Launch four reviewers in parallel"` ... `"Use `delegate_task` **batch mode**"` ... `"**No delegation available?** If you can't call `delegate_task` in this context (you're a leaf subagent, delegation is disabled, or the budget is exhausted), do NOT skip the review or drop angles. Work through all four reviewer angles yourself, sequentially, in this context"`.
- `:115`: `"SAFE = proven not to affect behavior (unused imports, commented-out code, pass-through wrappers). Auto-apply these."`
- `:194-195`: `"2. **Discard false positives** — you have the most context; you don't have to argue with a reviewer, just drop weak or wrong suggestions silently."`
- `:215-217`: `"5. **Verify** you didn't break anything: run the project's targeted tests for the touched files (not the full suite)..."`.

Xung đột/áp lực đối chiếu:

- Với `WORK_PRODUCER_NOTE` `roles.py:245`: `"You cannot delegate or call ask_user/interview directly."` — skill hướng dẫn fan-out `delegate_task` (4 con) và có nhánh fallback khi không delegate được. Con simplify là lá: `runtime.py:6812-6813` ném `PermissionError('Leaf agents cannot delegate')` khi con gọi `delegate_task`. Vậy nhánh fallback của skill ("Work through all four reviewer angles yourself, sequentially") là nhánh con simplify sẽ gặp.
- Với câu silent-drop `:194-195`: bản `roles.py` mới thêm luật đối trọng tại `roles.py:147` ("Do not silently drop a blocking finding that carries evidence... An optional cleanup idea may be dropped when you say why.") — nhưng **file vendor không đổi** (không nằm trong git status; hash ở §0). Đây là xung đột mức văn bản giữa hai nguồn được nạp vào cùng một phiên: role note (system prompt, qua `with_work_graph` `roles.py:269`) vs SKILL.md (nạp khi `skill_view` hoặc qua nội dung skill trong custom command `runtime_commands.py:662`). Plan §37.2 đã ghi chú đây là "điểm cần thích nghi skill", không phải bằng chứng lỗi runtime (`docs/plan/Work-Graph-fix.md:2775`).
- Đường custom command có dòng ưu tiên "role/tool restrictions take priority" (`runtime_commands.py:662`); đường `skill_view` thường không kèm dòng ưu tiên tương ứng — cần lưu ý khi đọc hành vi thực tế (chưa kiểm chứng runtime, xem §6).

### 5.3 Lead §37.2 #3 — `AGENT.md` vs quyết định §27–29 và code

- `AGENT.md:12`: `"BoxFox is one main agent (the orchestrator) and eleven specialist roles. Only the main agent delegates; a child never spawns another child and never asks the owner."`
- `AGENT.md:20`: `"5. **Review roles**: ... Every child output in a Work Graph goes to an independent reviewer that ends with `VERDICT: ok` or `VERDICT: revise`; the producer revises until the verdict is ok or the round cap is reached."`
- Đối chiếu quyết định mới: `docs/plan/Work-Graph-fix.md:1998`: `"Quy tắc “mọi sub đều Review” trong prompt cloud gốc đã được thay bằng policy theo đầu ra/rủi ro."` (và bảng §6 nói kiểm chứng bắt buộc theo nhiệm vụ, không gắn một reviewer giống nhau — `docs/plan/Work-Graph-fix.md:17`).
- Đối chiếu code: `work_policy.derive()` `work_policy.py:49-106` thêm check theo artifact/rủi ro (patch → tests/testing `:83`; plan → plan_review `:87`; design → design_review `:89`; research → evidence `:91`; knowledge/diagnostic + consequential → evidence `:92-94`; git_isolated → deferred code_review `:101-104`) — không có luật "mọi node đều review" đồng nhất.
- Đối chiếu "never asks the owner": code cho phép con lưu câu hỏi qua `work_report needs_user` và root xuất bản/grant (`roles.py:245`; cơ chế trong `work_feedback.py`, `work_scope` grant). Vậy câu AGENT.md là **mô tả cũ hơn** quyết định §27–29.
- Vì `AGENT.md` được nhét nguyên văn vào system prompt mọi phiên (`runtime.py:291-303` + `:1965-1967`), các câu cũ này **thực sự đi vào prompt runtime** — plan đã yêu cầu "không dùng doc cũ để đảo ngược kiến trúc đã duyệt" (`docs/plan/Work-Graph-fix.md:2776`).

### 5.4 Hai bộ heading cùng tồn tại trong một prompt

- `roles.py:246` (`WORK_PRODUCER_NOTE`): `"The task-specific deliverable overrides generic output headings."`
- Nhưng heading cũ vẫn nằm trong role instructions cùng phiên: ví dụ `EXPLORE_INSTRUCTIONS` `roles.py:57-60` (`### Architecture & Key Files` / `### Dependencies & Contracts` / `### Findings & Evidence` / `### Unknowns & Risks`); `TESTING_INSTRUCTIONS` `roles.py:156-159` (`### Test Execution Summary` / `### Detailed Test Case Logs` / `### Edge Cases & Failure Scenarios Tested` / `### Visual & Artifact Evidence`).
- Đây là chỉ dẫn "override" ở tầng note, không phải xóa heading cũ; model nhận cả hai. Không có cổng runtime nào kiểm định hình dạng output theo deliverable (theo đọc tĩnh).

### 5.5 Công cụ được quảng cáo nhưng bị runtime từ chối (mức con)

- `READ` `roles.py:14-15` chứa `DECISION` → mọi vai con (`explore, plan, plan-review, design, build, debug, review, simplify, testing, research`) đều **được liệt kê** `ask_user`/`request_approval` trong bộ công cụ.
- Nhưng `decision()` `runtime.py:5483-5490` từ chối mọi phiên con: `"DECISION_UNAVAILABLE: a delegated session cannot ask the user; decide from your own evidence"` (`:5489-5490`).
- `WORK_PRODUCER_NOTE` nhắc con điều này cho đường Work Graph (`roles.py:245`), nhưng các instruction gốc của REVIEW/SIMPLIFY... không nhắc; nên ở đường delegate thường, con thấy tool trong danh sách nhưng gọi sẽ lỗi. Đây là loại "quyền quảng cáo mạnh hơn quyền hiệu lực".

### 5.6 `plan` được cấp `write_plan` nhưng bị cấm gọi trong Work Graph

- Cấp quyền: `Role('plan', ..., READ | {'write_plan'})` `roles.py:279`.
- Cấm: `WORK_PLAN_NOTE` `roles.py:248`: `"Do NOT call `write_plan` for a Work Graph node — the harness writes the documents after the whole-plan review."`
- Không xung đột ở đường legacy (write_plan vẫn là đường ghi plan cũ); xung đột chỉ ở đường Work Graph. Ở đó: con check (có `checkId`) bị chặn cứng ở dispatch — `runtime.py:4863-4864` (`'WORK_CHECK_READ_ONLY: checker cannot modify source or delegate'`); còn node produce/execute **không tìm thấy cổng dispatch riêng chặn `write_plan`** (đã quét `write_plan` trong `runtime.py`/`work_scope.py`: chỉ có nhánh `plan_workflow` nội bộ, không có nhánh Work Graph) — nên với node produce, đây là ràng buộc mức chỉ dẫn (prompt-level), đúng như `WORK_PLAN_NOTE`.

### 5.7 Ghi chú tension (chưa kết luận là xung đột cứng)

- `TESTING_INSTRUCTIONS` `roles.py:150`: `"Your mission is to write and execute rigorous automated tests..."` + tool `WRITE` (`roles.py:289`, gồm `file_write/file_edit_block`) + `WORK_EXEC_REVIEWER_NOTE` gắn cùng (`roles.py:270`, `:252`): `"Do NOT edit source files"`. Hai câu này có thể cùng đúng (viết file test ≠ sửa source), nhưng cùng nằm trong một system prompt và không có định nghĩa "source file" trong prompt — nêu ra để P1 xem xét, không kết luận thay.

## 6. Những phần KHÔNG kiểm chứng được bằng đọc tĩnh

Nói rõ để tránh suy diễn quá mức (đúng tinh thần "tránh suy từ tên skill"):

1. **Chuỗi prompt render thực tế của một lượt sống** (sau khi ghép, cắt trần, bơm block theo lượt) chưa được quan sát: tài liệu này là đọc mã tĩnh; không có trace runtime trong phạm vi phiên này. Mọi kết luận là "theo code", không phải "đã thấy trên máy chạy".
2. **Đường executor `claude-code`** (`_run_cli` và các nhánh CLI) chưa đọc hết nội dung prompt mà CLI nhận; `EXTERNAL = {'claude-code','codex','opencode'}` (`commands.py:27`) có cổng riêng (`EXECUTOR_CONFLICT`, `ADAPTER_UNAVAILABLE` `commands.py:133-140`) — chưa inventory phần này.
3. **Đuôi `resolve()` cho custom commands** (`commands.py` sau khoảng dòng 260) chưa đọc trọn; chỉ xác nhận nhánh giao skills ở `:238/:241` và nhánh custom bắt đầu `:259+`.
4. **Nội dung đầy đủ `work-graph-planning/SKILL.md` (120 dòng)** chưa đọc từng dòng; chỉ xác nhận tồn tại, số dòng, và vai trò mặc định (`catalog.py:16`) + auto-add khi `skill_view` (`runtime.py:4894-4898`).
5. **`orchestrator_guidance()`** (text dành cho root khi role không nằm trong `ROLES`, `runtime.py:1954`) chưa đọc trọn văn bản.
6. **Trạng thái enable skill thực tế của owner trên box** không quan sát được từ repo — quyết định bởi Settings; inventory chỉ mô tả công thức giao (`runtime.py:6992`, `commands.py:238-241`).
7. **Việc một lượt chạy cụ thể có block WORK SCOPE cũ/stale hay không** và **một con cụ thể có thực sự nhận skill nào** (ví dụ simplify có mở `simplify-code` không) cần trace runtime — chưa có trong phạm vi đọc tĩnh này. Plan §37.2 cũng ghi đúng: "**Chưa có trace chứng minh skill này được nạp/gây lỗi trong ca đang xét**" (`docs/plan/Work-Graph-fix.md:2774`).
8. **Ảnh hưởng của các thay đổi chưa commit khác** (router/frontend/eval) tới prompt không thuộc phạm vi P0b; không đánh giá.
9. **`roles.py` đang được sửa song song** (mtime 20:44:17Z); nếu tiến trình khác commit thêm, số dòng có thể lệch — đối chiếu bằng hash ở §0 trước khi dùng lại tài liệu này.

## 7. Ghi chú tuân thủ

- Tài liệu chỉ chứa: vị trí mã, chuỗi prompt (văn bản dành cho model), hash nguồn. Không chứa hidden reasoning, không chứa bí mật (không có token/key/nội dung riêng tư).
- Không file nào trong repo bị sửa bởi phiên này; đây là inventory read-only. Artifact nằm ngoài repo tại `/var/tmp/w11-p0b-inventory.md`.
- Xung đột tên phiên: một tiến trình khác đã sửa `roles.py` trong lúc đọc (xem §0.1/§5.1); mọi trích dẫn `roles.py` đã được đối chiếu lại sau khi sửa.

