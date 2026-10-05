// W12.MODEL.METADATA — T2/T4: vòng đời refresh của một connection.
//
// Fixture không mạng: một adapter kịch bản trả đúng những dòng mà service nhìn
// thấy, nên mọi ca "provider rút model / đổi ID / dò hỏng / chồng lượt / restart"
// chạy được mà không gọi provider nào. Ca OpenCode dùng adapter thật + payload giả.
//
// Hợp đồng được ghim ở đây (docs/plan/Work-Graph-fix.md §38.5):
//   - model bị rút hoặc đổi ID: hàng cũ rời inventory, KHÔNG tự remap tên tương tự;
//   - dò hỏng: giữ last-good, gắn `stale`, ghi `error`, `discoveryState` degraded;
//     connection chưa có hàng nào thì seed fallback của adapter (tắt + stale);
//   - chồng lượt: một connection chỉ có MỘT lần dò đang bay (single-flight); revision
//     đổi giữa chừng thì kết quả cũ bị từ chối (STALE_RESULT) và không ghi đè;
//   - restart: nhãn nguồn/`stale` còn nguyên, hàng không tự nhận lại là dữ liệu live.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createProviders } from '../src/providers/index.mjs';
import { RouterError } from '../src/errors.mjs';
import { RouterStore } from '../src/store.mjs';
import { ProviderService } from '../src/service.mjs';
import { ModelSyncScheduler } from '../src/model-sync.mjs';

const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });

/** Một hàng đã qua adapter, mang đủ trường hợp đồng của `modelThinking`. */
const live = (id, extra = {}) => ({
  id,
  name: id,
  source: 'live',
  stale: false,
  enabled: true,
  contextWindow: null,
  contextWindowSource: null,
  thinkingType: 'none',
  thinkingLevels: [],
  defaultThinking: null,
  capabilities: { streaming: 'reported', tools: 'unknown', vision: 'unknown', reasoning: 'unknown' },
  ...extra,
});

/**
 * Adapter kịch bản: `source` là nguồn sống của test — sửa `source.models`/`source.fail`
 * giữa hai lần dò là đổi đúng thứ provider "trả về" ở lần sau. `source.wait` giữ lượt
 * dò đang bay để test chồng lượt/revision.
 */
function scriptedAdapter(source) {
  const adapter = {
    calls: [],
    fallbackModels: source.fallbackModels || [],
    thinkingMetadata: source.thinkingMetadata || (() => ({})),
    async discover(args) {
      adapter.calls.push(args);
      if (source.wait) await source.wait;
      if (source.fail) throw source.fail;
      return { models: (source.models || []).map(model => ({ ...model })) };
    },
  };
  return adapter;
}

/** Store + service + connection `opencode` (adapter kịch bản) cho một test. */
function fixture(t, source = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-w12-refresh-'));
  const store = new RouterStore({ dataDir: dir });
  const adapter = scriptedAdapter(source);
  const service = new ProviderService({ store, providers: { opencode: adapter } });
  const connection = service.create({ providerId: 'opencode', name: 'Scripted Free', endpoint: 'https://scripted.invalid', apiKey: 'test-only-key' });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  return { store, service, adapter, source, id: connection.id };
}

const ids = connection => connection.models.map(model => model.id);
const row = (connection, id) => connection.models.find(model => model.id === id);

test('T2: a model the provider retires leaves the inventory on the next refresh', async t => {
  const { service, source, id } = fixture(t, {
    models: [live('alpha-free', { contextWindow: 64000, contextWindowSource: 'reported' }), live('beta-free')],
  });
  await service.discover(id);
  assert.deepEqual(ids(service.connection(id)), ['alpha-free', 'beta-free']);

  source.models = [live('beta-free')];
  await service.discover(id);
  const connection = service.connection(id);
  assert.deepEqual(ids(connection), ['beta-free'], 'the retired model is gone, the rest of the inventory stays');
  assert.equal(row(connection, 'alpha-free'), undefined);
  assert.equal(row(connection, 'beta-free').stale, false);
  assert.equal(connection.discoveryState, 'ready');
  assert.equal(connection.error, null);
});

