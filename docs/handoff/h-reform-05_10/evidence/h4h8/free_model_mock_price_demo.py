"""#6526 — minh chứng cơ chế chặn tiền khi model MIỄN PHÍ được gán giá MOCK.

Không gọi provider thật, không sửa giá router: chỉ tiêm giá mock trong tiến trình demo
này rồi khôi phục. Model dùng để gọi là model free thật của Zen (`space-bunny-free`),
giá mock lấy đúng giá documented của `muse-spark-1.3`.

Chạy:
  cd /code/.worktrees/boxfox-harness-reform
  TMPDIR=/var/tmp PYTHONPATH=backend/src \
    /code/i3abyxinhdepqua-lang/BoxFox-Agent-Box/backend/.venv/bin/python \
    /code/.generated_artifacts/h4h8/free_model_mock_price_demo.py
"""
import asyncio
import copy
import json
import os
import subprocess
import tempfile
from pathlib import Path

os.environ['BOXFOX_USAGE_LEDGER'] = 'on'
os.environ['BOXFOX_ADAPTIVE_HARNESS'] = 'on'

from agentbox.agent_core import execution_kernel, usage_surface  # noqa: E402
from agentbox.agent_core.orchestration_contracts import ContractError  # noqa: E402
from agentbox.agent_core.runtime import HarnessRuntime  # noqa: E402
from agentbox.memory.session_store import SessionStore  # noqa: E402

FREE_MODEL = 'space-bunny-free'                      # model free thật của Zen
MOCK_FROM = 'muse-spark-1.3'                         # nguồn giá mock
# Giá MOCK (đúng bảng documented của muse-spark-1.3) — chỉ sống trong tiến trình này.
MOCK_PRICE = {'input': 1.25, 'output': 4.25, 'cachedInput': 0.15, 'cacheWriteInput': 1.25,
              'unit': 'per_million_tokens', 'source': 'manual', 'asOf': '2026-10-04'}
USAGE = {'prompt_tokens': 100, 'completion_tokens': 20,
         'prompt_tokens_details': {'cached_tokens': 40},
         'completion_tokens_details': {'reasoning_tokens': 10}}


class Client:
    """Client giả: model id là model free thật, giá do fixture tiêm."""

    def __init__(self):
        self.price = copy.deepcopy(MOCK_PRICE)
        self.calls = 0

    async def snapshot(self):
        return {'connections': [{'id': 'c1', 'providerId': 'opencode', 'revision': 1,
                                 'models': [{'id': FREE_MODEL, 'contextWindow': 1000,
                                             'pricing': self.price}]}]}

    async def complete(self, messages, tools, route, **kwargs):
        self.calls += 1
        return {'boxfox': {'connectionId': 'c1', 'modelId': FREE_MODEL}, 'usage': USAGE,
                'choices': [{'finish_reason': 'stop', 'message': {'content': 'demo'}}]}


class Executor:
    async def execute(self, name, args, sid):
        return {'content': 'demo'}

    async def cleanup(self, sid):
        pass


def router_price(model_id):
    """Giá THẬT của router (đọc từ module pricing.mjs, không sửa gì)."""
    code = ("import('./router/src/pricing.mjs').then(m => "
            "console.log(JSON.stringify(m.documentedZenPrice(process.argv[1]) ?? null)))")
    out = subprocess.run(['node', '-e', code, model_id], cwd='/code/.worktrees/boxfox-harness-reform',
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout.strip())


def main():
    evidence = {'owner_decision': '#6526', 'free_model': FREE_MODEL, 'mock_price_from': MOCK_FROM,
                'mock_price': MOCK_PRICE, 'real_router_prices_untouched': {}}
    for model_id in (FREE_MODEL, MOCK_FROM):
        evidence['real_router_prices_untouched'][model_id] = router_price(model_id)

    tmp = tempfile.mkdtemp(prefix='boxfox-demo-', dir='/var/tmp')
    store = SessionStore(Path(tmp) / 'sessions.db')
    client = Client()
    rt = HarnessRuntime(store, Executor(), client)
    session = rt.create({'connectionId': 'c1', 'modelId': FREE_MODEL, 'skills': []})
    sid = session['id']
    route = session['config']['route']
    ledger = usage_surface.service(rt)

    def config(**changes):
        current = store.get(sid)['config']
        store.update_config(sid, {**current, **changes})

    def rows():
        return ledger.calls(sid, limit=100)['items']

    def call():
        return asyncio.run(rt.complete_model(sid, store.get(sid)['messages'], [], route,
                                             max_tokens=100, purpose='demo'))

    def one_new(before):
        after = {row['callKey']: row for row in rows()}
        fresh = [row for key, row in after.items() if key not in before]
        assert len(fresh) == 1, fresh
        return fresh[0], set(after)

    # A — allocation đủ rộng: giá mock tính ra TIỀN thật (tokens × giá mock).
    ledger.reserve('demo-budget', sid, 1, 'demo-consent', {'amount': 0.01, 'ceiling': 0.01},
                   'demo-root')
    config(harnessAllocationId='demo-budget')
    before = {row['callKey'] for row in rows()}
    call()
    row_a, seen = one_new(before)
    evidence['A_mock_price_costs_money'] = {
        'model_calls': client.calls, 'amount_usd': row_a['amount'],
        'price_source': (row_a.get('priceSnapshot') or {}).get('source'),
        'expected': '0.000166 = 60×1.25 + 40×0.15 + 20×4.25 (per 1M)'}

    # B — trần nhỏ hơn bound: chặn TRƯỚC khi gọi model, không phát sinh request.
    ledger.reserve('demo-tight', sid, 1, 'demo-consent', {'amount': 0.0001, 'ceiling': 0.0001},
                   'demo-tight-root')
    config(harnessAllocationId='demo-tight')
    try:
        call()
        blocked = None
    except ContractError as exc:
        blocked = str(exc)
    evidence['B_ceiling_blocks_before_model'] = {
        'error': blocked, 'model_calls': client.calls, 'rows_after': len(rows()),
        'expected': 'USAGE_CEILING_EXCEEDED, model_calls=1 (không tăng)'}

    # C — khôi phục giá free thật (0) + policy adaptive: qua cửa, tiền = 0.
    config(harnessPolicy={'schema': execution_kernel.POLICY_SCHEMA, 'mode': 'adaptive'},
           harnessAllocationId=None)
    client.price = {**MOCK_PRICE, 'input': 0, 'output': 0, 'cachedInput': 0, 'cacheWriteInput': 0}
    before = {row['callKey'] for row in rows()}
    call()
    row_c, _ = one_new(before)
    evidence['C_free_route_passes'] = {'model_calls': client.calls, 'amount_usd': row_c['amount'],
                                       'expected': 'amount=0, model_calls=2'}

    # D — khôi phục: giá mock biến mất khỏi fixture; giá thật của router không đổi.
    client.price = copy.deepcopy(MOCK_PRICE)
    config(harnessPolicy=None)
    evidence['D_mock_restored'] = {
        'fixture_price_back_to_mock': client.price['input'] == MOCK_PRICE['input'],
        'real_router_prices_untouched': {m: router_price(m) for m in (FREE_MODEL, MOCK_FROM)}}
    store.close()

    path = '/code/.generated_artifacts/h4h8/free_model_mock_price_demo.json'
    with open(path, 'w', encoding='utf-8') as handle:
        json.dump(evidence, handle, ensure_ascii=False, indent=2, sort_keys=True)
    print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
