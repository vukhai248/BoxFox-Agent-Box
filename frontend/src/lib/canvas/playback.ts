/**
 * Lớp PHÁT LẠI (playback) — toán học thuần cho "agent vẽ ngay trước mặt chủ nhà".
 *
 * Vì sao có tệp này: một lời gọi `canvas_draw` áp CẢ LÔ op rồi phát đúng MỘT sự kiện
 * `design_canvas` (`design_runtime.py:1151-1178`), nên store giảm op và cảnh NHẢY từ trạng thái cũ
 * sang trạng thái mới trong một khung hình — mắt người không thấy ai vẽ, chỉ thấy kết quả. Tệp này
 * biến lô op ấy thành CÁC BƯỚC CÓ THỜI LƯỢNG (con trỏ đi tới, node lớn dần rồi gõ chữ, connector
 * vẽ dần), để tầng giao diện phát lại như một nét vẽ thật.
 *
 * Ba luật giữ cho lớp này trung thực:
 * 1. KHÔNG bịa hình học: mọi giá trị trung gian suy từ (cảnh trước, op, cảnh sau), và hết thời
 *    lượng thì cảnh trả về BẰNG ĐÚNG cảnh thật (`frameAt(plan, plan.totalMs).scene === plan.to`).
 *    Nếu chính lô op ấy KHÔNG dựng nên cảnh sau (op bị chối, cảnh do chủ nhà gửi, lệch sự kiện) thì
 *    kế hoạch rỗng: thà không phát hoạt hình còn hơn phát một bản vẽ sai.
 * 2. Mọi thời lượng đều có trần: `maxTotalMs` bị tôn trọng kể cả khi lô op dài.
 * 3. `reducedMotion` trả `totalMs = 0` — người bật giảm chuyển động thấy cảnh cuối ngay.
 *
 * Hàm ở đây KHÔNG đọc DOM, không hẹn giờ: hook `useCanvasPlayback` mới là chỗ chạy
 * `requestAnimationFrame`.
 */
import { applyCanvasAction, type CanvasAction } from './agent-protocol'
import { distance } from './geometry'
import type { CanvasConnector, CanvasNode, CanvasScene, CanvasStroke, Point } from './types'

/** Bộ số điều chỉnh tốc độ vẽ (ms, px/ms) — đo bằng mắt trên canvas khổ 1×. */
export interface PlaybackTuning {
  /** Tốc độ con trỏ, world px mỗi ms (1,4 ≈ 1400 px/s ở zoom 1). */
  cursorSpeed: number
  /** Thời gian tối thiểu cho một lần di chuyển (đi quãng ngắn vẫn phải thấy dịch chuyển). */
  moveMinMs: number
  /** Node hiện ra (lớn dần từ góc trên-trái). */
  createMs: number
  /** Tỷ lệ thời gian của bước `create` dành cho việc VẼ KHUNG (phần còn lại là gõ chữ). */
  createGrowRatio: number
  /** Connector vẽ dần. */
  connectMs: number
  /** Node đổi hình học/kiểu (op UPDATE_NODE). */
  updateMs: number
  /** Node biến mất (op DELETE_NODE). */
  deleteMs: number
  /** Nhịp gõ chữ cho title/body. */
  typingMsPerChar: number
  /** Trần thời gian gõ chữ cho MỘT node (title dài không giữ chủ nhà xem mãi). */
  typingMaxMs: number
  /** Nghỉ giữa hai op để mắt theo kịp. */
  settleMs: number
  /** Trần tổng thời lượng một lô op. */
  maxTotalMs: number
}

export const PLAYBACK_DEFAULTS: PlaybackTuning = {
  cursorSpeed: 1.4,
  moveMinMs: 90,
  createMs: 260,
  createGrowRatio: 0.45,
  connectMs: 220,
  updateMs: 200,
  deleteMs: 180,
  typingMsPerChar: 24,
  typingMaxMs: 900,
  settleMs: 120,
  maxTotalMs: 6000,
}

