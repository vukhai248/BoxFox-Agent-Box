"""`plan_verify` — phán quyết phản biện độc lập vào sổ (vòng 25, D-33/D-34).

Vì sao có tệp này: cổng duyệt (`PLAN_APPROVAL_UNVERIFIED`) đọc một hàng của `plan_verifications`,
nên hàng đó là thứ DUY NHẤT mở được đường duyệt. Nếu `plan_verify` nhận lời khai của model thay vì
đọc bằng chứng thật, cả vòng lặp trở thành thủ tục: model viết plan, tự nói "đã phản biện", rồi xin
duyệt. Bốn điều kiện của cổng provenance (có bản ghi thật; con mang vai `plan-review`; con chạy SAU
bản ghi; câu trả lời đủ dài) và dòng `VERDICT:` đọc từ văn bản của chính người phản biện là những
gì tệp này ghim.
"""
from __future__ import annotations

import asyncio
import copy
import json
import time

import pytest

from agentbox.agent_core import limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

IDENTITY = 'clinical-patient-record-lookup-research'
JOURNAL_OPS = {'journal_append', 'session_ensure', 'checkpoint_write'}
# Câu trả lời của người phản biện, dài hơn trần `PLAN_REVIEW_MIN_ANSWER_CHARS` (400) — cổng
# provenance từ chối một "phê bình" ngắn hơn thế vì nó không thể chứa đủ nội dung để đọc.
CRITIQUE = ('## Findings by Severity\n'
            '- high: `.plans/v1-x.md:31` runs a command that does not exist in this repository; '
            'replace it with one that does and say what output proves it.\n'
            '- medium: milestone 3 has no acceptance check at all, so a failure there would pass '
            'silently.\n'
            '- low: the risk list does not mention that the sandbox has no network access.\n\n'
            '### Milestones That Cannot Be Executed As Written\n- none.\n\n'
            '### Acceptance Checks That Would Not Prove Anything\n- the file-existence check.\n\n'
            '### Missing Risks, Unknowns And Unverified Claims\n'
            '- the plan claims a library version that no source backs.\n\nVERDICT: ok')


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


class FixtureExecutor:
    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name in JOURNAL_OPS:
            return {'ok': True, 'id': (args.get('record') or {}).get('id'), 'seq': 1,
                    'relPath': '.session-history/journal.jsonl'}
        if name == 'write_plan':
            # Cùng khuôn mà sandbox thật trả về: harness đọc `version`/`relativePath`/`bytes` từ đây.
            version = args.get('version') or 1
            return {'content': 'Written ' + args['slug'], 'version': version, 'slug': args['slug'],
                    'relativePath': f".plans/v{version}-{args['slug']}.md",
                    'bytes': len(args['markdown'].encode('utf-8'))}
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def verify_args(**extra):
    args = {'identity': IDENTITY, 'version': 1, 'verdict': 'ok', 'issues': [], 'summary': 'ổn'}
    args.update(extra)
    return args


def tool_results(store, sid):
    rows = []
    for message in store.get(sid)['messages']:
        if message['role'] != 'tool':
            continue
        try:
            rows.append(json.loads(message['content']))
        except (TypeError, ValueError):
            continue
    return rows


def seed_write(store, sid, version=1):
    """Bản ghi `plan_written` của đúng `(identity, version)` — mốc thời gian của cổng provenance."""
    store.emit(sid, 'plan_written', {'identity': IDENTITY, 'version': version, 'slug': 'clinical',
                                     'relativePath': f'.plans/v{version}-clinical.md',
                                     'title': 'Clinical', 'bytes': 1200})


def seed_critic(store, parent, *, role='plan-review', status='completed', answer_chars=None, text=None,
                wait=0.0):
    """Một phiên con phản biện ĐÃ XONG: hàng sổ con + event `assistant` mang câu trả lời của nó."""
    if wait:
        time.sleep(wait)
    child = store.create({'skills': []}, role=role, parent_id=parent)['id']
    store.child_start(child, parent, 1, 2, role, 'critique the plan')
    body = CRITIQUE if text is None else text
    store.emit(child, 'assistant', {'text': body, 'final': True})
    store.child_finish(child, status, reason=None, steps_used=4,
                       answer_chars=len(body) if answer_chars is None else answer_chars)
    return child


