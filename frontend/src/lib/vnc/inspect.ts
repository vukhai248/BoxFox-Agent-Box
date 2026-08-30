/**
 * Quy đổi toạ độ cho Element Selector / DOM Inspector (khung ④) — HÀM THUẦN.
 *
 * Không React, không DOM, không side-effect: nhận số/rect đã đo sẵn, trả số ra.
 * Nhờ vậy test được không cần trình duyệt, và bên gọi (lớp phủ) chịu trách
 * nhiệm tự đo `getBoundingClientRect()` — cùng tinh thần với `fit.ts`.
 *
 * VÌ SAO KHÔNG NHÂN `devicePixelRatio` Ở ĐÂY:
 *
 * `canvas.width`/`canvas.height` là số PIXEL FRAMEBUFFER (X11) mà noVNC đang
 * vẽ; `rect.width`/`rect.height` (`getBoundingClientRect()`) là số CSS PIXEL
 * mà canvas đó CHIẾM trên trang. Tỉ số `canvasWidth / rect.width` đã gộp SẴN
 * hai hệ số:
 *
 *   1. `devicePixelRatio` — vì `fit.ts` xin framebuffer theo PIXEL VẬT LÝ
 *      (`physicalScreenSize` = CSS × DPR, xem `fit.ts:77-93`), không phải
 *      theo CSS pixel.
 *   2. `scaleViewport` — khi server không hỗ trợ `SetDesktopSize` (lưới an
 *      toàn của `fit.ts:20-25`), noVNC co/giãn ảnh để vừa khung, và khi đó
 *      framebuffer không còn bằng đúng kích thước CSS của canvas.
 *
 * Nhân thêm `devicePixelRatio` vào công thức dưới đây là tính đúp hệ số (1),
 * và trên máy DPR ≠ 1 sẽ đi tra sai điểm một cách có hệ thống.
 *
 * VÌ SAO TRẢ `null` CHO ĐIỂM NGOÀI CANVAS, KHÔNG CLAMP:
 *
 * noVNC letterbox canvas bên trong container khi tỉ lệ khung không khớp tỉ lệ
 * framebuffer (viền đen hai bên/trên-dưới). Lớp phủ (`ElementInspectorOverlay`,
 * F9) che kín cả khung, kể cả dải viền đen đó — nên một cú bấm vào dải đen vẫn
 * đi tới đây với toạ độ hợp lệ trong hệ CSS của trang. Nếu clamp mọi điểm về
 * biên canvas thì cú bấm vào dải đen sẽ luôn tra ra pixel 0 hoặc pixel cuối —
 * một phần tử không liên quan gì tới nơi người dùng vừa bấm. Vậy điểm NGOÀI
 * canvas phải trả `null`, để bên gọi bỏ qua cú bấm hẳn (không gọi `onPick`,
 * không POST lên box). Clamp chỉ dùng SAU KHI đã xác định điểm nằm trong
 * canvas, để hấp thụ sai số làm tròn ở đúng biên (`Math.round` có thể đẩy
 * `canvasWidth - 0.4` thành `canvasWidth`, tức vượt chỉ số hợp lệ cuối).
 */

/** Hình chữ nhật CSS đã đo bằng `getBoundingClientRect()` của canvas. */
export interface CanvasRect {
  left: number
  top: number
  right: number
  bottom: number
  width: number
  height: number
}

/** Điểm trong hệ toạ độ framebuffer/X11 — chính là body của `POST /__box/inspect-element`. */
export interface FramebufferPoint {
  x: number
  y: number
}

/** Hình chữ nhật CSS, dùng để vẽ khung sáng trên lớp phủ. */
export interface CssBox {
  left: number
  top: number
  width: number
  height: number
}

/** Hình chữ nhật framebuffer/X11 — hình dạng `screenBox` trong phản hồi box. */
export interface FramebufferBox {
  x: number
  y: number
  width: number
  height: number
}

interface CanvasPointToFramebufferInput {
  /** Rect CSS của `<canvas>` noVNC, đo bằng `getBoundingClientRect()`. */
  rect: CanvasRect
  /** `canvas.width` hiện tại — số pixel framebuffer theo chiều ngang. */
  canvasWidth: number
  /** `canvas.height` hiện tại — số pixel framebuffer theo chiều dọc. */
  canvasHeight: number
  /** Toạ độ CSS của cú bấm (`PointerEvent.clientX/clientY`). */
  clientX: number
  clientY: number
}

/** `n` là số hữu hạn (không `NaN`, không `Infinity`/`-Infinity`). */
function isFiniteNumber(n: number): boolean {
  return typeof n === 'number' && Number.isFinite(n)
}

