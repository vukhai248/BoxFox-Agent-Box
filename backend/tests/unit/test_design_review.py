"""P4 — soát độc lập, báo cáo và bàn giao của `/design` (plan v1 §6.3, §6.6, §7.9).

Bốn cổng của `design_review` (`NO_CRITIC`, `VERDICT_MISSING`, `VERDICT_MISMATCH`) và cổng
`DESIGN_HANDOFF_UNREVIEWED` của `design_report` chạy tất định: không mạng, không mô hình thật.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore

CRITIQUE_TEMPLATE = (
    '## Findings by Severity\n'
    '- [high] `app.txt:1` — mốc chèn không xác định được nếu tệp đổi giữa hai lần ghi; '
    'hãy ghim sha256 trước khi ghi.\n'
    '- [medium] thiếu đường lỗi cho trạng thái rỗng của màn hình chat; bản thiết kế chỉ tả happy path.\n'
    '- [low] tên component trong sơ đồ chưa khớp tên trong mã.\n'
    '## Touch List Problems\n'
    '- `src/unlisted.ts` chưa nằm trong danh sách chạm nhưng phần triển khai sẽ cần nó.\n'
    '## Contract And State Gaps\n'
    '- chưa định nghĩa trạng thái khi nhánh thiết kế bị tạo lại.\n'
    '## Unverified Claims\n'
    '- khẳng định "không đổi API" chưa có bằng chứng trong mã.\n'
)


class RecordingExecutor:
    def __init__(self):
        self.ops = []

    async def execute(self, name, args, sid, **kwargs):
        self.ops.append((name, dict(args)))
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None

    def written(self):
        return [args.get('path') for name, args in self.ops if name == 'file_write']


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'sessions.db')
    executor = RecordingExecutor()
    runtime = HarnessRuntime(store, executor, FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30, 'deadlineSeconds': 60})['id']
    yield store, runtime, sid, executor
    store.close()


def open_run(runtime, store, sid):
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế lại màn hình chat')
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)
    return store.design_job(job['design_id'])


def call(runtime, store, sid, name, args):
    async def run():
        return await runtime.dispatch(store.get(sid), name, args)

    return asyncio.run(run())


def events(store, sid, kind):
    return [row['data'] for row in store.events(sid) if row['type'] == kind]


def seed_critic(store, sid, job, version, text, *, status='completed', role='plan-review',
                design_id=None, version_override=None, target=True, answer_chars=None):
    """Một con `plan-review` đã xong, mang `reviewTarget` trỏ đúng bản thiết kế (hoặc cố tình sai)."""
    child = store.create({'skills': []}, role=role, parent_id=sid)['id']
    store.child_start(child, sid, 1, 2, role, 'review the design')
    config = dict(store.get(child)['config'] or {})
    if target:
        config['reviewTarget'] = {'kind': 'design',
                                  'designId': design_id if design_id is not None else job['design_id'],
                                  'version': version if version_override is None else version_override,
                                  'path': f'.design/{job["design_id"]}/v{version}-design.md'}
    store.update_config(child, config)
    if text is not None:
        store.emit(child, 'assistant', {'text': text, 'final': True})
    store.child_finish(child, status, reason=None, steps_used=4,
                       answer_chars=answer_chars if answer_chars is not None else len(text or ''))
    return child


# ------------------------------------------------------------------ Cổng design_review


def test_no_critic_refused(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_review',
             {'designId': job['design_id'], 'version': 1, 'verdict': 'ok'})
    assert limits.DESIGN_REVIEW_NO_CRITIC_CODE in str(caught.value)


def test_verdict_mismatch_refused(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: revise')
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_review',
             {'designId': job['design_id'], 'version': 1, 'verdict': 'ok'})
    assert limits.DESIGN_REVIEW_VERDICT_MISMATCH_CODE in str(caught.value)


def test_verdict_missing_refused(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE.rstrip())
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_review',
             {'designId': job['design_id'], 'version': 1, 'verdict': 'ok'})
    assert limits.DESIGN_REVIEW_VERDICT_MISSING_CODE in str(caught.value)


def test_critic_for_another_run_is_not_usable(harness):
    """Một con `plan-review` của RUN KHÁC không mở được cổng của run này (§7.9)."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: ok', design_id='d-other-run')
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_review',
             {'designId': job['design_id'], 'version': 1, 'verdict': 'ok'})
    assert limits.DESIGN_REVIEW_NO_CRITIC_CODE in str(caught.value)


