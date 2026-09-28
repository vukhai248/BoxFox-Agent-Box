"""Hai cổng CUỐI LƯỢT của chế độ plan, bản vá F2/F3 (đợt soát 2026-09-27).

Vì sao có tệp này — đo ba ca plan ngày 2026-09-27:

* **F2**: cả ba ca đều **0 lượt hỏi lại** (`decision_requested` = 0, `ask_user` = 0) trong khi kế
  hoạch viết ra vẫn tự quyết những chỗ đề bài để mở. Kỹ năng `planning` nay có bước 0 "hỏi trước khi
  giả định", và harness ghim notice mềm `PLAN_ASSUMPTIONS_UNCONFIRMED` khi bản kế hoạch của lượt mang
  mục giả định/câu hỏi mở mà lượt ấy không hỏi ai.
* **F3**: lượt plan kết thúc mà không có kết luận phản biện nào được ghi (2/3 ca), nên bản đã viết
  không xin duyệt được (`PLAN_APPROVAL_UNVERIFIED`) — đúng anti-pattern "dừng sau `write_plan`".
  Harness nay bơm **ĐÚNG MỘT** bước nhắc giữa lượt (`PLAN_VERDICT_NUDGE`), và nếu vẫn thiếu thì ghim
  `PLAN_VERDICT_MISSING_AT_TURN_END` để chủ nhà biết vì sao bị chối duyệt.

Cả hai cổng đều MỀM: không chặn lượt, không sửa câu trả lời, không thêm lượt gọi mô hình nào ngoài
bước nhắc của F3.
"""
from __future__ import annotations

import asyncio
import copy
import json

from agentbox.agent_core import limits, plan_quality
from agentbox.agent_core.runtime import HarnessRuntime, turn_prompt_excerpt
from agentbox.memory.session_store import SessionStore

