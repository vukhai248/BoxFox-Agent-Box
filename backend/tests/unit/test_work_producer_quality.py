"""W6.2 producer/main quality: taskKind/depth deliverables, claim sourcing and W6.2.BIND."""
import asyncio
import json

import pytest

from agentbox.agent_core import work_graph as wg, work_prompts
from test_work_graph import build, ok_script, tool, EXPLORE, PLAN


def test_lookup_deliverable_is_short_contract_vi_en():
    for lang, headings, forbidden in (
            ('vi', ('## Trả lời', '## Nguồn đã mở', '## Chưa kiểm'), ('Khuyến nghị', 'So sánh phương án')),
            ('en', ('## Answer', '## Sources opened', '## Unverified'), ('Recommendation', 'Options compared'))):
        text = work_prompts.deliverable('research', lang, task_kind='lookup')
        assert all(head in text for head in headings), (lang, text)
        assert not any(word in text for word in forbidden), (lang, text)
        assert '120' in text
    knowledge = work_prompts.child_contract('knowledge', 'vi')
    assert '## Trả lời' in knowledge and '## Nguồn đã mở' in knowledge


def test_lookup_answer_cap_names_the_one_counting_rule():
    """FU5 (W6.Q): trần 120 từ phải nói rõ cách đếm — thân mục, không tính dòng tiêu đề.

    Đếm thô (kể cả `## Trả lời`) từng cho 122 và bị đọc là vượt trần, trong khi đúng luật là 119.
    """
    vi = work_prompts.deliverable('research', 'vi', task_kind='lookup')
    en = work_prompts.deliverable('research', 'en', task_kind='lookup')
    assert 'không tính dòng tiêu đề' in vi
    assert 'heading lines do not count' in en
    assert work_prompts.LOOKUP_ANSWER_COUNT_RULE in ('body of the Answer section, Markdown heading lines excluded',)


def test_research_brief_depth_omits_options_section():
    brief = work_prompts.deliverable('research', 'vi', depth='brief')
    assert all(head in brief for head in ('## Trả lời', '## Dữ kiện đã xác minh', '## Khoảng trống'))
    assert 'So sánh phương án' not in brief and 'Khuyến nghị' not in brief
    assert '400' in brief
    full = work_prompts.deliverable('research', 'vi')
    assert '## So sánh phương án' in full and '## Khuyến nghị' in full
    assert work_prompts.deliverable('research', 'en', depth='brief').startswith('Deliverable')
    plan = work_prompts.deliverable('plan', 'vi')
    assert 'không thêm mục rỗng' in plan


def test_depth_change_invalidates_definition():
    node = {'id': 'R1', 'kind': 'research', 'title': 'Lookup', 'goal': 'Find the exact Vite version',
            'acceptance': ['Name the version']}
    plain = wg.normalize_node(dict(node), {})
    brief = wg.normalize_node(dict(node, depth='brief'), plain)
    assert plain.get('depth') is None and brief['depth'] == 'brief'
    assert wg.work_policy.definition(plain) != wg.work_policy.definition(brief)
    assert wg.work_policy.definition(plain) == wg.work_policy.definition(wg.normalize_node(dict(node), {}))
    with pytest.raises(ValueError, match='depth must be one of'):
        wg.normalize_node(dict(node, depth='deep'), {})


def test_helper_claim_on_unopened_path_is_unverified(tmp_path):
    produced = {'n': 0}

    def script(kind, text):
        if kind == 'produce':
            produced['n'] += 1
            if produced['n'] == 1:
                return '## Draft\n## Knowledge requests\n- research: what does docs/source.md say?'
            return '## Findings\nfinal\n## Knowledge requests\n- none'
        if kind == 'knowledge':
            return 'The file docs/source.md defines the contract.'
        return ok_script(kind, text)

    _, runtime, model, _, sid = build(tmp_path, script)
    model.latest_assignment = True

    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Upgrade the build tool'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE]})
        return await tool(runtime, sid, 'work_run', {'phase': 'discover'})

    out = asyncio.run(run())
    run_doc = runtime.work_graph.get(out['runId'])
    knowledge = run_doc['nodes'][0]['stages']['produce']['rounds'][0]['knowledge'][0]
    assert knowledge['artifact']['binding']['verification'] == 'unverified'
    assert knowledge['error'].startswith('WORK_CLAIM_UNSOURCED: docs/source.md')


def verified_run(runtime, sid):
    async def run():
        await tool(runtime, sid, 'work_graph', {'action': 'create', 'goal': 'Add an export button', 'flow': 'plan'})
        await tool(runtime, sid, 'work_graph', {'action': 'add', 'nodes': [EXPLORE, PLAN]})
        await tool(runtime, sid, 'work_run', {'phase': 'discover'})
        return await tool(runtime, sid, 'work_graph', {'action': 'verify'})

    return asyncio.run(run())


