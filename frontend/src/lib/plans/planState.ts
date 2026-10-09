/**
 * Trạng thái duyệt THẬT của một bản kế hoạch + bản chấm P1–P8, đọc từ sổ của harness.
 *
 * Vì sao không đọc từ container: nhãn "approved" hôm nay do `withPresentationStatuses` gán theo VỊ
 * TRÍ trong danh sách version (`types.ts`), còn `.reviews/` trong box thì rỗng — nên hai nhóm kế
 * hoạch cùng lúc hiện "approved" mà không có quyết định nào của người dùng, và hai kế hoạch mới
 * tinh nhận số v5/v6 chỉ vì bộ đếm version đọc mọi file trong `.plans/`. Bảng `plan_reviews` của
 * harness là nguồn duy nhất biết ai đã duyệt bản nào; `GET /api/agent/plans/status` trả trạng thái
 * đó kèm `reviewStale` và `evaluation` của đúng bản đang được hỏi.
 *
 * Mọi trường đều đọc phòng thủ: dữ liệu tới từ mạng, nên một trường thiếu phải thành "chưa biết",
 * không được thành một lời khẳng định (điểm ảo, "đã duyệt" ảo).
 *
 * Vòng 25 thêm mặt `verification` (phiên `plan-review` nào đã đọc bản này, lỗi kèm cách sửa) và
 * `ownership.sessionId` (phiên đang sở hữu bản kế hoạch). Cùng luật cũ: harness CHƯA trả trường nào
 * thì trường đó là "chưa biết" (`unknown`/`null`) — giao diện không được tự suy ra "chưa phản biện"
 * rồi khoá nút duyệt oan.
 */
import { agentApi, ApiError } from '../agentApi'

export const EVAL_DIMENSIONS = ['P1', 'P2', 'P3', 'P4', 'P5', 'P6', 'P7', 'P8'] as const
export type PlanEvalDimension = (typeof EVAL_DIMENSIONS)[number]
export type PlanEvalLevel = 0 | 1 | 2
export type PlanEvalLayer = 'oracle' | 'judge'
/** `plan_eval.verdict_for`: ≥13 đạt, 9–12 đạt có điều kiện, ≤8 chưa đạt. */
export type PlanEvalVerdict = 'pass' | 'conditional' | 'fail'

/** `plan_registry.GROUP_STATES` — chỉ bản MỚI NHẤT của nhóm quyết định trạng thái. */
export const PLAN_REVIEW_STATES = [
  'none',
  'draft',
  'submitted',
  'approved',
  'changes_requested',
  'unknown',
] as const
export type PlanReviewState = (typeof PLAN_REVIEW_STATES)[number]

export type PlanDecision = 'approved' | 'changes_requested'

/**
 * Mặt phản biện của một bản kế hoạch. `none` = chưa phiên `plan-review` nào đọc bản này; `ok` = đã
 * đọc và không còn lỗi; `revise` = đã đọc và còn lỗi phải sửa; `unknown` = harness không nói gì.
 */
export const PLAN_VERIFICATION_STATES = ['none', 'ok', 'revise'] as const
export type PlanVerificationState = (typeof PLAN_VERIFICATION_STATES)[number] | 'unknown'

/**
 * Công tắc cổng duyệt của harness (`BOXFOX_PLAN_VERIFY`): `enforce` = từ chối 409, `warn` = vẫn ghi
 * sổ nhưng kèm `approvalWarning`, `off` = không kiểm. Giao diện phải siết ĐÚNG bằng harness, nên nó
 * đọc công tắc này thay vì mặc định `enforce` rồi khoá oan một bản mà harness sẽ cho qua.
 */
export const PLAN_GATE_MODES = ['enforce', 'warn', 'off'] as const
export type PlanGateMode = (typeof PLAN_GATE_MODES)[number]

export interface PlanGate {
  verifyMode: PlanGateMode
  /** Giá trị env lạ bị harness hạ về mặc định — giữ chuỗi gốc để giao diện nói thật là "không hiểu". */
  verifyUnknown: string | null
  sourcesMode: PlanGateMode
  sourcesUnknown: string | null
}

/** Harness cũ không có khoá `gate` (KHÔNG phải "cổng mở"): `enforce` là hành vi cũ của nó. */
export const DEFAULT_PLAN_GATE: PlanGate = {
  verifyMode: 'enforce',
  verifyUnknown: null,
  sourcesMode: 'enforce',
  sourcesUnknown: null,
}

