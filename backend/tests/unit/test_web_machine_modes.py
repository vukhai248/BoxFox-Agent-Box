import asyncio
from functools import wraps
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from agentbox.agent_core import permissions as permissions_module
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


def test_host_process_bootstraps_host_configuration_and_workspace(tmp_path):
    """Bản desktop mở ra là host: cấu hình mặc định và folder mặc định phải có sẵn.

    Trước đây CSDL mới luôn ghi `docker`, nên tiến trình host hiện "Docker" trong khi mọi công cụ
    chạy trên máy thật (DA3). Folder mặc định chưa tồn tại thì tạo — cài xong là có chỗ làm việc.
    """
    store = SessionStore(tmp_path / 'sessions.sqlite')
    workspace = tmp_path / 'BoxFox' / 'workspace'
    registry = MachineRegistry(store, default_mode='host', default_workspace=workspace)
    state = registry.state()
    assert state['mode'] == 'host'
    assert state['projectId'] and workspace.is_dir()
    assert [p for p in state['projects'] if p['id'] == state['projectId']][0]['trusted'] is False
    # Phiên cũ không có binding: tiến trình host không có box nào để giữ, nên đi theo cấu hình.
    legacy_session = store.create({}, 'orchestrator')
    assert registry.binding(legacy_session['id'])['mode'] == 'host'
    # CSDL đã có cấu hình thì không bị đổi (người dùng đã chọn thì tôn trọng).
    again = MachineRegistry(store, default_mode='host', default_workspace=tmp_path / 'khác')
    assert again.state()['projectId'] == state['projectId']
    store.close()


def test_machine_plans_route_serves_the_selected_folder(harness, tmp_path):
    """`/api/agent/machines/projects/{pid}/plans` — cùng payload với `/__box/plans` của box."""
    rt, _ = harness
    p = project(rt, tmp_path)
    room = Path(p['path']) / '.plans'
    room.mkdir()
    (room / 'v1-login-page.md').write_text('# Kế hoạch\n', encoding='utf-8')
    app = web.Application()
    register_routes(app, rt)

    async def run():
        async with TestClient(TestServer(app)) as client:
            base = '/api/agent/machines/projects/' + p['id']
            manifest = await client.get(base + '/plans')
            payload = await manifest.json()
            assert manifest.status == 200
            assert payload['plans'][0]['identity'] == 'login-page'
            content = await client.get(base + '/plans/content',
                                       params={'identity': 'login-page', 'version': '1'})
            assert (await content.json())['markdown'] == '# Kế hoạch\n'
            missing = await client.get(base + '/plans/content',
                                       params={'identity': 'login-page', 'version': '9'})
            assert missing.status == 404
            assert (await missing.json())['code'] == 'PLAN_REQUEST_INVALID'

    asyncio.run(run())


def test_session_request_reads_plans_from_its_own_folder(harness, tmp_path):
    """Phiên host đọc `.plans` trong folder của chính nó, không nhắm vào box (DA4)."""
    rt, legacy = harness
    p = project(rt, tmp_path)
    room = Path(p['path']) / '.plans'
    room.mkdir()
    (room / 'v1-login-page.md').write_text('# Trong folder\n', encoding='utf-8')
    session = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    legacy.request = AsyncMock(side_effect=AssertionError('host mode không được gọi box'))

    async def run():
        index = await rt.executor.request('/__box/plans/index', session=session['id'])
        assert index['plans'][0]['identity'] == 'login-page'
        document = await rt.executor.request('/__box/plans/content?identity=login-page&version=1',
                                             session=session['id'])
        assert document['markdown'] == '# Trong folder\n'

    asyncio.run(run())
    legacy.request.assert_not_called()  # không lượt nào chạm box


def test_docker_sessions_keep_reading_the_box(harness, tmp_path):
    """Phiên Docker (và chỗ gọi cũ không truyền phiên) vẫn đi nguyên đường box."""
    rt, legacy = harness
    legacy.request = AsyncMock(return_value={'plans': [], 'ignoredCount': 0, 'warnings': []})
    session = create(rt)

    async def run():
        assert await rt.executor.request('/__box/plans/index', session=session['id']) == {
            'plans': [], 'ignoredCount': 0, 'warnings': []}
        await rt.executor.request('/__box/plans/index')

    asyncio.run(run())
    assert legacy.request.await_count == 2


