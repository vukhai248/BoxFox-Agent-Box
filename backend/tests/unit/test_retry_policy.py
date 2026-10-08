"""Chính sách thử lại: phân loại, thời gian chờ, ngân sách và thông báo cho UI.

Trước bản này, cả harness chỉ có đúng MỘT lần thử lại với `asyncio.sleep(1.5)` và điều
kiện `is_transient` — mà `is_transient` trả `False` cho HTTP 429, nên một lần nhà cung
cấp yêu cầu chậm lại là lượt chết ngay lập tức (đúng ca Gemini 429 / DeepSeek Pro).
Bản này kiểm tra bốn thứ: 429 có được thử lại không, chờ bao lâu, khi nào dừng, và lượt
kết thúc có nói rõ đã thử lại mấy lần.
"""
import asyncio
import random

import pytest

from agentbox.agent_core.failures import (DEFAULT_MAX_RETRIES, RETRY_BUDGET_SECONDS,
                                          is_transient, level_refusal, retry_advice, stop_reason)
from agentbox.agent_core.runtime import HarnessRuntime, router_refusal
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.worker import SESSION_OP_NAMES


class ServerDisconnectedError(Exception):
    """Tên lớp giống aiohttp; `str()` rỗng là ca `Agent run failed` cũ."""


class FailingModel:
    """Client giả: ném lỗi theo kịch bản, rồi trả lời được."""

    def __init__(self, failures=(), then='xong'):
        self.failures = list(failures)
        self.then = then
        self.calls = 0

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return {'choices': [{'message': {'content': self.then}, 'finish_reason': 'stop'}], 'usage': None}


class StubExecutor:
    async def execute(self, name, args, sid):
        if name in SESSION_OP_NAMES:
            # Op nhật ký của box (A1/A7) trả `{ok, …}` như worker thật: thiếu `ok` thì
            # `session_journal._safe` coi là CHƯA ghi được và ghim `JOURNAL_DEGRADED`.
            return {'ok': True}
        return {'content': 'fixture'}

    async def cleanup(self, sid):
        return None


def _runtime(tmp_path, client):
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, StubExecutor(), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1', 'deadlineSeconds': 600})
    return store, runtime, session


def _rate_limit(retry_after_ms=None, message='Provider rate limit or quota reached. Try again later.'):
    """Lỗi đúng như `router_refusal` dựng từ envelope của router."""
    refusal = router_refusal(429, __import__('json').dumps(
        {'error': {'code': 'RATE_LIMIT', 'message': message, 'retryable': True,
                   **({'retryAfterMs': retry_after_ms} if retry_after_ms else {})}}).encode())
    return refusal


def _run(tmp_path, failures, monkeypatch=None):
    """Chạy một lượt thật, trả `(client, events, session)`."""
    client = FailingModel(failures)
    store, runtime, session = _runtime(tmp_path, client)
    asyncio.run(_drive(runtime, store, session))
    events = store.events(session['id'])
    status = store.get(session['id'])['status']
    store.close()
    return client, events, status


async def _drive(runtime, store, session, monkeypatch=None):
    await runtime.submit(session['id'], 'hỏi')
    await runtime.tasks[session['id']]


def _notices(events):
    return [event['data'] for event in events if event['type'] == 'notice']


# --------------------------------------------------------------------------- #
# Phân loại và thời gian chờ
# --------------------------------------------------------------------------- #

def test_rate_limit_is_retryable_and_honours_retry_after():
    advice = retry_advice(_rate_limit(retry_after_ms=9000), 0, remaining_seconds=300, rng=random.Random(1))
    assert advice['reason'] == 'rate-limit'
    assert advice['delay'] == 9.0, 'Retry-After của router phải được tôn trọng'
    assert advice['code'] == 'UPSTREAM_HTTP_429'
    assert advice['attempt'] == 1 and advice['maxRetries'] == DEFAULT_MAX_RETRIES


