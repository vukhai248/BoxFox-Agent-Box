import { RouterError } from '../errors.mjs';
import { resolveContextWindow } from '../context-window.mjs';

export function baseUrl(value) {
  return String(value || '').replace(/\/+$/, '');
}

/**
 * `Retry-After` (RFC 9110) là số giây hoặc một HTTP-date. Trả về số mili giây,
 * hoặc `null` khi header vắng mặt / không đọc được — im lặng bỏ qua một giá trị
 * rác an toàn hơn là đoán một cửa sổ nghỉ. Đây là đường DUY NHẤT đọc header này
 * dùng chung cho mọi adapter (antigravity đã tự gieo `retryAfterMs`).
 */
export function parseRetryAfter(value) {
  if (value === undefined || value === null) return null;
  const text = String(value).trim();
  if (!text) return null;
  if (/^\d+(?:\.\d+)?$/.test(text)) {
    const seconds = Number(text);
    return Number.isFinite(seconds) ? Math.round(seconds * 1000) : null;
  }
  const at = Date.parse(text);
  return Number.isFinite(at) ? Math.max(at - Date.now(), 0) : null;
}

/**
 * Mọi adapter đi qua đây khi provider trả lỗi. `retryAfterMs` (đọc từ header
 * `retry-after`) được gắn NGUYÊN vào lỗi khi nó là một số hữu hạn: engine đọc
 * nó để quyết định khoá nghỉ bao lâu, và một lỗi 429 thật đi ra tới harness vẫn
 * mang theo con số ấy trong envelope (`errors.mjs:55`). Không có header thì
 * trường vắng mặt và luật mặc định của ring áp dụng.
 */
export function providerError(status, retryable = status === 429 || status >= 500, detail = null, retryAfterMs = null) {
  const msgSuffix = detail ? `: ${detail.slice(0, 300)}` : '';
  let error;
  if (status === 401 || status === 403) error = new RouterError('AUTH', `Provider authentication failed${msgSuffix}. Reconnect or replace the credential.`, status, false);
  else if (status === 404) error = new RouterError('MODEL_NOT_FOUND', `The provider no longer exposes this model${msgSuffix}. Refreshing model inventory may resolve it.`, 404, true);
  else if (status === 429) error = new RouterError('RATE_LIMIT', `Provider rate limit or quota reached${msgSuffix}. Try again later.`, status, true);
  else error = new RouterError('UNAVAILABLE', detail ? `Provider error (${status}): ${detail.slice(0, 300)}` : 'Provider is unavailable or returned an invalid response.', status || 502, retryable);
  if (Number.isFinite(retryAfterMs)) error.retryAfterMs = retryAfterMs;
  // Lời của chính nhà cung cấp, giữ BÊN CẠNH câu chuẩn của router. Vòng khoá đọc
  // trường này (`keyring.mjs` → `classifyState`): câu chuẩn luôn chứa chữ "quota"
  // ("Provider rate limit or quota reached…"), nên phân loại trên cả câu sẽ biến mọi
  // 429 thành `exhausted` và trạng thái `cooling` (cùng số đếm ngược) không bao giờ
  // hiện ra với họ adapter này.
  if (typeof detail === 'string' && detail) error.providerMessage = detail.slice(0, 300);
  return error;
}

export async function ensureOk(response) {
  if (!response.ok) {
    let detail = null;
    try {
      const text = await response.text();
      try {
        const json = JSON.parse(text);
        detail = json.error?.message || json.message || text;
      } catch {
        detail = text;
      }
    } catch {}
    throw providerError(response.status, undefined, detail, parseRetryAfter(response.headers?.get?.('retry-after')));
  }
  return response;
}

export async function jsonOrProviderError(response) {
  await ensureOk(response);
  try { return await response.json(); }
  catch { throw new RouterError('UNAVAILABLE', 'Provider is unavailable or returned an invalid response.', 502, true); }
}

export async function* sseEvents(response) {
  await ensureOk(response);
  if (!response.body) throw new RouterError('UNAVAILABLE', 'Provider is unavailable or returned an invalid response.', 502, true);
  const decoder = new TextDecoder();
  let buffer = '';
  let event = null;
  let data = [];
  const flush = () => {
    if (!data.length && !event) return null;
    const value = { event, data: data.join('\n') };
    event = null; data = [];
    return value;
  };
  for await (const chunk of response.body) {
    buffer += decoder.decode(chunk, { stream: true });
    while (true) {
      const match = buffer.match(/\r?\n/);
      if (!match) break;
      const index = match.index;
      const line = buffer.slice(0, index);
      buffer = buffer.slice(index + match[0].length);
      if (!line) {
        const value = flush();
        if (value) yield value;
        continue;
      }
      if (line.startsWith(':')) continue;
      const split = line.indexOf(':');
      const field = split < 0 ? line : line.slice(0, split);
      const value = split < 0 ? '' : line.slice(split + 1).replace(/^ /, '');
      if (field === 'event') event = value;
      else if (field === 'data') data.push(value);
    }
  }
  buffer += decoder.decode();
  if (buffer) {
    for (const line of buffer.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      else if (line.startsWith('data:')) data.push(line.slice(5).trimStart());
    }
  }
  const value = flush();
  if (value) yield value;
}

