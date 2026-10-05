"""C1 — hai lỗi im lặng đo được từ lượt chạy sống 2026-09-21.

(a) Hạn chót bị KẸP mà không nói gì: người dùng đặt `deadlineSeconds: 900`, engine chạy
    600, và không có event, không log, không trường nào trong payload. Bản này giữ nguyên
    luật kẹp nhưng ghi lại sự thật: notice `DEADLINE_CLAMPED` + cờ `deadlineClamped` trong
    config phiên (config đã nằm trong payload `GET /api/agent/sessions/{sid}`).
(b) Trần bước: phiên `failed` dù việc đã xong trên đĩa — lượt chạy sống có plan `v5-…`
    9 155 B, 4 tệp sửa, `300 passed`, mà không hàng nào nói "việc đã xong, chỉ lượt là chưa
    đóng". Bản này phát đúng MỘT bản ghi `blocker` và giữ nguyên trạng thái `failed`.
"""
import asyncio
import copy
import json

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core.limits import (DEADLINE_CLAMP_NOTICE_CODE, DEADLINE_MAX_SECONDS,
                                        DEADLINE_MIN_SECONDS, MAX_STEPS_MAX, STEPS_CLAMP_NOTICE_CODE)
from agentbox.agent_core.runtime import HarnessRuntime, _journal_blocker
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


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
    async def execute(self, name, args, sid):
        return {'content': 'observed fixture result'}

    async def cleanup(self, sid):
        return None


def notices(store, sid, code=None):
    rows = [e['data'] for e in store.events(sid) if e['type'] == 'notice']
    return [row for row in rows if code is None or row.get('code') == code]


def blockers(store, sid):
    return [e['data'] for e in store.events(sid) if e['type'] == 'blocker']


# --------------------------------------------------------------------------- #
# (a) hạn chót bị kẹp
# --------------------------------------------------------------------------- #

def test_a_clamped_deadline_is_reported_once(tmp_path):
    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([answer('xong')]))
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                url = str(server.make_url('/api/agent/sessions'))
                # #6457 nâng trần lên 7200 s, nên con số "quá trần" phải lớn hơn trần MỚI:
                # xin 9000 để chắc chắn bị kẹp (1500 của bản cũ nay nằm trong khoảng hợp lệ).
                async with http.post(url, json={'skills': [], 'deadlineSeconds': 9000}) as resp:
                    assert resp.status == 201
                    payload = await resp.json()
                sid = payload['id']
                assert payload['config']['deadlineSeconds'] == DEADLINE_MAX_SECONDS
                assert payload['config']['deadlineClamped'] is True, 'payload phải nói ra sự thật'
                async with http.get(url + '/' + sid) as resp:
                    again = await resp.json()
                assert again['config']['deadlineClamped'] is True
            clamped = notices(store, sid, DEADLINE_CLAMP_NOTICE_CODE)
            assert len(clamped) == 1, 'một lần kẹp, một notice'
            assert clamped[0]['requested'] == 9000 and clamped[0]['applied'] == DEADLINE_MAX_SECONDS
            assert clamped[0]['message'].startswith(DEADLINE_CLAMP_NOTICE_CODE + ':')
            assert runtime.session_metrics(sid)['deadlineClamped'] is True

            # Trong khoảng hợp lệ thì không có cờ, không có notice — nếu không, cờ này vô nghĩa.
            async with ClientSession(headers=HEADERS) as http:
                async with http.post(url, json={'skills': [], 'deadlineSeconds': 300}) as resp:
                    plain = await resp.json()
            assert 'deadlineClamped' not in plain['config']
            assert notices(store, plain['id'], DEADLINE_CLAMP_NOTICE_CODE) == []
            # Dưới sàn cũng là một lần kẹp, và cũng phải nói ra.
            async with ClientSession(headers=HEADERS) as http:
                async with http.post(url, json={'skills': [], 'deadlineSeconds': 1}) as resp:
                    low = await resp.json()
            assert low['config']['deadlineSeconds'] == DEADLINE_MIN_SECONDS
            assert notices(store, low['id'], DEADLINE_CLAMP_NOTICE_CODE)[0]['applied'] == DEADLINE_MIN_SECONDS
        store.close()

    asyncio.run(run())


