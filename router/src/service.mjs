import { randomUUID } from 'node:crypto';
import { RouterError, assert, safeError } from './errors.mjs';
import { validateEndpoint } from './network.mjs';
import { PROVIDER_CATALOG, PROVIDER_ENDPOINTS } from './catalog.mjs';
import { normalizePrice } from './pricing.mjs';
import { isAntigravityModelValid } from './providers/antigravity-models.mjs';
import { EFFORT_LEVELS, modelThinking } from './providers/common.mjs';
import { MAX_KEYS_PER_CONNECTION, KeyRing, headOf } from './keyring.mjs';
import { SearchService } from './search.mjs';
export { PROVIDER_CATALOG };

/** Provider gọi được mà không cần khoá (OpenCode Free: `Authorization: Bearer public`). */
function anonymousProvider(provider) {
  return Boolean(provider && (provider.id === 'opencode' || provider.authModes?.includes('anonymous')));
}
/**
 * Dòng `credentials` mà một thao tác GHI phải nhắm tới: khoá đầu của ring, hoặc
 * chính dòng của connection khi connection chưa có ring. Sau khi gộp khoá, id
 * connection có thể không còn thuộc ring của nó nữa, nên mọi chỗ ghi phải đi qua
 * đây — ghi vào một dòng mồ côi là làm khoá "biến mất" một cách im lặng.
 */
export function credentialRowId(c) {
  return c?.keys?.[0]?.id ?? c?.id ?? null;
}
function label(value, fallback) {
  assert(value === undefined || typeof value === 'string', 'Name must be text.');
  const text = (value ?? fallback).trim();
  assert(text.length > 0 && text.length <= 120, 'Name must be 1–120 characters.');
  return text;
}
function secret(value) { assert(typeof value === 'string' && value.trim().length > 0 && value.length <= 32768, 'Enter a valid API key.'); return value.trim(); }
function projectId(value) {
  if (value === null || value === '') return null;
  assert(typeof value === 'string' && /^[a-z][a-z0-9-]{4,62}$/.test(value), 'Enter a valid Google Cloud project ID.');
  return value;
}
function probeHealth(error) {
  const safe = safeError(error);
  if (safe.code === 'MODEL_NOT_FOUND' || safe.status === 404) return 'unavailable';
  if (safe.code === 'RATE_LIMIT' || safe.status === 429) return 'rate_limited';
  if (safe.code === 'TIMEOUT' || safe.code === 'CAPACITY' || safe.status === 504) return 'slow';
  return 'failed';
}
/** Id model người dùng gõ tay được lưu nguyên văn: chỉ chặn ký tự điều khiển và độ dài. */
const MODEL_ID_CONTROL_CHARS = /[\u0000-\u001f\u007f]/;
const MODEL_ID_MAX_LENGTH = 191;
/**
 * Cách tính tiền của một connection, suy từ catalog: provider dùng API key thì
 * tính theo token (`metered`), còn lại là tài khoản bao trọn gói (`included`).
 * `custom` luôn là `metered` vì đó là endpoint người dùng tự khai. Trường này chỉ
 * quyết định nhãn chi phí ở giao diện — tài khoản bao trọn gói không bao giờ được
 * ghi $0.
 */
function costModeFor(providerId) {
  if (providerId === 'custom') return 'metered';
  const provider = PROVIDER_CATALOG.find(entry => entry.id === providerId);
  return provider?.authMethod === 'api_key' ? 'metered' : 'included';
}
/**
 * 404 khi probe một id gõ tay là câu trả lời cho "tôi gõ tên có đúng không".
 * Router gửi id nguyên văn — không thêm, không bớt, không đổi dấu — nên thông báo
 * nói rõ điều đó, rồi nối thêm phần nhà cung cấp tự nói khi họ có nói gì.
 */
function unrecognisedModelId(modelId, message) {
  const base = `The endpoint did not recognise this model id. The router sends the id exactly as typed: ${modelId}`;
  const detail = typeof message === 'string' ? message.trim() : '';
  return detail ? `${base} — ${detail}` : base;
}
/**
 * Mức thinking công bố cho một model khai tay (người dùng tự nhập id). Adapter
 * nào tài liệu hoá bộ mức riêng của nhà cung cấp thì bộ đó được dùng — DeepSeek
 * công bố `none|low|high|max`, còn bộ mặc định `auto|low|medium|high` giữ nguyên
 * cho mọi nhà cung cấp khác. Nhờ vậy hàng khai tay khớp hàng do ping phát hiện và
 * không đổi giá trị sau khi chuẩn hoá lại.
 */
function manualThinkingLevels(provider) {
  const levels = typeof provider?.manualThinkingLevels === 'function' ? provider.manualThinkingLevels() : null;
  return Array.isArray(levels) && levels.length > 0 ? [...levels] : ['auto', 'low', 'medium', 'high'];
}
/**
 * Giá của một dòng model sau một lần dò thành công. Thứ tự đã chốt:
 *
 *   `manual` (người dùng tự đặt trên chính dòng đó) > `ping` (giá provider vừa
 *   công bố trong `/models`) > `documented` (bảng của adapter, ví dụ DeepSeek).
 *
 * Giá `manual` KHÔNG BAO GIỜ bị lần dò sau ghi đè; `ping` đứng trên `documented`
 * vì đó là giá provider vừa công bố tại thời điểm gọi. Một dòng đã có giá mà lần
 * dò này không mang giá nào thì giữ nguyên con số cũ — xoá đi là mất thông tin
 * người dùng đã có. `at` là thời điểm dò, để adapter tra đúng mùa giá của mình.
 */
function modelPrice({ previous, found, provider, at }) {
  if (previous?.pricing?.source === 'manual') return previous.pricing;
  if (found?.pricing) return found.pricing;
  const documented = typeof provider?.documentedPricing === 'function' ? provider.documentedPricing(found, at) : null;
  return documented ?? previous?.pricing ?? null;
}
/**
 * M3 — số đo reasoning của CHÍNH router (`thinkingProbe`) sống qua mọi lần dò danh
 * sách. `thinkingProbe` là một phép ĐO trên một model, không phải kết quả dò; lần dò
 * sau chỉ mang `id/object/created/owned_by` từ `/models` nên nếu không giữ lại, một
 * cú "Refresh models" sẽ xoá mất kết quả vừa đo và hàng quay về `unknown` — đúng
 * vòng lặp người dùng báo ("chưa hiện thinking với model mới").
 *
 * Chỉ payload provider tự khai thinking (`thinkingSource: 'live'`) mới thắng số đo:
 * đó là nguồn mạnh hơn, đến thẳng từ provider tại thời điểm gọi. Hàng curated cũng
 * không được ghi đè — bảng curated là ảnh chụp, số đo là thực nghiệm.
 */
function preservedThinkingProbe(before, incoming) {
  if (before?.thinkingSource !== 'probe' || !before?.thinkingProbe) return null;
  if (incoming?.thinkingSource === 'live') return null;
  return {
    thinkingType: before.thinkingType,
    thinkingLevels: Array.isArray(before.thinkingLevels) ? before.thinkingLevels : [],
    defaultThinking: before.defaultThinking ?? null,
    thinkingSource: 'probe',
    thinkingAsOf: before.thinkingAsOf ?? null,
    thinkingEvidence: before.thinkingEvidence ?? null,
    thinkingStale: before.thinkingStale === true,
    thinkingProbe: before.thinkingProbe,
    fieldSources: { ...(before.fieldSources || {}), ...(incoming?.fieldSources || {}), thinking: 'probe' },
  };
}
/**
 * M6 — vì sao một model thiếu. Ba câu trả lời KHÁC NHAU và phải phân biệt được:
 *  * `not_in_catalogue` — nhà cung cấp không phục vụ id này cho bất kỳ ai (gõ sai
 *    chính tả, hoặc model đã bị rút khỏi catalogue);
 *  * `not_entitled` — id CÓ trong catalogue công khai nhưng tài khoản/khoá này không
 *    được cấp (đúng ca `exo-free`);
 *  * `null` — chưa tra được catalogue (offline/429). Không được đoán: "chưa biết" là
 *    một câu trả lời, còn "đoán bừa" thì gửi người dùng đi sai hướng.
 */
function catalogueReason(publicCatalogue) {
  if (publicCatalogue === true) return 'not_entitled';
  if (publicCatalogue === false) return 'not_in_catalogue';
  return null;
}
function missingModelMessage(modelId, publicCatalogue) {
  const base = 'This model is not on the connection. Add the model id first, then test it.';
  const reason = catalogueReason(publicCatalogue);
  if (reason === 'not_entitled') return `${base} The provider lists ${modelId} in its public catalogue, but this account's credential is not entitled to it (not_entitled).`;
  if (reason === 'not_in_catalogue') return `${base} The provider's public catalogue does not list ${modelId} either (not_in_catalogue) — check the spelling, or the model may have been withdrawn.`;
  return `${base} The public catalogue could not be checked, so the router cannot say whether the id exists anywhere.`;
}
/**
 * M1 — câu hỏi dò reasoning. Một câu hỏi có bước suy luận thật (đếm rồi trả lời)
 * thay vì một câu chào: model không reasoning vẫn trả lời được câu chào, còn câu này
 * buộc phải có bước trung gian mới ra đáp án, nên "có reasoning" là kết luận ĐO được.
 * Đo trên Zen 2026-10-08: prompt này làm cả họ chat lẫn họ responses stream suy luận.
 */
const REASONING_PROBE_PROMPT = 'A farmer has 17 sheep and all but 9 run away. How many are left? Think step by step, then answer in one line.';
/** Trần số mẫu một lượt dò: đủ rộng cho 4 mức + mẫu không mức, vẫn có trần. */
const REASONING_PROBE_MAX_SAMPLES = 12;
/** `max_tokens` tối thiểu: 64 token của `testInference` không đủ chỗ cho văn suy luận. */
const REASONING_PROBE_MAX_TOKENS = 512;
/**
 * Mức KHÔNG phải mức: `none`/`auto` bị adapter tự bỏ (`normalizeOpencodeReasoning`),
 * nên gửi chúng chỉ tạo ra một bản sao của mẫu "không gửi mức" và làm bảng kết quả
 * hiểu sai rằng mức đó đã được đo.
 */
const REASONING_PROBE_SKIPPED_LEVELS = new Set(['none', 'auto']);
/** Trường reasoning xuất hiện trong câu lỗi 400/422 ⇒ đáng thử cách viết còn lại. */
const REASONING_FIELD_RE = /reasoning|thinking|effort/i;

/**
 * Bí mật không được đi vào câu trả lời hay hàng model. Câu lỗi của provider là văn bản
 * do bên ngoài viết: nó có thể echo lại chính header `Authorization` mà router vừa gửi.
 * Hàng đã lưu là hàng đọc được ở UI và trong log, nên cắt bí mật ngay tại nguồn.
 */