export function parseJson(value) {
  try { return JSON.parse(value); } catch { return null; }
}

// BUG-4/R2: the model record carries the provider's own model metadata so the
// router, the harness and the UI share one source of truth.
export const THINKING_TYPES = Object.freeze(['effort', 'budget', 'fixed', 'none']);
// OpenAI `reasoning_effort` values used by OpenAI/Codex/OpenRouter.
export const EFFORT_LEVELS = Object.freeze(['minimal', 'low', 'medium', 'high']);
// Google maps OpenAI `reasoning_effort` directly onto `thinking_level`.
export const GEMINI_THINKING_LEVELS = Object.freeze(['low', 'medium', 'high']);

function positiveInteger(value) {
  return Number.isInteger(value) && value > 0 ? value : null;
}

export function normalizeThinkingLevels(value) {
  if (!Array.isArray(value)) return [];
  const levels = value.filter(level => typeof level === 'string' && level.trim().length > 0).map(level => level.trim());
  return [...new Set(levels)];
}

/**
 * Normalizes the shared thinking/context fields.
 *
 * The context window goes through the router's shipped name table
 * (`context-window.mjs`): a model whose name matches the table publishes the
 * table's number (`contextWindowSource:'documented'`), and the provider's own
 * number is kept beside it as `contextWindowReported` so a stale row can show
 * itself. A name the table does not know keeps the number its caller supplied
 * (`'reported'`), or `null` when nobody supplied one — nothing is guessed here.
 *
 * Inputs: `id`/`name` (what the table matches on), `contextWindow` (the number
 * the provider payload or the adapter's rule supplied), `declaredContextWindow`
 * (a number the user typed for this model), `reportedContextWindow` (a provider
 * number already held beside a user declaration).
 */
export function modelThinking(values = {}) {
  const source = values && typeof values === 'object' ? values : {};
  const thinkingLevels = normalizeThinkingLevels(source.thinkingLevels);
  const declared = THINKING_TYPES.includes(source.thinkingType) ? source.thinkingType : null;
  // A row already marked `manual` keeps the number it is holding, even when a
  // caller forgets to name it: a user declaration never degrades into a guess.
  const manual = positiveInteger(source.declaredContextWindow)
    ?? (source.contextWindowSource === 'manual' ? positiveInteger(source.contextWindow) : null);
  const reported = positiveInteger(source.reportedContextWindow) ?? (manual === null ? positiveInteger(source.contextWindow) : null);
  const context = resolveContextWindow({ id: source.id, name: source.name, reported, declared: manual });
  // Levels without an explicit control type still mean the provider exposes
  // selectable levels; those providers use an effort-style control.
  return {
    ...context,
    thinkingType: declared || (thinkingLevels.length ? 'effort' : 'none'),
    defaultThinking: typeof source.defaultThinking === 'string' && source.defaultThinking.trim() ? source.defaultThinking.trim() : null,
    thinkingLevels,
  };
}

/**
 * Maps an OpenRouter-shaped `/models` entry (also returned by several
 * OpenAI-compatible gateways) onto the shared metadata contract. Only payload
 * fields are read: `context_length`, top-level preferred, and the `reasoning`
 * block with `supported_efforts`/`default_effort`/`default_enabled`/`mandatory`.
 * `supported_parameters` containing reasoning/include_reasoning/thinking is the
 * weaker signal used when the `reasoning` block is absent.
 */
export function thinkingFromProviderPayload(item = {}) {
  const reasoning = item?.reasoning && typeof item.reasoning === 'object' ? item.reasoning : null;
  const params = Array.isArray(item?.supported_parameters) ? item.supported_parameters : [];
  const declared = Boolean(
    reasoning?.supported_efforts?.length ||
    reasoning?.default_enabled === true ||
    reasoning?.mandatory === true ||
    params.includes('reasoning') || params.includes('include_reasoning') || params.includes('thinking'),
  );
  return modelThinking({
    id: item?.id,
    name: item?.name,
    contextWindow: item?.context_length ?? item?.context_window ?? item?.top_provider?.context_length ?? item?.max_context_length ?? null,
    thinkingType: declared ? 'effort' : 'none',
    thinkingLevels: reasoning?.supported_efforts,
    defaultThinking: typeof reasoning?.default_effort === 'string' ? reasoning.default_effort : null,
  });
}

export function modelRecord(id, name = id, capabilities = {}, thinking = {}) {
  return {
    id,
    name: name || id,
    source: 'live',
    stale: false,
    ...modelThinking({ ...thinking, id, name }),
    capabilities: { streaming: 'reported', tools: 'unknown', vision: 'unknown', reasoning: 'unknown', ...capabilities },
  };
}

export function normalizeFinishReason(value) {
  if (value === 'tool_use' || value === 'tool_calls') return 'tool_calls';
  if (value === 'max_tokens' || value === 'length') return 'length';
  if (value === 'content_filter') return 'content_filter';
  if (value === 'refusal') return 'content_filter';
  if (value === 'stream_incomplete' || value === 'stream_interrupted') return 'stream_incomplete';
  return 'stop';
}


