/**
 * Dữ liệu thuần của chế độ `/design` (P1 — vỏ chế độ).
 *
 * Vì sao tách khỏi component: các pha P2–P5 còn đang chạy song song, trường nào backend CHƯA gửi
 * thì giao diện phải render như "không có", KHÔNG được ném. Mọi hàm ở đây đọc `unknown` và trả về
 * một shape đã chuẩn hoá, để component không phải `as` và cũng không phải `try/catch`.
 *
 * Tên trường bám đúng hợp đồng đã đông cứng ở `/code/.plans/design-interfaces.md` (§2, §9, §10) và
 * §7 của `/code/.plans/v1-design-mode-agent.md`.
 */
import { asBool, asNumber, asRecord, asString, type Json } from './researchMode'

export { asBool, asNumber, asRecord, asString }
export type { Json }

// ── Chế độ (session.config.designMode) ─────────────────────────────────────

export interface DesignMode {
  on: boolean
  since: string
  /** `'toggle'` hoặc `'command'` — chỉ để hiển thị nguồn vào. */
  enteredBy: string
  activeRunId: string
  revision: number
  /** `designId -> version` của mọi khối bàn giao đã giao cho lượt main (một lần mỗi phiên bản). */
  handoffDeliveredVersion: Record<string, string>
}

export const DESIGN_MODE_OFF: DesignMode = {
  on: false,
  since: '',
  enteredBy: '',
  activeRunId: '',
  revision: 0,
  handoffDeliveredVersion: {},
}

/**
 * Đọc `session.config.designMode`; thiếu khoá/`null` ⇒ chế độ TẮT (không bao giờ ném).
 *
 * Đây là hình dạng chốt của P1: phiên chưa từng bật `/design` không có khoá này trong config, và
 * giao diện phải coi đó là "chế độ tắt", không phải lỗi.
 */
export function readDesignMode(config: unknown): DesignMode {
  const value = asRecord(asRecord(config).designMode)
  return {
    on: asBool(value.on),
    since: asString(value.since),
    enteredBy: asString(value.enteredBy),
    activeRunId: asString(value.activeRunId),
    revision: asNumber(value.revision) ?? 0,
    handoffDeliveredVersion: readHandoffVersions(value.handoffDeliveredVersion),
  }
}

/** `designId -> version`: chỉ nhận chữ/số, ép về chuỗi, bỏ mọi giá trị khác. */
function readHandoffVersions(value: unknown): Record<string, string> {
  const versions: Record<string, string> = {}
  for (const [designId, item] of Object.entries(asRecord(value))) {
    if (typeof item === 'string') versions[designId] = item
    else if (typeof item === 'number' && Number.isFinite(item)) versions[designId] = String(item)
  }
  return versions
}

// ── Bảy bước hiển thị ─────────────────────────────────────────────────────

export type DesignStepKey = 'clarify' | 'brief' | 'approve' | 'draw' | 'write' | 'review' | 'handoff'

/** Bảy bước của thanh tiến trình, đúng thứ tự hợp đồng §2. */
export const DESIGN_STEPS: DesignStepKey[] = [
  'clarify',
  'brief',
  'approve',
  'draw',
  'write',
  'review',
  'handoff',
]

/** Pha của backend → bước hiển thị (hợp đồng §2 `PHASE_STEP`). Pha lạ rơi về `clarify`. */
export const PHASE_STEP: Record<string, DesignStepKey> = {
  interviewing: 'clarify',
  briefing: 'brief',
  'touch-list': 'approve',
  drawing: 'draw',
  scaffolding: 'write',
  reviewing: 'review',
  handoff: 'handoff',
  done: 'handoff',
}

export function stepForPhase(phase: string): DesignStepKey {
  return PHASE_STEP[phase] ?? 'clarify'
}

/** Chỉ số (0-based) của bước đang chạy; bước cuối khi run đã đóng. */
export function activeStepIndex(phase: string, status: string): number {
  if (status === 'completed' || status === 'partial' || status === 'cancelled') {
    return DESIGN_STEPS.length - 1
  }
  return DESIGN_STEPS.indexOf(stepForPhase(phase))
}

/** Nhãn ngắn của run ("D-1A2B3") — suy từ `designId`, không phải dữ liệu mới. */
export function runLabel(designId: string): string {
  const compact = designId.replace(/[^0-9a-z]/gi, '')
  if (!compact) return designId
  return `D-${compact.slice(-5).toUpperCase()}`
}

