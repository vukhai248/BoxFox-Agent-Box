/**
 * Bảng hiển thị Phím tắt & Lệnh Slash (ShortcutsPopover).
 * - Keyboard Shortcuts: phím tắt điều hướng nhanh (Ctrl+K, Ctrl+Shift+L, Shift+Tab...)
 * - Slash Commands: các lệnh /goal, /btw, /plan, /compact, /learn, /clear
 * - Tương thích popover mở từ thanh Chat [ ⌨ ] và từ Sidebar footer.
 * 
 * HƯỚNG DẪN MỞ RỘNG:
 * - Khi thêm phím tắt toàn cục mới: Đăng ký listener tại `App.tsx` / `useKeybindings` hook và bổ sung mô tả vào mảng `SHORTCUTS`.
 * - Khi thêm lệnh Slash mới: Bổ sung định nghĩa vào mảng `SLASH_COMMANDS` và xử lý parser tại `ChatInputBar.tsx`.
 */
import { useState, useRef, useEffect } from 'react'
import { Command, Keyboard, X, Terminal } from 'lucide-react'
import { useUiStore } from '../../store/uiStore'

export interface ShortcutItem {
  keys: string[]
  label: string
  /** true = tính năng đang mock, chưa có handler thật (hiển thị "(mock)"). */
  mock?: boolean
  /** id gắn với hành động thật đã có handler (vd 'search'). */
  id?: string
}

export interface SlashCommandItem {
  command: string
  description: string
}

const SHORTCUTS: ShortcutItem[] = [
  { keys: ['↑', '↓'], label: 'Browse message history', mock: true },
  { keys: ['Ctrl', 'K'], label: 'Search sessions', id: 'search' },
  { keys: ['Ctrl', 'Shift', 'L'], label: 'Clear input', mock: true },
  { keys: ['Ctrl', 'Shift', 'O'], label: 'Toggle diff panel', mock: true },
  { keys: ['Ctrl', 'Shift', 'I'], label: 'Toggle IDE / Code Studio', mock: true },
  { keys: ['Ctrl', 'Shift', 'X'], label: 'Toggle terminal', mock: true },
  { keys: ['Ctrl', 'C'], label: 'Cancel session (when active)', mock: true },
  { keys: ['Shift', 'Tab'], label: 'Toggle Autopilot', mock: true },
]

const SLASH_COMMANDS: SlashCommandItem[] = [
  { command: '/goal', description: 'Run long-running autonomous task with rigorous completion criteria' },
  { command: '/btw', description: 'Quick side note to agent without interrupting active execution flow' },
  { command: '/plan', description: 'Generate comprehensive architectural implementation blueprint' },
  { command: '/compact', description: 'Manually trigger instant context window memory compaction' },
  { command: '/learn', description: 'Save custom guidelines & preferences to persistent system memory' },
  { command: '/clear', description: 'Clear current conversation stream and reset focus' },
]

