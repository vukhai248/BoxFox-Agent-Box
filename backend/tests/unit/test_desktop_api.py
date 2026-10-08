"""API điều khiển desktop (H7): `GET|POST /api/agent/desktop/lease`, `POST .../inspect-element`.

Chạy trên `FakePlatform` nên kiểm được trên Linux; mọi ca gọi route THẬT qua aiohttp, không ca nào
chạm Windows thật hay ghi ra ngoài `tmp_path`.
"""
from __future__ import annotations

import asyncio
import os

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer
from win_fakes import FakePlatform, make_window, reset_win_state

from agentbox.agent_core import desktop_control as dc
from agentbox.agent_core import permissions as perms
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore
from agentbox.sandbox.host_executor import HostExecutor
from agentbox.sandbox.win import errors as win_errors

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class FixtureExecutor:
    """Executor kiểu docker: có `execute`/`cleanup`, KHÔNG có `policy` và KHÔNG có `desktop`."""

    async def execute(self, name, args, sid):
        return {'ok': True}

    async def cleanup(self, sid):
        return None


def host_executor(tmp_path, *, desktop=True, platform=None, hook_ok=True):
    workspace = tmp_path / 'ws'
    workspace.mkdir(exist_ok=True)
    profile = tmp_path / 'profile'
    profile.mkdir(exist_ok=True)
    home = tmp_path / 'home'
    home.mkdir(exist_ok=True)
    install = tmp_path / 'install'
    install.mkdir(exist_ok=True)
    env = dict(os.environ)
    env['BOXFOX_HOME_DIR'] = str(home)
    env['BOXFOX_INSTALL_DIR'] = str(install)
    fake = platform if platform is not None else FakePlatform(hook_ok=hook_ok)
    control = dc.DesktopControl(profile_dir=profile, platform=fake) if desktop else None
    policy = perms.PermissionPolicy(str(workspace), profile_dir=profile, env=env)
    executor = HostExecutor(str(workspace), policy=policy, platform='win32', env=env,
                            desktop=control)
    return executor, control, fake


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


def lease_get(client):
    return client.get('/api/agent/desktop/lease', headers=HEADERS)


def lease_post(client, payload):
    return client.post('/api/agent/desktop/lease', headers=HEADERS, json=payload)


# ------------------------------------------------------------------- lease

def test_the_lease_route_is_unavailable_in_docker_mode(tmp_path):
    async def main(client, _runtime):
        response = await lease_get(client)
        return response.status, await response.json()

    status, payload = run(tmp_path, main)
    assert status == 409
    assert payload['code'] == 'DESKTOP_CONTROL_UNAVAILABLE'


def test_the_lease_starts_with_the_agent_on_a_fresh_machine(tmp_path):
    executor, _control, _fake = host_executor(tmp_path)

    async def main(client, _runtime):
        response = await lease_get(client)
        return response.status, await response.json()

    status, payload = run(tmp_path, main, executor)
    assert status == 200
    assert payload['holder'] == dc.HOLDER_AGENT
    assert payload['epoch'] == 0
    assert payload['mutexHeld'] is False


def test_release_then_claim_moves_the_lease_back_to_the_agent(tmp_path):
    executor, control, _fake = host_executor(tmp_path)

    async def main(client, _runtime):
        released = await (await lease_post(client, {'action': 'release', 'reason': 'người dùng gõ'})).json()
        blocked = await client.post('/api/agent/desktop/inspect-element', headers=HEADERS,
                                    json={'x': 5, 'y': 5})
        claimed = await (await lease_post(client, {'action': 'claim', 'reason': 'bấm nút'})).json()
        return released, blocked.status, await blocked.json(), claimed

    released, blocked_status, blocked_body, claimed = run(tmp_path, main, executor)
    assert released['holder'] == dc.HOLDER_HUMAN
    assert blocked_status == 409
    assert blocked_body['code'] == 'HUMAN_HAS_CONTROL'
    assert blocked_body['holder'] == dc.HOLDER_HUMAN
    assert claimed['holder'] == dc.HOLDER_AGENT
    assert claimed['epoch'] > released['epoch'], 'epoch phải tiến, không được lùi'


