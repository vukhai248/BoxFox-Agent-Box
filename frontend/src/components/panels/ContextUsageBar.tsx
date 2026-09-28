/**
 * Thanh hiển thị Context Window & Modal Chi tiết Phân rã Context (Master-Detail Split Modal).
 * - Thanh đầu: Hiển thị thanh tiến trình token, trạng thái High/Normal, nút Compact nhanh và nút mở Modal.
 * - Modal Popup 2/3 màn hình: Tái cấu trúc chuẩn Design System (Semantic Tokens), phân loại tabs kèm badge đếm,
 *   nhãn bảo mật IFC trực quan, và khung xem mã nguồn chuẩn IDE.
 */
import { useState, useMemo, useEffect } from 'react'
import {
  Zap,
  X,
  Sparkles,
  FileCode,
  MessageSquare,
  Check,
  Copy,
  Terminal,
  Layers,
  ChevronRight,
  Database,
  Maximize2,
  ShieldCheck,
  ShieldAlert,
  Globe,
  Lock,
  KeyRound,
  FileText,
  Search,
} from 'lucide-react'
import { useT, type TKey, type TVars } from '../../i18n/context'
import { readingColumnClass } from '../../lib/readingColumn'
import { useUiStore } from '../../store/uiStore'
import { useAgentStore } from '../../store/agentStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useHarnessStore, AVAILABLE_MODELS } from '../../store/harnessStore'
import { useProviderStore } from '../../store/providerStore'
import { useRouterChatStore, type RouterChatSelection } from '../../store/routerChatStore'
import { routable } from '../../lib/routeOptions'
import type { ProviderSnapshot } from '../../types/provider'
import { LabelDot } from '../LabelDot'
import type { ContextChunk } from '../../types/context'

export interface DisplayChunk {
  id: string
  label_id: string
  title: string
  sourceKind: string
  sourceUri: string
  tokens: number
  percent: number
  integrity: 'duoc_nguoi_dung_cho_phep' | 'khong_tin_duoc'
  confidentiality: 'cong_khai' | 'noi_bo' | 'bi_mat'
  derivedFrom: string[]
  content: string
  lineCount: number
}

/**
 * Nguồn của con số cửa sổ ngữ cảnh — cùng từ vựng `contextWindowSource` mà router
 * công bố trên mỗi dòng model, cộng hai nguồn chỉ giao diện biết:
 * - `reported`: số nhà cung cấp công bố (router chuyển tiếp) — nguồn duy nhất không ước lượng.
 * - `manual`: người dùng tự khai cho model đó; số này thắng cả router lẫn nhà cung cấp.
 * - `documented`: bảng model của BoxFox (router) — không phải nhà cung cấp báo, nên có `est.`.
 * - `fallback`: không nguồn nào trả lời con số này — sàn an toàn của harness, hoặc một bản ghi
 *   phiên cũ không mang nhãn nguồn (không được đọc là `reported`) — có `est.`.
 * - `catalog`: danh mục tĩnh trong repo — ước lượng.
 * - `unknown`: không có số nào → hiện "unknown" (không vẽ phần trăm, KHÔNG bịa số).
 */
export type ContextWindowBasis = 'reported' | 'manual' | 'documented' | 'fallback' | 'catalog' | 'unknown'

/** Ba nguồn không phải nhà cung cấp báo: nhãn `est.` đi cùng đúng những nguồn này. */
const ESTIMATED_BASES: readonly ContextWindowBasis[] = ['documented', 'fallback', 'catalog']

export interface ContextWindowResolution {
  tokens: number | null
  basis: ContextWindowBasis
  estimated: boolean
}

/** Dòng model trong snapshot router: số đang dùng + nhãn nguồn của chính router. */
export interface RouterModelMetadata {
  contextWindow?: number | null
  contextWindowSource?: string | null
  contextWindowReported?: number | null
}

/** Cặp `(số, nguồn)` mà `GET /api/agent/sessions/{sid}` trả về trong `config`. */
export interface SessionContextWindow {
  contextWindow?: number | null
  contextWindowSource?: string | null
}

/** Cửa sổ của một dòng model router: đã lọc số rác, đã quy nhãn về từ vựng của giao diện. */
export interface RouterWindow {
  tokens: number
  basis: 'reported' | 'manual' | 'documented'
}

function positiveInteger(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return null
  return Math.round(value)
}

/**
 * Đọc một dòng model router thành `{ số, nguồn }`.
 *
 * Router cũ (trước đợt 18) không có `contextWindowSource`, và dòng do nó điền từ
 * payload nhà cung cấp cũng không có: cả hai đọc là `reported`.
 */
function readRouterWindow(model: unknown): RouterWindow | null {
  const row = model as RouterModelMetadata | null | undefined
  const tokens = positiveInteger(row?.contextWindow)
  if (tokens === null) return null
  const declared = row?.contextWindowSource
  return { tokens, basis: declared === 'manual' || declared === 'documented' ? declared : 'reported' }
}

const CATALOG_WINDOW_TOKENS: Record<string, number> = {
  '2M': 2_000_000,
  '1M': 1_000_000,
  '256k': 256_000,
  '200k': 200_000,
  '128k': 128_000,
}

