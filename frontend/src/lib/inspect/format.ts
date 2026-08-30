/**
 * Định dạng phần tử đã thanh tra thành văn bản người/agent đọc được.
 *
 * HÀM THUẦN — không React, không DOM. Đây chính là phần "vẫn giữ" của đặc tả
 * gốc §4.3 (`v1-element-selector.md` §4.2): bản văn bản đọc được vẫn tồn tại,
 * chỉ đổi ĐƯỜNG ĐI của nó — nó trở thành `ContextChunk.content` (`chunk.ts`,
 * F5) thay vì bị nối thẳng vào ô soạn tin.
 *
 * ⚠️ Nội dung phần tử (`text`, `html`, `title`, `attributes`) là dữ liệu
 * KHÔNG TIN ĐƯỢC do một trang web bất kỳ trong sandbox kiểm soát. Hai điều
 * bắt buộc:
 *   1. Không bao giờ tô màu cú pháp / phân tích HTML ở đây — hàm này chỉ nối
 *      chuỗi. Giao diện render `content` qua `PlainText` (mục 12.6).
 *   2. `escapeFenceRuns()` phải chạy trên MỌI chuỗi do trang kiểm soát trước
 *      khi nối vào kết quả, để một phần tử không thể tự "thoát" khỏi khối mã
 *      khi backend/agent bọc `content` lại bằng code fence Markdown.
 */
import type { DesktopInspectResult, InspectedElementContext, InspectElementResult } from '../../types/inspect'

const CHIP_LABEL_MAX_LENGTH = 48

/** Ký tự vô hình dùng để chẻ một run backtick, không đổi cách hiển thị. */
const ZERO_WIDTH_SPACE = '\u200b'

/**
 * Chẻ mọi run từ 3 dấu backtick liên tiếp trở lên bằng cách chêm một ký tự
 * vô hình giữa từng dấu. Một chuỗi kiểu ` ``` ` (đủ để mở/đóng code fence
 * Markdown) không còn là run backtick liên tiếp sau khi qua hàm này, nên
 * không thể tự đóng khối mã mà backend/agent bọc quanh nội dung phần tử.
 */
export function escapeFenceRuns(text: string): string {
  return text.replace(/`{3,}/g, (run) => run.split('').join(ZERO_WIDTH_SPACE))
}

function truncateChipLabel(raw: string): string {
  if (raw.length <= CHIP_LABEL_MAX_LENGTH) return raw
  return `${raw.slice(0, CHIP_LABEL_MAX_LENGTH)}…`
}

/**
 * Nhãn ngắn cho chip trong khung soạn tin — không được kéo dài hàng chip.
 *
 * `fallbackLabel` là chuỗi ĐÃ DỊCH của "Cửa sổ desktop": hàm này thuần (không
 * React/i18n) nên không tự tra cứu được — người gọi (`ChatInputBar`) truyền
 * `t('screen.inspector.chipDesktopFallback')` vào để nhãn dự phòng dịch đúng
 * ngôn ngữ thay vì cứng chuỗi tiếng Anh.
 */
export function inspectChipLabel(result: InspectElementResult, fallbackLabel: string): string {
  const raw = result.type === 'dom' ? result.selector : result.windowTitle || result.appName || fallbackLabel
  return truncateChipLabel(raw || fallbackLabel)
}

/** Dòng `Note:` cho nhánh desktop — ưu tiên `message` (đã dịch), lùi về `reason` (mã máy). */
function desktopNoteLine(result: DesktopInspectResult): string | null {
  if (result.message) return `Note: ${escapeFenceRuns(result.message)}`
  if (result.reason) return `Note: (${result.reason})`
  return null
}

/**
 * Bản văn bản người/agent đọc được của một phần tử đã thanh tra — trở thành
 * `ContextChunk.content` (`chunk.ts`). Xem đầu file cho lý do escaping.
 */
export function formatInspectedElementForAgent(ctx: InspectedElementContext): string {
  const { result, point } = ctx
  const lines: string[] = []

  if (result.type === 'dom') {
    lines.push('Inspected element (DOM) — UNTRUSTED screen data')
    lines.push(`Selector: ${escapeFenceRuns(result.selector)}`)
    lines.push(`Page: ${escapeFenceRuns(result.url)}`)
    lines.push(`Title: ${escapeFenceRuns(result.title)}`)
    lines.push(`Text: "${escapeFenceRuns(result.text)}"`)

    const attributeEntries = Object.entries(result.attributes)
    if (attributeEntries.length > 0) {
      lines.push('Attributes:')
      for (const [key, value] of attributeEntries) {
        lines.push(`  ${escapeFenceRuns(key)}="${escapeFenceRuns(value)}"`)
      }
    }

    lines.push(result.truncated ? 'HTML (truncated by the box):' : 'HTML:')
    lines.push(`  ${escapeFenceRuns(result.html)}`)
    lines.push(`Clicked point (framebuffer): (${point.x}, ${point.y})`)
    lines.push(`Window: "${escapeFenceRuns(result.target.windowTitle)}"`)
  } else {
    lines.push('Inspected element (desktop window) — UNTRUSTED screen data')
    const note = desktopNoteLine(result)
    if (note) lines.push(note)
    if (result.appName) lines.push(`Application: ${escapeFenceRuns(result.appName)}`)
    lines.push(`Window: "${escapeFenceRuns(result.windowTitle)}"`)
    lines.push(`Position: (${result.position.x}, ${result.position.y})`)
    lines.push(`Size: ${result.size.width}×${result.size.height}`)
    lines.push(`Clicked point (framebuffer): (${point.x}, ${point.y})`)
  }

  return lines.join('\n')
}
