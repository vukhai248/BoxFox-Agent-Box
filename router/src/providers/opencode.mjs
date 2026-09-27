// OpenCode Free Provider Adapter for BoxFox Router
//
// Adapted from 9Router MIT-licensed `open-sse/providers/registry/opencode.js` and
// `open-sse/executors/opencode.js` (checked against upstream v0.5.81, commit
// a8c9d38). The two clauses of that release this file implements are
// "resolve 403 FreeTierError and 429 rate limits with canonical session format,
// valid User-Agent, and stable upstream session reuse; force stream and declare
// `forceStream` for free-tier SSE aggregation" and "cloak decoy tools, normalize
// Muse Free tool choice, and strip prior reasoning items on Responses models".
//
// The free tier answers only a request that looks like the OpenCode client.
// Every rule below was measured live from this machine on 2026-09-21 with
// `Authorization: Bearer public` against `https://opencode.ai/zen/v1`:
//
//   | request shape                                | result             |
//   |----------------------------------------------|--------------------|
//   | `User-Agent: opencode` (no version)          | 403 FreeTierError  |
//   | `User-Agent: opencode/1.18.31`               | 200                |
//   | `tools: []` (no decoy tools)                 | 403 FreeTierError  |
//   | `stream: false`                              | 403 FreeTierError  |
//   | `x-opencode-session: ses_<32 hex>`           | 403 FreeTierError  |
//   | `x-opencode-session: ses_<12hex><14base62>`  | 200                |
//   | `reasoning_effort` in the body               | 400 invalid_request|
//   | `reasoning: {effort, summary}`               | 200                |
//   | `reasoning.effort: 'none'`                   | 400 invalid_request|
//   | data-URI `input_image` part                  | 200, colour read 4/4|
//   | tool result image flattened into `output`    | 200, empty answer  |
//   | tool result image as a following user turn   | 200, colour read   |
//
// Consequences carried in the code: always stream upstream and aggregate here,
// always send the two decoy tools beside the caller's tools, always mint
// OpenCode-shaped session/request ids and reuse one session per conversation,
// translate `reasoning_effort` into `reasoning.effort`, drop prior reasoning
// items, and move tool-result images into their own user turn.

import { createHash, randomUUID } from 'node:crypto';
import { EFFORT_LEVELS, modelRecord, normalizeFinishReason, parseJson, parseRetryAfter, providerError, sseEvents } from './common.mjs';
import { RouterError } from '../errors.mjs';

const BASE_URL = 'https://opencode.ai';

/** The CLI user agent the free tier accepts. 9Router pins the same shape; the gate reads the version. */
export const OPENCODE_UA = 'opencode/1.18.31';
/** `hasValidOpencodeVersion()` in 9Router: major > 1 or minor >= 17. */
export const OPENCODE_MIN_VERSION = Object.freeze({ major: 1, minor: 17 });

/** `ses_<12 hex><14 base62>` — a `ses_<32 hex>` uuid is refused with 403. */
export const OPENCODE_SESSION_RE = /^ses_[0-9a-f]{12}[0-9A-Za-z]{14}$/;
/** `msg_<12 hex><14 base62>`. */
export const OPENCODE_REQUEST_RE = /^msg_[0-9a-f]{12}[0-9A-Za-z]{14}$/;

const BASE62_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz';

/** How long a canonical session is reused before a new one is minted for the same conversation. */
const SESSION_TTL_MS = 6 * 60 * 60 * 1000;
const MAX_STABLE_SESSIONS = 200;

/**
 * The two decoy tools the free tier requires in every request. Their
 * description is upstream's, verbatim: the gate looks for tools that the real
 * OpenCode client would have sent.
 */
export const OPENCODE_DECOY_TOOLS = Object.freeze([
  { type: 'function', name: 'bash', description: 'This tool is currently unavailable and must not be used.', parameters: { type: 'object', properties: {} } },
  { type: 'function', name: 'read', description: 'This tool is currently unavailable and must not be used.', parameters: { type: 'object', properties: {} } },
]);

