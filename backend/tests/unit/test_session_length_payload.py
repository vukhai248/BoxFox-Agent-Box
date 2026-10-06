"""N10 — payload phiên phải mang theo SỐ ĐO ĐỘ DÀI, không chỉ hàng đã lưu.

`GET /api/agent/sessions/{sid}` trả nguyên hàng `sessions` (trừ `messages`) cộng `events`.
Đo sống 2026-09-21: 150 phiên, trung vị 7 message / 17 942 B, mà muốn biết phiên nào dài
thì phải tải cả transcript — trong khi 10 phiên lớn nhất (> 921 600 B) đều `failed`.
`runtime.session_metrics(sid)` gom bốn con số đó vào một chỗ; `api/server.py` chỉ cần một
dòng `| runtime.session_metrics(sid)` là payload có chúng (bản này kiểm luôn phép ghép đó).
"""
import asyncio
import copy
import json

from agentbox.agent_core.compression import estimate_tokens
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.agent_core.tool_contracts import schemas_for
from agentbox.memory.session_store import SessionStore
import pytest


# Đường TRƯỚC v2 (#6599): file này chốt hành vi cũ; khóa tổng `BOXFOX_REFORM` đã bị xoá ở bước B5
# (HANDOFF §10.3) nên nhãn `legacy_path` không còn kèm env nào để pin.
pytestmark = pytest.mark.legacy_path


# B7 (vòng 22) thêm `stepsClamped` — đối xứng với `deadlineClamped` của C1: một `maxSteps`
# bị kẹp cũng phải nói ra, không im lặng như trước.
METRIC_KEYS = {'messageCount', 'contextEstimate', 'compressionCount', 'deadlineClamped', 'stepsClamped'}
# T13 (vòng 22) thêm khối `peers` + cờ `peerMesh` vào CÙNG payload: đó là chỗ duy nhất trả lời
# được "mesh tốn thêm bao nhiêu" mà không phải mở SQLite bằng tay.
PEER_METRIC_KEYS = {'peerMesh', 'peers'}
# Vòng 25 (M8): `lastTurn` là TRẠNG THÁI lượt cuối (tab Plan đọc `status`/`partial` để biết lượt
# trước có bị đứt không), không phải một con đếm — nên là khoá riêng, có hình dạng riêng.
TURN_METRIC_KEYS = {'lastTurn'}


def answer(text='done', calls=None, finish='stop'):
    return {'choices': [{'message': {'content': text, **({'tool_calls': calls} if calls else {})},
                         'finish_reason': 'tool_calls' if calls else finish}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}


def call(name, args, cid='c1'):
    return {'id': cid, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(args)}}


class FixtureModel:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        return next(self.responses)


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def run_turn(tmp_path, values=None):
    store = SessionStore(tmp_path / 'sessions.db')
    client = FixtureModel([answer(calls=[call('file_read', {'path': 'notes.txt'})]), answer('xong')])
    runtime = HarnessRuntime(store, FixtureExecutor(), client)
    session = runtime.create(values or {'skills': [], 'connectionId': 'c1',
                                        'modelId': 'deepseek-v4-flash', 'contextWindow': 32768})

    async def run():
        await runtime.submit(session['id'], 'làm việc')
        await runtime.tasks[session['id']]

    asyncio.run(run())
    return store, runtime, session


def test_session_metrics_match_the_stored_transcript(tmp_path):
    store, runtime, session = run_turn(tmp_path)
    sid = session['id']
    metrics = runtime.session_metrics(sid)

    assert set(metrics) == METRIC_KEYS | PEER_METRIC_KEYS | TURN_METRIC_KEYS
    stored = store.get(sid)
    # Đủ mặt: system + user + assistant(xin tool) + kết quả tool + assistant(câu trả lời).
    assert metrics['messageCount'] == len(stored['messages']) == 5
    assert metrics['contextEstimate'] == estimate_tokens(stored['messages'],
                                                        schemas_for(stored['config']['tools']))
    # Bề mặt 7 đã xoá: hồ sơ LƯỢT của main gỡ các công cụ research nội bộ khỏi bộ tool
    # (`research_gateway.apply_profile`), nên `turn_end` đo trên bộ ĐÃ LỌC còn `session_metrics`
    # đọc `config.tools` đã lưu — hai con số khác nhau có chủ ý, mỗi con đúng với bộ tool của nó.
    last_end = [e['data'] for e in store.events(sid) if e['type'] == 'turn_end'][-1]
    assert last_end['contextEstimate'] == estimate_tokens(
        stored['messages'], schemas_for(runtime.turn_profile(stored)['tools']))
    assert last_end['contextEstimate'] < metrics['contextEstimate'], \
        'main không còn giữ công cụ research nội bộ trong hồ sơ lượt ⇒ ước lượng của lượt nhỏ hơn'
    assert metrics['contextEstimate'] > 0
    assert metrics['compressionCount'] == 0
    assert metrics['deadlineClamped'] is False
    assert json.loads(json.dumps(metrics)) == metrics, 'phải gửi được qua JSON'
    store.close()


