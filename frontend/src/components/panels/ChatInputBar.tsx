import React, { useState, useRef, useEffect } from 'react'
import {
  Zap,
  Mic,
  ArrowUp,
  Square,
  Paperclip,
  X,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { HarnessModelPicker } from '../chat/HarnessModelPicker'
import { RepoPicker } from '../chat/RepoPicker'
import { AttachmentPicker, type AttachedFile } from '../chat/AttachmentPicker'
import { ShortcutsPopover } from '../chat/ShortcutsPopover'

export function ChatInputBar() {
  const [input, setInput] = useState('')
  const [attachments, setAttachments] = useState<AttachedFile[]>([])
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const sendCommand = useAgentStore((s) => s.sendCommand)
  const isBusy = useAgentStore((s) => s.isBusy)
  const autopilotEnabled = useUiStore((s) => s.autopilotEnabled)
  const setAutopilotEnabled = useUiStore((s) => s.setAutopilotEnabled)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 140)}px`
    }
  }, [input])

  const handleSend = () => {
    if (!input.trim() && attachments.length === 0) return
    const textToSend = attachments.length > 0
      ? `${input.trim()}\n\n[Attached Files: ${attachments.map((a) => a.name).join(', ')}]`
      : input.trim()

    sendCommand({
      type: 'user_message',
      text: textToSend,
    })
    setInput('')
    setAttachments([])
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
    <div className="border-t border-line bg-panel p-3 select-none">
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

        <textarea
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type your message..."
          className="w-full resize-none bg-transparent px-1.5 py-1 text-xs leading-relaxed text-fg placeholder:text-muted/60 outline-hidden select-text"
        />

        {/* Toolbar below input */}
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2 pt-1.5 border-t border-line/40">
          <div className="flex items-center gap-1.5">
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
              className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium text-muted transition hover:bg-panel hover:text-fg cursor-pointer"
            >
              <Zap className="size-3 text-amber-400" />
              <span>Quick ask</span>
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
              title="Toggle automatic execution"
            >
              <Zap className="size-3" />
              <span>Autopilot</span>
              <span
                className={`size-1.5 rounded-full ${
                  autopilotEnabled ? 'bg-brand shadow-xs' : 'bg-muted/40'
                }`}
              />
            </button>
          </div>

          <div className="flex items-center gap-1.5">
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
                disabled={!input.trim() && attachments.length === 0}
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