/** Models whose free tier only accepts `tool_choice: 'auto'` (9Router `forceAutoToolChoiceModels`). */
const FORCE_AUTO_TOOL_CHOICE = Object.freeze(['muse-spark-1.3-contributor-free']);

const MAX_TOOL_NAME_LEN = 128;
const MAX_CALL_ID_LEN = 128;

export const OPENCODE_MODELS = Object.freeze([
  {
    ...modelRecord('muse-spark-1.2-contributor-free', 'Muse Spark 1.2 Contributor Free', { streaming: 'reported', tools: 'reported', vision: 'reported', reasoning: 'reported' }, { thinkingType: 'effort', thinkingLevels: EFFORT_LEVELS }),
  },
  {
    ...modelRecord('muse-spark-1.3-contributor-free', 'Muse Spark 1.3 Contributor Free', { streaming: 'reported', tools: 'reported', vision: 'reported', reasoning: 'reported' }, { thinkingType: 'effort', thinkingLevels: EFFORT_LEVELS }),
  },
]);

function isResponsesModel(modelId) {
  const m = String(modelId || '').toLowerCase();
  return m.includes('muse-spark') || m.includes('responses');
}

/** Accepts the versioned CLI user agent, refuses to send a bare `opencode` (403). */
export function hasValidOpencodeVersion(userAgent) {
  const match = /^opencode\/(\d+)\.(\d+)/i.exec(String(userAgent || '').trim());
  if (!match) return false;
  const major = Number(match[1]);
  const minor = Number(match[2]);
  return major > OPENCODE_MIN_VERSION.major || (major === OPENCODE_MIN_VERSION.major && minor >= OPENCODE_MIN_VERSION.minor);
}

/** `ses_`/`msg_` id from a seed: 12 hex chars then 14 base62 chars, both derived from one SHA-256 digest. */
export function mintOpencodeId(prefix, seed) {
  const digest = createHash('sha256').update(`${prefix}\0${seed}`).digest();
  const hex = digest.subarray(0, 6).toString('hex');
  let tail = '';
  for (let i = 6; i < 20; i += 1) tail += BASE62_CHARS[digest[i] % 62];
  return `${prefix}_${hex}${tail}`;
}

/** Passes a well-formed id through, otherwise derives one from the seed (9Router `translateSessionId`). */
export function translateSessionId(seed) {
  const value = typeof seed === 'string' ? seed.trim() : '';
  if (OPENCODE_SESSION_RE.test(value)) return value;
  return mintOpencodeId('ses', value || 'anonymous');
}

/** Deterministic per-turn request id, so a retry of the same turn reuses one id. */
export function deriveRequestId(sessionId, body) {
  const messages = Array.isArray(body?.messages) ? body.messages : null;
  let lastUser = '';
  if (messages) {
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i]?.role === 'user') {
        const content = messages[i].content;
        lastUser = typeof content === 'string' ? content : JSON.stringify(content ?? '');
        break;
      }
    }
  }
  if (!lastUser) {
    const input = Array.isArray(body?.input) ? body.input : [];
    for (let i = input.length - 1; i >= 0; i -= 1) {
      const item = input[i];
      if (item?.role === 'user') {
        lastUser = typeof item.content === 'string' ? item.content : JSON.stringify(item.content ?? '');
        break;
      }
    }
  }
  if (!lastUser) return mintOpencodeId('msg', randomUUID());
  return mintOpencodeId('msg', `${sessionId}\0${lastUser}`);
}

// ── canonical session reuse ─────────────────────────────────────────────────
// The free tier accounts quota per session, and minting a fresh one per request
// is what surfaces upstream as a 429. One canonical session is kept per
// conversation identity and reused until it goes idle.

const stableSessions = new Map();

function stableSessionId(key) {
  const now = Date.now();
  for (const [storedKey, entry] of stableSessions) {
    if (now - entry.lastUsed > SESSION_TTL_MS) stableSessions.delete(storedKey);
  }
  const existing = stableSessions.get(key);
  if (existing) {
    existing.lastUsed = now;
    return existing.sessionId;
  }
  const sessionId = mintOpencodeId('ses', `${key}\0${randomUUID()}`);
  if (stableSessions.size >= MAX_STABLE_SESSIONS) {
    stableSessions.delete(stableSessions.keys().next().value);
  }
  stableSessions.set(key, { sessionId, lastUsed: now });
  return sessionId;
}