# --------------------------------------------------------------------------- #
# (b) trần bước
# --------------------------------------------------------------------------- #

def run_step_capped_turn(tmp_path, seed=None):
    """Một lượt chạm trần bước: model luôn xin thêm tool, `maxSteps` = 1."""
    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([answer(calls=[call('file_read', {'path': 'x'})])]))
    session = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'deepseek-v4-flash',
                              'maxSteps': 1})
    if seed:
        seed(store, session['id'])

    async def run():
        await runtime.submit(session['id'], 'làm việc dài')
        await runtime.tasks[session['id']]

    asyncio.run(run())
    return store, session


def test_a_clamped_step_budget_is_reported_once(tmp_path):
    """B7 — `maxSteps` bị kẹp phải NÓI RA, đối xứng với `DEADLINE_CLAMPED` của C1.

    #6546 nâng trần bước lên `MAX_STEPS_MAX` (1500) nên số yêu cầu phải tính TỪ hằng số: một số
    cứng như 999 cũ sẽ nằm trong khoảng hợp lệ và bài kiểm sẽ đo một lần kẹp không bao giờ xảy ra.
    """
    requested_steps = MAX_STEPS_MAX + 400

    async def run():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([answer('xong')]))
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                url = str(server.make_url('/api/agent/sessions'))
                async with http.post(url, json={'skills': [], 'maxSteps': requested_steps}) as resp:
                    high = await resp.json()
                assert high['config']['maxSteps'] == MAX_STEPS_MAX
                assert high['config']['stepsClamped'] is True, 'payload phải nói ra sự thật'
                clamped = notices(store, high['id'], STEPS_CLAMP_NOTICE_CODE)
                assert len(clamped) == 1, 'một lần kẹp, một notice'
                assert clamped[0]['requested'] == requested_steps and clamped[0]['applied'] == MAX_STEPS_MAX
                assert clamped[0]['message'].startswith(STEPS_CLAMP_NOTICE_CODE + ':')
                assert runtime.session_metrics(high['id'])['stepsClamped'] is True

                # Trong khoảng hợp lệ thì không có cờ, không có notice — nếu không, cờ này vô nghĩa.
                async with http.post(url, json={'skills': [], 'maxSteps': 40}) as resp:
                    ok = await resp.json()
                assert ok['config']['maxSteps'] == 40
                assert 'stepsClamped' not in ok['config']
                assert notices(store, ok['id'], STEPS_CLAMP_NOTICE_CODE) == []
                assert runtime.session_metrics(ok['id'])['stepsClamped'] is False
        store.close()

    asyncio.run(run())


def test_step_cap_writes_exactly_one_blocker_record(tmp_path):
    store, session = run_step_capped_turn(tmp_path)
    records = blockers(store, session['id'])
    assert len(records) == 1, 'một lượt chạm trần = một bản ghi, không phải một bản mỗi bước'
    assert records[0] == {'kind': 'blocker', 'status': 'blocked', 'note': 'max-steps',
                          'maxSteps': 1, 'journalSeq': 1}
    # Không có plan/diff nào trên đĩa thì hai khoá đó KHÔNG được bịa ra.
    assert 'planPath' not in records[0] and 'diffPath' not in records[0]
    assert store.get(session['id'])['status'] == 'failed', 'trạng thái phiên không đổi vì bản ghi này'
    assert store.events(session['id'])[-1]['type'] == 'error'
    store.close()


