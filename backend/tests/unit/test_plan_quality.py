"""The write_plan gate: a plan without verification, limits or sources is refused before any write.

Contract: backend/src/agentbox/agent_core/plan_quality.py (pure) + failures.PLAN_QUALITY_REJECTED.
"""
import asyncio
import copy
import hashlib
import json

import pytest

from agentbox.agent_core.failures import KNOWN_PREFIXES, classify_failure, describe_failure
from agentbox.agent_core.plan_quality import (PLAN_QUALITY_PREFIX, REQUIRED_SECTIONS, check_plan_quality,
                                              normalize_path, plan_quality_issues, plan_quality_message,
                                              strip_www)
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

GOOD_PLAN = """# Workspace plan

## Milestones
1. Build the workspace panel.

## Verification / Acceptance criteria
Run `.venv/bin/python -m pytest backend/tests -q`; expect only the 3 known environment failures.

## Risks / Limitations
- none known: the change is additive.
"""

# The document shape the owner actually got: milestones and prose, no verification mechanism, no limits.
EMPTY_PLAN = """# Patient record lookup agent

## Steps
1. The agent queries the records service.
2. It formats the answer.
"""


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append(copy.deepcopy((messages, tools, route)))
        return next(self.responses)


class PlanFixtureExecutor:
    """Stands in for the sandbox worker: confirms the same metadata the real container returns."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name in {'journal_append', 'session_ensure', 'checkpoint_write'}:
            # A7 (đợt 20): một lần ghi plan còn ghim bản ghi `P:` — op nhật ký đi qua cùng executor,
            # nên cổng chất lượng vẫn phải nói "chỉ có một lần ghi plan", không phải "một lời gọi".
            return {'ok': True, 'id': (args.get('record') or {}).get('id'), 'seq': 1}
        return {'content': 'Written .plans/v1-x.md', 'version': 1, 'slug': args['slug'],
                'relativePath': f".plans/v1-{args['slug']}.md",
                'bytes': len(args['markdown'].encode('utf-8'))}

    async def cleanup(self, sid):
        return None


class SilentExecutor(PlanFixtureExecutor):
    async def execute(self, name, args, sid):
        raise AssertionError('the sandbox must not be called: ' + name)


def events_of(store, sid, kind):
    return [event for event in store.events(sid) if event['type'] == kind]


def tool_results(store, sid):
    return [json.loads(message['content']) for message in store.get(sid)['messages'] if message['role'] == 'tool']


# --- the pure rules -----------------------------------------------------------------------------------

def test_required_sections_constant_names_the_three_sections():
    assert [(section['id'], section['trigger']) for section in REQUIRED_SECTIONS] == \
        [('verification', None), ('risks', None), ('sources', 'external_facts')]
    assert all(section['heading_keys'] and section['requirement'] for section in REQUIRED_SECTIONS)


@pytest.mark.parametrize('markdown', [
    GOOD_PLAN,
    # heading style does not matter: ATX, bold label, or a plain `Verification:` label
    '# P\n\n**Verification**\n- `ls .plans` -> expect at least one vN-*.md file.\n\n**Risks**\n- none known.\n',
    '# P\n\nVerification:\nPOST /api/agent/sessions returns 201.\n\nRisks:\n- none known, the route is new.\n',
    # a check that is written as prose is still a check, as long as it names something concrete
    '# P\n\n## Acceptance criteria\n- The endpoint returns 201 for a valid payload.\n- Invalid payloads return 400.\n\n'
    '## Limitations\n- jsdom cannot measure layout.\n',
    # Vietnamese headings: this product's users and the repository plans write Vietnamese
    '# Kế hoạch\n\n## Nghiệm thu\nChạy `npm test` và mong đợi 0 lỗi.\n\n## Giới hạn\n- chưa kiểm thử trên Safari.\n',
    # a fenced command block counts
    '# P\n\n## How to verify\n```\nnpm test\n```\nExpect 0 failures.\n\n## Risks\n- none known\n',
])
def test_a_plan_with_evidence_and_limits_is_accepted(markdown):
    assert plan_quality_issues(markdown) == []
    assert check_plan_quality(markdown) is None


def test_a_plan_without_verification_or_limits_is_rejected():
    assert plan_quality_issues(EMPTY_PLAN) == ['verification-section', 'risks-section']


def test_a_verification_section_must_name_a_command_and_an_expected_result():
    no_check = '# P\n\n## Verification\nEverything the user cares about works.\n\n## Risks\n- none known\n'
    assert plan_quality_issues(no_check) == ['verification-command', 'verification-expected']
    no_expectation = '# P\n\n## Verification\nRun `pytest backend/tests -q`.\n\n## Risks\n- none known\n'
    assert plan_quality_issues(no_expectation) == ['verification-expected']
    # an empty section is not a section
    assert plan_quality_issues('# P\n\n## Verification\n## Risks\n- none known\n') == ['verification-section']


def test_later_verification_procedure_counts_after_early_acceptance_criteria():
    markdown = '''# Referral agent plan

## Tiêu chí nghiệm thu MVP
- Document classification accuracy exceeds 90% on the held-out set.

## Verification / Acceptance criteria
- Run `python -m pytest backend/tests/test_referral_validity.py -q`.
- Expected result: the suite passes and reports the held-out accuracy.

## Risks / Limitations
- Current legal rules require expert review before deployment.
'''
    assert plan_quality_issues(markdown) == []


def test_host_and_path_normalisation_is_prefix_based_not_character_set_based():
    """H2 (hậu kiểm vòng 25): `lstrip('www.')` / `lstrip('./')` cắt theo TẬP ký tự.

    Hệ quả đo được ở cổng nguồn: `web.dev` → `eb.dev`, `w3.org` → `3.org`, và
    `.github/workflows/ci.yml` mất dấu chấm đầu. Một kế hoạch viện dẫn đúng host mà bằng chứng công cụ
    trả về bị `sources-unbacked` chặn — cổng từ chối một kế hoạch có bằng chứng thật.
    """
    assert strip_www('www.docs.example.com') == 'docs.example.com'
    assert strip_www('Docs.Example.com') == 'docs.example.com'
    assert strip_www('docs.example.com.') == 'docs.example.com'
    assert strip_www('web.dev') == 'web.dev', 'chữ `w` đầu KHÔNG phải tiền tố `www.`'
    assert strip_www('w3.org') == 'w3.org'
    assert strip_www('wikipedia.org') == 'wikipedia.org'
    assert strip_www(None) == '' and strip_www('') == ''

    assert normalize_path('./docs/v1-plan.md') == 'docs/v1-plan.md'
    assert normalize_path('.//docs/v1-plan.md') == 'docs/v1-plan.md'
    assert normalize_path('/docs/v1-plan.md') == 'docs/v1-plan.md'
    assert normalize_path('.github/workflows/ci.yml') == '.github/workflows/ci.yml', \
        'tệp ẩn trong repo vẫn là tệp ẩn'
    assert normalize_path('docs/v1-plan.md') == 'docs/v1-plan.md'


def test_external_facts_require_a_sources_section_but_repo_links_do_not():
    external = '# P\n\n## Verification\n`curl -s https://example.com/health` expect {"ok":true}\n\n## Risks\n- none\n'
    assert plan_quality_issues(external) == ['sources-section']
    with_sources = external + '\n## Sources\n- https://example.com/health (checked 2026-09-20)\n'
    assert plan_quality_issues(with_sources) == []
    in_repo = '# P\n\n## Verification\nRun `.venv/bin/python -m pytest backend/tests -q`, expect 0 failures.\n\n' \
              '## Risks\n- none\n\nSee docs/plan/next-batch-contract.md for the event shapes.\n'
    assert plan_quality_issues(in_repo) == []


def test_the_rejection_message_is_one_line_and_names_every_missing_part():
    issues = plan_quality_issues(EMPTY_PLAN)
    message = plan_quality_message(issues)
    assert message.startswith(PLAN_QUALITY_PREFIX + ': ')
    assert '\n' not in message
    for issue in issues:
        assert f'({issue})' in message
    assert 'call write_plan again' in message and 'nothing was written' in message
    with pytest.raises(ValueError) as raised:
        check_plan_quality(EMPTY_PLAN)
    assert str(raised.value) == message

    # the sources remedy only appears when the plan really claims external facts
    external = '# P\n\n## Verification\n`curl -s https://example.com` expect 200\n\n## Risks\n- none\n'
    sources_only = plan_quality_message(plan_quality_issues(external))
    assert '(sources-section)' in sources_only and '(risks-section)' not in sources_only


# --- the gate in the live write path ------------------------------------------------------------------

def test_write_plan_rejects_before_the_sandbox_writer_runs(tmp_path):
    """A rejected plan must leave no file behind, and the model must get one actionable line."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = SilentExecutor()
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'patient-records', 'markdown': EMPTY_PLAN})]),
            answer('Plan bị từ chối, tôi viết lại')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Lên plan tra cứu hồ sơ bệnh nhân')
        assert executor.calls == [], 'the sandbox writer must never run for a rejected plan'
        assert events_of(store, sid, 'plan_written') == []
        assert events_of(store, sid, 'ui_intent') == []
        failure = [result for result in tool_results(store, sid) if result.get('is_error')][0]
        assert failure['errorCode'] == PLAN_QUALITY_PREFIX
        assert failure['error'] == plan_quality_message(plan_quality_issues(EMPTY_PLAN))
        assert store.get(sid)['status'] == 'completed', 'the agent keeps going after a refused plan'
        store.close()

    asyncio.run(run())


