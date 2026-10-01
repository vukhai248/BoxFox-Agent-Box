import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import http from 'node:http';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';
import { RouterEngine } from '../src/engine.mjs';
import { RouterError } from '../src/errors.mjs';
import { createSafeFetch, validateEndpoint } from '../src/network.mjs';
import { createRouterServer } from '../src/server.mjs';
import { OAuthManager } from '../src/oauth.mjs';
import { normalizeUsage } from '../src/usage.mjs';
import { ModelSyncScheduler } from '../src/model-sync.mjs';

const model = { id: 'model-1', name: 'Model', capabilities: { streaming: 'reported', tools: 'reported', vision: 'unsupported' } };
async function fixture(t, overrides = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-test-'));
  const store = new RouterStore({ dataDir: dir });
  const adapter = { discover: async () => ({ models: [model] }), quota: async () => null, async *generate() { yield { type: 'delta', delta: { content: 'Xin chào 🦊' } }; yield { type: 'usage', usage: { prompt_tokens: 3, completion_tokens: 4, total_tokens: 7 } }; yield { type: 'finish', finishReason: 'stop' }; }, ...overrides };
  const service = new ProviderService({ store, providers: { custom: adapter, openai: adapter, anthropic: adapter, gemini: adapter, antigravity: adapter } });
  const engine = new RouterEngine({ service, deadlineMs: 2000 });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const c = service.create({ providerId: 'custom', name: 'Local simulator', endpoint: 'http://127.0.0.1:9999/v1', apiKey: 'SECRET-SIMULATOR' });
  await service.discover(c.id);
  return { dir, store, service, engine, adapter, c: service.connection(c.id) };
}
async function events(engine, input, options) { const out = []; for await (const e of engine.generate(input, options)) out.push(e); return out; }
const request = id => ({ connectionId: id, modelId: model.id, messages: [{ role: 'user', content: 'hello' }], stream: true });
test('Stop propagates cancellation and request deadline is bounded, without fallback after output', async t => {
  let aborted = false;
  const f = await fixture(t, { async *generate({ signal }) {
    yield { type: 'delta', delta: { content: 'first' } };
    await new Promise((_, reject) => { const cancel = () => { aborted = true; reject(signal.reason); }; if (signal.aborted) cancel(); else signal.addEventListener('abort', cancel, { once: true }); });
  } });
  const control = new AbortController();
  await assert.rejects((async () => { for await (const e of f.engine.generate(request(f.c.id), { signal: control.signal })) if (e.type === 'delta') control.abort(new DOMException('Stop', 'AbortError')); })(), e => e.code === 'CANCELLED');
  assert.equal(f.store.list('usage')[0].status, 'cancelled');
  f.engine.deadlineMs = 30;
  // Keep an event-loop handle alive because AbortSignal.timeout intentionally uses an unref timer.
  const keepAlive = setInterval(() => {}, 1000); t.after(() => clearInterval(keepAlive));
  await assert.rejects(events(f.engine, request(f.c.id)), e => e.code === 'TIMEOUT'); assert.equal(aborted, true); assert.equal(f.store.list('usage')[0].status, 'failed');
});

