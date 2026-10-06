"""H10.2 — đường DUY NHẤT mở trần chi: route của người vận hành (gọi route THẬT qua aiohttp).

H6.9 để lại một lỗ: `harnessAllocationId` chỉ được test ghim bằng tay, không nơi nào trong
`backend/src` ghi được khoá đó — nên "main thích ứng" có ngân sách chỉ sống trên giấy. File này
khoá hợp đồng của writer mới: thiếu header admin ⇒ 403; PUT thiếu `ceiling`/`consentRef` ⇒ 400
(không auto-grant, không giá trị mặc định); PUT hợp lệ mở reservation rồi ghim vào PHIÊN GỐC
(gọi từ con cũng ghim ở root, đúng chỗ `usage_surface.complete()` đọc); PUT lần hai ⇒ 409 cho tới
khi DELETE; DELETE gỡ con trỏ và trả lại phần chưa tiêu; và không tool nào của model chạm tới trần.
"""
from __future__ import annotations

import asyncio

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from agentbox.agent_core import usage_surface
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


def run(tmp_path, coro_factory):
    """Một phiên gốc + một phiên con, chạy request THẬT trong một vòng aiohttp."""
    async def main():
        store = SessionStore(tmp_path / 'sessions.db')
        runtime = HarnessRuntime(store, FixtureExecutor(), None)
        root = runtime.create({'skills': []})['id']
        child = store.create({'skills': []}, parent_id=root)['id']
        async with TestServer(create_app(runtime)) as server:
            async with ClientSession(server.make_url('/')) as client:
                results = await coro_factory(client, store, runtime, root, child)
        store.close()
        return results

    return asyncio.run(main())


def allocation_rows(store):
    """Hàng allocation thô; bảng chỉ tồn tại sau lượt `UsageLedger` đầu tiên."""
    if store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                        "AND name='harness_allocations'").fetchone() is None:
        return []
    return list(store.db.execute('SELECT * FROM harness_allocations'))


def test_a_request_without_the_admin_header_is_refused(tmp_path):
    async def scenario(client, store, runtime, root, child):
        response = await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                    json={'ceiling': 5, 'consentRef': 'consent-1'},
                                    headers={'Host': '127.0.0.1:3102'})
        return response.status, await response.json(), allocation_rows(store)

    code, error, rows = run(tmp_path, scenario)
    assert code == 403
    assert error['error'] == 'Local administration required'
    assert rows == []


def test_put_requires_a_ceiling_and_a_consent_ref(tmp_path):
    async def scenario(client, store, runtime, root, child):
        no_consent = await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                      json={'ceiling': 5}, headers=HEADERS)
        no_ceiling = await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                      json={'consentRef': 'consent-1'}, headers=HEADERS)
        zero = await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                json={'ceiling': 0, 'consentRef': 'consent-1'}, headers=HEADERS)
        return (no_consent.status, await no_consent.json(),
                no_ceiling.status, await no_ceiling.json(),
                zero.status, await zero.json(), allocation_rows(store),
                runtime.store.get(root)['config'].get('harnessAllocationId'))

    no_consent, consent_error, no_ceiling, ceiling_error, zero, zero_error, rows, attached = \
        run(tmp_path, scenario)
    assert (no_consent, consent_error['code']) == (400, 'USAGE_NO_CONSENT')
    assert (no_ceiling, ceiling_error['code']) == (400, 'USAGE_FIELD_INVALID')
    assert (zero, zero_error['code']) == (400, 'USAGE_FIELD_INVALID')
    # Không auto-grant: ba lượt từ chối không để lại hàng nào và không ghim con trỏ.
    assert rows == []
    assert attached is None


def test_put_opens_a_reservation_and_pins_the_root(tmp_path):
    async def scenario(client, store, runtime, root, child):
        response = await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                    json={'ceiling': 5, 'consentRef': 'consent-1',
                                          'purpose': 'research'}, headers=HEADERS)
        body = await response.json()
        return (response.status, body, allocation_rows(store), runtime.store.get(root)['config'])

    code, body, rows, config = run(tmp_path, scenario)
    assert code == 200
    assert body['sessionId']
    assert body['attached'] is True
    view = body['allocation']
    assert view['ownerId'] == body['sessionId']
    assert view['policyRevision'] == 1
    assert view['consentRef'] == 'consent-1'
    assert view['reservation'] == {'amount': 5.0, 'ceiling': 5.0, 'currency': 'USD',
                                   'price': None, 'purpose': 'research'}
    assert view['state'] == 'reserved'
    assert view['remaining'] == 5.0
    assert config['harnessAllocationId'] == view['allocationId']
    assert len(rows) == 1
    assert rows[0]['owner_id'] == body['sessionId']


