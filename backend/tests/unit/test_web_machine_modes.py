import asyncio
from functools import wraps
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.machine_router import MachineError, MachineRegistry, attach, register_routes


def async_test(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


@pytest.fixture
def harness(tmp_path):
    legacy = type('Legacy', (), {'visual_lock': asyncio.Lock(), 'execute': AsyncMock(return_value={'content': 'docker'}),
                                'cleanup': AsyncMock()})()
    runtime = HarnessRuntime(SessionStore(tmp_path / 'sessions.sqlite'), legacy)
    attach(runtime, tmp_path / 'profile')
    yield runtime, legacy
    runtime.store.close()


def create(runtime, **values):
    return runtime.create({'skills': [], 'subagents': [], **values})


def project(runtime, tmp_path):
    root = tmp_path / 'Dự án có dấu'
    root.mkdir()
    (root / 'hello.txt').write_bytes('Nội dung tiếng Việt\r\n'.encode('utf-8'))
    return runtime.machine_registry.register(str(root))


def test_default_and_old_sessions_stay_docker(harness, tmp_path):
    rt, _ = harness
    old = rt.store.create({}, 'orchestrator')
    p = project(rt, tmp_path)
    rt.machine_registry.update({'revision': 1, 'mode': 'host', 'projectId': p['id']})
    assert rt.machine_registry.binding(old['id'])['mode'] == 'docker'
    assert create(rt)['config']['machineBinding']['workspace'] == p['path']


def test_projects_are_canonical_and_stable(harness, tmp_path):
    rt, _ = harness
    p = project(rt, tmp_path)
    assert rt.machine_registry.register(str(Path(p['path']) / '.'))['id'] == p['id']
    assert len(rt.machine_registry.state()['projects']) == 1
    assert p['trusted'] is False


def test_named_project_deduplicates_folder_without_changing_existing_name(harness, tmp_path):
    rt, _ = harness
    root = tmp_path / 'source'
    root.mkdir()
    p = rt.machine_registry.register(str(root), 'Dự án của tôi')
    assert p['name'] == 'Dự án của tôi' and not p['trusted']
    assert rt.machine_registry.register(str(root), 'Tên khác')['name'] == 'Dự án của tôi'
    with pytest.raises(MachineError):
        rt.machine_registry.register(str(root), '\nInvalid')


@async_test
async def test_select_only_picker_does_not_register_or_change_configuration(harness, tmp_path, monkeypatch):
    rt, _ = harness
    monkeypatch.setattr('agentbox.sandbox.machine_router.pick_folder', lambda: {'path': str(tmp_path)})
    app = web.Application()
    register_routes(app, rt)
    async with TestClient(TestServer(app)) as client:
        response = await client.post('/api/agent/machines/pick-folder', json={'selectOnly': True})
        assert await response.json() == {'path': str(tmp_path)}
        assert rt.machine_registry.state()['projects'] == []
        assert rt.machine_registry.state()['revision'] == 1


def test_child_cannot_change_environment(harness, tmp_path):
    rt, _ = harness
    p = project(rt, tmp_path)
    parent = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    child = rt.create({'skills': [], 'subagents': [], 'machineSelection': {'mode': 'docker'}}, parent_id=parent['id'], role='explore')
    assert child['config']['machineBinding'] == parent['config']['machineBinding']
    assert 'ACTIVE EXECUTION ENVIRONMENT: IDE / HOST' in child['messages'][0]['content']


@pytest.mark.parametrize('mode', ['cloud', 'HOST', None, 'invalid'])
def test_invalid_mode_rejected(harness, mode):
    rt, _ = harness
    with pytest.raises(MachineError):
        rt.machine_registry.update({'revision': 1, 'mode': mode})


def test_stale_revision_conflicts(harness):
    rt, _ = harness
    rt.machine_registry.update({'revision': 1, 'mode': 'host'})
    with pytest.raises(MachineError) as exc:
        rt.machine_registry.update({'revision': 1, 'mode': 'docker'})
    assert exc.value.status == 409


def test_registry_survives_restart(harness, tmp_path):
    rt, _ = harness
    p = project(rt, tmp_path)
    rt.machine_registry.update({'revision': 1, 'mode': 'host', 'projectId': p['id']})
    second = SessionStore(tmp_path / 'sessions.sqlite')
    try:
        state = MachineRegistry(second).state()
        assert state['mode'] == 'host' and state['projectId'] == p['id'] and state['revision'] == 2
    finally:
        second.close()


@async_test
async def test_host_read_never_calls_docker(harness, tmp_path):
    rt, legacy = harness
    p = project(rt, tmp_path)
    session = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    result = await rt.executor.execute('file_read', {'path': 'hello.txt'}, session['id'])
    assert 'tiếng Việt' in result['content']
    legacy.execute.assert_not_called()


@async_test
async def test_docker_still_routes_to_existing_executor(harness):
    rt, legacy = harness
    session = create(rt)
    assert (await rt.executor.execute('file_read', {'path': 'hello.txt'}, session['id']))['content'] == 'docker'
    legacy.execute.assert_awaited_once()


@async_test
async def test_no_project_and_untrusted_mutation_fail_closed(harness, tmp_path):
    rt, legacy = harness
    no_project = create(rt, machineSelection={'mode': 'host'})
    assert (await rt.executor.execute('file_read', {'path': 'hello.txt'}, no_project['id']))['errorCode'] == 'PROJECT_REQUIRED'
    p = project(rt, tmp_path)
    session = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    assert (await rt.executor.execute('file_write', {'path': 'bad.txt', 'content': 'x'}, session['id']))['errorCode'] == 'PROJECT_TRUST_REQUIRED'
    assert not (Path(p['path']) / 'bad.txt').exists()
    legacy.execute.assert_not_called()


@async_test
async def test_host_unsupported_does_not_fall_back(harness, tmp_path):
    rt, legacy = harness
    p = project(rt, tmp_path)
    rt.machine_registry.trust(p['id'], True)
    session = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    assert (await rt.executor.execute('write_plan', {}, session['id']))['errorCode'] == 'UNSUPPORTED_IN_HOST_MODE'
    assert (await rt.executor.execute('file_read', {'path': '../outside'}, session['id']))['errorCode'] == 'PATH_OUTSIDE_WORKSPACE'
    assert (await rt.executor.execute('file_read', {'path': 'hello.txt'}, session['id'], root='../outside'))['errorCode'] == 'PATH_OUTSIDE_WORKSPACE'
    legacy.execute.assert_not_called()


@async_test
async def test_ui_roundtrip_conflicts_trust_and_unicode(harness, tmp_path):
    rt, _ = harness
    p = project(rt, tmp_path)
    app = web.Application()
    register_routes(app, rt)
    async with TestClient(TestServer(app)) as client:
        base = '/api/agent/machines/projects/' + p['id']
        assert (await client.get(base + '/files')).status == 200
        file = await (await client.get(base + '/file?path=hello.txt')).json()
        assert file['content'] == 'Nội dung tiếng Việt\r\n'
        denied = await client.post(base + '/file', json={**file, 'path': 'hello.txt', 'content': 'Mới'})
        assert denied.status == 403
        await client.post('/api/agent/machines/trust', json={'projectId': p['id'], 'trusted': True})
        saved = await client.post(base + '/file', json={**file, 'path': 'hello.txt', 'content': 'Mới\r\n'})
        assert saved.status == 200
        stale = await client.post(base + '/file', json={**file, 'path': 'hello.txt', 'content': 'Sai'})
        assert stale.status == 409
        assert (Path(p['path']) / 'hello.txt').read_bytes() == 'Mới\r\n'.encode('utf-8')
        escape = await client.get(base + '/file?path=../sessions.sqlite')
        assert escape.status == 400
        consent = await client.post('/api/agent/machines/screen', json={})
        assert consent.status in (403, 409)  # Native provider may be unavailable on CI.


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Native Windows command probe')
@async_test
async def test_real_windows_command_uses_selected_folder(harness, tmp_path):
    rt, _ = harness
    p = project(rt, tmp_path)
    app = web.Application()
    register_routes(app, rt)
    async with TestClient(TestServer(app)) as client:
        base = '/api/agent/machines/projects/' + p['id']
        denied = await client.post(base + '/command', json={'command': 'Write-Output BOXFOX_HOST_OK'})
        assert denied.status == 403
        rt.machine_registry.trust(p['id'], True)
        command = 'Write-Output BOXFOX_HOST_OK; (Get-Location).Path'
        response = await client.post(base + '/command', json={'command': command})
        output = await response.json()
        assert response.status == 200 and output['exit_code'] == 0, output
        assert 'BOXFOX_HOST_OK' in output['content']
        assert p['path'].casefold() in output['content'].casefold()
        blocked = await client.post(base + '/command', json={'command': 'shutdown /r'})
        assert blocked.status == 403


@async_test
async def test_trust_revocation_is_checked_after_executor_cache(harness, tmp_path):
    rt, legacy = harness
    p = project(rt, tmp_path)
    session = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    await rt.executor.execute('file_read', {'path': 'hello.txt'}, session['id'])
    rt.machine_registry.trust(p['id'], True)
    rt.executor.runtime.decision = AsyncMock(return_value={'status': 'approved', 'choice': 'approve'})
    assert not (await rt.executor.execute('file_write', {'path': 'x.txt', 'content': 'Một'}, session['id'])).get('is_error')
    rt.machine_registry.trust(p['id'], False)
    assert (await rt.executor.execute('file_write', {'path': 'x.txt', 'content': 'Hai'}, session['id']))['errorCode'] == 'PROJECT_TRUST_REQUIRED'
    assert (Path(p['path']) / 'x.txt').read_text(encoding='utf-8') == 'Một'
    legacy.execute.assert_not_called()