/**
 * Đổi một điểm CSS trên canvas noVNC sang điểm framebuffer/X11.
 *
 * Trả `null` (KHÔNG phải `NaN`) khi:
 *   - `rect.width === 0` hoặc `rect.height === 0` — canvas chưa có kích thước
 *     (chưa đo được, hoặc đang ẩn) nên phép chia sẽ ra `Infinity`/`NaN`.
 *   - điểm nằm NGOÀI nửa-khoảng `[rect.left, rect.right) × [rect.top, rect.bottom)`
 *     — đây là chính xác vùng mà `getBoundingClientRect()` mô tả; nửa-khoảng
 *     (không lấy biên phải/dưới) khớp quy ước hit-test chuẩn của DOM.
 *   - `canvasWidth`/`canvasHeight` không phải số hữu hạn dương.
 *   - `clientX`/`clientY` không phải số hữu hạn.
 *
 * Khi điểm hợp lệ: quy đổi tuyến tính rồi `Math.round`, sau đó clamp vào
 * `[0, canvasWidth - 1]` / `[0, canvasHeight - 1]` CHỈ để hấp thụ sai số làm
 * tròn của một điểm ĐÃ nằm trong canvas (xem chú thích đầu file).
 */
export function canvasPointToFramebuffer({
  rect,
  canvasWidth,
  canvasHeight,
  clientX,
  clientY,
}: CanvasPointToFramebufferInput): FramebufferPoint | null {
  if (!isFiniteNumber(rect.width) || !isFiniteNumber(rect.height)) return null
  if (rect.width === 0 || rect.height === 0) return null
  if (!isFiniteNumber(canvasWidth) || !isFiniteNumber(canvasHeight)) return null
  if (canvasWidth <= 0 || canvasHeight <= 0) return null
  if (!isFiniteNumber(clientX) || !isFiniteNumber(clientY)) return null

  if (clientX < rect.left || clientX >= rect.right || clientY < rect.top || clientY >= rect.bottom) {
    return null
  }

  const scaleX = canvasWidth / rect.width
  const scaleY = canvasHeight / rect.height

  const rawX = Math.round((clientX - rect.left) * scaleX)
  const rawY = Math.round((clientY - rect.top) * scaleY)

  return {
    x: Math.min(Math.max(rawX, 0), canvasWidth - 1),
    y: Math.min(Math.max(rawY, 0), canvasHeight - 1),
  }
}

interface FramebufferBoxToCanvasCssInput {
  /** Hộp bao trong toạ độ framebuffer/X11 (`screenBox` của phản hồi box). */
  box: FramebufferBox
  /** Rect CSS hiện tại của canvas noVNC. */
  canvasRect: CanvasRect
  /** Rect CSS của lớp phủ (`ElementInspectorOverlay`) — gốc để vẽ khung sáng. */
  overlayRect: CanvasRect
  canvasWidth: number
  canvasHeight: number
}

/**
 * Đổi ngược một hộp framebuffer/X11 (`screenBox`) sang toạ độ CSS TƯƠNG ĐỐI SO
 * VỚI GỐC CỦA LỚP PHỦ, để vẽ khung sáng trên overlay.
 *
 * Cần HAI rect (canvas và overlay) vì overlay che kín toàn khung — kể cả dải
 * letterbox — nên gốc của nó có thể lệch khỏi gốc canvas. Kết quả cộng thêm
 * đúng `canvasRect.left - overlayRect.left` (và tương tự cho top) để khung vẽ
 * ra đứng đúng chỗ trong hệ toạ độ mà overlay dùng để tự định vị các con.
 *
 * Trả `null` khi rect rỗng (`width`/`height` của canvas hoặc overlay là 0),
 * khi `canvasWidth`/`canvasHeight` không hợp lệ, hoặc khi `box.width <= 0`
 * hay `box.height <= 0` (hộp suy biến — không có gì để vẽ).
 */
export function framebufferBoxToCanvasCss({
  box,
  canvasRect,
  overlayRect,
  canvasWidth,
  canvasHeight,
}: FramebufferBoxToCanvasCssInput): CssBox | null {
  if (!isFiniteNumber(canvasRect.width) || !isFiniteNumber(canvasRect.height)) return null
  if (canvasRect.width === 0 || canvasRect.height === 0) return null
  if (!isFiniteNumber(overlayRect.width) || !isFiniteNumber(overlayRect.height)) return null
  if (overlayRect.width === 0 || overlayRect.height === 0) return null
  if (!isFiniteNumber(canvasWidth) || !isFiniteNumber(canvasHeight)) return null
  if (canvasWidth <= 0 || canvasHeight <= 0) return null
  if (!isFiniteNumber(box.width) || !isFiniteNumber(box.height)) return null
  if (box.width <= 0 || box.height <= 0) return null

  const scaleX = canvasRect.width / canvasWidth
  const scaleY = canvasRect.height / canvasHeight
  const originLeft = canvasRect.left - overlayRect.left
  const originTop = canvasRect.top - overlayRect.top

  return {
    left: originLeft + box.x * scaleX,
    top: originTop + box.y * scaleY,
    width: box.width * scaleX,
    height: box.height * scaleY,
  }
}
