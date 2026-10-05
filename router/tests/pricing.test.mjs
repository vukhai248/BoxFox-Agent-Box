// Task 5 of the v1 API-provider plan: the pure price module. No store, no
// network, no stub — every case below calls a plain function.
//
// Why it exists: the router stores a cost only when the provider reports one.
// Measured on 2026-09-20 against the live store — OpenRouter 45/50 rows carried
// a `cost`, DeepSeek 0/61, Google 0/79 and the internal router 0/10 — while the
// DeepSeek row `input 11965 / cached 11776 / output 25, cost null` already held
// everything needed to price it. So an estimate has to be computed locally and
// labelled with the price that produced it.
//
// DeepSeek publishes no price through its API, so its table is shipped in
// src/pricing.mjs (`api-docs.deepseek.com/quick_start/pricing/`, read
// 2026-09-20): USD per 1M tokens, peak 01:00–04:00 and 06:00–10:00 UTC Monday–Friday,
// off-peak exactly half. Chinese public holidays are excluded from peak pricing
// and we do not ship that calendar, so an unreadable timestamp estimates high.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  DEEPSEEK_PRICE_AS_OF, MAX_PRICE_USD, OPENCODE_ZEN_PRICE_AS_OF, OPENCODE_ZEN_PRICE_DOCS, PER_MILLION, PRICE_SOURCES, PRICE_UNIT,
  costFromUsage, deepseekPeakAt, documentedDeepseekPrice, documentedZenPrice, normalizePrice, priceFromOpenRouter, roundUsd,
} from '../src/pricing.mjs';
import { normalizeUsage } from '../src/usage.mjs';

/** The one real DeepSeek row in the store on 2026-09-20, cache split included. */
const liveRow = { input: 11965, cached: 11776, output: 25 };
const closeTo = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-9, `${message} (got ${actual}, expected ${expected})`);
/** Costs are stored with six decimals, so a re-derived amount is compared at that granularity. */
const withinStoredDigit = (actual, expected, message) => assert.ok(Math.abs(actual - expected) < 1e-6, `${message} (got ${actual}, expected ${expected})`);

test('every produced price is USD per 1M tokens', () => {
  assert.equal(PRICE_UNIT, 'per_million_tokens');
  assert.equal(PER_MILLION, 1_000_000);
  assert.deepEqual([...PRICE_SOURCES], ['manual', 'ping', 'documented'], 'a provider-reported cost is a cost, not a storable price');
});

test('an OpenRouter pricing payload converts per-token strings to USD per 1M', () => {
  const price = priceFromOpenRouter({ prompt: '0.00000015', completion: '0.0000003', input_cache_read: '0.000000075' });
  assert.equal(price.currency, 'USD');
  assert.equal(price.unit, PRICE_UNIT);
  assert.equal(price.input, 0.15, "'0.00000015' per token is 0.15 per 1M");
  assert.equal(price.output, 0.3);
  assert.equal(price.cachedInput, 0.075);
  assert.equal(price.cacheWriteInput, null, 'a component the payload does not carry stays null, never 0');
  assert.equal('source' in price, false, 'the caller stamps the provenance');
});

test('an OpenRouter payload that cannot be read yields no price instead of a guess', () => {
  assert.equal(priceFromOpenRouter(null), null);
  assert.equal(priceFromOpenRouter({ completion: '0.0000003' }), null, 'without prompt there is no input price');
  assert.equal(priceFromOpenRouter({ prompt: 'not a number', completion: '0.0000003' }), null);
  assert.equal(priceFromOpenRouter({ prompt: '0.00000015' }), null);
  const partial = priceFromOpenRouter({ prompt: '0.00000015', completion: '0.0000003', input_cache_read: 'free', input_cache_write: '-1' });
  assert.equal(partial.cachedInput, null, 'an unreadable cache-read price is dropped, not treated as zero');
  assert.equal(partial.cacheWriteInput, null, 'a negative cache-write price is not a price');
});

