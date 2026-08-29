/**
 * Viewport canvas + toàn bộ xử lý con trỏ (Pointer Events + setPointerCapture).
 * Chuyển tọa độ screen↔world bằng hàm thuần `screenToWorld`; kéo/thả được
 * throttle qua `requestAnimationFrame` để giữ render mượt. Node chỉ báo pointer
 * down lên đây — Stage giữ pointer capture và tự chạy move/up toàn cục.
 */
import type { MouseEvent as ReactMouseEvent, PointerEvent as ReactPointerEvent } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'
import type { DesignCanvas, NodeGeometryPatch } from '../../../hooks/useDesignCanvas'
import type { CanvasView, Point } from '../../../lib/canvas'
import { anchorPoint, distanceToSegment, screenToWorld } from '../../../lib/canvas'
import { CardNode } from './CardNode'
import { ConnectorLayer } from './ConnectorLayer'
import { ContextMenu } from './ContextMenu'
import { SelectionOverlay, type ResizeHandle } from './SelectionOverlay'
import { ShapeNode } from './ShapeNode'
import { StrokeLayer } from './StrokeLayer'
import { StylePalette } from './StylePalette'
import { WebviewNode } from './WebviewNode'

type DragMode = 'pan' | 'node' | 'resize' | 'stroke' | 'connector'

interface PointerState {
  mode: DragMode
  pointerId: number
  startClient: Point
  startWorld: Point
  lastWorld: Point
  moved: boolean
  startPan?: Point
  fromNodeId?: string
  nodeId?: string
  handle?: ResizeHandle
  base?: { x: number; y: number; width: number; height: number }
}

function resizePatch(handle: ResizeHandle, b: NonNullable<PointerState['base']>, dx: number, dy: number): NodeGeometryPatch {
  switch (handle) {
    case 'nw':
      return { x: b.x + dx, y: b.y + dy, width: b.width - dx, height: b.height - dy }
    case 'n':
      return { y: b.y + dy, height: b.height - dy }
    case 'ne':
      return { y: b.y + dy, width: b.width + dx, height: b.height - dy }
    case 'e':
      return { width: b.width + dx }
    case 'se':
      return { width: b.width + dx, height: b.height + dy }
    case 's':
      return { height: b.height + dy }
    case 'sw':
      return { x: b.x + dx, width: b.width - dx, height: b.height + dy }
    case 'w':
      return { x: b.x + dx, width: b.width - dx }
  }
}

