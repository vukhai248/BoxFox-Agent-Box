// Search providers — khoá API tìm kiếm do người dùng nhập (tab "Web Search" của
// Settings → Provider).
//
// Bề mặt Provider của Settings vốn chỉ có khoá MÔ HÌNH. Tab mới mượn đúng cơ chế
// lưu khoá đã có (bảng `credentials`, AES-256-GCM, AAD = row id của dòng) qua hai
// kind MỚI, nên đường suy luận mô hình không bị chạm tới:
//
//   search_provider  — id = providerId; body KHÔNG BAO GIỜ chứa khoá thô;
//   search_config    — id = 'default'; { activeProviderId, revision, updatedAt };
//   credentials      — row id = `search:<providerId>`, value = { apiKey }.
//
// Khoá thô chỉ rời router qua `reveal()` (nút Hiện của giao diện) và `resolve()`
// (harness đọc qua loopback) — mọi đường khác chỉ thấy `prefix`: sáu ký tự đầu
// kèm `…`, đúng quy ước `headOf()` của keyring.mjs. Mọi thao tác ghi đều đẩy
// `revision` lên 1, để cache 15 giây phía harness biết mình phải đọc lại.
import { assert, safeError, RouterError } from './errors.mjs';
import { createSafeFetch, validateEndpoint } from './network.mjs';
import { headOf } from './keyring.mjs';

/**
 * Catalog 8 nhà cung cấp, ĐÚNG thứ tự hiển thị của giao diện. Đây là nguồn sự
 * thật duy nhất: `requires`/`optional` quyết định trường nào được nhận và trường
 * nào bắt buộc, `envKeys` nói biến môi trường tương ứng của đường cũ (deployment
 * hiện hữu không phải đổi gì), `icon` là tên file trong `frontend/public/providers/`.
 */
export const SEARCH_PROVIDER_CATALOG = [
  { id: 'brave',      name: 'Brave Search',           requires: ['apiKey'],              optional: [],         envKeys: ['BRAVE_API_KEY', 'BOXFOX_BRAVE_API_KEY'], icon: 'brave-search' },
  { id: 'tavily',     name: 'Tavily',                 requires: ['apiKey'],              optional: [],         envKeys: ['TAVILY_API_KEY'],   icon: 'tavily' },
  { id: 'exa',        name: 'Exa',                    requires: ['apiKey'],              optional: [],         envKeys: ['EXA_API_KEY'],      icon: 'exa' },
  { id: 'parallel',   name: 'Parallel',               requires: ['apiKey'],              optional: [],         envKeys: ['PARALLEL_API_KEY'], icon: null },
  { id: 'firecrawl',  name: 'Firecrawl',              requires: ['apiKey'],              optional: [],         envKeys: ['FIRECRAWL_API_KEY'], icon: 'firecrawl' },
  { id: 'searxng',    name: 'SearXNG (self-hosted)',  requires: ['endpoint'],            optional: [],         envKeys: ['BOXFOX_SEARXNG_URL'], icon: 'searxng' },
  { id: 'cloudflare', name: 'Cloudflare Web Search',  requires: ['accountId', 'apiKey'], optional: [],         envKeys: [],                   icon: 'cloudflare-ai' },
  { id: 'custom',     name: 'Custom search endpoint', requires: ['endpoint'],            optional: ['apiKey'], envKeys: [],                   icon: 'custom' },
];

/** Id theo đúng thứ tự catalog — dùng cho test hợp đồng và cho giao diện. */
export const SEARCH_PROVIDER_IDS = SEARCH_PROVIDER_CATALOG.map(provider => provider.id);

const PROVIDER_BY_ID = new Map(SEARCH_PROVIDER_CATALOG.map(provider => [provider.id, provider]));
const ACCOUNT_ID_RE = /^[A-Za-z0-9_-]{1,64}$/;
const MAX_SECRET_LENGTH = 32768;
const REQUIRED_LABELS = { apiKey: 'API key', endpoint: 'endpoint URL', accountId: 'account ID' };

