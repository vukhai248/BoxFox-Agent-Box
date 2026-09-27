"""P1 (vòng v3) — canvas có nghĩa NGAY từ phút đầu, kể cả khi chạy trong dự án thật.

Vòng trước, canvas chỉ có nội dung khi MÔ HÌNH tự nhớ gọi `canvas_draw`: mở một dự án đã có mã nguồn
thì canvas trống y hệt dự án mới. Vòng này gieo cảnh khởi đầu ở thời điểm run có đủ dữ liệu thật
(brief + danh sách chạm đã duyệt) — vẫn là op của `actor:'agent'`, vẫn đi qua `canvas_draw`.

Bài khẳng định: op gieo có khối dự án + màn hình đích + nét nối + mỗi mục chạm một thẻ (trần 8); cảnh
chủ nhà/agent đã vẽ KHÔNG bị ghi đè; tuyến duyệt danh sách chạm trả `canvasOps`, phát `design_canvas`
SAU `design_scope`, ghim ảnh chụp xuống `.design/<slug>/canvas.v1.json`; payload CHI TIẾT của run mang
`canvasScene` + `canvasSeq` còn danh sách thì không; chỉ thị không neo node đi được.
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


@pytest.fixture()
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv(limits.DESIGN_MODE_ENV, 'on')
    store = SessionStore(tmp_path / 'seed.db')
    executor = RecordingExecutor()
    runtime = HarnessRuntime(store, executor, FixtureRouterClient())
    sid = runtime.create({'skills': [], 'connectionId': 'c1', 'modelId': 'm1'})['id']
    yield store, runtime, sid, executor
    store.close()


def open_run(runtime, store, sid):
    design_runtime.apply_design_mode(runtime, sid, True, 'toggle')
    job = design_runtime.new_design_job(runtime, sid, 'thiết kế lại màn hình chat')
    session = store.get(sid)
    config = dict(session['config'])
    config['designMode'] = {**config['designMode'], 'on': True, 'activeRunId': job['design_id']}
    store.update_config(sid, config)
    return store.design_job(job['design_id'])


def save_brief(store, sid, job, **fields):
    """Brief như mô hình ghi qua `design_scope`: `project`/`screen`/`mode`/`goal`/`platform`."""
    payload = {'project': 'BoxFox', 'screen': 'Bảng tin', 'mode': 'redesign',
               'goal': 'thiết kế lại màn hình chat', 'platform': 'web', **fields}
    live = store.design_job(job['design_id'])
    state = dict(live['state'] or {})
    state['brief'] = payload
    return store.design_job_save(job['design_id'], sid, state, revision=live.get('revision'))


def touch_items(count):
    return [{'kind': 'new', 'path': 'src/app/screen-%d.tsx' % (index + 1),
             'reason': 'màn hình %d' % (index + 1), 'risk': 'low'} for index in range(count)]


def store_touch_list(runtime, store, sid, job, items):
    live = store.design_job(job['design_id'])
    design_runtime.design_touch_list_store(runtime, sid, live, items)


def approve(runtime, store, sid, job, items):
    store_touch_list(runtime, store, sid, job, items)
    live = store.design_job(job['design_id'])
    return design_runtime.design_touch_list_approve(
        runtime, sid, live, live['state']['touchList']['revision'])


def events(store, sid, kind=None):
    return [row for row in store.events(sid) if kind is None or row['type'] == kind]


def draw(runtime, store, sid, args):
    async def call():
        return await runtime.dispatch(store.get(sid), 'canvas_draw', args)
    return asyncio.run(call())


def node(node_id, **over):
    payload = {'id': node_id, 'kind': 'card', 'card': 'ui-mockup', 'x': 0, 'y': 0,
               'width': 100, 'height': 60, 'title': node_id, 'body': ''}
    payload.update(over)
    return payload


# --------------------------------------------------------------- op gieo


def test_seed_ops_carry_project_block_target_screen_and_one_card_per_touch_item(harness):
    store, runtime, sid, executor = harness
    job = save_brief(store, sid, open_run(runtime, store, sid))
    store_touch_list(runtime, store, sid, job, touch_items(3))
    live = store.design_job(job['design_id'])

    ops = design_runtime.canvas_seed_ops(live)
    created = [op['node'] for op in ops if op['type'] == 'CREATE_NODE']
    assert [item['id'] for item in created] == ['seed-workspace', 'seed-screen',
                                                'seed-touch-1', 'seed-touch-2', 'seed-touch-3']
    assert [op['type'] for op in ops].count('CONNECT_NODES') == 4, 'một nét vào + một nét cho mỗi mục'

    workspace, screen = created[0], created[1]
    assert 'BoxFox' in workspace['title'] and 'Mục tiêu: thiết kế lại màn hình chat' in workspace['body']
    assert 'Bảng tin' in screen['title'] and 'redesign' in screen['body'] and 'web' in screen['body']
    # Thẻ chạm xếp DỌC, không chồng lên nhau, và mang đúng đường dẫn + lý do của danh sách chạm.
    assert len({item['y'] for item in created[2:]}) == 3
    assert [item['y'] for item in created[2:]] == sorted(item['y'] for item in created[2:])
    assert created[2]['title'] == 'src/app/screen-1.tsx' and 'màn hình 1' in created[2]['body']
    # Nét nối neo màn hình đích vào từng thẻ chạm — bức tranh đọc được thành luồng.
    links = [op['connector'] for op in ops if op['type'] == 'CONNECT_NODES']
    assert links[0]['fromNodeId'] == 'seed-workspace' and links[0]['toNodeId'] == 'seed-screen'
    assert {link['fromNodeId'] for link in links[1:]} == {'seed-screen'}
    assert [link['toNodeId'] for link in links[1:]] == ['seed-touch-1', 'seed-touch-2', 'seed-touch-3']


def test_seed_ops_stop_at_eight_touch_items(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    store_touch_list(runtime, store, sid, job, touch_items(12))
    live = store.design_job(job['design_id'])

    created = [op['node']['id'] for op in design_runtime.canvas_seed_ops(live)
               if op['type'] == 'CREATE_NODE']
    assert created == ['seed-workspace', 'seed-screen'] + [
        'seed-touch-%d' % (index + 1) for index in range(design_runtime.CANVAS_SEED_ITEMS_MAX)]


def test_seed_ops_read_brief_fields_in_their_wrapped_shapes(harness):
    """Câu trả lời phỏng vấn đi vào brief dạng `{'text': ...}`; `platform` có thể là mảng."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    save_brief(store, sid, job, project={'text': 'Dự án BoxFox'}, screen={'value': 'Hộp thư'},
               mode='new', platform=['web', 'mobile'])
    store_touch_list(runtime, store, sid, job, touch_items(1))
    live = store.design_job(job['design_id'])

    created = [op['node'] for op in design_runtime.canvas_seed_ops(live) if op['type'] == 'CREATE_NODE']
    assert created[0]['title'] == 'Dự án: Dự án BoxFox'
    assert created[1]['title'] == 'Màn hình đích: Hộp thư'
    assert 'web; mobile' in created[1]['body']