/** Test seam: forget every canonical session. */
export function resetStableSessions() {
  stableSessions.clear();
}

function sessionHint(body) {
  const candidates = [body?.session_id, body?.sessionId, body?.metadata?.session_id, body?.metadata?.sessionId];
  for (const candidate of candidates) {
    const value = typeof candidate === 'string' ? candidate.trim() : '';
    if (value) return value;
  }
  return null;
}

function resolveSession({ connection, credentials, body } = {}) {
  const hinted = sessionHint(body);
  if (hinted) return translateSessionId(hinted);
  const key = ['opencode', credentials?.id || credentials?.label || '', connection?.id || connection?.providerId || 'global', body?.model || ''].join('\0');
  return stableSessionId(key);
}

function opencodeHeaders({ stream = true, apiKey = null, session, request, userAgent } = {}) {
  return {
    'Content-Type': 'application/json',
    Authorization: apiKey ? `Bearer ${apiKey}` : 'Bearer public',
    'User-Agent': hasValidOpencodeVersion(userAgent) ? userAgent : OPENCODE_UA,
    'x-opencode-client': 'desktop',
    'x-opencode-session': session,
    'x-opencode-request': request,
    'x-opencode-project': 'global',
    Accept: stream ? 'text/event-stream' : '*/*',
  };
}

// ── request translation ─────────────────────────────────────────────────────

function textOfContent(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) {
    if (content === undefined || content === null) return '';
    try { return JSON.stringify(content); } catch { return String(content); }
  }
  let text = '';
  for (const part of content) {
    if (typeof part === 'string') { text += part; continue; }
    if (!part || typeof part !== 'object') continue;
    if (typeof part.text === 'string') text += part.text;
  }
  return text;
}

function imageUrlsOfContent(content) {
  if (!Array.isArray(content)) return [];
  const urls = [];
  for (const part of content) {
    if (!part || typeof part !== 'object') continue;
    if (part.type === 'image_url') {
      const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url;
      if (url) urls.push(url);
      continue;
    }
    if (part.type === 'input_image') {
      const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url;
      if (url) urls.push(url);
    }
  }
  return urls;
}

function inputPartsOfContent(content) {
  if (typeof content === 'string') return content ? [{ type: 'input_text', text: content }] : [];
  if (!Array.isArray(content)) return textOfContent(content) ? [{ type: 'input_text', text: textOfContent(content) }] : [];
  const parts = [];
  for (const part of content) {
    if (typeof part === 'string') { if (part) parts.push({ type: 'input_text', text: part }); continue; }
    if (!part || typeof part !== 'object') continue;
    if (part.type === 'image_url' || part.type === 'input_image') {
      const url = typeof part.image_url === 'string' ? part.image_url : part.image_url?.url;
      if (url) parts.push({ type: 'input_image', image_url: url });
      continue;
    }
    if (part.type === 'input_text' && typeof part.text === 'string') { parts.push({ type: 'input_text', text: part.text }); continue; }
    if (typeof part.text === 'string') { if (part.text) parts.push({ type: 'input_text', text: part.text }); }
  }
  return parts;
}

function clampCallId(value) {
  const id = typeof value === 'string' ? value.trim() : '';
  if (!id) return `call_${randomUUID().replace(/-/g, '').slice(0, 20)}`;
  return id.length > MAX_CALL_ID_LEN ? id.slice(0, MAX_CALL_ID_LEN) : id;
}

/** Single stringify: objects become JSON once, fragments fall back to `{}`. */
function coerceArguments(value) {
  if (value === undefined || value === null || value === '') return '{}';
  if (typeof value === 'string') return value;
  try { return JSON.stringify(value); } catch { return '{}'; }
}

