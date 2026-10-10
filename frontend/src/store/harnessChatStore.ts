import { continuityInvocation } from '../lib/continuityInvocation'
import { newerTask, type LongTask } from '../types/longtask'
import { create } from 'zustand'
import { resolveThinkingLevel } from '../lib/harnessThinking'
import { agentApi } from '../lib/agentApi'
import { readHarnessSessionPages } from '../lib/harnessSessionPages'
import { useMachineStore, type MachineBinding } from './machineStore'
import type { OutgoingAttachment } from '../lib/chat/attachmentUpload'
import { useHarnessStore } from './harnessStore'
import { useOwnerSettingsStore } from './ownerSettingsStore'
import { useSessionRecordStore } from './sessionRecordStore'
import { useSkillsStore } from './skillsStore'
import { useUiStore } from './uiStore'
import type { TabIntent } from './uiStore'
import type { RouterChatSelection } from './routerChatStore'

export interface HarnessEvent { seq: number; type: string; data: Record<string, unknown>; created: number }
interface HarnessSession { goalRevision?: number; contractRef?: string | null; longtask?: LongTask | null; id: string; status: string; events: HarnessEvent[]; config?: Record<string, unknown>
  /** Khối `journal` của `GET /sessions/{sid}` — đọc ở `parseJournalPush`, không dùng trực tiếp. */
  journal?: unknown }

/** Một mảnh bằng chứng trong hàng `E:` — con trỏ kiểm chứng được (tệp, lệnh, ảnh), không phải lời kể. */
export interface JournalEvidenceItem {
  type: string
  path: string | null
  command: string | null
  note: string | null
}

/**
 * Một hàng nhật ký bền của phiên (khối `journal.records` — A9). Chỉ giữ những trường giao diện
 * thật sự đọc; hàng `E:` là hàng mang bằng chứng của một lượt.
 */
export interface JournalRow {
  seq: number
  kind: string
  text: string
  id: string | null
  status: string | null
  data: Record<string, unknown>
  evidence: JournalEvidenceItem[]
  /** Số LƯỢT của bản ghi — hàng ghi trước vòng này không có, nên phải phân biệt được "không có" với 0. */
  turn: number | null
  step: number | null
}

/**
 * Nhật ký của một phiên trong state. `evidenceByTurn` là DẪN XUẤT từ `records` (khoá theo `turn`),
 * giữ sẵn ở đây để chỗ vẽ không phải quét lại toàn bộ nhật ký mỗi vòng poll 1200 ms.
 */
export interface HarnessJournal {
  records: JournalRow[]
  lastSeq: number
  degraded: boolean
  evidenceByTurn: Record<number, JournalRow>
}

interface RunView { goalRevision?: number; contractRef?: string | null; longtask?: LongTask | null; decisionsHydrated?: boolean; id: string | null; status: string; events: HarnessEvent[]; error: string | null; lastModelLabel?: string
  /** Cặp `(số, nguồn)` của cửa sổ ngữ cảnh trong `config` phiên — harness nén theo đúng số này. */
  contextWindow?: number | null; contextWindowSource?: string | null
  /**
   * P4 — khối `config.researchMode` nguyên dạng server gửi, để `useResearchSync` đọc chế độ
   * `/research` mà KHÔNG mở thêm một vòng hỏi phiên thứ hai. Giữ `unknown` và chuẩn hoá ở
   * `lib/researchMode.ts`, nên trường lạ/thiếu không làm sập vòng poll.
   */
  researchMode?: unknown
  /**
   * P1 — khối `config.designMode` nguyên dạng server gửi, để `useDesignSync` đọc chế độ `/design`
   * mà KHÔNG mở thêm một vòng hỏi phiên thứ hai (cùng luật với `researchMode` ở trên).
   */
  designMode?: unknown
  planMode?: unknown
  autopilot?: boolean
  /** Nhật ký bền của phiên (khối `journal` đã gộp qua các vòng poll). */
  journal?: HarnessJournal | null
  /**
   * Vòng 27 / C-5 — chỉ thị vừa được XẾP HÀNG cho lượt đang chạy (harness trả 202
   * `{status:'steered'}`): giữ nguyên văn để ô soạn tin nói thật là đã nhận, chứ không xoá im lặng.
   */
  steerNotice?: SteerNotice | null }
/**
 * Vòng 27 / C-5 — dấu vết của một chỉ thị đã vào hàng cho lượt ĐANG chạy.
 *
 * `text` là nguyên văn chủ nhà vừa gõ (ô soạn tin không được nuốt nó), `at` là mốc thời gian
 * (ms) để hiện giờ cạnh dòng xác nhận, `steerId` là id hàng đợi harness trả về (có thì hiện,
 * không có thì không bịa).
 */
export interface SteerNotice {
  text: string
  at: number
  steerId: string | null
}

export interface SavedSessionRow {
  id: string
  role: string
  status: string
  updated: number
  config: Record<string, unknown>
}

// ── Quyết định thật của agent (hợp đồng §1 `decision_requested`/`decision_resolved`)

export type DecisionKind = 'question' | 'approval' | 'interview' | 'budget'
export type DecisionOptionKind = 'approve' | 'reject' | 'alternative'
// P4 (vá vòng soát) — `answered`: chủ nhà GÕ câu trả lời vào ô tự nhập. Đó là một hàng ĐÃ CHỐT
// nhưng trung tính: không phải "đã duyệt" và cũng không phải "bị từ chối".
export type DecisionStatus = 'pending' | 'approved' | 'rejected' | 'answered' | 'expired' | 'cancelled'
export type DecisionResolveReason = 'user' | 'timeout' | 'session_cancelled'

export interface DecisionOption {
  id: string
  label: string
  kind: DecisionOptionKind
  /**
   * P4 — lựa chọn cần CHỮ đã gõ: UI mở ô nhập và route từ chối khi chọn mà bỏ trống.
   * Runtime LUÔN thêm một lựa chọn như vậy (`id='other'`) vào mọi quyết định.
   */
  allowFreeText?: boolean
  budgetDelta?: { steps: number; activeTimeMs: number }
}

/**
 * Một mục trong danh sách quyết định của phiên. Mọi trường đều lấy nguyên từ
 * event của harness: không có hạn chót, lựa chọn hay lý do nào do giao diện bịa.
 */
