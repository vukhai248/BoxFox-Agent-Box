/**
 * Hook duy nhất điều khiển Design Canvas: một `CanvasScene` bất biến là nguồn
 * sự thật, kèm selection, view (scale/pan/origin), history (undo/redo ≤ 50) và
 * mọi hành động. Component chỉ đọc và render; hook KHÔNG đọc DOM (tọa độ do
 * `CanvasStage` chuyển bằng `getBoundingClientRect` rồi truyền vào).
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  CanvasConnector,
  CanvasNode,
  CanvasOutboundMessage,
  CanvasScene,
  CanvasStroke,
  CanvasStyle,
  CardKind,
  Point,
  ShapeKind,
} from '../lib/canvas'
import {
  buildCanvasDirective,
  buildCanvasMessage,
  DEFAULT_CARD_STYLE,
  DEFAULT_SHAPE_STYLE,
  CARD_META,
  cardTitleFallback,
  createInitialScene,
  newId,
  nearestAnchors,
  nodeById,
  PALETTE,
  screenToWorld,
  serialize,
  type CanvasView,
} from '../lib/canvas'

export type ToolMode = 'select' | 'hand' | 'pencil' | 'wireframe' | 'text' | 'arrow'

/** Giới hạn bước undo/redo (snapshot bất biến nên rẻ). */
export const MAX_HISTORY = 50

/** Kích thước mặc định khi tạo shape từ picker. */
const DEFAULT_SHAPE_SIZE = { width: 160, height: 120 }

/** Kích thước mặc định khi tạo node webview (live preview). */
const DEFAULT_WEBVIEW_SIZE = { width: 480, height: 320 }

/** Chỉ thị mặc định gửi agent khi chuột phải "bảo agent sửa component này". */
const AGENT_DIRECTIVE_TEXT = 'Sửa đúng component này theo yêu cầu của người dùng.'

/** Patch góc/độ rộng nhỏ nhất có thể resize một node (4 góc + 4 cạnh handle). */
export type NodeGeometryPatch = Partial<Pick<CanvasNode, 'x' | 'y' | 'width' | 'height'>>

interface History {
  present: CanvasScene
  past: CanvasScene[]
  future: CanvasScene[]
}

export interface DesignCanvas {
  scene: CanvasScene
  selection: ReadonlySet<string>
  activeTool: ToolMode
  view: CanvasView
  viewSize: Point
  draftStroke: CanvasStroke | null
  syncStatus: 'idle' | 'synced'
  lastSentMessage: CanvasOutboundMessage | null
  canUndo: boolean
  canRedo: boolean

  setTool(t: ToolMode): void
  setView(patch: Partial<CanvasView>): void
  setViewSize(size: Point): void

  addShape(kind: ShapeKind): void
  addCard(kind: CardKind): void
  addWebview(url: string): void
  addConnector(fromNodeId: string, toNodeId: string): void

  startStroke(worldPoint: Point): void
  extendStroke(worldPoint: Point): void
  endStroke(): void
  clearStrokes(): void
  recolorStroke(id: string, color: string): void

  select(id: string, additive?: boolean): void
  selectNone(): void
  moveSelection(delta: Point, commit?: boolean): void
  resizeNode(id: string, patch: NodeGeometryPatch, commit?: boolean): void
  finishGesture(): void
  duplicateSelection(): void
  deleteSelection(): void

  updateNodeStyle(id: string, patch: Partial<CanvasStyle>): void
  updateNodeTitle(id: string, title: string): void
  updateNodeBody(id: string, body: string): void
  updateNodeUrl(id: string, url: string): void

  sendToAgent(): string
  instructAgent(nodeId: string): void
  undo(): void
  redo(): void
}

function translateNode(node: CanvasNode, delta: Point): CanvasNode {
  return { ...node, x: node.x + delta.x, y: node.y + delta.y }
}

function translateStroke(stroke: CanvasStroke, delta: Point): CanvasStroke {
  return { ...stroke, points: stroke.points.map((p) => ({ x: p.x + delta.x, y: p.y + delta.y })) }
}

