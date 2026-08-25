/**
 * Bộ chọn nhanh Harness & Model (Quick Picker Popover) tại Chat Input Bar.
 * - Tab chuyển đổi ở đầu: [ 🧩 Harnesses | 🤖 Single Models ]
 * - Ô tìm kiếm nhanh (Search harnesses or models...)
 * - Danh sách item với dấu tích checkmark xanh cho cấu hình đang chọn
 * - Footer: [⚙️ Manage Harnesses] và [+ Create Harness]
 */
import { useState, useRef, useEffect, useMemo } from 'react'
import {
  Bot,
  Cpu,
  Search,
  Check,
  Settings,
  Plus,
  ChevronDown,
  X,
} from 'lucide-react'
import { useHarnessStore, AVAILABLE_MODELS } from '../../store/harnessStore'
import { useUiStore } from '../../store/uiStore'

export function HarnessModelPicker() {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [activeTab, setActiveTab] = useState<'harness' | 'model'>('harness')
  const popoverRef = useRef<HTMLDivElement>(null)

  const harnesses = useHarnessStore((s) => s.harnesses)
  const activeHarnessId = useHarnessStore((s) => s.activeHarnessId)
  const activeModelId = useHarnessStore((s) => s.activeModelId)
  const activeType = useHarnessStore((s) => s.activeType)
  const setActiveHarness = useHarnessStore((s) => s.setActiveHarness)
  const setActiveModel = useHarnessStore((s) => s.setActiveModel)
  const openSettings = useUiStore((s) => s.openSettings)

  // Current active entity
  const currentHarness = useMemo(
    () => harnesses.find((h) => h.id === activeHarnessId) ?? harnesses[0],
    [harnesses, activeHarnessId],
  )
  const currentModel = useMemo(
    () => AVAILABLE_MODELS.find((m) => m.id === activeModelId) ?? AVAILABLE_MODELS[0],
    [activeModelId],
  )

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

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [open])

  return (
    <div className="relative inline-block" ref={popoverRef}>
      {/* Trigger Button in Chat Input Toolbar — Compact Style */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium transition cursor-pointer ${
          open
            ? 'border-zinc-500 bg-panel text-fg shadow-xs'
            : 'border-line bg-panel/80 text-muted hover:border-zinc-600 hover:text-fg'
        }`}
        title={
          activeType === 'harness'
            ? `Harness: ${currentHarness?.name} (${subagentCount} sub-agents)`
            : `Model: ${currentModel?.name} (${currentModel?.provider})`
        }
      >
        {activeType === 'harness' ? (
          <>
            <Bot className="size-3.5 text-brand" />
            <span className="font-semibold text-fg">{subagentCount}</span>
          </>
        ) : (
          <>
            <Cpu className="size-3.5 text-amber-400" />
            <span className="font-semibold text-fg">
              {currentModel?.name.includes('Claude')
                ? 'Sonnet'
                : currentModel?.name.includes('DeepSeek')
                  ? 'DeepSeek'
                  : currentModel?.name.includes('Gemini')
                    ? 'Gemini'
                    : currentModel?.name.split(' ')[0]}
            </span>
          </>
        )}
        <ChevronDown className={`size-2.5 text-muted transition ${open ? 'rotate-180' : ''}`} />
      </button>

      {/* Floating Popover (Anchored above the chat bar) */}
      {open && (
        <div className="absolute bottom-full left-0 z-50 mb-2 w-80 overflow-hidden rounded-xl border border-line bg-[#111318] shadow-2xl animate-in fade-in zoom-in-95 duration-150 select-none">
          {/* Search Header */}
          <div className="border-b border-line/70 p-2 bg-[#151820]">
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
                className={`flex items-center justify-center gap-1.5 rounded-md py-1 text-[11px] font-medium transition cursor-pointer ${
                  activeTab === 'harness'
                    ? 'bg-[#1e222d] text-white shadow-xs font-semibold'
                    : 'text-muted hover:text-fg'
                }`}
              >
                <Bot className="size-3 text-brand" />
                <span>Harnesses</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('model')}
                className={`flex items-center justify-center gap-1.5 rounded-md py-1 text-[11px] font-medium transition cursor-pointer ${
                  activeTab === 'model'
                    ? 'bg-[#1e222d] text-white shadow-xs font-semibold'
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
                      className={`flex w-full items-start justify-between rounded-lg p-2 text-left transition cursor-pointer ${
                        isSelected
                          ? 'bg-[#1c212c] text-white'
                          : 'hover:bg-panel2/60 text-zinc-300'
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
              /* Single Models List */
              filteredModels.length === 0 ? (
                <div className="p-6 text-center text-xs text-muted">No models found</div>
              ) : (
                filteredModels.map((model) => {
                  const isSelected = activeType === 'model' && activeModelId === model.id
                  return (
                    <button
                      key={model.id}
                      type="button"
                      onClick={() => {
                        setActiveModel(model.id)
                        setOpen(false)
                      }}
                      className={`flex w-full items-center justify-between rounded-lg p-2 text-left transition cursor-pointer ${
                        isSelected
                          ? 'bg-[#1c212c] text-white'
                          : 'hover:bg-panel2/60 text-zinc-300'
                      }`}
                    >
                      <div className="min-w-0 flex-1 space-y-0.5">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold text-xs text-fg">{model.name}</span>
                          <span className="rounded bg-panel px-1 py-0.2 text-[9px] font-mono text-muted border border-line">
                            {model.provider}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-[10px] text-zinc-500 font-mono">
                          <span>Context: {model.contextWindow}</span>
                          {model.supportsImages && <span>· Vision ready</span>}
                        </div>
                      </div>

                      {isSelected && (
                        <Check className="size-4 shrink-0 text-brand ml-2" />
                      )}
                    </button>
                  )
                })
              )
            )}
          </div>

          {/* Footer Actions (Manage & Create) */}
          <div className="flex items-center justify-between border-t border-line/70 bg-[#141720] px-3 py-2 text-xs">
            <button
              type="button"
              onClick={() => {
                openSettings('harness')
                setOpen(false)
              }}
              className="flex items-center gap-1.5 text-zinc-400 hover:text-white transition cursor-pointer"
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
      )}
    </div>
  )
}
