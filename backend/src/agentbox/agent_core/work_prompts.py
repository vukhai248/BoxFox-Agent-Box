"""Existing Work Graph prompt contracts. No scheduling, persistence or permissions.

Protocol markers remain stable; owner-visible prose follows the original owner goal.
Reasoning and system instructions may use English. References and identifiers are data.
"""
import re
import unicodedata


def language(text):
    """Infer presentation language without interpreting a dependency as owner intent."""
    raw = str(text or '')
    owner = re.search(r'^(?:Overall owner goal|Owner goal|Mục tiêu của người dùng):\s*(.*)$', raw, re.M)
    if owner:
        raw = owner[1]
    folded = ''.join(c for c in unicodedata.normalize('NFD', raw.lower().replace('đ', 'd'))
                     if not unicodedata.combining(c))
    explicit = list(re.finditer(r'\b(?:in english|bang tieng anh|in vietnamese|bang tieng viet)\b', folded))
    if explicit:
        return 'en' if explicit[-1][0] in ('in english', 'bang tieng anh') else 'vi'
    if re.search(r'[đăơưĐĂƠƯạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]', raw):
        return 'vi'
    return 'vi' if re.search(r'\b(?:giup toi|toi can|toi muon|ke hoach|ho so|du lieu|tieng viet)\b', folded) else 'en'


def choose(lang, english, vietnamese):
    return vietnamese if lang == 'vi' else english


KNOWLEDGE = {
    'en': """## Knowledge requests
Only when a missing FACT blocks you; one line each, max 3:
- research: <external factual question>
- explore: <repository factual question>
Write `- none` when you need nothing. These markers are protocol, not prose to translate.
You cannot delegate or interview the owner; report missing owner decisions as open questions, not factual lookup requests. Never guess the owner's answer.""",
    'vi': """## Knowledge requests
Chỉ dùng khi thiếu dữ kiện đã xác minh khiến bạn không thể tiếp tục; tối đa 3 dòng:
- research: <câu hỏi dữ kiện bên ngoài>
- explore: <câu hỏi dữ kiện trong repository>
Ghi `- none` khi không cần. Giữ nguyên các marker này để harness đọc được.
Bạn không được giao việc hoặc phỏng vấn người dùng; nêu quyết định cần người dùng trả lời ở mục câu hỏi còn mở, không biến chúng thành yêu cầu tra cứu. Không tự đoán câu trả lời.""",
}