export interface PlaybackOptions extends Partial<PlaybackTuning> {
  /** Người dùng bật giảm chuyển động ⇒ không phát hoạt hình. */
  reducedMotion?: boolean
  /** Hệ số tốc độ chung (2 = nhanh gấp đôi). */
  speed?: number
}

export interface CursorState {
  /** Con trỏ có đang được hiển thị không (hết hoạt hình thì ẩn). */
  visible: boolean
  x: number
  y: number
  /** Đang "nhấn" trong lúc bắt đầu một op. */
  pressed: boolean
}

export type PlaybackStepKind = 'move' | 'create' | 'connect' | 'update' | 'delete' | 'settle'

/** Một bước đã lên lịch; `startMs`/`endMs` là mốc thời gian trong cả kế hoạch. */
export interface PlaybackStep {
  kind: PlaybackStepKind
  startMs: number
  endMs: number
  /** Điểm neo (world) mà con trỏ đứng ở bước này. */
  at: Point
  /** Điểm con trỏ đi TỪ (chỉ có nghĩa với `move`). */
  from?: Point
  /** Op gốc — giữ nguyên để tầng trên đối chiếu được. */
  op?: CanvasAction
  /** Node/connector liên quan (id ổn định theo op). */
  nodeId?: string
  connectorId?: string
}

export interface DrawingPlan {
  steps: PlaybackStep[]
  totalMs: number
  /** Cảnh TRƯỚC lô op (điểm xuất phát của hoạt hình). */
  from: CanvasScene
  /** Cảnh SAU lô op — đích, và là giá trị trả về khi hết thời lượng. */
  to: CanvasScene
  reducedMotion: boolean
}

export interface PlaybackFrame {
  scene: CanvasScene
  cursor: CursorState
  /** Id các node/connector đang được vẽ dở (để tầng trên tô sáng). */
  activeIds: string[]
  /** Tiến độ 0..1 của connector đang vẽ dần (id ⇒ tiến độ). */
  connectorProgress: Record<string, number>
  done: boolean
}

const HIDDEN_CURSOR: CursorState = { visible: false, x: 0, y: 0, pressed: false }

function easeInOut(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2
}

function easeOut(t: number): number {
  return 1 - Math.pow(1 - t, 3)
}

function clamp01(value: number): number {
  return value < 0 ? 0 : value > 1 ? 1 : value
}

/** Điểm "đặt bút" của một node: góc trên-trái (người vẽ bắt đầu từ đó), không phải tâm. */
function drawStart(node: CanvasNode): Point {
  return { x: node.x, y: node.y }
}

function nodeCenter(node: CanvasNode): Point {
  return { x: node.x + node.width / 2, y: node.y + node.height / 2 }
}

function nodeById(scene: CanvasScene, id: string): CanvasNode | undefined {
  return scene.nodes.find((node) => node.id === id)
}

function sameStyle(a: CanvasNode['style'], b: CanvasNode['style']): boolean {
  return a.fill === b.fill && a.stroke === b.stroke && a.strokeWidth === b.strokeWidth && a.radius === b.radius
}

function sameNode(a: CanvasNode, b: CanvasNode): boolean {
  return a.id === b.id && a.kind === b.kind && a.shape === b.shape && a.card === b.card && a.x === b.x && a.y === b.y
    && a.width === b.width && a.height === b.height && a.title === b.title && a.body === b.body && a.url === b.url
    && sameStyle(a.style, b.style)
}

function sameConnector(a: CanvasConnector, b: CanvasConnector): boolean {
  return a.id === b.id && a.fromNodeId === b.fromNodeId && a.toNodeId === b.toNodeId
    && a.fromAnchor === b.fromAnchor && a.toAnchor === b.toAnchor && a.stroke === b.stroke && a.strokeWidth === b.strokeWidth
}