test('large request extension still aborts the provider and records TIMEOUT', async t => {
  let aborted = false;
  const f = await fixture(t, { async *generate({ signal }) {
    yield { type: 'delta', delta: { content: 'partial' } };
    await new Promise((_, reject) => {
      const cancel = () => { aborted = true; reject(signal.reason); };
      if (signal.aborted) cancel(); else signal.addEventListener('abort', cancel, { once: true });
    });
  } });
  f.engine.deadlineMs = 10;
  f.engine.largeDeadlineMs = 60;
  const keepAlive = setInterval(() => {}, 1000); t.after(() => clearInterval(keepAlive));
  const started = performance.now();
  await assert.rejects(events(f.engine, { ...request(f.c.id), max_tokens: 16000 }), e => e.code === 'TIMEOUT');
  assert.ok(performance.now() - started >= 40, 'large profile rather than the short deadline was applied');
  assert.equal(aborted, true);
  assert.equal(f.store.list('usage')[0].status, 'failed');
});
test('SQLite persists metadata, encrypted credentials and hash-only gateway keys', async t => {
  const { store, dir, c, service } = await fixture(t);
  const key = store.addKey('client', []);
  assert.equal(store.credentials(c.id).apiKey, 'SECRET-SIMULATOR');
  assert.equal(JSON.stringify(service.snapshot()).includes('SECRET-SIMULATOR'), false);
  assert.equal(JSON.stringify(service.snapshot()).includes(key.key), false);
  assert.equal(readFileSync(join(dir, 'router.sqlite')).includes(Buffer.from('SECRET-SIMULATOR')), false);
  const reopened = new RouterStore({ dataDir: dir }); assert.equal(reopened.credentials(c.id).apiKey, 'SECRET-SIMULATOR'); assert.ok(reopened.authenticateKey(key.key)); reopened.close();
});
test('rename preserves verification; credential change invalidates it; stale discovery cannot overwrite', async t => {
  const f = await fixture(t); f.service.setDefault({ connectionId: f.c.id, modelId: model.id });
  await events(f.engine, request(f.c.id));
  const before = f.service.connection(f.c.id);
  const renamed = f.service.patch(f.c.id, { name: 'Renamed' }); assert.equal(renamed.revision, before.revision); assert.equal(renamed.inferenceState, 'ready');
  let release; f.adapter.discover = () => new Promise(r => { release = r; });
  const discovering = f.service.discover(f.c.id); await new Promise(r => setImmediate(r));
  const edited = f.service.patch(f.c.id, { apiKey: 'new-secret' }); assert.equal(edited.inferenceState, 'unknown'); assert.deepEqual(edited.models, []);
  release({ models: [model] }); await assert.rejects(discovering, e => e.code === 'STALE_RESULT'); assert.deepEqual(f.service.connection(f.c.id).models, []); assert.equal(f.store.getDefault().connectionId, null);
});
test('round robin, ordered fallback, cooldown and key allowlist enforce actual enabled targets', async t => {
  const f = await fixture(t); const second = f.service.create({ providerId: 'custom', endpoint: f.c.endpoint, apiKey: 'second', name: 'second' }); await f.service.discover(second.id);
  const alias = f.service.alias({ name: 'pool', strategy: 'round_robin', targets: [{ connectionId: f.c.id, modelId: model.id }, { connectionId: second.id, modelId: model.id }] });
  const input = { ...request(f.c.id), connectionId: undefined, aliasId: alias.id };
  assert.equal((await events(f.engine, input))[0].meta.connectionId, f.c.id); assert.equal((await events(f.engine, input))[0].meta.connectionId, second.id);
  await assert.rejects(events(f.engine, input, { key: { id: 'restricted', allowedModels: ['other'] } }), e => e.status === 403);
  f.service.alias({ strategy: 'fallback' }, alias.id);
  const calls = []; f.adapter.generate = async function* ({ connection }) { calls.push(connection.id); if (connection.id === f.c.id) throw new RouterError('RATE_LIMIT', 'Limit', 429, true); yield { type: 'delta', delta: { content: 'fallback' } }; yield { type: 'finish', finishReason: 'stop' }; };
  assert.equal((await events(f.engine, input))[0].meta.connectionId, second.id); assert.deepEqual(calls, [f.c.id, second.id]); calls.length = 0;
  await events(f.engine, input); assert.deepEqual(calls, [second.id], 'the parked key is skipped, so the next turn goes straight to the second connection'); f.service.patch(second.id, { enabled: false }); await assert.rejects(events(f.engine, input), e => e.status === 429 && e.message === 'Limit'); assert.deepEqual(calls, [second.id], 'and a fully parked ring costs no provider call at all');
});
test('provider account order and round robin select verified accounts only', async t => {
  const f = await fixture(t); const second = f.service.create({ providerId: 'custom', endpoint: f.c.endpoint, apiKey: 'second', name: 'second' }); await f.service.discover(second.id);
  f.service.setProviderConfig('custom', { roundRobin: true, connectionOrder: [second.id, f.c.id] });
  const input = { providerId: 'custom', modelId: model.id, messages: [{ role: 'user', content: 'hello' }], stream: true };
  assert.equal((await events(f.engine, input))[0].meta.connectionId, second.id); assert.equal((await events(f.engine, input))[0].meta.connectionId, f.c.id);
  f.service.patch(second.id, { enabled: false }); assert.equal((await events(f.engine, input))[0].meta.connectionId, f.c.id);
});
test('never fallback after stream content, provider finish missing is a failure, usage remains unknown', async t => {
  const f = await fixture(t); const second = f.service.create({ providerId: 'custom', endpoint: f.c.endpoint, apiKey: 'second' }); await f.service.discover(second.id);
  const a = f.service.alias({ name: 'fallback', strategy: 'fallback', targets: [{ connectionId: f.c.id, modelId: model.id }, { connectionId: second.id, modelId: model.id }] });
  const calls = []; f.adapter.generate = async function* ({ connection }) { calls.push(connection.id); yield { type: 'delta', delta: { content: 'partial' } }; throw new RouterError('UNAVAILABLE', 'failed', 502, true); };
  await assert.rejects(events(f.engine, { ...request(f.c.id), connectionId: undefined, aliasId: a.id })); assert.deepEqual(calls, [f.c.id]); assert.equal(f.store.list('usage')[0].status, 'failed'); assert.equal(f.store.list('usage')[0].inputTokens, null);
});
test('failed live discovery exposes disabled stale fallback without creating a route', async t => {
  const fallback = { ...model, source: 'static', stale: true };
  const f = await fixture(t);
  const account = f.service.create({ providerId: 'antigravity' });
  f.store.saveCredentials(account.id, { accessToken: 'token', refreshToken: 'refresh', expiresAt: Date.now() + 3600000, oauthClient: { clientId: 'client' } });
  f.adapter.fallbackModels = [fallback]; f.adapter.discover = async () => { throw new RouterError('UNAVAILABLE', 'offline', 502, true); };
  await assert.rejects(f.service.discover(account.id));
  const degraded = f.service.connection(account.id); assert.equal(degraded.discoveryState, 'degraded'); assert.equal(degraded.models[0].enabled, false); assert.equal(degraded.models[0].stale, true); assert.equal(f.service.validTarget({ connectionId: account.id, modelId: model.id }), false);
});
test('reactive model-not-found refreshes once before retrying inference', async t => {
  const f = await fixture(t); let attempts = 0; let discoveries = 0;
  f.adapter.discover = async () => { discoveries++; return { models: [model] }; };
  f.adapter.generate = async function* () { attempts++; if (attempts === 1) throw new RouterError('MODEL_NOT_FOUND', 'refresh', 404, true); yield { type: 'delta', delta: { content: 'ok' } }; yield { type: 'finish', finishReason: 'stop' }; };
  const out = await events(f.engine, request(f.c.id)); assert.equal(out.find(value => value.type === 'delta').delta.content, 'ok'); assert.equal(discoveries, 1); assert.equal(attempts, 2);
});
test('a model probe persists per-model health without poisoning its account', async t => {
  const missing = { ...model, id: 'removed-model', name: 'Removed model' };
  const f = await fixture(t, { discover: async () => ({ models: [model, missing] }), async *generate({ body }) {
    if (body.model === missing.id) throw new RouterError('MODEL_NOT_FOUND', 'gone', 404, true);
    yield { type: 'delta', delta: { content: 'ok' } }; yield { type: 'finish', finishReason: 'stop' };
  } });
  await f.service.discover(f.c.id);
  await assert.rejects(f.service.testInference(f.c.id, missing.id), error => error.code === 'MODEL_NOT_FOUND');
  let current = f.service.connection(f.c.id); const probed = current.models.find(value => value.id === missing.id);
  assert.equal(current.inferenceState, 'unknown'); assert.equal(probed.health, 'unavailable'); assert.equal(probed.lastProbe.status, 'failed');
  assert.equal(f.service.validTarget({ connectionId: f.c.id, modelId: missing.id }), false);
  await f.service.discover(f.c.id); current = f.service.connection(f.c.id);
  assert.equal(current.models.find(value => value.id === missing.id).health, 'unavailable');
});
test('model sync scheduler refreshes only eligible durable connections', async t => {
  const f = await fixture(t); let calls = 0; f.adapter.discover = async () => { calls++; return { models: [model] }; };
  const disabled = f.service.create({ providerId: 'custom', endpoint: f.c.endpoint, apiKey: 'disabled' }); f.service.patch(disabled.id, { enabled: false });
  const scheduler = new ModelSyncScheduler({ service: f.service, staggerMs: 0 }); await scheduler.run(); assert.equal(calls, 1); assert.ok(f.service.connection(f.c.id).lastModelSyncAt);
});
test('usage accounting keeps cache, reasoning and total token fields normalized', async t => {
  const normalized = normalizeUsage({ input_tokens: 100, cache_read_input_tokens: 25, cache_creation_input_tokens: 5, output_tokens: 40, reasoning_tokens: 12 });
  assert.equal(normalized.prompt_tokens, 130); assert.equal(normalized.cached_tokens, 25); assert.equal(normalized.cache_creation_input_tokens, 5); assert.equal(normalized.completion_tokens, 40); assert.equal(normalized.reasoning_tokens, 12); assert.equal(normalized.total_tokens, 170);
  const f = await fixture(t, { async *generate() { yield { type: 'delta', delta: { content: 'ok' } }; yield { type: 'usage', usage: { prompt_tokens: 130, cached_tokens: 25, cache_creation_input_tokens: 5, completion_tokens: 40, total_tokens: 170, reasoning_tokens: 12 } }; yield { type: 'finish', finishReason: 'stop' }; } });
  await events(f.engine, request(f.c.id));
  const row = f.store.list('usage')[0]; assert.equal(row.status, 'passed'); assert.equal(row.inputTokens, 130); assert.equal(row.cachedTokens, 25); assert.equal(row.cacheCreationTokens, 5); assert.equal(row.reasoningTokens, 12); assert.equal(row.outputTokens, 40); assert.equal(row.totalTokens, 170); assert.equal(row.cost, null);
});
test('parallel requests isolate connection credentials/project and refresh is single-flight', async t => {
  const f = await fixture(t); const account = f.service.create({ providerId: 'antigravity' });
  f.store.saveCredentials(account.id, { accessToken: 'old', refreshToken: 'refresh', expiresAt: 0, oauthClient: { clientId: 'bound-client' }, projectId: 'project-one' });
  let count = 0; f.adapter.refresh = async ({ credentials }) => { count++; assert.equal(credentials.oauthClient.clientId, 'bound-client'); await new Promise(r => setTimeout(r, 20)); return { accessToken: 'new', refreshToken: 'rotated', expiresAt: Date.now() + 3600000 }; };
  const refreshed = await Promise.all([f.service.credentials(account.id), f.service.credentials(account.id)]); assert.equal(count, 1); assert.equal(refreshed[0].refreshToken, 'rotated'); assert.equal(f.store.credentials(account.id).oauthClient.clientId, 'bound-client');
  const seen = []; f.adapter.generate = async function* ({ connection, credentials }) { seen.push([connection.id, credentials.apiKey, credentials.projectId]); await new Promise(r => setTimeout(r, 5)); yield { type: 'delta', delta: { content: connection.id } }; yield { type: 'finish', finishReason: 'stop' }; };
  const second = f.service.create({ providerId: 'custom', endpoint: f.c.endpoint, apiKey: 'different', projectId: 'project-two' }); await f.service.discover(second.id);
  await Promise.all([events(f.engine, request(f.c.id)), events(f.engine, request(second.id))]); assert.deepEqual(seen.find(x => x[0] === f.c.id).slice(1), ['SECRET-SIMULATOR', undefined]); assert.deepEqual(seen.find(x => x[0] === second.id).slice(1), ['different', 'project-two']);
});
test('HTTP admin boundaries, client key/revocation, JSON/SSE/tool-call and real upstream simulator', async t => {
  const upstream = http.createServer((req, res) => { if (req.url === '/v1/models') { res.end(JSON.stringify({ data: [{ id: model.id }] })); return; } res.setHeader('Content-Type', 'text/event-stream'); res.write('data: {"text":"Xin chào 🦊"}\n\n'); res.end('data: [DONE]\n\n'); });
  await new Promise(r => upstream.listen(0, '127.0.0.1', r)); t.after(() => new Promise(r => upstream.close(r)));
  const safeFetch = createSafeFetch(); const upstreamUrl = `http://127.0.0.1:${upstream.address().port}/v1`;
  const f = await fixture(t, { discover: async () => ({ models: (await (await safeFetch(upstreamUrl + '/models')).json()).data }), async *generate({ signal }) { const response = await safeFetch(upstreamUrl + '/chat/completions', { method: 'POST', body: '{}', signal }); const text = await response.text(); assert.ok(text.includes('🦊')); yield { type: 'delta', delta: { content: 'Xin chào 🦊', tool_calls: [{ index: 0, id: 'call_1', type: 'function', function: { name: 'lookup', arguments: '{"q":' } }] } }; yield { type: 'delta', delta: { tool_calls: [{ index: 0, function: { arguments: '"🦊"}' } }] } }; yield { type: 'finish', finishReason: 'tool_calls' }; } });
  const hosts = []; const server = createRouterServer({ ...f, oauth: {}, allowedHosts: hosts }); await new Promise(r => server.listen(0, '127.0.0.1', r)); t.after(() => { server.closeAllConnections(); return new Promise(r => server.close(r)); });
  const base = `http://127.0.0.1:${server.address().port}`; hosts.push(new URL(base).host); const headers = { 'X-BoxFox-Admin': '1', 'Content-Type': 'application/json' };
  assert.equal((await fetch(base + '/api/router/state', { headers: { Host: headers.Host } })).status, 403);
  assert.equal((await fetch(base + '/api/router/state', { headers: { ...headers, Origin: 'https://evil.example' } })).status, 403);
  assert.equal(await new Promise(r => { http.get(base + '/api/router/health', { headers: { Host: 'evil.example' } }, res => { res.resume(); r(res.statusCode); }); }), 403);
  const auto = await fetch(base + '/api/router/connections', { method: 'POST', headers, body: JSON.stringify({ providerId: 'custom', name: 'Auto-discovered', endpoint: upstreamUrl, apiKey: 'AUTO-SECRET' }) });
  const autoConnection = await auto.json(); assert.equal(auto.status, 201); assert.equal(autoConnection.discoveryState, 'ready'); assert.equal(autoConnection.models[0].id, model.id); assert.equal(JSON.stringify(autoConnection).includes('AUTO-SECRET'), false);
  const modelTest = await fetch(`${base}/api/router/connections/${f.c.id}/models/${model.id}/test`, { method: 'POST', headers }); assert.equal(modelTest.status, 200); assert.equal((await modelTest.json()).status, 'passed');
  const keyResponse = await fetch(base + '/api/router/keys', { method: 'POST', headers, body: JSON.stringify({ name: 'test-client', allowedModels: [`${f.c.id}/${model.id}`] }) }); const key = await keyResponse.json(); assert.equal(keyResponse.status, 201);
  const publicHeaders = { Host: headers.Host, Authorization: `Bearer ${key.key}`, 'Content-Type': 'application/json' };
  assert.equal((await fetch(base + '/v1/models', { headers: publicHeaders })).status, 200);
  const input = { model: `${f.c.id}/${model.id}`, messages: [{ role: 'user', content: 'hello' }], stream: false };
  const result = await (await fetch(base + '/v1/chat/completions', { method: 'POST', headers: publicHeaders, body: JSON.stringify(input) })).json(); assert.equal(result.choices[0].message.tool_calls[0].function.arguments, '{"q":"🦊"}'); assert.equal(result.choices[0].finish_reason, 'tool_calls'); assert.ok(result.boxfox.requestId);
  const streamed = await (await fetch(base + '/v1/chat/completions', { method: 'POST', headers: publicHeaders, body: JSON.stringify({ ...input, stream: true }) })).text(); assert.ok(streamed.includes('chat.completion.chunk')); assert.ok(streamed.endsWith('data: [DONE]\n\n'));
  await fetch(base + '/api/router/keys/' + key.record.id, { method: 'DELETE', headers }); assert.equal((await fetch(base + '/v1/models', { headers: publicHeaders })).status, 401);
  assert.equal((await fetch(base + '/v1/router/generate', { method: 'POST', headers, body: JSON.stringify({ ...request(f.c.id), messages: [{ role: 'user', content: 'a' }, { role: 'user', content: 'b' }] }) })).status, 400);
});
test('endpoint guard blocks metadata, DNS rebinding addresses and redirects, explicitly allows loopback', async t => {
  assert.throws(() => validateEndpoint('http://169.254.169.254/latest')); assert.throws(() => validateEndpoint('http://metadata.google.internal')); assert.throws(() => validateEndpoint('http://user:secret@localhost')); assert.equal(validateEndpoint('http://localhost:1234/v1/'), 'http://localhost:1234/v1');
  const dnsFetch = createSafeFetch({ resolver: async () => [{ address: '169.254.169.254', family: 4 }] }); await assert.rejects(dnsFetch('http://example.com'));
  const server = http.createServer((req, res) => { res.writeHead(302, { Location: 'http://169.254.169.254' }); res.end(); }); await new Promise(r => server.listen(0, '127.0.0.1', r)); t.after(() => new Promise(r => server.close(r)));
  await assert.rejects(createSafeFetch()(`http://127.0.0.1:${server.address().port}`));
});
test('OAuth state, one-time callback, cancel, timeout and project failure keep separate health', async t => {
  const f = await fixture(t); const c = f.service.create({ providerId: 'antigravity' });
  let exchanges = 0;
  f.adapter.buildAuthUrl = ({ state, redirectUri }) => `https://accounts.example/auth?state=${state}&redirect_uri=${encodeURIComponent(redirectUri)}`;
  f.adapter.exchangeCode = async () => { exchanges++; return { accessToken: 'access', refreshToken: 'refresh', expiresAt: Date.now() + 3600000, oauthClient: { clientId: 'client' } }; };
  f.adapter.discover = async () => { throw new RouterError('PROJECT_REQUIRED', 'Project required.', 409); };
  const oauth = new OAuthManager({ service: f.service, port: 0, attemptMs: 10000 }); t.after(() => oauth.close());
  const a = await oauth.start(c.id), auth = new URL(a.authorizationUrl), redirect = auth.searchParams.get('redirect_uri'), state = auth.searchParams.get('state');
  assert.equal((await fetch(redirect + '?state=wrong&code=abc')).status, 400); assert.equal(exchanges, 0);
  assert.equal((await fetch(redirect + '?state=' + state + '&code=abc')).status, 200); assert.equal(exchanges, 1); assert.equal(f.service.connection(c.id).projectState, 'required'); assert.equal(f.service.connection(c.id).inferenceState, 'unknown'); assert.equal(f.service.connection(c.id).credentialPresent, true);
  assert.equal((await fetch(redirect + '?state=' + state + '&code=abc')).status, 400); assert.equal(exchanges, 1);
  const b = await oauth.start(c.id); oauth.cancel(b.id); const bUrl = new URL(b.authorizationUrl); assert.equal((await fetch(redirect + '?state=' + bUrl.searchParams.get('state') + '&code=abc')).status, 400);
  const d = await oauth.start(c.id); oauth.attempts.get(d.id).expires = Date.now() - 1; assert.equal((await fetch(redirect + '?state=' + new URL(d.authorizationUrl).searchParams.get('state') + '&code=abc')).status, 400);
});