DELIVERABLES_EN = {
    'explore': """Deliverable (Markdown, in the owner's language):
## Findings — existing behavior, most important first, with path:line.
## Evidence table — claim, opened path:line, short quote.
## Contracts & call sites — functions, routes, events, data shapes relevant to the assignment.
## Risks & unknowns — what you could not confirm; planned paths are not existing files.""",
    'research': """Deliverable (Markdown, in the owner's language):
## Answer — direct answer, 3–8 sentences; this limit applies only to this section.
## Scope & method — question, scope, as-of date, sources opened and search limitations.
## Verified facts — each consequential fact mapped to an exact opened URL/path and short quote. Distinguish source statements from inference.
## Options compared — relevant alternatives, cost/fit/tradeoffs when there is a choice.
## Contrary evidence & gaps — contradictory findings, unavailable sources, open owner decisions; label UNVERIFIED. Not found does not mean nonexistent.
## Recommendation — reasoned proposal and what would change it. Do not invent implementation scope or a sub-plan unless requested.""",
    'design': """Deliverable (Markdown, in the owner's language):
## Goal & scope — identify architectural/API, UI/UX or prototype design; follow the assignment, not a default screen template.
## Structure — components, responsibilities, boundaries and core data contracts with types.
## Flows & failures — normal/error/auth/async behavior as applicable. UI tasks additionally define empty/loading/permission states; API-only work need not invent screens.
## Touch list — existing paths you read versus planned paths to create.
## Alternatives & tradeoffs — relevant alternative, decision and reasons.
## Acceptance & unknowns — observable design checks, unresolved owner decisions, risks. Do not implement or scaffold.""",
    'plan': """Deliverable: ONE sub-plan in Markdown, in the owner's language, proportional to the assignment:
## Goal & scope — users, outcome, main flow, success and non-goals; confirmed intent versus proposals/open questions. Unrelated old plans are not requirements.
## Evidence & current state — verified facts with opened path:line/URL; reuse/new/gaps. Distinguish existing from planned paths.
## Architecture & decisions — components, responsibilities, flow/errors, selected stack and purpose, alternatives and tradeoffs.
## Data & contracts — entities/IDs/types, schema/invariants/validation/lifecycle/migrations; API/event inputs/outputs/errors/auth/async/idempotency where relevant.
## AI & evaluation — when applicable: AI role, simple baseline, model choice, grounding, dataset/split/unit/denominator, scoring correctness/omissions/unsupported claims/abstention, fallback/human review, cost/latency. Unsupported thresholds are proposals to calibrate.
## Operations & risks — deployment/config/secrets/observability/retry/backup/rollback as relevant.
## Milestones M1…Mn — dependencies, assigned role, exact existing/planned paths and edits, deliverable, test file/command/check and expected result per milestone. Proposed tests are not test runs.
## Traceability & acceptance — requirement → decision → milestone → check; unresolved consequential decisions explicitly open. Merge small sections or explain N/A; do not pad headings.""",
    'build': """Deliverable (Markdown, in the owner's language):
## Changes — files and edits within the approved sub-plan.
## Test run — commands actually run and observed results, or NOT RUN with reason.
## Deviations & risk — differences from the assignment, remaining unverified behavior.""",
    'debug': """Deliverable (Markdown, in the owner's language):
## Reproduction — actual command/input and observed failure; otherwise NOT REPRODUCED.
## Root cause — evidence with path:line; confirmed cause versus hypothesis.
## Fix or recommendation — diagnosis-only assignments must not edit files. When a patch is authorized, list edits.
## Proof & limits — before/after reproduction and regression results only if actually run; mark NOT RUN and remaining questions. Do not turn diagnosis into a mandatory plan or patch.""",
    'testing': """Deliverable (Markdown, in the owner's language):
## Test matrix — acceptance case, input, expected, actual, pass/fail/NOT RUN.
## Evidence — real commands/output, fixtures/environment; screenshots only when relevant and captured.
## Failures & limits — exact errors, reproduction, untested cases. No invented passes or screenshots.""",
    'simplify': """Deliverable (Markdown, in the owner's language):
## Simplifications — files/patterns changed within scope.
## Behavior proof — before/after commands and actual output; unrun tests remain NOT RUN.
## Limits — remaining risk and unknowns.""",
}

