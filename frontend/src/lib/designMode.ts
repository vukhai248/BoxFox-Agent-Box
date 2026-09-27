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
import type { TKey } from '../i18n/context'
import { asBool, asNumber, asRecord, asString, type Json } from './researchMode'

export { asBool, asNumber, asRecord, asString }
export type { Json }

/**
 * `version` của backend có thể là số hoặc chuỗi (hợp đồng IF-3): nhận cả hai rồi ép về chuỗi, để
 * một báo cáo `v2` dạng số không bị hiển thị nhầm thành `v1` (hay mất hẳn chip `v…`).
 */
export function asVersionString(value: unknown): string {
  const text = asString(value)
  if (text) return text
  const numeric = asNumber(value)
  return numeric === null ? '' : String(numeric)
}

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

/** Bước của một pha; pha lạ/`null` ⇒ bước đầu (không bao giờ ném). */
export function stepForPhase(phase: unknown): DesignStepKey {
  return PHASE_STEP[asString(phase)] ?? 'clarify'
}

/** Chỉ số (0-based) của bước đang chạy; bước cuối khi run đã đóng. */
export function activeStepIndex(phase: unknown, status: string): number {
  if (runIsClosed(status)) return DESIGN_STEPS.length - 1
  return DESIGN_STEPS.indexOf(stepForPhase(phase))
}

/**
 * Run đã đóng hẳn (`completed`/`partial`/`cancelled`) — MỘT luật dùng chung cho dòng thời gian
 * (`activeStepIndex`) và dải trạng thái (`DesignComposerStatus`), để `partial` không bị một chỗ coi
 * là đang chạy còn chỗ kia coi là xong.
 */
export function runIsClosed(status: string): boolean {
  return DESIGN_TERMINAL_STATUSES.includes(status as DesignRunStatus)
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

/**
 * Các loại lời hỏi của chế độ (§2 `DESIGN_PROMPT_KINDS`): phỏng vấn, làm rõ phạm vi, danh sách chạm,
 * thoát chế độ, ngoài phạm vi. Loại lạ rơi về `'unknown'` — KHÔNG đoán bừa thành `'interview'`, vì như
 * vậy một lời hỏi `touch-list` sẽ hiện nhầm là "Câu hỏi phỏng vấn".
 */
export type DesignPromptKind =
  | 'interview'
  | 'scope-change'
  | 'touch-list'
  | 'exit-choice'
  | 'out-of-scope'
  | 'unknown'

const PROMPT_KINDS: DesignPromptKind[] = [
  'interview',
  'scope-change',
  'touch-list',
  'exit-choice',
  'out-of-scope',
]

/** Loại lời hỏi đã biết; loại lạ ⇒ `'unknown'` (không ném, không gán nhãn sai). */
export function readPromptKind(value: unknown): DesignPromptKind {
  const text = asString(value)
  return (PROMPT_KINDS as readonly string[]).includes(text) ? (text as DesignPromptKind) : 'unknown'
}

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
  /** Dữ liệu phụ của server — với `out-of-scope`, `meta.request` giữ nguyên văn tin nhắn gốc (§5.9). */
  meta: Json
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
    kind: readPromptKind(prompt.kind),
    revision: asNumber(prompt.revision) ?? 0,
    status: oneOf(prompt.status, ['open', 'answered', 'dismissed'] as const, 'open'),
    createdAt: asString(prompt.createdAt),
    questions: (Array.isArray(prompt.questions) ? prompt.questions : []).map(readQuestion),
    actions: (Array.isArray(prompt.actions) ? prompt.actions : []).filter((x): x is string => typeof x === 'string'),
    note: asString(prompt.note),
    meta: asRecord(prompt.meta),
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
  /** Lô ghi đang chờ duyệt/đã ghi (P3) — `null` khi run chưa ghi gì. */
  batch: DesignBatch | null
  /** Kết quả soát độc lập (P4) — `null` khi chưa soát. */
  review: DesignReview | null
}

// ── Lô ghi + soát độc lập (P3/P4) ──────────────────────────────────────────

export interface DesignBatchFile {
  path: string
  status: string
  added: number
  removed: number
}

