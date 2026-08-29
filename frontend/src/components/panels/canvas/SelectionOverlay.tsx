/**
 * Overlay chọn & resize (SVG, world-space, nằm trên cùng). Chỉ vẽ cho shape đang
 * chọn: viền nét đứt + 8 tay cầm resize (4 góc + 4 trung điểm cạnh). Kích thước
 * tay cầm chia theo `scale` để luôn trông ~8px trên màn hình.
 */
import type { PointerEvent as ReactPointerEvent } from 'react'
import type { CanvasNode } from '../../../lib/canvas'

export type ResizeHandle = 'nw' | 'n' | 'ne' | 'e' | 'se' | 's' | 'sw' | 'w'

interface SelectionOverlayProps {
  nodes: CanvasNode[]
  selection: ReadonlySet<string>
  scale: number
  onHandlePointerDown: (e: ReactPointerEvent, nodeId: string, handle: ResizeHandle) => void
}

const HANDLES: ResizeHandle[] = ['nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w']
const CURSOR: Record<ResizeHandle, string> = {
  nw: 'nwse-resize',
  se: 'nwse-resize',
  ne: 'nesw-resize',
  sw: 'nesw-resize',
  n: 'ns-resize',
  s: 'ns-resize',
  e: 'ew-resize',
  w: 'ew-resize',
}

export function handlePoint(handle: ResizeHandle, x: number, y: number, w: number, h: number): { x: number; y: number } {
  switch (handle) {
    case 'nw':
      return { x, y }
    case 'n':
      return { x: x + w / 2, y }
    case 'ne':
      return { x: x + w, y }
    case 'e':
      return { x: x + w, y: y + h / 2 }
    case 'se':
      return { x: x + w, y: y + h }
    case 's':
      return { x: x + w / 2, y: y + h }
    case 'sw':
      return { x, y: y + h }
    case 'w':
      return { x, y: y + h / 2 }
  }
}

export function SelectionOverlay({ nodes, selection, scale, onHandlePointerDown }: SelectionOverlayProps) {
  const handleSize = 8 / Math.max(scale, 0.1)

  return (
    <svg className="absolute left-0 top-0" style={{ width: 0, height: 0, overflow: 'visible', pointerEvents: 'none' }}>
      {nodes.map((n) => {
        if (n.kind !== 'shape' || !selection.has(n.id)) return null
        return (
          <g key={`sel-${n.id}`}>
            <rect
              x={n.x}
              y={n.y}
              width={n.width}
              height={n.height}
              fill="none"
              stroke="#3b82f6"
              strokeWidth={1.5 / Math.max(scale, 0.1)}
              strokeDasharray={`${4 / Math.max(scale, 0.1)} ${3 / Math.max(scale, 0.1)}`}
            />
            {HANDLES.map((handle) => {
              const p = handlePoint(handle, n.x, n.y, n.width, n.height)
              return (
                <rect
                  key={handle}
                  x={p.x - handleSize / 2}
                  y={p.y - handleSize / 2}
                  width={handleSize}
                  height={handleSize}
                  rx={1.5}
                  fill="#ffffff"
                  stroke="#3b82f6"
                  strokeWidth={1 / Math.max(scale, 0.1)}
                  style={{ cursor: CURSOR[handle], pointerEvents: 'all' }}
                  onPointerDown={(e) => onHandlePointerDown(e, n.id, handle)}
                />
              )
            })}
          </g>
        )
      })}
    </svg>
  )
}
