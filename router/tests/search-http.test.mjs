// PART 2 — bảy đường HTTP của tab "Web Search" (task 2).
//
// Bất biến được ghim ở đây: cả tám dòng của hợp đồng nằm sau cổng admin, khoá thô
// chỉ rời router qua `POST .../reveal` (và `GET .../resolve` của harness, kiểm ở
// test hình dạng), và sandbox không bao giờ chạm được kho này qua listener bridge.
import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';
import { RouterEngine } from '../src/engine.mjs';
import { RouterError } from '../src/errors.mjs';
import { createRouterServer } from '../src/server.mjs';
import { SEARCH_PROVIDER_IDS } from '../src/search.mjs';

const model = { id: 'model-1', name: 'Model', capabilities: { streaming: 'reported', tools: 'reported', vision: 'unsupported' } };
const SECRETS = ['SEARCH-SECRET-1', 'ROTATED-KEY-2'];
const PROVIDER_NAMES = ['Brave Search', 'Tavily', 'Exa', 'Parallel', 'Firecrawl', 'SearXNG (self-hosted)', 'Cloudflare Web Search', 'Custom search endpoint'];

async function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-search-http-'));
  const store = new RouterStore({ dataDir: dir });
  const adapter = {
    discover: async () => ({ models: [model] }),
    quota: async () => null,
    async *generate() { throw new RouterError('UNAVAILABLE', 'No adapter configured for this test.', 502, true); },
  };
  // Nút Kiểm tra gọi ra ngoài qua `fetchImpl`; ở đây nó là một nhà cung cấp giả.
  const fetchImpl = async () => new Response(JSON.stringify({ web: { results: [{ title: 'BoxFox search test', url: 'https://example.com/' }] } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  const service = new ProviderService({ store, providers: { custom: adapter, deepseek: adapter, opencode: adapter }, fetchImpl });
  const engine = new RouterEngine({ service, deadlineMs: 3000 });
  const hosts = [];
  const server = createRouterServer({ service, engine, oauth: {}, allowedHosts: hosts });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => { server.closeAllConnections(); return new Promise(resolve => server.close(resolve)); });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const base = `http://127.0.0.1:${server.address().port}`;
  hosts.push(new URL(base).host);
  const headers = { 'X-BoxFox-Admin': '1', 'Content-Type': 'application/json', Host: hosts[0] };
  const responses = [];
  const send = async (path, { method = 'GET', body, header = headers } = {}) => {
    const response = await fetch(base + path, { method, headers: header, ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    const text = await response.text();
    responses.push(text);
    return { status: response.status, text, data: text ? JSON.parse(text) : null };
  };
  const scanForSecrets = () => {
    for (const text of responses) for (const secret of SECRETS) assert.equal(text.includes(secret), false, `no response may carry ${secret}`);
  };
  return { store, service, engine, server, base, headers, send, responses, scanForSecrets };
}

test('the search routes refuse requests without the admin header', async t => {
  const f = await fixture(t);
  const anonymous = { 'Content-Type': 'application/json', Host: f.headers.Host };
  const paths = [
    ['/api/router/search', 'GET'],
    ['/api/router/search/providers', 'POST'],
    ['/api/router/search/providers/brave', 'PATCH'],
    ['/api/router/search/providers/brave', 'DELETE'],
    ['/api/router/search/providers/brave/reveal', 'POST'],
    ['/api/router/search/providers/brave/test', 'POST'],
    ['/api/router/search/active', 'PUT'],
    ['/api/router/search/resolve', 'GET'],
  ];
  for (const [path, method] of paths) {
    const response = await f.send(path, { method, header: anonymous, body: ['POST', 'PATCH', 'PUT'].includes(method) ? {} : undefined });
    assert.equal(response.status, 403, `${method} ${path} needs the admin header`);
    assert.equal(response.data.error.code, 'FORBIDDEN');
  }
  assert.equal(f.service.snapshot().search.revision, 0, 'and nothing was written');
});

test('the state snapshot carries the search section', async t => {
  const f = await fixture(t);
  const state = await f.send('/api/router/state');
  assert.equal(state.status, 200);
  assert.ok(state.data.search, 'the search section is part of the state snapshot the interface polls');
  assert.deepEqual(state.data.search.providers.map(provider => provider.id), SEARCH_PROVIDER_IDS);
  assert.deepEqual(state.data.search.providers.map(provider => provider.name), PROVIDER_NAMES);
  assert.equal(state.data.search.activeProviderId, null);
  assert.equal(state.data.search.revision, 0);

  const listed = await f.send('/api/router/search');
  assert.equal(listed.status, 200);
  assert.deepEqual(listed.data, state.data.search, 'GET /api/router/search serves exactly the section of /state');
});

test('the browser never sees the raw key in any response', async t => {
  const f = await fixture(t);
  await f.send('/api/router/search/providers', { method: 'POST', body: { providerId: 'brave', apiKey: 'SEARCH-SECRET-1' } });
  await f.send('/api/router/search');
  await f.send('/api/router/state');
  await f.send('/api/router/search/providers/brave', { method: 'PATCH', body: { apiKey: 'ROTATED-KEY-2' } });
  await f.send('/api/router/search/active', { method: 'PUT', body: { providerId: 'brave' } });
  await f.send('/api/router/search/providers/brave/test', { method: 'POST' });
  f.scanForSecrets();

  // `reveal` là đường DUY NHẤT trả khoá thô cho giao diện, và nó chỉ trả khi được gọi.
  const revealed = await f.send('/api/router/search/providers/brave/reveal', { method: 'POST' });
  assert.equal(revealed.status, 200);
  assert.deepEqual(revealed.data, { id: 'brave', key: 'ROTATED-KEY-2' });
  for (const text of f.responses.slice(0, -1)) for (const secret of SECRETS) assert.equal(text.includes(secret), false, `only the reveal response may carry ${secret}`);
  assert.equal(JSON.stringify(f.service.snapshot()).includes('ROTATED-KEY-2'), false);
});

test('create, patch, activate, reveal, test and delete walk the documented shapes', async t => {
  const f = await fixture(t);
  const created = await f.send('/api/router/search/providers', { method: 'POST', body: { providerId: 'brave', apiKey: 'SEARCH-SECRET-1' } });
  assert.equal(created.status, 201);
  assert.equal(created.data.id, 'brave');
  assert.equal(created.data.prefix, 'SEARCH…');
  assert.equal(created.data.hasSecret, true);
  assert.equal(created.data.credentialPresent, true);
  assert.equal(JSON.stringify(created.data).includes('SEARCH-SECRET-1'), false);
  assert.equal(f.service.snapshot().search.revision, 1);

  const again = await f.send('/api/router/search/providers', { method: 'POST', body: { providerId: 'brave', apiKey: 'SEARCH-SECRET-1' } });
  assert.equal(again.status, 409);
  assert.equal(again.data.error.code, 'ALREADY_CONFIGURED');

  const missing = await f.send('/api/router/search/providers', { method: 'POST', body: { providerId: 'cloudflare', accountId: 'acct-1' } });
  assert.equal(missing.status, 400);
  assert.equal(missing.data.error.code, 'CREDENTIAL_REQUIRED');

  const broken = await f.send('/api/router/search/providers', { method: 'POST', body: { providerId: 'custom', endpoint: 'http://127.0.0.1:8123/search?q=1' } });
  assert.equal(broken.status, 400);
  assert.equal(broken.data.error.code, 'INVALID_ENDPOINT');

  const patched = await f.send('/api/router/search/providers/brave', { method: 'PATCH', body: { apiKey: 'ROTATED-KEY-2' } });
  assert.equal(patched.status, 200);
  assert.equal(patched.data.prefix, 'ROTATE…');

  const activated = await f.send('/api/router/search/active', { method: 'PUT', body: { providerId: 'brave' } });
  assert.equal(activated.status, 200);
  assert.equal(activated.data.activeProviderId, 'brave');
  assert.equal(activated.data.revision, 3, 'create, patch and activate each bumped the revision');
  assert.equal(JSON.stringify(activated.data).includes('ROTATED-KEY-2'), false);

  const resolved = await f.send('/api/router/search/resolve');
  assert.equal(resolved.status, 200, 'the harness reads the active credential over loopback');
  assert.equal(resolved.data.revision, activated.data.revision);
  assert.deepEqual(resolved.data.active, { id: 'brave', apiKey: 'ROTATED-KEY-2', accountId: null, endpoint: null });

  const revealed = await f.send('/api/router/search/providers/brave/reveal', { method: 'POST' });
  assert.equal(revealed.status, 200);
  assert.deepEqual(revealed.data, { id: 'brave', key: 'ROTATED-KEY-2' });

  const tested = await f.send('/api/router/search/providers/brave/test', { method: 'POST' });
  assert.equal(tested.status, 200);
  assert.deepEqual(Object.keys(tested.data).sort(), ['code', 'latencyMs', 'message', 'ok', 'providerId', 'sample', 'status']);
  assert.equal(tested.data.ok, true);
  assert.equal(tested.data.providerId, 'brave');
  assert.deepEqual(tested.data.sample, { title: 'BoxFox search test', url: 'https://example.com/' });
  const recorded = (await f.send('/api/router/search')).data.providers.find(provider => provider.id === 'brave');
  assert.equal(recorded.lastTest.status, 'passed');
  assert.equal(recorded.lastTest.httpStatus, 200);

  assert.equal((await f.send('/api/router/search/providers/exa/test', { method: 'POST' })).status, 404, 'testing an entry that is not configured is a 404');
  assert.equal((await f.send('/api/router/search/providers/brave', { method: 'PATCH', body: { apiKey: '' } })).status, 400, 'Brave cannot lose its key');

  const cleared = await f.send('/api/router/search/active', { method: 'PUT', body: { providerId: null } });
  assert.equal(cleared.status, 200);
  assert.equal(cleared.data.activeProviderId, null);
  assert.equal((await f.send('/api/router/search/resolve')).data.active, null);

  const deleted = await f.send('/api/router/search/providers/brave', { method: 'DELETE' });
  assert.equal(deleted.status, 200);
  assert.deepEqual(deleted.data, { deleted: true });
  const after = (await f.send('/api/router/search')).data;
  assert.equal(after.activeProviderId, null);
  assert.equal(after.providers.find(provider => provider.id === 'brave').credentialPresent, false);
  assert.equal(f.store.credentials('search:brave'), null, 'the credential row left with the entry');
  assert.equal((await f.send('/api/router/search/providers/brave', { method: 'DELETE' })).status, 404);
  // Không quét khoá ở đây: test này CỐ Ý gọi `reveal` và `resolve` — hai đường duy
  // nhất được phép mang khoá thô. Đường rò rỉ được ghim ở test "the browser never
  // sees the raw key in any response".
});

test('the bridge listener does not serve the search routes', async t => {
  const f = await fixture(t);
  const server = createRouterServer({
    service: f.service, engine: f.engine, oauth: { routes: [] },
    allowedHosts: ['127.0.0.1:3101'], bridgeHost: '127.0.0.1',
  });
  t.after(() => { server.bridge.close(); server.close(); });
  await new Promise(resolve => server.bridge.listen(0, '127.0.0.1', resolve));
  // `fetch` refuses to set the Host header, and the host allow-list keys on it, so the
  // probe uses node:http directly with the allowed host — the same shape the sandbox sees.
  const call = (path, options = {}) => new Promise((resolve, reject) => {
    const request = http.request({
      host: '127.0.0.1', port: server.bridge.address().port, path, method: options.method || 'GET',
      headers: { host: '127.0.0.1:3101', 'x-boxfox-admin': '1', ...(options.headers || {}) },
    }, response => {
      let body = '';
      response.setEncoding('utf8');
      response.on('data', chunk => { body += chunk; });
      response.on('end', () => resolve({ status: response.statusCode, json: async () => JSON.parse(body || '{}') }));
    });
    request.on('error', reject);
    request.end(request.body || '');
  });

  for (const [path, options] of [
    ['/api/router/search', {}],
    ['/api/router/search/providers', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' }) }],
    ['/api/router/search/providers/brave/reveal', { method: 'POST' }],
    ['/api/router/search/active', { method: 'PUT', headers: { 'content-type': 'application/json' }, body: '{"providerId":"brave"}' }],
    ['/api/router/search/resolve', {}],
  ]) {
    const response = await call(path, options);
    assert.equal(response.status, 404, `${path} must not be served by the bridge`);
    assert.equal((await response.json()).error.code, 'NOT_FOUND');
  }
  assert.equal(f.service.snapshot().search.revision, 0, 'the bridge never wrote to the search store');
});
