"""H10.2 — kiểm chứng trần chi bằng model MIỄN PHÍ với giá GIẢ $4 in / $20 out (quyết định #6600).

Nguyên tắc bất di bất dịch của giao thức:
1. Chỉ gọi model free (`space-bunny-free`); bước nào cần model trả phí thì DỪNG.
2. Mọi thao tác giá chỉ trên router BẢN SAO (cổng 3211, data dir riêng) — router thật
   (`~/.local/share/boxfox/router/`, cổng 3101) không bị PATCH.
3. Giá $4/$20 là số giả chỉ sống trong bản sao và phải được revert sau khi xong.

Script chạy in-process vì `HarnessRuntime`/`main()` không có env override cho URL router:
dựng `HarnessRuntime(store, executor_stub, client=RouterClient(url='http://127.0.0.1:3211'))`,
route `usage-allocation` gọi qua aiohttp TestServer thật, và gọi model qua
`usage_surface.complete(...)` — đúng seam mà runtime dùng.

Bốn ca (A–D) theo kế hoạch v2 §4.3. Mỗi ca ghi một tệp JSON vào `--out`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys
import time

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

sys.path.insert(0, '/code/.worktrees/boxfox-harness-reform/backend/src')

from agentbox.agent_core import execution_kernel, usage_ledger, usage_surface  # noqa: E402
from agentbox.agent_core.orchestration_contracts import ContractError  # noqa: E402
from agentbox.agent_core.runtime import HarnessRuntime, RouterClient  # noqa: E402
from agentbox.api.server import create_app  # noqa: E402
from agentbox.memory.session_store import SessionStore  # noqa: E402

HEADERS = {'Host': '127.0.0.1:3102', 'X-BoxFox-Admin': '1'}
CONNECTION = 'd7e26488-65b0-4012-8009-589cd94b324b'
MODEL = 'space-bunny-free'


class StubExecutor:
    async def execute(self, name, args, sid):
        return {'content': 'stub'}

    async def cleanup(self, sid):
        return None


class CountingClient:
    """Router thật của bản sao + đếm số lần model được gọi (điều kiện của ca A/B)."""

    def __init__(self, url):
        self.inner = RouterClient(url=url)
        self.calls = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def snapshot(self):
        return await self.inner.snapshot()

    async def complete(self, messages, tools, route, **kwargs):
        self.calls += 1
        return await self.inner.complete(messages, tools, route, **kwargs)


def write(out, name, payload):
    path = pathlib.Path(out) / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(f'[saved] {path}')


def rows(store, table):
    if store.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,)).fetchone() is None:
        return []
    return [dict(row) for row in store.db.execute(f'SELECT * FROM {table} ORDER BY rowid')]


async def expect_error(label, awaitable):
    """Chạy một lượt mong đợi lỗi hợp đồng; trả (code, model_calls)."""
    try:
        await awaitable
    except ContractError as exc:
        return exc.code, str(exc)
    return None, None


async def scenario(args):
    store = SessionStore(pathlib.Path(args.db))
    client = CountingClient(args.router)
    runtime = HarnessRuntime(store, StubExecutor(), client)
    created = runtime.create({'connectionId': args.connection, 'modelId': args.model, 'skills': []})
    root = created['id']
    route = created['config']['route']
    ledger = usage_surface.service(runtime)
    summary = {'router': args.router, 'sessionId': root, 'route': route, 'cases': {}}
    wanted = {name.strip().upper() for name in args.cases.split(',') if name.strip()}

    # --- Bước 4: kiểm từ phía harness (giá giả đã gieo trước khi chạy script) -----------------
    snapshot = await client.snapshot()
    from agentbox.agent_core import usage_surface as us
    model_rows = await us.route_rows(runtime, route)
    if len(model_rows) != 1:
        raise SystemExit(f'expected exactly one model row for {args.connection}/{args.model}, '
                         f'got {len(model_rows)}')
    price = us._price(model_rows[0])
    bound = us._bound(model_rows, args.max_tokens)
    summary['price'] = price
    summary['contextWindow'] = model_rows[0].get('contextWindow')
    summary['bound'] = bound
    print(f'[price] {price} context={model_rows[0].get("contextWindow")} bound={bound}')
    write(args.out, 'step4-price-and-bound.json', summary)

    # Cả bốn ca dùng harness thích ứng: policy ghim ở root, đúng chỗ `complete()` đọc.
    store.update_config(root, dict(created['config'], harnessPolicy={
        'schema': execution_kernel.POLICY_SCHEMA, 'mode': 'adaptive'}))
    messages = [{'role': 'user', 'content': 'Reply with the single word: pong'}]

    async with TestServer(create_app(runtime)) as server:
        base = server.make_url('/')
        async with ClientSession(base, headers=HEADERS) as http:
            attach_url = str(base) + f'api/agent/sessions/{root}/usage-allocation'

            # --- Ca A: adaptive, KHÔNG allocation ⇒ fail closed trước khi gọi model -----------
            if 'A' in wanted:
                calls_before = client.calls
                code, detail = await expect_error('A', usage_surface.complete(
                runtime, root, messages, [], route, purpose='ceiling-probe',
                max_tokens=args.max_tokens))
                case_a = {'expect': 'USAGE_NO_CONSENT', 'code': code, 'detail': detail,
                'modelCalls': client.calls - calls_before,
                'allocationRows': len(rows(store, 'harness_allocations'))}
                summary['cases']['A'] = case_a
                write(args.out, 'case-A-no-consent.json', case_a)

            # --- Ca B: trần 1.00 < bound ⇒ vượt trần trước khi gọi model ----------------------
            if 'B' in wanted:
                opened = await (await http.put(attach_url, json={'ceiling': 1.0,
                'consentRef': 'consent-mock-6600',
                'purpose': 'mock-price'})).json()
                calls_before = client.calls
                code, detail = await expect_error('B', usage_surface.complete(
                runtime, root, messages, [], route, purpose='ceiling-probe',
                max_tokens=args.max_tokens))
                view = ledger.get_allocation(opened['allocation']['allocationId'])
                case_b = {'expect': 'USAGE_CEILING_EXCEEDED', 'code': code, 'detail': detail,
                'bound': bound, 'ceiling': 1.0, 'modelCalls': client.calls - calls_before,
                'allocation': view, 'usageRows': len(rows(store, 'harness_usage'))}
                summary['cases']['B'] = case_b
                write(args.out, 'case-B-ceiling-exceeded.json', case_b)

            # --- Ca C: trần 10.00 ⇒ reserve → gọi model free thật → settle + release ----------
            if 'C' in wanted:
                detached = await (await http.delete(attach_url)).json()
                opened = await (await http.put(attach_url, json={'ceiling': 10.0,
                'consentRef': 'consent-mock-6600',
                'purpose': 'mock-price'})).json()
                allocation_id = opened['allocation']['allocationId']
                calls_before = client.calls
                started = time.time()
                response = await usage_surface.complete(runtime, root, messages, [], route,
                purpose='ceiling-probe',
                max_tokens=args.max_tokens)
                usage = (response or {}).get('usage') or {}
                view = ledger.get_allocation(allocation_id)
                usage_row = rows(store, 'harness_usage')[-1] if rows(store, 'harness_usage') else None
                case_c = {'expect': 'reserve → call → settle + release',
                'detachedBefore': detached, 'ceiling': 10.0, 'bound': bound,
                'modelCalls': client.calls - calls_before,
                'seconds': round(time.time() - started, 2),
                'routerUsage': usage,
                'content': (((response or {}).get('choices') or [{}])[0]
                .get('message') or {}).get('content'),
                'allocation': view, 'usageRow': usage_row,
                'expectedAmount': round(((usage.get('prompt_tokens') or 0) * 4.0
                + (usage.get('completion_tokens') or 0) * 20.0)
                / 1_000_000, 6)}
                summary['cases']['C'] = case_c
                write(args.out, 'case-C-within-ceiling.json', case_c)

            # --- Ca D: giá về 0 ⇒ adaptive không allocation đi qua, amount 0.0 -----------------
            if 'D' in wanted:
                detached = await (await http.delete(attach_url)).json()
                calls_before = client.calls
                response = await usage_surface.complete(runtime, root, messages, [], route,
                purpose='free-probe',
                max_tokens=args.max_tokens)
                usage_row = rows(store, 'harness_usage')[-1] if rows(store, 'harness_usage') else None
                case_d = {'expect': 'free route passes without allocation',
                'detachedBefore': detached, 'modelCalls': client.calls - calls_before,
                'routerUsage': (response or {}).get('usage') or {},
                'usageRow': usage_row,
                'allocationRows': len(rows(store, 'harness_allocations'))}
                summary['cases']['D'] = case_d
                write(args.out, 'case-D-free-route.json', case_d)

        summary['allocationRowsFinal'] = rows(store, 'harness_allocations')
        summary['usageRowsFinal'] = rows(store, 'harness_usage')
        write(args.out, 'ledger-dump.json', summary)

    store.close()
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--router', default='http://127.0.0.1:3211')
    parser.add_argument('--out', default='/code/.generated_artifacts/h10/mock-price-20261005')
    parser.add_argument('--db', default='/var/tmp/boxfox-budget/harness-mock.sqlite')
    parser.add_argument('--connection', default=CONNECTION)
    parser.add_argument('--model', default=MODEL)
    parser.add_argument('--max-tokens', type=int, default=4096)
    parser.add_argument('--cases', default='A,B,C,D')
    args = parser.parse_args()
    pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
    summary = asyncio.run(scenario(args))
    print(json.dumps({key: summary['cases'][key].get('code') or summary['cases'][key]['expect']
                      for key in summary['cases']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