def run_verify(tmp_path, args, seed=None, responses=None, version=1):
    """Một lượt thật: (tuỳ chọn) gieo sổ, rồi model gọi `plan_verify`."""
    store = SessionStore(tmp_path / 'sessions.db')
    executor = FixtureExecutor()
    runtime = HarnessRuntime(store, executor, FixtureModel(
        responses or [answer('Đã ghi nhận', calls=[call('plan_verify', args)]), answer('Xong lượt.')]))
    sid = runtime.create({'skills': []})['id']
    if seed is not None:
        seed(store, sid)

    async def go():
        await runtime.start(sid, 'Xin duyệt kế hoạch')

    asyncio.run(asyncio.wait_for(go(), 10))
    return store, executor, sid, None


def only_result(store, sid):
    rows = tool_results(store, sid)
    assert len(rows) == 1, 'đúng một lời gọi công cụ trong lượt này'
    return rows[0]


def journal_writes(executor):
    """Op nhật ký THẬT của một hàng: `session_ensure` là hạ tầng chạy trước mọi lượt."""
    return [name for name, _args, _sid in executor.calls
            if name in JOURNAL_OPS and name != 'session_ensure']


# --- đường thành công ---------------------------------------------------------------------------

def test_an_ok_verdict_from_a_real_critique_is_recorded(tmp_path):
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, wait=0.02)

    store, executor, sid, _ = run_verify(tmp_path, verify_args(
        issues=[{'severity': 'low', 'text': 'thiếu mục Sources', 'fix': 'thêm URL'}]), seed=seed)
    result = only_result(store, sid)
    assert not result.get('is_error'), result
    assert result['verdict'] == 'ok' and result['issueCount'] == 1
    assert result['criticSessionId'] and result['criticAnswerChars'] >= limits.PLAN_REVIEW_MIN_ANSWER_CHARS

    row = store.plan_verification(IDENTITY, 1)
    assert row['verdict'] == 'ok' and row['critic_verdict'] == 'ok'
    assert row['critic_session_id'] == result['criticSessionId']
    assert row['issues'] == [{'severity': 'low', 'text': 'thiếu mục Sources', 'fix': 'thêm URL'}]
    assert row['summary'] == 'ổn'

    verified = [event['data'] for event in store.events(sid) if event['type'] == 'plan_verified']
    assert len(verified) == 1
    assert (verified[0]['identity'], verified[0]['version'], verified[0]['verdict']) == (IDENTITY, 1, 'ok')
    assert verified[0]['at'].endswith('Z')
    intent = [event['data'] for event in store.events(sid) if event['type'] == 'ui_intent']
    assert intent[-1] == {'tab': 'plan', 'target': {'identity': IDENTITY, 'version': 1},
                          'reason': 'plan_verified'}
    # Hàng nhật ký `fact` là thứ model đọc lại ở lượt sau — phải có, và mang dấu vết.
    assert journal_writes(executor), 'một phán quyết phải để lại hàng nhật ký'
    store.close()


def test_a_revise_verdict_carries_the_next_step_and_is_not_capped_at_once(tmp_path):
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, text=CRITIQUE.replace('VERDICT: ok', 'VERDICT: revise'), wait=0.02)

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(
        verdict='revise', issues=[{'severity': 'high', 'text': 'mốc 2 không kiểm được', 'fix': 'thay lệnh'}],
        summary='một lỗi nặng'), seed=seed)
    result = only_result(store, sid)
    assert not result.get('is_error'), result
    assert result['verdict'] == 'revise' and result['issueCount'] == 1
    assert 'capped' not in result, 'vòng sửa đầu tiên chưa chạm trần'
    assert result['next'].startswith('sửa các điểm đã nêu')
    assert store.plan_verification(IDENTITY, 1)['verdict'] == 'revise'
    store.close()


def test_the_third_revise_round_in_one_turn_is_reported_as_capped(tmp_path):
    """Trần 2 vòng: vòng thứ ba KHÔNG bị từ chối (sự thật vẫn vào sổ) nhưng phải nói ra `capped`."""
    store = SessionStore(tmp_path / 'sessions.db')
    executor = FixtureExecutor()
    runtime = HarnessRuntime(store, executor, FixtureModel([]))
    sid = runtime.create({'skills': []})['id']

    async def go():
        store.emit(sid, 'user', {'text': 'bắt đầu lượt', 'turn': 1})
        for version in (1, 2, 3):
            seed_write(store, sid, version)
            critic = seed_critic(store, sid, text=CRITIQUE.replace('VERDICT: ok', 'VERDICT: revise'),
                                 wait=0.02)
            assert critic
            answered = await runtime.plan_verify({'id': sid, 'parent_id': None},
                                                 verify_args(version=version, verdict='revise'))
            if version == 3:
                assert answered.get('capped') is True
                assert 'past the cap of 2 revise rounds' in answered['content']
                assert 'report the open findings to the owner honestly' in answered['content']
            else:
                assert 'capped' not in answered
        return None

    asyncio.run(go())
    assert {row['version'] for row in store.db.execute(
        "SELECT version FROM plan_verifications WHERE verdict='revise'")} == {1, 2, 3}
    store.close()