def test_step_cap_pins_exactly_one_journal_row(tmp_path):
    """Cùng sự việc, bề mặt thứ hai: MỘT hàng `blocker` trong nhật ký phiên (kế hoạch C1)."""
    store, session = run_step_capped_turn(tmp_path)
    tail = store.journal_tail(session['id'], limit=50)
    assert [row['kind'] for row in tail] == ['blocker'], 'một lượt chạm trần = một hàng nhật ký'
    row = tail[0]
    assert row['seq'] == blockers(store, session['id'])[0]['journalSeq'], \
        'event và nhật ký phải trỏ vào cùng một hàng'
    assert row['text'].startswith('STEP_BUDGET_EXHAUSTED:')
    record = row['payload']['record']
    assert record['numbers'] == {'step': 1, 'maxSteps': 1}, 'số đo nằm ở `numbers`, không trộn vào chữ'
    assert record['id'] == f"X:{session['id'][:8]}-{row['seq']}", \
        'hàng C1 cũng phải có mã như mọi bản ghi khác — bản 0.1 để trống nên khối ký ức in ra `X:?`'
    assert (record['kind'], record['status']) == ('blocker', 'blocked')
    store.close()


def test_blocker_references_the_plan_and_diff_only_when_they_exist(tmp_path):
    def seed(store, sid):
        # Đúng hình dạng `write_plan` phát SAU khi sandbox xác nhận đường dẫn (test_write_plan.py).
        store.emit(sid, 'plan_written', {'identity': 'limits-notice', 'version': 3,
                                         'relativePath': '.plans/v3-limits-notice.md', 'bytes': 9155})
        store.emit(sid, 'tool_end', {'id': 'c9', 'name': 'terminal_exec', 'args': {'command': 'git diff'},
                                     'result': {'content': 'wrote /home/agent/workspace/fix.diff'}})

    store, session = run_step_capped_turn(tmp_path, seed=seed)
    record = blockers(store, session['id'])[0]
    assert record['planPath'] == '.plans/v3-limits-notice.md'
    assert record['diffPath'] == '/home/agent/workspace/fix.diff'
    store.close()


def test_blocker_ignores_a_plan_path_the_reader_would_reject(tmp_path):
    def seed(store, sid):
        store.emit(sid, 'plan_written', {'identity': 'escape', 'version': 1,
                                         'relativePath': '../../etc/passwd'})
        store.emit(sid, 'tool_end', {'id': 'c1', 'name': 'terminal_exec', 'args': {},
                                     'result': {'content': 'notes about .plans/v1-real.md.txt'}})

    store, session = run_step_capped_turn(tmp_path, seed=seed)
    record = blockers(store, session['id'])[0]
    assert 'planPath' not in record, 'PLAN_PATH_RE từ chối thì không được ghi vào bản ghi'
    assert 'diffPath' not in record, '`.md.txt` không phải tệp diff'
    store.close()


def test_journal_write_never_breaks_a_turn(tmp_path):
    """Ghi nhật ký là việc PHỤ: kho không có API đó thì trả None, không ném."""
    class BareStore:
        pass

    assert _journal_blocker(BareStore(), 'a' * 32, {'note': 'max-steps'}) is None
    assert _journal_blocker(None, 'a' * 32, {'note': 'max-steps'}) is None

    class BrokenStore:
        def journal_add(self, *args, **kwargs):
            raise RuntimeError('disk full')

    assert _journal_blocker(BrokenStore(), 'a' * 32, {'note': 'max-steps'}) is None

    store = SessionStore(tmp_path / 'sessions.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureModel([answer('xong')]))
    session = runtime.create({'skills': []})
    journal_seq = _journal_blocker(store, session['id'], {'note': 'max-steps'}, step=7)
    assert isinstance(journal_seq, int) and journal_seq > 0
    last = store.journal_tail(session['id'])[-1]
    assert last['payload']['record']['numbers'] == {'step': 7}
    assert last['payload']['record']['id'].startswith('X:')
    store.close()
