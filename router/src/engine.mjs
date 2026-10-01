import { randomUUID } from 'node:crypto';
import { RouterError, assert, requestScopedClientError, safeError } from './errors.mjs';
import { normalizeUsage, reportedCost } from './usage.mjs';
import { costFromUsage } from './pricing.mjs';
import { RING_EXHAUSTED_MESSAGE } from './keyring.mjs';
import { logEvent } from './system-log.mjs';
import { LARGE_OUTPUT_TOKENS } from './request-budget.mjs';

export class RouterEngine {
  constructor({ service, deadlineMs = 90000, largeDeadlineMs = null }) { this.service = service; this.store = service.store; this.rotation = new Map(); this.keyRing = service.keyRing; this.deadlineMs = deadlineMs; this.largeDeadlineMs = largeDeadlineMs; }
  requestDeadline(body) {
    return body.max_tokens >= LARGE_OUTPUT_TOKENS && this.largeDeadlineMs !== null
      ? Math.max(this.deadlineMs, this.largeDeadlineMs) : this.deadlineMs;
  }
  selection(body, key) {
    let selected;
    if (body.aliasId) selected = { aliasId: body.aliasId };
    else if (body.providerId && (body.modelId || body.model)) selected = { providerId: body.providerId, modelId: body.modelId || body.model };
    else if (body.connectionId) selected = { connectionId: body.connectionId, modelId: body.modelId || body.model };
    else if (body.model) {
      const alias = this.store.list('alias').find(a => a.name === body.model);
      if (alias) selected = { aliasId: alias.id };
      else {
        const split = body.model.indexOf('/');
        assert(split > 0, 'Unknown model. Use an identifier returned by /v1/models.', 'MODEL_NOT_FOUND', 404);
        selected = { connectionId: body.model.slice(0, split), modelId: body.model.slice(split + 1) };
      }
    } else selected = this.store.getDefault();
    let targets; let alias = null;
    if (selected.providerId) {
      const config = this.service.providerConfig(selected.providerId);
      const rank = new Map(config.connectionOrder.map((id, index) => [id, index]));
      targets = this.store.list('connection')
        .filter(connection => connection.providerId === selected.providerId && this.service.validTarget({ connectionId: connection.id, modelId: selected.modelId }))
        .sort((a, b) => (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER))
        .map(connection => ({ connectionId: connection.id, modelId: selected.modelId }));
      if (config.roundRobin && targets.length) {
        const rotationKey = `provider:${selected.providerId}:${selected.modelId}`;
        const offset = (this.rotation.get(rotationKey) || 0) % targets.length;
        targets = [...targets.slice(offset), ...targets.slice(0, offset)];
        this.rotation.set(rotationKey, (offset + 1) % targets.length);
      }
    } else if (selected.aliasId) {
      alias = this.store.get('alias', selected.aliasId);
      assert(alias?.enabled, 'Alias is missing or disabled.', 'MODEL_NOT_FOUND', 404);
      targets = alias.targets.filter(t => this.service.validTarget(t));
      if (alias.strategy === 'round_robin' && targets.length) {
        const admitted = targets.filter(t => this.service.hasCallableKeys(t.connectionId));
        if (admitted.length) targets = admitted;
        const offset = this.rotation.get(alias.id) || 0;
        const start = offset % targets.length;
        targets = [...targets.slice(start), ...targets.slice(0, start)];
        this.rotation.set(alias.id, (offset + 1) % targets.length);
      }
    } else targets = [selected];
    const identifier = alias?.name || (selected.providerId ? `${selected.providerId}/${selected.modelId}` : `${selected.connectionId}/${selected.modelId}`);
    assert(!key || !key.allowedModels.length || key.allowedModels.includes(identifier), 'API key does not allow this model or alias.', 'POLICY_DENIED', 403);
    targets = targets.filter(t => this.service.validTarget(t));
    assert(targets.length, 'No enabled, authorized model is available for this route.', 'NO_ROUTE', 503);
    return { targets, alias, identifier };
  }
  async *generate(body, { key = null, signal } = {}) {
    assert(Array.isArray(body.messages) && body.messages.length > 0 && body.messages.length <= 200, 'Provide 1–200 chat messages.');
    assert(body.messages.every(m => m && ['system', 'user', 'assistant', 'tool', 'developer'].includes(m.role)), 'Invalid message role.');
    assert(body.messages.every(m => typeof m.content === 'string' || (m.role === 'assistant' && m.content == null && Array.isArray(m.tool_calls)) || (Array.isArray(m.content) && m.content.every(p => (p?.type === 'text' && typeof p.text === 'string') || (p?.type === 'image_url' && Boolean(p.image_url?.url))))), 'Invalid message content. Expected text, image_url, or tool_calls.');
    assert(body.stream === undefined || typeof body.stream === 'boolean', 'stream must be boolean.');
    assert(body.tools === undefined || (Array.isArray(body.tools) && body.tools.length <= 128 && body.tools.every(t => t.type === 'function' && typeof t.function?.name === 'string' && t.function.name.length <= 64)), 'Invalid tools.');
    assert(body.max_tokens === undefined || (Number.isInteger(body.max_tokens) && body.max_tokens > 0 && body.max_tokens <= 64000), 'max_tokens must be 1–64000.');
    const selection = this.selection(body, key);
    const requestId = randomUUID(); const began = Date.now();
    const controller = new AbortController();
    const deadline = AbortSignal.timeout(this.requestDeadline(body));
    const combined = AbortSignal.any([controller.signal, deadline, ...(signal ? [signal] : [])]);
    const record = { requestId, connectionId: null, modelId: null, keyId: null, keyLabel: null, aliasId: selection.alias?.id || null, clientKeyId: key?.id || null, status: 'failed', latencyMs: 0, inputTokens: null, cachedTokens: null, cacheCreationTokens: null, reasoningTokens: null, outputTokens: null, totalTokens: null, cost: null, costBasis: null, estimated: false, error: null };
    let lastError; let emitted = false; let succeeded = false; let outputBytes = 0; const reactiveRefresh = new Set();
    try {
      for (let targetIndex = 0; targetIndex < selection.targets.length; targetIndex++) {
        const target = selection.targets[targetIndex];
        combined.throwIfAborted();
        const connection = this.service.connection(target.connectionId);
        const model = connection.models.find(m => m.id === target.modelId);
        if (body.tools?.length && model.capabilities.tools === 'unsupported') { lastError = new RouterError('CAPABILITY', 'Selected model does not support tools.'); continue; }
        record.connectionId = connection.id; record.modelId = model.id;
        this.service.active.set(requestId, { connectionId: connection.id, controller });
        // Vòng khoá (vòng 29) lồng trong vòng target: mỗi lượt thử là MỘT khoá của
        // connection, theo thứ tự ring — khoá trên cùng chưa nghỉ được dùng trước.
        // Connection chưa có ring đi đúng đường hôm nay: một credential, không khoá.
        const keys = Array.isArray(connection.keys) ? connection.keys : [];
        while (true) {
          const picked = keys.length ? this.keyRing.pick(connection) : null;
          if (keys.length && !picked) {
            // Cả ring đang nghỉ ⇒ lượt này KHÔNG tốn một lần gọi provider nào. Lỗi
            // THẬT của provider đi ra nguyên vẹn (code/message/status/retryAfterMs);
            // câu tổng hợp chỉ dùng cho ca bất khả: ring nghỉ mà chưa từng có lỗi.
            lastError = this.keyRing.lastError(connection) || lastError || new RouterError('RATE_LIMIT', RING_EXHAUSTED_MESSAGE, 429, true);
            break;
          }
          const keyId = picked?.id ?? null;
          record.keyId = keyId; record.keyLabel = picked?.label ?? null;
          // Số token/chi phí là của LƯỢT THỬ này, không phải của target: một khoá có
          // thể kịp báo `usage` dở dang rồi mới 429, và lượt sau (khoá kế tiếp) không
          // được thừa hưởng số của nó.
          record.inputTokens = null; record.cachedTokens = null; record.cacheCreationTokens = null; record.reasoningTokens = null; record.outputTokens = null; record.totalTokens = null; record.cost = null; record.costBasis = null; record.estimated = false;
          try {
            const credentials = await this.service.credentials(connection.id, combined, keyId);
            const outgoing = { ...body, model: model.id, stream: body.stream !== false };
            delete outgoing.connectionId; delete outgoing.modelId; delete outgoing.aliasId;
            // BUG-4/R3: `thinkingType: 'none'` models get no thinking field at all,
            // even when the caller sends a stored default level the model cannot use.
            if (model.thinkingType === 'none') { delete outgoing.thinkingLevel; delete outgoing.reasoning_effort; }
            let started = false; let finishReason = null; let meaningful = false;
            let pendingUsage = null;
            const ensureStarted = () => ({ type: 'start', meta: { requestId, connectionId: connection.id, modelId: model.id, aliasId: selection.alias?.id || null } });
            for await (const event of this.service.providers[connection.providerId].generate({ connection, credentials, body: outgoing, signal: combined })) {
              combined.throwIfAborted();
              assert(this.service.validTarget(target), 'Connection or model disabled during request.', 'CANCELLED', 499);
              if (event.type === 'delta') {
                // BUG-2: a delta that carries only reasoning is still client output.
                const reasoning = typeof event.delta?.reasoning_content === 'string' ? event.delta.reasoning_content : event.delta?.reasoning;
                const useful = Boolean(event.delta?.content || event.delta?.tool_calls?.length || (typeof reasoning === 'string' && reasoning.length > 0));
                if (!useful) continue;
                outputBytes += Buffer.byteLength(JSON.stringify(event.delta));
                assert(outputBytes <= 8 * 1024 * 1024, 'Provider response exceeded the output limit.', 'OUTPUT_LIMIT', 502);
                if (!started) { yield ensureStarted(); started = true; }
                meaningful = true; emitted = true; yield event;
              } else if (event.type === 'finish') finishReason = event.finishReason || 'stop';
              else if (event.type === 'usage') {
                const usage = normalizeUsage(event.usage);
                record.inputTokens = usage.prompt_tokens;
                record.cachedTokens = usage.cached_tokens;
                record.cacheCreationTokens = usage.cache_creation_input_tokens;
                record.reasoningTokens = usage.reasoning_tokens;
                record.outputTokens = usage.completion_tokens;
                record.totalTokens = usage.total_tokens;
                // Ba tầng chi phí: số nhà cung cấp tự báo luôn thắng và được ghi
                // nguyên văn (`reported`); nếu không có, giá đã chốt trên dòng model
                // (tay / ping / documented) mới dùng để ƯỚC TÍNH, và bản ghi mang
                // theo nguồn (`costBasis`) + cờ `estimated`. Không có giá, hoặc
                // usage không có token nào, thì chi phí ở lại `null` — router không
                // bao giờ bịa ra một con số. Khung usage gửi cho client KHÔNG mang
                // số ước tính.
                const reported = reportedCost(usage);
                const price = reported === null ? this.service.priceFor(model, connection, new Date()) : null;
                const estimate = price ? costFromUsage({ usage, price }) : null;
                if (reported !== null) { record.cost = reported; record.costBasis = 'reported'; record.estimated = false; }
                else if (estimate) { record.cost = estimate.cost; record.costBasis = price.source; record.estimated = true; }
                else { record.cost = null; record.costBasis = null; record.estimated = false; }
                pendingUsage = { ...event, usage };
                if (started) { yield event; pendingUsage = null; }
              }
            }
            assert(meaningful && finishReason, 'Provider returned no complete response.', 'UNAVAILABLE', 502);
            if (pendingUsage) yield pendingUsage;
            const current = this.store.get('connection', connection.id);
            if (current && current.revision === connection.revision) {
              current.inferenceState = 'ready'; current.lastTestedAt = new Date().toISOString(); current.error = null;
              // `lastUsedAt` là thứ DUY NHẤT của ring được ghi bền, và nó đi kèm
              // chính lần ghi connection đã có sẵn ở đây — không thêm lần ghi DB nào.
              if (keyId && Array.isArray(current.keys)) {
                const used = current.keys.find(key => key.id === keyId);
                if (used) used.lastUsedAt = Date.now();
                current.activeKeyId = keyId;
              }
              this.store.put('connection', current);
            }
            if (keyId) this.keyRing.clear(keyId);
            record.status = 'passed'; succeeded = true;
            yield { type: 'finish', finishReason }; return;
          } catch (error) {
            const safe = combined.aborted ? safeError(combined.reason) : safeError(error);
            lastError = safe;
            const current = this.store.get('connection', connection.id);
            if (current && current.revision === connection.revision && !combined.aborted) {
              // A request-scoped 4xx (400 context overflow, 422 unsupported parameter, 403-like
              // policy on one input) says nothing about the credential, so it must not mark the
              // account failed or expire its auth: the same connection still serves the next
              // request (9Router `open-sse/services/accountFallback.js:48-60`).
              const isFatalConnection = (safe.code === 'AUTH' || safe.code === 'UNAVAILABLE' || safe.status === 502 || safe.status === 503 || safe.status === 504)
                && !requestScopedClientError(safe);
              if (isFatalConnection) {
                current.inferenceState = 'failed';
                current.error = safe.message;
                if (safe.code === 'AUTH') current.authState = 'expired';
                this.store.put('connection', current);
              }
            }
            // Chỉ một 429 mới đổi khoá trong cùng một request: park đúng khoá đó rồi
            // thử khoá kế tiếp theo thứ tự ring, khi chưa phát ra nội dung nào cho
            // client. Mọi lỗi khác (400 request-scoped, 5xx, AUTH) chỉ ghi lại "lần
            // thử gần nhất" của khoá và đi tiếp như hôm nay — không đổi khoá.
            if (safe.code === 'RATE_LIMIT') {
              if (keyId && !combined.aborted) {
                this.keyRing.park(keyId, { retryAfterMs: safe.retryAfterMs, error: safe, modelId: model.id });
                // Lượt xoay khoá không để lại dấu vết nào ngoài dòng usage: một dòng
                // log (không bao giờ có secret) để hỗ trợ đọc được "vì sao lượt này đổi
                // khoá, khoá nào bị bỏ qua". Ghi log là best-effort, không bao giờ ném.
                logEvent('router.key_parked', { requestId: record.requestId, provider: connection.providerId, model: model.id, code: safe.code, message: safe.message, keyId, keyLabel: record.keyLabel, retryAfterMs: safe.retryAfterMs ?? null });
              }
              try { await this.service.quota(connection.id, AbortSignal.timeout(5000)); } catch { /* inference error remains primary */ }
              if (keyId && !combined.aborted && !emitted && this.keyRing.pick(connection)) continue;
            } else if (keyId && !combined.aborted) this.keyRing.note(keyId, safe);
            if (!emitted && !combined.aborted && (safe.code === 'MODEL_NOT_FOUND' || safe.status === 404) && !reactiveRefresh.has(connection.id)) {
              reactiveRefresh.add(connection.id);
              try {
                await this.service.discover(connection.id, AbortSignal.any([combined, AbortSignal.timeout(60000)]));
                if (this.service.validTarget(target)) { continue; }
              } catch (refreshError) { lastError = safeError(refreshError); }
            }
            if (emitted || combined.aborted || !safe.retryable) throw safe;
            break;
          }
        }
      }
      throw lastError || new RouterError('NO_ROUTE', 'No usable route is available.', 503);
    } catch (error) {
      const safe = combined.aborted ? safeError(combined.reason) : safeError(error);
      record.status = safe.code === 'CANCELLED' ? 'cancelled' : 'failed'; record.error = safe.message;
      throw safe;
    } finally {
      if (!succeeded && !record.error) { record.status = 'cancelled'; record.error = 'Request cancelled.'; }
      controller.abort(new DOMException('Finished', 'AbortError'));
      this.service.active.delete(requestId); record.latencyMs = Date.now() - began; this.store.addUsage(record);
    }
  }
}
