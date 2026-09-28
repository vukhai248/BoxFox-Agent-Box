import { useState, useRef, useEffect } from 'react'
import { createPortal } from 'react-dom'
import {
  MoreVertical,
  GitFork,
  Zap,
  ChevronRight,
} from 'lucide-react'
import { RepoPickerView } from './RepoPicker'

export interface ChatMoreOptionsPickerProps {
  autopilotEnabled: boolean
  onToggleAutopilot: () => void
  selectedRepoIds: string[]
  onToggleRepo: (id: string) => void
  onOpenChange?: (open: boolean) => void
}

const PANEL_WIDTH = 340
const PANEL_HEIGHT = 220

export function ChatMoreOptionsPicker({
  autopilotEnabled,
  onToggleAutopilot,
  selectedRepoIds,
  onToggleRepo,
  onOpenChange,
}: ChatMoreOptionsPickerProps) {
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<'menu' | 'repos'>('menu')
  const [panelPosition, setPanelPosition] = useState<{ left: number; bottom: number } | null>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const handleOpen = (next: boolean) => {
    setOpen(next)
    onOpenChange?.(next)
    if (!next) {
      setView('menu')
    }
  }

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      onOpenChange?.(false)
    }
  }, [onOpenChange])

  // Click outside & Escape key
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (triggerRef.current?.contains(target)) return
      if (panelRef.current?.contains(target)) return
      handleOpen(false)
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') handleOpen(false)
    }

    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      document.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  // Căn chỉnh vị trí portal theo trigger
  useEffect(() => {
    if (!open) return

    const updatePosition = () => {
      const rect = triggerRef.current?.getBoundingClientRect()
      if (!rect) return
      const left = Math.max(8, Math.min(rect.left - PANEL_WIDTH / 2 + rect.width / 2, window.innerWidth - PANEL_WIDTH - 8))
      const maxBottom = Math.max(8, window.innerHeight - PANEL_HEIGHT - 8)
      const bottom = Math.min(Math.max(8, window.innerHeight - rect.top + 8), maxBottom)
      setPanelPosition({ left, bottom })
    }

    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open])

  const selectedCount = selectedRepoIds.length

  return (
    <div className="relative inline-flex items-center">
      {/* Trigger Button [ ⋮ ] */}
      <button
        ref={triggerRef}
        type="button"
        data-testid="chat-more-options-btn"
        onClick={(e) => {
          e.stopPropagation()
          handleOpen(!open)
        }}
        className={`flex size-7 items-center justify-center rounded-lg text-muted transition hover:bg-panel hover:text-fg cursor-pointer select-none ${
          open ? 'bg-panel text-fg border border-line shadow-2xs' : 'border border-transparent'
        }`}
        title="More options"
        aria-label="More options"
        aria-expanded={open}
      >
        <MoreVertical className="size-3.5" />
      </button>

      {/* Popover via Portal */}
      {open &&
        panelPosition &&
        createPortal(
          <div
            ref={panelRef}
            data-testid="chat-more-menu"
            data-portal-menu="true"
            className="fixed z-50 w-80 sm:w-[340px] rounded-2xl border border-line bg-panel p-2 shadow-2xl animate-in fade-in zoom-in-95 duration-150 select-none text-fg"
            style={{ left: panelPosition.left, bottom: panelPosition.bottom }}
          >
            {view === 'menu' ? (
              <div className="space-y-1">
                {/* Mục 1: Repositories */}
                <button
                  type="button"
                  data-testid="more-menu-repos-item"
                  onClick={() => setView('repos')}
                  className="flex w-full items-center justify-between gap-3 rounded-xl p-2 text-left transition hover:bg-panel2 cursor-pointer group"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-line bg-panel2 text-muted group-hover:text-fg transition">
                      <GitFork className="size-4 text-brand" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-fg">Repositories</div>
                      <div className="text-[11px] text-muted truncate">Choose project context</div>
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-1 text-xs text-muted">
                    <span className="font-mono text-[11px]">{selectedCount} selected</span>
                    <ChevronRight className="size-3.5" />
                  </div>
                </button>

                {/* Mục 2: Autopilot */}
                <div
                  data-testid="more-menu-autopilot-item"
                  onClick={onToggleAutopilot}
                  className="flex w-full items-center justify-between gap-3 rounded-xl p-2 text-left transition hover:bg-panel2/70 cursor-pointer group"
                >
                  <div className="flex items-center gap-2.5 min-w-0">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-line bg-panel2 text-muted">
                      <Zap className={`size-4 transition ${autopilotEnabled ? 'text-amber-400 fill-amber-400' : 'text-muted'}`} />
                    </div>
                    <div className="min-w-0">
                      <div className="text-xs font-semibold text-fg">Autopilot</div>
                      <div className="text-[11px] text-muted truncate">Auto approve plans and choices</div>
                    </div>
                  </div>
                  {/* Modern iOS / Material style toggle switch */}
                  <button
                    type="button"
                    role="switch"
                    data-testid="more-menu-autopilot-switch"
                    aria-checked={autopilotEnabled}
                    onClick={(e) => {
                      e.stopPropagation()
                      onToggleAutopilot()
                    }}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-hidden ${
                      autopilotEnabled ? 'bg-blue-600' : 'bg-zinc-600/50'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out ${
                        autopilotEnabled ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
              </div>
            ) : (
              /* View danh sách repositories */
              <div className="p-1">
                <RepoPickerView
                  selectedRepoIds={selectedRepoIds}
                  onToggleRepo={onToggleRepo}
                  onBack={() => setView('menu')}
                />
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  )
}
