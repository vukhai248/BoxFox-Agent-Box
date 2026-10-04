// Cost accounting for usage rows: four price tiers, and the provenance of every
// number that comes out of them.
//
// The router never invents a cost. When a usage event arrives the price is
// resolved in this order and the basis travels with the number, so the UI can
// label an estimate instead of showing it as a fact:
//
//   1. `reported`   — the provider stated the cost in its own usage payload
//                     (`reportedCost()` in usage.mjs). Never overwritten.
//   2. `ping`       — the price the provider published in its `/models` payload
//                     (OpenRouter-shaped `pricing`, USD per token, as strings).
//   3. `documented` — the table this module ships for a provider that publishes
//                     no price through its API (DeepSeek and OpenCode Zen).
//   4. `manual`     — the price the user set for one model on one connection.
//
// Everything here is a pure function: no I/O, no hidden clock (`at` is always a
// parameter), so the unit tests need no stubs. A cost is computed once, when the
// usage event is recorded, and stored with its basis — never recomputed on read,
// because prices move and a stored row must keep the basis it was written with.
//
// Units. Every price in this module is USD per 1,000,000 tokens (`PRICE_UNIT`,
// `PER_MILLION`), whatever unit the source used; `priceFromOpenRouter()` is the
// single place that converts a per-token payload. An absent optional component
// is `null` — never 0, which would be a price nobody published.
//
// DeepSeek table (USD / 1M tokens, `asOf: '2026-09-20'`)
//   https://api-docs.deepseek.com/quick_start/pricing/
//   Peak hours are 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday; every other
//   hour of the week is off-peak, and off-peak is exactly half of peak.
//   Caveat we cannot fix here: DeepSeek excludes Chinese public holidays from
//   peak pricing and we do not ship that calendar, so those days are estimated
//   up to 2× too high. The error deliberately goes in the direction that never
//   under-reports — an unreadable timestamp is treated as peak too.
//
// Cache accounting follows every OpenAI-style provider: cached tokens are a
// subset of the input tokens (`hit = min(cached, input)`), the rest of the input
// is a cache miss, and a missing cache-hit price falls back to the normal input
// price rather than guessing a discount.
export const PRICE_UNIT = 'per_million_tokens';
export const PER_MILLION = 1_000_000;
/** Ceiling for any single USD/1M component: above this the value is not a price. */
export const MAX_PRICE_USD = 1000;
/** The provenances a stored price may carry (`reported` is a cost, not a price). */
export const PRICE_SOURCES = Object.freeze(['manual', 'ping', 'documented']);

/** The day the shipped DeepSeek table was read off the pricing page. */
export const DEEPSEEK_PRICE_AS_OF = '2026-09-20';
export const DEEPSEEK_PRICE_DOCS = 'https://api-docs.deepseek.com/quick_start/pricing/';

// `cachedInput`/`cacheWriteInput` are `null` for DeepSeek: the page publishes no
// separate cache-write price, and a cache miss is the documented `input` price.
const DEEPSEEK_ROWS = Object.freeze({
  flash: Object.freeze({
    peak: Object.freeze({ input: 0.3, cachedInput: 0.006, cacheWriteInput: null, output: 1.2 }),
    offPeak: Object.freeze({ input: 0.15, cachedInput: 0.003, cacheWriteInput: null, output: 0.6 }),
  }),
  pro: Object.freeze({
    peak: Object.freeze({ input: 1.32, cachedInput: 0.044, cacheWriteInput: null, output: 3.96 }),
    offPeak: Object.freeze({ input: 0.66, cachedInput: 0.022, cacheWriteInput: null, output: 1.98 }),
  }),
});

// Explicit ids first: the retired aliases still bill as Flash. Anything else is
// matched by the provider's own naming pattern, and an unknown id resolves to no
// price at all — an empty cost is better than a wrong one.
const DEEPSEEK_EXACT_ROWS = Object.freeze({
  'deepseek-flash': 'flash',
  'deepseek-v4-flash': 'flash',
  'deepseek-v4-flash-vision-exp': 'flash',
  'deepseek-v4-pro': 'pro',
});

/** Ngày đọc bảng giá OpenCode Zen: USD / 1M tokens, không có giờ cao điểm. */
export const OPENCODE_ZEN_PRICE_AS_OF = '2026-10-04';
export const OPENCODE_ZEN_PRICE_DOCS = 'https://opencode.ai/docs/zen';

