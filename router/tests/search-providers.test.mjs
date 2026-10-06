// PART 2 — kho khoá API tìm kiếm (`router/src/search.mjs`).
//
// Tám nhà cung cấp của tab "Web Search", khoá thô chỉ rời router qua `reveal()`
// và `resolve()`, và mọi thao tác ghi đều đẩy `revision` lên 1 để cache 15 giây
// phía harness biết mình phải đọc lại. Tệp này ghim ba bất biến: catalog đúng
// thứ tự mà nửa UI đang viết theo, khoá nằm trên đĩa chỉ dưới dạng bản mã, và
// nút Kiểm tra luôn trả lời kể cả khi endpoint hỏng.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';
import { SEARCH_PROVIDER_CATALOG, SEARCH_PROVIDER_IDS } from '../src/search.mjs';

const model = { id: 'model-1', name: 'Model', capabilities: { streaming: 'reported', tools: 'reported', vision: 'unsupported' } };
async function fixture(t, { fetchImpl = null } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-search-'));
  const store = new RouterStore({ dataDir: dir });
  const adapter = {
    discover: async () => ({ models: [model] }),
    quota: async () => null,
    async *generate() { yield { type: 'delta', delta: { content: 'BOXFOX_OK' } }; yield { type: 'finish', finishReason: 'stop' }; },
  };
  const service = new ProviderService({ store, providers: { custom: adapter, opencode: adapter, antigravity: adapter }, fetchImpl });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  return { dir, store, service, search: service.search };
}

test('the search catalog lists the eight providers plus the default choice', async t => {
  const f = await fixture(t);
  assert.deepEqual(SEARCH_PROVIDER_IDS, ['brave', 'tavily', 'exa', 'parallel', 'firecrawl', 'searxng', 'cloudflare', 'custom'], 'the order of the catalog is the order of the tab');
  assert.equal(SEARCH_PROVIDER_CATALOG.length, 8);

  const snapshot = f.service.snapshot().search;
  assert.deepEqual(snapshot.providers.map(provider => provider.id), SEARCH_PROVIDER_IDS, 'the snapshot lists every provider of the catalog, in order');
  assert.equal(snapshot.activeProviderId, null, '“Mặc định” is the choice before anything is configured');
  assert.equal(snapshot.revision, 0);
  for (const provider of snapshot.providers) {
    assert.equal(provider.credentialPresent, false);
    assert.equal(provider.hasSecret, false);
    assert.equal(provider.prefix, null);
    assert.equal(provider.endpoint, null);
    assert.equal(provider.lastTestedAt, null);
    assert.equal(provider.lastTest, null);
    assert.equal('apiKey' in provider, false, 'a view never carries a key field');
  }

  const byId = id => snapshot.providers.find(provider => provider.id === id);
  assert.deepEqual(byId('brave').requires, ['apiKey']);
  assert.deepEqual(byId('brave').envKeys, ['BRAVE_API_KEY', 'BOXFOX_BRAVE_API_KEY'], 'the env vars of the legacy path are part of the contract');
  assert.equal(byId('brave').icon, 'brave-search');
  assert.deepEqual(byId('searxng').requires, ['endpoint']);
  assert.deepEqual(byId('cloudflare').requires, ['accountId', 'apiKey']);
  assert.deepEqual(byId('custom').requires, ['endpoint']);
  assert.deepEqual(byId('custom').optional, ['apiKey'], 'a custom endpoint may carry a key, but does not have to');
  assert.equal(byId('parallel').icon, null);
});