// ── Danh sách chạm (§7.10, §10) ───────────────────────────────────────────

export type DesignTouchKind = 'new' | 'insert'
export type DesignTouchStatus = 'proposed' | 'approved' | 'rejected' | 'written'

export interface DesignTouchItem {
  id: string
  kind: DesignTouchKind
  path: string
  reason: string
  risk: string
  status: DesignTouchStatus
  sha256: string | null
}

export interface DesignTouchList {
  revision: number
  designId: string
  branch: { name: string; base: string; status: string }
  items: DesignTouchItem[]
  forbidden: string[]
  /** `null` khi chưa duyệt; ngược lại là mốc ISO lúc duyệt. */
  approvedAt: string | null
}

const TOUCH_KINDS: DesignTouchKind[] = ['new', 'insert']
const TOUCH_STATUSES: DesignTouchStatus[] = ['proposed', 'approved', 'rejected', 'written']

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  const text = typeof value === 'string' ? value : ''
  return (allowed as readonly string[]).includes(text) ? (text as T) : fallback
}

export function readTouchItem(value: unknown, index: number): DesignTouchItem {
  const item = asRecord(value)
  return {
    id: asString(item.id) || `t${index + 1}`,
    kind: oneOf(item.kind, TOUCH_KINDS, 'new'),
    path: asString(item.path),
    reason: asString(item.reason),
    risk: asString(item.risk) || 'low',
    status: oneOf(item.status, TOUCH_STATUSES, 'proposed'),
    sha256: typeof item.sha256 === 'string' ? item.sha256 : null,
  }
}

export function readTouchList(value: unknown): DesignTouchList | null {
  const list = asRecord(value)
  if (Object.keys(list).length === 0) return null
  const branch = asRecord(list.branch)
  return {
    revision: asNumber(list.revision) ?? 0,
    designId: asString(list.designId),
    branch: { name: asString(branch.name), base: asString(branch.base), status: asString(branch.status) || 'proposed' },
    items: (Array.isArray(list.items) ? list.items : []).map(readTouchItem),
    forbidden: (Array.isArray(list.forbidden) ? list.forbidden : []).filter((x): x is string => typeof x === 'string'),
    approvedAt: typeof list.approvedAt === 'string' ? list.approvedAt : null,
  }
}

// ── Lời hỏi (`design_prompt`) ──────────────────────────────────────────────

/** Bốn loại lời hỏi của chế độ (§2): phỏng vấn, làm rõ phạm vi, thoát chế độ, chọn lựa giữa. */
export type DesignPromptKind = 'interview' | 'scope-change' | 'exit-choice' | 'out-of-scope'

const PROMPT_KINDS: DesignPromptKind[] = ['interview', 'scope-change', 'exit-choice', 'out-of-scope']

export interface DesignPromptOption {
  id: string
  label: string
}

export interface DesignPromptQuestion {
  id: string
  text: string
  why: string
  options: DesignPromptOption[]
  allowFreeText: boolean
  required: boolean
  /** Câu đã trả lời — `null` khi còn mở. */
  answer: { text: string; optionId: string | null } | null
}

export interface DesignPrompt {
  promptId: string
  designId: string
  kind: DesignPromptKind
  revision: number
  status: 'open' | 'answered' | 'dismissed'
  createdAt: string
  questions: DesignPromptQuestion[]
  actions: string[]
  note: string
}

function readQuestion(value: unknown): DesignPromptQuestion {
  const question = asRecord(value)
  const answer = asRecord(question.answer)
  return {
    id: asString(question.id),
    text: asString(question.text),
    why: asString(question.why),
    options: (Array.isArray(question.options) ? question.options : []).map((option) => {
      const item = asRecord(option)
      return { id: asString(item.id), label: asString(item.label) }
    }).filter((option) => option.id !== ''),
    allowFreeText: question.allowFreeText !== false,
    required: question.required !== false,
    answer: Object.keys(answer).length === 0
      ? null
      : { text: asString(answer.text), optionId: typeof answer.optionId === 'string' ? answer.optionId : null },
  }
}

/** Một lời hỏi từ `unknown`; thiếu `promptId` ⇒ `null` (không dựng thẻ rỗng). */
export function readPrompt(value: unknown): DesignPrompt | null {
  const prompt = asRecord(value)
  const promptId = asString(prompt.promptId)
  if (!promptId) return null
  return {
    promptId,
    designId: asString(prompt.designId),
    kind: oneOf(prompt.kind, PROMPT_KINDS, 'interview'),
    revision: asNumber(prompt.revision) ?? 0,
    status: oneOf(prompt.status, ['open', 'answered', 'dismissed'] as const, 'open'),
    createdAt: asString(prompt.createdAt),
    questions: (Array.isArray(prompt.questions) ? prompt.questions : []).map(readQuestion),
    actions: (Array.isArray(prompt.actions) ? prompt.actions : []).filter((x): x is string => typeof x === 'string'),
    note: asString(prompt.note),
  }
}

