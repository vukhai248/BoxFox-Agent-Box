# Cải tổ Plan mode — v1

Ngày bắt đầu: 2026-09-29. Nhánh làm việc duy nhất: `B`.

## Mục tiêu và quyết định của chủ dự án

Đưa `/plan` về phiên chính, theo workflow: hiểu yêu cầu → khảo sát → phỏng vấn → chốt brief/phương án → soạn → phản biện → duyệt → chọn triển khai. Kế hoạch phải đủ quyết định để một kỹ sư khác triển khai mà không đoán sản phẩm, kiến trúc, dữ liệu hay nghiệm thu. Cải tổ toàn luồng; hỏi nhiều vòng ngắn khi cần; agent tự nghiên cứu và đề xuất kỹ thuật; độ sâu theo độ phức tạp; duyệt không tự bắt đầu build; giữ model/provider hiện có.

## Bằng chứng ban đầu

- `/plan` hiện là role command tạo child; `runtime.decision` cấm child hỏi người dùng. Command kết thúc khi child xong, chưa điều phối workflow đầy đủ.
- Role `plan` không được bảo đảm nhận skill `planning`; `grill-me` phụ thuộc cấu hình bật skill.
- Bản hồ sơ y tế chủ dự án gửi (5.974 ký tự) qua `plan_quality_issues=[]`, `assumption_items=[]`, dù tự chốt offline/mock/kế thừa v3 và thiếu nhiều quyết định SWE/AI. Có tiêu đề không chứng minh chất lượng.
- Writer dùng UTF-8; chưa có bằng chứng bỏ dấu ở writer. Phải kiểm tra toàn đường model → file → API → UI.
- Duyệt tab Plan hiện tự mở lượt thi công.

## Hành vi cần triển khai

### Phỏng vấn và brief

- `/plan <task>` mở/tiếp tục run ở root; `/plan` bật mode và chờ task; `status` xem; `off` tạm dừng. Nút composer dùng cùng workflow; chat sau đó tiếp tục run.
- Đọc goal/attachment/workspace trước khi hỏi. Phân biệt dự án mới, sửa hiện hữu, sửa tài liệu. Chủ đề khác phải hỏi kế hoạch mới hay sửa run cũ trước khi gộp.
- Mỗi vòng 1–3 câu; lựa chọn có đánh đổi; luôn nhập tự do; hỗ trợ “chưa biết, hãy đề xuất”; không hỏi lại thông tin đã có. Không chốt offline/cloud/OCR/RAG/database hay kế thừa plan cũ khi thiếu căn cứ.
- Chờ user phải bền vững, kết thúc compute turn, không timeout 300 s tự từ chối. Reload/restart tiếp tục được.
- Brief: goal, users, workflow, scope, data, constraints, success, decisions/open questions, evidence. Phân biệt user-confirmed, observed, proposed, unresolved. Model không tự gán user confirmation.
- Dự án/kiến trúc lớn phải xác nhận brief/đánh đổi trước drafting; tác vụ nhỏ đã rõ đi thẳng sau khảo sát. Tài liệu cũ chỉ là ràng buộc khi đúng nhiệm vụ/được user yêu cầu.

### Chuẩn SWE/AI

Plan lớn cần sản phẩm, hiện trạng, kiến trúc/stack/lý do, data/schema/lifecycle/migration, contracts/errors/async/auth, AI/baseline/model/grounding/evaluation/fallback/human review/cost/latency, deployment/config/secrets/observability/retry/backup/rollback, milestones/dependencies/acceptance. Không áp dụng phải có lý do. Plan nhỏ được gộp mục.

Mỗi công nghệ gắn một quyết định; “LLM + rule”, “RAG”, “JSON Schema”, “có citation” chưa đủ. AI evaluation phải nêu dataset, đơn vị đo, baseline, cách chấm, ngưỡng và lý do; ngưỡng chưa hiệu chỉnh là mục tiêu đề xuất. Đo riêng correctness, omissions, unsupported claims, abstention. Ngôn ngữ theo user; Việt có dấu, giữ code/path/quotes. Plan đầy đủ ở file, chat tóm tắt.

### Engine, quyền, lưu trạng thái