const PLAN_ISSUE_SEVERITIES = ['high', 'medium', 'low'] as const
/** Mức lỗi — `unknown` khi harness không khai; KHÔNG hạ xuống `low` cho dễ nhìn. */
export type PlanIssueSeverity = (typeof PLAN_ISSUE_SEVERITIES)[number] | 'unknown'

export interface PlanVerificationIssue {
  severity: PlanIssueSeverity
  text: string
  /** Cách sửa. VẮNG MẶT = harness không nói; giao diện ẩn dòng đó, không bịa. */
  fix?: string
  /** Mã lỗi của phiên phản biện (`step-not-measurable`, …). Vắng mặt thì không in mã nào. */
  code?: string
}

export interface PlanVerification {
  state: PlanVerificationState
  /** ISO lúc phiên phản biện trả kết quả. */
  at: string | null
  criticSessionId: string | null
  issues: PlanVerificationIssue[]
}

/** Phiên đang sở hữu bản kế hoạch — lượt chạy tiếp theo mở trong phiên này. */
export interface PlanOwnership {
  sessionId: string | null
}

/** `POST /api/agent/plans/review` bị chặn vì bản kế hoạch chưa qua phản biện (HTTP 409). */
export class PlanReviewBlockedError extends Error {
  readonly code: string
  readonly reason: string
  readonly remedy: string

  constructor(code: string, reason: string, remedy: string) {
    super(reason || code || 'Plan approval is blocked.')
    this.name = 'PlanReviewBlockedError'
    this.code = code
    this.reason = reason
    this.remedy = remedy
  }
}

/** Ngưỡng độ dài của `plan_eval.py` — dùng để nói "306.721 ký tự > 150.000" trên giao diện. */
export const PLAN_MAX_CHARS = 150_000
export const PLAN_WARN_CHARS = 40_000

export interface PlanEvaluation {
  identity: string
  version: number | null
  parentVersion: number | null
  /** `false` = lần ghi này bị cổng cứng chặn, file trong `.plans` giữ nguyên. */
  written: boolean
  rubric: string
  levels: Record<PlanEvalDimension, PlanEvalLevel | null>
  layer: Partial<Record<PlanEvalDimension, PlanEvalLayer>>
  total: number | null
  maxTotal: number
  /**
   * `hardGate` = MỌI cổng cứng đều đạt (cùng cực với `scripts/eval/rubric.py::hard_gate_ok`).
   * Giao diện KHÔNG được suy ra "bị chặn" từ trường này — dấu hiệu bị chặn là `gatesFailed`
   * và `rejected`, đúng như `Evaluation.to_payload` phát ra.
   */
  hardGate: boolean
  gatesFailed: PlanEvalDimension[]
  verdict: PlanEvalVerdict | null
  /** Mã từ chối: `plan-too-long`, `plan-repetitive`, `QUALITY`, … hoặc `null` nếu được ghi. */
  rejected: string | null
  measures: Record<string, unknown>
  evidence: { code: string; excerpt: string }[]
  warnings: string[]
  evaluatedAt: string | null
}

export interface PlanStatusReview {
  identity: string
  version: number | null
  decision: PlanDecision
  note: string
  source: string
  /** `time.time()` lúc ghi quyết định. */
  decidedAt: number | null
}

export interface PlanStatusReport {
  identity: string
  version: number | null
  state: PlanReviewState
  stateVersion: number | null
  review: PlanStatusReview | null
  reviewStale: boolean
  indexAvailable: boolean
  evaluation: PlanEvaluation | null
  verification: PlanVerification
  ownership: PlanOwnership
  /** Công tắc cổng duyệt harness đang chạy — giao diện siết đúng bằng nó, không đoán. */
  gate: PlanGate
}

/** Kết cục một lần đánh thức phiên sở hữu (`plan_wake`) — harness là bên nói, giao diện không đoán. */
export const PLAN_WAKE_STATES = ['opened', 'busy', 'duplicate', 'missing', 'failed'] as const
export type PlanWakeState = (typeof PLAN_WAKE_STATES)[number] | 'unknown'

export interface PlanWake {
  state: PlanWakeState
  code: string | null
  /** Câu giải thích NGUYÊN VĂN của harness; vắng mặt thì giao diện không bịa câu nào. */
  message: string | null
  sessionId: string | null
}