# --- bốn điều kiện của cổng provenance ----------------------------------------------------------

def test_a_plan_that_was_never_written_cannot_be_verified(tmp_path):
    def seed(store, sid):
        seed_critic(store, sid)

    store, executor, sid, _ = run_verify(tmp_path, verify_args(), seed=seed)
    result = only_result(store, sid)
    assert result['is_error'] is True and result['errorCode'] == 'PLAN_VERIFY_NO_CRITIC'
    assert 'no plan write is recorded' in result['error']
    assert store.plan_verification(IDENTITY, 1) is None
    assert journal_writes(executor) == []
    store.close()


def test_a_write_without_any_critique_child_is_refused(tmp_path):
    def seed(store, sid):
        seed_write(store, sid)

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(), seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_NO_CRITIC'
    assert "role='plan-review'" in result['error']
    assert store.plan_verification(IDENTITY, 1) is None
    store.close()


def test_a_critique_that_ran_before_the_write_says_nothing_about_it(tmp_path):
    def seed(store, sid):
        seed_critic(store, sid)
        seed_write(store, sid)  # bản ghi ĐẾN SAU phiên phản biện

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(), seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_NO_CRITIC'
    assert store.plan_verification(IDENTITY, 1) is None
    store.close()


@pytest.mark.parametrize('status,answer_chars', [('partial', None), ('failed', None), ('completed', 120)])
def test_a_thin_or_unfinished_critique_is_refused(tmp_path, status, answer_chars):
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, status=status, answer_chars=answer_chars)

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(), seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_NO_CRITIC'
    assert 'at least 400 chars' in result['error']
    assert store.plan_verification(IDENTITY, 1) is None
    store.close()


def test_only_a_plan_review_child_counts_as_a_critique(tmp_path):
    """Một con `explore`/`review` chạy sau bản ghi KHÔNG phải người phản biện kế hoạch này."""
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, role='explore')

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(), seed=seed)
    assert only_result(store, sid)['errorCode'] == 'PLAN_VERIFY_NO_CRITIC'
    store.close()


def test_a_critique_without_a_verdict_line_is_refused(tmp_path):
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, text=CRITIQUE.replace('VERDICT: ok', 'Looks fine to me.'))

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(), seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_VERDICT_MISSING'
    assert 'VERDICT:' in result['error']
    assert store.plan_verification(IDENTITY, 1) is None
    store.close()


def test_a_verdict_the_critique_only_quotes_does_not_decide_the_outcome(tmp_path):
    """Hậu kiểm vòng 25 (M3): verdict là DÒNG CUỐI, không phải "lần khớp cuối ở bất kỳ đâu".

    Một bài phản biện thật hay **thuật lại** một verdict (vòng trước nói gì), nên luật cũ — lấy lần
    khớp cuối cùng trong cả văn bản — để một câu nhắc ở giữa bài quyết định kết quả, im lặng và không
    kiểm chứng được. Nay bài kết thúc bằng văn xuôi thì bị từ chối thẳng thắn.
    """
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, text=CRITIQUE.replace('VERDICT: ok', 'VERDICT: revise')
                    + '\n\n(Đó là điều vòng trước nói; bản này đã sửa, nên đây chỉ là chỗ tôi thuật lại.)')

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(verdict='revise'), seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_VERDICT_MISSING'
    assert 'must END' in result['error']
    assert store.plan_verification(IDENTITY, 1) is None
    store.close()


def test_blank_lines_after_the_verdict_still_leave_a_compliant_critique_readable(tmp_path):
    """Siết theo dòng cuối KHÔNG được biến một bài hợp lệ thành lỗi: dòng trống ở cuối là chuyện thường."""
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, text=CRITIQUE + '\n\n\n', wait=0.02)

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(), seed=seed)
    result = only_result(store, sid)
    assert not result.get('is_error'), result
    assert result['verdict'] == 'ok'
    assert store.plan_verification(IDENTITY, 1)['critic_verdict'] == 'ok'
    store.close()


