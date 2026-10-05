"""W4 prompt bugs and W5 existing document bugs; no new graph policy or store."""
import asyncio
import hashlib
import json
from pathlib import Path, PurePosixPath

import pytest

from agentbox.agent_core import work_graph as wg, work_prompts as wp
from agentbox.agent_core.roles import READ, ROLES
from agentbox.agent_core.runtime import CHILD_EXPECT_MAX_CHARS, HarnessRuntime
from agentbox.memory.session_store import SessionStore
from test_work_graph import build, tool, PLAN, EXPLORE
from test_runtime_prompt import Executor, Model, system_prompt


@pytest.mark.parametrize('goal,expected', [
    ('Giúp tôi lập kế hoạch tổng hợp hồ sơ.', 'vi'),
    ('giup toi lap ke hoach cho app', 'vi'),
    ('Add an export button to the app', 'en'),
    ('We can deploy an API', 'en'),
    ('Giúp tôi kiểm tra, write the report in English', 'en'),
    ('Design an API, write in Vietnamese', 'vi'),
    ('Work Graph "Kế hoạch"\nOverall owner goal: Add an API\nYour assignment: Đọc dữ liệu', 'en'),
    ('Work Graph "x"\nMục tiêu của người dùng: Giúp tôi tổng hợp hồ sơ\nNhiệm vụ: Read code', 'vi'),
])
def test_language_uses_owner_goal_and_explicit_output_request(goal, expected):
    assert wp.language(goal) == expected


@pytest.mark.parametrize('lang', ['en', 'vi'])
@pytest.mark.parametrize('role', list(wp.DELIVERABLES_EN))
def test_role_templates_fit_existing_expectation_limit(lang, role):
    assert 100 <= len(wp.deliverable(role, lang)) <= CHILD_EXPECT_MAX_CHARS
    assert wp.rubric(role, lang)


def test_roles_do_not_force_unrequested_scope_or_fake_evidence():
    assert 'API-only work need not invent screens' in wp.deliverable('design')
    assert 'diagnosis-only assignments must not edit files' in wp.deliverable('debug')
    assert 'unless requested' in wp.deliverable('research')
    assert 'Not found does not mean nonexistent' in wp.deliverable('research')
    assert 'Proposed tests are not test runs' in wp.deliverable('plan')
    assert 'inference, proposals and unresolved owner decisions' in wp.child_contract('produce')
    assert 'unavailable terminal_exec' in wp.rubric('build')
    assert 'do not require a patch' in wp.rubric('debug')
    assert 'Milestones M1' in wp.deliverable('plan')
    for word in ('schema', 'migration', 'baseline', 'denominator', 'rollback', 'Traceability'):
        assert word in wp.deliverable('plan')


def test_research_whole_review_keeps_research_scope_and_vietnamese_final():
    prompt = wp.whole_review_goal('CSV scope', 'Chỉ nghiên cứu phạm vi CSV', 'vi', research_only=True)
    assert 'Không đòi plan app' in prompt and 'nguồn hỗ trợ khẳng định' in prompt
    assert 'REVISE <nodeId>:' in prompt
    assert 'tiếng Việt có dấu' in wp.child_contract('review', 'vi')


@pytest.mark.parametrize('lang', ['vi', 'en'])
def test_protocol_markers_remain_parseable(lang):
    assert '## Knowledge requests' in wp.child_contract('produce', lang)
    assert '- research:' in wp.child_contract('produce', lang)
    assert wg.parse_knowledge_requests('## Knowledge requests\n- research: Which API contract is used?')
    assert 'VERDICT: ok' in wp.review_tail(lang)
    assert 'REVISE <nodeId>:' in wp.whole_review_goal('x', 'y', lang)
    assert wp.child_contract('unknown', lang) is None


@pytest.mark.parametrize('text,empty', [
    ('## Vấn đề chặn\nnone\n## Ghi chú không chặn\nThêm ví dụ.', True),
    ('## Vấn đề chặn\nKhông có vấn đề chặn', True),
    ('## Vấn đề chặn\n1. Thiếu schema nên chưa triển khai được.', False),
    ('## Blocking findings\nnone\n## Non-blocking notes\nAdd an example.', True),
    ('No structured findings, cannot conclude.', False),
])
def test_localized_empty_findings_have_same_meaning_as_legacy(text, empty):
    assert wg.has_no_blocking_findings(text) is empty


