"""Ranh giới LƯỢT trong dòng event của harness (N6) + event sửa cửa sổ (N2).

Đo sống 2026-09-21 trên `~/BoxFox/harness/sessions.sqlite`: `turn_start`/`turn_end`
= 0 trên 74 994 hàng `events`. Muốn biết một lượt có mấy bước, mỗi bước dài bao
nhiêu, ngưỡng nén lúc đó là bao nhiêu, thì phải suy từ `user`/`finish` — tức là
không biết. Bản này phát đúng MỘT cặp `turn_start`/`turn_end` cho mỗi bước, trên
mọi đường ra (xong, hỏng, bị dừng), và giữ nguyên mọi kind/payload cũ.

Ngưỡng trong `turn_start` phải là con số của CHÍNH bộ nén (`ContextCompressor`) —
lấy từ bộ đệm `runtime.compressors[sid]`, không chép lại công thức ở tầng event.
"""
import asyncio
import copy
import json

import pytest

from agentbox.agent_core.compression import ContextCompressor
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore


def answer(text='done', calls=None, finish='stop', usage=None):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': usage if usage is not None else {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.requests.append(copy.deepcopy((messages, tools, route)))
        return next(self.responses)


class BoomModel:
    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        raise RuntimeError('upstream socket closed')


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def drive(tmp_path, client, values=None, prompt='làm việc'):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create(values or {'skills': [], 'connectionId': 'c1',
                                        'modelId': 'deepseek-v4-flash', 'contextWindow': 32768})

    async def run():
        await runtime.submit(session['id'], prompt)
        await runtime.tasks[session['id']]

    asyncio.run(run())
    return store, runtime, session


def turn_events(store, sid):
    events = store.events(sid)
    return ([e['data'] for e in events if e['type'] == 'turn_start'],
            [e['data'] for e in events if e['type'] == 'turn_end'], events)


# --------------------------------------------------------------------------- #
# N6 — mỗi bước một cặp turn_start / turn_end
# --------------------------------------------------------------------------- #

def test_every_step_opens_and_closes_a_turn(tmp_path):
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'notes.txt'})]), answer('xong')])
    store, _runtime, session = drive(tmp_path, client)
    starts, ends, _events = turn_events(store, session['id'])

    assert [t['step'] for t in starts] == [1, 2], 'hai bước → hai lần mở'
    assert [t['step'] for t in ends] == [1, 2], 'và đúng hai lần đóng, cùng số bước'
    # T2 (vòng 22): payload mở bước mang thêm `turn` — số LƯỢT của phiên, khác `step`.
    assert set(starts[0]) == {'turn', 'step', 'modelId', 'contextWindow', 'threshold',
                              'contextEstimate'}
    assert [t['turn'] for t in starts] == [1, 1], 'cả hai bước của lượt 1 mang turn=1'
    # `outputTokens` chỉ xuất hiện khi usage có con số thật, nên khoá này là tuỳ chọn.
    # B9 (vòng 22): `turn_end` mang thêm ba số luỹ kế của cả lượt — `stepsUsed`, `toolsRun`,
    # `deadlineUsedMs`. Chúng có mặt ở MỌI lần đóng (mỗi bước một lần), nên lần đóng CUỐI là
    # con số của cả lượt.
    assert set(ends[0]) == {'turn', 'step', 'status', 'finishReason', 'toolCalls', 'contextEstimate',
                            'outputTokens', 'stepsUsed', 'toolsRun', 'deadlineUsedMs',
                            'completionAttempts', 'completionUsageComplete'}
    assert ends[0]['completionAttempts'] == 1 and ends[0]['completionUsageComplete'] is True
    assert [t['turn'] for t in ends] == [1, 1] and [t['step'] for t in ends] == [1, 2], \
        '`turn` là lượt (1), `step` là bước trong lượt (1 rồi 2)'
    assert starts[0]['modelId'] == 'deepseek-v4-flash'
    assert starts[0]['contextWindow'] == 32768
    assert ends[0]['status'] == 'tool_calls' and ends[0]['toolCalls'] == 1
    assert ends[0]['finishReason'] == 'tool_calls'
    assert ends[1]['status'] == 'completed' and ends[1]['toolCalls'] == 0
    assert ends[1]['finishReason'] == 'stop'
    assert ends[1]['outputTokens'] == 2
    assert ends[0]['contextEstimate'] > 0 and ends[1]['contextEstimate'] > 0
    store.close()


