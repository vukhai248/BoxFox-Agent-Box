import React, { useState, useRef, useEffect } from 'react'
import {
  Zap,
  Mic,
  ArrowUp,
  Square,
  Paperclip,
  Crosshair,
  X,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { useComposerStore } from '../../store/composerStore'
import { useT } from '../../i18n/context'
import { useCompactComposer } from '../../hooks/useCompactComposer'
import { HarnessModelPicker } from '../chat/HarnessModelPicker'
import { RepoPicker } from '../chat/RepoPicker'
import { AttachmentPicker, type AttachedFile } from '../chat/AttachmentPicker'
import { ShortcutsPopover } from '../chat/ShortcutsPopover'
import { LabelDot } from '../LabelDot'
import { inspectChipLabel } from '../../lib/inspect/format'

// Ở chế độ `live` (`VITE_TRANSPORT=live`) chưa có handler backend nào tiêu
// thụ `elements` (xem `types/transport.ts` chú thích trên `user_message`) —
// cùng cách đọc biến môi trường với `lib/vnc/config.ts:resolveScreenSource`.
function isLiveTransport(): boolean {
  return (import.meta.env.VITE_TRANSPORT ?? '').trim().toLowerCase() === 'live'
}

export function ChatInputBar() {
  const t = useT()
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<AttachedFile[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const compact = useCompactComposer(barRef)
  const sendCommand = useAgentStore((s) => s.sendCommand)
  const isBusy = useAgentStore((s) => s.isBusy)
  const autopilotEnabled = useUiStore((s) => s.autopilotEnabled)
  const setAutopilotEnabled = useUiStore((s) => s.setAutopilotEnabled)
  const pendingElements = useComposerStore((s) => s.pendingElements)
  const removePendingElement = useComposerStore((s) => s.removePendingElement)
  const clearPendingElements = useComposerStore((s) => s.clearPendingElements)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 140)}px`
    }
  }, [input])

  const handleSend = () => {
    if (!input.trim() && attachments.length === 0 && pendingElements.length === 0) return
    const textToSend = attachments.length > 0
      ? `${input.trim()}\n\n[Attached Files: ${attachments.map((a) => a.name).join(', ')}]`
      : input.trim()

    // `elements` đi qua trường CÓ CẤU TRÚC của `ClientCommand`, KHÔNG được
    // nối vào `text` như file đính kèm ở trên — quyết định D3
    // (`v1-element-selector.md` §4.2): phần tử phải đi tới agent kèm nhãn
    // Integrity/Confidentiality của nó, nối chuỗi sẽ làm mất nhãn đó.
    sendCommand({
      type: 'user_message',
      text: textToSend,
      ...(pendingElements.length > 0 ? { elements: pendingElements } : {}),
    })
    setInput('')
    setAttachments([])
    clearPendingElements()
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleInterrupt = () => {
    sendCommand({
      type: 'interrupt',
      level: 'tam_dung',
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div ref={barRef} className="border-t border-line bg-panel p-3 select-none">
      <div className="relative rounded-xl border border-line bg-panel2/70 p-2.5 shadow-xs transition-all focus-within:border-zinc-500 focus-within:ring-1 focus-within:ring-zinc-600/40">
        {/* Attached files chips */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5 px-1">
            {attachments.map((file) => (
              <div
                key={file.id}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2 py-1 text-[11px] text-fg shadow-2xs"
              >
                {file.source === 'drive' ? (
                  <svg className="size-3 shrink-0" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
                    <path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
                    <path d="M43.65 25 29.9 1.2c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44A8.9 8.9 0 0 0 0 53h27.5z" fill="#00ac47"/>
                    <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8l5.85 10.15z" fill="#ea4335"/>
                    <path d="M43.65 25 57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>
                    <path d="M59.8 53h27.5c0-1.55-.4-3.1-1.2-4.5L72.35 22.75c-.8-1.4-1.95-2.5-3.3-3.3L55.3 43.25z" fill="#2684fc"/>
                    <path d="m27.5 53 13.75 23.8c1.35-.8 2.5-1.9 3.3-3.3l20.75-35.95c.8-1.4 1.2-2.95 1.2-4.55H27.5z" fill="#ffba00"/>
                  </svg>
                ) : (
                  <Paperclip className="size-3 text-muted shrink-0" />
                )}
                <span className="truncate max-w-[140px] font-mono">{file.name}</span>
                <button
                  type="button"
                  onClick={() => setAttachments((prev) => prev.filter((a) => a.id !== file.id))}
                  className="text-muted hover:text-rose-500 transition ml-0.5 cursor-pointer"
                  title="Remove attachment"
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Element context chips (khung ④ Element Selector, plan §8-F12) —
            viền/nền trung tính giống chip đính kèm ở trên; màu vàng cảnh báo
            chỉ nằm ở chấm LabelDot, KHÔNG tô nền cả chip (mockup §12.6). */}
        {pendingElements.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5 px-1">
            {pendingElements.map((el) => (
              <div
                key={el.id}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2 py-1 text-[11px] text-fg shadow-2xs"
              >
                <Crosshair className="size-3 text-muted shrink-0" />
                <span className="truncate max-w-[160px] font-mono">{inspectChipLabel(el.result, t('screen.inspector.chipDesktopFallback'))}</span>
                <LabelDot integrity="khong_tin_duoc" />
                <button
                  type="button"
                  onClick={() => removePendingElement(el.id)}
                  className="text-muted hover:text-rose-500 transition ml-0.5 cursor-pointer"
                  title={t('composer.removeElementContext')}
                  aria-label={t('composer.removeElementContext')}
                >
                  <X className="size-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Cảnh báo: hợp đồng truyền tải đã có ở chế độ live nhưng chưa có
            handler backend nào tiêu thụ `elements` — không được âm thầm
            nuốt dữ liệu, phải nói thẳng với người dùng (plan §8-F7/F12). */}
        {pendingElements.length > 0 && isLiveTransport() && (
          <p className="mb-2 px-1 text-[11px] text-amber-500">{t('composer.elementContextLiveUnsupported')}</p>
        )}

        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={t(compact ? 'composer.placeholderShort' : 'composer.placeholder')}
          className="w-full resize-none bg-transparent px-1.5 py-1 text-xs leading-relaxed text-fg placeholder:text-muted/60 outline-hidden select-text"
        />

        {/* Toolbar below input — bỏ flex-wrap để Mic/Send không bao giờ rớt
            xuống dòng 2 khi cột chat hẹp; nhóm trái co lại (min-w-0 +
            overflow-hidden), nhóm phải giữ nguyên kích thước (shrink-0). */}
        <div className="mt-2 flex items-center justify-between gap-2 pt-1.5 border-t border-line/40">
          <div className="flex min-w-0 items-center gap-1.5 overflow-hidden">
            {/* Attachment Button [+] with Popover */}
            <AttachmentPicker onAttach={(file) => setAttachments((prev) => [...prev, file])} />

            {/* Repo Selector Popover */}
            <RepoPicker />

            {/* Shortcuts Popover [ ⌨ ] */}
            <ShortcutsPopover variant="toolbar" />

            {/* Quick Harness & Model Picker Popover */}
            <HarnessModelPicker />

            {/* Quick Ask */}
            <button
              type="button"
              title={t('composer.quickAsk')}
              aria-label={t('composer.quickAsk')}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium text-muted transition hover:bg-panel hover:text-fg cursor-pointer"
            >
              <Zap className="size-3 text-amber-400" />
              {!compact && <span>{t('composer.quickAsk')}</span>}
            </button>

            {/* Autopilot Toggle */}
            <button
              type="button"
              onClick={() => setAutopilotEnabled(!autopilotEnabled)}
              className={`flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium transition cursor-pointer ${
                autopilotEnabled
                  ? 'bg-panel2 text-fg border border-line'
                  : 'text-muted hover:bg-panel hover:text-fg border border-transparent'
              }`}
              title={t('composer.autopilotHint')}
              aria-label={t('composer.autopilot')}
              aria-pressed={autopilotEnabled}
            >
              <Zap className="size-3" />
              {!compact && <span>{t('composer.autopilot')}</span>}
              {/* Chấm trạng thái giữ inline ở cả hai chế độ — phải luôn nhìn thấy bật/tắt */}
              <span
                className={`size-1.5 rounded-full ${
                  autopilotEnabled ? 'bg-brand shadow-xs' : 'bg-muted/40'
                }`}
              />
            </button>
          </div>

          <div className="flex shrink-0 items-center gap-1.5">
            {/* Voice Input Mic */}
            <button
              type="button"
              className="flex size-7 items-center justify-center rounded-lg text-muted transition hover:bg-panel hover:text-fg cursor-pointer"
              title="Voice dictation"
            >
              <Mic className="size-3.5" />
            </button>

            {/* Dynamic Send / Stop Button in the exact same spot */}
            {isBusy ? (
              <button
                type="button"
                onClick={handleInterrupt}
                className="flex size-7 items-center justify-center rounded-lg bg-rose-500 text-white shadow-xs transition hover:bg-rose-600 active:scale-95 cursor-pointer animate-in fade-in zoom-in-90 duration-150"
                title="Stop / Interrupt agent action (Esc)"
              >
                <Square className="size-3 fill-current" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSend}
                disabled={!input.trim() && attachments.length === 0 && pendingElements.length === 0}
                className="flex size-7 items-center justify-center rounded-lg bg-zinc-100 text-zinc-900 shadow-xs transition hover:bg-white disabled:opacity-30 disabled:hover:bg-zinc-100 cursor-pointer animate-in fade-in zoom-in-90 duration-150"
                title="Send prompt (Enter)"
              >
                <ArrowUp className="size-3.5" />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