// Giới hạn đã biết: KHÔNG đoán giá cho model có bậc theo kích thước context.
// ≤/> 200K: Claude Sonnet 4.5, Gemini 3.1 Pro, Grok 4.7, Grok 4.6, Grok 4.5.
// ≤/> 272K: GPT 6 Astra, GPT 6 Sol, GPT 6.1 Sol, GPT 6 Luna, GPT 5.6 Sol,
// GPT 5.6 Terra, GPT 5.6 Luna, GPT 5.5, GPT 5.4. Các id này trả null.
// `Free` là giá 0 có nguồn; dấu `-` là null, không phải miễn phí.
const ZEN_ROWS = Object.freeze({
  'big-pickle': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'claude-fable-5': Object.freeze({ input: 10, cachedInput: 1, cacheWriteInput: 12.5, output: 50 }),
  'claude-fable-5-1': Object.freeze({ input: 10, cachedInput: 0.25, cacheWriteInput: 12.5, output: 50 }),
  'claude-haiku-4-5': Object.freeze({ input: 1, cachedInput: 0.1, cacheWriteInput: 1.25, output: 5 }),
  'claude-opus-4-5': Object.freeze({ input: 5, cachedInput: 0.5, cacheWriteInput: 6.25, output: 25 }),
  'claude-opus-4-6': Object.freeze({ input: 5, cachedInput: 0.5, cacheWriteInput: 6.25, output: 25 }),
  'claude-opus-4-7': Object.freeze({ input: 5, cachedInput: 0.5, cacheWriteInput: 6.25, output: 25 }),
  'claude-opus-4-8': Object.freeze({ input: 5, cachedInput: 0.5, cacheWriteInput: 6.25, output: 25 }),
  'claude-opus-5': Object.freeze({ input: 5, cachedInput: 0.5, cacheWriteInput: 6.25, output: 25 }),
  'claude-opus-5-5': Object.freeze({ input: 4, cachedInput: 0.2, cacheWriteInput: 5, output: 20 }),
  'claude-sonnet-4-6': Object.freeze({ input: 3, cachedInput: 0.3, cacheWriteInput: 3.75, output: 15 }),
  'claude-sonnet-5': Object.freeze({ input: 2, cachedInput: 0.2, cacheWriteInput: 2.5, output: 10 }),
  'deepseek-v4-flash': Object.freeze({ input: 0.14, cachedInput: 0.028, cacheWriteInput: null, output: 0.28 }),
  'deepseek-v4-flash-vision-exp': Object.freeze({ input: 0.14, cachedInput: 0.028, cacheWriteInput: null, output: 0.28 }),
  'deepseek-v4-pro': Object.freeze({ input: 1.74, cachedInput: 0.145, cacheWriteInput: null, output: 3.48 }),
  'deepseek-v4.1-flash': Object.freeze({ input: 0.3, cachedInput: 0.006, cacheWriteInput: null, output: 1.2 }),
  'fledge-alpha-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'gemini-3-flash': Object.freeze({ input: 0.5, cachedInput: 0.05, cacheWriteInput: null, output: 3 }),
  'gemini-3.5-flash': Object.freeze({ input: 1.5, cachedInput: 0.15, cacheWriteInput: null, output: 9 }),
  'gemini-3.5-flash-lite': Object.freeze({ input: 0.3, cachedInput: 0.03, cacheWriteInput: null, output: 2.5 }),
  'gemini-3.6-flash': Object.freeze({ input: 1.5, cachedInput: 0.15, cacheWriteInput: null, output: 7.5 }),
  'gemini-3.7-flash': Object.freeze({ input: 1.5, cachedInput: 0.15, cacheWriteInput: null, output: 7.5 }),
  'gemini-3.8-flash': Object.freeze({ input: 1.5, cachedInput: 0.15, cacheWriteInput: null, output: 7.5 }),
  'glm-5': Object.freeze({ input: 1, cachedInput: 0.2, cacheWriteInput: null, output: 3.2 }),
  'glm-5.1': Object.freeze({ input: 1.4, cachedInput: 0.26, cacheWriteInput: null, output: 4.4 }),
  'glm-5.2': Object.freeze({ input: 1.4, cachedInput: 0.26, cacheWriteInput: null, output: 4.4 }),
  'glm-5.3': Object.freeze({ input: 1.4, cachedInput: 0.26, cacheWriteInput: null, output: 4.4 }),
  'glm-5.3-flash': Object.freeze({ input: 0.15, cachedInput: 0.03, cacheWriteInput: null, output: 0.5 }),
  'gpt-5': Object.freeze({ input: 1.07, cachedInput: 0.107, cacheWriteInput: null, output: 8.5 }),
  'gpt-5-codex': Object.freeze({ input: 1.07, cachedInput: 0.107, cacheWriteInput: null, output: 8.5 }),
  'gpt-5-nano': Object.freeze({ input: 0.05, cachedInput: 0.005, cacheWriteInput: null, output: 0.4 }),
  'gpt-5.1': Object.freeze({ input: 1.07, cachedInput: 0.107, cacheWriteInput: null, output: 8.5 }),
  'gpt-5.1-codex': Object.freeze({ input: 1.07, cachedInput: 0.107, cacheWriteInput: null, output: 8.5 }),
  'gpt-5.1-codex-max': Object.freeze({ input: 1.25, cachedInput: 0.125, cacheWriteInput: null, output: 10 }),
  'gpt-5.1-codex-mini': Object.freeze({ input: 0.25, cachedInput: 0.025, cacheWriteInput: null, output: 2 }),
  'gpt-5.2': Object.freeze({ input: 1.75, cachedInput: 0.175, cacheWriteInput: null, output: 14 }),
  'gpt-5.2-codex': Object.freeze({ input: 1.75, cachedInput: 0.175, cacheWriteInput: null, output: 14 }),
  'gpt-5.3-codex': Object.freeze({ input: 1.75, cachedInput: 0.175, cacheWriteInput: null, output: 14 }),
  'gpt-5.3-codex-spark': Object.freeze({ input: 1.75, cachedInput: 0.175, cacheWriteInput: null, output: 14 }),
  'gpt-5.4-mini': Object.freeze({ input: 0.75, cachedInput: 0.075, cacheWriteInput: null, output: 4.5 }),
  'gpt-5.4-nano': Object.freeze({ input: 0.2, cachedInput: 0.02, cacheWriteInput: null, output: 1.25 }),
  'gpt-5.4-pro': Object.freeze({ input: 30, cachedInput: 30, cacheWriteInput: null, output: 180 }),
  'gpt-5.5-pro': Object.freeze({ input: 30, cachedInput: 30, cacheWriteInput: null, output: 180 }),
  'grok-build-0.1': Object.freeze({ input: 1, cachedInput: 0.2, cacheWriteInput: null, output: 2 }),
  'jev-1.13': Object.freeze({ input: 0.042, cachedInput: null, cacheWriteInput: null, output: 0 }),
  'jev-1.13-free': Object.freeze({ input: 0, cachedInput: null, cacheWriteInput: null, output: 0 }),
  'kimi-k2.5': Object.freeze({ input: 0.6, cachedInput: 0.1, cacheWriteInput: null, output: 3 }),
  'kimi-k2.6': Object.freeze({ input: 0.95, cachedInput: 0.16, cacheWriteInput: null, output: 4 }),
  'kimi-k2.7-code': Object.freeze({ input: 0.95, cachedInput: 0.19, cacheWriteInput: null, output: 4 }),
  'kimi-k3': Object.freeze({ input: 3, cachedInput: 0.3, cacheWriteInput: null, output: 15 }),
  'ling-3.0-flash-fin-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'ling-3.1-flash-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'longcat-2.5-preview-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'mimo-v2.5-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'mimo-v2.6-flash-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'minimax-m2.5': Object.freeze({ input: 0.3, cachedInput: 0.06, cacheWriteInput: null, output: 1.2 }),
  'minimax-m2.7': Object.freeze({ input: 0.3, cachedInput: 0.06, cacheWriteInput: null, output: 1.2 }),
  'minimax-m3': Object.freeze({ input: 0.3, cachedInput: 0.06, cacheWriteInput: null, output: 1.2 }),
  'muse-spark-1.2': Object.freeze({ input: 1.25, cachedInput: 0.15, cacheWriteInput: null, output: 4.25 }),
  'muse-spark-1.3': Object.freeze({ input: 1.25, cachedInput: 0.15, cacheWriteInput: null, output: 4.25 }),
  'muse-spark-1.3-contributor-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'nemotron-3-ultra-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'nemotron-3.5-lightning-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
  'qwen3.5-plus': Object.freeze({ input: 0.2, cachedInput: 0.02, cacheWriteInput: 0.25, output: 1.2 }),
  'qwen3.6-plus': Object.freeze({ input: 0.5, cachedInput: 0.05, cacheWriteInput: 0.625, output: 3 }),
  'qwen3.7-max': Object.freeze({ input: 2.5, cachedInput: 0.5, cacheWriteInput: 3.125, output: 7.5 }),
  'qwen3.7-plus': Object.freeze({ input: 0.4, cachedInput: 0.04, cacheWriteInput: 0.5, output: 1.6 }),
  'qwen3.8-flash': Object.freeze({ input: 0.15, cachedInput: 0.016, cacheWriteInput: 0.2, output: 0.47 }),
  'qwen3.8-max': Object.freeze({ input: 2, cachedInput: 0.25, cacheWriteInput: 2.5, output: 6 }),
  'space-bunny-free': Object.freeze({ input: 0, cachedInput: 0, cacheWriteInput: null, output: 0 }),
});