def test_turn_start_carries_the_compressors_own_threshold(tmp_path):
    """Ngưỡng phải khớp con số bộ nén đang chạy — bảng đo sống 2026-09-21."""
    client = FixtureModel([answer('xong')])
    store, runtime, session = drive(tmp_path, client)
    starts, _ends, _events = turn_events(store, session['id'])

    assert starts[0]['threshold'] == ContextCompressor(32768).threshold == 20070
    assert runtime.compressors[session['id']].threshold == starts[0]['threshold']
    store.close()

    # Cửa sổ 1M: 70 % của (cửa sổ trừ phần dành cho câu trả lời) không bao giờ chạm tới, vì
    # router từ chối body quá lớn — nên con số ở đây là trần của bộ nén, không phải 697k.
    client = FixtureModel([answer('xong')])
    store, _runtime, session = drive(tmp_path, client, {'skills': [], 'connectionId': 'c1',
                                                        'modelId': 'deepseek-flash',
                                                        'contextWindow': 1000000})
    starts, _ends, _events = turn_events(store, session['id'])
    assert starts[0]['threshold'] == ContextCompressor(1000000).threshold
    assert starts[0]['threshold'] < 1000000 * 0.7, 'trần thật chặn trước ngưỡng phần trăm'
    store.close()


def test_turn_ends_exactly_once_when_the_step_fails(tmp_path):
    store, _runtime, session = drive(tmp_path, BoomModel(), prompt='hỏng')
    starts, ends, events = turn_events(store, session['id'])

    assert [t['step'] for t in starts] == [1]
    assert [t['step'] for t in ends] == [1], 'lượt hỏng vẫn phải đóng, đúng một lần'
    assert ends[0]['status'] == 'error'
    assert store.get(session['id'])['status'] == 'failed'
    assert 'turn_start' not in [e['type'] for e in events[-1:]], 'event cuối vẫn là `error` như cũ'
    store.close()


def test_compaction_still_emits_every_event_kind_it_used_to(tmp_path):
    """Không kind nào bị mất hay đổi tên khi thêm ranh giới lượt."""
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'notes.txt'})]),
                           answer('xong', usage={'prompt_tokens': 10, 'completion_tokens': 2})])
    store, _runtime, session = drive(tmp_path, client)
    kinds = [e['type'] for e in store.events(session['id'])]
    for kind in ('user', 'step', 'usage', 'assistant', 'tool_start', 'tool_end', 'finish',
                 'turn_start', 'turn_end'):
        assert kind in kinds, f'{kind} phải còn trong dòng event'
    assert kinds[-1] == 'finish'
    store.close()


# --------------------------------------------------------------------------- #
# N2 — event của lượt sửa cửa sổ
# --------------------------------------------------------------------------- #

def test_context_window_healed_event_has_a_stable_shape(tmp_path):
    class FixtureRouterClient:
        async def model_metadata_map(self):
            return {('c1', 'deepseek-v4-flash'): {'id': 'deepseek-v4-flash', 'contextWindow': 1048576,
                                                 'contextWindowSource': 'documented'}}

    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash',
                              'contextWindow': 32768, 'contextWindowSource': 'manual'})
    assert asyncio.run(runtime.heal_context_windows()) == 1

    healed = [e for e in store.events(session['id']) if e['type'] == 'context_window_healed']
    assert len(healed) == 1
    payload = healed[0]['data']
    assert payload == {'from': 32768, 'to': 1048576, 'modelId': 'deepseek-v4-flash',
                       'source': 'router'}
    assert all(isinstance(value, (int, str)) for value in payload.values())
    store.close()