def test_critic_without_target_is_not_usable(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: ok', target=False)
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_review',
             {'designId': job['design_id'], 'version': 1, 'verdict': 'ok'})
    assert limits.DESIGN_REVIEW_NO_CRITIC_CODE in str(caught.value)


def test_short_critique_is_not_usable(harness):
    """Bản soát ngắn hơn trần `PLAN_REVIEW_MIN_ANSWER_CHARS` chưa phải một bản soát đầy đủ."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, 'VERDICT: ok', answer_chars=12)
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_review',
             {'designId': job['design_id'], 'version': 1, 'verdict': 'ok'})
    assert limits.DESIGN_REVIEW_NO_CRITIC_CODE in str(caught.value)


def test_review_records_verdict_and_writes_review_md(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: ok\n\n')
    result = call(runtime, store, sid, 'design_review',
                  {'designId': job['design_id'], 'version': 1, 'verdict': 'ok',
                   'summary': 'bản thiết kế đứng được', 'issues': [{'severity': 'low',
                                                                    'title': 'tên chưa khớp'}]})
    assert result == {'designId': job['design_id'], 'version': 1, 'verdict': 'ok',
                      'recorded': True}
    live = store.design_job(job['design_id'])
    assert live['state']['review']['verdict'] == 'ok'
    assert live['state']['review']['version'] == 1
    assert any(row['phase'] == 'reviewing' for row in live['state']['phaseHistory'])
    assert f'.design/{design_runtime._slug(job["design_id"])}/review.md' in executor.written()
    assert events(store, sid, 'design_run'), 'nhích pha phải phát `design_run`'


def test_revise_sends_the_run_back_to_scaffolding(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: revise')
    call(runtime, store, sid, 'design_review',
         {'designId': job['design_id'], 'version': 1, 'verdict': 'revise'})
    live = store.design_job(job['design_id'])
    assert live['state']['review']['verdict'] == 'revise'
    assert live['state']['phase'] == 'scaffolding'


# ------------------------------------------------------------------ Cổng design_report


def test_handoff_without_verdict_refused(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_report', {'summary': 'xong'})
    assert limits.DESIGN_HANDOFF_UNREVIEWED_CODE in str(caught.value)
    assert 'report.md' not in ' '.join(path or '' for path in executor.written())


def test_report_closes_the_run_and_emits_one_card(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: ok')
    call(runtime, store, sid, 'design_review',
         {'designId': job['design_id'], 'version': 1, 'verdict': 'ok', 'summary': 'ok'})
    result = call(runtime, store, sid, 'design_report',
                  {'summary': 'bản thiết kế sẵn sàng', 'labels': ['design-md'],
                   'nextSteps': ['triển khai màn hình chat']})
    live = store.design_job(job['design_id'])
    assert result == {'designId': job['design_id'], 'version': 1,
                      'path': live['state']['report']['path'], 'labels': ['design-md']}
    assert live['status'] == 'completed'
    assert live['state']['phase'] == design_runtime.PHASE_DONE
    assert live['state']['report']['nextSteps'] == ['triển khai màn hình chat']
    cards = events(store, sid, 'design_report')
    assert len(cards) == 1
    assert cards[0]['designId'] == job['design_id']
    assert cards[0]['labels'] == ['design-md']
    assert set(cards[0]) == {'designId', 'version', 'branch', 'path', 'labels', 'summary'}
    assert f'.design/{design_runtime._slug(job["design_id"])}/report.md' in executor.written()
    # Run đóng ⇒ không còn run sống để bơm/khối mode bám vào.
    mode = store.get(sid)['config']['designMode']
    assert not mode.get('activeRunId')


def test_partial_label_closes_as_partial(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: ok')
    call(runtime, store, sid, 'design_review',
         {'designId': job['design_id'], 'version': 1, 'verdict': 'ok'})
    call(runtime, store, sid, 'design_report',
         {'summary': 'còn hai màn hình', 'labels': ['partial']})
    assert store.design_job(job['design_id'])['status'] == 'partial'


def test_report_needs_an_ok_for_the_latest_version(harness):
    """`ok` của v1 không mở đường cho bàn giao khi bản được soát gần nhất là v2 `revise`."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    seed_critic(store, sid, job, 2, CRITIQUE_TEMPLATE + '\nVERDICT: revise')
    call(runtime, store, sid, 'design_review',
         {'designId': job['design_id'], 'version': 2, 'verdict': 'revise'})
    with pytest.raises(ValueError) as caught:
        call(runtime, store, sid, 'design_report', {'summary': 'xong'})
    assert limits.DESIGN_HANDOFF_UNREVIEWED_CODE in str(caught.value)


