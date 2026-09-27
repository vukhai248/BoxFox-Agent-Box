/**
 * Khung Chat phong cách Devin / BoxFox (Seamless Agent Stream).
 * - Tin nhắn người dùng: Thẻ gọn gàng bên phải kèm timestamp & avatar KV.
 * - Phản hồi Agent: Hòa vào nền, chữ text-fg sắc nét trên cả nền sáng lẫn tối.
 * - Quá trình suy luận: Thanh "Worked for Xs ›" có thể bấm mở để xem nội dung thinking.
 * - Khối lệnh: Khung code hiển thị rõ ràng kèm nút Copy và header ngôn ngữ.
 * - Khối Ảnh Chụp Màn Hình (Screen Captures Group):
 *   + Hiển thị ảnh nguyên bản, sắc nét, KHÔNG có lớp phủ mờ hay text che ảnh.
 *   + Các ảnh chụp liên tiếp được xếp liền kề sát nhau gọn gàng.
 *   + Click vào bất kỳ ảnh nào để mở trực tiếp Lightbox phóng to/thu nhỏ bằng con lăn chuột và tải về.
 */
import { useRef, useEffect, useState, useMemo, useCallback } from 'react'
import {
  ArrowDown,
  ChevronRight,
  ChevronDown,
  Copy,
  Check,
  Sparkles,
  ShieldAlert,
  ArrowRight,
  Terminal,
  Camera,
  Eye,
  Download,
  FileCode,
  FileText,
  Code2,
  FileJson,
  File,
  LoaderCircle,
  X,
} from 'lucide-react'
import type { ChatMessage, ReferencedFile } from '../../types/ui'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { readingColumnClass } from '../../lib/readingColumn'
import { useRouterChatStore, type RouterChatTurn } from '../../store/routerChatStore'
import { useProviderStore } from '../../store/providerStore'
import { useT } from '../../i18n/context'
import { LabelDot } from '../LabelDot'
import { ChatInputBar, type RouterComposerAdapter } from './ChatInputBar'
import type { OutgoingAttachment } from '../../lib/chat/attachmentUpload'
import { ContextUsageBar } from './ContextUsageBar'
import { MediaLightboxModal, type LightboxMediaProps } from '../chat/MediaLightboxModal'
import { Video, Play, BrainCircuit } from 'lucide-react'


import { MarkdownRenderer } from '../chat/MarkdownRenderer'
import { HarnessStepView } from '../chat/HarnessStepView'
import { ProviderIcon } from '../providers/ProviderIcon'
import { useHarnessStore } from '../../store/harnessStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useResearchSync } from '../../hooks/useResearchSync'
import { ResearchConversationCards } from './research/ResearchConversationCards'
import { resolveThinkingLevel } from '../../lib/harnessThinking'
import { composerModels, findRouteOption, routerChatOptions, routable, selectionKey } from '../../lib/routeOptions'

type ChatGroup =
  | { kind: 'single'; message: ChatMessage }
  | { kind: 'screenshots'; items: Extract<ChatMessage, { kind: 'screenshot' }>[] }

/**
 * Khoảng cách tối đa (px) từ đáy khung cuộn để vẫn coi là "đang ở cuối".
 * Vượt ngưỡng này nghĩa là người dùng đã kéo lên đọc → dừng bám ngay (BUG-U1).
 */
export const SCROLL_FOLLOW_THRESHOLD_PX = 40

export function distanceFromBottom(el: { scrollHeight: number; scrollTop: number; clientHeight: number }): number {
  return el.scrollHeight - el.scrollTop - el.clientHeight
}

export function isNearBottom(
  el: { scrollHeight: number; scrollTop: number; clientHeight: number },
  threshold = SCROLL_FOLLOW_THRESHOLD_PX,
): boolean {
  return distanceFromBottom(el) <= threshold
}

/**
 * Lệnh `interrupt` của transport mock chỉ có nghĩa trong kịch bản demo.
 * Phiên harness/model chạy qua HTTP API riêng, nên gửi lệnh mock vào đó sẽ
 * in `Received interrupt command …` vào đúng khung chat thật (BUG-20/U2).
 */
export function shouldEmitMockInterrupt(activeType: string): boolean {
  return activeType !== 'harness' && activeType !== 'model'
}

/** Phiên chat thật (harness hoặc single-model) — không đi qua transport mock. */
export function usesHarnessChat(activeType: string): boolean {
  return activeType === 'harness' || activeType === 'model'
}

const HARNESS_ERROR_CODES = [
  'SETUP_REQUIRED',
  'SKILL_DISABLED',
  'SESSION_BUSY',
  'UNKNOWN_COMMAND',
  'MISSING_TASK',
  'CONTEXT_LIMIT',
  'CHILD_FAILED',
]

export interface HarnessErrorInfo {
  message: string
  code: string | null
}

/**
 * Chuẩn hóa chuỗi lỗi của store (`error: String(error)`) thành thông báo đọc
 * được + mã lỗi nếu backend có trả. Hỗ trợ cả ba dạng đang tồn tại:
 * `Error: SETUP_REQUIRED: …`, JSON `{"error":{"code":…,"message":…}}`, và
 * chuỗi thuần `Unknown skill`.
 */
export function parseHarnessError(raw: string): HarnessErrorInfo {
  let text = raw.trim()
  if (text.startsWith('Error: ')) text = text.slice(7).trim()

  // Một số đường lỗi trả nguyên payload JSON dưới dạng chuỗi.
  if (text.startsWith('{')) {
    try {
      const parsed = JSON.parse(text) as { error?: unknown; code?: unknown; message?: unknown }
      const inner = parsed.error
      if (typeof inner === 'string') text = inner
      else if (inner && typeof inner === 'object') {
        const obj = inner as { code?: unknown; message?: unknown }
        const code = typeof obj.code === 'string' ? obj.code : null
        const message = typeof obj.message === 'string' ? obj.message : text
        return { message, code: code ?? extractErrorCode(message) }
      } else if (typeof parsed.message === 'string') text = parsed.message
    } catch {
      // Không phải JSON hợp lệ — giữ nguyên chuỗi gốc.
    }
  }

  return { message: text, code: extractErrorCode(text) }
}

function extractErrorCode(message: string): string | null {
  for (const code of HARNESS_ERROR_CODES) {
    if (new RegExp(`\\b${code}\\b`).test(message)) return code
  }
  const prefixed = /^([A-Z][A-Z0-9_]{3,}):\s*/.exec(message)
  return prefixed ? prefixed[1] : null
}

/** Bỏ tiền tố mã lỗi khỏi thông báo hiển thị (mã đã có dòng riêng). */
function stripErrorCode(message: string, code: string | null): string {
  if (!code) return message
  return message.replace(new RegExp(`^${code}:\\s*`), '').trim() || message
}

