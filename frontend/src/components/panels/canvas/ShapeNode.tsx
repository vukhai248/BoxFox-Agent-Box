/**
 * Hình vector trên canvas (rect/ellipse/triangle/diamond). Render bằng SVG để
 * kiểm soát fill/stroke/strokeWidth/radius; wrapper div nhận pointer cho move/
 * select (hit theo bbox — đủ cho bản này).
 */
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import type { CanvasNode } from '../../../lib/canvas'
import { shapeVertices, verticesToPoints } from '../../../lib/canvas'

interface ShapeNodeProps {
  node: CanvasNode
  selected: boolean
  onPointerDown: (e: ReactPointerEvent, nodeId: string) => void
  onContextMenu: (e: ReactMouseEvent, nodeId: string) => void
}

export function ShapeNode({ node, selected, onPointerDown, onContextMenu }: ShapeNodeProps) {
  const { shape } = node
  if (!shape) return null
  const { fill, stroke, strokeWidth, radius } = node.style

  return (
    <div
      data-node-id={node.id}
      className={`absolute cursor-move ${selected ? '' : ''}`}
      style={{ left: node.x, top: node.y, width: node.width, height: node.height }}
      onPointerDown={(e) => onPointerDown(e, node.id)}
      onContextMenu={(e) => onContextMenu(e, node.id)}
    >
      <svg
        className="absolute left-0 top-0 overflow-visible"
        width={node.width}
        height={node.height}
        style={{ pointerEvents: 'none', overflow: 'visible' }}
      >
        {shape === 'rect' && (
          <rect x={0} y={0} width={node.width} height={node.height} rx={radius} ry={radius} fill={fill} stroke={stroke} strokeWidth={strokeWidth} />
        )}
        {shape === 'ellipse' && (
          <ellipse
            cx={node.width / 2}
            cy={node.height / 2}
            rx={node.width / 2}
            ry={node.height / 2}
            fill={fill}
            stroke={stroke}
            strokeWidth={strokeWidth}
          />
        )}
        {(shape === 'triangle' || shape === 'diamond') && (
          <polygon
            points={verticesToPoints(shapeVertices(shape, 0, 0, node.width, node.height))}
            fill={fill}
            stroke={stroke}
            strokeWidth={strokeWidth}
            strokeLinejoin="round"
          />
        )}
      </svg>
    </div>
  )
}
