/**
 * Thanh kéo giãn giữa cột chat và panel phải (Resizer).
 * Dùng Pointer Events + setPointerCapture để kéo không bị gián đoạn
 * khi chuột lướt qua iframe (tab IDE) hoặc canvas noVNC (tab Machine).
 * Giới hạn theo pixel cứng (Min-width Chat: 480px, Min-width Workspace: 480px).
 */
import { useCallback, useEffect, useRef } from 'react'
import { useT } from '../../i18n/context'
import { useUiStore } from '../../store/uiStore'

export const MIN_CHAT_WIDTH_PX = 480
export const MIN_WORKSPACE_WIDTH_PX = 480

export function Resizer({ containerRef }: { containerRef: React.RefObject<HTMLDivElement | null> }) {
  const t = useT()
  const splitRatio = useUiStore((s) => s.splitRatio)
  const setSplitRatio = useUiStore((s) => s.setSplitRatio)
  const dragging = useRef(false)

  const updateRatio = useCallback(
    (clientX: number) => {
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      if (rect.width === 0) return

      const x = clientX - rect.left
      const minChat = Math.min(MIN_CHAT_WIDTH_PX, rect.width * 0.45)
      const minWorkspace = Math.min(MIN_WORKSPACE_WIDTH_PX, rect.width * 0.45)
      const clampedX = Math.max(minChat, Math.min(rect.width - minWorkspace, x))

      setSplitRatio(clampedX / rect.width)
    },
    [containerRef, setSplitRatio],
  )

  const stop = useCallback(() => {
    if (!dragging.current) return
    dragging.current = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }, [])

  // Fallback: window-level mouse listeners cho các browser/trường hợp
  // không hỗ trợ Pointer Events. Khi pointer capture hoạt động,
  // các event này không chạy vì dragging.current đã được reset bởi onPointerUp.
  const onMouseMove = useCallback(
    (e: MouseEvent) => {
      if (!dragging.current) return
      updateRatio(e.clientX)
    },
    [updateRatio],
  )

  useEffect(() => {
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', stop)
    // Nếu user Alt+Tab / mất focus khi đang kéo → nhả trạng thái
    window.addEventListener('blur', stop)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', stop)
      window.removeEventListener('blur', stop)
    }
  }, [onMouseMove, stop])

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t('common.resizeHandle')}
      aria-valuenow={Math.round(splitRatio * 100)}
      tabIndex={0}
      title={t('common.resizeHandle')}
      onPointerDown={(e) => {
        e.preventDefault()
        dragging.current = true
        ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
      }}
      onPointerMove={(e) => {
        if (!dragging.current) return
        updateRatio(e.clientX)
      }}
      onPointerUp={() => stop()}
      onPointerCancel={() => stop()}
      onMouseDown={(_e) => {
        // Fallback cho browser không hỗ trợ pointer events
        if ('onpointerdown' in window) return
        dragging.current = true
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
      }}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') setSplitRatio(splitRatio - 0.02)
        if (event.key === 'ArrowRight') setSplitRatio(splitRatio + 0.02)
      }}
      className="group relative flex w-2 shrink-0 cursor-col-resize items-center justify-center bg-transparent transition select-none hover:bg-brand/10 focus:bg-brand/15 focus:outline-hidden touch-none"
    >
      {/* Visual Divider Line */}
      <div className="h-full w-px bg-line transition group-hover:bg-brand/50 group-focus:bg-brand" />

      {/* Grip dots (3 chấm dọc phong cách Devin/VS Code) */}
      <div className="pointer-events-none absolute flex flex-col gap-1 rounded bg-panel px-0.5 py-1 text-muted opacity-0 shadow-xs transition group-hover:opacity-100 group-focus:opacity-100 border border-line">
        <span className="size-1 rounded-full bg-muted-foreground/60" />
        <span className="size-1 rounded-full bg-muted-foreground/60" />
        <span className="size-1 rounded-full bg-muted-foreground/60" />
      </div>
    </div>
  )
}