DELIVERABLES_VI = {
    'explore': """Đầu ra Markdown bằng tiếng Việt có dấu:
## Phát hiện — hành vi đang tồn tại, quan trọng trước, kèm path:line.
## Bằng chứng — bảng khẳng định, path:line đã mở, trích ngắn.
## Hợp đồng và nơi gọi — hàm, route, event, dạng dữ liệu liên quan nhiệm vụ.
## Rủi ro và điều chưa rõ — chưa xác minh; đường dẫn dự kiến không phải file có sẵn.""",
    'research': """Đầu ra Markdown bằng tiếng Việt có dấu:
## Trả lời — trả lời trực tiếp trong 3–8 câu; giới hạn chỉ áp dụng mục này.
## Phạm vi và phương pháp — câu hỏi, phạm vi, mốc thời gian, nguồn đã mở và giới hạn tìm kiếm.
## Dữ kiện đã xác minh — từng dữ kiện quan trọng liên kết URL/path đã mở và trích ngắn. Phân biệt lời nguồn với suy luận.
## So sánh phương án — lựa chọn liên quan, chi phí, độ phù hợp, đánh đổi khi cần.
## Bằng chứng trái chiều và khoảng trống — mâu thuẫn, nguồn không đọc được, quyết định chờ người dùng; ghi UNVERIFIED. Chưa tìm thấy không đồng nghĩa không tồn tại.
## Khuyến nghị — đề xuất, lý do và điều có thể thay đổi lựa chọn. Không tự mở phạm vi triển khai hoặc tạo sub-plan nếu chưa được yêu cầu.""",
    'design': """Đầu ra Markdown bằng tiếng Việt có dấu:
## Mục tiêu và phạm vi — xác định thiết kế kiến trúc/API, UI/UX hay prototype theo nhiệm vụ.
## Cấu trúc — thành phần, trách nhiệm, ranh giới và hợp đồng dữ liệu có kiểu.
## Luồng và lỗi — hành vi bình thường, lỗi, quyền và bất đồng bộ khi áp dụng. UI thêm trạng thái rỗng/đang tải/quyền; thiết kế API không tự thêm màn hình.
## Vị trí tác động — phân biệt path đã đọc đang tồn tại với path dự kiến tạo.
## Phương án và đánh đổi — lựa chọn thay thế liên quan, quyết định và lý do.
## Nghiệm thu và điều chưa rõ — kiểm chứng thiết kế, quyết định chờ người dùng, rủi ro. Không triển khai hoặc scaffold.""",
    'plan': """Đầu ra: MỘT sub-plan Markdown bằng tiếng Việt có dấu, độ sâu theo nhiệm vụ:
## Mục tiêu và phạm vi — người dùng, kết quả, luồng chính, thành công, ngoài phạm vi; ý định đã xác nhận, đề xuất, câu hỏi mở. Plan cũ khác việc không là yêu cầu.
## Bằng chứng và hiện trạng — dữ kiện đã xác minh với path:line/URL đã mở; tận dụng/tạo mới/khoảng trống. Phân biệt path tồn tại và dự kiến.
## Kiến trúc và quyết định — thành phần, trách nhiệm, luồng/lỗi, stack và mục đích, phương án thay thế, đánh đổi.
## Dữ liệu và hợp đồng — entity/ID/kiểu, schema/bất biến/validation/vòng đời/migration; API/event input/output/lỗi/quyền/async/idempotency khi liên quan.
## AI và đánh giá — khi áp dụng: vai trò AI, baseline đơn giản, chọn model, grounding, dataset/split/đơn vị/mẫu số, chấm đúng/thiếu/không có căn cứ/từ chối kết luận, fallback/người duyệt, chi phí/độ trễ. Ngưỡng thiếu bằng chứng là đề xuất cần hiệu chỉnh.
## Vận hành và rủi ro — triển khai/cấu hình/bí mật/quan sát/retry/backup/rollback khi liên quan.
## Milestone M1…Mn — phụ thuộc, role thực hiện, path tồn tại/dự kiến và thay đổi, đầu ra, file test/lệnh/kiểm tra và kết quả mong đợi từng mốc. Test dự kiến không phải kết quả đã chạy.
## Truy vết và nghiệm thu — yêu cầu → quyết định → milestone → kiểm tra; nêu quyết định quan trọng còn mở. Gộp mục cho việc nhỏ hoặc giải thích không áp dụng; không lấp bằng tiêu đề.""",
    'build': """Đầu ra Markdown bằng tiếng Việt có dấu:
## Thay đổi — file và chỉnh sửa trong sub-plan được duyệt.
## Kiểm thử — lệnh thực sự chạy, kết quả quan sát hoặc NOT RUN kèm lý do.
## Khác biệt và rủi ro — khác nhiệm vụ ở đâu, hành vi chưa xác minh.""",
    'debug': """Đầu ra Markdown bằng tiếng Việt có dấu:
## Tái hiện — lệnh/input thực tế và lỗi quan sát; chưa tái hiện ghi NOT REPRODUCED.
## Nguyên nhân — bằng chứng path:line; phân biệt nguyên nhân xác nhận và giả thuyết.
## Sửa hoặc khuyến nghị — nhiệm vụ chỉ chẩn đoán không được sửa file; được phép patch thì liệt kê chỉnh sửa.
## Chứng minh và giới hạn — tái hiện trước/sau và hồi quy chỉ khi đã chạy; ghi NOT RUN và câu hỏi mở. Không ép chẩn đoán thành plan hoặc patch.""",
    'testing': """Đầu ra Markdown bằng tiếng Việt có dấu:
## Ma trận kiểm thử — tiêu chí, input, expected, actual, pass/fail/NOT RUN.
## Bằng chứng — lệnh/output thực, fixture/môi trường; ảnh chỉ khi liên quan và thực sự chụp.
## Lỗi và giới hạn — lỗi nguyên văn, cách tái hiện, ca chưa chạy. Không bịa pass hoặc ảnh.""",
    'simplify': """Đầu ra Markdown bằng tiếng Việt có dấu:
## Đơn giản hóa — file/pattern chỉnh trong phạm vi.
## Chứng minh hành vi — lệnh trước/sau và output thực; chưa chạy ghi NOT RUN.
## Giới hạn — rủi ro và điều chưa rõ.""",
}