function redactSecrets(text, secrets = []) {
  let out = typeof text === 'string' ? text : '';
  for (const value of secrets) {
    if (typeof value === 'string' && value.length >= 8 && out.includes(value)) out = out.split(value).join('[redacted]');
  }
  return out;
}
/** Khoảng giá trị của một tín hiệu đo được, dạng `min–max`, hoặc `null` khi mọi mẫu bằng 0. */
function measuredRange(values) {
  const numbers = values.filter(value => Number.isFinite(value) && value > 0);
  if (!numbers.length) return null;
  const min = Math.min(...numbers);
  const max = Math.max(...numbers);
  return min === max ? `${min}` : `${min}–${max}`;
}
/** Câu lỗi của provider khi nó nói "id này không tồn tại" (401 kèm câu này = không được cấp). */
const REASONING_PROBE_MISSING_MODEL_RE = /not supported|not found|unknown model|does not exist|no such model|invalid model|unsupported model/i;
/**
 * M2 — luật phán xử của một lượt dò reasoning. Hàm THUẦN: chỉ đọc các mẫu đã đo, để
 * luật này test được mà không cần mạng.
 *
 * Nguyên tắc khắt khe nhất nằm ở đây: **một mẫu rỗng chưa chứng minh được gì**. Đo
 * được `fledge-alpha-free` có mẫu stream 0 ký tự dù model này reasoning thật, nên
 * "không thấy suy luận" chỉ là `inconclusive` — kết luận `none` từ nó là sai theo
 * hướng tệ nhất (xoá mất một điều khiển thật của người dùng). Chỉ một lời TỪ CHỐI
 * trường reasoning (400/422 nhắc tới `reasoning`/`thinking`/`effort`) mới là bằng
 * chứng âm, và phải có ít nhất 2 mẫu trước khi kết luận.
 */
export function judgeReasoningProbe(observations = []) {
  const samples = observations.length;
  const levelsTried = [...new Set(observations.map(sample => sample.level).filter(level => typeof level === 'string'))];
  const reasoned = observations.filter(sample => sample.reasoningChars > 0 || sample.reasoningTokens > 0);
  if (reasoned.length) {
    return {
      status: 'supports',
      levelsTried,
      levelsSupported: [...new Set(reasoned.map(sample => sample.level).filter(level => typeof level === 'string'))],
    };
  }
  const errors = observations.filter(sample => sample.error);
  if (samples > 0 && errors.length === samples) {
    const first = errors[0];
    const shared = { levelsTried, levelsSupported: [], httpStatus: first.httpStatus ?? null, message: first.message ?? null };
    if (first.httpStatus === 429 || first.code === 'RATE_LIMIT') return { ...shared, status: 'rate_limited', httpStatus: 429, retryAfterMs: first.retryAfterMs ?? null };
    if (first.httpStatus === 404 || first.code === 'MODEL_NOT_FOUND') return { ...shared, status: 'not_entitled', httpStatus: 404 };
    if (first.httpStatus === 401 && REASONING_PROBE_MISSING_MODEL_RE.test(first.message || '')) return { ...shared, status: 'not_entitled', httpStatus: 401 };
    if (first.httpStatus === 503 || first.httpStatus === 502 || first.httpStatus === 504 || first.httpStatus === 500 || first.code === 'TIMEOUT' || first.code === 'CAPACITY') {
      return { ...shared, status: 'unavailable' };
    }
    return { ...shared, status: 'failed' };
  }
  const refused = observations.filter(sample => sample.refusedReasoningField);
  if (refused.length && samples >= 2) return { status: 'refuses', levelsTried, levelsSupported: [] };
  return { status: 'inconclusive', levelsTried, levelsSupported: [] };
}
/**
 * M3 — phần hàng model được GHI sau một lượt dò, hoặc `null` khi không được ghi gì.
 *
 * Ba luật: (1) chỉ `supports`/`refuses` mới ghi — `inconclusive` giữ `unknown` và chỉ
 * để lại khối `thinkingProbe`; (2) hàng đang `thinkingSource: 'live'` (payload provider
 * tự khai) là nguồn MẠNH HƠN số đo, không bị đè; (3) mức chỉ được ghi khi chính mức đó
 * đã sinh reasoning — không suy ra "chắc là nhận" từ việc model reasoning ở mức khác.
 */
export function reasoningProbeRowPatch(row, { verdict, evidence, at }) {
  if (verdict.status !== 'supports' && verdict.status !== 'refuses') return null;
  if (row?.thinkingSource === 'live' || row?.fieldSources?.thinking === 'live') return null;
  const levels = verdict.status === 'supports' ? verdict.levelsSupported : [];
  return {
    // `effort` khi có ít nhất một mức đo được; model chỉ reasoning ở mẫu "không gửi
    // mức" thì trung thực là `none` + không mức — không có điều khiển nào để chọn.
    thinkingType: levels.length ? 'effort' : 'none',
    thinkingLevels: levels,
    defaultThinking: null,
    thinkingSource: 'probe',
    thinkingAsOf: at,
    thinkingEvidence: evidence,
    thinkingStale: false,
    fieldSources: { ...(row?.fieldSources || {}), thinking: 'probe' },
  };
}
/** Câu bằng chứng đi kèm hàng model, dạng người đọc được, dựng từ chính các mẫu đã đo. */
function reasoningProbeEvidence({ verdict, observations, at }) {
  // Chỉ hai kết luận ghi được lên hàng (`supports`/`refuses` — xem `reasoningProbeRowPatch`) mới
  // có câu bằng chứng để nói. Kết luận khác (`inconclusive`/`rate_limited`/…) đã có khối
  // `thinkingProbe` trên hàng và dòng phụ trên UI nói lại từ `status` + `samples`; dựng một câu
  // rồi để nó bị bỏ đi chỉ tạo chỗ trôi thứ hai.
  if (verdict.status !== 'supports' && verdict.status !== 'refuses') return null;
  const date = typeof at === 'string' ? at : new Date(at).toISOString().slice(0, 10);
  const reasoned = observations.filter(sample => sample.reasoningChars > 0 || sample.reasoningTokens > 0);
  const chars = measuredRange(reasoned.map(sample => sample.reasoningChars));
  const tokens = measuredRange(reasoned.map(sample => sample.reasoningTokens));
  const parts = [];
  if (verdict.status === 'supports') {
    parts.push(`${reasoned.length}/${observations.length} mẫu trả reasoning`);
    if (chars) parts.push(`reasoning_content ${chars} ký tự`);
    parts.push(tokens ? `reasoning_tokens ${tokens}` : 'reasoning_tokens không khai');
    parts.push(verdict.levelsSupported.length ? `mức đo được: ${verdict.levelsSupported.join('/')}` : 'chỉ reasoning mặc định (không mức nào đo được)');
  } else {
    const status = observations.find(sample => sample.refusedReasoningField)?.httpStatus ?? 400;
    parts.push(`${observations.length} mẫu, cả hai cách viết trường reasoning đều bị từ chối (${status})`);
  }
  return `probe ${date}: ${parts.join(', ')}`;
}
/** Ngày hôm nay, dạng `YYYY-MM-DD` — mốc `asOf` của giá người dùng tự đặt. */
function today() {
  return new Date().toISOString().slice(0, 10);
}
/** Một cửa sổ ngữ cảnh hợp lệ (số nguyên dương) hoặc `null`. */
function positiveWindow(value) {
  return Number.isInteger(value) && value > 0 ? value : null;
}
/**
 * Số nhà cung cấp đã công bố cho một dòng model — payload, luật của adapter, hoặc
 * số đã ghi lại trước đó trong `contextWindowReported`.
 *
 * Dòng đang giữ một lời khai tay thì chính `contextWindow` là số người dùng nhập,
 * nên nó không được coi là số nhà cung cấp: adapter "echo" số đó lại (deepseek,
 * openai) không biến nó thành lời của nhà cung cấp — chỉ `contextWindowReported`
 * mới nói được nhà cung cấp đã nói gì. Nhờ vậy `clear` trả dòng về đúng số nhà
 * cung cấp thay vì dựng lại chính số vừa xoá dưới nhãn `reported`.
 */
function providerPublishedWindow(model = {}, fromProvider = null) {
  const recorded = positiveWindow(model?.contextWindowReported);
  if (recorded !== null) return recorded;
  const inUse = positiveWindow(model?.contextWindow);
  const rule = positiveWindow(fromProvider?.contextWindow);
  const source = model?.contextWindowSource ?? null;
  if (source === 'documented' || source === 'manual') {
    // Số đang dùng đến từ bảng tên/người dùng; chỉ nhận luật adapter khi nó
    // thật sự khác số đang dùng (nếu không, đó chỉ là bản echo của chính nó).
    return rule !== null && rule !== inUse ? rule : null;
  }
  return rule ?? inUse;
}