function coerceOutput(value) {
  if (typeof value === 'string') return value;
  if (value === undefined || value === null) return '';
  if (Array.isArray(value)) {
    // Image parts are forwarded as a following user turn instead of being
    // inlined here: measured live, the array-output form answers 200 with an
    // empty body, and JSON-stringifying a screenshot would carry the base64 twice.
    return value.map(part => {
      if (!part || typeof part !== 'object') return String(part ?? '');
      if (typeof part.text === 'string') return part.text;
      if (part.type === 'image_url' || part.type === 'input_image') return '';
      try { return JSON.stringify(part); } catch { return String(part); }
    }).join('');
  }
  try { return JSON.stringify(value); } catch { return String(value); }
}

/**
 * Chat messages → Responses `input` items.
 *
 * Tool results that carry images cannot ride inside `function_call_output`:
 * measured live, the array-output form answers 200 with an empty body, while a
 * text-only output followed by a user turn holding the image is read correctly.
 * So an image-bearing tool result yields both items.
 */
export function toResponsesInput(messages = []) {
  const input = [];
  let instructions = null;
  for (const message of Array.isArray(messages) ? messages : []) {
    if (!message || typeof message !== 'object') continue;
    const role = message.role;
    if (role === 'system' || role === 'developer') {
      if (instructions === null) {
        const text = textOfContent(message.content);
        if (text) instructions = text;
      }
      continue;
    }
    if (role === 'tool' || role === 'function') {
      const callId = clampCallId(message.tool_call_id || message.call_id);
      input.push({ type: 'function_call_output', call_id: callId, output: coerceOutput(message.content) });
      const images = imageUrlsOfContent(message.content);
      if (images.length) {
        input.push({
          type: 'message',
          role: 'user',
          content: [
            { type: 'input_text', text: 'The tool result also returned image data; it follows as an attachment.' },
            ...images.map(url => ({ type: 'input_image', image_url: url })),
          ],
        });
      }
      continue;
    }
    if (role === 'assistant') {
      const text = textOfContent(message.content);
      if (text) input.push({ type: 'message', role: 'assistant', content: [{ type: 'output_text', text }] });
      for (const call of Array.isArray(message.tool_calls) ? message.tool_calls : []) {
        const name = String(call?.function?.name || call?.name || '').trim();
        if (!name) continue;
        input.push({
          type: 'function_call',
          name: name.slice(0, MAX_TOOL_NAME_LEN),
          call_id: clampCallId(call?.id),
          arguments: coerceArguments(call?.function?.arguments ?? call?.arguments),
        });
      }
      continue;
    }
    const parts = inputPartsOfContent(message.content);
    if (parts.length) input.push({ type: 'message', role: 'user', content: parts });
  }
  return { input, instructions };
}

/** Strips prior reasoning items and their encrypted payloads (refused across accounts / under `store:false`). */
export function sanitizeResponsesItems(input = []) {
  const items = [];
  for (const item of Array.isArray(input) ? input : []) {
    if (!item || typeof item !== 'object') { items.push(item); continue; }
    if (item.type === 'reasoning') continue;
    const next = { ...item };
    delete next.encrypted_content;
    delete next.reasoning_encrypted_content;
    if (next.type === 'function_call') {
      const name = typeof next.name === 'string' ? next.name.trim() : '';
      if (!name) continue;
      next.name = name.slice(0, MAX_TOOL_NAME_LEN);
      next.call_id = clampCallId(next.call_id);
      next.arguments = coerceArguments(next.arguments);
    }
    if (next.type === 'function_call_output') {
      next.call_id = clampCallId(next.call_id);
      next.output = coerceOutput(next.output);
    }
    items.push(next);
  }
  return items;
}

