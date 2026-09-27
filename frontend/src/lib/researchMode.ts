/**
 * Dữ liệu thuần của chế độ `/research` (P4 — giao diện).
 *
 * Vì sao tách khỏi component: backend P1/P2/P3 đang chạy song song và trường nào chưa gửi thì
 * giao diện phải render như "không có", KHÔNG được ném. Mọi hàm ở đây đọc `unknown` và trả về
 * một shape đã chuẩn hoá, để component không phải `as` và cũng không phải `try/catch`.
 *
 * Tên trường bám đúng hợp đồng đã đông cứng ở `/code/.plans/p23-interfaces.md` §0 và
 * `/code/.plans/v2-research-mode-overhaul.md` §5.12.
 */

import type { TKey } from '../i18n/context'

// ── Đọc giá trị an toàn ────────────────────────────────────────────────────

export type Json = Record<string, unknown>

export function asRecord(value: unknown): Json {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Json) : {}
}

export function asString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback
}

export function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export function asBool(value: unknown): boolean {
  return value === true
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asStringArray(value: unknown): string[] {
  return asArray(value).map((item) => (typeof item === 'string' ? item : '')).filter(Boolean)
}

// ── Chế độ (session.config.researchMode) ───────────────────────────────────

export interface ResearchMode {
  on: boolean
  since: string
  /** `'toggle'` hoặc `'command'` — chỉ để hiển thị nguồn vào. */
  enteredBy: string
  activeRunId: string
  revision: number
  /**
   * `researchId -> version` của mọi hồ sơ ĐÃ bàn giao sang lượt main. Backend ghi vào chính khối
   * `session.config.researchMode` (`runtime.mark_handoff_delivered`) và giao một lần cho mỗi phiên
   * bản hồ sơ. Giao diện cần nó để nút \"Dùng cho plan\" chỉ gửi ĐÚNG MỘT lần.
   */
  handoffDeliveredVersion: Record<string, string>
}

export const RESEARCH_MODE_OFF: ResearchMode = {
  on: false,
  since: '',
  enteredBy: '',
  activeRunId: '',
  revision: 0,
  handoffDeliveredVersion: {},
}

/** Đọc `session.config.researchMode`; thiếu/`null` ⇒ chế độ tắt (không bao giờ ném). */
export function readResearchMode(config: unknown): ResearchMode {
  const value = asRecord(asRecord(config).researchMode)
  return {
    on: asBool(value.on),
    since: asString(value.since),
    enteredBy: asString(value.enteredBy),
    activeRunId: asString(value.activeRunId),
    revision: asNumber(value.revision) ?? 0,
    handoffDeliveredVersion: readHandoffVersions(value.handoffDeliveredVersion),
  }
}

/** `researchId -> version` bàn giao: chỉ nhận chữ/số, ép về chuỗi, bỏ mọi giá trị khác. */
function readHandoffVersions(value: unknown): Record<string, string> {
  const raw = asRecord(value)
  const versions: Record<string, string> = {}
  for (const [researchId, item] of Object.entries(raw)) {
    if (typeof item === 'string') versions[researchId] = item
    else if (typeof item === 'number' && Number.isFinite(item)) versions[researchId] = String(item)
  }
  return versions
}

// ── Lời hỏi nhiều câu (`research_prompt`) ──────────────────────────────────

export type ResearchPromptKind = 'interview' | 'scope-change' | 'exit-choice' | 'out-of-scope' | 'budget'

export interface ResearchPromptOption {
  id: string
  label: string
  /** Cái giá của lựa chọn ("+8 phút") — chỉ hiện khi server gửi. */
  cost: string | null
}

export interface ResearchPromptQuestion {
  id: string
  text: string
  why: string
  options: ResearchPromptOption[]
  allowFreeText: boolean
  affects: string[]
  required: boolean
  blocking: boolean
  /** Câu đã trả lời (mục `confirmed` của thẻ phạm vi) — `null` khi còn mở. */
  answer: { text: string; optionId: string | null } | null
}

export interface ResearchPrompt {
  promptId: string
  researchId: string
  kind: ResearchPromptKind
  revision: number
  blocking: boolean
  createdAt: string
  status: 'open' | 'answered' | 'dismissed'
  questions: ResearchPromptQuestion[]
  actions: string[]
  note: string
}

const PROMPT_KINDS: ResearchPromptKind[] = ['interview', 'scope-change', 'exit-choice', 'out-of-scope', 'budget']

function readPromptKind(value: unknown): ResearchPromptKind {
  const raw = asString(value)
  return (PROMPT_KINDS as string[]).includes(raw) ? (raw as ResearchPromptKind) : 'interview'
}

export function readPrompt(value: unknown): ResearchPrompt | null {
  const raw = asRecord(value)
  const promptId = asString(raw.promptId)
  if (!promptId) return null
  const status = asString(raw.status, 'open')
  return {
    promptId,
    researchId: asString(raw.researchId),
    kind: readPromptKind(raw.kind),
    revision: asNumber(raw.revision) ?? 0,
    blocking: raw.blocking === undefined ? true : asBool(raw.blocking),
    createdAt: asString(raw.createdAt),
    status: status === 'answered' || status === 'dismissed' ? status : 'open',
    questions: asArray(raw.questions).map(readPromptQuestion).filter((item): item is ResearchPromptQuestion => item !== null),
    actions: asStringArray(raw.actions),
    note: asString(raw.note),
  }
}

function readPromptQuestion(value: unknown): ResearchPromptQuestion | null {
  const raw = asRecord(value)
  const id = asString(raw.id)
  if (!id) return null
  const answerRaw = asRecord(raw.answer)
  const answerText = asString(answerRaw.text)
  return {
    id,
    text: asString(raw.text),
    why: asString(raw.why),
    options: asArray(raw.options)
      .map((option) => {
        const item = asRecord(option)
        const optionId = asString(item.id)
        if (!optionId) return null
        const cost = asString(item.cost)
        return { id: optionId, label: asString(item.label), cost: cost || null }
      })
      .filter((item): item is ResearchPromptOption => item !== null),
    allowFreeText: raw.allowFreeText === undefined ? true : asBool(raw.allowFreeText),
    affects: asStringArray(raw.affects),
    required: raw.required === undefined ? true : asBool(raw.required),
    blocking: raw.blocking === undefined ? true : asBool(raw.blocking),
    answer: answerText ? { text: answerText, optionId: asString(answerRaw.optionId) || null } : null,
  }
}

/** Mọi lời hỏi còn mở của một run. */
export function openPrompts(prompts: readonly ResearchPrompt[]): ResearchPrompt[] {
  return prompts.filter((prompt) => prompt.status === 'open')
}

/** Lời hỏi đầu tiên theo thứ tự ưu tiên hiển thị (thoát mode trước, rồi tới phỏng vấn). */
export function preferredPrompt(prompts: readonly ResearchPrompt[], kind: ResearchPromptKind): ResearchPrompt | null {
  return openPrompts(prompts).find((prompt) => prompt.kind === kind) ?? null
}

// ── Thẻ phạm vi (`scope`) ──────────────────────────────────────────────────

export interface ScopeEntry {
  text: string
  status: 'confirmed' | 'assumed'
}

export interface ScopeQuestion {
  id: string
  text: string
  importance: string
  status: string
}

export interface ScopeOpenQuestion {
  id: string
  text: string
  blocking: boolean
  affects: string[]
  answer: string
  promptId: string
}

export interface ScopeBudget {
  proposedSeconds: number | null
  hardCeilingSeconds: number | null
  approved: boolean
  bigJob: boolean
}

export interface ScopeTimePolicy {
  velocity: string
  foundational: string
  reason: string
  status: string
  /** Ghi chú khi `velocity` gửi lên không hợp lệ (server giữ giá trị cũ) — hiện cho người dùng. */
  note: string
}

/** Cửa sổ thời gian do RUNTIME suy từ `timePolicy.velocity` + `surveyDate` (P2 §7.3). */
export interface ScopeWindow {
  velocity: string
  days: number | null
  start: string
  end: string
}

export interface ResearchScope {
  revision: number
  goal: ScopeEntry | null
  purpose: ScopeEntry | null
  jobKinds: string[]
  questions: ScopeQuestion[]
  timePolicy: ScopeTimePolicy | null
  surveyDate: string
  window: ScopeWindow | null
  sourceKinds: string[]
  exclusions: ScopeEntry[]
  outputs: string[]
  depth: string
  tier: number
  budget: ScopeBudget | null
  openQuestions: ScopeOpenQuestion[]
}

function readScopeEntry(value: unknown): ScopeEntry | null {
  if (value === undefined || value === null || value === '') return null
  const raw = asRecord(value)
  const text = typeof value === 'string' ? value : asString(raw.text)
  if (!text) return null
  return { text, status: asString(raw.status) === 'confirmed' ? 'confirmed' : 'assumed' }
}

function readScopeEntryList(value: unknown): ScopeEntry[] {
  return asArray(value)
    .map(readScopeEntry)
    .filter((item): item is ScopeEntry => item !== null)
}

export function readScope(value: unknown): ResearchScope | null {
  if (value === undefined || value === null) return null
  const raw = asRecord(value)
  if (Object.keys(raw).length === 0) return null
  const budgetRaw = asRecord(raw.budget)
  const hasBudget = Object.keys(budgetRaw).length > 0
  const timeRaw = asRecord(raw.timePolicy)
  const hasTime = Object.keys(timeRaw).length > 0
  return {
    revision: asNumber(raw.revision) ?? 0,
    goal: readScopeEntry(raw.goal),
    purpose: readScopeEntry(raw.purpose),
    jobKinds: asStringArray(raw.jobKinds),
    questions: asArray(raw.questions).map((item) => {
      const question = asRecord(item)
      return {
        id: asString(question.id),
        text: asString(question.text),
        importance: asString(question.importance, 'medium'),
        status: asString(question.status, 'unexplored'),
      }
    }),
    timePolicy: hasTime
      ? {
          velocity: asString(timeRaw.velocity),
          foundational: asString(timeRaw.foundational),
          reason: asString(timeRaw.reason),
          status: asString(timeRaw.status),
          note: asString(timeRaw.note),
        }
      : null,
    surveyDate: asString(raw.surveyDate),
    window: (() => {
      const windowRaw = asRecord(raw.window)
      if (Object.keys(windowRaw).length === 0) return null
      return {
        velocity: asString(windowRaw.velocity),
        days: asNumber(windowRaw.days),
        start: asString(windowRaw.start),
        end: asString(windowRaw.end),
      }
    })(),
    sourceKinds: asStringArray(raw.sourceKinds),
    exclusions: readScopeEntryList(raw.exclusions),
    outputs: asStringArray(raw.outputs),
    depth: asString(raw.depth),
    tier: asNumber(raw.tier) ?? 0,
    budget: hasBudget
      ? {
          proposedSeconds: asNumber(budgetRaw.proposedSeconds),
          hardCeilingSeconds: asNumber(budgetRaw.hardCeilingSeconds),
          approved: asBool(budgetRaw.approved),
          bigJob: asBool(budgetRaw.bigJob),
        }
      : null,
    openQuestions: asArray(raw.openQuestions).map((item) => {
      const question = asRecord(item)
      const answer = asRecord(question.answer)
      return {
        id: asString(question.id),
        text: asString(question.text),
        blocking: question.blocking === undefined ? true : asBool(question.blocking),
        affects: asStringArray(question.affects),
        answer: asString(answer.text),
        promptId: asString(question.promptId),
      }
    }),
  }
}

/** Danh sách "Bạn đã xác nhận" — mục có `status: 'confirmed'` của thẻ phạm vi. */
export function confirmedItems(scope: ResearchScope | null): ScopeEntry[] {
  if (!scope) return []
  const items: ScopeEntry[] = []
  if (scope.goal?.status === 'confirmed') items.push(scope.goal)
  if (scope.purpose?.status === 'confirmed') items.push(scope.purpose)
  for (const item of scope.exclusions) if (item.status === 'confirmed') items.push(item)
  return items
}

/** Danh sách "Giả định của agent" — mục còn `assumed` của thẻ phạm vi. */
export function assumedItems(scope: ResearchScope | null): ScopeEntry[] {
  if (!scope) return []
  const items: ScopeEntry[] = []
  if (scope.goal?.status === 'assumed') items.push(scope.goal)
  if (scope.purpose?.status === 'assumed') items.push(scope.purpose)
  for (const item of scope.exclusions) if (item.status === 'assumed') items.push(item)
  return items
}

/** Còn câu chặn nào chưa trả lời (nút "Bắt đầu" khoá cho tới khi hết). */
export function blockingOpenQuestions(scope: ResearchScope | null): ScopeOpenQuestion[] {
  return (scope?.openQuestions ?? []).filter((item) => item.blocking && !item.answer)
}

// ── Bảy bước của run ───────────────────────────────────────────────────────

export type ResearchStepKey = 'clarify' | 'plan' | 'search' | 'read' | 'synthesize' | 'critique' | 'done'

/** Bảy bước hiển thị của `run-status-timeline.html`, theo đúng thứ tự. */
export const RESEARCH_STEPS: ResearchStepKey[] = [
  'clarify',
  'plan',
  'search',
  'read',
  'synthesize',
  'critique',
  'done',
]

/** Pha của backend → bước hiển thị. Pha lạ rơi về `clarify` (không bao giờ ném). */
const PHASE_STEP: Record<string, ResearchStepKey> = {
  clarifying: 'clarify',
  scoping: 'clarify',
  planning: 'plan',
  searching: 'search',
  reading: 'read',
  analyzing: 'read',
  synthesizing: 'synthesize',
  // `revising` là pha mở ra sau một phán quyết `revise` (§5.2: "Tổng hợp = `synthesizing` +
  // `revising`"): bước hiển thị vẫn là Tổng hợp. Thiếu hàng này thì `stepForPhase` rơi về
  // `clarify` và thanh tiến trình của một run vừa kiểm chứng xong nhảy về bước 0 (đợt soát
  // `3dc745f`, finding 1).
  revising: 'synthesize',
  // `deep-reading` là tên pha trong bảng §5.2 (bước hiển thị `read`); chưa có đường nào ghi nó,
  // nhưng để sẵn ở đây thì một người ghi sau không vô tình vẽ nó thành bước 0.
  'deep-reading': 'read',
  // `verifying` (claim verifier + coverage reviewer) và `critiquing` (phản biện) là hai pha của
  // cùng một bước hiển thị theo bảng pha §5.2 (line 369).
  verifying: 'critique',
  critiquing: 'critique',
  reviewing: 'critique',
  completed: 'done',
  done: 'done',
  cancelled: 'done',
}

export function stepForPhase(phase: string): ResearchStepKey {
  return PHASE_STEP[phase] ?? 'clarify'
}

/** Chỉ số (0-based) của bước đang chạy; `-1` khi run đã dừng hẳn ở ngoài luồng. */
export function activeStepIndex(phase: string, status: string): number {
  if (status === 'completed' || status === 'cancelled') return RESEARCH_STEPS.length - 1
  return RESEARCH_STEPS.indexOf(stepForPhase(phase))
}

/** Nhãn ngắn của run ("R-118") — suy từ `research_id`, không phải dữ liệu mới. */
export function runLabel(researchId: string): string {
  const compact = researchId.replace(/[^0-9a-z]/gi, '')
  if (!compact) return researchId
  return `R-${compact.slice(-5).toUpperCase()}`
}

// ── Trạng thái run ─────────────────────────────────────────────────────────

export type ResearchJobStatus =
  | 'scoping'
  | 'researching'
  | 'verifying'
  | 'synthesizing'
  | 'critiquing'
  | 'needs_user'
  | 'paused'
  | 'partial'
  | 'completed'
  | 'cancelled'

export interface ResearchJobQuestion {
  id: string
  text: string
  importance: string
  status: string
  note: string
}

export interface ResearchBranch {
  sessionId: string
  questionId: string
  status: string
  goal: string
}

export interface ResearchDossier {
  relativePath: string
  version: number
  gate: string
  critique: string
}

export interface ResearchReview {
  version: number
  mode: string
  verdict: string
}

export interface ResearchEvidenceRow {
  rowId: string
  claim: string
  url: string
  excerpt: string
  status: string
  accessLevel: string
  publishedAt: string
  originCluster: string
  relation: string
  confidence: string
}

export interface ResearchFacet {
  id: string
  label: string
  kind: string
  status: string
  evidenceCount: number
  questionId: string
}

/** Bản bao phủ của run (P2 §5.5) — server có thể chưa gửi ⇒ mọi trường đọc mềm. */
export interface ResearchCoverage {
  counts: Record<string, number>
  unexplored: string[]
  facets: ResearchFacet[]
}

export interface ResearchJob {
  researchId: string
  sessionId: string
  revision: number
  status: ResearchJobStatus
  phase: string
  origin: string
  background: boolean
  scopeRevision: number
  usedSeconds: number
  remainingSeconds: number
  budgetSeconds: number
  tier: number
  goal: string
  output: string
  methods: string[]
  questions: ResearchJobQuestion[]
  findings: string[]
  blockedSources: { url: string; impact: string }[]
  branches: ResearchBranch[]
  evidence: ResearchEvidenceRow[]
  dossier: ResearchDossier | null
  reviews: ResearchReview[]
  /** Bản bao phủ facet — P2 ghi vào `state.coverage`/`research_status`; vắng ⇒ mọi trường rỗng. */
  coverage: ResearchCoverage
  prompts: ResearchPrompt[]
  scope: ResearchScope | null
}

/** Run chưa kết thúc (đang chạy, chờ người dùng, tạm dừng, hoặc dở dang). */
export function jobIsActive(job: ResearchJob): boolean {
  return job.status !== 'completed' && job.status !== 'cancelled'
}

export function jobIsRunningInBackground(job: ResearchJob): boolean {
  return job.background && jobIsActive(job)
}

/**
 * Sắc thái hiển thị của trạng thái run — nguồn DUY NHẤT cho màu badge ở mọi chỗ vẽ trạng thái.
 *
 * `warn` (chờ người dùng) · `brand` (đang chạy) · `muted` (tạm dừng/dở dang/đã huỷ) · `done` (xong).
 */
export type ResearchStatusTone = 'warn' | 'brand' | 'muted' | 'done'

/** Lớp Tailwind của badge trạng thái run — nguồn DUY NHẤT cho màu badge ở mọi nơi vẽ trạng thái. */
export const STATUS_TONE_CLASS: Record<ResearchStatusTone, string> = {
  warn: 'bg-amber-500/15 text-amber-300',
  brand: 'bg-brand/15 text-brand',
  muted: 'bg-zinc-500/15 text-muted',
  done: 'bg-emerald-500/15 text-emerald-300',
}

/** Run đang tạm dừng hoặc dở dang — hiện nút "Tiếp tục" thay cho "Tạm dừng". */
export function jobIsSuspendable(job: ResearchJob): boolean {
  return job.status === 'paused' || job.status === 'partial'
}

/**
 * Trạng thái run → khoá i18n. Mọi chỗ vẽ trạng thái PHẢI đi qua đây: trước đây `ResearchPanel` và
 * `ScopeCard` tự viết `jobIsActive ? statusRunning : statusDone`, nên một run `paused`/`partial` bị
 * vẽ nhầm thành ĐANG CHẠY (D-3).
 */
export function jobStatusKey(job: ResearchJob): TKey {
  switch (job.status) {
    case 'needs_user':
      return 'research.statusNeedsUser'
    case 'paused':
      return 'research.statusPaused'
    case 'partial':
      return 'research.statusPartial'
    case 'cancelled':
      return 'research.statusCancelled'
    case 'completed':
      return 'research.statusDone'
    default:
      return 'research.statusRunning'
  }
}

/** Trạng thái run → sắc thái badge (đi kèm `jobStatusKey`). */
export function jobStatusTone(job: ResearchJob): ResearchStatusTone {
  switch (job.status) {
    case 'needs_user':
      return 'warn'
    case 'paused':
    case 'partial':
    case 'cancelled':
      return 'muted'
    case 'completed':
      return 'done'
    default:
      return 'brand'
  }
}

function readCoverage(value: unknown): ResearchCoverage {
  const raw = asRecord(value)
  const countsRaw = asRecord(raw.counts)
  const counts: Record<string, number> = {}
  for (const [key, item] of Object.entries(countsRaw)) {
    const numeric = asNumber(item)
    if (numeric !== null) counts[key] = numeric
  }
  return {
    counts,
    unexplored: asStringArray(raw.unexplored),
    facets: asArray(raw.facets).map((item) => {
      const facet = asRecord(item)
      return {
        id: asString(facet.facetId) || asString(facet.id),
        label: asString(facet.label),
        kind: asString(facet.kind),
        status: asString(facet.status, 'unexplored'),
        evidenceCount: asNumber(facet.evidenceCount) ?? asNumber(facet.evidence_count) ?? 0,
        questionId: asString(facet.questionId) || asString(facet.question_id),
      }
    }),
  }
}

function readEvidenceRow(value: unknown): ResearchEvidenceRow {
  const raw = asRecord(value)
  return {
    rowId: asString(raw.rowId),
    claim: asString(raw.claim),
    url: asString(raw.url),
    excerpt: asString(raw.excerpt),
    status: asString(raw.status),
    accessLevel: asString(raw.accessLevel),
    publishedAt: asString(raw.publishedAt),
    originCluster: asString(raw.originCluster),
    relation: asString(raw.relation),
    confidence: asString(raw.confidence),
  }
}

const JOB_STATUSES: ResearchJobStatus[] = [
  'scoping',
  'researching',
  'verifying',
  'synthesizing',
  'critiquing',
  'needs_user',
  'paused',
  'partial',
  'completed',
  'cancelled',
]

function readJobStatus(value: unknown): ResearchJobStatus {
  const raw = asString(value)
  return (JOB_STATUSES as string[]).includes(raw) ? (raw as ResearchJobStatus) : 'scoping'
}

/**
 * Chuẩn hoá một hàng job (`GET /jobs` hoặc `GET /jobs/{id}`).
 *
 * Hai tuyến trả độ sâu khác nhau, nên hàm này chấp nhận cả hai: trường thiếu ⇒ giá trị rỗng,
 * KHÔNG ném, để hàng `jobs` ở danh sách vẫn vẽ được dù server chưa gửi chi tiết.
 */
export function readJob(value: unknown): ResearchJob {
  const raw = asRecord(value)
  const state = asRecord(raw.state)
  const stateScope = readScope(state.scope)
  const stateQuestions = asArray(state.questions)
  const questions = (stateQuestions.length ? stateQuestions : asArray(raw.questions)).map((item) => {
    const question = asRecord(item)
    return {
      id: asString(question.id),
      text: asString(question.text),
      importance: asString(question.importance, 'medium'),
      status: asString(question.status, 'unexplored'),
      note: asString(question.note),
    }
  })
  const dossierRaw = asRecord(raw.dossier)
  const hasDossier = Object.keys(dossierRaw).length > 0
  return {
    researchId: asString(raw.research_id) || asString(raw.researchId),
    sessionId: asString(raw.session_id),
    revision: asNumber(raw.revision) ?? 0,
    status: readJobStatus(raw.status),
    phase: asString(raw.phase) || asString(state.phase),
    origin: asString(raw.origin) || asString(state.origin),
    background: asBool(state.background) || asBool(raw.background),
    scopeRevision: asNumber(raw.scopeRevision) ?? stateScope?.revision ?? 0,
    usedSeconds: asNumber(raw.usedSeconds) ?? 0,
    remainingSeconds: asNumber(raw.remainingSeconds) ?? 0,
    budgetSeconds: asNumber(state.budgetSeconds) ?? 0,
    tier: asNumber(state.tier) ?? stateScope?.tier ?? 0,
    goal: asString(state.goal),
    output: asString(state.output),
    methods: asStringArray(state.methods),
    questions,
    findings: asStringArray(state.findings),
    blockedSources: asArray(state.blockedSources).map((item) => {
      const source = asRecord(item)
      return { url: asString(source.url), impact: asString(source.impact) }
    }),
    branches: asArray(raw.branches).map((item) => {
      const branch = asRecord(item)
      return {
        sessionId: asString(branch.session_id),
        questionId: asString(branch.questionId),
        status: asString(branch.status),
        goal: asString(branch.goal),
      }
    }),
    evidence: asArray(raw.evidence).map(readEvidenceRow),
    dossier: hasDossier
      ? {
          relativePath: asString(dossierRaw.relative_path) || asString(dossierRaw.relativePath),
          version: asNumber(dossierRaw.version) ?? 0,
          gate: asString(dossierRaw.gate),
          critique: asString(dossierRaw.critique),
        }
      : null,
    reviews: asArray(raw.reviews).map((item) => {
      const review = asRecord(item)
      return {
        version: asNumber(review.version) ?? 0,
        mode: asString(review.mode),
        verdict: asString(review.verdict),
      }
    }),
    coverage: readCoverage(raw.coverage ?? state.coverage),
    // Lời hỏi có thể đến từ CẢ HAI chỗ (`prompts` cấp trên của tuyến chi tiết và `state.prompts` của
    // hàng job) — gộp rồi khử trùng theo `promptId` để badge "Phản biện" không đếm gấp đôi.
    prompts: (() => {
      const seen = new Set<string>()
      return asArray(raw.prompts)
        .concat(asArray(state.prompts))
        .map(readPrompt)
        .filter((item): item is ResearchPrompt => {
          if (item === null || seen.has(item.promptId)) return false
          seen.add(item.promptId)
          return true
        })
    })(),
    scope: stateScope ?? readScope(raw.scope),
  }
}

/** Gộp danh sách job (đã chuẩn hoá), mới nhất theo thứ tự server trả về. */
export function readJobs(value: unknown): ResearchJob[] {
  return asArray(asRecord(value).jobs).map(readJob)
}

/** Run đang giữ tiền cảnh: theo `activeRunId`, nếu không có thì run còn hoạt động gần nhất. */
export function activeJob(jobs: readonly ResearchJob[], activeRunId: string): ResearchJob | null {
  if (activeRunId) {
    const named = jobs.find((job) => job.researchId === activeRunId)
    if (named) return named
  }
  return jobs.find(jobIsActive) ?? jobs[0] ?? null
}

// ── Dòng công cụ gom ───────────────────────────────────────────────────────

const SEARCH_TOOLS = new Set(['web_search', 'paper_citations', 'research_search'])
const READ_TOOLS = new Set(['web_fetch', 'research_read'])

export interface ResearchActivity {
  searches: number
  reads: number
}

/**
 * Đếm lời gọi research trong luồng sự kiện để thay cho loạt dòng "Executed <tool>":
 * số lần tìm và số nguồn đã đọc. Chỉ đếm `tool_start` để một lời gọi tính đúng một lần.
 */
export function researchActivity(events: readonly { type: string; data: Record<string, unknown> }[]): ResearchActivity {
  let searches = 0
  let reads = 0
  for (const event of events) {
    if (event.type !== 'tool_start') continue
    const name = asString(event.data.name)
    if (SEARCH_TOOLS.has(name)) searches += 1
    else if (READ_TOOLS.has(name)) reads += 1
  }
  return { searches, reads }
}

// ── Sự kiện `research_*` ───────────────────────────────────────────────────

/** Sự kiện mà `ResearchPanel` phải phản ứng (tải lại chi tiết job), không phải mỗi `source_add`. */
export function isResearchEvent(event: { type: string }): boolean {
  return event.type.startsWith('research_')
}
