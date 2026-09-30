"""F1 — trả lời lời hỏi design phải MỞ LƯỢT TIẾP TỤC khi chủ nhà bấm "Bắt đầu".

Số đo sống 2026-09-27 (harness thật `:3102`, model `muse-spark-1.3-contributor-free`, phiên
`23d1ee8ad8e043e9aafd5f2ab56dc272`): chủ nhà trả lời lời hỏi `out-of-scope` với `start=true`; tuyến
`POST /api/agent/design/prompts/{id}/answer` trả `{"status": "answered", "start": true, "resume": true}`
và đổi run sang `status='designing'`, `phase='briefing'` — nhưng KHÔNG lượt nào chạy tiếp, và không
đường bơm nào cứu được pha ấy (`design_continuation_step` chỉ nhận `scaffolding`/`reviewing`). Run
đứng im vô hạn. Đường research đã có `await runtime.submit(...)` từ trước (`research_prompt_answer`);
đường design thiếu hẳn.

Bốn bài ở đây đi qua ĐÚNG biên thật (`create_app` + `TestServer`, tức tuyến HTTP) và chỉ dùng mô hình
giả; khẳng định hệ quả đo được: có lượt mới hay không, qua `turn_start`.

Lưu ý khi đọc: `create_app` đóng store lúc dọn server, nên mọi số đo được chụp NGAY trong phiên chạy
(khuôn `test_design_canvas.py`).
"""
from __future__ import annotations

import asyncio
import json

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore


@pytest.fixture(autouse=True)
def legacy_mode_path(monkeypatch):
    """This file pins the legacy slash-mode path; the Work Graph (the default) is tested in test_work_graph.py."""
    monkeypatch.setenv('BOXFOX_WORK_GRAPH', 'off')

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'ok'}

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


class RecordingModel:
    """Đếm lượt gọi mô hình: lượt tiếp tục phải thật sự chạy, không chỉ được xếp lịch."""

    answer = 'ok'

    def __init__(self):
        self.calls = 0

    async def model_metadata_map(self):
        return {}

    async def complete(self, messages, tools, route, max_tokens=4096, on_thought=None, on_content=None):
        self.calls += 1
        return {'choices': [{'message': {'content': self.answer}, 'finish_reason': 'stop'}],
                'usage': None, 'boxfox': None}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'prompt-resume.db')
    runtime = HarnessRuntime(store, FixtureExecutor(), FixtureRouterClient())
    runtime.client = RecordingModel()
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1',
                          'timeoutSeconds': 30, 'deadlineSeconds': 60})['id']
    yield store, runtime, sid
    store.close()


def turn_starts(store, sid):
    return [row['data'] for row in store.events(sid) if row['type'] == 'turn_start']


def run_turn(runtime, sid, prompt, invocation_id=None):
    async def main():
        await runtime.submit(sid, prompt, invocation_id=invocation_id)
        task = runtime.tasks.get(sid)
        if task is not None:
            await task

    asyncio.run(main())


def answer_via_route(runtime, store, sid, prompt_id, body, design_id):
    """Gọi ĐÚNG tuyến HTTP rồi chụp số đo NGAY trong phiên chạy (store sống).

    `newTask` là hiệu đối tượng: `runtime.tasks[sid]` giữ lại task đã xong của lượt trước, nên chỉ
    "có task" không nói được gì — task MỚI mới là dấu hiệu lượt mới.
    """

    async def main():
        before_task = runtime.tasks.get(sid)
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                url = str(server.make_url(f'/api/agent/design/prompts/{prompt_id}/answer'))
                async with http.post(url, json=body) as resp:
                    status, payload = resp.status, await resp.json()
                task = runtime.tasks.get(sid)
                new_task = task is not None and task is not before_task
                if new_task:
                    await asyncio.wait_for(asyncio.shield(task), 10)
                return {
                    'status': status,
                    'payload': payload,
                    'newTask': new_task,
                    'turnStarts': len(turn_starts(store, sid)),
                    'steers': store.pending_steer_count(sid),
                    'userMessages': [message['content'] for message in store.get(sid)['messages']
                                     if message['role'] == 'user'],
                    'job': store.design_job(design_id),
                }

    return asyncio.run(main())


