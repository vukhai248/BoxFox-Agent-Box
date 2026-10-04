"""H8 — đường DUY NHẤT ghi `harnessPolicy`: route của người vận hành (gọi route THẬT qua aiohttp).

Soát tuân thủ 2026-10-04 chỉ ra H8 ("main thích ứng") chỉ có thư viện + seam: bật công tắc cũng
không có cách nào đặt mode cho một phiên, nên phần "main thích ứng" không vận hành được. File này
khoá hợp đồng của writer mới: GET thấy mode + hai công tắc; PUT `adaptive` bị từ chối khi thiếu công
tắc (409, policy KHÔNG đổi); đủ công tắc thì policy ghim ở PHIÊN GỐC của run (con đọc theo cha);
`legacy` gỡ khoá; mode lạ 400. Và: không tool nào của model chạm tới policy.
"""
from __future__ import annotations

import asyncio

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import execution_kernel
from agentbox.agent_core.roles import ORCHESTRATOR_TOOLS
from agentbox.agent_core.runtime import HarnessRuntime
from agentbox.api.server import create_app
from agentbox.memory.session_store import SessionStore

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}


class FixtureExecutor:
    async def execute(self, name, args, sid):
        return {'ok': True}

    async def cleanup(self, sid):
        return None


def run(tmp_path, coro_factory, switches=()):
    """Một phiên gốc + một phiên con, chạy request THẬT trong một vòng aiohttp."""
    async def main():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, FixtureExecutor(), None)
        root = runtime.create({'skills': []})['id']
        child = store.create({'skills': []}, parent_id=root)['id']
        results = []
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                results = await coro_factory(client, store, runtime, root, child)
        store.close()
        return results

    import os
    saved = {name: os.environ.get(name) for name in (execution_kernel.ADAPTIVE_SWITCH,
                                                     execution_kernel.LEDGER_SWITCH)}
    for name in saved:
        os.environ.pop(name, None)
    for name in switches:
        os.environ[name] = 'on'
    try:
        return asyncio.run(main())
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def test_status_reports_legacy_and_the_two_switches(tmp_path):
    async def scenario(client, store, runtime, root, child):
        return await (await client.get(f'/api/agent/sessions/{root}/execution-policy',
                                      headers=HEADERS)).json()

    payload = run(tmp_path, scenario)
    assert payload['mode'] == 'legacy'
    assert payload['policy'] is None
    assert payload['sessionId']
    assert payload['switches'] == {execution_kernel.ADAPTIVE_SWITCH: False,
                                   execution_kernel.LEDGER_SWITCH: False}


def test_adaptive_is_refused_while_a_switch_is_off(tmp_path):
    async def scenario(client, store, runtime, root, child):
        response = await client.put(f'/api/agent/sessions/{root}/execution-policy',
                                    json={'mode': 'adaptive'}, headers=HEADERS)
        status = await (await client.get(f'/api/agent/sessions/{root}/execution-policy',
                                        headers=HEADERS)).json()
        return response.status, await response.json(), status, runtime.store.get(root)['config']

    code, error, status, config = run(tmp_path, scenario)
    assert code == 409
    assert error['error'].startswith('POLICY_SWITCH_OFF')
    assert status['mode'] == 'legacy'
    assert execution_kernel.POLICY_KEY not in config


def test_adaptive_pins_the_root_run_and_legacy_releases_it(tmp_path):
    async def scenario(client, store, runtime, root, child):
        turned_on = await (await client.put(f'/api/agent/sessions/{root}/execution-policy',
                                           json={'mode': 'adaptive'}, headers=HEADERS)).json()
        from_child = await (await client.get(f'/api/agent/sessions/{child}/execution-policy',
                                            headers=HEADERS)).json()
        released = await (await client.put(f'/api/agent/sessions/{child}/execution-policy',
                                          json={'mode': 'legacy'}, headers=HEADERS)).json()
        return turned_on, from_child, released, runtime.store.get(root)['config'], root

    turned_on, from_child, released, config, root_id = run(tmp_path, scenario,
                                                  switches=(execution_kernel.ADAPTIVE_SWITCH,
                                                            execution_kernel.LEDGER_SWITCH))
    assert turned_on['mode'] == 'adaptive'
    assert turned_on['policy'] == {'schema': execution_kernel.POLICY_SCHEMA, 'mode': 'adaptive'}
    # Con KHÔNG có khoá riêng: nó đọc policy của phiên gốc, nên bật ở con cũng là bật cả run.
    assert from_child['mode'] == 'adaptive'
    assert from_child['sessionId'] == turned_on['sessionId'] == root_id
    assert released['mode'] == 'legacy'
    assert execution_kernel.POLICY_KEY not in config


def test_a_bad_mode_is_refused_with_the_mode_code(tmp_path):
    async def scenario(client, store, runtime, root, child):
        response = await client.put(f'/api/agent/sessions/{root}/execution-policy',
                                    json={'mode': 'fast'}, headers=HEADERS)
        return response.status, await response.json()

    code, error = run(tmp_path, scenario)
    assert code == 400
    assert error['error'].startswith('POLICY_MODE_INVALID')


def test_no_model_tool_can_write_the_policy():
    """Hàng rào cuối: policy là chuyện của người vận hành, không phải của model."""
    assert not [name for name in ORCHESTRATOR_TOOLS if 'policy' in name]
    import inspect
    from agentbox.agent_core import tool_contracts
    source = inspect.getsource(tool_contracts)
    assert 'harnessPolicy' not in source
    assert 'set_policy' not in source
