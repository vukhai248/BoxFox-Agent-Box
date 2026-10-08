import http from 'node:http';
import { randomUUID } from 'node:crypto';
import { once } from 'node:events';
import { readFile, stat } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { assert, RouterError, safeError, errorEnvelope } from './errors.mjs';
import { logEvent, logFailure } from './system-log.mjs';
import {
  anthropicApply,
  anthropicError,
  anthropicFrame,
  anthropicMessageBody,
  anthropicToOpenAI,
  claudeCliHousekeeping,
  createAnthropicState,
  estimateInputTokens,
  housekeepingEvents,
} from './anthropic.mjs';

function json(res, status, value) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
  res.end(JSON.stringify(value));
}
async function body(req) {
  assert((req.headers['content-type'] || '').split(';')[0] === 'application/json', 'JSON content type required.', 'INVALID_REQUEST', 415);
  let size = 0; const chunks = [];
  for await (const chunk of req) { size += chunk.length; assert(size <= 1048576, 'Request is too large.', 'INVALID_REQUEST', 413); chunks.push(chunk); }
  try { const value = JSON.parse(Buffer.concat(chunks).toString('utf8')); assert(value && typeof value === 'object' && !Array.isArray(value), 'JSON object required.'); return value; }
  catch (e) { if (e instanceof RouterError) throw e; throw new RouterError('INVALID_REQUEST', 'Invalid JSON.'); }
}
const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon', '.woff2': 'font/woff2' };
/**
 * Thân request TUỲ CHỌN cho những đường POST mà mọi tham số đều có mặc định (ví dụ dò
 * reasoning: `{levels, samples}` đều bỏ trống được). `body()` đòi
 * `Content-Type: application/json` và trả 415 khi thiếu, nên dùng thẳng nó thì một nút
 * bấm không thân request sẽ bị chặn oan; đọc hết request để không treo keep-alive.
 */
async function optionalBody(req) {
  if (!req.headers['content-type']) { req.resume(); return {}; }
  return await body(req);
}
const STREAM_HEADERS = { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-store', 'Connection': 'keep-alive', 'X-Accel-Buffering': 'no' };
// OpenAI dialect: `data: {json}\n\n` frames terminated by `data: [DONE]`.
const openAIFrame = value => `data: ${typeof value === 'string' ? value : JSON.stringify(value)}\n\n`;
// Anthropic dialect: `event: <type>\ndata: {json}\n\n` frames, no terminator.
const anthropicFraming = value => (typeof value === 'string' ? value : anthropicFrame(value));
/** Loopback, link-local, or one of the private IPv4/IPv6 ranges — the only addresses the
 * sandbox bridge may bind. A LAN or public address would put the inference endpoints on
 * the corporate/office network, which is never what "let the box reach the router" means. */
function isPrivateAddress(value) {
  const host = String(value).trim().toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host === '::1') return true;
  if (host.startsWith('fe80:') || host.startsWith('fc') || host.startsWith('fd')) return true;
  const parts = host.split('.');
  if (parts.length !== 4 || parts.some(part => !/^\d{1,3}$/.test(part) || Number(part) > 255)) return false;
  const [first, second] = parts.map(Number);
  if (first === 127 || first === 10) return true;
  if (first === 192 && second === 168) return true;
  if (first === 172 && second >= 16 && second <= 31) return true;
  return false;
}

/** Advisory text for a legal-but-wider bridge host, or `null` for the container-style ranges the
 * bridge is meant for. The listener serves inference endpoints only (all key-gated) and never the
 * admin surface, so a wide range is a caution, not a refusal — but the operator should know that
 * every host on that network can now reach the router. */
export function bridgeExposureNote(value) {
  const host = String(value || '').trim().toLowerCase().replace(/^\[|\]$/g, '');
  if (host === 'localhost' || host === '::1' || host.startsWith('127.')) {
    return 'Loopback already serves the admin surface: the bridge cannot bind it. Use the container gateway address, for example 172.18.0.1.';
  }
  if (host.startsWith('10.') || host.startsWith('192.168.')) {
    return 'This is a general private network, not a container network: every host on it can reach the inference endpoints. Prefer the container gateway address, for example 172.18.0.1.';
  }
  return null;
}