def test_seed_ops_stay_out_of_a_canvas_that_already_carries_the_seed_anchor(harness):
    """Gieo chỉ xảy ra MỘT lần: cảnh đã có neo `seed-workspace` thì không gieo lại (không nhân đôi)."""
    store, runtime, sid, executor = harness
    job = save_brief(store, sid, open_run(runtime, store, sid))
    approve(runtime, store, sid, job, touch_items(2))
    live = store.design_job(job['design_id'])

    assert design_runtime.canvas_seed_ops(live) == []
    result = design_runtime.design_touch_list_approve(
        runtime, sid, live, live['state']['touchList']['revision'])
    assert 'canvasOps' not in result, 'cảnh đã có neo gieo ⇒ không gieo lại, không báo op nào'
    stored = store.design_job(job['design_id'])['state']['canvasScene']
    assert [item['id'] for item in stored['nodes']].count('seed-workspace') == 1, 'không nhân đôi neo'


def test_seed_ops_keep_an_earlier_drawing_and_still_build_the_map(harness):
    """Bản vẽ sớm của agent không được chặn bản đồ: mẻ gieo chỉ THÊM node, không sửa node của ai."""
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)
    draw(runtime, store, sid, {'designId': job['design_id'],
                               'actions': [{'type': 'CREATE_NODE', 'node': node('owner-1')}]})
    store_touch_list(runtime, store, sid, job, touch_items(2))
    live = store.design_job(job['design_id'])

    created = [op['node']['id'] for op in design_runtime.canvas_seed_ops(live) if op['type'] == 'CREATE_NODE']
    assert created == ['seed-workspace', 'seed-screen', 'seed-touch-1', 'seed-touch-2']
    result = design_runtime.design_touch_list_approve(
        runtime, sid, live, live['state']['touchList']['revision'])
    assert result['canvasOps'] == 7
    stored = store.design_job(job['design_id'])['state']['canvasScene']
    assert [item['id'] for item in stored['nodes']][0] == 'owner-1', 'node cũ vẫn nguyên chỗ cũ'
    assert [item['id'] for item in stored['nodes']][1:3] == ['seed-workspace', 'seed-screen']