export interface PlanReviewOutcome {
  review: PlanStatusReview | null
  /** `false` = đã ghi vào sổ harness nhưng chưa chuyển được sang box; `null` = không đọc được. */
  forwarded: boolean | null
  /** `null` = harness không khai (bản cũ), KHÔNG phải "không ghi được". */
  recorded: boolean | null
  /**
   * Ba trạng thái: `true` = có lượt chạy mới được mở, `false` = không mở, `null` = harness không nói.
   * Mặc định về `false` sẽ biến "chưa biết" thành một lời khẳng định sai.
   */
  resumed: boolean | null
  turnId: string | null
  /**
   * Harness giải thích NGAY trong thân trả về vì sao mở/không mở được lượt (`opened|busy|duplicate|
   * missing|failed`) kèm câu chữ của chính nó. Bỏ trường này đi là bỏ lời giải thích thật, rồi giao
   * diện phải đoán từ `resumed` — `null` khi harness cũ không khai.
   */
  wake: PlanWake | null
  /** Chỉ có ở chế độ `warn`: harness đã cho qua một bản chưa đạt phản biện, kèm lý do. */
  approvalWarning: string | null
}

function readPlanGateMode(value: unknown, fallback: PlanGateMode): PlanGateMode {
  return PLAN_GATE_MODES.find((candidate) => candidate === value) ?? fallback
}

/** Chuẩn hoá `gate` của `GET /api/agent/plans/status`; thiếu khoá ⇒ hành vi cũ của harness = `enforce`. */
export function readPlanGate(raw: unknown): PlanGate {
  if (!isRecord(raw)) return DEFAULT_PLAN_GATE
  return {
    verifyMode: readPlanGateMode(raw.verifyMode, DEFAULT_PLAN_GATE.verifyMode),
    verifyUnknown: asText(raw.verifyUnknown),
    sourcesMode: readPlanGateMode(raw.sourcesMode, DEFAULT_PLAN_GATE.sourcesMode),
    sourcesUnknown: asText(raw.sourcesUnknown),
  }
}

/** Chuẩn hoá `wake` của hai route ghi quyết định/đánh thức; state lạ đọc là `unknown`, không đoán. */
export function readPlanWake(raw: unknown): PlanWake | null {
  if (!isRecord(raw)) return null
  const state = PLAN_WAKE_STATES.find((candidate) => candidate === raw.state)
  return {
    state: state ?? 'unknown',
    code: asText(raw.code),
    message: asText(raw.message),
    sessionId: asText(raw.sessionId),
  }
}

