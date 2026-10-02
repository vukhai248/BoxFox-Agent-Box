// R2 / BUG-4: every model record carries `contextWindow`, `thinkingType`,
// `defaultThinking` and `thinkingLevels`, and those values come from the
// provider payload (or from the provider's own model ids) instead of a model
// name heuristic. These tests stub each provider's `/models` payload.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createProviders } from '../src/providers/index.mjs';
import { createAntigravityAdapter } from '../src/providers/antigravity.mjs';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';

const json = (value, options = {}) => new Response(JSON.stringify(value), { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
const connection = { id: 'connection', providerId: 'stub', endpoint: 'https://provider.invalid/v1' };
const credentials = { apiKey: 'test-only-key' };
// Đợt 18: mỗi dòng model còn phải nói được cửa sổ ngữ cảnh của nó ĐẾN TỪ ĐÂU, và
// giữ số nhà cung cấp đã công bố bên cạnh khi bảng tên thắng.
const SHARED_FIELDS = ['contextWindow', 'contextWindowSource', 'contextWindowReported', 'thinkingType', 'defaultThinking', 'thinkingLevels'];
const contract = model => SHARED_FIELDS.map(field => field in model);

function assertContract(models) {
  for (const model of models) assert.deepEqual(contract(model), [true, true, true, true, true, true], `model ${model.id} carries the shared metadata fields`);
}

const providers = fetchImpl => createProviders({ fetchImpl });

test('OpenRouter reads context_length and the reasoning block; no name guessing', async t => {
  const data = [
    {
      id: 'deepseek/deepseek-r1:free',
      name: 'DeepSeek R1 (Free)',
      context_length: 163840,
      top_provider: { context_length: 65536 },
      supported_parameters: ['reasoning', 'include_reasoning'],
      reasoning: { supported_efforts: ['low', 'medium', 'high'], default_effort: 'medium', default_enabled: true, mandatory: false },
    },
    {
      id: 'vendor/top-provider-only',
      name: 'Top provider only',
      top_provider: { context_length: 131072 },
      supported_parameters: ['reasoning'],
      reasoning: { supported_efforts: [], default_enabled: false, mandatory: false },
    },
    { id: 'vendor/r1-o3-thinking-in-the-name', name: 'Totally Thinking R1 O3', supported_parameters: [], pricing: { prompt: '0.000001' } },
  ];
  const adapter = providers(async url => (url.includes('/models') ? json({ data }) : json({ data: {} }))).openrouter;
  const { models } = await adapter.discover({ connection, credentials });
  assertContract(models);
  const [reasoning, params, plain] = models;
  assert.equal(reasoning.contextWindow, 163840, 'top-level context_length wins over top_provider.context_length');
  assert.equal(reasoning.thinkingType, 'effort');
  assert.deepEqual(reasoning.thinkingLevels, ['low', 'medium', 'high']);
  assert.equal(reasoning.defaultThinking, 'medium');
  assert.equal(params.contextWindow, 131072, 'top_provider.context_length is the fallback');
  assert.equal(params.thinkingType, 'effort', 'supported_parameters alone still declares thinking support');
  assert.deepEqual(params.thinkingLevels, [], 'no supported_efforts published, so no levels are invented');
  assert.equal(params.defaultThinking, null);
  assert.equal(plain.contextWindow, null, 'no context_length reported');
  assert.equal(plain.contextWindowSource, null, 'and no source either — an unknown name says nothing');
  assert.equal(plain.thinkingType, 'none', 'a reasoning-sounding name is no longer evidence');
  assert.deepEqual(plain.thinkingLevels, []);
});

test('Anthropic declares the token-budget control and the documented window', async t => {
  const data = [{ id: 'claude-sonnet-4-5', display_name: 'Claude Sonnet 4.5' }, { id: 'claude-sonnet-4-5[1m]', display_name: 'Claude Sonnet 4.5 (1M)' }];
  const adapter = providers(async () => json({ data })).anthropic;
  const { models } = await adapter.discover({ connection, credentials });
  assertContract(models);
  assert.equal(models[0].contextWindow, 200000);
  assert.equal(models[1].contextWindow, 1000000, 'the [1m] long-context marker raises the window');
  for (const model of models) {
    assert.equal(model.thinkingType, 'budget');
    assert.deepEqual(model.thinkingLevels, ['low', 'medium', 'high']);
    assert.equal(model.defaultThinking, null);
    assert.equal(model.capabilities.tools, 'reported');
  }
});

test('Gemini maps inputTokenLimit and the thinking flag from models.list', async t => {
  const data = {
    models: [
      { name: 'models/gemini-3-pro', displayName: 'Gemini 3 Pro', inputTokenLimit: 1048576, thinking: true, supportedGenerationMethods: ['generateContent'] },
      { name: 'models/gemini-2.0-flash', displayName: 'Gemini 2.0 Flash', inputTokenLimit: 1048576, supportedGenerationMethods: ['generateContent'] },
    ],
  };
  const adapter = providers(async () => json(data)).gemini;
  const { models } = await adapter.discover({ connection, credentials });
  assertContract(models);
  assert.equal(models[0].contextWindow, 1048576);
  assert.equal(models[0].thinkingType, 'effort');
  assert.deepEqual(models[0].thinkingLevels, ['low', 'medium', 'high']);
  assert.equal(models[1].contextWindow, 1048576);
  assert.equal(models[1].thinkingType, 'none', 'no thinking flag in the payload, so nothing is claimed');
  assert.deepEqual(models[1].thinkingLevels, []);
});

test('Gemini records the control the model really takes: level, budget or none', async t => {
  const data = {
    models: [
      { name: 'models/gemini-3.5-flash-lite', displayName: 'Gemini 3.5 Flash Lite', inputTokenLimit: 1048576, thinking: true, supportedGenerationMethods: ['generateContent'] },
      { name: 'models/gemini-flash-latest', displayName: 'Gemini Flash Latest', inputTokenLimit: 1048576, thinking: true, supportedGenerationMethods: ['generateContent'] },
      { name: 'models/gemini-2.5-flash', displayName: 'Gemini 2.5 Flash', inputTokenLimit: 1048576, thinking: true, supportedGenerationMethods: ['generateContent'] },
      { name: 'models/gemini-2.5-flash-lite', displayName: 'Gemini 2.5 Flash Lite', inputTokenLimit: 1048576, thinking: true, supportedGenerationMethods: ['generateContent'] },
      { name: 'models/gemma-4-31b-it', displayName: 'Gemma 4 31B IT', inputTokenLimit: 262144, thinking: true, supportedGenerationMethods: ['generateContent'] },
    ],
  };
  const adapter = providers(async () => json(data)).gemini;
  const { models } = await adapter.discover({ connection, credentials });
  assertContract(models);
  const byId = Object.fromEntries(models.map(model => [model.id, model]));
  for (const id of ['gemini-3.5-flash-lite', 'gemini-flash-latest']) {
    assert.equal(byId[id].thinkingType, 'effort', `${id} takes thinkingLevel`);
    assert.deepEqual(byId[id].thinkingLevels, ['low', 'medium', 'high']);
  }
  for (const id of ['gemini-2.5-flash', 'gemini-2.5-flash-lite']) {
    assert.equal(byId[id].thinkingType, 'budget', `${id} refuses a level and takes thinkingBudget`);
    assert.deepEqual(byId[id].thinkingLevels, ['low', 'medium', 'high'], 'the documented level to budget translation still lets the UI pick a depth');
  }
  assert.equal(byId['gemma-4-31b-it'].thinkingType, 'none', 'Gemma refuses both controls, so no thinking is claimed');
  assert.deepEqual(byId['gemma-4-31b-it'].thinkingLevels, []);
});

test('OpenAI-compatible endpoints use reasoning_effort levels and any reported window', async t => {
  const data = [
    { id: 'gpt-5.4' },
    { id: 'local-model', context_length: 32768, reasoning: { supported_efforts: ['low', 'high'], default_effort: 'low' } },
  ];
  const adapter = providers(async () => json({ data })).openai;
  const { models } = await adapter.discover({ connection, credentials });
  assertContract(models);
  assert.equal(models[0].thinkingType, 'effort');
  assert.deepEqual(models[0].thinkingLevels, ['minimal', 'low', 'medium', 'high'], 'the adapter control is reasoning_effort');
  assert.equal(models[0].contextWindow, null, 'OpenAI /models reports no window, so none is invented');
  assert.equal(models[0].contextWindowSource, null);
  assert.equal(models[1].contextWindow, 32768, 'a compatible gateway that reports a window is believed');
  assert.equal(models[1].contextWindowSource, 'reported', 'a number the payload published is labelled as such');
  assert.deepEqual(models[1].thinkingLevels, ['low', 'high'], 'published efforts win over the default set');
  assert.equal(models[1].defaultThinking, 'low');
});

test('Antigravity metadata comes from the published model ids', async t => {
  const adapter = createAntigravityAdapter({
    fetchImpl: async url => {
      if (url.includes('loadCodeAssist')) return json({ cloudaicompanionProject: 'project' });
      if (url.includes('fetchAvailableModels')) return json({ models: { 'gemini-3.8-flash-medium': { displayName: 'Gemini 3.8 Flash Medium' }, 'gemini-3.8-flash-low': { displayName: 'Gemini 3.8 Flash Low' }, 'claude-sonnet-4-6': {} } });
      return json({});
    },
  });
  const { models } = await adapter.discover({ connection: { id: 'account' }, credentials: { accessToken: 'test' } });
  assertContract(models);
  const byId = new Map(models.map(model => [model.id, model]));
  const selectable = byId.get('gemini-3.8-flash');
  assert.equal(selectable.contextWindow, 1000000);
  assert.equal(selectable.thinkingType, 'effort');
  assert.deepEqual(selectable.thinkingLevels, ['low', 'medium', 'high']);
  assert.equal(selectable.defaultThinking, 'medium', 'the level published in the backing model id');
  const fixed = byId.get('gemini-3.8-flash-low');
  assert.equal(fixed.contextWindow, 1000000);
  assert.equal(fixed.thinkingType, 'fixed', 'a tier suffix is already the model level');
  assert.deepEqual(fixed.thinkingLevels, []);
  assert.equal(fixed.defaultThinking, 'low');
  assert.equal(byId.get('claude-sonnet-4-6').thinkingType, 'effort');
});

test('curated catalogs no longer claim a live inventory', async () => {
  const registry = providers(async () => json({ data: [] }));
  for (const id of ['claude', 'codex', 'cline']) {
    const { models } = await registry[id].discover({ connection: { id }, credentials: { accessToken: 'test' } });
    assert.ok(models.length > 0);
    assert.equal(models.every(model => model.source === 'static'), true, `${id} catalog is labelled static`);
    assertContract(models);
  }
  const openrouter = providers(async () => { throw new Error('offline'); }).openrouter;
  assert.equal((await openrouter.discover({ connection, credentials })).models.every(model => model.source === 'static'), true);
  const opencode = providers(async () => { throw new Error('offline'); }).opencode;
  assert.equal((await opencode.discover({ connection, credentials })).models.every(model => model.source === 'static'), true);
});

test('a stored row picks up the shipped table, and a row outside the table keeps its own number', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-context-test-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const registry = providers(async () => json({ data: [] }));
  const service = new ProviderService({ store, providers: registry });
  const account = service.create({ providerId: 'deepseek', name: 'DeepSeek', endpoint: 'https://deepseek.invalid/v1', apiKey: 'test-only-key' });
  const legacy = store.get('connection', account.id);
  // Ba dòng cũ, đúng trạng thái trước đợt 18: dòng DeepSeek chính chủ không có số
  // (nên harness tự đoán 64 000), một dòng họ cũ có số thật của nhà cung cấp, và
  // một dòng người dùng tự gõ tay.
  legacy.models = [
    { id: 'deepseek-flash', name: 'deepseek-flash', source: 'live', capabilities: {}, enabled: true, contextWindow: null },
    { id: 'deepseek-r1', name: 'deepseek-r1', source: 'live', capabilities: {}, enabled: true, contextWindow: 64000 },
    { id: 'typed-by-hand', name: 'Typed By Hand', source: 'custom', capabilities: {}, enabled: true, contextWindow: 32768, contextWindowSource: 'manual' },
  ];
  store.put('connection', legacy);

  const restarted = new ProviderService({ store, providers: registry });
  const models = restarted.connection(account.id).models;
  assertContract(models);
  const row = id => models.find(model => model.id === id);
  assert.equal(row('deepseek-flash').contextWindow, 1000000, 'a name in the table gets the table’s number');
  assert.equal(row('deepseek-flash').contextWindowSource, 'documented');
  assert.equal(row('deepseek-r1').contextWindow, 64000, 'a name outside the table keeps the provider’s number');
  assert.equal(row('deepseek-r1').contextWindowSource, 'reported');
  assert.equal(row('typed-by-hand').contextWindow, 32768, 'a number the user typed is not normalized away');
  assert.equal(row('typed-by-hand').contextWindowSource, 'manual');

  const before = JSON.stringify(models);
  new ProviderService({ store, providers: registry });
  assert.equal(JSON.stringify(restarted.connection(account.id).models), before, 'normalization is idempotent');
});

test('W12: stored OpenCode rows are repaired from the verified registry, payload rows are left alone', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-opencode-metadata-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const registry = providers(async () => json({ data: [] }));
  const service = new ProviderService({ store, providers: registry });
  const account = service.create({ providerId: 'opencode', name: 'OpenCode Zen', endpoint: 'https://opencode.ai', apiKey: 'test-only-key' });
  const legacy = store.get('connection', account.id);
  // Rows as they were stored before the fix: the free tier publishes no thinking
  // metadata, so every non-curated id was flattened to `thinkingType: 'none'`.
  legacy.models = [
    { id: 'space-bunny-free', name: 'space-bunny-free', source: 'live', capabilities: {}, enabled: true, thinkingType: 'none', thinkingLevels: [], contextWindow: null },
    { id: 'gateway-unknown-free', name: 'gateway-unknown-free', source: 'live', capabilities: {}, enabled: true, thinkingType: 'none', thinkingLevels: [] },
    { id: 'payload-reasoner-free', name: 'Payload Reasoner', source: 'live', capabilities: {}, enabled: true, thinkingType: 'effort', thinkingLevels: ['low'], fieldSources: { thinking: 'live' } },
  ];
  store.put('connection', legacy);

  const restarted = new ProviderService({ store, providers: registry });
  const models = restarted.connection(account.id).models;
  assertContract(models);
  const row = id => models.find(model => model.id === id);
  assert.equal(row('space-bunny-free').thinkingType, 'effort');
  assert.deepEqual(row('space-bunny-free').thinkingLevels, ['minimal', 'low', 'medium', 'high']);
  assert.equal(row('gateway-unknown-free').thinkingLevels.length, 0, 'no evidence means no invented levels');
  assert.deepEqual(row('payload-reasoner-free').thinkingLevels, ['low'], 'levels the payload published are not overwritten by a supplementary source');
});