- Module Plan riêng; phases `scoping`, `investigating`, `interviewing`, `drafting`, `reviewing`, `ready`, `approved`; status gồm `needs_user`, `paused`, `blocked`, `cancelled`. Có thể quay lại hỏi/khảo sát.
- Root sở hữu brief, phỏng vấn và official writer. Specialist trả đề xuất/câu hỏi với snapshot; child không ghi official plan.
- `ACTIVE MODE: PLAN` bắt buộc từng turn, kể cả custom AGENT.md. Chặn implementation tools ở tool list và dispatch, bao gồm delegation/custom commands. Chỉ read/research và plan artifacts. Không tự bật design để scaffold. Các mode chuyển tường minh, pause run trước.
- SQLite PlanRun: id/root/revision/phase/status/language/brief/questions/decisions/evidence/current document. Questions/answers có stable ID và revision. Optimistic concurrency + invocation ID. Answer và continuation request transaction; pump restart phục hồi đúng một lần.
- API: PUT `/sessions/{sid}/plan-mode`; GET `/plans/runs/{runId}`; POST `/plans/runs/{runId}/answers`; POST `/plans/runs/{runId}/actions`; POST `/plans/execute` (đều dưới `/api/agent`).
- `plan_scope` đọc/cập nhật brief, propose decisions, hỏi. `write_plan` phải mang run/brief revision; chặn unresolved critical choices. Giữ registry/header/version/events/ledger; bind review run + brief revision + identity/version/hash.
- Hết compute budget: lưu checkpoint và nói phần còn thiếu; user wait không tiêu compute budget.

### UI, chất lượng, duyệt

- Composer có Plan toggle/phase; chat interview card hỗ trợ partial/free-text; tab Plan brief/decisions/questions/review. Draft chưa đạt không hiện completed/ready.
- Duyệt chỉ ghi acceptance; Execute riêng kiểm exact approved version/hash; changes request cùng workflow; giải thích không tự version bump.
- Legacy docs/approvals vẫn đọc được, không retroactively chứng nhận chuẩn mới; execute/continue cần adopt và readiness check.
- Ba lớp: brief readiness có provenance; deterministic validity/traceability requirements→decisions→milestones→checks; independent semantic review đọc exact snapshot.
- Rubric versioned: intent, grounding, technical decisions, data/contracts, AI nếu áp dụng, acceptance, operations, clarity. Per-dimension evidence/findings; total không bù critical gaps. Ready khi mọi required dimension đạt và không còn blocking finding.
- Tối đa 2 automatic revise rounds/đợt; provider retry reviewer 1 lần trong budget. Failure = chưa đánh giá, không fake pass. P1–P8 chỉ structural/proxy history. Accent heuristic chỉ signal; semantic reviewer quyết định.

## Checklist triển khai — tick chỉ khi thật sự hoàn thành

- [x] Đọc sample, code path và xác nhận failure modes.
- [x] Chốt preferences với user và tạo nhánh `B`.
- [x] Lưu plan và bàn giao vào repository.
- [x] P1: SQLite workflow/brief/questions/revision/idempotency và root `/plan`.
- [x] P2: Mode prompt, quyền read-only, child snapshot và interview persistence/continuation.
- [x] P3: API routes, readiness/traceability, semantic review và exact-version execution.
- [x] P4: Frontend API/store/sync, composer/interview/tab Plan, approve vs execute.
- [ ] P5: Tests xác định backend/frontend, typecheck/lint và browser verification. Test mục tiêu/typecheck/lint file đổi pass; browser chưa chạy, full frontend còn lỗi ngoài phạm vi.
- [ ] P6: 12 live scenarios ×2 trên model hiện tại, so baseline cũ, ghi mọi lỗi/token/latency. Fixture/runner/runbook đã có; chưa có USD budget, 0 live calls.
- [ ] P7: Docs index, report kết quả và bàn giao cuối. Index/checkpoint/runbook đã viết; chờ báo cáo browser/live để nghiệm thu toàn bộ.

## Nghiệm thu

Deterministic: /plan không child; empty không fake task; explicit task không hỏi thừa; premature write blocked; tool/custom/delegate bypass blocked; reload/restart answers; duplicate exactly once; stale revisions conflict; changed brief invalidates review; approval no Build; execute exact hash/idempotent; UTF-8 end-to-end; legacy preserved.