test('T2: an id change is a new row — the old id and its metadata are not carried over', async t => {
  const { service, source, id } = fixture(t, {
    models: [live('old-name-free', { contextWindow: 128000, contextWindowSource: 'reported', thinkingType: 'effort', thinkingLevels: ['low', 'high'], defaultThinking: 'low' })],
  });
  await service.discover(id);

  source.models = [live('new-name-free')];
  await service.discover(id);
  const connection = service.connection(id);
  assert.deepEqual(ids(connection), ['new-name-free'], 'no similar-name remap: the old row is not renamed');
  const fresh = row(connection, 'new-name-free');
  assert.equal(fresh.contextWindow, null, 'the new id starts from what the payload said — nothing inherited');
  assert.deepEqual(fresh.thinkingLevels, []);
  assert.equal(fresh.thinkingType, 'none');
});

test('T2: a failed refresh keeps last-good rows, marks them stale, and records the error', async t => {
  const { service, source, id } = fixture(t, {
    models: [
      live('keep-a-free', { contextWindow: 64000, contextWindowSource: 'reported', thinkingType: 'effort', thinkingLevels: ['low', 'high'], defaultThinking: 'low' }),
      live('keep-b-free'),
    ],
  });
  await service.discover(id);
  // Người dùng tắt một model và gõ tay một model: cả hai quyết định phải sống sót
  // qua một lần dò hỏng.
  service.patch(id, { enabledModelIds: ['keep-a-free'] });
  service.patch(id, { customModel: { id: 'hand-typed-free', capabilities: {} } });
  const before = service.connection(id);
  const beforeSyncAt = before.lastModelSyncAt;
  assert.deepEqual(ids(before), ['keep-a-free', 'keep-b-free', 'hand-typed-free']);

  source.fail = new Error('offline');
  await assert.rejects(() => service.discover(id), /offline/);

  const after = service.connection(id);
  assert.deepEqual(ids(after), ['keep-a-free', 'keep-b-free', 'hand-typed-free'], 'the inventory is kept, not replaced');
  assert.equal(after.discoveryState, 'degraded');
  assert.match(after.error, /unavailable|offline/i);
  assert.equal(after.lastModelSyncAt, beforeSyncAt, 'a failed attempt is not a successful sync');
  for (const modelId of ['keep-a-free', 'keep-b-free']) {
    const kept = row(after, modelId);
    assert.equal(kept.stale, true, `${modelId} is labelled stale`);
    assert.equal(kept.enabled, modelId === 'keep-a-free', 'the user’s enabled/disabled choice survives');
  }
  const typed = row(after, 'hand-typed-free');
  assert.equal(typed.source, 'custom');
  assert.equal(Boolean(typed.stale), false, 'a hand-typed row never came from a ping, so it cannot be stale');
  assert.equal(row(after, 'keep-a-free').contextWindow, 64000, 'the kept row keeps its metadata');
  assert.deepEqual(row(after, 'keep-a-free').thinkingLevels, ['low', 'high']);
});

test('T2: an auth failure expires the account and still keeps last-good rows', async t => {
  const { service, source, id } = fixture(t, { models: [live('keep-free')] });
  await service.discover(id);

  source.fail = new RouterError('AUTH', 'Provider authentication failed. Reconnect or replace the credential.', 401, false);
  await assert.rejects(() => service.discover(id), error => error.code === 'AUTH');

  const connection = service.connection(id);
  assert.equal(connection.authState, 'expired');
  assert.equal(connection.discoveryState, 'degraded');
  assert.deepEqual(ids(connection), ['keep-free']);
  assert.equal(row(connection, 'keep-free').stale, true);
});

test('T2: a failed first refresh seeds the adapter fallback disabled, static and stale', async t => {
  const { store, service, id } = fixture(t, {
    fallbackModels: [live('curated-one-free'), live('curated-two-free')],
    fail: new Error('offline'),
  });
  // Connection chưa có hàng nào để giữ: `create()` seed sẵn bảng curated của adapter,
  // nên xoá inventory để chạm đúng nhánh "chưa có gì để giữ" của lần dò hỏng.
  store.put('connection', { ...store.get('connection', id), models: [] });
  await assert.rejects(() => service.discover(id), /offline/);

  const connection = service.connection(id);
  assert.deepEqual(ids(connection), ['curated-one-free', 'curated-two-free']);
  assert.equal(connection.discoveryState, 'degraded');
  assert.match(connection.error, /unavailable|offline/i);
  for (const model of connection.models) {
    assert.equal(model.source, 'static');
    assert.equal(model.stale, true);
    assert.equal(model.enabled, false, 'an unreachable provider must not advertise an enabled model');
  }
  assert.equal(service.validTarget({ connectionId: id, modelId: 'curated-one-free' }), false, 'and the router refuses to route to it');
});