export interface DecisionEntry {
  revision?: number
  restored?: boolean
  actionable?: boolean
  id: string
  kind: DecisionKind
  question: string | null
  action: string | null
  reason: string | null
  options: DecisionOption[]
  /** Hạn chót, epoch giây (float) — đúng con số server gửi. */
  deadline: number | null
  defaultChoice: string | null
  status: DecisionStatus
  choice: string | null
  note: string | null
  resolvedReason: DecisionResolveReason | null
  resolvedAt: number | null
  /** `created` của event `decision_requested` (ms) — chỉ để hiện thứ tự. */
  requestedAt: number
  /** Thẻ phỏng vấn (`interview`): tiêu đề chung của cả thẻ. */
  title?: string | null
  /** Thẻ phỏng vấn: 1–5 câu hỏi, mỗi câu 2–4 lựa chọn (server đã chuẩn hoá). */
  questions?: InterviewQuestion[]
  /** Thẻ phỏng vấn đã chốt: câu trả lời theo từng câu hỏi (`decision_resolved.answers`). */
  answers?: InterviewAnswer[]
  /** Quyết định thuộc một lượt Work Graph (thẻ duyệt kế hoạch). */
  workRunId?: string | null
}

export interface InterviewOption {
  id: string
  label: string
  description: string
  recommended: boolean
}

export interface InterviewQuestion {
  id: string
  question: string
  rationale: string
  options: InterviewOption[]
}

/** Một câu trả lời gửi đi: chọn `optionId`, hoặc `optionId='other'` kèm `text`, hoặc `decide`. */
export interface InterviewReply {
  questionId: string
  optionId?: string
  text?: string
}

/** Câu trả lời đã chuẩn hoá do harness trả về. `decidedBy='agent'` là câu để agent tự quyết. */
export interface InterviewAnswer {
  questionId: string
  question: string | null
  optionId: string | null
  answer: string | null
  decidedBy: 'user' | 'agent'
  recommended?: string | null
}

interface State {
  sessions: Record<string, RunView>
  /** Quyết định thật theo từng phiên chat, dẫn xuất từ `events[]`. */
  decisions: Record<string, DecisionEntry[]>
  /** Số `seq` lớn nhất đã xử lý ý định mở tab — cùng một event không kích hoạt lại. */
  intentSeq: Record<string, number>
  fetchSavedSessions: () => Promise<SavedSessionRow[]>
  deleteSession: (id: string, operation: { operationId: string; expectedRevision: string }) => Promise<{ status: string }>
  send: (
    chatId: string,
    prompt: string,
    selection: RouterChatSelection | null,
    image?: string | null,
    modelLabel?: string,
    thinkingLevels?: string[],
    images?: string[] | null,
    attachments?: OutgoingAttachment[],
  ) => Promise<void>
  refresh: (chatId: string) => Promise<void>
  stop: (chatId: string) => Promise<void>
  /** Trả lời một quyết định qua harness; cập nhật ngay tại chỗ khi thành công. */
  answerDecision: (
    chatId: string,
    decisionId: string,
    choice: string,
    note?: string,
    answers?: InterviewReply[],
  ) => Promise<void>
  clearError: (chatId: string) => void
}

const asString = (value: unknown): string | null =>
  typeof value === 'string' && value.length > 0 ? value : null
const asNumber = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

const OPTION_KINDS: DecisionOptionKind[] = ['approve', 'reject', 'alternative']

/** `options` là 2–5 mục `{id, label, kind}`; mục méo bị bỏ, không bịa thêm. */
export function parseDecisionOptions(value: unknown): DecisionOption[] {
  if (!Array.isArray(value)) return []
  const options: DecisionOption[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as { id?: unknown; label?: unknown; kind?: unknown; allowFreeText?: unknown; budgetDelta?: unknown }
    const id = asString(item.id)
    const label = asString(item.label)
    if (!id || !label) continue
    const kind = OPTION_KINDS.includes(item.kind as DecisionOptionKind)
      ? (item.kind as DecisionOptionKind)
      : 'alternative'
    // Cờ tự nhập đi nguyên từ server (đúng cả với `id='other'` runtime luôn thêm).
    const delta = item.budgetDelta as Record<string, unknown> | undefined
    options.push({ id, label, kind, ...(item.allowFreeText === true ? { allowFreeText: true } : {}),
      ...(delta && typeof delta.steps === 'number' && typeof delta.activeTimeMs === 'number' ? { budgetDelta: { steps: delta.steps, activeTimeMs: delta.activeTimeMs } } : {}) })
  }
  return options
}

export function decisionStatusFrom(value: unknown): DecisionStatus {
  // `'answered'` (P4 — chữ tự nhập) phải đi nguyên qua đây, nếu không cập nhật lạc quan sau khi
  // bấm sẽ rơi vào nhánh mặc định và hiện hàng tự nhập thành "đã duyệt".
  return value === 'answered' ||
    value === 'approved' ||
    value === 'rejected' ||
    value === 'expired' ||
    value === 'cancelled'
    ? value
    : 'pending'
}

export function decisionReasonFrom(value: unknown): DecisionResolveReason | null {
  return value === 'user' || value === 'timeout' || value === 'session_cancelled' ? value : null
}

/** Câu hỏi của thẻ phỏng vấn; mục méo bị bỏ, không bịa thêm. */
export function parseInterviewQuestions(value: unknown): InterviewQuestion[] {
  if (!Array.isArray(value)) return []
  const questions: InterviewQuestion[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const id = asString(item.id)
    const question = asString(item.question)
    if (!id || !question) continue
    const options: InterviewOption[] = []
    for (const rawOption of Array.isArray(item.options) ? item.options : []) {
      if (!rawOption || typeof rawOption !== 'object') continue
      const option = rawOption as Record<string, unknown>
      const optionId = asString(option.id)
      const label = asString(option.label)
      if (!optionId || !label) continue
      options.push({
        id: optionId,
        label,
        description: asString(option.description) ?? '',
        recommended: option.recommended === true,
      })
    }
    if (options.length === 0) continue
    questions.push({ id, question, rationale: asString(item.rationale) ?? '', options })
  }
  return questions
}

/** Câu trả lời đã chuẩn hoá của thẻ phỏng vấn (`decision_resolved.answers` hoặc kết quả route). */
export function parseInterviewAnswers(value: unknown): InterviewAnswer[] {
  if (!Array.isArray(value)) return []
  const answers: InterviewAnswer[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const questionId = asString(item.questionId)
    if (!questionId) continue
    answers.push({
      questionId,
      question: asString(item.question),
      optionId: asString(item.optionId),
      answer: asString(item.answer),
      decidedBy: item.decidedBy === 'agent' ? 'agent' : 'user',
      recommended: asString(item.recommended),
    })
  }
  return answers
}

/**
 * Dựng danh sách quyết định từ `events[]`. Hàm THUẦN để test được.
 * `decision_resolved` tới trước `decision_requested` (dữ liệu cũ, phân trang)
 * vẫn tạo một mục để lịch sử không mất.
 */
