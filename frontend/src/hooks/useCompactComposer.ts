/**
 * Đo bề rộng của một phần tử DOM để quyết định `ChatInputBar` có nên vào
 * chế độ compact hay không. Sao y khuôn mẫu `useVncScreen.ts` (Effect D,
 * dòng 156-179): bọc `ResizeObserver` trong `requestAnimationFrame` để không
 * đo lúc layout đang thrash, chỉ `setState` khi giá trị boolean thật sự đổi.
 */
import { useEffect, useState, type RefObject } from 'react'
import { isCompactComposer } from '../lib/layout/composer'

export function useCompactComposer(ref: RefObject<HTMLElement | null>): boolean {
  const [compact, setCompact] = useState(false)

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (typeof ResizeObserver === 'undefined') return

    let raf = 0
    const ro = new ResizeObserver((entries) => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const width = entries[0]?.contentRect.width ?? 0
        const next = isCompactComposer(width)
        setCompact((prev) => (prev === next ? prev : next))
      })
    })
    ro.observe(el)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [ref])

  return compact
}