def test_a_child_session_pins_the_allocation_to_the_root(tmp_path):
    async def scenario(client, store, runtime, root, child):
        from_child = await client.put(f'/api/agent/sessions/{child}/usage-allocation',
                                      json={'ceiling': 2, 'consentRef': 'consent-2'}, headers=HEADERS)
        body = await from_child.json()
        seen_from_root = await (await client.get(f'/api/agent/sessions/{root}/usage-allocation',
                                                 headers=HEADERS)).json()
        seen_from_child = await (await client.get(f'/api/agent/sessions/{child}/usage-allocation',
                                                  headers=HEADERS)).json()
        return (body, seen_from_root, seen_from_child, runtime.store.get(root)['config'],
                runtime.store.get(child)['config'], root)

    body, from_root, from_child, root_config, child_config, root = run(tmp_path, scenario)
    assert body['sessionId'] == root
    assert body['allocation']['ownerId'] == root
    # Con KHÔNG có con trỏ riêng: `complete()` đọc config của root, nên ghim ở con cũng là ghim cả run.
    assert root_config['harnessAllocationId'] == body['allocation']['allocationId']
    assert 'harnessAllocationId' not in child_config
    assert from_root['attached'] is True and from_child['attached'] is True
    assert from_child['sessionId'] == root


def test_a_second_put_is_refused_until_delete(tmp_path):
    async def scenario(client, store, runtime, root, child):
        first = await (await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                        json={'ceiling': 5, 'consentRef': 'consent-1'},
                                        headers=HEADERS)).json()
        second = await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                  json={'ceiling': 9, 'consentRef': 'consent-9'}, headers=HEADERS)
        error = await second.json()
        return first, second.status, error, allocation_rows(store)

    first, code, error, rows = run(tmp_path, scenario)
    assert code == 409
    assert error['code'] == 'ALLOCATION_ALREADY_ATTACHED'
    # Trần đã ghim không bị ghi đè ngầm: vẫn đúng một hàng, đúng số tiền ban đầu.
    assert len(rows) == 1
    assert rows[0]['allocation_id'] == first['allocation']['allocationId']


def test_two_concurrent_puts_attach_exactly_one(tmp_path):
    """Hai PUT song song: một thắng 200, một phải 409 — không hàng reservation mồ côi.

    PUT đầu gửi body theo từng khúc và giữ khúc cuối, nên handler của nó đọc `attached`
    xong vẫn đang chờ body khi PUT thứ hai chạy trọn. Nếu lượt kiểm `attached` dùng giá
    trị đọc trước `await request.json()`, cả hai đều reserve: con trỏ trỏ về cái sau, còn
    reservation của cái trước mồ côi vĩnh viễn vì DELETE chỉ gỡ theo con trỏ.
    """
    async def scenario(client, store, runtime, root, child):
        url = f'/api/agent/sessions/{root}/usage-allocation'
        release = asyncio.Event()

        async def slow_body():
            yield b'{"ceiling": 7, "consentRef": "race-A"}'
            await release.wait()

        slow = asyncio.create_task(client.put(url, data=slow_body(), headers=HEADERS))
        await asyncio.sleep(0.3)   # handler A đã đọc `attached`, đang chờ nốt body
        fast = await client.put(url, json={'ceiling': 3, 'consentRef': 'race-B'},
                                headers=HEADERS)
        fast_body = await fast.json()
        release.set()
        slow_response = await slow
        slow_body_payload = await slow_response.json()
        return (fast.status, fast_body, slow_response.status, slow_body_payload,
                allocation_rows(store), runtime.store.get(root)['config'])

    fast_status, fast_body, slow_status, slow_body, rows, config = run(tmp_path, scenario)
    assert fast_status == 200
    assert slow_status == 409
    assert slow_body['code'] == 'ALLOCATION_ALREADY_ATTACHED'
    assert len(rows) == 1
    winner = fast_body['allocation']['allocationId']
    assert rows[0]['allocation_id'] == winner
    assert config['harnessAllocationId'] == winner