/** Chat-shaped tools → Responses-shaped tools, dropping anything with no usable name. */
export function responsesTools(tools = []) {
  const out = [];
  for (const tool of Array.isArray(tools) ? tools : []) {
    if (!tool || typeof tool !== 'object') continue;
    const fn = tool.function && typeof tool.function === 'object' ? tool.function : null;
    const name = String(tool.name || fn?.name || '').trim();
    if (!name) continue;
    const parameters = (tool.parameters && typeof tool.parameters === 'object')
      ? tool.parameters
      : (fn?.parameters && typeof fn.parameters === 'object' ? fn.parameters : { type: 'object', properties: {} });
    out.push({
      type: 'function',
      name: name.slice(0, MAX_TOOL_NAME_LEN),
      description: String(tool.description || fn?.description || ''),
      parameters: parameters.type === 'object' && !parameters.properties ? { ...parameters, properties: {} } : parameters,
    });
  }
  return out;
}

/** Adds the two decoy tools when the caller's set does not already carry them. */
export function cloakOpencodeTools(tools = []) {
  const list = Array.isArray(tools) ? [...tools] : [];
  const names = new Set(list.map(tool => String(tool?.name || '').trim()));
  for (const decoy of OPENCODE_DECOY_TOOLS) {
    if (!names.has(decoy.name)) list.push({ ...decoy });
  }
  return list;
}

/** `reasoning_effort` is refused by this endpoint; `reasoning: {effort}` is the accepted spelling. */
export function normalizeOpencodeReasoning(model, body = {}) {
  const current = body?.reasoning && typeof body.reasoning === 'object' && !Array.isArray(body.reasoning) ? body.reasoning : null;
  const requested = typeof body?.reasoning_effort === 'string' ? body.reasoning_effort : current?.effort;
  const outgoing = { ...body };
  delete outgoing.reasoning_effort;
  if (body?.thinkingLevel !== undefined) delete outgoing.thinkingLevel;
  const effort = typeof requested === 'string' ? requested.toLowerCase().trim() : '';
  if (!effort || effort === 'none' || effort === 'auto') {
    if (current) delete outgoing.reasoning;
    return outgoing;
  }
  outgoing.reasoning = { ...current, effort, summary: current?.summary || 'auto' };
  return outgoing;
}

// ── response translation ────────────────────────────────────────────────────

function usageFrom(input) {
  if (!input) return null;
  return {
    prompt_tokens: input.input_tokens || 0,
    completion_tokens: input.output_tokens || 0,
    total_tokens: input.total_tokens || ((input.input_tokens || 0) + (input.output_tokens || 0)),
  };
}

/**
 * One Responses SSE stream → the router's event contract.
 *
 * `output_index` counts every output item (reasoning, message, function_call),
 * while `tool_calls[].index` counts only tool calls, so the two are mapped as
 * calls arrive.
 */
