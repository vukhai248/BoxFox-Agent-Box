export type ProviderId = string
export type CapabilityEvidence = 'unknown' | 'reported' | 'verified' | 'unsupported'
export interface ProviderDefinition {
  id: ProviderId
  name: string
  authMethod: 'oauth' | 'api_key'
  icon: string
  protocol: string
  category?: 'oauth' | 'free' | 'api_key'
  discoveryClass?: 'account-live' | 'openai-compat' | 'provider-specific' | 'static-only'
  availability?: 'ready' | 'planned'
  implementationStatus?: 'ready' | 'experimental' | 'planned' | 'unavailable'
  runtimeAvailable?: boolean
  routerVisible?: boolean
  defaultEndpoint?: string
  authHint?: string
  authModes?: Array<'oauth' | 'device' | 'import' | 'api_key' | 'anonymous' | 'service_account'>
  riskNotice?: string
  capabilities?: { chat: boolean; streaming: boolean; tools: CapabilityEvidence; vision: CapabilityEvidence }
}
/**
 * The price a model is billed at, whatever its provenance. Every component is USD
 * per 1,000,000 tokens, `null` means the source published nothing for that
 * component, and `source` travels with the number so the UI can label an estimate
 * instead of showing it as something the provider reported.
 */
export interface ModelPricing {
  currency: 'USD'
  unit: 'per_million_tokens'
  input: number
  cachedInput: number | null
  cacheWriteInput?: number | null
  output: number
  source: 'manual' | 'ping' | 'documented'
  asOf?: string | null
  updatedAt?: number
}
export interface ProviderModel {
  id: string; name: string; enabled: boolean; source?: 'live' | 'static' | 'registry' | 'probe' | 'custom'; stale?: boolean; thinkingLevels?: string[];
  pricing?: ModelPricing | null;
  /** Số token router đang dùng cho model này; `null` khi không nguồn nào trả lời. */
  contextWindow?: number | null;
  /** Nguồn của con số đó: `manual` (người dùng khai) · `documented` (bảng của BoxFox) · `reported` (nhà cung cấp). */
  contextWindowSource?: 'manual' | 'documented' | 'reported' | null;
  /** Số nhà cung cấp đã công bố, chỉ có khi khác số đang dùng (để đối chiếu). */
  contextWindowReported?: number | null;
  upstreamModelId?: string; thinkingLevel?: string | null; quotaFamily?: 'gemini' | 'claude_gpt' | null; probeStatus?: 'registry' | 'passed' | 'fallback'; lastProbedAt?: string | null;
  /**
   * W12 — nguồn của TỪNG trường metadata, dùng đúng từ vựng đã có trong router:
   * `live` (payload provider), `documented` (bảng curated/tài liệu), `probe` (số đo của
   * router, có mốc), `static` (danh sách dự phòng khi discovery hỏng), `reported`
   * (context window lấy từ payload), `ping` (giá lấy từ endpoint models), `unknown`.
   * `source` của hàng chỉ nói nguồn inventory; đọc trường này trước khi coi một giá trị
   * là dữ liệu provider vừa công bố.
   */
  fieldSources?: Partial<Record<'inventory' | 'name' | 'thinking' | 'contextWindow' | 'pricing', 'live' | 'documented' | 'probe' | 'static' | 'reported' | 'ping' | 'unknown'>>;
  /** Nguồn của `thinkingLevels` (trùng `fieldSources.thinking`), kèm mốc và bằng chứng khi không phải dữ liệu live. */
  thinkingSource?: 'live' | 'documented' | 'probe' | 'unknown';
  thinkingAsOf?: string | null;
  /**
   * Bằng chứng `thinkingLevels` đã cũ (`opencode-capabilities.THINKING_EVIDENCE_MAX_AGE_DAYS`).
   * Router tính sẵn theo `asOf`; UI chỉ đọc, không tự đo tuổi — đồng hồ máy khách lệch
   * với máy chủ thì nhãn "(cũ)" sẽ sai.
   */
  thinkingStale?: boolean;
  thinkingEvidence?: string | null;
  health?: 'unknown' | 'ready' | 'unavailable' | 'rate_limited' | 'slow' | 'failed'
  lastProbe?: { status: 'passed' | 'failed'; httpStatus: number; latencyMs: number; testedAt: string; error: string | null }
  capabilities: Record<'streaming' | 'tools' | 'vision', CapabilityEvidence> & { reasoning?: CapabilityEvidence }
}
/**
 * One key of a connection's ring. The router sends the label, the leading characters of
 * the secret (`prefix`) and the state it observed — never the secret itself. `state` is
 * the router's verdict: `cooling`/`exhausted` mean parked after a 429 (`exhausted` when
 * the provider's message named a quota), `error` means the last call failed for another
 * reason. The UI renders whichever value arrives and never derives one of its own.
 */
