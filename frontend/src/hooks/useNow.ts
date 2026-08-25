/**
 * Đồng hồ dùng chung cho mọi bộ đếm ngược (thẻ xin quyền, giấy phép).
 *
 * Trả về mốc thời gian hiện tại theo ms, tự cập nhật mỗi giây. Truyền vào
 * `formatCountdown` / `isExpired` để component không tự gọi `Date.now()` rải
 * rác — như vậy mọi bộ đếm trên màn hình luôn khớp nhau.
 */
import { useEffect, useState } from 'react'

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])

  return now
}
