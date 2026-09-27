/**
 * Định dạng nhỏ dùng chung trong các component research.
 *
 * Giữ ở đây thay vì nhét vào từng component để mọi chỗ hiển thị ngân sách cùng một kiểu
 * (`18:24 / 30:00`), đúng như mockup `run-status-timeline.html`.
 */

/** `754` → `12:34`; từ một giờ trở lên → `1:02:03`. */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.round(seconds))
  const hours = Math.floor(total / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  const secs = total % 60
  const pad = (value: number) => String(value).padStart(2, '0')
  return hours > 0 ? `${hours}:${pad(minutes)}:${pad(secs)}` : `${pad(minutes)}:${pad(secs)}`
}

/** `1680` → `28`. Dùng cho nhãn ngân sách theo phút. */
export function formatMinutes(seconds: number): number {
  return Math.max(0, Math.round(seconds / 60))
}

/** Đọc số giây từ một trường của thẻ phạm vi; `null`/lạ ⇒ `null`. */
export function secondsOrNull(value: number | null): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}