function sameStroke(a: CanvasStroke, b: CanvasStroke): boolean {
  return a.id === b.id && a.color === b.color && a.width === b.width && a.points.length === b.points.length
    && a.points.every((p, index) => p.x === b.points[index].x && p.y === b.points[index].y)
}

/** So cảnh theo TỪNG trường (không so identity, không phụ thuộc thứ tự khoá của object). */
export function sameScene(a: CanvasScene, b: CanvasScene): boolean {
  return a.version === b.version && a.nodes.length === b.nodes.length
    && a.connectors.length === b.connectors.length && a.strokes.length === b.strokes.length
    && a.nodes.every((node, index) => sameNode(node, b.nodes[index]))
    && a.connectors.every((connector, index) => sameConnector(connector, b.connectors[index]))
    && a.strokes.every((stroke, index) => sameStroke(stroke, b.strokes[index]))
}

/**
 * Dựng lô op MÔ TẢ ĐÚNG chênh lệch `from → to` — dùng khi cảnh tới mà KHÔNG kèm op nào.
 *
 * Vì sao cần: cảnh canvas có hai nguồn. Sự kiện `design_canvas` mang theo `ops` (đường sống, có hoạt
 * hình). Payload chi tiết của run chỉ mang `canvasScene` đã hoàn chỉnh — tải lại trang, hoặc cảnh gieo
 * lúc duyệt touch list — nên không có op nào để phát lại. So cảnh cũ với cảnh mới rồi dựng op cho
 * phần chênh lệch giữ cả được câu chuyện "Design Lead vẽ trước mặt chủ nhà".
 *
 * KHÔNG bịa: bốn lệnh hiện có (`CREATE_NODE`/`CONNECT_NODES`/`UPDATE_NODE`/`DELETE_NODE`) không diễn tả
 * được nét nối bị sửa/thay, và không có lệnh xoá riêng cho nét nối. Gặp ca đó (hoặc nét bút chì đổi),
 * hàm trả `[]` — `planPlayback` sẽ trả kế hoạch rỗng và chủ nhà thấy thẳng cảnh thật.
 */
export function diffSceneOps(from: CanvasScene, to: CanvasScene): CanvasAction[] {
  if (from.version !== to.version) return []
  if (from.strokes.length !== to.strokes.length
      || !from.strokes.every((stroke, index) => sameStroke(stroke, to.strokes[index]))) return []
  const ops: CanvasAction[] = []
  const before = new Map(from.nodes.map((node) => [node.id, node]))
  for (const node of to.nodes) {
    const previous = before.get(node.id)
    if (!previous) ops.push({ type: 'CREATE_NODE', node })
    else if (!sameNode(previous, node)) ops.push({ type: 'UPDATE_NODE', nodeId: node.id, patch: node })
  }
  const alive = new Set(to.nodes.map((node) => node.id))
  const known = new Set(from.connectors.map((connector) => connector.id))
  const next = new Map(to.connectors.map((connector) => [connector.id, connector]))
  for (const connector of to.connectors) {
    if (!known.has(connector.id)) ops.push({ type: 'CONNECT_NODES', connector: { ...connector } })
  }
  for (const connector of from.connectors) {
    if (next.has(connector.id)) continue
    // Nét biến mất: xoá node đầu mút thì reducer tự cắt nét (cascade); còn hai đầu vẫn sống thì bốn
    // lệnh hiện có KHÔNG nói được điều đó ⇒ đành thôi, thà không có hoạt hình còn hơn vẽ sai.
    if (alive.has(connector.fromNodeId) && alive.has(connector.toNodeId)) return []
  }
  for (const node of from.nodes) if (!alive.has(node.id)) ops.push({ type: 'DELETE_NODE', nodeId: node.id })
  return ops
}

