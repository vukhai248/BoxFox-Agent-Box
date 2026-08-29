/**
 * Khung Chat phong cách Devin / BoxFox (Seamless Agent Stream).
 * - Tin nhắn người dùng: Thẻ gọn gàng bên phải kèm timestamp & avatar KV.
 * - Phản hồi Agent: Hòa vào nền, chữ text-fg sắc nét trên cả nền sáng lẫn tối.
 * - Quá trình suy luận: Thanh "Worked for Xs ›" có thể bấm mở để xem nội dung thinking.
 * - Khối lệnh: Khung code hiển thị rõ ràng kèm nút Copy và header ngôn ngữ.
 * - Khối Ảnh Chụp Màn Hình (Screen Captures Group):
 *   + Hiển thị ảnh nguyên bản, sắc nét, KHÔNG có lớp phủ mờ hay text che ảnh.
 *   + Các ảnh chụp liên tiếp được xếp liền kề sát nhau gọn gàng.
 *   + Click vào bất kỳ ảnh nào để mở trực tiếp Lightbox phóng to/thu nhỏ bằng con lăn chuột và tải về.
 */
import { useRef, useEffect, useState, useMemo } from 'react'
import {
  ChevronRight,
  ChevronDown,
  Copy,
  Check,
  Sparkles,
  ShieldAlert,
  ArrowRight,
  Terminal,
  Camera,
  Eye,
  Download,
  FileCode,
  FileText,
  Code2,
  FileJson,
  File,
} from 'lucide-react'
import type { ChatMessage, ReferencedFile } from '../../types/ui'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n/context'
import { LabelDot } from '../LabelDot'
import { ChatInputBar } from './ChatInputBar'
import { ContextUsageBar } from './ContextUsageBar'
import { MediaLightboxModal, type LightboxMediaProps } from '../chat/MediaLightboxModal'
import { Video, Play } from 'lucide-react'
import { MarkdownRenderer } from '../chat/MarkdownRenderer'

type ChatGroup =
  | { kind: 'single'; message: ChatMessage }
  | { kind: 'screenshots'; items: Extract<ChatMessage, { kind: 'screenshot' }>[] }

function groupMessages(messages: ChatMessage[]): ChatGroup[] {
  const groups: ChatGroup[] = []
  let currentScreenshots: Extract<ChatMessage, { kind: 'screenshot' }>[] = []

  for (const msg of messages) {
    if (msg.kind === 'screenshot') {
      currentScreenshots.push(msg)
    } else {
      if (currentScreenshots.length > 0) {
        groups.push({ kind: 'screenshots', items: currentScreenshots })
        currentScreenshots = []
      }
      groups.push({ kind: 'single', message: msg })
    }
  }

  if (currentScreenshots.length > 0) {
    groups.push({ kind: 'screenshots', items: currentScreenshots })
  }

  return groups
}

