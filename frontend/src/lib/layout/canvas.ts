/**
 * Ngưỡng chế độ compact của thanh công cụ Design Canvas.
 *
 * Sau khi di dời cụm Zoom xuống góc dưới phải, toolbar trên đỉnh chỉ cần ~400px
 * cho chế độ đầy đủ. Đặt ngưỡng 420px để tự động chuyển sang icon-only pill khi hẹp.
 */
export const CANVAS_TOOLBAR_COMPACT_MAX_PX = 420

/**
 * `width === 0` nghĩa là chưa layout xong (lúc mount, `ResizeObserver` chưa bắn
 * lần đầu) → trả `false` để không nháy compact trước khi có số đo thật.
 */
export function isCompactCanvasToolbar(width: number): boolean {
  return width > 0 && width < CANVAS_TOOLBAR_COMPACT_MAX_PX
}
