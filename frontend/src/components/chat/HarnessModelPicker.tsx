/**
 * Bộ chọn nhanh Harness & Model (Quick Picker Popover) tại Chat Input Bar.
 * - Tab chuyển đổi ở đầu: [ 🧩 Harnesses | 🤖 Single Models ]
 * - Ô tìm kiếm nhanh (Search harnesses or models...)
 * - Danh sách item với dấu tích checkmark xanh cho cấu hình đang chọn
 * - Hỗ trợ chọn mức độ Thinking (Low / Medium / High) cho các model hỗ trợ reasoning
 * - Footer: [⚙️ Manage Harnesses] và [+ Create Harness]
 */
import { useState, useRef, useEffect, useLayoutEffect, useMemo, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { resolveThinkingLevel, thinkingLevelIsPublished } from '../../lib/harnessThinking'
import {
  Bot,
  Cpu,
  Search,
  Check,
  Settings,
  Plus,
  ChevronDown,
  ChevronRight,
  X,
  Brain,
  Pin,
  KeyRound,
  Loader2,
} from 'lucide-react'
import { useHarnessStore, AVAILABLE_MODELS } from '../../store/harnessStore'
import { useUiStore } from '../../store/uiStore'
import { useProviderStore } from '../../store/providerStore'
import { ProviderIcon } from '../providers/ProviderIcon'
import { api } from '../../lib/providerApi'
import { composerModels, routable, routerChatOptions, type RouterComposerModel } from '../../lib/routeOptions'
import type { ProviderSnapshot } from '../../types/provider'

/**
 * Model cho picker/composer. `id`/`name`/`provider` là tên trường đang dùng ở hai đầu; `pins` là
 * các connection riêng lẻ của cùng một model (nhóm ≥ 2 connection) — xem `lib/routeOptions.ts`.
 */
export type RouterSingleModel = RouterComposerModel

/** Danh sách mức rỗng nghĩa là "không gửi mức nào" ⇒ bỏ trường, thay vì gửi mảng rỗng. */
function withPublishedLevels(model: RouterSingleModel): RouterSingleModel {
  return {
    ...model,
    thinkingLevels: model.thinkingLevels && model.thinkingLevels.length > 0 ? model.thinkingLevels : undefined,
    pins: model.pins?.map((pin) => ({
      ...pin,
      thinkingLevels: pin.thinkingLevels && pin.thinkingLevels.length > 0 ? pin.thinkingLevels : undefined,
    })),
  }
}

/** Trạng thái THẬT của connection sau một hàng ghim — id ghim là `model:<connectionId>:<modelId>`. */
function pinState(id: string, snapshot: ProviderSnapshot | null | undefined) {
  const connectionId = id.startsWith('model:') ? id.slice('model:'.length).split(':')[0] : ''
  const connection = snapshot?.connections.find((c) => c.id === connectionId)
  if (!connection) return null
  if (connection.inferenceState === 'ready') return { label: 'ready', tone: 'ready' as const }
  if (connection.inferenceState === 'failed') return { label: 'failed', tone: 'failed' as const }
  return { label: 'untested', tone: 'idle' as const }
}

interface HarnessModelPickerProps {
  routerModels?: RouterSingleModel[]
  activeRouterModelId?: string
  onRouterModelChange?: (id: string) => void
}

/**
 * `provider:<providerId>:<modelId>` / `model:<connectionId>:<modelId>` → `<modelId>`.
 * Id model có thể chứa `:` nên phần đuôi phải nối lại, không lấy một mảnh.
 */
function rowModelId(id: string) {
  return id.split(':').slice(2).join(':')
}

/**
 * Đích dò reasoning của một hàng. Hàng ghim (`model:<connectionId>:<modelId>`) chỉ có một
 * connection. Hàng nhóm phải dò MỌI connection định tuyến được, vì `thinkingLevels` của hàng
 * nhóm là GIAO của các connection (`intersectThinkingLevels`): dò một cái rồi nạp lại snapshot
 * thì bộ chọn mức vẫn không hiện, và người dùng vừa bấm một nút "không có tác dụng gì".
 *
 * Luật "định tuyến được" không chép lại ở đây — `routable()` là bản sao duy nhất phía UI.
 */
function probeTargets(id: string, snapshot: ProviderSnapshot | null | undefined) {
  const parts = id.split(':')
  if (parts[0] === 'model') return [{ connectionId: parts[1], modelId: rowModelId(id) }]
  const providerId = parts[1]
  const modelId = rowModelId(id)
  return (snapshot?.connections ?? [])
    .filter((connection) => connection.providerId === providerId
      && (connection.models ?? []).some((model) => model.id === modelId && routable(connection, model)))
    .map((connection) => ({ connectionId: connection.id, modelId }))
}

/** Câu trả lời của route `…/models/:modelId/reasoning-probe` — chỉ những trường dòng phụ cần. */
interface ReasoningProbeResult {
  status: string
  thinkingLevels?: string[]
  samples?: number
  reasoningChars?: number
  reasoningTokens?: number
  thinkingEvidence?: string | null
  retryAfterMs?: number | null
}

/**
 * Một câu cho dòng phụ, đúng từ vựng trạng thái của router (`judgeReasoningProbe`) — không tự
 * diễn giải thành lời hứa. "1 level measured" phải nói thẳng là bộ chọn mức KHÔNG hiện, vì bộ
 * chọn đòi > 1 mức: thà nói ra còn hơn để người dùng đoán.
 */
function probeNote(result: ReasoningProbeResult | null) {
  if (!result) return 'the router sent no answer'
  if (result.status === 'supports') {
    const levels = result.thinkingLevels?.length ?? 0
    if (levels > 1) return `${levels} levels measured`
    if (levels === 1) return '1 level measured — the picker needs more than one'
    return 'reasoning without a level — nothing to pick'
  }
  if (result.status === 'refuses') return 'the provider refuses the reasoning field'
  if (result.status === 'inconclusive') return `${result.samples ?? 0} samples, no reasoning seen`
  if (result.status === 'rate_limited') return 'rate limited — try again later'
  if (result.status === 'not_entitled') return 'this key is not entitled to the model'
  if (result.status === 'not_in_catalogue') return 'the provider does not list the model any more'
  if (result.status === 'not_on_connection') return 'the model is not on this connection'
  if (result.status === 'unavailable') return 'the provider is unavailable right now'
  return result.status
}

/** Một đích dò đã trả lời. `measured` theo ĐÚNG luật của router: chỉ `supports`/`refuses` mới ghi được hàng. */
interface ProbeOutcome {
  measured: boolean
  error: boolean
  note: string
}

/**
 * Gộp kết quả của MỌI đích thành MỘT câu. Hàng nhóm lấy `thinkingLevels` là GIAO của các
 * connection, nên ghi đè bằng câu của đích chạy được ("4 levels measured") là hứa hão khi một
 * đích khác hỏng hoặc bị rate-limit: nạp lại xong bộ chọn mức vẫn không hiện, mà chẳng có gì
 * nói vì sao. Vì vậy hàng nhiều đích luôn nói "mấy trên mấy", và lỗi đầu tiên giữ nguyên văn.
 */
function probeRun(outcomes: ProbeOutcome[], total: number): { state: 'done' | 'error'; note: string } {
  if (total === 1) {
    const only = outcomes[0]
    if (!only) return { state: 'error', note: 'the router sent no answer' }
    return { state: only.error ? 'error' : 'done', note: only.note }
  }
  const measured = outcomes.filter((outcome) => outcome.measured)
  const failed = outcomes.filter((outcome) => !outcome.measured)
  const counted = `${measured.length}/${total} connections measured`
  if (!failed.length) return { state: 'done', note: `${counted} — ${[...new Set(measured.map((outcome) => outcome.note))].join(' · ')}` }
  return {
    state: 'error',
    note: measured.length ? `${counted} — ${failed.length} failed: ${failed[0].note}` : `${failed.length}/${total} failed: ${failed[0].note}`,
  }
}

export function HarnessModelPicker({ routerModels, activeRouterModelId, onRouterModelChange }: HarnessModelPickerProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [activeTab, setActiveTab] = useState<'harness' | 'model'>('harness')
  const triggerRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [panelPosition, setPanelPosition] = useState<{ left: number; bottom: number } | null>(null)
  const sidebarCollapsed = useUiStore((s) => s.sidebarCollapsed)

  const harnesses = useHarnessStore((s) => s.harnesses)
  const activeHarnessId = useHarnessStore((s) => s.activeHarnessId)
  const activeModelId = useHarnessStore((s) => s.activeModelId)
  const activeType = useHarnessStore((s) => s.activeType)
  const thinkingLevel = useHarnessStore((s) => s.thinkingLevel)
  const setActiveHarness = useHarnessStore((s) => s.setActiveHarness)
  const setActiveModel = useHarnessStore((s) => s.setActiveModel)
  const setThinkingLevel = useHarnessStore((s) => s.setThinkingLevel)
  const openSettings = useUiStore((s) => s.openSettings)

  // ── Live Provider Models (tự kết nối Router, chỉ hiện khi user đã bật
  //    provider trong Settings > Provider) ────────────────────────────────
  const { snapshot, load: loadProviders } = useProviderStore()
  useEffect(() => {
    if (!snapshot) void loadProviders().catch(() => {})
  }, [snapshot, loadProviders])

  // ── Dò reasoning (nhóm M) ────────────────────────────────────────────────
  // Vì sao nút này nằm Ở ĐÂY: bộ chọn mức chỉ hiện khi model công bố > 1 mức, nên model mới
  // (`thinkingSource: 'unknown'`) hiện ra như thể nó không suy luận — người dùng chỉ thấy một
  // điều khiển biến mất mà không có gì giải thích. Đây là chỗ họ nhận ra điều đó, nên cũng là
  // chỗ phải có cách đo và câu trả lời vì sao.
  const [probes, setProbes] = useState<Record<string, { state: 'running' | 'done' | 'error'; note: string }>>({})
  const probeControllers = useRef(new Map<string, AbortController>())
  useEffect(() => () => {
    // Một phép dò có thể chạy tới 90 s; rời màn hình thì huỷ, đừng để nó ghi state vào hư không.
    for (const controller of probeControllers.current.values()) controller.abort()
  }, [])

  const runReasoningProbe = useCallback(async (id: string) => {
    const targets = probeTargets(id, useProviderStore.getState().snapshot)
    if (targets.length === 0) {
      setProbes((previous) => ({ ...previous, [id]: { state: 'error', note: 'no routable connection for this model' } }))
      return
    }
    const controller = new AbortController()
    probeControllers.current.set(id, controller)
    setProbes((previous) => ({ ...previous, [id]: { state: 'running', note: targets.length > 1 ? `measuring ${targets.length} connections…` : 'measuring…' } }))
    const outcomes: ProbeOutcome[] = []
    for (const target of targets) {
      try {
        const result = await api<ReasoningProbeResult>(
          `/api/router/connections/${encodeURIComponent(target.connectionId)}/models/${encodeURIComponent(target.modelId)}/reasoning-probe`,
          { method: 'POST', signal: controller.signal },
        )
        // Chỉ `supports`/`refuses` mới ghi được hàng (xem `reasoningProbeRowPatch` phía router):
        // mọi kết luận khác — kể cả `rate_limited` — là CHƯA đo được, không được tính là xong.
        outcomes.push({
          measured: result.status === 'supports' || result.status === 'refuses',
          error: false,
          note: probeNote(result),
        })
      } catch (error) {
        // Không đi qua `useProviderStore.request()`: một phép dò có thể chạy 90 s và cờ `busy`
        // toàn cục sẽ đóng băng mọi nút trên màn hình; câu trả lời cũng thuộc về ĐÚNG hàng này.
        outcomes.push({ measured: false, error: true, note: error instanceof Error ? error.message : 'Router request failed.' })
      }
    }
    if (controller.signal.aborted) return
    probeControllers.current.delete(id)
    // Bộ chọn mức đọc từ snapshot, nên phải nạp lại: hàng vừa đo xong mới có `thinkingLevels`.
    await loadProviders().catch(() => {})
    setProbes((previous) => ({ ...previous, [id]: probeRun(outcomes, targets.length) }))
  }, [loadProviders])

  /**
   * Nguồn của `thinkingLevels` theo model, để dòng phụ nói được "vì sao không có bộ chọn mức".
   * Nguồn mạnh nhất thắng (`probe`/`live` nói được nhiều hơn `unknown`).
   */
  const thinkingFacts = useMemo(() => {
    const facts = new Map<string, { source: string; asOf: string | null; stale: boolean }>()
    for (const connection of snapshot?.connections ?? []) {
      for (const model of connection.models ?? []) {
        const key = `${connection.providerId}:${model.id}`
        const current = facts.get(key)
        const source = model.thinkingSource ?? 'unknown'
        if (current && !(current.source === 'unknown' && source !== 'unknown')) continue
        facts.set(key, { source, asOf: model.thinkingAsOf ?? null, stale: model.thinkingStale === true })
      }
    }
    return facts
  }, [snapshot])

  /**
   * Vòng 29 — MỘT dòng cho mỗi (provider, model): danh sách option sống ở `lib/routeOptions.ts`
   * (đúng hàm composer dùng). Picker KHÔNG tự dựng danh sách thứ hai — bản cũ dựng một dòng cho
   * mỗi connection, nên bốn connection opencode cùng model hiện thành bốn dòng giống nhau.
   */
  const liveOptions = useMemo(() => composerModels(routerChatOptions(snapshot)), [snapshot])

  // Khi có live models từ provider → ưu tiên hiển thị, ngược lại fallback
  // về danh sách tĩnh AVAILABLE_MODELS.
  const hasLive = liveOptions.length > 0 || (routerModels && routerModels.length > 0)
  const effectiveModels = routerModels && routerModels.length > 0
    ? routerModels.map(withPublishedLevels)
    : liveOptions.length > 0 ? liveOptions.map(withPublishedLevels) : null

  /** Nhánh ghim của nhóm nào đang mở; nhóm đang ghim thì luôn mở sẵn (xem `pinsOpen`). */
  const [openPins, setOpenPins] = useState<string | null>(null)

  /** Tra model theo id — TÌM CẢ trong `pins`: phiên ghim có id `model:<connectionId>:<modelId>`. */
  const modelById = useMemo(() => {
    const byId = new Map<string, RouterSingleModel>()
    for (const model of effectiveModels ?? []) {
      byId.set(model.id, model)
      for (const pin of model.pins ?? []) if (!byId.has(pin.id)) byId.set(pin.id, pin)
    }
    return byId
  }, [effectiveModels])

  // Đổi model: nếu mức thinking đang chọn không có trong danh sách model công bố
  // (ví dụ `medium` trong khi DeepSeek Pro chỉ có `max/high/low`) thì kéo về mức
  // gần nhất ngay, để nhãn trên composer khớp đúng mức sẽ gửi.
  useEffect(() => {
    const target = modelById.get(activeRouterModelId || activeModelId)
    if (!target?.thinkingLevels?.length) return
    if (thinkingLevelIsPublished(target.thinkingLevels, thinkingLevel)) return
    const next = resolveThinkingLevel(target.thinkingLevels, thinkingLevel)
    if (next && next !== thinkingLevel) setThinkingLevel(next)
  }, [modelById, activeRouterModelId, activeModelId, thinkingLevel, setThinkingLevel])

  // Current active entity
  const currentHarness = useMemo(
    () => harnesses.find((h) => h.id === activeHarnessId) ?? harnesses[0],
    [harnesses, activeHarnessId],
  )
  const currentModel = useMemo(
    () => AVAILABLE_MODELS.find((m) => m.id === activeModelId) ?? AVAILABLE_MODELS[0],
    [activeModelId],
  )
  const activeRouterId = activeRouterModelId || activeModelId
  /** Hàng cha của connection đang ghim (nếu lượt này đang ghim một connection). */
  const pinnedModel = useMemo(
    () => (effectiveModels ?? []).find((model) => model.pins?.some((pin) => pin.id === activeRouterId)) ?? null,
    [effectiveModels, activeRouterId],
  )
  const pinnedConnection = pinnedModel?.pins?.find((pin) => pin.id === activeRouterId) ?? null
  const currentRouterModel = modelById.get(activeRouterId)
    ?? effectiveModels?.find((model) => model.id === activeModelId)
    ?? effectiveModels?.[0] ?? null
  const selectedModelName = currentRouterModel?.name ?? currentModel?.name ?? ''
  const selectedModelProvider = currentRouterModel?.provider ?? currentModel?.provider ?? ''

  const displayModelName = useMemo(() => {
    // Ghim một connection: chip phải nói rõ đang ghim cái nào — nhãn hàng cha là cả nhóm, không
    // nói được điều đó (mockup 03: `pinned: OpenCode Free (key 2) · muse-spark-1.3-c…`).
    if (pinnedConnection && pinnedModel) {
      const parts = pinnedModel.name.split('·')
      const modelName = (parts.length > 1 ? parts.slice(1).join('·').trim() : pinnedModel.name).trim()
      const short = modelName.length > 16 ? modelName.slice(0, 14) + '…' : modelName
      return `pinned: ${pinnedConnection.name} · ${short}`
    }
    if (!selectedModelName) return ''
    const parts = selectedModelName.split('·')
    const rawName = parts.length > 1 ? parts.slice(1).join('·').trim() : selectedModelName
    const cleaned = rawName
      .replace(/^Nex AGI:\s*/i, '')
      .replace(/\s*\(free\)$/i, '')
      .replace(/\s*\(Low\)|\(Medium\)|\(High\)/i, '')
      .trim()
    if (cleaned.length > 0) {
      if (cleaned.includes('Claude')) return 'Sonnet'
      if (cleaned.includes('DeepSeek')) return 'DeepSeek'
      if (cleaned.includes('Gemini')) return 'Gemini'
      return cleaned.length > 18 ? cleaned.slice(0, 16) + '…' : cleaned
    }
    return selectedModelName.split(' ')[0]
  }, [pinnedConnection, pinnedModel, selectedModelName])

  const activeThinkingModel = useMemo(() => {
    if (activeType !== 'model') return null
    const target = modelById.get(activeRouterId)
    if (target?.thinkingLevels && target.thinkingLevels.length > 1) {
      return {
        id: target.id,
        name: target.name,
        provider: target.provider,
        thinkingLevels: target.thinkingLevels,
      }
    }
    return null
  }, [activeType, modelById, activeRouterId])

  const subagentCount = currentHarness?.subagents?.filter((s) => s.enabled).length ?? 1

  // Filtered lists
  const filteredHarnesses = useMemo(() => {
    if (!search.trim()) return harnesses
    const q = search.toLowerCase()
    return harnesses.filter(
      (h) =>
        h.name.toLowerCase().includes(q) ||
        h.description.toLowerCase().includes(q) ||
        h.mainModel.toLowerCase().includes(q),
    )
  }, [harnesses, search])

  const filteredModels = useMemo(() => {
    if (!search.trim()) return AVAILABLE_MODELS
    const q = search.toLowerCase()
    return AVAILABLE_MODELS.filter(
      (m) =>
        m.name.toLowerCase().includes(q) ||
        m.provider.toLowerCase().includes(q) ||
        (m.contextWindow ? m.contextWindow.toLowerCase().includes(q) : false),
    )
  }, [search])

  const filteredRouterModels = useMemo(() => {
    const list = effectiveModels ?? []
    if (!search.trim()) return list
    const q = search.toLowerCase()
    return list.filter((model) => model.name.toLowerCase().includes(q) || model.provider.toLowerCase().includes(q))
  }, [effectiveModels, search])

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node
      if (!triggerRef.current?.contains(target) && !panelRef.current?.contains(target)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  // Tính toán vị trí dropdown neo phía trên nút trigger
  const updatePosition = useCallback(() => {
    const rect = triggerRef.current?.getBoundingClientRect()
    if (!rect) return
    const width = 320
    const idealLeft = rect.right - width
    setPanelPosition({
      left: Math.max(8, Math.min(idealLeft, window.innerWidth - width - 8)),
      bottom: Math.max(8, window.innerHeight - rect.top + 8),
    })
  }, [])

  useLayoutEffect(() => {
    if (!open) return

    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open, updatePosition, sidebarCollapsed])

  const handleToggle = () => {
    if (!open) {
      updatePosition()
      setOpen(true)
    } else {
      setOpen(false)
    }
  }

  return (
    <div className="relative inline-block" ref={triggerRef}>
      {/* Trigger Button inside Chat Input Toolbar */}
      <button
        type="button"
        onClick={handleToggle}
        // F7 (đợt soát 2026-09-27) — chip này nằm trong hàng nút của ô soạn: `min-w-0` cho nó co lại
        // thay vì đẩy cả hàng, và mọi mảnh bên trong là `shrink-0` để tên model dài KHÔNG xuống ba
        // hàng (đo ở bố cục 1440: `OpenCode Free · mimo-v2.5-free` từng làm ô soạn cao bất thường).
        className={`flex min-w-0 max-w-[260px] items-center gap-1.5 rounded-lg border border-line/50 bg-panel px-2 py-1 text-xs text-muted transition hover:border-zinc-500 hover:text-fg cursor-pointer select-none ${open ? 'border-brand/60 bg-panel2 text-fg ring-1 ring-brand/30' : ''
          }`}
        title={
          activeType === 'harness'
            ? `Harness: ${currentHarness?.name} (${subagentCount} sub-agents)`
            : pinnedConnection && pinnedModel
              // Nhãn ghim bị cắt trong chip (`pinned: …`); chuột vào đây là đọc được cả connection đã
              // ghim lẫn tên ĐẦY ĐỦ của model — hai thứ mà nhãn cắt không nói hết.
              ? `Model: ${pinnedModel.name} (${selectedModelProvider}) · pinned ${pinnedConnection.name}`
              : `Model: ${selectedModelName} (${selectedModelProvider})`
        }
      >
        {activeType === 'harness' ? (
          <>
            <Bot className="size-3.5 shrink-0 text-brand" />
            {/* Nhãn của nhánh này là một CON SỐ nên nó không tự xuống hàng; `shrink-0` giữ đúng hợp
                đồng của chip: chỉ phần tên model được co và cắt, mọi mảnh khác đứng yên. */}
            <span className="shrink-0 font-semibold text-fg">{subagentCount}</span>
          </>
        ) : (
          <>
            {hasLive && selectedModelProvider ? (
              <ProviderIcon providerId={selectedModelProvider} className="size-3.5 shrink-0" />
            ) : (
              <Cpu className="size-3.5 shrink-0 text-amber-400" />
            )}
            <span className="flex min-w-0 items-center gap-1.5 font-semibold text-fg">
              {/* `truncate` + trần bề rộng: tên model dài đi vào một dòng, phần bị cắt vẫn đọc được
                  trọn vẹn ở `title` của nút. */}
              <span className="truncate max-w-[170px]" data-testid="composer-model-name">
                {displayModelName}
              </span>
              {activeThinkingModel && (
                <span className="shrink-0 text-[10px] text-brand font-medium px-1.5 py-0.5 rounded bg-brand/10 border border-brand/25 capitalize leading-none">
                  {thinkingLevel}
                </span>
              )}
            </span>
          </>
        )}
        <ChevronDown className={`size-2.5 shrink-0 text-muted transition ${open ? 'rotate-180' : ''}`} />
      </button>

      {/* Floating Popover (Anchored above the chat bar) */}
      {open && panelPosition && createPortal(
        <>
          <div
            ref={panelRef}
            className="fixed z-50 w-80 overflow-hidden rounded-xl border border-line bg-panel shadow-2xl animate-in fade-in zoom-in-95 duration-150 origin-bottom-right select-none"
            style={{ left: panelPosition.left, bottom: panelPosition.bottom }}
          >
            {/* Search Header */}
            <div className="border-b border-line/70 p-2 bg-panel2/70">
              <div className="relative flex items-center">
                <Search className="absolute left-2.5 size-3.5 text-muted pointer-events-none" />
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search harnesses or models..."
                  className="w-full rounded-lg border border-line/60 bg-panel px-2.5 py-1.5 pl-8 text-xs text-fg placeholder:text-muted/60 outline-hidden focus:border-zinc-500 focus:ring-1 focus:ring-zinc-600"
                  autoFocus
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => setSearch('')}
                    className="absolute right-2 text-muted hover:text-fg cursor-pointer"
                  >
                    <X className="size-3" />
                  </button>
                )}
              </div>

              {/* Segmented Switch Tabs */}
              <div className="mt-2 grid grid-cols-2 gap-1 rounded-lg border border-line/50 bg-panel p-0.5">
                <button
                  type="button"
                  onClick={() => setActiveTab('harness')}
                  className={`flex items-center justify-center gap-1.5 rounded-md py-1 text-[11px] font-medium transition cursor-pointer ${activeTab === 'harness'
                      ? 'bg-panel2 text-fg shadow-xs font-semibold'
                      : 'text-muted hover:text-fg'
                    }`}
                >
                  <Bot className="size-3 text-brand" />
                  <span>Harnesses</span>
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('model')}
                  className={`flex items-center justify-center gap-1.5 rounded-md py-1 text-[11px] font-medium transition cursor-pointer ${activeTab === 'model'
                      ? 'bg-panel2 text-fg shadow-xs font-semibold'
                      : 'text-muted hover:text-fg'
                    }`}
                >
                  <Cpu className="size-3 text-amber-400" />
                  <span>Single Models</span>
                </button>
              </div>
            </div>

            {/* Items List Area */}
            <div className="max-h-64 overflow-y-auto p-1.5 divide-y divide-line/30">
              {activeTab === 'harness' ? (
                /* Harnesses List */
                filteredHarnesses.length === 0 ? (
                  <div className="p-6 text-center text-xs text-muted">No harnesses found</div>
                ) : (
                  filteredHarnesses.map((harness) => {
                    const isSelected = activeType === 'harness' && activeHarnessId === harness.id
                    const enabledSubCount = harness.subagents?.filter((s) => s.enabled).length ?? 1
                    return (
                      <button
                        key={harness.id}
                        type="button"
                        onClick={() => {
                          setActiveHarness(harness.id)
                          setOpen(false)
                        }}
                        className={`flex w-full items-start justify-between rounded-lg p-2 text-left transition cursor-pointer ${isSelected
                            ? 'bg-brand/10 text-fg ring-1 ring-brand/30 dark:bg-brand/15'
                            : 'hover:bg-panel2/60 text-muted hover:text-fg'
                          }`}
                      >
                        <div className="min-w-0 flex-1 space-y-0.5">
                          <div className="flex items-center gap-1.5">
                            <span className="font-semibold text-xs text-fg">{harness.name}</span>
                            {harness.isBuiltIn && (
                              <span className="rounded bg-panel px-1 py-0.2 text-[9px] font-mono text-muted border border-line">
                                default
                              </span>
                            )}
                          </div>
                          <p className="line-clamp-1 text-[11px] text-muted leading-tight">
                            {harness.description}
                          </p>
                          <div className="mt-1 flex items-center gap-2 text-[10px] text-zinc-500 font-mono">
                            <span className="flex items-center gap-1">
                              <Bot className="size-2.5 text-brand" />
                              {enabledSubCount} sub-agents
                            </span>
                            <span>·</span>
                            <span className="truncate">{harness.mainModel}</span>
                          </div>
                        </div>

                        {isSelected && (
                          <Check className="size-4 shrink-0 text-brand mt-0.5 ml-2" />
                        )}
                      </button>
                    )
                  })
                )
              ) : (
                /* Single Models List — hiển thị live models khi user đã bật
                   provider trong Settings, ngược lại fallback AVAILABLE_MODELS */
                hasLive ? (
                  filteredRouterModels.length === 0 ? (
                    <div className="p-6 text-center text-xs text-muted">No models found</div>
                  ) : (
                    filteredRouterModels.map((model) => {
                      const pins = model.pins ?? []
                      // `activeRouterId` chứ không phải prop: đường ChatInputBar truyền
                      // `activeRouterModelId`, còn chỗ gọi khác chỉ đặt id qua store — cả hai đều
                      // phải nhận ra hàng đang chạy để không bày dấu tích sai chỗ.
                      const pinned = pins.find((pin) => pin.id === activeRouterId) ?? null
                      const isSelected = activeType === 'model'
                        && (activeRouterId === model.id || Boolean(pinned))
                      const rowHasThinking = Boolean(model.thinkingLevels && model.thinkingLevels.length > 1)
                      // Hàng đang ghim: mức hiện trên hàng phải là mức của CONNECTION đang chạy, không
                      // phải giao của cả nhóm — mức nào gửi đi phải khớp đúng thứ đang thấy.
                      const selectedLevels = pinned ? pinned.thinkingLevels : model.thinkingLevels
                      const hasThinking = Boolean(selectedLevels && selectedLevels.length > 1)
                      const pinsOpen = openPins === model.id || Boolean(pinned)
                      // Nhóm connection đã bị dò hỏng thì KHÔNG dò reasoning được (router không
                      // định tuyến được model đó), nên đừng bày nút bấm chắc chắn hỏng.
                      const probe = probes[model.id]
                      const facts = thinkingFacts.get(`${model.provider}:${rowModelId(model.id)}`)
                      return (
                        <div
                          key={model.id}
                          role="button"
                          tabIndex={0}
                          aria-pressed={isSelected}
                          data-component-id={`model-row-${model.id}`}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              onRouterModelChange?.(model.id)
                              setActiveModel(model.id)
                            }
                          }}
                          onClick={() => {
                            onRouterModelChange?.(model.id)
                            setActiveModel(model.id)
                            if (!rowHasThinking) {
                              setOpen(false)
                            }
                          }}
                          className={`flex flex-col rounded-lg p-2 text-left transition cursor-pointer select-none ${
                            isSelected
                              ? 'bg-brand/10 text-fg ring-1 ring-brand/30 dark:bg-brand/15'
                              : 'hover:bg-panel2/60 text-muted hover:text-fg'
                          }`}
                        >
                          <div className="flex w-full items-center justify-between">
                            <div className="min-w-0 flex-1 space-y-0.5">
                              <div className="flex items-center gap-2">
                                <ProviderIcon providerId={model.provider} className="size-4" />
                                <span className="font-semibold text-xs text-fg truncate">{model.name}</span>
                              </div>
                              {/* `flex-wrap` + `whitespace-nowrap`: hàng phụ có thể dài (nhiều connection,
                                  nhiều khoá, thêm cảnh báo model gõ tay) — các mảnh phải xuống dòng
                                  NGUYÊN VẸN, không bị bóp cho tới khi chữ gãy giữa từ. Khe hở `1.5` (không phải `2`) để
                                  hàng phụ của nhóm bình thường VẪN vừa một dòng: đo trong bảng chọn thật,
                                  một dòng cần 231.5px trong 235px. */}
                              <div className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[10px] text-zinc-500 font-mono">
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                  <span className={`size-1.5 rounded-full inline-block ${isSelected ? 'bg-emerald-500' : 'bg-zinc-600'}`} />
                                  Live Provider
                                </span>
                                {/* Số connection KHÔNG vào nhãn (nhãn bị `displayModelName` cắt theo `·`);
                                    đây là chỗ duy nhất nói dòng này gộp mấy connection. */}
                                {model.connections && model.connections > 1 && (
                                  <>
                                    <span>·</span>
                                    <span className="whitespace-nowrap">{model.connections} connections</span>
                                  </>
                                )}
                                {/* Số khoá cũng nói được điều mà tên connection không nói: cả nhóm
                                    đang có mấy khoá để router xoay khi một khoá hết hạn mức. */}
                                {model.keys && model.keys > 1 && (
                                  <>
                                    <span>·</span>
                                    <span className="whitespace-nowrap">{model.keys} keys</span>
                                  </>
                                )}
                                {/* Connection dò hỏng nhưng model gõ tay: router VẪN định tuyến (nhánh
                                    `custom` của `validTarget`), nên hàng phải nói ra thay vì gộp im
                                    lặng với connection đã dò được danh sách. */}
                                {(model.handTyped ?? 0) > 0 && (
                                  <>
                                    <span>·</span>
                                    <span
                                      className="whitespace-nowrap text-amber-400"
                                      title={`Model discovery did not complete on ${model.handTyped} of these connections, so only the models typed by hand are routable there. The router still routes them.`}
                                    >
                                      {model.handTyped} hand-typed
                                    </span>
                                  </>
                                )}
                                {/* Nguồn của các mức thinking. Đây là câu trả lời cho "vì sao model
                                    này không có bộ chọn mức": `unknown` nghĩa là chưa ai đo. */}
                                {facts && (
                                  <>
                                    <span>·</span>
                                    <span
                                      data-component-id={`thinking-facts-${model.id}`}
                                      className={`whitespace-nowrap ${facts.stale ? 'text-amber-400' : ''}`}
                                      title={facts.source === 'unknown'
                                        ? 'Nobody has measured whether this model returns reasoning, so there is no thinking level picker. Use “Measure thinking”.'
                                        : `Thinking levels come from: ${facts.source}${facts.asOf ? ` (${facts.asOf})` : ''}.${facts.stale ? ' That reading is old — measure again.' : ''}`}
                                    >
                                      thinking: {facts.source === 'unknown' ? 'not measured' : `${facts.source}${facts.asOf ? ` ${facts.asOf}` : ''}`}
                                      {facts.stale ? ' (old)' : ''}
                                    </span>
                                  </>
                                )}
                                {/* Nút dò: hiện khi KHÔNG có bộ chọn mức (chỗ người dùng đang thắc
                                    mắc), và khi số đo cũ đã quá hạn. Đo xong thì nạp lại snapshot,
                                    và bộ chọn mức tự hiện nếu đo được > 1 mức. */}
                                {(!rowHasThinking || facts?.stale) && (
                                  <>
                                    <span>·</span>
                                    <button
                                      type="button"
                                      disabled={probe?.state === 'running'}
                                      aria-label={`Measure whether ${model.name} returns reasoning and at which levels`}
                                      title="Ask the router to measure reasoning through this provider's own request shape."
                                      data-component-id={`thinking-probe-${model.id}`}
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        void runReasoningProbe(model.id)
                                      }}
                                      className="whitespace-nowrap text-brand hover:underline cursor-pointer disabled:cursor-wait disabled:opacity-60"
                                    >
                                      {probe?.state === 'running' ? 'measuring…' : 'Measure thinking'}
                                    </button>
                                  </>
                                )}
                              </div>
                              {probe && (
                                <div
                                  data-component-id={`thinking-probe-note-${model.id}`}
                                  className={`flex items-center gap-1 text-[10px] font-mono ${probe.state === 'error' ? 'text-amber-400' : 'text-zinc-500'}`}
                                >
                                  {probe.state === 'running' && <Loader2 className="size-2.5 shrink-0 animate-spin" />}
                                  <span className="min-w-0 truncate">{probe.note}</span>
                                </div>
                              )}
                              {pinned && (
                                <div className="flex items-center gap-1 text-[10px] text-brand font-mono">
                                  <Pin className="size-2.5" />
                                  <span>pinned · {pinned.name}</span>
                                </div>
                              )}
                            </div>

                            {/* Chỉ hiện khi nhóm có ≥ 2 connection: ghim một connection là việc vô nghĩa
                                khi cả nhóm chỉ có một. */}
                            {pins.length > 1 && (
                              <button
                                type="button"
                                aria-expanded={pinsOpen}
                                aria-label={pinsOpen ? 'Collapse the connection list' : 'Pin one connection for this model'}
                                title="Pin one connection"
                                data-component-id={`model-row-pin-toggle-${model.id}`}
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setOpenPins(pinsOpen && openPins === model.id ? null : model.id)
                                }}
                                className={`ml-2 flex size-5 shrink-0 items-center justify-center rounded-md transition cursor-pointer ${
                                  pinsOpen ? 'bg-brand/10 text-brand' : 'text-muted hover:bg-panel2 hover:text-fg'
                                }`}
                              >
                                <ChevronRight className={`size-3 transition ${pinsOpen ? 'rotate-90' : ''}`} />
                              </button>
                            )}

                            {isSelected && (
                              <Check className="size-4 shrink-0 text-brand ml-2" />
                            )}
                          </div>

                          {/* Nhánh ghim: một hàng con cho mỗi connection của nhóm — chỗ DUY NHẤT còn hiện
                              tên connection. Bấm hàng con ⇒ route `model:<connectionId>:<modelId>` (đường
                              cũ), router thôi chạy luân phiên. */}
                          {pinsOpen && (
                            <div
                              className="mt-1.5 rounded-md border border-line/50 bg-panel/70 p-1"
                              data-component-id={`pin-menu-${model.id}`}
                              onClick={(e) => e.stopPropagation()}
                            >
                              <div className="flex select-none items-center gap-1.5 px-1.5 pb-1 pt-0.5">
                                <Pin className="size-2.5 text-brand" />
                                <span className="text-[10px] font-semibold text-fg">Pin this connection</span>
                                <span className="min-w-0 flex-1" />
                                {pinned ? (
                                  <button
                                    type="button"
                                    aria-label={`Unpin the connection in use and go back to rotating across all ${pins.length} connections`}
                                    data-component-id={`pin-row-${pinned.id}-unpin`}
                                    onClick={() => {
                                      onRouterModelChange?.(model.id)
                                      setActiveModel(model.id)
                                    }}
                                    className="text-[10px] font-medium text-brand hover:underline cursor-pointer"
                                  >
                                    Unpin
                                  </button>
                                ) : (
                                  <span className="text-[9.5px] text-muted">this connection only</span>
                                )}
                              </div>
                              {pins.map((pin) => {
                                const isPinned = pinned?.id === pin.id
                                const state = pinState(pin.id, snapshot)
                                return (
                                  <div
                                    key={pin.id}
                                    role="button"
                                    tabIndex={0}
                                    aria-pressed={isPinned}
                                    data-component-id={`pin-row-${pin.id}`}
                                    onKeyDown={(e) => {
                                      if (e.key === 'Enter' || e.key === ' ') {
                                        onRouterModelChange?.(pin.id)
                                        setActiveModel(pin.id)
                                      }
                                    }}
                                    onClick={() => {
                                      onRouterModelChange?.(pin.id)
                                      setActiveModel(pin.id)
                                      // Hàng con cũng giữ panel ở lại khi connection đó có mức thinking,
                                      // để chọn mức ngay tại chỗ (cùng luật với hàng cha).
                                      if (!(pin.thinkingLevels && pin.thinkingLevels.length > 1)) setOpen(false)
                                    }}
                                    className={`flex items-center gap-2 rounded-md px-2 py-1 cursor-pointer select-none ${
                                      isPinned ? 'bg-brand/10 ring-1 ring-brand/30' : 'hover:bg-panel2/60'
                                    }`}
                                  >
                                    {isPinned
                                      ? <Pin className="size-2.5 shrink-0 text-brand" />
                                      : <span className={`size-1.5 shrink-0 rounded-full inline-block ${state?.tone === 'failed' ? 'bg-rose-500' : 'bg-zinc-600'}`} />}
                                    <span className="min-w-0 flex-1 truncate text-[11.5px] text-fg">{pin.name}</span>
                                    {state && (
                                      <span className={`shrink-0 font-mono text-[9.5px] ${state.tone === 'ready' ? 'text-emerald-400' : state.tone === 'failed' ? 'text-amber-400' : 'text-zinc-500'}`}>
                                        {state.label}
                                      </span>
                                    )}
                                    {isPinned && <span className="shrink-0 font-mono text-[9.5px] text-brand">in use</span>}
                                  </div>
                                )
                              })}
                            </div>
                          )}

                          {/* Inline Thinking Selector cho model đang được chọn */}
                          {isSelected && hasThinking && (
                            <div
                              className="mt-2 pt-1.5 border-t border-line/40 flex items-center justify-between"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <span className="text-[10px] text-muted font-medium flex items-center gap-1">
                                <Brain className="size-3 text-brand" />
                                <span>Thinking:</span>
                              </span>
                              <div className="flex items-center gap-1 bg-panel p-0.5 rounded-md border border-line/50">
                                {selectedLevels!.map((lvl) => {
                                  const isActive = thinkingLevel === lvl
                                  return (
                                    <button
                                      key={lvl}
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        setThinkingLevel(lvl)
                                      }}
                                      className={`px-2 py-0.5 rounded text-[10px] font-medium transition cursor-pointer capitalize ${
                                        isActive
                                          ? 'bg-brand text-brandfg font-semibold shadow-xs'
                                          : 'text-muted hover:text-fg hover:bg-panel2'
                                      }`}
                                    >
                                      {lvl}
                                    </button>
                                  )
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })
                  )
                ) : (
                  filteredModels.length === 0 ? (
                    <div className="p-6 text-center text-xs text-muted">No models found</div>
                  ) : (
                    filteredModels.map((model) => {
                      const isSelected = activeType === 'model' && activeModelId === model.id
                      const hasThinking = Boolean(model.thinkingLevels && model.thinkingLevels.length > 1)
                      return (
                        <div
                          key={model.id}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              setActiveModel(model.id)
                            }
                          }}
                          onClick={() => {
                            setActiveModel(model.id)
                            if (!hasThinking) {
                              setOpen(false)
                            }
                          }}
                          className={`flex flex-col rounded-lg p-2 text-left transition cursor-pointer select-none ${
                            isSelected
                              ? 'bg-brand/10 text-fg ring-1 ring-brand/30 dark:bg-brand/15'
                              : 'hover:bg-panel2/60 text-muted hover:text-fg'
                          }`}
                        >
                          <div className="flex w-full items-center justify-between">
                            <div className="min-w-0 flex-1 space-y-0.5">
                              <div className="flex items-center gap-2">
                                <Cpu className="size-4 text-amber-400" />
                                <span className="font-semibold text-xs text-fg">{model.name}</span>
                              </div>
                              <div className="flex items-center gap-2 text-[10px] text-zinc-500 font-mono">
                                <span>{model.provider}</span>
                                {model.contextWindow && (
                                  <>
                                    <span>·</span>
                                    <span>{model.contextWindow}</span>
                                  </>
                                )}
                              </div>
                            </div>

                            {isSelected && (
                              <Check className="size-4 shrink-0 text-brand ml-2" />
                            )}
                          </div>

                          {/* Inline Thinking Selector cho model đang được chọn */}
                          {isSelected && hasThinking && (
                            <div
                              className="mt-2 pt-1.5 border-t border-line/40 flex items-center justify-between"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <span className="text-[10px] text-muted font-medium flex items-center gap-1">
                                <Brain className="size-3 text-brand" />
                                <span>Thinking:</span>
                              </span>
                              <div className="flex items-center gap-1 bg-panel p-0.5 rounded-md border border-line/50">
                                {model.thinkingLevels!.map((lvl) => {
                                  const isActive = thinkingLevel === lvl
                                  return (
                                    <button
                                      key={lvl}
                                      type="button"
                                      onClick={(e) => {
                                        e.stopPropagation()
                                        setThinkingLevel(lvl)
                                      }}
                                      className={`px-2 py-0.5 rounded text-[10px] font-medium transition cursor-pointer capitalize ${
                                        isActive
                                          ? 'bg-brand text-brandfg font-semibold shadow-xs'
                                          : 'text-muted hover:text-fg hover:bg-panel2'
                                      }`}
                                    >
                                      {lvl}
                                    </button>
                                  )
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      )
                    })
                  )
                )
              )}
            </div>

            {/* Dòng nhắc của tab Single Models: chọn cả nhóm nghĩa là router tự chuyển khoá khi
                một khoá hết hạn mức — điều mà danh sách một-dòng-mỗi-model mang lại. */}
            {activeTab === 'model' && (
              <div className="flex items-center gap-1.5 border-t border-line/70 px-3 py-1.5 text-[10px] text-muted">
                <KeyRound className="size-2.5 text-zinc-500" />
                <span>Auto-switch on quota — shared across the group.</span>
              </div>
            )}

            {/* Footer Actions (Manage & Create) */}
            <div className="flex items-center justify-between border-t border-line/70 bg-panel2/60 px-3 py-2 text-xs">
              <button
                type="button"
                onClick={() => {
                  openSettings('harness')
                  setOpen(false)
                }}
                className="flex items-center gap-1.5 text-muted hover:text-fg transition cursor-pointer"
              >
                <Settings className="size-3.5" />
                <span className="text-[11px] font-medium">Manage Harnesses</span>
              </button>

              <button
                type="button"
                onClick={() => {
                  openSettings('harness')
                  setOpen(false)
                }}
                className="flex items-center gap-1 text-brand hover:underline text-[11px] font-medium cursor-pointer"
              >
                <Plus className="size-3" />
                <span>Create Harness</span>
              </button>
            </div>
          </div>
        </>,
        document.body,
      )}
    </div>
  )
}
