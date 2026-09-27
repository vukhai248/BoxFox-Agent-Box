"""Pha phản biện độc lập — cổng provenance (`research_critique`, vòng 27 đợt 6, D-40/#6024).

Một phán quyết chỉ có giá trị khi có MỘT phiên khác thật, chạy SAU khi bản hồ sơ được ghi, mang vai
`research-review`, và nói ra kết luận của nó ở dòng cuối. Ca kiểm ghim đúng bốn điều kiện ấy — thiếu
một điều là `research_verify` từ chối, không phải ghi khống.
"""
from __future__ import annotations

import asyncio

import pytest

from agentbox.agent_core import limits, research_runtime
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        pass


class FixtureModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return {'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}]}


CRITIQUE = ('Đã đọc bản hồ sơ và mở lại hai nguồn tầng 1 bằng `source_verify`. Mức hưởng đúng '
            'tuyến khớp với văn bản đã dẫn, và mục Việc chưa làm nói đúng chỗ còn thiếu. Hai điểm '
            'còn yếu: mục mâu thuẫn chưa nói bản tiếng Anh của văn bản, và khẳng định về phụ phí '
            'chỉ đứng trên một nguồn tầng 2 nên chưa đủ để chủ nhà dùng khi quyết. Đề nghị bổ sung '
            'nguồn thứ hai cho khẳng định ấy, hoặc hạ nó xuống mức suy luận và nói rõ là suy luận.\n'
            'VERDICT: revise\n')

QUOTED = ('Trong bản kế hoạch cũ tôi thấy có ghi "VERDICT: ok" ở giữa bài và người viết đã dẫn lại '
          'nó như một kết luận. Nhưng đó là chữ tôi đang trích lại chứ không phải kết luận của tôi: '
          'dòng ấy nằm trong phần mô tả định dạng, không nằm ở cuối bài, và tôi không viết nó. Tôi '
          'cần thêm một nguồn gốc trước khi nói được bản hồ sơ này đạt hay không, nên xin phép chưa '
          'kết luận ở lượt này. Nếu chủ nhà muốn tôi kết luận ngay thì cần bổ sung nguồn cho khẳng '
          'định về phụ phí, hoặc xác nhận rằng khẳng định ấy chỉ là suy luận của người viết.\n')

assert len(CRITIQUE) >= 400, len(CRITIQUE)
assert len(QUOTED) >= 400, len(QUOTED)


@pytest.fixture()
def harness(tmp_path):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel())
    sid = runtime.create({'skills': []})['id']
    yield store, runtime, sid, store.get(sid)
    store.close()


def record_dossier(store, sid, version=1, minutes_ago=0.0):
    """Ghi chỉ mục hồ sơ như `dossier_write` đã làm — không cần op của box để kiểm cổng."""
    import time

    store.record_dossier(sid, 'gia-dich-vu-2026', version, f'.research/gia-dich-vu-2026/v{version}-gia-dich-vu-2026.md',
                         profile='price', level=3, critique='none', gate='warn', rows=3, bytes=1200)
    if minutes_ago:
        with store.db:
            store.db.execute('UPDATE research_dossiers SET created=? WHERE research_id=? AND version=?',
                             (time.time() - minutes_ago * 60, 'gia-dich-vu-2026', version))
    return version


def review_child(store, runtime, parent_id, text=None, started_offset=1.0, status='completed',
                 answer_chars=None):
    """Một phiên con `research-review` đã xong, có câu trả lời trong luồng của nó."""
    import time

    child = runtime.create({'skills': []}, parent_id=parent_id, role='research-review')
    # Hàng sổ con do `delegate_task` ghi, không do `create` — dựng đúng hàng ấy ở đây.
    store.child_start(child['id'], parent_id, 1, 1, 'research-review', 'phản biện hồ sơ')
    body = text if text is not None else CRITIQUE
    store.emit(child['id'], 'assistant', {'text': body})
    store.child_finish(child['id'], status, answer_chars=answer_chars if answer_chars is not None
                       else len(body))
    if started_offset:
        with store.db:
            store.db.execute('UPDATE children SET started=started+? WHERE session_id=?',
                             (started_offset, child['id']))
    del time
    return child


def test_a_critique_that_ran_before_the_dossier_write_cannot_decide(harness):
    store, runtime, sid, session = harness
    record_dossier(store, sid, version=1)
    review_child(store, runtime, sid, started_offset=-30.0)
    with pytest.raises(ValueError, match=limits.RESEARCH_VERIFY_NO_CRITIC_CODE):
        research_runtime.research_critique(runtime, sid, 'gia-dich-vu-2026', 1)


def test_a_critique_shorter_than_the_minimum_is_not_accepted(harness):
    store, runtime, sid, session = harness
    record_dossier(store, sid, 1)
    review_child(store, runtime, sid, text='VERDICT: ok\n', answer_chars=10)
    with pytest.raises(ValueError, match=limits.RESEARCH_VERIFY_NO_CRITIC_CODE):
        research_runtime.research_critique(runtime, sid, 'gia-dich-vu-2026', 1)