/**
 * Tìm cửa sổ của model đang chạy trong snapshot router: ưu tiên route đang chọn
 * (model hoặc target đầu của alias), sau đó khớp nhãn model. Trả về CẢ nhãn nguồn
 * của dòng đó, vì "số này ở đâu ra" là câu hỏi thứ hai của người dùng.
 */
export function findRouterContextWindow(
  snapshot: ProviderSnapshot | null,
  selection: RouterChatSelection | null,
  modelLabelOrId?: string | null,
): RouterWindow | null {
  if (!snapshot) return null
  const modelOf = (connectionId?: string | null, modelId?: string | null) => {
    if (!connectionId || !modelId) return null
    const connection = snapshot.connections.find((c) => c.id === connectionId)
    return connection?.models.find((m) => m.id === modelId) ?? null
  }

  if (selection?.kind === 'model') {
    const found = readRouterWindow(modelOf(selection.connectionId, selection.modelId))
    if (found) return found
  }
  if (selection?.kind === 'provider') {
    // Tuyến provider chạy trên BẤT KỲ connection dùng được nào của nhóm, nên số hiển thị phải là
    // số NHỎ NHẤT của nhóm — đúng con số harness nén theo (`aggregate_model_metadata` phía harness
    // lấy min cùng luật). Hứa số của target rộng nhất là hứa điều lượt không giữ được.
    let smallest: RouterWindow | null = null
    for (const connection of snapshot.connections) {
      if (connection.providerId !== selection.providerId) continue
      const model = connection.models.find((m) => m.id === selection.modelId)
      // Cùng luật với router (`validTarget`): connection `degraded`/`failed` vẫn là một đích nếu
      // model là thứ người dùng gõ tay. Bỏ nó đi là hứa cửa sổ RỘNG HƠN thứ harness nén theo.
      if (!routable(connection, model)) continue
      const found = readRouterWindow(model)
      if (!found) continue
      if (!smallest || found.tokens < smallest.tokens) smallest = found
    }
    if (smallest) return smallest
  }
  if (selection?.kind === 'alias') {
    const target = snapshot.aliases.find((a) => a.id === selection.aliasId)?.targets?.[0]
    const found = readRouterWindow(modelOf(target?.connectionId, target?.modelId))
    if (found) return found
  }

  // Nhãn harness là "Tên connection · Tên model (High)" — bỏ hậu tố mức thinking
  // rồi so khớp với id/tên model trong snapshot.
  const needle = (modelLabelOrId ?? '').replace(/\s*\((?:low|medium|high|minimal)\)\s*$/i, '').trim().toLowerCase()
  if (!needle) return null
  for (const connection of snapshot.connections) {
    for (const model of connection.models) {
      if (!needle.includes(model.id.toLowerCase()) && !needle.includes(model.name.toLowerCase())) continue
      const found = readRouterWindow(model)
      if (found) return found
    }
  }
  return null
}

/**
 * Context window của model đang chạy. Thứ tự: số đang có hiệu lực trong **bản ghi
 * phiên** (harness nén theo đúng số này) → dòng model router → danh mục tĩnh →
 * `unknown` (không bịa số).
 *
 * Bảng đoán theo tên (`gemini`→1M, `deepseek`→64k, `claude`→200k) đã bị xoá: nó là
 * câu trả lời thứ tư cho cùng một câu hỏi, và là câu trả lời sai — harness nén ở
 * 128 000 trong khi thanh ghi `64.0k (59%) est.`.
 */
export function resolveContextWindow(
  router: RouterWindow | null,
  modelIdOrName?: string | null,
  session?: SessionContextWindow | null,
): ContextWindowResolution {
  const fromSession = positiveInteger(session?.contextWindow)
  if (fromSession !== null) {
    const declared = session?.contextWindowSource
    // Bản ghi CÓ số mà KHÔNG có nhãn nguồn (phiên cũ, không mang `route` nên bản
    // vá lúc khởi động bỏ qua) không được đọc là `reported`: chưa ai báo con số
    // ấy cả — trước đợt 18 nhãn này vẫn còn dấu `est.` (lỗi b18-review #4). Đọc
    // là `fallback` (một nguồn KHÔNG phải nhà cung cấp) để số hiện kèm `est.` và
    // tooltip nói thẳng là chưa có nguồn.
    const basis: ContextWindowBasis =
      declared === 'manual' || declared === 'documented' || declared === 'reported' ? declared : 'fallback'
    return { tokens: fromSession, basis, estimated: ESTIMATED_BASES.includes(basis) }
  }
  if (router) {
    return { tokens: router.tokens, basis: router.basis, estimated: ESTIMATED_BASES.includes(router.basis) }
  }
  if (!modelIdOrName) return { tokens: null, basis: 'unknown', estimated: false }

  const found = AVAILABLE_MODELS.find(m => m.id === modelIdOrName || m.name === modelIdOrName)
  const catalogTokens = found?.contextWindow ? CATALOG_WINDOW_TOKENS[found.contextWindow] : undefined
  if (catalogTokens) return { tokens: catalogTokens, basis: 'catalog', estimated: true }

  return { tokens: null, basis: 'unknown', estimated: false }
}

