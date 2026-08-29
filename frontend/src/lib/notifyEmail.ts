/**
 * Dựng nội dung email MOCK "box đã xong task" theo ngôn ngữ giao diện hiện tại.
 *
 * Email này KHÔNG có danh sách commit — người dùng chỉ muốn một bản tóm tắt việc
 * đã làm (quyết định #4650). Phần "việc đã làm" được lấy từ các bước `agent_step`
 * đã thực thi thật (tool + mục tiêu), không phải từ trạng thái bước của plan (vì
 * plan snapshot trong mock không cập nhật `status` theo tiến độ). Vì AI/backend
 * đang tạm gác nên đây thuần là một chuỗi xem trước trong trình duyệt.
 */
import vi from '../i18n/vi'
import en from '../i18n/en'
import { interpolate, type Lang } from '../i18n/context'
import type { ToolName } from '../types/lease'

/** Một thao tác thật mà agent đã chạy — đủ để diễn tả "đã làm gì". */
export interface ExecutedWork {
  tool: ToolName
  /** Mục tiêu ngắn gọn (path/command/url/…) — có thể rỗng. */
  target: string
}

export interface CompletionEmailContent {
  subject: string
  body: string
}

/** Lấy mục tiêu dễ đọc nhất từ `params` của một tool call (đã cắt ngắn nếu dài). */
export function workTargetOf(params: Record<string, string> | undefined): string {
  if (!params) return ''
  const preferred = ['path', 'file_path', 'command', 'url', 'text', 'destination'] as const
  for (const key of preferred) {
    const value = params[key]
    if (value) return value.length > 72 ? `${value.slice(0, 72)}…` : value
  }
  const first = Object.values(params)[0]
  return first ? String(first) : ''
}

export function buildCompletionEmail(
  lang: Lang,
  title: string,
  work: readonly ExecutedWork[] = [],
): CompletionEmailContent {
  const dict = lang === 'vi' ? vi : en
  const ns = dict.notifications
  const subject = interpolate(ns.emailSubject, { title })
  const intro = interpolate(ns.emailBody, { title })

  if (work.length === 0) {
    return { subject, body: intro }
  }

  const bullets = work
    .map((item) => {
      const label = ns.tools[item.tool] ?? item.tool
      return `• ${label}${item.target ? ` — ${item.target}` : ''}`
    })
    .join('\n')

  return {
    subject,
    body: `${intro}\n\n${ns.workLabel}\n${bullets}`,
  }
}