def test_vietnamese_full_child_prompts_and_review_cycle_keep_existing_graph(tmp_path):
    def script(kind, text):
        if text.startswith(('Phản biện độc lập', 'Phản biện toàn kế hoạch')):
            return '## Vấn đề chặn\nnone\nVERDICT: ok'
        return '## Phát hiện\nfixture đã cung cấp\n## Knowledge requests\n- none'

    store, rt, model, executor, sid = build(tmp_path, script)

    async def run():
        await tool(rt, sid, 'work_graph', {'action': 'create', 'goal': 'Giúp tôi sửa chức năng export', 'flow': 'plan'})
        await tool(rt, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        discovered = await tool(rt, sid, 'work_run', {'phase': 'discover'})
        verified = await tool(rt, sid, 'work_graph', {'action': 'verify'})
        return discovered, verified

    discovered, verified = asyncio.run(run())
    assert all(n['status'] == 'accepted' for n in discovered['outputs'])
    assert verified['status'] == 'verified'
    assert [c for c in executor.calls if c[0] == 'write_plan']
    prompts = [text for _, text in model.prompts]
    assert len(prompts) == 4  # simple Explore consumes an opened source; Plan check and whole check remain independent
    for text in prompts:
        for old_label in ('Overall owner goal:', 'Your assignment:', 'Parent-supplied context',
                          'Parent-required deliverable', 'Deliverable (Markdown', 'Every claim needs evidence'):
            assert old_label not in text
        assert 'Mục tiêu của người dùng:' in text
    assert any('Milestone M1' in p and 'Dữ liệu và hợp đồng' in p for p in prompts)
    assert any('Phản biện toàn kế hoạch' in p and 'REVISE <nodeId>:' in p for p in prompts)
    master = [args['markdown'] for name, args in executor.calls if name == 'write_plan'][-1]
    assert '.plans/work/' in master and '/p1-export-plan.md`' in master  # confirmed legacy fixture path
    assert '## Mục tiêu' in master and '## Mục tiêu / Goal' not in master


def test_existing_subplan_link_uses_fresh_writer_version_not_old_run_documents(tmp_path):
    _, rt, _, _, _ = build(tmp_path)
    run = {'title': 'Export', 'goal': 'Add export', 'runId': 'r', 'slug': 'export', 'flow': 'plan',
           'nodes': [wg.normalize_node(PLAN)], 'documents': [{'identity': 'work/export/p1-export-plan',
              'path': '.plans/work/export/v1-p1-export-plan.md', 'version': 1}]}
    draft = wg.service(rt).master_document(run)
    assert 'not saved yet' in draft and 'v1-p1-export-plan.md' not in draft
    saved = [{'identity': 'work/export/p1-export-plan', 'path': '.plans/work/export/v3-p1-export-plan.md', 'version': 3}]
    master = wg.service(rt).master_document(run, saved)
    assert 'v3 · `.plans/work/export/v3-p1-export-plan.md`' in master
    assert 'v1-p1-export-plan.md' not in master


@pytest.mark.parametrize('response', [None, [], ['bad gateway'], 'bad gateway', {}, {'is_error': True, 'error': 'disk full'}])
def test_existing_writer_reports_bad_responses_without_attribute_error(tmp_path, response):
    store, rt, _, executor, sid = build(tmp_path)

    async def fake_execute(*args, **kwargs):
        return response

    executor.execute = fake_execute
    with pytest.raises(ValueError, match='^WORK_DOCUMENT_FAILED:'):
        asyncio.run(wg.service(rt).write_document(sid, {'slug': 'x', 'runId': 'r'}, 'plan', '# Plan\n', 'Plan'))
    assert not [e for e in store.events(sid) if e['type'] == 'plan_written']


def test_existing_document_keeps_utf8_content_hash_and_nested_path(tmp_path):
    store, rt, _, executor, sid = build(tmp_path)
    markdown = '# Kế hoạch\n\nĐường dẫn, dữ liệu, kiểm thử.\n'

    async def fake_execute(name, args, *unused):
        path = '.plans/' + args['directory'] + '/v7-' + args['slug'] + '.md'
        (tmp_path / PurePosixPath(path)).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / PurePosixPath(path)).write_bytes(args['markdown'].encode('utf-8'))
        return {'relativePath': path, 'version': 7}

    executor.execute = fake_execute
    result = asyncio.run(wg.service(rt).write_document(sid, {'slug': 'x', 'runId': 'r'}, 'plan', markdown, 'Kế hoạch'))
    raw = (tmp_path / PurePosixPath(result['path'])).read_bytes()
    emitted = [e['data'] for e in store.events(sid) if e['type'] == 'plan_written'][-1]
    assert raw.decode('utf-8') == markdown
    assert emitted['bytes'] == len(raw)
    assert emitted['contentHash'] == hashlib.sha256(raw).hexdigest()
    assert json.loads(json.dumps(emitted, ensure_ascii=False))['title'] == 'Kế hoạch'