def test_the_emergency_stop_button_bumps_the_generation_and_returns_control(tmp_path):
    executor, control, _fake = host_executor(tmp_path)

    async def main(client, _runtime):
        control.agent_lease('agent bắt đầu')
        before = control.generation
        response = await lease_post(client, {'action': 'stop', 'reason': 'nút Dừng khẩn'})
        return before, await response.json()

    before, payload = run(tmp_path, main, executor)
    assert payload['holder'] == dc.HOLDER_HUMAN
    assert payload['generation'] == before + 1
    assert control.mutex.handle is None


def test_an_unknown_lease_action_is_refused_with_a_code(tmp_path):
    executor, _control, _fake = host_executor(tmp_path)

    async def main(client, _runtime):
        response = await lease_post(client, {'action': 'chiem-quyen'})
        return response.status, await response.json()

    status, payload = run(tmp_path, main, executor)
    assert status == 400
    assert payload['code'] == 'DESKTOP_LEASE_ACTION_UNKNOWN'


# --------------------------------------------------------- soi phần tử (UI)

def test_inspect_element_returns_the_payload_the_selector_parses(tmp_path, monkeypatch):
    executor, _control, _fake = host_executor(tmp_path)
    window = make_window(hwnd=321, title='Chrome')

    def fake_inspect(x, y, *, platform=None, **kwargs):
        return {'kind': 'desktop', 'windowId': 321, 'windowTitle': 'Chrome',
                'label': {'integrity': 'khong_tin_duoc', 'source_kind': 'screen_element'},
                'point': {'x': x, 'y': y}}

    monkeypatch.setattr('agentbox.agent_core.inspect_host.inspect_element', fake_inspect)

    async def main(client, _runtime):
        response = await client.post('/api/agent/desktop/inspect-element', headers=HEADERS,
                                     json={'x': 12, 'y': 34})
        return response.status, await response.json()

    status, payload = run(tmp_path, main, executor)
    assert status == 200
    assert payload['kind'] == 'desktop'
    assert payload['windowTitle'] == 'Chrome'
    assert payload['point'] == {'x': 12, 'y': 34}
    assert payload['label']['integrity'] == 'khong_tin_duoc'
    assert window.hwnd == 321


def test_inspect_element_keeps_the_platform_error_code(tmp_path, monkeypatch):
    executor, _control, _fake = host_executor(tmp_path)

    def boom(x, y, *, platform=None, **kwargs):
        raise win_errors.PlatformError(win_errors.DESKTOP_LOCKED, 'màn hình đang khoá')

    monkeypatch.setattr('agentbox.agent_core.inspect_host.inspect_element', boom)

    async def main(client, _runtime):
        response = await client.post('/api/agent/desktop/inspect-element', headers=HEADERS,
                                     json={'x': 1, 'y': 1})
        return response.status, await response.json()

    status, payload = run(tmp_path, main, executor)
    assert status == 409
    assert payload['code'] == win_errors.DESKTOP_LOCKED


def test_inspect_element_needs_integer_coordinates(tmp_path):
    executor, _control, _fake = host_executor(tmp_path)

    async def main(client, _runtime):
        response = await client.post('/api/agent/desktop/inspect-element', headers=HEADERS,
                                     json={'x': 'một', 'y': None})
        return response.status, await response.json()

    status, payload = run(tmp_path, main, executor)
    assert status == 400
    assert payload['code'] == 'INSPECT_POINT_INVALID'


def test_the_inspect_route_is_unavailable_in_docker_mode(tmp_path):
    async def main(client, _runtime):
        response = await client.post('/api/agent/desktop/inspect-element', headers=HEADERS,
                                     json={'x': 1, 'y': 1})
        return response.status, await response.json()

    status, payload = run(tmp_path, main)
    assert status == 409
    assert payload['code'] == 'DESKTOP_CONTROL_UNAVAILABLE'


# ------------------------------------------------------------------ health

def test_health_carries_the_real_lease_for_host_mode(tmp_path):
    executor, _control, _fake = host_executor(tmp_path)

    async def main(client, _runtime):
        response = await client.get('/api/agent/health', headers=HEADERS)
        return await response.json()

    payload = run(tmp_path, main, executor)
    lease = payload['execution']['lease']
    assert payload['execution']['mode'] == 'host'
    assert lease['holder'] == dc.HOLDER_AGENT
    assert lease['epoch'] == 0
    assert 'generation' in lease and 'mutexHeld' in lease