test('a published zero is a price, not a missing one', () => {
  const free = priceFromOpenRouter({ prompt: '0', completion: '0', input_cache_read: '0' });
  assert.equal(free.input, 0);
  assert.equal(free.output, 0);
  assert.equal(free.cachedInput, 0);
  assert.deepEqual(costFromUsage({ usage: liveRow, price: { ...free, source: 'ping' } }), { cost: 0, basis: 'ping' });
});

test('normalizePrice demands a real number for input and output', () => {
  const base = { output: 1.2, source: 'manual' };
  assert.equal(normalizePrice({ ...base, input: 0.3 }).input, 0.3);
  assert.equal(normalizePrice({ ...base }), null, 'an absent input price is not a price');
  assert.equal(normalizePrice({ input: 0.3, source: 'manual' }), null, 'nor is an absent output price');
  assert.equal(normalizePrice({ ...base, input: '0.3' }), null, 'a string is not Number.isFinite — the store must hold a number');
  assert.equal(normalizePrice({ ...base, input: Number.NaN }), null);
  assert.equal(normalizePrice({ ...base, input: -0.01 }), null);
  assert.equal(normalizePrice({ ...base, output: Number.POSITIVE_INFINITY }), null);
  assert.equal(normalizePrice({ ...base, input: MAX_PRICE_USD }).input, MAX_PRICE_USD, 'the ceiling itself is allowed');
  assert.equal(normalizePrice({ ...base, input: MAX_PRICE_USD + 0.01 }), null);
  assert.equal(normalizePrice(null), null);
  assert.equal(normalizePrice('0.3'), null);
  assert.equal(normalizePrice({}), null);
});

test('normalizePrice returns the canonical shape together with its provenance', () => {
  const price = normalizePrice({ input: 0.3, cachedInput: 0.006, output: 1.2, source: 'manual', asOf: '2026-09-20', updatedAt: 1758380000000 });
  assert.deepEqual(price, {
    currency: 'USD', unit: PRICE_UNIT, input: 0.3, cachedInput: 0.006, cacheWriteInput: null, output: 1.2,
    source: 'manual', asOf: '2026-09-20', updatedAt: 1758380000000,
  });
  assert.equal(normalizePrice({ input: 0.3, output: 1.2, source: 'guessed' }), null, 'an unknown provenance is refused');
  assert.equal(normalizePrice({ input: 0.3, output: 1.2 }), null, 'a price with no source cannot be stored');
  assert.equal(normalizePrice({ input: 0.3, output: 1.2, source: 'manual', currency: 'EUR' }), null, 'we only price in USD');
  assert.equal(normalizePrice({ input: 0.3, output: 1.2, source: 'manual', unit: 'per_token' }), null, 'a per-token price is not this unit');
  assert.equal(normalizePrice({ input: 0.3, output: 1.2, source: 'manual', cachedInput: -1 }), null, 'a broken optional component rejects the whole price instead of vanishing');
  assert.equal(normalizePrice({ input: 0.3, output: 1.2, source: 'manual', cachedInput: null }).cachedInput, null, 'null means "not published", not "zero"');
  assert.equal(normalizePrice({ input: 0.3, output: 1.2, source: 'manual' }).asOf, null);
  assert.equal(normalizePrice({ input: 0.3, output: 1.2, source: 'manual', asOf: new Date('2026-09-20T10:00:00Z') }).asOf, '2026-09-20', 'a Date becomes the snapshot day');
  assert.deepEqual(normalizePrice(price), price, 'an already canonical price survives a second pass');
});

test('DeepSeek peak hours are 01:00–04:00 and 06:00–10:00 UTC on weekdays', () => {
  assert.equal(deepseekPeakAt('2026-09-23T02:00:00Z'), true, 'Wednesday 02:00 UTC is peak');
  assert.equal(deepseekPeakAt('2026-09-21T02:00:00Z'), true, 'Monday 02:00 UTC');
  assert.equal(deepseekPeakAt('2026-09-25T09:00:00Z'), true, 'Friday 09:00 UTC');
  assert.equal(deepseekPeakAt('2026-09-23T11:00:00Z'), false, 'Wednesday 11:00 UTC is off-peak');
  assert.equal(deepseekPeakAt(new Date('2026-09-23T02:00:00Z')), true, 'a Date works as well as an ISO string');
  assert.equal(deepseekPeakAt('2026-09-26T02:00:00Z'), false, 'Saturday is off-peak all day');
  assert.equal(deepseekPeakAt('2026-09-27T02:00:00Z'), false, 'Sunday is off-peak all day');
});