export function parseDecisions(events: HarnessEvent[]): DecisionEntry[] {
  const byId = new Map<string, DecisionEntry>()
  for (const event of events) {
    if (event.type === 'decision_requested') {
      const id = asString(event.data.decisionId)
      if (!id || byId.has(id)) continue
      byId.set(id, {
        id,
        revision: asNumber(event.data.revision) ?? undefined,
        kind: event.data.kind === 'budget' ? 'budget' : event.data.kind === 'approval' ? 'approval' : event.data.kind === 'interview' ? 'interview' : 'question',
        question: asString(event.data.question),
        action: asString(event.data.action),
        reason: asString(event.data.reason),
        options: parseDecisionOptions(event.data.options),
        deadline: asNumber(event.data.deadline),
        defaultChoice: asString(event.data.defaultChoice),
        status: 'pending',
        choice: null,
        note: null,
        resolvedReason: null,
        resolvedAt: null,
        requestedAt: event.created,
        ...(event.data.kind === 'interview'
          ? { title: asString(event.data.title), questions: parseInterviewQuestions(event.data.questions) }
          : {}),
        workRunId: asString(event.data.workRunId) ?? asString(event.data.runId),
      })
      continue
    }
    if (event.type === 'decision_resolved') {
      const id = asString(event.data.decisionId)
      if (!id) continue
      const entry = byId.get(id) ?? {
        id,
        kind: 'question' as DecisionKind,
        question: null,
        action: null,
        reason: null,
        options: [],
        deadline: null,
        defaultChoice: null,
        status: 'pending' as DecisionStatus,
        choice: null,
        note: null,
        resolvedReason: null,
        resolvedAt: null,
        requestedAt: event.created,
      }
      byId.set(id, {
        ...entry,
        revision: asNumber(event.data.revision) ?? entry.revision,
        status: decisionStatusFrom(event.data.status),
        choice: asString(event.data.choice),
        note: asString(event.data.note),
        resolvedReason: decisionReasonFrom(event.data.reason),
        resolvedAt: asNumber(event.data.resolvedAt),
        ...(Array.isArray(event.data.answers) ? { answers: parseInterviewAnswers(event.data.answers) } : {}),
      })
    }
  }
  return [...byId.values()]
}

/** Quyết định đang chờ trả lời — agent đang bị chặn ở đúng những mục này. */
/** Same-ID hydration; an older pending snapshot must never revive a settled card. */
export function canonicalDecisionEntries(rows: Record<string, unknown>[]): DecisionEntry[] {
  return rows.flatMap(row => {
    const data = { ...row, decisionId: row.decisionId ?? row.id }
    const entries = parseDecisions([{ seq: 0, type: 'decision_requested', data, created: Number(row.created ?? row.requestedAt ?? 0) }])
    return entries.map(entry => ({ ...entry, status: decisionStatusFrom(row.status ?? 'pending'),
      restored: true, actionable: row.actionable !== false, revision: asNumber(row.revision) ?? undefined }))
  })
}
export function mergeCanonicalDecisions(previous: DecisionEntry[], events: DecisionEntry[], canonical?: DecisionEntry[]): DecisionEntry[] {
  const byId = new Map<string, DecisionEntry>()
  for (const entry of [...previous, ...events, ...(canonical ?? [])]) {
    const old = byId.get(entry.id)
    if (old && ((old.revision ?? 0) > (entry.revision ?? 0)
      || (old.status !== 'pending' && entry.status === 'pending'))) continue
    byId.set(entry.id, entry)
  }
  if (canonical !== undefined) {
    const pendingIds = new Set(canonical.map(entry => entry.id))
    for (const [id, entry] of byId) {
      if (entry.status === 'pending' && !pendingIds.has(id)) byId.set(id, { ...entry, actionable: false })
    }
  }
  return [...byId.values()]
}

export function pendingDecisions(decisions: DecisionEntry[]): DecisionEntry[] {
  return decisions.filter((entry) => entry.status === 'pending')
}

/**
 * Xử lý ý định mở tab của agent (hợp đồng §3/§4) cho các event MỚI.
 *
 * Trả về `seq` lớn nhất đã xử lý để vòng poll sau không kích hoạt lại cùng một
 * event. Bản plan cũ nạp từ lịch sử không tự mở tab; nhưng một
 * `decision_requested` chưa có `decision_resolved` thì luôn đáng mở — agent
 * đang chờ người dùng thật.
 */