def test_the_recorded_verdict_must_match_what_the_critique_actually_said(tmp_path):
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid, text=CRITIQUE.replace('VERDICT: ok', 'VERDICT: revise'))

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(verdict='ok'), seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_VERDICT_MISMATCH'
    assert "says 'revise'" in result['error'] and "recorded 'ok'" in result['error']
    assert store.plan_verification(IDENTITY, 1) is None
    # Ghi đúng điều nó nói thì qua cổng.
    store.close()


def test_a_revised_version_needs_its_own_critique(tmp_path):
    """Verdict gắn với ĐÚNG bản: phản biện của v1 không nói gì về v2."""
    def seed(store, sid):
        seed_write(store, sid, 1)
        seed_critic(store, sid)
        store.emit(sid, 'plan_written', {'identity': IDENTITY, 'version': 2, 'slug': 'clinical',
                                         'relativePath': '.plans/v2-clinical.md', 'title': 'Clinical',
                                         'bytes': 1300})

    store, _executor, sid, _ = run_verify(tmp_path, verify_args(version=2), seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_NO_CRITIC'
    assert store.plan_verification(IDENTITY, 2) is None
    assert store.plan_verification(IDENTITY, 1) is None
    store.close()


# --- đầu vào sai bị từ chối trước khi chạm sổ ---------------------------------------------------

@pytest.mark.parametrize('bad', [
    {'identity': 'Clinical Lookup', 'version': 1, 'verdict': 'ok'},
    {'identity': IDENTITY, 'version': 0, 'verdict': 'ok'},
    {'identity': IDENTITY, 'version': True, 'verdict': 'ok'},
    {'identity': IDENTITY, 'version': 1, 'verdict': 'maybe'},
    {'identity': IDENTITY, 'version': 1, 'verdict': 'ok',
     'issues': [{'severity': 'critical', 'text': 'x'}]},
    {'identity': IDENTITY, 'version': 1, 'verdict': 'ok', 'issues': [{'severity': 'high', 'text': ''}]},
    {'identity': IDENTITY, 'version': 1, 'verdict': 'ok', 'issues': 'not-a-list'},
])
def test_invalid_input_is_refused_before_anything_is_written(tmp_path, bad):
    def seed(store, sid):
        seed_write(store, sid)
        seed_critic(store, sid)

    store, executor, sid, _ = run_verify(tmp_path, bad, seed=seed)
    result = only_result(store, sid)
    assert result['errorCode'] == 'PLAN_VERIFY_INVALID', result
    assert store.plan_verification(IDENTITY, 1) is None
    assert journal_writes(executor) == []
    store.close()


# --- lời nhắc trong kết quả `write_plan` --------------------------------------------------------

def test_the_write_plan_result_names_the_mandatory_next_step(tmp_path):
    """Model chỉ đi tiếp nếu kết quả công cụ NÓI RA bước kế tiếp — đây là chỗ BUG-1 được vá."""
    store = SessionStore(tmp_path / 'sessions.db')
    executor = FixtureExecutor()
    runtime = HarnessRuntime(store, executor, FixtureModel([
        answer('Đã ghi', calls=[call('write_plan', {'slug': 'clinical',
                                                    'markdown': '# Clinical\n\n## Milestones\n1. Chạy '
                                                                '`pytest -q`; mong đợi 3 passed.\n'
                                                                '\n## Verification / Acceptance '
                                                                'criteria\nRun `pytest -q`, expect '
                                                                '3 passed.\n\n## Risks / '
                                                                'Limitations\n- chưa có mạng trong '
                                                                'máy này.\n'})]),
        answer('Xong.'),
        # F3: bước nhắc sau một lần ghi plan chưa có phán quyết — thiếu câu này thì lượt chết.
        answer('Chưa chạy phản biện, dừng ở đây.')]))
    sid = runtime.create({'skills': []})['id']

    async def go():
        await runtime.start(sid, 'Viết plan')

    asyncio.run(asyncio.wait_for(go(), 10))

    written = [event['data'] for event in store.events(sid) if event['type'] == 'plan_written']
    assert written, 'fixture phải ghi được plan để bài này có nghĩa'
    result = only_result(store, sid)
    assert "role='plan-review'" in result['next'] and 'plan_verify' in result['next']
    assert 'request_approval' in result['next'] and 'PLAN_APPROVAL_UNVERIFIED' in result['next']
    assert store.get(sid)['status'] == 'completed', \
        'lượt phải đóng TRỌN VẸN: fixture cạn câu trả lời làm lượt chết sau khi đã ghi plan'
    store.close()