function groupMessages(messages: ChatMessage[]): ChatGroup[] {
  const groups: ChatGroup[] = []
  let currentScreenshots: Extract<ChatMessage, { kind: 'screenshot' }>[] = []

  for (const msg of messages) {
    if (msg.kind === 'screenshot') {
      currentScreenshots.push(msg)
    } else {
      if (currentScreenshots.length > 0) {
        groups.push({ kind: 'screenshots', items: currentScreenshots })
        currentScreenshots = []
      }
      groups.push({ kind: 'single', message: msg })
    }
  }

  if (currentScreenshots.length > 0) {
    groups.push({ kind: 'screenshots', items: currentScreenshots })
  }

  return groups
}

export function ChatPanel() {
  const t = useT()
  const messages = useAgentStore((s) => s.messages)
  const requests = useAgentStore((s) => s.requests)
  const proposal = useAgentStore((s) => s.proposal)
  // Vòng 18 (Kế hoạch E2, việc 6): bốn lối người dùng bấm trong chat phải THẤY bảng.
  // `openTab` chỉ mở tab trong im lặng; khi bảng Workspace đang ẩn thì nó chỉ xếp hàng.
  // `showTab` mới là đường "người dùng vừa bấm một thứ cần bảng": hiện bảng + ghim + mở.
  const showTab = useUiStore((s) => s.showTab)
  // Bảng Workspace ẩn ⇒ cột chat giãn hết, nội dung đọc gom vào cột 768 px (việc 7).
  const workspaceHidden = useUiStore((s) => s.workspaceHidden)
  const chatScrollRef = useRef<HTMLDivElement>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatId = useAgentStore((s) => s.activeSessionId)
  const activeType = useHarnessStore((s) => s.activeType)
  const harnessRun = useHarnessChatStore((s) => s.sessions[chatId])
  const harnessSend = useHarnessChatStore((s) => s.send)
  const harnessRefresh = useHarnessChatStore((s) => s.refresh)
  const harnessStop = useHarnessChatStore((s) => s.stop)
  const harnessClearError = useHarnessChatStore((s) => s.clearError)
  const harnessBusy =
    harnessRun?.status === 'running' ||
    harnessRun?.status === 'starting' ||
    // Phiên đang chờ người dùng quyết định vẫn là một lượt chạy đang sống: nút Stop và các lệnh
    // điều khiển vẫn phải dùng được. Từ vòng 27 (C-5) ô soạn tin KHÔNG còn bị khoá ở trạng thái
    // này — câu gõ vào được xếp hàng cho lượt đang chạy (`canSteer` bên dưới).
    harnessRun?.status === 'awaiting_decision'
  // Vòng 27 / C-5 — lượt đang chạy nhận chỉ thị giữa lượt: nhận ở `running`/`awaiting_decision`
  // và áp ở BƯỚC KẾ. Riêng `starting` (lượt chưa mở xong, chưa có bước nào để áp) vẫn khoá nút gửi.
  const harnessSteerable = harnessRun?.status === 'running' || harnessRun?.status === 'awaiting_decision'
  // P4 — chế độ Research: đẩy (cấu hình, sự kiện `research_*`) vào store. Cầu nối này là thứ THAY
  // cho vòng hỏi 5000 ms của `ResearchPanel`: nguồn sự thật là luồng sự kiện phiên, vòng 1200 ms
  // bên dưới đã hỏi luồng rồi.
  useResearchSync()
  const researchSuggest = useMemo<{ reason: string; draftGoal: string } | null>(() => {
    const latest = [...(harnessRun?.events ?? [])].reverse().find((event) => event.type === 'research_suggested')
    if (!latest) return null
    return { reason: String(latest.data.reason ?? ''), draftGoal: String(latest.data.draftGoal ?? '') }
  }, [harnessRun?.events])

  // Lỗi của lần gửi/dừng vừa rồi được giữ thêm một bản cục bộ: `refresh` được
  // gọi mỗi 1200ms ghi lại `sessions[id].error` (thành `null` khi phiên không
  // hỏng) nên thông báo lỗi vừa hiện đã bị xoá sau ~1s — người dùng vẫn không
  // thấy gì (BUG-17/F1). Bản cục bộ tồn tại tới khi bấm xoá hoặc đổi phiên.
  const [recentRunError, setRecentRunError] = useState<string | null>(null)
  const captureRunError = useCallback(() => {
    const error = useHarnessChatStore.getState().sessions[chatId]?.error ?? null
    if (error) setRecentRunError(error)
  }, [chatId])

  // ── Auto-scroll có kiểm soát (BUG-U1) ────────────────────────────────
  // `followingRef` là nguồn sự thật cho "đang bám đáy"; state chỉ dùng để vẽ
  // nút mũi tên, nên việc bám không phụ thuộc vào nhịp re-render.
  const followingRef = useRef(true)
  const [showJumpToLatest, setShowJumpToLatest] = useState(false)
  /** Số mục mới của transcript nhận được kể từ lúc người dùng rời đáy. */
  const [unseenCount, setUnseenCount] = useState(0)
  // Bỏ qua sự kiện `scroll` do chính mình phát ra: cuộn mượt bắn nhiều sự kiện
  // trung gian ở xa đáy, nếu tính là "người dùng kéo lên" thì việc bám sẽ tự tắt.
  const programmaticScrollRef = useRef(false)
  const programmaticScrollTimer = useRef<number | null>(null)
  // Phiên đang chờ transcript: chuyển phiên không được nháy "Chưa có hội thoại".
  const [hydratingSession, setHydratingSession] = useState(true)

  const scrollToLatest = useCallback((behavior: ScrollBehavior = 'smooth') => {
    programmaticScrollRef.current = true
    if (programmaticScrollTimer.current !== null) window.clearTimeout(programmaticScrollTimer.current)
    programmaticScrollTimer.current = window.setTimeout(() => {
      programmaticScrollRef.current = false
      programmaticScrollTimer.current = null
    }, 400)
    messagesEndRef.current?.scrollIntoView?.({ behavior, block: 'end' })
  }, [])

  const handleChatScroll = useCallback(() => {
    const el = chatScrollRef.current
    if (!el) return
    // Cuộn do CHÍNH MÌNH phát ra (agent mọc thêm hàng → `scrollToLatest`) không
    // phải hoạt động của người dùng: phải thoát TRƯỚC khi ghi mốc, nếu không thì
    // mỗi hàng agent sinh ra lại gia hạn cửa sổ rảnh 15s và ý định tự mở tab
    // không bao giờ tới hạn (B12). Chỉ thao tác thật mới được ghi mốc (§3).
    if (programmaticScrollRef.current) return
    // Cuộn thật trong khung chat là hoạt động thật của người dùng → ý định tự mở
    // tab của agent chỉ xếp hàng (hợp đồng §3). Không ảnh hưởng tới giao diện.
    useUiStore.getState().noteUserActivity()
    const atBottom = isNearBottom(el)
    followingRef.current = atBottom
    setShowJumpToLatest(!atBottom)
    if (atBottom) setUnseenCount((count) => (count === 0 ? count : 0))
    // Nhớ vị trí đọc của phiên này để quay lại là về đúng chỗ.
    useUiStore.getState().rememberSessionScroll(chatId, el.scrollTop)
  }, [chatId])

  const jumpToLatest = useCallback(() => {
    followingRef.current = true
    setShowJumpToLatest(false)
    setUnseenCount(0)
    scrollToLatest('smooth')
  }, [scrollToLatest])

  useEffect(() => {
    let pending = false
    setHydratingSession(true)
    const refresh = async () => {
      if (pending) return
      pending = true
      try { await harnessRefresh(chatId) } finally { pending = false; setHydratingSession(false) }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 1200)
    return () => window.clearInterval(timer)
  }, [chatId, harnessRefresh])

  // Đổi phiên: bám lại đáy và bỏ thông báo lỗi của phiên trước.
  useEffect(() => {
    followingRef.current = true
    setShowJumpToLatest(false)
    setRecentRunError(null)
  }, [chatId])

  // Lightbox Modal State
  const [lightboxMedia, setLightboxMedia] = useState<LightboxMediaProps | null>(null)

  // ── Router Chat Integration ──────────────────────────────────────────
  const { snapshot, load: loadProviders } = useProviderStore()
  const { selection, turns: routerTurns, isSending, setSelection, send: routerSend, stop: routerStop } = useRouterChatStore()

  // Load provider snapshot on mount
  useEffect(() => { void loadProviders().catch(() => {}) }, [loadProviders])

  // Derive options from snapshot
  const routerOptions = useMemo(() => snapshot ? routerChatOptions(snapshot) : [], [snapshot])
  // `findRouteOption` tra cả trong `pins`: một phiên ghim connection (route `model:<c>:<m>`) phải
  // thấy đúng hàng con, không rơi về hàng cha của nhóm provider.
  const selected = findRouteOption(routerOptions, selectionKey(selection))

  // Auto-select default route when provider loads
  useEffect(() => {
    if (!snapshot || selected) return
    const r = snapshot.defaultRoute
    const key = r.aliasId ? `alias:${r.aliasId}` : `model:${r.connectionId}:${r.modelId}`
    const next = findRouteOption(routerOptions, key)?.selection ?? routerOptions[0]?.selection ?? null
    if (selectionKey(next) !== selectionKey(selection)) setSelection(next)
  }, [snapshot, routerOptions, selected, selection, setSelection])

  // Kiểm tra trạng thái connection của model đang chọn để cảnh báo người dùng nếu ping false
  const selectedConnection = useMemo(() => {
    if (!snapshot || !selection) return null
    if (selection.kind === 'model') {
      return snapshot.connections.find(c => c.id === selection.connectionId) || null
    }
    if (selection.kind === 'provider') {
      // Tuyến provider chạy trên BẤT KỲ connection dùng được nào của nhóm, nên chỉ cảnh báo khi
      // MỌI connection dùng được đều hỏng ping — còn một đích sống là lượt vẫn chạy được. Nhãn
      // nêu tên PROVIDER (tên connection trong nhóm chỉ là "key 1/2/3", không nói gì thêm).
      // Cùng luật định tuyến với router (`validTarget`): connection dò hỏng vẫn là một đích nếu
      // model là thứ người dùng gõ tay, nên đừng cảnh báo trong khi vẫn còn đích sống.
      const usable = snapshot.connections.filter((c) => c.providerId === selection.providerId
        && c.models.some((m) => m.id === selection.modelId && routable(c, m)))
      if (usable.length === 0 || usable.some(c => c.inferenceState !== 'failed')) return null
      const first = usable[0]
      return { ...first, name: snapshot.providers?.find(p => p.id === selection.providerId)?.name ?? first.name }
    }
    if (selection.kind === 'alias') {
      const alias = snapshot.aliases.find(a => a.id === selection.aliasId)
      const firstTarget = alias?.targets?.[0]
      return firstTarget ? snapshot.connections.find(c => c.id === firstTarget.connectionId) || null : null
    }
    return null
  }, [snapshot, selection])

  const [dismissedWarning, setDismissedWarning] = useState<string | null>(null)

  const connectionWarning = useMemo(() => {
    if (!selectedConnection) return null
    const err = selectedConnection.error || ''
    // Ignore parameter/functionCall schema errors that do not mean connection or credentials are down
    if (err.includes('thought_signature') || err.includes('functionCall')) return null

    let msg: string | null = null
    if (selectedConnection.inferenceState === 'failed') {
      msg = `Provider ${selectedConnection.name} connection failed (Ping error: ${selectedConnection.error || 'Connection down'}). Please check credentials in Settings.`
    } else if (selectedConnection.error) {
      msg = `Provider ${selectedConnection.name} warning: ${selectedConnection.error}`
    }
    if (msg && dismissedWarning === msg) return null
    return msg
  }, [selectedConnection, dismissedWarning])

  const sendCommand = useAgentStore((s) => s.sendCommand)
  const agentBusy = useAgentStore((s) => s.isBusy)
  const isGlobalBusy = Boolean(harnessBusy || isSending || agentBusy)

  const handleStopAll = useCallback(() => {
    void harnessStop(chatId).then(captureRunError, captureRunError)
    routerStop()
    // Chỉ kịch bản demo mới đi qua transport mock. Phiên harness/model dừng
    // bằng `harnessStop`; gửi thêm lệnh mock sẽ in chuỗi
    // `Received interrupt command …` vào khung chat thật (BUG-20/U2).
    if (shouldEmitMockInterrupt(activeType)) sendCommand({ type: 'interrupt', level: 'tam_dung' })
  }, [harnessStop, chatId, routerStop, sendCommand, activeType, captureRunError])

  // Clear harness error when switching sessions
  useEffect(() => {
    harnessClearError(chatId)
  }, [chatId, harnessClearError])

  // Reset dismissed warning only when user switches to a different model/connection
  useEffect(() => {
    setDismissedWarning(null)
  }, [selection])

  // Build router adapter only when live models available
  const routerAdapter: RouterComposerAdapter | undefined = useMemo(() => {
    const models = composerModels(routerOptions)
    return {
      models,
      activeModelId: selectionKey(selection),
      isBusy: isGlobalBusy,
      // Chỉ khi lượt harness thật đang chạy (không phải `starting`) mới có chỉ thị giữa lượt —
      // nút Stop vẫn ở nguyên chỗ cũ, nút Gửi chỉ hiện thêm (C-5).
      canSteer: usesHarnessChat(activeType) && harnessSteerable,
      steerNotice: harnessRun?.steerNotice ?? null,
      connectionWarning,
      onModelChange: (id: string) => {
        setSelection(findRouteOption(routerOptions, id)?.selection ?? null)
        harnessClearError(chatId)
        setDismissedWarning(null)
      },
      onSend: (prompt: string, images?: string[] | null, attachments?: OutgoingAttachment[]) => {
        harnessClearError(chatId)
        if (connectionWarning) setDismissedWarning(connectionWarning)
        const thinkingLevel = useHarnessStore.getState().thinkingLevel
        const baseLabel = selected?.label || (selection?.kind === 'model' || selection?.kind === 'provider' ? selection.modelId : selection?.kind === 'alias' ? selection.aliasId : 'Gemini 3.7 Flash')
        const activeOption = findRouteOption(routerOptions, selectionKey(selection))
        const publishedLevels = activeOption?.thinkingLevels
        // Nhãn phải nói đúng mức sẽ gửi: model chỉ công bố một mức (`['high']`) cũng
        // có mức thật, và store kéo mức toàn cục về đúng nó trước khi gửi.
        const effectiveLevel = publishedLevels?.length ? resolveThinkingLevel(publishedLevels, thinkingLevel) : thinkingLevel
        const hasThinking = Boolean(
          (publishedLevels?.length ?? 0) > 0 ||
          (/deepseek|r1|qwq|o1|o3|claude-3[-.]7.*think/i.test(baseLabel) && !/\((?:Low|Medium|High)\)/i.test(baseLabel))
        )
        const modelLabel = hasThinking && effectiveLevel ? `${baseLabel} (${effectiveLevel.charAt(0).toUpperCase() + effectiveLevel.slice(1)})` : baseLabel
        if (usesHarnessChat(activeType)) {
          // Lượt CHƯA mở xong (`starting`) không nhận prompt thường: `send` từ chối tại chỗ, nên
          // trả `false` để composer giữ nguyên bản nháp thay vì xoá im lặng (BUG-17/F1).
          // Lượt ĐANG chạy (`running`/`awaiting_decision`) thì nay gửi được: harness xếp chỉ thị
          // vào hàng đợi và áp ở bước kế (vòng 27 / C-5) — không còn bị chặn tại đây.
          const status = useHarnessChatStore.getState().sessions[chatId]?.status
          if (status === 'starting') {
            return Promise.resolve(false)
          }
          // Trả về kết quả để composer biết lần gửi có thất bại không — khi
          // harness trả 400 thì nội dung người dùng vừa gõ phải còn nguyên
          // trong ô nhập, không bị xoá im lặng (BUG-17/F1).
          // Mức thinking của model đang chọn đi kèm để store kéo mức toàn cục về
          // mức model thật sự công bố trước khi gửi lượt.
          return harnessSend(
            chatId,
            prompt,
            selection,
            images?.[0],
            modelLabel,
            activeOption?.thinkingLevels,
            images,
            attachments,
          ).then(() => {
            captureRunError()
            return !useHarnessChatStore.getState().sessions[chatId]?.error
          })
        }
        // Router chat chưa có hợp đồng nhiều ảnh: giữ nguyên một ảnh như trước.
        if (selected) void routerSend(prompt, undefined, images?.[0])
        return undefined
      },
      onStop: handleStopAll,
    }
  }, [routerOptions, selected, selection, isGlobalBusy, harnessSteerable, harnessRun?.steerNotice, connectionWarning, setSelection, routerSend, activeType, harnessSend, handleStopAll, chatId, harnessClearError, captureRunError])

  // Escape to stop streaming
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape' && isGlobalBusy) handleStopAll() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [isGlobalBusy, handleStopAll])

  // End / Shift+G: nhảy xuống cuối transcript và bám lại đáy. Escape vẫn là
  // "dừng agent" — không đổi nghĩa. Bỏ qua khi con trỏ đang ở ô nhập liệu.
  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      const isEnd = e.key === 'End' || (e.shiftKey && (e.key === 'G' || e.key === 'g'))
      if (!isEnd) return
      const target = e.target as HTMLElement | null
      const tag = target?.tagName?.toLowerCase()
      if (tag === 'input' || tag === 'textarea' || target?.isContentEditable) return
      e.preventDefault()
      jumpToLatest()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [jumpToLatest])

  const pendingRequestIds = Object.values(requests)
    .filter((r) => r.status === 'dang_cho')
    .map((r) => r.request_id)

  const messageGroups = useMemo(() => groupMessages(messages), [messages])

  const prevEventsLengthRef = useRef(0)
  const prevTurnsLengthRef = useRef(0)
  const prevTotalRef = useRef(0)

  useEffect(() => {
    const currentEvents = harnessRun?.events.length ?? 0
    const currentTurns = routerTurns.length
    const total = currentEvents + currentTurns + messages.length
    const delta = Math.max(0, total - prevTotalRef.current)
    const isNewTurn = (currentEvents > 0 && prevEventsLengthRef.current === 0) || currentTurns > prevTurnsLengthRef.current

    prevEventsLengthRef.current = currentEvents
    prevTurnsLengthRef.current = currentTurns
    prevTotalRef.current = total

    // Gửi tin mới → bám lại đáy rồi đi theo nội dung agent sinh ra.
    if (isNewTurn) {
      followingRef.current = true
      setShowJumpToLatest(false)
    }
    // Người dùng đã kéo lên đọc → không giật khung nhìn về đáy nữa, nhưng đếm
    // số mục mới để nút "xuống cuối" nói đúng đang có bao nhiêu thứ chờ.
    if (!followingRef.current) {
      if (delta > 0) setUnseenCount((count) => count + delta)
      return
    }
    setUnseenCount((count) => (count === 0 ? count : 0))

    scrollToLatest(isNewTurn ? 'smooth' : 'auto')
  }, [messages.length, routerTurns.length, harnessRun?.events.length, harnessRun?.status, scrollToLatest])

  // Đổi phiên: khôi phục đúng vị trí đọc đã nhớ của phiên đó (nếu có), ngược
  // lại thì bám đáy. Chạy sau khi transcript của phiên mới đã dựng.
  const restoredSessionRef = useRef<string | null>(null)
  useEffect(() => {
    if (restoredSessionRef.current === chatId) return
    // Chờ transcript của phiên có nội dung rồi mới đặt lại vị trí — đặt trước
    // khi có nội dung thì trình duyệt kẹp về 0 và lần cuộn tự động sau đó thắng.
    const hasContent =
      (harnessRun?.events.length ?? 0) > 0 || messages.length > 0 || routerTurns.length > 0
    if (!hasContent) return
    restoredSessionRef.current = chatId
    const saved = useUiStore.getState().sessionScrollOffsets[chatId]
    const el = chatScrollRef.current
    if (saved === undefined || saved <= 0 || !el) {
      followingRef.current = true
      setShowJumpToLatest(false)
      scrollToLatest('auto')
      return
    }
    el.scrollTop = saved
    const atBottom = isNearBottom(el)
    followingRef.current = atBottom
    setShowJumpToLatest(!atBottom)
  }, [chatId, scrollToLatest, harnessRun?.events.length, messages.length, routerTurns.length])

  useEffect(() => () => {
    if (programmaticScrollTimer.current !== null) window.clearTimeout(programmaticScrollTimer.current)
  }, [])

  // Lỗi harness hiện inline ngay trên ô nhập (BUG-17/F1) — không im lặng.
  // Ưu tiên lỗi mới nhất trong store, rơi về bản cục bộ khi vòng poll vừa xoá nó.
  const harnessError = harnessRun?.error ?? recentRunError
  const harnessErrorInfo = useMemo(() => (harnessError ? parseHarnessError(harnessError) : null), [harnessError])
  const dismissHarnessError = useCallback(() => {
    setRecentRunError(null)
    harnessClearError(chatId)
  }, [chatId, harnessClearError])
  const showEmptyState = messages.length === 0 && !harnessRun?.events.length && routerTurns.length === 0

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg">
      {/* Top Context Usage Bar */}
      <ContextUsageBar />

      {/* Scrollable conversation stream (+ nút nhảy xuống cuối ở đáy khung) */}
      <div className="relative flex min-h-0 flex-1 flex-col">
      <div
        ref={chatScrollRef}
        onScroll={handleChatScroll}
        data-testid="chat-scroll"
        className="min-h-0 flex-1 overflow-y-auto p-5 space-y-6 select-text"
      >
        {/* Cột đọc: bảng ẩn thì nội dung gom 768 px ở giữa; `h-full` giữ nguyên chỗ
            neo của trạng thái rỗng/đang nạp (khối đó tự căn giữa theo `h-full`). */}
        <div
          data-testid="chat-reading-column"
          className={`h-full space-y-6 ${readingColumnClass(workspaceHidden)}`}
        >
        {showEmptyState && hydratingSession ? (
          <div
            data-testid="chat-session-loading"
            className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center text-xs text-muted"
          >
            <LoaderCircle className="size-4 animate-spin" />
            <span>{t('chat.loadingSession')}</span>
          </div>
        ) : showEmptyState ? (
          <div className="flex h-full flex-col items-center justify-center p-8 text-center">
            <div className="max-w-sm space-y-2">
              <div className="mx-auto flex size-10 items-center justify-center rounded-xl bg-panel2 border border-line text-muted">
                <Sparkles className="size-5 text-brand" />
              </div>
              <h3 className="text-sm font-semibold text-fg">{t('chat.empty.title')}</h3>
              <p className="text-xs leading-relaxed text-muted">{t('chat.empty.body')}</p>
            </div>
          </div>
        ) : (
          messageGroups.map((group, groupIdx) => {
            if (group.kind === 'screenshots') {
              return (
                <ScreenshotsGroupCard
                  key={`ss-group-${groupIdx}`}
                  items={group.items}
                  onOpenLightbox={(img) => setLightboxMedia(img)}
                />
              )
            }

            return (
              <MessageRow
                key={group.message.id}
                message={group.message}
                hasPendingPermission={pendingRequestIds.includes(
                  group.message.kind === 'permission_request' ? group.message.request_id : '',
                )}
                hasModeSwitch={proposal !== null && group.message.kind === 'mode_switch'}
                onOpenPermission={() => showTab('decisions')}
                onOpenModeSwitch={() => showTab('plan')}
                onOpenLightbox={setLightboxMedia}
              />
            )
          })
        )}
        {/* Router Turns — hiển thị kết quả chat qua Provider */}
        {routerTurns.length > 0 && routerTurns.map(turn => (
          <RouterTurnBubble key={turn.id} turn={turn} snapshot={snapshot} onOpenLightbox={setLightboxMedia} />
        ))}

        {/* Harness Events — hiển thị tiến trình thinking & tool execution chuyên nghiệp */}
        {harnessRun && (harnessRun.events.length > 0 || harnessBusy) && (
          <HarnessStepView
            events={harnessRun.events}
            status={harnessRun.status}
            error={harnessRun.error}
            // T15 — `deliveries[].recipient` là `sessionId`; `main` chính là phiên đang chạy.
            sessionId={harnessRun.id}
            connectionWarning={connectionWarning}
            onDismissWarning={() => setDismissedWarning(connectionWarning)}
            onOpenLightbox={setLightboxMedia}
            snapshot={snapshot}
            selection={selection}
            // Chip kế hoạch / sub-agent / quyết định trong transcript đều mở tab
            // tại chỗ — người dùng đọc chat không bị mất vị trí (giữ nguyên khung cuộn).
            onOpenTab={(tab, target) => showTab(tab, target ?? null)}
            // P4.1/P4.3 — nhật ký bền của phiên (`GET /sessions/{sid}` trả về, store gộp theo `seq`):
            // hàng `E:` trong đó là bằng chứng cổng đã ghim cho từng lượt.
            journal={harnessRun.journal ?? null}
          />
        )}
        {/* Sub-agent Status Capsule — Theo dõi tiến độ sub-agent và mở SubagentInspectorPanel */}
        {harnessRun?.events.some(e => e.type === 'child') && (
          <div
            onClick={() => showTab('subagents')}
            className="flex items-center justify-between gap-3 rounded-xl border border-brand/40 bg-brand/10 p-3 text-xs text-fg cursor-pointer hover:bg-brand/15 transition shadow-xs group"
          >
            <div className="flex items-center gap-2">
              <BrainCircuit className="size-4 text-brand animate-pulse" />
              <span className="font-semibold text-brand">Autonomous Specialists Active</span>
              <span className="text-zinc-400">·</span>
              <span className="text-zinc-300">
                {Array.from(new Set(harnessRun.events.filter(e => e.type === 'child').map(e => String(e.data.role)))).join(' → ')}
              </span>
            </div>
            <div className="flex items-center gap-1 text-[11px] text-brand font-medium group-hover:underline">
              <span>View Console</span>
              <ChevronRight className="size-3" />
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
        {/* P4 — thẻ Research trong hội thoại: lời hỏi nhiều câu, thẻ ngoài phạm vi, thẻ báo cáo
            (kể cả run chạy nền xong sau khi đã tắt chế độ) và thẻ gợi ý của main. */}
        <ResearchConversationCards suggest={researchSuggest} />
        </div>

      </div>

        {/* Nút nhảy xuống cuối — chỉ hiện khi người dùng đã kéo lên (BUG-U1) */}
        {showJumpToLatest && (
          <button
            type="button"
            onClick={jumpToLatest}
            data-testid="chat-jump-to-latest"
            data-unseen-count={unseenCount}
            aria-label={
              unseenCount > 0
                ? `${t('chat.scrollToBottom')} — ${t('chat.newMessages', { count: unseenCount })}`
                : t('chat.scrollToBottom')
            }
            title={
              unseenCount > 0 ? t('chat.newMessages', { count: unseenCount }) : t('chat.scrollToBottom')
            }
            className={`absolute bottom-4 left-1/2 z-20 flex -translate-x-1/2 items-center gap-1.5 rounded-full border border-line bg-panel text-fg shadow-lg transition hover:bg-panel2 hover:text-brand cursor-pointer ${
              unseenCount > 0 ? 'h-8 pl-2 pr-3' : 'size-8 justify-center'
            }`}
          >
            <ArrowDown className="size-4" />
            {unseenCount > 0 && (
              <span className="font-mono text-[11px] font-bold tabular-nums">{unseenCount}</span>
            )}
          </button>
        )}
      </div>

      {/* Lỗi harness hiện inline ngay trên ô nhập; nội dung người dùng vừa gõ
          được composer giữ lại nguyên vẹn (BUG-17/F1). */}
      {harnessErrorInfo && (
        <div
          role="alert"
          data-testid="chat-error"
          className="border-t border-rose-500/40 bg-rose-500/10 px-4 py-2.5 text-xs text-rose-200"
        >
          <div className="flex items-start gap-2">
            <ShieldAlert className="mt-0.5 size-3.5 shrink-0 text-rose-400" />
            <div className="min-w-0 flex-1 space-y-0.5">
              <p className="font-semibold text-rose-300">{t('chat.errorTitle')}</p>
              <p className="break-words leading-relaxed">{stripErrorCode(harnessErrorInfo.message, harnessErrorInfo.code)}</p>
              {harnessErrorInfo.code && (
                <p className="font-mono text-[10px] text-rose-300/80">
                  {t('chat.errorCodeLabel')}: {harnessErrorInfo.code}
                </p>
              )}
            </div>
            <button
              type="button"
              onClick={dismissHarnessError}
              aria-label={t('chat.errorDismiss')}
              title={t('chat.errorDismiss')}
              className="rounded p-0.5 text-rose-300/80 transition hover:text-rose-100 cursor-pointer"
            >
              <X className="size-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Fixed bottom chat input bar */}
      <ChatInputBar router={routerAdapter} />

      {/* Fullscreen Interactive Lightbox Modal */}
      {lightboxMedia && (
        <MediaLightboxModal
          type={lightboxMedia.type}
          src={lightboxMedia.src}
          poster={lightboxMedia.poster}
          caption={lightboxMedia.caption}
          sourceUrl={lightboxMedia.sourceUrl}
          duration={lightboxMedia.duration}
          onClose={() => setLightboxMedia(null)}
        />
      )}
    </div>
  )
}

/** Group of consecutive screenshots placed seamlessly right next to each other */
function ScreenshotsGroupCard({
  items,
  onOpenLightbox,
}: {
  items: Extract<ChatMessage, { kind: 'screenshot' }>[]
  onOpenLightbox?: (props: LightboxMediaProps) => void
}) {
  const first = items[0]

  return (
    <div className="space-y-2 max-w-xl pl-0.5">
      {/* Header bar: Single clean header for the group */}
      <div className="flex items-center justify-between text-xs text-muted select-none">
        <div className="flex items-center gap-1.5 font-medium">
          <Camera className="size-3.5 text-brand" />
          <span className="text-fg font-semibold">
            Screen Capture{items.length > 1 ? ` (${items.length})` : ''}
          </span>
          {first.source_url && (
            <span className="font-mono text-[10px] text-muted truncate max-w-[240px]">
              ({first.source_url})
            </span>
          )}
        </div>
        {first.label_id && first.integrity && first.confidentiality && (
          <div className="flex items-center gap-1.5">
            <LabelDot integrity={first.integrity} confidentiality={first.confidentiality} />
            <span className="font-mono text-[10px] text-muted">{first.label_id}</span>
          </div>
        )}
      </div>

      {/* Images stacked seamlessly right next to each other */}
      <div className="space-y-2">
        {items.map((ss) => (
          <div
            key={ss.id}
            onClick={() =>
              onOpenLightbox?.({
                type: 'image',
                src: ss.image_url,
                caption: ss.caption,
                sourceUrl: ss.source_url,
              })
            }
            className="cursor-pointer overflow-hidden rounded-xl border border-line bg-panel2 transition hover:border-brand/50 hover:shadow-md select-none"
            title="Click to zoom / download"
          >
            <img
              src={ss.image_url}
              alt={ss.caption || 'Screenshot'}
              className="w-full object-cover max-h-72 select-none"
            />
          </div>
        ))}
      </div>
    </div>
  )
}


/** Screen Recording Card with Play Overlay and Duration Badge */
function ScreenRecordingCard({
  message,
  onOpenLightbox,
}: {
  message: Extract<ChatMessage, { kind: 'screen_recording' }>
  onOpenLightbox: (props: LightboxMediaProps) => void
}) {
  return (
    <div className="space-y-2.5 max-w-xl pl-0.5 animate-in fade-in duration-150">
      <div className="flex items-center justify-between gap-2 text-xs text-muted select-none">
        <div className="flex items-center gap-1.5 font-semibold text-fg">
          <Video className="size-3.5 text-brand" />
          <span>Screen Recording Session</span>
        </div>
        {message.label_id && message.integrity && message.confidentiality && (
          <div className="flex items-center gap-1.5">
            <LabelDot integrity={message.integrity} confidentiality={message.confidentiality} />
            <span className="font-mono text-[10px] text-muted">{message.label_id}</span>
          </div>
        )}
      </div>

      <div
        onClick={() =>
          onOpenLightbox?.({
            type: 'video',
            src: message.video_url,
            poster: message.poster_url,
            caption: message.caption,
            sourceUrl: message.source_url,
            duration: message.duration_seconds,
          })
        }
        className="group relative cursor-pointer overflow-hidden rounded-xl border border-line bg-panel2 transition hover:border-brand/50 hover:shadow-lg select-none"
        title="Click to play and inspect recording"
      >
        <video
          src={message.video_url}
          poster={message.poster_url}
          muted
          playsInline
          loop
          autoPlay
          className="w-full object-cover max-h-72 rounded-xl"
        />

        {/* Play Overlay */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/40 transition">
          <div className="flex size-12 items-center justify-center rounded-full bg-black/60 text-white border border-white/20 group-hover:scale-110 transition shadow-lg backdrop-blur-xs">
            <Play className="size-5 ml-0.5 fill-white" />
          </div>
        </div>

        {/* Bottom Badges */}
        <div className="absolute bottom-2.5 left-2.5 right-2.5 flex items-center justify-between text-[11px] text-white font-medium drop-shadow-md pointer-events-none">
          <span className="rounded-md bg-black/60 px-2 py-0.5 backdrop-blur-xs border border-white/10">
            {message.caption || 'Browser Session'}
          </span>
          {message.duration_seconds && (
            <span className="rounded-md bg-black/60 px-2 py-0.5 font-mono backdrop-blur-xs border border-white/10">
              0:{message.duration_seconds.toString().padStart(2, '0')} • 60 FPS
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function MessageRow({
  message,
  hasPendingPermission,
  hasModeSwitch,
  onOpenPermission,
  onOpenModeSwitch,
  onOpenLightbox,
}: {
  message: ChatMessage
  hasPendingPermission: boolean
  hasModeSwitch: boolean
  onOpenPermission: () => void
  onOpenModeSwitch: () => void
  onOpenLightbox: (props: LightboxMediaProps) => void
}) {
  switch (message.kind) {
    case 'user_text':
      return <UserBubble text={message.text} />
    case 'agent_text':
      return <SeamlessAgentMessage message={message} />
    case 'agent_step':
      return <StepBlock message={message} />
    case 'screenshot':
      return null // handled in ScreenshotsGroupCard
    case 'screen_recording':
      return <ScreenRecordingCard message={message} onOpenLightbox={onOpenLightbox} />
    case 'system_note':
      return (
        <div className="my-2 py-1 text-center text-xs italic text-muted max-w-lg mx-auto">
          {message.text}
        </div>
      )
    case 'permission_request':
      return (
        <PermissionChatRow
          requestId={message.request_id}
          pending={hasPendingPermission}
          onClick={onOpenPermission}
        />
      )
    case 'mode_switch':
      return <ModeSwitchChatRow pending={hasModeSwitch} onClick={onOpenModeSwitch} />
  }
}

/** User message card with timestamp and KV badge */
function UserBubble({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="max-w-[85%] rounded-2xl bg-panel2 border border-line px-4 py-3 text-xs leading-relaxed text-fg shadow-xs">
        <MarkdownRenderer content={text} />
      </div>
      <div className="flex items-center gap-2 text-[10px] text-muted pr-1 select-none">
        <span>Just now</span>
        <button
          type="button"
          onClick={handleCopy}
          className="hover:text-fg transition cursor-pointer"
          title="Copy message"
        >
          {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
        </button>
        <span className="flex size-4 items-center justify-center rounded-full bg-panel border border-line text-[8px] font-bold text-muted">
          KV
        </span>
      </div>
    </div>
  )
}

/** Seamless Agent message: flat text, rich markdown, code blocks, referenced files */
function SeamlessAgentMessage({
  message,
}: {
  message: Extract<ChatMessage, { kind: 'agent_text' }>
}) {
  return (
    <div className="space-y-3 pl-0.5">
      {/* Agent Response Text with Markdown & KaTeX LaTeX Render */}
      <MarkdownRenderer content={message.text} />

      {/* Referenced / Related Files with View (Eye) and Download Buttons */}
      {message.files && message.files.length > 0 && (
        <ReferencedFilesList files={message.files} />
      )}

      {/* Provenance Label */}
      <div className="flex items-center gap-1.5 pt-1 select-none">
        <LabelDot integrity={message.integrity} confidentiality={message.confidentiality} />
        <span className="text-[10px] font-mono text-muted">{message.label_id}</span>
      </div>
    </div>
  )
}

function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  if (['py', 'pyw'].includes(ext)) {
    return <FileCode className="size-4 text-blue-400 shrink-0" />
  }
  if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) {
    return <Code2 className="size-4 text-cyan-400 shrink-0" />
  }
  if (['md', 'markdown', 'txt', 'rst'].includes(ext)) {
    return <FileText className="size-4 text-emerald-400 shrink-0" />
  }
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) {
    return <FileJson className="size-4 text-orange-400 shrink-0" />
  }
  return <File className="size-4 text-muted shrink-0" />
}

function formatBytes(bytes?: number) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

/**
 * Khối hiển thị danh sách file tham chiếu / liên quan (Referenced Files).
 * - Hiển thị icon định dạng màu theo extension (.py, .ts, .md, .json...).
 * - Nút [👁 View]: Gọi `selectFile(path)` — nó mở tab Files và HIỆN bảng Workspace
 *   nếu bảng đang ẩn (`showTab`), để cú bấm không im lặng.
 * - Nút [⬇ Download]: Xuất file trực tiếp về máy tính người dùng.
 */
function ReferencedFilesList({ files }: { files: ReferencedFile[] }) {
  const selectFile = useUiStore((s) => s.selectFile)
  const allWorkspaceFiles = useAgentStore((s) => s.files)

  // Chỉ gọi selectFile — nó đã tự mở tab Files (panel Workspace Files). Không
  // mở song song tab IDE nữa, tránh hai tab bật lên cùng lúc.
  const handleOpenFile = (path: string) => {
    selectFile(path)
  }

  const handleDownloadFile = (file: ReferencedFile) => {
    let content = file.content
    if (!content) {
      const findContent = (nodes: typeof allWorkspaceFiles): string | undefined => {
        for (const node of nodes) {
          if (node.path === file.path && node.content) return node.content
          if (node.children) {
            const found = findContent(node.children)
            if (found) return found
          }
        }
        return undefined
      }
      content = findContent(allWorkspaceFiles) || `# ${file.name}\n`
    }

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-2 pt-1 max-w-xl">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-fg select-none">
        <FileText className="size-3.5 text-brand" />
        <span>Referenced Files ({files.length})</span>
      </div>

      <div className="space-y-1.5">
        {files.map((file) => (
          <div
            key={file.path}
            className="flex items-center justify-between gap-3 rounded-xl border border-line bg-panel2/80 px-3.5 py-2.5 transition hover:bg-panel2 hover:border-brand/40 shadow-2xs group select-none"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              {getFileIcon(file.name)}
              <div className="min-w-0">
                <div className="text-xs font-medium font-mono text-fg truncate">
                  {file.name}
                </div>
                <div className="text-[10px] font-mono text-muted truncate">
                  {file.path} {file.size_bytes ? `• ${formatBytes(file.size_bytes)}` : ''}
                </div>
              </div>
            </div>

            {/* Action Buttons: View (Eye) + Download */}
            <div className="flex items-center gap-1.5 shrink-0">
              {/* Open file in right workspace panel */}
              <button
                type="button"
                onClick={() => handleOpenFile(file.path)}
                className="flex items-center gap-1 rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-medium text-fg hover:text-brand hover:border-brand/40 transition cursor-pointer shadow-2xs"
                title="Open file in right workspace window"
              >
                <Eye className="size-3.5 text-brand" />
                <span className="text-[11px]">View</span>
              </button>

              {/* Download file button */}
              <button
                type="button"
                onClick={() => handleDownloadFile(file)}
                className="flex size-7 items-center justify-center rounded-lg border border-line bg-panel text-muted hover:text-fg hover:border-brand/40 transition cursor-pointer shadow-2xs"
                title="Download file to computer"
              >
                <Download className="size-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Step block with collapsible Thinking accordion and tool output */
function StepBlock({
  message,
}: {
  message: Extract<ChatMessage, { kind: 'agent_step' }>
}) {
  const [thinkingOpen, setThinkingOpen] = useState(false)

  return (
    <div className="space-y-2 pl-0.5 animate-in fade-in duration-150">
      {/* Thinking Accordion Bar: Worked for Xs > */}
      {message.thought && (
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={() => setThinkingOpen(!thinkingOpen)}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-fg font-medium transition cursor-pointer select-none group"
          >
            <span className="flex size-1.5 rounded-full bg-brand/80 group-hover:scale-125 transition duration-200" />
            <span>Worked for 4s</span>
            {thinkingOpen ? (
              <ChevronDown className="size-3.5 text-muted group-hover:text-fg transition" />
            ) : (
              <ChevronRight className="size-3.5 text-muted group-hover:text-fg transition" />
            )}
          </button>

          {/* Thinking Content */}
          {thinkingOpen && (
            <div className="border-l-2 border-brand/50 pl-3.5 py-1.5 text-xs italic text-muted leading-relaxed animate-in fade-in duration-150 bg-panel2/30 rounded-r-xl">
              {message.thought}
            </div>
          )}
        </div>
      )}

      {/* Tool Call and Code Output Block */}
      {message.tool_name && (
        <div className="space-y-2">
          {/* Tool banner */}
          <div className="flex items-center gap-2 text-xs font-mono text-muted">
            <Terminal className="size-3.5 text-brand" />
            <span className="font-semibold text-fg">{message.tool_name}</span>
            {message.params && (
              <span className="text-muted/80 truncate">
                {Object.entries(message.params)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(' ')}
              </span>
            )}
          </div>

          {/* Tool Result Preview */}
          {message.result_preview && (
            <div className="rounded-xl border border-line bg-panel2/60 p-3 font-mono text-xs text-fg shadow-2xs">
              <pre className="overflow-x-auto whitespace-pre-wrap">{message.result_preview}</pre>
            </div>
          )}
        </div>
      )}

      {/* Provenance Label */}
      {message.label_id && message.integrity && message.confidentiality && (
        <div className="flex items-center gap-1.5 pt-0.5 select-none">
          <LabelDot integrity={message.integrity} confidentiality={message.confidentiality} />
          <span className="text-[10px] font-mono text-muted">{message.label_id}</span>
        </div>
      )}
    </div>
  )
}


function PermissionChatRow({
  requestId,
  pending,
  onClick,
}: {
  requestId: string
  pending: boolean
  onClick: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-fg">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <ShieldAlert className={`size-4 shrink-0 ${pending ? 'text-amber-500 animate-pulse' : 'text-muted'}`} />
        <span className="truncate">
          {pending
            ? `Permission request #${requestId} — awaiting your decision`
            : `Permission request #${requestId} decided`}
        </span>
      </div>
      <button
        type="button"
        onClick={onClick}
        className="flex items-center gap-1 shrink-0 rounded-md border border-line bg-panel px-2.5 py-1 text-[11px] font-semibold text-brand hover:opacity-80 transition cursor-pointer"
      >
        <span>Open Decisions Tab</span>
        <ArrowRight className="size-3" />
      </button>
    </div>
  )
}

/** Inline router chat turn — hiển thị trong conversation stream */
function RouterTurnBubble({ turn, snapshot, onOpenLightbox }: {
  turn: RouterChatTurn
  snapshot: import('../../types/provider').ProviderSnapshot | null
  onOpenLightbox?: (props: LightboxMediaProps) => void
}) {
  const [copied, setCopied] = useState(false)
  const t = useT()
  const connId = turn.meta?.connectionId ?? (turn.selection.kind === 'model' ? turn.selection.connectionId : null)
  const conn = snapshot?.connections.find(c => c.id === connId)

  return (
    <div className="space-y-4">
      {/* User prompt — right aligned */}
      <div className="flex flex-col items-end gap-1.5">
        <div className="max-w-[85%] rounded-2xl bg-panel2 border border-line px-4 py-3 text-xs leading-relaxed text-fg shadow-xs">
          {turn.imageUrl && (
            <div
              onClick={() => onOpenLightbox?.({ type: 'image', src: turn.imageUrl!, caption: t('chat.attachedImage') })}
              className="mb-2.5 max-w-sm cursor-pointer overflow-hidden rounded-xl border border-line/80 bg-panel hover:border-brand/60 transition shadow-xs group"
              title={t('chat.openImage')}
            >
              <img
                src={turn.imageUrl}
                alt={t('chat.attachedImageAlt')}
                className="w-full object-cover max-h-56 rounded-lg group-hover:scale-[1.02] transition duration-200"
              />
            </div>
          )}
          <MarkdownRenderer content={turn.prompt} />
        </div>
        <div className="flex items-center gap-2 text-[10px] text-muted pr-1 select-none">
          <time dateTime={turn.startedAt}>
            {new Date(turn.startedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </time>
          <button
            type="button"
            title="Copy"
            onClick={() => { void navigator.clipboard.writeText(turn.prompt).then(() => setCopied(true)) }}
            className="hover:text-fg transition cursor-pointer"
          >
            {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
          </button>
          <span className="flex size-4 items-center justify-center rounded-full bg-panel border border-line text-[8px] font-bold text-muted">
            KV
          </span>
        </div>
      </div>

      {/* AI response — left aligned */}
      <div className="space-y-2 pl-0.5">
        <div className="flex items-center gap-1.5 text-[11px] text-muted select-none">
          {conn ? (
            <ProviderIcon providerId={conn.providerId} name={conn.name} className="size-3.5" />
          ) : (
            <Sparkles className="size-3.5 text-brand" />
          )}
          <span className="font-medium text-fg">{conn?.name ?? 'BoxFox'}</span>
          {turn.status === 'streaming' && (
            <span className="size-3 rounded-full border-2 border-brand border-t-transparent animate-spin" />
          )}
          {turn.meta?.modelId && (
            <span className="text-muted">{turn.meta.modelId}</span>
          )}
        </div>

        {turn.response ? (
          <div className="text-xs leading-relaxed text-fg">
            <MarkdownRenderer content={turn.response} />
          </div>
        ) : turn.status === 'streaming' ? (
          <p className="text-xs text-muted">{t('chat.routerWaiting')}</p>
        ) : null}

        {turn.error && (
          <p role="alert" className="text-xs leading-relaxed text-rose-500">{turn.error}</p>
        )}
        {turn.status === 'cancelled' && (
          <p className="text-xs text-muted">{t('chat.routerStopped')}</p>
        )}

        {/* Compact meta */}
        <div className="flex items-center gap-3 text-[10px] text-muted select-none">
          <span>
            {turn.status === 'streaming'
              ? t('chat.routerStatus.running')
              : turn.status === 'failed'
                ? t('chat.routerStatus.failed')
                : turn.status === 'cancelled'
                  ? t('chat.routerStatus.cancelled')
                  : t('chat.routerStatus.done')}
            {turn.latencyMs != null && ` · ${(turn.latencyMs / 1000).toFixed(2)}s`}
          </span>
          {turn.usage && (
            <span>
              {turn.usage.prompt_tokens ?? '?'} in · {turn.usage.completion_tokens ?? '?'} out
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function ModeSwitchChatRow({ pending, onClick }: { pending: boolean; onClick: () => void }) {
  const t = useT()
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-xl border p-3 text-left transition cursor-pointer ${pending
          ? 'border-brand/40 bg-panel shadow-xs'
          : 'border-line bg-panel2/60 hover:bg-panel2'
        }`}
    >
      <span className={`size-2 rounded-full ${pending ? 'bg-brand animate-pulse' : 'bg-muted'}`} />
      <span className="flex-1 text-xs font-medium text-fg">
        {t('chat.modeSwitchPending')}
      </span>
      <span className="flex items-center gap-1 rounded bg-brand px-2.5 py-1 text-[11px] font-semibold text-brandfg shadow-xs hover:opacity-90 transition">
        <span>{t('chat.view')}</span>
        <ArrowRight className="size-3" />
      </span>
    </button>
  )
}
