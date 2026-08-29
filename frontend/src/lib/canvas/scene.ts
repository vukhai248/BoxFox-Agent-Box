/**
 * Cây scene canvas + helper bất biến (create/seed/serialize/deserialize/upsert/
 * remove). Mọi helper trả về scene MỚI, không đổi tham số đầu vào.
 *
 * `serialize`/`deserialize` giúp gửi scene cho agent và tải lại từ JSON ngoài
 * (backend) an toàn: deserialize bỏ field lạ (forward-compatible) và loại
 * connector mồ côi (trỏ tới node không tồn tại) để render không crash.
 */
import { PALETTE } from './palette'
import type { Anchor, CanvasConnector, CanvasNode, CanvasScene, CanvasStroke, CanvasStyle, CardKind, Point, ShapeKind } from './types'

export const SCENE_VERSION = 1

/** Style mặc định khi tạo shape (nền panel2, viền brand, bo góc 8). */
export const DEFAULT_SHAPE_STYLE: CanvasStyle = {
  fill: PALETTE.panel2,
  stroke: PALETTE.brand,
  strokeWidth: 2,
  radius: 8,
}

/** Style mặc định khi tạo card (nền panel, viền line mảnh, bo góc 12). */
export const DEFAULT_CARD_STYLE: CanvasStyle = {
  fill: PALETTE.panel,
  stroke: PALETTE.line,
  strokeWidth: 1,
  radius: 12,
}

/** Kích thước + tiêu đề mặc định theo loại card (dùng cho nút "+" và fallback title). */
export const CARD_META: Record<CardKind, { width: number; height: number; title: string }> = {
  'ui-mockup': { width: 380, height: 240, title: 'Frontend UI Mockup' },
  'agent-reasoning-flow': { width: 340, height: 200, title: 'Agent Reasoning Flow' },
  'directive-annotation': { width: 500, height: 120, title: 'Directive Annotation' },
}

/** Tiêu đề fallback khi người dùng xóa trắng title của card (plain text). */
export function cardTitleFallback(card: CardKind | null): string {
  return (card && CARD_META[card]?.title) || 'Card'
}

export function createEmptyScene(): CanvasScene {
  return { version: SCENE_VERSION, nodes: [], connectors: [], strokes: [] }
}

function card(id: string, x: number, y: number, width: number, height: number, kind: CardKind, title: string, body: string): CanvasNode {
  return {
    id,
    kind: 'card',
    shape: null,
    card: kind,
    x,
    y,
    width,
    height,
    title,
    body,
    url: null,
    style: { ...DEFAULT_CARD_STYLE },
  }
}

/**
 * Seed cảnh khởi đầu tương đương tab cũ: 3 thẻ (UI mockup 380px, reasoning
 * flow 340px, annotation 500px) + 1 connector card1→card2. Id ổn định
 * (`node-c1/c2/c3`, `conn-1`) để connector/test tham chiếu được.
 */
export function createInitialScene(): CanvasScene {
  const c1 = card('node-c1', 40, 40, 380, 240, 'ui-mockup', 'Frontend UI Mockup',
    'Self-hosted AI computer environment with unified sandbox, live browser frame & VS Code integration.')
  const c2 = card('node-c2', 480, 40, 340, 200, 'agent-reasoning-flow', 'Agent Reasoning Flow',
    'User Visual Prompt → ReAct Plan Generator → Sandbox Tool Execution')
  const c3 = card('node-c3', 40, 340, 500, 120, 'directive-annotation', 'Annotation & Directive for Agent',
    'Agent: when the user edits the wireframe above, convert the UI changes into React components and render them live in the sandbox.')
  const connectors: CanvasConnector[] = [
    { id: 'conn-1', fromNodeId: 'node-c1', toNodeId: 'node-c2', fromAnchor: 'right', toAnchor: 'left', stroke: PALETTE.brand, strokeWidth: 2 },
  ]
  return { version: SCENE_VERSION, nodes: [c1, c2, c3], connectors, strokes: [] }
}

export function nodeById(scene: CanvasScene, id: string): CanvasNode | undefined {
  return scene.nodes.find((n) => n.id === id)
}

/** Chèn hoặc ghi đè node theo id (thay thế node đang tuyển chọn id đó). */
export function upsertNode(scene: CanvasScene, node: CanvasNode): CanvasScene {
  const exists = scene.nodes.some((n) => n.id === node.id)
  const nodes = exists ? scene.nodes.map((n) => (n.id === node.id ? node : n)) : [...scene.nodes, node]
  return { ...scene, nodes }
}

/** Xóa node theo id và MỌI connector trỏ tới node đó (cascade), bất biến. */
export function removeNode(scene: CanvasScene, id: string): CanvasScene {
  return {
    ...scene,
    nodes: scene.nodes.filter((n) => n.id !== id),
    connectors: scene.connectors.filter((c) => c.fromNodeId !== id && c.toNodeId !== id),
  }
}

