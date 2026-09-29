// Vòng 29 §1.4 — năm đường dẫn khoá qua HTTP, đúng tên mà nửa UI đã chốt, cộng
// `GET /api/router/connections` (giờ trả connection đã trang trí như `/state`).
//
// Bất biến được ghim ở đây: không một chuỗi secret nào rời khỏi router (chỉ `prefix`
// ≤ 6 ký tự), xoá một connection còn khoá là 409 `KEYS_PRESENT`, và `keys/import`
// không bị nuốt thành một key id tên "import".
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';
import { RouterEngine } from '../src/engine.mjs';
import { RouterError } from '../src/errors.mjs';
import { createRouterServer } from '../src/server.mjs';

const model = { id: 'model-1', name: 'Model', capabilities: { streaming: 'reported', tools: 'reported', vision: 'unsupported' } };
const KEY_FIELDS = ['id', 'label', 'prefix', 'createdAt', 'state', 'cooldownUntil', 'resetAt', 'lastErrorCode', 'lastErrorMessage', 'lastUsedAt'];
const SECRETS = ['FIRST-SECRET', 'SECOND-SECRET', 'MOVED-SECRET', 'ELSEWHERE-SECRET'];

async function fixture(t) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-router-keyring-http-'));
  const store = new RouterStore({ dataDir: dir });
  const adapter = {
    discover: async () => ({ models: [model] }),
    quota: async () => null,
    async *generate() { throw new RouterError('UNAVAILABLE', 'No adapter configured for this test.', 502, true); },
  };
  const service = new ProviderService({ store, providers: { custom: adapter, deepseek: adapter, opencode: adapter } });
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
  const c = service.create({ providerId: 'custom', name: 'Local simulator', endpoint: 'http://127.0.0.1:9999/v1', apiKey: 'FIRST-SECRET' });
  await service.discover(c.id);
  const scanForSecrets = () => {
    for (const text of responses) for (const secret of SECRETS) assert.equal(text.includes(secret), false, `no response may carry ${secret}`);
  };
  return { store, service, engine, server, base, headers, send, responses, scanForSecrets, c: service.connection(c.id) };
}

test('the key routes serve one decorated ring, key by key, and leak no secret', async t => {
  const f = await fixture(t);
  const ring = path => `/api/router/connections/${f.c.id}${path}`;

  const added = await f.send(ring('/keys'), { method: 'POST', body: { key: 'SECOND-SECRET' } });
  assert.equal(added.status, 201, 'a new key answers 201 with the decorated connection');
  assert.equal(added.data.keys.length, 2);
  assert.equal(added.data.keys[1].label, 'Key 2');
  assert.equal(added.data.keys[1].prefix, 'SECOND…');
  assert.equal(added.data.keys[0].prefix, 'FIRST-…', 'and the ring never carries more than six characters of a secret');
  assert.equal(added.data.keys[0].lastUsedAt, null);
  assert.equal(added.data.activeKeyId, null);

  const listed = await f.send('/api/router/connections');
  const state = await f.send('/api/router/state');
  assert.equal(listed.status, 200);
  const fromList = listed.data.find(connection => connection.id === f.c.id);
  const fromState = state.data.connections.find(connection => connection.id === f.c.id);
  assert.deepEqual(fromList.keys, fromState.keys, 'GET /connections and GET /state serve the same decorated ring');
  for (const key of fromState.keys) for (const field of KEY_FIELDS) assert.ok(field in key, `${field} is part of the key contract`);

  const secondId = added.data.keys[1].id;
  const relabelled = await f.send(ring(`/keys/${secondId}`), { method: 'PATCH', body: { label: 'Khoá 2' } });
  assert.equal(relabelled.status, 200);
  assert.equal(relabelled.data.keys[1].label, 'Khoá 2');
  assert.equal(relabelled.data.keys[1].prefix, 'SECOND…', 'a label change never touches the secret');
  assert.deepEqual(relabelled.data.models.map(entry => entry.id), [model.id], 'and it never resets the model inventory (unlike the legacy PATCH { apiKey })');

  const replaced = await f.send(ring(`/keys/${secondId}`), { method: 'PATCH', body: { key: 'MOVED-SECRET' } });
  assert.equal(replaced.status, 200);
  assert.equal(replaced.data.keys[1].prefix, 'MOVED-…');
  assert.equal((await f.service.credentials(f.c.id, null, secondId)).apiKey, 'MOVED-SECRET');

  const probe = await f.send(ring(`/keys/${secondId}/try`), { method: 'POST', body: {} });
  assert.equal(probe.status, 200);
  assert.equal(probe.data.probe, null, 'no model named ⇒ nothing is probed, the button keeps its label');
  assert.equal(probe.data.connection.activeKeyId, secondId, 'and the key it was pressed on is the active one');
  assert.equal(probe.data.connection.keys[1].state, 'ready');

  f.scanForSecrets();
});