/** Truy vấn thử của nút "Kiểm tra" — cố định, nhỏ, không lấy từ người dùng. */
const PROBE_QUERY = 'boxfox search test';
const PROBE_TIMEOUT_MS = 15000;

/**
 * Endpoint thật của từng nhà cung cấp. `probe` đọc biến ghi đè
 * `BOXFOX_<PROVIDER>_SEARCH_URL` trước (hook test/E2E, không phải API người dùng);
 * `{account_id}` của Cloudflare được thay bằng account id đã lưu.
 */
const REAL_ENDPOINTS = {
  brave: 'https://api.search.brave.com/res/v1/web/search',
  tavily: 'https://api.tavily.com/search',
  exa: 'https://api.exa.ai/search',
  parallel: 'https://api.parallel.ai/v1beta/search',
  firecrawl: 'https://api.firecrawl.dev/v1/search',
  cloudflare: 'https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/websearch/',
};
const OVERRIDE_ENV = {
  brave: 'BOXFOX_BRAVE_SEARCH_URL',
  tavily: 'BOXFOX_TAVILY_SEARCH_URL',
  exa: 'BOXFOX_EXA_SEARCH_URL',
  parallel: 'BOXFOX_PARALLEL_SEARCH_URL',
  firecrawl: 'BOXFOX_FIRECRAWL_SEARCH_URL',
  cloudflare: 'BOXFOX_CLOUDFLARE_SEARCH_URL',
  custom: 'BOXFOX_CUSTOM_SEARCH_URL',
};

const nowIso = () => new Date().toISOString();
const rowId = providerId => `search:${providerId}`;
function envValue(name) {
  const value = (process.env[name] || '').trim();
  return value || null;
}
/** Câu lỗi nhà cung cấp tự nói trong payload (nếu có) — không bao giờ là request của ta. */
function providerMessage(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const candidates = [payload.error?.message, payload.message, payload.detail, payload.errors?.[0]?.message];
  const found = candidates.find(value => typeof value === 'string' && value.trim());
  return found ? found.trim() : null;
}
/**
 * Kết quả đầu tiên trong payload, chuẩn hoá về `{ title, url }` — "một mẫu kết quả"
 * của nút Kiểm tra. Mỗi nhà cung cấp trả một hình dạng khác nhau (Brave:
 * `web.results`; Firecrawl: `data`; Cloudflare: `result.items`; custom:
 * `results` hoặc `items`), nên đọc lần lượt các vị trí đã biết thay vì đoán.
 */
function firstSample(payload) {
  if (!payload || typeof payload !== 'object') return null;
  const lists = [
    payload.web?.results,
    payload.results,
    payload.items,
    payload.data?.web,
    payload.data?.results,
    payload.data,
    payload.result?.items,
    payload.result?.results,
  ];
  for (const list of lists) {
    if (!Array.isArray(list)) continue;
    const hit = list.find(item => item && typeof item === 'object' && (item.url || item.link));
    if (hit) return { title: String(hit.title ?? hit.name ?? hit.url ?? ''), url: String(hit.url ?? hit.link ?? '') };
  }
  return null;
}
/** Mã lỗi của một phép thử nhận HTTP status: 401/403 là khoá, 429 là hạn mức, còn lại là hạ tầng. */
function verdictFor(status) {
  if (status === 401 || status === 403) return 'AUTH';
  if (status === 429) return 'RATE_LIMIT';
  return 'UNAVAILABLE';
}

export class SearchService {
  constructor({ store, fetchImpl = null } = {}) {
    assert(store, 'SearchService requires a store.');
    this.store = store;
    // `createSafeFetch()` chặn metadata/link-local và ghim địa chỉ đã phân giải —
    // cùng đường mạng mọi adapter dùng. Test truyền `fetchImpl` giả qua ProviderService.
    this.fetchImpl = typeof fetchImpl === 'function' ? fetchImpl : createSafeFetch();
  }

