/**
 * Bảng chỉnh style cho shape đang chọn: màu fill, màu viền, độ dày viền, bo góc.
 * Gọi `updateNodeStyle` (transient — không tạo bước undo mỗi lần kéo thanh trượt).
 */
import { Palette } from 'lucide-react'
import type { CanvasNode, CanvasStyle } from '../../../lib/canvas'
import { FILL_SWATCHES, STROKE_SWATCHES } from '../../../lib/canvas'

interface StylePaletteProps {
  node: CanvasNode
  onUpdateStyle: (id: string, patch: Partial<CanvasStyle>) => void
}

function Swatch({ color, active, onClick }: { color: string; active: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={`color ${color}`}
      className={`size-4 rounded-full border transition cursor-pointer ${active ? 'border-brand ring-1 ring-brand/50' : 'border-line hover:border-muted'}`}
      style={{ backgroundColor: color }}
    />
  )
}

export function StylePalette({ node, onUpdateStyle }: StylePaletteProps) {
  const id = node.id
  const style = node.style

  return (
    <div className="pointer-events-auto absolute bottom-3 left-1/2 z-30 flex max-w-[calc(100%-16px)] -translate-x-1/2 items-center gap-4 overflow-x-auto rounded-lg border border-line bg-panel2/90 px-3 py-2 shadow-xl backdrop-blur-md">
      <div className="flex shrink-0 items-center gap-1.5 pr-3 border-r border-line">
        <Palette className="size-3.5 text-brand" />
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted">Fill</span>
        <div className="flex items-center gap-1">
          {FILL_SWATCHES.map((c) => (
            <Swatch key={c} color={c} active={style.fill === c} onClick={() => onUpdateStyle(id, { fill: c })} />
          ))}
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-1.5 pr-3 border-r border-line">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted">Stroke</span>
        <div className="flex items-center gap-1">
          {STROKE_SWATCHES.map((c) => (
            <Swatch key={c} color={c} active={style.stroke === c} onClick={() => onUpdateStyle(id, { stroke: c })} />
          ))}
        </div>
      </div>

      <label className="flex shrink-0 items-center gap-1.5 text-[10px] text-muted">
        <span className="font-medium uppercase tracking-wider">Width</span>
        <input
          type="range"
          min={1}
          max={8}
          step={1}
          value={style.strokeWidth}
          onChange={(e) => onUpdateStyle(id, { strokeWidth: Number(e.target.value) })}
          className="h-1 w-16 cursor-pointer accent-brand"
        />
        <span className="w-3 font-mono text-fg">{style.strokeWidth}</span>
      </label>

      <label className="flex shrink-0 items-center gap-1.5 text-[10px] text-muted">
        <span className="font-medium uppercase tracking-wider">Radius</span>
        <input
          type="range"
          min={0}
          max={24}
          step={1}
          value={style.radius}
          onChange={(e) => onUpdateStyle(id, { radius: Number(e.target.value) })}
          className="h-1 w-16 cursor-pointer accent-brand"
        />
        <span className="w-4 font-mono text-fg">{style.radius}</span>
      </label>
    </div>
  )
}