// Chỉ nhận id chính xác từ bảng Model ID trên cùng trang tài liệu, không suy
// giá từ prefix/hậu tố `-free`, và không áp giá Zen cho gateway khác.

/** Peak windows as minutes-of-day, half-open `[from, to)`, UTC. */
const DEEPSEEK_PEAK_WINDOWS = Object.freeze([[60, 240], [360, 600]]);

// The names a usage row can arrive under. The store's own usage records use the
// `…Tokens` spelling (`inputTokens`/`cachedTokens`/`cacheCreationTokens`/
// `outputTokens`), `normalizeUsage()` produces the snake_case ones, and a raw
// provider payload adds the OpenAI/OpenRouter spellings.
const USAGE_INPUT_KEYS = Object.freeze(['input', 'inputTokens', 'prompt_tokens', 'promptTokens']);
const USAGE_CACHED_KEYS = Object.freeze(['cached', 'cachedTokens', 'cached_tokens', 'cacheRead', 'cacheReadTokens', 'cache_read_input_tokens']);
const USAGE_CACHE_WRITE_KEYS = Object.freeze(['cacheWrite', 'cacheWriteTokens', 'cacheCreationTokens', 'cache_creation_tokens', 'cache_creation_input_tokens', 'cache_write_tokens']);
const USAGE_OUTPUT_KEYS = Object.freeze(['output', 'outputTokens', 'completion_tokens', 'completionTokens']);

