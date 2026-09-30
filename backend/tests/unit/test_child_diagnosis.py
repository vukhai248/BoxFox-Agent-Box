"""B10 — con chạm trần trả CHẨN ĐOÁN, và chẩn đoán đó về tới cha (yêu cầu mới của chủ nhà).

Đo sống vòng 21 (BUG-42): con `ea948649…` chạy 10/10 bước, 33 lời gọi tool, 120 s, rồi kết
thúc `DEADLINE` với `answerChars = 0` — cha nhận một dòng `failed` trắng và mất toàn bộ việc
con đã làm. Hợp đồng mới: con chạm trần bước **hoặc** hạn chót phải tự đọc lại trạng thái rồi
trả bốn phần (đã làm / tắc ở đâu / còn lại / thử gì tiếp); cha nhận `status='partial'`,
`reason=<mã>`, `diagnosis: True`, `answerChars > 0`, `is_error: False`.
"""
import asyncio
import copy
import json

from agentbox.agent_core.limits import DEADLINE_NOTICE_CODE, STEP_BUDGET_NOTICE_CODE
from agentbox.agent_core.runtime import DIAGNOSIS_PARTS, DIAGNOSIS_PROMPT, HarnessRuntime
from agentbox.memory.session_store import SessionStore

CHILD_DIAGNOSIS = ('Đã làm: đọc hai tệp nguồn và ghi lại các symbol chính. Tắc ở đâu: tệp thứ ba '
                   'cần quyền đọc mà lệnh bị từ chối. Còn lại: chưa đối chiếu call site nào. '
                   'Thử gì tiếp: đọc tệp bằng `file_read` thay vì `terminal_exec` rồi chạy lại.')


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
        self.requests.append({'messages': copy.deepcopy(messages), 'tools': copy.deepcopy(tools),
                              'route': copy.deepcopy(route), 'max_tokens': max_tokens})
        item = next(self.responses)
        if isinstance(item, BaseException):
            raise item
        return item


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def run_parent_turn(tmp_path, client, values=None):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash',
                              **(values or {})})

    async def run():
        await runtime.submit(session['id'], 'nhờ chuyên gia đọc ba tệp')
        await runtime.tasks[session['id']]

    asyncio.run(run())
    return store, runtime, session


def child_result(store, sid):
    rows = [e['data'] for e in store.events(sid) if e['type'] == 'child']
    assert len(rows) == 2, 'một event mở + một event kết quả'
    return rows[-1]


DELEGATE = answer(calls=[call('delegate_task', {'role': 'explore', 'goal': 'đọc ba tệp trong workspace'})])


def test_budget_exhausted_child_returns_diagnosis(tmp_path):
    """(a) con hết bước ⇒ TRƯỚC ĐÂY `failed`/`answerChars = 0`; BÂY GIỜ `partial` + chẩn đoán."""
    client = FixtureModel([DELEGATE,
                           answer(calls=[call('file_read', {'path': 'a', 'path2': 'b'})]),
                           answer(calls=[call('file_write', {'path': 'notes.md', 'content': 'x'})]),
                           answer(CHILD_DIAGNOSIS),
                           answer('câu trả lời cuối của cha')])
    store, _runtime, session = run_parent_turn(tmp_path, client, values={'maxSteps': 3})
    child = child_result(store, session['id'])

    assert child['status'] == 'partial', 'con chạm trần không còn là `failed` trắng'
    assert child['reason'] == STEP_BUDGET_NOTICE_CODE
    assert child['diagnosis'] is True and child['stuckReason'] == STEP_BUDGET_NOTICE_CODE
    assert child['answerChars'] > 0 and CHILD_DIAGNOSIS in child['summary']
    assert child['summary'] == CHILD_DIAGNOSIS, 'chẩn đoán do model viết giữ nguyên, không thêm metadata'
    assert child['is_error'] is False, 'chẩn đoán là kết quả DÙNG ĐƯỢC, không phải lỗi'
    # Bốn phần, đúng bốn nhãn mà câu chỉ dẫn yêu cầu (câu chỉ dẫn nói tiếng Anh, câu trả lời
    # của con theo tiếng của phiên — cùng bốn phần, không phải cùng ngôn ngữ).
    for label in ('Đã làm', 'Tắc ở đâu', 'Còn lại', 'Thử gì tiếp'):
        assert label in CHILD_DIAGNOSIS, 'bốn phần là hợp đồng của câu chốt'
    assert DIAGNOSIS_PROMPT.count(' / ') == DIAGNOSIS_PARTS.count(' / '), \
        'nhãn trong prompt và nhãn test đọc là CÙNG một hằng số'
    child_row = store.get(child['sessionId'])
    assert child_row['status'] == 'completed', 'bất biến #1: hàng `sessions` của con không đổi'
    ends = [e['data'] for e in store.events(child['sessionId']) if e['type'] == 'turn_end']
    assert ends[-1]['status'] == 'partial' and ends[-1]['stepsUsed'] == 3
    store.close()


def test_deadline_hitting_child_returns_diagnosis(tmp_path):
    """(c) con chạm HẠN CHÓT ⇒ cùng hợp đồng, mã lý do khác."""
    client = FixtureModel([DELEGATE,
                           answer(calls=[call('file_read', {'path': 'a'})]),
                           asyncio.TimeoutError(),
                           answer(CHILD_DIAGNOSIS),
                           answer('câu trả lời cuối của cha')])
    store, _runtime, session = run_parent_turn(tmp_path, client, values={'maxSteps': 6})
    child = child_result(store, session['id'])

    assert child['status'] == 'partial'
    assert child['reason'] == DEADLINE_NOTICE_CODE, 'cha phân biệt được hai ca'
    assert child['diagnosis'] is True and child['stuckReason'] == DEADLINE_NOTICE_CODE
    assert child['answerChars'] > 0 and child['is_error'] is False
    store.close()


def test_a_really_failing_child_stays_failed(tmp_path):
    """(b) lượt chốt của con cũng hỏng ⇒ không nuốt lỗi thật, vẫn `failed` như cũ."""
    client = FixtureModel([DELEGATE,
                           answer(calls=[call('file_read', {'path': 'a'})]),
                           asyncio.TimeoutError(),
                           asyncio.TimeoutError(),
                           answer('câu trả lời cuối của cha')])
    store, _runtime, session = run_parent_turn(tmp_path, client, values={'maxSteps': 6})
    child = child_result(store, session['id'])

    assert child['status'] == 'failed'
    assert child['is_error'] is True and child['answerChars'] == 0
    assert child['summary'] == '', 'lỗi thật chỉ ở metadata; không tạo báo cáo diagnostic giả'
    assert 'diagnosis' not in child
    store.close()