test('a connection that still holds keys refuses deletion, and only its own keys leave with it', async t => {
  const f = await fixture(t);
  const ring = path => `/api/router/connections/${f.c.id}${path}`;
  await f.send(ring('/keys'), { method: 'POST', body: { key: 'SECOND-SECRET' } });
  const keys = f.service.connection(f.c.id).keys;

  const refused = await f.send(`/api/router/connections/${f.c.id}`, { method: 'DELETE' });
  assert.equal(refused.status, 409);
  assert.equal(refused.data.error.code, 'KEYS_PRESENT');
  assert.match(refused.data.error.message, /Remove the 2 keys on this connection first/);

  const dropped = await f.send(ring(`/keys/${keys[1].id}`), { method: 'DELETE' });
  assert.equal(dropped.status, 200);
  assert.equal(dropped.data.keys.length, 1);
  assert.equal(f.store.credentials(keys[1].id), null, 'the row that belonged to that key leaves with it');
  assert.equal((await f.send(`/api/router/connections/${f.c.id}`, { method: 'DELETE' })).status, 409);

  const emptied = await f.send(ring(`/keys/${keys[0].id}`), { method: 'DELETE' });
  assert.equal(emptied.status, 200);
  assert.deepEqual(emptied.data.keys, []);
  assert.equal(emptied.data.credentialPresent, false);
  assert.equal(emptied.data.authState, 'required', 'an emptied connection stays alive and waits for a key');
  assert.equal(emptied.data.enabled && f.service.validTarget({ connectionId: f.c.id, modelId: model.id }), false, 'and it is out of routing while it has no key');

  const deleted = await f.send(`/api/router/connections/${f.c.id}`, { method: 'DELETE' });
  assert.equal(deleted.status, 200);
  assert.deepEqual(deleted.data, { deleted: true });

  const other = f.service.create({ providerId: 'custom', name: 'Other', endpoint: f.c.endpoint, apiKey: 'MOVED-SECRET' });
  const importPath = `/api/router/connections/${other.id}/keys/import`;
  assert.equal((await f.send(importPath, { method: 'POST', body: { fromConnectionId: 'missing-id' } })).status, 404);
  assert.equal((await f.send(importPath, { method: 'POST', body: { fromConnectionId: other.id } })).data.error.message, 'Choose a different connection.');
  assert.equal((await f.send(importPath, { method: 'POST', body: {} })).data.error.message, 'Choose a connection to move keys from.');
  assert.equal((await f.send(importPath, { method: 'POST', body: { fromConnectionId: f.c.id } })).status, 404, 'a deleted connection cannot be a source');
  assert.equal(f.service.connection(other.id).keys.length, 1, 'and a refused import never touches a ring');
  f.scanForSecrets();
});

