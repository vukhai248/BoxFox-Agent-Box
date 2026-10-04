"""Hạn chót của lượt lập kế hoạch + lượt dở không được giả `completed` (vòng 25, D-35).

Vì sao có tệp này: đo vòng 25 cho hai con số rõ ràng — lượt lập kế hoạch cơ bản chết ở **210 s**
trước cả lệnh `write_plan`, và một lượt khác chạy **622 s** nhưng vẫn `partial` trong khi
`sessions.status` nói `completed`. Hai sự thật đó cần hai cơ chế khác nhau:

* hạn chót mặc định 180 → 600 s, trần 600 → 1200 s, hạn chót con 300 → 420 s;
* `extend_turn_budget(sid, reason)` nới **một lần** cho đúng sự kiện `plan_written` (không nới theo
  cảm tính của model), và lượt dở được kể ra bằng event `finish` (`partial: true` + `code`) cùng
  `sessionMetrics.lastTurn` — KHÔNG thêm từ vựng trạng thái nào (bất biến #1: một lượt dở vẫn để
  phiên `completed`).
"""
from __future__ import annotations

import asyncio
import copy
import json

import pytest

from agentbox.agent_core import limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


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
    def __init__(self, result=None):
        self.calls = []
        self.result = result or {'content': 'observed fixture result'}

    async def execute(self, name, args, sid):
        self.calls.append((name, args, sid))
        return dict(self.result)

    async def cleanup(self, sid):
        return None


class FakeBudget:
    """Ngân sách giả: ghi lại `reschedule`, `when()` trả đúng con số được gieo."""

    def __init__(self, when):
        self._when = when
        self.rescheduled = []

    def when(self):
        return self._when

    def reschedule(self, when):
        self.rescheduled.append(when)
        self._when = when


def runtime_at(tmp_path, responses, executor=None):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, executor or FixtureExecutor(), FixtureModel(responses))
    sid = runtime.create({'skills': []})['id']
    return store, runtime, sid


def notices(store, sid, code=None):
    return [event['data'] for event in store.events(sid) if event['type'] == 'notice'
            and (code is None or event['data'].get('code') == code)]


# --- con số cấu hình (một nguồn duy nhất) -------------------------------------------------------

def test_the_deadline_numbers_are_the_measured_ones():
    # #6546 (04/10/2026): chủ nhà chốt nâng trần lên "1k–1k5 bước và 7200 s, tương tự vorflux" —
    # phiên 1000 bước (trần 1500) / 7200 s, con 1000 bước / 7200 s. Số cũ 1800/3600 ghi ở #6457
    # (03/10/2026); trước nữa là 600/1200/900 ở W8.A4.5.N lượt 15 (con `debug` hết bước giữa chừng).
    assert limits.MAX_STEPS_DEFAULT == 1000 and limits.MAX_STEPS_MAX == 1500
    assert limits.DEADLINE_DEFAULT_SECONDS == 7200
    assert limits.DEADLINE_MAX_SECONDS == 7200
    assert limits.CHILD_MAX_STEPS == 1000
    assert limits.CHILD_DEADLINE_SECONDS == 7200
    assert limits.PLAN_TURN_EXTENSION_SECONDS == 420 and limits.PLAN_TURN_EXTENSIONS_MAX == 1
    assert limits.TURN_EXTENDED_CODE == 'TURN_EXTENDED'
    assert limits.DEADLINE_MIN_SECONDS == 5, 'sàn cũ giữ nguyên: nới không được phá nó'


# --- `extend_turn_budget` ----------------------------------------------------------------------

def test_the_budget_is_extended_once_by_the_measured_amount(tmp_path):
    store, runtime, sid = runtime_at(tmp_path, [])
    budget = FakeBudget(1000.0)
    runtime.run_budget[sid] = budget
    runtime.turn_started_at[sid] = 900.0

    assert runtime.extend_turn_budget(sid, 'plan_written') is True
    assert budget.rescheduled == [1420.0], 'nới đúng 420 s'
    rows = notices(store, sid, 'TURN_EXTENDED')
    assert len(rows) == 1
    assert rows[0]['code'] == 'TURN_EXTENDED' and rows[0]['seconds'] == 420.0
    assert rows[0]['reason'] == 'plan_written' and rows[0]['extensions'] == 1
    assert rows[0]['partial'] is False, 'nới hạn chót không phải một lượt dở'
    assert str(rows[0]['message']).startswith('TURN_EXTENDED: +420s')
    store.close()


def test_the_second_extension_in_a_turn_is_a_no_op(tmp_path):
    store, runtime, sid = runtime_at(tmp_path, [])
    budget = FakeBudget(1000.0)
    runtime.run_budget[sid] = budget
    runtime.turn_started_at[sid] = 900.0

    assert runtime.extend_turn_budget(sid, 'plan_written') is True
    assert runtime.extend_turn_budget(sid, 'plan_written') is False, 'một lượt chỉ được nới một lần'
    assert budget.rescheduled == [1420.0]
    assert len(notices(store, sid, 'TURN_EXTENDED')) == 1
    store.close()


def test_a_paused_budget_is_not_counted_as_an_extension(tmp_path):
    """Đang chờ người trả lời (`when()` là `None`): bỏ qua, và **không** tính là đã nới."""
    store, runtime, sid = runtime_at(tmp_path, [])
    budget = FakeBudget(None)
    runtime.run_budget[sid] = budget
    runtime.turn_started_at[sid] = 900.0

    assert runtime.extend_turn_budget(sid, 'plan_written') is False
    assert budget.rescheduled == []
    assert notices(store, sid, 'TURN_EXTENDED') == []
    budget._when = 1000.0
    assert runtime.extend_turn_budget(sid, 'plan_written') is True, 'lượt chưa nới lần nào thì còn lượt'
    store.close()


