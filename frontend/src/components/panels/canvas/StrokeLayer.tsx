/**
 * Lớp nét bút chì (SVG, world-space). Mỗi `CanvasStroke` là một path độc lập;
 * nét đang chọn vẽ thêm halo brand để nhìn rõ. `draftStroke` là nét đang vẽ
 * (chưa commit) do hook giữ.
 */
import type { CanvasStroke } from '../../../lib/canvas'
import { pointsToPath } from '../../../lib/canvas'

interface StrokeLayerProps {
  strokes: CanvasStroke[]
  draftStroke: CanvasStroke | null
  selection: ReadonlySet<string>
}

export function StrokeLayer({ strokes, draftStroke, selection }: StrokeLayerProps) {
  return (
    <svg className="absolute left-0 top-0" style={{ width: 0, height: 0, overflow: 'visible', pointerEvents: 'none' }}>
      {strokes.map((s) => (
        <g key={s.id}>
          {selection.has(s.id) && (
            <path d={pointsToPath(s.points)} stroke="#3b82f6" strokeWidth={s.width + 5} fill="none" strokeLinecap="round" strokeLinejoin="round" opacity={0.3} />
          )}
          <path d={pointsToPath(s.points)} stroke={s.color} strokeWidth={s.width} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </g>
      ))}
      {draftStroke && draftStroke.points.length > 0 && (
        <path
          d={pointsToPath(draftStroke.points)}
          stroke={draftStroke.color}
          strokeWidth={draftStroke.width}
          fill="none"
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={0.9}
        />
      )}
      {/* Nét một chấm khi mới bắt đầu vẽ: vẽ chấm tròn để thấy được. */}
      {draftStroke && draftStroke.points.length === 1 && (
        <circle cx={draftStroke.points[0].x} cy={draftStroke.points[0].y} r={draftStroke.width / 2} fill={draftStroke.color} />
      )}
    </svg>
  )
}