test('creating a search provider stores the key encrypted and returns only a six character prefix', async t => {
  const f = await fixture(t);
  const view = f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });
  assert.equal(view.id, 'brave');
  assert.equal(view.name, 'Brave Search');
  assert.equal(view.hasSecret, true);
  assert.equal(view.credentialPresent, true);
  assert.equal(view.prefix, 'SEARCH…', 'only six characters of the key ever leave the store');
  assert.equal(view.lastTest, null);

  assert.deepEqual(f.store.credentials('search:brave'), { apiKey: 'SEARCH-SECRET-1' });
  const blob = f.store.db.prepare('SELECT encrypted FROM credentials WHERE id=?').get('search:brave').encrypted;
  assert.equal(blob.includes('SEARCH-SECRET-1'), false, 'the key is on disk only as ciphertext');
  assert.equal(JSON.stringify(f.store.get('search_provider', 'brave')).includes('SEARCH-SECRET-1'), false, 'and never in the record body');
  assert.equal(f.store.get('search_provider', 'brave').prefix, 'SEARCH…');
  assert.equal(f.service.snapshot().search.revision, 1, 'a create bumps the revision the harness caches on');

  const rotated = f.search.patch('brave', { apiKey: 'ROTATED-SECRET' });
  assert.equal(rotated.prefix, 'ROTATE…');
  assert.equal(f.store.credentials('search:brave').apiKey, 'ROTATED-SECRET');
  assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM credentials').get().n, 1, 'rotating reuses the same row instead of leaving a second one behind');
  assert.equal(f.service.snapshot().search.revision, 2);

  const noSecret = f.search.create({ providerId: 'custom', endpoint: 'http://127.0.0.1:8123/search' });
  assert.equal(noSecret.hasSecret, false);
  assert.equal(noSecret.credentialPresent, true, 'an endpoint is a credential too — the entry is usable');
  assert.equal(noSecret.prefix, null);
  assert.equal(f.store.credentials('search:custom'), null, 'an entry with no secret has no credential row');
  assert.equal(f.store.db.prepare('SELECT COUNT(*) AS n FROM credentials').get().n, 1);
});

test('the snapshot never contains a raw search key', async t => {
  const f = await fixture(t, { fetchImpl: async () => { throw new TypeError('fetch failed'); } });
  f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });
  f.search.create({ providerId: 'tavily', apiKey: 'TAVILY-SECRET-1' });
  f.search.create({ providerId: 'custom', endpoint: 'http://127.0.0.1:8123/search', apiKey: 'CUSTOM-SECRET-1' });
  f.search.setActive('brave');
  await f.search.probe('brave');

  const serialized = JSON.stringify(f.service.snapshot());
  for (const secret of ['SEARCH-SECRET-1', 'TAVILY-SECRET-1', 'CUSTOM-SECRET-1']) {
    assert.equal(serialized.includes(secret), false, `the snapshot must not carry ${secret}`);
  }
  assert.equal(serialized.includes('SEARCH…'), true, 'the prefix is how the interface recognises the stored key');
  assert.deepEqual(f.service.snapshot().search.providers.find(provider => provider.id === 'tavily').prefix, 'TAVILY…');
  assert.deepEqual(f.service.snapshot().search.activeProviderId, 'brave');
});