def test_the_extension_never_crosses_the_turn_ceiling(tmp_path):
    """Chạm trần `DEADLINE_MAX_SECONDS` của cả lượt thì `seconds` bị cắt, không cộng thêm 420."""
    store, runtime, sid = runtime_at(tmp_path, [])
    started = 5000.0
    budget = FakeBudget(started + limits.DEADLINE_MAX_SECONDS - 30)
    runtime.run_budget[sid] = budget
    runtime.turn_started_at[sid] = started

    assert runtime.extend_turn_budget(sid, 'plan_written') is True
    assert budget.rescheduled == [started + limits.DEADLINE_MAX_SECONDS]
    assert notices(store, sid, 'TURN_EXTENDED')[0]['seconds'] == 30.0
    store.close()


def test_a_closed_budget_is_left_alone(tmp_path):
    store, runtime, sid = runtime_at(tmp_path, [])
    assert runtime.extend_turn_budget(sid, 'plan_written') is False, 'không có ngân sách thì không nới'

    class Closed:
        def when(self):
            return 10.0

        def reschedule(self, when):
            raise RuntimeError('already closed')

    runtime.run_budget[sid] = Closed()
    runtime.turn_started_at[sid] = 0.0
    assert runtime.extend_turn_budget(sid, 'plan_written') is False
    assert notices(store, sid, 'TURN_EXTENDED') == []
    store.close()


def test_the_extension_is_logged_for_the_developer(tmp_path, monkeypatch):
    written = []
    monkeypatch.setattr('agentbox.agent_core.runtime.system_log.write',
                        lambda event, **fields: written.append((event, fields)))
    store, runtime, sid = runtime_at(tmp_path, [])
    budget = FakeBudget(1000.0)
    runtime.run_budget[sid] = budget
    runtime.turn_started_at[sid] = 900.0

    assert runtime.extend_turn_budget(sid, 'plan_written') is True
    event, fields = written[-1]
    assert event == 'turn.extend' and fields['code'] == 'TURN_EXTENDED'
    assert fields['reason'] == 'plan_written' and fields['extensions'] == 1
    assert fields['session_id'] == sid and fields['seconds'] == 420.0
    store.close()


# --- lượt dở được kể ra -------------------------------------------------------------------------

def test_a_partial_turn_is_told_apart_from_a_finished_one(tmp_path):
    """Hai lượt thật: một lượt trọn vẹn, rồi một lượt bị cắt ở trần độ dài — `lastTurn` phân biệt được.

    Lượt dở ở đây là lượt **thật** (câu trả lời 200 000 ký tự qua cổng D2), không phải một lời gọi
    hàm dựng sẵn: điều cần chứng minh là cờ `partial` sống sót tới `sessionMetrics`.
    """

    async def run():
        store, runtime, sid = runtime_at(tmp_path, [answer('Xong việc.'), answer('b' * 200_000)])
        assert await asyncio.wait_for(runtime.start(sid, 'Việc thường'), 10) == 'Xong việc.'
        first = runtime.session_metrics(sid)['lastTurn']
        assert first['partial'] is False and first['status'] == 'completed' and first['code'] is None
        finish = [event['data'] for event in store.events(sid) if event['type'] == 'finish']
        assert finish[0].get('partial') in (None, False), 'lượt thường không mang cờ dở'

        await asyncio.wait_for(runtime.start(sid, 'Việc dài'), 20)
        latest = runtime.session_metrics(sid)['lastTurn']
        assert latest['turn'] == 2
        assert latest['partial'] is True and latest['code'] == limits.ANSWER_TOO_LONG_CODE
        assert latest['status'] == 'partial'
        assert store.get(sid)['status'] == 'completed', 'bất biến #1: một lượt dở vẫn để phiên completed'
        last_finish = [event['data'] for event in store.events(sid) if event['type'] == 'finish'][-1]
        assert last_finish['partial'] is True and last_finish['code'] == limits.ANSWER_TOO_LONG_CODE
        store.close()

    asyncio.run(run())


def test_the_partial_turn_is_closed_in_the_contract_order(tmp_path):
    """Thứ tự chốt lượt dở không đổi: notice bền mang mã lý do → `turn_end` (partial) → `finish`.

    Notice là bản DUY NHẤT sống qua `store.save` của lượt sau (`partial_turn` đọc chính nó), nên nó
    đi trước; `finish` là hàng đóng lượt và luôn là hàng cuối — và từ vòng 25 nó mang `partial` +
    `code`, đúng như `turn_end` đã nói.
    """

    async def run():
        store, runtime, sid = runtime_at(tmp_path, [answer('c' * 200_000)])
        await asyncio.wait_for(runtime.start(sid, 'Việc dài'), 20)
        events = store.events(sid)
        kinds = [event['type'] for event in events]
        end = kinds.index('turn_end')
        assert events[end]['data']['status'] == 'partial'
        assert kinds[end + 1] == 'finish', 'finish là hàng đóng lượt, ngay sau turn_end'
        assert kinds.count('finish') == 1
        assert notices(store, sid, limits.ANSWER_TOO_LONG_CODE)[0]['partial'] is True
        assert kinds.index('notice') < end, 'notice bền đã ở trong luồng trước khi lượt đóng'
        store.close()

    asyncio.run(run())
