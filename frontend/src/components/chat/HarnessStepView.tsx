import React, { useState, useMemo, useEffect, useCallback } from 'react'
import { useT } from '../../i18n/context'
import { useAnswerLabels } from '../../i18n/answerLabels'
import {
  Terminal,
  Camera,
  FileText,
  Search,
  BrainCircuit,
  Loader2,
  AlertCircle,
  ChevronRight,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Copy,
  Check,
  Hexagon,
  X,
  Maximize2,
  Layers,
  Film,
  ShieldAlert,
  RefreshCw,
  FolderOpen,
  Crosshair,
} from 'lucide-react'
import type { HarnessJournal, HarnessEvent, JournalRow } from '../../store/harnessChatStore'
import { useUiStore } from '../../store/uiStore'
import type { ProviderSnapshot } from '../../types/provider'
import type { RouterChatSelection } from '../../store/routerChatStore'
import { MarkdownRenderer } from './MarkdownRenderer'
import { formatAttachmentSize } from './AttachmentPicker'
import { absoluteWorkspacePath } from '../../lib/chat/attachmentUpload'
import { appendStreamText } from '../../lib/streamText'
import { researchActivity } from '../../lib/researchMode'
import {
  deliveryLabel,
  peerDeliveries,
  peerDeliveryView,
  peerLabels,
  peerSkipReason,
  shortPeerId,
  type PeerSkipReason,
} from '../../lib/chat/peerPipeline'
import type { TKey, TVars } from '../../i18n/context'
import { ProviderIcon } from '../providers/ProviderIcon'
import type { LightboxMediaProps } from './MediaLightboxModal'

/** Tab mà một chip trong transcript có thể mở (hợp đồng §3 — gợi ý, không ra lệnh). */
export type TranscriptTabId = 'plan' | 'decisions' | 'subagents'

type Translate = (key: TKey, vars?: TVars) => string

/** Mã lý do `skipped` có chữ riêng; mã lạ hiện NGUYÊN mã (không giấu vì sao không giao). */
const SKIP_REASON_KEY: Record<PeerSkipReason, TKey> = {
  no_such_peer: 'chat.subagentSkipReason.no_such_peer',
  recipient_not_running: 'chat.subagentSkipReason.recipient_not_running',
}

function skipReasonText(t: Translate, reason: string | null): string {
  if (!reason) return t('chat.subagentSkipReason.unknown')
  const known = peerSkipReason(reason)
  return known ? t(SKIP_REASON_KEY[known]) : reason
}

interface HarnessStepViewProps {
  events: HarnessEvent[]
  status: string
  error: string | null
  /** `sessionId` của phiên cha — nhờ nó mới gọi được tên `main` trong `deliveries[].recipient`. */
  sessionId?: string | null
  connectionWarning?: string | null
  onDismissWarning?: () => void
  onOpenLightbox?: (media: LightboxMediaProps) => void
  snapshot?: ProviderSnapshot | null
  selection?: RouterChatSelection | null
  /** Mở tab tại chỗ khi người dùng bấm chip kế hoạch / sub-agent / quyết định. */
  onOpenTab?: (tab: TranscriptTabId, target?: Record<string, unknown> | null) => void
  /**
   * P4.1/P4.3 — nhật ký bền của phiên (`journal` của `GET /sessions/{sid}`, đã gộp qua các vòng
   * poll). Hàng `E:` trong đó là bằng chứng cổng đã ghim; thiếu prop này thì lượt vẫn vẽ được,
   * chỉ không có mảnh nào đến từ nhật ký.
   */
  journal?: HarnessJournal | null
}

/**
 * Một mục trong dòng thời gian của lượt (F2). Lượt được vẽ như MỘT danh sách
 * phẳng theo `seq`, không gom tool/ảnh vào accordion hay gallery riêng.
 */
type TurnTimelineItem =
  | { kind: 'text'; id: string; seq: number; text: string; live: boolean }
  // Vòng 27 / C-5 — chỉ thị chủ nhà gửi GIỮA lượt (harness phát `user` với `{steer:true}`): nó
  // thuộc lượt ĐANG chạy, không mở lượt mới, nên nằm trong dòng thời gian ở đúng chỗ `seq` của nó.
  | { kind: 'user_steer'; id: string; seq: number; event: HarnessEvent }
  | { kind: 'tool'; id: string; seq: number; start: HarnessEvent | null; end: HarnessEvent | null }
  | { kind: 'child'; id: string; seq: number; event: HarnessEvent }
  | { kind: 'plan'; id: string; seq: number; event: HarnessEvent }
  | { kind: 'decision'; id: string; seq: number; event: HarnessEvent; resolution?: HarnessEvent }
  | { kind: 'compression'; id: string; seq: number; event: HarnessEvent }
  | { kind: 'notice'; id: string; seq: number; event: HarnessEvent }

interface HarnessTurn {
  id: string
  modelChange?: { from: string; to: string } | null
  userEvent: HarnessEvent | null
  thought: string | null
  items: TurnTimelineItem[]
  finalAssistant: HarnessEvent | null
  usage: {
    prompt_tokens?: number
    completion_tokens?: number
    total_tokens?: number
    reasoning_tokens?: number
  } | null
  target: {
    modelId?: string
    connectionId?: string
    aliasId?: string | null
  } | null
  finish: HarnessEvent | null
  startTime: number
  endTime: number
  isCompleted: boolean
  error?: string | null
}

/**
 * Vòng 23 / P4.3 — loại ảnh/ghi hình của một mảnh media, đọc từ chính payload (`/captures/<kind>/`)
 * hoặc từ tên tool. Giao diện dựng chú thích từ từ điển theo ngôn ngữ câu trả lời (P5.3).
 */
export type MediaCaptionKind = 'capture-window' | 'capture-tab' | 'capture-screen' | 'record' | 'browser'

/** Khoá từ điển của từng loại mảnh — bảng tường minh để gõ sai khoá là lỗi biên dịch. */
const MEDIA_CAPTION_KEYS: Record<MediaCaptionKind, TKey> = {
  'capture-window': 'chat.mediaCaption.capture-window',
  'capture-tab': 'chat.mediaCaption.capture-tab',
  'capture-screen': 'chat.mediaCaption.capture-screen',
  record: 'chat.mediaCaption.record',
  browser: 'chat.mediaCaption.browser',
}

/** Ảnh/video sinh ra bởi một lần gọi tool (nguồn thật: payload `tool_end`). */
export interface ToolMedia {
  eventSeq: number
  kind: 'image' | 'video'
  src: string
  mime: string | null
  dimensions: [number, number] | null
  artifactPath: string | null
  /**
   * P4.3 — nhãn của MODEL (`args.caption`) nếu có, ngược lại `null`. App KHÔNG bịa nhãn ảnh nữa:
   * ba chuỗi tiếng Anh viết cứng trước đây ("Sandbox Desktop Screen Capture") nói sai bản chất ảnh.
   * Chữ dựng từ từ điển do `captionKind` quyết định, và chỉ ở tầng giao diện.
   */
  caption: string | null
  /** P4.3 — loại của mảnh, khoá để tra chú thích theo ngôn ngữ câu trả lời. */
  captionKind: MediaCaptionKind
  sourceUrl?: string
  durationSec?: number
  /** D3: tệp có thật nhưng bản ghi không chạy `stop` trọn vẹn → không có số thời lượng. */
  unfinished?: boolean
}

export const FINAL_ANSWER_SUMMARY_MAX_CHARS = 600
export const FINAL_ANSWER_SUMMARY_MAX_LINES = 6

/** R2 (yêu cầu 5): số liệu của khối hoạt động — đếm từ chính dữ liệu lượt, không phải từ prop. */
export interface ActivityCounts {
  thinking: boolean
  commands: number
  captures: number
  failed: number
  unfinished: number
  /**
   * P4.4 — số mảnh bằng chứng mở được của lượt. `undefined` (không phải 0) khi lượt không mang
   * trường `evidence`: công tắt đo đang tắt, hoặc hàng nhật ký cũ, thì lượt không có số để nói.
   */
  evidence?: number
  /** P4.4 — số khẳng định cổng chấm là chưa có bằng chứng; cũng chỉ có khi cổng đã chấm. */
  unverified?: number
}

export interface ActivityReceiptPart {
  label: string
  tone: 'muted' | 'rose' | 'amber'
}

/**
 * Nhãn của dòng biên nhận: chữ do i18n cấp, hàm thuần này không tự bịa chữ.
 *
 * Vòng 23 / P5.3 — ngôn ngữ của CHÍNH câu trả lời chọn từ điển (`i18n/answerLabels.ts`), nên mọi
 * đoạn đếm đều nhận chữ từ người gọi; thiếu chữ thì hàm rơi về bản tiếng Anh như trước.
 */
export interface ActivityReceiptLabels {
  thinking: string
  commandOne: string
  commandMany: string
  captureOne: string
  captureMany: string
  failed: string
  withoutResult: string
  evidence: string
  unverified: string
}

export const ACTIVITY_TONE_CLASS: Record<ActivityReceiptPart['tone'], string> = {
  muted: 'text-zinc-400',
  rose: 'text-rose-400',
  amber: 'text-amber-400',
}

/**
 * R2: dòng biên nhận in đúng những gì đang nằm trong khối hoạt động, để việc gấp khối không
 * giấu mất chuyện "có lệnh chưa trả kết quả". Trả mảng đoạn thuần (không JSX) để kiểm thử được
 * bằng đơn vị; đoạn đếm 0 bị bỏ, không có gì thì trả mảng rỗng.
 *
 * P4.4: hai số của cổng bằng chứng đi CUỐI dòng — chúng chỉ có mặt khi lượt thật sự mang trường
 * `evidence`, còn lượt cũ thì dòng biên nhận giữ nguyên như trước.
 */
export function activityReceipt(counts: ActivityCounts, labels?: Partial<ActivityReceiptLabels>): ActivityReceiptPart[] {
  const parts: ActivityReceiptPart[] = []
  if (counts.thinking) parts.push({ label: labels?.thinking ?? 'Thinking', tone: 'muted' })
  if (counts.commands > 0) {
    const fallback = `${counts.commands} ${counts.commands === 1 ? 'command' : 'commands'}`
    parts.push({ label: (counts.commands === 1 ? labels?.commandOne : labels?.commandMany) ?? fallback, tone: 'muted' })
  }
  if (counts.captures > 0) {
    const fallback = `${counts.captures} ${counts.captures === 1 ? 'capture' : 'captures'}`
    parts.push({ label: (counts.captures === 1 ? labels?.captureOne : labels?.captureMany) ?? fallback, tone: 'muted' })
  }
  if (counts.failed > 0) parts.push({ label: labels?.failed ?? `${counts.failed} failed`, tone: 'rose' })
  if (counts.unfinished > 0) parts.push({ label: labels?.withoutResult ?? `${counts.unfinished} without result`, tone: 'amber' })
  if (counts.evidence) parts.push({ label: labels?.evidence ?? `${counts.evidence} evidence`, tone: 'muted' })
  // Khẳng định thiếu bằng chứng là chuyện phải đọc thấy: tô hổ phách như `without result`.
  if (counts.unverified) {
    parts.push({ label: labels?.unverified ?? `${counts.unverified} unverified`, tone: 'amber' })
  }
  return parts
}