# Kế hoạch đã qua trọn thang chấm (lấy từ `test_write_plan.py`) + mục giả định — thứ mà F2 đọc.
PLAN_MARKDOWN = """# Workspace plan

## Giả định / Câu hỏi mở
- Chưa rõ màn hình đích là chat hay bảng điều khiển.
- Người dùng đã có tài khoản sẵn hay phải tự đăng ký.

## Milestones
1. Chạy `.venv/bin/python -m pytest backend/tests -q`; mong đợi 9 passed.
2. Gọi `GET /api/agent/health` và xác nhận mã trả về là 200.

## Verification / Acceptance criteria
Run `.venv/bin/python -m pytest backend/tests -q`; expect only the 3 known environment failures.

## Risks / Limitations
- Giới hạn: chưa kiểm được hành vi khi box mất mạng vì môi trường này không mô phỏng được.
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


JOURNAL_OPS = {'journal_append', 'session_ensure', 'checkpoint_write'}


class PlanFixtureExecutor:
    """Đứng thay hộp cát: trả đúng khuôn `write_plan` mà worker thật trả (không có `identity`)."""

    def __init__(self):
        self.calls = []
        self.versions = 0

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        if name in JOURNAL_OPS:
            return {'ok': True, 'id': (args.get('record') or {}).get('id'), 'seq': 1,
                    'relPath': '.session-history/journal.jsonl'}
        assert name == 'write_plan', 'write_plan phải đi qua hộp cát: ' + name
        self.versions += 1
        return {'content': 'Written ' + args['slug'], 'version': self.versions,
                'slug': args['slug'], 'relativePath': f".plans/v{self.versions}-{args['slug']}.md",
                'bytes': len(args['markdown'].encode('utf-8'))}

    async def cleanup(self, sid):
        return None


class FakeBudget:
    """Ngân sách giả: `when()` trả đúng mốc được gieo."""

    def __init__(self, when):
        self._when = when

    def when(self):
        return self._when

    def reschedule(self, when):
        self._when = when


def runtime_at(tmp_path, responses):
    store = SessionStore(tmp_path / 'sessions.db')
    model = FixtureModel(responses)
    runtime = HarnessRuntime(store, PlanFixtureExecutor(), model)
    sid = runtime.create({'skills': []})['id']
    return store, runtime, sid, model


def notices(store, sid, code=None):
    return [event['data'] for event in store.events(sid) if event['type'] == 'notice'
            and (code is None or event['data'].get('code') == code)]


def kinds(store, sid):
    return [event['type'] for event in store.events(sid)]


def turn_messages(store, sid):
    return store.get(sid)['messages']


def write_call(slug='workspace-plan', markdown=PLAN_MARKDOWN):
    return call('write_plan', {'slug': slug, 'markdown': markdown, 'title': 'Workspace plan'})


# --- những con số mà hợp đồng đã chốt -----------------------------------------------------------

def test_the_gate_codes_and_numbers_are_the_contract_ones():
    assert limits.PLAN_ASSUMPTIONS_UNCONFIRMED_CODE == 'PLAN_ASSUMPTIONS_UNCONFIRMED'
    assert limits.PLAN_VERDICT_NUDGE_CODE == 'PLAN_VERDICT_NUDGE'
    assert limits.PLAN_VERDICT_MISSING_TURN_CODE == 'PLAN_VERDICT_MISSING_AT_TURN_END'
    assert limits.PLAN_VERDICT_NUDGE_MAX == 1, 'một lượt chỉ được nhắc MỘT lần'
    assert limits.PLAN_VERDICT_NUDGE_MIN_SECONDS == 180


def test_assumption_items_reads_the_open_questions_section():
    """F2 đọc đúng mục giả định: có thì kể ra (đã bỏ dấu đầu dòng), không có thì rỗng."""
    items = plan_quality.assumption_items(PLAN_MARKDOWN)
    assert items == ['Chưa rõ màn hình đích là chat hay bảng điều khiển.',
                     'Người dùng đã có tài khoản sẵn hay phải tự đăng ký.']
    assert plan_quality.assumption_items('# Plan\n\n## Risks\n- rủi ro\n') == []


def test_assumption_items_is_capped_and_says_how_many_were_left_out():
    """Mục thứ 6 trở đi không bị bỏ im lặng: chúng được đếm thành một dòng `... và N mục nữa`."""
    lines = '\n'.join(f'- giả định {i}' for i in range(1, 9))
    items = plan_quality.assumption_items(f'# Plan\n\n## Assumptions\n{lines}\n')
    assert items[:plan_quality.ASSUMPTION_ITEMS_MAX] == [f'giả định {i}'
                                                         for i in range(1, plan_quality.ASSUMPTION_ITEMS_MAX + 1)]
    assert items[-1] == '... và 3 mục nữa'


# --- F3: bước nhắc giữa lượt --------------------------------------------------------------------

def test_a_plan_without_a_verdict_gets_exactly_one_nudge_step(tmp_path):
    """Lượt viết plan rồi định đóng: MỘT câu nhắc, rồi notice nói rõ vì sao vẫn chưa duyệt được."""

    async def run():
        store, runtime, sid, model = runtime_at(tmp_path, [
            answer('Viết plan', calls=[write_call()]),
            answer('Xong, plan đã viết.'),
            answer('Xong thật rồi.')])
        await asyncio.wait_for(runtime.start(sid, 'Lên plan'), 20)

        nudges = notices(store, sid, limits.PLAN_VERDICT_NUDGE_CODE)
        assert len(nudges) == 1, 'nhắc đúng MỘT lần'
        assert nudges[0]['identity'] == 'workspace-plan' and nudges[0]['version'] == 1

        # Câu nhắc là một BƯỚC THẬT của lượt: nó nằm trong transcript như một chỉ dẫn, và mô hình
        # được gọi thêm đúng một lần để trả lời nó.
        nudge_text = [m['content'] for m in turn_messages(store, sid)
                      if m['role'] == 'user' and str(m.get('content') or '').startswith(
                          limits.PLAN_VERDICT_NUDGE_CODE)]
        assert len(nudge_text) == 1
        assert "role='plan-review'" in nudge_text[0]
        assert "reviewTarget={kind:'plan', identity:'workspace-plan', version:1}" in nudge_text[0], \
            'câu nhắc phải mang ĐÚNG danh tính và bản của kế hoạch, không phải chỗ trống'
        assert '{identity}' not in nudge_text[0] and '{{' not in nudge_text[0], \
            'mẫu còn sót chỗ trống hoặc ngoặc đôi là chỉ dẫn mô hình không đọc được'
        assert 'PLAN_APPROVAL_UNVERIFIED' in nudge_text[0]
        assert 'UPSTREAM_HTTP_502' in nudge_text[0], 'lỗi tạm thời của nhà cung cấp phải được nói rõ'
        assert len(model.requests) == 3, 'hai câu trả lời của mô hình + một bước nhắc'

        # Nhắc xong vẫn thiếu phán quyết ⇒ notice bền, và notice ấy phải nói rõ hệ quả.
        missing = notices(store, sid, limits.PLAN_VERDICT_MISSING_TURN_CODE)
        assert len(missing) == 1 and missing[0]['version'] == 1
        assert 'PLAN_APPROVAL_UNVERIFIED' in missing[0]['message']
        assert kinds(store, sid).count('finish') == 1, 'một lượt, không mở lượt mới'
        assert [n['code'] for n in notices(store, sid) if n['code'].startswith('PLAN_VERDICT')] == \
            [limits.PLAN_VERDICT_NUDGE_CODE, limits.PLAN_VERDICT_MISSING_TURN_CODE]
        store.close()

    asyncio.run(run())


def test_the_nudge_carries_the_prefix_the_recap_knows_to_skip(tmp_path):
    """Tiền tố câu nhắc là HỢP ĐỒNG giữa chỗ VIẾT (harness) và chỗ BỎ QUA (`turn_prompt_excerpt`).

    Đây là dây nối hai đầu: câu nhắc do harness bơm phải mang `PLAN_VERDICT_NUDGE_PREFIX`, và hàm
    dựng bản nhắc việc phải nhận ra ĐÚNG tiền tố ấy. Đứt dây thì bước sau đọc chỉ dẫn của harness
    như thể chủ nhà vừa yêu cầu giao một con `plan-review` (`owner request (excerpt): …`), còn việc
    đổi tên hằng số thì không ai bắt được — cả hai đầu đều nằm trong một tệp khác.
    """
    assert limits.PLAN_VERDICT_NUDGE_PREFIX == limits.PLAN_VERDICT_NUDGE_CODE + ':', \
        'tiền tố phải dựng TỪ mã, không phải một chuỗi chép tay'

    async def run():
        store, runtime, sid, _ = runtime_at(tmp_path, [
            answer('Viết plan', calls=[write_call()]),
            answer('Xong, plan đã viết.'),
            answer('Xong thật rồi.')])
        await asyncio.wait_for(runtime.start(sid, 'Lên plan'), 20)

        nudge = [m['content'] for m in turn_messages(store, sid)
                 if m['role'] == 'user' and str(m.get('content') or '').startswith(
                     limits.PLAN_VERDICT_NUDGE_CODE)]
        assert len(nudge) == 1, 'lượt này phải có đúng một bước nhắc để đem ra thử'
        assert nudge[0].startswith(limits.PLAN_VERDICT_NUDGE_PREFIX), \
            'chỗ VIẾT phải dùng đúng tiền tố mà chỗ BỎ QUA biết'
        assert turn_prompt_excerpt([{'role': 'user', 'content': nudge[0]}]) == '', \
            'chỉ dẫn của harness không bao giờ là "việc chủ giao"'

        owner = {'role': 'user', 'content': 'Làm nốt phần phản biện giúp tôi.'}
        assert turn_prompt_excerpt([owner, {'role': 'user', 'content': nudge[0]}]) == owner['content'], \
            'việc THẬT của chủ vẫn phải đọc được khi câu nhắc nằm sau nó'
        store.close()

    asyncio.run(run())


def test_the_turn_deadline_extension_is_recorded_for_the_write(tmp_path):
    """Lượt plan thường nới hạn chót ĐÚNG một lần, và lần ấy là của `write_plan`."""

    async def run():
        store, runtime, sid, _ = runtime_at(tmp_path, [
            answer('Viết plan', calls=[write_call()]),
            answer('Xong.'),
            answer('Xong thật rồi.')])
        await asyncio.wait_for(runtime.start(sid, 'Lên plan'), 20)

        extended = notices(store, sid, limits.TURN_EXTENDED_CODE)
        assert [row['reason'] for row in extended] == ['plan_written'], \
            'một lượt chỉ nới MỘT lần, và lần của bước nhắc không còn chỗ khi bước ghi đã dùng nó'
        store.close()

    asyncio.run(run())


def test_the_nudge_would_extend_a_turn_that_still_has_its_extension(tmp_path):
    """Phần nới của bước nhắc là lưới an toàn: nó chạy khi lượt CHƯA dùng lần nới nào.

    Bài này chốt HỢP ĐỒNG CỦA HELPER, không chốt đường nhắc: `extend_turn_budget` là hàm cũ và
    nhận mọi lý do, nên bài vẫn xanh nếu nhánh nhắc biến mất. Đường nhắc thật được chốt ở
    `test_the_turn_deadline_extension_is_recorded_for_the_write` (thứ tự nới của lượt plan).
    """
    store, runtime, sid, _ = runtime_at(tmp_path, [])
    runtime.run_budget[sid] = FakeBudget(1000.0)
    runtime.turn_started_at[sid] = 900.0

    assert runtime.extend_turn_budget(sid, 'plan_verdict_missing') is True
    assert [row['reason'] for row in notices(store, sid, limits.TURN_EXTENDED_CODE)] == \
        ['plan_verdict_missing']
    store.close()


def test_a_turn_without_a_written_plan_is_never_nudged(tmp_path):
    """Lượt thường không bị làm phiền: không có bản kế hoạch nào thì không có gì để phản biện."""

    async def run():
        store, runtime, sid, model = runtime_at(tmp_path, [answer('Xong việc.')])
        await asyncio.wait_for(runtime.start(sid, 'Việc thường'), 20)
        assert notices(store, sid, limits.PLAN_VERDICT_NUDGE_CODE) == []
        assert notices(store, sid, limits.PLAN_VERDICT_MISSING_TURN_CODE) == []
        assert len(model.requests) == 1
        store.close()

    asyncio.run(run())


def test_a_recorded_ok_verdict_closes_only_the_verdict_gate(tmp_path):
    """Phán quyết `ok` đóng cổng PHÁN QUYẾT (không nhắc, không notice) — cổng đọc SỔ, không đếm event.

    Cổng GIẢ ĐỊNH thì vẫn mở: `ok` nói bản kế hoạch đã được phản biện, không nói chủ nhà đã xác nhận
    các giả định nằm trong nó. Gộp hai cổng làm một là chỗ bản trước im lặng sai (soát 2026-09-27).
    """

    async def run():
        store, runtime, sid, model = runtime_at(tmp_path, [answer('Xong việc.')])
        runtime.active_turn[sid] = 1
        runtime.plan_turn_notes[sid] = {'turn': 1, 'identity': 'workspace-plan', 'version': 1,
                                        'assumptions': ['giả định chưa xác nhận']}
        assert runtime.plan_verdict_nudge(sid, 1) is not None

        store.record_plan_verification('workspace-plan', 1, 'ok', summary='đã phản biện')
        assert runtime.plan_verdict_nudge(sid, 1) is None
        runtime.plan_turn_notices(sid, [])
        assert notices(store, sid, limits.PLAN_VERDICT_MISSING_TURN_CODE) == [], \
            'có `ok` thì không còn gì thiếu để nói'
        rows = notices(store, sid, limits.PLAN_ASSUMPTIONS_UNCONFIRMED_CODE)
        assert len(rows) == 1 and rows[0]['items'] == ['giả định chưa xác nhận'], \
            'giả định chưa ai xác nhận vẫn phải được nói ra, kể cả khi đã có `ok`'
        store.close()

    asyncio.run(run())


def test_the_nudge_stands_down_when_the_turn_has_too_little_time_left(tmp_path):
    """Không nhắc khi lượt chỉ còn vài giây: nhắc lúc ấy là biến lượt thành một cú hết giờ."""
    store, runtime, sid, _ = runtime_at(tmp_path, [])
    runtime.active_turn[sid] = 3
    runtime.plan_turn_notes[sid] = {'turn': 3, 'identity': 'workspace-plan', 'version': 2, 'assumptions': []}
    assert runtime.plan_verdict_nudge(sid, 3) is not None

    runtime.turn_seconds_left = lambda _sid: limits.PLAN_VERDICT_NUDGE_MIN_SECONDS - 1
    assert runtime.plan_verdict_nudge(sid, 3) is None
    runtime.turn_seconds_left = lambda _sid: limits.PLAN_VERDICT_NUDGE_MIN_SECONDS
    assert runtime.plan_verdict_nudge(sid, 3) is not None
    runtime.turn_seconds_left = lambda _sid: None
    assert runtime.plan_verdict_nudge(sid, 3) is not None, 'không hỏi được đồng hồ thì không chặn nhắc'
    store.close()


def test_turn_seconds_left_reads_the_live_budget(tmp_path):
    """Đồng hồ của lượt là `when() - bây giờ` (giây CÒN LẠI), không phải độ dài ngân sách."""
    import time as _time

    store, runtime, sid, _ = runtime_at(tmp_path, [])
    assert runtime.turn_seconds_left(sid) is None, 'ngoài lượt thì không có gì để hỏi'

    deadline = _time.monotonic() + limits.PLAN_VERDICT_NUDGE_MIN_SECONDS
    runtime.run_budget[sid] = FakeBudget(deadline)
    left = runtime.turn_seconds_left(sid)
    assert 0 <= left <= limits.PLAN_VERDICT_NUDGE_MIN_SECONDS + 1
    store.close()


def test_the_nudge_leaves_the_wrap_up_window_to_the_diagnosis(tmp_path):
    """Cửa sổ giữ chỗ cuối lượt là của việc CHẨN ĐOÁN: đã chạm `wrap_up_at` thì không nhắc."""
    store, runtime, sid, _ = runtime_at(tmp_path, [])
    runtime.active_turn[sid] = 2
    runtime.plan_turn_notes[sid] = {'turn': 2, 'identity': 'workspace-plan', 'version': 1, 'assumptions': []}

    assert runtime.plan_verdict_nudge(sid, 2, steps_used=9, wrap_up_at=10) is not None
    assert runtime.plan_verdict_nudge(sid, 2, steps_used=10, wrap_up_at=10) is None
    store.close()


def test_a_session_that_cannot_delegate_is_never_nudged(tmp_path):
    """Vai không có `delegate_task` (vai `plan` là một): nhắc nó giao con là nhắc việc nó không làm được."""
    store, runtime, sid, _ = runtime_at(tmp_path, [])
    runtime.active_turn[sid] = 7
    runtime.plan_turn_notes[sid] = {'turn': 7, 'identity': 'workspace-plan', 'version': 1,
                                    'assumptions': []}
    assert runtime.plan_verdict_nudge(sid, 7, can_delegate=False) is None
    assert runtime.plan_verdict_nudge(sid, 7, can_delegate=True) is not None
    store.close()


def test_the_nudge_is_spent_after_one_shot_per_turn(tmp_path):
    """Lượt đã nhắc một lần thì `plan_verdict_nudge` trả `None` — vòng lặp không thể đứng nhắc mãi."""
    store, runtime, sid, _ = runtime_at(tmp_path, [])
    runtime.active_turn[sid] = 4
    runtime.plan_turn_notes[sid] = {'turn': 4, 'identity': 'workspace-plan', 'version': 1, 'assumptions': []}
    runtime.plan_verdict_nudges[sid] = {'turn': 4, 'count': limits.PLAN_VERDICT_NUDGE_MAX}
    assert runtime.plan_verdict_nudge(sid, 4) is None

    runtime.plan_verdict_nudges[sid] = {'turn': 3, 'count': limits.PLAN_VERDICT_NUDGE_MAX}
    assert runtime.plan_verdict_nudge(sid, 4) is not None, 'bộ đếm của lượt CŨ không khoá lượt mới'
    store.close()


# --- F2: giả định chưa xác nhận -----------------------------------------------------------------

def test_a_plan_built_on_unconfirmed_assumptions_is_named_at_turn_end(tmp_path):
    """Plan mang mục giả định mà lượt không hỏi ai ⇒ notice mềm, kèm đúng những mục ấy."""

    async def run():
        store, runtime, sid, _ = runtime_at(tmp_path, [
            answer('Viết plan', calls=[write_call()]),
            answer('Xong, plan đã viết.'),
            answer('Xong thật rồi.')])
        await asyncio.wait_for(runtime.start(sid, 'Làm cái gì đó hay ho'), 20)

        rows = notices(store, sid, limits.PLAN_ASSUMPTIONS_UNCONFIRMED_CODE)
        assert len(rows) == 1
        assert rows[0]['identity'] == 'workspace-plan' and rows[0]['version'] == 1
        assert rows[0]['items'] == plan_quality.assumption_items(PLAN_MARKDOWN)
        assert 'ask_user' in rows[0]['message']
        store.close()

    asyncio.run(run())


def test_asking_the_owner_in_the_same_turn_silences_the_assumption_notice(tmp_path):
    """Đã hỏi (hoặc đã từng hỏi) thì im: notice chỉ nói về những giả định KHÔNG ai xác nhận."""
    store, runtime, sid, _ = runtime_at(tmp_path, [])
    runtime.active_turn[sid] = 5
    runtime.plan_turn_notes[sid] = {'turn': 5, 'identity': 'workspace-plan', 'version': 1,
                                    'assumptions': ['màn hình đích chưa rõ']}

    runtime.plan_turn_notices(sid, [{'id': 'c1', 'name': 'ask_user', 'args': {'question': 'màn hình nào?'}}])
    assert notices(store, sid, limits.PLAN_ASSUMPTIONS_UNCONFIRMED_CODE) == []
    store.close()


def test_the_assumption_notice_is_pinned_once_per_plan_version(tmp_path):
    """Hai lượt cùng nói về một bản kế hoạch thì chủ nhà chỉ đọc notice ấy MỘT lần."""
    store, runtime, sid, _ = runtime_at(tmp_path, [])
    runtime.active_turn[sid] = 6
    runtime.plan_turn_notes[sid] = {'turn': 6, 'identity': 'workspace-plan', 'version': 1,
                                    'assumptions': ['màn hình đích chưa rõ']}

    runtime.plan_turn_notices(sid, [])
    runtime.plan_turn_notices(sid, [])
    assert len(notices(store, sid, limits.PLAN_ASSUMPTIONS_UNCONFIRMED_CODE)) == 1

    runtime.plan_turn_notes[sid] = {'turn': 6, 'identity': 'workspace-plan', 'version': 2,
                                    'assumptions': ['màn hình đích chưa rõ']}
    runtime.plan_turn_notices(sid, [])
    assert len(notices(store, sid, limits.PLAN_ASSUMPTIONS_UNCONFIRMED_CODE)) == 2, \
        'bản kế hoạch KHÁC thì notice phải nói lại'
    store.close()