export function readPrompts(value: unknown): DesignPrompt[] {
  return (Array.isArray(value) ? value : []).map(readPrompt).filter((prompt): prompt is DesignPrompt => prompt !== null)
}

// ── Run (hàng `design_jobs` đã camelCase) ─────────────────────────────────

export type DesignRunStatus =
  | 'scoping'
  | 'designing'
  | 'writing'
  | 'reviewing'
  | 'completed'
  | 'partial'
  | 'needs_user'
  | 'paused'
  | 'cancelled'

/** Trạng thái đóng hẳn — không còn gì để bơm hay tạm dừng. */
export const DESIGN_TERMINAL_STATUSES: DesignRunStatus[] = ['completed', 'partial', 'cancelled']

export interface DesignRun {
  designId: string
  sessionId: string
  status: DesignRunStatus
  phase: string
  step: DesignStepKey
  origin: string
  background: boolean
  revision: number
  goal: string
  touchListRevision: number
  touchList: DesignTouchList | null
  prompts: DesignPrompt[]
  phaseHistory: { phase: string; at: string; reason: string }[]
}

/** Bước hiển thị của run: ưu tiên `step` backend gửi, thiếu thì suy từ pha. */
function readStep(value: unknown, phase: string): DesignStepKey {
  const text = asString(value)
  return (DESIGN_STEPS as readonly string[]).includes(text) ? (text as DesignStepKey) : stepForPhase(phase)
}

function readPhaseHistory(value: unknown): { phase: string; at: string; reason: string }[] {  return (Array.isArray(value) ? value : []).map((entry) => {
    const row = asRecord(entry)
    return { phase: asString(row.phase), at: asString(row.at), reason: asString(row.reason) }
  })
}

/** Một run từ `unknown`; thiếu `designId` ⇒ `null`. */
export function readRun(value: unknown): DesignRun | null {
  const run = asRecord(value)
  const designId = asString(run.designId)
  if (!designId) return null
  const phase = asString(run.phase)
  const status = oneOf(run.status, [
    'scoping', 'designing', 'writing', 'reviewing', 'completed', 'partial',
    'needs_user', 'paused', 'cancelled',
  ] as const, 'scoping')
  const touchList = readTouchList(run.touchList)
  return {
    designId,
    sessionId: asString(run.sessionId),
    status,
    phase,
    step: readStep(run.step, phase),
    origin: asString(run.origin),
    background: asBool(run.background),
    revision: asNumber(run.revision) ?? 0,
    goal: asString(run.goal),
    touchListRevision: asNumber(run.touchListRevision) ?? touchList?.revision ?? 0,
    touchList,
    prompts: readPrompts(run.prompts),
    phaseHistory: readPhaseHistory(run.phaseHistory),
  }
}

export function readRuns(payload: unknown): DesignRun[] {
  const rows = Array.isArray(payload) ? payload : asRecord(payload).runs
  return (Array.isArray(rows) ? rows : []).map(readRun).filter((run): run is DesignRun => run !== null)
}

/** Run đang mở: ưu tiên `activeRunId`, nếu không thì run chưa đóng mới nhất. */
export function activeRun(runs: readonly DesignRun[], activeRunId: string): DesignRun | null {
  const pinned = activeRunId ? runs.find((run) => run.designId === activeRunId) : undefined
  if (pinned) return pinned
  return runs.find((run) => !DESIGN_TERMINAL_STATUSES.includes(run.status)) ?? runs[0] ?? null
}

/** Sự kiện nào thuộc chế độ Design — một chỗ để luồng sự kiện và store không lệch nhau. */
export function isDesignEvent(event: { type: string }): boolean {
  return event.type.startsWith('design_')
}

/** Lời hỏi `exit-choice` còn MỞ của bất kỳ run nào đang thấy. */
export function openExitPrompt(runs: readonly DesignRun[]): DesignPrompt | null {
  for (const run of runs) {
    const prompt = run.prompts.find((item) => item.status === 'open' && item.kind === 'exit-choice')
    if (prompt) return prompt
  }
  return null
}
