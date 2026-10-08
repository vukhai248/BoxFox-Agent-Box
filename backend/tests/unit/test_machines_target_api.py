"""E — ba route đích CUA của phiên: `GET|PUT|DELETE /api/agent/machines/target`.

Route là hợp đồng giữa backend và panel, nên bài kiểm đi qua HTTP thật (`aiohttp` test client) chứ
không gọi hàm nội bộ. Cái được kiểm: `consent`, `expectedRevision`, hai dạng thân yêu cầu (phẳng và
lồng), cửa sổ đã chết, phạm vi `workspace` chặn đích "cả máy", phiên Docker bị từ chối, và việc ghi
đích của phiên con đi vào phiên gốc.
"""
import asyncio
from functools import wraps
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.machine_router import attach, register_routes


def async_test(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


WINDOW = {'windowId': 777, 'zOrder': 0, 'title': 'Untitled - Notepad', 'windowClass': 'Notepad',
          'pid': 4242, 'processName': 'notepad.exe', 'position': {'x': 10, 'y': 20},
          'size': {'width': 640, 'height': 480}, 'dpi': 96}


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_PERMISSION_MODE', 'ask')
    monkeypatch.setenv('BOXFOX_PERMISSION_SCOPE', 'machine')
    legacy = type('Legacy', (), {'visual_lock': asyncio.Lock(),
                                 'execute': AsyncMock(return_value={'content': 'docker'}),
                                 'cleanup': AsyncMock()})()
    runtime = HarnessRuntime(SessionStore(tmp_path / 'sessions.sqlite'), legacy)
    attach(runtime, tmp_path / 'profile')
    monkeypatch.setattr('agentbox.sandbox.win.capture.list_windows',
                        lambda platform=None, include_minimized=False: [dict(WINDOW)])
    yield runtime
    runtime.store.close()


def host_session(runtime, tmp_path, **values):
    root = tmp_path / 'Dự án'
    root.mkdir(exist_ok=True)
    project = runtime.machine_registry.register(str(root))
    runtime.machine_registry.update({'revision': runtime.machine_registry.state()['revision'],
                                     'mode': 'host', 'projectId': project['id']})
    return runtime.create({'skills': [], 'subagents': [], **values})


async def with_client(runtime, fn):
    app = web.Application()
    register_routes(app, runtime)
    async with TestClient(TestServer(app)) as client:
        return await fn(client)


def get_target(client, sid):
    return client.get('/api/agent/machines/target', params={'sessionId': sid})


@async_test
async def test_get_reports_the_empty_target_with_the_scope_and_capability(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        response = await get_target(client, session['id'])
        assert response.status == 200
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['target'] is None and payload['effective'] is None
    assert payload['requestedBy'] is None and payload['revision'] == 0
    assert payload['scope'] == 'machine' and payload['machineAllowed'] is True
    assert payload['cuaEnabled'] is False          # Linux: không có DesktopControl
    assert payload['activeWindow'] is None and payload['updatedAt'] is None


@async_test
async def test_put_a_window_target_then_read_it_back(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'kind': 'window',
                                          'windowId': 777, 'pid': 4242, 'consent': True})
        assert response.status == 200
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['target']['windowId'] == 777
    assert payload['target']['processName'] == 'notepad.exe'
    assert payload['requestedBy'] == 'user' and payload['revision'] == 1
    assert payload['effective']['windowId'] == 777
    assert payload['updatedAt'] and payload['updatedAt'].endswith('Z')


@async_test
async def test_put_accepts_the_nested_target_shape_too(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'consent': True,
                                          'target': {'kind': 'window', 'windowId': 777}})
        assert response.status == 200
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['target']['windowId'] == 777


@async_test
async def test_put_without_consent_is_refused(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'kind': 'machine'})
        assert response.status == 403
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'TARGET_CONSENT_REQUIRED'