export function useDesignCanvas(): DesignCanvas {
  const [history, setHistory] = useState<History>(() => ({
    present: createInitialScene(),
    past: [],
    future: [],
  }))
  const [selection, setSelection] = useState<Set<string>>(() => new Set())
  const [activeTool, setActiveTool] = useState<ToolMode>('select')
  const [view, setViewState] = useState<CanvasView>({ scale: 1, pan: { x: 0, y: 0 }, origin: { x: 0, y: 0 } })
  const [viewSize, setViewSizeState] = useState<Point>({ x: 0, y: 0 })
  const [draftStroke, setDraftStroke] = useState<CanvasStroke | null>(null)
  const [syncStatus, setSyncStatus] = useState<'idle' | 'synced'>('idle')
  const [lastSentMessage, setLastSentMessage] = useState<CanvasOutboundMessage | null>(null)
  const syncTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Scene gốc lúc bắt đầu cử chỉ (drag/resize) — để ghi ĐÚNG MỘT bước undo ở pointer-up.
  const gestureBaseRef = useRef<CanvasScene | null>(null)

  const scene = history.present

  useEffect(() => {
    return () => {
      if (syncTimerRef.current) clearTimeout(syncTimerRef.current)
    }
  }, [])

  /** Ghi `next` mà KHÔNG tạo bước lịch sử (drag/resize đang diễn ra, gõ text). */
  const transient = useCallback((next: CanvasScene) => {
    setHistory((h) => ({ ...h, present: next }))
  }, [])

  /** Ghi `next` và đẩy scene hiện tại thành một bước undo (ranh giới thao tác). */
  const commit = useCallback((next: CanvasScene) => {
    setHistory((h) => ({ present: next, past: [...h.past, h.present].slice(-MAX_HISTORY), future: [] }))
  }, [])

  const flashSync = useCallback(() => {
    setSyncStatus('synced')
    if (syncTimerRef.current) clearTimeout(syncTimerRef.current)
    syncTimerRef.current = setTimeout(() => setSyncStatus('idle'), 3000)
  }, [])

  /** Tọa độ world ở giữa khung nhìn hiện tại (để thêm node vào chỗ nhìn thấy). */
  const centerWorld = useCallback((): Point => {
    return screenToWorld({ x: view.origin.x + viewSize.x / 2, y: view.origin.y + viewSize.y / 2 }, view)
  }, [view, viewSize])

  const setTool = useCallback((t: ToolMode) => setActiveTool(t), [])

  const setView = useCallback((patch: Partial<CanvasView>) => {
    setViewState((v) => ({ ...v, ...patch }))
  }, [])

  const setViewSize = useCallback((size: Point) => setViewSizeState(size), [])

  const addShape = useCallback(
    (kind: ShapeKind) => {
      const c = centerWorld()
      const node: CanvasNode = {
        id: newId('node'),
        kind: 'shape',
        shape: kind,
        card: null,
        x: c.x - DEFAULT_SHAPE_SIZE.width / 2,
        y: c.y - DEFAULT_SHAPE_SIZE.height / 2,
        width: DEFAULT_SHAPE_SIZE.width,
        height: DEFAULT_SHAPE_SIZE.height,
        title: '',
        body: '',
        url: null,
        style: { ...DEFAULT_SHAPE_STYLE },
      }
      commit({ ...scene, nodes: [...scene.nodes, node] })
    },
    [centerWorld, commit, scene],
  )

  const addCard = useCallback(
    (kind: CardKind) => {
      const meta = CARD_META[kind]
      const c = centerWorld()
      const node: CanvasNode = {
        id: newId('node'),
        kind: 'card',
        shape: null,
        card: kind,
        x: c.x - meta.width / 2,
        y: c.y - meta.height / 2,
        width: meta.width,
        height: meta.height,
        title: meta.title,
        body: '',
        url: null,
        style: { ...DEFAULT_CARD_STYLE },
      }
      commit({ ...scene, nodes: [...scene.nodes, node] })
    },
    [centerWorld, commit, scene],
  )

  const addWebview = useCallback(
    (url: string) => {
      const c = centerWorld()
      const node: CanvasNode = {
        id: newId('node'),
        kind: 'webview',
        shape: null,
        card: null,
        x: c.x - DEFAULT_WEBVIEW_SIZE.width / 2,
        y: c.y - DEFAULT_WEBVIEW_SIZE.height / 2,
        width: DEFAULT_WEBVIEW_SIZE.width,
        height: DEFAULT_WEBVIEW_SIZE.height,
        title: 'Live Preview',
        body: url,
        url,
        style: { ...DEFAULT_CARD_STYLE, fill: PALETTE.bg },
      }
      commit({ ...scene, nodes: [...scene.nodes, node] })
    },
    [centerWorld, commit, scene],
  )

  const addConnector = useCallback(
    (fromNodeId: string, toNodeId: string) => {
      const a = nodeById(scene, fromNodeId)
      const b = nodeById(scene, toNodeId)
      if (!a || !b || fromNodeId === toNodeId) return
      const { from, to } = nearestAnchors(a, b)
      const connector: CanvasConnector = {
        id: newId('conn'),
        fromNodeId,
        toNodeId,
        fromAnchor: from,
        toAnchor: to,
        stroke: PALETTE.brand,
        strokeWidth: 2,
      }
      commit({ ...scene, connectors: [...scene.connectors, connector] })
    },
    [commit, scene],
  )

  const startStroke = useCallback((worldPoint: Point) => {
    setDraftStroke({ id: newId('stroke'), points: [worldPoint], color: PALETTE.brand, width: 2 })
  }, [])

  const extendStroke = useCallback((worldPoint: Point) => {
    setDraftStroke((s) => (s ? { ...s, points: [...s.points, worldPoint] } : s))
  }, [])

  const endStroke = useCallback(() => {
    // Đọc `draftStroke` ngoài updater (updater React phải thuần — StrictMode gọi 2 lần)
    // rồi commit ĐÚNG MỘT lần: chỉ giữ nét có ≥ 2 điểm, không ghi mỗi mousemove.
    const stroke = draftStroke
    if (stroke && stroke.points.length >= 2) {
      commit({ ...scene, strokes: [...scene.strokes, stroke] })
    }
    setDraftStroke(null)
  }, [commit, draftStroke, scene])

  const clearStrokes = useCallback(() => {
    setDraftStroke(null)
    commit({ ...scene, strokes: [] })
  }, [commit, scene])

  const recolorStroke = useCallback(
    (id: string, color: string) => {
      transient({ ...scene, strokes: scene.strokes.map((s) => (s.id === id ? { ...s, color } : s)) })
    },
    [scene, transient],
  )

  const select = useCallback((id: string, additive = false) => {
    setSelection((prev) => {
      if (additive) {
        const next = new Set(prev)
        next.add(id)
        return next
      }
      return new Set([id])
    })
  }, [])

  const selectNone = useCallback(() => setSelection(new Set()), [])

  const moveSelection = useCallback(
    (delta: Point, doCommit = true) => {
      if (selection.size === 0) return
      // Khi kéo (commit=false): chụp scene gốc MỘT lần để finishGesture ghi undo.
      if (!doCommit && gestureBaseRef.current === null) gestureBaseRef.current = scene
      const nodes = scene.nodes.map((n) => (selection.has(n.id) ? translateNode(n, delta) : n))
      const strokes = scene.strokes.map((s) => (selection.has(s.id) ? translateStroke(s, delta) : s))
      const next: CanvasScene = { ...scene, nodes, strokes }
      if (doCommit) {
        // Thao tác độc lập: base undo là scene hiện tại, KHÔNG dùng lại base của
        // cử chỉ commit=false đang dở (tránh undo lùi về trạng thái cũ sai).
        setHistory((h) => ({ present: next, past: [...h.past, scene].slice(-MAX_HISTORY), future: [] }))
        gestureBaseRef.current = null
      } else {
        transient(next)
      }
    },
    [scene, selection, transient],
  )

  const resizeNode = useCallback(
    (id: string, patch: NodeGeometryPatch, doCommit = true) => {
      if (!doCommit && gestureBaseRef.current === null) gestureBaseRef.current = scene
      const nodes = scene.nodes.map((n) => {
        if (n.id !== id) return n
        const width = patch.width !== undefined ? Math.max(1, patch.width) : n.width
        const height = patch.height !== undefined ? Math.max(1, patch.height) : n.height
        const x = patch.x ?? n.x
        const y = patch.y ?? n.y
        return { ...n, x, y, width, height }
      })
      const next: CanvasScene = { ...scene, nodes }
      if (doCommit) {
        // Thao tác độc lập: base undo là scene hiện tại, KHÔNG dùng lại base của
        // cử chỉ commit=false đang dở (tránh undo lùi về trạng thái cũ sai).
        setHistory((h) => ({ present: next, past: [...h.past, scene].slice(-MAX_HISTORY), future: [] }))
        gestureBaseRef.current = null
      } else {
        transient(next)
      }
    },
    [scene, transient],
  )

  /** Kết thúc cử chỉ drag/resize: ghi MỘT bước undo nếu có thay đổi transient trước đó. */
  const finishGesture = useCallback(() => {
    if (gestureBaseRef.current !== null) {
      const base = gestureBaseRef.current
      gestureBaseRef.current = null
      setHistory((h) => ({ ...h, past: [...h.past, base].slice(-MAX_HISTORY), future: [] }))
    }
  }, [])

  const duplicateSelection = useCallback(() => {
    const offset = { x: 24, y: 24 }
    const newNodes: CanvasNode[] = []
    const newStrokes: CanvasStroke[] = []
    const newSel = new Set<string>()
    for (const n of scene.nodes) {
      if (selection.has(n.id)) {
        const id = newId('node')
        newNodes.push({ ...n, id, x: n.x + offset.x, y: n.y + offset.y })
        newSel.add(id)
      }
    }
    for (const s of scene.strokes) {
      if (selection.has(s.id)) {
        const id = newId('stroke')
        newStrokes.push({ ...s, id, points: s.points.map((p) => ({ x: p.x + offset.x, y: p.y + offset.y })) })
        newSel.add(id)
      }
    }
    if (newNodes.length === 0 && newStrokes.length === 0) return
    commit({ ...scene, nodes: [...scene.nodes, ...newNodes], strokes: [...scene.strokes, ...newStrokes] })
    setSelection(newSel)
  }, [commit, scene, selection])

  const deleteSelection = useCallback(() => {
    if (selection.size === 0) return
    const nodes = scene.nodes.filter((n) => !selection.has(n.id))
    const connectors = scene.connectors.filter((c) => !selection.has(c.fromNodeId) && !selection.has(c.toNodeId))
    const strokes = scene.strokes.filter((s) => !selection.has(s.id))
    commit({ ...scene, nodes, connectors, strokes })
    setSelection(new Set())
  }, [commit, scene, selection])

  const updateNodeStyle = useCallback(
    (id: string, patch: Partial<CanvasStyle>) => {
      transient({
        ...scene,
        nodes: scene.nodes.map((n) => (n.id === id ? { ...n, style: { ...n.style, ...patch } } : n)),
      })
    },
    [scene, transient],
  )

  const updateNodeTitle = useCallback(
    (id: string, title: string) => {
      transient({ ...scene, nodes: scene.nodes.map((n) => (n.id === id ? { ...n, title } : n)) })
    },
    [scene, transient],
  )

  const updateNodeBody = useCallback(
    (id: string, body: string) => {
      transient({ ...scene, nodes: scene.nodes.map((n) => (n.id === id ? { ...n, body } : n)) })
    },
    [scene, transient],
  )

  const updateNodeUrl = useCallback(
    (id: string, url: string) => {
      transient({ ...scene, nodes: scene.nodes.map((n) => (n.id === id ? { ...n, url, body: url } : n)) })
    },
    [scene, transient],
  )

  const sendToAgent = useCallback((): string => {
    const message = buildCanvasMessage(scene)
    // TODO(transport): khi backend hỗ trợ command canvas, thay mock dưới đây bằng
    //   useAgentStore.getState().sendCommand(...) — hợp đồng `boxfox.canvas.v1` đã sẵn.
    setLastSentMessage(message)
    flashSync()
    return serialize(scene)
  }, [flashSync, scene])

  const instructAgent = useCallback(
    (nodeId: string) => {
      const node = nodeById(scene, nodeId)
      if (!node) return
      const directive = buildCanvasDirective(node.id, node.title || cardTitleFallback(node.card), AGENT_DIRECTIVE_TEXT)
      // TODO(transport): điểm tích hợp transport thật sau này (xem sendToAgent).
      setLastSentMessage(directive)
      flashSync()
    },
    [flashSync, scene],
  )

  const undo = useCallback(() => {
    setHistory((h) => {
      if (h.past.length === 0) return h
      const previous = h.past[h.past.length - 1]
      return { present: previous, past: h.past.slice(0, -1), future: [h.present, ...h.future] }
    })
  }, [])

  const redo = useCallback(() => {
    setHistory((h) => {
      if (h.future.length === 0) return h
      const [next, ...restFuture] = h.future
      return { present: next, past: [...h.past, h.present], future: restFuture }
    })
  }, [])

  return {
    scene,
    selection,
    activeTool,
    view,
    viewSize,
    draftStroke,
    syncStatus,
    lastSentMessage,
    canUndo: history.past.length > 0,
    canRedo: history.future.length > 0,

    setTool,
    setView,
    setViewSize,
    addShape,
    addCard,
    addWebview,
    addConnector,
    startStroke,
    extendStroke,
    endStroke,
    clearStrokes,
    recolorStroke,
    select,
    selectNone,
    moveSelection,
    resizeNode,
    finishGesture,
    duplicateSelection,
    deleteSelection,
    updateNodeStyle,
    updateNodeTitle,
    updateNodeBody,
    updateNodeUrl,
    sendToAgent,
    instructAgent,
    undo,
    redo,
  }
}