def test_rate_limit_without_retry_after_waits_a_floor_not_zero():
    advice = retry_advice(_rate_limit(), 0, remaining_seconds=300, rng=random.Random(1))
    assert advice['delay'] >= 2.0


def test_rate_limit_wait_is_clamped_to_thirty_seconds():
    advice = retry_advice(_rate_limit(retry_after_ms=600_000), 0, remaining_seconds=900, rng=random.Random(1))
    assert advice['delay'] == 30.0, 'một lượt không được ngồi chờ 10 phút vì cooldown của router'


def test_five_hundred_backs_off_exponentially_with_jitter():
    class Boom(RuntimeError):
        pass

    first = retry_advice(Boom('Router HTTP 503: down'), 0, remaining_seconds=300, rng=random.Random(1))
    second = retry_advice(Boom('Router HTTP 503: down'), 1, remaining_seconds=300, rng=random.Random(1))
    assert first['reason'] == 'upstream' and second['reason'] == 'upstream'
    assert second['delay'] > first['delay']
    assert 0.8 * 4.0 <= second['delay'] <= 1.2 * 4.0, 'giây thứ hai lấy backoff 4 s ± jitter'


def test_rejected_request_never_retries():
    assert retry_advice(RuntimeError('Router HTTP 400: bad request'), 0, remaining_seconds=300) is None
    assert retry_advice(RuntimeError('Router HTTP 404: unknown model'), 0, remaining_seconds=300) is None
    assert retry_advice(PermissionError('nope'), 0, remaining_seconds=300) is None


def test_spent_deadline_never_retries():
    """Provider chậm đã tiêu hết cửa sổ: gọi lại bắt đầu từ số 0, chỉ tốn thời gian.

    `TimeoutError` là hạn của chính lượt, `UPSTREAM_TIMEOUT` là mã của harness, và
    `ReadTimeout` của httpx là "nhà cung cấp không trả lời kịp" — cùng một kết luận:
    gửi lại chỉ khởi động lại đồng hồ. Ca này khẳng định đúng nhánh đó, thay vì để
    mọi lớp ngoại lệ rơi vào nhánh mặc định rồi kết luận là đã kiểm.
    """
    assert retry_advice(TimeoutError(), 0, remaining_seconds=300) is None
    assert retry_advice(RuntimeError('UPSTREAM_TIMEOUT: the model provider did not answer in time'), 0, remaining_seconds=300) is None

    class ReadTimeout(Exception):
        """Hình dạng của `httpx.ReadTimeout`: tên kết thúc bằng `Timeout`, không phải `TimeoutError`."""

    ReadTimeout.__name__ = 'ReadTimeout'
    assert retry_advice(ReadTimeout('read timed out'), 0, remaining_seconds=300) is None
    assert stop_reason(ReadTimeout('read timed out'), 0, remaining_seconds=300) == 'permanent'

    # Ngược lại, một kênh stream bị đứt thì gửi lại được — đó là ca `stream` riêng.
    assert retry_advice(ServerDisconnectedError(), 0, remaining_seconds=300)['reason'] == 'stream'


def test_a_router_verdict_of_retryable_false_stops_the_retry():
    """Router đã tự thử lại và nói lỗi này không qua được bằng cách gửi lại."""
    refusal = RuntimeError('Router HTTP 425: too early')
    refusal.router_status = 425
    refusal.retryable = False
    assert retry_advice(refusal, 0, remaining_seconds=300) is None
    assert stop_reason(refusal, 0, remaining_seconds=300) == 'permanent'

    # 429 luôn thử lại được, kể cả khi trường `retryable` thiếu hoặc sai.
    throttled = _rate_limit()
    throttled.retryable = False
    assert retry_advice(throttled, 0, remaining_seconds=300)['reason'] == 'rate-limit'


