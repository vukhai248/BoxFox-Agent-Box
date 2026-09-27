/**
 * Ngưỡng chế độ compact của thanh composer (`ChatInputBar`).
 *
 * Số đo thật (viewport 1180×820, DPR 1, xem plan `v1-composer-compact.md`):
 * - Chế độ đầy đủ cần 1 dòng: nhóm trái 373px + gap 8px + nhóm phải 62px = 443px
 *   → cộng chrome ngang 44px (p-3 + p-2.5) → pane cần ≥ 487px.
 * - Chế độ compact (ẩn 2 nhãn chữ, giải phóng ~105px): 268 + 8 + 62 = 338px
 *   → pane cần ≥ 382px.
 *
 * ĐO LẠI 2026-09-27 khi thêm hai nút chế độ Research + Design vào nhóm trái
 * (đo trên bản chạy thật qua CDP, bề rộng khung soạn tin 515px, `contentRect` 495px):
 * nhóm trái chế độ đầy đủ cần **553px** (`scrollWidth`, lúc đó chỉ được cấp 423px nên
 * nút Design bị cắt hẳn), nhóm phải 62px + gap 8px → chế độ đầy đủ cần `contentRect`
 * ≥ 553 + 8 + 62 = **623px**. Bốn nhãn chữ (Quick ask · Autopilot · Research · Design)
 * giải phóng ~185px → chế độ compact cần ~438px.
 *
 * Chọn ngưỡng compact 640px (dư 14px so với 626) để chuyển sang compact TRƯỚC khi
 * kịp cắt nút ở chế độ đầy đủ. Hai nút chế độ là lối vào duy nhất của `/research` và
 * `/design`, nên chúng không bao giờ được phép rơi ra ngoài vùng nhìn thấy.
 *
 * Lưu ý về thang số: `useCompactComposer` đọc `contentRect.width`, tức KHÔNG
 * gồm 24px padding ngang (`p-3`) của thanh composer. Vì vậy quy ra bề rộng pane chat
 * thì mốc chuyển chế độ nằm ở ~664px, chứ không phải đúng 640px. Đây là hướng an toàn:
 * compact bật SỚM hơn mức 623px mà chế độ đầy đủ cần, nên chế độ đầy đủ không bao giờ
 * kịp cắt.
 */
export const COMPOSER_COMPACT_MAX_PX = 640

/**
 * `width === 0` nghĩa là chưa layout xong (lúc mount, `ResizeObserver` chưa
 * bắn lần đầu) → trả `false` để không nháy compact trước khi có số đo thật.
 */
export function isCompactComposer(width: number): boolean {
  return width > 0 && width < COMPOSER_COMPACT_MAX_PX
}