  /** `{ activeProviderId, revision, providers: [view] }` — đúng khối `search` của `/api/router/state`. */
  snapshot() {
    const config = this.#config();
    return {
      activeProviderId: this.#activeId(config),
      revision: config.revision,
      providers: SEARCH_PROVIDER_CATALOG.map(provider => this.#view(provider.id)),
    };
  }

  /** Tạo mục mới; 409 nếu mục đã có, 400 CREDENTIAL_REQUIRED nếu thiếu trường bắt buộc. */
  create(values = {}) {
    const provider = this.#provider(values.providerId);
    assert(!this.#record(provider.id), `${provider.name} is already configured.`, 'ALREADY_CONFIGURED', 409);
    const fields = this.#fields(provider, values);
    this.#assertRequired(provider, { hasSecret: Boolean(fields.apiKey), endpoint: fields.endpoint || '', accountId: fields.accountId || '' });
    const timestamp = Date.now();
    const record = {
      id: provider.id,
      endpoint: fields.endpoint || null,
      accountId: fields.accountId || null,
      credentialPresent: Boolean(fields.apiKey) || Boolean(fields.endpoint),
      hasSecret: Boolean(fields.apiKey),
      prefix: headOf(fields.apiKey),
      createdAt: timestamp,
      updatedAt: timestamp,
      lastTestedAt: null,
      lastTest: null,
    };
    if (fields.apiKey) this.store.saveCredentials(rowId(provider.id), { apiKey: fields.apiKey });
    this.store.put('search_provider', record);
    this.#bump();
    return this.#view(provider.id);
  }

  /**
   * Sửa mục đã có; 404 nếu chưa cấu hình. `apiKey: ""` XOÁ khoá của mục — nhưng nếu
   * sau phép sửa mà thiếu trường bắt buộc (khoá của Brave, endpoint của SearXNG,
   * account id của Cloudflare) thì trả 400 và KHÔNG ghi gì.
   */
  patch(id, values = {}) {
    const provider = this.#provider(id);
    const current = this.#record(provider.id);
    assert(current, `${provider.name} is not configured.`, 'NOT_FOUND', 404);
    const fields = this.#fields(provider, values);
    const next = { ...current };
    if ('endpoint' in fields) next.endpoint = fields.endpoint || null;
    if ('accountId' in fields) next.accountId = fields.accountId || null;
    if ('apiKey' in fields) { next.hasSecret = Boolean(fields.apiKey); next.prefix = headOf(fields.apiKey); }
    // Kiểm tra trên HÌNH DẠNG KẾT QUẢ trước khi ghi: một PATCH hỏng không được để
    // lại dòng credential đã bị xoá nhưng bản ghi vẫn khai là còn khoá.
    this.#assertRequired(provider, { hasSecret: Boolean(next.hasSecret), endpoint: next.endpoint || '', accountId: next.accountId || '' });
    next.credentialPresent = Boolean(next.hasSecret) || Boolean(next.endpoint);
    next.updatedAt = Date.now();
    if ('apiKey' in fields) {
      if (fields.apiKey) this.store.saveCredentials(rowId(provider.id), { apiKey: fields.apiKey });
      else this.store.removeCredentials(rowId(provider.id));
    }
    this.store.put('search_provider', next);
    this.#bump();
    return this.#view(provider.id);
  }

  /** Xoá mục và dòng credential của nó; đang là mục được chọn ⇒ quay về "Mặc định". */
  remove(id) {
    const provider = this.#provider(id);
    const record = this.#record(provider.id);
    assert(record, `${provider.name} is not configured.`, 'NOT_FOUND', 404);
    this.store.removeCredentials(rowId(provider.id));
    this.store.delete('search_provider', provider.id);
    this.#bump(this.#config().activeProviderId === provider.id ? null : undefined);
  }

  /** `null` = "Mặc định" (đường built-in); mục chưa cấu hình không chọn được (404). */
  setActive(providerId) {
    if (providerId === null) {
      const config = this.#bump(null);
      return { activeProviderId: null, revision: config.revision };
    }
    const provider = this.#provider(providerId);
    assert(this.#record(provider.id), `${provider.name} is not configured yet.`, 'NOT_FOUND', 404);
    const config = this.#bump(provider.id);
    return { activeProviderId: config.activeProviderId, revision: config.revision };
  }

  /** Khoá thô của một mục — chỉ đường `POST .../reveal` gọi hàm này. Mục không khoá ⇒ `''`. */
  reveal(id) {
    const provider = this.#provider(id);
    assert(this.#record(provider.id), `${provider.name} is not configured.`, 'NOT_FOUND', 404);
    const credential = this.#credential(provider.id);
    return { id: provider.id, key: typeof credential?.apiKey === 'string' ? credential.apiKey : '' };
  }

  /** `{ revision, active }` — hợp đồng đọc của harness qua loopback (task 3 của PART 2). */
  resolve() {
    const config = this.#config();
    const activeId = this.#activeId(config);
    if (!activeId) return { revision: config.revision, active: null };
    const record = this.#record(activeId);
    const credential = this.#credential(activeId);
    return {
      revision: config.revision,
      active: {
        id: activeId,
        apiKey: typeof credential?.apiKey === 'string' ? credential.apiKey : '',
        accountId: record.accountId ?? null,
        endpoint: record.endpoint ?? null,
      },
    };
  }

  /**
   * Gọi thử một truy vấn nhỏ tới endpoint thật của mục, ghi `lastTest`/`lastTestedAt`
   * rồi trả `{ ok, providerId, status, latencyMs, code, message, sample }`. Mọi thất
   * bại MẠNG trả `ok:false` + `code` chứ không ném ra ngoài — nút Kiểm tra phải luôn
   * có câu trả lời; chỉ mục chưa cấu hình mới là 404.
   */
  async probe(id, { signal } = {}) {
    const provider = this.#provider(id);
    const record = this.#record(provider.id);
    assert(record, `${provider.name} is not configured.`, 'NOT_FOUND', 404);
    const started = Date.now();
    let result;
    try {
      result = await this.#runProbe(provider, record, signal);
    } catch (error) {
      const safe = safeError(error);
      result = { ok: false, status: null, code: safe.code, message: safe.message, sample: null };
    }
    const latencyMs = Date.now() - started;
    const outcome = {
      ok: result.ok,
      providerId: provider.id,
      status: result.status,
      latencyMs,
      code: result.code,
      message: result.message,
      sample: result.sample,
    };
    const current = this.#record(provider.id);
    if (current) {
      current.lastTestedAt = nowIso();
      current.lastTest = { status: outcome.ok ? 'passed' : 'failed', httpStatus: outcome.status, latencyMs, code: outcome.code, message: outcome.message };
      current.updatedAt = Date.now();
      this.store.put('search_provider', current);
      this.#bump();
    }
    return outcome;
  }

  // ── Nội bộ ─────────────────────────────────────────────────────────────────
  /** Hình dạng của một mục: catalog (nguồn sự thật) + phần đã lưu. Không có khoá thô. */
  #view(providerId) {
    const provider = PROVIDER_BY_ID.get(providerId);
    const record = this.#record(providerId);
    const hasSecret = Boolean(record?.hasSecret);
    return {
      id: provider.id,
      name: provider.name,
      requires: [...provider.requires],
      optional: [...provider.optional],
      envKeys: [...provider.envKeys],
      icon: provider.icon,
      credentialPresent: Boolean(record?.credentialPresent),
      hasSecret,
      prefix: hasSecret ? (record?.prefix ?? null) : null,
      endpoint: record?.endpoint ?? null,
      accountId: record?.accountId ?? null,
      lastTestedAt: record?.lastTestedAt ?? null,
      lastTest: record?.lastTest ?? null,
    };
  }
  #provider(value) {
    assert(typeof value === 'string' && value.length > 0, 'providerId must be a string.', 'INVALID_REQUEST', 400);
    const provider = PROVIDER_BY_ID.get(value);
    assert(provider, 'Unknown search provider.', 'NOT_FOUND', 404);
    return provider;
  }
  #record(providerId) { return this.store.get('search_provider', providerId); }
  /** Dòng credential hỏng (đổi master key, file bị sửa) không được hạ cả tab Settings. */
  #credential(providerId) {
    try { return this.store.credentials(rowId(providerId)); } catch { return null; }
  }
  #config() {
    return this.store.get('search_config', 'default') || { id: 'default', activeProviderId: null, revision: 0, updatedAt: null };
  }
  /** Mục đang chọn chỉ có hiệu lực khi bản ghi của nó còn — id mồ côi coi như "Mặc định". */
  #activeId(config) {
    const id = config.activeProviderId;
    return id && this.#record(id) ? id : null;
  }
  /**
   * Ghi `search_config` và tăng `revision` — mọi thao tác ghi của dịch vụ đi qua
   * đây. `activeProviderId`: `undefined` giữ nguyên lựa chọn, `null` về "Mặc định",
   * một id là chọn mục đó.
   */
  #bump(activeProviderId) {
    const current = this.#config();
    const next = {
      id: 'default',
      activeProviderId: activeProviderId === undefined ? current.activeProviderId : activeProviderId,
      revision: current.revision + 1,
      updatedAt: nowIso(),
    };
    this.store.put('search_config', next);
    return next;
  }
  /**
   * Đọc và kiểm tra các trường được phép gửi lên. Chỉ trường catalog khai báo mới
   * được nhận; `endpoint` đi qua `validateEndpoint()` (chỉ http/https, không
   * userinfo/query/fragment, chặn metadata/link-local); `apiKey` là chuỗi ≤ 32768
   * ký tự, chuỗi rỗng nghĩa là XOÁ khoá (patch) / thiếu khoá (create).
   */
  #fields(provider, values) {
    assert(values && typeof values === 'object' && !Array.isArray(values), 'JSON object required.', 'INVALID_REQUEST', 400);
    const declared = new Set([...provider.requires, ...provider.optional]);
    const fields = {};
    if (values.endpoint !== undefined && declared.has('endpoint')) {
      assert(typeof values.endpoint === 'string', 'Endpoint must be text.', 'INVALID_REQUEST', 400);
      const text = values.endpoint.trim();
      if (text) {
        // `validateEndpoint()` dùng chung với connection: nó ném `INVALID_REQUEST` cho
        // query/userinfo nhưng `INVALID_ENDPOINT` cho URL không phân tích được. Giao
        // diện chỉ có một nhánh cho trường endpoint, nên quy về MỘT mã ở đây.
        try { fields.endpoint = validateEndpoint(text); }
        catch (error) { throw new RouterError('INVALID_ENDPOINT', safeError(error).message, 400); }
      } else fields.endpoint = '';
    }
    if (values.accountId !== undefined && declared.has('accountId')) {
      assert(typeof values.accountId === 'string', 'Account id must be text.', 'INVALID_REQUEST', 400);
      const text = values.accountId.trim();
      assert(text === '' || ACCOUNT_ID_RE.test(text), 'Account id must be 1–64 letters, numbers, underscores or hyphens.', 'INVALID_REQUEST', 400);
      fields.accountId = text;
    }
    if (values.apiKey !== undefined && declared.has('apiKey')) {
      assert(typeof values.apiKey === 'string', 'API key must be text.', 'INVALID_REQUEST', 400);
      assert(values.apiKey.length <= MAX_SECRET_LENGTH, 'API key is too long.', 'INVALID_REQUEST', 400);
      fields.apiKey = values.apiKey.trim();
    }
    return fields;
  }
  #assertRequired(provider, { hasSecret, endpoint, accountId }) {
    const missing = provider.requires.filter(field => {
      if (field === 'apiKey') return !hasSecret;
      if (field === 'endpoint') return !endpoint;
      if (field === 'accountId') return !accountId;
      return true;
    });
    assert(
      missing.length === 0,
      `${missing.map(field => REQUIRED_LABELS[field] || field).join(' and ')} ${missing.length > 1 ? 'are' : 'is'} required for ${provider.name}.`,
      'CREDENTIAL_REQUIRED',
      400,
    );
  }
  /** Yêu cầu HTTP của một phép thử, theo hình dạng thật của từng nhà cung cấp. */
  #probeRequest(provider, record) {
    const key = this.#credential(provider.id)?.apiKey ?? '';
    const override = OVERRIDE_ENV[provider.id] ? envValue(OVERRIDE_ENV[provider.id]) : null;
    const bearer = key ? { Authorization: `Bearer ${key}` } : {};
    switch (provider.id) {
      case 'brave': {
        const url = new URL(override || REAL_ENDPOINTS.brave);
        url.searchParams.set('q', PROBE_QUERY);
        url.searchParams.set('count', '1');
        return { method: 'GET', url: url.toString(), headers: { Accept: 'application/json', ...(key ? { 'X-Subscription-Token': key } : {}) } };
      }
      case 'tavily':
        return { method: 'POST', url: override || REAL_ENDPOINTS.tavily, headers: { 'Content-Type': 'application/json', ...bearer }, body: { query: PROBE_QUERY, max_results: 1 } };
      case 'exa':
        return { method: 'POST', url: override || REAL_ENDPOINTS.exa, headers: { 'Content-Type': 'application/json', ...(key ? { 'x-api-key': key } : {}) }, body: { query: PROBE_QUERY, numResults: 1 } };
      case 'parallel':
        return { method: 'POST', url: override || REAL_ENDPOINTS.parallel, headers: { 'Content-Type': 'application/json', ...(key ? { 'x-api-key': key } : {}) }, body: { objective: PROBE_QUERY, max_results: 1 } };
      case 'firecrawl':
        return { method: 'POST', url: override || REAL_ENDPOINTS.firecrawl, headers: { 'Content-Type': 'application/json', ...bearer }, body: { query: PROBE_QUERY, limit: 1 } };
      case 'searxng': {
        const url = new URL(`${String(record.endpoint || '').replace(/\/+$/, '')}/search`);
        url.searchParams.set('q', PROBE_QUERY);
        url.searchParams.set('format', 'json');
        return { method: 'GET', url: url.toString(), headers: { Accept: 'application/json' } };
      }
      case 'cloudflare': {
        const url = (override || REAL_ENDPOINTS.cloudflare).replace('{account_id}', encodeURIComponent(record.accountId || ''));
        return { method: 'POST', url, headers: { 'Content-Type': 'application/json', ...bearer }, body: { query: PROBE_QUERY, provider: 'ceramic', limit: 1, options: { gateway: { id: 'default' } } } };
      }
      case 'custom':
        return { method: 'POST', url: record.endpoint || override, headers: { 'Content-Type': 'application/json', ...bearer }, body: { query: PROBE_QUERY } };
      default:
        throw new RouterError('INVALID_REQUEST', 'Unknown search provider.', 400);
    }
  }
  async #runProbe(provider, record, signal) {
    const request = this.#probeRequest(provider, record);
    const timeout = AbortSignal.timeout(PROBE_TIMEOUT_MS);
    const response = await this.fetchImpl(request.url, {
      method: request.method,
      headers: request.headers,
      ...(request.body === undefined ? {} : { body: JSON.stringify(request.body) }),
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    });
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch { payload = null; }
    if (!response.ok) {
      return { ok: false, status: response.status, code: verdictFor(response.status), message: providerMessage(payload) || `The provider refused the test request (HTTP ${response.status}).`, sample: null };
    }
    if (text && payload === null) {
      return { ok: false, status: response.status, code: 'UNAVAILABLE', message: 'The provider returned a response that is not JSON.', sample: null };
    }
    if (payload && typeof payload === 'object' && payload.success === false) {
      return { ok: false, status: response.status, code: 'UNAVAILABLE', message: providerMessage(payload) || 'The provider answered with success: false.', sample: null };
    }
    return { ok: true, status: response.status, code: null, message: null, sample: firstSample(payload) };
  }
}