test('creating the same provider twice answers 409 ALREADY_CONFIGURED', async t => {
  const f = await fixture(t);
  f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });
  await assert.rejects(
    async () => f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-2' }),
    error => error.code === 'ALREADY_CONFIGURED' && error.status === 409 && /already configured/.test(error.message),
  );
  assert.equal(f.store.credentials('search:brave').apiKey, 'SEARCH-SECRET-1', 'the refused create never overwrote the stored key');

  const refuses = async (run, code, status) => assert.rejects(run, error => error.code === code && error.status === status);
  await refuses(async () => f.search.create({ providerId: 'brave' }), 'ALREADY_CONFIGURED', 409);
  await refuses(async () => f.search.create({ providerId: 'searxng' }), 'CREDENTIAL_REQUIRED', 400);
  await refuses(async () => f.search.create({ providerId: 'cloudflare', accountId: 'acct-1' }), 'CREDENTIAL_REQUIRED', 400);
  await refuses(async () => f.search.create({ providerId: 'nope', apiKey: 'x' }), 'NOT_FOUND', 404);
  await refuses(async () => f.search.create({}), 'INVALID_REQUEST', 400);
  await refuses(async () => f.search.patch('tavily', { apiKey: 'x' }), 'NOT_FOUND', 404);
  assert.equal(f.service.snapshot().search.providers.filter(provider => provider.credentialPresent).length, 1, 'a refused create writes nothing');

  // `apiKey: ""` xoá khoá — nhưng Brave không thể sống thiếu khoá, nên lệnh sửa bị
  // từ chối TRƯỚC khi ghi và dòng credential vẫn còn nguyên.
  await refuses(async () => f.search.patch('brave', { apiKey: '' }), 'CREDENTIAL_REQUIRED', 400);
  assert.equal(f.store.credentials('search:brave').apiKey, 'SEARCH-SECRET-1', 'a refused patch never removes the key');
  assert.equal(f.store.get('search_provider', 'brave').hasSecret, true);
});

test('the searxng entry rejects an endpoint with a query string', async t => {
  const f = await fixture(t);
  await assert.rejects(
    async () => f.search.create({ providerId: 'searxng', endpoint: 'http://127.0.0.1:8080/search?q=x' }),
    error => error.code === 'INVALID_ENDPOINT' && error.status === 400 && /key field/.test(error.message),
  );
  assert.equal(f.store.get('search_provider', 'searxng'), null, 'the refused entry is not on disk');
  await assert.rejects(
    async () => f.search.create({ providerId: 'custom', endpoint: 'http://169.254.169.254/latest' }),
    error => error.code === 'INVALID_ENDPOINT' && error.status === 400,
  );

  const view = f.search.create({ providerId: 'searxng', endpoint: 'http://127.0.0.1:8080/' });
  assert.equal(view.endpoint, 'http://127.0.0.1:8080', 'a trailing slash is trimmed, the endpoint is stored normalised');
  assert.equal(view.credentialPresent, true);
  assert.equal(f.search.reveal('searxng').key, '');
  await assert.rejects(
    async () => f.search.patch('searxng', { endpoint: 'not a url' }),
    error => error.code === 'INVALID_ENDPOINT' && error.status === 400,
  );
  assert.equal(f.store.get('search_provider', 'searxng').endpoint, 'http://127.0.0.1:8080', 'a refused patch leaves the stored endpoint alone');
});

test('setting the active provider bumps the revision and clearing it returns to default', async t => {
  const f = await fixture(t);
  f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });
  assert.equal(f.service.snapshot().search.revision, 1);
  assert.deepEqual(f.search.setActive('brave'), { activeProviderId: 'brave', revision: 2 });
  assert.equal(f.service.snapshot().search.activeProviderId, 'brave');
  assert.deepEqual(f.search.setActive('brave'), { activeProviderId: 'brave', revision: 3 }, 'choosing the same provider again still bumps the revision');
  assert.deepEqual(f.search.setActive(null), { activeProviderId: null, revision: 4 });
  assert.equal(f.service.snapshot().search.activeProviderId, null, 'null is “Mặc định”, the built-in path');

  const refuses = async (run, code, status) => assert.rejects(run, error => error.code === code && error.status === status);
  await refuses(async () => f.search.setActive('tavily'), 'NOT_FOUND', 404);
  await refuses(async () => f.search.setActive('nope'), 'NOT_FOUND', 404);
  assert.equal(f.service.snapshot().search.revision, 4, 'a refused selection never bumps the revision');
});