export function dispatchTabIntents(params: {
  allEvents: HarnessEvent[]
  freshEvents: HarnessEvent[]
  lastSeq: number
  firstHydration: boolean
}): number {
  const { allEvents, freshEvents, lastSeq, firstHydration } = params
  if (freshEvents.length === 0) return lastSeq
  const ui = useUiStore.getState()
  // Cùng một lượt có thể mang cả event gốc lẫn `ui_intent` đi kèm của harness
  // (bản gợi ý cùng nội dung), nên gộp theo (tab, đích): một ý định chỉ xếp hàng
  // một lần, không nhân đôi số trên huy hiệu.
  const handled = new Set<string>()
  const request = (tab: TabIntent['tab'], target: TabIntent['target'], reason: string) => {
    const key = intentKey(tab, target)
    if (handled.has(key)) return
    handled.add(key)
    ui.requestTabIntent({ tab, target, reason })
  }
  for (const event of freshEvents) {
    if (event.type === 'plan_written') {
      if (firstHydration) continue
      // `identity` là định danh trần như `GET /__box/plans` trả về (hợp đồng §1,
      // đã sửa): không kèm `vN-`, không so với `relativePath`. Bản vừa ghi là
      // cặp (identity, version) — version là số nguyên riêng.
      const identity = asString(event.data.identity)
      const version = asNumber(event.data.version)
      ui.bumpPlanRevision()
      request(
        'plan',
        identity ? { identity, ...(version === null ? {} : { version }) } : null,
        'plan_written',
      )
      continue
    }
    if (event.type === 'decision_requested') {
      const id = asString(event.data.decisionId)
      const stillPending = !allEvents.some(
        (other) => other.type === 'decision_resolved' && String(other.data.decisionId) === String(id),
      )
      if (stillPending) {
        request('decisions', id ? { requestId: id } : null, 'decision_requested')
      }
      continue
    }
    // Work Graph: lần đầu một lượt xuất hiện (hoặc lượt chuyển sang chờ duyệt) thì mở tab Work
    // Graph — không mở lại cho mỗi ảnh chụp, vì mỗi vòng review đều phát một `work_graph`.
    if (event.type === 'work_graph') {
      if (firstHydration) continue
      const runId = asString(event.data.runId)
      if (!runId) continue
      const status = asString(event.data.status)
      const earlier = allEvents.filter(
        (other) => other.type === 'work_graph' && other.seq < event.seq && other.data.runId === runId,
      )
      const statusIsNew = !earlier.some((other) => other.data.status === status)
      if (earlier.length === 0 || (statusIsNew && status === 'awaiting_approval')) {
        request('work', { runId }, 'work_graph')
      }
      continue
    }
    // Design/Canvas: `canvas_draw` phát `design_canvas` cho MỖI lần vẽ — đó là
    // CẬP NHẬT trạng thái, không phải sự kiện "xong một artifact", nên chỉ mở
    // tab ở lần vẽ ĐẦU của một `designId` (đúng tiền lệ `work_graph` ở trên;
    // `plan_written` tần suất thấp nên mở mỗi bản có version mới là hợp lý).
    // Không thêm producer `ui_intent` song song: `design_canvas` đã mang
    // `designId` — bản sao thứ hai là chỗ trôi thứ hai của cùng một sự thật.
    if (event.type === 'design_canvas') {
      if (firstHydration) continue
      const designId = asString(event.data.designId)
      if (!designId) continue
      // Cảnh do chính chủ nhà gửi (`persist_design_canvas` phát `actor: 'user'`)
      // là cảnh họ vừa nhìn — không cướp tab.
      if (asString(event.data.actor) === 'user') continue
      const earlier = allEvents.some(
        (other) =>
          other.type === 'design_canvas' && other.seq < event.seq && String(other.data.designId) === designId,
      )
      if (!earlier) request('design', { designId }, 'canvas_drawn')
      continue
    }
    // `ui_intent` là gợi ý của harness (hợp đồng §1/§3): UI vẫn tự quyết theo luật
    // auto-open, và những ý định không có event gốc đi kèm (ví dụ tab Files) cũng
    // được tôn trọng. Tab lạ thì bỏ qua.
    if (event.type === 'ui_intent') {
      const tab = asString(event.data.tab)
      if (tab !== 'plan' && tab !== 'work' && tab !== 'decisions' && tab !== 'files' && tab !== 'subagents' && tab !== 'research' && tab !== 'design') continue
      if (firstHydration && (tab === 'plan' || tab === 'decisions')) continue
      const rawTarget = event.data.target
      request(
        tab,
        rawTarget && typeof rawTarget === 'object' ? (rawTarget as Record<string, unknown>) : null,
        asString(event.data.reason) ?? 'ui_intent',
      )
    }
  }
  return allEvents.reduce((max, event) => Math.max(max, event.seq), lastSeq)
}

/** Khoá gộp ý định trong một lượt: (tab, đích) — không phụ thuộc thứ tự khoá. */
function intentKey(tab: TabIntent['tab'], target: TabIntent['target']): string {
  const entries = Object.entries(target ?? {}).sort(([a], [b]) => a.localeCompare(b))
  return `${tab}|${entries.map(([key, value]) => `${key}=${String(value)}`).join(',')}`
}


const storageKey = (chatId: string) => `boxfox-harness-session:${chatId}`
const isHexId = (s: string) => /^[0-9a-f]{16,64}$/i.test(s)
const empty = (): RunView => ({ id: null, status: 'idle', events: [], error: null })

/**
 * Cặp `(số, nguồn)` của cửa sổ ngữ cảnh trong `config` phiên, đã lọc kiểu.
 *
 * `GET /sessions/{sid}` vốn đã trả `config` trong mỗi vòng poll; đọc nó ở đây là
 * cách duy nhất thanh ngữ cảnh biết con số harness THẬT SỰ đang nén theo, thay vì
 * đoán lại lần thứ tư từ tên model.
 */
function sessionContextWindow(config: Record<string, unknown> | undefined) {
  const tokens = config?.contextWindow
  const source = config?.contextWindowSource
  return {
    contextWindow: typeof tokens === 'number' && Number.isFinite(tokens) && tokens > 0 ? Math.round(tokens) : null,
    contextWindowSource: typeof source === 'string' && source ? source : null,
  }
}

/** `evidence[]` của một hàng `E:` — mục méo bị bỏ, không bịa thêm mục. */
function parseJournalEvidence(value: unknown): JournalEvidenceItem[] {
  if (!Array.isArray(value)) return []
  const items: JournalEvidenceItem[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const type = asString(item.type)
    if (!type) continue
    items.push({ type, path: asString(item.path), command: asString(item.command), note: asString(item.note) })
  }
  return items
}

/** `journal.records` → hàng đã lọc kiểu. Hàng không có `seq` là hàng không gộp được ⇒ bỏ. */
export function parseJournalRows(value: unknown): JournalRow[] {
  if (!Array.isArray(value)) return []
  const rows: JournalRow[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const seq = asNumber(item.seq)
    if (seq === null) continue
    rows.push({
      seq,
      kind: String(item.kind ?? ''),
      text: String(item.text ?? ''),
      id: asString(item.id),
      status: asString(item.status),
      data: item.data && typeof item.data === 'object' ? (item.data as Record<string, unknown>) : {},
      evidence: parseJournalEvidence(item.evidence),
      turn: asNumber(item.turn),
      step: asNumber(item.step),
    })
  }
  return rows.sort((a, b) => a.seq - b.seq)
}

/** Khối `journal` thô của API: `{records, lastSeq, degraded}` (A9). */
export interface JournalPush {
  records: JournalRow[]
  lastSeq: number
  degraded: boolean
}

/**
 * Đọc khối `journal` của `GET /sessions/{sid}`; trả `null` khi harness không gửi khối đó (bản cũ) —
 * chỗ gọi phải giữ nguyên nhật ký đang có thay vì coi như phiên không có bằng chứng nào.
 */
export function parseJournalPush(value: unknown): JournalPush | null {
  if (!value || typeof value !== 'object') return null
  const block = value as Record<string, unknown>
  if (!Array.isArray(block.records)) return null
  const records = parseJournalRows(block.records)
  const declared = asNumber(block.lastSeq)
  return {
    records,
    lastSeq: declared ?? records.at(-1)?.seq ?? 0,
    degraded: block.degraded === true,
  }
}

/**
 * Hàng `E:` theo số LƯỢT. Một lượt chỉ có một hàng (P3.4), nhưng nếu dữ liệu cũ có nhiều hơn thì
 * hàng `seq` lớn nhất thắng — bản mới nhất là bản cổng vừa chấm.
 */
export function evidenceRowsByTurn(records: JournalRow[]): Record<number, JournalRow> {
  const byTurn: Record<number, JournalRow> = {}
  for (const row of records) {
    if (row.kind !== 'evidence' || row.turn === null) continue
    const seen = byTurn[row.turn]
    if (!seen || row.seq > seen.seq) byTurn[row.turn] = row
  }
  return byTurn
}

