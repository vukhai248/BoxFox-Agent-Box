/**
 * Cấu hình tab IDE — nhúng code-server (VS Code bản web) của box.
 *
 * Đây là kênh THỨ BA của giao diện, khác cả hai kênh đã có:
 *   - `src/lib/transport/`  : kênh sự kiện của agent (`ServerEvent` / `ClientCommand`)
 *   - `src/lib/vnc/`        : khung hình RFB của màn hình box (khung ④)
 *   - file này              : trình duyệt nạp thẳng HTTP của code-server trong
 *                             một `<iframe>`; không `ServerEvent` nào, không
 *                             qua session, không qua Policy Engine.
 *
 * Vì sao nhúng bản web mà không mở VS Code bản desktop trong box: bản desktop
 * (Electron) phải vẽ ra Xvfb rồi đẩy PIXEL qua x11vnc/websockify, nên mỗi lần
 * gõ một ký tự là một lượt truyền ảnh; bản web gửi text tới trình duyệt người
 * dùng và không cần một pixel nào của desktop.
 *
 * File này chỉ chứa logic thuần — không React, không DOM — nên test được bằng
 * vitest mà không cần trình duyệt.
 */

/**
 * `?folder=` mở sẵn workspace của box, nếu không code-server hiện trang Welcome
 * rỗng và người dùng phải tự đi tìm thư mục.
 */
/** Mặc định trỏ tới proxy (:8081) thay vì code-server trực tiếp (:8080).
 *  Proxy chèn CSP frame-ancestors — bảo vệ chống clickjacking. */
export const DEFAULT_IDE_URL = 'http://localhost:8081/?folder=/home/agent/workspace'

/**
 * `codeServer` — nhúng code-server của box (mặc định).
 * `off`        — không nhúng gì, không thăm dò mạng. Dùng khi demo giao diện
 *                trên máy không chạy box và không muốn có thêm request nào.
 */
export type IdeSource = 'codeServer' | 'off'

/**
 * Chọn nguồn cho tab IDE.
 *
 * Mặc định là BẬT — khác với khung ④ (mặc định `mock`). Lý do: khung ④ có màn
 * hình mô phỏng phải bảo vệ vì đó là cảnh demo VPI ở mục 14.5, còn ở đây không
 * có "IDE mô phỏng" nào cả; dựng một VS Code giả thì vô nghĩa. Box tắt thì panel
 * hiện thẳng trạng thái chưa nối được kèm cách bật box.
 *
 * Nhận `env` qua tham số (không đọc trực tiếp `import.meta.env`) để test chạy
 * được ngoài Vite.
 */
export function resolveIdeSource(env?: { VITE_IDE_SOURCE?: string }): IdeSource {
  const explicit = env?.VITE_IDE_SOURCE?.trim().toLowerCase()
  if (explicit === 'off') return 'off'
  return 'codeServer'
}

/**
 * Rút ra URL code-server sẽ nhúng. Nhận `env` qua tham số (không đọc trực tiếp
 * `import.meta.env`) để test chạy được ngoài Vite.
 */
export function resolveIdeUrl(env?: { VITE_IDE_URL?: string }): string {
  const raw = env?.VITE_IDE_URL?.trim()
  return raw ? raw : DEFAULT_IDE_URL
}

export type IdeContextProblem = 'mixedContent'

export interface IdeContext {
  /** `window.location.protocol`, ví dụ `'http:'`. */
  pageProtocol: string
  url: string
}

/**
 * Lý do phải chặn TRƯỚC khi nhúng iframe: trang HTTPS + iframe `http://` là
 * mixed content, trình duyệt chặn thẳng và chỉ để lại một dòng mờ trong console.
 * Bắt sớm thì nói được thành câu người đọc hiểu (mở giao diện qua
 * `http://localhost:3100`).
 */
export function describeIdeContextProblem(ctx: IdeContext): IdeContextProblem | null {
  if (ctx.pageProtocol === 'https:' && ctx.url.startsWith('http://')) return 'mixedContent'
  return null
}