RUBRICS_EN = {
    'explore': 'Open at most 6 decision-critical cited paths. Block invented paths/symbols, substantively wrong claims or missing required call sites. Do not re-explore the repo.',
    'research': 'Open at most 6 decision-critical sources. Check claim/source entailment, contrary evidence, and separation of observation/inference/proposal. Unopened sources remain UNVERIFIED; not found is not proof of absence. Do not require an unsolicited implementation plan.',
    'design': 'Check the assigned design subtype, component/data/API consistency, existing versus planned paths, relevant failures and observable acceptance. Empty/loading/screen states are required only for UI work; do not demand screens for API design.',
    'plan': 'Check goal coverage, grounded current state, justified architecture/stack, data/contracts, proportional operations and risks, milestones/dependencies, test/check expected results and traceability. Check baseline/dataset/scoring/calibration/fallback for AI when applicable. A heading or citation alone does not prove correctness. Do not require unrun proposed tests to pass already.',
    'build': 'Read the reported changes and real test evidence against acceptance. Execute tests only if your available tools and assignment permit; otherwise mark NOT RUN and the verification gap. Do not call unavailable terminal_exec or invent a pass. Do not edit files.',
    'debug': 'For diagnosis-only, check reproduction, causal evidence and limits; do not require a patch. For an authorized patch, also check changes and actual before/after regression evidence. Never invent test execution.',
    'testing': 'Check actual versus expected, acceptance coverage, edge cases, commands/output and NOT RUN limitations. A command listed in a plan is not a test execution.',
    'simplify': 'Read changes and before/after evidence that behavior is unchanged. Run tests only when tools and scope permit, otherwise report NOT RUN; do not edit files.',
}
RUBRICS_VI = {
    'explore': 'Mở tối đa 6 path quan trọng cho quyết định. Chặn path/symbol bịa, khẳng định sai bản chất hoặc thiếu nơi gọi bắt buộc. Không khảo sát lại toàn repo.',
    'research': 'Mở tối đa 6 nguồn quan trọng; kiểm nguồn có hỗ trợ khẳng định, bằng chứng trái chiều, phân biệt dữ kiện/suy luận/đề xuất. Nguồn chưa mở giữ UNVERIFIED; chưa tìm thấy không chứng minh không tồn tại. Không yêu cầu plan triển khai ngoài nhiệm vụ.',
    'design': 'Kiểm đúng loại thiết kế được giao, thống nhất thành phần/data/API, path tồn tại/dự kiến, lỗi liên quan và nghiệm thu. Trạng thái màn hình rỗng/đang tải chỉ bắt buộc cho UI; không đòi màn hình cho API.',
    'plan': 'Kiểm bao phủ mục tiêu, hiện trạng có căn cứ, kiến trúc/stack có lý do, data/hợp đồng, vận hành/rủi ro theo quy mô, milestone/phụ thuộc, test/check có expected và truy vết. AI cần baseline/dataset/cách chấm/hiệu chỉnh/fallback khi áp dụng. Tiêu đề hoặc citation không chứng minh đúng. Không bắt test mới được đề xuất phải chạy pass sẵn.',
    'build': 'Đọc thay đổi và bằng chứng test thực đối chiếu nghiệm thu. Chỉ chạy test khi công cụ được cấp và nhiệm vụ cho phép; nếu không, ghi NOT RUN và khoảng trống kiểm chứng. Không gọi terminal_exec không khả dụng, không bịa pass. Không sửa file.',
    'debug': 'Chỉ chẩn đoán: kiểm tái hiện, bằng chứng nguyên nhân và giới hạn, không đòi patch. Patch được phép: kiểm thêm thay đổi và hồi quy trước/sau thực tế. Không bịa kết quả chạy.',
    'testing': 'Kiểm actual so với expected, bao phủ nghiệm thu/biên, lệnh/output và giới hạn NOT RUN. Lệnh ghi trong plan chưa là lần chạy test.',
    'simplify': 'Đọc thay đổi và bằng chứng trước/sau giữ hành vi. Chỉ chạy test khi công cụ/phạm vi cho phép, nếu không ghi NOT RUN; không sửa file.',
}

