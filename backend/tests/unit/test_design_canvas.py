"""P2 — đường truyền canvas hai chiều và lưu cảnh (plan v1 §6.4 + §8 P2).

Ba bài chạy tất định, không mạng, trên ĐÚNG cửa vào của harness (`runtime.dispatch` cho công cụ
`canvas_draw`, và tuyến `POST /api/agent/sessions/{sid}/canvas` cho phía chủ nhà):

* `canvas_draw` áp op hợp lệ, đếm op sai vào `rejected`, phát ĐÚNG MỘT `design_canvas {actor:'agent'}`
  và ghi cảnh xuống `.design/<slug>/canvas.v1.json` qua worker;
* gói sai giao thức `boxfox.canvas.v1` ⇒ `DESIGN_CANVAS_PROTOCOL_INVALID`, KHÔNG dựng node bịa;
* scene của chủ nhà (`type:'scene'`) lưu vào run và phát `design_canvas {actor:'user'}`;
  directive (`type:'directive'`) xếp hàng cho lượt Design Lead kế tiếp và trả `{accepted:true}`.
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

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class RecordingExecutor:
    """Box giả: ghi lại lời gọi worker, luôn trả `ok` (không chạm đĩa)."""

    def __init__(self):
        self.calls = []

    async def execute(self, name, args, sid, **_identity):
        self.calls.append((name, args, sid))
        return {'content': 'ok', 'path': args.get('path'), 'sha256': 'x', 'bytes': 1}

    async def cleanup(self, sid):
        return None


class FixtureRouterClient:
    async def model_metadata_map(self):
        return {}


def node(node_id, **over):
    payload = {'id': node_id, 'kind': 'card', 'shape': None, 'card': 'ui-mockup', 'x': 0, 'y': 0,
               'width': 100, 'height': 60, 'title': node_id, 'body': '', 'url': None,
               'style': {'fill': '#fff', 'stroke': '#000', 'strokeWidth': 1, 'radius': 8}}
    payload.update(over)
    return payload


def empty_scene():
    return {'version': 1, 'nodes': [], 'connectors': [], 'strokes': []}


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'canvas.db')
    executor = RecordingExecutor()
    runtime = HarnessRuntime(store, executor, FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1'})['id']
    yield store, runtime, sid, executor
    store.close()


def open_run(runtime, store, sid):
    """Bật mode và mở một run đang hoạt động cho phiên."""
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế lại màn hình chat')
    session = store.get(sid)
    config = dict(session['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)
    return store.design_job(job['design_id'])


def events(store, sid, kind=None):
    return [row['data'] for row in store.events(sid) if kind is None or row['type'] == kind]


def draw(runtime, store, sid, args):
    async def call():
        return await runtime.dispatch(store.get(sid), 'canvas_draw', args)
    return asyncio.run(call())


# --------------------------------------------------------------- agent vẽ


def test_canvas_draw_emits_one_event_persists_scene_and_counts_applied(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    result = draw(runtime, store, sid, {
        'designId': job['design_id'],
        'actions': [{'type': 'CREATE_NODE', 'node': node('n1')},
                    {'type': 'CREATE_NODE', 'node': node('n2')}]})

    assert result == {'applied': 2, 'rejected': 0, 'sceneVersion': 1}
    canvas_events = events(store, sid, 'design_canvas')
    assert len(canvas_events) == 1, 'ĐÚNG MỘT sự kiện gộp cho cả lần gọi'
    event = canvas_events[0]
    assert event['designId'] == job['design_id'] and event['actor'] == 'agent'
    assert event['seq'] == 1 and event['sceneVersion'] == 1
    assert len(event['ops']) == 2

    stored = store.design_job(job['design_id'])['state']['canvasScene']
    assert [n['id'] for n in stored['nodes']] == ['n1', 'n2']
    assert stored['version'] == 1

    writes = [call for call in executor.calls if call[0] == 'file_write']
    assert len(writes) == 1, 'cảnh ghi xuống một tệp duy nhất'
    path = writes[0][1]['path']
    assert path.startswith('.design/') and path.endswith('/canvas.v1.json')
    assert json.loads(writes[0][1]['content'])['nodes'][0]['id'] == 'n1'


def test_canvas_draw_rejects_bad_ops_without_inventing_a_node(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    result = draw(runtime, store, sid, {
        'designId': job['design_id'],
        'actions': [
            {'type': 'CREATE_NODE', 'node': node('n1')},        # hợp lệ
            {'type': 'BOGUS_OP', 'node': node('n2')},           # op lạ
            {'type': 'UPDATE_NODE'},                            # thiếu nodeId/patch
            {'type': 'CREATE_NODE', 'node': {'x': 1}},          # node thiếu id
        ]})

    assert result['applied'] == 1 and result['rejected'] == 3
    stored = store.design_job(job['design_id'])['state']['canvasScene']
    assert [n['id'] for n in stored['nodes']] == ['n1'], 'không dựng node bịa'
    assert len(events(store, sid, 'design_canvas')) == 1


def test_canvas_draw_refuses_a_malformed_envelope(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    with pytest.raises(ValueError, match=limits.DESIGN_CANVAS_PROTOCOL_INVALID_CODE):
        draw(runtime, store, sid, {'designId': job['design_id']})
    with pytest.raises(ValueError, match=limits.DESIGN_CANVAS_PROTOCOL_INVALID_CODE):
        draw(runtime, store, sid, {'designId': job['design_id'], 'actions': 'not-a-list'})
    assert events(store, sid, 'design_canvas') == []
    assert executor.calls == [], 'gói sai ⇒ không chạm box'


# --------------------------------------------------------------- chủ nhà gửi


def test_user_scene_and_directive_routes(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                scene_body = {'protocol': 'boxfox.canvas.v1', 'type': 'scene',
                              'scene': {**empty_scene(), 'nodes': [node('u1')]}}
                async with http.post(str(server.make_url(f'/api/agent/sessions/{sid}/canvas')),
                                     json=scene_body) as resp:
                    assert resp.status == 200
                    posted = await resp.json()
                directive_body = {'protocol': 'boxfox.canvas.v1', 'type': 'directive',
                                  'targetNodeId': 'u1', 'targetNodeTitle': 'Thẻ chat',
                                  'instruction': 'đổi nút gửi thành màu xanh'}
                async with http.post(str(server.make_url(f'/api/agent/sessions/{sid}/canvas')),
                                     json=directive_body) as resp:
                    assert resp.status == 200
                    accepted = await resp.json()
                # `create_app` đóng store khi server dọn, nên đọc trạng thái NGAY trong phiên chạy.
                stored = store.design_job(job['design_id'])['state']['canvasScene']
                user_events = [event for event in events(store, sid, 'design_canvas')
                               if event['actor'] == 'user']
                block = runtime.turn_profile(store.get(sid))['promptBlock']
                tasks = dict(runtime.tasks)
            return posted, accepted, stored, user_events, block, tasks

    posted, accepted, stored, user_events, block, tasks = asyncio.run(run())
    assert accepted == {'accepted': True}

    # Scene lưu trên run và phát một `design_canvas {actor:'user'}` — KHÔNG mở lượt nào.
    assert [item['id'] for item in stored['nodes']] == ['u1']
    assert len(user_events) == 1 and user_events[0]['ops'] == []
    assert sid not in tasks, 'gửi scene không mở lượt'

    # Directive xếp hàng và xuất hiện trong khối lời dặn của lượt Design Lead kế tiếp.
    assert 'đổi nút gửi thành màu xanh' in block
