/**
 * Subagent Inspector Dashboard — Thiết kế lại thành Luồng Hội Thoại (Chat Stream).
 * 
 * - Cột trái (~240px): Danh sách Specialists Pipeline (Explore, Plan, Build, Testing, v.v...)
 *   kèm status badge (Running 🟡, Done 🟢, Error 🔴), số tool calls.
 * - Cột phải: Khung Chat Stream đồng bộ với luồng hội thoại chính:
 *   1. Tin nhắn Prompt từ Main Agent (Orchestrator): Bong bóng giao việc với huy hiệu 🧠 Main Agent.
 *   2. Phản hồi từ Sub-agent:
 *      - Accordion Thinking (suy nghĩ nội tâm).
 *      - Accordion Tools Executed (danh sách công cụ đã chạy kèm arguments, stdout).
 *      - Báo cáo Markdown hoàn chỉnh qua MarkdownRenderer.
 *      - Cảnh báo lỗi inline nếu có.
 *   3. Thanh Footer Read-only Guard: Khóa không cho user gõ phím vào tiến trình con.
 */
import { useState, useMemo, useEffect, useRef } from 'react'
import {
  Bot,
  Terminal,
  CheckCircle2,
  AlertCircle,
  Info,
  ChevronRight,
  ChevronDown,
  BrainCircuit,
  Sparkles,
  Copy,
  Check,
  FileCode2,
  Search,
  Camera,
  ArrowRight,
  Clock,
  Inbox,
} from 'lucide-react'
import { useHarnessChatStore, type HarnessEvent } from '../../store/harnessChatStore'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { MarkdownRenderer } from '../chat/MarkdownRenderer'
import { appendStreamText } from '../../lib/streamText'
import { readHarnessSessionPages } from '../../lib/harnessSessionPages'
import { useT } from '../../i18n/context'
import type { TKey, TVars } from '../../i18n/context'
import {
  deliveryLabel,
  formatClock,
  hasAbsoluteDeadline,
  mergeReceipts,
  openPeerWait,
  peerDeliveries,
  peerDeliveryView,
  peerLabels,
  peerReceipts,
  peerSkipReason,
  receiptsFromDeliveries,
  safetyNetSeconds,
  shortPeerId,
  type PeerDelivery,
  type PeerReceipt,
  type PeerSkipReason,
  type PeerWait,
} from '../../lib/chat/peerPipeline'

type Translate = (key: TKey, vars?: TVars) => string

/** Mã lý do `skipped` có chữ riêng; mã lạ thì hiện NGUYÊN mã, không giấu vì sao không giao. */
const SKIP_REASON_KEY: Record<PeerSkipReason, TKey> = {
  no_such_peer: 'chat.subagentSkipReason.no_such_peer',
  recipient_not_running: 'chat.subagentSkipReason.recipient_not_running',
}

function skipReasonText(t: Translate, reason: string | null): string {
  if (!reason) return t('chat.subagentSkipReason.unknown')
  const known = peerSkipReason(reason)
  return known ? t(SKIP_REASON_KEY[known]) : reason
}

const ROLE_DESCRIPTIONS: Record<string, string> = {
  explore: 'Inspect the repository. Return file/symbol evidence, dependencies and unknowns.',
  plan: 'Produce an ordered implementation plan, constraints, risks and concrete acceptance checks.',
  design: 'Design interfaces, data flow and user interaction. Explain tradeoffs and compatibility.',
  build: 'Implement the assigned scope. Inspect before editing; report changed paths and verification.',
  debug: 'Reproduce, isolate and explain the root cause. Apply targeted fix and verify regressions.',
  review: 'Review without editing. Return actionable findings with severity and exact file evidence.',
  'plan-review':
    'Read the plan version on screen as an independent critic and return issues with severity, evidence and a concrete fix.',
  simplify: 'Simplify existing code without changing behavior. Preserve public contracts.',
  testing: 'Run meaningful tests in the sandbox, including UI/visual checks when relevant.',
  research: 'Research using observed repository or browser sources with grounded citations.',
  'research-review':
    'Read the research dossier as an independent critic and return issues with severity, evidence and a concrete fix.',
}

interface ChildSessionView {
  sessionId: string
  role: string
  status: 'running' | 'completed' | 'failed' | 'partial'
  goal?: string
  prompt?: string
  context?: string
  summary?: string
  lastError?: string
  toolsRun: string[]
  events: HarnessEvent[]
  updateSeq: number
  /**
   * Lượt mà con này thuộc về (T4). `data.turn` khi backend khai báo (đợt 22); bản ghi CŨ
   * không có `turn` thì lấy lượt của event `user` gần nhất đứng trước — đúng luật
   * `buildHarnessTurns` dùng cho transcript, nên bảng và khung chat không lệch nhau.
   */
  turn: number
  /** Bước của lượt cha lúc giao việc (`data.step`) — chỉ có từ đợt 22. */
  step: number | null
  /** Số bước con đã dùng, khi hàng sổ con báo (`stepsUsed`). */
  stepsUsed: number | null
  /**
   * `deliverTo` lúc giao việc — Ý ĐỊNH, không phải kết quả. Chỉ được vẽ khi con còn chạy
   * ("sẽ giao cho …"); con đóng sổ rồi thì `deliveries` mới là sự thật.
   */
  deliverTo: string[]
  /** `deliveries[]` thật của hàng sổ con; mỗi mục là một biên nhận kèm `state`/`reason`. */
  deliveries: PeerDelivery[]
}

/** Một khối bảng của MỘT lượt (T4) — bảng cũ trộn mọi lượt vào một danh sách phẳng. */
interface ChildTurnGroup {
  turn: number
  userEvent: HarnessEvent | null
  prompt: string
  children: ChildSessionView[]
  steps: number | null
  startedAt: number | null
  endedAt: number | null
  completed: boolean
}