async function* translateResponsesStream(response) {
  const toolIndexByOutput = new Map();
  let nextToolIndex = 0;
  let sawToolCall = false;
  let finishReason = null;

  const toolIndexOf = outputIndex => {
    if (toolIndexByOutput.has(outputIndex)) return toolIndexByOutput.get(outputIndex);
    const index = nextToolIndex;
    nextToolIndex += 1;
    toolIndexByOutput.set(outputIndex, index);
    return index;
  };

  for await (const event of sseEvents(response)) {
    if (!event.data || event.data === '[DONE]') continue;
    const data = parseJson(event.data);
    if (!data) continue;

    if (data.type === 'response.output_text.delta' && data.delta) {
      yield { type: 'delta', delta: { content: data.delta } };
      continue;
    }
    if (typeof data.type === 'string' && /^response\.(reasoning|reasoning_summary|thought)/.test(data.type) && data.delta) {
      yield { type: 'delta', delta: { reasoning_content: data.delta } };
      continue;
    }
    if (data.type === 'response.output_item.added' && data.item?.type === 'function_call') {
      sawToolCall = true;
      yield {
        type: 'delta',
        delta: {
          tool_calls: [{
            index: toolIndexOf(data.output_index),
            id: clampCallId(data.item.call_id || data.item.id),
            type: 'function',
            function: { name: data.item.name || '', arguments: data.item.arguments || '' },
          }],
        },
      };
      continue;
    }
    if (data.type === 'response.function_call_arguments.delta' && data.delta) {
      sawToolCall = true;
      yield {
        type: 'delta',
        delta: { tool_calls: [{ index: toolIndexOf(data.output_index), function: { arguments: data.delta } }] },
      };
      continue;
    }
    if (data.type === 'response.output_item.done' && data.item?.type === 'function_call' && !toolIndexByOutput.has(data.output_index)) {
      sawToolCall = true;
      yield {
        type: 'delta',
        delta: {
          tool_calls: [{
            index: toolIndexOf(data.output_index),
            id: clampCallId(data.item.call_id || data.item.id),
            type: 'function',
            function: { name: data.item.name || '', arguments: data.item.arguments || '' },
          }],
        },
      };
      continue;
    }
    if (data.type === 'response.failed' || data.type === 'error') {
      const detail = data.response?.error?.message || data.error?.message || data.message || 'OpenCode Free stream failed.';
      throw new RouterError('UNAVAILABLE', `OpenCode Free stream failed: ${String(detail).slice(0, 300)}`, 502, true);
    }
    if (data.type === 'response.completed' || data.type === 'response.done') {
      const usage = usageFrom(data.response?.usage);
      if (usage) yield { type: 'usage', usage };
      finishReason = sawToolCall ? 'tool_calls' : normalizeFinishReason(data.response?.status === 'incomplete' ? 'length' : 'stop');
      continue;
    }
  }
  // A `response.completed`/`response.done` event is the ONLY thing that sets `finishReason`
  // above, but the `finish` line is synthesised by US - so a stream cut mid-answer (no
  // terminal event, hence no `finishReason`) must not be reported as a clean stop.
  // Measured live 2026-09-26 on a `muse-spark-1.3-contributor-free` review turn: the
  // severed answer looked complete, so a critique without its required final `VERDICT:`
  // line passed as a finished critique. `length` is the honest reason.
  yield { type: 'finish', finishReason: finishReason || 'length' };
}

async function* aggregate(events) {
  let content = '';
  let reasoning = '';
  const calls = new Map();
  let usage = null;
  let finishReason = 'stop';
  // A `finish` event is the provider SAYING it finished. `aggregate` folds a provider stream into
  // ONE response, so a stream that ended without that event was cut: the aggregated `stop` default
  // would hand the caller a severed answer that looks complete (measured live 2026-09-26 on a
  // `muse-spark-1.3-contributor-free` review turn - a critique without its required final
  // `VERDICT:` line passed as a finished critique). The harness reads this field on its
  // non-streaming fallback after a broken SSE channel, so `length` is the honest reason and it wins
  // over the tool-call guess below.
  let sawFinish = false;
  for await (const event of events) {
    if (event.type === 'delta') {
      if (event.delta.content) content += event.delta.content;
      if (event.delta.reasoning_content) reasoning += event.delta.reasoning_content;
      for (const call of event.delta.tool_calls || []) {
        const index = call.index ?? 0;
        const current = calls.get(index) || { id: '', type: 'function', function: { name: '', arguments: '' } };
        if (call.id) current.id = call.id;
        if (call.function?.name) current.function.name += call.function.name;
        if (call.function?.arguments) current.function.arguments += call.function.arguments;
        calls.set(index, current);
      }
      continue;
    }
    if (event.type === 'usage') usage = event.usage;
    if (event.type === 'finish') { sawFinish = true; finishReason = event.finishReason; }
  }
  const delta = {};
  if (content) delta.content = content;
  if (reasoning) delta.reasoning_content = reasoning;
  if (calls.size) {
    delta.tool_calls = [...calls.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([index, call]) => ({ index, id: call.id || clampCallId(null), type: 'function', function: call.function }));
  }
  if (Object.keys(delta).length) yield { type: 'delta', delta };
  if (usage) yield { type: 'usage', usage };
  if (!sawFinish) finishReason = 'length';
  else if (calls.size && finishReason === 'stop') finishReason = 'tool_calls';
  yield { type: 'finish', finishReason };
}

/**
 * Phân loại lỗi của OpenCode Free. Giữ nguyên tên và câu chữ của từng nhánh;
 * `retryAfterMs` được gắn ở lớp ngoài (`opencodeError`) nên mọi nhánh đều mang
 * theo header `retry-after` khi provider có gửi nó.
 */
