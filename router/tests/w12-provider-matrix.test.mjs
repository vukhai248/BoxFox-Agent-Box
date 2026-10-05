// W12.MODEL.METADATA — T5: một provider KHÁC với payload khác khuôn, và ca đối
// chứng âm: thiếu metadata thì phải ở lại `unknown` — không tự thành `unsupported`,
// không thành giá 0/"free", không đoán từ tên model.
//
// Gemini là khuôn khác hẳn OpenCode: `models[]` lồng nhau, tên có tiền tố `models/`,
// cửa sổ nằm ở `inputTokenLimit`, và thinking là cờ boolean + luật theo họ model.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createProviders } from '../src/providers/index.mjs';
import { EFFORT_LEVELS } from '../src/providers/common.mjs';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';

const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
const connection = { id: 'connection', providerId: 'gemini', endpoint: 'https://provider.invalid/v1' };
const credentials = { apiKey: 'test-only-key' };
const geminiRow = (models, id) => models.find(model => model.id === id);

test('T5/Gemini: a differently-shaped payload drives the record', async () => {
  const data = {
    models: [
      { name: 'models/gemini-3-pro', displayName: 'Gemini 3 Pro', inputTokenLimit: 1048576, thinking: true, supportedGenerationMethods: ['generateContent'] },
      { name: 'models/gemini-2.5-flash', displayName: 'Gemini 2.5 Flash', inputTokenLimit: 1048576, thinking: true, supportedGenerationMethods: ['generateContent'] },
      { name: 'models/gemini-embedding-001', displayName: 'Embedding', inputTokenLimit: 2048, supportedGenerationMethods: ['embedContent'] },
    ],
  };
  const adapter = createProviders({ fetchImpl: async () => json(data) }).gemini;
  const { models } = await adapter.discover({ connection, credentials });

  const pro = geminiRow(models, 'gemini-3-pro');
  assert.equal(pro.name, 'Gemini 3 Pro', 'the display name is kept and the `models/` prefix is stripped from the id');
  assert.equal(pro.contextWindow, 1048576, 'the window comes from inputTokenLimit');
  assert.equal(pro.contextWindowSource, 'reported');
  assert.equal(pro.thinkingType, 'effort', 'Gemini 3 takes thinkingLevel');
  assert.deepEqual(pro.thinkingLevels, ['low', 'medium', 'high']);
  assert.equal(pro.defaultThinking, null);

  const flash = geminiRow(models, 'gemini-2.5-flash');
  assert.equal(flash.thinkingType, 'budget', 'Gemini 2.5 takes thinkingBudget instead');
  assert.deepEqual(flash.thinkingLevels, ['low', 'medium', 'high']);

  assert.equal(models.some(model => model.id === 'gemini-embedding-001'), false, 'a model that cannot generate content is not an inventory row');
});

test('T5/Gemini: a payload that omits the window and the thinking flag invents nothing', async () => {
  const data = {
    models: [
      { name: 'models/mystery-model-v1', displayName: 'Mystery', supportedGenerationMethods: ['generateContent'] },
    ],
  };
  const adapter = createProviders({ fetchImpl: async () => json(data) }).gemini;
  const { models } = await adapter.discover({ connection, credentials });
  const row = models[0];

  assert.equal(row.contextWindow, null, 'nobody published a window, so the row has none — not 0, not a guess');
  assert.equal(row.contextWindowSource, null, 'and no provenance is claimed for a number that does not exist');
  assert.deepEqual(row.thinkingLevels, [], 'no thinking flag means no level is offered');
  assert.equal(row.thinkingType, 'none');
  assert.equal(row.pricing, undefined, 'an unpriced row is not free — it simply has no price');
  assert.equal(row.capabilities.reasoning, 'unknown', 'a missing capability stays unknown, never `unsupported`');
  assert.equal(row.capabilities.tools, 'reported', 'the adapter’s own rule for the Gemini family is a documented source, not a missing-field default');
});

test('T5/OpenCode: one payload field is kept even when the same payload has no reasoning block', async () => {
  const data = {
    data: [
      { id: 'ctx-only-free', context_length: 128000 },
      { id: 'price-only-free', pricing: { prompt: '0.000001', completion: '0.000002' } },
    ],
  };
  const adapter = createProviders({ fetchImpl: async () => json(data) }).opencode;
  const { models } = await adapter.discover({ connection: { ...connection, providerId: 'opencode' }, credentials });
  const [ctx, price] = models;

  // Trường nào payload có thì giữ, kể cả khi nó không nói gì về thinking: cửa sổ ngữ cảnh
  // không được rơi chỉ vì thiếu khối `reasoning`.
  assert.equal(ctx.contextWindow, 128000);
  assert.equal(ctx.contextWindowSource, 'reported');
  assert.equal(ctx.fieldSources.contextWindow, 'reported');
  assert.deepEqual(ctx.thinkingLevels, [], 'a row without reasoning evidence offers no level');
  assert.equal(ctx.thinkingSource, 'unknown');
  assert.equal(ctx.pricing, undefined);

  assert.equal(price.pricing.input, 1, 'a payload price is kept and read as USD per million tokens');
  assert.equal(price.pricing.source, 'ping', 'and it is labelled as coming from the provider payload');
  assert.equal(price.fieldSources.pricing, 'ping');
  assert.equal(price.contextWindow, null, 'the field the payload does not carry stays unknown');
  assert.equal(price.fieldSources.contextWindow, 'unknown');
});