def answers_via_route(runtime, store, sid, steps, design_id):
    """Nhiều lần trả lời trong MỘT phiên chạy app.

    `create_app` đóng store lúc dọn server, nên hai lần POST liên tiếp bắt buộc phải nằm trong cùng
    một `TestServer`; `step['prepare'](store, sid)` chạy giữa hai lần để dựng lời hỏi kế tiếp và trả
    về `promptId` của nó.
    """

    async def main():
        out = []
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                for step in steps:
                    prompt_id = step.get('promptId')
                    if step.get('prepare'):
                        prompt_id = step['prepare'](store, sid)
                    before_task = runtime.tasks.get(sid)
                    url = str(server.make_url(f'/api/agent/design/prompts/{prompt_id}/answer'))
                    async with http.post(url, json=step['body']) as resp:
                        status, payload = resp.status, await resp.json()
                    task = runtime.tasks.get(sid)
                    new_task = task is not None and task is not before_task
                    if new_task:
                        await asyncio.wait_for(asyncio.shield(task), 10)
                    out.append({'status': status,
                                'payload': payload,
                                'newTask': new_task,
                                'turnStarts': len(turn_starts(store, sid)),
                                'steers': store.pending_steer_count(sid),
                                'job': store.design_job(design_id)})
        return out

    return asyncio.run(main())


def interview_run(store, runtime, sid):
    """Chạy `/design <brief mơ hồ>`: mở run ở mode + lời hỏi phỏng vấn đang mở."""
    run_turn(runtime, sid, '/design thiết kế một giao diện chat')
    jobs = store.design_jobs_for(sid)
    assert len(jobs) == 1
    prompts = jobs[0]['state']['prompts']
    assert [p['kind'] for p in prompts] == ['interview'] and prompts[0]['status'] == 'open'
    return jobs[0], prompts[0]


def interview_answers(prompt, text='Màn hình chat, nền tảng web'):
    return [{'questionId': prompt['questions'][0]['id'], 'text': text}]


# ------------------------------------------------------------------ F1-01


def test_f1_01_start_opens_a_continuation_turn(harness):
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)
    assert len(turn_starts(store, sid)) == 1, 'lượt `/design ...` là lượt thứ nhất'

    got = answer_via_route(runtime, store, sid, prompt['promptId'],
                           {'answers': interview_answers(prompt), 'start': True}, job['design_id'])

    assert got['status'] == 200
    assert got['payload']['status'] == 'answered' and got['payload']['resume'] is True
    assert got['newTask'] is True, 'F1-01: `start=true` phải MỞ LƯỢT TIẾP TỤC'
    assert got['turnStarts'] == 2, f"F1-01: đúng một lượt mới, thấy {got['turnStarts']}"
    assert any(str(text).startswith(f'Continue design job {job["design_id"]}')
               for text in got['userMessages']), 'F1-01: lượt tiếp tục mang lời dặn của đường design'
    assert runtime.client.calls == 2, 'F1-01: lượt tiếp tục THẬT SỰ chạy, không chỉ được xếp lịch'
    assert got['job']['status'] == 'designing' and got['job']['state']['phase'] == 'briefing'


def test_f1_02_a_busy_session_steers_the_continuation_instead_of_a_second_turn(harness):
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)
    # Phiên đang chạy lượt khác: KHÔNG mở lượt thứ hai, và cũng KHÔNG bỏ rơi run — lời dặn thành chỉ
    # thị giữa lượt cho chính lượt đang chạy (`allow_steer` mặc định bật với phiên gốc).
    store.save(sid, store.get(sid)['messages'], status='running')

    got = answer_via_route(runtime, store, sid, prompt['promptId'],
                           {'answers': interview_answers(prompt), 'start': True}, job['design_id'])

    assert got['status'] == 200 and got['payload']['resume'] is True
    assert got['newTask'] is False, 'F1-02: phiên đang bận thì KHÔNG mở thêm lượt'
    assert got['turnStarts'] == 1 and runtime.client.calls == 1
    assert got['steers'] == 1, 'F1-02: lượt đang chạy phải nhận được chỉ thị tiếp tục'


def test_f1_03_a_run_that_is_not_the_active_one_is_not_resumed(harness):
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)
    # Mode vẫn bật nhưng `activeRunId` đã nhả (run không còn là run của mode) ⇒ `resume` ghi sổ mà
    # không mở lượt, đúng `design_job_pumpable` — nền tảng cho luật của `design_continuation_step`.
    config = dict(store.get(sid)['config'])
    config['designMode'] = {**config['designMode'], 'activeRunId': None}
    store.update_config(sid, config)

    got = answer_via_route(runtime, store, sid, prompt['promptId'],
                           {'answers': interview_answers(prompt), 'start': True}, job['design_id'])

    assert got['status'] == 200 and got['payload']['resume'] is True
    assert got['newTask'] is False, 'F1-03: run không thuộc mode thì không được bơm'
    assert got['turnStarts'] == 1 and runtime.client.calls == 1
    assert got['job']['state']['phase'] == 'briefing', \
        'F1-03: câu trả lời VẪN vào brief dù không mở lượt'