export function ShortcutsPopover({
  variant = 'toolbar',
  customOpen,
  onCustomToggle,
}: {
  variant?: 'toolbar' | 'sidebar'
  customOpen?: boolean
  onCustomToggle?: (open: boolean) => void
}) {
  const [internalOpen, setInternalOpen] = useState(false)
  const [activeTab, setActiveTab] = useState<'shortcuts' | 'commands'>('shortcuts')
  const popoverRef = useRef<HTMLDivElement>(null)
  const openSearch = useUiStore((s) => s.openSearch)

  // Kích hoạt hành động tương ứng với một dòng phím tắt (đóng popover trước).
  const activateShortcut = (item: ShortcutItem) => {
    setOpen(false)
    if (item.id === 'search') openSearch()
  }

  const isControlled = customOpen !== undefined
  const open = isControlled ? customOpen : internalOpen
  const setOpen = (val: boolean) => {
    if (isControlled && onCustomToggle) {
      onCustomToggle(val)
    } else {
      setInternalOpen(val)
    }
  }

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
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

  return (
    <div className="relative inline-block" ref={popoverRef}>
      {/* Trigger Button based on variant */}
      {variant === 'toolbar' ? (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={`flex size-6 items-center justify-center rounded transition cursor-pointer select-none ${
            open
              ? 'bg-brand/15 text-brand shadow-xs'
              : 'text-muted hover:bg-panel hover:text-fg'
          }`}
          title="Keyboard shortcuts & Slash commands"
        >
          <Keyboard className="size-3.5" />
        </button>
      ) : (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs transition cursor-pointer ${
            open
              ? 'bg-panel2 text-fg font-medium'
              : 'text-muted hover:bg-panel2 hover:text-fg'
          }`}
        >
          <Keyboard className="size-3.5" />
          <span>Shortcuts & Commands</span>
        </button>
      )}

      {/* Popover Card */}
      {open && (
        <div
          className={`absolute z-50 rounded-2xl border border-line bg-panel p-3.5 shadow-2xl animate-in fade-in zoom-in-95 duration-150 select-none ${
            variant === 'toolbar'
              ? 'bottom-full left-0 mb-2 w-80 sm:w-96'
              : 'bottom-0 left-full ml-2 w-84 sm:w-96'
          }`}
        >
          {/* Header & Tabs */}
          <div className="flex items-center justify-between border-b border-line pb-2.5 mb-3">
            <div className="flex items-center gap-1.5 bg-panel2 p-0.5 rounded-lg border border-line">
              <button
                type="button"
                onClick={() => setActiveTab('shortcuts')}
                className={`flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-md transition cursor-pointer ${
                  activeTab === 'shortcuts'
                    ? 'bg-panel text-fg shadow-2xs'
                    : 'text-muted hover:text-fg'
                }`}
              >
                <Keyboard className="size-3" />
                <span>Shortcuts</span>
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('commands')}
                className={`flex items-center gap-1 px-2.5 py-1 text-[11px] font-semibold rounded-md transition cursor-pointer ${
                  activeTab === 'commands'
                    ? 'bg-panel text-fg shadow-2xs'
                    : 'text-muted hover:text-fg'
                }`}
              >
                <Command className="size-3" />
                <span>Slash Commands</span>
              </button>
            </div>

            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-muted hover:text-fg transition p-1 rounded-md hover:bg-panel2 cursor-pointer"
            >
              <X className="size-3.5" />
            </button>
          </div>

          {/* Tab 1: Keyboard shortcuts */}
          {activeTab === 'shortcuts' && (
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              <span className="text-[11px] font-semibold text-muted px-1">Keyboard shortcuts</span>
              <div className="space-y-1.5 pt-1">
                {SHORTCUTS.map((item, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => activateShortcut(item)}
                    className="flex w-full items-center justify-between rounded-lg px-2 py-1 text-xs hover:bg-panel2/50 transition cursor-pointer"
                  >
                    <div className="flex items-center gap-1 shrink-0">
                      {item.keys.map((k, ki) => (
                        <kbd
                          key={ki}
                          className="rounded-md border border-line bg-panel2 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-fg shadow-2xs"
                        >
                          {k}
                        </kbd>
                      ))}
                    </div>
                    <span className="text-[11px] text-muted text-right ml-3 truncate">
                      {item.label}
                      {item.mock ? ' (mock)' : ''}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Tab 2: Slash Commands */}
          {activeTab === 'commands' && (
            <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
              <span className="text-[11px] font-semibold text-muted px-1">Agent Slash commands</span>
              <div className="space-y-1 pt-1">
                {SLASH_COMMANDS.map((item, i) => (
                  <div
                    key={i}
                    className="rounded-xl border border-line/60 bg-panel2/40 p-2 text-xs space-y-0.5 hover:border-brand/40 hover:bg-panel2/80 transition"
                  >
                    <div className="flex items-center gap-1.5 font-mono font-bold text-brand text-[12px]">
                      <Terminal className="size-3" />
                      <span>{item.command}</span>
                    </div>
                    <p className="text-[11px] text-muted leading-relaxed">{item.description}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