test('T5: what the adapter leaves unknown stays unknown through the store', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-w12-matrix-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const providers = createProviders({ fetchImpl: async () => json({ models: [{ name: 'models/mystery-model-v1', supportedGenerationMethods: ['generateContent'] }] }) });
  const service = new ProviderService({ store, providers });
  const created = service.create({ providerId: 'gemini', name: 'Gemini', endpoint: 'https://provider.invalid/v1', apiKey: 'test-only-key' });
  await service.discover(created.id);

  const stored = service.connection(created.id).models.find(model => model.id === 'mystery-model-v1');
  assert.equal(stored.contextWindow, null, 'the store keeps the absence — it does not fill in a default');
  assert.equal(stored.contextWindowSource, null);
  assert.deepEqual(stored.thinkingLevels, []);
  assert.equal(stored.pricing, undefined);
  assert.equal(service.priceFor(stored, service.connection(created.id)), null, 'no price is null, not 0');
  assert.equal(service.validTarget({ connectionId: created.id, modelId: 'mystery-model-v1' }), true, 'a model without metadata is still routable');

  // Đọc lại từ store mới: không có bước nào ở tầng lưu tự sinh giá trị mặc định.
  const reopened = new ProviderService({ store, providers });
  const reread = reopened.connection(created.id).models.find(model => model.id === 'mystery-model-v1');
  assert.deepEqual(reread, stored);
});

test('T5: two adapters with different row shapes agree on what a shared payload means', async () => {
  const payload = {
    data: [
      { id: 'shared-gateway-free', name: 'Shared Gateway', context_length: 128000, reasoning: { supported_efforts: ['low', 'high'], default_effort: 'high' }, pricing: { prompt: '0.0000005', completion: '0.0000015' } },
      { id: 'shared-bare-free', name: 'Shared Bare' },
    ],
  };
  const providers = createProviders({ fetchImpl: async () => json(payload) });
  const [gateway, bare] = (await providers.openai.discover({ connection: { ...connection, providerId: 'openai' }, credentials })).models;
  assert.equal(gateway.contextWindow, 128000, 'the payload window wins in the OpenAI-compatible adapter');
  assert.equal(gateway.contextWindowSource, 'reported');
  assert.deepEqual(gateway.thinkingLevels, ['low', 'high']);
  assert.equal(gateway.defaultThinking, 'high');
  assert.equal(gateway.pricing.source, 'ping');
  assert.equal(bare.contextWindow, null, 'and a bare row still has no window');
  assert.equal(bare.pricing, undefined);

  const [opencodeGateway, opencodeBare] = (await providers.opencode.discover({ connection: { ...connection, providerId: 'opencode' }, credentials })).models;
  assert.equal(opencodeGateway.contextWindow, 128000, 'the same payload means the same thing in the OpenCode adapter');
  assert.equal(opencodeGateway.contextWindowSource, 'reported');
  assert.deepEqual(opencodeGateway.thinkingLevels, ['low', 'high']);
  assert.equal(opencodeGateway.fieldSources.thinking, 'live', 'and its provenance is labelled live, not assumed');
  assert.equal(opencodeGateway.pricing.source, 'ping');
  assert.equal(opencodeBare.contextWindow, null);
  assert.equal(opencodeBare.pricing, undefined);
  assert.deepEqual(opencodeBare.thinkingLevels, []);
  assert.equal(opencodeBare.thinkingSource, 'unknown', 'a row nobody has evidence for is not labelled verified');
  assert.equal(opencodeBare.fieldSources.thinking, 'unknown');
  assert.equal(opencodeBare.capabilities.reasoning, 'unknown');
  // Cùng một khuôn payload, hai adapter khác nhau: các quyết định giống nhau.
  assert.deepEqual(opencodeGateway.thinkingLevels, gateway.thinkingLevels);
  assert.deepEqual(EFFORT_LEVELS, ['minimal', 'low', 'medium', 'high'], 'the shared effort vocabulary is unchanged');
});
