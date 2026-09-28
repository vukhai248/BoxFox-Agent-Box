import { useEffect, useState, type KeyboardEvent } from 'react'
import {
  Lightbulb,
  Microscope,
  Palette,
  Square,
  MessageSquareQuote,
  Layers,
  Zap,
  Wrench,
  Terminal,
} from 'lucide-react'
import { useCommandsStore } from '../../store/commandsStore'

function getCommandIcon(slug: string) {
  switch (slug) {
    case 'plan':
      return <Lightbulb className="size-3.5 text-amber-400" />
    case 'research':
      return <Microscope className="size-3.5 text-blue-400" />
    case 'design':
      return <Palette className="size-3.5 text-purple-400" />
    case 'stop':
      return <Square className="size-3.5 text-rose-400" />
    case 'btw':
      return <MessageSquareQuote className="size-3.5 text-emerald-400" />
    case 'context':
      return <Layers className="size-3.5 text-indigo-400" />
    case 'compact':
      return <Zap className="size-3.5 text-amber-500" />
    case 'skills':
    case 'skill':
    case 'agents':
      return <Wrench className="size-3.5 text-teal-400" />
    default:
      return <Terminal className="size-3.5 text-muted" />
  }
}

/**
 * Lệnh còn dùng được khi chế độ Research đang bật.
 *
 * Vì sao có danh sách này: trong chế độ Research, một lệnh VAI (ví dụ `/review` — vai soát mã) sẽ
 * mở một lượt vai khác ngay giữa run, phá đúng ranh giới mà §4.7 dựng ra. Bảng 4.8 (dòng 1) yêu cầu
 * `/review` KHÔNG được nằm trong danh sách lệnh của research. Ta lọc theo danh sách trắng các lệnh
 * mode/điều khiển, thay vì đoán theo `kind` (mọi lệnh vai đều là `builtin`).
 */
export const RESEARCH_MODE_COMMANDS = new Set([
  'research',
  'stop',
  'context',
  'compact',
  'help',
  'status',
  'skills',
  'agents',
  'skill',
])

/**
 * Lệnh còn dùng được khi MỘT chế độ đang bật (P1).
 *
 * Cùng lý do với `RESEARCH_MODE_COMMANDS`: giữa một run, một lệnh VAI sẽ mở lượt vai khác và phá
 * ranh giới mà chế độ dựng ra. Vì cả hai chế độ chia một ô soạn tin, danh sách lọc là HỢP của hai
 * bộ — người dùng đang ở chế độ nào thì vẫn thấy đủ lệnh điều khiển của cả hai.
 */
// P5 — `/btw` được phép ở MỌI chế độ: nó không mở lượt vai nào và không phá ranh giới mode, nó
// chỉ hỏi thêm giữa lượt (hàng chờ steer). Vì vậy nó nằm trong danh sách lọc chung.
export const MODE_COMMANDS = new Set([...RESEARCH_MODE_COMMANDS, 'design', 'btw'])

export function useSlashCompletion(input: string, change: (value: string) => void, options?: { modeOnly?: boolean }) {
  const { commands, load } = useCommandsStore()
  const modeOnly = options?.modeOnly ?? false
  const [index, setIndex] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const query = /^\/[\w-]*$/.test(input) ? input.slice(1).toLowerCase() : null
  useEffect(() => { if (query !== null) void load() }, [query === null, load])
  useEffect(() => { setIndex(0); setDismissed(false) }, [input])
  const options2 = query !== null && !dismissed ? commands.filter(c => c.enabled && c.slug.startsWith(query) && (!modeOnly || MODE_COMMANDS.has(c.slug))).slice(0, 8) : []
  const choose = (slug: string) => { change('/' + slug + ' '); setDismissed(true) }
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return true
    if (!options2.length) return false
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); setDismissed(true); return true }
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault(); setIndex((index + (event.key === 'ArrowDown' ? 1 : options2.length - 1)) % options2.length); return true
    }
    if (event.key === 'Tab' || (event.key === 'Enter' && !event.shiftKey)) {
      event.preventDefault(); choose(options2[index % options2.length].slug); return true
    }
    return false
  }
  const popup = options2.length > 0 && (
    <div
      id="slash-completions"
      role="listbox"
      aria-label="Slash commands"
      className="absolute bottom-full -left-[1px] -right-[1px] z-50 mb-2 max-h-80 overflow-y-auto rounded-2xl border border-line bg-panel p-1.5 shadow-2xl animate-in fade-in zoom-in-95 duration-150 select-none space-y-0.5"
    >
      {options2.map((c, i) => (
        <button
          id={`slash-option-${i}`}
          key={c.slug}
          role="option"
          aria-selected={i === index}
          type="button"
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => choose(c.slug)}
          className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
            i === index
              ? 'bg-panel2 text-brand font-medium shadow-xs'
              : 'text-fg hover:bg-panel2/60'
          }`}
        >
          <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-panel2/80">
            {getCommandIcon(c.slug)}
          </div>
          <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
            <span className="font-semibold text-fg">/{c.slug}</span>
            <span className="text-[11px] text-muted truncate">{c.description}</span>
          </div>
        </button>
      ))}
    </div>
  )
  return { keyDown, popup, expanded: options2.length > 0, activeId: options2.length ? `slash-option-${index}` : undefined }
}