# ------------------------------------------------- duyệt danh sách chạm ⇒ gieo


def test_approving_the_touch_list_seeds_the_canvas_through_canvas_draw(harness):
    store, runtime, sid, executor = harness
    job = save_brief(store, sid, open_run(runtime, store, sid))
    result = approve(runtime, store, sid, job, touch_items(2))

    # 2 thẻ neo + 1 nét, rồi mỗi mục chạm: 1 thẻ + 1 nét ⇒ 7 op cho 2 mục.
    assert result['canvasOps'] == 7 and result['canvasRejected'] == 0
    stored = store.design_job(job['design_id'])['state']
    assert [item['id'] for item in stored['canvasScene']['nodes']][:2] == ['seed-workspace', 'seed-screen']
    assert len(stored['canvasScene']['connectors']) == 3 and stored['canvasSeq'] == 1
    assert stored['phase'] == 'drawing'

    # Thứ tự sự kiện: duyệt xong (`design_scope`) rồi mới có nét vẽ (`design_canvas`) — giao diện đọc
    # theo thứ tự đó để không vẽ cảnh gieo lên một run vừa đổi revision.
    kinds = [row['type'] for row in events(store, sid)]
    assert kinds.index('design_scope') < kinds.index('design_canvas')
    assert [row['type'] for row in events(store, sid, 'design_canvas')] == ['design_canvas']
    canvas_event = events(store, sid, 'design_canvas')[0]['data']
    assert canvas_event['actor'] == 'agent' and canvas_event['sceneVersion'] == 1
    assert len(canvas_event['ops']) == 7 and len(canvas_event['scene']['nodes']) == 4


def test_an_empty_touch_list_still_gets_the_two_anchor_cards(harness):
    """Danh sách chạm rỗng vẫn có khung dự án + màn hình đích: canvas không được là ngõ cụt."""
    store, runtime, sid, executor = harness
    job = save_brief(store, sid, open_run(runtime, store, sid))
    store_touch_list(runtime, store, sid, job, [])
    live = store.design_job(job['design_id'])

    created = [op['node']['id'] for op in design_runtime.canvas_seed_ops(live)
               if op['type'] == 'CREATE_NODE']
    assert created == ['seed-workspace', 'seed-screen']
    assert executor.calls == [], 'hàm gieo là THUẦN: không chạm box'


# --------------------------------------------------------------- payload run


def test_detail_payload_carries_the_scene_and_the_list_payload_does_not(harness):
    store, runtime, sid, executor = harness
    job = save_brief(store, sid, open_run(runtime, store, sid))
    approve(runtime, store, sid, job, touch_items(1))
    live = store.design_job(job['design_id'])

    detail = design_runtime.design_run_payload(live, with_canvas=True)
    assert detail['canvasSeq'] == 1
    assert detail['canvasScene'] == live['state']['canvasScene'], 'payload trả ĐÚNG cảnh đang có'
    assert [item['id'] for item in detail['canvasScene']['nodes']][:2] == ['seed-workspace', 'seed-screen']

    listed = design_runtime.design_run_payload(live)
    assert 'canvasScene' not in listed and 'canvasSeq' not in listed, (
        'danh sách run bị gọi lại mỗi vòng đồng bộ — không mang theo cảnh')
    assert listed['designId'] == live['design_id'] and listed['phase'] == 'drawing'


def test_design_prompt_block_puts_the_canvas_in_the_lead_s_job(harness):
    """Luật vẽ phải nằm trong khối mode — trước đây `canvas_draw` chỉ hiện trong schema công cụ."""
    store, runtime, sid, executor = harness
    open_run(runtime, store, sid)
    block = runtime.turn_profile(store.get(sid))['promptBlock']
    assert 'ACTIVE MODE: DESIGN' in block
    assert 'canvas_draw' in block, 'Design Lead phải được NHẮC vẽ lên canvas, không chỉ có schema'
    assert 'canvas is the shared surface' in block
    assert 'seeds it from the approved' in block, 'nói rõ canvas được gieo sẵn từ danh sách chạm đã duyệt'


