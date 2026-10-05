# Bàn giao cho cloud agent mới — BoxFox Work Graph

Ngày: **03/10/2026**. Đây là **bản chỉ dẫn ngắn**, không thay kế hoạch, source code hoặc evidence. Agent nhận việc không cần ký ức hội thoại cũ, nhưng **phải đọc các tài liệu bên dưới trước khi quyết định/sửa**. Người dùng muốn tiếp tục từ checkpoint, không làm lại dự án hoặc mở goal chạy dài vô hạn.

## 1. Đọc gì trước

1. [Work-Graph-fix.md](Work-Graph-fix.md): kế hoạch gốc và nhật ký canonical. Đọc mục12 (các W), mục27–29 (kiến trúc/quyết định owner), mục30–35 (checkpoint local/cloud), mục36 (lỗi bộ đo mới), mục37 (W11 prompt/skill), mục38 (W12 adaptive model/thinking/budget/pricing). Đọc mục6–9 để hiểu chuẩn đầu ra; quay lại các phần W6/W6.5 khi sửa review/budget.
2. [cloud-pr-audit-03_10.md](cloud-pr-audit-03_10.md): audit code/PR và nguyên nhân không hội tụ. **Mục9 là cập nhật sau khi nhận bundle**, supersede các đoạn trước nói còn thiếu cả folder. H1–H5 có nguyên nhân, vị trí code và checkpoint.
3. [cloud-w10-bundle-audit-03_10.json](cloud-w10-bundle-audit-03_10.json): receipt đếm/hash local. Sau đó đọc [README bundle](../w10-handoff-03_10/README-BAN-GIAO.md), `reports/`, `merged-partial/results.json`, raw `shards/*/runs/*/bundle.json` và `w8-a45/` cho ca mình điều tra.
4. [handoff-03_10.md](handoff-03_10.md) và [review-simplify-03_10.md](review-simplify-03_10.md): lịch sử cloud, commit, tests và findings đã vá. Một số trạng thái cũ/nhãn “Xong” không phải nghiệm thu chất lượng; đối chiếu mục34/36 và audit mới.
5. Đọc source/callers/tests/evidence của W đang làm. Báo cáo chỉ giúp tìm vấn đề; **không sửa dựa vào tóm tắt hoặc xem test xanh là đủ**. `AGENT.md` còn một số chính sách cũ; đối chiếu quyết định owner ở mục27–29 trước khi dùng.

## 2. Snapshot và dữ liệu có thể thiếu trên cloud