test('stored rows are normalized to the contract without inventing provider data', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-metadata-test-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const registry = providers(async () => json({ data: [] }));
  const service = new ProviderService({ store, providers: registry });
  const account = service.create({ providerId: 'antigravity' });
  const legacy = store.get('connection', account.id);
  legacy.models = [
    { id: 'gemini-3.8-flash-high', name: 'Gemini 3.8 Flash (High)', source: 'registry', capabilities: { reasoning: 'reported' }, thinkingLevels: ['low', 'medium', 'high'] },
    { id: 'gemini-3.8-flash', name: 'Gemini 3.8 Flash', source: 'registry', capabilities: { reasoning: 'reported' }, upstreamModelId: 'gemini-3.8-flash-medium' },
  ];
  store.put('connection', legacy);

  // A restart re-runs the sanitizer, which re-derives the provider's own rules.
  const restarted = new ProviderService({ store, providers: registry });
  const models = restarted.connection(account.id).models;
  assertContract(models);
  assert.equal(models[0].thinkingType, 'fixed');
  assert.deepEqual(models[0].thinkingLevels, []);
  assert.equal(models[0].contextWindow, 1000000);
  assert.equal(models[0].defaultThinking, 'high');
  assert.equal(models[1].thinkingType, 'effort');
  assert.deepEqual(models[1].thinkingLevels, ['low', 'medium', 'high']);
  assert.equal(models[1].defaultThinking, 'medium');

  // Normalization is idempotent: a second restart changes nothing.
  const before = JSON.stringify(restarted.connection(account.id).models);
  new ProviderService({ store, providers: registry });
  assert.equal(JSON.stringify(restarted.connection(account.id).models), before);
});
