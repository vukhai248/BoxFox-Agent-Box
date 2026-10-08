/**
 * Quy đổi toạ độ cho panel "Màn hình máy" — HÀM THUẦN, không React/không DOM.
 *
 * Ba hệ toạ độ cùng tồn tại ở panel này:
 *
 *   1. **Màn hình vật lý** (physical) — hệ của `activeWindow.rect` (backend trả)
 *      và của `captureOrigin` (gốc vùng chụp, CÓ THỂ ÂM: màn hình phụ nằm bên
 *      trái màn hình chính làm gốc chung âm).
 *   2. **Framebuffer của ảnh chụp** — toạ độ trong ẢNH: `0..width`, `0..height`.
 *      Đây là hệ NỘI BỘ của panel (vẽ lớp phủ, khoanh vùng phần tử). ⚠️
 *      `POST /desktop/inspect-element` KHÔNG nhận hệ này: route kiểm điểm theo
 *      màn hình ảo (`_validate_point` phía backend), nên phải CỘNG `captureOrigin`
 *      trước khi gửi — đó là lý do `imagePointToFramebuffer` tồn tại. Bỏ phép
 *      cộng đó là mọi cửa sổ có gốc chụp khác `(0, 0)` soi sai chỗ.
 *   3. **CSS pixel trên trang** — hệ của `getBoundingClientRect()` và của
 *      `style.left/top` khi vẽ lớp phủ.
 *
 * Hai hàm ở đây là hai chiều của cùng một phép dịch gốc:
 *
 *   ảnh  =  vật lý − captureOrigin
 *   vật lý =  ảnh + captureOrigin
 *
 * rồi mới co/giãn theo tỉ lệ `ảnh / CSS` — phần co/giãn đó KHÔNG viết lại ở
 * đây mà giao cho `lib/vnc/inspect.ts` (đã có test riêng, và đã ghi rõ vì sao
 * KHÔNG nhân `devicePixelRatio`: tỉ số `ảnh.width / rect.width` đã gộp sẵn hệ
 * số đó).
 */
import { canvasPointToFramebuffer, framebufferBoxToCanvasCss } from '../vnc/inspect'
import type { CanvasRect, CssBox, FramebufferBox, FramebufferPoint } from '../vnc/inspect'

/** Gốc vùng chụp trong toạ độ màn hình vật lý (`HostSnapshot.captureOrigin`). */
export interface CaptureOrigin {
  x: number
  y: number
}

/** `n` là số hữu hạn (không `NaN`, không `Infinity`). */
function isFiniteNumber(n: unknown): n is number {
  return typeof n === 'number' && Number.isFinite(n)
}

/** Gốc thiếu/không hợp lệ coi như `(0, 0)` — nền cũ trả ảnh không kèm gốc. */
function normalizeOrigin(origin: CaptureOrigin | undefined | null): CaptureOrigin {
  if (!origin || !isFiniteNumber(origin.x) || !isFiniteNumber(origin.y)) return { x: 0, y: 0 }
  return origin
}

interface ImagePointInput {
  /** Rect CSS của `<img>` — ảnh có thể bị letterbox trong khung nên đo riêng. */
  imageRect: CanvasRect
  /** `naturalWidth`/`width` của ảnh — số pixel thật của khung hình. */
  imageWidth: number
  imageHeight: number
  captureOrigin: CaptureOrigin
  /** Toạ độ CSS của cú bấm (`PointerEvent.clientX/clientY`). */
  clientX: number
  clientY: number
}

/**
 * Đổi một cú bấm trên ảnh (CSS pixel) sang toạ độ framebuffer để gửi
 * `POST /desktop/inspect-element`.
 *
 * Trả `null` khi cú bấm nằm NGOÀI ảnh (dải letterbox quanh ảnh, hoặc ảnh chưa
 * đo được) — bên gọi BỎ QUA cú bấm hẳn, không tra vào pixel biên (cùng quy tắc
 * với `canvasPointToFramebuffer`).
 */
export function imagePointToFramebuffer({
  imageRect,
  imageWidth,
  imageHeight,
  captureOrigin,
  clientX,
  clientY,
}: ImagePointInput): FramebufferPoint | null {
  const local = canvasPointToFramebuffer({
    rect: imageRect,
    canvasWidth: imageWidth,
    canvasHeight: imageHeight,
    clientX,
    clientY,
  })
  if (!local) return null
  const origin = normalizeOrigin(captureOrigin)
  return { x: local.x + origin.x, y: local.y + origin.y }
}

interface ImageBoxInput {
  /** Hộp trong toạ độ màn hình vật lý (`activeWindow.rect`, `bounds.screenBox`). */
  box: FramebufferBox
  /** Rect CSS của `<img>`. */
  imageRect: CanvasRect
  /** Rect CSS của khung chứa lớp phủ (ảnh có thể lệch trong khung). */
  overlayRect: CanvasRect
  imageWidth: number
  imageHeight: number
  captureOrigin: CaptureOrigin
}

/**
 * Đổi một hộp trong toạ độ màn hình vật lý sang CSS pixel TƯƠNG ĐỐI SO VỚI GỐC
 * CỦA KHUNG, để vẽ viền xanh / khung sáng.
 *
 * Hộp nằm HOÀN TOÀN ngoài vùng chụp (ví dụ cửa sổ agent đang ở màn hình khác)
 * ⇒ trả `null`, KHÔNG vẽ gì: khung chứa không cắt (`overflow-hidden` sẽ cắt luôn
 * quầng sáng của viền), nên toạ độ âm sẽ vẽ viền tràn ra ngoài ảnh. Hộp chỉ nằm
 * MỘT PHẦN ngoài vẫn cho toạ độ âm và KHÔNG clamp — clamp sẽ vẽ một khung sai
 * chỗ thay vì vẽ đúng phần nhìn thấy được.
 */
export function framebufferBoxToImageCss({
  box,
  imageRect,
  overlayRect,
  imageWidth,
  imageHeight,
  captureOrigin,
}: ImageBoxInput): CssBox | null {
  const origin = normalizeOrigin(captureOrigin)
  const local = { x: box.x - origin.x, y: box.y - origin.y, width: box.width, height: box.height }
  if (local.x + local.width <= 0 || local.y + local.height <= 0) return null
  if (local.x >= imageWidth || local.y >= imageHeight) return null
  return framebufferBoxToCanvasCss({
    box: local,
    canvasRect: imageRect,
    overlayRect,
    canvasWidth: imageWidth,
    canvasHeight: imageHeight,
  })
}

/** CSS của một `CssBox` để đặt vào `style` của một `div` tuyệt đối. */
export function cssBoxStyle(box: CssBox): { left: number; top: number; width: number; height: number } {
  return { left: box.left, top: box.top, width: box.width, height: box.height }
}