export function ChatPanel() {
  const t = useT()
  const messages = useAgentStore((s) => s.messages)
  const requests = useAgentStore((s) => s.requests)
  const proposal = useAgentStore((s) => s.proposal)
  const openTab = useUiStore((s) => s.openTab)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Lightbox Modal State
  const [lightboxMedia, setLightboxMedia] = useState<LightboxMediaProps | null>(null)

  const pendingRequestIds = Object.values(requests)
    .filter((r) => r.status === 'dang_cho')
    .map((r) => r.request_id)

  const messageGroups = useMemo(() => groupMessages(messages), [messages])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  return (
    <div className="flex h-full flex-col overflow-hidden bg-bg">
      {/* Top Context Usage Bar */}
      <ContextUsageBar />

      {/* Scrollable conversation stream */}
      <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-6 select-text">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center p-8 text-center">
            <div className="max-w-sm space-y-2">
              <div className="mx-auto flex size-10 items-center justify-center rounded-xl bg-panel2 border border-line text-muted">
                <Sparkles className="size-5 text-brand" />
              </div>
              <h3 className="text-sm font-semibold text-fg">{t('chat.empty.title')}</h3>
              <p className="text-xs leading-relaxed text-muted">{t('chat.empty.body')}</p>
            </div>
          </div>
        ) : (
          messageGroups.map((group, groupIdx) => {
            if (group.kind === 'screenshots') {
              return (
                <ScreenshotsGroupCard
                  key={`ss-group-${groupIdx}`}
                  items={group.items}
                  onOpenLightbox={(img) => setLightboxMedia(img)}
                />
              )
            }

            return (
              <MessageRow
                key={group.message.id}
                message={group.message}
                hasPendingPermission={pendingRequestIds.includes(
                  group.message.kind === 'permission_request' ? group.message.request_id : '',
                )}
                hasModeSwitch={proposal !== null && group.message.kind === 'mode_switch'}
                onOpenPermission={() => openTab('decisions')}
                onOpenModeSwitch={() => openTab('plan')}
                onOpenLightbox={setLightboxMedia}
                    />
            )
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Fixed bottom chat input bar */}
      <ChatInputBar />

      {/* Fullscreen Interactive Lightbox Modal */}
      {lightboxMedia && (
        <MediaLightboxModal
          src={lightboxMedia.src}
          caption={lightboxMedia.caption}
          sourceUrl={lightboxMedia.sourceUrl}
          onClose={() => setLightboxMedia(null)}
        />
      )}
    </div>
  )
}

/** Group of consecutive screenshots placed seamlessly right next to each other */
function ScreenshotsGroupCard({
  items,
  onOpenLightbox,
}: {
  items: Extract<ChatMessage, { kind: 'screenshot' }>[]
  onOpenLightbox?: (props: LightboxMediaProps) => void
}) {
  const first = items[0]

  return (
    <div className="space-y-2 max-w-xl pl-0.5">
      {/* Header bar: Single clean header for the group */}
      <div className="flex items-center justify-between text-xs text-muted select-none">
        <div className="flex items-center gap-1.5 font-medium">
          <Camera className="size-3.5 text-brand" />
          <span className="text-fg font-semibold">
            Screen Capture{items.length > 1 ? ` (${items.length})` : ''}
          </span>
          {first.source_url && (
            <span className="font-mono text-[10px] text-muted truncate max-w-[240px]">
              ({first.source_url})
            </span>
          )}
        </div>
        {first.label_id && first.integrity && first.confidentiality && (
          <div className="flex items-center gap-1.5">
            <LabelDot integrity={first.integrity} confidentiality={first.confidentiality} />
            <span className="font-mono text-[10px] text-muted">{first.label_id}</span>
          </div>
        )}
      </div>

      {/* Images stacked seamlessly right next to each other */}
      <div className="space-y-2">
        {items.map((ss) => (
          <div
            key={ss.id}
            onClick={() =>
              onOpenLightbox?.({
                src: ss.image_url,
                caption: ss.caption,
                sourceUrl: ss.source_url,
              })
            }
            className="cursor-pointer overflow-hidden rounded-xl border border-line bg-panel2 transition hover:border-brand/50 hover:shadow-md select-none"
            title="Click to zoom / download"
          >
            <img
              src={ss.image_url}
              alt={ss.caption || 'Screenshot'}
              className="w-full object-cover max-h-72 select-none"
            />
          </div>
        ))}
      </div>
    </div>
  )
}


/** Screen Recording Card with Play Overlay and Duration Badge */
function ScreenRecordingCard({
  message,
  onOpenLightbox,
}: {
  message: Extract<ChatMessage, { kind: 'screen_recording' }>
  onOpenLightbox: (props: LightboxMediaProps) => void
}) {
  return (
    <div className="space-y-2.5 max-w-xl pl-0.5 animate-in fade-in duration-150">
      <div className="flex items-center justify-between gap-2 text-xs text-muted select-none">
        <div className="flex items-center gap-1.5 font-semibold text-fg">
          <Video className="size-3.5 text-brand" />
          <span>Screen Recording Session</span>
        </div>
        {message.label_id && message.integrity && message.confidentiality && (
          <div className="flex items-center gap-1.5">
            <LabelDot integrity={message.integrity} confidentiality={message.confidentiality} />
            <span className="font-mono text-[10px] text-muted">{message.label_id}</span>
          </div>
        )}
      </div>

      <div
        onClick={() =>
          onOpenLightbox?.({
            type: 'video',
            src: message.video_url,
            poster: message.poster_url,
            caption: message.caption,
            sourceUrl: message.source_url,
            duration: message.duration_seconds,
          })
        }
        className="group relative cursor-pointer overflow-hidden rounded-xl border border-line bg-panel2 transition hover:border-brand/50 hover:shadow-lg select-none"
        title="Click to play and inspect recording"
      >
        <video
          src={message.video_url}
          poster={message.poster_url}
          muted
          playsInline
          loop
          autoPlay
          className="w-full object-cover max-h-72 rounded-xl"
        />

        {/* Play Overlay */}
        <div className="absolute inset-0 flex items-center justify-center bg-black/30 group-hover:bg-black/40 transition">
          <div className="flex size-12 items-center justify-center rounded-full bg-black/60 text-white border border-white/20 group-hover:scale-110 transition shadow-lg backdrop-blur-xs">
            <Play className="size-5 ml-0.5 fill-white" />
          </div>
        </div>

        {/* Bottom Badges */}
        <div className="absolute bottom-2.5 left-2.5 right-2.5 flex items-center justify-between text-[11px] text-white font-medium drop-shadow-md pointer-events-none">
          <span className="rounded-md bg-black/60 px-2 py-0.5 backdrop-blur-xs border border-white/10">
            {message.caption || 'Browser Session'}
          </span>
          {message.duration_seconds && (
            <span className="rounded-md bg-black/60 px-2 py-0.5 font-mono backdrop-blur-xs border border-white/10">
              0:{message.duration_seconds.toString().padStart(2, '0')} • 60 FPS
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

function MessageRow({
  message,
  hasPendingPermission,
  hasModeSwitch,
  onOpenPermission,
  onOpenModeSwitch,
  onOpenLightbox,
}: {
  message: ChatMessage
  hasPendingPermission: boolean
  hasModeSwitch: boolean
  onOpenPermission: () => void
  onOpenModeSwitch: () => void
  onOpenLightbox: (props: LightboxMediaProps) => void
}) {
  switch (message.kind) {
    case 'user_text':
      return <UserBubble text={message.text} />
    case 'agent_text':
      return <SeamlessAgentMessage message={message} />
    case 'agent_step':
      return <StepBlock message={message} />
    case 'screenshot':
      return null // handled in ScreenshotsGroupCard
    case 'screen_recording':
      return <ScreenRecordingCard message={message} onOpenLightbox={onOpenLightbox} />
    case 'system_note':
      return (
        <div className="my-2 py-1 text-center text-xs italic text-muted max-w-lg mx-auto">
          {message.text}
        </div>
      )
    case 'permission_request':
      return (
        <PermissionChatRow
          requestId={message.request_id}
          pending={hasPendingPermission}
          onClick={onOpenPermission}
        />
      )
    case 'mode_switch':
      return <ModeSwitchChatRow pending={hasModeSwitch} onClick={onOpenModeSwitch} />
  }
}

/** User message card with timestamp and KV badge */
function UserBubble({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="max-w-[85%] rounded-2xl bg-panel2 border border-line px-4 py-3 text-xs leading-relaxed text-fg shadow-xs">
        {text}
      </div>
      <div className="flex items-center gap-2 text-[10px] text-muted pr-1 select-none">
        <span>Just now</span>
        <button
          type="button"
          onClick={handleCopy}
          className="hover:text-fg transition cursor-pointer"
          title="Copy message"
        >
          {copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
        </button>
        <span className="flex size-4 items-center justify-center rounded-full bg-panel border border-line text-[8px] font-bold text-muted">
          KV
        </span>
      </div>
    </div>
  )
}

/** Seamless Agent message: flat text, rich markdown, code blocks, referenced files */
function SeamlessAgentMessage({
  message,
}: {
  message: Extract<ChatMessage, { kind: 'agent_text' }>
}) {
  return (
    <div className="space-y-3 pl-0.5">
      {/* Agent Response Text with Markdown & KaTeX LaTeX Render */}
      <MarkdownRenderer content={message.text} />

      {/* Referenced / Related Files with View (Eye) and Download Buttons */}
      {message.files && message.files.length > 0 && (
        <ReferencedFilesList files={message.files} />
      )}

      {/* Provenance Label */}
      <div className="flex items-center gap-1.5 pt-1 select-none">
        <LabelDot integrity={message.integrity} confidentiality={message.confidentiality} />
        <span className="text-[10px] font-mono text-muted">{message.label_id}</span>
      </div>
    </div>
  )
}

function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  if (['py', 'pyw'].includes(ext)) {
    return <FileCode className="size-4 text-blue-400 shrink-0" />
  }
  if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) {
    return <Code2 className="size-4 text-cyan-400 shrink-0" />
  }
  if (['md', 'markdown', 'txt', 'rst'].includes(ext)) {
    return <FileText className="size-4 text-emerald-400 shrink-0" />
  }
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) {
    return <FileJson className="size-4 text-orange-400 shrink-0" />
  }
  return <File className="size-4 text-muted shrink-0" />
}

function formatBytes(bytes?: number) {
  if (!bytes) return ''
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}

/**
 * Khối hiển thị danh sách file tham chiếu / liên quan (Referenced Files).
 * - Hiển thị icon định dạng màu theo extension (.py, .ts, .md, .json...).
 * - Nút [👁 View]: Gọi `openTab('files')` và `selectFile(path)` để mở file tại panel Code Studio bên phải.
 * - Nút [⬇ Download]: Xuất file trực tiếp về máy tính người dùng.
 */
function ReferencedFilesList({ files }: { files: ReferencedFile[] }) {
  const selectFile = useUiStore((s) => s.selectFile)
  const allWorkspaceFiles = useAgentStore((s) => s.files)

  // Chỉ gọi selectFile — nó đã tự mở tab Files (panel Workspace Files). Không
  // mở song song tab IDE nữa, tránh hai tab bật lên cùng lúc.
  const handleOpenFile = (path: string) => {
    selectFile(path)
  }

  const handleDownloadFile = (file: ReferencedFile) => {
    let content = file.content
    if (!content) {
      const findContent = (nodes: typeof allWorkspaceFiles): string | undefined => {
        for (const node of nodes) {
          if (node.path === file.path && node.content) return node.content
          if (node.children) {
            const found = findContent(node.children)
            if (found) return found
          }
        }
        return undefined
      }
      content = findContent(allWorkspaceFiles) || `# ${file.name}\n`
    }

    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = file.name
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="space-y-2 pt-1 max-w-xl">
      <div className="flex items-center gap-1.5 text-xs font-semibold text-fg select-none">
        <FileText className="size-3.5 text-brand" />
        <span>Referenced Files ({files.length})</span>
      </div>

      <div className="space-y-1.5">
        {files.map((file) => (
          <div
            key={file.path}
            className="flex items-center justify-between gap-3 rounded-xl border border-line bg-panel2/80 px-3.5 py-2.5 transition hover:bg-panel2 hover:border-brand/40 shadow-2xs group select-none"
          >
            <div className="flex items-center gap-2.5 min-w-0">
              {getFileIcon(file.name)}
              <div className="min-w-0">
                <div className="text-xs font-medium font-mono text-fg truncate">
                  {file.name}
                </div>
                <div className="text-[10px] font-mono text-muted truncate">
                  {file.path} {file.size_bytes ? `• ${formatBytes(file.size_bytes)}` : ''}
                </div>
              </div>
            </div>

            {/* Action Buttons: View (Eye) + Download */}
            <div className="flex items-center gap-1.5 shrink-0">
              {/* Open file in right workspace panel */}
              <button
                type="button"
                onClick={() => handleOpenFile(file.path)}
                className="flex items-center gap-1 rounded-lg border border-line bg-panel px-2.5 py-1 text-xs font-medium text-fg hover:text-brand hover:border-brand/40 transition cursor-pointer shadow-2xs"
                title="Open file in right workspace window"
              >
                <Eye className="size-3.5 text-brand" />
                <span className="text-[11px]">View</span>
              </button>

              {/* Download file button */}
              <button
                type="button"
                onClick={() => handleDownloadFile(file)}
                className="flex size-7 items-center justify-center rounded-lg border border-line bg-panel text-muted hover:text-fg hover:border-brand/40 transition cursor-pointer shadow-2xs"
                title="Download file to computer"
              >
                <Download className="size-3.5" />
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/** Step block with collapsible Thinking accordion and tool output */
function StepBlock({
  message,
}: {
  message: Extract<ChatMessage, { kind: 'agent_step' }>
}) {
  const [thinkingOpen, setThinkingOpen] = useState(false)

  return (
    <div className="space-y-2 pl-0.5 animate-in fade-in duration-150">
      {/* Thinking Accordion Bar: Worked for Xs > */}
      {message.thought && (
        <div className="space-y-1.5">
          <button
            type="button"
            onClick={() => setThinkingOpen(!thinkingOpen)}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-fg font-medium transition cursor-pointer select-none group"
          >
            <span className="flex size-1.5 rounded-full bg-brand/80 group-hover:scale-125 transition duration-200" />
            <span>Worked for 4s</span>
            {thinkingOpen ? (
              <ChevronDown className="size-3.5 text-muted group-hover:text-fg transition" />
            ) : (
              <ChevronRight className="size-3.5 text-muted group-hover:text-fg transition" />
            )}
          </button>

          {/* Thinking Content */}
          {thinkingOpen && (
            <div className="border-l-2 border-brand/50 pl-3.5 py-1.5 text-xs italic text-muted leading-relaxed animate-in fade-in duration-150 bg-panel2/30 rounded-r-xl">
              {message.thought}
            </div>
          )}
        </div>
      )}

      {/* Tool Call and Code Output Block */}
      {message.tool_name && (
        <div className="space-y-2">
          {/* Tool banner */}
          <div className="flex items-center gap-2 text-xs font-mono text-muted">
            <Terminal className="size-3.5 text-brand" />
            <span className="font-semibold text-fg">{message.tool_name}</span>
            {message.params && (
              <span className="text-muted/80 truncate">
                {Object.entries(message.params)
                  .map(([k, v]) => `${k}=${v}`)
                  .join(' ')}
              </span>
            )}
          </div>

          {/* Tool Result Preview */}
          {message.result_preview && (
            <div className="rounded-xl border border-line bg-panel2/60 p-3 font-mono text-xs text-fg shadow-2xs">
              <pre className="overflow-x-auto whitespace-pre-wrap">{message.result_preview}</pre>
            </div>
          )}
        </div>
      )}

      {/* Provenance Label */}
      {message.label_id && message.integrity && message.confidentiality && (
        <div className="flex items-center gap-1.5 pt-0.5 select-none">
          <LabelDot integrity={message.integrity} confidentiality={message.confidentiality} />
          <span className="text-[10px] font-mono text-muted">{message.label_id}</span>
        </div>
      )}
    </div>
  )
}


function PermissionChatRow({
  requestId,
  pending,
  onClick,
}: {
  requestId: string
  pending: boolean
  onClick: () => void
}) {
  return (
    <div className="flex items-center justify-between gap-2.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3.5 py-2 text-xs text-fg">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        <ShieldAlert className={`size-4 shrink-0 ${pending ? 'text-amber-500 animate-pulse' : 'text-muted'}`} />
        <span className="truncate">
          {pending
            ? `Permission request #${requestId} — awaiting your decision`
            : `Permission request #${requestId} decided`}
        </span>
      </div>
      <button
        type="button"
        onClick={onClick}
        className="flex items-center gap-1 shrink-0 rounded-md border border-line bg-panel px-2.5 py-1 text-[11px] font-semibold text-brand hover:opacity-80 transition cursor-pointer"
      >
        <span>Open Decisions Tab</span>
        <ArrowRight className="size-3" />
      </button>
    </div>
  )
}

function ModeSwitchChatRow({ pending, onClick }: { pending: boolean; onClick: () => void }) {
  const t = useT()
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex w-full items-center gap-2.5 rounded-xl border p-3 text-left transition cursor-pointer ${
        pending
          ? 'border-brand/40 bg-panel shadow-xs'
          : 'border-line bg-panel2/60 hover:bg-panel2'
      }`}
    >
      <span className={`size-2 rounded-full ${pending ? 'bg-brand animate-pulse' : 'bg-muted'}`} />
      <span className="flex-1 text-xs font-medium text-fg">
        {t('chat.modeSwitchPending')}
      </span>
      <span className="flex items-center gap-1 rounded bg-brand px-2.5 py-1 text-[11px] font-semibold text-brandfg shadow-xs hover:opacity-90 transition">
        <span>{t('chat.view')}</span>
        <ArrowRight className="size-3" />
      </span>
    </button>
  )
}