function absent(value) {
  return value === undefined || value === null || value === '';
}

function strictNumber(value) {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/** A permissive read of a number that may have travelled through JSON as a string. */
function looseNumber(value) {
  const direct = strictNumber(value);
  if (direct !== null) return direct;
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value.trim());
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

/** A usable USD/1M component, or `null` when it is absent or unusable. */
function priceNumber(value) {
  if (absent(value)) return null;
  const parsed = strictNumber(value);
  return parsed !== null && parsed >= 0 && parsed <= MAX_PRICE_USD ? parsed : null;
}

/** Three-state read for `normalizePrice`: a number, `null` when absent, `undefined` when broken. */
function priceComponent(value) {
  if (absent(value)) return null;
  const parsed = priceNumber(value);
  return parsed === null ? undefined : parsed;
}

function asOfDate(value) {
  if (value instanceof Date) return Number.isFinite(value.getTime()) ? value.toISOString().slice(0, 10) : null;
  if (typeof value === 'number' && Number.isFinite(value)) return new Date(value).toISOString().slice(0, 10);
  if (typeof value !== 'string' || !value.trim()) return null;
  const text = value.trim().slice(0, 10);
  const parsed = Date.parse(text);
  return Number.isFinite(parsed) ? text : null;
}

function tokenCount(usage, keys) {
  for (const key of keys) {
    const parsed = looseNumber(usage?.[key]);
    if (parsed !== null) return Math.max(0, parsed);
  }
  return null;
}

function deepseekRow(modelId) {
  const id = typeof modelId === 'string' ? modelId.trim().toLowerCase() : '';
  if (!id) return null;
  if (DEEPSEEK_EXACT_ROWS[id]) return DEEPSEEK_EXACT_ROWS[id];
  if (id.startsWith('deepseek-v4-pro') || id.includes('pro')) return 'pro';
  if (id.includes('flash')) return 'flash';
  return null;
}

/**
 * Rounds a USD amount to the six decimals the router stores. Returns `null` for
 * anything that is not a finite number, so a broken value can never become a cost.
 */
export function roundUsd(value) {
  const parsed = strictNumber(value);
  if (parsed === null) return null;
  const scaled = parsed * 1e6;
  return Number.isFinite(scaled) ? Math.round(scaled) / 1e6 : null;
}

/**
 * Validates a stored or user-set price and returns its canonical shape, or `null`
 * when it must be dropped.
 *
 * Rules: `input` and `output` are required and must be finite numbers in
 * `[0, MAX_PRICE_USD]` USD/1M — `Number.isFinite`, so a string is not a price.
 * An optional `cachedInput`/`cacheWriteInput` that is present but out of range
 * rejects the whole price instead of being dropped silently, and `source` must be
 * one of `PRICE_SOURCES`: a price with no provenance is not a price. `currency` is
 * always `'USD'` (another currency cannot be stored) and `unit` is always
 * `PRICE_UNIT`; a value that says otherwise is rejected. `source`, `asOf` and
 * `updatedAt` are preserved when present.
 */
export function normalizePrice(value) {
  const price = value && typeof value === 'object' ? value : null;
  if (!price) return null;
  if (!absent(price.currency) && String(price.currency).trim().toUpperCase() !== 'USD') return null;
  if (!absent(price.unit) && String(price.unit).trim() !== PRICE_UNIT) return null;
  if (!PRICE_SOURCES.includes(price.source)) return null;
  const input = priceComponent(price.input);
  const output = priceComponent(price.output);
  const cachedInput = priceComponent(price.cachedInput);
  const cacheWriteInput = priceComponent(price.cacheWriteInput);
  // `undefined` means the field was there and was not a usable number, for every
  // component; `null` means absent, which only the optional ones may be.
  if ([input, output, cachedInput, cacheWriteInput].includes(undefined)) return null;
  if (input === null || output === null) return null;
  const updatedAt = strictNumber(price.updatedAt);
  return {
    currency: 'USD',
    unit: PRICE_UNIT,
    input,
    cachedInput,
    cacheWriteInput,
    output,
    source: price.source,
    asOf: asOfDate(price.asOf),
    ...(updatedAt !== null ? { updatedAt: Math.max(0, Math.trunc(updatedAt)) } : {}),
  };
}

/**
 * Converts an OpenRouter-shaped `pricing` object (USD **per token**, values are
 * strings such as `'0.00000015'`) into this module's USD/1M shape, without a
 * `source` — the caller owns that (`{ ...price, source: 'ping' }`).
 *
 * `prompt` → `input`, `completion` → `output`, `input_cache_read` → `cachedInput`,
 * `input_cache_write` → `cacheWriteInput`. A component that cannot be parsed is
 * left `null` instead of being invented, and the price is `null` only when the
 * required pair cannot be derived. A published `'0'` is a real price (a free
 * model), not a missing one.
 */
export function priceFromOpenRouter(pricing) {
  const payload = pricing && typeof pricing === 'object' ? pricing : null;
  if (!payload) return null;
  const convert = value => {
    const parsed = looseNumber(value);
    if (parsed === null || parsed < 0) return null;
    const perMillion = parsed * PER_MILLION;
    return perMillion <= MAX_PRICE_USD ? perMillion : null;
  };
  const input = convert(payload.prompt);
  const output = convert(payload.completion);
  if (input === null || output === null) return null;
  return {
    currency: 'USD',
    unit: PRICE_UNIT,
    input,
    cachedInput: convert(payload.input_cache_read),
    cacheWriteInput: convert(payload.input_cache_write),
    output,
  };
}

/**
 * Whether DeepSeek bills the documented peak price at `at` (a `Date`, an ISO
 * string or a timestamp).
 *
 * Peak is 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday; both windows are
 * half-open, so 04:00:00Z and 10:00:00Z are already off-peak. A timestamp that
 * cannot be read answers `true`: an estimate may be too high, never too low.
 */
export function deepseekPeakAt(at) {
  const date = at instanceof Date ? at : new Date(at);
  if (!Number.isFinite(date?.getTime?.())) return true;
  const day = date.getUTCDay();
  if (day === 0 || day === 6) return false;
  const minutes = date.getUTCHours() * 60 + date.getUTCMinutes();
  return DEEPSEEK_PEAK_WINDOWS.some(([from, to]) => minutes >= from && minutes < to);
}

/**
 * The documented DeepSeek price for `modelId` at `at`, in USD/1M, or `null` when
 * the id is not one of the documented rows.
 *
 * This function knows nothing about connections: it matches an id, so the caller
 * must scope it to a DeepSeek connection. A hand-typed id on another gateway is
 * *not* priced from here, and a non-DeepSeek name that happens to carry the
 * provider's own words (`gemini-3.8-flash-high`) would match the Flash pattern if
 * it were ever passed in. The result carries `asOf` but no `source` — the adapter
 * that wraps it stamps `'documented'`.
 */
export function documentedDeepseekPrice(modelId, at) {
  const row = deepseekRow(modelId);
  if (!row) return null;
  const prices = DEEPSEEK_ROWS[row][deepseekPeakAt(at) ? 'peak' : 'offPeak'];
  return {
    currency: 'USD',
    unit: PRICE_UNIT,
    input: prices.input,
    cachedInput: prices.cachedInput,
    cacheWriteInput: prices.cacheWriteInput,
    output: prices.output,
    asOf: DEEPSEEK_PRICE_AS_OF,
  };
}

/**
 * Giá Zen công bố cho id chính xác, hoặc null khi không có giá phẳng đáng tin.
 * Hàm thuần, không đọc đồng hồ; adapter chịu trách nhiệm scope provider và gắn
 * source: 'documented'. Bảng/asOf cố định nên không cần tham số thời gian.
 */
export function documentedZenPrice(modelId) {
  const id = typeof modelId === 'string' ? modelId.trim().toLowerCase() : '';
  if (!Object.hasOwn(ZEN_ROWS, id)) return null;
  return { currency: 'USD', unit: PRICE_UNIT, ...ZEN_ROWS[id], asOf: OPENCODE_ZEN_PRICE_AS_OF };
}

/**
 * Prices a usage row with a resolved price. Returns `{ cost, basis }` or `null`.
 *
 * Tokens are read from any of the spellings a usage row arrives under — the
 * store's own record (`inputTokens`/`cachedTokens`/`cacheCreationTokens`/
 * `outputTokens`), `normalizeUsage()`'s snake_case names, or the short model
 * (`input`/`cached`/`cacheWrite`/`output`) — clamped to `>= 0`. Counts may be
 * numbers or numeric strings; `null`/absent means "not reported".
 *
 *   hit      = min(cached, input)
 *   write    = min(cacheWrite, max(0, input - hit))
 *   miss     = max(0, input - hit - write)
 *   cost     = (miss·input + hit·cachedInput + write·cacheWriteInput + output·output) / 1e6
 *
 * `input` is the FULL input count, which is the spelling every payload that
 * publishes cache tokens uses and the one `normalizeUsage()` publishes: Anthropic
 * sends `input_tokens` (input only) beside `cache_read_input_tokens` and
 * `cache_creation_input_tokens`, and the normalizer folds all three into one
 * total. The hit and write counts are therefore already inside `input` and both are
 * subtracted before the miss bucket is charged — without that, a row carrying
 * cache-write tokens pays for them twice (measured 2026-09-20 on an
 * Anthropic-shaped row: `$0.01055` instead of the true `$0.00785`).
 *
 * A missing cache-hit price falls back to the normal input price, and the same
 * applies to a cache-write price: the honest behaviour is to charge the base rate
 * rather than invent a discount. `null` means "no number at all" — no price, or a
 * usage row that carries no token counts, where `$0` would be a lie. `basis` is
 * the price's `source`, so a computed amount is never separated from its origin.
 */
export function costFromUsage({ usage, price } = {}) {
  const source = price && typeof price === 'object' ? price : null;
  if (!source) return null;
  const inputPrice = priceNumber(source.input);
  const outputPrice = priceNumber(source.output);
  if (inputPrice === null || outputPrice === null) return null;
  const cachedPrice = priceNumber(source.cachedInput);
  const cacheWritePrice = priceNumber(source.cacheWriteInput);
  const record = usage && typeof usage === 'object' ? usage : {};
  const input = tokenCount(record, USAGE_INPUT_KEYS);
  const cached = tokenCount(record, USAGE_CACHED_KEYS);
  const cacheWrite = tokenCount(record, USAGE_CACHE_WRITE_KEYS);
  const output = tokenCount(record, USAGE_OUTPUT_KEYS);
  if (input === null && cached === null && cacheWrite === null && output === null) return null;
  const hit = Math.min(cached ?? 0, input ?? 0);
  const write = Math.min(cacheWrite ?? 0, Math.max(0, (input ?? 0) - hit));
  const miss = Math.max(0, (input ?? 0) - hit - write);
  const total = miss * inputPrice
    + hit * (cachedPrice ?? inputPrice)
    + write * (cacheWritePrice ?? inputPrice)
    + (output ?? 0) * outputPrice;
  return {
    cost: roundUsd(total / PER_MILLION),
    basis: typeof source.source === 'string' && source.source ? source.source : null,
  };
}