function classifyOpencodeError(status, statusText, errorText) {
  let parsed = null;
  try { parsed = JSON.parse(errorText); } catch { /* not JSON */ }
  const detail = parsed?.error?.message || parsed?.message || null;
  const type = parsed?.error?.type || parsed?.type || null;
  if (status === 403 && /free tier/i.test(detail || errorText)) {
    return new RouterError(
      'AUTH',
      'OpenCode Free refused the request: the free tier only answers OpenCode\'s own client shape (versioned user agent, streaming, decoy tools, canonical session id). Reconnect the provider or refresh the model inventory.',
      403,
      false,
    );
  }
  if (status === 429) {
    return new RouterError('RATE_LIMIT', detail || 'OpenCode Free quota reached for this session. Try again later.', 429, true);
  }
  if (status === 401 && /api key/i.test(detail || '')) {
    return new RouterError('AUTH', `${detail} This model id is not on the free tier; add an OpenCode credential to use it.`, 401, false);
  }
  let message = detail;
  if (!message) {
    if (errorText.includes('<!DOCTYPE') || errorText.includes('<html')) {
      message = `OpenCode API returned HTTP ${status} (${statusText || 'Endpoint Error'})`;
    } else {
      message = errorText.slice(0, 300) || `OpenCode error HTTP ${status}`;
    }
  }
  if (type === 'FreeTierError') return new RouterError('AUTH', message, 403, false);
  return new RouterError('PROVIDER_ERROR', message, status, status >= 500);
}

function opencodeError(status, statusText, errorText, retryAfterMs = null) {
  const error = classifyOpencodeError(status, statusText, errorText);
  if (Number.isFinite(retryAfterMs)) error.retryAfterMs = retryAfterMs;
  return error;
}

