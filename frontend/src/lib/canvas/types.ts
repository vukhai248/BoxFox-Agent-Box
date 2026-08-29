/**
 * Mô hình dữ liệu canvas (JSON-portable) — nguồn sự thật duy nhất cho toàn bộ
 * Canvas. Mọi tọa độ là world-space px (chưa nhân zoom/pan). Màu là HEX thật để
 * dùng được cho attribute SVG và gửi thẳng cho agent (không `var(--c-*)`).
 */

export interface Point {
  x: number
  y: number
}

export type ShapeKind = 'rect' | 'ellipse' | 'triangle' | 'diamond'
export type CardKind = 'ui-mockup' | 'agent-reasoning-flow' | 'directive-annotation'
export type NodeKind = 'shape' | 'card' | 'webview'

export type AnchorSide = 'top' | 'right' | 'bottom' | 'left'
export type Anchor = AnchorSide | 'center'

/** Kiểu hình của node/connector/stroke; strokeWidth dùng đơn vị world px. */
export interface CanvasStyle {
  fill: string
  stroke: string
  strokeWidth: number
  radius: number
}

/**
 * Một đối tượng trên canvas: hình vector (`shape`), thẻ UI (`card`) hoặc
 * khung xem web/app live (`webview`). `title`/`body` là PLAIN TEXT (không
 * markdown/KaTeX). `url` chỉ có nghĩa khi kind === 'webview'.
 */
export interface CanvasNode {
  id: string
  kind: NodeKind
  shape: ShapeKind | null
  card: CardKind | null
  x: number
  y: number
  width: number
  height: number
  title: string
  body: string
  url: string | null
  style: CanvasStyle
}

/** Mũi tên nối giữa 2 node — lưu theo id + cạnh neo, endpoint tính lại mỗi render. */
export interface CanvasConnector {
  id: string
  fromNodeId: string
  toNodeId: string
  fromAnchor: Anchor
  toAnchor: Anchor
  stroke: string
  strokeWidth: number
}

/** Một nét bút chì vẽ tự do — đối tượng độc lập, chọn/move/đổi màu/xóa riêng. */
export interface CanvasStroke {
  id: string
  points: Point[]
  color: string
  width: number
}

export interface CanvasScene {
  version: 1
  nodes: CanvasNode[]
  connectors: CanvasConnector[]
  strokes: CanvasStroke[]
}
