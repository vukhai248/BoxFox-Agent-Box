// W12.MODEL.METADATA — T3: yêu cầu của người dùng so với thứ thật sự đi tới provider
// (limits/budget), và giá/usage: thiếu là unknown — không bao giờ tự thành 0 hay
// "free"; lịch sử usage giữ nguyên basis khi bảng giá đổi.
//
// Fixture không mạng: adapter thật + `fetchImpl` giả, store riêng cho mỗi test.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createProviders } from '../src/providers/index.mjs';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';
import { RouterEngine } from '../src/engine.mjs';

const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const messages = [{ role: 'user', content: 'Xin chào' }];

async function collect(iterator) {
  const values = [];
  for await (const event of iterator) values.push(event);
  return values;
}

/** Service + engine tạm, adapter thật với `fetchImpl` giả. */
function fixture(t, { fetchImpl } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-w12-limits-'));
  const store = new RouterStore({ dataDir: dir });
  const service = new ProviderService({ store, providers: createProviders({ fetchImpl }) });
  const engine = new RouterEngine({ service, deadlineMs: 5000 });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  return { store, service, engine };
}

test('T3: an Anthropic budget level lifts max_tokens above the budget, never past the owner ceiling', async () => {
  const calls = [];
  const adapter = createProviders({
    fetchImpl: async (_url, init) => {
      calls.push(JSON.parse(init.body));
      return json({ content: [{ type: 'text', text: 'ok' }], stop_reason: 'end_turn', usage: { input_tokens: 1, output_tokens: 1 } });
    },
  }).anthropic;
  const send = (max_tokens, thinkingLevel) => collect(adapter.generate({
    connection: { endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' },
    body: { model: 'claude-sonnet-4-5', messages, stream: false, max_tokens, thinkingLevel },
  }));

  await send(1024, 'low');
  await send(1024, 'high');
  await send(20000, 'high');
  await send(64000, 'high');

  assert.equal(calls[0].max_tokens, 6144, 'low (2048) lifts 1024 above the budget');
  assert.equal(calls[0].thinking.budget_tokens, 2048);
  assert.equal(calls[1].max_tokens, 20480, 'high (16384) lifts 1024 to budget + 4096');
  assert.equal(calls[2].max_tokens, 20000, 'a request already above the budget is left alone, not raised further');
  assert.equal(calls[3].max_tokens, 64000, 'the owner ceiling is not pushed past 64000');
  assert.ok(calls.every(call => call.max_tokens <= 64000), 'every effective max_tokens stays inside 1–64000');
});

test('T3: the engine accepts 1–64000 requested tokens and refuses anything outside it', async t => {
  const { engine } = fixture(t, { fetchImpl: async () => { throw new Error('no network in this test'); } });
  const call = max_tokens => ({ connectionId: 'missing', modelId: 'missing', messages, stream: false, max_tokens });

  for (const value of [0, -1, 1.5, 64001, Number.MAX_SAFE_INTEGER]) {
    await assert.rejects(() => collect(engine.generate(call(value))), /max_tokens must be 1–64000/, `${value} is refused`);
  }
  // 64000 đi qua phép kiểm và chỉ chết ở bước chọn tuyến (không có connection) —
  // nghĩa là trần trên là 64000, không phải một con số nào khác.
  await assert.rejects(() => collect(engine.generate(call(64000))), error => error.code === 'NO_ROUTE');
});

test('T3: a published zero is a real price; an absent or unreadable price stays unknown (never 0)', async t => {
  const usage = { prompt_tokens: 1000, completion_tokens: 100, total_tokens: 1100 };
  const { store, service, engine } = fixture(t, {
    fetchImpl: async url => (String(url).endsWith('/models')
      ? json({ data: [
        { id: 'free-model', pricing: { prompt: '0', completion: '0' } },
        { id: 'opaque-model' },
        { id: 'partial-model', pricing: { prompt: '0.000001' } },
        { id: 'junk-model', pricing: { prompt: 'free', completion: 'free' } },
      ] })
      : json({ choices: [{ message: { content: 'ok' }, finish_reason: 'stop' }], usage })),
  });
  const connection = service.create({ providerId: 'custom', name: 'Gateway', endpoint: 'https://gateway.invalid/v1', apiKey: 'test-only-key' });
  await service.discover(connection.id);
  const row = id => service.connection(connection.id).models.find(model => model.id === id);
  assert.deepEqual(row('free-model').pricing, { currency: 'USD', unit: 'per_million_tokens', input: 0, cachedInput: null, cacheWriteInput: null, output: 0, source: 'ping' });
  assert.equal(row('opaque-model').pricing, undefined, 'nobody published a price, so there is none');
  assert.equal(row('partial-model').pricing, undefined, 'a half-published price is not completed with an invented 0');
  assert.equal(row('junk-model').pricing, undefined, 'an unreadable price is not invented');

  for (const id of ['free-model', 'opaque-model', 'partial-model', 'junk-model']) {
    await collect(engine.generate({ connectionId: connection.id, modelId: id, messages, stream: false }));
  }
  const byModel = Object.fromEntries(store.list('usage').map(record => [record.modelId, record]));
  assert.equal(byModel['free-model'].cost, 0, 'a model published at 0 costs 0 — a real number, with a basis');
  assert.equal(byModel['free-model'].costBasis, 'ping');
  assert.equal(byModel['free-model'].estimated, true);
  for (const id of ['opaque-model', 'partial-model', 'junk-model']) {
    assert.equal(byModel[id].cost, null, `${id}: no price means no cost — never 0`);
    assert.equal(byModel[id].costBasis, null);
    assert.equal(byModel[id].estimated, false);
  }
});

test('T3: a manual price carries its unit, currency and as-of date; a broken one is refused', async t => {
  const { store, service } = fixture(t, { fetchImpl: async () => json({ data: [{ id: 'vendor/model-a' }] }) });
  const connection = service.create({ providerId: 'custom', name: 'Gateway', endpoint: 'https://gateway.invalid/v1', apiKey: 'test-only-key' });
  await service.discover(connection.id);
  const row = () => service.connection(connection.id).models.find(model => model.id === 'vendor/model-a');

  const patched = service.patch(connection.id, { modelPricing: { modelId: 'vendor/model-a', input: 0.5, output: 1.5 } });
  const price = patched.models.find(model => model.id === 'vendor/model-a').pricing;
  assert.equal(price.source, 'manual');
  assert.equal(price.currency, 'USD');
  assert.equal(price.unit, 'per_million_tokens');
  assert.equal(price.asOf, new Date().toISOString().slice(0, 10));
  assert.equal(typeof price.updatedAt, 'number');

  for (const bad of [
    { input: '1', output: 2 },
    { input: 1 },
    { input: -1, output: 2 },
    { input: 1, output: 2000 },
  ]) {
    assert.throws(
      () => service.patch(connection.id, { modelPricing: { modelId: 'vendor/model-a', ...bad } }),
      error => error.code === 'INVALID_PRICE',
      `${JSON.stringify(bad)} is not a price the router stores`,
    );
  }
  assert.equal(row().pricing.input, 0.5, 'a refused price never replaces the stored one');

  // Giá lạ đơn vị/tiền tệ nằm sẵn trong store (file cũ, tay sửa) không được hiện ra:
  // `sanitizeConnection` chỉ nhận giá đã qua `normalizePrice` — USD/1M.
  store.put('connection', {
    ...store.get('connection', connection.id),
    models: [{ ...row(), pricing: { currency: 'EUR', unit: 'per_token', input: 1, output: 2, source: 'manual' } }],
  });
  const restarted = new ProviderService({ store, providers: service.providers });
  assert.equal(restarted.connection(connection.id).models[0].pricing, undefined, 'a price in the wrong unit or currency is dropped, never converted');
});

test('T3: a price change never rewrites a stored usage row — history keeps its own basis', async t => {
  const usage = { prompt_tokens: 1_000_000, completion_tokens: 0, total_tokens: 1_000_000 };
  const { store, service, engine } = fixture(t, {
    fetchImpl: async url => (String(url).endsWith('/models')
      ? json({ data: [{ id: 'vendor/model-a' }] })
      : json({ choices: [{ message: { content: 'ok' }, finish_reason: 'stop' }], usage })),
  });
  const connection = service.create({ providerId: 'custom', name: 'Gateway', endpoint: 'https://gateway.invalid/v1', apiKey: 'test-only-key' });
  await service.discover(connection.id);
  service.patch(connection.id, { modelPricing: { modelId: 'vendor/model-a', input: 1, output: 0 } });

  await collect(engine.generate({ connectionId: connection.id, modelId: 'vendor/model-a', messages, stream: false }));
  const first = store.list('usage')[0];
  assert.equal(first.cost, 1);
  assert.equal(first.costBasis, 'manual');
  assert.equal(first.estimated, true);

  // Giá đổi sau lượt chạy: bảng giá mới chỉ áp cho lượt SAU, không viết lại lượt cũ.
  service.patch(connection.id, { modelPricing: { modelId: 'vendor/model-a', input: 4, output: 0 } });
  const reread = store.list('usage')[0];
  assert.equal(reread.cost, 1, 'the stored row keeps the price it ran under');
  assert.equal(reread.costBasis, 'manual');
  assert.equal(reread.updatedAt ?? null, null, 'and nothing on the row was restamped');

  await collect(engine.generate({ connectionId: connection.id, modelId: 'vendor/model-a', messages, stream: false }));
  const rows = store.list('usage');
  assert.equal(rows.length, 2);
  assert.equal(rows[0].cost, 4, 'the new run uses the new price');
  assert.equal(rows[1].cost, 1, 'the old row is still the old number');
});

test('T3: setting a price never rewrites the model choice, its levels or an alias target', async t => {
  const { service } = fixture(t, {
    fetchImpl: async url => (String(url).endsWith('/models')
      ? json({ data: [{ id: 'vendor/model-a', reasoning: { supported_efforts: ['low', 'high'], default_effort: 'low' } }] })
      : json({ choices: [{ message: { content: 'ok' }, finish_reason: 'stop' }], usage: { prompt_tokens: 1, completion_tokens: 1 } })),
  });
  const connection = service.create({ providerId: 'custom', name: 'Gateway', endpoint: 'https://gateway.invalid/v1', apiKey: 'test-only-key' });
  await service.discover(connection.id);
  const alias = service.alias({ name: 'main-route', strategy: 'fallback', targets: [{ connectionId: connection.id, modelId: 'vendor/model-a' }] });
  service.setDefault({ aliasId: alias.id });

  const before = service.connection(connection.id).models[0];
  assert.deepEqual(before.thinkingLevels, ['low', 'high']);
  const defaultBefore = service.store.getDefault();

  service.patch(connection.id, { modelPricing: { modelId: 'vendor/model-a', input: 0.5, output: 1.5 } });

  // Giá là metadata của CHI PHÍ: nó không được đổi model đang chọn, mức thinking đã công bố,
  // cờ bật/tắt hay đích của alias.
  const after = service.connection(connection.id).models[0];
  assert.deepEqual(after.thinkingLevels, ['low', 'high'], 'the published levels are untouched');
  assert.equal(after.defaultThinking, before.defaultThinking);
  assert.equal(after.enabled, before.enabled);
  assert.equal(after.thinkingType, before.thinkingType);
  assert.equal(after.pricing.source, 'manual');
  assert.deepEqual(service.store.getDefault(), defaultBefore, 'the default route is untouched');
  assert.deepEqual(service.alias({ name: 'main-route', strategy: 'fallback', targets: [{ connectionId: connection.id, modelId: 'vendor/model-a' }] }, alias.id).targets, [{ connectionId: connection.id, modelId: 'vendor/model-a' }]);
  // Cùng một hàng dữ liệu cho mọi đường (pin hay alias): giá đọc từ connection row, không bản sao.
  const snapshot = service.snapshot();
  assert.equal(snapshot.connections.find(c => c.id === connection.id).models[0].pricing.input, 0.5);
  assert.equal(snapshot.defaultRoute.aliasId, alias.id);
});