12 live cases ×2: prompt medical nguyên văn, vague new app, fully specified, small repo fix, contradictions, unknown stack, unrelated old doc, offline/cloud, changed intent, fake headings-only plan, reviewer failure, restart. Isolated DB/session/workspace. Same prompt/answers/model/config for baseline. Every vague case asks before critical decisions; no approval auto-build; sample flagged substantive gaps; ready passes all required dimensions/no invented paths/results; medical evaluates synthesis correctness, not just citations; ≥90% workflow completion within budget, provider/product errors both reported. Medical/legal sample sources are unverified, not ground truth.

## Bàn giao đang hoạt động

**Checkpoint ngày 2026-09-29, trước commit bàn giao:** phần code P1–P4 đã triển khai và qua test xác định mục tiêu. P5 còn browser và các lỗi hồi quy ngoài phạm vi; P6 chưa chạy live, chưa có bằng chứng đạt 90%. Tick P1–P4 là tiến độ triển khai, không chứng nhận chất lượng mọi đầu ra model.

### Đã làm và bằng chứng

- [x] SQLite `plan_runs`, `plan_run_admissions`, `plan_continuations`: revisions, partial answers, retry idempotent, transaction rollback, restart/checkpoint.
- [x] `/plan` ở phiên chính; empty/status/off không tạo child; nạp planning v2 bắt buộc, override custom identity.
- [x] Chặn sửa mã/shell/build/install ở cả schemas và dispatch; child giữ snapshot/binding, không ghi official plan; custom command/delegation bị kiểm tra.
- [x] `plan_scope`, owner provenance, xác nhận brief, writer run/brief revision, traceability, historical versions.
- [x] API mode/runs/answers/actions/execute; approval không Build; execution đọc file thật, kiểm hash và admission ID.
- [x] SWE-AI/1 đủ tám chiều và findings; review đúng run/brief/hash; hai vòng sửa, một retry provider; failure không tính đạt.
- [x] Composer toggle/status, interview lựa chọn/free text/partial, brief trước confirm, kết quả phản biện, Execute riêng; dùng poll chat hiện có.
- [x] Tài liệu/lịch sử cũ giữ nguyên. Legacy execute trả `PLAN_LEGACY_ADOPTION_REQUIRED`; tiếp tục bằng `/plan <đường dẫn>` để root đọc, chốt brief và viết phiên bản được phản biện. Chưa tự nhập mọi metadata legacy.
- [x] Chuẩn bị 12 ca ×2 và bản mẫu nguyên văn, runner dry-run mặc định, database/workspace riêng từng cell; lưu checkpoint kết quả từng cell.
- [ ] Browser thực tế (công cụ chưa khởi tạo được).
- [ ] Benchmark model thật + baseline, chấm nội dung export theo rubric/kịch bản và báo tỷ lệ.

### Kết quả kiểm tra hiện tại

- Backend workflow/routes/eval runner + quy ước eval: **104 pass**, `plan-mode-final-eval-contracts.log`. Bao gồm reviewer một retry, resume mode, pause/cancel đang chạy, giải thích không trả lời thay approval, phân loại lỗi và network boundary.
- Hồi quy các contract Plan/commands/verify: **274 pass**, `plan-mode-final-contracts.log`.
- Frontend PlanPanel/usePlanFiles/interview UI: **71 pass**, `plan-mode-final-ui.log`.
- TypeScript `npm run typecheck`: PASS sau đợt UI cuối. ESLint trên toàn bộ file Plan đã sửa: PASS.
- Full backend cuối: **2.412 pass, 18 skip** trong 494,73 giây, `plan-mode-backend-verified.log`. Fixture log đã dùng SQLite thật; runner dùng đúng network boundary `scripts/eval/net.py`. Nhóm 104 kiểm lại code workflow/API cuối. Fixture fake-headings đã yêu cầu đọc cả bản mẫu nguyên văn để đối chứng live sau này.
- Full frontend: **1.430 pass, 2 fail**, `plan-mode-frontend-verified.log` trong `SubagentInspectorPanel.stream.test.tsx`: ghép delta mất khoảng trắng, canonical assistant bị lặp. Inspector đã dirty trước task và được giữ nguyên; chưa sửa hai lỗi đó.
- Full frontend lint: 10 lỗi ở `HarnessFlowVisualizer`, `ModelManagerModal`, `ui.tsx`, `harnessChatStore.retry.test`, `routerChatStore.test`; không nằm trong file Plan thay đổi.
- Browser: `mcp__cua_repl` lỗi `failed to write kernel assets ... os error 3` cả sau reset; chưa có browser pass. Test React/DOM không thay thế browser.
- Live model: **0 lượt**. Chưa lấy kết quả live để chứng nhận tiếng Việt, độ sâu SWE/AI hay tỷ lệ 90%.