def test_stop_reason_names_why_the_loop_gave_up():
    assert stop_reason(RuntimeError('Router HTTP 400: bad request'), 0, remaining_seconds=300) == 'permanent'
    assert stop_reason(_rate_limit(), DEFAULT_MAX_RETRIES, remaining_seconds=300) == 'attempts'
    assert stop_reason(_rate_limit(retry_after_ms=20_000), 0, remaining_seconds=300,
                       spent_seconds=RETRY_BUDGET_SECONDS) == 'budget'
    assert stop_reason(_rate_limit(retry_after_ms=20_000), 0, remaining_seconds=10) == 'window'
    assert stop_reason(_rate_limit(), 0, remaining_seconds=300) is None


def test_dropped_socket_and_empty_stream_retry():
    assert retry_advice(ServerDisconnectedError(), 0, remaining_seconds=300)['reason'] == 'stream'
    empty = ValueError('Upstream did not return any SSE completion content')
    assert retry_advice(empty, 0, remaining_seconds=300)['reason'] == 'stream'


def test_attempts_and_budget_are_bounded():
    assert retry_advice(_rate_limit(), DEFAULT_MAX_RETRIES, remaining_seconds=300) is None, 'hết số lần thử lại'
    assert retry_advice(_rate_limit(retry_after_ms=20_000), 0, remaining_seconds=300,
                        spent_seconds=RETRY_BUDGET_SECONDS) is None, 'hết ngân sách chờ của lượt'
    assert retry_advice(_rate_limit(retry_after_ms=20_000), 0, remaining_seconds=10) is None, \
        'chờ xong thì hết deadline — thà báo lỗi còn hơn ngủ quá giờ'


def test_is_transient_view_matches_the_policy():
    assert is_transient(ServerDisconnectedError()) is True
    assert is_transient(RuntimeError('Router HTTP 503: down')) is True
    assert is_transient(RuntimeError('Router HTTP 400: bad request')) is False
    assert is_transient(TimeoutError()) is False
    assert is_transient(PermissionError('nope')) is False
    # Điểm sửa chính: 429 giờ là lỗi tạm thời.
    assert is_transient(_rate_limit()) is True


# --------------------------------------------------------------------------- #
# Vòng lặp trong lượt
# --------------------------------------------------------------------------- #

async def fast_sleep(_seconds):
    """Bỏ thời gian chờ thật; backoff được kiểm ở phần `retry_advice`."""
    return None


def _no_sleep(monkeypatch):
    monkeypatch.setattr(asyncio, 'sleep', fast_sleep)


def test_rate_limit_is_retried_then_the_turn_completes(tmp_path, monkeypatch):
    _no_sleep(monkeypatch)
    client, events, status = _run(tmp_path, [_rate_limit(), _rate_limit()])
    notices = _notices(events)
    assert client.calls == 3, 'hai lần 429 rồi lần thứ ba thành công'
    assert [n['attempt'] for n in notices] == [1, 2]
    assert all(n['code'] == 'UPSTREAM_RETRY' and n['reason'] == 'rate-limit' for n in notices)
    assert status == 'completed'
    assert [e for e in events if e['type'] == 'finish']


def test_giving_up_reports_the_attempt_count(tmp_path, monkeypatch):
    _no_sleep(monkeypatch)
    client, events, status = _run(tmp_path, [_rate_limit()] * 8)
    assert client.calls == DEFAULT_MAX_RETRIES + 1, 'gọi lần đầu + số lần thử lại'
    assert status == 'failed'
    exhausted = [n for n in _notices(events) if n['code'] == 'UPSTREAM_RETRY_EXHAUSTED']
    assert len(exhausted) == 1
    assert exhausted[0]['attempts'] == DEFAULT_MAX_RETRIES
    assert exhausted[0]['stopReason'] == 'attempts'
    error = [e for e in events if e['type'] == 'error'][0]['data']
    assert error['code'] == 'UPSTREAM_HTTP_429'
    # Banner chat chỉ in lỗi cuối; không có vế này thì người dùng đọc thành "không thử lại".
    assert f'after {DEFAULT_MAX_RETRIES} retries' in error['message']