test('both peak windows are half-open', () => {
  const wednesday = '2026-09-23T';
  assert.equal(deepseekPeakAt(`${wednesday}00:59:59Z`), false);
  assert.equal(deepseekPeakAt(`${wednesday}01:00:00Z`), true);
  assert.equal(deepseekPeakAt(`${wednesday}03:59:59Z`), true);
  assert.equal(deepseekPeakAt(`${wednesday}04:00:00Z`), false, '04:00 is already off-peak');
  assert.equal(deepseekPeakAt(`${wednesday}05:59:59Z`), false);
  assert.equal(deepseekPeakAt(`${wednesday}06:00:00Z`), true);
  assert.equal(deepseekPeakAt(`${wednesday}09:59:59Z`), true);
  assert.equal(deepseekPeakAt(`${wednesday}10:00:00Z`), false, '10:00 is already off-peak');
});

test('a timestamp that cannot be read is estimated as peak, never as a discount', () => {
  assert.equal(deepseekPeakAt(new Date('not a date')), true);
  assert.equal(deepseekPeakAt(undefined), true);
});

test('the documented table answers documented ids, retired aliases and the provider patterns', () => {
  const at = '2026-09-23T11:00:00Z';
  for (const id of ['deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp', 'DEEPSEEK-V4-FLASH-VISION-EXP', '  deepseek-flash  ']) {
    assert.equal(documentedDeepseekPrice(id, at).input, 0.15, `${id} bills as Flash`);
  }
  for (const id of ['deepseek-v4-pro', 'deepseek-v4-pro-0813', 'tokenharbor/deepseek-pro-latest']) {
    assert.equal(documentedDeepseekPrice(id, at).input, 0.66, `${id} matches the pro pattern`);
  }
  for (const id of ['gpt-5.4', 'deepseek-v3', 'claude-sonnet-4-6', '', null, undefined]) {
    assert.equal(documentedDeepseekPrice(id, at), null, `${id} has no documented DeepSeek price`);
  }
  const price = documentedDeepseekPrice('deepseek-flash', at);
  assert.equal(price.currency, 'USD');
  assert.equal(price.unit, PRICE_UNIT);
  assert.equal(price.asOf, DEEPSEEK_PRICE_AS_OF);
  assert.equal('source' in price, false, 'the adapter that knows the provider stamps the provenance');
});

// The table is keyed by model id alone, so a caller that prices a hand-typed id
// on another gateway must scope it to the DeepSeek provider itself. This pins
// that contract: the module answers for any id it recognises, and "no price" —
// never a wrong one — for anything else. Note the pattern is the provider's own
// (`*flash*`, `*pro*`), so a non-DeepSeek id that happens to carry those words
// matches too; the caller owns the provider check.
test('an unrecognised id resolves to no price at all', () => {
  const at = '2026-09-23T11:00:00Z';
  assert.equal(documentedDeepseekPrice('gpt-5.4', at), null);
  assert.equal(documentedDeepseekPrice('claude-sonnet-4-6', at), null);
  assert.equal(documentedDeepseekPrice('deepseek', at), null, 'the provider name alone is not a model');
  assert.equal(documentedDeepseekPrice({ id: 'deepseek-flash' }, at), null, 'an object is not an id');
});

test('off-peak DeepSeek prices are exactly half of the peak prices', () => {
  const peak = documentedDeepseekPrice('deepseek-flash', '2026-09-21T02:00:00Z');
  const offPeak = documentedDeepseekPrice('deepseek-flash', '2026-09-21T11:00:00Z');
  assert.deepEqual([peak.input, peak.cachedInput, peak.output], [0.3, 0.006, 1.2]);
  assert.deepEqual([offPeak.input, offPeak.cachedInput, offPeak.output], [0.15, 0.003, 0.6]);
  for (const component of ['input', 'cachedInput', 'output']) {
    assert.equal(peak[component], 2 * offPeak[component], `the peak ${component} price is exactly twice the off-peak one`);
  }
  const proPeak = documentedDeepseekPrice('deepseek-v4-pro', '2026-09-21T02:00:00Z');
  const proOffPeak = documentedDeepseekPrice('deepseek-v4-pro', '2026-09-21T11:00:00Z');
  assert.deepEqual([proPeak.input, proPeak.cachedInput, proPeak.output], [1.32, 0.044, 3.96]);
  assert.deepEqual([proOffPeak.input, proOffPeak.cachedInput, proOffPeak.output], [0.66, 0.022, 1.98]);
});