/** Văn xuôi: không mở đầu bằng tiêu đề, bảng, danh sách hay trích dẫn. */
const SUMMARY_BLOCK_OPENER = /^\s*(#{1,6}\s|\||[-*+]\s|>\s?|\d+[.)]\s|```)/
const SUMMARY_SENTENCE_MARKS = ['.', '!', '?', ':', '…']

/**
 * R3 (yêu cầu 6): bộ nhận biết ranh giới tóm tắt/chi tiết đọc **cấu trúc của chính câu trả lời**.
 * Đoạn đầu tới dòng trống đầu tiên là tóm tắt khi nó là văn xuôi, nằm trong hạn 6 dòng/600 ký tự
 * và **có** phần còn lại để mở. Trả `null` khi không chắc — người gọi quay về đường cắt cũ, chứ
 * không im lặng cắt ở một chỗ vô nghĩa.
 */
export function splitAuthoredSummary(text: string): { summary: string; rest: string } | null {
  const normalized = text.replace(/\r\n/g, '\n')
  const lines = normalized.split('\n')
  const blank = lines.findIndex((line) => line.trim() === '')
  // Không có dòng trống (hoặc đoạn đầu rỗng) → không có gì tách ra.
  if (blank <= 0) return null
  const block = lines.slice(0, blank)
  const rest = lines.slice(blank).join('\n').trim()
  if (!rest) return null
  if (block.length > FINAL_ANSWER_SUMMARY_MAX_LINES) return null
  let summary = block.join('\n').trim()
  if (!summary || summary.length > FINAL_ANSWER_SUMMARY_MAX_CHARS) return null
  if (SUMMARY_BLOCK_OPENER.test(summary) || summary.includes('```')) return null
  // Đoạn kết giữa câu → lùi về mốc câu cuối cùng trong đoạn đó; không có mốc nào thì không nhận.
  if (!/[.!?:…]$/.test(summary)) {
    let cut = -1
    for (const mark of SUMMARY_SENTENCE_MARKS) cut = Math.max(cut, summary.lastIndexOf(mark))
    if (cut < 0) return null
    summary = summary.slice(0, cut + 1).trim()
    if (!summary) return null
  }
  return { summary, rest }
}

/**
 * R3: hai luật an toàn khối cho lát cắt cũ — không kết thúc trong khối ``` ``` chưa đóng và không
 * giữ nửa hàng bảng. Chỉ bỏ phần đuôi; không bao giờ làm lát cắt rỗng.
 */
function safetyTrim(summary: string): string {
  let result = summary
  const fences = (result.match(/```/g) ?? []).length
  if (fences % 2 === 1) {
    const fenceLineStart = result.lastIndexOf('\n', result.lastIndexOf('```')) + 1
    if (fenceLineStart > 0) result = result.slice(0, fenceLineStart).replace(/\s+$/, '')
  }
  const rows = result.split('\n')
  if (rows.length > 1) {
    const last = rows[rows.length - 1].trim()
    const prev = rows[rows.length - 2].trim()
    if (last.includes('|') && !last.endsWith('|') && prev.startsWith('|')) {
      result = rows.slice(0, -1).join('\n').replace(/\s+$/, '')
    }
  }
  return result || summary
}

/** F3: không bịa nội dung suy luận — chỉ nói đúng những gì model trả về. */
export function reasoningTokensNotice(reasoningTokens: number): string {
  return `Model returned ${reasoningTokens} reasoning tokens; no streamed reasoning text.`
}

/** F7: thông báo nén context ở cấp cao nhất của lượt, kèm số token thật. */
export function compactionNoticeText(data: Record<string, unknown>): string {
  const kind = String(data.kind ?? 'unchanged')
  const before = typeof data.beforeEstimate === 'number' ? data.beforeEstimate : null
  const after = typeof data.afterEstimate === 'number' ? data.afterEstimate : null
  if (kind === 'unchanged') return 'No compaction needed — context is still within budget.'
  if (kind === 'summary_failed') {
    return before === null
      ? 'Context compaction failed; the original transcript was preserved.'
      : `Context compaction failed; the original transcript was preserved (${before} tokens).`
  }
  if (before !== null && after !== null) return `Context compacted: ${before} → ${after} tokens`
  if (before !== null) return `Context compaction requested (${before} tokens)`
  return 'Context compaction applied'
}

function toMs(t?: number): number {
  if (!t) return Date.now()
  return t < 1e11 ? t * 1000 : t
}

function formatTokens(n?: number): string {
  if (typeof n !== 'number') return '0'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

function formatTime(timestamp?: number): string {
  if (!timestamp) return 'Just now'
  const d = new Date(toMs(timestamp))
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/** F4: đọc kích thước thật từ payload (`dimensions` có thể là mảng, object hay chuỗi). */
export function parseDimensions(value: unknown): [number, number] | null {
  if (Array.isArray(value) && value.length >= 2) {
    const w = Number(value[0])
    const h = Number(value[1])
    return Number.isFinite(w) && Number.isFinite(h) ? [w, h] : null
  }
  if (value && typeof value === 'object') {
    const obj = value as Record<string, unknown>
    const w = Number(obj.width ?? obj.w)
    const h = Number(obj.height ?? obj.h)
    return Number.isFinite(w) && Number.isFinite(h) && w > 0 && h > 0 ? [w, h] : null
  }
  if (typeof value === 'string') {
    const match = value.match(/(\d+)\s*[x×]\s*(\d+)/)
    if (match) return [Number(match[1]), Number(match[2])]
  }
  return null
}

const IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.webp', '.svg', '.gif']
const VIDEO_EXTENSIONS = ['.mp4', '.webm', '.mov', '.mkv']

const MIME_LABELS: Record<string, string> = {
  'image/png': 'PNG',
  'image/jpeg': 'JPEG',
  'image/jpg': 'JPEG',
  'image/webp': 'WEBP',
  'image/svg+xml': 'SVG',
  'image/gif': 'GIF',
  'video/mp4': 'MP4',
  'video/webm': 'WEBM',
  'video/quicktime': 'MOV',
}

function extensionOf(path: string): string {
  const clean = path.split('?')[0].toLowerCase()
  const dot = clean.lastIndexOf('.')
  return dot === -1 ? '' : clean.slice(dot)
}

/**
 * Vòng 23 / P4.3 — loại ảnh chụp đọc từ CHÍNH đường dẫn (`<capture root>/<kind>/<sid8>/…`, P2.1):
 * box ghi `window | tab | screen` ngay trong đường dẫn, nên không phải đoán từ tên tool — và chú
 * thích cũ ("Sandbox Desktop Screen Capture") đã nói sai với mọi ảnh chụp tab.
 */
function captureKindOf(artifactPath: string | null): MediaCaptionKind | null {
  if (!artifactPath) return null
  if (artifactPath.includes('/captures/window/')) return 'capture-window'
  if (artifactPath.includes('/captures/tab/')) return 'capture-tab'
  if (artifactPath.includes('/captures/screen/')) return 'capture-screen'
  return null
}

/** F4: nhãn `1280 × 800 · PNG` — số đo lấy từ chính `tool_end`, không hardcode. */
export function formatMediaLabel(media: Pick<ToolMedia, 'mime' | 'dimensions' | 'artifactPath' | 'durationSec' | 'kind'>): string {
  const parts: string[] = []
  if (media.dimensions) parts.push(`${media.dimensions[0]} × ${media.dimensions[1]}`)
  const ext = media.artifactPath ? extensionOf(media.artifactPath) : ''
  const mimeLabel =
    (media.mime && MIME_LABELS[media.mime.toLowerCase()]) ||
    (ext ? ext.replace('.', '').toUpperCase() : '')
  if (media.kind === 'video' && typeof media.durationSec === 'number') parts.push(`${media.durationSec}s`)
  if (mimeLabel) parts.push(mimeLabel)
  return parts.join(' · ')
}

/**
 * P4.3 (soát vòng kiểm độc lập) — MỘT khuôn đường dẫn cho mọi mảnh bằng chứng.
 *
 * Box báo tệp theo hai khuôn khác nhau: `computer_screen_capture` trả đường dẫn TUYỆT ĐỐI
 * (`/home/agent/workspace/.generated_artifacts/…`), còn `file_write` và mảnh cổng ghim trong hàng
 * `E:` trả đường dẫn TƯƠNG ĐỐI trong workspace. Danh sách bằng chứng khử trùng theo đường dẫn, nên
 * hai khuôn của CÙNG một tệp thành hai dòng: một ảnh chụp hiện hai lần và bộ đếm `N bằng chứng`
 * phồng lên so với số mảnh thật. Chuẩn hoá về khuôn tương đối — khuôn mà panel Files và mọi mảnh
 * cổng đang dùng.
 */
export function workspacePath(path: string): string {
  return path.replace(/^\/home\/agent\/workspace\//, '')
}

function boxMediaUrl(artifactPath: string): string {
  return `/__box/file/media?path=${encodeURIComponent(workspacePath(artifactPath))}`
}

/**
 * Đường dẫn tệp thật của một hàng `tool_end` (nếu có). Dùng để biết hàng `start` của một bản ghi
 * đã có hàng nào khác trong cùng lượt nói tới chưa — xem `TurnBlock` (D3).
 */
export function artifactPathOf(event: HarnessEvent | null | undefined): string | null {
  const result = event?.data?.result
  const resObj = result && typeof result === 'object' ? (result as Record<string, unknown>) : null
  if (!resObj) return null
  // Hàng `ok:false` nói về một lần gọi hỏng, không nói về một tệp có thật.
  if (resObj.ok === false) return null
  return typeof resObj.artifact === 'string' ? resObj.artifact : typeof resObj.path === 'string' ? resObj.path : null
}

/**
 * F2 + F4: ảnh/video của `tool_end` lấy từ payload thật, gắn ngay dưới hàng tool.
 *
 * `opts.allowStartMedia` chỉ có tác dụng với hàng `start` của `computer_screen_record` — hàng này
 * trả về đường dẫn tệp ĐANG ghi, không phải tệp đã đóng. Mặc định `false` để một bản ghi đã đóng
 * đúng không hiện hai player (một ở hàng `start`, một ở hàng `stop`). `TurnBlock` bật nó lên **chỉ
 * khi** trong lượt không hàng nào khác nói về chính tệp ấy — ca bản ghi bị cắt ngang
 * (`1789929795687-screen.mp4`): tệp có thật trên đĩa mà trước đây không có đường nào mở.
 */
export function extractToolMedia(
  event: HarnessEvent,
  opts?: { allowStartMedia?: boolean },
): ToolMedia | null {
  const result = event.data?.result
  const resObj = result && typeof result === 'object' ? (result as Record<string, unknown>) : null
  if (!resObj) return null
  // Hàng `ok:false` nói về một lần gọi hỏng, không nói về một tệp có thật → không có dòng media.
  if (resObj.ok === false) return null

  const name = String(event.data?.name ?? '')
  const args = event.data?.args as Record<string, unknown> | null
  const action = String(args?.action ?? '')
  const inlineImage = typeof resObj.image === 'string' ? resObj.image : null
  const artifactPath = artifactPathOf(event)
  const mime = typeof resObj.mime === 'string' ? resObj.mime : null
  const dimensions = parseDimensions(resObj.dimensions)
  const durationSec = typeof resObj.durationSec === 'number' ? resObj.durationSec : undefined

  let src: string | null = inlineImage ? `data:${mime || 'image/png'};base64,${inlineImage}` : null
  let kind: 'image' | 'video' = 'image'
  let unfinished = false
  if (!src && artifactPath) {
    const ext = extensionOf(artifactPath)
    if (VIDEO_EXTENSIONS.includes(ext)) {
      // `action=start` của computer_screen_record trả về đường dẫn tệp ĐANG ghi. Chỉ nhận nó khi
      // người gọi xác nhận không hàng nào khác trong lượt nói về chính tệp ấy; nếu không, một bản
      // ghi sẽ hiện thành hai player: một ở hàng `start`, một ở hàng `stop`.
      if (action === 'start' && !opts?.allowStartMedia) return null
      // D3: thiếu `durationSec` không có nghĩa là không có tệp. Bản ghi bị cắt ngang (`stop`
      // không trả số) vẫn là một tệp CÓ THẬT trên đĩa — bỏ nó đi là không còn đường nào mở tệp
      // đó ra. Giữ dòng media, để trống thời lượng và đánh dấu là chưa trọn.
      if (typeof durationSec !== 'number') unfinished = true
      src = boxMediaUrl(artifactPath)
      kind = 'video'
    } else if (IMAGE_EXTENSIONS.includes(ext)) {
      src = boxMediaUrl(artifactPath)
    }
  }
  if (!src) return null

  // P4.3: nhãn là chữ của MODEL (`args.caption` — chính chữ model gửi cho `computer_screen_capture`,
  // P2.3) nếu có; không có thì để `null` và chỉ giữ loại — chữ dựng từ từ điển ở tầng giao diện.
  const modelCaption = typeof args?.caption === 'string' && args.caption.trim() ? args.caption.trim() : null
  const captionKind: MediaCaptionKind =
    kind === 'video'
      ? 'record'
      : name === 'browser_use'
        ? 'browser'
        : (captureKindOf(artifactPath) ?? 'capture-screen')

  return {
    eventSeq: event.seq,
    kind,
    src,
    mime,
    dimensions,
    artifactPath,
    caption: modelCaption,
    captionKind,
    sourceUrl: typeof args?.url === 'string' ? args.url : undefined,
    durationSec,
    unfinished,
  }
}

/* ------------------------------------------------------------------ *
 * P4 — cổng bằng chứng sống: đọc `evidence` của lượt + mảnh bằng chứng
 * ------------------------------------------------------------------ */

/** Một lý do cổng chấm là thiếu bằng chứng: mã máy (`reason`) + câu backend kể (`detail`). */
export interface EvidenceMissing {
  reason: string
  detail: string
}

/**
 * Vòng kiểm độc lập (L14) — một khẳng định cổng đã ĐỌC RA từ câu trả lời, kèm bản ghi `backed`.
 *
 * `missing[]` chỉ nói ĐƯỜNG DẪN hay LỆNH nào bị ghim, không nói câu nào của câu trả lời bị ghim.
 * Bản ghi `claims[]` mới có câu đó (`text` là dòng nguyên văn, backend đã cắt trần), nên khối bằng
 * chứng phải đọc cả hai thì người đọc mới thấy mình đang bị ghim vì CÂU NÀO — đúng mặt mock `dv23`.
 */
export interface EvidenceClaim {
  text: string
  path: string | null
  command: string | null
}

/**
 * Một mảnh bằng chứng cổng đã chấm, đọc từ `evidence.artifacts[]`. Đây là dữ liệu THÔ của backend
 * (`{kind, path, command, exitCode, changed, tool, step, bytes, …}`) — không suy diễn thêm gì.
 */
export interface EvidenceFragment {
  kind: string | null
  path: string | null
  command: string | null
  /** Nhãn đọc được của mảnh: `exit N` với lệnh, chính `kind` với tệp. */
  note: string | null
  /** Tệp trong workspace mà mảnh này nói về (khác `path` = chính tệp bằng chứng). */
  changed: string | null
  tool: string | null
  /** Vân tay nội dung cổng ghim vào event (`sha256`) — bằng chứng độc lập với lời khai. */
  sha256: string | null
  /** Số byte của tệp bằng chứng, khi payload có. */
  bytes: number | null
}

/**
 * Bản đọc đã chuẩn hoá của trường `evidence` trên event `assistant` cuối lượt.
 *
 * `verdict`/`checked`/`mode` là BẢN SAO NGUYÊN VĂN của payload backend, giữ lại cho vòng "agent
 * verify" (D-20) — mặt câu trả lời không còn chỗ vẽ chúng, nhưng dữ liệu cổng vẫn đọc được từ event.
 */
export interface AnswerEvidence {
  /** Giá trị `verdict` THẬT trong event; `null` khi event có `evidence` nhưng thiếu `verdict`. */
  verdict: string | null
  checked: number | null
  /** Công tắc cổng lúc chấm lượt (`off|warn|strict`) — bản sao nguyên văn của payload. */
  mode: string | null
  turn: number | null
  missing: EvidenceMissing[]
  /** Khẳng định cổng đã đọc ra từ câu trả lời (`claims[]` của event) — nguồn của câu bị ghim. */
  claims: EvidenceClaim[]
  /** Mảnh bằng chứng cổng đã ghim cho lượt (`artifacts[]` của event). */
  artifacts: EvidenceFragment[]
  /** Tệp trong workspace mà cổng nói đã đổi ở lượt này. */
  changedFiles: string[]
}

/**
 * Năm mã `missing[].reason` là lời của CÂU TRẢ LỜI (khẳng định mà lượt này không đỡ được); sáu mã
 * còn lại là chuyện của CÁI CÂN (`box_unreachable`, `box_probe_failed`, `gate_error`,
 * `answer_too_long`, `no_evidence_for_tools`, `no_change`).
 *
 * Vòng soát đợt 3 bắt được chỗ này: dòng biên nhận khẳng định "1 khẳng định chưa kiểm" trong khi
 * lượt chỉ hỏng phép đo là nói sai về lượt — số khẳng định chỉ được đếm từ năm mã đầu, còn lý do
 * của phép đo hỏng không bao giờ là một khẳng định của câu trả lời.
 */
export const CLAIM_REASON_CODES = new Set([
  'change_without_verification',
  'claim_path_not_in_turn',
  'claim_path_missing',
  'ui_change_without_capture',
  'answer_references_unknown_command',
])

/** Lọc `missing[]` xuống đúng những lý do là khẳng định của câu trả lời. */
export function claimMissing(missing: EvidenceMissing[]): EvidenceMissing[] {
  return missing.filter((item) => CLAIM_REASON_CODES.has(item.reason))
}

function parseEvidenceMissing(value: unknown): EvidenceMissing[] {
  if (!Array.isArray(value)) return []
  const items: EvidenceMissing[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const reason = typeof item.reason === 'string' ? item.reason : ''
    if (!reason) continue
    items.push({ reason, detail: typeof item.detail === 'string' ? item.detail : '' })
  }
  return items
}

/** `artifacts[]` của event: mảnh cổng đã ghim. Mảnh không có đường dẫn lẫn lệnh thì bỏ. */
function parseEvidenceFragments(value: unknown): EvidenceFragment[] {
  if (!Array.isArray(value)) return []
  const items: EvidenceFragment[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const kind = typeof item.kind === 'string' ? item.kind : null
    const path = typeof item.path === 'string' && item.path ? item.path : null
    const command = typeof item.command === 'string' && item.command ? item.command : null
    if (!path && !command) continue
    const exitCode = typeof item.exitCode === 'number' ? item.exitCode : null
    items.push({
      kind,
      path,
      command,
      // Nhãn chỉ nói điều payload nói: `exit 3` khi có số, còn lại là chính `kind`.
      note: kind === 'command' && exitCode !== null ? `exit ${exitCode}` : kind,
      changed: typeof item.changed === 'string' && item.changed ? item.changed : null,
      tool: typeof item.tool === 'string' ? item.tool : null,
      sha256: typeof item.sha256 === 'string' && item.sha256 ? item.sha256 : null,
      bytes: typeof item.bytes === 'number' ? item.bytes : null,
    })
  }
  return items
}

/** `claims[]` của event: những câu cổng đã đọc ra. Bản ghi không có câu thì bỏ — không có gì để in. */
function parseEvidenceClaims(value: unknown): EvidenceClaim[] {
  if (!Array.isArray(value)) return []
  const items: EvidenceClaim[] = []
  for (const raw of value) {
    if (!raw || typeof raw !== 'object') continue
    const item = raw as Record<string, unknown>
    const text = typeof item.text === 'string' ? item.text.trim() : ''
    if (!text) continue
    items.push({
      text,
      path: typeof item.path === 'string' && item.path ? item.path : null,
      command: typeof item.command === 'string' && item.command ? item.command : null,
    })
  }
  return items
}

/**
 * Câu của câu trả lời đã bị cổng ghim cho một mục `missing[]`.
 *
 * `missing[].detail` CHÍNH LÀ đường dẫn hoặc lệnh mà `claims[]` ghi lại (xem `assess` của backend),
 * nên tra thẳng theo khoá đó — không đoán theo thứ tự. Không có bản ghi (phiên cũ, hoặc lý do thuộc
 * phép đo hỏng) ⇒ `null`, và mục ấy giữ nguyên lối vẽ cũ.
 */
export function chargedClaimText(claims: EvidenceClaim[], item: EvidenceMissing): string | null {
  const key = item.detail.trim()
  if (!key) return null
  const found = claims.find((claim) => claim.path === key || claim.command === key)
  return found ? found.text : null
}

/** `changedFiles[]`: backend ghi chuỗi đường dẫn, bản cũ hơn có thể ghi `{path}` — nhận cả hai. */
function parseChangedFiles(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const paths: string[] = []
  for (const raw of value) {
    if (typeof raw === 'string' && raw) paths.push(raw)
    else if (raw && typeof raw === 'object') {
      const path = (raw as Record<string, unknown>).path
      if (typeof path === 'string' && path) paths.push(path)
    }
  }
  return paths
}

/**
 * P4.2: đọc trường `evidence` của event `assistant` cuối lượt.
 *
 * Trả `null` khi lượt KHÔNG mang trường này — phiên cũ, hoặc công tắt đo đang tắt (lúc đó backend
 * không gắn `evidence` vào event). `null` là "không đo", KHÔNG phải "đã kiểm chứng": chỗ vẽ không
 * được bịa mục bằng chứng rỗng từ một lượt không đo.
 */
export function readAnswerEvidence(event: HarnessEvent | null | undefined): AnswerEvidence | null {
  const raw = event?.data?.evidence
  if (!raw || typeof raw !== 'object') return null
  const block = raw as Record<string, unknown>
  const verdict = typeof block.verdict === 'string' ? block.verdict : null
  return {
    verdict,
    checked: typeof block.checked === 'number' ? block.checked : null,
    mode: typeof block.mode === 'string' ? block.mode : null,
    turn: typeof block.turn === 'number' ? Math.trunc(block.turn) : null,
    missing: parseEvidenceMissing(block.missing),
    claims: parseEvidenceClaims(block.claims),
    artifacts: parseEvidenceFragments(block.artifacts),
    changedFiles: parseChangedFiles(block.changedFiles),
  }
}

/** Câu tiếng người cho một mã `reason`; mã lạ thì in nguyên mã, không đoán nghĩa. */
export function evidenceReasonText(t: Translate, reason: string): string {
  const key = `chat.evidenceReason.${reason}` as TKey
  const text = t(key)
  // `t()` trả CHÍNH khoá khi cả hai từ điển đều trượt, nên `text || reason` không bao giờ chạy và
  // người đọc thấy `chat.evidenceReason.<mã>` (vòng soát đợt 3, F2). Mã máy là thứ đối chiếu được
  // với log, nên nó là câu dự phòng đúng.
  return text === key ? reason : text
}

/** Đuôi tệp được coi là mảnh bằng chứng của lượt (P1.4 sinh ra chúng). */
export const EVIDENCE_FILE_EXTENSIONS = ['.diff', '.patch', '.txt', '.log', '.md', '.json']

/** Một mảnh bằng chứng mở được của lượt — đúng thứ khối `Bằng chứng` đếm và liệt kê. */
export interface TurnArtifact {
  /** Đường dẫn THẬT trên đĩa box; cũng là giá trị hook `data-artifact-path`. */
  path: string
  /** Có mặt khi mảnh này là ảnh/ghi hình: bấm mở khung xem lớn như mọi media khác. */
  media: ToolMedia | null
  /** Nhãn phụ đọc từ hàng `E:` / `artifacts[]` (`diff`, `image`, …) — không suy diễn thêm. */
  note: string | null
  /** Nguồn thật của mục, để chỗ vẽ nói được vì sao nó ở đây. */
  source: 'changed' | 'media' | 'tool' | 'journal' | 'fragment'
  /** Vân tay nội dung (`sha256`), khi cổng hoặc payload công cụ có ghim. */
  sha256: string | null
  /** Số byte của tệp bằng chứng, khi payload công cụ có ghi. */
  bytes: number | null
  /** Số dòng thêm/bớt mà công cụ báo (`numbers` của `tool_end`) — `null` khi không đo được. */
  added: number | null
  removed: number | null
}

/** Số đo của một mảnh bằng chứng, gom từ payload `tool_end` theo đường dẫn `artifact`. */
export interface TurnArtifactFact {
  sha256: string | null
  bytes: number | null
  added: number | null
  removed: number | null
}

function numberOrNull(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

/**
 * P4.3: số đo THẬT của từng mảnh bằng chứng, đọc từ `tool_end.result` của chính lượt — chỗ công cụ
 * báo nó vừa ghi tệp nào (`artifact`), `sha256After`, `added`/`removed` và số byte. Không có nguồn
 * nào khác mang những con số này: hàng `E:` chỉ ghim đường dẫn, còn event `assistant.evidence` ghim
 * `sha256`/`bytes` (đọc ở `parseEvidenceFragments`) nhưng không có số dòng.
 */
export function turnArtifactFacts(turn: HarnessTurn): Map<string, TurnArtifactFact> {
  const facts = new Map<string, TurnArtifactFact>()
  for (const item of turn.items) {
    if (item.kind !== 'tool' || !item.end) continue
    const result = item.end.data.result
    if (!result || typeof result !== 'object') continue
    const payload = result as Record<string, unknown>
    const path = typeof payload.artifact === 'string' && payload.artifact ? payload.artifact : null
    const numbers = payload.numbers
    if (!path || !numbers || typeof numbers !== 'object') continue
    const raw = numbers as Record<string, unknown>
    const sha256 = typeof raw.sha256After === 'string' && raw.sha256After ? raw.sha256After : null
    facts.set(path, {
      sha256,
      bytes: numberOrNull(raw.bytes),
      added: numberOrNull(raw.added),
      removed: numberOrNull(raw.removed),
    })
  }
  return facts
}

/** Một lệnh cổng ghi nhận đã chạy ở lượt: chữ lệnh + mã thoát/thời lượng ĐO ĐƯỢC từ chính lượt. */
export interface TurnCommand {
  command: string
  /** Mã thoát thật (từ `tool_end.result.exit_code`); `null` khi nhật ký là nguồn duy nhất. */
  exitCode: number | null
  /** Thời gian chạy thật (ms) giữa `tool_start` và `tool_end`; `null` khi thiếu một trong hai. */
  durationMs: number | null
  /** Nhãn phụ dựng từ hai số trên (`exit 0 · 2.9s`); không có số nào thì để trống, không bịa. */
  note: string | null
}

/** Số đo của một lệnh, gom theo chữ lệnh — dùng để ghép vào nhật ký cổng ghim. */
export interface TurnCommandFact {
  exitCode: number | null
  durationMs: number | null
}

/** `840ms` / `2.9s` — đủ chính xác để người đọc ước lượng, không thêm chữ thừa. */
function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/**
 * P4.3: số đo THẬT của từng lệnh trong lượt, đọc từ cặp `tool_start`/`tool_end` mà giao diện đã có
 * sẵn trong timeline. Vì sao cần: hàng `E:` của nhật ký chỉ ghim chữ lệnh (bản đang chạy còn ghim
 * `exit None` khi payload lệnh không mang mã thoát), còn event `assistant.evidence.artifacts[]`
 * cũng bỏ trống mã thoát. Hai payload đó không nói được lệnh chạy xong hay chưa, nên mặt "đã kiểm
 * chứng" phải lấy số từ chính sự kiện công cụ thay vì in một nhãn rỗng.
 */
export function turnCommandFacts(turn: HarnessTurn): Map<string, TurnCommandFact> {
  const facts = new Map<string, TurnCommandFact>()
  for (const item of turn.items) {
    if (item.kind !== 'tool' || !item.end) continue
    const args = item.end.data.args
    const command = args && typeof args === 'object' ? (args as Record<string, unknown>).command : null
    if (typeof command !== 'string' || !command) continue
    const result = item.end.data.result
    const rawExit = result && typeof result === 'object' ? (result as Record<string, unknown>).exit_code : null
    const exitCode = typeof rawExit === 'number' ? rawExit : null
    const spent = item.start && item.end.created > item.start.created ? item.end.created - item.start.created : null
    const durationMs = spent !== null && spent > 0 ? Math.round(spent * 1000) : null
    const previous = facts.get(command)
    // Lần chạy sau chỉ thay lần trước khi nó ĐO ĐƯỢC nhiều hơn (mã thoát thật thắng `null`).
    if (previous && previous.exitCode !== null) continue
    facts.set(command, { exitCode, durationMs })
  }
  return facts
}

/** Ảnh/ghi hình của lượt lấy từ payload `tool_end`, đã khử trùng theo đường dẫn. */
export function turnMediaOf(turn: HarnessTurn, startAllowed?: Set<number>): ToolMedia[] {
  const media: ToolMedia[] = []
  const seen = new Set<string>()
  for (const item of turn.items) {
    if (item.kind !== 'tool' || !item.end) continue
    const found = extractToolMedia(item.end, { allowStartMedia: Boolean(startAllowed?.has(item.end.seq)) })
    const key = found?.artifactPath ?? found?.src ?? ''
    if (!found || seen.has(key)) continue
    seen.add(key)
    media.push(found)
  }
  return media
}

/**
 * P4.3: mọi mảnh bằng chứng MỞ ĐƯỢC của một lượt, gom từ các nguồn thật — không nguồn nào là
 * phỏng đoán:
 *
 *  (a) ảnh/ghi hình đã có của lượt (payload `tool_end`, `opts.media` do `TurnBlock` đưa xuống để
 *      không tính lại và để dùng đúng luật `allowStartMedia` của D3);
 *  (b) tệp bằng chứng sinh trong lượt (`artifact` của `tool_end` với đuôi trong
 *      `EVIDENCE_FILE_EXTENSIONS`) — đây là `.diff` mà cổng đã ghim;
 *  (c) mảnh cổng ghim trong hàng `E:` của lượt (`evidence[]`, và `data.artifacts[]` nếu có);
 *  (d) `artifacts[]`/`changedFiles[]` của chính event `assistant` — cổng ghim vào event trước khi
 *      ghim nhật ký, và nhật ký có thể đang `degraded`, nên đọc cả hai đường là đọc đúng thực tế;
 *  (e) tệp trong workspace mà cổng nói đã đổi (`changedFiles`) — người đọc quan tâm tệp nguồn, và
 *      mở được nó trong Files là cách kiểm chứng độc lập với chính lời khai của agent.
 *
 * Khử trùng theo đường dẫn, giữ thứ tự gặp: một đường dẫn chỉ hiện một lần dù nhiều nguồn nhắc.
 */
export function collectTurnArtifacts(
  turn: HarnessTurn,
  opts?: {
    media?: ToolMedia[]
    evidenceRow?: JournalRow | null
    evidence?: AnswerEvidence | null
    facts?: Map<string, TurnArtifactFact>
  },
): TurnArtifact[] {
  const items: TurnArtifact[] = []
  const seen = new Set<string>()
  const media = opts?.media ?? turnMediaOf(turn)
  const facts = opts?.facts
  const mediaOf = (path: string) =>
    media.find((m) => m.artifactPath && workspacePath(m.artifactPath) === workspacePath(path)) ?? null
  const push = (artifact: {
    path: string
    media: ToolMedia | null
    note: string | null
    source: TurnArtifact['source']
    sha256?: string | null
    bytes?: number | null
  }) => {
    // Khử trùng theo đường dẫn ĐÃ CHUẨN HOÁ: payload ảnh của box là đường dẫn tuyệt đối, mảnh cổng
    // ghim là đường dẫn tương đối — so thô thì cùng một ảnh hiện hai dòng (`workspacePath`).
    const path = workspacePath(artifact.path)
    if (!path || seen.has(path)) return
    seen.add(path)
    // Số đo ghép từ hai nguồn thật: payload công cụ (`facts`) và mảnh cổng ghim vào event.
    const fact = facts?.get(path) ?? facts?.get(artifact.path) ?? null
    items.push({
      ...artifact,
      path,
      sha256: artifact.sha256 ?? fact?.sha256 ?? null,
      bytes: artifact.bytes ?? fact?.bytes ?? null,
      added: fact?.added ?? null,
      removed: fact?.removed ?? null,
    })
  }

  // (e) tệp nguồn đã đổi: đứng đầu danh sách vì đây là thứ người đọc hỏi tới.
  for (const path of opts?.evidence?.changedFiles ?? []) {
    push({ path, media: mediaOf(path), note: null, source: 'changed' })
  }
  for (const fragment of opts?.evidence?.artifacts ?? []) {
    if (fragment.changed) push({ path: fragment.changed, media: mediaOf(fragment.changed), note: null, source: 'changed' })
  }
  // (a) ảnh/ghi hình của lượt.
  for (const found of media) {
    if (!found.artifactPath) continue
    push({ path: found.artifactPath, media: found, note: null, source: 'media' })
  }
  // (b) tệp bằng chứng sinh trong lượt.
  for (const item of turn.items) {
    if (item.kind !== 'tool' || !item.end) continue
    const path = artifactPathOf(item.end)
    if (!path || !EVIDENCE_FILE_EXTENSIONS.includes(extensionOf(path))) continue
    push({ path, media: mediaOf(path), note: null, source: 'tool' })
  }
  // (c) mảnh cổng ghim trong hàng `E:` — và (d) mảnh trong chính event, chỗ duy nhất có
  // `sha256`/`bytes`, nên mỗi đường dẫn tra một lần ngay tại nguồn của nó.
  const row = opts?.evidenceRow
  const fragments = opts?.evidence?.artifacts ?? []
  const pushJournal = (path: string | null | undefined, note: string | null) => {
    if (!path) return
    const fragment = fragments.find((item) => item.path === path)
    push({
      path,
      media: mediaOf(path),
      note,
      source: 'journal',
      sha256: fragment?.sha256 ?? null,
      bytes: fragment?.bytes ?? null,
    })
  }
  for (const fragment of row?.evidence ?? []) pushJournal(fragment.path, fragment.note)
  const dataArtifacts = row?.data?.artifacts
  if (Array.isArray(dataArtifacts)) {
    for (const raw of dataArtifacts) {
      if (!raw || typeof raw !== 'object') continue
      const item = raw as Record<string, unknown>
      if (typeof item.path === 'string') pushJournal(item.path, null)
      if (typeof item.changed === 'string') pushJournal(item.changed, null)
    }
  }
  for (const fragment of fragments) pushJournal(fragment.path, fragment.note)
  return items
}

/**
 * P4.3: các lệnh cổng ghi nhận đã chạy ở lượt. Hai đường đọc cùng một sự thật: hàng `E:` của nhật
 * ký (`evidence[]` kiểu `command`, nhãn `exit N`) và `artifacts[]` của event (kiểu `command`, có
 * `exitCode`). Nguồn thứ ba — `facts` từ `turnCommandFacts` — mới là chỗ có mã thoát và thời lượng
 * thật; khi có, nó thắng nhãn của payload vì payload thường chỉ có chữ lệnh.
 */
export function collectTurnCommands(
  evidenceRow?: JournalRow | null,
  evidence?: AnswerEvidence | null,
  facts?: Map<string, TurnCommandFact>,
): TurnCommand[] {
  const items: TurnCommand[] = []
  const seen = new Set<string>()
  const push = (command: string, fallback: string | null) => {
    if (!command || seen.has(command)) return
    seen.add(command)
    const fact = facts?.get(command) ?? null
    const exitCode = fact?.exitCode ?? exitCodeOfNote(fallback)
    const durationMs = fact?.durationMs ?? null
    const note = [
      exitCode !== null ? `exit ${exitCode}` : null,
      durationMs !== null ? formatMs(durationMs) : null,
    ].filter(Boolean).join(' · ')
    items.push({ command, exitCode, durationMs, note: note || null })
  }
  for (const fragment of evidenceRow?.evidence ?? []) {
    if (fragment.type === 'command') push(fragment.command ?? '', fragment.note)
  }
  for (const fragment of evidence?.artifacts ?? []) {
    if (fragment.kind === 'command') push(fragment.command ?? '', fragment.note)
  }
  return items
}

/** `exit 0` → 0; mọi nhãn khác (kể cả `exit None` của payload hỏng) → không có số. */
function exitCodeOfNote(note: string | null): number | null {
  const matched = note ? /^exit (\d+)$/.exec(note.trim()) : null
  return matched ? Number(matched[1]) : null
}

function resolveProvider(modelId?: string, connectionId?: string, snapshot?: ProviderSnapshot | null, providerId?: string): string {
  // Vòng 29 — tuyến provider (`{providerId, modelId}`) không có `connectionId` nào để dò ngược:
  // `providerId` của route là câu trả lời trực tiếp. Connection THẬT đã phục vụ lượt vẫn đọc
  // được ở `turn.target.connectionId` (khung `boxfox` của event `usage`).
  if (providerId) return providerId
  if (connectionId && snapshot?.connections) {
    const conn = snapshot.connections.find((c) => c.id === connectionId)
    if (conn?.providerId) return conn.providerId
  }
  const m = (modelId || '').toLowerCase()
  if (m.includes('gemini') || m.includes('google')) return 'gemini'
  if (m.includes('claude') || m.includes('anthropic')) return 'anthropic'
  if (m.includes('gpt') || m.includes('openai') || m.includes('o1') || m.includes('o3')) return 'openai'
  if (m.includes('antigravity') || m.includes('boxfox')) return 'antigravity'
  return 'antigravity'
}

function getToolDisplay(name: string, args: Record<string, unknown> | null, isError: boolean): {
  actionLabel: string
  detailLabel: string
  icon: React.ReactNode
} {
  switch (name) {
    case 'terminal_exec': {
      const cmd = String(args?.command || args?.cmd || 'command')
      const shortCmd = cmd.length > 38 ? cmd.slice(0, 35) + '...' : cmd
      return {
        actionLabel: 'Ran',
        detailLabel: shortCmd,
        icon: <Terminal className="size-3.5 text-brand" />,
      }
    }
    case 'file_write':
    case 'file_edit': {
      const path = String(args?.path || args?.target || 'file')
      const fileName = path.split(/[/\\]/).pop() || path
      return {
        actionLabel: 'Edited',
        detailLabel: fileName,
        icon: <FileText className="size-3.5 text-amber-400" />,
      }
    }
    case 'file_read': {
      const path = String(args?.path || args?.target || 'file')
      const fileName = path.split(/[/\\]/).pop() || path
      return {
        actionLabel: 'Explored',
        detailLabel: fileName,
        icon: <FileText className="size-3.5 text-sky-400" />,
      }
    }
    case 'codebase_grep':
    case 'codebase_glob': {
      const q = String(args?.query || args?.pattern || 'patterns')
      return {
        actionLabel: 'Explored',
        detailLabel: `codebase (${q})`,
        icon: <Search className="size-3.5 text-purple-400" />,
      }
    }
    case 'computer_screen_capture': {
      return {
        actionLabel: 'Captured',
        detailLabel: 'sandbox display',
        icon: <Camera className="size-3.5 text-blue-400" />,
      }
    }
    case 'computer_screen_record': {
      return {
        actionLabel: 'Recorded',
        detailLabel: 'sandbox display',
        icon: <Film className="size-3.5 text-fuchsia-400" />,
      }
    }
    case 'browser_use': {
      return {
        actionLabel: 'Explored',
        detailLabel: 'browser page',
        icon: <Camera className="size-3.5 text-emerald-400" />,
      }
    }
    case 'delegate_task': {
      return {
        actionLabel: 'Delegated',
        detailLabel: `specialist (${String(args?.role || 'agent')})`,
        icon: <BrainCircuit className="size-3.5 text-brand" />,
      }
    }
    // P4 — công cụ của chế độ Research: một hàng vẫn hiện đủ, nhưng dòng GOM phía trên
    // (`researchActivity`) mới là thứ cho biết nhịp tìm/đọc của run.
    case 'web_search':
    case 'paper_citations':
    case 'research_search': {
      const q = String(args?.query || args?.q || args?.topic || 'queries')
      return {
        actionLabel: 'Searched',
        detailLabel: q.length > 38 ? q.slice(0, 35) + '...' : q,
        icon: <Search className="size-3.5 text-brand" />,
      }
    }
    case 'web_fetch':
    case 'research_read': {
      const url = String(args?.url || args?.source || args?.path || 'source')
      const short = url.length > 38 ? url.slice(0, 35) + '...' : url
      return {
        actionLabel: 'Read source',
        detailLabel: short,
        icon: <FileText className="size-3.5 text-sky-400" />,
      }
    }
    case 'research_brief':
    case 'research_status': {
      return {
        actionLabel: 'Research state',
        detailLabel: String(args?.researchId || 'run'),
        icon: <BrainCircuit className="size-3.5 text-brand" />,
      }
    }
    case 'research_scope': {
      return {
        actionLabel: 'Scope card',
        detailLabel: String(args?.action || 'update'),
        icon: <FileText className="size-3.5 text-amber-400" />,
      }
    }
    case 'research_update':
    case 'research_branch_report': {
      return {
        actionLabel: 'Recorded evidence',
        detailLabel: String(args?.questionId || args?.facetId || 'claim'),
        icon: <FileText className="size-3.5 text-emerald-400" />,
      }
    }
    case 'dossier_write': {
      return {
        actionLabel: 'Wrote dossier',
        detailLabel: String(args?.version ? `v${String(args.version)}` : 'report'),
        icon: <FileText className="size-3.5 text-emerald-400" />,
      }
    }
    default: {
      return {
        actionLabel: isError ? 'Failed' : 'Executed',
        detailLabel: name,
        icon: <Terminal className="size-3.5 text-brand" />,
      }
    }
  }
}

/** F6 + R3 (yêu cầu 6): tóm tắt do chính câu trả lời viết, hoặc lát cắt cũ có luật an toàn khối. */
export function summarizeFinalText(text: string): { summary: string; truncated: boolean } {
  const normalized = text.replace(/\r\n/g, '\n')

  // R3: đoạn đầu nguyên văn của chính câu trả lời là tóm tắt — không rút gọn, không viết lại.
  const authored = splitAuthoredSummary(normalized)
  if (authored) return { summary: authored.summary, truncated: true }

  // Không nhận ra cấu trúc → giữ nguyên đường cắt hôm nay (6 dòng, rồi 600 ký tự)…
  const lines = normalized.split('\n')
  const cutOff =
    lines.length > FINAL_ANSWER_SUMMARY_MAX_LINES || normalized.length > FINAL_ANSWER_SUMMARY_MAX_CHARS
  let summary = lines.slice(0, FINAL_ANSWER_SUMMARY_MAX_LINES).join('\n')
  if (summary.length > FINAL_ANSWER_SUMMARY_MAX_CHARS) {
    summary = summary.slice(0, FINAL_ANSWER_SUMMARY_MAX_CHARS)
  }
  // …cộng hai luật an toàn khối, để lát cắt không rơi vào giữa khối code hay nửa hàng bảng.
  if (cutOff) summary = safetyTrim(summary)
  const truncated = summary.length < normalized.length
  return {
    summary: truncated ? summary.replace(/\s+$/, '') + '…' : normalized,
    truncated,
  }
}

function applyTimelineEvent(turn: HarnessTurn, event: HarnessEvent) {
  // F5: thời lượng chỉ được cộng khi lượt CHƯA kết thúc. Event `finish`/`error` đầu tiên
  // vẫn chốt được mốc kết thúc (kể cả khi `assistant` final đã tới trước đó), nhưng sau đó
  // lượt đóng băng — không còn bị kéo dài bởi event tới muộn (lượt cancel 36s từng hiện 1702s).
  const terminal = event.type === 'finish' || event.type === 'error'
  const firstTerminal = terminal && !turn.finish && !turn.error
  if (!turn.isCompleted || firstTerminal) {
    turn.endTime = Math.max(turn.endTime, event.created)
  }

  switch (event.type) {
    case 'thought': {
      // Event có thể là văn bản tích luỹ (harness cũ) hoặc mảnh rời (harness mới).
      turn.thought = appendStreamText(turn.thought ?? '', String(event.data.text ?? ''))
      return
    }
    case 'usage': {
      turn.usage = event.data.usage as HarnessTurn['usage']
      turn.target =
        (event.data.target as HarnessTurn['target']) || (event.data.model ? { modelId: String(event.data.model) } : null)
      return
    }
    case 'assistant_delta': {
      const text = String(event.data.text ?? '')
      const last = turn.items[turn.items.length - 1]
      if (last && last.kind === 'text' && last.live) {
        last.text = appendStreamText(last.text, text)
      } else {
        turn.items.push({ kind: 'text', id: `text_${event.seq}`, seq: event.seq, text, live: true })
      }
      return
    }
    case 'assistant': {
      if (event.data.thought) turn.thought = String(event.data.thought)
      const text = String(event.data.text ?? '')
      const isFinal = event.data.final !== false
      const last = turn.items[turn.items.length - 1]
      if (isFinal) {
        turn.finalAssistant = event
        turn.isCompleted = true
        // Văn bản đang stream chính là câu trả lời cuối: bỏ khỏi timeline để không lặp.
        if (last && last.kind === 'text' && (last.live || (text && text.startsWith(last.text)))) {
          turn.items.pop()
        }
      } else if (last && last.kind === 'text') {
        // Event `assistant` (final:false) là bản đầy đủ của đúng đoạn vừa stream.
        last.text = text
        last.live = false
      } else if (text) {
        turn.items.push({ kind: 'text', id: `text_${event.seq}`, seq: event.seq, text, live: false })
      }
      return
    }
    case 'tool_start': {
      turn.items.push({
        kind: 'tool',
        id: `tool_${event.data.id ?? event.seq}`,
        seq: event.seq,
        start: event,
        end: null,
      })
      return
    }
    case 'tool_end': {
      const callId = event.data.id
      const pending = findPendingTool(turn, callId)
      if (pending) pending.end = event
      else turn.items.push({ kind: 'tool', id: `tool_${event.seq}`, seq: event.seq, start: null, end: event })
      return
    }
    case 'child': {
      turn.items.push({ kind: 'child', id: `child_${event.seq}`, seq: event.seq, event })
      return
    }
    case 'plan_written': {
      // Chip kế hoạch trong transcript — bấm để mở đúng bản vừa ghi ở tab Plan.
      turn.items.push({ kind: 'plan', id: `plan_${event.seq}`, seq: event.seq, event })
      return
    }
    case 'decision_requested': {
      turn.items.push({
        kind: 'decision',
        id: `decision_${String(event.data.decisionId ?? event.seq)}`,
        seq: event.seq,
        event,
      })
      return
    }
    case 'decision_resolved': {
      // Một hàng duy nhất cho mỗi quyết định: cập nhật tại chỗ, không thêm hàng mới.
      const existing = turn.items.find(
        (item): item is Extract<TurnTimelineItem, { kind: 'decision' }> =>
          item.kind === 'decision' && item.event.data.decisionId === event.data.decisionId,
      )
      if (existing) existing.resolution = event
      else {
        turn.items.push({
          kind: 'decision',
          id: `decision_${String(event.data.decisionId ?? event.seq)}`,
          seq: event.seq,
          event,
          resolution: event,
        })
      }
      return
    }
    case 'compression': {
      turn.items.push({ kind: 'compression', id: `compaction_${event.seq}`, seq: event.seq, event })
      return
    }
    case 'notice': {
      // Harness báo thử lại yêu cầu model: câu trả lời vừa stream bị bỏ, nên phần văn bản
      // đang hiện của lượt này phải biến mất — nếu không, câu trả lời mới bị dán vào phần cũ.
      if (event.data.reset) {
        while (turn.items.length > 0) {
          const last = turn.items[turn.items.length - 1]
          if (last.kind !== 'text' || !last.live) break
          turn.items.pop()
        }
        turn.thought = ''
      }
      turn.items.push({ kind: 'notice', id: `notice_${event.seq}`, seq: event.seq, event })
      return
    }
    case 'finish': {
      turn.finish = event
      turn.isCompleted = true
      return
    }
    case 'error': {
      turn.error = String(event.data?.message ?? 'Turn execution error')
      turn.isCompleted = true
      return
    }
    default:
      // `step`, `command_resolved`, `skill_loaded`, `executor`... chỉ là telemetry.
      return
  }
}

function findPendingTool(turn: HarnessTurn, callId: unknown): Extract<TurnTimelineItem, { kind: 'tool' }> | null {
  for (let i = turn.items.length - 1; i >= 0; i -= 1) {
    const item = turn.items[i]
    if (item.kind === 'tool' && !item.end && (item.start?.data.id === callId || callId === undefined)) return item
  }
  return null
}

/**
 * Một hàng cho mỗi quyết định của agent: câu hỏi nằm ngay chỗ nó được hỏi, và
 * một nút mở tab Decisions tại đúng yêu cầu đó. Trạng thái đọc từ
 * `decision_resolved` thật — không có bộ đếm hạn nào do giao diện bịa.
 */
function DecisionRow({
  event,
  resolution,
  onOpenTab,
}: {
  event: HarnessEvent
  resolution?: HarnessEvent
  onOpenTab?: (tab: TranscriptTabId, target?: Record<string, unknown> | null) => void
}) {
  const t = useT()
  const data = event.data ?? {}
  const decisionId = String(data.decisionId ?? '')
  const question = String(data.question ?? data.action ?? '')
  const kind = String(data.kind ?? 'question')
  const status = resolution ? String(resolution.data?.status ?? '') : 'pending'
  const timedOut = resolution ? String(resolution.data?.reason ?? '') === 'timeout' : false

  const statusLabel = timedOut
    ? t('decisions.status.expired')
    : status === 'approved'
      ? t('decisions.status.approved')
      : status === 'rejected'
        ? t('decisions.status.rejected')
        : status === 'cancelled'
          ? t('decisions.status.cancelled')
          : t('decisions.status.pending')

  return (
    <div
      data-timeline="decision"
      data-decision-id={decisionId || undefined}
      data-decision-status={status}
      className="max-w-2xl rounded-lg border border-amber-500/45 bg-amber-500/5 px-2.5 py-2"
    >
      <div className="flex items-center gap-2 text-[11px] font-semibold text-amber-700 dark:text-amber-300">
        <span
          className={`size-1.5 rounded-full bg-amber-500 ${status === 'pending' ? 'animate-pulse' : 'opacity-50'}`}
        />
        <span>
          {status === 'pending'
            ? t('chat.decisionWaiting')
            : `${kind === 'approval' ? t('decisions.kind.approval') : t('decisions.kind.question')} · ${statusLabel}`}
        </span>
      </div>
      {question && <p className="mt-1 text-xs leading-relaxed text-fg select-text">{question}</p>}
      <div className="mt-1.5 flex items-center gap-2">
        <button
          type="button"
          onClick={() => onOpenTab?.('decisions', decisionId ? { requestId: decisionId } : null)}
          className="group inline-flex items-center gap-1 rounded-md border border-line bg-panel px-2 py-0.5 text-[11px] font-medium text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
        >
          <ShieldAlert className="size-3" />
          <span className="group-hover:underline">{t('chat.openDecisionTab')}</span>
          <ChevronRight className="size-3 opacity-0 transition group-hover:opacity-100" />
        </button>
        {resolution && (
          <span className="font-mono text-[10px] text-muted">{statusLabel}</span>
        )}
      </div>
    </div>
  )
}

function emptyTurn(id: string, modelChange: { from: string; to: string } | null, userEvent: HarnessEvent | null, created: number): HarnessTurn {
  return {
    id,
    modelChange,
    userEvent,
    thought: null,
    items: [],
    finalAssistant: null,
    usage: null,
    target: null,
    finish: null,
    startTime: created,
    endTime: created,
    isCompleted: false,
  }
}

function sortItems(items: TurnTimelineItem[]): TurnTimelineItem[] {
  return [...items].sort((a, b) => a.seq - b.seq)
}

/** F2 + F5: nhóm event thành lượt theo `user`, dựng timeline phẳng theo `seq`. */
export function buildHarnessTurns(events: HarnessEvent[]): HarnessTurn[] {
  const list: HarnessTurn[] = []
  let current: HarnessTurn | null = null
  let pendingModelChange: { from: string; to: string } | null = null
  // `command_resolved` được phát TRƯỚC `user` ở mọi lượt. F5: không dựng lượt "ma" từ
  // những event này — chỉ gắn vào lượt kế tiếp (và chúng vốn không được vẽ).
  let preUserEvents: HarnessEvent[] = []

  const closeTurn = () => {
    if (!current) return
    current.items = sortItems(current.items)
    list.push(current)
    current = null
  }

  for (const event of events) {
    if (event.type === 'model_change') {
      pendingModelChange = { from: String(event.data.from || ''), to: String(event.data.to || '') }
      continue
    }

    if (event.type === 'user') {
      // Chỉ thị giữa lượt (`{control:true, steer:true}`) KHÔNG mở lượt mới và không đếm thêm lượt:
      // nó là một hàng của lượt đang chạy, đúng vị trí `seq` (C-5). Chưa có lượt nào để gắn (transcript
      // cũ/thiếu) thì rơi về đường cũ — vẫn phải hiển thị, không được nuốt mất câu của chủ nhà.
      if (event.data?.steer === true && current) {
        current.items.push({ kind: 'user_steer', id: `steer_${event.seq}`, seq: event.seq, event })
        continue
      }
      closeTurn()
      current = emptyTurn(`turn_${event.seq}`, pendingModelChange, event, event.created)
      pendingModelChange = null
      preUserEvents = []
      continue
    }

    if (!current) {
      preUserEvents.push(event)
      continue
    }

    applyTimelineEvent(current, event)
  }

  closeTurn()

  // Fallback: transcript không có event `user` nào (dữ liệu cũ/không đầy đủ) — vẫn phải
  // hiển thị thay vì làm mất toàn bộ nội dung.
  if (list.length === 0 && preUserEvents.length > 0) {
    const fallback = emptyTurn('turn_pre_user', pendingModelChange, null, preUserEvents[0].created)
    for (const event of preUserEvents) applyTimelineEvent(fallback, event)
    fallback.items = sortItems(fallback.items)
    list.push(fallback)
  }

  return list
}

export function HarnessStepView({
  events,
  status,
  error,
  sessionId,
  connectionWarning,
  onDismissWarning,
  onOpenLightbox,
  snapshot,
  selection,
  onOpenTab,
  journal,
}: HarnessStepViewProps) {
  const isBusy = status === 'running' || status === 'starting'
  const t = useT()

  const turns = useMemo(() => buildHarnessTurns(events), [events])

  return (
    <div className="space-y-6 font-sans select-text">
      {turns.map((turn, index) => {
        const isLastTurn = index === turns.length - 1
        const isTurnBusy = isLastTurn && isBusy && !turn.isCompleted

        return (
          <div key={turn.id} data-turn-latest={isLastTurn ? 'true' : undefined} data-turn-user="true">
            <TurnBlock
              turn={turn}
              sessionId={sessionId ?? null}
              ordinal={index + 1}
              isTurnBusy={isTurnBusy}
              onOpenLightbox={onOpenLightbox}
              snapshot={snapshot}
              selection={selection}
              onOpenTab={onOpenTab}
              journal={journal ?? null}
            />
          </div>
        )
      })}

      {/* P4.1: nhật ký bền của box không ghi được ở phiên này (`degraded` của khối `journal`).
          Nuốt cờ này đi là để người đọc tin nhầm rằng bằng chứng nào cũng đã được ghim. */}
      {journal?.degraded && (
        <div className="flex items-start gap-1.5 py-1 text-[11px] text-zinc-500 select-text" data-journal-degraded="true">
          <ShieldAlert className="mt-0.5 size-3 shrink-0" />
          <span>{t('chat.evidenceJournalDegraded')}</span>
        </div>
      )}

      {/* Provider Connection Warning / Error: báo cùng chữ đỏ inline, không tạo box mới, tự động ẩn khi chat mới / đang chạy */}
      {!isBusy && connectionWarning && (
        <div className="flex items-center justify-between gap-2 py-1 text-xs text-rose-400 font-sans leading-relaxed select-text animate-in fade-in duration-150">
          <span className="flex-1">{connectionWarning}</span>
          {onDismissWarning && (
            <button
              type="button"
              onClick={onDismissWarning}
              className="text-zinc-500 hover:text-zinc-300 transition p-0.5 rounded cursor-pointer shrink-0"
              title="Đóng cảnh báo"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>
      )}

      {/* Global Error: only show if the session is currently failed AND error is not already shown in any turn AND not busy */}
      {!isBusy && status === 'failed' && error && !turns.some(t => t.error === error) && (
        <div className="py-1.5 text-xs text-rose-400 font-sans leading-relaxed select-text animate-in fade-in duration-150">
          {error}
        </div>
      )}
    </div>
  )
}

/**
 * E5 — loại tệp của chip đính kèm. Bản ghi `user.attachments` chỉ mang `name`/`path`/`sizeBytes`
 * (không có trường loại), nên chỉ dám suy từ phần mở rộng và nói "tệp" khi không chắc — thà
 * thiếu chữ còn hơn gán sai loại cho tệp của người dùng.
 */
function attachmentKindLabel(label: string): string {
  if (/\.(png|jpe?g|gif|webp|bmp|avif|svg)$/i.test(label)) return 'ảnh'
  if (/\.(txt|md|markdown|log|csv|tsv|json|ya?ml|toml|ini|pdf|docx?|xlsx?|pptx?)$/i.test(label)) {
    return 'văn bản'
  }
  return 'tệp'
}

function TurnBlock({
  turn,
  sessionId,
  ordinal,
  isTurnBusy,
  onOpenLightbox,
  snapshot,
  selection,
  onOpenTab,
  journal,
}: {
  turn: HarnessTurn
  sessionId: string | null
  /** Số thứ tự lượt trong phiên (bắt đầu từ 1) — dùng khi lượt cũ không mang `evidence.turn`. */
  ordinal: number
  isTurnBusy: boolean
  onOpenLightbox?: (media: LightboxMediaProps) => void
  snapshot?: ProviderSnapshot | null
  selection?: RouterChatSelection | null
  onOpenTab?: (tab: TranscriptTabId, target?: Record<string, unknown> | null) => void
  journal?: HarnessJournal | null
}) {
  const t = useT()
  const [copiedUser, setCopiedUser] = useState(false)
  const [copiedAssistant, setCopiedAssistant] = useState(false)
  // E5 — "Mở trong Files" dùng đúng hành động `selectFile` đã có (mở tab Files + hiện
  // bảng Workspace), không thêm đường mở tệp thứ hai.
  const selectFile = useUiStore((s) => s.selectFile)

  // Xác định Model info và Provider
  const targetModelId =
    turn.target?.modelId ??
    (selection?.kind === 'model' || selection?.kind === 'provider' ? selection.modelId : selection?.kind === 'alias' ? selection.aliasId : 'gemini-3.7-flash-high')

  const targetConnId =
    turn.target?.connectionId ??
    (selection?.kind === 'model' ? selection.connectionId : undefined)

  const providerId = resolveProvider(targetModelId, targetConnId, snapshot, selection?.kind === 'provider' ? selection.providerId : undefined)

  // F5: endTime chỉ được cộng khi lượt chưa xong.
  const durationSec = Math.max(1, Math.round((toMs(turn.endTime) - toMs(turn.startTime)) / 1000))

  // Tool đang chạy (chưa có `tool_end`) — vẫn nằm đúng vị trí trong timeline.
  const pendingTool = useMemo(
    () => turn.items.find((item) => item.kind === 'tool' && !item.end) ?? null,
    [turn.items],
  )

  // D3: hàng `start` chỉ được hiện tệp khi trong lượt KHÔNG hàng nào khác nói về chính tệp ấy.
  // Ca thật: `1789929795687-screen.mp4` (560 s) — lượt chết vì DEADLINE trước khi kịp chạy `stop`,
  // tệp nằm trên đĩa mà chat không có đường nào mở. Nhiều hàng `start` cùng một tệp thì chỉ hàng
  // đầu tiên được hiện, để một tệp không thành hai player.
  const startAllowedSeqs = useMemo(() => {
    const startSeqs = new Map<string, number[]>()
    const closed = new Set<string>()
    for (const item of turn.items) {
      if (item.kind !== 'tool' || !item.end) continue
      const path = artifactPathOf(item.end)
      if (!path) continue
      const action = String((item.end.data?.args as Record<string, unknown> | null)?.action ?? '')
      if (action === 'start') {
        startSeqs.set(path, [...(startSeqs.get(path) ?? []), item.end.seq])
      } else {
        closed.add(path)
      }
    }
    const allowed = new Set<number>()
    for (const [path, seqs] of startSeqs) {
      if (!closed.has(path)) allowed.add(Math.min(...seqs))
    }
    return allowed
  }, [turn.items])

  // T15 — đích THẬT trong `deliveries[]` là `sessionId` của người nhận. Backend chỉ phân giải
  // anh em CÙNG LƯỢT (hoặc chính phiên cha), nên bản đồ vai dựng từ chính lượt này là đủ.
  const roleOfChild = useMemo(() => {
    const roles = new Map<string, string>()
    for (const item of turn.items) {
      if (item.kind !== 'child') continue
      const id = String(item.event.data.sessionId ?? '')
      const role = String(item.event.data.role ?? '')
      if (id && role) roles.set(id, role)
    }
    return (childSessionId: string) => roles.get(childSessionId) ?? null
  }, [turn.items])

  const turnMedia = useMemo(() => turnMediaOf(turn, startAllowedSeqs), [turn, startAllowedSeqs])

  /* ---------------- P5.3: chữ của app quanh lượt đi theo ngôn ngữ CÂU TRẢ LỜI ---------------- */

  // Mặt câu trả lời cuối không còn chữ nào của app (P4.2), nên ngôn ngữ câu trả lời chỉ còn ảnh
  // hưởng tới hai chỗ: chú thích ảnh trong timeline (P4.3) và dòng biên nhận ở đầu lượt. Lượt chưa
  // có văn cuối (lượt cũ, lượt đang chạy) rơi về từ điển của ngôn ngữ giao diện — mặc định `en`.
  const answerText = String(turn.finalAssistant?.data?.text ?? '')
  const { tLabel } = useAnswerLabels(answerText)

  // P4.3: nhãn của model thắng; không có nhãn thì dựng chữ từ từ điển theo LOẠI của mảnh.
  const mediaCaption = useCallback(
    (media: ToolMedia) => media.caption ?? tLabel(MEDIA_CAPTION_KEYS[media.captionKind]),
    [tLabel],
  )

  // P4.1 — liên kết tệp bằng chứng trong câu trả lời mở tab Files đúng tệp (không mở tab trình duyệt).
  const showTab = useUiStore((s) => s.showTab)
  const openArtifactFile = useCallback((path: string) => showTab('files', { path }), [showTab])

  const reasoningTokens = typeof turn.usage?.reasoning_tokens === 'number' ? turn.usage.reasoning_tokens : 0
  const thoughtText = turn.thought && turn.thought.trim() ? turn.thought : null

  /* ---------------- P4: cổng bằng chứng của lượt ---------------- */

  // `null` = lượt không mang trường `evidence` (phiên cũ / công tắc đo tắt) — KHÔNG phải đã xác minh.
  const answerEvidence = useMemo(() => readAnswerEvidence(turn.finalAssistant), [turn.finalAssistant])

  // Số lượt để tra hàng `E:`: ưu tiên con số backend ghi trong chính event; lượt cũ không có thì
  // dùng thứ tự trong phiên (đúng cách backend đếm lượt: bắt đầu từ 1).
  const turnNumber = answerEvidence?.turn ?? ordinal
  const evidenceRow = useMemo(
    () => (answerEvidence && journal?.evidenceByTurn ? journal.evidenceByTurn[turnNumber] ?? null : null),
    [answerEvidence, journal, turnNumber],
  )

  const artifactFacts = useMemo(() => turnArtifactFacts(turn), [turn])
  const turnArtifacts = useMemo(
    () =>
      answerEvidence
        ? collectTurnArtifacts(turn, { media: turnMedia, evidenceRow, evidence: answerEvidence, facts: artifactFacts })
        : [],
    [answerEvidence, turn, turnMedia, evidenceRow, artifactFacts],
  )

  // Lệnh cổng ghi nhận đã chạy: cũng là bằng chứng, nhưng mở bằng mắt chứ không mở bằng tab.
  const commandFacts = useMemo(() => turnCommandFacts(turn), [turn])
  const turnCommands = useMemo(
    () => (answerEvidence ? collectTurnCommands(evidenceRow, answerEvidence, commandFacts) : []),
    [answerEvidence, evidenceRow, commandFacts],
  )

  // Hàng `E:` có thể mang danh sách `missing` mà event không có (event cũ hơn hàng nhật ký);
  // hợp hai nguồn, không bịa mục nào.
  const missingEvidence = useMemo(() => {
    if (!answerEvidence) return []
    if (answerEvidence.missing.length) return answerEvidence.missing
    return parseEvidenceMissing(evidenceRow?.data?.missing)
  }, [answerEvidence, evidenceRow])

  // F1 (vòng soát đợt 3): số "khẳng định chưa kiểm" chỉ đếm lý do là khẳng định — lý do của phép
  // đo hỏng không phải một khẳng định của câu trả lời.
  const unverifiedClaims = useMemo(() => claimMissing(missingEvidence), [missingEvidence])

  // R2 (yêu cầu 5): số liệu của dòng biên nhận đếm từ chính dữ liệu lượt — không có con số nào
  // được viết tay ở đây. `captures` dùng danh sách media đã khử trùng của lượt.
  const counts = useMemo<ActivityCounts>(() => {
    let commands = 0
    let failed = 0
    let unfinished = 0
    for (const item of turn.items) {
      if (item.kind !== 'tool') continue
      commands += 1
      const result = item.end?.data?.result
      if (result && typeof result === 'object' && (result as Record<string, unknown>).is_error) failed += 1
      if (!item.end && turn.isCompleted) unfinished += 1
    }
    return {
      thinking: Boolean(thoughtText),
      commands,
      captures: turnMedia.length,
      failed,
      unfinished,
      // P4.2/D-20: hai số của cổng chỉ có khi cổng đã chấm lượt này (`answerEvidence` khác null).
      // Mặt câu trả lời KHÔNG còn khối bằng chứng để đối chiếu, nên dòng biên nhận này là chỗ duy
      // nhất người đọc còn thấy số liệu cổng — nó phải đếm đúng thứ nó nói: số mảnh bằng chứng đã
      // ghim trong lượt, và số khẳng định chưa có bằng chứng.
      evidence: answerEvidence ? turnArtifacts.length + turnCommands.length : undefined,
      unverified: answerEvidence ? unverifiedClaims.length : undefined,
    }
  }, [turn.items, turn.isCompleted, thoughtText, turnMedia, answerEvidence, turnArtifacts, turnCommands, unverifiedClaims])

  const receipt = useMemo(
    () =>
      activityReceipt(counts, {
        thinking: tLabel('chat.receiptThinking'),
        commandOne: tLabel('chat.receiptCommandOne', { count: counts.commands }),
        commandMany: tLabel('chat.receiptCommandMany', { count: counts.commands }),
        captureOne: tLabel('chat.receiptCaptureOne', { count: counts.captures }),
        captureMany: tLabel('chat.receiptCaptureMany', { count: counts.captures }),
        failed: tLabel('chat.receiptFailed', { count: counts.failed }),
        withoutResult: tLabel('chat.receiptWithoutResult', { count: counts.unfinished }),
        evidence: tLabel('chat.evidenceReceiptCount', { count: counts.evidence ?? 0 }),
        unverified: tLabel('chat.evidenceReceiptUnverified', { count: counts.unverified ?? 0 }),
      }),
    [counts, tLabel],
  )

  // Khối hoạt động: mở khi lượt đang chạy, gấp còn dòng biên nhận khi lượt xong — nhưng ý định
  // của người dùng thắng: đã bấm thì không tự đổi nữa.
  const hasActivity = Boolean(thoughtText) || turn.items.length > 0 || isTurnBusy
  const [activityOpen, setActivityOpen] = useState(() => !turn.isCompleted)
  const [activityTouched, setActivityTouched] = useState(false)
  useEffect(() => {
    if (!activityTouched && turn.isCompleted) setActivityOpen(false)
  }, [turn.isCompleted, activityTouched])

  const handleCopyUser = () => {
    const text = String(turn.userEvent?.data?.text ?? '')
    if (!text) return
    navigator.clipboard.writeText(text)
    setCopiedUser(true)
    setTimeout(() => setCopiedUser(false), 2000)
  }

  const handleCopyAssistant = () => {
    const text = String(turn.finalAssistant?.data?.text ?? '')
    if (!text) return
    navigator.clipboard.writeText(text)
    setCopiedAssistant(true)
    setTimeout(() => setCopiedAssistant(false), 2000)
  }

  const userImage = turn.userEvent?.data?.image as string | undefined
  // A10: một lượt có thể mang NHIỀU ảnh (`images`) — bản ghi cũ chỉ có `image` số ít, và
  // lượt cũ không có `attachments`: cả hai trường hợp phải render y như trước.
  const rawUserImages = turn.userEvent?.data?.images
  const userImages = Array.isArray(rawUserImages)
    ? (rawUserImages.filter((item) => typeof item === 'string') as string[])
    : userImage
      ? [userImage]
      : []
  const rawAttachments = turn.userEvent?.data?.attachments
  const userAttachments = Array.isArray(rawAttachments)
    ? (rawAttachments.filter(
        (item): item is { name?: string; path?: string; sizeBytes?: number } =>
          Boolean(item) && typeof item === 'object',
      ))
    : []

  return (
    <div className="space-y-4">
      {/* 0. Model Changed Notice (if model was changed before this turn) */}
      {turn.modelChange && (
        <div className="flex items-center justify-center gap-2 py-1.5 select-none animate-in fade-in duration-200">
          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-panel2 border border-line text-zinc-400 text-[11px] shadow-2xs">
            <Hexagon className="size-3.5 text-brand" />
            <span>
              Model changed from <strong className="text-zinc-200 font-medium">{turn.modelChange.from}</strong> to <strong className="text-zinc-200 font-medium">{turn.modelChange.to}</strong>
            </span>
          </div>
        </div>
      )}

      {/* 1. User Prompt Bubble — Căn phải, chiếm tối đa 2/3 khung chat */}
      {turn.userEvent && (
        <div className="flex flex-col items-end gap-1.5 ml-auto max-w-[68%]">
          <div className="w-fit rounded-2xl bg-panel2 border border-line px-4 py-3 text-xs leading-relaxed text-fg shadow-xs">
            {userImages.map((src, index) => (
              <div
                key={`user-image-${index}`}
                onClick={() => onOpenLightbox?.({ type: 'image', src, caption: 'Attached image' })}
                className="mb-2 max-w-sm cursor-pointer overflow-hidden rounded-xl border border-line/80 bg-panel hover:border-brand/60 transition shadow-xs group"
                title="Nhấp vào để phóng to ảnh"
              >
                <img
                  src={src}
                  alt="Attached"
                  className="w-full object-cover max-h-56 rounded-lg group-hover:scale-[1.02] transition duration-200"
                />
              </div>
            ))}
            <MarkdownRenderer content={String(turn.userEvent.data.text ?? '')} />
            {/* A10: chip tệp đính kèm của lượt — người dùng phải thấy tệp nào ĐÃ tới box.
                `title` là đường dẫn tuyệt đối để đối chiếu với đường dẫn agent đọc.
                E5: hàng đọc `đường dẫn · dung lượng · loại` và có nút Mở trong Files. */}
            {userAttachments.length > 0 && (
              <div data-testid="user-attachments" className="mt-2 flex flex-col gap-1">
                {userAttachments.map((file, index) => {
                  const path = typeof file.path === 'string' ? file.path : ''
                  const name = typeof file.name === 'string' && file.name ? file.name : path
                  const sizeBytes = typeof file.sizeBytes === 'number' ? file.sizeBytes : undefined
                  const label = path || name
                  const kind = attachmentKindLabel(label)
                  return (
                    <div
                      key={`user-attachment-${index}`}
                      data-testid="user-attachment-chip"
                      data-attachment-path={path || undefined}
                      title={path ? absoluteWorkspacePath(path) : undefined}
                      className="flex items-center gap-1.5 rounded-lg border border-line/80 bg-panel px-2 py-1 text-[10px] text-muted"
                    >
                      <FileText className="size-3 shrink-0" />
                      <span className="truncate font-mono text-fg" data-testid="user-attachment-name">
                        {label}
                      </span>
                      {sizeBytes !== undefined && (
                        <span className="shrink-0">
                          <span className="text-zinc-600">{' · '}</span>
                          {formatAttachmentSize(sizeBytes)}
                        </span>
                      )}
                      {kind && (
                        <span className="shrink-0">
                          <span className="text-zinc-600">{' · '}</span>
                          {kind}
                        </span>
                      )}
                      {/* Mở đúng tệp trong tab Files — chính hành động `selectFile` mà nút
                          [👁 View] trong chat đang dùng (mở tab Files + hiện bảng Workspace).
                          Không có đường dẫn thật thì không có nút: không bịa đường dẫn. */}
                      {path && (
                        <button
                          type="button"
                          data-testid="user-attachment-open-files"
                          onClick={() => selectFile(path)}
                          title={`Mở ${path} trong tab Files`}
                          className="ml-auto inline-flex shrink-0 cursor-pointer items-center gap-0.5 rounded border border-line/80 bg-panel2 px-1.5 py-0.5 text-[10px] text-muted transition hover:border-brand/60 hover:text-fg"
                        >
                          <FolderOpen className="size-3" />
                          Mở trong Files
                        </button>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* User Bubble Footer */}
          <div className="flex items-center gap-2 text-[10px] text-muted pr-1 select-none">
            <span>{formatTime(turn.userEvent.created)}</span>
            <button
              type="button"
              onClick={handleCopyUser}
              className="hover:text-fg transition cursor-pointer"
              title="Copy message"
            >
              {copiedUser ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
            </button>
            <span className="flex size-4 items-center justify-center rounded-full bg-panel border border-line text-[8px] font-bold text-muted">
              KV
            </span>
          </div>
        </div>
      )}

      {/* 2. Slim turn header — hàng nhãn là NÚT GẤP của khối hoạt động, dưới nó là dòng biên nhận (F2 + R2) */}
      <div className="space-y-1.5 pl-0.5" data-turn-header="true">
        {/* `data-thinking-toggle` giữ nguyên tên cũ: vùng hoạt động **chính là** vùng suy luận sau
            yêu cầu 5, nên nút này vừa là nút của khối vừa là nút mở văn bản suy luận. */}
        <button
          type="button"
          data-activity-toggle="true"
          data-thinking-toggle="true"
          aria-expanded={activityOpen}
          onClick={() => {
            setActivityTouched(true)
            setActivityOpen(!activityOpen)
          }}
          className="flex items-center gap-1.5 text-xs text-muted hover:text-fg transition cursor-pointer select-none group"
        >
          <span
            className={`size-1.5 rounded-full transition duration-200 ${
              isTurnBusy ? 'bg-brand animate-pulse scale-110' : 'bg-brand/80'
            }`}
          />
          <span className="text-zinc-400">
            {isTurnBusy ? 'Working...' : `Worked for ${durationSec}s`}
          </span>
          {hasActivity &&
            (activityOpen ? (
              <ChevronDown className="size-3 text-muted group-hover:text-fg" />
            ) : (
              <ChevronRight className="size-3 text-muted group-hover:text-fg" />
            ))}
        </button>

        {/* R2: dòng biên nhận — in đúng những gì đang nằm trong khối, kể cả lệnh chưa trả kết quả */}
        {receipt.length > 0 && (
          <div className="flex flex-wrap items-center text-[11px] font-mono select-none" data-activity-receipt="true">
            {receipt.map((part, index) => (
              <span key={part.label} className="flex items-center">
                {/* Dấu phân tách mang chính khoảng trắng của nó, nên chữ trong DOM đọc
                    đúng `Thinking · 6 commands · …` chứ không dính liền nhau. */}
                {index > 0 && <span className="text-zinc-600">{' · '}</span>}
                <span className={ACTIVITY_TONE_CLASS[part.tone]}>{part.label}</span>
              </span>
            ))}
          </div>
        )}

        {/* Suy luận thật (stream từ model) hoặc dòng trung thực khi model chỉ trả token (F3).
            Dòng token ở LẠI header, ngoài khối gấp — không giấu khi model chỉ trả token. */}
        {!thoughtText && reasoningTokens > 0 && (
          <div className="flex items-center gap-1.5 text-[11px] text-muted" data-thinking-tokens="true">
            <Sparkles className="size-3 text-brand/70 shrink-0" />
            <span className="text-zinc-400">{reasoningTokensNotice(reasoningTokens)}</span>
          </div>
        )}
      </div>

      {/* 3. MỘT khối hoạt động (R2): văn xuôi suy luận + mọi hàng theo `seq` + chỉ báo bận.
          Câu trả lời cuối và khối lỗi nằm NGOÀI khối này. */}
      <div data-activity="true" data-activity-open={activityOpen ? 'true' : 'false'}>
        {activityOpen && (
          <div className="space-y-3">
            {thoughtText && <ThoughtProse thought={thoughtText} isLive={isTurnBusy} />}

            {/* P4 §4.5 — dòng công cụ gom: thay vì để người đọc đếm loạt hàng `Searched …`,
                một dòng nói đúng nhịp của run. `researchActivity` chỉ đếm `tool_start`
                nên một lời gọi không bị tính hai lần. */}
            {(() => {
              const activity = researchActivity(
                turn.items
                  .filter((item): item is Extract<TurnTimelineItem, { kind: 'tool' }> => item.kind === 'tool' && !!item.start)
                  .map((item) => ({ type: 'tool_start', data: (item.start as HarnessEvent).data })),
              )
              if (activity.searches + activity.reads === 0) return null
              return (
                <div className="flex items-center gap-1.5 text-xs text-muted" data-testid="research-activity-line">
                  <BrainCircuit className="size-3.5 shrink-0 text-brand" />
                  <span className="text-zinc-300">
                    {t('research.activity', { searches: activity.searches, reads: activity.reads })}
                  </span>
                </div>
              )
            })()}

            {turn.items.map((item) => {
              if (item.kind === 'text') {
                return <TimelineTextBlock key={item.id} text={item.text} isLive={item.live && isTurnBusy} />
              }
              if (item.kind === 'user_steer') {
                return <OwnerSteerRow key={item.id} event={item.event} />
              }
              if (item.kind === 'tool') {
                return (
                  <ToolTimelineRow
                    key={item.id}
                    start={item.start}
                    end={item.end}
                    isTurnBusy={isTurnBusy}
                    allowStartMedia={item.end ? startAllowedSeqs.has(item.end.seq) : false}
                    onOpenLightbox={onOpenLightbox}
                    captionFor={mediaCaption}
                  />
                )
              }
              if (item.kind === 'child') {
                const childSessionId = String(item.event.data.sessionId ?? item.event.data.role ?? '')
                // T15 — chip chuyên gia phải kể được đường ống peer, nhưng KHÔNG được hứa hão:
                // * con còn chạy  → mũi tên là Ý ĐỊNH, đọc từ `deliverTo` lúc giao việc ("sẽ giao cho …");
                // * con đóng sổ  → biên nhận THẬT trong `deliveries[]` (kèm người nhận bị `skipped`).
                // Nhãn chờ peer không có ở đây: `peer_wait` nằm trong luồng của CHÍNH con đang chờ,
                // và transcript không đọc luồng con (tab Sub-agents mới là chỗ poll luồng đó).
                const childData = item.event.data
                const childStatus = String(childData.status ?? '')
                // C-5: nhánh bị CHỦ NHÀ dừng bằng `cancel_child` — sổ con vẫn ghi `failed`, nhưng
                // câu hiện ra phải nói đúng việc đã xảy ra, không gọi đó là "lỗi".
                const childStatusLabel =
                  String(childData.cancelledBy ?? '') === 'owner' ? t('chat.childStoppedByOwner') : childStatus
                const pipeParts: string[] = []
                const childTargets: string[] = []
                if (childStatus === 'started' || childStatus === 'running') {
                  childTargets.push(...peerLabels(childData.deliverTo))
                  if (childTargets.length > 0) {
                    pipeParts.push(
                      t('chat.subagentWillDeliverTo', { targets: childTargets.join(', ') }),
                    )
                  }
                } else {
                  const view = peerDeliveryView(peerDeliveries(childData.deliveries), (recipient) =>
                    deliveryLabel(recipient, sessionId, roleOfChild) ?? shortPeerId(recipient),
                  )
                  childTargets.push(...view.delivered, ...view.skipped.map((row) => row.target))
                  if (view.delivered.length > 0) {
                    pipeParts.push(
                      t('chat.subagentDeliversTo', { targets: view.delivered.join(', ') }),
                    )
                  }
                  for (const row of view.skipped) {
                    pipeParts.push(
                      t('chat.subagentDeliversSkipped', {
                        target: row.target,
                        reason: skipReasonText(t, row.reason),
                      }),
                    )
                  }
                }
                const pipeSuffix = pipeParts.length > 0 ? ` · ${pipeParts.join(' · ')}` : ''
                return (
                  <button
                    key={item.id}
                    type="button"
                    data-timeline="child"
                    data-child-targets={childTargets.length > 0 ? childTargets.join(',') : undefined}
                    aria-label={t('chat.openSubagentTab')}
                    onClick={() => onOpenTab?.('subagents', childSessionId ? { sessionId: childSessionId } : null)}
                    className="group inline-flex items-center gap-1.5 rounded-md border border-brand/30 bg-brand/5 px-2 py-0.5 text-[11px] text-brand font-medium select-none transition hover:bg-brand/10 cursor-pointer"
                  >
                    <BrainCircuit className="size-3 animate-pulse" />
                    <span className="group-hover:underline">
                      Specialist: {String(item.event.data.role)} ({childStatusLabel})
                      {pipeSuffix}
                    </span>
                    <ChevronRight className="size-3 opacity-0 transition group-hover:opacity-100" />
                  </button>
                )
              }
              if (item.kind === 'plan') {
                const identity = String(item.event.data.identity ?? '')
                return (
                  <button
                    key={item.id}
                    type="button"
                    data-timeline="plan"
                    data-plan-identity={identity || undefined}
                    aria-label={t('chat.openPlanTab')}
                    onClick={() => onOpenTab?.('plan', identity ? { identity } : null)}
                    className="group inline-flex items-center gap-1.5 rounded-md border border-brand/30 bg-brand/5 px-2 py-0.5 text-[11px] text-brand font-medium select-none transition hover:bg-brand/10 cursor-pointer"
                  >
                    <FileText className="size-3" />
                    <span className="group-hover:underline">{t('chat.planWritten')}</span>
                    {identity && <span className="font-mono text-[10px] text-muted">{identity}</span>}
                    <ChevronRight className="size-3 opacity-0 transition group-hover:opacity-100" />
                  </button>
                )
              }
              if (item.kind === 'decision') {
                return (
                  <DecisionRow
                    key={item.id}
                    event={item.event}
                    resolution={item.resolution}
                    onOpenTab={onOpenTab}
                  />
                )
              }
              if (item.kind === 'notice') {
                return <ServicingNotice key={item.id} event={item.event} />
              }
              return <CompactionNotice key={item.id} event={item.event} />
            })}

            {/* Lightweight Text-only Thinking Indicator (Không viền hộp to) */}
            {isTurnBusy && !pendingTool && (
              <div className="flex items-center gap-2 py-1 text-xs text-muted select-none" data-state-indicator="thinking">
                <Sparkles className="size-3.5 text-brand animate-pulse shrink-0" />
                <span className="text-zinc-300">BoxFox is thinking and synthesizing response...</span>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 4. Final answer — CHỈ markdown của model (D-19/P4.2): tóm tắt + nút mở rộng VĂN, ảnh nằm
          trong mạch chữ và bấm ra xem lớn (P4.1). Không huy hiệu, không khối bằng chứng, không
          hàng tệp/lệnh, không lưới ảnh do app vẽ — dữ liệu `evidence` vẫn nguyên trên event. */}
      <FinalAnswerBlock
        turn={turn}
        providerId={providerId}
        targetModelId={targetModelId}
        isTurnBusy={isTurnBusy}
        copiedAssistant={copiedAssistant}
        onCopyAssistant={handleCopyAssistant}
        onOpenLightbox={onOpenLightbox}
        onOpenFile={openArtifactFile}
        fileLinkLabel={tLabel('chat.evidenceOpenFile')}
        // P5.3/D-24: hai nhãn mở/gấp văn là CHỮ CỦA APP quanh lượt, nên đi theo ngôn ngữ câu trả lời
        // như dòng biên nhận và chú thích ảnh — không còn là chuỗi tiếng Anh viết cứng trong mã.
        expandLabel={tLabel('chat.finalAnswerExpand')}
        collapseLabel={tLabel('chat.finalAnswerCollapse')}
      />

      {/* 5. Turn Error: Rendered cleanly within the specific turn where it occurred */}
      {turn.error && (
        <div className="py-2 text-xs text-rose-400 font-sans leading-relaxed select-text animate-in fade-in duration-150">
          {turn.error}
        </div>
      )}
    </div>
  )
}

/**
 * Vòng 27 / C-5 — chỉ thị chủ nhà gửi GIỮA lượt: hiện như bong bóng của chủ nhà ngay tại chỗ nó
 * được gửi (theo `seq` trong dòng thời gian của lượt đang chạy), kèm nhãn nhỏ "can thiệp".
 *
 * Không khung, không dải, không huy hiệu quanh câu trả lời cuối (D-19–D-25): đây là MỘT hàng của
 * mạch đọc, đúng như hàng `text` của lượt.
 */
function OwnerSteerRow({ event }: { event: HarnessEvent }) {
  const t = useT()
  const text = String(event.data?.text ?? '')
  if (!text) return null
  return (
    <div className="flex flex-col items-end gap-1" data-timeline="owner-steer">
      <div className="flex items-center gap-1.5 pr-1 text-[10px] text-muted select-none">
        <span
          data-testid="owner-steer-label"
          className="inline-flex items-center gap-1 rounded-full border border-brand/30 bg-brand/5 px-1.5 py-0.5 font-medium text-brand"
        >
          <Crosshair className="size-2.5" />
          {t('chat.steerLabel')}
        </span>
        <span className="font-mono">{formatTime(event.created)}</span>
      </div>
      <div className="w-fit max-w-[68%] rounded-2xl border border-line bg-panel2 px-4 py-3 text-xs leading-relaxed text-fg shadow-xs">
        <MarkdownRenderer content={text} />
      </div>
    </div>
  )
}

/** Văn bản trợ lý giữa lượt (kể cả `final:false`) — hiện đúng vị trí theo `seq`. */
function TimelineTextBlock({ text, isLive }: { text: string; isLive: boolean }) {
  if (!text) return null
  return (
    <div className="max-w-3xl pl-0.5 text-sm text-fg leading-relaxed" data-timeline="assistant-text">
      <ProgressiveMarkdown content={text} isLive={isLive} />
    </div>
  )
}

/** Một hàng cho mỗi cặp `tool_start` + `tool_end`, ảnh/video nằm ngay dưới hàng đó (F2/F4). */
function ToolTimelineRow({
  start,
  end,
  isTurnBusy,
  allowStartMedia,
  onOpenLightbox,
  captionFor,
}: {
  start: HarnessEvent | null
  end: HarnessEvent | null
  isTurnBusy?: boolean
  /** D3: hàng `start` của bản ghi chưa từng `stop` vẫn có đường mở tệp — xem `TurnBlock`. */
  allowStartMedia?: boolean
  onOpenLightbox?: (media: LightboxMediaProps) => void
  /** P4.3 + P5.3: chú thích của mảnh, dựng theo ngôn ngữ câu trả lời (xem `TurnBlock`). */
  captionFor?: (media: ToolMedia) => string
}) {
  const [open, setOpen] = useState(false)

  const source = end ?? start
  const name = String(source?.data.name ?? '')
  const args = (source?.data.args ?? null) as Record<string, unknown> | null
  const result = end?.data.result
  const isError = Boolean(result && typeof result === 'object' && (result as Record<string, unknown>).is_error)
  const display = getToolDisplay(name, args, isError)
  const media = useMemo(
    () => (end ? extractToolMedia(end, { allowStartMedia }) : null),
    [end, allowStartMedia],
  )
  // Chỉ hiện trạng thái "đang chạy" khi lượt thực sự đang chạy; lượt đã xong mà thiếu
  // `tool_end` (bị huỷ / hết hạn) phải nói thật là không có kết quả.
  const running = !end && Boolean(isTurnBusy)
  const unfinished = !end && !isTurnBusy

  return (
    <div className="space-y-1.5" data-timeline="tool" data-tool-name={name} data-tool-pending={running ? 'true' : undefined} data-tool-unfinished={unfinished ? 'true' : undefined}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs text-muted hover:text-fg transition cursor-pointer select-none group"
      >
        <div className="flex items-center gap-1.5">
          {running ? (
            <Loader2 className="size-3.5 text-blue-400 animate-spin shrink-0" />
          ) : isError || unfinished ? (
            <AlertCircle className={`size-3 shrink-0 ${isError ? 'text-red-400' : 'text-amber-400'}`} />
          ) : (
            display.icon
          )}
          <span className={running ? 'text-blue-300 animate-pulse' : 'text-zinc-400'}>
            {running ? 'Running' : display.actionLabel}
          </span>
          <span className="font-mono text-[11px] text-zinc-200 font-semibold">{display.detailLabel}</span>
          {running && <span className="text-[10px] text-blue-300">…</span>}
          {!running && isError && <span className="text-[10px] text-red-400">· failed</span>}
          {unfinished && <span className="text-[10px] text-amber-400">· no result recorded</span>}
        </div>
        {open ? (
          <ChevronDown className="size-3 text-muted group-hover:text-fg" />
        ) : (
          <ChevronRight className="size-3 text-muted group-hover:text-fg" />
        )}
      </button>

      {/* Ảnh/video của chính tool này — không gom vào gallery riêng */}
      {media && <ToolMediaBlock media={media} onOpenLightbox={onOpenLightbox} captionFor={captionFor} />}

      {open && (
        <div className="ml-4 space-y-2 rounded-xl border border-line bg-panel2/60 p-2.5 text-xs animate-in fade-in duration-150">
          {args && Object.keys(args).length > 0 && (
            <div className="text-[11px] text-zinc-400 font-mono">
              <span className="text-zinc-500">Input:</span> {JSON.stringify(args)}
            </div>
          )}

          {media?.artifactPath && (
            <div className="text-[11px] text-zinc-400 font-mono flex items-center gap-1">
              <span className="text-zinc-500">Artifact:</span>
              <span className="text-blue-400 truncate">{media.artifactPath}</span>
            </div>
          )}

          {end && (
            <pre className="max-h-48 overflow-auto font-mono text-[11px] text-zinc-300 whitespace-pre-wrap">
              {typeof result === 'string' ? result : JSON.stringify(result, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}

function ToolMediaBlock({
  media,
  onOpenLightbox,
  captionFor,
}: {
  media: ToolMedia
  onOpenLightbox?: (media: LightboxMediaProps) => void
  captionFor?: (media: ToolMedia) => string
}) {
  const t = useT()
  // P4.3 + P5.3: nhãn của model thắng; không có thì lấy chữ của từ điển theo ngôn ngữ câu trả lời.
  const caption = captionFor ? captionFor(media) : (media.caption ?? '')
  // R1 (yêu cầu 4): ảnh chụp gấp theo mặc định. State nằm trong chính hàng này (cùng khuôn với
  // `ToolTimelineRow`), nên vòng poll 1200 ms không tự mở/gấp lại ảnh.
  const [open, setOpen] = useState(false)
  // Payload `dimensions` là nguồn chính; nếu tool không kèm (ví dụ browser_use) thì lấy
  // kích thước thật của chính ảnh khi nó tải xong — không đoán, không hardcode.
  const [naturalSize, setNaturalSize] = useState<[number, number] | null>(null)
  const dimensions = media.dimensions ?? naturalSize
  const label = formatMediaLabel({ ...media, dimensions })
  const measure = (el: HTMLImageElement) => {
    if (el.naturalWidth && el.naturalHeight) setNaturalSize([el.naturalWidth, el.naturalHeight])
  }
  const openLightbox = () =>
    onOpenLightbox?.({
      type: media.kind,
      src: media.src,
      caption,
      sourceUrl: media.sourceUrl,
      duration: media.durationSec,
      artifactPath: media.artifactPath ?? undefined,
    })

  return (
    <div
      className="max-w-2xl space-y-1 pl-0.5"
      data-tool-media={media.kind}
      data-media-collapsed={open ? undefined : 'true'}
      data-media-unfinished={media.unfinished ? 'true' : undefined}
    >
      {/* Hàng gấp nói thật là CÓ ảnh đã tới: ảnh thu 56 × 36 (hoặc chip chữ cho video),
          nhãn dựng từ payload, và đúng một mũi tên. Mở rồi thì hàng gấp biến mất — một tài
          liệu chỉ hiện một lần. */}
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          aria-expanded={false}
          data-media-toggle="true"
        className="flex items-center gap-2 text-xs text-muted hover:text-fg transition cursor-pointer select-none group rounded-md text-left"
      >
          {media.kind === 'video' ? (
            <span className="flex h-9 w-14 shrink-0 items-center justify-center rounded-md border border-line bg-panel2 text-fuchsia-400">
              <Film className="size-3.5" />
            </span>
          ) : (
            <img
              data-media-thumb="true"
              src={media.src}
              alt={caption}
              loading="lazy"
              onLoad={(e) => measure(e.currentTarget)}
              onError={(e) => {
                // Ảnh không tải được thì nhãn chỉ in định dạng — không suy ra số.
                e.currentTarget.style.display = 'none'
              }}
              className="h-9 w-14 shrink-0 rounded-md border border-line bg-panel2 object-cover"
            />
          )}
          <span className="truncate font-mono text-[10px] text-zinc-400" data-media-label="true">
            {label}
          </span>
          <ChevronRight className="size-3 shrink-0 text-muted group-hover:text-fg" />
        </button>
      ) : null}

      {/* Nhánh mở: giữ nguyên khối markup cũ (ảnh/video lớn + chip Zoom + dòng caption có đường dẫn) */}
      {open && (
        <div className="space-y-1" data-media-full="true">
          <div
            className="group relative overflow-hidden rounded-xl border border-line bg-panel2 shadow-xs transition hover:border-brand/50 hover:shadow-md cursor-pointer"
            onClick={openLightbox}
            data-media-open="true"
            title="Nhấp để phóng to"
          >
            {media.kind === 'video' ? (
              <video src={media.src} muted playsInline className="w-full max-h-80 rounded-lg" data-tool-media-element="video" />
            ) : (
              <img
                src={media.src}
                alt={caption}
                onLoad={(e) => measure(e.currentTarget)}
                onError={(e) => {
                  (e.currentTarget as HTMLElement).style.display = 'none'
                }}
                className="w-full object-contain max-h-96 rounded-lg transition group-hover:scale-[1.01]"
              />
            )}
            <div className="absolute top-2 right-2 flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition bg-black/75 backdrop-blur-xs px-2.5 py-1 rounded-md text-[11px] text-white shadow-xs">
              <Maximize2 className="size-3 text-zinc-200" />
              <span>{t('chat.zoom')}</span>
            </div>
          </div>
          {/* F4: nhãn lấy từ `dimensions` + `mime` thật của payload; đường dẫn artifact chỉ ở đây */}
          <div className="flex items-center justify-between text-[10px] text-zinc-500 font-mono" data-media-label="true">
            <span className="shrink-0">{label}</span>
            <span className="flex min-w-0 items-center gap-1.5">
              {media.artifactPath && <span className="truncate">{media.artifactPath}</span>}
              {/* Nút thu lại nằm NGOÀI khung ảnh, nên bấm nó không mở khung xem lớn. */}
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-expanded
                data-media-toggle="true"
                data-media-collapse="true"
                title="Thu hàng ảnh lại"
                className="flex shrink-0 items-center text-muted hover:text-fg transition cursor-pointer"
              >
                <ChevronUp className="size-3" />
              </button>
            </span>
          </div>
        </div>
      )}
    </div>
  )
}

/** F7: thông báo nén context ở cấp cao nhất của lượt, bấm để xem chi tiết. */
/** Thông báo ngắn của harness (ví dụ `UPSTREAM_RETRY`). Cùng khung chữ mờ như nhật ký
 * hệ thống khác trong lượt; không thêm bảng màu mới. */
function ServicingNotice({ event }: { event: HarnessEvent }) {
  const code = String(event.data.code ?? 'NOTICE')
  const message = String(event.data.message ?? '').trim()
  return (
    <div
      className="max-w-2xl rounded-xl border border-line/60 bg-panel/40 px-3 py-2 text-[11px] text-muted"
      data-timeline="notice"
      data-notice-code={code}
    >
      <div className="flex items-start gap-1.5">
        <RefreshCw className="mt-0.5 size-3 shrink-0 text-zinc-500" />
        <span className="flex-1">
          {message || code}
        </span>
      </div>
    </div>
  )
}


function CompactionNotice({ event }: { event: HarnessEvent }) {
  const [open, setOpen] = useState(false)
  const kind = String(event.data.kind ?? 'unchanged')
  const before = typeof event.data.beforeEstimate === 'number' ? event.data.beforeEstimate : null
  const after = typeof event.data.afterEstimate === 'number' ? event.data.afterEstimate : null
  const pruned = typeof event.data.pruned === 'number' ? event.data.pruned : null

  return (
    <div className="max-w-2xl rounded-xl border border-amber-500/30 bg-amber-500/5 px-3 py-2" data-timeline="compaction" data-compaction-kind={kind}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        className="flex w-full items-center gap-1.5 text-xs text-amber-200/90 hover:text-amber-100 transition cursor-pointer select-none text-left"
      >
        <Layers className="size-3.5 text-amber-400 shrink-0" />
        <span className="flex-1">{compactionNoticeText(event.data)}</span>
        {open ? (
          <ChevronDown className="size-3.5 text-amber-400/80" />
        ) : (
          <ChevronRight className="size-3.5 text-amber-400/80" />
        )}
      </button>

      {open && (
        <dl className="mt-1.5 space-y-0.5 pl-5 text-[11px] text-zinc-400 font-mono animate-in fade-in duration-150" data-compaction-detail="true">
          <div>
            <dt className="inline text-zinc-500">Kind: </dt>
            <dd className="inline">{kind}</dd>
          </div>
          <div>
            <dt className="inline text-zinc-500">Before: </dt>
            <dd className="inline">{before === null ? '—' : `${before} tokens`}</dd>
          </div>
          <div>
            <dt className="inline text-zinc-500">After: </dt>
            <dd className="inline">{after === null ? '—' : `${after} tokens`}</dd>
          </div>
          {pruned !== null && (
            <div>
              <dt className="inline text-zinc-500">Tool outputs pruned: </dt>
              <dd className="inline">{pruned}</dd>
            </div>
          )}
        </dl>
      )}
    </div>
  )
}

/** F6: tóm tắt câu trả lời cuối + nút mở rộng (P4.2 bỏ lưới ảnh của lượt khỏi mặt này — ảnh nằm trong mạch chữ). */
function FinalAnswerBlock({
  turn,
  providerId,
  targetModelId,
  isTurnBusy,
  copiedAssistant,
  onCopyAssistant,
  onOpenLightbox,
  onOpenFile,
  fileLinkLabel,
  expandLabel,
  collapseLabel,
}: {
  turn: HarnessTurn
  providerId: string
  targetModelId: string
  isTurnBusy: boolean
  copiedAssistant: boolean
  onCopyAssistant: () => void
  onOpenLightbox?: (media: LightboxMediaProps) => void
  /** P4.1 — liên kết tệp bằng chứng mở tab Files đúng tệp, không mở tab trình duyệt. */
  onOpenFile?: (path: string) => void
  /** P5.3 — nhãn nút mở tệp, chữ theo ngôn ngữ câu trả lời. */
  fileLinkLabel?: string
  /** P5.3 — nhãn nút mở phần văn còn lại, cùng luật ngôn ngữ với `fileLinkLabel`. */
  expandLabel: string
  /** P5.3 — nhãn nút gấp phần văn vừa mở. */
  collapseLabel: string
}) {
  const [expanded, setExpanded] = useState(false)

  const fullText = String(turn.finalAssistant?.data?.text ?? '')
  const { summary, truncated } = useMemo(() => summarizeFinalText(fullText), [fullText])

  if (!turn.finalAssistant) return null

  const visibleText = truncated && !expanded ? summary : fullText
  // R3: nút chỉ tồn tại khi còn VĂN để mở (P4.2 bỏ lưới ảnh của lượt khỏi mặt này).
  const hasMore = truncated

  return (
    <div className="space-y-1.5 pl-0.5" data-final-answer="true">
      {/* Model Info Header */}
      <div className="flex items-center gap-1.5 text-[11px] text-muted select-none">
        <ProviderIcon providerId={providerId} className="size-3.5" />
        <span className="font-semibold text-fg">{targetModelId}</span>
        <span className="text-zinc-500">·</span>
        <span>{formatTime(turn.finalAssistant.created || turn.endTime)}</span>

        {/* Token Usage Metrics (↑ prompt_tokens ↓ completion_tokens) */}
        {turn.usage && (
          <>
            <span className="text-zinc-500">·</span>
            <span
              className="font-mono text-[10px] text-zinc-400"
              title={`Prompt tokens: ${turn.usage.prompt_tokens ?? 0} | Completion tokens: ${turn.usage.completion_tokens ?? 0}`}
            >
              ↑ {formatTokens(turn.usage.prompt_tokens)} ↓ {formatTokens(turn.usage.completion_tokens)}
            </span>
          </>
        )}

        {isTurnBusy && (
          <span className="flex items-center gap-1 text-brand font-medium animate-pulse">
            <Loader2 className="size-3 animate-spin" />
            <span>streaming</span>
          </span>
        )}

        <button
          type="button"
          onClick={onCopyAssistant}
          className="ml-auto hover:text-fg text-muted transition cursor-pointer p-0.5"
          title="Copy response"
        >
          {copiedAssistant ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
        </button>
      </div>

      {/* P4.2 / D-19 + D-20 — không còn dòng trạng thái cổng, không còn câu giải thích của app:
          mặt này CHỈ có chữ do model viết. Hậu kiểm để vai "agent verify" ở vòng sau. */}

      {/* Summary (mặc định) hoặc toàn bộ markdown khi người dùng mở rộng */}
      <div className="max-w-3xl text-sm text-fg leading-relaxed" data-final-text={expanded ? 'expanded' : 'summary'}>
        {/* P4.1 — ảnh trong câu trả lời thành tile bấm xem lớn; link tệp bằng chứng mở tab Files. */}
        <MarkdownRenderer
          content={visibleText}
          onOpenImage={onOpenLightbox}
          onOpenFile={onOpenFile}
          fileLinkLabel={fileLinkLabel}
        />

        {/* R3 (yêu cầu 6): nút nằm NGAY DƯỚI đoạn tóm tắt, và chỉ tồn tại khi có gì để mở. */}
        {hasMore && !expanded && (
          <button
            type="button"
            onClick={() => setExpanded(true)}
            aria-expanded={false}
            data-final-expander="true"
            className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-brand hover:text-brand/80 font-medium transition cursor-pointer select-none"
          >
            <ChevronRight className="size-3" />
            <span>› {expandLabel}</span>
          </button>
        )}
      </div>

      {/* Nút gấp nằm ở CUỐI phần vừa mở */}
      {hasMore && expanded && (
        <button
          type="button"
          onClick={() => setExpanded(false)}
          aria-expanded
          data-final-expander="true"
          className="inline-flex items-center gap-1 text-[11px] text-brand hover:text-brand/80 font-medium transition cursor-pointer select-none"
        >
          <ChevronDown className="size-3" />
          <span>› {collapseLabel}</span>
        </button>
      )}
    </div>
  )
}

/** Progressive Typewriter Markdown Reveal component */
function ProgressiveMarkdown({
  content,
  isLive,
}: {
  content: string
  isLive?: boolean
}) {
  const [displayedLength, setDisplayedLength] = useState(() => (isLive ? 0 : content.length))

  React.useEffect(() => {
    if (!isLive) {
      setDisplayedLength(content.length)
      return
    }

    if (displayedLength < content.length) {
      // Natural cadence: between 2 and 8 characters per tick (approx 1 word every 1-2 ticks)
      const remaining = content.length - displayedLength
      const step = Math.min(remaining, Math.max(2, Math.ceil(remaining / 12)))
      const timer = window.setTimeout(() => {
        setDisplayedLength((prev) => Math.min(content.length, prev + step))
      }, 18)
      return () => window.clearTimeout(timer)
    }
  }, [content, displayedLength, isLive])

  const isTyping = isLive && displayedLength < content.length
  const currentText = isLive ? content.slice(0, displayedLength) : content

  return (
    <div className="relative">
      <MarkdownRenderer content={currentText} />
      {isTyping && (
        <span className="inline-block w-1.5 h-3.5 bg-brand animate-pulse ml-0.5 align-middle rounded-xs" />
      )}
    </div>
  )
}

/**
 * R2 (yêu cầu 5): văn bản suy luận nằm TRONG khối hoạt động, không còn nút `Thinking (Xs)` riêng —
 * thông tin của nút đó nay nằm ở hàng nhãn (`Worked for Xs`) và dòng biên nhận (`Thinking · …`).
 * Khung giữ nguyên như trước, chỉ bỏ state riêng vì việc mở/gấp do khối hoạt động quyết định.
 */
function ThoughtProse({ thought, isLive }: { thought: string; isLive?: boolean }) {
  return (
    <div className="ml-3 pl-3 border-l-2 border-brand/50 py-1.5 text-xs text-zinc-300/95 leading-relaxed bg-panel2/40 rounded-r-xl animate-in fade-in duration-150">
      <ProgressiveMarkdown content={thought} isLive={isLive} />
    </div>
  )
}