def test_agent_identity_text_matches_the_current_policy():
    """W11 P0c: `AGENT.md` đi NGUYÊN VĂN vào system prompt của mọi phiên (kể cả con).

    Câu cũ ở đây từng mô tả một thiết kế khác (mọi con đều có reviewer; con không bao giờ hỏi
    chủ) và đảo ngược quyết định §27–29 — plan đã yêu cầu không dùng doc cũ để đảo kiến trúc.
    """
    text = (Path(__file__).resolve().parents[3] / 'AGENT.md').read_text(encoding='utf-8')
    assert 'never asks the owner' not in text
    assert 'work_report' in text and 'needs_user' in text
    assert 'Every child output in a Work Graph goes to an independent reviewer' not in text
    assert 'work_policy.derive' in text and 'converged tree' in text


def test_simplify_skill_keeps_dropped_findings_visible():
    """W11 P0c: skill vendor không được dặn bỏ gợi ý "âm thầm" — mọi kết luận cần bằng chứng."""
    path = (Path(__file__).resolve().parents[2] / 'src' / 'agentbox' / 'vendor' / 'hermes' / 'skills'
            / 'software-development' / 'simplify-code' / 'SKILL.md')
    text = path.read_text(encoding='utf-8')
    assert 'drop weak or wrong suggestions silently' not in text
    assert 'never drop a suggestion silently' in text


# ------------------------- W11.PROMPT P3 — prompt ĐÃ LẮP theo từng vai (P0b §5.4, §5.6, §5.7)

# Chín vai còn lại của W11.PROMPT; nhánh Simplify có tệp ghim riêng (`test_work_simplify_prompt.py`).
W11_ROLES = ('explore', 'plan', 'plan-review', 'design', 'build', 'debug', 'review', 'testing', 'research')
HEADINGS_YIELD = 'Unless the assignment supplies its own deliverable, return a structured Markdown report with:'
HEADINGS_YIELD_PLAN_REVIEW = ('unless the assignment supplies its own deliverable or rubric, '
                              'return a Markdown report.')
HEADINGS_ABSOLUTE = ('Output Requirement: Return a structured Markdown report with:',
                     'Output Requirement: return a Markdown report.')
# Ba note Work Graph (producer, reviewer, execution reviewer) — mỗi vai nhận đúng bộ của nó.
WORK_GRAPH_NOTES = ('Work Graph node: when the prompt starts with',
                    'Work Graph review: when the prompt starts with',
                    'Work Graph execution review: for "Independent review')


def assembled_prompts(tmp_path, roles):
    """System prompt THẬT của từng vai con: `AGENT.md` + `ROLES[vai].instructions` đã ghép note."""
    store = SessionStore(tmp_path / 'w11-assembled.db')
    runtime = HarnessRuntime(store, Executor(), Model([]))
    main = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm'})
    prompts = {role: system_prompt(runtime, runtime.create(
        {'skills': [], 'connectionId': 'c1', 'modelId': 'm'}, parent_id=main['id'], role=role))
        for role in roles}
    store.close()
    return prompts