test('the live DeepSeek row costs 0.000079 off-peak', () => {
  // 2026-09-20 is a Sunday, so DeepSeek bills the off-peak table.
  const price = { ...documentedDeepseekPrice('deepseek-flash', '2026-09-20T03:00:00Z'), source: 'documented' };
  const { cost, basis } = costFromUsage({ usage: liveRow, price });
  // miss 189 × 0.15 + hit 11776 × 0.003 + output 25 × 0.6 = 78.678 USD per 1M tokens
  assert.equal(cost, 0.000079);
  closeTo(cost, 0.000079, 'the cache split is what makes this exact');
  assert.equal(basis, 'documented');
});

test('the same row at peak is exactly twice the off-peak amount', () => {
  const offPeak = costFromUsage({ usage: liveRow, price: documentedDeepseekPrice('deepseek-flash', '2026-09-20T03:00:00Z') });
  const peak = costFromUsage({ usage: liveRow, price: documentedDeepseekPrice('deepseek-flash', '2026-09-21T03:00:00Z') });
  const exactOffPeak = (189 * 0.15 + 11776 * 0.003 + 25 * 0.6) / PER_MILLION;
  assert.equal(offPeak.cost, roundUsd(exactOffPeak));
  assert.equal(peak.cost, roundUsd(2 * exactOffPeak), 'peak is the doubled price, rounded once');
  assert.ok(peak.cost > offPeak.cost, 'the peak estimate is never presented as the lower one');
});

test('a cache hit is capped by the input it is counted from', () => {
  const price = { input: 0.15, cachedInput: 0.003, output: 0.6 };
  const { cost } = costFromUsage({ usage: { input: 10000, cached: 40000, output: 0 }, price });
  assert.equal(cost, roundUsd((10000 * 0.003) / PER_MILLION), 'hit = min(cached, input), so nothing is left as a cache miss');
  assert.equal(cost, 0.00003);
});

test('a missing cache-hit price charges the normal input price', () => {
  const price = { input: 0.3, output: 1.2 };
  const withCache = costFromUsage({ usage: { input: 1000, cached: 400, output: 0 }, price }).cost;
  const withoutCache = costFromUsage({ usage: { input: 1000, cached: 0, output: 0 }, price }).cost;
  assert.equal(withCache, withoutCache, 'an unpublished cache-hit price is not a discount we invented');
  assert.equal(withCache, roundUsd((1000 * 0.3) / PER_MILLION));
});

test('a null cache count makes every input token a cache miss', () => {
  const price = { input: 0.15, cachedInput: 0.003, output: 0.6 };
  const nullCache = costFromUsage({ usage: { input: 11965, cached: null, output: 25 }, price }).cost;
  const noCache = costFromUsage({ usage: { input: 11965, cached: 0, output: 25 }, price }).cost;
  assert.equal(nullCache, noCache);
  assert.equal(nullCache, roundUsd((11965 * 0.15 + 25 * 0.6) / PER_MILLION));
});

test('costFromUsage refuses to price nothing at all', () => {
  const price = { input: 0.15, cachedInput: 0.003, output: 0.6, source: 'documented' };
  assert.equal(costFromUsage({ usage: liveRow }), null, 'no price means no number');
  assert.equal(costFromUsage({ usage: {}, price }), null, '$0 would be a lie for a row that carries no token counts');
  assert.equal(costFromUsage({ price }), null);
  assert.equal(costFromUsage({}), null);
  assert.equal(costFromUsage(), null);
  assert.equal(costFromUsage({ usage: { input: 10 }, price: { output: 1 } }), null, 'a price without an input component cannot price input');
  assert.equal(costFromUsage({ usage: { input: 10 }, price: { input: 0.1, output: Number.NaN } }), null);
  assert.equal(costFromUsage({ usage: { input: 10 }, price: { input: -1, output: 1 } }), null);
});

