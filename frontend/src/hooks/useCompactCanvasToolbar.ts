/**
 * Đo bề rộng toolbar Design Canvas để quyết định có vào chế độ compact (chỉ
 * icon) hay không. Sao y khuôn mẫu `useCompactComposer.ts`: bọc `ResizeObserver`
 * trong `requestAnimationFrame`, chỉ `setState` khi boolean thật sự đổi.
 */
import { useEffect, useState, type RefObject } from 'react'
import { isCompactCanvasToolbar } from '../lib/layout/canvas'

export function useCompactCanvasToolbar(ref: RefObject<HTMLElement | null>): boolean {
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
        const next = isCompactCanvasToolbar(width)
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