export interface ConnectionKey {
  id: string; label: string; prefix: string; state: 'ready' | 'cooling' | 'exhausted' | 'error';
  cooldownUntil: number | null; resetAt: number | null;
  lastErrorCode: string | null; lastErrorMessage: string | null; lastUsedAt: number | null;
}
export interface ProviderConnection {
  id: string; providerId: ProviderId; name: string; endpoint: string | null; email: string | null; accountLabel: string | null; projectId: string | null;
  revision: number; enabled: boolean; credentialPresent: boolean;
  authState: 'required' | 'ready' | 'expired'; projectState: 'not_applicable' | 'pending' | 'ready' | 'required' | 'failed';
  discoveryState: 'pending' | 'ready' | 'degraded' | 'failed'; inferenceState: 'unknown' | 'ready' | 'failed';
  models: ProviderModel[]; lastTestedAt: string | null; lastModelSyncAt?: string | null; nextModelSyncAt?: string | null; autoSync?: boolean;
  /** `included` means a subscription account: usage records no token price, and the cost cell says so. */
  costMode?: 'metered' | 'included';
  /** Epoch ms of the last discovery attempt, so a failed listing can say when it was tried. */
  lastDiscoveryAttemptAt?: number | null; error: string | null; quota: ProviderQuota | null;
  /** Ordered key ring, first key tried first. Absent while the router does not decorate
   *  the connection — that absence is the legacy single-key shape the card still renders. */
  keys?: ConnectionKey[];
  /** Key that served the last attempt, `null` when the router has not recorded one. */
  activeKeyId?: string | null;
}
export interface ProviderQuota {
  updatedAt: string; plan?: string | null; models: Array<{ modelId: string; upstreamModelId?: string; quotaFamily?: 'gemini' | 'claude_gpt' | null; remainingFraction: number | null; resetAt: string | null; source?: string }>;
  weekly?: Array<{ id: string; name: string; remainingFraction: number | null; resetAt: string | null }>;
  consumption: unknown | null
}
export interface RouteTarget { connectionId: string; modelId: string }
export interface RouterAlias { id: string; name: string; strategy: 'fallback' | 'round_robin'; targets: RouteTarget[]; enabled: boolean; error?: string | null }
export interface ProviderRoutingConfig { id: ProviderId; roundRobin: boolean; connectionOrder: string[] }
export interface ProviderDefault { connectionId: string | null; modelId: string | null; aliasId: string | null }
export interface RouterClientKey { id: string; name: string; prefix: string; allowedModels: string[]; enabled: boolean; createdAt: string; lastUsedAt: string | null }
export interface RouterUsage {
  id: string; requestId: string; connectionId: string | null; modelId: string | null; aliasId: string | null; clientKeyId: string | null;
  status: 'passed' | 'failed' | 'cancelled'; latencyMs: number; inputTokens: number | null; cachedTokens: number | null; cacheCreationTokens: number | null; reasoningTokens: number | null; outputTokens: number | null; totalTokens: number | null; cost: number | null;
  /** Where the stored `cost` came from; `null` on a row recorded before costs carried a basis. */
  costBasis?: 'reported' | 'ping' | 'documented' | 'manual' | null; estimated?: boolean;
  error: string | null; createdAt: string;
}
/**
 * One search source a user may enter a key for, as the router describes it. The view
 * never carries the raw key: `prefix` is the leading characters the router is willing
 * to show, and the secret itself only travels back through an explicit reveal call.
 * `requires`/`optional` name the fields the entry needs (`apiKey`, `endpoint`,
 * `accountId`), and `envKeys` names the host environment variables that keep the same
 * provider working with no entry at all.
 */
export type SearchProviderId = 'brave' | 'tavily' | 'exa' | 'parallel' | 'firecrawl' | 'searxng' | 'cloudflare' | 'custom'
export interface SearchProviderView {
  id: SearchProviderId; name: string; requires: string[]; optional: string[]; envKeys: string[]
  icon: string | null; credentialPresent: boolean; hasSecret: boolean; prefix: string | null
  endpoint: string | null; accountId: string | null; lastTestedAt: string | null
  lastTest: { status: 'passed' | 'failed'; httpStatus: number | null; latencyMs: number | null; code: string | null; message: string | null } | null
}
/** The search section of the router snapshot. `revision` moves on every write, which is
 *  what lets the harness cache a resolved source without ever reusing a stale one. */
export interface SearchSnapshot { activeProviderId: SearchProviderId | null; revision: number; providers: SearchProviderView[] }
/** The verdict of one test call; `sample` is the first result the provider answered with. */
export interface SearchTestResult { ok: boolean; providerId: string; status: number | null; latencyMs: number | null; code: string | null; message: string | null; sample: { title: string; url: string } | null }
export interface ProviderSnapshot { providers: ProviderDefinition[]; connections: ProviderConnection[]; providerConfigs?: ProviderRoutingConfig[]; aliases: RouterAlias[]; defaultRoute: ProviderDefault; keys: RouterClientKey[]; usage: RouterUsage[]; health: { status: 'ok'; version: string }; /** Absent while the running router predates the search surface — the Web Search tab says so instead of crashing. */ search?: SearchSnapshot }
export interface OAuthAttempt {
  id: string;
  connectionId: string;
  providerId?: string;
  flowType?: 'authorization_code' | 'device_code';
  status: 'pending' | 'exchanging' | 'completed' | 'failed' | 'cancelled' | 'expired';
  authorizationUrl: string;
  userCode?: string | null;
  verificationUri?: string | null;
  expiresAt: string;
  error: string | null;
}
export interface RouterRequestMeta { requestId: string; connectionId: string; modelId: string; aliasId: string | null }