test('deleting the active provider resets the selection to default and removes the credential row', async t => {
  const f = await fixture(t);
  f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });
  f.search.create({ providerId: 'exa', apiKey: 'EXA-SECRET-1' });
  f.search.setActive('exa');
  const before = f.service.snapshot().search.revision;

  f.search.remove('brave');
  assert.equal(f.service.snapshot().search.activeProviderId, 'exa', 'deleting another provider leaves the selection alone');
  assert.equal(f.store.credentials('search:brave'), null, 'the credential row of the deleted provider leaves with it');
  assert.equal(f.store.get('search_provider', 'brave'), null);

  f.search.remove('exa');
  const snapshot = f.service.snapshot().search;
  assert.equal(snapshot.activeProviderId, null, 'the deleted provider was the active one, so the choice falls back to “Mặc định”');
  assert.equal(snapshot.revision, before + 2, 'both writes bumped the revision');
  assert.equal(snapshot.providers.find(provider => provider.id === 'exa').credentialPresent, false);
  assert.equal(f.store.credentials('search:exa'), null);
  await assert.rejects(async () => f.search.remove('exa'), error => error.code === 'NOT_FOUND' && error.status === 404);
  assert.equal(f.service.snapshot().search.revision, before + 2, 'the refused delete changes nothing');
});

test('reveal returns the raw key only through the reveal call', async t => {
  const f = await fixture(t);
  const view = f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });
  assert.equal(JSON.stringify(view).includes('SEARCH-SECRET-1'), false);
  assert.deepEqual(f.search.reveal('brave'), { id: 'brave', key: 'SEARCH-SECRET-1' });

  f.search.setActive('brave');
  const resolved = f.search.resolve();
  assert.equal(resolved.active.apiKey, 'SEARCH-SECRET-1', 'resolve is the harness exit, and it carries the key');
  assert.equal(resolved.active.id, 'brave');
  assert.equal(resolved.active.endpoint, null);
  assert.equal(resolved.active.accountId, null);
  assert.equal(resolved.revision, f.service.snapshot().search.revision);

  f.search.create({ providerId: 'custom', endpoint: 'http://127.0.0.1:8123/search' });
  assert.deepEqual(f.search.reveal('custom'), { id: 'custom', key: '' }, 'an entry with no secret reveals an empty string');
  await assert.rejects(async () => f.search.reveal('tavily'), error => error.code === 'NOT_FOUND' && error.status === 404);
  f.search.remove('brave');
  assert.equal(f.search.resolve().active, null, 'with nothing selected, resolve answers null');
});