export function createOpenCodeAdapter({ fetchImpl }) {
  const baseFor = connection => {
    const rawBase = (connection?.endpoint || BASE_URL).replace(/\/+$/, '');
    return rawBase.includes('/zen/v1') ? rawBase : `${rawBase}/zen/v1`;
  };

  return {
    fallbackModels: OPENCODE_MODELS.map(model => ({ ...model, source: 'static', stale: false, enabled: true })),

    async discover({ connection, credentials, signal } = {}) {
      try {
        const modelsUrl = `${baseFor(connection)}/models`;
        const response = await fetchImpl(modelsUrl, {
          headers: opencodeHeaders({ stream: false, apiKey: credentials?.apiKey, userAgent: credentials?.userAgent, session: translateSessionId('discovery'), request: mintOpencodeId('msg', randomUUID()) }),
          signal,
        });
        if (response.ok) {
          const data = await response.json();
          const list = Array.isArray(data?.data) ? data.data : Array.isArray(data) ? data : [];
          if (list.length) {
            return {
              models: list.map(item => {
                const curated = OPENCODE_MODELS.find(m => m.id === item.id) || null;
                // Only the free ids answer without a credential; everything else
                // needs a key (measured: plain `muse-spark-1.2` → 401 AuthError).
                const isFree = item.id.includes('-free');
                return {
                  ...(curated ? { ...curated } : modelRecord(item.id, item.name || item.id)),
                  enabled: isFree,
                  stale: false,
                  source: 'live',
                };
              }),
            };
          }
        }
      } catch {
        /* best effort fallback */
      }
      return {
        // Curated fallback: the inventory call did not answer, so this is not
        // live data (BUG-4/R2).
        models: OPENCODE_MODELS.map(m => ({ ...m, source: 'static', stale: false, enabled: true })),
      };
    },

    async *generate({ connection, credentials, body, signal }) {
      const wantsStream = body?.stream !== false;
      const modelId = body?.model;
      const base = baseFor(connection);
      const isResponses = isResponsesModel(modelId);
      const targetUrl = isResponses ? `${base}/responses` : `${base}/chat/completions`;
      const session = resolveSession({ connection, credentials, body });
      const headers = opencodeHeaders({
        stream: true,
        apiKey: credentials?.apiKey,
        userAgent: credentials?.userAgent,
        session,
        request: deriveRequestId(session, body),
      });

      let requestBody;
      if (isResponses) {
        const source = normalizeOpencodeReasoning(modelId, body);
        const { input, instructions } = toResponsesInput(source.messages);
        const items = sanitizeResponsesItems(input);
        if (!items.length) {
          items.push({ type: 'message', role: 'user', content: [{ type: 'input_text', text: 'Hello' }] });
        }
        const tools = cloakOpencodeTools(responsesTools(source.tools));
        requestBody = {
          model: modelId,
          input: items,
          ...(instructions ? { instructions } : {}),
          ...(source.reasoning ? { reasoning: source.reasoning } : {}),
          // The free tier refuses `tools: []`, so the decoys always ride along.
          tools,
          tool_choice: 'auto',
          max_output_tokens: Math.max(1000, Number(source.max_output_tokens || source.max_tokens) || 1000),
          // Always stream upstream: a non-streaming free-tier request is a 403.
          stream: true,
          store: false,
        };
        if (FORCE_AUTO_TOOL_CHOICE.includes(String(modelId))) requestBody.tool_choice = 'auto';
      } else {
        const source = normalizeOpencodeReasoning(modelId, body);
        // 9Router `cloakOpencodeTools(body, false)`: the free tier requires the two decoy tools in every
        // chat payload, so a caller that brings no tools of its own still sends `tools: [bash, read]`
        // (and only then `tool_choice: 'none'`, because the decoys must never be called). Omitting
        // `tools` — the shape this branch used to send — is the `tools: []` row of the table above:
        // a `403 FreeTierError`, which the account-scoped AUTH rule then turns into a dead connection.
        const callerTools = Array.isArray(source.tools) ? source.tools : [];
        const names = new Set(callerTools.map(tool => String(tool?.function?.name || tool?.name || '')));
        const chatTools = [...callerTools, ...OPENCODE_DECOY_TOOLS.filter(decoy => !names.has(decoy.name))
          .map(decoy => ({ type: 'function', function: { name: decoy.name, description: decoy.description, parameters: decoy.parameters } }))];
        requestBody = { ...source, tools: chatTools, ...(callerTools.length ? {} : { tool_choice: 'none' }), stream: true };
      }

      const response = await fetchImpl(targetUrl, {
        method: 'POST',
        headers,
        body: JSON.stringify(requestBody),
        signal,
      });

      if (!response.ok) {
        const errorText = await response.text().catch(() => '');
        throw opencodeError(response.status, response.statusText, errorText, parseRetryAfter(response.headers?.get?.('retry-after')));
      }

      if (!isResponses) {
        if (wantsStream) {
          yield* translateChatStream(response);
          return;
        }
        yield* aggregate(translateChatStream(response));
        return;
      }

      if (wantsStream) {
        yield* translateResponsesStream(response);
        return;
      }
      yield* aggregate(translateResponsesStream(response));
    },

    async quota() {
      return { updatedAt: new Date().toISOString(), models: [], consumption: null };
    },
  };
}

/** The chat-completions branch, used by every non-`muse-spark` id. */
async function* translateChatStream(response) {
  for await (const event of sseEvents(response)) {
    if (!event.data || event.data === '[DONE]') continue;
    const data = parseJson(event.data);
    if (!data) continue;
    if (data.error) throw providerError(data?.error?.status || 502, true, data?.error?.message || null);
    const choice = data.choices?.[0];
    const reasoning = choice?.delta?.reasoning_content || choice?.delta?.reasoning || choice?.delta?.thought;
    if (choice?.delta && (choice.delta.content || choice.delta.tool_calls?.length || reasoning)) {
      yield { type: 'delta', delta: { ...choice.delta, ...(reasoning ? { reasoning_content: reasoning } : {}) } };
    }
    if (data.usage) yield { type: 'usage', usage: data.usage };
    if (choice?.finish_reason) yield { type: 'finish', finishReason: normalizeFinishReason(choice.finish_reason) };
  }
}