### Nhánh và bảo toàn công việc

**Chỉ nhánh `B`.** Code được lưu bằng commit `feat(plan): persist root workflow and separate approval from execution`; dùng `git log -1` để lấy hash. Base: `feature/thinking-box-ui`, commit `7bf93950104b6cd06d726da5082b4c52e0c9ae8e`. Không checkout main. Chưa đổi model/provider; quan sát root đang dùng `opencode / space-bunny-free` (phải đọc lại config khi benchmark).

**Dirty có sẵn:** `frontend/src/components/panels/SubagentInspectorPanel.tsx`. Không chỉnh hoặc đưa vào commit Plan; không reset. Test lỗi ở Inspector phải báo riêng.

### Bản đồ code để tiếp tục

| Phần | File |
|---|---|
| Workflow/SQLite/provenance/rubric/checkpoint/pump | `backend/src/agentbox/agent_core/plan_workflow.py` |
| Command admission, mode root và prompt | `backend/src/agentbox/skills/runtime_commands.py`, `skills/commands.py` |
| Dispatch, writer, delegation, review, kết thúc turn khi chờ | `backend/src/agentbox/agent_core/runtime.py` |
| API và approve/execute/hash | `backend/src/agentbox/api/server.py` |
| Quy trình mandatory | `backend/src/agentbox/vendor/hermes/skills/software-development/planning/SKILL.md` |
| Client/store/shared poll | `frontend/src/lib/planApi.ts`, `store/planStore.ts`, `hooks/usePlanSync.ts` |
| Interview/brief/findings | `frontend/src/components/panels/plan/PlanWorkflowView.tsx` |
| Plan tab/approval refresh | `frontend/src/components/panels/PlanPanel.tsx`, `hooks/usePlanFiles.ts` |
| Live fixtures/runner | `backend/tests/fixtures/plan_workflow_eval_v1.json`, `scripts/eval/plan_workflow_eval.py` |

### Thứ tự agent tiếp theo

1. Đọc checkpoint và kiểm `git branch --show-current` phải là B; giữ Inspector dirty.
2. Backend full và target đã pass theo log. Rerun target nếu sửa engine; typecheck/lint file đã sửa + test UI nếu sửa giao diện. Full frontend/lint còn lỗi ngoài phạm vi ghi trên.
3. Sửa khả năng khởi tạo browser tool, rồi chạy flow thật ở harness/DB/workspace thử nghiệm: empty Plan, interview partial, reload/restart, confirm, review, approve, separate Execute, double-click, copy/export tiếng Việt. Không dùng DB/workspace phiên thật để eval.
4. **Chờ chủ dự án nêu USD budget.** Repo `scripts/eval/guard.py` yêu cầu opt-in `BOXFOX_EVAL_ALLOW_SPEND=1` và budget >0. Đã hỏi qua async; chưa có giá trị được xác nhận. Không tự điền 10 USD hay đổi provider.
5. Theo [runbook đánh giá](plan-mode-evaluation-runbook.md), chạy reform 24 cell và baseline 24 cell, cùng config/prompt/answers. Baseline được extract từ commit ghi trên, không checkout branch khác.
6. Đọc toàn bộ exported plan/findings/events; chấm từng yêu cầu của kịch bản, báo riêng lỗi provider/sản phẩm/substrate đánh giá, giữ mọi lượt lỗi trong mẫu số. Runner chỉ ghi workflow signals, không tự chứng nhận nội dung.
7. Nếu benchmark/browser phát hiện lỗi, sửa trên B, thêm regression, tick/ghi tiến độ tại đây. Chỉ tick P5/P6/P7 hoàn tất sau nghiệm thu tương ứng.