test('the probe records the last test verdict and never throws on a broken endpoint', async t => {
  const calls = [];
  let mode = 'ok';
  const fetchImpl = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || 'GET', headers: init.headers || {}, body: init.body ? JSON.parse(String(init.body)) : null });
    if (mode === 'throw') throw new TypeError('fetch failed');
    if (mode === 'unauthorized') return new Response(JSON.stringify({ error: { message: 'Invalid API key' } }), { status: 401, headers: { 'Content-Type': 'application/json' } });
    if (mode === 'garbage') return new Response('<html>not json</html>', { status: 200, headers: { 'Content-Type': 'text/html' } });
    return new Response(JSON.stringify({ web: { results: [{ title: 'BoxFox search test', url: 'https://example.com/' }] } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  const f = await fixture(t, { fetchImpl });
  f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });

  const passed = await f.search.probe('brave');
  assert.deepEqual(Object.keys(passed).sort(), ['code', 'latencyMs', 'message', 'ok', 'providerId', 'sample', 'status']);
  assert.equal(passed.ok, true);
  assert.equal(passed.status, 200);
  assert.equal(passed.code, null);
  assert.equal(typeof passed.latencyMs, 'number');
  assert.deepEqual(passed.sample, { title: 'BoxFox search test', url: 'https://example.com/' });
  assert.equal(calls[0].url, 'https://api.search.brave.com/res/v1/web/search?q=boxfox+search+test&count=1', 'the trial query goes to the real endpoint of the provider');
  assert.equal(calls[0].headers['X-Subscription-Token'], 'SEARCH-SECRET-1');
  const recorded = f.service.snapshot().search.providers.find(provider => provider.id === 'brave');
  assert.equal(recorded.lastTest.status, 'passed');
  assert.equal(recorded.lastTest.httpStatus, 200);
  assert.equal(recorded.lastTest.code, null);
  assert.equal(Number.isNaN(Date.parse(recorded.lastTestedAt)), false, 'the verdict is timestamped');
  assert.equal(JSON.stringify(f.service.snapshot()).includes('SEARCH-SECRET-1'), false, 'even the probe record keeps the key out of the snapshot');

  mode = 'throw';
  const broken = await f.search.probe('brave');
  assert.equal(broken.ok, false, 'an unreachable endpoint is a verdict, not an exception');
  assert.equal(broken.code, 'UNAVAILABLE');
  assert.equal(broken.status, null);
  assert.equal(f.service.snapshot().search.providers.find(provider => provider.id === 'brave').lastTest.status, 'failed');

  mode = 'unauthorized';
  const refused = await f.search.probe('brave');
  assert.equal(refused.ok, false);
  assert.equal(refused.code, 'AUTH');
  assert.equal(refused.status, 401);
  assert.equal(refused.message, 'Invalid API key', 'the provider’s own words are passed through');

  mode = 'garbage';
  const garbage = await f.search.probe('brave');
  assert.equal(garbage.ok, false);
  assert.equal(garbage.code, 'UNAVAILABLE');
  assert.match(garbage.message, /not JSON/);

  mode = 'ok';
  f.search.create({ providerId: 'searxng', endpoint: 'http://127.0.0.1:8123' });
  const searx = await f.search.probe('searxng');
  assert.equal(searx.ok, true);
  assert.equal(calls.at(-1).url, 'http://127.0.0.1:8123/search?q=boxfox+search+test&format=json', 'searxng answers JSON on its own /search path');
  assert.equal('Authorization' in calls.at(-1).headers, false, 'a self-hosted searxng needs no key');

  const original = process.env.BOXFOX_BRAVE_SEARCH_URL;
  process.env.BOXFOX_BRAVE_SEARCH_URL = 'http://127.0.0.1:9911/search';
  try {
    await f.search.probe('brave');
    assert.equal(calls.at(-1).url, 'http://127.0.0.1:9911/search?q=boxfox+search+test&count=1', 'the E2E override replaces the real endpoint');
  } finally {
    if (original === undefined) delete process.env.BOXFOX_BRAVE_SEARCH_URL;
    else process.env.BOXFOX_BRAVE_SEARCH_URL = original;
  }
  await assert.rejects(async () => f.search.probe('tavily'), error => error.code === 'NOT_FOUND' && error.status === 404, 'probing an entry that is not configured is a 404');
});

test('a provider that echoes the key into its own error text cannot put it in the record', async t => {
  const page = 'x'.repeat(600);
  const fetchImpl = async () => new Response(
    JSON.stringify({ error: { message: `Bad credentials: SEARCH-SECRET-1 ${page}` } }),
    { status: 401, headers: { 'Content-Type': 'application/json' } },
  );
  const f = await fixture(t, { fetchImpl });
  f.search.create({ providerId: 'brave', apiKey: 'SEARCH-SECRET-1' });

  const verdict = await f.search.probe('brave');
  assert.equal(verdict.ok, false);
  assert.equal(verdict.code, 'AUTH');
  assert.equal(verdict.message.includes('SEARCH-SECRET-1'), false, 'the echoed key is redacted before it is stored');
  assert.equal(verdict.message.includes('[redacted]'), true);
  assert.equal(verdict.message.length <= 301, true, 'the provider text is capped at 300 characters plus the ellipsis');
  const raw = JSON.stringify(f.service.snapshot());
  assert.equal(raw.includes('SEARCH-SECRET-1'), false, 'the snapshot never carries the key');
  assert.equal(raw.includes('x'.repeat(400)), false, 'the snapshot never carries the whole page either');
});