# ---------------------------------------------------------------- nút chọn quyền ở thanh chat

def test_host_session_policy_follows_the_user_layer_mode(harness, tmp_path, monkeypatch):
    """Mức cho phép của phiên host đọc từ tầng `user` — nơi nút ở thanh chat và tab Settings ghi vào.

    Trước đây policy của phiên bị ghim `mode='ask'`, nên đổi mức ở giao diện xong vẫn bị hỏi.
    """
    rt, _ = harness
    home = tmp_path / 'home'
    (home / '.boxfox').mkdir(parents=True)
    (home / '.boxfox' / 'settings.json').write_text(json.dumps({'mode': 'auto'}), encoding='utf-8')
    monkeypatch.setenv('BOXFOX_HOME_DIR', str(home))
    p = project(rt, tmp_path)
    session = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    executor, _project = rt.executor.host(session['id'])
    assert executor.policy.mode_value() == 'auto'


@async_test
async def test_chat_bar_mode_change_applies_to_the_next_tool_call(harness, tmp_path, monkeypatch):
    """Đổi mức giữa hai lượt: lượt sau không được dùng bản luật cũ (policy đọc lại từ đĩa)."""
    rt, _ = harness
    home = tmp_path / 'home'
    settings = home / '.boxfox' / 'settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({'mode': 'plan'}), encoding='utf-8')
    monkeypatch.setenv('BOXFOX_HOME_DIR', str(home))
    p = project(rt, tmp_path)
    rt.machine_registry.trust(p['id'], True)
    session = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})

    denied = await rt.executor.execute('file_write', {'path': 'plan.txt', 'content': 'x'}, session['id'])
    assert denied['errorCode'] == 'PERMISSION_DENIED'
    assert not (Path(p['path']) / 'plan.txt').exists()

    settings.write_text(json.dumps({'mode': 'auto'}), encoding='utf-8')
    allowed = await rt.executor.execute('file_write', {'path': 'auto.txt', 'content': 'x'}, session['id'])
    assert allowed.get('errorCode') is None
    assert (Path(p['path']) / 'auto.txt').read_text(encoding='utf-8') == 'x'


def test_permissions_policy_answers_from_the_active_project(harness, tmp_path, monkeypatch):
    """Tiến trình docker + máy cấu hình host: `permissions_policy()` phải dựng được policy của folder."""
    rt, _ = harness
    home = tmp_path / 'home'
    (home / '.boxfox').mkdir(parents=True)
    monkeypatch.setenv('BOXFOX_HOME_DIR', str(home))
    p = project(rt, tmp_path)
    rt.machine_registry.update({'revision': 1, 'mode': 'host', 'projectId': p['id']})
    policy = rt.executor.permissions_policy()
    assert policy.workspace == p['path']
    assert policy.mode_value() == 'ask'      # mặc định khi chưa ai đổi


def test_permissions_policy_survives_without_a_project(harness):
    """Chưa chọn folder: vẫn trả lời được (policy rỗng), không ném ra ngoài route."""
    rt, _ = harness
    assert rt.executor.permissions_policy().workspace == ''


def test_two_sessions_in_one_project_keep_separate_session_rules(harness, tmp_path, monkeypatch):
    """`session_rules` là ranh giới PHIÊN: cho phép ở phiên A không được tự cho phép ở phiên B.

    Hai phiên cùng folder phải dùng hai đối tượng policy, nếu không một lần "cho phép trong phiên"
    sẽ rò sang phiên khác (và sang cả policy của route).
    """
    rt, _ = harness
    monkeypatch.setenv('BOXFOX_HOME_DIR', str(tmp_path / 'home'))
    p = project(rt, tmp_path)
    first = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    second = create(rt, machineSelection={'mode': 'host', 'projectId': p['id']})
    a, _ = rt.executor.host(first['id'])
    b, _ = rt.executor.host(second['id'])
    assert a.policy is not b.policy
    assert a.policy is not rt.executor.policy_for(p)
    key = a.policy.session_key('terminal_exec', {'command': 'ls'}, cwd=p['path'])
    a.policy.remember(key, permissions_module.allow('', 'user'), 'session')
    assert key in a.policy.session_rules
    assert key not in b.policy.session_rules