def test_get_shows_remaining_and_delete_releases_it(tmp_path):
    async def scenario(client, store, runtime, root, child):
        opened = await (await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                         json={'ceiling': 5, 'consentRef': 'consent-1'},
                                         headers=HEADERS)).json()
        allocation_id = opened['allocation']['allocationId']
        before = await (await client.get(f'/api/agent/sessions/{root}/usage-allocation',
                                         headers=HEADERS)).json()
        detached = await (await client.delete(f'/api/agent/sessions/{root}/usage-allocation',
                                              headers=HEADERS)).json()
        after = await (await client.get(f'/api/agent/sessions/{root}/usage-allocation',
                                        headers=HEADERS)).json()
        again = await (await client.delete(f'/api/agent/sessions/{root}/usage-allocation',
                                           headers=HEADERS)).json()
        ledger = usage_surface.service(runtime)
        return (allocation_id, before, detached, after, again, ledger.get_allocation(allocation_id),
                runtime.store.get(root)['config'])

    allocation_id, before, detached, after, again, view, config = run(tmp_path, scenario)
    assert before['attached'] is True
    assert before['allocation']['allocationId'] == allocation_id
    assert before['allocation']['remaining'] == 5.0
    assert detached == {'sessionId': before['sessionId'], 'detached': True, 'released': 5.0}
    # Gỡ con trỏ là hàng đầu tiên: không còn đường reserve mới, rồi phần chưa tiêu được trả lại.
    assert 'harnessAllocationId' not in config
    assert after == {'sessionId': before['sessionId'], 'attached': False, 'allocation': None}
    assert again['detached'] is False and again['released'] is None
    assert view['state'] == 'released'
    assert view['remaining'] == 0.0
    assert view['consumed']['releasedAmount'] == 5.0


def test_the_ledger_view_is_the_one_the_route_returns(tmp_path):
    """Route không bịa shape: view trả ra đúng bằng `ledger.get_allocation()`."""
    async def scenario(client, store, runtime, root, child):
        opened = await (await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                         json={'ceiling': 3, 'consentRef': 'consent-3'},
                                         headers=HEADERS)).json()
        return opened, usage_surface.service(runtime).get_allocation(
            opened['allocation']['allocationId'])

    opened, view = run(tmp_path, scenario)
    assert opened['allocation'] == view


def test_no_model_tool_can_open_a_ceiling():
    """Hàng rào cuối: trần chi là chuyện của người vận hành, không phải của model."""
    assert not [name for name in ORCHESTRATOR_TOOLS
                if 'allocation' in name or 'ceiling' in name or 'consent' in name]
    import inspect
    from agentbox.agent_core import tool_contracts
    source = inspect.getsource(tool_contracts)
    assert 'harnessAllocationId' not in source
    assert 'reserve' not in source


