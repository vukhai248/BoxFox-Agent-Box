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

import pytest
from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import design_runtime, limits
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

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
    """Đếm lượt gọi mô hình; lượt tiếp tục phải chạy được tới `finish_reason='stop'`."""

    def __init__(self, answer='ok'):
        self.calls = 0
        self.answer = answer

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


def events(store, sid, kind=None):
    return [row['data'] for row in store.events(sid) if kind is None or row['type'] == kind]


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
                    'turnStarts': len(events(store, sid, 'turn_start')),
                    'userMessages': [message['content'] for message in store.get(sid)['messages']
                                     if message['role'] == 'user'],
                    'job': store.design_job(design_id),
                }

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
    assert len(events(store, sid, 'turn_start')) == 1, 'lượt `/design ...` là lượt thứ nhất'

    got = answer_via_route(runtime, store, sid, prompt['promptId'],
                           {'answers': interview_answers(prompt), 'start': True}, job['design_id'])

    assert got['status'] == 200
    assert got['payload']['status'] == 'answered' and got['payload']['resume'] is True
    assert got['newTask'] is True, 'F1-01: `start=true` phải MỞ LƯỢT TIẾP TỤC'
    assert got['turnStarts'] == 2, f"F1-01: đúng một lượt mới, thấy {got['turnStarts']}"
    assert any(str(text).startswith(f'Continue design job {job["design_id"]}')
               for text in got['userMessages']), 'F1-01: lượt tiếp tục mang lời dặn của đường design'
    assert got['job']['status'] == 'designing' and got['job']['state']['phase'] == 'briefing'


def test_f1_02_an_answered_prompt_does_not_open_a_turn_when_the_session_is_busy(harness):
    store, runtime, sid = harness
    job, prompt = interview_run(store, runtime, sid)
    # Cửa sổ đua: phiên đang chạy lượt khác thì tuyến chỉ ghi sổ, không mở lượt thứ hai.
    store.save(sid, store.get(sid)['messages'], status='running')

    got = answer_via_route(runtime, store, sid, prompt['promptId'],
                           {'answers': interview_answers(prompt), 'start': True}, job['design_id'])

    assert got['status'] == 200 and got['payload']['resume'] is True
    assert got['newTask'] is False, 'F1-02: phiên đang bận thì KHÔNG mở thêm lượt'
    assert got['turnStarts'] == 1


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
    assert got['turnStarts'] == 1
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
    assert got['turnStarts'] == 1
    brief = got['job']['state']['brief']
    assert brief['screen']['text'] == 'Màn hình chat, nền tảng web'