def test_reviewed_set_written_on_ok_and_stale_after_artifact_change(tmp_path):
    _, runtime, _, _, sid = build(tmp_path)
    out = verified_run(runtime, sid)
    assert out['verdict'] == 'ok' and out['stale'] is False
    reviewed = out['reviewedSet']
    assert reviewed['verdict'] == 'ok' and reviewed['reviewedAt']
    assert reviewed['artifacts'] and reviewed['claims']
    graph = runtime.work_graph
    run = graph.get(out['runId'])
    assert graph.stale_review(run) is False
    # A changed reviewed artifact makes the old whole-pass unusable for a new summary.
    aid = reviewed['artifacts'][0]['artifactId']
    with graph.db:
        graph.db.execute("UPDATE work_artifacts SET metadata=json_set(metadata,'$.contentHash','deadbeef') WHERE id=?",
                         (aid,))
    assert graph.stale_review(graph.get(out['runId'])) is True
    assert graph.result(graph.get(out['runId']))['stale'] is True


def test_final_claims_check_flags_new_error_code_not_in_reviewed_artifacts(tmp_path):
    _, runtime, _, _, sid = build(tmp_path)
    out = verified_run(runtime, sid)
    run = runtime.work_graph.get(out['runId'])
    tokens = wg.final_claims_check(run, 'The run is verified; docs/source.md:12 and WORK_NEW_CODE_123 are new.')
    assert 'WORK_NEW_CODE_123' in tokens and 'docs/source.md' in tokens
    reviewed = wg.final_claims_check(run, 'Reviewed artifacts and the plan document are listed above.')
    assert reviewed == []


def test_final_claims_check_accepts_labeled_unverified_claim(tmp_path):
    _, runtime, _, _, sid = build(tmp_path)
    out = verified_run(runtime, sid)
    run = runtime.work_graph.get(out["runId"])
    text = ('New numbers were not part of the review.\n\n'
            'chưa kiểm: WORK_NEW_CODE_123 and docs/other.md:3 appear in a new proposal.\n')
    assert wg.final_claims_check(run, text) == []


def test_reviewed_set_reports_a_truncated_claim_set_instead_of_cutting_silently(tmp_path, monkeypatch):
    """#6474: chạm trần token claim thì phải nói ra, không cắt im lặng.

    Badge W6.2.BIND chỉ là tập token; nếu tập bị cắt ở 600 mà không ghi gì thì lượt đọc sau tưởng
    "mọi token đều đã kiểm" trong khi một phần chưa từng vào bộ đã phản biện.
    """
    _, runtime, _, _, sid = build(tmp_path)
    out = verified_run(runtime, sid)
    graph = runtime.work_graph
    run = graph.get(out['runId'])
    full = graph.reviewed_set(run)
    assert full['claimsTruncated'] is False and full['claimsTotal'] == len(full['claims'])
    real = wg.claim_tokens
    monkeypatch.setattr(wg, 'claim_tokens', lambda text: set(real(text)) | {'WORK_A_1', 'WORK_B_2'})
    monkeypatch.setattr(wg, 'CLAIM_TOKENS_MAX', 2)
    cut = graph.reviewed_set(run)
    assert cut['claimsTruncated'] is True
    assert cut['claimsTotal'] > 2 and len(cut['claims']) == 2, 'vẫn cắt để giữ trần, nhưng phải khai'


def test_final_claim_notices_fire_before_the_run_is_verified(tmp_path):
    """#6474: notice claim chưa kiểm không chỉ nổ khi graph đã `verified`.

    Main trả lời giữa lượt hoặc sau `needs_revision` cũng phải thấy tín hiệu; notice KHÔNG chặn
    câu trả lời, nên phát sớm không khoá chat.
    """
    _, runtime, _, _, sid = build(tmp_path)
    out = verified_run(runtime, sid)
    graph = runtime.work_graph
    assert runtime.final_claim_notices(sid, 'WORK_NEW_CODE_123 xuất hiện ở đây.')
    run = graph.get(out['runId'])
    run['status'] = 'needs_revision'
    graph.save(run, 'test_status_move')
    notices = runtime.final_claim_notices(sid, 'WORK_NEW_CODE_123 xuất hiện ở đây.')
    assert notices and notices[0]['type'] == 'unreviewed_claims'
    assert 'WORK_NEW_CODE_123' in notices[0]['tokens']
    assert notices[0]['truncated'] is False
    # Không có reviewedSet (chưa từng whole-pass) thì im lặng — không có gì để so.
    empty = graph.get(out['runId'])
    empty.pop('reviewedSet')
    graph.save(empty, 'test_no_review')
    assert runtime.final_claim_notices(sid, 'WORK_NEW_CODE_123 xuất hiện ở đây.') == []