def test_a_verdict_the_critique_only_quotes_does_not_count(harness):
    store, runtime, sid, session = harness
    record_dossier(store, sid, 1)
    review_child(store, runtime, sid, text=QUOTED)
    with pytest.raises(ValueError, match=limits.RESEARCH_VERIFY_VERDICT_MISSING_CODE):
        research_runtime.research_critique(runtime, sid, 'gia-dich-vu-2026', 1)


def test_a_real_critique_is_read_from_its_last_line(harness):
    store, runtime, sid, session = harness
    record_dossier(store, sid, 1)
    child = review_child(store, runtime, sid)
    critic, verdict, chars = research_runtime.research_critique(runtime, sid, 'gia-dich-vu-2026', 1)
    assert verdict == 'revise'
    assert critic['session_id'] == child['id']
    assert chars == len(CRITIQUE)


def test_an_unknown_version_is_named_as_such(harness):
    store, runtime, sid, session = harness
    with pytest.raises(ValueError, match=limits.RESEARCH_VERIFY_UNKNOWN_CODE):
        research_runtime.research_critique(runtime, sid, 'gia-dich-vu-2026', 4)


def test_only_the_orchestrator_records_the_verdict(harness):
    store, runtime, sid, session = harness
    record_dossier(store, sid, 1)
    review_child(store, runtime, sid)
    branch = runtime.create({'skills': []}, parent_id=sid, role='research')
    with pytest.raises(PermissionError):
        asyncio.run(runtime.dispatch(store.get(branch['id']), 'research_verify',
                                     {'researchId': 'gia-dich-vu-2026', 'version': 1, 'verdict': 'revise'}))
    answer = asyncio.run(runtime.dispatch(session, 'research_verify',
                                          {'researchId': 'gia-dich-vu-2026', 'version': 1,
                                           'verdict': 'revise', 'issues': ['thiếu nguồn thứ hai'],
                                           'summary': 'bổ sung nguồn'}))
    assert answer['verdict'] == 'revise'
    assert answer['label'] == limits.RESEARCH_CRITIQUE_LABEL
    assert answer['capped'] is False
    assert answer['criticSessionId'] and answer['criticAnswerChars'] == len(CRITIQUE)
    assert store.dossier('gia-dich-vu-2026', 1)['critique'] == 'revise'


def test_a_verdict_that_disagrees_with_the_critique_is_refused(harness):
    store, runtime, sid, session = harness
    record_dossier(store, sid, 1)
    review_child(store, runtime, sid)
    with pytest.raises(ValueError, match=limits.RESEARCH_VERIFY_VERDICT_MISMATCH_CODE):
        asyncio.run(runtime.dispatch(session, 'research_verify',
                                     {'researchId': 'gia-dich-vu-2026', 'version': 1, 'verdict': 'ok'}))
    with pytest.raises(ValueError, match=limits.RESEARCH_VERIFY_VERSION_MISSING_CODE):
        asyncio.run(runtime.dispatch(session, 'research_verify',
                                     {'researchId': 'gia-dich-vu-2026', 'version': 'v1', 'verdict': 'ok'}))
    assert store.research_verification_count('gia-dich-vu-2026') == 0


def test_a_review_child_that_declares_another_target_cannot_decide(harness):
    """Đợt soát `3dc745f`, finding 7: con nào đã KHAI đích danh bản và mức soát thì phải khớp —
    kể cả khi hàng hồ sơ không có băm. Trước đây cả khối kiểm danh tính nằm trong
    `if row.get('content_hash'):`, nên lượt quét MỚI-NHẤT-TRƯỚC (A2) có thể nhận một con
    `evidence` cho một lần kiểm `critique`, hoặc một con trỏ vào bản khác, chỉ vì nó xong sau cùng.
    """
    store, runtime, sid, session = harness
    record_dossier(store, sid, 1)
    wrong_mode = review_child(store, runtime, sid)
    config = store.get(wrong_mode['id'])['config']
    config['reviewTarget'] = {'kind': 'research', 'researchId': 'gia-dich-vu-2026',
                              'version': 1, 'mode': 'evidence'}
    store.update_config(wrong_mode['id'], config)
    wrong_version = review_child(store, runtime, sid)
    config = store.get(wrong_version['id'])['config']
    config['reviewTarget'] = {'kind': 'research', 'researchId': 'gia-dich-vu-2026',
                              'version': 2, 'mode': 'critique'}
    store.update_config(wrong_version['id'], config)
    with pytest.raises(ValueError, match=limits.RESEARCH_VERIFY_NO_CRITIC_CODE):
        research_runtime.research_critique(runtime, sid, 'gia-dich-vu-2026', 1, mode='critique')
