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

test('a large transcript takes the large deadline even when the output ceiling is small', () => {
  const engine = new RouterEngine({ service: { store: {}, keyRing: {} }, largeDeadlineMs: 240000 });
  // The threshold counts the SERIALIZED length, so size the filler from the JSON overhead.
  const message = content => [{ role: 'user', content }];
  const messageOverhead = JSON.stringify(message('')).length;
  const tools = name => [{ type: 'function', function: { name } }];
  const toolOverhead = JSON.stringify(tools('')).length;
  assert.equal(engine.requestDeadline({ max_tokens: 4096, messages: message('x'.repeat(200000 - messageOverhead - 1)) }), 90000);
  assert.equal(engine.requestDeadline({ max_tokens: 4096, messages: message('x'.repeat(200000 - messageOverhead)) }), 240000);
  // Tool schemas count too: they ride the same body and slow the same first token.
  assert.equal(engine.requestDeadline({ max_tokens: 4096, messages: undefined,
    tools: tools('t'.repeat(200000 - toolOverhead - 1)) }), 90000);
  assert.equal(engine.requestDeadline({ max_tokens: 4096, messages: undefined,
    tools: tools('t'.repeat(200000 - toolOverhead)) }), 240000);
  // A small request keeps the quick profile, and no large profile means no large deadline.
  assert.equal(engine.requestDeadline({ max_tokens: 4096, messages: message('hello') }), 90000);
  assert.equal(engine.requestDeadline({ max_tokens: 4096 }), 90000);
  const embedded = new RouterEngine({ service: { store: {}, keyRing: {} }, deadlineMs: 30 });
  assert.equal(embedded.requestDeadline({ max_tokens: 4096, messages: message('x'.repeat(400000)) }), 30);
});