export function serialize(scene: CanvasScene): string {
  return JSON.stringify(scene)
}

/* ------------------------- deserialize / chuẩn hóa ------------------------- */

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

function num(v: unknown, fallback = 0): number {
  return typeof v === 'number' && Number.isFinite(v) ? v : fallback
}

function str(v: unknown, fallback = ''): string {
  return typeof v === 'string' ? v : fallback
}

export function isShapeKind(v: unknown): v is ShapeKind {
  return v === 'rect' || v === 'ellipse' || v === 'triangle' || v === 'diamond'
}

export function isCardKind(v: unknown): v is CardKind {
  return v === 'ui-mockup' || v === 'agent-reasoning-flow' || v === 'directive-annotation'
}

export function isAnchor(v: unknown): v is Anchor {
  return v === 'top' || v === 'right' || v === 'bottom' || v === 'left' || v === 'center'
}

function normalizeStyle(raw: unknown): CanvasStyle {
  const r = isRecord(raw) ? raw : {}
  return {
    fill: str(r.fill, PALETTE.panel2),
    stroke: str(r.stroke, PALETTE.brand),
    strokeWidth: num(r.strokeWidth, 2),
    radius: num(r.radius, 8),
  }
}

function normalizeNode(raw: unknown): CanvasNode | null {
  const r = isRecord(raw) ? raw : null
  if (!r || typeof r.id !== 'string') return null
  const kind = r.kind === 'shape' || r.kind === 'card' || r.kind === 'webview' ? r.kind : 'card'
  return {
    id: r.id,
    kind,
    shape: kind === 'shape' && isShapeKind(r.shape) ? r.shape : null,
    card: kind === 'card' && isCardKind(r.card) ? r.card : null,
    x: num(r.x),
    y: num(r.y),
    width: num(r.width),
    height: num(r.height),
    title: str(r.title),
    body: str(r.body),
    url: typeof r.url === 'string' ? r.url : null,
    style: normalizeStyle(r.style),
  }
}

function normalizeConnector(raw: unknown): CanvasConnector | null {
  const r = isRecord(raw) ? raw : null
  if (!r || typeof r.id !== 'string') return null
  return {
    id: r.id,
    fromNodeId: str(r.fromNodeId),
    toNodeId: str(r.toNodeId),
    fromAnchor: isAnchor(r.fromAnchor) ? r.fromAnchor : 'center',
    toAnchor: isAnchor(r.toAnchor) ? r.toAnchor : 'center',
    stroke: str(r.stroke, PALETTE.brand),
    strokeWidth: num(r.strokeWidth, 2),
  }
}

function normalizeStroke(raw: unknown): CanvasStroke | null {
  const r = isRecord(raw) ? raw : null
  if (!r || typeof r.id !== 'string') return null
  const points: Point[] = Array.isArray(r.points)
    ? r.points.reduce<Point[]>((acc, item) => {
        const p = isRecord(item) ? { x: num(item.x), y: num(item.y) } : null
        return p ? [...acc, p] : acc
      }, [])
    : []
  return { id: r.id, points, color: str(r.color, PALETTE.brand), width: num(r.width, 2) }
}

/**
 * Parse JSON (chuỗi hoặc object đã parse) thành `CanvasScene`. Ném `Error` có
 * thông điệp công khai khi sai shape/thiếu mảng/phiên bản khác 1. Field lạ bị
 * bỏ qua; connector mồ côi (từ/to không tồn tại) bị loại.
 */
export function deserialize(json: string | unknown): CanvasScene {
  let raw: unknown = json
  if (typeof json === 'string') {
    try {
      raw = JSON.parse(json)
    } catch {
      throw new Error('Canvas JSON không hợp lệ: không thể parse.')
    }
  }
  if (!isRecord(raw)) throw new Error('Canvas JSON không hợp lệ: không phải object.')
  if (raw.version !== SCENE_VERSION) throw new Error(`Canvas JSON version không được hỗ trợ (cần ${SCENE_VERSION}).`)
  if (!Array.isArray(raw.nodes) || !Array.isArray(raw.connectors) || !Array.isArray(raw.strokes)) {
    throw new Error('Canvas JSON thiếu mảng nodes/connectors/strokes.')
  }

  const nodes = raw.nodes.map(normalizeNode).filter((n): n is CanvasNode => n !== null)
  const validIds = new Set(nodes.map((n) => n.id))
  const connectors = raw.connectors
    .map(normalizeConnector)
    .filter((c): c is CanvasConnector => c !== null)
    .filter((c) => validIds.has(c.fromNodeId) && validIds.has(c.toNodeId))
  const strokes = raw.strokes.map(normalizeStroke).filter((s): s is CanvasStroke => s !== null)

  return { version: SCENE_VERSION, nodes, connectors, strokes }
}