/** Hợp đồng tối thiểu mà `usePlanFiles` cần — test bơm bản giả, không cần mạng. */
export interface PlanStatusClient {
  read(identity: string, version: number | null): Promise<PlanStatusReport>
  submitReview(
    identity: string,
    version: number,
    decision: PlanDecision,
    note: string,
    workflow?: { revision: number; invocationId: string; contentHash: string },
  ): Promise<PlanReviewOutcome>
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function asText(value: unknown): string | null {
  return typeof value === 'string' ? value : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function asLevel(value: unknown): PlanEvalLevel | null {
  return value === 0 || value === 1 || value === 2 ? value : null
}

function isDimension(value: unknown): value is PlanEvalDimension {
  return typeof value === 'string' && (EVAL_DIMENSIONS as readonly string[]).includes(value)
}

function readLevels(raw: unknown): Record<PlanEvalDimension, PlanEvalLevel | null> {
  const source = isRecord(raw) ? raw : {}
  const levels = {} as Record<PlanEvalDimension, PlanEvalLevel | null>
  for (const dimension of EVAL_DIMENSIONS) levels[dimension] = asLevel(source[dimension])
  return levels
}

function readLayer(raw: unknown): Partial<Record<PlanEvalDimension, PlanEvalLayer>> {
  const source = isRecord(raw) ? raw : {}
  const layer: Partial<Record<PlanEvalDimension, PlanEvalLayer>> = {}
  for (const dimension of EVAL_DIMENSIONS) {
    const value = source[dimension]
    if (value === 'oracle' || value === 'judge') layer[dimension] = value
  }
  return layer
}

function readEvidence(raw: unknown): { code: string; excerpt: string }[] {
  if (!Array.isArray(raw)) return []
  const items: { code: string; excerpt: string }[] = []
  for (const entry of raw) {
    if (!isRecord(entry)) continue
    const code = asText(entry.code)
    const excerpt = asText(entry.excerpt)
    if (code && excerpt) items.push({ code, excerpt })
  }
  return items
}

/**
 * Chuẩn hoá `evaluation` của `GET /api/agent/plans/status`. Payload thật nằm ở `payload` (hàng bảng
 * `plan_evaluations`), nhưng lớp ngoài nhắc lại `total`/`verdict`/`evaluatedAt`; gộp hai lớp lại
 * (lớp trong thắng) để đọc được cả hai hình dạng thay vì im lặng trả về toàn `null`.
 */
export function readPlanEvaluation(raw: unknown): PlanEvaluation | null {
  if (!isRecord(raw)) return null
  const payload = isRecord(raw.payload) ? { ...raw, ...raw.payload } : raw
  const levels = readLevels(payload.levels)
  const known = EVAL_DIMENSIONS.map((dimension) => levels[dimension])
  const complete = known.every((level) => level !== null)
  const verdictRaw = asText(payload.verdict)
  const rejected = asText(payload.rejected)
  return {
    identity: asText(payload.identity) ?? '',
    version: asNumber(payload.version),
    parentVersion: asNumber(payload.parentVersion) ?? asNumber(payload.parent_version),
    written: payload.written === true,
    rubric: asText(payload.rubric) ?? '',
    levels,
    layer: readLayer(payload.layer),
    total:
      asNumber(payload.total) ??
      (complete ? known.reduce<number>((sum, level) => sum + (level ?? 0), 0) : null),
    maxTotal: asNumber(payload.maxTotal) ?? EVAL_DIMENSIONS.length * 2,
    hardGate: payload.hardGate === true,
    gatesFailed: Array.isArray(payload.gatesFailed)
      ? payload.gatesFailed.filter(isDimension)
      : [],
    verdict:
      verdictRaw === 'pass' || verdictRaw === 'conditional' || verdictRaw === 'fail'
        ? verdictRaw
        : null,
    rejected,
    measures: isRecord(payload.measures) ? payload.measures : {},
    evidence: readEvidence(payload.evidence),
    warnings: Array.isArray(payload.warnings)
      ? payload.warnings.filter((item): item is string => typeof item === 'string')
      : [],
    evaluatedAt: asText(payload.evaluatedAt),
  }
}

function readVerificationIssues(raw: unknown): PlanVerificationIssue[] {
  if (!Array.isArray(raw)) return []
  const issues: PlanVerificationIssue[] = []
  for (const entry of raw) {
    if (!isRecord(entry)) continue
    const text = asText(entry.text)
    if (!text) continue
    // Mức lạ/thiếu ⇒ `unknown`; thà nói "không rõ mức" còn hơn vẽ nó thành lỗi thấp.
    const severity = PLAN_ISSUE_SEVERITIES.find((candidate) => candidate === entry.severity) ?? 'unknown'
    const issue: PlanVerificationIssue = { severity, text }
    const fix = asText(entry.fix)
    if (fix) issue.fix = fix
    const code = asText(entry.code)
    if (code) issue.code = code
    issues.push(issue)
  }
  return issues
}

/**
 * Chuẩn hoá `verification` của `GET /api/agent/plans/status`. Harness cũ không có trường này ⇒
 * `state: 'unknown'` — giao diện KHÔNG được đọc thành `none` rồi khoá duyệt oan.
 */
export function readPlanVerification(raw: unknown): PlanVerification {
  const source = isRecord(raw) ? raw : {}
  const state = PLAN_VERIFICATION_STATES.find((candidate) => candidate === source.state)
  return {
    state: state ?? 'unknown',
    at: asText(source.at),
    criticSessionId: asText(source.criticSessionId),
    issues: readVerificationIssues(source.issues),
  }
}

export function readPlanStatusReview(raw: unknown): PlanStatusReview | null {
  if (!isRecord(raw)) return null
  const decision = raw.decision
  if (decision !== 'approved' && decision !== 'changes_requested') return null
  return {
    identity: asText(raw.identity) ?? '',
    version: asNumber(raw.version),
    decision,
    note: asText(raw.note) ?? '',
    source: asText(raw.source) ?? 'plan-tab',
    decidedAt: asNumber(raw.decidedAt),
  }
}

/** Chuẩn hoá thân của `GET /api/agent/plans/status`; `null` khi thân không phải một object. */
export function readPlanStatus(raw: unknown): PlanStatusReport | null {
  if (!isRecord(raw)) return null
  const state = PLAN_REVIEW_STATES.find((candidate) => candidate === raw.state)
  return {
    identity: asText(raw.identity) ?? '',
    version: asNumber(raw.version),
    // Trạng thái lạ (harness cũ hơn giao diện) đọc là `unknown`, không đoán thành `draft`.
    state: state ?? 'unknown',
    stateVersion: asNumber(raw.stateVersion),
    review: readPlanStatusReview(raw.review),
    reviewStale: raw.reviewStale === true,
    // Chỉ `false` tường minh mới là "không đọc được chỉ mục"; thiếu trường thì giữ giả định cũ.
    indexAvailable: raw.indexAvailable !== false,
    evaluation: readPlanEvaluation(raw.evaluation),
    verification: readPlanVerification(raw.verification),
    ownership: {
      sessionId: asText(isRecord(raw.ownership) ? raw.ownership.sessionId : null),
    },
    gate: readPlanGate(raw.gate),
  }
}

/**
 * 409 kèm `blocked: true` là "bị khoá vì chưa phản biện" — giữ NGUYÊN `code`/`reason`/`remedy` của
 * harness (không dịch lại, không viết lại); mọi lỗi khác đi đường cũ.
 */
function toPlanReviewError(error: unknown): unknown {
  if (!(error instanceof ApiError) || error.status !== 409 || !isRecord(error.body)) return error
  const body = error.body
  if (body.blocked !== true) return error
  return new PlanReviewBlockedError(
    asText(body.code) || error.code || 'PLAN_APPROVAL_UNVERIFIED',
    asText(body.reason) ?? '',
    asText(body.remedy) ?? '',
  )
}

/** `306.721` — nhóm nghìn kiểu Việt Nam, cùng cách mockup đang ghi số đo. */
export function planCount(value: number | null | undefined): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, '.')
}