- Checkout local: `D:/create/BoxFox-Agent-Box`, **B@6732f9342c5d838bc49493f93641fdbb2ec0b350**. Đã đồng bộ main remote vào B ở lượt trước. Agent mới kiểm HEAD/remote/worktree thật; chỉ làm ở **B**, không checkout/sửa main.
- PR cloud [nganngan99hy-coder/BoxFox-Agent-Box#1](https://github.com/nganngan99hy-coder/BoxFox-Agent-Box/pull/1) đã merge; repo owner tích hợp qua [vukhai248/BoxFox-Agent-Box#5](https://github.com/vukhai248/BoxFox-Agent-Box/pull/5). Không coi hai repo có cùng mọi commit ID.
- Fork cloud B được quan sát tại `95a968f`. Sau head cũ `3f2ff6ae`, ba commit `744bc658`, `dbfad869`, `95a968f7` chỉ đổi harness partial/report/handoff (5 file), **không vá runtime thêm**. Chưa tự nhập ba commit này vào local B.
- W10 chạy sản phẩm **46ed557a**, chấm lại bằng oracle **3f2ff6ae**. Rescore không có nghĩa sản phẩm sau `3b23fa3`/`1bd238f` đã được chạy lại.
- Cập nhật phát hành 03/10: commit tài liệu gồm file bàn giao này, hai file audit local và phần cập nhật Work-Graph-fix. **Folder `docs/w10-handoff-03_10/` chưa đưa vào Git**; người dùng cần gửi gói dữ liệu kèm để cloud đọc raw evidence. Repo local còn WIP của user ở `.gitignore`, `HarnessFlowVisualizer.tsx` và các file docs/log bị xóa: không reset/clean/stage chung hoặc ghi đè.
- Hai nguồn nghiên cứu bị ignore: `research_prompt/simplify_subagent_prompt.md`; `research_code/research-pi-agent/PI-ARCHITECTURE-AND-BOXFOX-ASSESSMENT.md`. **Prompt Simplify đã được chép nguyên văn vào Work-Graph-fix mục37.1.1**, kèm phân tích/đối chiếu, nên vẫn đọc được mẫu khi file gốc không đi theo Git. Report Pi thiếu thì xin file hoặc clone ngoài project tại `https://github.com/earendil-works/pi`, pin nghiên cứu cũ `0495646a8322ff99ce40ac2f9e15f1f49f56bb11`; không vendor/thay harness bằng Pi.

## 3. Những quyết định owner phải giữ

- Main chọn assignment/dependencies/checks theo yêu cầu/rủi ro. **Không dựng pipeline theo role**, không bắt mọi sub qua cùng một review. Debug khi cần điều tra; lỗi test rõ có thể giao Build sửa trực tiếp.
- “Sub → main” là thông báo ngắn/ref. Handoff đã giao và đủ điều kiện có thể chạy ở backend song song với thông báo, **không cần main model relay**. Tách notification, handoff, main decision và user decision.
- Artifact có session/lượt/run/node ID, version/hash/binding; ID riêng **không phải mã hóa nội dung**. Agent sau đọc đúng ref/snapshot. Produced khác accepted; retry không tạo hai check/execution. Plan-only/research-only/design-only không tự Build.
- Sub soạn 1–3 câu mỗi vòng; main mở bằng ref hoặc backend xuất bản/tiếp tục theo grant. Ownership phiên chính, user-action/revision/idempotency; giữ câu hỏi/answer/checkpoint. Không timeout đoán câu trả lời. Hỏi user về ý định/quyết định, tự tra dữ kiện kỹ thuật trước.
- Ưu tiên cùng child/context/folder khi tiếp tục; cùng Testing child kiểm code mới nếu assignment còn tương thích. Không reuse pass cũ. Fallback child mới chỉ khi không resume được, phải ghi lý do.
- Reset budget **từng lượt** khi có answer/code/evidence thực sự mới; giữ lifetime usage/lỗi. Ba lượt không tiến triển thì báo main chọn hướng khác. **Child không vượt trần cha**; thời gian user suy nghĩ không là compute. Không tự tăng token/steps/time để che chất lượng kém.
- Review công tâm trước: source/acceptance/phản chứng phải chứng minh finding; thiếu proof ngoài scope không là lỗi chặn. Sau adjudication mới phân trách nhiệm main/producer, ghi W riêng nếu cần.
- Giữ **UI/UX**, model kiểm thử **OpenCode `opencode/space-bunny-free`**. Riêng **W12.MODEL.METADATA** được owner làm rõ: discovery adaptive cho OpenCode và các provider khác, model/thinking/token budget/limits/pricing có provenance/freshness; khôi phục selector hiện hữu và sửa metadata/mapping/request liên quan. Space Bunny là ca lỗi, không hardcode từng ID hoặc redesign composer. Contract/kiểu điều khiển mới phải trình scope riêng. CUA chỉ khi cần; không đổi provider/model kiểm thử để tăng điểm. Đổi kiến trúc/quyền/workflow mới phải trình thay đổi và đánh đổi để owner duyệt.

## 4. Local đã làm gì — đọc chi tiết tại Work-Graph-fix

| W | Checkpoint local | Đọc thêm / giới hạn |
|---|---|---|
| W0–W2 | Sửa schema/validation plan_scope, options/slug/glob, hướng phục hồi revision, capability errors; tách diagnostic/tools_run khỏi Markdown/source link | Mục13; kiểm optimistic lock còn nguyên. Lịch sử test tất định cuối 611 pass, không chứng minh chất lượng model |
| W3 | Research/Plan/Design producer16k, recovery bounded, phân biệt truncation/stream interrupted; không chạy tool call chưa hoàn chỉnh | Mục14; `W3-output-budget-evidence.json`. Ceiling cha/provider và helper lookup là nhánh khác, không giả định tất cả call16k |
| W4/W5 | Prompt đúng role/phạm vi/ngôn ngữ; parser findings và writer/document version refs | Mục15; `W4-W5-bugfix-evidence.json`. Live4role×2 chỉ7/8 hoàn tất, không gọi chuẩn SWE đạt |
| W6/W6.1 | Review16k, grounding/coverage/scope/calibration và adjudication | Mục16,18–26,32; các `W6.1*` report/evidence. Reviewer còn false-positive/prose sai; chưa hoàn tất chất lượng |
| W6.5 | Đo bước/time/output/requested-effective; child≤parent, không tổng quota tool mới | Mục17/19 và `W6.5-budget-report.md`, boundary/watchdog/concurrency evidence. Hai ca mất mạng không dùng làm lý do nâng timeout |
| W7 foundations | Durable feedback/answer, grant/ref, direct continuation, history/API | Mục30–31,33; `W7-*` evidence. UI/legacy history chưa nghiệm thu CUA |
| W8 A3/A4.1 | Artifact/input closure/manifest, notification-handoff tách, main decisions, chống lặp; cùng tester kiểm snapshot mới | Mục33; `W8-A3.*`, `W8-A4.1-retest-evidence.json`. Retest native2/2 trên source cuối; full suite source cuối bị dừng, không có verdict |
| Pi research | Đọc kiến trúc core/CLI/extensions và pi-durable experimental | Report bị ignore ở mục2. Có bài học intent/checkpoint/dedupe/replay; Pi không tự giải quyết fair review hoặc BoxFox DAG |

Goal local cũ đã được owner **chốt tại checkpoint và bàn giao**, không phải W7/W8 toàn bộ đạt. Các test trên là lịch sử có source/evidence riêng; lượt tạo file này không chạy lại test/model.

## 5. Cloud đã bổ sung gì

| Phần | Đã có trong code/evidence | Còn phải kiểm |
|---|---|---|
| W8.A4.2 | Scope tại tool list/dispatch/delegate/custom command; vá shell flag/quoting bypass | Giữ guard, không nới allowlist chỉ để fixture xanh |
| W8.A4.3/A4.4 | Worktree/touch-set, checkpoint/integration, ship đúng snapshot, giữ dirty user | Probe isolation/scoped ship đạt trong phạm vi ca đã đo; không là whole workflow đạt |
| W8.A4.5 | Repair có điều kiện, cùng Build child/fallback, converged integration review | Probe hiện **false**; fixture trigger đã vá nhưng rerun chưa hoàn tất; `__integration__` chưa native |
| W7/W1.P/W5.LEGACY | Action schema, structured errors, receipt recovery/replay, preflight, legacy contracts/API history | UI/legacy export/index/migration toàn bộ còn riêng; không lặp TODO đã được code hiện tại giải quyết |
| W6.1.3/W6.2 | verify_exec read-only/scratch, finding receipts, chặn bỏ finding hợp lệ, deliverable theo taskKind/depth | Native review4/6 oracle, false-positive control2/2; probe đó0/6 verify_exec. W10 có6 calls bị fixture từ chối: hai dữ kiện khác nhau |
| W6.5.3 | Helper knowledge4096→16000 | 32lượt: length5/16→0/16; timeout cấu hình khác giữa nhóm, không kết luận riêng tăng cap làm nhanh hơn |
| W9/W10 | Recorder/CDP robustness, harness/oracles/rescore và báo cáo một phần | Recorder evidence tốt; W10 chưa đủ/đúng phép đo. CUA UI chỉ runbook |

Cloud báo suite988pass/2fail/1skip, targeted294pass/1skip và E2E đạt; đọc log/commit trong `review-simplify-03_10.md` và audit§3.5 trước khi gán cho HEAD hiện tại. Không loại hai test môi trường khỏi thống kê. Compose có `seccomp=unconfined`, `apparmor=unconfined`, network mặc định on theo quyết định owner mà cloud ghi; giữ rõ đánh đổi, không âm thầm nới thêm.

## 6. Vì sao còn lỗi và cần sửa phép đo trước

Gói có20bundle nhưng merged mới16/24: statePassed4/16, passed0/16, gatefalse, **10/16 no_run** (report cũ viết8). Thiếu S02/S12 và report shard1/6; thiếu DB/events các trang sau. 30artifact hash khớp chỉ chứng minh integrity. Không đổ toàn bộ0/16 cho model hoặc coi các counter0 là an toàn đã được chứng nhận.

| Việc mở | Nguyên nhân/tác hại đã xác nhận | Đọc chi tiết và expected checkpoint |
|---|---|---|
| W10.M1 | Export chỉ trang500events;57sessions chạm trần, mất final/receipt/interview | Audit§9.4H1, `_safe_events()`/SessionStore.events. Fixture>500 thấy marker cuối và đủ seq; xin raw data rồi rescore |
| W10.M2 | Restart caller collect DB cũ;647/647call thiếu sessionId, faultchild rơi vào main | H2/H3; `drive_session`/`_restart_session`/`run_cell`/RecordingClient. Thu đúng store mới, identity thật, root không nhận child fault |
| W10.M3 | Executor không có verify_exec/commands worktree; oracle hỏi≤3 toàn run, revision thành answer; partial/state/quality gate sai nghĩa | H4/H5. Positive/negative controls cho parity và oracle; giữ scope; requested/effective/driver riêng; missing là lỗi đo có giữ mẫu số |
| W8.A4.5.N | Đường repair chưa có probe khép kín xanh, integration chưa đo | Audit§3.1/9.6, repair evidence + raw workspace. Đỏ→sửa→tester cũ retest hash mới; Debug có điều kiện; thêm integration |
| W6.Q/W6.2.BIND | Review có finding chưa công tâm/prose sai; claim main mới chưa được chứng nhận bởi whole-pass cũ | Work-Graph-fix§34.4, audit§3.3/9.5. Adjudicate từng finding; sửa review trước, producer/main sau đúng tác nhân |
| W11.PROMPT | Giao việc cần cụ thể hơn; role/skill có thể áp sai quyền/độ sâu/baseline | **Mục37**: phân tích prompt Simplify đã xong; inventory → đề xuất nhỏ → tests → A/B output. Chưa sửa runtime/prompt/skill |
| W12.MODEL.METADATA | Bug Space Bunny mất thinking đã được user xác nhận; owner yêu cầu adaptive theo provider vì inventory/thinking/budget/giá thay đổi | **Mục38**: cơ chế discovery/refresh đã có; kiểm metadata/freshness đi đủ pipeline, model mới/retired và field đổi. Tách effort/budget/limits/quota/price; thiếu API fields thì nguồn bổ sung hoặc unknown, không hardcode/đoán/free |

**Prompt duy nhất cho cloud:** Work-Graph-fix§38.6 hợp nhất prompt tiếp nhận checkpoint và yêu cầu W12. Nó có đủ nội dung để cloud đang dùng repo cũ ghi W mới vào `docs/plan/Work-Graph-fix.md` trước khi sửa code; nếu W đã tồn tại thì cập nhật, nếu ID đã dùng cho việc khác thì chọn ID tiếp theo và ghi mapping. W mới bổ sung nhiệm vụ, không thay việc hoàn thiện các W còn mở trong bản bàn giao cũ.

Đợt19–20giờ không hội tụ liên quan nhiều yếu tố: review sai scope, thay node/criteria, partial/provider failures, fixture và thu bằng chứng lỗi, chạy nhiều vòng rộng. Audit§4 có chứng cứ; chưa có trace phân bổ chính xác toàn20giờ, không quy tất cả cho timeout/mạng. Tăng token không chữa các nguyên nhân này.

## 7. Thứ tự tiếp tục và cách bàn giao lần sau

- [ ] **Nhận việc:** xác minh B/HEAD/WIP, đọc các file mục1, liệt kê evidence thiếu và scope dự định sửa; không sửa chồng một task đang chạy.
- [ ] **Dễ trước:** M1 → M2 → M3, unit/fixture nhỏ không model; xin dữ liệu gốc khi thiếu. Không chạy lại24ca trên harness hiện tại.
- [ ] **Adaptive metadata:** W12 theo mục38; fixture provider đổi model/levels/budget/pricing qua refresh, rồi picker/payload/persistence. Space Bunny là pilot live lỗi đã báo, các provider khác kiểm discovery/API và fixtures; không cần mở DAG hoặc gọi inference cho mọi model. Ghi provenance/freshness/unknown và applied selection.
- [ ] **Kiểm cơ chế:** native pilot repair/integration A4.5.N sau khi fixture đúng. Kiểm budget/interview/replay theo quyết định đã duyệt, không đổi scheduler để chữa lỗi đo.
- [ ] **Kiểm nội dung:** W6.Q và W11 inventory/prompt theo scope riêng; review-first, corpus cũ còn đủ nguồn dùng được; thiếu thì mới gọi Space Bunny. Chuẩn Plan/Research/Design và ma trận output đúng ở mục37.
- [ ] **Nghiệm thu:** W10.F freeze product/oracle/config/applied budget; pilot ít ca rồi12scenario×2 khi phép đo đúng. Báo mọi failure, product/provider/measurement riêng; đọc nội dung đúng prompt AI bệnh án thực, không thay bằng API nhỏ rồi gọi nghiệm thu y tế.
- [ ] **Việc riêng sau:** policy version/legacy compatibility, W6.2.BIND, legacy export/index, W2.UI/W9.UI và simplify code chỉ triển khai khi scope tương ứng được duyệt. Không coi prompt tham khảo là quyền cleanup.

Mỗi checkpoint cập nhật **Work-Graph-fix.md**: source/commit, files, lệnh thật + kết quả, model/config, refs/version/hash, lỗi còn lại, bước tiếp tục. Chỉ tick phần kiểm được; giữ failure/cancelled/incomplete. Patch và commit nhỏ trên B theo quyền đợt làm việc; không `git add -A` vào WIP, không push/merge nếu chưa được yêu cầu. Nếu cần thay kiến trúc, trình current → proposed → tradeoff và chờ owner duyệt. Gửi tiến độ ngắn khi làm lâu.

**Tình trạng file này:** tài liệu bàn giao; chưa triển khai các ô trống, chưa có test/model/CUA mới. Chi tiết quyết định và test cases nằm trong các file được dẫn ở trên.

## 8. Trạng thái lượt local 02/10/2026 (UTC, tối) — branch `vorflux/w10-w12-completion`

Branch `vorflux/w10-w12-completion` tách từ B `4e0923d`, **17 commit**, working tree sạch. **Chưa push, chưa mở PR** (chờ yêu cầu). Chi tiết + bằng chứng ở Work-Graph-fix **mục 39** (mục 37 W11, mục 38 W12 giữ nguyên):

| Việc | Trạng thái | Bằng chứng chính |
|---|---|---|
| W10.M1/M2/M3 (phép đo) | **Đã commit + xác minh dữ liệu thật** | `dd69edf`, `c731318`; `test_work_acceptance_bench.py` 64 passed; lượt S09 pilot3: `missing: []`, `measurementInvalid: false`, bundle 48 596 event = DB, 92/92 lượt gọi có `sessionId`, ngân sách requested/effective + clampNotices |
| W12.MODEL.METADATA | Đã commit + kiểm live | `f2f2260`, `3265475`, `e62c0f7`; router `npm test` 257 passed; ảnh picker `w12-thinking-space-bunny-picker.png` |
| W11.PROMPT | P0b + nhánh Simplify đã commit; P0c và câu vendor/`AGENT.md` chờ owner | `9d5ab04`, `182a974`; `docs/plan/W11-p0b-inventory.md` |
| W8.A4.5.N (`__integration__`) | **Một nửa có bằng chứng native**; `oracle` vẫn `false` | `3d6fd2f`, `346430f`, `473e6ad`, `500665a`, `664f25e`, `6f7ea56`, `1f53f9e`; 7 lượt probe, bằng chứng `docs/plan/W8.A4.5.N-repair-loop-native-evidence.json`; lượt 7: node `__integration__` dựng thật + child Testing chạy trên cây gộp |
| S09 pilot (kịch bản) | **Chưa đạt** (giữ trong thống kê) | Work-Graph-fix 39.7: root dừng ở `discovering`, chưa tới bước hỏi/thi công trong 45 phút |
| W6.1 C4/C5, W6.Q, W6.2.BIND, W6.5.2, W7.1 UI, W7.2, W9.UI, W10.F | Vẫn mở | Work-Graph-fix 39.5/39.6; W6.5.2 đã có tracing bằng mã (ngân sách per-call) |

Phạm vi đã giữ: chỉ OpenCode `opencode/space-bunny-free` cho inference; không đổi UI/UX; không đổi kiến trúc/quyền/workflow; không push/merge.

**Hai việc cần owner quyết trước khi làm tiếp:** (1) cò đỏ của fixture W8.A4.5.N nên gieo đỏ thật thay vì trả traceback cắm sẵn (đổi ngữ nghĩa phép đo); (2) câu vendor `simplify-code/SKILL.md` dòng 195 và `AGENT.md:12/:20` so với §27–29.