/** Một lô ghi các tệp đã chạm — hợp đồng §5 (thẻ `design-diff-batch-card`). */
export interface DesignBatch {
  index: number
  total: number
  /** `'proposed' | 'approved' | 'reverted' | …` — giữ chuỗi thô để không bịa trạng thái. */
  status: string
  revision: number
  /** Đường patch trên nhánh thiết kế (`.design/<slug>/diff.patch`). */
  patchPath: string
  added: number
  removed: number
  files: DesignBatchFile[]
}

export function readBatch(value: unknown): DesignBatch | null {
  if (value === null || value === undefined) return null
  const row = asRecord(value)
  const files = (Array.isArray(row.files) ? row.files : []).map((entry) => {
    const file = asRecord(entry)
    return {
      path: asString(file.path),
      status: asString(file.status),
      added: asNumber(file.added) ?? 0,
      removed: asNumber(file.removed) ?? 0,
    }
  })
  const patchPath = asString(row.patchPath)
  if (!patchPath && files.length === 0) return null
  return {
    index: asNumber(row.index) ?? 0,
    total: asNumber(row.total) ?? 0,
    status: asString(row.status),
    revision: asNumber(row.revision) ?? 0,
    patchPath,
    added: asNumber(row.added) ?? files.reduce((sum, file) => sum + file.added, 0),
    removed: asNumber(row.removed) ?? files.reduce((sum, file) => sum + file.removed, 0),
    files,
  }
}

/** Vòng soát độc lập (P4) — `verdict` là chuỗi thô (`'passed'`, `'changes'`, …). */
export interface DesignReview {
  version: string
  verdict: string
  summary: string
}

export function readReview(value: unknown): DesignReview | null {
  if (value === null || value === undefined) return null
  const row = asRecord(value)
  const verdict = asString(row.verdict)
  const summary = asString(row.summary)
  if (!verdict && !summary) return null
  return { version: asVersionString(row.version), verdict, summary }
}

/** Bước hiển thị của run: ưu tiên `step` backend gửi, thiếu thì suy từ pha. */
function readStep(value: unknown, phase: string): DesignStepKey {
  const text = asString(value)
  return (DESIGN_STEPS as readonly string[]).includes(text) ? (text as DesignStepKey) : stepForPhase(phase)
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
    batch: readBatch(run.batch),
    review: readReview(run.review),
  }
}

export function readRuns(payload: unknown): DesignRun[] {
  const rows = Array.isArray(payload) ? payload : asRecord(payload).runs
  return (Array.isArray(rows) ? rows : []).map(readRun).filter((run): run is DesignRun => run !== null)
}

/** Run đang mở: ưu tiên `activeRunId`, nếu không thì run chưa đóng mới nhất. */
export function activeRun(runs: readonly DesignRun[], activeRunId: unknown): DesignRun | null {
  const pinned = activeRunId
    ? runs.find((run) => run.designId === asString(activeRunId))
    : undefined
  if (pinned) return pinned
  return runs.find((run) => !DESIGN_TERMINAL_STATUSES.includes(run.status)) ?? runs[0] ?? null
}