@async_test
async def test_put_with_an_unknown_kind_is_a_400(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'consent': True,
                                          'kind': 'everything'})
        assert response.status == 400
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'TARGET_KIND_INVALID'


@async_test
async def test_put_a_window_that_is_gone_is_refused(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'consent': True,
                                          'kind': 'window', 'windowId': 999})
        assert response.status == 409
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'TARGET_UNKNOWN'


@async_test
async def test_put_a_window_whose_pid_changed_is_refused(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'consent': True,
                                          'kind': 'window', 'windowId': 777, 'pid': 1})
        assert response.status == 409
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'TARGET_CHANGED'


@async_test
async def test_a_stale_expected_revision_is_refused(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        first = await client.put('/api/agent/machines/target',
                                 json={'sessionId': session['id'], 'consent': True,
                                       'kind': 'machine'})
        assert first.status == 200
        stale = await client.put('/api/agent/machines/target',
                                 json={'sessionId': session['id'], 'consent': True,
                                       'kind': 'machine', 'expectedRevision': 0})
        assert stale.status == 409
        return await stale.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'TARGET_REVISION_CONFLICT'


@async_test
async def test_the_machine_target_needs_the_machine_scope(harness, tmp_path, monkeypatch):
    session = host_session(harness, tmp_path)
    monkeypatch.setenv('BOXFOX_PERMISSION_SCOPE', 'workspace')

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'consent': True,
                                          'kind': 'machine'})
        assert response.status == 403
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'CUA_MACHINE_SCOPE_REQUIRED'


@async_test
async def test_delete_clears_the_target_and_bumps_the_revision(harness, tmp_path):
    session = host_session(harness, tmp_path)

    async def body(client):
        await client.put('/api/agent/machines/target',
                         json={'sessionId': session['id'], 'consent': True, 'kind': 'machine'})
        response = await client.delete('/api/agent/machines/target',
                                       params={'sessionId': session['id']})
        assert response.status == 200
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['target'] is None and payload['revision'] == 2


@async_test
async def test_a_child_session_writes_the_target_to_the_root(harness, tmp_path):
    parent = host_session(harness, tmp_path)
    child = harness.store.create({}, 'subagent', parent['id'])

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': child['id'], 'consent': True,
                                          'kind': 'machine'})
        assert response.status == 200
        read = await get_target(client, parent['id'])
        return await response.json(), await read.json()

    written, read_back = await with_client(harness, body)
    assert written['target'] == {'kind': 'machine'}
    assert read_back['target'] == {'kind': 'machine'}
    assert read_back['inheritedFrom'] is None


@async_test
async def test_a_docker_session_cannot_have_a_target(harness, tmp_path):
    session = harness.create({'skills': [], 'subagents': []})

    async def body(client):
        response = await client.put('/api/agent/machines/target',
                                    json={'sessionId': session['id'], 'consent': True,
                                          'kind': 'machine'})
        assert response.status == 409
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'HOST_SESSION_REQUIRED'


@async_test
async def test_an_unknown_session_is_a_404(harness, tmp_path):
    async def body(client):
        response = await get_target(client, 'khong-co-phien-nay')
        assert response.status == 404
        return await response.json()

    payload = await with_client(harness, body)
    assert payload['code'] == 'SESSION_NOT_FOUND'


@async_test
async def test_the_window_list_for_the_picker_hides_minimized_windows(harness, tmp_path):
    calls = []

    def fake_list_windows(platform=None, include_minimized=False):
        calls.append(include_minimized)
        return [dict(WINDOW)]

    import agentbox.sandbox.win.capture as capture_module
    original = capture_module.list_windows
    capture_module.list_windows = fake_list_windows
    try:
        async def body(client):
            response = await client.get('/api/agent/machines/screen')
            assert response.status == 200
            return await response.json()

        payload = await with_client(harness, body)
    finally:
        capture_module.list_windows = original
    assert payload['windows'][0]['windowId'] == 777
    assert calls == [False]