REVIEW_TAIL_EN = """A finding is BLOCKING when relying on the output would make the next step or owner decision wrong. Style and optional detail are NON-BLOCKING. Missing consequential decisions/evidence are blocking, not cosmetic. With no blocking findings use `ok`. Check, do not redo the work.
Before making a blocking finding, identify the exact assigned requirement, read the relevant artifact passage and original source, and consider the strongest counterargument to your finding. Search/open a targeted authoritative alternative if a material source cannot be opened or contradicts the claim and search tools are available. Record what you actually checked, including failed access. A declared limitation is not itself a defect: block only when it undermines a required conclusion or deliverable. Proposals need rationale, not proof they already exist. Do not reject local fixture provenance merely because it is a fixture when the assignment explicitly uses that evidence. Unsupported suspicion stays UNVERIFIED; never assert it as a confirmed error. Optional work outside owner scope is non-blocking. For each blocking finding cite requirement, observed evidence, counterevidence considered, concrete impact and smallest necessary fix.
## Blocking findings — acceptance/section, evidence and exact fix; write `none` if empty.
## Non-blocking notes — optional.
END with one final line `VERDICT: ok` or `VERDICT: revise`, with nothing after it. Keep this protocol marker unchanged."""
REVIEW_TAIL_VI = """Finding chặn khi dùng đầu ra khiến bước tiếp theo hoặc quyết định người dùng sai. Văn phong và chi tiết tùy chọn là ghi chú không chặn. Thiếu quyết định/bằng chứng quan trọng là vấn đề chặn. Không còn vấn đề chặn thì dùng `ok`. Kiểm tra, không làm lại công việc.
Trước khi chặn, chỉ rõ yêu cầu được giao, đọc đoạn artifact và nguồn gốc liên quan, xét bằng chứng mạnh nhất có thể bác bỏ chính finding của bạn. Nếu nguồn quan trọng không mở được hoặc trái với khẳng định, dùng search/read được cấp để tìm và mở nguồn chính thức thay thế có mục tiêu. Ghi điều thực sự đã kiểm, kể cả truy cập thất bại. Giới hạn đã khai báo không tự là lỗi: chỉ chặn khi nó làm mất căn cứ của kết luận hoặc đầu ra bắt buộc. Đề xuất cần lý do, không cần chứng minh đã triển khai. Không bác nguồn fixture chỉ vì là fixture khi nhiệm vụ dùng dữ liệu đó. Nghi ngờ chưa có bằng chứng giữ UNVERIFIED, không gọi là lỗi đã xác nhận. Việc tùy chọn ngoài phạm vi không chặn. Mỗi finding chặn nêu yêu cầu, bằng chứng quan sát, bằng chứng phản bác đã xét, hệ quả cụ thể và sửa tối thiểu cần thiết.
## Vấn đề chặn — tiêu chí/mục, bằng chứng và sửa cụ thể; ghi `none` nếu trống.
## Ghi chú không chặn — tùy chọn.
KẾT THÚC bằng đúng một dòng `VERDICT: ok` hoặc `VERDICT: revise`, không có chữ phía sau. Giữ nguyên marker này."""


def deliverable(kind, lang='en'):
    return (DELIVERABLES_VI if lang == 'vi' else DELIVERABLES_EN).get(kind)


def rubric(kind, lang='en'):
    values = RUBRICS_VI if lang == 'vi' else RUBRICS_EN
    return values.get(kind, values['plan'])


def review_tail(lang='en'):
    return choose(lang, REVIEW_TAIL_EN, REVIEW_TAIL_VI)


