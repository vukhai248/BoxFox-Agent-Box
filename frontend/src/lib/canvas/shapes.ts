/**
 * Hình học shape vector thuần (không đọc DOM): đỉnh hình, phép thử điểm trong
 * polygon và hit-test theo từng `ShapeKind`. Dùng chung cho render SVG và hit-test.
 *
 * Ghi chú "Circle": canvas không có shape tròn riêng — "hình tròn" là `ellipse`
 * với `width === height`, hit-test dùng phương trình ellipse chuẩn.
 */
import type { Point, ShapeKind } from './types'

function isPointInPolygon(p: Point, verts: Point[]): boolean {
  let inside = false
  for (let i = 0, j = verts.length - 1; i < verts.length; j = i++) {
    const a = verts[i]!
    const b = verts[j]!
    const intersects = (a.y > p.y) !== (b.y > p.y) && p.x < ((b.x - a.x) * (p.y - a.y)) / (b.y - a.y) + a.x
    if (intersects) inside = !inside
  }
  return inside
}

/**
 * Đỉnh của shape trong bounding (x, y, width, height) — thứ tự theo chiều kim
 * đồng hồ để `isPointInPolygon` xử lý đúng. `ellipse` trả `[]` vì render bằng
 * thẻ `<ellipse>` riêng; hit-test ellipse dùng phương trình chuẩn.
 */
export function shapeVertices(shape: ShapeKind, x: number, y: number, w: number, h: number): Point[] {
  switch (shape) {
    case 'rect':
      return [
        { x, y },
        { x: x + w, y },
        { x: x + w, y: y + h },
        { x, y: y + h },
      ]
    case 'diamond':
      return [
        { x: x + w / 2, y },
        { x: x + w, y: y + h / 2 },
        { x: x + w / 2, y: y + h },
        { x, y: y + h / 2 },
      ]
    case 'triangle':
      return [
        { x: x + w / 2, y },
        { x: x + w, y: y + h },
        { x, y: y + h },
      ]
    case 'ellipse':
      return []
  }
}

/** Đỉnh polygon thành chuỗi `x,y` cho attribute `points` của `<polygon>`. */
export function verticesToPoints(verts: Point[]): string {
  return verts.map((p) => `${p.x},${p.y}`).join(' ')
}

/**
 * Hit-test một shape tại điểm `p` (world-space) trong bounding (x, y, w, h).
 * `ellipse` dùng phương trình `((px - cx)/rx)^2 + ((py - cy)/ry)^2 <= 1`;
 * `rect`/`triangle`/`diamond` dùng point-in-polygon trên đỉnh.
 */
export function hitTestShape(shape: ShapeKind, x: number, y: number, w: number, h: number, p: Point): boolean {
  if (shape === 'ellipse') {
    const rx = w / 2
    const ry = h / 2
    if (rx <= 0 || ry <= 0) return false
    const cx = x + rx
    const cy = y + ry
    return ((p.x - cx) / rx) ** 2 + ((p.y - cy) / ry) ** 2 <= 1
  }
  return isPointInPolygon(p, shapeVertices(shape, x, y, w, h))
}