def test_rejected_request_fails_on_the_first_call(tmp_path):
    client, events, status = _run(tmp_path, [RuntimeError('Router HTTP 400: bad request')])
    assert client.calls == 1, 'lỗi 4xx không được thử lại'
    assert status == 'failed'
    assert [n for n in _notices(events) if n['code'] == 'UPSTREAM_RETRY'] == []
    error = [e for e in events if e['type'] == 'error'][0]['data']
    assert 'retries' not in error['message']


def test_router_refusal_keeps_code_and_retry_after():
    refusal = _rate_limit(retry_after_ms=4000)
    assert str(refusal) == 'Router HTTP 429: Provider rate limit or quota reached. Try again later.'
    assert refusal.router_status == 429
    assert refusal.router_code == 'RATE_LIMIT'
    assert refusal.retryable is True
    assert refusal.retry_after_ms == 4000.0


# --------------------------------------------------------------------------- #
# Mức thinking bị provider từ chối
# --------------------------------------------------------------------------- #

def test_a_refused_thinking_level_is_dropped_and_the_turn_survives(tmp_path):
    """Google trả `400 Thinking level is not supported` cho Gemini 2.5.

    Danh mục của router quảng cáo `low/medium/high` cho cả họ 2.5 (payload `models.list`
    nói `thinking: true`), nhưng API chỉ nhận `thinkingLevel` từ thế hệ 3. Đây là lỗi
    của YÊU CẦU: lượt phải bỏ mức rồi trả lời, không được dựng banner đỏ.
    """
    refusal = RuntimeError('Router HTTP 400: Provider error (400): Thinking level is not supported for this model.')
    client = FailingModel([refusal])
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, StubExecutor(), client)
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'gemini-2.5-flash',
                              'thinkingLevel': 'medium', 'deadlineSeconds': 600})
    routes = []
    original = client.complete

    async def spy(messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        routes.append(dict(route))
        return await original(messages, tools, route, max_tokens=max_tokens,
                              on_thought=on_thought, on_content=on_content)

    client.complete = spy
    asyncio.run(_drive(runtime, store, session))
    events = store.events(session['id'])
    status = store.get(session['id'])['status']
    assert client.calls == 2, 'lần đầu bị từ chối, lần hai gọi lại không kèm mức'
    assert routes[0].get('thinkingLevel') == 'medium'
    assert 'thinkingLevel' not in routes[1]
    assert status == 'completed'
    assert [e for e in events if e['type'] == 'error'] == []
    refused = [n for n in _notices(events) if n['code'] == 'THINKING_LEVEL_REFUSED']
    assert len(refused) == 1 and refused[0]['level'] == 'medium'
    assert [n for n in _notices(events) if n['code'] == 'UPSTREAM_RETRY'] == [], 'đây là sửa yêu cầu, không phải chờ provider'
    store.close()


def test_only_a_level_message_triggers_the_drop(tmp_path):
    """Một 400 khác (sai tham số, model không tồn tại) vẫn chết ngay như trước."""
    client, events, status = _run(tmp_path, [RuntimeError('Router HTTP 400: Provider error (400): Invalid JSON payload received.')])
    assert client.calls == 1
    assert status == 'failed'
    assert [n for n in _notices(events) if n['code'] == 'THINKING_LEVEL_REFUSED'] == []


def test_level_refusal_ignores_statuses_that_are_not_a_refusal():
    """429/5xx nhắc tới chữ "thinking" không phải là từ chối mức."""
    throttled = _rate_limit(message='Thinking level is not supported until your quota resets.')
    assert level_refusal(throttled) is False
    refused = RuntimeError('Router HTTP 400: Provider error (400): Thinking level is not supported for this model.')
    assert level_refusal(refused) is True
    assert level_refusal(RuntimeError('Router HTTP 400: Invalid JSON payload received.')) is False