def test_w11_generic_headings_yield_to_the_assignment_in_the_assembled_prompt(tmp_path):
    """P0b §5.4 — hai bộ heading không được cùng là "mặc định" trong một prompt.

    `WORK_PRODUCER_NOTE` nói deliverable của nhiệm vụ đè heading chung, nhưng bộ heading cũ vẫn nằm
    nguyên văn trong instruction của vai, nên model nhận cả hai chuẩn (và không cổng runtime nào kiểm
    hình dạng output). Bản vá biến bộ heading chung thành MẶC ĐỊNH CÓ ĐIỀU KIỆN — bộ heading vẫn còn
    nguyên, nên không mất năng lực nào.
    """
    prompts = assembled_prompts(tmp_path, W11_ROLES)
    for role, prompt in prompts.items():
        expected = HEADINGS_YIELD_PLAN_REVIEW if role == 'plan-review' else HEADINGS_YIELD
        assert expected in prompt, f'vai {role}: thiếu câu điều kiện cho heading chung'
        for absolute in HEADINGS_ABSOLUTE:
            assert absolute not in prompt, f'vai {role}: heading chung vẫn được rao như mặc định duy nhất'
    # Bộ heading cũ không bị xóa: khi assignment không cấp deliverable, model vẫn có khuôn để theo.
    assert '### Architecture & Key Files' in prompts['explore']
    assert '### Failure Reproduction' in prompts['debug']
    assert '### Findings by Severity' in prompts['plan-review']
    assert '### Verified Facts & Technical Specifications' in prompts['research']


def test_w11_plan_forbids_write_plan_inside_a_work_graph_node_only(tmp_path):
    """P0b §5.6 — `plan` giữ `write_plan` cho đường cũ, nhưng trong Work Graph harness tự ghi tài liệu.

    Lỗi cũ: bước 5 ra lệnh "call it again" mà không nêu ngoại lệ, còn `WORK_PLAN_NOTE` cấm gọi
    `write_plan` cho node — hai câu mâu thuẫn trong cùng một prompt, và không có cổng dispatch nào
    chặn `write_plan` ở node produce (chỉ node check bị `WORK_CHECK_READ_ONLY`). Ràng buộc này phải
    nhất quán ở tầng prompt; quyền của vai không đổi.
    """
    prompt = assembled_prompts(tmp_path, ('plan',))['plan']
    assert 'In a Work Graph node you must NOT call `write_plan` at all' in prompt
    assert 'Do NOT call `write_plan` for a Work Graph node' in prompt       # WORK_PLAN_NOTE vẫn còn
    assert '`write_plan` refuses a plan without those sections' in prompt   # đường ghi plan cũ không mất
    assert ROLES['plan'].tools == READ | {'write_plan'}, 'W11 chỉ sửa prompt — quyền của vai không đổi'


def test_w11_testing_review_names_the_source_it_must_not_edit(tmp_path):
    """P0b §5.7 — vai Testing phải VIẾT test (mission + `WRITE`) mà note lại phán "Do NOT edit source files".

    Hai câu có thể cùng đúng, nhưng prompt không định nghĩa "source file": lượt kiểm có thể tưởng mình
    bị cấm viết file test, còn lượt sản xuất có thể tưởng được sửa mã nguồn. Bản vá chỉ định đúng đối
    tượng — mã nguồn SẢN XUẤT đang được kiểm — và không đổi bộ công cụ của vai.
    """
    prompt = assembled_prompts(tmp_path, ('testing',))['testing']
    assert 'write and execute rigorous automated tests' in prompt
    assert 'Do NOT edit the production source under test' in prompt
    assert 'Do NOT edit source files' not in prompt
    assert {'file_write', 'file_edit_block'} <= ROLES['testing'].tools


def test_w11_work_graph_note_never_lands_after_the_roles_closing_prohibition():
    """Bất biến P2: `with_work_graph` chèn note TRƯỚC câu `STRICT PROHIBITION` cuối của vai.

    Vai nào không có câu chốt (`debug`) thì hàm nối khối note vào cuối — nhánh dự phòng đã có trong
    mã; bài kiểm chỉ đòi note nằm SAU phần protocol của vai, không chen vào giữa các bước.
    """
    for role in W11_ROLES:
        text = ROLES[role].instructions
        notes = [note for note in WORK_GRAPH_NOTES if note in text]
        assert notes, f'vai {role}: không thấy note Work Graph nào'
        if 'STRICT PROHIBITION' in text:
            closing = text.rindex('STRICT PROHIBITION')
            for note in notes:
                assert text.index(note) < closing, f'vai {role}: note Work Graph nằm sau câu chốt của vai'
        else:
            assert text.index(notes[0]) > text.index('5. Output Requirement:'), \
                f'vai {role}: note Work Graph phải nằm sau phần protocol của vai'