export class ProviderService {
  constructor({ store, providers, fetchImpl = null }) {
    this.store = store;
    this.providers = providers;
    // PART 2: khoá tìm kiếm là một kho độc lập với kho khoá mô hình — cùng bảng
    // `credentials` đã mã hoá nhưng không đi qua `connection`/key ring/định tuyến.
    this.search = new SearchService({ store: this.store, fetchImpl });
    this.refreshes = new Map();
    this.discoveries = new Map();
    // M6: kết quả tra catalogue công khai (`Bearer public`) của một provider, cache theo
    // (provider, ngày) — CHỈ để trả lời "vì sao thiếu model", chỉ gọi ở nhánh lỗi, và
    // không bao giờ ghi xuống hàng model nào. Chỉ trong RAM: restart là tra lại, vì một
    // danh sách miễn phí có thể đổi bất cứ lúc nào.
    this.catalogueChecks = new Map();
    this.active = new Map();
    // Vòng 29: trạng thái nghỉ của từng khoá sống ở đây và được dùng CHUNG với
    // engine (`engine.keyRing` là chính đối tượng này), nên snapshot và vòng xoay
    // không bao giờ nhìn thấy hai sự thật khác nhau. Chỉ trong RAM: restart là mọi
    // khoá về vòng xoay ngay — đúng ý đồ với cửa sổ nghỉ 30 s–2 phút.
    this.keyRing = new KeyRing();
    this.sanitizeAllConnections();
  }
  sanitizeConnection(c) {
    if (!c) return c;
    let modified = false;
    // Connection đọc từ store cũ tự lành ở đây: mốc thời gian của lần dò cuối và
    // cách tính tiền được suy ra một lần rồi lưu lại, để giao diện hiện được
    // "Last attempt: <giờ>" và không bao giờ trình bày tài khoản bao trọn gói như
    // một hoá đơn $0.
    if (c.lastDiscoveryAttemptAt !== null && !Number.isFinite(c.lastDiscoveryAttemptAt)) { c.lastDiscoveryAttemptAt = null; modified = true; }
    if (c.costMode !== 'metered' && c.costMode !== 'included') { c.costMode = costModeFor(c.providerId); modified = true; }
    if (c.providerId === 'antigravity') {
      if (Array.isArray(c.models)) {
        const originalCount = c.models.length;
        c.models = c.models.filter(m => isAntigravityModelValid(m.id));
        if (c.models.length !== originalCount) modified = true;
      }
      if (c.quota && Array.isArray(c.quota.models)) {
        const originalQuotaCount = c.quota.models.length;
        c.quota.models = c.quota.models.filter(m => isAntigravityModelValid(m.modelId));
        if (c.quota.models.length !== originalQuotaCount) modified = true;
      }
    }
    if (Array.isArray(c.models)) {
      const provider = this.providers[c.providerId];
      for (const m of c.models) {
        // Giá hỏng/thiếu nguồn trong store cũ bị xoá tại đây thay vì để giao
        // diện hiện một con số vô nghĩa; router chỉ tin giá đã qua `normalizePrice`.
        if (m.pricing !== undefined && m.pricing !== null && normalizePrice(m.pricing) === null) {
          delete m.pricing;
          modified = true;
        }
        // BUG-4/R2: every stored model record carries contextWindow,
        // thinkingType and defaultThinking. The context window itself is decided
        // by the shipped name table (`context-window.mjs`) and the provider's own
        // number travels beside it: an adapter may re-derive metadata from
        // provider rules, a row the user declared keeps its number, and an
        // unknown row keeps what the payload said (or null — never a guess).
        const fromProvider = typeof provider?.thinkingMetadata === 'function' ? provider.thinkingMetadata(m) : null;
        // Vòng soát 2 (F2) — adapter bổ sung có thể khai provenance cho trường nó vừa vá
        // (`thinkingSource`/`thinkingAsOf`/`fieldSources`); `modelThinking` không mang các
        // khoá này nên phải ghim riêng, nếu không hàng vá xong vẫn tự nhận là dữ liệu live.
        if (fromProvider?.thinkingSource && m.thinkingSource !== fromProvider.thinkingSource) {
          m.thinkingSource = fromProvider.thinkingSource;
          if (fromProvider.thinkingAsOf) m.thinkingAsOf = fromProvider.thinkingAsOf;
          if (fromProvider.thinkingEvidence) m.thinkingEvidence = fromProvider.thinkingEvidence;
          m.fieldSources = { ...(m.fieldSources || {}), ...(fromProvider.fieldSources || {}) };
          modified = true;
        }
        // M4: `thinkingStale` là kết luận của adapter (mốc bằng chứng đã quá hạn), không
        // phải giá trị của hàng — `modelThinking` không mang khoá này nên phải ghim riêng,
        // nếu không cờ quá hạn chỉ sống trong RAM và mất sau lần khởi động lại.
        if (typeof fromProvider?.thinkingStale === 'boolean' && m.thinkingStale !== fromProvider.thinkingStale) {
          m.thinkingStale = fromProvider.thinkingStale;
          modified = true;
        }
        const manualNumber = m.contextWindowSource === 'manual' ? m.contextWindow : null;
        const normalized = modelThinking({
          ...m,
          ...(fromProvider || {}),
          declaredContextWindow: manualNumber,
          reportedContextWindow: providerPublishedWindow(m, fromProvider),
        });
        const levels = Array.isArray(m.thinkingLevels) ? m.thinkingLevels.join(',') : null;
        if (
          m.contextWindow !== normalized.contextWindow ||
          m.contextWindowSource !== normalized.contextWindowSource ||
          m.contextWindowReported !== normalized.contextWindowReported ||
          m.thinkingType !== normalized.thinkingType ||
          m.defaultThinking !== normalized.defaultThinking ||
          levels !== normalized.thinkingLevels.join(',')
        ) {
          Object.assign(m, normalized);
          modified = true;
        }
      }
    }
    if (modified) {
      this.store.put('connection', c);
    }
    // Vòng 29: ring được dựng một lần, chỉ thêm, idempotent.
    this.ensureRing(c);
    return c;
  }
  /**
   * Di trú ring cho connection cũ. Chỉ thêm, một lần, idempotent:
   *
   *   1. Đã có `keys` ⇒ không làm gì — kể cả ring RỖNG: connection đã chuyển hết
   *      khoá đi vẫn phải giữ nguyên mảng rỗng của nó (`keys` vắng nghĩa là
   *      "connection chưa từng có khoá", nhánh legacy của giao diện).
   *   2. Chưa từng có dòng credential (ví dụ một `opencode` không khoá) ⇒ KHÔNG
   *      tạo ring rỗng.
   *   3. Còn lại: dòng credential đang có trở thành khoá đầu tiên, và `id` của
   *      entry CHÍNH LÀ id dòng đó. Không có thao tác mật mã nào ở đây: AAD của
   *      bản mã là id DÒNG chứ không phải id connection (`store.mjs:44`).
   */
  ensureRing(c) {
    if (!c) return c;
    if (Array.isArray(c.keys)) {
      if (c.activeKeyId && !c.keys.some(key => key.id === c.activeKeyId)) { delete c.activeKeyId; this.store.put('connection', c); }
      return c;
    }
    // Đọc blob có thể NÉM (auth tag hỏng, dòng bị cắt, master key đổi) — và đây là
    // đường ĐỌC của mọi connection (`/state`, `GET /connections`, chi tiết provider,
    // PATCH, DELETE), nên một dòng hỏng không được phép hạ cả trang Settings: không
    // dựng được ring thì trả về đúng nhánh legacy (giao diện vẫn vẽ được, và vẫn xoá
    // được connection đó).
    let blob;
    try { blob = this.store.credentials(c.id); } catch { return c; }
    if (!blob) return c;
    c.keys = [{ id: c.id, label: c.name || 'Key 1', prefix: headOf(blob.apiKey || blob.accessToken), createdAt: Date.now(), lastUsedAt: null }];
    this.store.put('connection', c);
    return c;
  }
  sanitizeAllConnections() {
    try {
      const list = this.store.list('connection');
      for (const c of list) {
        this.sanitizeConnection(c);
      }
    } catch { /* best effort on startup */ }
  }
  connection(id) { const c = this.store.get('connection', id); assert(c, 'Connection not found.', 'NOT_FOUND', 404); return this.ensureRing(c); }
  provider(id) { const provider = PROVIDER_CATALOG.find(value => value.id === id); assert(provider, 'Provider not found.', 'NOT_FOUND', 404); return { ...provider, connections: this.connections().filter(value => value.providerId === id) }; }
  /** Mọi connection đã trang trí ring — nguồn chung cho `/state`, `GET /connections` và chi tiết provider. */
  connections() { return this.store.list('connection').map(c => this.#ringView(c)); }
  /**
   * `keys` chỉ có mặt khi connection thật sự có ring (hoặc đã từng có — ring
   * rỗng cũng là một mảng). Vắng `keys` là nhánh legacy của giao diện, nên ở đó
   * hàm này KHÔNG được thêm một mảng rỗng vào.
   */
  #ringView(c) {
    this.ensureRing(c);
    return Array.isArray(c.keys) ? { ...c, ...this.keyRing.state(c, Date.now()) } : { ...c };
  }
  snapshot() {
    return { providers: PROVIDER_CATALOG, connections: this.connections(), providerConfigs: this.store.list('provider_config'), aliases: this.store.list('alias'), defaultRoute: this.store.getDefault(), keys: this.store.list('key').map(k => this.store.publicKey(k)), usage: this.store.list('usage').slice(0, 200), search: this.search.snapshot(), health: { status: 'ok', version: '0.1.0' } };
  }
  providerConfig(id) {
    this.provider(id);
    return this.store.get('provider_config', id) || { id, roundRobin: false, connectionOrder: [] };
  }
  setProviderConfig(id, values) {
    const current = this.providerConfig(id);
    const connections = this.store.list('connection').filter(connection => connection.providerId === id);
    const connectionIds = new Set(connections.map(connection => connection.id));
    const roundRobin = values.roundRobin ?? current.roundRobin;
    assert(typeof roundRobin === 'boolean', 'Round robin must be boolean.');
    const requested = values.connectionOrder ?? current.connectionOrder;
    assert(Array.isArray(requested) && requested.every(value => typeof value === 'string' && connectionIds.has(value)) && new Set(requested).size === requested.length, 'Connection order contains an invalid account.');
    const connectionOrder = [...requested, ...connections.map(connection => connection.id).filter(value => !requested.includes(value))];
    return this.store.put('provider_config', { id, roundRobin, connectionOrder });
  }
  create(values) {
    const provider = PROVIDER_CATALOG.find(p => p.id === values.providerId);
    assert(provider && this.providers[provider.id], 'Unsupported provider.');
    assert(provider.runtimeAvailable && this.providers[provider.id], `The ${provider.name} adapter is not integrated yet.`, 'ADAPTER_REQUIRED', 501);
    const isOAuth = provider.authMethod === 'oauth' || ['antigravity', 'agy', 'codex', 'claude', 'github', 'cline'].includes(provider.id);
    const isAnonymous = provider.id === 'opencode' || provider.authModes?.includes('anonymous');
    const endpoint = (isOAuth || isAnonymous)
      ? (values.endpoint ? validateEndpoint(values.endpoint) : (PROVIDER_ENDPOINTS[provider.id] || null))
      : validateEndpoint(values.endpoint || PROVIDER_ENDPOINTS[provider.id] || '');
    let credential = null;
    if (values.apiKey !== undefined && values.apiKey.trim()) credential = { apiKey: secret(values.apiKey) };
    else if (values.accessToken || values.token) credential = { accessToken: secret(values.accessToken || values.token), refreshToken: values.refreshToken ? secret(values.refreshToken) : null };
    assert(isOAuth || isAnonymous || credential, 'An API key is required.');
    const fallback = this.providers[provider.id]?.fallbackModels || [];
    const c = {
      id: randomUUID(), providerId: provider.id, name: label(values.name, provider.name), endpoint, email: null, accountLabel: null,
      projectId: values.projectId ? projectId(values.projectId) : null, revision: 1, enabled: true, credentialPresent: Boolean(credential) || isAnonymous,
      authState: (credential || isAnonymous) ? 'ready' : 'required', projectState: provider.id === 'antigravity' ? 'pending' : 'not_applicable',
      discoveryState: (credential || isAnonymous) ? 'ready' : 'pending', inferenceState: 'unknown',
      lastDiscoveryAttemptAt: null, costMode: costModeFor(provider.id),
      models: fallback.map(m => ({ ...m, enabled: true, source: 'static' })),
      lastTestedAt: null, lastModelSyncAt: null, nextModelSyncAt: null,
      autoSync: provider.discoveryClass !== 'static-only', error: null, quota: null,
    };
    if (credential) this.store.saveCredentials(c.id, credential);
    this.store.put('connection', c);
    this.setProviderConfig(provider.id, { connectionOrder: [...this.providerConfig(provider.id).connectionOrder, c.id] });
    return c;
  }
  patch(id, values) {
    const c = this.connection(id);
    const invalidates = values.apiKey !== undefined || values.endpoint !== undefined || values.projectId !== undefined || values.accessToken !== undefined || values.token !== undefined;
    if (values.name !== undefined) c.name = label(values.name, c.name);
    if (values.endpoint !== undefined) { assert(!['antigravity', 'agy', 'codex', 'claude', 'github', 'cline', 'opencode'].includes(c.providerId), 'Managed endpoints cannot be overwritten.'); c.endpoint = validateEndpoint(values.endpoint); }
    if (values.projectId !== undefined) c.projectId = projectId(values.projectId);
    if (values.enabled !== undefined) { assert(typeof values.enabled === 'boolean', 'Enabled must be boolean.'); c.enabled = values.enabled; }
    if (values.autoSync !== undefined) { assert(typeof values.autoSync === 'boolean', 'Auto sync must be boolean.'); c.autoSync = values.autoSync; }
    if (values.customModel && typeof values.customModel.id === 'string') {
      // A hand-typed model is the second mechanism beside discovery: the user
      // states the id and whether the model reasons. The id is kept VERBATIM —
      // stored, sent upstream and displayed exactly as typed, never normalized or
      // rewritten — and only the minimum is checked: not blank, no control
      // characters, short enough to store. When the adapter documents its own
      // level set (DeepSeek: none/low/high/max), that set is published, so the
      // manual row matches a discovered one and survives normalization.
      const modelId = values.customModel.id;
      assert(modelId.trim().length > 0, 'Model id is required.', 'INVALID_MODEL', 400);
      assert(!MODEL_ID_CONTROL_CHARS.test(modelId), 'Model id cannot contain control characters.', 'INVALID_MODEL', 400);
      assert(modelId.length <= MODEL_ID_MAX_LENGTH, `Model id must be ${MODEL_ID_MAX_LENGTH} characters or fewer.`, 'INVALID_MODEL', 400);
      const existing = c.models.find(m => m.id === modelId);
      const declared = values.customModel.capabilities && typeof values.customModel.capabilities === 'object' ? values.customModel.capabilities : null;
      if (existing) {
        existing.enabled = true;
        if (values.customModel.name) existing.name = values.customModel.name.trim();
        // Gõ lại một id đã có là cách SỬA lời khai cũ, không chỉ là bật nó lên.
        // Hai cờ trong form (vision/reasoning) phải ghi được ở nhánh cập nhật;
        // nếu không, chọn sai một lần là hết đường sửa, còn `thinkingLevels` thì
        // mâu thuẫn với chính cờ `reasoning` vừa khai. `streaming`/`tools` không
        // có trong form nên giữ nguyên bằng chứng đã dò được.
        if (declared) {
          // `'reported'` is the shared vocabulary's word for "declared, not yet
          // verified". A fifth word (`'supported'`) used to live here and no
          // consumer knew it, so a row the user ticked as vision-capable showed no
          // vision evidence anywhere in the UI.
          const vision = declared.vision ? 'reported' : 'unknown';
          const reasoning = declared.reasoning ? 'reported' : 'unknown';
          existing.capabilities = { streaming: 'reported', tools: 'unknown', ...existing.capabilities, vision, reasoning };
          existing.thinkingLevels = declared.reasoning ? manualThinkingLevels(this.providers[c.providerId]) : [];
          existing.thinkingType = declared.reasoning ? 'effort' : 'none';
          if (!declared.reasoning) existing.defaultThinking = null;
        }
      } else {
        c.models.push({
          id: modelId,
          name: values.customModel.name?.trim() || modelId,
          source: 'custom',
          stale: false,
          enabled: true,
          capabilities: {
            streaming: 'reported',
            tools: 'unknown',
            vision: values.customModel.capabilities?.vision ? 'reported' : 'unknown',
            reasoning: values.customModel.capabilities?.reasoning ? 'reported' : 'unknown',
          },
          thinkingLevels: values.customModel.capabilities?.reasoning ? manualThinkingLevels(this.providers[c.providerId]) : [],
          thinkingType: values.customModel.capabilities?.reasoning ? 'effort' : 'none',
          contextWindow: Number.isInteger(values.customModel.contextWindow) && values.customModel.contextWindow > 0 ? values.customModel.contextWindow : null,
          // A number typed in the form is the user's own declaration, so the row
          // says so — that is what keeps the name table from overwriting it later.
          contextWindowSource: Number.isInteger(values.customModel.contextWindow) && values.customModel.contextWindow > 0 ? 'manual' : null,
          contextWindowReported: null,
          defaultThinking: null,
        });
      }
    }
    // Cửa sổ ngữ cảnh người dùng tự khai cho MỘT model đã có trên connection —
    // đúng khuôn khối `modelPricing` dưới đây, và vì cùng một lý do: bảng tên phủ
    // họ V4/V4.1, nhưng một model lạ (hoặc một bảng đã cũ) vẫn cần một đường để
    // người dùng nói đúng số. Không nhét vào `customModel` vì khối đó chỉ áp khi
    // TẠO dòng mới: một model đã dò được từ nhà cung cấp không có đường nào khác.
    if (values.modelContextWindow && typeof values.modelContextWindow === 'object') {
      const requested = values.modelContextWindow;
      const modelId = typeof requested.modelId === 'string' ? requested.modelId : '';
      const model = c.models.find(m => m.id === modelId);
      assert(model, 'Add the model id first, then set a context window.', 'MODEL_NOT_FOUND', 404);
      if (requested.clear === true) {
        // Xoá lời khai tay để bảng tên (hoặc số nhà cung cấp) quay lại trả lời.
        // Số nhà cung cấp đã công bố phải được nhặt ra TRƯỚC khi xoá dòng: để
        // nguyên `contextWindow` cũ rồi dò lại thì chính số người dùng vừa khai
        // quay lại dưới nhãn `reported`, và một dòng ngoài bảng tên vĩnh viễn
        // không xoá được lời khai của mình.
        const provider = this.providers[c.providerId];
        const published = providerPublishedWindow(model);
        delete model.contextWindowSource;
        delete model.contextWindowReported;
        delete model.contextWindow;
        const fromProvider = typeof provider?.thinkingMetadata === 'function' ? provider.thinkingMetadata(model) : null;
        Object.assign(model, modelThinking({
          ...model,
          ...(fromProvider || {}),
          declaredContextWindow: null,
          reportedContextWindow: published,
        }));
      } else {
        const value = requested.contextWindow;
        assert(
          Number.isInteger(value) && value > 0 && value <= 2_000_000,
          'Enter a whole number of tokens (1–2000000).',
          'INVALID_CONTEXT_WINDOW',
          400,
        );
        // Số nhà cung cấp (nếu có) được giữ lại trước khi số tay thay chỗ nó —
        // đúng C3 "giữ `contextWindowReported` nếu có" — nếu không thì `clear`
        // không còn gì để trả dòng về, và số nhà cung cấp mất khỏi bản ghi.
        const provider = this.providers[c.providerId];
        const fromProvider = typeof provider?.thinkingMetadata === 'function' ? provider.thinkingMetadata(model) : null;
        const published = providerPublishedWindow(model, fromProvider);
        model.contextWindow = value;
        model.contextWindowSource = 'manual';
        // CONTRACT: `contextWindowReported` chỉ có mặt khi nó KHÁC số đang dùng.
        // Khai tay đúng bằng số nhà cung cấp thì không còn gì "ở bên cạnh" để báo —
        // trước đây nhánh này gán thẳng `published`, nên một dòng có thể tự báo hai
        // lần cùng một số (lỗi b18-review #5).
        model.contextWindowReported = published !== null && published !== value ? published : null;
      }
    }
    // Giá người dùng tự đặt cho một model. Khối `customModel` ở trên đã chạy
    // trước, nên một PATCH có thể vừa khai id vừa đặt giá cho nó. Model phải có
    // trên connection — đặt giá cho một id chưa tồn tại là bước thiếu, không phải
    // lỗi cú pháp, nên câu trả lời nói thẳng bước còn thiếu.
    if (values.modelPricing && typeof values.modelPricing === 'object') {
      const requested = values.modelPricing;
      const modelId = typeof requested.modelId === 'string' ? requested.modelId : '';
      const model = c.models.find(m => m.id === modelId);
      assert(model, 'Add the model id first, then set a price.', 'MODEL_NOT_FOUND', 404);
      if (requested.clear === true) {
        // Xoá giá tay để giá `ping`/`documented` quay lại: giá của adapter được
        // tra lại ngay, còn giá provider công bố trở lại ở lần dò kế tiếp.
        delete model.pricing;
        const provider = this.providers[c.providerId];
        const documented = typeof provider?.documentedPricing === 'function' ? provider.documentedPricing(model, new Date()) : null;
        if (documented) model.pricing = documented;
      } else {
        const price = normalizePrice({
          input: requested.input,
          output: requested.output,
          cachedInput: requested.cachedInput,
          cacheWriteInput: requested.cacheWriteInput,
          source: 'manual',
          asOf: today(),
          updatedAt: Date.now(),
        });
        assert(price, 'Enter an input and an output price in USD per million tokens (0–1000).', 'INVALID_PRICE', 400);
        model.pricing = price;
      }
    }
    if (values.enabledModelIds !== undefined) {      assert(Array.isArray(values.enabledModelIds) && values.enabledModelIds.every(id => typeof id === 'string' && c.models.some(m => m.id === id)), 'Select only models discovered for this connection.');
      c.models = c.models.map(m => ({ ...m, enabled: values.enabledModelIds.includes(m.id) }));
    }
    if (values.apiKey !== undefined || values.accessToken !== undefined || values.token !== undefined) {
      assert(c.providerId !== 'antigravity', 'Use account authorization for Antigravity.');
      const val = (values.apiKey ?? values.accessToken ?? values.token)?.trim();
      if (val) {
        // Nhánh legacy giữ nguyên hành vi hôm nay, chỉ đổi ĐÍCH ghi sang khoá đầu
        // của ring: một khoá đã bị chuyển sang connection khác thì không được ghi
        // vào dòng cũ của nó nữa.
        const rowId = this.saveCredential(c, {
          apiKey: secret(val),
          accessToken: secret(val),
          ...(values.refreshToken ? { refreshToken: secret(values.refreshToken) } : {}),
        });
        // Cùng luật với `replaceKey`: khoá vừa đổi secret là khoá MỚI với vòng xoay —
        // để nguyên `cooling`/`exhausted` cũ là bỏ qua một khoá vừa gõ lại tới 120 giây.
        this.keyRing.clear(rowId);
        c.credentialPresent = true; c.authState = 'ready';
      }
    }
    if (values.projectId !== undefined) {
      // `credentialRowId` rơi về `c.id` khi ring RỖNG, mà dòng cũ đó có thể đã được
      // chuyển sang connection khác (`importKeys` không xoá dòng nguồn): đọc nó rồi
      // ghi lại là hồi sinh một khoá MA và connection không xoá được nữa. Ring rỗng ⇒
      // không có gì để ghi; không có `keys` (legacy) ⇒ vẫn là dòng của chính nó.
      const rowId = Array.isArray(c.keys) ? (c.keys[0]?.id ?? null) : c.id;
      const credential = rowId ? this.store.credentials(rowId) : null;
      if (credential) this.saveCredential(c, { ...credential, projectId: c.projectId }, rowId);
    }
    if (invalidates) {
      const fallback = this.providers[c.providerId]?.fallbackModels || [];
      c.revision++; c.models = fallback.map(m => ({ ...m, enabled: true, source: 'static' })); c.discoveryState = 'ready'; c.inferenceState = 'unknown'; c.lastTestedAt = null; c.error = null; c.quota = null;
      if (c.providerId === 'antigravity') c.projectState = c.projectId ? 'ready' : 'pending';
      this.cancelConnection(id);
    }
    if (!c.enabled) this.cancelConnection(id);
    this.store.put('connection', c);
    this.repairDefault();
    return c;
  }
  remove(id) {
    const removed = this.connection(id);
    // Còn khoá thì không xoá connection: xoá nó là bỏ luôn những khoá đó, và giao
    // diện đã disable nút Delete — đây là lớp thứ hai cho người gọi API trực tiếp.
    const keys = Array.isArray(removed.keys) ? removed.keys : [];
    assert(keys.length === 0, `Remove the ${keys.length} keys on this connection first — deleting it would drop them.`, 'KEYS_PRESENT', 409);
    this.cancelConnection(id);
    // Chỉ xoá những dòng thuộc ring của CHÍNH connection này (ring rỗng ⇒ không
    // xoá gì). Sau khi gộp khoá, dòng của một connection shell có thể đã thuộc
    // ring của connection đích — xoá nó là xoá mất khoá của đích.
    for (const key of keys) this.store.removeCredentials(key.id);
    this.store.delete('connection', id);
    const config = this.providerConfig(removed.providerId); this.setProviderConfig(removed.providerId, { connectionOrder: config.connectionOrder.filter(value => value !== id) });
    for (const alias of this.store.list('alias')) {
      alias.targets = alias.targets.filter(t => t.connectionId !== id);
      if (!alias.targets.length) alias.enabled = false;
      this.store.put('alias', alias);
    }
    this.repairDefault();
  }
  cancelConnection(id) { for (const run of this.active.values()) if (run.connectionId === id) run.controller.abort(new DOMException('Cancelled', 'AbortError')); }
  /**
   * Credential của MỘT khoá trong connection. Không bao giờ đọc thẳng
   * `store.credentials(connectionId)` nữa: giải qua ring trước, nên một dòng mồ côi
   * (khoá đã bị chuyển đi) không thể bị đọc nhầm, và ring rỗng cho ra đúng câu AUTH
   * 401 hôm nay. `id` của khoá được TIÊM LÚC ĐỌC — không bao giờ ghi xuống blob —
   * nên `opencode` thấy mỗi khoá là một session riêng (`providers/opencode.mjs:179-182`)
   * trong khi blob trên đĩa không đổi một byte.
   */
  async credentials(id, signal, keyId = null) {
    const c = this.connection(id);
    const keys = Array.isArray(c.keys) ? c.keys : [];
    const chosen = keyId ? keys.find(key => key.id === keyId) : keys[0];
    assert(!keyId || chosen, 'This key is not on the connection.', 'NOT_FOUND', 404);
    assert(chosen, 'Connect an account or configure an API key first.', 'AUTH', 401);
    let credentials = this.store.credentials(chosen.id);
    assert(credentials, 'Connect an account or configure an API key first.', 'AUTH', 401);
    if (c.providerId === 'antigravity' && Number(credentials.expiresAt) <= Date.now() + 300000) {
      // Bản làm mới thuộc về ĐÚNG dòng credential đang phục vụ lượt này, nên khoá của
      // map là id DÒNG chứ không phải id connection: một connection giữ hai tài khoản
      // Google phải làm mới hai grant riêng, và bản làm mới của tài khoản này không
      // bao giờ được trả cho tài khoản kia.
      const servingId = chosen.id;
      if (!this.refreshes.has(servingId)) {
        const revision = c.revision;
        const promise = this.providers.antigravity.refresh({ credentials, signal: AbortSignal.timeout(20000) }).then(refreshed => {
          const current = this.store.get('connection', id);
          assert(current && current.revision === revision, 'Credential configuration changed during refresh.', 'STALE_RESULT', 409);
          const merged = { ...credentials, ...refreshed, refreshToken: refreshed.refreshToken || credentials.refreshToken, oauthClient: credentials.oauthClient };
          // Ghi vào dòng đã phục vụ (`chosen.id`), không phải khoá đầu của ring: ghi
          // nhầm là xoá grant của tài khoản kia một cách im lặng.
          this.saveCredential(current, merged, servingId); current.authState = 'ready'; this.store.put('connection', current); return merged;
        }).catch(error => {
          const current = this.store.get('connection', id);
          if (current && current.revision === revision) {
            const safe = safeError(error);
            if (safe.code === 'AUTH') current.authState = 'expired';
            current.error = safe.message; this.store.put('connection', current);
          }
          throw error;
        }).finally(() => this.refreshes.delete(servingId));
        this.refreshes.set(servingId, promise);
      }
      credentials = await this.refreshes.get(servingId);
      signal?.throwIfAborted();
    }
    return { ...credentials, id: chosen.id, ...(c.projectId ? { projectId: c.projectId } : {}) };
  }
  async discover(id, signal = AbortSignal.timeout(60000)) {
    if (this.discoveries.has(id)) return this.discoveries.get(id);
    const promise = this.#discover(id, signal).finally(() => this.discoveries.delete(id));
    this.discoveries.set(id, promise);
    return promise;
  }
  /**
   * Một luật, hai chỗ gọi: alias trỏ vào hàng model không còn tồn tại thì không còn đường đi
   * nào, nên tắt nó kèm lý do — `#discover` (provider rút model khỏi danh sách) và
   * `removeCustomModel` (người dùng xoá hàng gõ tay) phải nói cùng MỘT câu. `missing` là
   * phép thử của từng chỗ; cờ `Array.isArray` nằm ở đây để một hàng alias cũ/hỏng (`targets`
   * không phải mảng) không làm cả vòng lặp ném lỗi — đi qua đường nào cũng vậy.
   */
  #disableAliases(missing) {
    for (const alias of this.store.list('alias')) {
      if (!Array.isArray(alias.targets) || !alias.targets.some(missing)) continue;
      alias.enabled = false;
      alias.error = 'One or more target models are no longer available. Choose a current model and enable this alias again.';
      this.store.put('alias', alias);
    }
  }
  async #discover(id, signal) {
    const initial = this.connection(id);
    // Ghi mốc thời gian TRƯỚC khi gọi mạng: một lần dò thất bại là trạng thái
    // người dùng phải thấy ("Last attempt: <giờ>"), nên mốc thuộc về lúc bắt đầu
    // chứ không phải lúc kết thúc.
    initial.lastDiscoveryAttemptAt = Date.now();
    this.store.put('connection', initial);
    const credentials = await this.credentials(id, signal);
    try {
      const found = await this.providers[initial.providerId].discover({ connection: initial, credentials, signal });
      const current = this.connection(id);
      assert(current.revision === initial.revision, 'Connection changed during discovery. Retry.', 'STALE_RESULT', 409);
      assert(Array.isArray(found.models) && found.models.length > 0, 'Provider did not return any eligible models.', 'NO_MODELS', 502);
      // Inventory is live, but a probe belongs to a particular model. Keep its
      // result across a refresh so a model that disappeared or failed is not
      // silently presented as untested again.
      const previous = new Map(current.models.map(m => [m.id, m]));
      const eligibleFound = current.providerId === 'antigravity'
        ? found.models.filter(m => isAntigravityModelValid(m.id))
        : found.models;
      current.models = eligibleFound.filter(m => typeof m.id === 'string' && m.id && m.id.length <= 200).map(m => {
        const before = previous.get(m.id);
        const row = {
          ...before, ...m, id: m.id, name: m.name || m.id, enabled: before?.enabled ?? m.enabled ?? true,
          source: m.source || 'live', stale: Boolean(m.stale),
          // BUG-4/R2: the payload (or the adapter's provider rules) owns the
          // metadata; a previous row only fills gaps the payload left. A number
          // the user declared is not a gap the payload may fill.
          ...modelThinking({
            ...before,
            ...m,
            declaredContextWindow: before?.contextWindowSource === 'manual' ? before.contextWindow : null,
            reportedContextWindow: m.contextWindow ?? before?.contextWindowReported ?? null,
          }),
          // M3: giữ số đo reasoning của router qua lần dò danh sách này (xem
          // `preservedThinkingProbe`), rồi mới tới capabilities của payload.
          ...(preservedThinkingProbe(before, m) || {}),
          capabilities: { streaming: 'reported', tools: 'unknown', vision: 'unknown', reasoning: 'unknown', ...m.capabilities },
        };
        // Giá của dòng sau khi dò lại: giá tay người dùng đặt luôn thắng, rồi mới
        // tới giá provider vừa công bố, rồi tới bảng giá của adapter.
        const price = modelPrice({ previous: before, found: m, provider: this.providers[current.providerId], at: new Date() });
        if (price) row.pricing = price; else delete row.pricing;
        return row;
      });
      // Hàng gõ tay là lời khai của người dùng, không phải kết quả dò: một lần dò
      // thành công không được xoá chúng (id + cờ bật/tắt + kết quả probe giữ
      // nguyên). Chỉ một lần "thay thế" danh sách tường minh mới được xoá — hiện
      // chưa có đường đó.
      current.models.push(...previous.values().filter(model => model.source === 'custom' && model.id && !current.models.some(row => row.id === model.id)));
      // `credentials` đã đi qua ring nên mang theo `id` tiêm lúc đọc; blob ghi xuống
      // đĩa KHÔNG bao giờ mang trường đó (nó là id DÒNG, không phải dữ liệu).
      if (found.credentials) { const { id: keyId, ...blob } = credentials; this.saveCredential(current, { ...blob, ...found.credentials }, keyId); }
      if (found.email) { current.email = found.email; current.accountLabel = found.email; }
      if (found.projectId) { current.projectId = found.projectId; this.saveCredential(current, { ...(this.store.credentials(credentialRowId(current)) || {}), projectId: found.projectId }); }
      current.authState = 'ready'; current.discoveryState = 'ready'; current.lastModelSyncAt = new Date().toISOString(); current.nextModelSyncAt = new Date(Date.now() + 6 * 60 * 60 * 1000).toISOString(); current.error = null;
      if (current.providerId === 'antigravity') current.projectState = found.projectState || (current.projectId ? 'ready' : 'required');
      this.store.put('connection', current);
      // Alias mất đường đi thì tắt kèm lý do — cùng một luật với `removeCustomModel`.
      this.#disableAliases(target => target.connectionId === id && !current.models.some(model => model.id === target.modelId));
      this.repairDefault(); return current;
    } catch (error) {
      const current = this.store.get('connection', id);
      if (current && current.revision === initial.revision) {
        const safe = safeError(error); current.error = safe.message; current.discoveryState = 'failed';
        if (safe.code === 'AUTH') current.authState = 'expired';
        if (current.providerId === 'antigravity') current.projectState = safe.code === 'PROJECT_REQUIRED' ? 'required' : current.projectId ? 'ready' : 'failed';
        const fallback = this.providers[current.providerId]?.fallbackModels;
        if (!current.models.length && Array.isArray(fallback) && fallback.length) {
          current.models = fallback.map(model => ({ ...model, enabled: false, source: 'static', stale: true, capabilities: { streaming: 'reported', tools: 'unknown', vision: 'unknown', reasoning: 'unknown', ...model.capabilities } }));
          current.discoveryState = 'degraded';
        } else if (current.models.length) {
          // Model gõ tay chưa bao giờ đến từ một lần dò, nên không có gì để "cũ":
          // một lần dò thất bại để nguyên id người dùng đã khai và kết quả probe
          // của nó. Chỉ các dòng do ping phát hiện mới thành `stale`.
          current.models = current.models.map(model => (model.source === 'custom' ? model : { ...model, stale: true }));
          current.discoveryState = 'degraded';
        }
        this.store.put('connection', current);
      }
      throw error;
    }
  }
  async testInference(id, modelId, signal = AbortSignal.timeout(90000), keyId = null) {
    const connection = this.connection(id);
    // Phép thử thuộc về một model, không thuộc về cờ bật/tắt của nó: người dùng
    // phải Test được đúng id họ vừa khai (và cả id họ vừa tắt) trước khi quyết
    // định bất cứ điều gì về nó.
    // M6 — "không có hàng" có BA nguyên nhân và câu trả lời phải nói đúng cái nào:
    // id gõ sai / provider đã rút id (không có trong catalogue công khai), hay id CÓ
    // trong catalogue mà khoá không được cấp (đúng ca `exo-free`: 404 khi test nhưng
    // vẫn nằm trong danh sách công khai). Câu gốc giữ nguyên làm tiền tố để không phá
    // vỡ người đọc cũ.
    const row = connection.models.find(model => model.id === modelId);
    if (!row) {
      const { publicCatalogue } = await this.#catalogueVerdict(connection, modelId, signal);
      throw new RouterError('MODEL_NOT_FOUND', missingModelMessage(modelId, publicCatalogue), 404);
    }
    const startedAt = Date.now();
    try {
      const credentials = await this.credentials(id, signal, keyId);
      let meaningful = false; let finished = false; let usage = null;
      for await (const event of this.providers[connection.providerId].generate({ connection, credentials, body: { model: modelId, messages: [{ role: 'user', content: 'Reply exactly: BOXFOX_OK' }], max_tokens: 64, stream: false }, signal })) {
        if (event.type === 'delta' && (event.delta?.content || event.delta?.tool_calls?.length)) meaningful = true;
        if (event.type === 'finish') finished = true;
        if (event.type === 'usage') usage = event.usage;
      }
      assert(meaningful && finished, 'Provider returned no complete response.', 'UNAVAILABLE', 502);
      const current = this.connection(id); current.inferenceState = 'ready'; current.lastTestedAt = new Date().toISOString();
      // Một phép thử đạt là bằng chứng cho MỘT model, không phải cho đường dò
      // danh sách: nếu lần dò vẫn hỏng, câu lỗi của nó phải ở lại, để khối "Models
      // could not be listed" còn nói được lý do và ba lối thoát của nó.
      if (current.discoveryState === 'ready') current.error = null;
      current.models = current.models.map(model => model.id === modelId ? {
        ...model, health: 'ready', probeStatus: 'passed', lastProbedAt: current.lastTestedAt, lastProbe: { status: 'passed', httpStatus: 200, latencyMs: Date.now() - startedAt, testedAt: current.lastTestedAt, error: null },
      } : model);
      this.store.put('connection', current);
      return { status: 'passed', connectionId: id, modelId, usage, testedAt: current.lastTestedAt };
    } catch (error) {
      const current = this.store.get('connection', id);
      if (current && current.revision === connection.revision) {
        const safe = safeError(error);
        // A per-model test is a probe: it must not mark a healthy account as
        // broken. OmniRoute follows the same isolation rule for its model
        // probes. Authentication failures remain connection-level evidence.
        // 404 trên một id gõ tay là câu trả lời cho "tôi gõ tên có đúng không":
        // router gửi id nguyên văn, nên thông báo nói rõ điều đó rồi để lời của
        // nhà cung cấp đi kèm khi họ có nói gì.
        const typedByHand = connection.models.find(model => model.id === modelId)?.source === 'custom';
        const message = safe.status === 404 && typedByHand ? unrecognisedModelId(modelId, safe.message) : safe.message;
        current.models = current.models.map(model => model.id === modelId ? {
          ...model, health: probeHealth(safe), lastProbe: { status: 'failed', httpStatus: safe.status, latencyMs: Date.now() - startedAt, testedAt: new Date().toISOString(), error: message },
        } : model);
        if (safe.code === 'AUTH') { current.authState = 'expired'; current.error = safe.message; }
        this.store.put('connection', current);
      }
      if (safeError(error).code === 'RATE_LIMIT') {
        try { await this.quota(id, AbortSignal.timeout(5000)); } catch { /* inference error remains primary */ }
      }
      throw error;
    }
  }
  /**
   * M1 — dò REASONING của một model, không phải dò "gọi được hay không".
   *
   * `testInference` trả lời "model này gọi được không" bằng một câu hỏi 64 token KHÔNG
   * mang trường reasoning nào, nên nó không bao giờ nói được model có suy luận hay
   * không (đo được: `fledge-alpha-free` PASS phép thử đó mà không có một token suy
   * luận nào). Phép dò này là ANH EM của nó, không phải bản thay thế: cùng adapter,
   * cùng hình dạng request mà lượt gọi thật dùng (`generate` — nơi sở hữu giả trang,
   * hai tool mồi, `stream: true` bắt buộc và định tuyến `/responses`), chỉ khác câu
   * hỏi và việc ĐẾM hai tín hiệu: `reasoning_content` chảy về và `reasoning_tokens`.
   *
   * Vì sao phải nhiều mẫu: một mẫu rỗng KHÔNG chứng minh provider không hỗ trợ — nó
   * chỉ là một mẫu rỗng. Xem `judgeReasoningProbe`.
   */
  async probeReasoning(id, modelId, { levels = null, samples = 2, prompt = null } = {}, signal = AbortSignal.timeout(90000), keyId = null) {
    const connection = this.connection(id);
    const provider = this.providers[connection.providerId];
    assert(provider && typeof provider.generate === 'function', 'This provider cannot be probed.', 'ADAPTER_REQUIRED', 501);
    const row = connection.models.find(model => model.id === modelId);
    // Hàng không có trên connection: câu hỏi thật sự là "vì sao nó không có ở đây",
    // và câu trả lời phải phân biệt được với "khoá chưa được cấp".
    if (!row) {
      const { publicCatalogue, reason } = await this.#catalogueVerdict(connection, modelId, signal);
      return {
        status: reason || 'not_on_connection', connectionId: id, modelId, publicCatalogue,
        message: missingModelMessage(modelId, publicCatalogue),
        thinkingType: null, thinkingLevels: [], thinkingSource: null, thinkingAsOf: null, thinkingEvidence: null,
        httpStatus: null, latencyMs: null, reasoningChars: 0, reasoningTokens: 0,
        samples: 0, levelsTried: [], levelsSupported: [], retryAfterMs: null,
      };
    }
    const credentials = await this.credentials(id, signal, keyId);
    // Bí mật không bao giờ được đi vào câu trả lời hay hàng model: câu lỗi của provider
    // là văn bản do bên ngoài viết, và nó có thể echo lại chính header Authorization.
    const secrets = [credentials.apiKey, credentials.accessToken, credentials.refreshToken]
      .filter(value => typeof value === 'string' && value.length >= 8);
    const published = Array.isArray(row.thinkingLevels) ? row.thinkingLevels.filter(level => typeof level === 'string' && level.trim()) : [];
    const requested = Array.isArray(levels) && levels.length ? levels : (published.length ? published : [...EFFORT_LEVELS]);
    const named = [...new Set(requested
      .filter(level => typeof level === 'string' && level.trim())
      .map(level => level.trim())
      .filter(level => !REASONING_PROBE_SKIPPED_LEVELS.has(level.toLowerCase())))];
    // `samples` là SÀN, không phải trần: luật M2 đòi ≥ 2 mẫu trước khi được kết luận
    // "không", còn bảng mức thì phải dò hết. Dừng ở mẫu dương đầu tiên nghe tiết kiệm,
    // nhưng `thinkingLevels` chính là bộ chọn mức người dùng nhìn thấy — đo được ngày
    // 2026-10-08: `space-bunny-free` có 4 mức trong hàng, dò kiểu dừng sớm ghi lại 1 mức
    // và bộ chọn (cần > 1 mức) biến mất. Đó đúng là kiểu hỏng đợt này sinh ra để chữa.
    const floor = Math.max(1, Math.floor(Number(samples) || 1));
    // Mẫu "không gửi mức" LUÔN có mặt: nó trả lời "model có tự suy luận không", và trên
    // Zen nó là cách viết trung thực duy nhất cho `none`/`auto` — adapter bỏ hai giá trị
    // đó, nên gửi chúng chỉ tạo ra một bản sao của mẫu này.
    const schedule = [...named, null];
    while (schedule.length < floor) schedule.push(...(named.length ? named : [null]));
    // Vòng `while` ngay trên đã bảo đảm `schedule.length >= floor`, nên chỉ còn lại cái trần.
    const budget = Math.min(REASONING_PROBE_MAX_SAMPLES, schedule.length);
    const question = typeof prompt === 'string' && prompt.trim() ? prompt.trim() : REASONING_PROBE_PROMPT;
    const observations = [];
    for (const level of schedule.slice(0, budget)) {
      const sample = await this.#probeSample(provider, { connection, credentials, modelId, level, prompt: question, signal, secrets });
      observations.push(sample);
      // Lỗi hạ tầng (429/503/timeout) không phải "model không hỗ trợ": dừng ngay để
      // không đốt thêm hạn mức và để kết luận nói đúng chuyện gì đã xảy ra.
      if (sample.error) break;
      // Từ chối trường reasoning là bằng chứng âm, nhưng luật M2 đòi ≥ 2 mẫu.
      if (sample.refusedReasoningField && observations.length >= 2) break;
    }
    const verdict = judgeReasoningProbe(observations);
    const at = today();
    const evidence = reasoningProbeEvidence({ verdict, observations, at });
    // M6 — provider nói "id này không được cấp": tra catalogue công khai để phân biệt
    // "provider có model nhưng khoá không được cấp" với "provider đã rút id này".
    let publicCatalogue = null;
    let reason = null;
    if (verdict.status === 'not_entitled') {
      const found = await this.#catalogueVerdict(connection, modelId, signal);
      publicCatalogue = found.publicCatalogue;
      reason = found.reason;
    }
    const status = reason || verdict.status;
    const block = {
      status,
      samples: observations.length,
      httpStatus: verdict.httpStatus ?? observations.find(sample => sample.httpStatus === 200)?.httpStatus ?? null,
      latencyMs: observations.reduce((total, sample) => total + (sample.latencyMs || 0), 0),
      reasoningChars: observations.reduce((total, sample) => total + sample.reasoningChars, 0),
      reasoningTokens: observations.reduce((max, sample) => Math.max(max, sample.reasoningTokens), 0),
      levelsTried: verdict.levelsTried,
      levelsSupported: verdict.levelsSupported,
      at: new Date().toISOString(),
      ...(reason ? { reason } : {}),
      ...(publicCatalogue === null ? {} : { publicCatalogue }),
      ...(verdict.retryAfterMs ? { retryAfterMs: verdict.retryAfterMs } : {}),
      ...(verdict.message ? { message: verdict.message } : {}),
    };
    // M3/M6 — chỉ lần ĐO ĐƯỢC mới ghi khối `thinkingProbe` (và `reasoningProbeRowPatch` cũng chỉ
    // ghi hàng cho đúng hai kết luận đó): khối này là bằng chứng đứng cạnh
    // `thinkingEvidence`/`thinkingLevels`, nên một lần hỏng hạ tầng (`rate_limited`,
    // `unavailable`, …) ghi đè nó sẽ để lại một cặp đọc lệch nhau — bằng chứng "4/5 mẫu trả
    // reasoning" cạnh khối "rate limited". Lần hỏng vẫn tới người dùng ngay: câu trả lời của
    // route (kèm `retryAfterMs`) và dòng phụ trên UI, còn hàng giữ nguyên số đo cũ.
    const carriesEvidence = verdict.status === 'supports' || verdict.status === 'refuses';
    const patch = reasoningProbeRowPatch(row, { verdict, evidence, at });
    // Ghi kèm bằng chứng vào ĐÚNG hàng đã đọc: revision đổi giữa chừng nghĩa là cấu
    // hình vừa bị sửa (thêm/xoá khoá, đổi endpoint) nên kết quả này thuộc về một
    // connection khác — bỏ ghi thay vì ghi đè lên thay đổi của người dùng.
    const current = this.connection(id);
    if (carriesEvidence && current.revision === connection.revision && current.models.some(model => model.id === modelId)) {
      current.models = current.models.map(model => model.id === modelId
        ? { ...model, ...(patch || {}), thinkingProbe: block }
        : model);
      this.store.put('connection', current);
    }
    return {
      status, connectionId: id, modelId,
      thinkingType: patch?.thinkingType ?? row.thinkingType ?? null,
      thinkingLevels: patch?.thinkingLevels ?? (Array.isArray(row.thinkingLevels) ? row.thinkingLevels : []),
      thinkingSource: patch?.thinkingSource ?? row.thinkingSource ?? null,
      thinkingAsOf: patch?.thinkingAsOf ?? row.thinkingAsOf ?? null,
      thinkingEvidence: patch?.thinkingEvidence ?? row.thinkingEvidence ?? null,
      latencyMs: block.latencyMs, httpStatus: block.httpStatus,
      reasoningChars: block.reasoningChars, reasoningTokens: block.reasoningTokens,
      samples: observations.length, levelsTried: verdict.levelsTried, levelsSupported: verdict.levelsSupported,
      publicCatalogue, reason, message: verdict.message ?? null, retryAfterMs: verdict.retryAfterMs ?? null,
      thinkingProbe: block,
    };
  }
  /**
   * Một mẫu của phép dò, chạy qua CHÍNH `generate()` của adapter — nơi sở hữu giả trang,
   * hai tool mồi, `stream: true` bắt buộc và định tuyến `/responses` cho họ
   * `muse-spark*`. Chép lại hình dạng đó ở đây là tự tạo chỗ trôi thứ hai.
   *
   * `reasoning_tokens` đọc CẢ HAI chỗ (`usage.reasoning_tokens` và
   * `usage.completion_tokens_details.reasoning_tokens`): đo được họ `muse-spark*` trả
   * token suy luận ở trường thứ hai trong khi `reasoning_content` rỗng, nên chỉ đếm
   * văn bản là kết luận sai cho cả một họ model.
   */
  async #probeSample(provider, { connection, credentials, modelId, level, prompt, signal, secrets }) {
    const attempt = async body => {
      const startedAt = Date.now();
      let reasoningChars = 0;
      let reasoningTokens = 0;
      let contentChars = 0;
      for await (const event of provider.generate({ connection, credentials, body, signal })) {
        if (event.type === 'delta') {
          reasoningChars += (event.delta?.reasoning_content || '').length;
          contentChars += (event.delta?.content || '').length;
        }
        if (event.type === 'usage') {
          const tokens = Number(event.usage?.reasoning_tokens ?? event.usage?.completion_tokens_details?.reasoning_tokens ?? 0);
          if (Number.isFinite(tokens)) reasoningTokens = Math.max(reasoningTokens, tokens);
        }
      }
      return { httpStatus: 200, latencyMs: Date.now() - startedAt, reasoningChars, reasoningTokens, contentChars };
    };
    const base = { model: modelId, messages: [{ role: 'user', content: prompt }], max_tokens: REASONING_PROBE_MAX_TOKENS, stream: true };
    try {
      return { level, ...(await attempt(level ? { ...base, thinkingLevel: level } : base)) };
    } catch (error) {
      const safe = safeError(error);
      const refusedSpelling = (safe.status === 400 || safe.status === 422) && REASONING_FIELD_RE.test(safe.message || '');
      if (!level || !refusedSpelling) {
        return { level, error: true, httpStatus: safe.status ?? null, code: safe.code, message: redactSecrets(safe.message, secrets), retryAfterMs: safe.retryAfterMs ?? null };
      }
      // 400/422 nhắc tới trường reasoning: provider có thể chỉ không nhận CÁCH VIẾT
      // này. Thử cách viết còn lại (`thinkingLevel` ↔ `reasoning_effort`) trước khi
      // kết luận "không hỗ trợ" — kết luận sai ở đây xoá mất điều khiển của người dùng.
      try {
        return { level, alternateSpelling: 'reasoning_effort', ...(await attempt({ ...base, reasoning_effort: level })) };
      } catch (retry) {
        const retrySafe = safeError(retry);
        if ((retrySafe.status === 400 || retrySafe.status === 422) && REASONING_FIELD_RE.test(retrySafe.message || '')) {
          return { level, refusedReasoningField: true, httpStatus: retrySafe.status, code: retrySafe.code, message: redactSecrets(retrySafe.message, secrets) };
        }
        return { level, error: true, httpStatus: retrySafe.status ?? null, code: retrySafe.code, message: redactSecrets(retrySafe.message, secrets), retryAfterMs: retrySafe.retryAfterMs ?? null };
      }
    }
  }
  /**
   * M6 — vì sao một model không nằm trên connection, trả lời bằng catalogue CÔNG KHAI
   * của provider (`Bearer public` với OpenCode Zen). Chỉ gọi ở nhánh lỗi, cache theo
   * `(providerId, ngày)`, và không bao giờ ghi vào hàng model: catalogue là danh sách
   * người ta được phép dùng, không phải quyền của tài khoản này.
   *
   * Tra hỏng (offline/429) trả `null` — "chưa biết" chứ không đoán, và xoá cache để
   * lần sau còn thử lại.
   */
  async #catalogueVerdict(connection, modelId, signal) {
    const provider = this.providers[connection.providerId];
    if (typeof provider?.publicCatalogue !== 'function') return { publicCatalogue: null, reason: null };
    const key = `${connection.providerId}:${today()}`;
    if (!this.catalogueChecks.has(key)) {
      const timeout = AbortSignal.timeout(10000);
      const check = provider.publicCatalogue({ connection, signal: signal ? AbortSignal.any([signal, timeout]) : timeout })
        .then(ids => new Set(ids))
        .catch(() => null);
      this.catalogueChecks.set(key, check);
    }
    const ids = await this.catalogueChecks.get(key);
    if (!ids) { this.catalogueChecks.delete(key); return { publicCatalogue: null, reason: null }; }
    return { publicCatalogue: ids.has(modelId), reason: catalogueReason(ids.has(modelId)) };
  }
  /**
   * M6 — xoá một hàng GÕ TAY. Hàng do dò phát hiện KHÔNG xoá được (409
   * `MODEL_NOT_CUSTOM`): lần dò sau nó mọc lại y hệt, nên xoá tay chỉ là một hành động
   * vô nghĩa — hàng đó đã có `stale` để nói "đã biến mất khỏi provider".
   */
  removeCustomModel(id, modelId) {
    const c = this.connection(id);
    const row = c.models.find(model => model.id === modelId);
    assert(row, 'This model is not on the connection.', 'MODEL_NOT_FOUND', 404);
    assert(row.source === 'custom', 'Only a hand-typed model can be deleted. A discovered row comes back on the next refresh.', 'MODEL_NOT_CUSTOM', 409);
    c.models = c.models.filter(model => model.id !== modelId);
    // Alias trỏ vào hàng vừa xoá không còn đường đi nào: tắt nó kèm lý do, cùng luật
    // với nhánh "model biến mất sau một lần dò" trong `#discover`.
    this.#disableAliases(target => target.connectionId === id && target.modelId === modelId);
    this.store.put('connection', c);
    this.repairDefault();
    return { removed: true, modelId };
  }
  async quota(id, signal = AbortSignal.timeout(30000)) {
    const c = this.connection(id); const credentials = await this.credentials(id, signal);
    const result = await this.providers[c.providerId].quota({ connection: c, credentials, signal });
    const current = this.connection(id);
    assert(current.revision === c.revision, 'Connection changed during quota refresh.', 'STALE_RESULT', 409);
    current.quota = result; this.store.put('connection', current); return result;
  }
  /**
   * Giá dùng để ước tính chi phí của MỘT lượt gọi, hoặc `null` khi không có giá
   * nào đáng tin. Ba tầng đã chốt trên dòng model (`manual` người dùng đặt,
   * `ping` provider công bố trong `/models`, `documented` bảng của adapter) —
   * riêng tầng `documented` được tra LẠI theo giờ của chính lượt gọi, vì giá
   * DeepSeek đổi theo giờ cao điểm; adapter không còn tra được thì dùng đúng con
   * số đã lưu trên dòng. Tài khoản bao trọn gói (`costMode === 'included'`)
   * không bao giờ được ghi $0.
   */
  priceFor(model, connection, at = new Date()) {
    // Giá hỏng (store cũ, tay sửa file) không bao giờ thành một con số: đúng
    // phép kiểm `normalizePrice` mà `sanitizeConnection` dùng, để đường tính chi
    // phí không thể sinh ra `NaN` chỉ vì một trường không đọc được.
    const price = normalizePrice(model?.pricing);
    if (!price || connection?.costMode === 'included') return null;
    if (price.source !== 'documented') return price;
    const provider = this.providers[connection.providerId];
    const current = typeof provider?.documentedPricing === 'function' ? provider.documentedPricing(model, at) : null;
    return current ?? price;
  }
  // ── Vòng 29: khoá trong một connection ─────────────────────────────────────
  /**
   * Ghi một blob credential vào ĐÚNG dòng của connection: khoá đầu của ring, hoặc
   * dòng của chính connection khi chưa có ring. Ring RỖNG (mọi khoá đã được chuyển
   * đi) thì credential mới là một dòng MỚI và thành khoá đầu tiên — không bao giờ
   * ghi đè id cũ, vì dòng đó có thể đang là khoá của connection khác.
   * `rowId` (tuỳ chọn) chỉ thẳng một dòng trong ring — dùng ở đường đã cầm sẵn một
   * dòng cụ thể (bản làm mới OAuth của đúng khoá đang phục vụ).
   */
  saveCredential(c, blob, rowId = null) {
    if (!rowId && Array.isArray(c.keys) && !c.keys.length) {
      const rowId = randomUUID();
      this.store.saveCredentials(rowId, blob);
      c.keys.push({ id: rowId, label: c.name || 'Key 1', prefix: headOf(blob.apiKey || blob.accessToken), createdAt: Date.now(), lastUsedAt: null });
      this.store.put('connection', c);
      return rowId;
    }
    const target = rowId ?? credentialRowId(c);
    this.store.saveCredentials(target, blob);
    const key = Array.isArray(c.keys) ? c.keys.find(entry => entry.id === target) : null;
    if (key) { key.prefix = headOf(blob.apiKey || blob.accessToken); this.store.put('connection', c); }
    return target;
  }
  /** Còn khoá nào gọi được không — dùng cho phép lọc target đang nghỉ của alias `round_robin`. */
  hasCallableKeys(id, now = Date.now()) {
    const c = this.store.get('connection', id);
    return Boolean(c) && this.keyRing.hasCallable(c, now);
  }
  /** Khoá của một connection, đã dựng ring nếu cần. */
  #keyList(c) {
    this.ensureRing(c);
    return Array.isArray(c.keys) ? c.keys : [];
  }
  /**
   * Thêm một khoá vào CUỐI ring. `key` bắt buộc với provider cần khoá; provider
   * anonymous (`opencode`) cho phép bỏ trống — khi đó dòng credential là một blob
   * rỗng, vẫn có id riêng để mỗi khoá là một session riêng.
   */
  addKey(id, values = {}) {
    const c = this.connection(id);
    const keys = this.#keyList(c);
    if (!Array.isArray(c.keys)) c.keys = keys;
    assert(keys.length < MAX_KEYS_PER_CONNECTION, `A connection holds at most ${MAX_KEYS_PER_CONNECTION} keys.`);
    const provider = PROVIDER_CATALOG.find(entry => entry.id === c.providerId);
    const provided = typeof values.key === 'string' && values.key.trim() ? secret(values.key) : null;
    assert(provided || anonymousProvider(provider), 'Enter a valid API key.');
    if (provided) assert(c.providerId !== 'antigravity', 'Use account authorization for Antigravity.');
    const rowId = randomUUID();
    this.store.saveCredentials(rowId, provided ? { apiKey: provided } : {});
    keys.push({ id: rowId, label: label(values.label, `Key ${keys.length + 1}`), prefix: headOf(provided), createdAt: Date.now(), lastUsedAt: null });
    c.credentialPresent = true; c.authState = 'ready'; c.inferenceState = 'unknown'; c.error = null;
    this.store.put('connection', c);
    this.repairDefault();
    return this.#ringView(c);
  }
  /**
   * Thay secret của ĐÚNG khoá đó, và/hoặc đổi nhãn. Cố ý KHÔNG reset danh sách
   * `models` (khác nhánh legacy `PATCH {apiKey}`): endpoint không đổi thì danh sách
   * model không đổi — sửa một chữ trong khoá 2 không được xoá 43 model.
   */
  replaceKey(id, keyId, values = {}) {
    const c = this.connection(id);
    const keys = this.#keyList(c);
    const index = keys.findIndex(key => key.id === keyId);
    assert(index >= 0, 'This key is not on the connection.', 'NOT_FOUND', 404);
    const key = keys[index];
    if (values.key !== undefined) {
      assert(c.providerId !== 'antigravity', 'Use account authorization for Antigravity.');
      const value = secret(values.key);
      const blob = this.store.credentials(key.id) || {};
      this.store.saveCredentials(key.id, { ...blob, apiKey: value, accessToken: value });
      key.prefix = headOf(value);
      // Khoá vừa đổi secret là khoá mới với vòng xoay: hết nghỉ, hết dòng lỗi cũ.
      this.keyRing.clear(key.id);
    }
    if (values.label !== undefined) key.label = label(values.label, key.label || `Key ${index + 1}`);
    c.credentialPresent = true; c.authState = 'ready'; c.inferenceState = 'unknown'; c.error = null;
    this.store.put('connection', c);
    this.repairDefault();
    return this.#ringView(c);
  }
  /**
   * Bỏ MỘT khoá. Xoá khoá cuối ⇒ ring rỗng và connection Ở LẠI với
   * `credentialPresent: false`, `authState: 'required'` (nó tự rời khỏi định tuyến
   * qua `validTarget`), không tự xoá mình.
   */
  removeKey(id, keyId) {
    const c = this.connection(id);
    const keys = this.#keyList(c);
    const index = keys.findIndex(key => key.id === keyId);
    assert(index >= 0, 'This key is not on the connection.', 'NOT_FOUND', 404);
    keys.splice(index, 1);
    this.store.removeCredentials(keyId);
    this.keyRing.clear(keyId);
    if (c.activeKeyId === keyId) delete c.activeKeyId;
    if (keys.length) { c.credentialPresent = true; c.authState = 'ready'; }
    else { c.credentialPresent = false; c.authState = 'required'; }
    c.inferenceState = 'unknown'; c.error = null;
    this.store.put('connection', c);
    this.repairDefault();
    return this.#ringView(c);
  }
  /**
   * Đọc và giải mã API key / access token của một khoá trong ring để phục vụ
   * chức năng xem (reveal) và sao chép (copy) của người dùng ở Settings.
   */
  revealKey(id, keyId) {
    const c = this.connection(id);
    const keys = this.#keyList(c);
    const key = keys.find(entry => entry.id === keyId) || (c.id === keyId ? { id: c.id } : null);
    assert(key, 'This key is not on the connection.', 'NOT_FOUND', 404);
    const blob = this.store.credentials(key.id) || {};
    return { id: key.id, key: blob.apiKey || blob.accessToken || '' };
  }
  /**
   * Chuyển TOÀN BỘ khoá của một connection khác vào CUỐI ring này, giữ nguyên thứ
   * tự. Không dedupe, không mã hoá lại: mỗi entry `{ id, label, prefix, createdAt }`
   * được bê nguyên sang (nên ciphertext trong DB không đổi một byte), và nguồn ở
   * lại với ring rỗng — nó chỉ rời khỏi định tuyến chứ không tự xoá.
   */
  importKeys(id, fromConnectionId) {
    const target = this.connection(id);
    const sourceId = typeof fromConnectionId === 'string' ? fromConnectionId.trim() : '';
    assert(sourceId, 'Choose a connection to move keys from.');
    assert(sourceId !== id, 'Choose a different connection.');
    const source = this.connection(sourceId);
    const from = Array.isArray(source.keys) ? source.keys : [];
    const into = this.#keyList(target);
    assert(target.providerId === source.providerId, 'Keys can only move between connections of the same provider.');
    assert((target.endpoint || null) === (source.endpoint || null), 'Keys can only move between connections with the same endpoint.');
    assert(target.enabled, 'Enable the target connection before moving keys into it.');
    assert(from.length > 0, 'The source connection has no key to move.');
    assert(into.length + from.length <= MAX_KEYS_PER_CONNECTION, `A connection holds at most ${MAX_KEYS_PER_CONNECTION} keys.`);
    for (const key of from) into.push({ id: key.id, label: key.label || source.name, prefix: key.prefix ?? null, createdAt: key.createdAt ?? Date.now(), lastUsedAt: key.lastUsedAt ?? null });
    target.keys = into;
    source.keys = [];
    delete source.activeKeyId;
    source.credentialPresent = false; source.authState = 'required'; source.inferenceState = 'unknown'; source.error = null;
    target.credentialPresent = true; target.authState = 'ready'; target.inferenceState = 'unknown'; target.error = null;
    this.store.put('connection', source);
    this.store.put('connection', target);
    this.repairDefault();
    return this.#ringView(target);
  }
  /**
   * "Thử ngay" của giao diện: bỏ nghỉ và xoá dòng lỗi của khoá đó, đánh dấu nó là
   * khoá của lượt thử gần nhất, rồi — nếu có model — chạy ĐÚNG một probe ghim vào
   * khoá ấy. Probe 429 park lại khoá theo luật mới.
   */
  async tryKey(id, keyId, { modelId = null } = {}) {
    const c = this.connection(id);
    const keys = this.#keyList(c);
    assert(keys.some(key => key.id === keyId), 'This key is not on the connection.', 'NOT_FOUND', 404);
    this.keyRing.clear(keyId);
    c.activeKeyId = keyId;
    this.store.put('connection', c);
    let probe = null;
    if (modelId) {
      try { probe = await this.testInference(id, modelId, AbortSignal.timeout(90000), keyId); }
      catch (error) {
        const safe = safeError(error);
        if (safe.code === 'RATE_LIMIT') this.keyRing.park(keyId, { retryAfterMs: safe.retryAfterMs, error: safe, modelId });
        throw error;
      }
    }
    return { connection: this.#ringView(this.connection(id)), probe };
  }
  /**
   * Một model gõ tay là lời khai của người dùng, không phải kết quả dò: khi
   * endpoint không có đường dẫn `/models` (`discoveryState: 'failed'`, hoặc
   * `'degraded'` khi lần dò hỏng đó còn để lại danh sách cũ) thì id họ
   * tự khai vẫn phải định tuyến được — nếu không, cả luồng "gõ tay rồi Test"
   * dừng lại đúng ở lần Test đầu tiên. Mọi luật còn lại giữ nguyên: connection
   * phải bật, tài khoản phải `ready` (project của Antigravity phải `ready`),
   * model phải bật và `health !== 'unavailable'`; dòng do dò phát hiện vẫn cần
   * một lần dò thành công như trước.
   */
  validTarget(target) {
    const c = this.store.get('connection', target?.connectionId);
    if (!c?.enabled || c.authState !== 'ready') return false;
    if (c.providerId === 'antigravity' && c.projectState !== 'ready') return false;
    const model = c.models.find(m => m.id === target.modelId);
    if (!model?.enabled || model.health === 'unavailable') return false;
    if (c.discoveryState === 'ready') return true;
    // `degraded` là hình dạng khác của CÙNG một lần dò hỏng: catch giữ lại danh
    // sách cũ thay vì để connection trống. Một cú `Refresh models` hỏng lần thứ
    // hai không được biến id người dùng vừa khai (và vừa Test đạt) từ định tuyến
    // được thành 503.
    return model.source === 'custom' && (c.discoveryState === 'failed' || c.discoveryState === 'degraded');
  }
  alias(values, id = randomUUID()) {
    const old = this.store.get('alias', id);
    const alias = { ...old, ...values, id, name: label(values.name, old?.name || ''), enabled: values.enabled ?? old?.enabled ?? true };
    assert(/^[a-zA-Z][a-zA-Z0-9_.-]{0,79}$/.test(alias.name), 'Alias must start with a letter and contain only letters, numbers, dots, underscores or hyphens.');
    assert(!this.store.list('alias').some(a => a.id !== id && a.name === alias.name), 'Alias name is already used.');
    assert(['fallback', 'round_robin'].includes(alias.strategy), 'Choose fallback or round-robin.');
    assert(typeof alias.enabled === 'boolean', 'Enabled must be boolean.');
    assert(Array.isArray(alias.targets) && alias.targets.length > 0 && alias.targets.length <= 16, 'Choose 1–16 targets.');
    // Disabling a previously valid alias must still work after an account expires.
    assert(alias.targets.every(t => this.validTarget(t) || (!alias.enabled && old?.targets.some(o => o.connectionId === t?.connectionId && o.modelId === t?.modelId))), 'Each target must be enabled and discovered on an authorized connection.');
    assert(new Set(alias.targets.map(t => `${t.connectionId}/${t.modelId}`)).size === alias.targets.length, 'Alias targets must not be duplicated.');
    alias.targets = alias.targets.map(t => ({ connectionId: t.connectionId, modelId: t.modelId }));
    this.store.put('alias', alias); this.repairDefault(); return alias;
  }
  setDefault(value) {
    const v = { connectionId: value.connectionId || null, modelId: value.modelId || null, aliasId: value.aliasId || null };
    if (v.aliasId) { const alias = this.store.get('alias', v.aliasId); assert(alias?.enabled && alias.targets.some(t => this.validTarget(t)), 'Choose an enabled alias with an available target.'); v.connectionId = null; v.modelId = null; }
    else assert(this.validTarget(v), 'Choose an enabled model on an authorized connection.');
    return this.store.setDefault(v);
  }
  repairDefault() {
    const d = this.store.getDefault();
    const alias = d.aliasId ? this.store.get('alias', d.aliasId) : null;
    if (d.aliasId ? !alias?.enabled || !alias.targets.some(t => this.validTarget(t)) : d.connectionId && !this.validTarget(d)) this.store.setDefault({ connectionId: null, modelId: null, aliasId: null });
  }
  publicModels(key = null) {
    // BUG-4/R2: model records exported to clients carry the shared metadata.
    const described = m => ({ contextWindow: m.contextWindow ?? null, contextWindowSource: m.contextWindowSource ?? null, contextWindowReported: m.contextWindowReported ?? null, thinkingType: m.thinkingType ?? 'none', defaultThinking: m.defaultThinking ?? null, thinkingLevels: Array.isArray(m.thinkingLevels) ? m.thinkingLevels : [] });
    const direct = this.store.list('connection').flatMap(c => c.models.filter(m => this.validTarget({ connectionId: c.id, modelId: m.id })).map(m => ({ id: `${c.id}/${m.id}`, object: 'model', owned_by: c.providerId, name: m.name, ...described(m) })));
    const aliases = this.store.list('alias').filter(a => a.enabled && a.targets.some(t => this.validTarget(t))).map(a => ({ id: a.name, object: 'model', owned_by: 'boxfox' }));
    return [...direct, ...aliases].filter(m => !key || !key.allowedModels.length || key.allowedModels.includes(m.id));
  }
}