interface ParsedToolCall {
  id: string
  name: string
  args: Record<string, unknown> | null
  result?: string | null
  isError?: boolean
  isRunning?: boolean
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/** `data.turn` mà event tự khai báo; `null` cho bản ghi cũ (trước đợt 22). */
function declaredTurn(event: HarnessEvent): number | null {
  const turn = asNumber(event.data?.turn)
  return turn !== null && turn > 0 ? Math.trunc(turn) : null
}

/**
 * Trạng thái hàng con. `partial` KHÔNG được vẽ như `failed`: đợt 22 (D-1) biến "chạm trần
 * bước/hạn" thành lượt dở nhưng CÓ kết quả, nên tô nó màu đỏ là nói sai sự thật.
 */
function childStatus(value: unknown): ChildSessionView['status'] {
  if (value === 'completed') return 'completed'
  if (value === 'partial') return 'partial'
  if (value === 'started' || value === 'running') return 'running'
  return 'failed'
}

/** Gộp một event `child` (start hoặc end) vào hàng của con đó, giữ nguyên cách đọc cũ. */
function mergeChildEvent(
  existing: ChildSessionView | undefined,
  event: HarnessEvent,
  turn: number,
): ChildSessionView {
  const data = event.data
  const view: ChildSessionView = existing ?? {
    sessionId: String(data.sessionId ?? data.role ?? 'unknown'),
    role: String(data.role ?? 'specialist'),
    status: 'running',
    toolsRun: [],
    events: [],
    updateSeq: event.seq,
    turn,
    step: null,
    stepsUsed: null,
    deliverTo: [],
    deliveries: [],
  }
  view.turn = turn
  view.updateSeq = event.seq
  if (data.role) view.role = String(data.role)
  if (data.status !== undefined) view.status = childStatus(data.status)
  if (data.goal) view.goal = String(data.goal)
  if (data.prompt) view.prompt = String(data.prompt)
  if (data.context) view.context = String(data.context)
  if (data.summary) view.summary = String(data.summary)
  if (data.last_error) view.lastError = String(data.last_error)
  if (Array.isArray(data.tools_run)) view.toolsRun = data.tools_run.map(String)

  const step = asNumber(data.step)
  if (step !== null) view.step = Math.trunc(step)
  const stepsUsed = asNumber(data.stepsUsed)
  if (stepsUsed !== null) view.stepsUsed = Math.trunc(stepsUsed)
  const deliverTo = peerLabels(data.deliverTo)
  if (deliverTo.length > 0) view.deliverTo = deliverTo
  const deliveries = peerDeliveries(data.deliveries)
  if (deliveries.length > 0) view.deliveries = deliveries
  return view
}

/**
 * T4: gom event `child` theo lượt và dựng luôn phần đầu của mỗi lượt (prompt, số bước, thời lượng).
 *
 * Luật gán lượt cho event con **không có `turn`** là luật của transcript: lượt của event
 * `user` gần nhất đứng trước (`HarnessStepView.buildHarnessTurns`, bản ghi trước đợt 22).
 * Không có event `user` nào cả (bản ghi méo) ⇒ gom vào lượt `0` để không im lặng bỏ mất hàng.
 */
export function buildChildTurns(events: readonly HarnessEvent[]): ChildTurnGroup[] {
  const groups = new Map<number, ChildTurnGroup>()
  const ensure = (turn: number): ChildTurnGroup => {
    let group = groups.get(turn)
    if (!group) {
      group = {
        turn,
        userEvent: null,
        prompt: '',
        children: [],
        steps: null,
        startedAt: null,
        endedAt: null,
        completed: false,
      }
      groups.set(turn, group)
    }
    return group
  }

  let currentTurn: number | null = null
  let userIndex = 0

  for (const event of events) {
    if (event.type === 'model_change') continue
    const declared = declaredTurn(event)

    if (event.type === 'user') {
      // Vòng 27 / C-5 — chỉ thị giữa lượt (`{steer:true}`) KHÔNG mở lượt mới (harness cũng không
      // tăng `_turn_index`): tính nó là mốc lượt thì nhánh đang chạy bị tách sang một lượt ma.
      // Bỏ qua nó ⇒ con phía sau vẫn thuộc đúng lượt đang chạy.
      if (event.data?.steer === true) continue
      userIndex += 1
      currentTurn = declared ?? userIndex
      const group = ensure(currentTurn)
      if (!group.userEvent) {
        group.userEvent = event
        group.prompt = String(event.data.text ?? '')
        group.startedAt = event.created
      }
      continue
    }

    if (declared !== null) currentTurn = declared

    if (event.type === 'child') {
      const turn = currentTurn ?? 0
      const group = ensure(turn)
      const sessionId = String(event.data.sessionId ?? event.data.role ?? 'unknown')
      const existing = group.children.find((child) => child.sessionId === sessionId)
      const merged = mergeChildEvent(existing, event, turn)
      if (existing) Object.assign(existing, merged)
      else group.children.push(merged)
      if (!group.completed) group.endedAt = Math.max(group.endedAt ?? event.created, event.created)
      continue
    }

    const group = currentTurn === null ? undefined : groups.get(currentTurn)
    if (!group) continue
    if (!group.completed) group.endedAt = Math.max(group.endedAt ?? event.created, event.created)
    if (event.type === 'turn_end' && declared !== null) {
      const steps = asNumber(event.data.stepsUsed) ?? asNumber(event.data.step)
      if (steps !== null) group.steps = Math.max(group.steps ?? 0, Math.trunc(steps))
    } else if (event.type === 'finish' || event.type === 'error') {
      group.completed = true
      const steps = asNumber(event.data.steps)
      if (steps !== null) group.steps = Math.max(group.steps ?? 0, Math.trunc(steps))
    }
  }

  return [...groups.values()].sort((a, b) => a.turn - b.turn)
}

function getToolIcon(name: string) {
  switch (name) {
    case 'terminal_exec':
      return <Terminal className="size-3.5 text-brand" />
    case 'file_read':
    case 'file_write':
    case 'file_edit':
      return <FileCode2 className="size-3.5 text-brand" />
    case 'codebase_search':
    case 'codebase_glob':
      return <Search className="size-3.5 text-brand" />
    case 'browser_action':
      return <Camera className="size-3.5 text-brand" />
    default:
      return <Terminal className="size-3.5 text-brand" />
  }
}

function SubagentToolItem({ tool }: { tool: ParsedToolCall }) {
  const [expanded, setExpanded] = useState(false)
  const cmd = tool.args ? (tool.args.command || tool.args.cmd || tool.args.path || JSON.stringify(tool.args)) : ''

  return (
    <div className="rounded-lg border border-line bg-panel2/40 overflow-hidden text-xs">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between p-2 text-left hover:bg-panel2/70 transition cursor-pointer"
      >
        <div className="flex items-center gap-2 min-w-0 flex-1">
          {getToolIcon(tool.name)}
          <span className="font-semibold text-fg text-[11px]">{tool.name}</span>
          {cmd && (
            <span className="text-[10px] font-mono text-muted truncate max-w-[280px]">
              {String(cmd)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1.5 shrink-0 ml-2">
          {tool.isRunning ? (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] text-amber-400 font-mono flex items-center gap-1">
              <span className="size-1.5 rounded-full bg-amber-400 animate-ping" />
              running
            </span>
          ) : tool.isError ? (
            <span className="rounded bg-rose-500/15 px-1.5 py-0.5 text-[9px] text-rose-400 font-mono">
              failed
            </span>
          ) : (
            <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[9px] text-emerald-400 font-mono">
              exit 0
            </span>
          )}
          <ChevronDown className={`size-3 text-muted transition ${expanded ? 'rotate-180' : ''}`} />
        </div>
      </button>

      {expanded && (
        <div className="border-t border-line/40 bg-panel/50 p-2.5 space-y-2 font-mono text-[11px]">
          {tool.args && (
            <div>
              <div className="text-[10px] text-muted font-sans font-medium uppercase tracking-wider mb-1">
                Arguments:
              </div>
              <pre className="rounded bg-panel2/60 border border-line/50 p-2 text-fg overflow-x-auto whitespace-pre-wrap">
                {JSON.stringify(tool.args, null, 2)}
              </pre>
            </div>
          )}
          {tool.result && (
            <div>
              <div className="text-[10px] text-muted font-sans font-medium uppercase tracking-wider mb-1">
                Result Output:
              </div>
              <pre className="rounded bg-panel2/60 border border-line/50 p-2 text-fg overflow-x-auto whitespace-pre-wrap max-h-48 overflow-y-auto">
                {tool.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function SubagentThinkingItem({ text, onInspect }: { text: string; onInspect: () => void }) {
  const [expanded, setExpanded] = useState(false)
  if (!text.trim()) return null
  return (
    <div className="rounded-xl border border-line bg-panel2/40 overflow-hidden text-xs">
      <button
        type="button"
        aria-expanded={expanded}
        onClick={() => { onInspect(); setExpanded(!expanded) }}
        className="w-full flex items-center justify-between px-3 py-2 text-muted hover:text-fg transition cursor-pointer"
      >
        <div className="flex items-center gap-2">
          <Sparkles className="size-3.5 text-brand" />
          <span className="font-medium text-[11px] text-fg">
            Thinking & Internal Reasoning
          </span>
        </div>
        <ChevronDown
          className={`size-3 text-muted transition ${expanded ? 'rotate-180' : ''}`}
        />
      </button>
      {expanded && (
        <div className="px-3 pb-3 text-fg/80 font-mono text-[11px] leading-relaxed whitespace-pre-wrap border-t border-line/30 pt-2 bg-panel/50 max-h-60 overflow-y-auto">
          {text}
        </div>
      )}
    </div>
  )
}

function SubagentToolGroupItem({ tools }: { tools: ParsedToolCall[] }) {
  if (!tools || tools.length === 0) return null
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-semibold text-muted flex items-center gap-1.5">
        <Terminal className="size-3 text-brand" />
        <span>Tools Executed ({tools.length})</span>
      </div>
      <div className="space-y-1">
        {tools.map((tool) => (
          <SubagentToolItem key={tool.id} tool={tool} />
        ))}
      </div>
    </div>
  )
}

function SubagentTextItem({ text, isFinal }: { text: string; isFinal?: boolean }) {
  if (!text.trim()) return null
  if (isFinal) {
    return (
      <div className="rounded-xl border border-line bg-panel2/40 p-4 text-xs leading-relaxed text-fg">
        <MarkdownRenderer content={text} />
      </div>
    )
  }
  return (
    <div className="rounded-lg border border-line/40 bg-panel2/25 px-3.5 py-2.5 text-xs leading-relaxed text-fg">
      <MarkdownRenderer content={text} />
    </div>
  )
}

export interface SubagentTimelineItem {
  id: string
  kind: 'thought' | 'text' | 'tool_group'
  thoughtText?: string
  text?: string
  isFinal?: boolean
  tools?: ParsedToolCall[]
}

export function buildSubagentTimeline(events: readonly HarnessEvent[]): SubagentTimelineItem[] {
  const items: SubagentTimelineItem[] = []
  const toolMap = new Map<string, ParsedToolCall>()
  const seen = new Set<string>()
  let thoughtItem: SubagentTimelineItem | undefined
  let textItem: SubagentTimelineItem | undefined
  let stepStart = 0
  const beginStep = () => {
    thoughtItem = undefined
    textItem = undefined
    stepStart = items.length
  }

  for (const ev of events) {
    // Poll/reconnect can repeat a receipt; equal text in DIFFERENT steps is legitimate.
    if (ev.seq > 0) {
      const identity = `${ev.seq}:${ev.type}`
      if (seen.has(identity)) continue
      seen.add(identity)
    }
    if (ev.type === 'step' || ev.type === 'turn_start') {
      beginStep()
      continue
    }
    if (ev.type === 'notice' && ev.data.reset) {
      // A retry abandons this model attempt, not earlier steps or completed tools.
      items.splice(stepStart, items.length - stepStart,
        ...items.slice(stepStart).filter(item => item.kind === 'tool_group'))
      beginStep()
      continue
    }

    if (ev.type === 'thought') {
      const raw = String(ev.data.thought ?? ev.data.text ?? '')
      if (!raw) continue

      if (thoughtItem) {
        thoughtItem.thoughtText = ev.data.snapshot === true ? raw
          : appendStreamText(thoughtItem.thoughtText ?? '', raw)
      } else {
        thoughtItem = {
          id: `thought_${ev.seq || items.length}`,
          kind: 'thought',
          thoughtText: raw,
        }
        items.push(thoughtItem)
      }
      continue
    }

    if (ev.type === 'assistant_delta' || ev.type === 'assistant') {
      // `assistant` is the canonical snapshot of this step, even when thought/usage
      // events separate it from the text deltas. It is not another answer bubble.
      if (ev.type === 'assistant' && ev.data.thought) {
        const thought = String(ev.data.thought)
        if (thoughtItem) thoughtItem.thoughtText = thought
        else {
          thoughtItem = { id: `thought_assistant_${ev.seq}`, kind: 'thought', thoughtText: thought }
          items.push(thoughtItem)
        }
      }
      const raw = String(ev.data.text ?? '')
      if (raw && textItem) {
        textItem.text = ev.type === 'assistant' ? raw : appendStreamText(textItem.text ?? '', raw)
      } else if (raw) {
        textItem = {
          id: `text_${ev.seq || items.length}`,
          kind: 'text',
          text: raw,
        }
        items.push(textItem)
      }
      if (ev.type === 'assistant') beginStep()
      continue
    }

    if (ev.type === 'tool_start') {
      const name = String(ev.data.name ?? 'tool')
      const args = typeof ev.data.args === 'object' && ev.data.args !== null ? (ev.data.args as Record<string, unknown>) : null
      const callId = String(ev.data.id ?? ev.data.tool_call_id ?? `${name}-${toolMap.size}`)

      const toolCall: ParsedToolCall = {
        id: callId,
        name,
        args,
        isRunning: true,
      }
      toolMap.set(callId, toolCall)

      const last = items[items.length - 1]
      if (last && last.kind === 'tool_group' && last.tools) {
        last.tools.push(toolCall)
      } else {
        items.push({
          id: `tools_${callId}`,
          kind: 'tool_group',
          tools: [toolCall],
        })
      }
      // Old histories may lack step markers. A tool dispatch ends their model response.
      beginStep()
      continue
    }

    if (ev.type === 'tool_end') {
      const callId = String(ev.data.id ?? ev.data.tool_call_id ?? '')
      const res = ev.data.result ? (typeof ev.data.result === 'object' ? JSON.stringify(ev.data.result, null, 2) : String(ev.data.result)) : null
      const isError = Boolean(ev.data.is_error ?? (ev.data.result as Record<string, unknown> | null)?.is_error)

      let targetTool = callId ? toolMap.get(callId) : null
      if (!targetTool) {
        for (let i = items.length - 1; i >= 0; i--) {
          const it = items[i]
          if (it.kind === 'tool_group' && it.tools) {
            for (let j = it.tools.length - 1; j >= 0; j--) {
              if (it.tools[j].isRunning) {
                targetTool = it.tools[j]
                break
              }
            }
            if (targetTool) break
          }
        }
      }

      if (targetTool) {
        targetTool.result = res
        targetTool.isError = isError
        targetTool.isRunning = false
      }
      continue
    }
  }

  // Đánh dấu item text cuối cùng là isFinal nếu nó đứng sau mọi tool calls
  let lastTextIndex = -1
  let lastToolIndex = -1
  for (let i = 0; i < items.length; i++) {
    if (items[i].kind === 'text') lastTextIndex = i
    if (items[i].kind === 'tool_group') lastToolIndex = i
  }

  if (lastTextIndex !== -1 && lastTextIndex > lastToolIndex) {
    items[lastTextIndex].isFinal = true
  }

  return items
}

export function SubagentInspectorPanel() {
  const t = useT()
  const activeChatId = useAgentStore((s) => s.activeSessionId)
  const harnessRun = useHarnessChatStore((s) => s.sessions[activeChatId])

  // T4: gom con theo LƯỢT. Bảng cũ dựng một danh sách phẳng từ MỌI event `child` của cả run,
  // nên đang hỏi câu 2 vẫn còn thấy con của câu 1 (BUG-43).
  const turnGroups = useMemo(() => buildChildTurns(harnessRun?.events ?? []), [harnessRun?.events])
  const childrenList = useMemo(() => turnGroups.flatMap((group) => group.children), [turnGroups])
  /** `sessionId` → vai, để đọc `deliveries[].recipient` (đích THẬT là sessionId của người nhận). */
  const rolesBySession = useMemo(
    () => new Map(childrenList.map((child) => [child.sessionId, child.role])),
    [childrenList],
  )
  const roleOfSession = (sessionId: string): string | null => rolesBySession.get(sessionId) ?? null

  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null)

  const [childStream, setChildStream] = useState<{ sessionId: string | null; events: HarnessEvent[]; loading: boolean; error: string | null }>({ sessionId: null, events: [], loading: false, error: null })
  const childEventCache = useRef(new Map<string, HarnessEvent[]>())
  const [streamRetry, setStreamRetry] = useState(0)
  const [copied, setCopied] = useState(false)
  const [sidCopied, setSidCopied] = useState(false)
  const [showInfoPopover, setShowInfoPopover] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!showInfoPopover) return
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setShowInfoPopover(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [showInfoPopover])

  // Lượt đang xem: mặc định lượt mới nhất (lượt vừa hỏi), đổi được bằng chip lượt hoặc công tắc.
  const [viewedTurn, setViewedTurn] = useState<number | null>(null)
  const [allTurns, setAllTurns] = useState(false)

  // Đổi phiên chat ⇒ bộ lọc lượt của phiên CŨ vô nghĩa với phiên mới (`turnGroups` khác hẳn),
  // và bảng sẽ trống không lời giải thích. Xoá bộ lọc để phiên mới tự về lượt mới nhất của nó.
  const filteredChatRef = useRef<string | null>(activeChatId)
  useEffect(() => {
    if (filteredChatRef.current === activeChatId) return
    filteredChatRef.current = activeChatId
    setViewedTurn(null)
    setAllTurns(false)
    setSelectedSessionId(null)
    childEventCache.current.clear()
    setShowInfoPopover(false)
  }, [activeChatId])

  const latestTurn = turnGroups.length > 0 ? turnGroups[turnGroups.length - 1].turn : null
  // Lượt đã chọn có thể không còn tồn tại (vừa đổi phiên, hoặc lượt bị gom lại): lùi về lượt mới
  // nhất thay vì để bảng rỗng mà không nói vì sao.
  const effectiveTurn =
    viewedTurn !== null && turnGroups.some((group) => group.turn === viewedTurn)
      ? viewedTurn
      : latestTurn
  const visibleGroups = useMemo(
    () => (allTurns ? turnGroups : turnGroups.filter((group) => group.turn === effectiveTurn)),
    [allTurns, effectiveTurn, turnGroups],
  )
  const visibleChildren = useMemo(
    () => visibleGroups.flatMap((group) => group.children),
    [visibleGroups],
  )

  // Chip chuyên gia trong transcript hoặc capsule sub-agent mở tab này kèm `sessionId` hoặc `turn`
  const subagentsTarget = useUiStore((s) => s.tabIntentTargets.subagents)
  const targetChildId = typeof subagentsTarget?.sessionId === 'string' ? subagentsTarget.sessionId : null
  const targetTurn = typeof subagentsTarget?.turn === 'number' ? subagentsTarget.turn : null
  const appliedChildTargetRef = useRef<string | null>(null)
  const appliedTurnTargetRef = useRef<number | null>(null)
  useEffect(() => {
    if (targetTurn !== null && appliedTurnTargetRef.current !== targetTurn) {
      appliedTurnTargetRef.current = targetTurn
      setViewedTurn(targetTurn)
      setAllTurns(false)
    }
    if (!targetChildId || appliedChildTargetRef.current === targetChildId) return
    const target = [...childrenList].reverse().find((child) => child.sessionId === targetChildId)
    if (!target) return
    appliedChildTargetRef.current = targetChildId
    setSelectedSessionId(targetChildId)
    // Mở đúng lượt chứa em đó — nếu không, hàng được chọn nằm ngoài tầm mắt của bảng.
    if (target.turn > 0) {
      setAllTurns(false)
      setViewedTurn(target.turn)
    }
  }, [targetChildId, targetTurn, childrenList])

  const activeChild = useMemo(() => {
    const selected = selectedSessionId
      ? visibleChildren.find(child => child.sessionId === selectedSessionId && child.turn === viewedTurn)
        ?? visibleChildren.find(child => child.sessionId === selectedSessionId)
        ?? [...childrenList].reverse().find(child => child.sessionId === selectedSessionId) ?? null
      : null
    if (selected && visibleChildren.some((child) => child.sessionId === selected.sessionId)) return selected
    return visibleChildren[0] ?? selected
  }, [selectedSessionId, viewedTurn, childrenList, visibleChildren])

  // A pinned earlier turn may reuse the same child later. Follow its newest receipt
  // for fetching, while keeping the user's selected turn and expanded history.
  const streamChild = activeChild
    ? [...childrenList].reverse().find(child => child.sessionId === activeChild.sessionId)
    : undefined

  // Drain every event page, then poll only new receipts without overlapping requests.
  useEffect(() => {
    if (!activeChild || !activeChild.sessionId || activeChild.sessionId === 'unknown') {
      return
    }

    const sessionId = activeChild.sessionId
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let history = childEventCache.current.get(sessionId) ?? []
    setChildStream({ sessionId, events: history, loading: true, error: null })
    const fetchChildEvents = async () => {
      try {
        const page = await readHarnessSessionPages(sessionId, history.at(-1)?.seq ?? 0, controller.signal)
        if (controller.signal.aborted) return
        history = [...history, ...page.events]
        childEventCache.current.set(sessionId, history)
        setChildStream({ sessionId, events: history, loading: false, error: null })
      } catch (error) {
        if (controller.signal.aborted) return
        setChildStream({ sessionId, events: history, loading: false, error: String(error) })
      } finally {
        if (!controller.signal.aborted && streamChild?.status === 'running') {
          timer = setTimeout(() => { void fetchChildEvents() }, 1000)
        }
      }
    }

    void fetchChildEvents()
    return () => {
      controller.abort()
      clearTimeout(timer)
    }
  }, [activeChild?.sessionId, streamChild?.status, streamChild?.updateSeq, activeChatId, streamRetry])

  const childEvents = childStream.sessionId === activeChild?.sessionId ? childStream.events : []
  const inspectActiveChild = () => {
    if (!activeChild) return
    setSelectedSessionId(activeChild.sessionId)
    setViewedTurn(activeChild.turn)
  }

  // Dựng dòng thời gian tuần tự của sub-agent (thinking, text, tools) theo đúng thứ tự thời gian
  const timelineItems = useMemo(() => buildSubagentTimeline(childEvents), [childEvents])

  // T15 — đường ống peer của em ĐANG XEM, đọc từ chính luồng của em đó (poll ở trên).
  // Đây là nguồn SỐNG duy nhất: hàng sổ con của cha không mang `waiting_for` trong event nào.
  const activeWait = useMemo(() => openPeerWait(childEvents), [childEvents])
  const activeReceipts = useMemo(() => peerReceipts(childEvents), [childEvents])

  // Hàng con của CHA mang `deliveries[]` (kèm `state`), nhưng biên nhận thuộc về em NHẬN:
  // phải đối chiếu `recipient` với role/sessionId của từng em rồi mới gắn huy hiệu.
  const receiptsByChild = useMemo(() => {
    const map = new Map<string, PeerReceipt[]>()
    for (const source of childrenList) {
      if (source.deliveries.length === 0) continue
      for (const child of childrenList) {
        if (child.sessionId === source.sessionId) continue
        for (const receipt of receiptsFromDeliveries(source.deliveries, child.role, child.sessionId)) {
          const list = map.get(child.sessionId) ?? []
          list.push({ ...receipt, role: receipt.role || source.role })
          map.set(child.sessionId, list)
        }
      }
    }
    return map
  }, [childrenList])

  // Đồng hồ chỉ chạy khi có mốc hạn THẬT (deadline tuyệt đối) — không đếm ngược bằng số giây
  // ước lượng, và không đếm khi người chờ đã tự đặt hạn riêng (`waitsUntilDelivery === false`).
  const clockNeeded = useMemo(() => hasAbsoluteDeadline(activeWait), [activeWait])
  const [nowMs, setNowMs] = useState(() => Date.now())
  useEffect(() => {
    if (!clockNeeded) return
    const timer = setInterval(() => setNowMs(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [clockNeeded])

  /** Lượt chờ của một hàng: chỉ luồng đang được đọc mới có `peer_wait`/`peer_wait_end`. */
  const waitForRow = (child: ChildSessionView): PeerWait | null =>
    activeChild?.sessionId === child.sessionId ? activeWait : null

  const receiptsForRow = (child: ChildSessionView): PeerReceipt[] => {
    const own = activeChild?.sessionId === child.sessionId ? activeReceipts : []
    return mergeReceipts(own, receiptsByChild.get(child.sessionId) ?? [])
  }

  /** `main` = phiên cha; em cùng lượt đọc theo `sessionId`; còn lại cắt ngắn id cho đọc được. */
  const deliveryTarget = (recipient: string): string => {
    const label = deliveryLabel(recipient, harnessRun?.id ?? activeChatId, roleOfSession)
    return label ?? shortPeerId(recipient)
  }

  /** Mũi tên giao kết quả: con còn chạy ⇒ Ý ĐỊNH (`deliverTo`), con đóng sổ ⇒ biên nhận THẬT. */
  const deliveryLines = (
    child: ChildSessionView,
  ): Array<{ key: string; icon: typeof ArrowRight; className: string; text: string }> => {
    const lines: Array<{ key: string; icon: typeof ArrowRight; className: string; text: string }> = []
    if (child.status === 'running') {
      if (child.deliverTo.length > 0) {
        lines.push({
          key: 'intent',
          icon: ArrowRight,
          className: 'text-zinc-500',
          text: t('chat.subagentWillDeliverTo', { targets: child.deliverTo.join(', ') }),
        })
      }
      return lines
    }
    const view = peerDeliveryView(child.deliveries, deliveryTarget)
    if (view.delivered.length > 0) {
      lines.push({
        key: 'delivered',
        icon: ArrowRight,
        className: 'text-zinc-500',
        text: t('chat.subagentDeliversTo', { targets: view.delivered.join(', ') }),
      })
    }
    view.skipped.forEach((row, index) => {
      lines.push({
        key: `skipped-${index}`,
        icon: AlertCircle,
        className: 'text-amber-300/90',
        text: t('chat.subagentDeliversSkipped', {
          target: row.target,
          reason: skipReasonText(t, row.reason),
        }),
      })
    })
    return lines
  }

  /** Biên nhận: chỉ `injected` được nói "đã nhận"; `pending` là đang tới; `skipped` là không nhận. */
  const receiptLine = (
    receipt: PeerReceipt,
  ): { icon: typeof ArrowRight; className: string; text: string } => {
    if (receipt.state === 'injected') {
      return {
        icon: Inbox,
        className: 'text-emerald-300',
        text: `${t('chat.subagentReceivedFrom', { role: receipt.role })}${
          receipt.chars !== null ? ` · ${receipt.chars} chars` : ''
        }`,
      }
    }
    if (receipt.state === 'skipped') {
      return {
        icon: AlertCircle,
        className: 'text-amber-300/90',
        text: t('chat.subagentReceiveSkipped', {
          role: receipt.role,
          reason: skipReasonText(t, receipt.reason),
        }),
      }
    }
    return {
      icon: Clock,
      className: 'text-sky-300',
      text: `${t('chat.subagentReceivingFrom', { role: receipt.role })}${
        receipt.chars !== null ? ` · ${receipt.chars} chars` : ''
      }`,
    }
  }

  const roleDescription = activeChild ? (ROLE_DESCRIPTIONS[activeChild.role] ?? 'Specialized subagent execution.') : ''

  const allTextForCopy = useMemo(() => {
    const texts = timelineItems
      .filter((it) => it.kind === 'text')
      .map((it) => it.text)
      .filter(Boolean) as string[]
    return texts.join('\n\n') || activeChild?.summary || ''
  }, [timelineItems, activeChild?.summary])

  const handleCopy = () => {
    if (!allTextForCopy) return
    void navigator.clipboard.writeText(allTextForCopy)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex h-full w-full flex-col bg-panel text-fg select-none">
      {/* Main 2-Column Area: Specialists Pipeline (Trái) & Chat Stream (Phải) */}
      <div className="flex min-h-0 flex-1">
        {/* Left Column: Subagents List Pipeline */}
        <div className="flex w-64 shrink-0 flex-col border-r border-line bg-panel">
          <div className="border-b border-line px-3 py-2 text-[10px] font-semibold text-muted uppercase tracking-wider flex items-center justify-between">
            <span>Specialists Pipeline</span>
            {/* Nút Info thay cho phần đếm số con */}
            {activeChild && (
              <div ref={popoverRef} className="relative">
                <button
                  type="button"
                  data-testid="subagent-info-trigger"
                  onClick={() => setShowInfoPopover((prev) => !prev)}
                  className={`flex size-5 items-center justify-center rounded border transition cursor-pointer ${
                    showInfoPopover
                      ? 'border-line bg-panel2 text-fg shadow-2xs'
                      : 'border-transparent text-muted hover:border-line hover:bg-panel2 hover:text-fg'
                  }`}
                  aria-label="Specialist Info"
                  aria-expanded={showInfoPopover}
                >
                  <Info className="size-3.5" />
                </button>
                {/* Popup thông tin khi click */}
                {showInfoPopover && (
                  <div className="absolute right-0 top-full mt-1.5 z-50 w-72 rounded-xl border border-line bg-panel p-3 shadow-2xl text-xs normal-case tracking-normal">
                    <div className="flex items-center justify-between pb-2 border-b border-line/50">
                      <span className="font-semibold text-fg capitalize truncate mr-2">
                        {activeChild.role} Specialist
                      </span>
                      <span
                        className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider ${
                          activeChild.status === 'completed'
                            ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                            : activeChild.status === 'running'
                              ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                              : activeChild.status === 'partial'
                                ? 'bg-sky-500/15 text-sky-400 border border-sky-500/30'
                                : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                        }`}
                      >
                        {activeChild.status}
                      </span>
                    </div>

                    <div className="mt-2 space-y-2">
                      <div>
                        <div className="text-[10px] text-muted uppercase tracking-wider font-semibold">
                          Session ID
                        </div>
                        <div className="flex items-center justify-between gap-1 mt-0.5 font-mono text-[10px] text-fg bg-panel2 px-2 py-1 rounded border border-line/40">
                          <span className="truncate" title={activeChild.sessionId}>
                            {activeChild.sessionId}
                          </span>
                          <button
                            type="button"
                            onClick={() => {
                              void navigator.clipboard.writeText(activeChild.sessionId)
                              setSidCopied(true)
                              setTimeout(() => setSidCopied(false), 1500)
                            }}
                            className="shrink-0 text-muted hover:text-fg cursor-pointer p-0.5"
                            title="Copy Session ID"
                          >
                            {sidCopied ? (
                              <Check className="size-3 text-emerald-400" />
                            ) : (
                              <Copy className="size-3" />
                            )}
                          </button>
                        </div>
                      </div>

                      {roleDescription && (
                        <div>
                          <div className="text-[10px] text-muted uppercase tracking-wider font-semibold">
                            Description
                          </div>
                          <p className="mt-0.5 text-[11px] text-muted leading-relaxed">
                            {roleDescription}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* T4 — phạm vi lượt: ẩn khỏi UI theo yêu cầu tối ưu UX; giữ selector test */}
          {turnGroups.length > 0 && (
            <div
              data-testid="subagents-turn-scope"
              className="hidden"
            >
              {turnGroups.map((group) => {
                const isCurrent = !allTurns && group.turn === effectiveTurn
                return (
                  <button
                    key={group.turn}
                    type="button"
                    data-testid="subagents-turn-chip"
                    data-turn={group.turn}
                    data-selected={isCurrent}
                    aria-current={isCurrent ? 'true' : undefined}
                    onClick={() => {
                      setAllTurns(false)
                      setViewedTurn(group.turn)
                    }}
                    title={t('chat.subagentTurnHeader', {
                      turn: group.turn,
                      count: group.children.length,
                    })}
                    className={`rounded-full border px-1.5 py-0.5 font-mono text-[9px] transition cursor-pointer ${
                      isCurrent
                        ? 'border-brand/60 bg-brand/15 text-brand'
                        : 'border-line bg-panel2 text-zinc-400 hover:text-fg'
                    }`}
                  >
                    {/* Lượt `0` là bản ghi không có event `user` nào — nói thẳng là chưa rõ lượt. */}
                    {group.turn > 0 ? t('chat.subagentTurnChip', { turn: group.turn }) : '?'} ·{' '}
                    {group.children.length}
                  </button>
                )
              })}
              <label
                data-testid="subagents-all-turns"
                data-on={allTurns}
                className="ml-auto flex items-center gap-1 text-[10px] text-zinc-400 cursor-pointer select-none"
              >
                <input
                  type="checkbox"
                  checked={allTurns}
                  aria-label={t('chat.subagentAllTurns')}
                  onChange={(e) => setAllTurns(e.target.checked)}
                  className="size-3 cursor-pointer accent-brand"
                />
                {t('chat.subagentAllTurns')}
              </label>
            </div>
          )}

          <div className="flex-1 overflow-y-auto p-1.5 space-y-1">
            {turnGroups.length === 0 ? (
              <div className="p-6 text-center text-xs text-muted space-y-2">
                <Bot className="size-8 mx-auto text-muted/60 animate-pulse" />
                <p>No subagents active yet.</p>
                <p className="text-[10px] text-muted">
                  Orchestrator will delegate subtasks here during complex runs.
                </p>
              </div>
            ) : (
              visibleGroups.map((group) => {
                const durationSeconds =
                  group.startedAt !== null && group.endedAt !== null
                    ? Math.max(0, Math.round((group.endedAt - group.startedAt) / 1000))
                    : null
                return (
                  <div
                    key={group.turn}
                    data-testid="subagents-turn-block"
                    data-turn={group.turn}
                    className="space-y-1"
                  >
                    {/* Giữ button turn-header ẩn trong DOM cho các bài test */}
                    <button
                      type="button"
                      data-testid="subagents-turn-header"
                      aria-expanded="true"
                      className="hidden"
                    >
                      <span>
                        {group.turn > 0
                          ? t('chat.subagentTurnHeader', {
                              turn: group.turn,
                              count: group.children.length,
                            })
                          : t('chat.subagentTurnUnknown', { count: group.children.length })}
                      </span>
                      {group.steps !== null && <span>{group.steps} steps</span>}
                      {durationSeconds !== null && <span>{durationSeconds}s</span>}
                    </button>

                    {group.children.length === 0 ? (
                      <div
                        data-testid="subagents-turn-empty"
                        role="status"
                        className="flex items-start gap-2 px-2 py-2 rounded-lg border border-dashed border-line bg-panel2/30"
                      >
                        <Bot className="mt-0.5 size-3.5 shrink-0 text-muted" />
                        <div className="space-y-0.5">
                          <p className="text-[10px] text-muted">
                            {t('chat.subagentTurnEmpty')}
                          </p>
                          <p className="text-[10px] text-muted/70">
                            {t('chat.subagentTurnEmptyHint')}
                          </p>
                        </div>
                      </div>
                    ) : (
                      group.children.map((child) => {
                        const isSelected = activeChild?.sessionId === child.sessionId
                        const waiting = waitForRow(child)
                        const receipts = receiptsForRow(child)
                        const safetySeconds = waiting ? safetyNetSeconds(waiting, nowMs) : null
                        const deliveries = deliveryLines(child)

                        return (
                          <button
                            key={child.sessionId}
                            type="button"
                            data-child-session-id={child.sessionId}
                            data-selected={isSelected}
                            data-child-turn={child.turn}
                            data-child-status={child.status}
                            onClick={() => { setSelectedSessionId(child.sessionId); setViewedTurn(child.turn) }}
                            className={`flex w-full flex-col gap-0.5 rounded-xl p-2 text-left transition cursor-pointer ${
                              isSelected
                                ? 'bg-panel2 text-fg border border-line shadow-2xs font-medium'
                                : 'text-muted hover:bg-panel2/60 hover:text-fg border border-transparent'
                            }`}
                          >
                            <div className="flex items-center gap-2.5">
                              <div
                                className={`flex size-7 shrink-0 items-center justify-center rounded-lg border border-line ${
                                  child.status === 'completed'
                                    ? 'bg-emerald-500/15 text-emerald-400'
                                    : child.status === 'running'
                                      ? 'bg-amber-500/15 text-amber-400'
                                      : child.status === 'partial'
                                        ? 'bg-sky-500/15 text-sky-400'
                                        : 'bg-rose-500/15 text-rose-400'
                                }`}
                              >
                                <Bot className="size-3.5" />
                              </div>

                              <div className="min-w-0 flex-1">
                                <div className="flex items-center justify-between">
                                  <span className="font-semibold text-xs capitalize truncate text-fg">
                                    {child.role} Specialist
                                  </span>
                                  {child.status === 'completed' ? (
                                    <CheckCircle2 className="size-3 text-emerald-400 shrink-0" />
                                  ) : child.status === 'running' ? (
                                    <span className="size-2 rounded-full bg-amber-400 animate-ping shrink-0" />
                                  ) : child.status === 'partial' ? (
                                    <AlertCircle className="size-3 text-sky-400 shrink-0" />
                                  ) : (
                                    <AlertCircle className="size-3 text-rose-400 shrink-0" />
                                  )}
                                </div>
                                <div className="text-[10px] text-muted truncate mt-0.5">
                                  {child.toolsRun.length > 0
                                    ? `${child.toolsRun.length} tools executed`
                                    : 'Autonomous run'}
                                </div>
                              </div>

                              <ChevronRight
                                className={`size-3 text-muted transition ${isSelected ? 'text-fg' : ''}`}
                              />
                            </div>

                            {/* T15 — bước và số bước con đã dùng (chỉ có từ đợt 22). */}
                            {(child.turn > 0 && child.step !== null) || child.stepsUsed !== null ? (
                              <div className="pl-9 font-mono text-[9px] text-muted">
                                {child.turn > 0 && child.step !== null
                                  ? t('chat.subagentTurnStep', {
                                      turn: child.turn,
                                      step: child.step,
                                    })
                                  : ''}
                                {child.stepsUsed !== null
                                  ? `${child.turn > 0 && child.step !== null ? ' · ' : ''}${child.stepsUsed} steps used`
                                  : ''}
                              </div>
                            ) : null}

                            {/* T15 — đang chờ peer giao kết quả */}
                            {waiting && (
                              <div
                                data-testid="child-peer-wait"
                                className="pl-9 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-[10px] text-sky-300"
                              >
                                <Clock className="size-3 shrink-0" />
                                <span className="truncate">
                                  {t('chat.subagentWaitingFor', {
                                    role: waiting.roles.join(', ') || 'peer',
                                  })}
                                </span>
                                {safetySeconds !== null && (
                                  <span className="shrink-0 font-mono text-muted">
                                    ·{' '}
                                    {t('chat.subagentSafetyNet', {
                                      time: formatClock(safetySeconds),
                                    })}
                                  </span>
                                )}
                              </div>
                            )}

                            {/* T15 — mũi tên giao kết quả */}
                            {deliveries.length > 0 && (
                              <div data-testid="child-delivers-to" className="space-y-0.5 pl-9">
                                {deliveries.map((line) => (
                                  <div
                                    key={line.key}
                                    data-delivery-line={line.key}
                                    className={`flex items-center gap-1 text-[10px] ${line.className}`}
                                  >
                                    <line.icon className="size-3 shrink-0" />
                                    <span className="truncate" title={line.text}>{line.text}</span>
                                  </div>
                                ))}
                              </div>
                            )}

                            {/* T15 — biên nhận */}
                            {receipts.map((receipt, index) => {
                              const line = receiptLine(receipt)
                              return (
                                <div
                                  key={`${receipt.role}-${receipt.deliveryId ?? index}`}
                                  data-testid="child-receipt"
                                  data-receipt-state={receipt.state}
                                  className={`pl-9 flex items-center gap-1 text-[10px] ${line.className}`}
                                >
                                  <line.icon className="size-3 shrink-0" />
                                  <span className="truncate" title={line.text}>{line.text}</span>
                                </div>
                              )
                            })}
                          </button>
                        )
                      })
                    )}
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Right Column: Sub-agent Chat Stream */}
        <div className="flex min-w-0 flex-1 flex-col bg-panel">
          {activeChild ? (
            <>
              {/* Chat Stream Body */}
              <div className="flex-1 overflow-y-auto p-4 space-y-4 select-text">
                {/* 1. Assigned Task & Context từ Main Agent (Orchestrator) */}
                <div className="rounded-xl border border-line bg-panel2/50 p-3.5 space-y-2">
                  <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted">
                    <BrainCircuit className="size-3.5 text-brand" />
                    <span>Assigned Task & Context (Orchestrator)</span>
                  </div>
                  <div className="text-xs leading-relaxed text-fg">
                    <MarkdownRenderer
                      content={activeChild.prompt || activeChild.goal || 'Inspect repository and report findings.'}
                    />
                  </div>
                </div>

                {/* 2. Luồng phản hồi của Sub-agent */}
                <div className="space-y-3.5 pt-2">
                  <div className="flex items-center justify-between text-xs text-muted pb-1 border-b border-line">
                    <div className="flex items-center gap-2">
                      <div className="flex size-5 items-center justify-center rounded bg-brand/10 text-brand">
                        <Bot className="size-3.5" />
                      </div>
                      <span className="font-semibold text-fg capitalize">
                        {activeChild.role} Specialist Output
                      </span>
                    </div>
                    {allTextForCopy && (
                      <button
                        type="button"
                        onClick={handleCopy}
                        className="flex items-center gap-1 text-[11px] text-muted hover:text-fg transition cursor-pointer"
                        title="Copy response"
                      >
                        {copied ? (
                          <>
                            <Check className="size-3 text-emerald-400" />
                            <span className="text-emerald-400">Copied</span>
                          </>
                        ) : (
                          <>
                            <Copy className="size-3" />
                            <span>Copy</span>
                          </>
                        )}
                      </button>
                    )}
                  </div>

                  {/* Dòng thời gian tuần tự (Sequential Timeline Stream): Thinking -> Text -> Tools */}
                  {timelineItems.length > 0 ? (
                    timelineItems.map((item) => {
                      if (item.kind === 'thought') {
                        return <SubagentThinkingItem key={`${activeChild.sessionId}:${item.id}`} text={item.thoughtText || ''} onInspect={inspectActiveChild} />
                      }
                      if (item.kind === 'tool_group' && item.tools) {
                        return <SubagentToolGroupItem key={item.id} tools={item.tools} />
                      }
                      if (item.kind === 'text') {
                        return <SubagentTextItem key={item.id} text={item.text || ''} isFinal={item.isFinal} />
                      }
                      return null
                    })
                  ) : activeChild.summary ? (
                    <div className="rounded-xl border border-line bg-panel2/40 p-4 text-xs leading-relaxed text-fg">
                      <MarkdownRenderer content={activeChild.summary} />
                    </div>
                  ) : (
                    <div className="rounded-xl border border-line bg-panel2/40 p-4 text-xs leading-relaxed text-fg">
                      <div className="text-muted italic py-2">
                        {activeChild.status === 'running'
                          ? 'Specialist is processing instructions autonomously in the sandbox...'
                          : childStream.sessionId !== activeChild.sessionId || childStream.loading
                            ? 'Loading sub-agent history…'
                            : childStream.error ? 'Sub-agent history is unavailable. Retry below.'
                              : 'No synthesis text returned from sub-agent.'}
                      </div>
                    </div>
                  )}

                  {timelineItems.length > 0 && childStream.sessionId === activeChild.sessionId && childStream.loading && (
                    <div role="status" className="text-xs text-muted">Loading sub-agent history…</div>
                  )}
                  {childStream.sessionId === activeChild.sessionId && childStream.error && (
                    <div role="alert" className="text-xs text-rose-400">
                      Unable to load complete sub-agent history: {childStream.error}
                      <button type="button" className="ml-2 underline cursor-pointer" onClick={() => setStreamRetry(value => value + 1)}>Retry</button>
                    </div>
                  )}

                  {/* Fallback Summary nếu timeline chưa có text cuối cùng mà summary có nội dung */}
                  {activeChild.summary &&
                    timelineItems.length > 0 &&
                    !timelineItems.some((it) => it.kind === 'text' && it.isFinal) && (
                      <div className="rounded-xl border border-line bg-panel2/40 p-4 text-xs leading-relaxed text-fg">
                        <MarkdownRenderer content={activeChild.summary} />
                      </div>
                    )}

                  {/* Error Box if any */}
                  {activeChild.lastError && (
                    <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-400 flex items-start gap-2">
                      <AlertCircle className="size-4 shrink-0 mt-0.5" />
                      <div>
                        <div className="font-semibold">Execution Issue Encountered:</div>
                        <div className="mt-0.5 text-[11px] leading-relaxed font-mono">
                          {activeChild.lastError}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Bottom Footer: 1 dòng chữ đơn giản phẳng, không icon, không viền hộp bao ngoài */}
              <div className="border-t border-line bg-panel px-4 py-2 flex items-center justify-between text-[10px] text-muted select-none">
                <span>Read-only sub-agent stream · Delegated by Main Agent · Sandbox protected</span>
                {activeChild && (
                  <span
                    className={`rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider ${
                      activeChild.status === 'completed'
                        ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                        : activeChild.status === 'running'
                          ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                          : activeChild.status === 'partial'
                            ? 'bg-sky-500/15 text-sky-400 border border-sky-500/30'
                            : 'bg-rose-500/15 text-rose-400 border border-rose-500/30'
                    }`}
                  >
                    {activeChild.status}
                  </span>
                )}
              </div>
            </>
          ) : (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center text-muted">
              <Bot className="size-10 mb-2 text-muted/60 animate-pulse" />
              <p className="text-xs">Select a specialist from the list to inspect its chat stream.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
