// R3: how each adapter translates a thinking level onto the wire. `effort` maps
// to `reasoning_effort` (OpenAI/OpenRouter) or `thinkingLevel` (Gemini,
// Antigravity); `budget` maps to Anthropic's `thinking.budget_tokens`; `none`
// sends no thinking field at all, and a `fixed` model keeps its own level.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createProviders } from '../src/providers/index.mjs';
import { createAntigravityAdapter } from '../src/providers/antigravity.mjs';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';
import { RouterEngine } from '../src/engine.mjs';

const json = (value, options = {}) => new Response(JSON.stringify(value), { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
const messages = [{ role: 'user', content: 'Xin chào 🦊' }];

async function collect(iterator) {
  const values = [];
  for await (const event of iterator) values.push(event);
  return values;
}

function recorder(response) {
  const calls = [];
  const fetchImpl = async (url, init = {}) => {
    if (init.body) calls.push(typeof init.body === 'string' ? JSON.parse(init.body) : init.body);
    return response(url);
  };
  return { calls, fetchImpl };
}

const completion = () => json({ choices: [{ message: { content: 'ok' }, finish_reason: 'stop' }], usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 } });
const anthropicResponse = () => json({ content: [{ type: 'text', text: 'ok' }], stop_reason: 'end_turn', usage: { input_tokens: 1, output_tokens: 1 } });
const geminiResponse = () => json({ candidates: [{ content: { parts: [{ text: 'ok' }] }, finishReason: 'STOP' }], usageMetadata: { promptTokenCount: 1, candidatesTokenCount: 1 } });
const sse = payload => new Response(`data: ${JSON.stringify(payload)}\n\n`, { headers: { 'Content-Type': 'text/event-stream' } });

async function openaiRequest(level, extra = {}) {
  const { calls, fetchImpl } = recorder(completion);
  const adapter = createProviders({ fetchImpl }).openai;
  await collect(adapter.generate({ connection: { providerId: 'openai', endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' }, body: { model: 'gpt-5.4', messages, stream: false, ...(level === undefined ? {} : { thinkingLevel: level }), ...extra } }));
  return calls[0];
}

test('OpenAI: effort levels become reasoning_effort, none sends no thinking field', async () => {
  const high = await openaiRequest('high');
  assert.equal(high.reasoning_effort, 'high');
  assert.equal('thinkingLevel' in high, false);
  assert.equal('thinking' in high, false);
  assert.equal((await openaiRequest('minimal')).reasoning_effort, 'minimal');
  for (const level of ['none', 'auto', undefined]) {
    const request = await openaiRequest(level);
    assert.equal('reasoning_effort' in request, false, `level ${level} sends no reasoning_effort`);
    assert.equal('thinking' in request, false);
  }
});

test('OpenRouter: effort levels become reasoning.effort, auto/none send nothing', async () => {
  const { calls, fetchImpl } = recorder(completion);
  const adapter = createProviders({ fetchImpl }).openrouter;
  for (const thinkingLevel of ['low', 'medium', 'high', 'none', 'auto']) {
    await collect(adapter.generate({ connection: { endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' }, body: { model: 'vendor/model', messages, stream: false, thinkingLevel } }));
  }
  assert.deepEqual(calls[0].reasoning, { effort: 'low' });
  assert.deepEqual(calls[2].reasoning, { effort: 'high' });
  assert.equal('reasoning' in calls[3], false, 'none means the provider default, no thinking field');
  assert.equal('reasoning' in calls[4], false);
  assert.equal(calls.every(call => !('thinkingLevel' in call)), true);
});

test('W12/OpenCode: the level BoxFox stores as thinkingLevel reaches the provider as reasoning.effort', async () => {
  // The harness sends `thinkingLevel` (already checked against the model's published
  // levels); the Responses endpoint refuses `reasoning_effort` in the body and only
  // accepts `reasoning: {effort, summary}`. Before the fix the adapter deleted
  // `thinkingLevel` without ever reading it, so a chosen level never left BoxFox.
  const { calls, fetchImpl } = recorder(() => sse({ type: 'response.completed', response: { output: [] } }));
  const adapter = createProviders({ fetchImpl }).opencode;
  const body = level => ({ model: 'space-bunny-free', messages, stream: true, ...(level ? { thinkingLevel: level } : {}) });
  await collect(adapter.generate({ connection: { endpoint: 'https://opencode.ai' }, credentials: {}, body: body('high') }));
  await collect(adapter.generate({ connection: { endpoint: 'https://opencode.ai' }, credentials: {}, body: body('none') }));
  await collect(adapter.generate({ connection: { endpoint: 'https://opencode.ai' }, credentials: {}, body: body(undefined) }));
  assert.deepEqual(calls[0].reasoning, { effort: 'high', summary: 'auto' });
  assert.equal('thinkingLevel' in calls[0], false, 'the router-internal field is not forwarded');
  assert.equal('reasoning_effort' in calls[0], false, 'the endpoint refuses this spelling');
  for (const call of calls.slice(1)) {
    assert.equal('reasoning' in call, false, 'none/absent means the provider default, no thinking field');
    assert.equal('thinkingLevel' in call, false);
  }
});

test('Anthropic: budget thinking maps low/medium/high to 2048/8192/16384', async () => {
  const { calls, fetchImpl } = recorder(anthropicResponse);
  const adapter = createProviders({ fetchImpl }).anthropic;
  const send = (body, extra = {}) => collect(adapter.generate({ connection: { endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' }, body: { model: 'claude-sonnet-4-5', messages, stream: false, max_tokens: 1024, ...body, ...extra } }));
  await send({ thinkingLevel: 'low' });
  await send({ thinkingLevel: 'medium' });
  await send({ thinkingLevel: 'high' });
  await send({ thinkingLevel: 'none' });
  await send({});
  await send({ thinkingLevel: 'high' }, { thinkingType: 'fixed' });
  assert.equal(calls[0].thinking.budget_tokens, 2048);
  assert.equal(calls[1].thinking.budget_tokens, 8192);
  assert.equal(calls[2].thinking.budget_tokens, 16384);
  assert.ok(calls[2].max_tokens > 16384, 'the max token budget is lifted above the thinking budget');
  assert.equal('thinking' in calls[3], false, 'none sends no thinking block');
  assert.equal('thinking' in calls[4], false);
  assert.equal('thinking' in calls[5], false, 'a fixed model already carries its level');
});

test('Gemini: the level is sent as thinking_level, never as a token budget', async () => {
  const { calls, fetchImpl } = recorder(geminiResponse);
  const adapter = createProviders({ fetchImpl }).gemini;
  await collect(adapter.generate({ connection: { endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' }, body: { model: 'gemini-3-pro', messages, stream: false, thinkingLevel: 'high' } }));
  await collect(adapter.generate({ connection: { endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' }, body: { model: 'gemini-3-pro', messages, stream: false, thinkingLevel: 'none' } }));
  await collect(adapter.generate({ connection: { endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' }, body: { model: 'gemini-3-pro', messages, stream: false } }));
  assert.deepEqual(calls[0].generationConfig.thinkingConfig, { thinkingLevel: 'high', includeThoughts: true });
  assert.equal('thinkingBudget' in (calls[0].generationConfig.thinkingConfig || {}), false);
  assert.equal('thinkingConfig' in calls[1].generationConfig, false, 'none sends no thinking config');
  assert.equal('thinkingConfig' in calls[2].generationConfig, false);
});

test('Gemini 2.5 takes the documented thinkingBudget, Gemma takes no thinking field at all', async () => {
  const { calls, fetchImpl } = recorder(geminiResponse);
  const adapter = createProviders({ fetchImpl }).gemini;
  const send = (model, thinkingLevel) => collect(adapter.generate({ connection: { endpoint: 'https://provider.invalid/v1' }, credentials: { apiKey: 'k' }, body: { model, messages, stream: false, ...(thinkingLevel ? { thinkingLevel } : {}) } }));
  await send('gemini-2.5-flash', 'low');
  await send('gemini-2.5-flash', 'medium');
  await send('gemini-2.5-flash', 'high');
  await send('gemini-2.5-flash', 'none');
  await send('gemma-4-31b-it', 'low');
  assert.deepEqual(calls[0].generationConfig.thinkingConfig, { thinkingBudget: 1024, includeThoughts: true });
  assert.deepEqual(calls[1].generationConfig.thinkingConfig, { thinkingBudget: 8192, includeThoughts: true });
  assert.deepEqual(calls[2].generationConfig.thinkingConfig, { thinkingBudget: 24576, includeThoughts: true });
  assert.equal('thinkingLevel' in calls[0].generationConfig.thinkingConfig, false, 'the two controls are never combined');
  assert.equal(calls[3].generationConfig?.thinkingConfig ?? null, null, 'none sends no thinking config');
  assert.equal(calls[4].generationConfig?.thinkingConfig ?? null, null, 'Gemma refuses both controls, so neither is sent');
});

test('Antigravity: selectable models honour the level, fixed models keep their own', async () => {
  const calls = [];
  const adapter = createAntigravityAdapter({
    fetchImpl: async (_url, init) => {
      calls.push(JSON.parse(init.body));
      return sse({ response: { candidates: [{ content: { parts: [{ text: 'BOXFOX_OK' }] }, finishReason: 'STOP' }] } });
    },
  });
  const send = (model, thinkingLevel) => collect(adapter.generate({ connection: { id: 'account', projectId: 'project' }, credentials: { accessToken: 'token' }, body: { model, messages, stream: false, max_tokens: 64, ...(thinkingLevel ? { thinkingLevel } : {}) } }));
  await send('gemini-3.8-flash', 'high');
  await send('gemini-3.8-flash', 'none');
  await send('gemini-3.8-flash-low', 'high');
  assert.deepEqual(calls[0].request.generationConfig.thinkingConfig, { thinkingLevel: 'high', includeThoughts: true });
  assert.deepEqual(calls[1].request.generationConfig.thinkingConfig, { thinkingLevel: 'medium', includeThoughts: true }, 'none falls back to the model level');
  assert.deepEqual(calls[2].request.generationConfig.thinkingConfig, { thinkingLevel: 'low', includeThoughts: true }, 'a fixed model ignores the caller level');
});

test('a model the provider reports as non-thinking receives no thinking field', async t => {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-thinking-test-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const seen = [];
  const plain = { id: 'plain-model', name: 'Plain', source: 'live', stale: false, contextWindow: null, thinkingType: 'none', defaultThinking: null, thinkingLevels: [], capabilities: { streaming: 'reported', tools: 'reported', vision: 'unknown' } };
  const adapter = {
    discover: async () => ({ models: [plain] }),
    quota: async () => null,
    async *generate({ body }) {
      seen.push(body);
      yield { type: 'delta', delta: { content: 'ok' } };
      yield { type: 'finish', finishReason: 'stop' };
    },
  };
  const service = new ProviderService({ store, providers: { custom: adapter } });
  const engine = new RouterEngine({ service, deadlineMs: 2000 });
  const connection = service.create({ providerId: 'custom', name: 'simulator', endpoint: 'http://127.0.0.1:9999/v1', apiKey: 'SECRET' });
  await service.discover(connection.id);
  await collect(engine.generate({ connectionId: connection.id, modelId: plain.id, messages, stream: true, thinkingLevel: 'high', reasoning_effort: 'high' }));
  assert.equal('thinkingLevel' in seen[0], false, 'the stored default level of a non-thinking model is not forwarded');
  assert.equal('reasoning_effort' in seen[0], false);
});