export function createRouterServer({ service, engine, oauth, frontendDir = null, allowedOrigins = ['http://localhost:3100', 'http://127.0.0.1:3100'], allowedHosts = ['localhost:3100', '127.0.0.1:3100', 'localhost:3101', '127.0.0.1:3101'], bridgeHost = null }) {
  function admin(req) {
    assert(req.headers['x-boxfox-admin'] === '1', 'Local administration header required.', 'FORBIDDEN', 403);
    assert(!req.headers.origin || allowedOrigins.includes(req.headers.origin), 'Origin not allowed.', 'FORBIDDEN', 403);
    assert(!req.headers['sec-fetch-site'] || ['same-origin', 'same-site', 'none'].includes(req.headers['sec-fetch-site']), 'Cross-site administration is forbidden.', 'FORBIDDEN', 403);
  }
  /**
   * Client-disconnect cancellation, explicit SSE headers and back-pressure for
   * every streaming dialect, so a Stop reaches the provider mid-answer.
   */
  function liveStream(req, res, frame = openAIFrame) {
    const controller = new AbortController();
    const cancel = () => { if (!res.writableEnded) controller.abort(new DOMException('Client disconnected', 'AbortError')); };
    res.on('close', cancel); req.on('aborted', cancel);
    const write = async value => {
      if (controller.signal.aborted) throw controller.signal.reason;
      if (!res.headersSent) res.writeHead(200, STREAM_HEADERS);
      if (!res.write(frame(value))) await once(res, 'drain', { signal: controller.signal });
    };
    return { controller, write, release: () => { res.removeListener('close', cancel); req.removeListener('aborted', cancel); } };
  }
  async function generate(req, res, input, clientKey) {
    const { controller, write, release } = liveStream(req, res);
    let meta = null, content = '', reasoningContent = '', finishReason = null, usage = null; const toolCalls = new Map();
    const stream = input.stream === true;
    const started = Date.now();
    // The developer system log records every model request: what was asked, how long it
    // took, how it ended, and — on failure — the code and reason. Never agent-visible.
    const logChat = (event, fields = {}) => logEvent(event, {
      requestId: meta?.requestId, provider: meta?.provider || meta?.providerId, model: meta?.modelId,
      durationMs: Date.now() - started, stream, ...fields,
    });
    const chunk = (delta, reason = null, extra = {}) => ({ id: `chatcmpl-${meta.requestId}`, object: 'chat.completion.chunk', created: Math.floor(Date.now() / 1000), model: `${meta.connectionId}/${meta.modelId}`, choices: [{ index: 0, delta, finish_reason: reason }], ...extra });
    try {
      for await (const event of engine.generate(input, { key: clientKey, signal: controller.signal })) {
        if (event.type === 'start') { meta = event.meta; if (stream) await write(chunk({ role: 'assistant' }, null, { boxfox: meta })); }
        if (event.type === 'delta') {
          content += event.delta.content || '';
          // BUG-2: reasoning-only deltas are passed through, so the non-stream
          // response has to accumulate them into message.reasoning_content.
          const reasoning = event.delta.reasoning_content || event.delta.reasoning;
          if (typeof reasoning === 'string' && reasoning) reasoningContent += reasoning;
          for (const call of event.delta.tool_calls || []) {
            const index = call.index ?? 0, old = toolCalls.get(index) || { id: '', type: 'function', function: { name: '', arguments: '' } };
            if (call.id) old.id = call.id;
            if (call.function?.name) old.function.name += call.function.name;
            old.function.arguments += call.function?.arguments || '';
            const sig = call.thought_signature || call.thoughtSignature;
            if (sig) { old.thought_signature = sig; old.thoughtSignature = sig; }
            toolCalls.set(index, old);
          }
          if (stream) await write(chunk(event.delta));
        }
        if (event.type === 'usage') { usage = event.usage; if (stream) await write({ ...chunk({}, null), choices: [], usage }); }
        if (event.type === 'finish') { finishReason = event.finishReason; if (stream) await write(chunk({}, finishReason)); }
      }
      logChat('chat.end', {
        finishReason,
        inputTokens: usage?.prompt_tokens ?? usage?.input_tokens ?? null,
        outputTokens: usage?.completion_tokens ?? usage?.output_tokens ?? null,
        contentChars: content.length,
        reasoningChars: reasoningContent.length,
        toolCalls: toolCalls.size,
      });
      if (stream) { await write('[DONE]'); res.end(); }
      else json(res, 200, { id: `chatcmpl-${meta.requestId}`, object: 'chat.completion', created: Math.floor(Date.now() / 1000), model: `${meta.connectionId}/${meta.modelId}`, choices: [{ index: 0, message: { role: 'assistant', content: content || null, ...(reasoningContent ? { reasoning_content: reasoningContent } : {}), ...(toolCalls.size ? { tool_calls: [...toolCalls.values()] } : {}) }, finish_reason: finishReason }], usage, boxfox: meta });
    } catch (e) {
      if (controller.signal.aborted) {
        logChat('chat.aborted', { level: 'warn', message: 'client disconnected before the model finished', contentChars: content.length });
        return;
      }
      const safe = safeError(e);
      logFailure('chat.failed', e, {
        requestId: meta?.requestId, provider: meta?.provider || meta?.providerId, model: meta?.modelId,
        durationMs: Date.now() - started, stream, code: safe.code, httpStatus: safe.status,
        contentChars: content.length, toolCalls: toolCalls.size,
      });
      if (res.headersSent) {
        // The stream aborted after HTTP 200, so the status can no longer change: the error
        // has to travel in-band. The frame comes first, then the `[DONE]` terminator, so an
        // OpenAI-compatible client raises on the error frame instead of reading a body that
        // ended without a terminator as a finished answer, and never a fabricated
        // finish_reason (9Router `open-sse/utils/streamHelpers.js:128-158`).
        await write({ ...errorEnvelope(e), boxfox: meta }).catch(() => {});
        await write('[DONE]').catch(() => {});
        res.end();
      } else json(res, safe.status, errorEnvelope(e));
    } finally { release(); }
  }
  /**
   * Anthropic Messages ingress. The translation lives in anthropic.mjs; this owns
   * the HTTP concerns, which are deliberately the same as the OpenAI path: the
   * same key store, the same engine (so the same route resolution, allowlist and
   * 90 s deadline), client-disconnect cancellation and the developer system log.
   * `provider` yields engine events — the model pipeline, or the local answer to
   * a Claude Code housekeeping call.
   */
  async function anthropicMessages(req, res, { input, provider }) {
    const stream = input.stream === true;
    const started = Date.now();
    const messageId = `msg_${randomUUID().replace(/-/g, '').slice(0, 24)}`;
    const state = createAnthropicState({ id: messageId, model: input.model, inputTokens: estimateInputTokens(input) });
    const { controller, write, release } = liveStream(req, res, anthropicFraming);
    let meta = null;
    const logChat = (event, fields = {}) => logEvent(event, {
      requestId: meta?.requestId, provider: meta?.provider || meta?.providerId, model: meta?.modelId,
      messageId, durationMs: Date.now() - started, stream, ...fields,
    });
    try {
      // message_start leaves before the provider's usage is known; the response
      // header names the request for the client and for the system log.
      res.setHeader('request-id', messageId);
      for await (const event of provider(controller.signal)) {
        if (event.type === 'start') { meta = event.meta; continue; }
        for (const frame of anthropicApply(state, event)) if (stream) await write(frame);
      }
      logChat('anthropic.end', {
        stopReason: state.stopReason, inputTokens: state.inputTokens,
        contentChars: state.blocks.reduce((total, block) => total + block.text.length, 0),
        thinkingChars: state.blocks.reduce((total, block) => total + block.thinking.length, 0),
        toolCalls: state.toolCalls.size,
      });
      if (stream) { res.end(); return true; }
      json(res, 200, anthropicMessageBody(state));
      return true;
    } catch (e) {
      if (controller.signal.aborted) {
        logChat('anthropic.aborted', { level: 'warn', message: 'client disconnected before the model finished' });
        return false;
      }
      const safe = safeError(e);
      logFailure('anthropic.failed', e, {
        requestId: meta?.requestId, provider: meta?.provider || meta?.providerId, model: meta?.modelId,
        messageId, durationMs: Date.now() - started, stream, code: safe.code, httpStatus: safe.status,
      });
      const payload = anthropicError(safe);
      if (res.headersSent) { await write(anthropicFrame(payload)).catch(() => {}); res.end(); return false; }
      json(res, safe.status, payload);
      return false;
    } finally { release(); }
  }
  // 9Router's `extractApiKey` order: `Authorization: Bearer` first, then the
  // Anthropic `x-api-key` header, both against the same key store.
  function ingressKey(req) {
    const bearer = (req.headers.authorization || '').match(/^Bearer (.+)$/)?.[1];
    return service.store.authenticateKey(bearer) || service.store.authenticateKey(req.headers['x-api-key']);
  }
  /** `/v1/messages` and `/v1/messages/count_tokens`, every error Anthropic-shaped. */
  async function anthropicRoute(req, res, path, method) {
    try {
      assert(method === 'POST', 'Endpoint not found.', 'NOT_FOUND', 404);
      const key = ingressKey(req);
      assert(key, 'Valid BoxFox API key required.', 'AUTH', 401);
      const input = await body(req);
      if (path === '/v1/messages/count_tokens') {
        // The same 4-characters-per-token estimate the streaming usage falls back
        // to; no provider call, no routing, nothing invented.
        json(res, 200, { input_tokens: estimateInputTokens(input) });
        return;
      }
      const housekeeping = claudeCliHousekeeping(input, req.headers['user-agent']);
      if (housekeeping) {
        logEvent('anthropic.housekeeping', { kind: housekeeping.kind, stream: input.stream === true, userAgent: req.headers['user-agent'] });
        await anthropicMessages(req, res, { input, provider: () => housekeepingEvents(housekeeping) });
        return;
      }
      const translated = anthropicToOpenAI(input);
      await anthropicMessages(req, res, { input, provider: signal => engine.generate(translated, { key, signal }) });
    } catch (e) {
      const safe = safeError(e);
      logFailure('anthropic.request_rejected', e, { path, code: safe.code, httpStatus: safe.status });
      if (!res.headersSent && !res.destroyed) json(res, safe.status, anthropicError(safe));
      else res.end();
    }
  }
  const handler = async (req, res) => {
    try {
      assert(allowedHosts.includes(req.headers.host), 'Host not allowed.', 'FORBIDDEN', 403);
      const url = new URL(req.url, 'http://localhost'); const path = url.pathname; const method = req.method;
      if (path === '/api/router/health' && method === 'GET') return json(res, 200, { status: 'ok', version: '0.1.0' });
      if (path.startsWith('/api/router/') || path === '/v1/router/generate') admin(req);
      if (path === '/api/router/chat' && method === 'POST') {
        const input = await body(req);
        assert(Array.isArray(input.messages) && input.messages.length > 0, 'Router requires a non-empty messages array.');
        return await generate(req, res, input, null);
      }
      if (path === '/v1/router/generate' && method === 'POST') {
        const input = await body(req); assert(input.messages?.length === 1 && input.messages[0].role === 'user', 'Router Test accepts exactly one user message.');
        return await generate(req, res, input, null);
      }
      if (path === '/v1/models' || path === '/v1/chat/completions') {
        const key = service.store.authenticateKey((req.headers.authorization || '').match(/^Bearer (.+)$/)?.[1]);
        assert(key, 'Valid BoxFox API key required.', 'AUTH', 401);
        if (path === '/v1/models' && method === 'GET') return json(res, 200, { object: 'list', data: service.publicModels(key) });
        if (path === '/v1/chat/completions' && method === 'POST') return await generate(req, res, await body(req), key);
      }
      if (path === '/v1/messages' || path === '/v1/messages/count_tokens') return await anthropicRoute(req, res, path, method);
      if (path === '/api/router/state' && method === 'GET') return json(res, 200, service.snapshot());
      if (path === '/api/router/providers' && method === 'GET') return json(res, 200, service.snapshot().providers);
      const providerDetail = path.match(/^\/api\/router\/providers\/([^/]+)$/);
      if (providerDetail && method === 'GET') return json(res, 200, service.provider(decodeURIComponent(providerDetail[1])));
      if (providerDetail && method === 'PUT') return json(res, 200, service.setProviderConfig(decodeURIComponent(providerDetail[1]), await body(req)));
      // Web Search (PART 2): khoá API tìm kiếm nằm trong kho riêng của router, không
      // phải kho khoá mô hình. Mọi đường đi qua cổng admin chung ở trên và KHÔNG có
      // mặt trong BRIDGE_PATHS — sandbox không bao giờ chạm được kho này.
      const searchProvider = path.match(/^\/api\/router\/search\/providers(?:\/([^/]+)(?:\/(reveal|test))?)?$/);
      if (searchProvider) {
        const searchId = searchProvider[1] ? decodeURIComponent(searchProvider[1]) : null;
        const searchAction = searchProvider[2] || null;
        if (!searchId && method === 'POST') return json(res, 201, service.search.create(await body(req)));
        if (searchId && !searchAction && method === 'PATCH') return json(res, 200, service.search.patch(searchId, await body(req)));
        if (searchId && !searchAction && method === 'DELETE') { service.search.remove(searchId); return json(res, 200, { deleted: true }); }
        if (searchId && searchAction === 'reveal' && method === 'POST') return json(res, 200, service.search.reveal(searchId));
        if (searchId && searchAction === 'test' && method === 'POST') return json(res, 200, await service.search.probe(searchId));
      }
      if (path === '/api/router/search' && method === 'GET') return json(res, 200, service.search.snapshot());
      if (path === '/api/router/search/active' && method === 'PUT') {
        const active = await body(req);
        assert(active.providerId === null || typeof active.providerId === 'string', 'providerId must be a string or null.');
        return json(res, 200, service.search.setActive(active.providerId));
      }
      // Chỉ harness trong sandbox đọc đường này (qua loopback) để lấy khoá đang chọn;
      // giao diện không dùng nó — giao diện chỉ thấy `prefix`.
      if (path === '/api/router/search/resolve' && method === 'GET') return json(res, 200, service.search.resolve());
      // Vòng 29: danh sách connection đi qua `service.connections()` để mỗi dòng mang
      // theo `keys`/`activeKeyId` đã trang trí — cùng hình dạng với `GET /api/router/state`.
      if (path === '/api/router/connections' && method === 'GET') return json(res, 200, service.connections());
      if (path === '/api/router/connections' && method === 'POST') {
        const created = service.create(await body(req));
        // API providers can expose their inventory immediately. Keep the
        // connection durable when the upstream is temporarily unavailable so
        // the UI can show the discovery error and offer a retry.
        if (created.credentialPresent && created.providerId !== 'antigravity') {
          try { await service.discover(created.id, AbortSignal.timeout(30000)); } catch { /* surfaced on the connection */ }
        }
        return json(res, 201, service.connection(created.id));
      }
      const modelTest = path.match(/^\/api\/router\/connections\/([^/]+)\/models\/([^/]+)\/test$/);
      if (modelTest && method === 'POST') return json(res, 200, await service.testInference(decodeURIComponent(modelTest[1]), decodeURIComponent(modelTest[2]), AbortSignal.timeout(90000)));
      // M5 — đo REASONING của một model, ngay cạnh nhánh `test` ở trên (mọi `/api/router/*`
      // đã đi qua cổng admin ở đầu handler). Thân request tuỳ chọn `{levels, samples}`;
      // timeout 90 s cùng khuôn vì một lượt dò có thể chạy nhiều mẫu.
      const reasoningProbe = path.match(/^\/api\/router\/connections\/([^/]+)\/models\/([^/]+)\/reasoning-probe$/);
      if (reasoningProbe && method === 'POST') return json(res, 200, await service.probeReasoning(decodeURIComponent(reasoningProbe[1]), decodeURIComponent(reasoningProbe[2]), await optionalBody(req), AbortSignal.timeout(90000)));
      // M6 — xoá một hàng model GÕ TAY (`source: 'custom'`); hàng do dò phát hiện trả 409
      // `MODEL_NOT_CUSTOM` vì lần dò sau nó sẽ mọc lại y hệt.
      const modelRow = path.match(/^\/api\/router\/connections\/([^/]+)\/models\/([^/]+)$/);
      if (modelRow && method === 'DELETE') return json(res, 200, service.removeCustomModel(decodeURIComponent(modelRow[1]), decodeURIComponent(modelRow[2])));
      const connection = path.match(/^\/api\/router\/connections\/([^/]+)(?:\/(test|models\/refresh|quota|reveal))?$/);
      if (connection) {
        const id = decodeURIComponent(connection[1]);
        if (!connection[2] && method === 'PATCH') return json(res, 200, service.patch(id, await body(req)));
        if (!connection[2] && method === 'DELETE') { service.remove(id); return json(res, 200, { deleted: true }); }
        if (['test', 'models/refresh'].includes(connection[2]) && method === 'POST') return json(res, 200, await service.discover(id, AbortSignal.timeout(60000)));
        if (connection[2] === 'quota' && method === 'GET') return json(res, 200, await service.quota(id, AbortSignal.timeout(20000)));
        if (connection[2] === 'reveal' && (method === 'GET' || method === 'POST')) {
          const c = service.connection(id);
          const firstKeyId = c.keys?.[0]?.id ?? c.id;
          return json(res, 200, service.revealKey(id, firstKeyId));
        }
      }
      const connectionKeys = path.match(/^\/api\/router\/connections\/([^/]+)\/keys(?:\/([^/]+))?(?:\/(try|reveal))?$/);
      if (connectionKeys) {
        // Năm đường dẫn khoá của hợp đồng vòng 29 (tên do nửa UI chốt, không đổi):
        // `POST .../keys` (201), `PATCH`/`DELETE .../keys/:keyId` (200),
        // `POST .../keys/:keyId/try` (200 { connection, probe }), `POST .../keys/import` (200).
        // Thêm `GET/POST .../keys/:keyId/reveal` (200 { id, key }) để phục vụ nút xem/copy key.
        // Nhánh `import` phải đọc TRƯỚC nhánh `:keyId`, nếu không chữ "import" bị nuốt
        // làm key id và route import biến thành một khoá tên "import".
        const id = decodeURIComponent(connectionKeys[1]);
        const keyId = connectionKeys[2] ? decodeURIComponent(connectionKeys[2]) : null;
        if (keyId === 'import' && !path.endsWith('/try') && !path.endsWith('/reveal') && method === 'POST') return json(res, 200, service.importKeys(id, (await body(req)).fromConnectionId));
        if (!keyId && method === 'POST') return json(res, 201, service.addKey(id, await body(req)));
        if (keyId && method === 'PATCH') return json(res, 200, service.replaceKey(id, keyId, await body(req)));
        if (keyId && method === 'DELETE') return json(res, 200, service.removeKey(id, keyId));
        if (keyId && path.endsWith('/try') && method === 'POST') return json(res, 200, await service.tryKey(id, keyId, await body(req)));
        if (keyId && path.endsWith('/reveal') && (method === 'GET' || method === 'POST')) return json(res, 200, service.revealKey(id, keyId));
      }
      if ((path === '/callback' || path === '/auth/callback') && method === 'GET') return await oauth.handleHttpCallback(req, res);
      if (path === '/api/router/oauth/attempts' && method === 'POST') return json(res, 201, await oauth.start((await body(req)).connectionId));
      const attemptCallback = path.match(/^\/api\/router\/oauth\/attempts\/([^/]+)\/callback$/);
      if (attemptCallback && method === 'POST') {
        const payload = await body(req);
        return json(res, 200, await oauth.manualCallback(attemptCallback[1], payload.callbackUrl || payload.code));
      }
      const attempt = path.match(/^\/api\/router\/oauth\/attempts\/([^/]+)$/);
      if (attempt && method === 'GET') return json(res, 200, oauth.get(attempt[1]));
      if (attempt && method === 'DELETE') return json(res, 200, oauth.cancel(attempt[1]));
      if (path === '/api/router/aliases' && method === 'POST') return json(res, 201, service.alias(await body(req)));
      const alias = path.match(/^\/api\/router\/aliases\/([^/]+)$/);
      if (alias && method === 'PATCH') return json(res, 200, service.alias(await body(req), alias[1]));
      if (alias && method === 'DELETE') { service.store.delete('alias', alias[1]); service.repairDefault(); return json(res, 200, { deleted: true }); }
      if (path === '/api/router/default' && method === 'PUT') return json(res, 200, service.setDefault(await body(req)));
      if (path === '/api/router/keys' && method === 'GET') return json(res, 200, service.store.list('key').map(k => service.store.publicKey(k)));
      if (path === '/api/router/keys' && method === 'POST') {
        const value = await body(req); assert(typeof value.name === 'string' && value.name.trim().length > 0 && value.name.length <= 120, 'Key name required.');
        const allowed = value.allowedModels ?? []; assert(Array.isArray(allowed) && allowed.length <= 200 && allowed.every(m => typeof m === 'string' && service.publicModels(null).some(x => x.id === m)), 'Allowlist must contain enabled model IDs or aliases.');
        return json(res, 201, service.store.addKey(value.name.trim(), [...new Set(allowed)]));
      }
      const key = path.match(/^\/api\/router\/keys\/([^/]+)$/);
      if (key && method === 'DELETE') { const record = service.store.get('key', key[1]); assert(record, 'Key not found.', 'NOT_FOUND', 404); record.enabled = false; service.store.put('key', record); return json(res, 200, { revoked: true }); }
      if (path === '/api/router/usage' && method === 'GET') return json(res, 200, service.store.list('usage').slice(0, 200));
      if (frontendDir && method === 'GET' && !path.startsWith('/api/') && !path.startsWith('/v1/')) {
        const root = resolve(frontendDir), file = resolve(root, `.${decodeURIComponent(path)}`); assert(file === root || file.startsWith(root + sep), 'Invalid path.');
        let target = file; try { if (!(await stat(target)).isFile()) target = resolve(root, 'index.html'); } catch { target = resolve(root, 'index.html'); }
        const data = await readFile(target); res.writeHead(200, { 'Content-Type': `${mime[extname(target)] || 'application/octet-stream'}; charset=utf-8`, 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer' }); return res.end(data);
      }
      throw new RouterError('NOT_FOUND', 'Endpoint not found.', 404);
    } catch (e) { if (!res.headersSent && !res.destroyed) json(res, safeError(e).status, errorEnvelope(e)); else res.end(); }
  };
  // The sandbox can reach the router only through the docker bridge gateway. When the
  // owner opts in (`BOXFOX_ROUTER_BRIDGE_HOST`, e.g. 172.18.0.1) a second listener serves
  // the INFERENCE endpoints on that single address — never the administration surface:
  // the agent inside the box is exactly the client the bridge is opened for, and it must
  // not be able to read the router state, mint or revoke keys, edit connections or call
  // the admin generator (`/v1/router/generate`, which bypasses a key's model allow-list).
  const BRIDGE_PATHS = new Set(['/v1/models', '/v1/chat/completions', '/v1/messages', '/v1/messages/count_tokens']);
  const bridgeHandler = async (req, res) => {
    const path = String(req.url || '/').split('?')[0];
    if (!BRIDGE_PATHS.has(path)) {
      logEvent('router.bridge_denied', {
        level: 'warn', code: 'NOT_FOUND', path, method: req.method,
        message: 'The sandbox bridge serves inference endpoints only.',
      });
      return json(res, 404, { error: { code: 'NOT_FOUND', message: 'The sandbox bridge serves inference endpoints only.', retryable: false } });
    }
    return handler(req, res);
  };
  const server = http.createServer(handler);
  server.requestTimeout = 110000; server.headersTimeout = 10000;
  if (bridgeHost) {
    assert(isPrivateAddress(bridgeHost), 'Bridge host must be a private or loopback address.', 'INVALID_REQUEST', 400);
    server.bridge = http.createServer(bridgeHandler);
    server.bridge.requestTimeout = server.requestTimeout; server.bridge.headersTimeout = server.headersTimeout;
    server.bridge.on('error', error => logFailure('router.bridge_failed', error, { host: bridgeHost }));
  }
  return server;
}