test('import moves every key of the source to the end of the target ring, and refuses the shapes it cannot serve', async t => {
  const f = await fixture(t);
  const importPath = `/api/router/connections/${f.c.id}/keys/import`;
  const source = f.service.create({ providerId: 'custom', name: 'Source', endpoint: f.c.endpoint, apiKey: 'MOVED-SECRET' });
  await f.service.discover(source.id);

  const anonymous = f.service.create({ providerId: 'opencode', name: 'Free' });
  const elsewhere = f.service.create({ providerId: 'custom', name: 'Elsewhere', endpoint: 'http://127.0.0.1:9998/v1', apiKey: 'ELSEWHERE-SECRET' });
  const refusals = [
    [{}, 400, 'Choose a connection to move keys from.'],
    [{ fromConnectionId: f.c.id }, 400, 'Choose a different connection.'],
    [{ fromConnectionId: 'missing-id' }, 404, undefined],
    [{ fromConnectionId: anonymous.id }, 400, 'Keys can only move between connections of the same provider.'],
    [{ fromConnectionId: elsewhere.id }, 400, 'Keys can only move between connections with the same endpoint.'],
  ];
  for (const [payload, status, message] of refusals) {
    const response = await f.send(importPath, { method: 'POST', body: payload });
    assert.equal(response.status, status, `${JSON.stringify(payload)} ⇒ ${status}`);
    if (message) assert.equal(response.data.error.message, message);
    assert.equal(response.data.error.code, status === 404 ? 'NOT_FOUND' : 'INVALID_REQUEST');
  }
  assert.equal(f.service.connection(source.id).keys.length, 1, 'a refused import leaves both rings untouched');

  const moved = await f.send(importPath, { method: 'POST', body: { fromConnectionId: source.id } });
  assert.equal(moved.status, 200);
  assert.deepEqual(moved.data.keys.map(key => key.id), [f.c.id, source.id], 'the moved key goes to the END of the target ring');
  assert.equal(moved.data.keys[1].label, 'Source', 'a key with no label of its own keeps the name of its old connection');
  assert.equal(moved.data.keys[1].prefix, 'MOVED-…');
  assert.equal(moved.data.keys[1].state, 'ready');
  assert.equal((await f.service.credentials(f.c.id, null, source.id)).apiKey, 'MOVED-SECRET', 'the same encrypted row is read through its new ring');

  const shell = (await f.send('/api/router/state')).data.connections.find(connection => connection.id === source.id);
  assert.deepEqual(shell.keys, []);
  assert.equal(shell.credentialPresent, false);
  assert.equal(shell.authState, 'required');
  assert.equal(f.service.validTarget({ connectionId: source.id, modelId: model.id }), false);
  assert.equal((await f.send(`/api/router/connections/${source.id}`, { method: 'DELETE' })).status, 200, 'an emptied shell still deletes');
  assert.equal(f.store.credentials(source.id).apiKey, 'MOVED-SECRET', 'and the key it handed over stays with the target');
  f.scanForSecrets();
});

test('the key routes stay behind the local administration header', async t => {
  const f = await fixture(t);
  const anonymous = { 'Content-Type': 'application/json', Host: f.headers.Host };
  const paths = [
    ['/api/router/connections', 'GET'],
    [`/api/router/connections/${f.c.id}/keys`, 'POST'],
    [`/api/router/connections/${f.c.id}/keys/${f.c.id}`, 'DELETE'],
    [`/api/router/connections/${f.c.id}/keys/${f.c.id}/try`, 'POST'],
    [`/api/router/connections/${f.c.id}/keys/import`, 'POST'],
  ];
  for (const [path, method] of paths) {
    const response = await f.send(path, { method, header: anonymous, body: method === 'GET' || method === 'DELETE' ? undefined : {} });
    assert.equal(response.status, 403, `${method} ${path} needs the admin header`);
    assert.equal(response.data.error.code, 'FORBIDDEN');
  }
  assert.equal(f.service.connection(f.c.id).keys.length, 1, 'and nothing was written');
});

test('reveal endpoint returns the decrypted secret for inspection/copying', async t => {
  const f = await fixture(t);
  const res = await f.send(`/api/router/connections/${f.c.id}/keys/${f.c.id}/reveal`, { method: 'GET' });
  assert.equal(res.status, 200);
  assert.equal(res.data.id, f.c.id);
  assert.equal(res.data.key, 'FIRST-SECRET');
});