test('costFromUsage reads the router normalized usage names as well as the short ones', () => {
  const price = { input: 0.15, cachedInput: 0.003, cacheWriteInput: 1.5, output: 0.6, source: 'documented' };
  // `input` is the FULL input count — the convention `normalizeUsage()` publishes.
  // The Anthropic-shaped payload below is the one that keeps a cache-write count:
  // input-only 189 + cache read 11776 + cache creation 900.
  const anthropicPayload = { input_tokens: 189, cache_read_input_tokens: 11776, cache_creation_input_tokens: 900, output_tokens: 25 };
  const normalized = normalizeUsage(anthropicPayload);
  assert.equal(normalized.prompt_tokens, 12865, 'the normalizer folds the writes into the input total, so they are already inside `input`');
  const truth = roundUsd((189 * 0.15 + 11776 * 0.003 + 900 * 1.5 + 25 * 0.6) / PER_MILLION);
  const priced = costFromUsage({ usage: normalized, price });
  assert.deepEqual(priced, { cost: truth, basis: 'documented' });
  assert.equal(costFromUsage({ usage: { input: 12865, cached: 11776, cacheWrite: 900, output: 25 }, price }).cost, truth,
    'a cache-write count is inside `input` and is subtracted from the miss bucket before it is charged — never paid for twice');
  assert.deepEqual(costFromUsage({ usage: { prompt_tokens: 12865, cached_tokens: 11776, cache_creation_input_tokens: 900, completion_tokens: 25 }, price }), priced);
  // The spelling a stored usage record actually carries (verified against the live
  // store on 2026-09-20: `inputTokens`, `cachedTokens`, `cacheCreationTokens`, `outputTokens`).
  const stored = costFromUsage({ usage: { inputTokens: 12865, cachedTokens: 11776, cacheCreationTokens: 900, outputTokens: 25, reasoningTokens: 396, totalTokens: 12890 }, price });
  assert.deepEqual(stored, priced, 'the row an engine hands over prices identically');
  // A write count that does not fit inside the input it claims to live in is clamped
  // to what is left after the hit, and charged the base rate when its own price is absent.
  const noWritePrice = costFromUsage({ usage: { input: 1000, cacheWrite: 2000, output: 0 }, price: { input: 0.5, output: 1 } });
  assert.equal(noWritePrice.cost, roundUsd((1000 * 0.5) / PER_MILLION), 'an unpublished cache-write price charges the base input rate, never a guess');
  assert.equal(costFromUsage({ usage: { input: -5, cached: -1, output: -1 }, price: { input: 1, output: 2 } }).cost, 0, 'negative counts are clamped to zero');
  withinStoredDigit(costFromUsage({ usage: { prompt_tokens: '11965', completion_tokens: '25' }, price: { input: 0.3, output: 1.2 } }).cost, (11965 * 0.3 + 25 * 1.2) / PER_MILLION, 'counts that travelled through JSON as strings still price');
});

test('the amount is never separated from the basis that produced it', () => {
  assert.equal(costFromUsage({ usage: liveRow, price: { ...documentedDeepseekPrice('deepseek-flash', '2026-09-20T03:00:00Z'), source: 'documented' } }).basis, 'documented');
  assert.equal(costFromUsage({ usage: liveRow, price: { ...priceFromOpenRouter({ prompt: '0.00000015', completion: '0.0000003' }), source: 'ping' } }).basis, 'ping');
  assert.equal(costFromUsage({ usage: liveRow, price: { input: 0.3, output: 1.2, source: 'manual' } }).basis, 'manual');
  assert.equal(costFromUsage({ usage: liveRow, price: { input: 0.3, output: 1.2 } }).basis, null, 'a caller that passed no provenance gets null, not an invented label');
  withinStoredDigit(costFromUsage({ usage: liveRow, price: { input: 0.3, output: 1.2, source: 'manual' } }).cost, (11965 * 0.3 + 25 * 1.2) / PER_MILLION, 'without a cache-hit price every input token is charged the input rate');
});

