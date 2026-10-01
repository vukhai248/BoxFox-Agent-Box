import test from 'node:test';
import assert from 'node:assert/strict';
import { largeRequestDeadline } from '../src/request-budget.mjs';
import { RouterEngine } from '../src/engine.mjs';

test('bounded large request settings and quick/large profiles', () => {
  assert.equal(largeRequestDeadline(undefined), 180000);
  for (const ms of [90000, 180000, 240000]) assert.equal(largeRequestDeadline(String(ms)), ms);
  for (const value of ['0', '-1', 'Infinity', 'NaN', '300000', '', '180001']) {
    assert.throws(() => largeRequestDeadline(value), /BOXFOX_ROUTER_LARGE_REQUEST_MS/);
  }
  const engine = new RouterEngine({ service: { store: {}, keyRing: {} }, largeDeadlineMs: 180000 });
  assert.equal(engine.requestDeadline({ max_tokens: 4096 }), 90000);
  assert.equal(engine.requestDeadline({ max_tokens: 7999 }), 90000);
  assert.equal(engine.requestDeadline({ max_tokens: 8000 }), 180000);
  assert.equal(engine.requestDeadline({ max_tokens: 16000 }), 180000);
  engine.largeDeadlineMs = 240000;
  assert.equal(engine.requestDeadline({ max_tokens: 16000 }), 240000);
  // Explicit constructor deadlines used by embedders/tests remain unchanged.
  const embedded = new RouterEngine({ service: { store: {}, keyRing: {} }, deadlineMs: 30 });
  assert.equal(embedded.requestDeadline({ max_tokens: 16000 }), 30);
});