def test_a_compliant_plan_is_written_exactly_as_before_the_gate(tmp_path):
    """The gate must not change what a good plan writes: same events, same payload, same file body.

    The turn itself is ONE step longer than before the gate: F3 injects a nudge step unless the plan
    already carries a critique verdict, so this good turn needs a third reply. Without it the fixture
    iterator runs dry and the turn dies (2026-09-27 review) while the write-side asserts below stay
    green — hence the explicit `completed` check.
    """

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        executor = PlanFixtureExecutor()
        runtime = HarnessRuntime(store, executor, FixtureModel([
            answer(calls=[call('write_plan', {'slug': 'workspace-plan', 'markdown': GOOD_PLAN, 'title': ''})]),
            answer('Đã ghi plan'),
            answer('Chưa chạy phản biện, dừng ở đây.')]))
        sid = runtime.create({'skills': []})['id']

        await runtime.start(sid, 'Ghi plan')
        assert [name for name, _, _ in executor.calls].count('write_plan') == 1, \
            'cổng chất lượng không được gọi sandbox ghi plan hai lần'
        # Bỏ op hạ tầng `session_ensure` (A1, dọn thư mục phiên ở đầu lượt) để phép kiểm dưới đây
        # vẫn nói về ĐÚNG lời gọi công cụ `write_plan`.
        tool_calls = [row for row in executor.calls if row[0] != 'session_ensure']
        name, args, _ = tool_calls[0]
        assert (name, args['slug'], args['markdown']) == ('write_plan', 'workspace-plan', GOOD_PLAN)
        written = events_of(store, sid, 'plan_written')[0]['data']
        assert written == {'identity': 'workspace-plan', 'version': 1, 'slug': 'workspace-plan',
                               'relativePath': '.plans/v1-workspace-plan.md', 'title': 'Workspace plan',
                               'bytes': len(GOOD_PLAN.encode('utf-8')),
                               'contentHash': hashlib.sha256(GOOD_PLAN.encode('utf-8')).hexdigest()}
        assert events_of(store, sid, 'ui_intent')[0]['data'] == \
            {'tab': 'plan', 'target': {'identity': 'workspace-plan', 'version': 1}, 'reason': 'plan_written'}
        assert tool_results(store, sid)[-1]['relativePath'] == '.plans/v1-workspace-plan.md'
        assert store.get(sid)['status'] == 'completed', \
            'lượt tốt lành phải ĐÓNG TRỌN VẸN, không phải chết vì fixture cạn câu trả lời'
        store.close()

    asyncio.run(run())


# --- failure classification ---------------------------------------------------------------------------

def test_the_new_code_keeps_its_own_message():
    assert PLAN_QUALITY_PREFIX in KNOWN_PREFIXES
    message = plan_quality_message(['verification-section'])
    code, classified = classify_failure(ValueError(message))
    assert code == PLAN_QUALITY_PREFIX
    assert classified == message, 'the actionable text must survive classification untouched'
    assert describe_failure(ValueError(message)) == message
