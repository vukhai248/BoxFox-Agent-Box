import { useEffect, useState, type KeyboardEvent } from 'react'
import { useCommandsStore } from '../../store/commandsStore'

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

export function useSlashCompletion(input: string, change: (value: string) => void, options?: { modeOnly?: boolean }) {
  const { commands, load } = useCommandsStore()
  const modeOnly = options?.modeOnly ?? false
  const [index, setIndex] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const query = /^\/[\w-]*$/.test(input) ? input.slice(1).toLowerCase() : null
  useEffect(() => { if (query !== null) void load() }, [query === null, load])
  useEffect(() => { setIndex(0); setDismissed(false) }, [input])
  const options2 = query !== null && !dismissed ? commands.filter(c => c.enabled && c.slug.startsWith(query) && (!modeOnly || RESEARCH_MODE_COMMANDS.has(c.slug))).slice(0, 8) : []
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
  const popup = options2.length > 0 && <div id="slash-completions" role="listbox" aria-label="Slash commands" className="absolute bottom-full left-0 right-0 z-50 mb-2 max-h-64 overflow-auto rounded-lg border border-line bg-panel p-1 shadow-xl">
    {options2.map((c, i) => <button id={`slash-option-${i}`} key={c.slug} role="option" aria-selected={i === index} type="button" onMouseDown={e => e.preventDefault()} onClick={() => choose(c.slug)} className={`block w-full rounded p-2 text-left text-xs ${i === index ? 'bg-panel2 text-brand' : 'text-fg'}`}>
      <span className="font-semibold">/{c.slug}</span><span className="ml-2 text-muted">{c.description}</span>
    </button>)}
  </div>
  return { keyDown, popup, expanded: options2.length > 0, activeId: options2.length ? `slash-option-${index}` : undefined }
}