/**
 * Gán id cho op `CONNECT_NODES` khi op ấy thiếu id.
 *
 * Backend áp op lên cảnh với `setdefault('id', uuid…)` trên một BẢN SAO (`design_runtime.py:1122`)
 * nên connector trong `scene` có id còn op phát ra thì không. Thiếu bước gán này, `applyCanvasAction`
 * sẽ sinh id ngẫu nhiên và kế hoạch không bao giờ khớp cảnh thật ⇒ mọi lô op có connector đều mất
 * hoạt hình.
 */
export function alignConnectorIds(ops: CanvasAction[], from: CanvasScene, to: CanvasScene): CanvasAction[] {
  let added = from.connectors.length
  return ops.map((op) => {
    if (op.type !== 'CONNECT_NODES') return op
    const opId = op.connector.id
    const expected = to.connectors[added]?.id
    added += 1
    if (opId || !expected) return op
    return { type: 'CONNECT_NODES', connector: { ...op.connector, id: expected } }
  })
}

/**
 * Lên kế hoạch phát lại một lô op. Trả kế hoạch RỖNG (không bước, `totalMs = 0`) khi chính lô op ấy
 * không dựng nên `to` từ `from` — tầng giao diện khi đó hiện thẳng cảnh thật.
 */
export function planPlayback(input: {
  ops: CanvasAction[]
  from: CanvasScene
  to: CanvasScene
  options?: PlaybackOptions
}): DrawingPlan {
  const options = input.options ?? {}
  const tuning = { ...PLAYBACK_DEFAULTS, ...options }
  const from = input.from
  const to = input.to
  const empty: DrawingPlan = { steps: [], totalMs: 0, from, to, reducedMotion: true }

  if (input.ops.length === 0 || options.reducedMotion) return empty
  const ops = alignConnectorIds(input.ops, from, to)
  // Từng op phải được reducer CHẤP NHẬN: `applyCanvasAction` trả lại chính cảnh cũ khi op bị chối
  // (id trùng, node lạ, connector thiếu đầu). Một op bị chối mà vẫn phát hoạt hình = vẽ thứ không có.
  let rebuilt = from
  for (const op of ops) {
    const next = applyCanvasAction(rebuilt, op)
    if (next === rebuilt) return empty
    rebuilt = next
  }
  if (!sameScene(rebuilt, to)) return empty

  const speed = options.speed && options.speed > 0 ? options.speed : 1
  const ms = (value: number) => value / speed
  const steps: PlaybackStep[] = []
  let t = 0
  let cursor: Point = { x: 0, y: 0 }
  let walking = false

  const pushMove = (target: Point) => {
    const span = walking ? distance(cursor, target) : 0
    const duration = Math.max(tuning.moveMinMs, Math.round(span / tuning.cursorSpeed))
    steps.push({ kind: 'move', startMs: t, endMs: t + ms(duration), at: target, from: walking ? cursor : undefined })
    t += ms(duration)
    cursor = target
    walking = true
  }

  const pushShow = (kind: PlaybackStepKind, at: Point, durationMs: number, extra: Partial<PlaybackStep>) => {
    steps.push({ kind, startMs: t, endMs: t + ms(durationMs), at, ...extra })
    t += ms(durationMs)
    cursor = at
    walking = true
  }

  for (const op of ops) {
    if (op.type === 'CREATE_NODE') {
      const node = op.node
      const at = drawStart(node)
      // Bước tạo node dài theo LƯỢNG CHỮ phải gõ: tiêu đề dài thì vẽ lâu hơn một chút, nhưng có trần.
      const typing = Math.min(tuning.typingMaxMs, node.title.length * tuning.typingMsPerChar)
      pushMove(at)
      pushShow('create', at, tuning.createMs + typing, { op, nodeId: node.id })
    } else if (op.type === 'CONNECT_NODES') {
      const fromNode = nodeById(from, op.connector.fromNodeId)
      const toNode = nodeById(from, op.connector.toNodeId)
      const at = fromNode && toNode ? nodeCenter(fromNode) : { x: cursor.x + 40, y: cursor.y + 40 }
      pushMove(at)
      pushShow('connect', at, tuning.connectMs, { op, connectorId: op.connector.id })
    } else if (op.type === 'UPDATE_NODE') {
      const node = nodeById(from, op.nodeId)
      const at = node ? drawStart(node) : cursor
      pushMove(at)
      pushShow('update', at, tuning.updateMs, { op, nodeId: op.nodeId })
    } else {
      const node = nodeById(from, op.nodeId)
      const at = node ? drawStart(node) : cursor
      pushMove(at)
      pushShow('delete', at, tuning.deleteMs, { op, nodeId: op.nodeId })
    }
    steps.push({ kind: 'settle', startMs: t, endMs: t + ms(tuning.settleMs), at: cursor })
    t += ms(tuning.settleMs)
  }

  // Trần tổng thời lượng: co mọi bước theo CÙNG một hệ số để bản vẽ dài không giữ chủ nhà lâu.
  const raw = t
  if (raw <= tuning.maxTotalMs) return { steps, totalMs: raw, from, to, reducedMotion: false }
  const scale = raw / tuning.maxTotalMs
  return {
    steps: steps.map((step) => ({ ...step, startMs: step.startMs / scale, endMs: step.endMs / scale })),
    totalMs: raw / scale,
    from,
    to,
    reducedMotion: false,
  }
}