# ------------------------------------------------------------------ Payload cho giao diện


def test_payload_exposes_batch_and_review(harness):
    """Khoá `batch`/`review` của hợp đồng §6 — đúng tên, và `verdict` đã dịch sang cặp giao diện."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    payload = design_runtime.design_run_payload(store.design_job(job['design_id']))
    assert payload['batch'] is None and payload['review'] is None
    state = dict(store.design_job(job['design_id'])['state'])
    state['diff'] = {'files': [{'path': 'app.txt', 'status': 'M', 'added': 3, 'removed': 1}],
                     'patchPath': f'.design/{design_runtime._slug(job["design_id"])}/diff.patch',
                     'at': '2026-09-27T00:00:00Z'}
    store.design_job_save(job['design_id'], sid, state)
    seed_critic(store, sid, job, 1, CRITIQUE_TEMPLATE + '\nVERDICT: ok')
    call(runtime, store, sid, 'design_review',
         {'designId': job['design_id'], 'version': 1, 'verdict': 'ok', 'summary': 'đứng được'})
    payload = design_runtime.design_run_payload(store.design_job(job['design_id']))
    assert payload['batch']['files'][0]['path'] == 'app.txt'
    assert payload['batch']['added'] == 3 and payload['batch']['removed'] == 1
    assert payload['batch']['status'] == 'proposed'
    assert payload['review'] == {'version': '1', 'verdict': 'passed', 'summary': 'đứng được'}


def test_named_design_run_matches_the_ui_label(harness):
    """Nút "Dùng cho plan" gửi NHÃN `D-<5 cuối>`, không gửi mã đầy đủ (`designMode.runLabel`)."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    compact = ''.join(ch for ch in job['design_id'].lower() if ch.isalnum())
    label = f'D-{compact[-5:].upper()}'
    assert runtime.named_design_run(store.get(sid),
                                    f'Lập plan dựa trên bàn giao thiết kế {label} v1') == job['design_id']
    assert runtime.named_design_run(store.get(sid), 'không nhắc tên run nào') == ''


# ------------------------------------------------------------------ `design_notice` (§7.2)


def test_needs_user_notice_fires_exactly_once(harness):
    """Brief mơ hồ ⇒ run dừng ở `needs_user` và thông báo chỉ nói MỘT lần cho mỗi run."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    notices = [row['data'] for row in store.events(sid) if row['type'] == 'design_notice']
    assert [row['kind'] for row in notices].count('needs-user') == 1
    live = store.design_job(job['design_id'])
    assert live['status'] == 'needs_user'
    assert design_runtime.notify_run(runtime, sid, live) is None, 'lần gọi lại không nhân thông báo'


def test_paused_run_notifies_blocked_exactly_once(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    live = store.design_job(job['design_id'])
    paused = store.design_job_save(job['design_id'], sid, dict(live['state']), status='paused',
                                   revision=live['revision'])
    assert design_runtime.notify_run(runtime, sid, paused) is not None
    assert design_runtime.notify_run(runtime, sid, store.design_job(job['design_id'])) is None
    kinds = [row['data']['kind'] for row in store.events(sid) if row['type'] == 'design_notice']
    assert kinds.count('blocked') == 1