/**
 * Gộp khối `journal` mới vào nhật ký đang giữ, theo `seq` — cùng luật với `events`: vòng poll
 * 1200 ms không được nhân đôi hàng. API luôn trả 50 hàng cuối nên lần gộp nào cũng chồng lên
 * phần đã có; giữ hợp của hai bên là cách duy nhất để lượt cũ không biến mất khi nhật ký dài.
 *
 * `degraded` là cờ MỘT CHIỀU của phiên (nó đếm các `notice` đã ghim trong bảng `events`, mà bảng
 * đó chỉ ghi thêm): đã từng hỏng thì nói thật là đã từng hỏng, không tự tắt đi.
 */
export function mergeJournal(previous: HarnessJournal | null | undefined, incoming: JournalPush): HarnessJournal {
  const bySeq = new Map<number, JournalRow>()
  for (const row of previous?.records ?? []) bySeq.set(row.seq, row)
  for (const row of incoming.records) bySeq.set(row.seq, row)
  const records = [...bySeq.values()].sort((a, b) => a.seq - b.seq)
  return {
    records,
    lastSeq: Math.max(previous?.lastSeq ?? 0, incoming.lastSeq, records.at(-1)?.seq ?? 0),
    degraded: incoming.degraded || Boolean(previous?.degraded),
    evidenceByTurn: evidenceRowsByTurn(records),
  }
}

/** True khi harness trả lời rằng id phiên không còn tồn tại (mã `SESSION_NOT_FOUND`). */
function isStaleSession(error: unknown): boolean {
  return /SESSION_NOT_FOUND/.test(String(error))
}

/**
 * Vòng 27 / C-5 — đọc câu trả lời của `POST /sessions/{id}/turns` khi lượt đang chạy: harness trả
 * 202 `{status:'steered', steerId}` lúc chỉ thị đã vào hàng đợi. `agentApi` coi 202 là `ok` nên
 * phản hồi này tới đây nguyên vẹn; mọi dạng khác (kể cả `{status:'running'}` của lượt vừa mở) đều
 * không phải "đã xếp hàng", nên không được ghi lời xác nhận.
 */
function parseSteerAccepted(result: unknown): { accepted: boolean; steerId: string | null } {
  if (!result || typeof result !== 'object') return { accepted: false, steerId: null }
  const body = result as Record<string, unknown>
  if (body.status !== 'steered') return { accepted: false, steerId: null }
  return { accepted: true, steerId: typeof body.steerId === 'string' ? body.steerId : null }
}

// A slow older hydration must not replace a newer poll or a newly submitted turn.
const refreshRequests = new Map<string, symbol>()

