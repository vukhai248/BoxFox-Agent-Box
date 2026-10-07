"""API quyền (H4): `BOXFOX_EXECUTION_MODE`, bốn route, khối `execution` của health.

Mọi ca gọi route THẬT qua aiohttp trên executor giả hoặc `HostExecutor` trong `tmp_path`; không ca
nào chạm máy thật, không ca nào ghi vào `~/.boxfox` hay hồ sơ thật.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import permissions as perms
from agentbox.api import server as server_module
from agentbox.api.server import build_executor, create_app, execution_mode
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.host_executor import HostExecutor

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class FixtureExecutor:
    """Executor kiểu docker: có `execute`/`cleanup` nhưng KHÔNG có `policy`."""

    async def execute(self, name, args, sid):
        return {'ok': True}

    async def cleanup(self, sid):
        return None


def host_executor(tmp_path):
    workspace = tmp_path / 'ws'
    workspace.mkdir(exist_ok=True)
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    install = tmp_path / 'install'
    install.mkdir(exist_ok=True)
    env = dict(os.environ)
    env['BOXFOX_AGENT_DATA_DIR'] = str(profile)
    # Chặn tuyệt đối việc ghi vào `~/.boxfox` thật: mọi tầng đều nằm trong tmp_path.
    env['BOXFOX_HOME_DIR'] = str(home)
    env['BOXFOX_INSTALL_DIR'] = str(install)
    policy = perms.PermissionPolicy(str(workspace), profile_dir=profile, env=env)
    return HostExecutor(str(workspace), policy=policy, platform='posix', env=env)


def run(tmp_path, coro_factory, executor=None):
    async def main():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, executor if executor is not None else FixtureExecutor(), None)
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                results = await coro_factory(client, runtime)
        store.close()
        return results

    return asyncio.run(main())


# ------------------------------------------------------------------ chọn chế độ

def test_execution_mode_defaults_to_docker():
    assert execution_mode({}) == 'docker'
    assert execution_mode({'BOXFOX_EXECUTION_MODE': 'host'}) == 'host'
    assert execution_mode({'BOXFOX_EXECUTION_MODE': 'HOST'}) == 'host'
    assert execution_mode({'BOXFOX_EXECUTION_MODE': 'lung-tung'}) == 'docker'


def test_build_executor_returns_the_docker_executor_by_default(tmp_path):
    executor = build_executor(tmp_path, env={})
    assert type(executor).__name__ == 'SandboxExecutor'


def test_build_executor_returns_a_host_executor_with_a_policy(tmp_path):
    executor = build_executor(tmp_path, env={'BOXFOX_EXECUTION_MODE': 'host',
                                             'BOXFOX_HOST_WORKSPACE': str(tmp_path / 'ws'),
                                             'BOXFOX_AGENT_DATA_DIR': str(tmp_path / 'profile')})
    assert isinstance(executor, HostExecutor)
    assert isinstance(executor.policy, perms.PermissionPolicy)
    assert Path(executor.policy.workspace).resolve() == (tmp_path / 'ws').resolve()


def test_build_executor_refuses_cloud_loudly(tmp_path):
    try:
        build_executor(tmp_path, env={'BOXFOX_EXECUTION_MODE': 'cloud'})
    except RuntimeError as exc:
        assert 'cloud' in str(exc).lower()
    else:
        raise AssertionError('`cloud` chưa cài đặt — phải báo lỗi rõ, không im lặng rơi về docker')


# ------------------------------------------------------------------ health

def test_health_reports_docker_mode_without_a_policy(tmp_path):
    async def scenario(client, runtime):
        response = await client.get('/api/agent/health', headers={'Host': '127.0.0.1:3102'})
        return await response.json()

    payload = run(tmp_path, scenario)
    assert payload['execution']['mode'] == 'docker'
    assert payload['execution']['policy'] is False
    assert payload['execution']['scope'] is None


def test_health_reports_host_mode_and_hardline_hits(tmp_path, monkeypatch):
    monkeypatch.setenv('BOXFOX_EXECUTION_MODE', 'host')
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        executor.policy.mode = 'trusted'
        await executor.execute('terminal_exec', {'command': 'format C:'}, 's1')
        response = await client.get('/api/agent/health', headers={'Host': '127.0.0.1:3102'})
        return await response.json()

    payload = run(tmp_path, scenario, executor=executor)
    execution = payload['execution']
    assert execution['mode'] == 'host'
    assert execution['policy'] is True
    assert execution['permissionMode'] == 'trusted'
    assert execution['hardlineHits'] == 1
    assert execution['lease'] is None


# ------------------------------------------------------------------ GET/PUT

def test_get_permissions_returns_the_snapshot(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.get('/api/agent/permissions', headers=HEADERS)
        return response.status, await response.json()

    status, payload = run(tmp_path, scenario, executor=executor)
    assert status == 200
    assert payload['mode'] == 'ask'
    assert payload['scope'] in perms.SCOPES
    assert set(payload['rules']) == {'allow', 'ask', 'deny'}
    assert payload['execution']['mode'] == 'host'


def test_put_permissions_writes_the_user_layer(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.put('/api/agent/permissions', headers=HEADERS,
                                    json={'mode': 'auto', 'scope': 'workspace'})
        return response.status, await response.json()

    status, payload = run(tmp_path, scenario, executor=executor)
    assert status == 200
    assert payload['mode'] == 'auto' and payload['scope'] == 'workspace'
    saved = executor.policy.paths[perms.LAYER_USER]
    assert saved.is_file()
    assert '"auto"' in saved.read_text(encoding='utf-8')


def test_put_permissions_rejects_an_unknown_mode(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.put('/api/agent/permissions', headers=HEADERS, json={'mode': 'yolo'})
        return response.status, await response.json()

    status, payload = run(tmp_path, scenario, executor=executor)
    assert status == 400
    assert payload['code'] == 'PERMISSION_MODE_UNKNOWN'


def test_put_permissions_needs_a_change(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.put('/api/agent/permissions', headers=HEADERS, json={})
        return (response.status,)

    assert run(tmp_path, scenario, executor=executor)[0] == 400


# ------------------------------------------------------------------ decide

def test_decide_returns_ask_with_a_reason(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                     json={'tool': 'terminal_exec', 'args': {'command': 'npm test'},
                                           'sessionId': 's1'})
        return await response.json()

    payload = run(tmp_path, scenario, executor=executor)
    assert payload['outcome'] == 'ask'
    assert payload['reason']


def test_decide_allow_always_saves_a_rule_and_get_rules_shows_it(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        saved = await (await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                         json={'tool': 'terminal_exec', 'args': {'command': 'npm test'},
                                               'sessionId': 's1', 'decision': 'allow_always'})).json()
        rules = await (await client.get('/api/agent/permissions/rules', headers=HEADERS)).json()
        return saved, rules

    saved, rules = run(tmp_path, scenario, executor=executor)
    assert saved['saved'] is True and saved['saveCode'] == 'OK'
    assert saved['rules'] == ['terminal_exec(npm test)']
    assert 'terminal_exec(npm test)' in rules['rules']['allow']


def test_decide_allow_session_removes_the_second_question(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        first = await (await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                         json={'tool': 'terminal_exec', 'args': {'command': 'npm test'},
                                               'sessionId': 's1'})).json()
        second = await (await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                          json={'tool': 'terminal_exec', 'args': {'command': 'npm test'},
                                                'sessionId': 's1', 'decision': 'allow_session'})).json()
        third = await (await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                         json={'tool': 'terminal_exec', 'args': {'command': 'npm test'},
                                               'sessionId': 's1'})).json()
        return first, second, third

    first, second, third = run(tmp_path, scenario, executor=executor)
    assert first['outcome'] == 'ask'
    assert second['decision'] == 'allow_session'
    assert third['outcome'] == 'allow'


def test_decide_deny_trips_the_breaker(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        out = []
        for _ in range(perms.DENIAL_BREAKER_LIMIT):
            out.append(await (await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                                json={'tool': 'terminal_exec',
                                                      'args': {'command': 'npm publish'},
                                                      'sessionId': 's1', 'decision': 'deny'})).json())
        return out

    out = run(tmp_path, scenario, executor=executor)
    assert out[-1]['breaker'] is True


def test_decide_rejects_an_unknown_decision(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                     json={'tool': 'terminal_exec', 'args': {}, 'decision': 'maybe'})
        return response.status, await response.json()

    status, payload = run(tmp_path, scenario, executor=executor)
    assert status == 400 and payload['code'] == 'PERMISSION_DECISION_UNKNOWN'


def test_decide_needs_a_tool(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.post('/api/agent/permissions/decide', headers=HEADERS, json={})
        return (response.status,)

    assert run(tmp_path, scenario, executor=executor)[0] == 400


def test_hardline_call_is_denied_over_http(tmp_path):
    executor = host_executor(tmp_path)
    executor.policy.mode = 'trusted'

    async def scenario(client, runtime):
        response = await client.post('/api/agent/permissions/decide', headers=HEADERS,
                                     json={'tool': 'terminal_exec', 'args': {'command': 'diskpart'},
                                           'sessionId': 's1'})
        return await response.json()

    payload = run(tmp_path, scenario, executor=executor)
    assert payload['outcome'] == 'deny'
    assert payload['layer'] == 'hardline'


# ------------------------------------------------------------------ pending + thu hồi

def test_pending_starts_empty_and_can_be_read(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        executor.policy.register_pending('req-1', 'terminal_exec', {'command': 'npm test'},
                                         perms.ask('cần hỏi', 'x', 'user'), session_id='s1')
        response = await client.get('/api/agent/permissions/pending', headers=HEADERS)
        return await response.json()

    payload = run(tmp_path, scenario, executor=executor)
    assert [item['id'] for item in payload['pending']] == ['req-1']


def test_delete_rule_revokes_it(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        await client.post('/api/agent/permissions/decide', headers=HEADERS,
                          json={'tool': 'terminal_exec', 'args': {'command': 'npm test'},
                                'sessionId': 's1', 'decision': 'allow_always'})
        removed = await (await client.delete('/api/agent/permissions/rules', headers=HEADERS,
                                             json={'rule': 'terminal_exec(npm test)'})).json()
        rules = await (await client.get('/api/agent/permissions/rules', headers=HEADERS)).json()
        return removed, rules

    removed, rules = run(tmp_path, scenario, executor=executor)
    assert removed['ok'] is True
    assert 'terminal_exec(npm test)' not in rules['rules']['allow']


def test_delete_missing_rule_is_a_409(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.delete('/api/agent/permissions/rules', headers=HEADERS,
                                       json={'rule': 'terminal_exec(khong-co)'})
        return (response.status,)

    assert run(tmp_path, scenario, executor=executor)[0] == 409


# ------------------------------------------------------------------ docker mode + biên

def test_permissions_routes_are_unavailable_in_docker_mode(tmp_path):
    async def scenario(client, runtime):
        response = await client.get('/api/agent/permissions', headers=HEADERS)
        return response.status, await response.json()

    status, payload = run(tmp_path, scenario)
    assert status == 409
    assert payload['code'] == 'PERMISSIONS_UNAVAILABLE'


def test_routes_need_the_admin_header(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, runtime):
        response = await client.get('/api/agent/permissions', headers={'Host': '127.0.0.1:3102'})
        return (response.status,)

    assert run(tmp_path, scenario, executor=executor)[0] == 403


def test_routes_answer_when_the_process_is_docker_but_the_machine_is_host(tmp_path, monkeypatch):
    """Bản desktop: tiến trình docker, máy cấu hình host ⇒ route quyền vẫn trả lời.

    Nút chọn quyền ở thanh chat và tab Settings → Machines đi qua đúng route này; nếu vẫn 409 thì
    người dùng không đổi được mức cho phép dù phiên IDE đang chạy trên máy thật.
    """
    from aiohttp.test_utils import TestClient
    from agentbox.sandbox.machine_router import attach as attach_machines

    home = tmp_path / 'home'
    (home / '.boxfox').mkdir(parents=True)
    (home / '.boxfox' / 'settings.json').write_text('{"mode": "auto"}', encoding='utf-8')
    monkeypatch.setenv('BOXFOX_HOME_DIR', str(home))
    workspace = tmp_path / 'ws'
    workspace.mkdir(exist_ok=True)

    async def main():
        class Legacy(FixtureExecutor):
            visual_lock = None

        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, Legacy(), None)      # executor KHÔNG có `policy`
        attach_machines(runtime, tmp_path / 'profile')
        project = runtime.machine_registry.register(str(workspace))
        runtime.machine_registry.update({'revision': 1, 'mode': 'host', 'projectId': project['id']})
        async with TestClient(TestServer(create_app(runtime))) as client:
            response = await client.get('/api/agent/permissions', headers=HEADERS)
            payload = await response.json()
            changed = await client.put('/api/agent/permissions', headers=HEADERS, json={'mode': 'plan'})
        store.close()
        return response.status, payload, changed.status

    status, payload, changed_status = asyncio.run(main())
    assert status == 200
    assert payload['mode'] == 'auto'
    assert payload['workspace'] == str(workspace)
    assert changed_status == 200


# ------------------------------------------------------------- trục mạng (1b)

def test_network_can_be_set_and_read_back(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, _runtime):
        before = await (await client.get('/api/agent/permissions', headers=HEADERS)).json()
        changed = await client.put('/api/agent/permissions', headers=HEADERS,
                                   json={'network': 'enabled'})
        after = await (await client.get('/api/agent/permissions', headers=HEADERS)).json()
        return before, changed.status, await changed.json(), after

    before, status, payload, after = run(tmp_path, scenario, executor=executor)
    assert before['network'] == perms.NETWORK_RESTRICTED
    assert status == 200
    assert payload['network'] == perms.NETWORK_ENABLED
    assert after['network'] == perms.NETWORK_ENABLED


def test_unknown_network_value_is_rejected(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, _runtime):
        response = await client.put('/api/agent/permissions', headers=HEADERS,
                                    json={'network': 'mở-toang'})
        return response.status, await response.json()

    status, payload = run(tmp_path, scenario, executor=executor)
    assert status == 400
    assert payload['code'] == 'PERMISSION_NETWORK_UNKNOWN'


def test_health_reports_the_network_axis(tmp_path):
    executor = host_executor(tmp_path)

    async def scenario(client, _runtime):
        return await (await client.get('/api/agent/health', headers=HEADERS)).json()

    payload = run(tmp_path, scenario, executor=executor)
    assert payload['execution']['network'] == perms.NETWORK_RESTRICTED
