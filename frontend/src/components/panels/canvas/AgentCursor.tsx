/**
 * Con trỏ của Design Lead trên canvas (world-space).
 *
 * Vì sao cần: op của agent được áp cả lô trong một khung hình, nên không ai thấy AI "vẽ". Con trỏ này
 * là thứ duy nhất nói cho chủ nhà biết AI đang ở đâu và đang làm gì: mũi tên đi tới điểm đặt bút, một
 * vòng nhấp khi bắt đầu một bước, kèm nhãn nhỏ. Nó nằm TRONG lớp đã transform (pan/zoom) nên phải
 * tự chia tỉ lệ `1/scale` để giữ kích thước không đổi trên màn hình.
 */
import type { CursorState } from '../../../lib/canvas'

/** Cạnh của mũi tên con trỏ (screen px) — cỡ chuột mặc định của hệ điều hành. */
const ARROW_SIZE = 22

export function AgentCursor({ cursor, scale, label }: { cursor: CursorState; scale: number; label: string }) {
  if (!cursor.visible) return null
  const shrink = scale > 0 ? 1 / scale : 1
  return (
    <div
      data-testid="design-canvas-cursor"
      data-pressed={cursor.pressed ? 'true' : 'false'}
      aria-hidden
      className="pointer-events-none absolute left-0 top-0 z-30"
      style={{ transform: `translate(${cursor.x}px, ${cursor.y}px) scale(${shrink})`, transformOrigin: '0 0' }}
    >
      {cursor.pressed && (
        <span
          data-testid="design-canvas-cursor-press"
          className="absolute left-0 top-0 -translate-x-1/2 -translate-y-1/2 rounded-full border border-brand/70 bg-brand/10"
          style={{ width: 26, height: 26 }}
        />
      )}
      <svg width={ARROW_SIZE} height={ARROW_SIZE} viewBox="0 0 22 22" aria-hidden className="drop-shadow">
        <path d="M2 1.5 L2 17 L6.4 12.9 L9.2 19.4 L12.2 18 L9.4 11.7 L15.4 11.7 Z" fill="#f4f4f5" stroke="#18181b" strokeWidth="1.2" strokeLinejoin="round" />
      </svg>
      <span className="absolute left-4 top-4 whitespace-nowrap rounded bg-brand/90 px-1.5 py-0.5 text-[10px] font-medium text-white shadow">
        {label}
      </span>
    </div>
  )
}
