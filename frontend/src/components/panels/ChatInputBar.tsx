import React, { useState, useRef, useEffect } from 'react'
import {
  Zap,
  Mic,
  ArrowUp,
  Square,
  Paperclip,
  Crosshair,
  Loader2,
  X,
  Check,
  FolderOpen,
  Clock,
  Info,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { readingColumnClass } from '../../lib/readingColumn'
import { useComposerStore } from '../../store/composerStore'
import { useT } from '../../i18n/context'
import { useCompactComposer } from '../../hooks/useCompactComposer'
import { HarnessModelPicker, type RouterSingleModel } from '../chat/HarnessModelPicker'
import { RepoPicker } from '../chat/RepoPicker'
import {
  AttachmentPicker,
  formatAttachmentSize,
  shortenAttachmentPath,
  type AttachedFile,
} from '../chat/AttachmentPicker'
import { uploadAttachments, type OutgoingAttachment } from '../../lib/chat/attachmentUpload'
import { createWorkspaceRepository, type WorkspaceRepository } from '../../lib/workspace'
import { ShortcutsPopover } from '../chat/ShortcutsPopover'
import { useSlashCompletion } from '../chat/useSlashCompletion'
import { LabelDot } from '../LabelDot'
import { inspectChipLabel } from '../../lib/inspect/format'
import type { SteerNotice } from '../../store/harnessChatStore'
import { useResearchStore } from '../../store/researchStore'
import { ResearchComposerStatus } from './research/ResearchComposerStatus'
import { ResearchToggle } from './research/ResearchToggle'

// Ở chế độ `live` (`VITE_TRANSPORT=live`) chưa có handler backend nào tiêu
// thụ `elements` (xem `types/transport.ts` chú thích trên `user_message`) —
// cùng cách đọc biến môi trường với `lib/vnc/config.ts:resolveScreenSource`.
function isLiveTransport(): boolean {
  return (import.meta.env.VITE_TRANSPORT ?? '').trim().toLowerCase() === 'live'
}

export interface RouterComposerAdapter {
  models: RouterSingleModel[]
  activeModelId: string
  isBusy: boolean
  connectionWarning?: string | null
  /**
   * Vòng 27 / C-5 — lượt ĐANG CHẠY vẫn nhận chỉ thị của chủ nhà: khi `true`, nút Gửi ở LẠI cạnh
   * nút Stop, câu gõ vào được xếp hàng cho lượt đang chạy và main đọc ở bước kế. `isBusy` vẫn là
   * thứ khoá nút Gửi ở mọi trạng thái khác (lượt chưa mở xong).
   */
  canSteer?: boolean
  /** Dòng xác nhận của chỉ thị vừa vào hàng (nguyên văn + mốc thời gian) — không có thì không hiện. */
  steerNotice?: SteerNotice | null
  onModelChange: (id: string) => void
  /**
   * Trả `false` (hoặc Promise resolve `false`) khi lần gửi thất bại — khi đó
   * composer khôi phục lại nội dung vừa gõ thay vì xoá trắng (BUG-17/F1).
   *
   * `images` là **mọi** ảnh đính kèm (đã cắt còn 2 ảnh đầu, xem `collectTurnImages`) chứ
   * không chỉ ảnh đầu như trước; `attachments` là các tệp đã nằm THẬT trên đĩa box
   * (`uploadAttachments` chạy xong mới gọi tới đây, nên đường dẫn trong đó luôn đọc được).
   */
  onSend: (
    prompt: string,
    images?: string[] | null,
    attachments?: OutgoingAttachment[],
  ) => void | Promise<boolean>
  onStop: () => void
}

/**
 * Lệnh điều khiển vẫn gửi được khi agent đang chạy (BUG-21/U5) — danh sách
 * này phải khớp regex `control` trong `store/harnessChatStore.ts`, nếu không
 * nút Gửi sẽ bật cho một lệnh mà store âm thầm bỏ qua.
 */
export const CONTROL_COMMANDS = ['/help', '/status', '/skills', '/agents', '/context', '/stop'] as const

export function isControlCommand(text: string): boolean {
  const normalized = text.trim().toLowerCase()
  return (CONTROL_COMMANDS as readonly string[]).includes(normalized)
}

/**
 * Trần ảnh inline của một lượt: harness chỉ nhận nhiều nhất 2 ảnh và thân request bị chặn ở
 * 1 MiB, nên hai ảnh phải nằm gọn trong 800 000 ký tự base64 (phần còn lại là JSON + prompt).
 */
export const MAX_TURN_IMAGES = 2
export const MAX_TURN_IMAGE_CHARS = 800_000

/** Tất cả ảnh có `dataUrl`, cắt còn 2 ảnh đầu và tổng ≤ 800 000 ký tự. */
function collectTurnImages(attachments: readonly AttachedFile[]): string[] | undefined {
  const images: string[] = []
  let total = 0
  for (const attachment of attachments) {
    if (!attachment.dataUrl) continue
    if (images.length >= MAX_TURN_IMAGES) break
    // Ảnh quá lớn bị bỏ qua nhưng KHÔNG chặn các ảnh nhỏ hơn phía sau (nếu còn chỗ).
    if (total + attachment.dataUrl.length > MAX_TURN_IMAGE_CHARS) continue
    images.push(attachment.dataUrl)
    total += attachment.dataUrl.length
  }
  return images.length ? images : undefined
}

/**
 * `repository` để test (và nhúng) truyền repo riêng; mặc định lấy đúng repo của ứng dụng
 * (`createWorkspaceRepository`) — cùng nguồn với panel Workspace Files, không tạo kênh thứ hai.
 *
 * E5 — trạng thái tải lên của một chip đính kèm. `attachment` chỉ có khi box ĐÃ nhận tệp
 * (đường dẫn + dung lượng box cấp), nhờ vậy lượt gửi sau không phải tải lại tệp đó.
 */
interface ChipUpload {
  status: 'uploading' | 'uploaded' | 'failed'
  done: number
  total: number
  attachment?: OutgoingAttachment
}

export function ChatInputBar({
  router,
  repository,
}: {
  router?: RouterComposerAdapter
  repository?: WorkspaceRepository
}) {
  const t = useT()
  const [input, setInput] = useState('')
  // Chế độ Research (P4): placeholder đổi khi đang bật, và danh sách lệnh gợi ý chỉ còn lệnh mode
  // (loại `/review` và mọi lệnh vai khác — bảng 4.8 dòng 1).
  const researchOn = useResearchStore((s) => s.mode.on)
  const slash = useSlashCompletion(input, setInput, { modeOnly: researchOn })
  const [attachments, setAttachments] = useState<AttachedFile[]>([])
  const [uploading, setUploading] = useState(false)
  const [attachError, setAttachError] = useState<string | null>(null)
  /**
   * E5 — trạng thái tải lên của TỪNG chip, đúng thứ mockup `attachments-chip-row` vẽ
   * (`đang tải` / `✓ đã tải lên` / `tải lên thất bại` + Thử lại).
   *
   * Chỉ chứa trạng thái ĐỌC ĐƯỢC TỪ SỰ THẬT: tệp nào đang bay, tệp nào box đã nhận (kèm
   * đường dẫn + dung lượng box trả về), tệp nào hỏng. KHÔNG có phần trăm: `uploadAttachments`
   * chỉ báo số tệp xong và `SandboxWorkspaceRepository.upload` không đọc được luồng byte,
   * nên phần trăm sẽ là con số bịa.
   */
  const [uploadStates, setUploadStates] = useState<Record<string, ChipUpload>>({})
  const defaultRepositoryRef = useRef<WorkspaceRepository | null>(null)
  if (!defaultRepositoryRef.current) defaultRepositoryRef.current = createWorkspaceRepository()
  const repositoryRef = useRef<WorkspaceRepository>(repository ?? defaultRepositoryRef.current)
  repositoryRef.current = repository ?? defaultRepositoryRef.current
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const barRef = useRef<HTMLDivElement>(null)
  const compact = useCompactComposer(barRef)
  const sendCommand = useAgentStore((s) => s.sendCommand)
  const agentBusy = useAgentStore((s) => s.isBusy)
  const isBusy = router?.isBusy ?? agentBusy
  const workspaceHidden = useUiStore((s) => s.workspaceHidden)
  // E5 — chip "Mở trong Files" của tệp ĐÃ lên box dùng đúng hành động có sẵn của app.
  const selectFile = useUiStore((s) => s.selectFile)
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

  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items
    if (!items) return
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf('image') !== -1) {
        const blob = items[i].getAsFile()
        if (blob) {
          const reader = new FileReader()
          reader.onload = () => {
            setAttachments((prev) => [
              ...prev,
              {
                id: `pasted-${Date.now()}`,
                name: `Pasted_Image_${Date.now().toString(36)}.png`,
                source: 'computer',
                size: formatAttachmentSize(blob.size),
                sizeBytes: blob.size,
                // Giữ chính đối tượng File: ảnh dán từ clipboard cũng phải đi tới box (A2/A5),
                // không chỉ nằm lại trong `dataUrl` của trình duyệt.
                file: blob,
                dataUrl: reader.result as string,
              },
            ])
          }
          reader.readAsDataURL(blob)
        }
      }
    }
  }

  const handleSend = async () => {
    // Chặn gửi hai lần: `handleSend` giờ bất đồng bộ (upload xong mới gửi), nên Enter
    // hai lần liên tiếp sẽ tạo hai lượt cùng bản nháp nếu không khoá.
    if (uploading) return
    if (!input.trim() && attachments.length === 0 && pendingElements.length === 0) return
    const draftText = input
    const draftAttachments = attachments
    const draftElements = pendingElements
    // Text gửi đi là ĐÚNG những gì người dùng gõ: không còn chuỗi `[Attached Files: …]`
    // — khối mô tả tệp do harness dựng từ `attachments` (hợp đồng A7).
    const textToSend = input.trim()
    const images = collectTurnImages(attachments)

    // Lệnh điều khiển (`/stop`, `/status`, …) không mang tệp: upload sẽ chỉ tạo rác
    // trong `.uploaded_artifacts` mà không ai đọc.
    let outgoing: OutgoingAttachment[] | undefined
    if (attachments.length > 0 && !isControlCommand(textToSend)) {
      const files = attachments.filter((a) => Boolean(a.file))
      if (files.length > 0) {
        setAttachError(null)
        setUploading(true)
        // E5 — gửi TỪNG tệp (không gọi một lượt cả mảng) để mỗi chip biết chính xác tệp nào
        // đang bay, tệp nào box đã nhận, tệp nào hỏng. Luật cũ giữ nguyên: tuần tự, và tệp
        // đầu tiên lỗi thì DỪNG CẢ LƯỢT (`return` trước `onSend`), bản nháp còn nguyên.
        // Tệp đã lên box ở lần bấm trước được dùng lại — bấm Gửi lần hai không nhân bản tệp.
        const total = files.length
        const uploaded: OutgoingAttachment[] = []
        let done = 0
        for (const file of files) {
          const cached = uploadStates[file.id]
          if (cached?.status === 'uploaded' && cached.attachment) {
            uploaded.push(cached.attachment)
            done += 1
            continue
          }
          setUploadStates((prev) => ({ ...prev, [file.id]: { status: 'uploading', done: done + 1, total } }))
          try {
            const [result] = await uploadAttachments(
              [{ name: file.name, file: file.file as File, relativePath: file.relativePath }],
              { repo: repositoryRef.current },
            )
            uploaded.push(result)
            done += 1
            setUploadStates((prev) => ({
              ...prev,
              [file.id]: { status: 'uploaded', done, total, attachment: result },
            }))
          } catch (error) {
            // Chip đỏ + giữ nguyên bản nháp: người dùng bấm Thử lại (hoặc Gửi lại) là đi tiếp
            // được, chứ không mất công chọn tệp từ đầu.
            setUploadStates((prev) => ({ ...prev, [file.id]: { status: 'failed', done, total } }))
            setUploading(false)
            setAttachError(error instanceof Error ? error.message : String(error))
            return
          }
        }
        outgoing = uploaded
        setUploading(false)
      }
    }

    let result: void | Promise<boolean> = undefined
    if (router) result = router.onSend(textToSend, images, outgoing)
    else sendCommand({
        type: 'user_message',
        text: textToSend,
        ...(draftElements.length > 0 ? { elements: draftElements } : {}),
      })
    setInput('')
    setAttachments([])
    // Chip biến mất thì trạng thái tải lên của nó cũng hết — không giữ lại đường dẫn cũ
    // cho một lượt đã gửi.
    setUploadStates({})
    clearPendingElements()
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    // Phản hồi tức thì: xoá ô nhập ngay, nhưng nếu harness trả lỗi (400) thì
    // trả lại đúng nội dung người dùng vừa gõ — lỗi hiện inline ở ChatPanel.
    if (result instanceof Promise) {
      const restoreDraft = () => {
        setInput(draftText)
        setAttachments(draftAttachments)
      }
      void result.then((ok) => { if (!ok) restoreDraft() }).catch(restoreDraft)
    }
  }

  /**
   * E5 — "Thử lại" cho MỘT tệp hỏng: chỉ tải lại chính tệp đó (không đụng các tệp đã lên
   * box, không gửi lượt). Tệp đã nhận thì giữ đường dẫn box cấp để lần bấm Gửi kế tiếp
   * không nhân bản tệp trên box.
   */
  const handleRetryUpload = async (file: AttachedFile) => {
    if (!file.file || uploading) return
    setAttachError(null)
    setUploading(true)
    setUploadStates((prev) => ({ ...prev, [file.id]: { status: 'uploading', done: 1, total: 1 } }))
    try {
      const [result] = await uploadAttachments(
        [{ name: file.name, file: file.file, relativePath: file.relativePath }],
        { repo: repositoryRef.current },
      )
      setUploadStates((prev) => ({
        ...prev,
        [file.id]: { status: 'uploaded', done: 1, total: 1, attachment: result },
      }))
    } catch (error) {
      setUploadStates((prev) => ({ ...prev, [file.id]: { status: 'failed', done: 0, total: 1 } }))
      setAttachError(error instanceof Error ? error.message : String(error))
    }
    setUploading(false)
  }

  const handleInterrupt = () => {
    if (router) { router.onStop(); return }
    sendCommand({
      type: 'interrupt',
      level: 'tam_dung',
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Gõ trong ô soạn tin = người dùng đang thao tác → ý định tự mở tab của
    // agent chỉ xếp hàng (hợp đồng §3). Không ảnh hưởng gì tới giao diện.
    useUiStore.getState().noteUserActivity()
    // Lệnh điều khiển đã gõ đủ (vd `/stop`) phải gửi được ngay ở lần Enter đầu;
    // popup gợi ý không được "ăn" phím này (BUG-21/U5).
    const controlSubmit = e.key === 'Enter' && !e.shiftKey && isControlCommand(input)
    if (!controlSubmit && slash.keyDown(e)) return
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  // Đang chạy: nút Gửi biến mất (thay bằng Stop) trừ khi ô nhập đang là một
  // lệnh điều khiển — người dùng vẫn phải bấm gửi được `/stop` (BUG-21/U5) —
  // hoặc lượt đang chạy NHẬN chỉ thị giữa lượt (vòng 27 / C-5: câu gõ vào được
  // xếp hàng cho lượt đang chạy, áp ở bước kế, nên nút Gửi phải còn).
  const canSend = Boolean(input.trim() || attachments.length || pendingElements.length)
  const canSteer = Boolean(router?.canSteer)
  const steerNotice = router?.steerNotice ?? null
  const showSendButton = !isBusy || isControlCommand(input) || canSteer

  return (
    <div ref={barRef} className="border-t border-line bg-panel p-3 select-none">
      {/* Hộp soạn tin gom theo cột đọc khi bảng Workspace ẩn; thanh ngoài
          (`border-t border-line bg-panel p-3`) vẫn chạy hết bề rộng. */}
      <div
        data-testid="chat-input-bar"
        className={`relative rounded-xl border border-line bg-panel2/70 p-2.5 shadow-xs transition-all focus-within:border-zinc-500 focus-within:ring-1 focus-within:ring-zinc-600/40 ${readingColumnClass(workspaceHidden)}`}
      >
        {slash.popup}
        {/* P4 — dải trạng thái Research: chế độ đang bật, lời hỏi thoát chế độ, hoặc run chạy nền.
            Khối này thay cho thẻ rời rạc: nó luôn nằm ngay trên ô nhập. */}
        <ResearchComposerStatus />
        {/* Attached files chips — E5: mỗi chip mang trạng thái tải lên THẬT của nó
            (`data-attach-state`, đúng tên thuộc tính của mockup `attachments-chip-row`). */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-1.5 px-1">
            {attachments.map((file) => {
              const upload = uploadStates[file.id]
              return (
              <div
                key={file.id}
                data-testid="composer-attach-chip"
                data-attach-state={upload?.status}
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
                {file.size && <span className="shrink-0 text-muted">{file.size}</span>}
                {/* Tệp trong thư mục vừa chọn: nói rõ nó nằm ở đâu, không chỉ tên tệp. */}
                {file.relativePath && (
                  <span className="shrink-0 text-muted" title={file.relativePath}>
                    {shortenAttachmentPath(file.relativePath)}
                  </span>
                )}
                {/* Trạng thái thật. Không có phần trăm: nguồn không cho biết số byte đã đi. */}
                {upload?.status === 'uploading' && (
                  <span
                    data-testid="composer-attach-state"
                    data-attach-state="uploading"
                    className="inline-flex shrink-0 items-center gap-0.5 text-amber-400"
                  >
                    <Loader2 className="size-3 animate-spin" />
                    đang tải lên {upload.done}/{upload.total} tệp
                  </span>
                )}
                {upload?.status === 'uploaded' && (
                  <span
                    data-testid="composer-attach-state"
                    data-attach-state="uploaded"
                    className="inline-flex shrink-0 items-center gap-0.5 text-emerald-400"
                  >
                    <Check className="size-3" />
                    đã tải lên
                  </span>
                )}
                {upload?.status === 'failed' && (
                  <span className="inline-flex shrink-0 items-center gap-1">
                    <span
                      data-testid="composer-attach-state"
                      data-attach-state="failed"
                      className="text-rose-400"
                    >
                      tải lên thất bại
                    </span>
                    <button
                      type="button"
                      data-testid="composer-attach-retry"
                      onClick={() => void handleRetryUpload(file)}
                      title={`Thử lại tải lên ${file.name}`}
                      className="rounded border border-rose-500/40 px-1 py-0.5 text-rose-300 transition hover:bg-rose-500/10 cursor-pointer"
                    >
                      Thử lại
                    </button>
                  </span>
                )}
                {/* Chỉ hiện khi box ĐÃ nhận tệp: lúc đó mới có đường dẫn thật để mở. */}
                {upload?.status === 'uploaded' && upload.attachment && (
                  <button
                    type="button"
                    data-testid="composer-attach-open"
                    onClick={() => selectFile(upload.attachment!.path)}
                    title={`Mở ${upload.attachment.path} trong tab Files`}
                    className="inline-flex shrink-0 items-center gap-0.5 text-muted transition hover:text-fg cursor-pointer"
                  >
                    <FolderOpen className="size-3" />
                    Mở trong Files
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setAttachments((prev) => prev.filter((a) => a.id !== file.id))
                    // Chip bị bỏ thì trạng thái của nó cũng bỏ — không giữ lại đường dẫn cũ.
                    setUploadStates((prev) => {
                      const next = { ...prev }
                      delete next[file.id]
                      return next
                    })
                  }}
                  className="text-muted hover:text-rose-500 transition ml-0.5 cursor-pointer"
                  title="Remove attachment"
                >
                  <X className="size-3" />
                </button>
              </div>
              )
            })}
          </div>
        )}

        {/* Lỗi upload: chip đỏ + giữ nguyên bản nháp (A6). Nói thẳng tệp nào hỏng thay vì
            im lặng bỏ tệp — đây là bài học của BUG-40. */}
        {attachError && (
          <p
            data-testid="composer-attach-error"
            role="alert"
            className="mb-2 rounded-lg border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] text-rose-400"
          >
            {attachError}
          </p>
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

        {/* Chỉ thị đã xếp hàng cho lượt đang chạy (vòng 27 / C-5): dòng này nằm TRONG hộp soạn
            tin, ngay trên ô nhập — nó thuộc về câu vừa gõ, không phải một khối quanh câu trả lời.
            Nguyên văn được giữ lại để chủ nhà thấy đúng thứ mình đã gửi. */}
        {steerNotice && (
          <div
            data-testid="composer-steer-queued"
            className="mb-2 flex items-start gap-1.5 rounded-lg border border-brand/30 bg-brand/5 px-2 py-1.5 text-[11px] text-brand"
          >
            <Clock className="mt-0.5 size-3 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="font-medium">
                {t('composer.steerQueued')}
                <span className="ml-1.5 font-mono text-[10px] text-muted">
                  {new Date(steerNotice.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                </span>
              </p>
              <p className="truncate text-muted" title={steerNotice.text}>
                “{steerNotice.text}”
              </p>
            </div>
          </div>
        )}

        <textarea
          role="combobox"
          aria-label="Message"
          aria-autocomplete="list"
          aria-expanded={slash.expanded}
          aria-controls={slash.expanded ? 'slash-completions' : undefined}
          aria-activedescendant={slash.activeId}
          ref={textareaRef}
          rows={1}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={t(researchOn ? 'research.placeholderRunning' : compact ? 'composer.placeholderShort' : 'composer.placeholder')}
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
            <HarnessModelPicker routerModels={router?.models} activeRouterModelId={router?.activeModelId} onRouterModelChange={router?.onModelChange} />

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

            {/* P4 — nút Research trong thanh công cụ (`composer-toggle-toolbar-pill.html`).
                Chế độ đang tắt mà còn run chạy nền thì bấm vào mở tab Research thay vì bật chế độ. */}
            <ResearchToggle compact={compact} />
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
            {isBusy && (
              <button
                type="button"
                onClick={handleInterrupt}
                className="flex size-7 items-center justify-center rounded-lg bg-rose-500 text-white shadow-xs transition hover:bg-rose-600 active:scale-95 cursor-pointer animate-in fade-in zoom-in-90 duration-150"
                title="Stop / Interrupt agent action (Esc)"
              >
                <Square className="size-3 fill-current" />
              </button>
            )}
            {showSendButton && (
              <button
                type="button"
                onClick={handleSend}
                disabled={!canSend || uploading}
                data-testid="composer-send"
                data-uploading={uploading ? 'true' : undefined}
                aria-busy={uploading || undefined}
                className="flex size-7 items-center justify-center rounded-lg bg-zinc-100 text-zinc-900 shadow-xs transition hover:bg-white disabled:opacity-30 disabled:hover:bg-zinc-100 cursor-pointer animate-in fade-in zoom-in-90 duration-150"
                title={
                  uploading
                    ? t('composer.uploadingAttachments')
                    : isControlCommand(input) && isBusy
                      ? t('composer.sendControlWhileBusy')
                      : canSteer
                        ? t('composer.sendSteer')
                        : 'Send prompt (Enter)'
                }
              >
                {uploading ? <Loader2 className="size-3.5 animate-spin" /> : <ArrowUp className="size-3.5" />}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Dòng chú thích DƯỚI ô nhập khi lượt đang chạy (vòng 27 / C-5): câu gõ vào không cắt
          ngang bước đang chạy và không mở lượt mới — nó vào hàng cho lượt này. */}
      {canSteer && (
        <div
          data-testid="composer-steer-hint"
          className="mt-1.5 flex items-center gap-1.5 px-1 text-[11px] text-amber-500"
        >
          <Info className="size-3 shrink-0" />
          <span>{t('composer.steerHint')}</span>
        </div>
      )}
    </div>
  )
}