# ------------------------------------------------------------------ tuyến HTTP


def test_approve_route_pins_the_seeded_scene_to_the_box(harness):
    store, runtime, sid, executor = harness
    job = save_brief(store, sid, open_run(runtime, store, sid))
    store_touch_list(runtime, store, sid, job, touch_items(1))
    live = store.design_job(job['design_id'])
    revision = live['state']['touchList']['revision']

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                url = str(server.make_url(f"/api/agent/design/runs/{job['design_id']}/touch-list/approve"))
                async with http.post(url, json={'revision': revision}) as resp:
                    assert resp.status == 200
                    return await resp.json()

    result = asyncio.run(run())
    assert result['canvasOps'] == 5, 'một mục chạm: 2 thẻ neo + 1 thẻ chạm + 2 nét'
    writes = [call for call in executor.calls if call[0] == 'file_write']
    assert len(writes) == 1, 'cảnh gieo ghim xuống box ĐÚNG MỘT lần'
    path = writes[0][1]['path']
    assert path.startswith('.design/') and path.endswith('/canvas.v1.json')
    pinned = json.loads(writes[0][1]['content'])
    assert [item['id'] for item in pinned['nodes']][:2] == ['seed-workspace', 'seed-screen']


def test_approve_route_rewrites_the_snapshot_even_when_the_scene_is_already_drawn(harness):
    """Ảnh chụp phải sống sót qua một lần ghi hỏng: duyệt lại (không op nào) vẫn ghim lại cảnh."""
    store, runtime, sid, executor = harness
    job = save_brief(store, sid, open_run(runtime, store, sid))
    store_touch_list(runtime, store, sid, job, touch_items(1))
    live = store.design_job(job['design_id'])
    revision = live['state']['touchList']['revision']
    # Cảnh ĐÃ có (đúng cảnh một lần gieo trước để lại: neo `seed-workspace` ⇒ lần này không gieo lại).
    assert design_runtime.canvas_scene_has_nodes(live) is False
    design_runtime.design_touch_list_approve(runtime, sid, live, revision)
    executor.calls.clear()

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                url = str(server.make_url(f"/api/agent/design/runs/{job['design_id']}/touch-list/approve"))
                async with http.post(url, json={'revision': revision}) as resp:
                    assert resp.status == 200
                    return await resp.json()

    result = asyncio.run(run())
    assert 'canvasOps' not in result, 'cảnh đã có neo gieo ⇒ lượt duyệt này không thêm op nào'
    writes = [call for call in executor.calls if call[0] == 'file_write']
    assert len(writes) == 1, 'cảnh có nội dung ⇒ ảnh chụp vẫn được ghim lại'
    assert writes[0][1]['path'].endswith('/canvas.v1.json')


def test_directive_route_accepts_a_whole_canvas_note_without_a_target_node(harness):
    store, runtime, sid, executor = harness
    job = open_run(runtime, store, sid)

    async def run():
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(headers=HEADERS) as http:
                url = str(server.make_url(f'/api/agent/sessions/{sid}/canvas'))
                body = {'protocol': 'boxfox.canvas.v1', 'type': 'directive', 'targetNodeId': '',
                        'instruction': 'vẽ bản đồ dự án lên canvas trống'}
                async with http.post(url, json=body) as resp:
                    assert resp.status == 200
                    accepted = await resp.json()
                # Thiếu HẲN lời dặn thì vẫn phải bị chối: nới `target` không có nghĩa nới `instruction`.
                async with http.post(url, json={**body, 'instruction': '   '}) as resp:
                    rejected = resp.status
                block = runtime.turn_profile(store.get(sid))['promptBlock']
            return accepted, rejected, block

    accepted, rejected, block = asyncio.run(run())
    assert accepted == {'accepted': True}
    assert rejected == 400
    # Chỉ thị không neo node đọc được thành "cả canvas", KHÔNG thành "node  ()".
    assert 'vẽ bản đồ dự án lên canvas trống' in block
    assert 'node  (' not in block
    assert 'whole canvas: vẽ bản đồ dự án lên canvas trống' in block