export function CanvasStage({ canvas }: { canvas: DesignCanvas }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const canvasRef = useRef(canvas)
  canvasRef.current = canvas

  const [spacePressed, setSpacePressed] = useState(false)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; nodeId: string } | null>(null)
  const [connectorPreview, setConnectorPreview] = useState<{ from: Point; to: Point } | null>(null)

  const pointerRef = useRef<PointerState | null>(null)
  const rafRef = useRef(0)
  const moveCoordsRef = useRef<Point | null>(null)

  const { scene, selection, activeTool, view, draftStroke } = canvas

  const clientView = useCallback((): CanvasView => {
    const rect = containerRef.current?.getBoundingClientRect()
    return {
      scale: view.scale,
      pan: view.pan,
      origin: rect ? { x: rect.left, y: rect.top } : view.origin,
    }
  }, [view])

  const toWorld = useCallback(
    (clientX: number, clientY: number): Point => screenToWorld({ x: clientX, y: clientY }, clientView()),
    [clientView],
  )

  // Đo viewport → hook dùng cho thêm node vào tâm view hiện tại.
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const measure = () => {
      const rect = el.getBoundingClientRect()
      canvas.setView({ origin: { x: rect.left, y: rect.top } })
      canvas.setViewSize({ x: rect.width, y: rect.height })
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    ro?.observe(el)
    window.addEventListener('resize', measure)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [canvas.setView, canvas.setViewSize])

  // Phím tắt + Spacebar pan (không chặn khi đang gõ trong input/textarea).
  useEffect(() => {
    function isEditable(t: EventTarget | null): boolean {
      if (t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement) return true
      return t instanceof HTMLElement && t.isContentEditable
    }
    function onKeyDown(e: KeyboardEvent) {
      const c = canvasRef.current
      const editable = isEditable(e.target)
      if (e.code === 'Space' && !editable) {
        e.preventDefault()
        setSpacePressed(true)
        return
      }
      if (editable) return
      const mod = e.metaKey || e.ctrlKey
      const key = e.key.toLowerCase()
      if (mod && key === 'z') {
        e.preventDefault()
        if (e.shiftKey) c.redo()
        else c.undo()
        return
      }
      if (mod && key === 'y') {
        e.preventDefault()
        c.redo()
        return
      }
      if (mod && key === 'd') {
        e.preventDefault()
        c.duplicateSelection()
        return
      }
      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault()
        c.deleteSelection()
        return
      }
      if (e.key === 'Escape') {
        c.selectNone()
        setContextMenu(null)
        return
      }
      if (mod) return
      switch (key) {
        case 'v':
          c.setTool('select')
          break
        case 'h':
          c.setTool('hand')
          break
        case 'p':
          c.setTool('pencil')
          break
        case 'r':
          c.addShape('rect')
          break
        case 'a':
          c.setTool('arrow')
          break
        case 't':
          c.addCard('directive-annotation')
          break
      }
    }
    function onKeyUp(e: KeyboardEvent) {
      if (e.code === 'Space') setSpacePressed(false)
    }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [])

  const nodeAt = useCallback(
    (world: Point): string | undefined => {
      for (let i = scene.nodes.length - 1; i >= 0; i--) {
        const n = scene.nodes[i]
        if (world.x >= n.x && world.x <= n.x + n.width && world.y >= n.y && world.y <= n.y + n.height) return n.id
      }
      return undefined
    },
    [scene],
  )

  const hitStroke = useCallback(
    (world: Point): string | undefined => {
      const tol = 8 / Math.max(view.scale, 0.1)
      for (let i = scene.strokes.length - 1; i >= 0; i--) {
        const s = scene.strokes[i]
        for (let j = 0; j < s.points.length - 1; j++) {
          if (distanceToSegment(world, s.points[j], s.points[j + 1]) <= tol) return s.id
        }
      }
      return undefined
    },
    [scene.strokes, view.scale],
  )

  function beginPan(e: ReactPointerEvent) {
    pointerRef.current = {
      mode: 'pan',
      pointerId: e.pointerId,
      startClient: { x: e.clientX, y: e.clientY },
      startWorld: toWorld(e.clientX, e.clientY),
      lastWorld: toWorld(e.clientX, e.clientY),
      moved: false,
      startPan: canvas.view.pan,
    }
    containerRef.current?.setPointerCapture(e.pointerId)
  }

  function beginStroke(e: ReactPointerEvent) {
    const world = toWorld(e.clientX, e.clientY)
    canvas.selectNone()
    canvas.startStroke(world)
    pointerRef.current = {
      mode: 'stroke',
      pointerId: e.pointerId,
      startClient: { x: e.clientX, y: e.clientY },
      startWorld: world,
      lastWorld: world,
      moved: false,
    }
    containerRef.current?.setPointerCapture(e.pointerId)
  }

  function beginConnector(e: ReactPointerEvent, nodeId: string) {
    const world = toWorld(e.clientX, e.clientY)
    pointerRef.current = {
      mode: 'connector',
      pointerId: e.pointerId,
      startClient: { x: e.clientX, y: e.clientY },
      startWorld: world,
      lastWorld: world,
      moved: false,
      fromNodeId: nodeId,
    }
    containerRef.current?.setPointerCapture(e.pointerId)
  }

  function beginNodeDrag(e: ReactPointerEvent, world: Point) {
    pointerRef.current = {
      mode: 'node',
      pointerId: e.pointerId,
      startClient: { x: e.clientX, y: e.clientY },
      startWorld: world,
      lastWorld: world,
      moved: false,
    }
    containerRef.current?.setPointerCapture(e.pointerId)
  }

  function onBackgroundPointerDown(e: ReactPointerEvent) {
    if (e.button === 1 || spacePressed || activeTool === 'hand') {
      beginPan(e)
      return
    }
    if (activeTool === 'pencil' && e.button === 0) {
      beginStroke(e)
      return
    }
    if (activeTool === 'select' && e.button === 0) {
      const world = toWorld(e.clientX, e.clientY)
      const strokeId = hitStroke(world)
      if (strokeId) {
        canvas.select(strokeId, e.shiftKey)
        beginNodeDrag(e, world)
        return
      }
      canvas.selectNone()
      setContextMenu(null)
      return
    }
    if (activeTool === 'arrow' && e.button === 0) {
      canvas.selectNone()
      setContextMenu(null)
    }
  }

  function onNodePointerDown(e: ReactPointerEvent, nodeId: string) {
    if (e.button === 1 || spacePressed || activeTool === 'hand') return
    if (activeTool === 'pencil' && e.button === 0) {
      e.stopPropagation()
      beginStroke(e)
      return
    }
    if (activeTool === 'arrow' && e.button === 0) {
      e.stopPropagation()
      beginConnector(e, nodeId)
      return
    }
    if (activeTool === 'select' && e.button === 0) {
      e.stopPropagation()
      if (!canvas.selection.has(nodeId)) canvas.select(nodeId, e.shiftKey)
      beginNodeDrag(e, toWorld(e.clientX, e.clientY))
    }
  }

  function onHandlePointerDown(e: ReactPointerEvent, nodeId: string, handle: ResizeHandle) {
    e.stopPropagation()
    e.preventDefault()
    const node = canvas.scene.nodes.find((n) => n.id === nodeId)
    if (!node) return
    pointerRef.current = {
      mode: 'resize',
      pointerId: e.pointerId,
      startClient: { x: e.clientX, y: e.clientY },
      startWorld: toWorld(e.clientX, e.clientY),
      lastWorld: toWorld(e.clientX, e.clientY),
      moved: false,
      nodeId,
      handle,
      base: { x: node.x, y: node.y, width: node.width, height: node.height },
    }
    containerRef.current?.setPointerCapture(e.pointerId)
  }

  function handleDrag(cur: PointerState, clientX: number, clientY: number) {
    const world = toWorld(clientX, clientY)
    switch (cur.mode) {
      case 'pan': {
        const dx = clientX - cur.startClient.x
        const dy = clientY - cur.startClient.y
        canvas.setView({ pan: { x: (cur.startPan?.x ?? 0) + dx, y: (cur.startPan?.y ?? 0) + dy } })
        break
      }
      case 'node': {
        const dx = world.x - cur.lastWorld.x
        const dy = world.y - cur.lastWorld.y
        if (Math.abs(dx) + Math.abs(dy) > 0.001) cur.moved = true
        canvas.moveSelection({ x: dx, y: dy }, false)
        cur.lastWorld = world
        break
      }
      case 'resize': {
        canvas.resizeNode(cur.nodeId!, resizePatch(cur.handle!, cur.base!, world.x - cur.startWorld.x, world.y - cur.startWorld.y), false)
        cur.moved = true
        break
      }
      case 'stroke': {
        canvas.extendStroke(world)
        break
      }
      case 'connector': {
        const fromNode = canvas.scene.nodes.find((n) => n.id === cur.fromNodeId)
        setConnectorPreview(fromNode ? { from: anchorPoint(fromNode, 'center'), to: world } : null)
        break
      }
    }
  }

  function onPointerMove(e: ReactPointerEvent) {
    const cur = pointerRef.current
    if (!cur || e.pointerId !== cur.pointerId) return
    moveCoordsRef.current = { x: e.clientX, y: e.clientY }
    if (rafRef.current) return
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0
      const active = pointerRef.current
      const coords = moveCoordsRef.current
      if (active && coords) handleDrag(active, coords.x, coords.y)
    })
  }

  function finishPointer(e: ReactPointerEvent) {
    const cur = pointerRef.current
    if (!cur || e.pointerId !== cur.pointerId) return
    switch (cur.mode) {
      case 'node':
        if (cur.moved) canvas.finishGesture()
        break
      case 'resize':
        if (cur.moved) canvas.finishGesture()
        break
      case 'stroke':
        canvas.endStroke()
        break
      case 'connector': {
        const world = toWorld(e.clientX, e.clientY)
        const target = nodeAt(world)
        if (target && target !== cur.fromNodeId) canvas.addConnector(cur.fromNodeId!, target)
        canvas.setTool('select')
        setConnectorPreview(null)
        break
      }
      case 'pan':
        break
    }
    pointerRef.current = null
    moveCoordsRef.current = null
  }

  function onNodeContextMenu(e: ReactMouseEvent, nodeId: string) {
    e.preventDefault()
    e.stopPropagation()
    canvas.select(nodeId)
    setContextMenu({ x: e.clientX, y: e.clientY, nodeId })
  }

  const isHandMode = spacePressed || activeTool === 'hand'
  const cursorClass = isHandMode
    ? 'cursor-grab'
    : activeTool === 'pencil' || activeTool === 'arrow'
      ? 'cursor-crosshair'
      : 'cursor-default'

  const selectedShape = scene.nodes.find((n) => n.kind === 'shape' && selection.has(n.id))
  const contextNode = contextMenu ? scene.nodes.find((n) => n.id === contextMenu.nodeId) : null

  return (
    <div className="relative flex-1 overflow-hidden">
      <div
        ref={containerRef}
        onPointerDown={onBackgroundPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={finishPointer}
        onPointerCancel={finishPointer}
        onContextMenu={(e) => e.preventDefault()}
        className={`canvas-grid-bg relative h-full w-full overflow-hidden bg-bg bg-[radial-gradient(#27272a_1.2px,transparent_1.2px)] [background-size:20px_20px] ${cursorClass}`}
      >
        <div
          className="absolute inset-0 origin-top-left"
          style={{ transform: `translate(${view.pan.x}px, ${view.pan.y}px) scale(${view.scale})` }}
        >
          <ConnectorLayer nodes={scene.nodes} connectors={scene.connectors} preview={connectorPreview} />
          <StrokeLayer strokes={scene.strokes} draftStroke={draftStroke} selection={selection} />
          {scene.nodes.map((node) => {
            if (node.kind === 'shape') {
              return (
                <ShapeNode
                  key={node.id}
                  node={node}
                  selected={selection.has(node.id)}
                  onPointerDown={onNodePointerDown}
                  onContextMenu={onNodeContextMenu}
                />
              )
            }
            if (node.kind === 'webview') {
              return (
                <WebviewNode
                  key={node.id}
                  node={node}
                  selected={selection.has(node.id)}
                  onPointerDown={onNodePointerDown}
                  onContextMenu={onNodeContextMenu}
                  onUpdateUrl={canvas.updateNodeUrl}
                />
              )
            }
            return (
              <CardNode
                key={node.id}
                node={node}
                selected={selection.has(node.id)}
                onPointerDown={onNodePointerDown}
                onContextMenu={onNodeContextMenu}
                onUpdateTitle={canvas.updateNodeTitle}
                onUpdateBody={canvas.updateNodeBody}
              />
            )
          })}
          <SelectionOverlay nodes={scene.nodes} selection={selection} scale={view.scale} onHandlePointerDown={onHandlePointerDown} />
        </div>
      </div>

      {selectedShape && <StylePalette node={selectedShape} onUpdateStyle={canvas.updateNodeStyle} />}

      {contextMenu && contextNode && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          nodeTitle={contextNode.title || contextNode.body.split('\n')[0]}
          onInstruct={() => canvas.instructAgent(contextMenu.nodeId)}
          onDuplicate={() => canvas.duplicateSelection()}
          onDelete={() => canvas.deleteSelection()}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  )
}
