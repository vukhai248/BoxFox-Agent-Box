/**
 * Lớp mũi tên connector (SVG, world-space). Endpoint tính lại mỗi render qua
 * `connectorPath` nên khi node di chuyển, hai đầu trượt theo cạnh neo. `preview`
 * là đường nét đứt đang kéo (chế độ Arrow) chưa thả.
 */
import type { CanvasConnector, CanvasNode, Point } from '../../../lib/canvas'
import { connectorPath } from '../../../lib/canvas'

interface ConnectorLayerProps {
  nodes: CanvasNode[]
  connectors: CanvasConnector[]
  preview: { from: Point; to: Point } | null
}

export function ConnectorLayer({ nodes, connectors, preview }: ConnectorLayerProps) {
  return (
    <svg className="absolute left-0 top-0" style={{ width: 0, height: 0, overflow: 'visible', pointerEvents: 'none' }}>
      {connectors.map((c) => {
        const d = connectorPath(c, nodes)
        if (!d) return null
        return <path key={c.id} d={d} stroke={c.stroke} strokeWidth={c.strokeWidth} fill="none" strokeLinecap="round" />
      })}
      {preview && (
        <path
          d={`M ${preview.from.x} ${preview.from.y} L ${preview.to.x} ${preview.to.y}`}
          stroke="#3b82f6"
          strokeWidth={2}
          strokeDasharray="6 5"
          fill="none"
          opacity={0.7}
        />
      )}
    </svg>
  )
}