test('T2: the next successful refresh clears the failure and refreshes the rows', async t => {
  const { service, source, id } = fixture(t, { models: [live('keep-free')] });
  await service.discover(id);
  source.fail = new Error('offline');
  await assert.rejects(() => service.discover(id));
  assert.equal(service.connection(id).discoveryState, 'degraded');

  source.fail = null;
  source.models = [live('keep-free'), live('fresh-free')];
  await service.discover(id);
  const connection = service.connection(id);
  assert.equal(connection.discoveryState, 'ready');
  assert.equal(connection.error, null);
  assert.deepEqual(ids(connection), ['keep-free', 'fresh-free']);
  assert.equal(row(connection, 'keep-free').stale, false, 'a healthy refresh clears the stale label');
});

test('T2: refreshing the same payload twice neither duplicates nor reorders rows', async t => {
  const { service, source, id } = fixture(t, { models: [live('one-free'), live('two-free'), live('three-free')] });
  const first = await service.discover(id);
  const second = await service.discover(id);
  assert.deepEqual(ids(service.connection(id)), ['one-free', 'two-free', 'three-free']);
  assert.deepEqual(ids(first), ids(second));
  assert.equal(service.connection(id).models.length, 3);
});

test('T2: concurrent refreshes share one discovery (single-flight)', async t => {
  let release;
  const { service, adapter, source, id } = fixture(t, { models: [live('one-free')] });
  source.wait = new Promise(resolve => { release = resolve; });

  const first = service.discover(id);
  const second = service.discover(id);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(adapter.calls.length, 1, 'a second caller joins the flight instead of pinging again');
  release();
  const [a, b] = await Promise.all([first, second]);
  assert.deepEqual(ids(a), ['one-free']);
  assert.deepEqual(ids(b), ['one-free']);
  assert.equal(adapter.calls.length, 1);

  await service.discover(id);
  assert.equal(adapter.calls.length, 2, 'after the flight lands, the next refresh really pings');
});

test('T2: an edit during a flight wins — the stale result is refused and nothing is overwritten', async t => {
  let release;
  const { service, source, id } = fixture(t, { models: [live('old-free')] });
  source.wait = new Promise(resolve => { release = resolve; });

  const flight = service.discover(id).then(value => ({ ok: true, value }), error => ({ ok: false, error }));
  await new Promise(resolve => setImmediate(resolve));
  // Đổi credential là bump revision + reset inventory: kết quả đang bay thuộc về
  // revision cũ và không được phép ghi đè lên nó.
  service.patch(id, { apiKey: 'rotated-key' });
  const revision = service.connection(id).revision;
  release();

  const result = await flight;
  assert.equal(result.ok, false);
  assert.equal(result.error.code, 'STALE_RESULT');
  assert.equal(result.error.status, 409);
  const connection = service.connection(id);
  assert.equal(connection.revision, revision, 'the newer revision stands');
  assert.equal(ids(connection).includes('old-free'), false, 'the old flight did not write its inventory');
});

test('T2/T4: a vanished model disables the alias that pointed at it and clears the default route', async t => {
  const { service, source, id } = fixture(t, { models: [live('target-free'), live('other-free')] });
  await service.discover(id);
  const alias = service.alias({ name: 'daily', strategy: 'fallback', targets: [{ connectionId: id, modelId: 'target-free' }] });
  service.setDefault({ connectionId: id, modelId: 'target-free' });

  source.models = [live('other-free')];
  await service.discover(id);

  const stored = service.store.get('alias', alias.id);
  assert.equal(stored.enabled, false, 'an alias must not stay enabled over a model that no longer exists');
  assert.match(stored.error, /no longer available/i);
  assert.deepEqual(service.store.getDefault(), { connectionId: null, modelId: null, aliasId: null }, 'the default route is cleared instead of pointing at a ghost');
});

