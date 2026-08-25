/**
 * Thanh kéo giãn giữa cột chat và panel phải (Resizer).
 * Giới hạn theo pixel cứng (Min-width Chat: 420px, Min-width Workspace: 460px),
 * tự động thích ứng mượt mà khi người dùng thu gọn hoặc mở rộng Sidebar.
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

  const onMove = useCallback(
    (event: MouseEvent) => {
      if (!dragging.current) return
      const container = containerRef.current
      if (!container) return
      const rect = container.getBoundingClientRect()
      if (rect.width === 0) return

      const clientX = event.clientX - rect.left
      // Khóa an toàn 480px tuyệt đối cho cả 2 bên
      const minChat = Math.min(MIN_CHAT_WIDTH_PX, rect.width * 0.45)
      const minWorkspace = Math.min(MIN_WORKSPACE_WIDTH_PX, rect.width * 0.45)
      const clampedX = Math.max(minChat, Math.min(rect.width - minWorkspace, clientX))

      setSplitRatio(clampedX / rect.width)
    },
    [containerRef, setSplitRatio],
  )

  useEffect(() => {
    const stop = () => {
      dragging.current = false
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', stop)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', stop)
    }
  }, [onMove])

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={t('common.resizeHandle')}
      aria-valuenow={Math.round(splitRatio * 100)}
      tabIndex={0}
      title={t('common.resizeHandle')}
      onMouseDown={() => {
        dragging.current = true
        document.body.style.cursor = 'col-resize'
        document.body.style.userSelect = 'none'
      }}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') setSplitRatio(splitRatio - 0.02)
        if (event.key === 'ArrowRight') setSplitRatio(splitRatio + 0.02)
      }}
      className="group relative flex w-2 shrink-0 cursor-col-resize items-center justify-center bg-transparent transition select-none hover:bg-brand/10 focus:bg-brand/15 focus:outline-hidden"
    >
      {/* Visual Divider Line */}
      <div className="h-full w-px bg-line transition group-hover:bg-brand/50 group-focus:bg-brand" />

      {/* Grip dots (6 chấm dọc phong cách Devin/VS Code) */}
      <div className="pointer-events-none absolute flex flex-col gap-1 rounded bg-panel px-0.5 py-1 text-muted opacity-0 shadow-xs transition group-hover:opacity-100 group-focus:opacity-100 border border-line">
        <span className="size-1 rounded-full bg-muted-foreground/60" />
        <span className="size-1 rounded-full bg-muted-foreground/60" />
        <span className="size-1 rounded-full bg-muted-foreground/60" />
      </div>
    </div>
  )
}
