"""Duyệt kế hoạch trong chat phải vào sổ thật (§4.1): `request_approval` ↔ `plan_reviews`.

Vì sao có tệp này: hai nguồn tài liệu trong repo (`api/server.py` mục "plan duyệt (vòng 20)" và
`memory/session_store.py` mục "Sổ duyệt plan") đều mô tả đường ghi thứ hai — `settle()` ghi hàng
`source='approval'` khi record mang `planIdentity`/`planVersion` — nhưng **không ai viết nó**, và
không bài nào chạy `request_approval` cùng một version kế hoạch nên chỗ trống đó không lộ ra. Hệ quả
đo được: `group_state` không bao giờ trả `'submitted'`, và đồng ý trong chat không bao giờ làm nhóm
thành `approved` (nên bản sửa sau đó vẫn bị bắt khai cha theo luật R1).

Ba kết cục phải phân biệt được: đồng ý → `approved`; từ chối → `changes_requested` + ghi chú; hết hạn
→ `changes_requested` (chưa đồng ý thì không phải đồng ý).
"""
import asyncio
import copy
import json
import time

import pytest

from agentbox.agent_core import limits, plan_registry
from agentbox.agent_core.runtime import HarnessRuntime, plan_approval_target
from agentbox.memory.session_store import SessionStore

IDENTITY = 'clinical-patient-record-lookup-research'


@pytest.fixture(autouse=True)
def _approval_gate_off(monkeypatch):
    """Vòng 25 đặt cổng "chưa phản biện thì không xin duyệt được" (`PLAN_APPROVAL_UNVERIFIED`) ở
    `runtime.decision()`. Tệp này kiểm **sổ duyệt**, không kiểm cổng, nên tắt cổng cho đường ghi sổ
    chạy trần — cổng có bộ ca riêng (`test_plan_verify_gate.py`), gồm cả ca `enforce` chặn thật."""
    monkeypatch.setenv('BOXFOX_PLAN_VERIFY', 'off')


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
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        pass


async def blocked_session(runtime, store, prompt='Làm việc'):
    sid = runtime.create({'skills': []})['id']
    runtime.start(sid, prompt)
    loop = asyncio.get_running_loop()
    # Trần 5 s quá sát khi cả bộ kiểm chạy song song trên máy đang tải: lượt gieo có lần chưa kịp
    # tới `awaiting_decision` (đo vòng 25 — phải chạy lại mới xanh). Trần 30 s chỉ thành hiện thực
    # khi có lỗi thật; đường xanh vẫn thoát ở vòng lặp đầu tiên.
    end = loop.time() + 30
    while loop.time() < end:
        if store.get(sid)['status'] == 'awaiting_decision':
            return sid, runtime.pending_for(sid)[0]
        await asyncio.sleep(0.01)
    raise AssertionError('session never reached awaiting_decision within 30 s; it is ' + store.get(sid)['status'])


def approval_args(**extra):
    args = {'action': 'apply v1 of the plan', 'reason': 'Kế hoạch đã viết xong, cần bạn duyệt',
            'planIdentity': IDENTITY, 'planVersion': 1}
    args.update(extra)
    return args


def versions_of(*numbers):
    """Chỉ mục box tối thiểu mà `group_state` cần: version + đường dẫn tương đối."""
    return tuple(plan_registry._entry_from_payload({'version': number,
                                                    'relativePath': f'v{number}-{IDENTITY}.md',
                                                    'sizeBytes': 1000, 'status': 'draft'})
                 for number in numbers)


