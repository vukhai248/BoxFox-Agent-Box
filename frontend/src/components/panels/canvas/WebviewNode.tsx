/**
 * Node webview: hiển thị giao diện web/app THẬT lên canvas qua `<iframe>` live.
 * URL sửa inline ở header; kéo bằng header. iframe giữ pointer-events để người
 * dùng tương tác trực tiếp (scroll/click) bên trong app đang xem.
 */
import { Globe, GripHorizontal } from 'lucide-react'
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import type { CanvasNode } from '../../../lib/canvas'

interface WebviewNodeProps {
  node: CanvasNode
  selected: boolean
  onPointerDown: (e: ReactPointerEvent, nodeId: string) => void
  onContextMenu: (e: ReactMouseEvent, nodeId: string) => void
  onUpdateUrl: (id: string, url: string) => void
}

export function WebviewNode({ node, selected, onPointerDown, onContextMenu, onUpdateUrl }: WebviewNodeProps) {
  const url = node.url ?? ''

  return (
    <div
      data-node-id={node.id}
      className="absolute"
      style={{ left: node.x, top: node.y, width: node.width, height: node.height }}
    >
      <div
        className={`flex h-full w-full flex-col overflow-hidden border bg-panel shadow-2xl transition-shadow ${
          selected ? 'ring-2 ring-brand/30 border-brand' : ''
        }`}
        style={{ borderColor: node.style.stroke, borderRadius: node.style.radius, backgroundColor: node.style.fill }}
      >
        <div
          className="flex cursor-move items-center gap-2 border-b border-line/60 px-3 py-2 select-none"
          onPointerDown={(e) => onPointerDown(e, node.id)}
          onContextMenu={(e) => onContextMenu(e, node.id)}
        >
          <GripHorizontal className="size-3 shrink-0 text-muted" />
          <Globe className="size-3.5 shrink-0 text-brand" />
          <input
            type="url"
            value={url}
            onChange={(e) => onUpdateUrl(node.id, e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
            className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-fg outline-none focus:text-brand"
            placeholder="https://your-app.example.com"
            aria-label="Web preview URL"
          />
          <span className="rounded bg-emerald-500/20 px-1.5 py-0.5 text-[9px] font-bold uppercase text-emerald-300">Live</span>
        </div>
        <div className="flex-1 overflow-hidden bg-bg">
          {url ? (
            <iframe
              title={node.title || 'Web preview'}
              src={url}
              className="h-full w-full border-0"
              sandbox="allow-scripts allow-same-origin allow-forms allow-popups"
              referrerPolicy="no-referrer"
            />
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-muted">
              Enter a URL to preview a web/app here
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