def child_contract(purpose, lang='en'):
    if purpose == 'review':
        return choose(lang, '\n\nIndependent Work Graph review: read evidence yourself. End with the single VERDICT line.',
                      '\n\nPhản biện Work Graph độc lập: tự đọc bằng chứng. Câu trả lời cuối tiếng Việt có dấu, giữ identifier và trích dẫn. Kết thúc bằng một dòng VERDICT.')
    if purpose == 'knowledge' and lang == 'vi':
        return '\n\nTrả lời tra cứu bằng tiếng Việt có dấu: dữ kiện liên quan, bằng chứng đã đọc, kiểm chứng thực hiện và giới hạn. Giữ nguyên path/URL/identifier/trích dẫn. Không bịa nguồn hoặc quyết định của người dùng.'
    if purpose != 'produce':
        return None
    return choose(lang, """\n\nWork Graph result contract: put the full deliverable in your final answer for the independent reviewer. Stay within the assignment and acceptance. Factual claims need opened path:line/URL or real command output. Label inference, proposals and unresolved owner decisions explicitly; do not invent evidence or user confirmation. Reasoning may be English; final text follows the owner, preserving identifiers/quotes.
""", """\n\nHợp đồng đầu ra Work Graph: đặt toàn bộ báo cáo trong câu trả lời cuối cho reviewer độc lập. Giữ đúng nhiệm vụ và nghiệm thu. Dữ kiện cần path:line/URL đã mở hoặc output lệnh thực. Ghi rõ suy luận, đề xuất và quyết định chờ người dùng; không bịa bằng chứng hoặc xác nhận. Có thể suy nghĩ tiếng Anh; câu trả lời cuối tiếng Việt có dấu, giữ identifier/trích dẫn.
""") + KNOWLEDGE[lang if lang == 'vi' else 'en']


def whole_review_goal(title, goal, lang='en', research_only=False):
    if research_only:
        return choose(lang, f'''Whole-plan review of Work Graph run "{title}" — research deliverable.
Owner goal: {goal}
Check research coverage, claim/source entailment, consistency across nodes, owner scope, uncertainty and limitations.
This is research, not an implementation contract. Do not require an app plan, API/schema/defaults, rollout/rollback or executed tests unless the owner requested them. Keep optional implementation detail non-blocking.
For each research node that must change write `REVISE <nodeId>: <what to fix>`.
''', f'''Phản biện toàn kế hoạch Work Graph "{title}" — sản phẩm nghiên cứu.
Mục tiêu của người dùng: {goal}
Kiểm bao phủ câu hỏi nghiên cứu, nguồn hỗ trợ khẳng định, thống nhất giữa các nút, phạm vi người dùng, độ bất định và giới hạn.
Đây là nghiên cứu, chưa phải hợp đồng triển khai. Không đòi plan app, API/schema/default, rollout/rollback hay test đã chạy nếu người dùng chưa yêu cầu. Chi tiết triển khai tùy chọn là ghi chú không chặn.
Với từng nút nghiên cứu cần sửa ghi `REVISE <nodeId>: <nội dung cần sửa>`. Giữ nguyên marker REVISE.
''') + review_tail(lang)
    return choose(lang, f'''Whole-plan review of Work Graph run "{title}" before the owner approves it.
Owner goal: {goal}
Check goal/owner-decision COVERAGE, DEPENDENCIES (declared needs, no hidden coupling, consistent contracts), ORDER (safe execution waves), TESTS (concrete checks that prove the goal) and RISK (rollout/rollback).
For each sub-plan that must change write `REVISE <nodeId>: <what to fix>`. Missing sub-plans or wrong dependencies are blocking.
''', f'''Phản biện toàn kế hoạch Work Graph "{title}" trước khi người dùng duyệt.
Mục tiêu của người dùng: {goal}
Kiểm bao phủ mục tiêu/quyết định người dùng; phụ thuộc đã khai báo, không liên kết ngầm, hợp đồng thống nhất; thứ tự thực thi an toàn; kiểm thử cụ thể chứng minh mục tiêu; rủi ro, rollout và rollback.
Với từng sub-plan cần sửa ghi `REVISE <nodeId>: <nội dung cần sửa>`. Thiếu sub-plan hoặc sai phụ thuộc là vấn đề chặn. Giữ nguyên marker REVISE.
''') + review_tail(lang)