/** Sự kiện nào thuộc chế độ Design — một chỗ để luồng sự kiện và store không lệch nhau. */
export function isDesignEvent<T extends { type: string }>(event: T): boolean {
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

// ── Trạng thái điều khiển được của run (§5.6/§5.8) ─────────────────────────

/** Run còn chạy nền (nền + chưa đóng) — nguồn sự thật cho chấm hổ phách ở nút Design (§5.2). */
export function runIsRunningInBackground(run: DesignRun): boolean {
  return run.background && !DESIGN_TERMINAL_STATUSES.includes(run.status)
}

/** Run có thể tạm dừng — bốn trạng thái đang chạy; `paused`/trạng thái đóng thì không. */
export function runIsPausable(run: DesignRun): boolean {
  return (['scoping', 'designing', 'writing', 'reviewing'] as DesignRunStatus[]).includes(run.status)
}

/** Run có thể TIẾP TỤC (§5.8: từ `paused`/`partial`/`needs_user` về pha trước đó). */
export function runIsSuspendable(run: DesignRun): boolean {
  return (['paused', 'partial', 'needs_user'] as DesignRunStatus[]).includes(run.status)
}

/** Run có thể huỷ — nhánh giữ lại để đọc; run đã xong/huỷ thì thôi. */
export function runIsCancellable(run: DesignRun): boolean {
  return run.status !== 'completed' && run.status !== 'cancelled'
}

// ── Thông báo nền (`design_notice`, hợp đồng §9) ──────────────────────────

/** Ba lý do một thông báo nền xuất hiện — không có lý do nào được bịa thêm. */
export type DesignNoticeKind = 'background-done' | 'needs-user' | 'blocked'

const NOTICE_KINDS: DesignNoticeKind[] = ['background-done', 'needs-user', 'blocked']

export interface DesignNotice {
  designId: string
  kind: DesignNoticeKind
  /** `seq` của sự kiện sinh ra thông báo — dùng để chống vẽ trùng khi poll lặp. */
  seq: number
}

/** Một thông báo từ `unknown`; thiếu `designId` ⇒ `null` (không dựng thẻ rỗng). */
export function readNotice(value: unknown, seq: number): DesignNotice | null {
  const row = asRecord(value)
  const designId = asString(row.designId)
  if (!designId) return null
  return { designId, kind: oneOf(row.kind, NOTICE_KINDS, 'blocked'), seq }
}

// ── Lỗi chế độ (§7.6/§8) ──────────────────────────────────────────────────

/**
 * `mã lỗi -> khoá i18n` cho câu tiếng Việt/Anh đọc được của backend. Mã lạ rơi về thông điệp thô
 * (đã gồm mã) nên giao diện không bao giờ hiện một nút chết im lặng.
 */
export const DESIGN_ERROR_KEY: Record<string, TKey> = {
  DESIGN_MODE_UNAVAILABLE: 'design.errors.DESIGN_MODE_UNAVAILABLE',
  DESIGN_MODE_REQUIRED: 'design.errors.DESIGN_MODE_REQUIRED',
  DESIGN_EXIT_CHOICE_REQUIRED: 'design.errors.DESIGN_EXIT_CHOICE_REQUIRED',
  DESIGN_TOUCH_LIST_REQUIRED: 'design.errors.DESIGN_TOUCH_LIST_REQUIRED',
  DESIGN_TOUCH_LIST_REVISION_STALE: 'design.errors.DESIGN_TOUCH_LIST_REVISION_STALE',
  DESIGN_PATH_NOT_APPROVED: 'design.errors.DESIGN_PATH_NOT_APPROVED',
  DESIGN_BRANCH_REQUIRED: 'design.errors.DESIGN_BRANCH_REQUIRED',
  DESIGN_BRANCH_EXISTS: 'design.errors.DESIGN_BRANCH_EXISTS',
  DESIGN_MAIN_BRANCH_FORBIDDEN: 'design.errors.DESIGN_MAIN_BRANCH_FORBIDDEN',
  DESIGN_WORKSPACE_NOT_REPO: 'design.errors.DESIGN_WORKSPACE_NOT_REPO',
  DESIGN_WRITE_EXISTS: 'design.errors.DESIGN_WRITE_EXISTS',
  DESIGN_WRITE_MISSING: 'design.errors.DESIGN_WRITE_MISSING',
  DESIGN_ANCHOR_NOT_UNIQUE: 'design.errors.DESIGN_ANCHOR_NOT_UNIQUE',
  DESIGN_WRITE_STALE: 'design.errors.DESIGN_WRITE_STALE',
  DESIGN_DIFF_DIRTY_BASE: 'design.errors.DESIGN_DIFF_DIRTY_BASE',
  DESIGN_REVIEW_NO_CRITIC: 'design.errors.DESIGN_REVIEW_NO_CRITIC',
  DESIGN_REVIEW_VERDICT_MISSING: 'design.errors.DESIGN_REVIEW_VERDICT_MISSING',
  DESIGN_REVIEW_VERDICT_MISMATCH: 'design.errors.DESIGN_REVIEW_VERDICT_MISMATCH',
  DESIGN_HANDOFF_UNREVIEWED: 'design.errors.DESIGN_HANDOFF_UNREVIEWED',
  DESIGN_CANVAS_PROTOCOL_INVALID: 'design.errors.DESIGN_CANVAS_PROTOCOL_INVALID',
  DESIGN_PROMPT_ANSWERED: 'design.errors.DESIGN_PROMPT_ANSWERED',
}

/** Khoá i18n của một mã lỗi; `null` khi mã không có trong bảng (dùng thông điệp thô). */
export function designErrorKey(code: string): TKey | null {
  return DESIGN_ERROR_KEY[asString(code)] ?? null
}