def test_delete_closes_a_ceiling_even_when_a_child_already_spent(tmp_path):
    """Con đã tiêu là tiêu: phần đó không trả lại được, nhưng trần vẫn phải gỡ được.

    `_held` cộng cả phần con đã tiêu vào hạn mức cha, nên nếu chỉ đóng khi
    `consumed + released >= amount` thì mọi trần từng có con tiêu tiền nằm `reserved`
    vĩnh viễn: DELETE trả phần rảnh, con trả nốt phần chưa tiêu, mà hàng vẫn mở và vẫn
    hiện trong `usage.allocations`. Bài này khoá luật đóng mới (đóng theo `remaining`)
    và đường chảy tiếp của phần con trả lại sau khi cha đã đóng.
    """
    async def scenario(client, store, runtime, root, child):
        opened = await (await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                         json={'ceiling': 10, 'consentRef': 'consent-10'},
                                         headers=HEADERS)).json()
        allocation_id = opened['allocation']['allocationId']
        ledger = usage_surface.service(runtime)
        # Đúng đường `usage_surface.complete()` đi: con giữ chỗ 4, tiêu 0.5, rồi trả lại 3.5.
        ledger.reserve('call-1', root, 1, None, {'amount': 4, 'currency': 'USD'},
                       'call-1', parent_id=allocation_id)
        ledger.settle('call-1', {'amount': 0.5}, invocation_id='settle-1')
        detached = await (await client.delete(f'/api/agent/sessions/{root}/usage-allocation',
                                              headers=HEADERS)).json()
        while_held = ledger.get_allocation(allocation_id)
        open_while_held = ledger.open_allocations()
        ledger.release('call-1', 3.5, 'call done', invocation_id='release-1')
        closed = ledger.get_allocation(allocation_id)
        return detached, while_held, open_while_held, closed

    detached, while_held, open_while_held, closed = run(tmp_path, scenario)
    assert detached['detached'] is True and detached['released'] == 6.0
    # Đóng ngay cả khi con còn giữ 4: `remaining` bằng 0, không nằm lại trong danh sách mở.
    assert while_held['state'] == 'released' and while_held['remaining'] == 0.0
    assert open_while_held == []
    # Con trả lại 3.5 sau đó chảy vào `releasedAmount` của cha, không kẹt trong hàng đã đóng.
    assert closed['state'] == 'released' and closed['remaining'] == 0.0
    assert closed['consumed']['releasedAmount'] == 9.5


def test_delete_closes_a_ceiling_when_a_child_holds_all_of_it(tmp_path):
    """Con giữ TRỌN trần thì `remaining` của cha đúng bằng 0.0 — vẫn phải gọi release để chốt hàng.

    Bản trước dùng `if released:` nên bỏ qua đúng trường hợp `remaining == 0.0`: con trỏ bị gỡ
    (không API nào chạm tới hàng nữa) mà hàng nằm `reserved` vĩnh viễn; khi con tiêu rồi trả lại,
    hàng hiện lại trong `usage.allocations` với phần chưa tiêu và không còn đường gỡ.
    """
    async def scenario(client, store, runtime, root, child):
        opened = await (await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                         json={'ceiling': 10, 'consentRef': 'consent-full'},
                                         headers=HEADERS)).json()
        allocation_id = opened['allocation']['allocationId']
        ledger = usage_surface.service(runtime)
        # Đúng đường `usage_surface.complete()` đi: con giữ trọn 10 nên cha hết chỗ.
        ledger.reserve('call-full', root, 1, None, {'amount': 10, 'currency': 'USD'},
                       'call-full', parent_id=allocation_id)
        before = ledger.get_allocation(allocation_id)
        detached = await (await client.delete(f'/api/agent/sessions/{root}/usage-allocation',
                                              headers=HEADERS)).json()
        closed = ledger.get_allocation(allocation_id)
        ledger.settle('call-full', {'amount': 1}, invocation_id='settle-full')
        ledger.release('call-full', 9, 'call done', invocation_id='release-full')
        after = ledger.get_allocation(allocation_id)
        return before, detached, closed, after, ledger.open_allocations()

    before, detached, closed, after, still_open = run(tmp_path, scenario)
    assert before['state'] == 'reserved' and before['remaining'] == 0.0
    assert detached['detached'] is True and detached['released'] == 0.0
    assert closed['state'] == 'released' and closed['remaining'] == 0.0
    # Con tiêu 1 rồi trả 9: chảy hết vào `releasedAmount` của cha đã đóng, không kẹt lại.
    assert after['state'] == 'released' and after['remaining'] == 0.0
    assert after['consumed']['releasedAmount'] == 9.0
    assert still_open == []


def test_an_absurd_integer_ceiling_is_refused_not_a_crash(tmp_path):
    """`10**400` qua được `isinstance` nhưng `float()` ném OverflowError: vẫn phải là 400."""
    async def scenario(client, store, runtime, root, child):
        response = await client.put(f'/api/agent/sessions/{root}/usage-allocation',
                                    json={'ceiling': 10 ** 400, 'consentRef': 'consent-huge'},
                                    headers=HEADERS)
        return response.status, await response.json(), allocation_rows(store)

    code, error, rows = run(tmp_path, scenario)
    assert code == 400
    assert error['code'] == 'USAGE_FIELD_INVALID'
    assert rows == []