test('T4: rows, stale labels and provenance survive a restart', async t => {
  const { store, service, source, id } = fixture(t, {
    models: [live('keep-free', { thinkingType: 'effort', thinkingLevels: ['low', 'high'], defaultThinking: 'low' })],
  });
  await service.discover(id);
  service.patch(id, { customModel: { id: 'hand-typed-free', capabilities: {} } });
  source.fail = new Error('offline');
  await assert.rejects(() => service.discover(id));
  const before = JSON.stringify(service.connection(id).models);

  // Restart: cùng store, service mới — `sanitizeAllConnections` chạy lúc dựng và
  // không được phép "sửa" một hàng stale thành hàng live.
  const restarted = new ProviderService({ store, providers: { opencode: scriptedAdapter(source) } });
  const connection = restarted.connection(id);
  assert.equal(connection.discoveryState, 'degraded');
  assert.equal(row(connection, 'keep-free').stale, true);
  assert.deepEqual(row(connection, 'keep-free').thinkingLevels, ['low', 'high']);
  assert.equal(row(connection, 'hand-typed-free').source, 'custom');
  assert.equal(JSON.stringify(connection.models), before, 'normalization is idempotent across a restart');
});

test('T2/OpenCode: duplicate ids in one payload collapse into one row', async t => {
  const payload = { data: [{ id: 'dup-free' }, { id: 'dup-free' }, { id: 'other-free' }, { id: 'dup-free' }] };
  const adapter = createProviders({ fetchImpl: async () => json(payload) }).opencode;
  const { models } = await adapter.discover({ connection: { id: 'opencode', providerId: 'opencode', endpoint: 'https://opencode.invalid' }, credentials: {} });
  assert.deepEqual(models.map(model => model.id), ['dup-free', 'other-free'], 'one row per id, first occurrence wins');

  // Qua service: hai lần refresh cùng payload vẫn chỉ có hai hàng.
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-w12-opencode-dedupe-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const service = new ProviderService({ store, providers: createProviders({ fetchImpl: async () => json(payload) }) });
  const connection = service.create({ providerId: 'opencode', name: 'OpenCode Free', endpoint: 'https://opencode.invalid', apiKey: 'test-only-key' });
  await service.discover(connection.id);
  await service.discover(connection.id);
  assert.deepEqual(ids(service.connection(connection.id)), ['dup-free', 'other-free']);
});

test('T2/OpenCode: a failed refresh keeps last-good instead of replacing it with the curated list', async t => {
  const livePayload = {
    data: [
      { id: 'space-bunny-free', object: 'model' },
      { id: 'muse-spark-1.3-contributor-free', object: 'model' },
      { id: 'another-free', object: 'model' },
    ],
  };
  let mode = 'ok';
  const fetchImpl = async () => {
    if (mode === 'throw') throw new Error('offline');
    if (mode === '429') return json({ error: { message: 'rate limited' } }, 429);
    return json(livePayload);
  };
  const dir = mkdtempSync(join(tmpdir(), 'boxfox-w12-opencode-lastgood-'));
  const store = new RouterStore({ dataDir: dir });
  t.after(() => { store.close(); rmSync(dir, { recursive: true, force: true }); });
  const service = new ProviderService({ store, providers: createProviders({ fetchImpl }) });
  const connection = service.create({ providerId: 'opencode', name: 'OpenCode Free', endpoint: 'https://opencode.invalid', apiKey: 'test-only-key' });
  await service.discover(connection.id);
  assert.deepEqual(ids(service.connection(connection.id)), ['space-bunny-free', 'muse-spark-1.3-contributor-free', 'another-free']);

  for (const [next, expected] of [['throw', /unavailable|offline/i], ['429', /rate limit|quota/i]]) {
    mode = next;
    await assert.rejects(
      () => service.discover(connection.id),
      error => (next === '429' ? error.code === 'RATE_LIMIT' : error.message === 'offline'),
    );
    const current = service.connection(connection.id);
    assert.deepEqual(ids(current), ['space-bunny-free', 'muse-spark-1.3-contributor-free', 'another-free'], `${next}: last-good inventory is kept`);
    assert.equal(current.discoveryState, 'degraded', `${next}: the connection says it is degraded`);
    assert.match(current.error, expected);
    for (const model of current.models) assert.equal(model.stale, true, `${next}: ${model.id} is stale`);
    assert.equal(row(current, 'space-bunny-free').thinkingSource, 'probe', 'the verified registry label is still there');
  }
});

