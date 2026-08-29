/**
 * Thẻ trên canvas (ui-mockup / agent-reasoning-flow / directive-annotation).
 * Render bằng div thuần để chứa input/textarea chỉnh sửa PLAIN TEXT. Tiêu đề
 * sửa inline ở header; thân là textarea. Kéo card bằng header (giữ input bấm
 * được mà không kích hoạt drag).
 */
import { Eye, GripHorizontal, Layers, Sliders } from 'lucide-react'
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import type { CanvasNode, CardKind } from '../../../lib/canvas'
import { cardTitleFallback } from '../../../lib/canvas'

interface CardNodeProps {
  node: CanvasNode
  selected: boolean
  onPointerDown: (e: ReactPointerEvent, nodeId: string) => void
  onContextMenu: (e: ReactMouseEvent, nodeId: string) => void
  onUpdateTitle: (id: string, title: string) => void
  onUpdateBody: (id: string, body: string) => void
}

const CARD_ICON: Record<CardKind, typeof Layers> = {
  'ui-mockup': Layers,
  'agent-reasoning-flow': Sliders,
  'directive-annotation': Eye,
}

const CARD_BADGE: Record<CardKind, { label: string; className: string }> = {
  'ui-mockup': { label: 'Interactive', className: 'bg-brand/15 text-brand' },
  'agent-reasoning-flow': { label: 'Workflow', className: 'bg-amber-500/15 text-amber-300' },
  'directive-annotation': { label: 'Directive', className: 'bg-amber-500/15 text-amber-300' },
}

export function CardNode({ node, selected, onPointerDown, onContextMenu, onUpdateTitle, onUpdateBody }: CardNodeProps) {
  const kind = node.card ?? 'ui-mockup'
  const Icon = CARD_ICON[kind]
  const badge = CARD_BADGE[kind]

  return (
    <div
      data-node-id={node.id}
      className="absolute"
      style={{ left: node.x, top: node.y, width: node.width, height: node.height }}
    >
      <div
        className={`flex h-full w-full flex-col overflow-hidden border bg-panel/95 backdrop-blur-md shadow-2xl transition-shadow ${
          selected ? 'ring-2 ring-brand/30 border-brand' : ''
        }`}
        style={{ borderColor: node.style.stroke, borderRadius: node.style.radius, backgroundColor: node.style.fill }}
      >
        <div
          className="flex cursor-move items-center justify-between gap-2 border-b border-line/60 px-3 py-2 select-none"
          onPointerDown={(e) => onPointerDown(e, node.id)}
          onContextMenu={(e) => onContextMenu(e, node.id)}
        >
          <div className="flex min-w-0 flex-1 items-center gap-1.5">
            <GripHorizontal className="size-3 shrink-0 text-muted" />
            <Icon className="size-3.5 shrink-0 text-brand" />
            <input
              type="text"
              value={node.title}
              onChange={(e) => onUpdateTitle(node.id, e.target.value)}
              onPointerDown={(e) => e.stopPropagation()}
              className="min-w-0 flex-1 truncate bg-transparent text-xs font-medium text-fg outline-none focus:text-brand"
              placeholder={cardTitleFallback(node.card)}
              aria-label="Card title"
            />
          </div>
          <span className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${badge.className}`}>{badge.label}</span>
        </div>
        <div className="flex-1 overflow-hidden p-3">
          <textarea
            value={node.body}
            onChange={(e) => onUpdateBody(node.id, e.target.value)}
            className="h-full w-full resize-none bg-transparent text-xs leading-relaxed text-muted outline-none"
            placeholder="Description (plain text)…"
            onPointerDown={(e) => e.stopPropagation()}
            aria-label="Card body"
            style={{ color: kind === 'directive-annotation' ? 'var(--c-fg)' : undefined }}
          />
        </div>
      </div>
    </div>
  )
}
