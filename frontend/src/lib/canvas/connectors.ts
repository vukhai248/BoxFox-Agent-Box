/**
 * Neo (anchor) và mũi tên connector — hàm thuần, không đọc DOM.
 *
 * Connector lưu `{fromNodeId, toNodeId}` + 2 cạnh neo, KHÔNG lưu tọa độ tuyệt
 * đối: endpoint được tính lại mỗi render bằng `anchorPoint` nên khi node di
 * chuyển, hai đầu trượt mượt theo cạnh đã chọn (không đứt trục).
 */
import type { Anchor, CanvasConnector, CanvasNode, Point } from './types'
import { distanceToSegment } from './geometry'

/** Các cạnh neo khả dụng của một node (thứ tự hiển thị cố định: top, right, bottom, left, center). */
export const ANCHOR_SIDES: readonly Anchor[] = ['top', 'right', 'bottom', 'left', 'center']

/** Chiều dài đầu mũi tên (world px). */
export const ARROW_HEAD_LEN = 14

/** Tỷ lệ sải cánh so với chiều dài đầu mũi tên. */
export const ARROW_WING_RATIO = 0.55

/** Góc ± (độ) của hai cánh arrowhead so với hướng thân. */
export const ARROW_WING_ANGLE_DEG = 140

/** Điểm neo theo cạnh `side` trên node (world-space). */
export function anchorPoint(node: CanvasNode, side: Anchor): Point {
  const cx = node.x + node.width / 2
  const cy = node.y + node.height / 2
  switch (side) {
    case 'top':
      return { x: cx, y: node.y }
    case 'right':
      return { x: node.x + node.width, y: cy }
    case 'bottom':
      return { x: cx, y: node.y + node.height }
    case 'left':
      return { x: node.x, y: cy }
    case 'center':
      return { x: cx, y: cy }
  }
}

/**
 * Chọn cặp neo tốt nhất giữa node `a` và `b` theo hướng trục giữa hai tâm node.
 * Quy tắc deterministic (không dùng `center`): vector tâm b→a lệch NGANG
 * (|dx| ≥ |dy|) thì nối cạnh trái/phải theo chiều; ngược lại nối cạnh trên/dưới.
 * Nhờ đó connector "đổ" đúng hướng liên kết (chạy ngang → right/left, cao dọc →
 * bottom/top). Chỉ chạy LÚC TẠO connector (và khi chủ động re-bind), không chạy
 * mỗi lần move.
 */
export function nearestAnchors(a: CanvasNode, b: CanvasNode): { from: Anchor; to: Anchor } {
  const dx = b.x + b.width / 2 - (a.x + a.width / 2)
  const dy = b.y + b.height / 2 - (a.y + a.height / 2)
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0 ? { from: 'right', to: 'left' } : { from: 'left', to: 'right' }
  }
  return dy >= 0 ? { from: 'bottom', to: 'top' } : { from: 'top', to: 'bottom' }
}

/**
 * Hai endpoint hiện tại của connector, tính lại từ cây node. Trả `null` nếu
 * thiếu node tham chiếu (connector mồ côi) — để caller/hit-test xử lý an toàn.
 */
export function connectorPoints(connector: CanvasConnector, nodes: CanvasNode[]): { from: Point; to: Point } | null {
  const fromNode = nodes.find((n) => n.id === connector.fromNodeId)
  const toNode = nodes.find((n) => n.id === connector.toNodeId)
  if (!fromNode || !toNode) return null
  return {
    from: anchorPoint(fromNode, connector.fromAnchor),
    to: anchorPoint(toNode, connector.toAnchor),
  }
}

function rotate(vector: Point, angleDeg: number): Point {
  const rad = (angleDeg * Math.PI) / 180
  const cos = Math.cos(rad)
  const sin = Math.sin(rad)
  return { x: vector.x * cos - vector.y * sin, y: vector.x * sin + vector.y * cos }
}

/** Path SVG của mũi tên: thân + 2 cánh arrowhead. Trả `''` nếu ref node mất. */
export function connectorPath(connector: CanvasConnector, nodes: CanvasNode[]): string {
  const pts = connectorPoints(connector, nodes)
  if (!pts) return ''
  const { from, to } = pts

  const dx = to.x - from.x
  const dy = to.y - from.y
  const len = Math.hypot(dx, dy)
  if (len === 0) return `M ${from.x} ${from.y} L ${to.x} ${to.y}`

  const ux = dx / len
  const uy = dy / len
  const base = { x: to.x - ux * ARROW_HEAD_LEN, y: to.y - uy * ARROW_HEAD_LEN }
  const wingLen = ARROW_HEAD_LEN * ARROW_WING_RATIO
  const w1 = rotate({ x: ux, y: uy }, ARROW_WING_ANGLE_DEG)
  const w2 = rotate({ x: ux, y: uy }, -ARROW_WING_ANGLE_DEG)

  return [
    `M ${from.x} ${from.y} L ${base.x} ${base.y}`,
    `M ${base.x} ${base.y} L ${base.x + w1.x * wingLen} ${base.y + w1.y * wingLen}`,
    `M ${base.x} ${base.y} L ${base.x + w2.x * wingLen} ${base.y + w2.y * wingLen}`,
  ].join(' ')
}

/** Hit-test: điểm `p` có gần thân mũi tên trong `tolerance` (world px) không. */
export function hitTestConnector(connector: CanvasConnector, nodes: CanvasNode[], p: Point, tolerance = 8): boolean {
  const pts = connectorPoints(connector, nodes)
  if (!pts) return false
  return distanceToSegment(p, pts.from, pts.to) <= tolerance
}
