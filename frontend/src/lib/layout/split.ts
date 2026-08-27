/**
 * Kẹp tỉ lệ chia cột chat/workspace theo sàn pixel cứng.
 *
 * Tách khỏi `Resizer.tsx` để dùng chung cho cả đường kéo chuột (pointer) và
 * bàn phím (ArrowLeft/ArrowRight) — tránh tình trạng bàn phím lách qua sàn
 * pixel như trước.
 */
export function clampSplitRatio(
  x: number,
  containerWidth: number,
  minChat: number,
  minWorkspace: number,
): number {
  if (containerWidth <= 0) return 0

  // Ở container hẹp, sàn cứng có thể vượt quá 45% bề rộng — hạ sàn theo tỉ lệ
  // để hai cột vẫn chia được, tránh minChat + minWorkspace > containerWidth.
  const clampedMinChat = Math.min(minChat, containerWidth * 0.45)
  const clampedMinWorkspace = Math.min(minWorkspace, containerWidth * 0.45)
  const clampedX = Math.max(clampedMinChat, Math.min(containerWidth - clampedMinWorkspace, x))

  return clampedX / containerWidth
}