export const useHarnessChatStore = create<State>((set, get) => ({
  sessions: {},
  decisions: {},
  intentSeq: {},
  refresh: async (chatId) => {
    const captured = get().sessions[chatId]
    const current = captured ?? empty()
    const id = current.id ?? (isHexId(chatId) ? chatId : localStorage.getItem(storageKey(chatId)))
    if (!id) return
    const request = Symbol('session-refresh')
    refreshRequests.set(chatId, request)
    try {
      const lastServerSeq = current.events.filter(e => e.type !== 'model_change').at(-1)?.seq ?? 0
      const session = await readHarnessSessionPages<HarnessSession>(id, lastServerSeq)
      // Thẻ quyết định bền nằm ở `session_decisions`, không phát lại trong `events`, nên phải
      // hỏi bản chuẩn. Chỉ hỏi khi thật sự cần — lần nạp đầu, lúc lượt đang chờ quyết định,
      // hoặc khi vòng poll này mang tới event quyết định mới — để không nhân đôi nhịp 1200ms
      // trong suốt tác vụ dài.
      const decisionEventsArrived = session.events.some(e => (e.type === 'decision_requested' || e.type === 'decision_resolved')
        && !current.events.some(old => old.seq === e.seq && old.type === e.type))
      let canonical: DecisionEntry[] | undefined
      if ('longtask' in session && (!current.decisionsHydrated || session.status === 'awaiting_decision' || decisionEventsArrived)) {
        canonical = []
        let after = ''
        for (let page = 0; page < 50; page++) {
          const result = await agentApi<{ decisions: Record<string, unknown>[]; nextAfter?: string; hasMore?: boolean }>(
            `/sessions/${id}/decisions?state=pending&after=${encodeURIComponent(after)}&limit=20`)
          canonical.push(...canonicalDecisionEntries(result.decisions))
          if (!result.hasMore) break
          if (!result.nextAfter || result.nextAfter === after) throw new Error('DECISION_CURSOR_INVALID')
          after = result.nextAfter
          if (page === 49) throw new Error('DECISION_HYDRATION_INCOMPLETE')
        }
      }
      // A slow full hydration may outlast the poll interval. Let it populate an
      // unchanged cache while another poll is pending, avoiding starvation.
      if (refreshRequests.get(chatId) !== request
        && !(refreshRequests.has(chatId) && get().sessions[chatId] === captured)) return
      if (get().sessions[chatId]?.id && get().sessions[chatId]?.id !== id) return
      const hydrated = get().sessions[chatId] ?? current
      const cachedCursor = hydrated.events.filter(e => e.type !== 'model_change').at(-1)?.seq ?? 0
      if (cachedCursor > (session.events.at(-1)?.seq ?? lastServerSeq)) return
      useMachineStore.getState().bind(chatId, (session.config?.machineBinding as MachineBinding | undefined)
        ?? { mode: 'docker', revision: 1, projectId: null, workspace: '/home/agent/workspace' })
      const prevEvents = hydrated.events ?? []
      // Nhật ký đi cùng vòng poll này (hàng `E:` là bằng chứng của lượt); gộp theo `seq` như `events`.
      const journalPush = parseJournalPush(session.journal)
      const newEvents = session.events.filter(e => !prevEvents.some(old => old.seq === e.seq && old.type === e.type))
      const allEvents = [...prevEvents, ...newEvents]
      // Ý định mở tab: chỉ xét event có `seq` vượt mốc đã xử lý, nên vòng poll
      // 1200ms không mở lại tab cho đúng một event.
      const lastIntentSeq = get().intentSeq[chatId] ?? 0
      const freshEvents = allEvents.filter(e => e.seq > lastIntentSeq)
      const firstHydration = !current.id && prevEvents.length === 0 && lastIntentSeq === 0
      const nextIntentSeq = dispatchTabIntents({ allEvents, freshEvents, lastSeq: lastIntentSeq, firstHydration })
      const isFailed = session.status === 'failed'
      const lastEvent = allEvents.at(-1)
      const lastIsError = lastEvent?.type === 'error'
      // Keep a reported error on screen until the user dismisses it or starts a new turn:
      // the 1200 ms poll must not wipe a message the user is still reading.
      // The harness always reports a message + a code, but a legacy row can still carry an
      // empty one. Say what we know in the code form the panel already understands, instead
      // of the bare "Agent run failed" that tells the user nothing.
      const reportedCode = String(lastEvent?.data?.code ?? 'RUN_FAILED')
      const sessionError = isFailed && lastIsError
        ? String(lastEvent?.data?.message || `${reportedCode}: the run stopped before it reported a reason`)
        : (hydrated.error ?? null)
      set((state) => {
        const parsed = parseDecisions(allEvents)
        const previousDecisions = state.decisions[chatId] ?? []
        // Trả lời thành công đã ghi ngay vào chỗ chứa cục bộ; vòng poll tới muộn
        // hơn không được kéo mục đó về `pending` khi event `decision_resolved`
        // chưa kịp tới.
        const decisions = mergeCanonicalDecisions(previousDecisions, parsed, canonical)

        return {
          sessions: {
            ...state.sessions,
            [chatId]: {
              ...hydrated,
              id,
              status: session.status,
              longtask: newerTask(state.sessions[chatId]?.longtask, session.longtask),
              decisionsHydrated: canonical !== undefined || state.sessions[chatId]?.decisionsHydrated === true,
              goalRevision: session.goalRevision,
              contractRef: session.contractRef,
              error: sessionError,
              events: allEvents,
              journal: journalPush ? mergeJournal(hydrated.journal, journalPush) : hydrated.journal,
              ...sessionContextWindow(session.config),
              researchMode: session.config?.researchMode,
              designMode: session.config?.designMode,
              planMode: session.config?.planMode,
              autopilot: session.config?.autopilot === true,
              // Lời xác nhận "đã xếp hàng" chỉ sống trong lúc lượt còn đang chạy: lượt đã đóng thì
              // nó là thông tin cũ, và bong bóng "can thiệp" trong transcript đã là biên nhận thật.
              steerNotice: session.status === 'running' || session.status === 'awaiting_decision'
                ? hydrated.steerNotice ?? null
                : null,
            },
          },
          decisions: { ...state.decisions, [chatId]: decisions },
          intentSeq: { ...state.intentSeq, [chatId]: nextIntentSeq },
        }
      })
    } catch (error) {
      if (refreshRequests.get(chatId) !== request) return
      const errStr = String(error)
      // Mã máy là thứ đáng tin, câu chữ thì không: bản cũ khớp `'404'`/`'not found'`,
      // mà harness nay trả `SESSION_NOT_FOUND: … is not known to this harness …`,
      // nên nhánh tự dọn này chết lặng và khung chat đỏ mãi. Khớp theo mã, và bỏ
      // luôn id đã chết trong localStorage để lần gửi sau mở phiên mới ngay.
      if (isStaleSession(error) || errStr.includes('404') || errStr.toLowerCase().includes('not found')) {
        localStorage.removeItem(storageKey(chatId))
        localStorage.removeItem(storageKey(id))
        // Session was deleted or not found in database: cleanly purge from cache without displaying red error
        set((state) => {
          const next = { ...state.sessions }
          delete next[chatId]
          const nextDecisions = { ...state.decisions }
          delete nextDecisions[chatId]
          const nextIntentSeq = { ...state.intentSeq }
          delete nextIntentSeq[chatId]
          return { sessions: next, decisions: nextDecisions, intentSeq: nextIntentSeq }
        })
        return
      }
      set((state) => ({
        sessions: { ...state.sessions, [chatId]: { ...(state.sessions[chatId] ?? current), id, status: 'failed', error: errStr } },
        ...(current.longtask !== undefined ? { decisions: { ...state.decisions, [chatId]: (state.decisions[chatId] ?? []).map(entry => ({ ...entry, actionable: false })) } } : {}),
      }))
    } finally {
      if (refreshRequests.get(chatId) === request) refreshRequests.delete(chatId)
    }
  },
  fetchSavedSessions: async () => {
    try {
      const data = await agentApi<{ sessions: Array<{ id: string; role: string; status: string; updated: number; config: Record<string, unknown> }> }>('/sessions')
      for (const row of data.sessions) useMachineStore.getState().bind(row.id,
        (row.config.machineBinding as MachineBinding | undefined) ?? { mode: 'docker', revision: 1, projectId: null, workspace: '/home/agent/workspace' })
      return data.sessions || []
    } catch {
      return []
    }
  },
  deleteSession: async (id: string, operation) => {
    try {
      if (!operation?.operationId || !(/^[a-f0-9]{64}$/.test(operation.expectedRevision))) throw new Error('DELETE_REQUIRES_CARRY_FORWARD')
      const result = await agentApi<{ status: string }>(`/sessions/${id}/deletion-confirm`, { ...operation, confirm: true })
      if (result.status !== 'deleted') return result
      localStorage.removeItem(storageKey(id))
      set((state) => {
        const next = { ...state.sessions }
        delete next[id]
        return { sessions: next }
      })
      return result
    } catch (error) {
      console.error('Failed to delete session:', error)
      throw error
    }
  },
  send: async (chatId, prompt, selection, image, modelLabel, thinkingLevels, images, attachments) => {
    const current = get().sessions[chatId] ?? empty()
    // Capture before asynchronous skill/directive loading; another chat may change defaults meanwhile.
    const machineState = useMachineStore.getState()
    const selectedMachine = machineState.bindings[chatId] ?? machineState.configuration
    const control = /^\/(help|skills|agents|status|context|stop)\s*$/.test(prompt)
    // Vòng 27 / C-5 — lượt ĐANG chạy vẫn nhận chỉ thị của chủ nhà: câu này vào hàng đợi
    // (`session_steers` của harness) và main đọc ở BƯỚC KẾ, nên không còn bị chặn tại chỗ.
    // Chỉ `starting` mới còn khoá (lượt chưa mở xong, chưa có bước nào để áp), và phiên con
    // vẫn bị harness trả 409 `SESSION_BUSY` như trước — lỗi ấy hiện nguyên trong banner.
    const steering = !control && (current.status === 'running' || current.status === 'awaiting_decision')
    if (current.status === 'starting' && !control) return
    refreshRequests.delete(chatId)
    if (control && current.id) {
      try {
        await agentApi(`/sessions/${current.id}/turns`, { prompt, invocationId: crypto.randomUUID() })
        await get().refresh(chatId)
      } catch (error) {
        set(state => ({ sessions: { ...state.sessions, [chatId]: { ...current, error: String(error) } } }))
      }
      return
    }

    const prevModel = current.lastModelLabel
    const newModel = modelLabel || (selection?.kind === 'model' ? selection.modelId : selection?.kind === 'provider' ? selection.modelId : selection?.kind === 'alias' ? selection.aliasId : undefined)

    const updatedEvents = [...current.events]
    if (!steering && prevModel && newModel && prevModel !== newModel && updatedEvents.length > 0) {
      const changeEvent: HarnessEvent = {
        seq: Date.now(),
        type: 'model_change',
        data: { from: prevModel, to: newModel },
        created: Date.now(),
      }
      updatedEvents.push(changeEvent)
    }

    // Chỉ thị giữa lượt KHÔNG mở lượt mới: trạng thái `running` giữ nguyên, danh sách event giữ
    // nguyên — lượt đang chạy phải tiếp tục hiện đúng nội dung của nó (C-5).
    if (steering) {
      set((state) => ({
        sessions: {
          ...state.sessions,
          [chatId]: { ...current, error: null, steerNotice: null },
        },
      }))
    } else {
      set((state) => ({
        sessions: {
          ...state.sessions,
          [chatId]: {
            ...current,
            events: updatedEvents,
            lastModelLabel: newModel || current.lastModelLabel,
            status: 'starting',
            error: null,
            steerNotice: null,
          },
        },
      }))
    }
    /** Mở phiên mới cho khung chat này; trả id để lượt sau dùng lại. */
    const openSession = async (): Promise<string> => {
      {
        const harnessStore = useHarnessStore.getState()
        const isSingleModel = harnessStore.activeType === 'model'
        const harness = harnessStore.getHarnessById(harnessStore.activeHarnessId)
        await useSkillsStore.getState().load()
        // Chỉ dẫn của chủ sở hữu đọc trước khi mở phiên. Lỗi mạng thì phiên VẪN mở, nhưng
        // không mang chỉ dẫn — và sổ ghi phiên ghi lại lý do để tab Instructions nói thật,
        // thay vì im lặng coi như đã gửi.
        const directivesLoaded = await useOwnerSettingsStore.getState().ensureLoaded()
        const ownerDirectives = useOwnerSettingsStore.getState()
        const skills = useSkillsStore.getState().skills.filter(s => s.enabled).map(s => s.id)
        const route = selection?.kind === 'model' ? { connectionId: selection.connectionId, modelId: selection.modelId }
          : selection?.kind === 'provider' ? { providerId: selection.providerId, modelId: selection.modelId }
          : selection?.kind === 'alias' ? { aliasId: selection.aliasId } : {}
        // Chỉ gửi trần bước/thời gian/công cụ khi harness thật sự đặt chúng: thiếu trường
        // nghĩa là engine tự quyết, không phải client gửi số đoán.
        const tuning = {
          ...(harness?.maxSteps !== undefined ? { maxSteps: harness.maxSteps } : {}),
          ...(harness?.deadlineSeconds !== undefined ? { deadlineSeconds: harness.deadlineSeconds } : {}),
          ...(harness?.tools !== undefined ? { tools: harness.tools } : {}),
        }
        
        // Single Model Mode: When user selects Single Model, override entire harness with this single model
        const singleModelId = isSingleModel
          ? (selection?.kind === 'model' ? `model:${selection.connectionId}:${selection.modelId}`
            : selection?.kind === 'provider' ? `provider:${selection.providerId}:${selection.modelId}`
            : harnessStore.activeModelId)
          : null

        const session = await agentApi<HarnessSession>('/sessions', {
          ...route,
          ...(selectedMachine ? { machineSelection: {
            mode: selectedMachine.mode,
            projectId: selectedMachine.projectId,
          } } : {}),
          skills,
          ...(harness ? { harnessId: harness.id } : {}),
          ...(directivesLoaded ? { instructions: ownerDirectives.instructions } : {}),
          ...tuning,
          subagents: isSingleModel && singleModelId
            ? harness?.subagents?.map(s => ({ ...s, model: singleModelId })) ?? []
            : harness?.subagents,
          ...(singleModelId ? { singleModel: singleModelId, model: singleModelId, isSingleModel: true }
              : (harness?.mainModel && harness.mainModel !== 'default' ? { model: harness.mainModel } : {}))
        })
        useSessionRecordStore.getState().record(session.id, {
          harnessId: harness?.id ?? '',
          instructionsChars: directivesLoaded ? [...ownerDirectives.instructions].length : 0,
          ...(directivesLoaded ? {} : { directivesSkipped: ownerDirectives.loadError ?? 'the harness did not answer' }),
        })
        localStorage.setItem(storageKey(session.id), session.id)
        if (session.config?.machineBinding) useMachineStore.getState().bind(chatId, session.config.machineBinding as MachineBinding)
        // Phiên vừa mở đã mang sẵn cặp (số, nguồn): hiện ngay, không phải chờ vòng poll
        // đầu tiên. Cùng một phản hồi `/sessions`, không thêm lời gọi mạng nào.
        if (session.config) {
          set(state => ({ sessions: { ...state.sessions,
            [chatId]: { ...(state.sessions[chatId] ?? current), ...sessionContextWindow(session.config), autopilot: session.config?.autopilot === true } } }))
        }
        return session.id
      }
      throw new Error('SESSION_NOT_FOUND: could not open a harness session')
    }

    // `image` (số ít) vẫn được gửi để tương thích với harness cũ trong lúc triển khai A7;
    // `images` là hợp đồng mới (nhiều ảnh) và `attachments` là tệp đã nằm thật trên đĩa box.
    const submitTurn = (id: string, route: unknown) => agentApi(`/sessions/${id}/turns`, {
      prompt: prompt || (attachments?.length ? 'Inspect the attached files.' : 'Inspect the attached image.'),
      image: images?.[0] ?? image,
      ...(images?.length ? { images } : {}),
      ...(attachments?.length ? { attachments } : {}),
      route,
      invocationId: crypto.randomUUID() })

    try {
      let id = current.id ?? (isHexId(chatId) ? chatId : localStorage.getItem(storageKey(chatId)))
      if (!id) {
        id = await openSession()
        localStorage.setItem(storageKey(chatId), id)
      }
      // Mức thinking chỉ được là mức model đã công bố: `thinkingLevels` của model
      // đang chọn tới từ đây, để composer không gửi `medium` cho một model chỉ có
      // `max/high/low` (harness trả THINKING_LEVEL_UNSUPPORTED và lượt chết).
      // Tuyến alias và tuyến provider đều không mang danh sách mức của MỘT đích: mỗi
      // tuyến là nhiều đích, và khi không biết model nào sẽ nhận lượt thì gửi kèm một
      // mức là đoán bừa — bỏ hẳn để router tự chọn mức mặc định của đích nó chọn.
      // (Danh sách mức của tuyến provider là GIAO mức của mọi connection trong nhóm.)
      const levelKnown = Array.isArray(thinkingLevels) && thinkingLevels.length > 0
      const thinkingLevel = (selection?.kind === 'alias' || selection?.kind === 'provider') && !levelKnown
        ? undefined
        : resolveThinkingLevel(thinkingLevels, useHarnessStore.getState().thinkingLevel)
      const route = selection?.kind === 'model'
        ? { connectionId: selection.connectionId, modelId: selection.modelId, ...(thinkingLevel ? { thinkingLevel } : {}) }
        : selection?.kind === 'provider'
        ? { providerId: selection.providerId, modelId: selection.modelId, ...(thinkingLevel ? { thinkingLevel } : {}) }
        : selection?.kind === 'alias'
        ? { aliasId: selection.aliasId, ...(thinkingLevel ? { thinkingLevel } : {}) }
        : {}
      let turnResult: unknown
      try {
        turnResult = await submitTurn(id, route)
      } catch (error) {
        // Id phiên mà harness không còn biết (phiên bị xoá, hoặc harness chạy lại với store
        // mới) trước đây làm mọi lần gửi hỏng mãi với đúng một chữ "Not found". Mở phiên mới
        // rồi gửi lại lượt **một lần** — đúng lần thử lại mà người dùng mong có.
        if (!isStaleSession(error)) throw error
        localStorage.removeItem(storageKey(chatId))
        localStorage.removeItem(storageKey(id))
        id = await openSession()
        localStorage.setItem(storageKey(chatId), id)
        // Id mới phải vào **store** ngay: vòng poll 1200 ms và lần gửi sau đều đọc
        // `sessions[chatId].id` trước, nên nếu chỉ ghi localStorage thì cả hai vẫn
        // nhắm vào id đã chết và khung chat đỏ vĩnh viễn dù lượt đã chạy xong.
        set(state => ({ sessions: { ...state.sessions, [chatId]: { ...(state.sessions[chatId] ?? current), id, error: null } } }))
        turnResult = await submitTurn(id, route)
      }
      // 202 `{status:'steered'}` (Vòng 27 / C-5): harness đã NHẬN câu này vào hàng đợi của lượt
      // đang chạy ⇒ ghi lại lời xác nhận kèm nguyên văn, KHÔNG đóng lượt và không xoá nội dung
      // đang chạy. Đây là đường duy nhất để ô soạn tin nói thật "đã nhận" thay vì im lặng.
      const steer = parseSteerAccepted(turnResult)
      if (steer.accepted) {
        set(state => ({
          sessions: {
            ...state.sessions,
            [chatId]: {
              ...(state.sessions[chatId] ?? current),
              error: null,
              steerNotice: { text: prompt, at: Date.now(), steerId: steer.steerId },
            },
          },
        }))
      }
      await get().refresh(chatId)
    } catch (error) {
      // Chỉ thị bị từ chối (`BOXFOX_STEER=off` ⇒ 409, hàng đầy ⇒ `STEER_QUEUE_FULL`) KHÔNG làm
      // lượt đang chạy thành `failed`: lượt vẫn sống ở harness, chỉ câu vừa gõ là không được nhận,
      // nên giữ nguyên trạng thái và chỉ nêu lỗi (banner ngay trên ô nhập).
      set((state) => ({ sessions: { ...state.sessions,
        [chatId]: steering
          ? { ...(state.sessions[chatId] ?? current), error: String(error), steerNotice: null }
          : { ...(state.sessions[chatId] ?? current), status: 'failed', error: String(error) } } }))
    }
  },

  stop: async (chatId) => {
    const id = get().sessions[chatId]?.id ?? (isHexId(chatId) ? chatId : null)
    if (!id) return
    try { await agentApi(`/sessions/${id}/stop`, {}); await get().refresh(chatId) }
    catch (error) { set((state) => ({ sessions: { ...state.sessions, [chatId]: { ...state.sessions[chatId], error: String(error) } } })) }
  },

  answerDecision: async (chatId, decisionId, choice, note, answers) => {
    const current = get().sessions[chatId] ?? empty()
    const id = current.id ?? (isHexId(chatId) ? chatId : localStorage.getItem(storageKey(chatId)))
    if (!id) {
      set((state) => ({
        sessions: {
          ...state.sessions,
          [chatId]: { ...current, error: 'DECISION_UNKNOWN_SESSION: no harness session for this chat' },
        },
      }))
      return
    }
    const target = get().decisions[chatId]?.find(entry => entry.id === decisionId)
    if (target?.actionable === false || (target && target.status !== 'pending')) return
    try {
      const result = await agentApi<{
        status: string
        decisionId: string
        choice: string
        outcome: string
        answers?: unknown
        revision?: number
      }>(`/sessions/${id}/decisions`, {
        decisionId,
        choice,
        ...(target?.revision !== undefined ? { invocationId: continuityInvocation([id, decisionId, target.revision, choice, note, answers]) } : {}),
        ...(target?.revision !== undefined ? { expectedRevision: target.revision } : {}),
        ...(note ? { note } : {}),
        ...(answers ? { answers } : {}),
      })
      set((state) => {
        const list = state.decisions[chatId] ?? parseDecisions(current.events)
        const decisions = list.map((entry) => {
          if (entry.id !== decisionId || (result.revision !== undefined && (entry.revision ?? 0) > result.revision)) return entry
          const optionKind = entry.options.find((option) => option.id === choice)?.kind
          const outcome = decisionStatusFrom(result?.outcome)
          return {
            ...entry,
            revision: result.revision ?? entry.revision,
            status: outcome !== 'pending' ? outcome : optionKind === 'reject' ? 'rejected' : 'approved',
            choice: result?.choice ?? choice,
            note: note ?? null,
            resolvedReason: 'user' as DecisionResolveReason,
            resolvedAt: Date.now() / 1000,
            ...(Array.isArray(result?.answers) ? { answers: parseInterviewAnswers(result.answers) } : {}),
          }
        })
        return { decisions: { ...state.decisions, [chatId]: decisions } }
      })
      // Kéo `decision_resolved` về sớm để hàng trong transcript cũng tắt trạng
      // thái "đang chờ" — câu trả lời đã nằm trong store từ dòng trên rồi.
      void get().refresh(chatId)
    } catch (error) {
      set((state) => ({
        sessions: {
          ...state.sessions,
          [chatId]: { ...(state.sessions[chatId] ?? current), error: String(error) },
        },
      }))
    }
  },

  clearError: (chatId: string) => {
    set((state) => ({
      sessions: {
        ...state.sessions,
        [chatId]: {
          ...(state.sessions[chatId] ?? empty()),
          error: null,
        },
      },
    }))
  },
}))
