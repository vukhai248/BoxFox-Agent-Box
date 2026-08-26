/**
 * Cấu hình kênh noVNC — KHÔNG phải transport của agent.
 *
 * `src/lib/transport/` là kênh sự kiện của agent (`ServerEvent` / `ClientCommand`);
 * noVNC là kênh thứ hai, hoàn toàn khác: trình duyệt nối *trực tiếp* tới
 * websockify của box (`ws://…/websockify`), dữ liệu là khung hình RFB, không
 * có `ServerEvent` nào, không qua session, không qua Policy Engine. Vì vậy
 * logic ở đây không được đặt vào `transport/` (xem plan §4, quyết định D-1).
 *
 * File này chỉ chứa logic thuần — không React, không DOM — nên test được
 * bằng vitest mà không cần trình duyệt.
 */

export const DEFAULT_SANDBOX_VNC_URL = 'ws://localhost:6080/websockify'

/**
 * Nguồn khung hình của khung ④.
 *
 * `mock`  — màn hình mô phỏng dựng sẵn. Đây là cảnh demo VPI chính (mục 14.5)
 *           nên phải giữ được nguyên vẹn: ở nguồn này gói `@novnc/novnc`
 *           KHÔNG được nạp và KHÔNG mở socket nào.
 * `novnc` — màn hình máy thật qua websockify của box.
 */
export type ScreenSource = 'mock' | 'novnc'

/**
 * Chọn nguồn khung hình.
 *
 * Vì sao cần cổng này: hook noVNC nối độc lập với transport của agent, nên nếu
 * cứ hễ mount là nối thì trên máy nào đang chạy box, màn hình thật sẽ chiếm
 * chỗ của `screenWithInjection()` trong kịch bản mock và phá luôn cảnh demo
 * VPI 8 bước. Mặc định vì thế là `mock`.
 *
 * Nhận `env` qua tham số (không đọc trực tiếp `import.meta.env`) để test chạy
 * được ngoài Vite.
 */
export function resolveScreenSource(env?: {
  VITE_SANDBOX_SCREEN_SOURCE?: string
  VITE_TRANSPORT?: string
}): ScreenSource {
  const explicit = env?.VITE_SANDBOX_SCREEN_SOURCE?.trim().toLowerCase()
  if (explicit === 'novnc') return 'novnc'
  if (explicit === 'mock') return 'mock'
  // Không đặt tường minh: transport thật ⇒ ngầm hiểu là muốn xem máy thật.
  return env?.VITE_TRANSPORT?.trim().toLowerCase() === 'live' ? 'novnc' : 'mock'
}

/**
 * Rút ra URL websockify sẽ dùng. Nhận `env` qua tham số (không đọc trực
 * tiếp `import.meta.env`) để test chạy được ngoài Vite.
 */
export function resolveVncUrl(env?: { VITE_SANDBOX_VNC_URL?: string }): string {
  const raw = env?.VITE_SANDBOX_VNC_URL?.trim()
  return raw ? raw : DEFAULT_SANDBOX_VNC_URL
}

export type VncContextProblem = 'mixedContent' | 'insecureContext'

export interface VncContext {
  /** `window.location.protocol`, ví dụ `'http:'`. */
  pageProtocol: string
  /** `window.isSecureContext`. */
  isSecureContext: boolean
  url: string
}

/**
 * Hai lý do phải chặn TRƯỚC khi nạp `@novnc/novnc`:
 *
 * - `mixedContent`    — trang HTTPS + kênh `ws://` (không mã hoá): trình duyệt
 *   chặn thẳng tay. Báo lý do tiếng người thay vì để lỗi mờ trồi lên console.
 * - `insecureContext` — `window.isSecureContext === false` (ví dụ mở giao diện
 *   qua `http://<IP-LAN>:3100` thay vì `http://localhost:3100`). `core/rfb.js`
 *   của noVNC tự log `"noVNC requires a secure context (TLS). Expect crashes!"`
 *   rồi chạy tiếp và vỡ sau đó — dừng sớm thì thông báo mới dùng được.
 *
 * Kiểm `mixedContent` trước vì nó cụ thể hơn và có cách sửa khác.
 */
export function describeVncContextProblem(ctx: VncContext): VncContextProblem | null {
  if (ctx.pageProtocol === 'https:' && ctx.url.startsWith('ws://')) return 'mixedContent'
  if (!ctx.isSecureContext) return 'insecureContext'
  return null
}