def test_compression_count_comes_from_the_event_stream(tmp_path):
    store, runtime, session = run_turn(tmp_path)
    sid = session['id']
    # Đúng hình dạng `ContextCompressor.compact` phát ra (compression.py:595).
    store.emit(sid, 'compression', {'kind': 'summary', 'beforeEstimate': 20070, 'afterEstimate': 4100})
    assert runtime.session_metrics(sid)['compressionCount'] == 1
    store.emit(sid, 'compression', {'kind': 'tail', 'beforeEstimate': 21000, 'afterEstimate': 6000})
    # Hàng khác kind không được đếm; checkpoint cũng không (đo sống: 22 checkpoint / 12 phiên).
    store.emit(sid, 'notice', {'code': 'PROVIDER_OUTPUT_TRUNCATED'})
    store.emit(sid, 'step', {'iteration': 3})
    assert runtime.session_metrics(sid)['compressionCount'] == 2
    assert runtime.session_metrics(sid)['messageCount'] == 5, 'event không làm dài transcript'
    store.close()


def test_deadline_clamp_flag_is_visible_in_the_session_payload(tmp_path):
    store, runtime, session = run_turn(tmp_path)
    assert runtime.session_metrics(session['id'])['deadlineClamped'] is False

    store2 = SessionStore(tmp_path / 'sessions2.db')
    runtime2 = HarnessRuntime(store2, FixtureExecutor(), FixtureModel([answer('xong')]))
    # #6457 nâng trần lên 7200 s ⇒ con số "quá trần" phải lớn hơn trần MỚI (không phải 1500 cũ).
    clamped = runtime2.create({'skills': [], 'connectionId': 'c1', 'deadlineSeconds': 9000})
    assert clamped['config']['deadlineClamped'] is True, 'config đã nằm trong payload GET'
    assert runtime2.session_metrics(clamped['id'])['deadlineClamped'] is True
    store.close()
    store2.close()


def test_server_can_surface_the_metrics_with_a_one_line_merge(tmp_path):
    """Phép ghép mà `api/server.py:session()` cần thêm — vài khoá cộng thêm, không ghi đè."""
    store, runtime, session = run_turn(tmp_path)
    sid = session['id']
    value = store.get(sid)
    payload = {k: v for k, v in copy.deepcopy(value).items() if k != 'messages'}
    events = store.events(sid, 0)
    merged = payload | runtime.session_metrics(sid) | {'events': events}

    assert METRIC_KEYS <= set(merged)
    assert 'messages' not in merged and merged['id'] == sid
    assert merged['events'] == events, 'events vẫn là bản ghi đầy đủ như trước'
    assert all(k in merged for k in ('id', 'role', 'status', 'config', 'updated', 'parent_id'))
    assert set(value) - {'messages'} <= set(merged), 'không mất khoá cũ nào'
    assert json.loads(json.dumps(merged))['messageCount'] == 5
    store.close()


def test_the_route_serves_the_metrics_and_never_the_transcript(tmp_path):
    """Bài này gọi ROUTE THẬT (aiohttp), không chỉ phép ghép: tab nào cũng thấy số đo.

    Phép ghép ở bài trên có thể đúng mà `api/server.py` vẫn quên nối — dạng lỗi đã xảy ra hai lần
    trong đợt này (hàm có sẵn, chỗ gọi chưa có). Nên bài này chỉ tin vào `GET` thật.
    """
    from aiohttp import ClientSession
    from aiohttp.test_utils import TestServer

    from agentbox.api.server import create_app

    store, runtime, session = run_turn(tmp_path)
    sid = session['id']

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                async with client.get(
                        f'/api/agent/sessions/{sid}',
                        headers={'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}) as response:
                    assert response.status == 200
                    return await response.json()

    payload = asyncio.run(run())
    assert METRIC_KEYS | TURN_METRIC_KEYS <= set(payload['sessionMetrics'])
    metrics = dict(payload['sessionMetrics'])
    last_turn = metrics.pop('lastTurn')          # có `at` là đồng hồ, nên so riêng phần ổn định
    assert set(last_turn) == {'turn', 'status', 'partial', 'code', 'at'}
    assert (last_turn['turn'], last_turn['status'], last_turn['partial']) == (1, 'completed', False)
    assert isinstance(last_turn['at'], (int, float)) and last_turn['at'] > 0
    assert metrics == {'messageCount': 5, 'contextEstimate': payload['sessionMetrics']['contextEstimate'],
                                         'compressionCount': 0, 'deadlineClamped': False, 'stepsClamped': False,
                                         'peerMesh': True,
                                         'peers': {'spawned': 0, 'running': 0, 'completed': 0, 'partial': 0,
                                                   'failed': 0, 'childSteps': 0, 'childTokens': 0,
                                                   'childAnswerChars': 0, 'deliveries': 0, 'waitedMs': 0}}
    assert 'messages' not in payload, 'transcript vẫn không được gửi kèm mỗi lần hỏi'
    assert payload['id'] == sid and payload['events'], 'events vẫn là bản ghi đầy đủ như trước'