/**
 * Dòng `title` của nhãn, theo nguồn gốc con số. `reported` không cần tooltip (như
 * hôm nay): nhà cung cấp báo thì không có gì phải giải thích.
 */
export function contextWindowHint(
  resolution: ContextWindowResolution,
  t: (key: TKey, vars?: TVars) => string,
): string | undefined {
  switch (resolution.basis) {
    case 'reported':
      return undefined
    case 'manual':
      return t('contextUsage.manualHint')
    case 'documented':
      return t('contextUsage.documentedHint')
    case 'fallback':
      return t('contextUsage.fallbackHint', { tokens: formatTokenCount(resolution.tokens ?? 0) })
    case 'catalog':
      return t('contextUsage.estimatedHint')
    default:
      return t('contextUsage.unknownHint')
  }
}

/** `28.6k` / `1.0M` — dùng chung cho thanh và modal để hai nhãn không lệch nhau. */
export function formatTokenCount(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`
  return `${(tokens / 1000).toFixed(tokens >= 100_000 ? 0 : 1)}k`
}

export interface ContextUsageBarProps {
  variant?: 'topbar' | 'panel'
}

export function ContextUsageBar({ variant = 'panel' }: ContextUsageBarProps = {}) {
  const t = useT()
  const activeSessionId = useAgentStore((s) => s.activeSessionId)
  const harnessRun = useHarnessChatStore((s) => s.sessions[activeSessionId])
  const sendHarnessCommand = useHarnessChatStore((s) => s.send)
  const activeModelId = useHarnessStore((s) => s.activeModelId)
  const workspaceHidden = useUiStore((s) => s.workspaceHidden)
  const openTabs = useUiStore((s) => s.openTabs)
  const isReadingColumn = workspaceHidden || openTabs.length === 0

  const context = useAgentStore((s) => s.context)
  const contextChunks = context?.chunks || []
  const snapshot = useProviderStore((s) => s.snapshot)
  const routerSelection = useRouterChatStore((s) => s.selection)

  // Toggle modal mở rộng
  const [inspectorModalOpen, setInspectorModalOpen] = useState(false)
  const [selectedChunkId, setSelectedChunkId] = useState<string>('chunk-0')
  const [activeCategoryFilter, setActiveCategoryFilter] = useState<'all' | 'files' | 'tools' | 'chat'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [copied, setCopied] = useState(false)
  const [compactedSuccess, setCompactedSuccess] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // Context window thật theo model đang chạy: số đang có hiệu lực trong bản ghi
  // phiên trước (harness nén theo đúng số đó), rồi tới dòng model của router, cuối
  // cùng là danh mục tĩnh (BUG-4/U3 + vòng 18: bỏ bảng đoán theo tên).
  const modelLabel = harnessRun?.lastModelLabel || activeModelId
  const contextWindow = useMemo(() => {
    const router = findRouterContextWindow(snapshot, routerSelection, modelLabel)
    return resolveContextWindow(router, modelLabel, harnessRun)
  }, [snapshot, routerSelection, modelLabel, harnessRun])
  const contextLimitTokens = contextWindow.tokens
  const limitLabel = contextLimitTokens === null ? t('contextUsage.unknown') : formatTokenCount(contextLimitTokens)

  // Lắng nghe phím ESC để đóng Modal
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && inspectorModalOpen) {
        setInspectorModalOpen(false)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [inspectorModalOpen])

  // Tính toán tokens ước lượng từ event step của harnessRun hoặc fallback contextChunks
  const currentTokens = useMemo(() => {
    if (harnessRun?.events && harnessRun.events.length > 0) {
      // F7 (đợt 7): sau khi nén, `step` cuối vẫn mang ước lượng TRƯỚC khi nén, nên thanh
      // ngữ cảnh hiện số cũ cho tới lượt sau. Event `compression` mới hơn thì thắng.
      const sized = harnessRun.events.filter(
        e => e.type === 'step' || e.type === 'compression',
      )
      const lastSized = sized.at(-1)
      if (lastSized?.type === 'compression') {
        const after = lastSized.data?.afterEstimate
        if (typeof after === 'number') return after
      }
      const lastStep = sized.filter(e => e.type === 'step').at(-1)
      if (lastStep && typeof lastStep.data?.contextEstimate === 'number') {
        return lastStep.data.contextEstimate
      }
      // Ước lượng từ tổng độ dài text của các event assistant + user nếu chưa có step event
      const textLen = harnessRun.events.reduce((acc, ev) => {
        const t = String(ev.data?.text || ev.data?.thought || '')
        return acc + t.length
      }, 0)
      if (textLen > 0) {
        return Math.max(100, Math.round(textLen / 3.5))
      }
    }
    if (!contextChunks || contextChunks.length === 0) return 0
    return contextChunks.reduce((acc: number, c: ContextChunk) => acc + Math.round((c.content || '').length / 4), 0)
  }, [harnessRun?.events, contextChunks])

  // `percent === null` khi router chưa báo context window: không vẽ phần trăm,
  // không vẽ thanh tiến trình như thể đã biết mẫu số (U3).
  const percent = contextLimitTokens === null
    ? null
    : Math.min(Math.round((currentTokens / contextLimitTokens) * 100), 100)

  // Chunks hiển thị chuẩn hóa tiêu đề và định dạng từ contextChunks thực tế
  const displayChunks: DisplayChunk[] = useMemo(() => {
    if (!contextChunks || contextChunks.length === 0) return []
    return contextChunks.map((c: ContextChunk, idx: number) => {
      const estTokens = Math.max(1, Math.round((c.content || '').length / 4))
      const rawUri = c.provenance?.source_uri || 'file:///workspace'
      const filename = rawUri.split('/').pop() || rawUri

      let formattedTitle = filename
      if (c.provenance?.source_kind === 'user_input') formattedTitle = `User Prompt #${idx + 1}`
      else if (c.provenance?.source_kind === 'workspace_file') formattedTitle = `Source: ${filename}`
      else if (c.provenance?.source_kind === 'command_output') formattedTitle = `Terminal: ${c.provenance?.tool_name || 'output'}`
      else if (c.provenance?.source_kind === 'plan_artifact') formattedTitle = `Plan: ${filename}`

      return {
        id: `chunk-${idx}`,
        label_id: c.provenance?.label_id || `L${String(idx + 1).padStart(3, '0')}`,
        title: formattedTitle,
        sourceKind: c.provenance?.source_kind || 'workspace_file',
        sourceUri: rawUri,
        tokens: estTokens,
        percent: currentTokens > 0 ? Math.max(1, Math.round((estTokens / currentTokens) * 100)) : 0,
        integrity: c.integrity || 'duoc_nguoi_dung_cho_phep',
        confidentiality: c.confidentiality || 'cong_khai',
        derivedFrom: c.provenance?.derived_from || [],
        content: c.content || 'No preview content available.',
        lineCount: (c.content || '').split('\n').length || 1,
      }
    })
  }, [contextChunks, currentTokens])

  // Đếm số lượng theo danh mục cho tabs
  const tabCounts = useMemo(() => {
    return {
      all: displayChunks.length,
      files: displayChunks.filter((c) => c.sourceKind === 'workspace_file' || c.sourceKind === 'external_file' || c.sourceKind === 'plan_artifact').length,
      tools: displayChunks.filter((c) => c.sourceKind === 'command_output' || c.sourceKind === 'external_tool').length,
      chat: displayChunks.filter((c) => c.sourceKind === 'user_input' || c.sourceKind === 'system').length,
    }
  }, [displayChunks])

  // Lọc theo category và search
  const filteredChunks = useMemo(() => {
    let list = displayChunks

    if (activeCategoryFilter === 'files') {
      list = list.filter((c) => c.sourceKind === 'workspace_file' || c.sourceKind === 'external_file' || c.sourceKind === 'plan_artifact')
    } else if (activeCategoryFilter === 'tools') {
      list = list.filter((c) => c.sourceKind === 'command_output' || c.sourceKind === 'external_tool')
    } else if (activeCategoryFilter === 'chat') {
      list = list.filter((c) => c.sourceKind === 'user_input' || c.sourceKind === 'system')
    }

    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase()
      list = list.filter((c) => c.title.toLowerCase().includes(q) || c.sourceUri.toLowerCase().includes(q) || c.label_id.toLowerCase().includes(q))
    }

    return list
  }, [displayChunks, activeCategoryFilter, searchQuery])

  // Tự động chọn mẩu đầu tiên nếu mẩu đang chọn không thuộc danh sách sau lọc
  const selectedChunk = useMemo(() => {
    const found = filteredChunks.find((c) => c.id === selectedChunkId)
    if (found) return found
    return filteredChunks[0] || null
  }, [filteredChunks, selectedChunkId])

  const handleCopyContent = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const handleCompactAll = () => {
    if (activeSessionId) {
      void sendHarnessCommand(activeSessionId, '/compact', null)
    }
    setCompactedSuccess(true)
    setTimeout(() => {
      setCompactedSuccess(false)
    }, 1500)
  }

  const handleCompactSingleChunk = (id: string) => {
    const chunk = displayChunks.find((c) => c.id === id)
    if (chunk) {
      chunk.tokens = Math.round(chunk.tokens * 0.3)
      chunk.percent = Math.max(1, Math.round(chunk.percent * 0.3))
      chunk.title = `[Compacted] ${chunk.title}`
      chunk.content = `[Summary: High-level synthesis of ${chunk.sourceUri}]\n- Core definitions and logic retained.\n- Raw intermediate steps purged.`
      chunk.lineCount = 3
      setSelectedChunkId(id)
    }
  }

  const showMangaBubble = percent !== null && percent >= 75 && !dismissed

  return (
    <div
      data-testid="context-usage-bar"
      className={
        variant === 'topbar'
          ? 'relative flex items-center min-w-0 select-none'
          : 'relative border-b border-line bg-panel px-4 py-2 select-none'
      }
    >
      <div
        data-testid="context-usage-row"
        className={
          variant === 'topbar'
            ? 'flex items-center gap-2.5 sm:gap-3.5 overflow-hidden whitespace-nowrap min-w-0'
            : `flex @container items-center justify-between gap-3 overflow-hidden whitespace-nowrap ${readingColumnClass(isReadingColumn)}`
        }
      >
        {/* Left: Context Window Title & Expand Toggle */}
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            type="button"
            onClick={() => setInspectorModalOpen(true)}
            className="group flex items-center gap-1.5 text-xs font-semibold text-fg hover:text-brand transition cursor-pointer select-none"
            title="Click to open full Context Breakdown & Chunk Inspector modal"
          >
            <Zap className="size-3.5 text-amber-500 fill-amber-500/20" />
            <span className="font-semibold">{t('contextUsage.title')}</span>
            <Maximize2 className="size-3 text-muted group-hover:text-brand transition ml-0.5" />
          </button>
        </div>

        {/* Center: Progress Bar */}
        <div
          data-testid="context-usage-progress"
          className={
            variant === 'topbar'
              ? 'hidden sm:flex items-center w-24 md:w-36 lg:w-44 h-1.5 overflow-hidden rounded-full bg-panel2 border border-line'
              : 'hidden flex-1 min-w-[40px] max-w-xs items-center gap-2 @lg:flex'
          }
        >
          <div className={variant === 'topbar' ? 'relative h-full w-full overflow-hidden' : 'relative h-1.5 w-full overflow-hidden rounded-full bg-panel2 border border-line'}>
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                percent === null
                  ? 'bg-muted/40'
                  : percent >= 85
                    ? 'bg-rose-500'
                    : percent >= 70
                      ? 'bg-amber-500'
                      : 'bg-emerald-500'
              }`}
              style={{ width: `${percent ?? 0}%` }}
            />
          </div>
        </div>

        {/* Right: Token count & Actions */}
        <div data-testid="context-usage-actions" className="flex min-w-0 items-center gap-2">
          <span
            data-testid="context-usage-label"
            title={contextWindowHint(contextWindow, t)}
            className="min-w-0 overflow-hidden whitespace-nowrap text-ellipsis font-mono text-[11px] tabular-nums text-muted"
          >
            <strong className="text-fg">{formatTokenCount(currentTokens)}</strong>
            {' / '}
            <span>{limitLabel}</span>
            {percent !== null && <> ({percent}%)</>}
            {contextWindow.estimated ? (
              <span className={variant === 'topbar' ? 'ml-1 hidden xl:inline text-amber-500/90' : 'ml-1 hidden text-amber-500/90 @lg:inline'}>
                {t('contextUsage.estimated')}
              </span>
            ) : null}
          </span>

          <button
            type="button"
            onClick={handleCompactAll}
            data-testid="context-usage-compact"
            className={
              variant === 'topbar'
                ? `shrink-0 flex items-center gap-1 rounded-md px-2 py-0.5 text-[11px] font-medium transition cursor-pointer ${
                    compactedSuccess
                      ? 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/30'
                      : percent !== null && percent >= 75
                        ? 'border border-brand/50 bg-brand/10 text-fg hover:bg-brand/20 shadow-xs'
                        : 'border border-line bg-panel2/60 text-muted hover:text-fg hover:bg-panel2'
                  }`
                : `shrink-0 flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-semibold transition cursor-pointer ${
                    compactedSuccess
                      ? 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/30'
                      : percent !== null && percent >= 75
                        ? 'border border-brand/50 bg-brand/10 text-fg hover:bg-brand/20 shadow-xs'
                        : 'border border-line bg-panel2 text-muted hover:text-fg hover:bg-panel'
                  }`
            }
          >
            {compactedSuccess ? (
              <>
                <Check className="size-3 text-emerald-500" />
                <span className={variant === 'topbar' ? 'hidden sm:inline' : 'hidden @lg:inline'}>
                  {t('contextUsage.compacted')}
                </span>
              </>
            ) : (
              <>
                <Sparkles className="size-3 text-brand" />
                <span className={variant === 'topbar' ? 'hidden sm:inline' : 'hidden @lg:inline'}>
                  {t('contextUsage.compact')}
                </span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* ========================================================================= */}
      {/* FULL-SIZE POPUP MODAL (~2/3 SCREEN WIDTH & HEIGHT) */}
      {/* ========================================================================= */}
      {inspectorModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-xs p-4 md:p-8 animate-in fade-in duration-150">
          <div className="relative w-full max-w-5xl h-[84vh] rounded-2xl border border-line bg-panel shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-line bg-panel2 px-6 py-4 select-none">
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-xl bg-brand/15 text-brand border border-brand/30 shadow-xs">
                  <Database className="size-4.5" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-bold text-fg">Context Breakdown & Chunk Inspector</h2>
                    <span className="rounded-md bg-panel px-2 py-0.5 text-[10px] font-mono font-semibold text-muted border border-line">
                      {formatTokenCount(currentTokens)} / {limitLabel}{percent !== null && ` (${percent}%)`}
                    </span>
                  </div>
                  <p className="text-xs text-muted mt-0.5">
                    Inspect active context segments, provenance labels, and token usage distribution.
                  </p>
                </div>
              </div>

              {/* Category Filter Tabs & Close Button */}
              <div className="flex items-center gap-3">
                <div className="flex items-center rounded-xl border border-line bg-panel p-1 text-xs shadow-xs">
                  <button
                    type="button"
                    onClick={() => setActiveCategoryFilter('all')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition cursor-pointer ${
                      activeCategoryFilter === 'all'
                        ? 'bg-panel2 text-fg shadow-xs border border-line/60'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    <span>All</span>
                    <span className="rounded-full bg-panel2 px-1.5 py-0.2 text-[10px] font-mono text-muted">
                      {tabCounts.all}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveCategoryFilter('files')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition cursor-pointer ${
                      activeCategoryFilter === 'files'
                        ? 'bg-panel2 text-fg shadow-xs border border-line/60'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    <span>Files</span>
                    <span className="rounded-full bg-panel2 px-1.5 py-0.2 text-[10px] font-mono text-muted">
                      {tabCounts.files}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveCategoryFilter('tools')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition cursor-pointer ${
                      activeCategoryFilter === 'tools'
                        ? 'bg-panel2 text-fg shadow-xs border border-line/60'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    <span>Tool Outputs</span>
                    <span className="rounded-full bg-panel2 px-1.5 py-0.2 text-[10px] font-mono text-muted">
                      {tabCounts.tools}
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => setActiveCategoryFilter('chat')}
                    className={`flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition cursor-pointer ${
                      activeCategoryFilter === 'chat'
                        ? 'bg-panel2 text-fg shadow-xs border border-line/60'
                        : 'text-muted hover:text-fg'
                    }`}
                  >
                    <span>Chat & System</span>
                    <span className="rounded-full bg-panel2 px-1.5 py-0.2 text-[10px] font-mono text-muted">
                      {tabCounts.chat}
                    </span>
                  </button>
                </div>

                <button
                  type="button"
                  onClick={() => setInspectorModalOpen(false)}
                  className="rounded-xl p-1.5 text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer border border-transparent hover:border-line"
                  title="Close Inspector (Esc)"
                >
                  <X className="size-5" />
                </button>
              </div>
            </div>

            {/* Modal Body: Master-Detail Split Area */}
            <div className="flex flex-1 min-h-0 overflow-hidden bg-bg">
              {/* Left Column: Chunks Master List (36% width) */}
              <div className="w-[36%] border-r border-line bg-panel flex flex-col min-h-0">
                {/* Search / Filter Subheader */}
                <div className="p-3 border-b border-line bg-panel2/50">
                  <div className="relative flex items-center rounded-lg border border-line bg-panel px-2.5 py-1.5">
                    <Search className="size-3.5 text-muted mr-2 shrink-0" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Search chunks or files..."
                      className="w-full bg-transparent text-xs text-fg placeholder:text-muted outline-hidden"
                    />
                    {searchQuery && (
                      <button
                        type="button"
                        onClick={() => setSearchQuery('')}
                        className="text-muted hover:text-fg text-xs"
                      >
                        <X className="size-3" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Chunks Scrollable List */}
                <div className="flex-1 overflow-y-auto p-3 space-y-2">
                  {filteredChunks.length === 0 ? (
                    <div className="flex flex-col items-center justify-center p-8 text-center text-muted">
                      <FileCode className="size-8 text-muted/50 mb-2" />
                      <p className="text-xs font-semibold text-fg">No matching chunks found</p>
                      <p className="text-[11px] text-muted mt-0.5">Try selecting another filter or clear search.</p>
                    </div>
                  ) : (
                    filteredChunks.map((chunk) => {
                      const isSelected = selectedChunk?.id === chunk.id
                      return (
                        <div
                          key={chunk.id}
                          onClick={() => setSelectedChunkId(chunk.id)}
                          className={`group relative flex flex-col rounded-xl p-3 text-xs transition cursor-pointer border ${
                            isSelected
                              ? 'bg-panel2 border-brand/60 text-fg shadow-sm ring-2 ring-brand/15'
                              : 'bg-panel border-line hover:border-brand/40 text-muted hover:text-fg'
                          }`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-2 min-w-0 flex-1">
                              {/* Source Kind Icon */}
                              {chunk.sourceKind === 'workspace_file' || chunk.sourceKind === 'external_file' ? (
                                <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-amber-500/15 text-amber-500 border border-amber-500/30">
                                  <FileCode className="size-3.5" />
                                </div>
                              ) : chunk.sourceKind === 'command_output' || chunk.sourceKind === 'external_tool' ? (
                                <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-emerald-500/15 text-emerald-500 border border-emerald-500/30">
                                  <Terminal className="size-3.5" />
                                </div>
                              ) : chunk.sourceKind === 'plan_artifact' ? (
                                <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-blue-500/15 text-blue-500 border border-blue-500/30">
                                  <FileText className="size-3.5" />
                                </div>
                              ) : chunk.sourceKind === 'system' ? (
                                <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-purple-500/15 text-purple-500 border border-purple-500/30">
                                  <Layers className="size-3.5" />
                                </div>
                              ) : (
                                <div className="flex size-6 shrink-0 items-center justify-center rounded-md bg-brand/15 text-brand border border-brand/30">
                                  <MessageSquare className="size-3.5" />
                                </div>
                              )}

                              {/* Title & Metadata */}
                              <div className="min-w-0 flex-1">
                                <p className="truncate font-bold text-xs text-fg leading-tight">
                                  {chunk.title}
                                </p>
                                <span className="text-[10px] font-mono text-muted truncate block">
                                  {chunk.sourceUri}
                                </span>
                              </div>
                            </div>

                            {/* Label Badge & IFC Dot */}
                            <div className="flex items-center gap-1.5 shrink-0">
                              <span className="rounded bg-panel px-1.5 py-0.2 font-mono text-[10px] font-bold text-brand border border-line">
                                {chunk.label_id}
                              </span>
                              <LabelDot integrity={chunk.integrity} confidentiality={chunk.confidentiality} />
                              <ChevronRight className={`size-3.5 text-muted transition group-hover:translate-x-0.5 ${isSelected ? 'text-brand' : ''}`} />
                            </div>
                          </div>

                          {/* Token Bar & Percent */}
                          <div className="mt-2.5 pt-2 border-t border-line/60 flex items-center justify-between text-[11px] font-mono">
                            <span className="text-muted">
                              <strong className="text-fg font-semibold">{chunk.tokens.toLocaleString()}</strong> tokens
                            </span>
                            <span className="text-muted text-[10px]">
                              {chunk.percent}% of context
                            </span>
                          </div>

                          {/* Micro Progress Bar */}
                          <div className="mt-1 h-1 w-full overflow-hidden rounded-full bg-panel border border-line/40">
                            <div
                              className="h-full rounded-full bg-brand"
                              style={{ width: `${Math.min(chunk.percent * 2.5, 100)}%` }}
                            />
                          </div>
                        </div>
                      )
                    })
                  )}
                </div>
              </div>

              {/* Right Column: Chunk Detail Inspector (64% width) */}
              {selectedChunk ? (
                <div className="flex-1 flex flex-col justify-between overflow-y-auto p-6 bg-panel select-text">
                  <div className="space-y-6">
                    {/* Detail Header Title Row */}
                    <div className="flex items-start justify-between border-b border-line pb-4">
                      <div className="flex items-start gap-3">
                        <span className="flex size-7 items-center justify-center rounded-lg bg-brand/15 font-mono text-xs font-bold text-brand border border-brand/30 mt-0.5 shadow-xs">
                          {selectedChunk.label_id}
                        </span>
                        <div>
                          <h3 className="text-base font-bold text-fg">{selectedChunk.title}</h3>
                          <p className="text-xs text-muted font-mono mt-0.5">{selectedChunk.sourceUri}</p>
                        </div>
                      </div>

                      <div className="text-right font-mono bg-panel2 px-3 py-1.5 rounded-xl border border-line shadow-xs">
                        <span className="text-sm font-bold text-fg">
                          {selectedChunk.tokens.toLocaleString()} tokens
                        </span>
                        <p className="text-[11px] text-muted">{selectedChunk.percent}% of context window</p>
                      </div>
                    </div>

                    {/* Security & IFC Provenance Cards */}
                    <div className="space-y-2">
                      <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
                        IFC Provenance & Security Labels
                      </span>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
                        {/* IFC Integrity Card */}
                        <div className="rounded-xl border border-line bg-panel2 p-3.5 space-y-1.5 shadow-xs">
                          <div className="flex items-center justify-between">
                            <span className="text-[10px] uppercase font-bold text-muted tracking-wider">
                              IFC Integrity
                            </span>
                            <LabelDot integrity={selectedChunk.integrity} confidentiality={selectedChunk.confidentiality} />
                          </div>

                          <div className="flex items-center gap-2">
                            {selectedChunk.integrity === 'duoc_nguoi_dung_cho_phep' ? (
                              <span className="inline-flex items-center gap-1.5 rounded-md bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-1 text-xs font-semibold text-emerald-600 dark:text-emerald-400">
                                <ShieldCheck className="size-3.5" />
                                <span>User Authorized</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 rounded-md bg-amber-500/15 border border-amber-500/30 px-2.5 py-1 text-xs font-semibold text-amber-600 dark:text-amber-400">
                                <ShieldAlert className="size-3.5" />
                                <span>Untrusted Data</span>
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-muted">
                            {selectedChunk.integrity === 'duoc_nguoi_dung_cho_phep'
                              ? 'Verified user-authorized artifact with full execution permissions.'
                              : 'External/unverified content strictly blocked from directing actions.'}
                          </p>
                        </div>

                        {/* Confidentiality Card */}
                        <div className="rounded-xl border border-line bg-panel2 p-3.5 space-y-1.5 shadow-xs">
                          <span className="text-[10px] uppercase font-bold text-muted tracking-wider">
                            Confidentiality Clearance
                          </span>

                          <div className="flex items-center gap-2">
                            {selectedChunk.confidentiality === 'cong_khai' ? (
                              <span className="inline-flex items-center gap-1.5 rounded-md bg-blue-500/15 border border-blue-500/30 px-2.5 py-1 text-xs font-semibold text-brand">
                                <Globe className="size-3.5" />
                                <span>Public Domain</span>
                              </span>
                            ) : selectedChunk.confidentiality === 'noi_bo' ? (
                              <span className="inline-flex items-center gap-1.5 rounded-md bg-muted/15 border border-line px-2.5 py-1 text-xs font-semibold text-fg">
                                <Lock className="size-3.5" />
                                <span>Internal Workspace</span>
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1.5 rounded-md bg-rose-500/15 border border-rose-500/30 px-2.5 py-1 text-xs font-semibold text-rose-500">
                                <KeyRound className="size-3.5" />
                                <span>Secret (Restricted)</span>
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-muted">
                            {selectedChunk.confidentiality === 'cong_khai'
                              ? 'Exportable to external networks and third-party gateways.'
                              : 'Restricted to local workspace sandbox.'}
                          </p>
                        </div>

                        {/* Lineage & Origin Info */}
                        <div className="col-span-1 md:col-span-2 rounded-xl border border-line bg-panel2 p-3 text-xs font-mono text-muted flex flex-wrap items-center justify-between gap-2 shadow-xs">
                          <span>Origin URI: <strong className="text-fg">{selectedChunk.sourceUri}</strong></span>
                          {selectedChunk.derivedFrom.length > 0 && (
                            <span>Lineage: <strong className="text-brand font-bold">{selectedChunk.derivedFrom.join(' → ')}</strong></span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* Raw Content Viewer (Code Editor Style) */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between text-xs font-bold text-fg">
                        <div className="flex items-center gap-2">
                          <span className="uppercase tracking-wider">Raw Chunk Content</span>
                          <span className="rounded bg-panel2 px-2 py-0.5 text-[10px] font-mono text-muted border border-line">
                            {selectedChunk.lineCount} lines • {selectedChunk.content.length} bytes
                          </span>
                        </div>

                        <button
                          type="button"
                          onClick={() => handleCopyContent(selectedChunk.content)}
                          className="flex items-center gap-1 text-xs text-muted hover:text-fg transition cursor-pointer rounded-md border border-line bg-panel2 px-2.5 py-1"
                        >
                          {copied ? (
                            <>
                              <Check className="size-3.5 text-emerald-500" />
                              <span className="text-emerald-500 font-medium">Copied</span>
                            </>
                          ) : (
                            <>
                              <Copy className="size-3.5" />
                              <span>Copy Raw</span>
                            </>
                          )}
                        </button>
                      </div>

                      <div className="max-h-60 overflow-y-auto rounded-xl border border-line bg-panel2 p-4 font-mono text-xs leading-relaxed text-fg whitespace-pre-wrap select-text shadow-inner">
                        {selectedChunk.content}
                      </div>
                    </div>
                  </div>

                  {/* Footer Action: Compact this single chunk */}
                  <div className="mt-6 pt-4 border-t border-line flex items-center justify-between">
                    <span className="text-xs text-muted max-w-lg">
                      Compacting replaces full raw text with a concise high-level synthesis while preserving provenance tags.
                    </span>
                    <button
                      type="button"
                      onClick={() => handleCompactSingleChunk(selectedChunk.id)}
                      className="flex items-center gap-1.5 rounded-xl border border-line bg-panel2 px-4 py-2 text-xs font-semibold text-fg hover:border-brand hover:bg-panel transition cursor-pointer shadow-xs active:scale-98"
                    >
                      <Zap className="size-3.5 text-amber-500" />
                      <span>Compact This Chunk</span>
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex-1 flex items-center justify-center text-muted p-8 text-center">
                  <p className="text-xs">Select a context chunk on the left to inspect details.</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Manga-Style Speech Bubble (Bong bóng thoại gợi ý nén khi context cao) */}
      {showMangaBubble && (
        <div className="absolute left-6 top-full z-40 mt-2 max-w-sm rounded-xl border border-line bg-panel p-4 shadow-2xl animate-in fade-in slide-in-from-top-2 duration-200">
          {/* Header */}
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2">
              <div className="flex size-6 items-center justify-center rounded-full bg-amber-500/20 text-amber-500 border border-amber-500/30">
                <Sparkles className="size-3.5" />
              </div>
              <span className="text-xs font-bold text-fg">{t('contextUsage.thresholdTitle')}</span>
            </div>
            <button
              type="button"
              onClick={() => setDismissed(true)}
              className="rounded p-0.5 text-muted hover:text-fg transition cursor-pointer"
              title={t('contextUsage.dismiss')}
            >
              <X className="size-3.5" />
            </button>
          </div>

          {/* Bubble Body */}
          {/* Bubble Body — không còn hứa hẹn số token tiết kiệm bịa (backend
              chưa có cờ auto-compact, xem U3) */}
          <p className="mt-2 text-xs leading-relaxed text-muted">
            {t('contextUsage.thresholdBody', { percent: percent ?? 0, tokens: formatTokenCount(currentTokens) })}
          </p>

          {/* Action Buttons */}
          <div className="mt-3 flex items-center justify-end gap-2 pt-2 border-t border-line">
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setDismissed(true)}
                className="rounded px-2.5 py-1 text-xs text-muted hover:text-fg transition cursor-pointer"
              >
                {t('contextUsage.later')}
              </button>
              <button
                type="button"
                onClick={handleCompactAll}
                className="flex items-center gap-1 rounded-md bg-brand px-3 py-1 text-xs font-semibold text-brandfg shadow-xs hover:opacity-90 transition cursor-pointer"
              >
                <Zap className="size-3 fill-current" />
                <span>{t('contextUsage.compactNow')}</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