test('roundUsd stores six decimals and refuses what it cannot round', () => {
  assert.equal(roundUsd(0.000078678), 0.000079);
  assert.equal(roundUsd(1.23456789), 1.234568);
  assert.equal(roundUsd(0.0000004), 0, 'below half of the last stored digit there is nothing to show');
  assert.equal(roundUsd(0), 0);
  assert.equal(roundUsd(Number.NaN), null);
  assert.equal(roundUsd('0.5'), null);
  assert.equal(roundUsd(null), null);
  assert.equal(roundUsd(), null);
});

// Giá Zen đọc từ bảng USD / 1M của https://opencode.ai/docs/zen ngày 2026-10-04.
// Giá cache tách riêng; dấu `-` không được đổi thành 0.
test('Zen documented flat prices preserve the published components and snapshot', () => {
  assert.equal(OPENCODE_ZEN_PRICE_AS_OF, '2026-10-04');
  assert.equal(OPENCODE_ZEN_PRICE_DOCS, 'https://opencode.ai/docs/zen');
  const rows = [
    ['claude-sonnet-4-6', [3, 0.3, 3.75, 15]],
    ['qwen3.8-flash', [0.15, 0.016, 0.2, 0.47]],
    ['deepseek-v4-pro', [1.74, 0.145, null, 3.48]],
    ['gpt-5.4-mini', [0.75, 0.075, null, 4.5]],
    ['gemini-3.8-flash', [1.5, 0.15, null, 7.5]],
    ['jev-1.13', [0.042, null, null, 0]],
  ];
  for (const [id, [input, cachedInput, cacheWriteInput, output]] of rows) {
    const price = documentedZenPrice(id);
    assert.deepEqual(price, { currency: 'USD', unit: PRICE_UNIT, input, cachedInput, cacheWriteInput, output, asOf: OPENCODE_ZEN_PRICE_AS_OF }, id);
    assert.equal('source' in price, false, 'adapter owns provenance');
    assert.ok(normalizePrice({ ...price, source: 'documented' }), 'table meets the price invariants');
  }
  assert.deepEqual(documentedZenPrice('  QWEN3.8-FLASH  '), documentedZenPrice('qwen3.8-flash'));
  const changed = documentedZenPrice('qwen3.8-flash');
  changed.input = 999;
  assert.equal(documentedZenPrice('qwen3.8-flash').input, 0.15, 'a returned snapshot cannot mutate the table');
});

test('a documented free Zen model has a real zero cost but absent cache prices stay null', () => {
  for (const id of ['big-pickle', 'space-bunny-free', 'muse-spark-1.3-contributor-free', 'jev-1.13-free']) {
    const price = { ...documentedZenPrice(id), source: 'documented' };
    assert.equal(price.input, 0);
    assert.equal(price.output, 0);
    assert.equal(price.cacheWriteInput, null);
    assert.equal(price.cachedInput, id === 'jev-1.13-free' ? null : 0);
    assert.deepEqual(costFromUsage({ usage: liveRow, price }), { cost: 0, basis: 'documented' });
  }
});

test('Zen unknown ids and context-tiered models are not guessed', () => {
  // Không lấy bậc thấp/cao tuỳ tiện khi đường tính giá chỉ nhận id model.
  for (const id of [
    'claude-sonnet-4-5', 'gemini-3.1-pro', 'grok-4.7', 'grok-4.6', 'grok-4.5',
    'gpt-6-astra', 'gpt-6-sol', 'gpt-6.1-sol', 'gpt-6-luna', 'gpt-5.6-sol',
    'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.4',
    'unknown-free', 'deepseek-v4-flash-free', 'muse-spark-1.2-contributor-free',
    'gateway/space-bunny-free', 'gpt-5.4-mini-latest', '__proto__', 'constructor',
    '', null, undefined, { id: 'space-bunny-free' },
  ]) assert.equal(documentedZenPrice(id), null, `${String(id)} has no documented flat Zen price`);
});
