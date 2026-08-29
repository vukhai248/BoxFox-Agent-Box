/**
 * Ngưỡng chế độ compact của thanh công cụ Design Canvas.
 *
 * Cụm công cụ đầy đủ gồm 6 nút tool + zoom + 2 pill (Clear/Send-to-Agent), đo
 * theo bề rộng contentRect (KHÔNG gồm padding panel — cùng kiểu `composer.ts`).
 * 460px là ước lượng: khi hẹp hơn ngưỡng này, chỉ giữ icon (ẩn nhãn chữ) để
 * tránh wrap. Giá trị chưa đóng băng cuối — phải nghiệm lại trên browser như
 * tác giả đã đo cho `composer.ts` trước khi dùng lâu dài.
 */
export const CANVAS_TOOLBAR_COMPACT_MAX_PX = 460

/**
 * `width === 0` nghĩa là chưa layout xong (lúc mount, `ResizeObserver` chưa bắn
 * lần đầu) → trả `false` để không nháy compact trước khi có số đo thật.
 */
export function isCompactCanvasToolbar(width: number): boolean {
  return width > 0 && width < CANVAS_TOOLBAR_COMPACT_MAX_PX
}