def test_f1_04_answering_without_start_writes_the_brief_and_opens_nothing(harness):
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)

    got = answer_via_route(runtime, store, sid, prompt['promptId'],
                           {'answers': interview_answers(prompt), 'start': False}, job['design_id'])

    assert got['status'] == 200
    assert got['payload']['resume'] is False and got['payload']['start'] is False
    assert got['newTask'] is False, 'F1-04: trả lời KHÔNG kèm "Bắt đầu" thì không mở lượt'
    assert got['turnStarts'] == 1 and runtime.client.calls == 1
    brief = got['job']['state']['brief']
    assert brief['screen']['text'] == 'Màn hình chat, nền tảng web'


def test_f1_05_two_prompts_of_one_run_open_two_turns(harness):
    """`promptId` nằm trong `invocationId` là điều KIỆN SỐNG: dùng chung một mã thì lời hỏi thứ hai
    trả lại kết quả đã ghi của lời hỏi thứ nhất và lượt tiếp tục KHÔNG mở."""
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)

    def open_second_prompt(store, sid):
        live = store.design_job(job['design_id'])
        created = design_runtime.design_prompt_new(
            runtime, sid, live, 'interview',
            questions=[{'id': 'dq-style', 'text': 'Bạn muốn giữ phong cách hiện có chứ?', 'why': '',
                        'allowFreeText': True, 'required': True,
                        'options': [{'id': 'follow-existing', 'label': 'Giữ phong cách hiện có'},
                                    {'id': 'fresh', 'label': 'Đổi mới hoàn toàn'}]}])
        assert store.design_job(job['design_id'])['status'] == 'needs_user'
        return created['promptId']

    first, second = answers_via_route(runtime, store, sid, [
        {'promptId': prompt['promptId'],
         'body': {'answers': interview_answers(prompt), 'start': True}},
        {'prepare': open_second_prompt,
         'body': {'answers': [{'questionId': 'dq-style', 'optionId': 'follow-existing'}],
                  'start': True}},
    ], job['design_id'])

    assert first['newTask'] is True and first['turnStarts'] == 2
    assert second['status'] == 200 and second['payload']['resume'] is True
    assert second['newTask'] is True, 'F1-05: lời hỏi thứ hai phải mở lượt riêng'
    assert second['turnStarts'] == 3 and runtime.client.calls == 3


def test_f1_06_answering_the_same_prompt_twice_is_refused_and_opens_nothing(harness):
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)
    body = {'answers': interview_answers(prompt), 'start': True}

    first, again = answers_via_route(runtime, store, sid, [
        {'promptId': prompt['promptId'], 'body': body},
        {'promptId': prompt['promptId'], 'body': body},
    ], job['design_id'])

    assert first['newTask'] is True and first['turnStarts'] == 2
    # `DESIGN_PROMPT_ANSWERED` không nằm trong `_DESIGN_CONFLICT_STATUS` nên đi ra 400 (không phải
    # 409) — đúng như bảng mã ở `api/server.py:261`; cái phải khẳng định là KHÔNG lượt nào mở thêm.
    assert again['status'] == 400, 'F1-06: lời hỏi đã trả lời thì bị chối, không mở lượt nào'
    assert 'DESIGN_PROMPT_ANSWERED' in json.dumps(again['payload'], ensure_ascii=False)
    assert again['newTask'] is False and again['turnStarts'] == 2 and runtime.client.calls == 2


def test_f1_07_a_busy_session_with_steering_off_logs_instead_of_failing(harness, monkeypatch):
    """Chủ nhà tắt `BOXFOX_STEER`: câu trả lời ĐÃ ghi sổ nên tuyến trả 200 (không phải 500/409),
    không mở lượt, không xếp chỉ thị — và ghi nhật ký hệ thống để trạng thái ấy đọc được."""
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)
    store.save(sid, store.get(sid)['messages'], status='running')
    monkeypatch.setenv(limits.STEER_ENV, 'off')

    got = answer_via_route(runtime, store, sid, prompt['promptId'],
                           {'answers': interview_answers(prompt), 'start': True}, job['design_id'])

    assert got['status'] == 200 and got['payload']['resume'] is True
    assert got['newTask'] is False and got['turnStarts'] == 1 and runtime.client.calls == 1
    assert got['steers'] == 0, 'F1-07: chế độ chỉ thị giữa lượt đang tắt thì không xếp chỉ thị'
    assert got['job']['state']['brief']['screen']['text'] == 'Màn hình chat, nền tảng web'
