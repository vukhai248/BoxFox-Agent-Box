/**
 * Ngưỡng chế độ compact của thanh composer (`ChatInputBar`).
 *
 * Số đo thật (viewport 1180×820, DPR 1, xem plan `v1-composer-compact.md`):
 * - Chế độ đầy đủ cần 1 dòng: nhóm trái 373px + gap 8px + nhóm phải 62px = 443px
 *   → cộng chrome ngang 44px (p-3 + p-2.5) → pane cần ≥ 487px.
 * - Chế độ compact (ẩn 2 nhãn chữ, giải phóng ~105px): 268 + 8 + 62 = 338px
 *   → pane cần ≥ 382px.
 * Chọn ngưỡng compact 500px (dư 13px so với 487) để chuyển sang compact TRƯỚC
 * khi kịp wrap ở chế độ đầy đủ.
 *
 * Lưu ý về thang số: `useCompactComposer` đọc `contentRect.width`, tức KHÔNG
 * gồm 24px padding ngang (`p-3`) của thanh composer. Vì vậy quy ra bề rộng
 * pane chat thì mốc chuyển chế độ nằm ở ~524/525px (đã nghiệm trên browser),
 * chứ không phải đúng 500px. Đây là hướng an toàn: compact bật SỚM hơn mức
 * 487px mà chế độ đầy đủ cần, nên chế độ đầy đủ không bao giờ kịp wrap.
 */
export const COMPOSER_COMPACT_MAX_PX = 500

/**
 * `width === 0` nghĩa là chưa layout xong (lúc mount, `ResizeObserver` chưa
 * bắn lần đầu) → trả `false` để không nháy compact trước khi có số đo thật.
 */
export function isCompactComposer(width: number): boolean {
  return width > 0 && width < COMPOSER_COMPACT_MAX_PX
}