/** Bước VẼ (bỏ `move`/`settle` — chúng không tạo ra hình gì). */
function isDrawStep(step: PlaybackStep): boolean {
  return step.kind !== 'move' && step.kind !== 'settle'
}

/**
 * Tổng số bước VẼ của kế hoạch, để dải "canvas sống" nói được "đang vẽ N/M" mà không đếm nhầm bước
 * con trỏ đi.
 */
export function drawStepCount(plan: DrawingPlan): number {
  return plan.steps.filter(isDrawStep).length
}

/** Số bước vẽ đã xong tại thời điểm `tMs`. */
export function drawnStepCount(plan: DrawingPlan, tMs: number): number {
  return plan.steps.filter((step) => isDrawStep(step) && tMs >= step.endMs).length
}

/** Tiến độ 0..1 bên trong một bước (bước có thời lượng 0 coi như đã xong). */
function stepProgress(step: PlaybackStep, tMs: number): number {
  const span = step.endMs - step.startMs
  return span <= 0 ? 1 : clamp01((tMs - step.startMs) / span)
}

/** Điểm con trỏ dọc đường đi của một bước `move` — cung nhẹ để nét vẽ trông như tay người. */
export function cursorAt(step: PlaybackStep, tMs: number): Point {
  const from = step.from ?? step.at
  const progress = easeInOut(stepProgress(step, tMs))
  const straight = { x: from.x + (step.at.x - from.x) * progress, y: from.y + (step.at.y - from.y) * progress }
  if (step.kind !== 'move') return straight
  const d = distance(from, step.at)
  if (d === 0) return straight
  // Pháp tuyến của đoạn thẳng: cung lệch một bên, đỉnh ở giữa đường, cao nhất 48 px.
  const bulge = Math.sin(Math.PI * progress) * Math.min(48, d * 0.12)
  return {
    x: straight.x + (-(step.at.y - from.y) / d) * bulge,
    y: straight.y + ((step.at.x - from.x) / d) * bulge,
  }
}

/** Chữ hiện dần theo từng ký tự; phần chưa gõ thì bỏ hẳn (không hiện mờ). */
function typedText(text: string, progress: number): string {
  if (!text) return text
  return text.slice(0, Math.floor(text.length * clamp01(progress)))
}

/** Node đang được vẽ: khung lớn dần trong `createGrowRatio` đầu, rồi tới lượt chữ. */
function drawingNode(target: CanvasNode, progress: number, growRatio: number): CanvasNode {
  const grow = easeOut(clamp01(progress / growRatio))
  const type = clamp01((progress - growRatio) / (1 - growRatio))
  return {
    ...target,
    width: target.width * grow,
    height: target.height * grow,
    title: typedText(target.title, type),
  }
}

