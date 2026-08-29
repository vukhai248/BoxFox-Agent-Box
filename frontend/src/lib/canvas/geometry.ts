/**
 * Hàm toán thuần (không đọc DOM) cho hệ tọa độ canvas: chuyển đổi
 * screen ↔ world, bbox và culling. `CanvasView` do hook tính từ
 * `getBoundingClientRect()` rồi truyền vào — giữ phần này unit-test được.
 */
import type { CanvasNode, Point } from './types'

export interface CanvasView {
  /** zoomLevel / 100 (0.5 = 50%, 1 = 100%, 1.5 = 150%). */
  scale: number
  /** Offset pan (px, screen-space). */
  pan: Point
  /** rect.left / rect.top của container (điểm gốc màn hình của canvas). */
  origin: Point
}

export interface Bounds {
  minX: number
  minY: number
  maxX: number
  maxY: number
}

export function screenToWorld(screen: Point, view: CanvasView): Point {
  return {
    x: (screen.x - view.origin.x - view.pan.x) / view.scale,
    y: (screen.y - view.origin.y - view.pan.y) / view.scale,
  }
}

export function worldToScreen(world: Point, view: CanvasView): Point {
  return {
    x: world.x * view.scale + view.pan.x + view.origin.x,
    y: world.y * view.scale + view.pan.y + view.origin.y,
  }
}

export function boundsOfNode(node: CanvasNode): Bounds {
  return { minX: node.x, minY: node.y, maxX: node.x + node.width, maxY: node.y + node.height }
}

export function boundsOfStroke(points: Point[]): Bounds {
  if (points.length === 0) return { minX: 0, minY: 0, maxX: 0, maxY: 0 }
  let minX = Infinity
  let minY = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  for (const p of points) {
    if (p.x < minX) minX = p.x
    if (p.y < minY) minY = p.y
    if (p.x > maxX) maxX = p.x
    if (p.y > maxY) maxY = p.y
  }
  return { minX, minY, maxX, maxY }
}

export function pointsToPath(points: Point[]): string {
  if (points.length === 0) return ''
  return points.reduce((acc, p, index) => (index === 0 ? `M ${p.x} ${p.y}` : `${acc} L ${p.x} ${p.y}`), '')
}

export function distance(a: Point, b: Point): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

/** Bbox `v` có giao với khung nhìn `viewport` không (viewport culling). */
export function fitsIn(v: Bounds, viewport: Bounds): boolean {
  return v.maxX >= viewport.minX && v.minX <= viewport.maxX && v.maxY >= viewport.minY && v.minY <= viewport.maxY
}

/** Khoảng cách từ điểm `p` tới đoạn thẳng a→b (dùng hit-test connector). */
export function distanceToSegment(p: Point, a: Point, b: Point): number {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const lenSq = dx * dx + dy * dy
  if (lenSq === 0) return distance(p, a)
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq
  t = Math.max(0, Math.min(1, t))
  return distance(p, { x: a.x + t * dx, y: a.y + t * dy })
}