/** `20/09 20:57` theo giờ máy — epoch giây (`decidedAt`) hoặc chuỗi ISO (`evaluatedAt`). */
export function planStamp(value: number | string | null | undefined): string | null {
  if (typeof value !== 'number' && typeof value !== 'string') return null
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${pad(date.getDate())}/${pad(date.getMonth() + 1)} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** Số đo trong `measures` (payload không hứa kiểu, nên đọc phòng thủ). */
export function planMeasure(measures: Record<string, unknown>, key: string): number | null {
  return asNumber(measures[key])
}

export function planMeasureText(measures: Record<string, unknown>, key: string): string | null {
  return asText(measures[key])
}

/**
 * `POST /api/agent/plans/review` + `GET /api/agent/plans/status` qua proxy `/api/agent`.
 *
 * `sessionId` (tuỳ chọn) là phiên đang mở tab. Host mode cần nó để đọc `.plans` trong ĐÚNG folder dự
 * án của phiên; Docker bỏ qua. Chỗ gọi cũ không truyền gì vẫn chạy nguyên.
 */
export class HarnessPlanStatusClient implements PlanStatusClient {
  constructor(private readonly sessionId?: string) {}

  async read(identity: string, version: number | null): Promise<PlanStatusReport> {
    const query = new URLSearchParams({ identity })
    if (version !== null) query.set('version', String(version))
    if (this.sessionId) query.set('sessionId', this.sessionId)
    const payload = await agentApi<unknown>(`/plans/status?${query.toString()}`)
    const report = readPlanStatus(payload)
    if (!report) throw new Error('The harness returned an unreadable plan status.')
    return report
  }

  async submitReview(
    identity: string,
    version: number,
    decision: PlanDecision,
    note: string,
    workflow?: { revision: number; invocationId: string; contentHash: string },
  ): Promise<PlanReviewOutcome> {
    let payload: unknown
    try {
      payload = await agentApi<unknown>('/plans/review', {
        identity, version, decision, note, ...workflow,
        ...(this.sessionId ? { sessionId: this.sessionId } : {}),
      })
    } catch (error) {
      throw toPlanReviewError(error)
    }
    const body = isRecord(payload) ? payload : {}
    return {
      review: readPlanStatusReview(body.review),
      forwarded: typeof body.forwarded === 'boolean' ? body.forwarded : null,
      recorded: typeof body.recorded === 'boolean' ? body.recorded : null,
      resumed: typeof body.resumed === 'boolean' ? body.resumed : null,
      turnId: asText(body.turnId),
      wake: readPlanWake(body.wake),
      approvalWarning: asText(body.approvalWarning),
    }
  }
}

export function createPlanStatusClient(sessionId?: string): PlanStatusClient {
  return new HarnessPlanStatusClient(sessionId)
}