function shrunkNode(target: CanvasNode, progress: number): CanvasNode {
  const eased = 1 - easeOut(progress)
  return { ...target, width: target.width * eased, height: target.height * eased }
}

function lerpNode(before: CanvasNode, after: CanvasNode, progress: number): CanvasNode {
  const eased = easeOut(progress)
  return {
    ...after,
    x: before.x + (after.x - before.x) * eased,
    y: before.y + (after.y - before.y) * eased,
    width: before.width + (after.width - before.width) * eased,
    height: before.height + (after.height - before.height) * eased,
  }
}

/**
 * Cảnh + con trỏ tại thời điểm `tMs`.
 *
 * Cảnh trung gian = cảnh `from` + các op ĐÃ XONG + op đang chạy ở dạng dở (node lớn dần rồi gõ chữ,
 * connector vẽ dần, node đổi hình học/biến mất). Hết `totalMs` (hoặc kế hoạch rỗng) trả ĐÚNG `to`
 * và con trỏ ẩn.
 */
export function frameAt(plan: DrawingPlan, tMs: number): PlaybackFrame {
  const growRatio = PLAYBACK_DEFAULTS.createGrowRatio
  if (plan.steps.length === 0 || tMs >= plan.totalMs) {
    return { scene: plan.to, cursor: HIDDEN_CURSOR, activeIds: [], connectorProgress: {}, done: true }
  }
  let scene = plan.from
  const activeIds: string[] = []
  const connectorProgress: Record<string, number> = {}
  let cursor: CursorState = HIDDEN_CURSOR

  for (const step of plan.steps) {
    if (tMs >= step.endMs) {
      // Bước đã xong: áp op của nó (bước `move`/`settle` không mang op).
      if (step.op) scene = applyCanvasAction(scene, step.op)
      continue
    }
    const progress = stepProgress(step, tMs)
    if (step.kind === 'move') {
      const point = cursorAt(step, tMs)
      cursor = { visible: true, x: point.x, y: point.y, pressed: false }
    } else if (step.kind === 'settle') {
      cursor = { visible: true, x: step.at.x, y: step.at.y, pressed: false }
    } else {
      cursor = { visible: true, x: step.at.x, y: step.at.y, pressed: progress < 0.35 }
    }
    const op = step.op
    if (op?.type === 'CREATE_NODE' && step.kind === 'create') {
      scene = { ...scene, nodes: [...scene.nodes, drawingNode(op.node, progress, growRatio)] }
      activeIds.push(op.node.id)
    } else if (op?.type === 'UPDATE_NODE' && step.kind === 'update') {
      const before = nodeById(scene, op.nodeId)
      const after = nodeById(plan.to, op.nodeId)
      if (before && after) {
        scene = { ...scene, nodes: scene.nodes.map((node) => (node.id === before.id ? lerpNode(before, after, progress) : node)) }
        activeIds.push(before.id)
      }
    } else if (op?.type === 'DELETE_NODE' && step.kind === 'delete') {
      const target = nodeById(scene, op.nodeId)
      if (target) {
        scene = {
          ...scene,
          nodes: scene.nodes.map((node) => (node.id === target.id ? shrunkNode(target, progress) : node)),
          connectors: scene.connectors.filter((c) => c.fromNodeId !== target.id && c.toNodeId !== target.id),
        }
        activeIds.push(target.id)
      }
    } else if (op?.type === 'CONNECT_NODES' && step.kind === 'connect') {
      const withConnector = applyCanvasAction(scene, op)
      const drawn = withConnector.connectors[withConnector.connectors.length - 1]
      scene = withConnector
      if (drawn) {
        connectorProgress[drawn.id] = progress
        activeIds.push(drawn.id)
      }
    }
    break
  }
  return { scene, cursor, activeIds, connectorProgress, done: false }
}