def test_a_plan_approval_lands_in_the_ledger_with_its_source(tmp_path):
    """Đồng ý trong chat ghi đúng một hàng `approved` với `source='approval'`."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin bạn duyệt', calls=[call('request_approval', approval_args())]),
            answer('Cảm ơn, tôi đi tiếp.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        # Trong lúc chờ: lượt xin duyệt phải được tính là "đã trình" cho đúng version đó.
        assert (record['planIdentity'], record['planVersion']) == (IDENTITY, 1)
        assert plan_registry.pending_submissions(runtime.pending.values(), IDENTITY) == (1,)
        state = plan_registry.group_state(versions_of(1), reviews=(),
                                          submitted=plan_registry.pending_submissions(
                                              runtime.pending.values(), IDENTITY))
        assert state.state == 'submitted'
        other = plan_registry.group_state(versions_of(1), reviews=(), submitted=())
        assert other.state == 'draft', 'không có lượt chờ nào thì vẫn là draft'

        assert runtime.resolve_decision(sid, record['decisionId'], 'approve', None)['outcome'] == 'approved'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Cảm ơn, tôi đi tiếp.'

        row = store.plan_review(IDENTITY, 1)
        assert row['decision'] == 'approved' and row['source'] == 'approval'
        assert row['session_id'] == sid and row['note'] == ''
        assert store.plan_reviews_for(IDENTITY) == [row], 'đúng MỘT hàng, không sinh hàng thứ hai'
        state = plan_registry.group_state(versions_of(1), reviews=store.plan_reviews_for(IDENTITY),
                                          submitted=())
        assert state.state == 'approved', 'đồng ý trong chat phải mở khoá luật R1 cho bản sửa'
        assert row['content_size'] is None, 'chat không đo được file nên không được bịa số đo'
        store.close()

    asyncio.run(run())


def test_a_rejection_in_chat_is_a_request_for_changes_with_the_note(tmp_path):
    """Từ chối trong chat = "yêu cầu sửa": hàng `changes_requested` mang đúng ghi chú người dùng gõ."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin bạn duyệt', calls=[call('request_approval', approval_args())]),
            answer('Tôi sửa theo ghi chú.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        runtime.resolve_decision(sid, record['decisionId'], 'reject', 'Thiếu phần đo độ trễ')
        await asyncio.wait_for(runtime.tasks[sid], 5)

        row = store.plan_review(IDENTITY, 1)
        assert row['decision'] == 'changes_requested' and row['note'] == 'Thiếu phần đo độ trễ'
        assert row['source'] == 'approval' and row['session_id'] == sid
        # R3 đọc chính hàng này: nhóm đang chờ sửa thì cùng chủ đề không được mở identity khác.
        assert plan_registry.group_state(versions_of(1), reviews=store.plan_reviews_for(IDENTITY),
                                         submitted=()).state == 'changes_requested'
        store.close()

    asyncio.run(run())


def test_an_expired_approval_is_not_an_approval(tmp_path):
    """Hết hạn: chưa ai trả lời, nên **không** hàng nào — hết hạn không phải một lời từ chối (D-37).

    Bản trước ghi `changes_requested` cho kết cục này (BUG-6), nên một lượt hết hạn trông y như một
    lời từ chối: nhóm về `changes_requested` và luật R3 bật lên vô cớ, chặn oan một identity mới
    cùng chủ đề. Nay sự thật vẫn có dấu vết, nhưng ở chỗ khác: event `plan_decision_skipped` + một
    dòng nhật ký hệ thống.
    """

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin bạn duyệt', calls=[call('request_approval', approval_args(deadlineSeconds=1))]),
            answer('Không ai trả lời nên tôi dừng.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        assert await asyncio.wait_for(runtime.tasks[sid], 10) == 'Không ai trả lời nên tôi dừng.'
        assert store.plan_review(IDENTITY, 1) is None, 'hết hạn không được ghi hàng nào'
        assert store.plan_reviews_for(IDENTITY) == []
        skipped = [event['data'] for event in store.events(sid)
                   if event['type'] == 'plan_decision_skipped']
        assert len(skipped) == 1
        assert (skipped[0]['identity'], skipped[0]['version'], skipped[0]['status']) == (IDENTITY, 1,
                                                                                        'expired')
        assert skipped[0]['reason'] == 'timeout' and skipped[0]['kind'] == 'approval'
        # Nhóm về `draft` ⇒ R3 (`:865-884`) không chặn identity mới cùng chủ đề nữa.
        assert plan_registry.group_state(versions_of(1), reviews=store.plan_reviews_for(IDENTITY),
                                         submitted=()).state == 'draft'
        store.close()

    asyncio.run(run())



def test_a_free_text_answer_on_a_plan_gate_is_not_an_approval(tmp_path):
    """P4 (vá vòng soát) — chữ tự nhập ở cổng duyệt kế hoạch là CÂU TRẢ LỜI, không phải một lời duyệt.

    Đo được trước khi vá: lựa chọn `other` mang `kind='alternative'` nên `resolve_decision` chốt thẳng
    `approved`; chủ nhà gõ "Không đồng ý, sửa lại phần X" vào ô tự nhập vẫn ghi một hàng `approved`
    vào sổ duyệt — hàng mà tab Plan đọc là "chủ nhà thật sự đồng ý". Nay kết cục là `answered`:
    không hàng nào vào sổ, nhưng sự thật vẫn có dấu vết (`plan_decision_skipped` + một dòng nhật ký).
    """

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin bạn duyệt', calls=[call('request_approval', approval_args())]),
            answer('Tôi sửa lại theo ghi chú.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        assert limits.DECISION_OTHER_OPTION_ID in [option['id'] for option in record['options']], \
            'mọi cổng duyệt đều mở ô tự nhập (P4)'
        note = 'Không đồng ý, sửa lại phần đo độ trễ'
        result = runtime.resolve_decision(sid, record['decisionId'], limits.DECISION_OTHER_OPTION_ID, note)
        assert result['outcome'] == 'answered'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Tôi sửa lại theo ghi chú.'

        assert store.plan_review(IDENTITY, 1) is None, 'chữ tự nhập không được ghi hàng duyệt nào'
        assert store.plan_reviews_for(IDENTITY) == []
        skipped = [event['data'] for event in store.events(sid)
                   if event['type'] == 'plan_decision_skipped']
        assert len(skipped) == 1
        assert (skipped[0]['identity'], skipped[0]['version'], skipped[0]['status']) == (IDENTITY, 1,
                                                                                        'answered')
        assert skipped[0]['reason'] == 'free_text' and skipped[0]['kind'] == 'approval'
        # Nhóm vẫn `draft`: câu trả lời tự nhập không mở khoá R1 (không phải `approved`) và
        # cũng không bật R3 (không phải `changes_requested`).
        assert plan_registry.group_state(versions_of(1), reviews=store.plan_reviews_for(IDENTITY),
                                         submitted=()).state == 'draft'
        # Chữ đã gõ tới được model như câu trả lời thật, kèm lời nhắn nói rõ đây KHÔNG phải đồng ý.
        seen = [json.loads(message['content']) for message in store.get(sid)['messages']
                if message['role'] == 'tool'][-1]
        assert seen['decision'] == 'answered' and seen['note'] == note
        assert 'Do NOT treat this as approval' in seen['message']
        store.close()

    asyncio.run(run())


def test_an_answer_to_a_question_about_a_plan_lands_in_the_ledger(tmp_path):
    """BUG-7: chủ nhà bấm "Duyệt" ở một câu `ask_user` mang cặp khoá plan thì hàng duyệt phải có.

    Đo vòng 25: cặp khoá chỉ được đọc cho `request_approval`, nên một câu hỏi có cặp khoá bị bỏ qua
    — tab Plan hiện "Changes requested" cho đúng bản vừa được duyệt và vừa được thi hành.
    """

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Hỏi trước khi làm', calls=[call('ask_user', {
                'question': 'Thi hành bản v1 này?', 'options': [{'id': 'go', 'label': 'Chạy',
                                                                'kind': 'approve'},
                                                               {'id': 'wait', 'label': 'Chờ',
                                                                'kind': 'reject'}],
                'planIdentity': IDENTITY, 'planVersion': 1})]),
            answer('Đã thi hành.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        assert record['kind'] == 'question'
        assert (record['planIdentity'], record['planVersion']) == (IDENTITY, 1)
        assert plan_registry.pending_submissions(runtime.pending.values(), IDENTITY) == ()
        assert runtime.resolve_decision(sid, record['decisionId'], 'approve', None)['outcome'] == 'approved'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Đã thi hành.'

        row = store.plan_review(IDENTITY, 1)
        assert row is not None, 'đồng ý ở ask_user cũng là một quyết định thật về kế hoạch'
        assert row['decision'] == 'approved' and row['source'] == 'approval'
        assert row['session_id'] == sid and row['note'] == ''
        assert store.plan_reviews_for(IDENTITY) == [row], 'đúng MỘT hàng'
        store.close()

    asyncio.run(run())


def test_an_ask_user_approval_of_an_unverified_plan_writes_no_row(tmp_path, monkeypatch):
    """H1 (hậu kiểm vòng 25): cổng phản biện phải đứng ở chỗ GHI, không chỉ ở chỗ HỎI.

    Trước khi siết: `request_approval` bị từ chối `PLAN_APPROVAL_UNVERIFIED` (không hàng nào), nhưng
    CÙNG cặp khoá plan đi qua `ask_user` + "Duyệt" thì ghi thẳng một hàng `approved` — một kế hoạch
    được duyệt mà không có phán quyết `ok` nào, đúng trạng thái vòng này dựng ra để cấm. Nay: không
    hàng, để lại dấu vết `plan_decision_skipped`, và quyết định của chủ nhà vẫn được trả như thường
    (sổ không bao giờ được giết một quyết định).
    """
    monkeypatch.setenv('BOXFOX_PLAN_VERIFY', 'enforce')

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Hỏi trước khi làm', calls=[call('ask_user', {
                'question': 'Thi hành bản v1 này?', 'options': [{'id': 'go', 'label': 'Chạy',
                                                                'kind': 'approve'},
                                                               {'id': 'wait', 'label': 'Chờ',
                                                                'kind': 'reject'}],
                'planIdentity': IDENTITY, 'planVersion': 1})]),
            answer('Đã thi hành.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        assert runtime.resolve_decision(sid, record['decisionId'], 'approve', None)['outcome'] == 'approved'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Đã thi hành.', \
            'quyết định vẫn phải được trả, chỉ đường GHI SỔ bị chặn'
        assert store.plan_review(IDENTITY, 1) is None, \
            'chưa có phán quyết `ok` thì không được sinh hàng duyệt nào'
        assert store.plan_verification(IDENTITY, 1) is None, 'cổng không được tự ghi phán quyết thay'
        skipped = [row['data'] for row in store.events(sid) if row['type'] == 'plan_decision_skipped']
        assert skipped, 'sự thật phải có dấu vết, chỉ là không nằm trong sổ duyệt'
        assert skipped[-1]['reason'] == 'unverified'
        assert skipped[-1]['code'] == 'PLAN_APPROVAL_UNVERIFIED'
        assert (skipped[-1]['identity'], skipped[-1]['version']) == (IDENTITY, 1)
        store.close()

    asyncio.run(run())


def test_a_downgraded_gate_still_lets_the_ledger_row_through(tmp_path, monkeypatch):
    """Cùng cặp khoá plan, công tắc hạ xuống `warn`: hàng duyệt CÓ mặt (đó là ý nghĩa của công tắc)."""
    monkeypatch.setenv('BOXFOX_PLAN_VERIFY', 'warn')

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Hỏi trước khi làm', calls=[call('ask_user', {
                'question': 'Thi hành bản v1 này?', 'options': [{'id': 'go', 'label': 'Chạy',
                                                                'kind': 'approve'},
                                                               {'id': 'wait', 'label': 'Chờ',
                                                                'kind': 'reject'}],
                'planIdentity': IDENTITY, 'planVersion': 1})]),
            answer('Đã thi hành.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        assert runtime.resolve_decision(sid, record['decisionId'], 'approve', None)['outcome'] == 'approved'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Đã thi hành.'
        row = store.plan_review(IDENTITY, 1)
        assert row is not None and row['decision'] == 'approved', 'hạ công tắc thì harness cho qua'
        assert [r['data'] for r in store.events(sid) if r['type'] == 'plan_decision_skipped'] == []
        store.close()

    asyncio.run(run())


def test_a_rejected_question_is_not_a_request_for_changes(tmp_path):
    """Câu hỏi bị trả lời "không" **không** phải yêu cầu sửa kế hoạch: chỉ log, không hàng (D-37)."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Hỏi trước khi làm', calls=[call('ask_user', {
                'question': 'Thi hành bản v1 này?',
                'options': [{'id': 'go', 'label': 'Chạy', 'kind': 'approve'},
                            {'id': 'wait', 'label': 'Chờ', 'kind': 'reject'}],
                'planIdentity': IDENTITY, 'planVersion': 1})]),
            answer('Thôi không làm nữa.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        assert runtime.resolve_decision(sid, record['decisionId'], 'reject', 'chưa cần')['outcome'] == 'rejected'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Thôi không làm nữa.'
        assert store.plan_reviews_for(IDENTITY) == [], 'một câu hỏi bị từ chối không sửa kế hoạch nào'
        # Không có hàng ⇒ nhóm vẫn `draft`, luật R3 không bật lên vì một câu hỏi.
        assert plan_registry.group_state(versions_of(1), reviews=store.plan_reviews_for(IDENTITY),
                                         submitted=()).state == 'draft'
        store.close()

    asyncio.run(run())


def test_a_cancelled_session_does_not_claim_a_rejection(tmp_path):
    """Phiên bị dừng khi đang chờ: không ai từ chối, nên không hàng — chỉ `plan_decision_skipped`."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin bạn duyệt', calls=[call('request_approval', approval_args())]),
            answer('Im lặng.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, _record = await blocked_session(runtime, store, 'Trình kế hoạch')

        await runtime.stop(sid)
        assert store.get(sid)['status'] == 'cancelled'
        assert store.plan_reviews_for(IDENTITY) == []
        skipped = [event['data'] for event in store.events(sid)
                   if event['type'] == 'plan_decision_skipped']
        assert [(item['status'], item['reason']) for item in skipped] == [('cancelled', 'session_cancelled')]
        store.close()

    asyncio.run(run())

def test_an_approval_that_never_named_a_plan_writes_nothing(tmp_path):
    """Đường cũ (không khai kế hoạch) không được sinh một hàng duyệt giả."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin phép xoá', calls=[call('request_approval', {'action': 'rm -rf build',
                                                                   'reason': 'Dọn thư mục build'})]),
            answer('Không xoá gì.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Dọn dẹp')

        assert 'planIdentity' not in record and 'planVersion' not in record
        assert plan_registry.pending_submissions(runtime.pending.values(), IDENTITY) == ()
        runtime.resolve_decision(sid, record['decisionId'], 'approve', None)
        await asyncio.wait_for(runtime.tasks[sid], 5)
        assert store.plan_reviews_for(IDENTITY) == [], 'không có kế hoạch nào thì không có hàng nào'
        store.close()

    asyncio.run(run())


def test_the_target_is_all_or_nothing_and_must_be_a_plan_group():
    """Hai tham số đi cặp, và `planIdentity` phải theo đúng grammar nhóm kế hoạch."""
    assert plan_approval_target({}) == (None, None)
    assert plan_approval_target({'planIdentity': '', 'planVersion': None}) == (None, None)
    assert plan_approval_target({'planIdentity': 'subplans/api', 'planVersion': 2}) == ('subplans/api', 2)
    assert plan_approval_target({'planIdentity': IDENTITY, 'planVersion': '3'}) == (IDENTITY, 3)

    for bad in ({'planIdentity': IDENTITY}, {'planVersion': 1}, {'planIdentity': IDENTITY, 'planVersion': 0},
                {'planIdentity': IDENTITY, 'planVersion': True}, {'planIdentity': IDENTITY, 'planVersion': 'v2'},
                {'planIdentity': 'Clinical Lookup', 'planVersion': 1},
                {'planIdentity': 'sub plans/api', 'planVersion': 1}):
        try:
            plan_approval_target(bad)
        except ValueError as exc:
            assert str(exc).startswith('DECISION_INVALID:'), str(exc)
        else:
            raise AssertionError('phải từ chối: ' + json.dumps(bad))
    # Grammar ở đây là **cùng một** luật với `plan_identity_arg` của route `GET /plans/status`
    # (`plan_header.IDENTITY_PATTERN`), nên không có luật thứ hai để lệch nhau: một chuỗi hợp lệ về
    # grammar nhưng vô nghĩa (`v2-slug`) là việc của `plan_registry`, không phải của chỗ kiểm tham số.
    # Dấu `/` thừa cũng được cắt như route làm, không phải lỗi.
    assert plan_approval_target({'planIdentity': 'v2-lookup', 'planVersion': 2}) == ('v2-lookup', 2)
    assert plan_approval_target({'planIdentity': '/subplans/api/', 'planVersion': 2}) == ('subplans/api', 2)


def test_a_half_declared_plan_is_a_tool_error_not_a_silent_approval(tmp_path):
    """Khai `planIdentity` mà quên số: lượt xin duyệt hỏng ngay, không có hàng duyệt nào được ghi."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin bạn duyệt', calls=[call('request_approval', {'action': 'apply the plan',
                                                                     'reason': 'Cần duyệt',
                                                                     'planIdentity': IDENTITY})]),
            answer('Tôi hỏi lại cho đủ.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid = runtime.create({'skills': []})['id']

        assert await asyncio.wait_for(runtime.start(sid, 'Trình kế hoạch'), 5) == 'Tôi hỏi lại cho đủ.'
        errors = [json.loads(message['content']) for message in store.get(sid)['messages']
                  if message['role'] == 'tool' and json.loads(message['content']).get('is_error')]
        assert errors and errors[0]['error'].startswith('DECISION_INVALID: request_approval needs '
                                                        'planIdentity and planVersion')
        assert store.get(sid)['status'] == 'completed', 'lỗi tham số không được treo lượt'
        assert store.plan_reviews_for(IDENTITY) == [] and not runtime.pending_for(sid)
        store.close()

    asyncio.run(run())


def test_the_ledger_write_never_blocks_the_decision(tmp_path):
    """Sổ duyệt hỏng thì quyết định vẫn phải chốt — người dùng đã trả lời, không được treo lượt."""

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        model = FixtureModel([
            answer('Xin bạn duyệt', calls=[call('request_approval', approval_args())]),
            answer('Đi tiếp.')])
        runtime = HarnessRuntime(store, FixtureExecutor(), model)
        sid, record = await blocked_session(runtime, store, 'Trình kế hoạch')

        def boom(*args, **kwargs):
            raise RuntimeError('database is locked')

        store.record_plan_review = boom
        assert runtime.resolve_decision(sid, record['decisionId'], 'approve', None)['status'] == 'resolved'
        assert await asyncio.wait_for(runtime.tasks[sid], 5) == 'Đi tiếp.'
        assert record['outcome']['decision'] == 'approved'
        store.close()

    asyncio.run(run())


def test_the_submitted_state_disappears_when_the_answer_arrives(tmp_path):
    """`submitted` là trạng thái của một lượt CÒN TREO, không phải một hàng trong sổ."""
    now = time.time()
    record = {'kind': 'approval', 'resolved': False, 'planIdentity': IDENTITY, 'planVersion': 2}
    assert plan_registry.pending_submissions([record], IDENTITY) == (2,)
    record['resolved'] = True
    assert plan_registry.pending_submissions([record], IDENTITY) == ()
    assert plan_registry.pending_submissions([{'kind': 'approval', 'resolved': False,
                                               'planIdentity': IDENTITY, 'planVersion': 0}], IDENTITY) == ()
    assert plan_registry.pending_submissions([{'kind': 'question', 'resolved': False,
                                               'planIdentity': IDENTITY, 'planVersion': 2}], IDENTITY) == ()
    assert now > 0
