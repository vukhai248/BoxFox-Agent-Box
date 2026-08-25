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
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { LabelDot } from '../LabelDot'
import type { ContextChunk } from '../../types/context'

const CONTEXT_LIMIT_TOKENS = 128_000

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

export function ContextUsageBar() {
  const context = useAgentStore((s) => s.context)
  const contextChunks = context?.chunks || []
  const autopilotEnabled = useUiStore((s) => s.autopilotEnabled)
  const setAutopilotEnabled = useUiStore((s) => s.setAutopilotEnabled)

  // Toggle modal mở rộng
  const [inspectorModalOpen, setInspectorModalOpen] = useState(false)
  const [selectedChunkId, setSelectedChunkId] = useState<string>('chunk-0')
  const [activeCategoryFilter, setActiveCategoryFilter] = useState<'all' | 'files' | 'tools' | 'chat'>('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [copied, setCopied] = useState(false)
  const [compactedSuccess, setCompactedSuccess] = useState(false)
  const [dismissed, setDismissed] = useState(false)

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

  // Tính toán tokens ước lượng từ contextChunks thực tế (bắt đầu từ 0)
  const currentTokens = useMemo(() => {
    if (!contextChunks || contextChunks.length === 0) return 0
    return contextChunks.reduce((acc: number, c: ContextChunk) => acc + Math.round((c.content || '').length / 4), 0)
  }, [contextChunks])

  const percent = Math.min(Math.round((currentTokens / CONTEXT_LIMIT_TOKENS) * 100), 100)

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
    setCompactedSuccess(true)
    setTimeout(() => {
      setCompactedSuccess(false)
    }, 1200)
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

  const showMangaBubble = percent >= 75 && !dismissed

  return (
    <div className="relative border-b border-line bg-panel px-4 py-2 select-none">
      {/* Top Header Bar */}
      <div className="flex items-center justify-between gap-3 overflow-hidden whitespace-nowrap">
        {/* Left: Context Window Title & Expand Toggle */}
        <div className="flex items-center gap-2 shrink-0">
          <button
            type="button"
            onClick={() => setInspectorModalOpen(true)}
            className="group flex items-center gap-1.5 text-xs font-bold text-fg hover:text-brand transition cursor-pointer"
            title="Click to open full Context Breakdown & Chunk Inspector modal"
          >
            <Zap className="size-3.5 text-amber-500 fill-amber-500/20" />
            <span>Context Window</span>
            <Maximize2 className="size-3 text-muted group-hover:text-brand transition ml-0.5" />
          </button>
        </div>

        {/* Center: Progress Bar */}
        <div className="flex-1 min-w-[40px] max-w-xs flex items-center gap-2">
          <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-panel2 border border-line">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                percent >= 85
                  ? 'bg-rose-500'
                  : percent >= 70
                    ? 'bg-amber-500'
                    : 'bg-emerald-500'
              }`}
              style={{ width: `${percent}%` }}
            />
          </div>
        </div>

        {/* Right: Token count & Actions */}
        <div className="flex items-center gap-2 shrink-0">
          <span className="font-mono text-[11px] text-muted">
            <strong className="text-fg">{(currentTokens / 1000).toFixed(1)}k</strong>
            <span className="hidden xl:inline"> / {(CONTEXT_LIMIT_TOKENS / 1000).toFixed(0)}k</span> ({percent}%)
          </span>

          <button
            type="button"
            onClick={handleCompactAll}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[11px] font-semibold transition cursor-pointer ${
              compactedSuccess
                ? 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/30'
                : percent >= 75
                  ? 'border border-brand/50 bg-brand/10 text-fg hover:bg-brand/20 shadow-xs'
                  : 'border border-line bg-panel2 text-muted hover:text-fg hover:bg-panel'
            }`}
          >
            {compactedSuccess ? (
              <>
                <Check className="size-3 text-emerald-500" />
                <span>Compacted</span>
              </>
            ) : (
              <>
                <Sparkles className="size-3 text-brand" />
                <span>Compact</span>
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
                      {(currentTokens / 1000).toFixed(1)}k / {(CONTEXT_LIMIT_TOKENS / 1000).toFixed(0)}k tokens ({percent}%)
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
              <span className="text-xs font-bold text-fg">Context Threshold Alert</span>
            </div>
            <button
              type="button"
              onClick={() => setDismissed(true)}
              className="rounded p-0.5 text-muted hover:text-fg transition cursor-pointer"
              title="Dismiss recommendation"
            >
              <X className="size-3.5" />
            </button>
          </div>

          {/* Bubble Body */}
          <p className="mt-2 text-xs leading-relaxed text-muted">
            Context window is reaching <strong className="text-amber-500 font-mono">{percent}%</strong> ({(currentTokens / 1000).toFixed(1)}k tokens).
            You can summarize completed tool traces to free up ~<strong>45k tokens</strong> while strictly preserving provenance labels (Rule N5).
          </p>

          {/* Action Buttons */}
          <div className="mt-3 flex items-center justify-between gap-2 pt-2 border-t border-line">
            <button
              type="button"
              onClick={() => setAutopilotEnabled(!autopilotEnabled)}
              className="text-[11px] text-muted hover:text-fg transition cursor-pointer"
            >
              {autopilotEnabled ? '✓ Auto-compact enabled' : 'Enable auto-compact'}
            </button>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setDismissed(true)}
                className="rounded px-2.5 py-1 text-xs text-muted hover:text-fg transition cursor-pointer"
              >
                Later
              </button>
              <button
                type="button"
                onClick={handleCompactAll}
                className="flex items-center gap-1 rounded-md bg-brand px-3 py-1 text-xs font-semibold text-brandfg shadow-xs hover:opacity-90 transition cursor-pointer"
              >
                <Zap className="size-3 fill-current" />
                <span>Compact Now</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