test('T2: the sync scheduler skips ineligible connections and never overlaps runs', async t => {
  const { service, adapter, source, id } = fixture(t, { models: [live('one-free')] });
  const scheduler = new ModelSyncScheduler({ service, staggerMs: 0 });

  // Hai lượt chồng nhau: `run()` lần thứ hai thoát ngay, nên connection chỉ được ping một lần.
  let release;
  source.wait = new Promise(resolve => { release = resolve; });
  const first = scheduler.run();
  await new Promise(resolve => setImmediate(resolve));
  await scheduler.run();
  assert.equal(adapter.calls.length, 1, 'a run already in flight is not started again');
  release();
  await first;

  // Connection không đủ điều kiện thì không được ping: tắt, thiếu credential, hoặc tắt autoSync.
  service.patch(id, { enabled: false });
  await scheduler.run();
  assert.equal(adapter.calls.length, 1, 'a disabled connection is skipped');
  service.patch(id, { enabled: true });
  service.patch(id, { autoSync: false });
  await scheduler.run();
  assert.equal(adapter.calls.length, 1, 'autoSync=false is respected');

  // Lượt dò hỏng không làm scheduler ném: trạng thái bền ghi lại thất bại.
  service.patch(id, { autoSync: true });
  source.fail = new Error('offline');
  await scheduler.run();
  assert.equal(adapter.calls.length, 2);
  assert.equal(service.connection(id).discoveryState, 'degraded');
});

test('T2: a level the provider withdraws leaves the row on the next refresh, and a new one appears', async t => {
  const { service, source, id } = fixture(t, {
    models: [live('alpha-free', { thinkingType: 'effort', thinkingLevels: ['low', 'medium', 'high'], defaultThinking: 'medium' })],
  });
  await service.discover(id);
  assert.deepEqual(row(service.connection(id), 'alpha-free').thinkingLevels, ['low', 'medium', 'high']);

  // Payload sau rút `medium` và thêm `max`: metadata mới thắng, không giữ mức cũ đã bị bỏ.
  source.models = [live('alpha-free', { thinkingType: 'effort', thinkingLevels: ['low', 'high', 'max'], defaultThinking: 'max' })];
  await service.discover(id);
  const updated = row(service.connection(id), 'alpha-free');
  assert.deepEqual(updated.thinkingLevels, ['low', 'high', 'max'], 'the withdrawn level is gone, the new one is offered');
  assert.equal(updated.defaultThinking, 'max', 'and the default follows the payload');

  // Lần dò hỏng sau đó giữ nguyên mức vừa công bố (last-good), không quay về mức cũ.
  source.fail = new Error('offline');
  await assert.rejects(() => service.discover(id));
  assert.deepEqual(row(service.connection(id), 'alpha-free').thinkingLevels, ['low', 'high', 'max']);
});

test('T2: a successful refresh schedules the next attempt hours out; a failure does not pull it in', async t => {
  const { service, source, id } = fixture(t, { models: [live('one-free')] });
  const before = Date.now();
  await service.discover(id);
  const scheduled = Date.parse(service.connection(id).nextModelSyncAt);
  assert.ok(scheduled - before > 5 * 60 * 60 * 1000, 'the next sync is hours away — discovery is not run per render');
  assert.ok(scheduled - before < 7 * 60 * 60 * 1000);

  // Dò hỏng không dời lịch: lần thử kế tiếp vẫn theo nhịp cũ, không thành vòng lặp nóng.
  source.fail = new Error('offline');
  await assert.rejects(() => service.discover(id));
  assert.equal(service.connection(id).nextModelSyncAt, new Date(scheduled).toISOString(), 'a failure keeps the schedule, it does not retry hot');
});