def test_health_says_none_when_there_is_no_desktop_control(tmp_path):
    executor, _control, _fake = host_executor(tmp_path, desktop=False)

    async def main(client, _runtime):
        response = await client.get('/api/agent/health', headers=HEADERS)
        return await response.json()

    payload = run(tmp_path, main, executor)
    assert payload['execution']['mode'] == 'host'
    assert payload['execution']['lease'] is None


# ------------------------------------------------- người thật chạm máy (X11)

class WatchedPlatform(FakePlatform):
    """Nền tảng có `supports_idle_watch` như X11: bộ đếm input là thứ ĐO ĐƯỢC, không phải hook."""

    supports_idle_watch = True


def test_the_idle_watch_releases_the_lease_when_the_machine_is_touched(tmp_path, monkeypatch):
    """X11 không có hook bàn phím/chuột ⇒ bộ theo dõi lấy mẫu phải TỰ nhả quyền về tay người.

    Quyết định #6785: trên Linux, con trỏ/tiêu điểm đổi mà không do agent gây ra được coi là người
    can thiệp. Ca này kiểm đường thật: aiohttp khởi động → pump → `poll_idle()` → nhả quyền.
    """
    from agentbox.api import server as server_module

    executor, control, fake = host_executor(tmp_path, platform=WatchedPlatform())
    monkeypatch.setattr(server_module, 'IDLE_WATCH_INTERVAL_SEC', 0.02)

    async def main(client, _runtime):
        # Mốc nền: agent đã gửi input một lần (như mọi phiên đang làm việc thật).
        fake.input_tick = 3
        control.note_own_input()
        first = await (await lease_get(client)).json()
        fake.input_tick = 7                      # "người thật vừa chạm chuột"
        await asyncio.sleep(0.3)
        second = await (await lease_get(client)).json()
        return first, second

    first, second = run(tmp_path, main, executor)
    assert first['holder'] == dc.HOLDER_AGENT
    assert second['holder'] == dc.HOLDER_HUMAN
    assert second['reason'], 'phải nói vì sao quyền về tay người'


def test_a_platform_without_the_watch_capability_never_gets_a_pump(tmp_path, monkeypatch):
    """Windows đang chạy thật: không có cờ ⇒ không dựng pump, hành vi không đổi."""
    from agentbox.api import server as server_module

    executor, control, fake = host_executor(tmp_path)
    assert not getattr(fake, 'supports_idle_watch', False)
    calls: list[int] = []
    monkeypatch.setattr(control, 'poll_idle', lambda: calls.append(1))
    monkeypatch.setattr(server_module, 'IDLE_WATCH_INTERVAL_SEC', 0.02)

    async def main(client, _runtime):
        await asyncio.sleep(0.2)
        return (await (await lease_get(client)).json())

    payload = run(tmp_path, main, executor)
    assert calls == [] and payload['holder'] == dc.HOLDER_AGENT


class _BareRuntime:
    """Runtime tối thiểu: `store` + `tasks`, KHÔNG có `executor`.

    Một số bài kiểm dựng app đúng theo hình dạng này (`test_system_log_v2.py`), nên mọi hook khởi
    động phải chịu được runtime thiếu `executor`.
    """

    def __init__(self, store):
        self.store = store
        self.tasks = {}

    async def stop(self, sid):
        return None


def test_the_idle_watch_hook_tolerates_a_runtime_without_an_executor(tmp_path):
    """Thiếu `executor` thì hook bỏ qua — không được làm app không dựng nổi.

    Đúng lỗi đã xảy ra: hook đọc thẳng `runtime.executor.desktop`, nên app dựng bằng runtime tối
    thiểu chết ngay lúc khởi động và 11 bài kiểm của hai tệp khác đỏ theo.
    """
    from agentbox.api import server as server_module

    async def main():
        store = SessionStore(tmp_path / 'sessions.db')
        async with TestServer(create_app(_BareRuntime(store))) as server:
            watching = server.app.get(server_module.IDLE_WATCH_KEY)
        store.close()
        return watching

    assert asyncio.run(main()) is None
