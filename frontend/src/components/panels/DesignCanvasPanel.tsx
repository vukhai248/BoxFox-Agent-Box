/**
 * Interactive Design Canvas & Visual Flow Studio (DesignCanvasPanel).
 * - Cho phép người dùng trực quan hóa giao diện (UI Wireframe / Mockup),
 *   vẽ luồng hoạt động (Flow Diagram), và ghi chú trực tiếp lên canvas để Agent thao tác.
 * - Hỗ trợ:
 *     + Bút chì (Pencil Tool) vẽ nét tự do (freehand sketching).
 *     + Giữ phím Cách (Spacebar) + Kéo chuột để Pan (di chuyển) không gian canvas vô tận.
 *     + Kéo thả di chuyển vị trí các khối Component (Draggable Cards).
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Shapes,
  MousePointer,
  Hand,
  Pencil,
  Square,
  Type,
  MoveRight,
  ZoomIn,
  ZoomOut,
  RotateCcw,
  Sparkles,
  Layers,
  CheckCircle2,
  Sliders,
  Eye,
  Trash2,
  GripHorizontal,
} from 'lucide-react'

type ToolMode = 'select' | 'hand' | 'pencil' | 'wireframe' | 'text' | 'arrow'

interface Point {
  x: number
  y: number
}

interface DrawingLine {
  id: string
  points: Point[]
  color: string
}

export function DesignCanvasPanel() {
  const [activeTool, setActiveTool] = useState<ToolMode>('select')
  const [zoomLevel, setZoomLevel] = useState(100)
  const [syncStatus, setSyncStatus] = useState<'idle' | 'synced'>('idle')
  const [selectedElement, setSelectedElement] = useState<string | null>('card-1')

  // Tọa độ Pan của không gian Canvas
  const [panOffset, setPanOffset] = useState<Point>({ x: 0, y: 0 })
  const [isSpacePressed, setIsSpacePressed] = useState(false)
  const [isPanning, setIsPanning] = useState(false)
  const panStartRef = useRef<{ mouseX: number; mouseY: number; startPanX: number; startPanY: number } | null>(null)

  // Vị trí kéo thả của các Component Cards
  const [cardPositions, setCardPositions] = useState({
    card1: { x: 40, y: 40 },
    card2: { x: 480, y: 40 },
    card3: { x: 40, y: 340 },
  })
  const [draggingCard, setDraggingCard] = useState<'card1' | 'card2' | 'card3' | null>(null)
  const dragStartRef = useRef<{ mouseX: number; mouseY: number; elemX: number; elemY: number } | null>(null)

  // Nét vẽ tự do của công cụ Bút chì (Pencil Tool)
  const [drawingLines, setDrawingLines] = useState<DrawingLine[]>([])
  const [currentLine, setCurrentLine] = useState<Point[] | null>(null)

  // Trường chỉnh sửa trực tiếp trên canvas
  const [componentTitle, setComponentTitle] = useState('Agent Box — Smart AI Workspace')
  const [buttonLabel, setButtonLabel] = useState('Explore Plans')

  const containerRef = useRef<HTMLDivElement>(null)

  // Nhận diện giữ phím Spacebar để kích hoạt chế độ Hand Pan
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (
        e.code === 'Space' &&
        !isSpacePressed &&
        !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)
      ) {
        e.preventDefault()
        setIsSpacePressed(true)
      }
    }

    function handleKeyUp(e: KeyboardEvent) {
      if (e.code === 'Space') {
        setIsSpacePressed(false)
        setIsPanning(false)
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
    }
  }, [isSpacePressed])

  // Xử lý chuyển đổi tọa độ chuột từ Màn hình sang Canvas (tính theo Zoom và Pan)
  const getCanvasPoint = useCallback(
    (clientX: number, clientY: number): Point => {
      if (!containerRef.current) return { x: 0, y: 0 }
      const rect = containerRef.current.getBoundingClientRect()
      const scale = zoomLevel / 100
      return {
        x: (clientX - rect.left - panOffset.x) / scale,
        y: (clientY - rect.top - panOffset.y) / scale,
      }
    },
    [zoomLevel, panOffset],
  )

  // Xử lý Mouse Down trên Canvas Background
  const handleCanvasMouseDown = (e: React.MouseEvent) => {
    // 1. Chế độ Pan khi giữ Spacebar hoặc chọn công cụ Hand
    if (isSpacePressed || activeTool === 'hand' || e.button === 1) {
      setIsPanning(true)
      panStartRef.current = {
        mouseX: e.clientX,
        mouseY: e.clientY,
        startPanX: panOffset.x,
        startPanY: panOffset.y,
      }
      return
    }

    // 2. Chế độ vẽ Bút chì (Pencil Tool)
    if (activeTool === 'pencil' && e.button === 0) {
      const pt = getCanvasPoint(e.clientX, e.clientY)
      setCurrentLine([pt])
      return
    }

    // 3. Bỏ chọn card nếu click vào nền trống
    if (e.target === containerRef.current || (e.target as HTMLElement).classList.contains('canvas-grid-bg')) {
      setSelectedElement(null)
    }
  }

  // Xử lý Mouse Move toàn canvas
  const handleMouseMove = (e: React.MouseEvent) => {
    // 1. Đang kéo Pan canvas
    if (isPanning && panStartRef.current) {
      const dx = e.clientX - panStartRef.current.mouseX
      const dy = e.clientY - panStartRef.current.mouseY
      setPanOffset({
        x: panStartRef.current.startPanX + dx,
        y: panStartRef.current.startPanY + dy,
      })
      return
    }

    // 2. Đang kéo di chuyển Component Card
    if (draggingCard && dragStartRef.current) {
      const scale = zoomLevel / 100
      const dx = (e.clientX - dragStartRef.current.mouseX) / scale
      const dy = (e.clientY - dragStartRef.current.mouseY) / scale
      setCardPositions((prev) => ({
        ...prev,
        [draggingCard]: {
          x: Math.round(dragStartRef.current!.elemX + dx),
          y: Math.round(dragStartRef.current!.elemY + dy),
        },
      }))
      return
    }

    // 3. Đang vẽ nét Bút chì
    if (currentLine && activeTool === 'pencil') {
      const pt = getCanvasPoint(e.clientX, e.clientY)
      setCurrentLine((prev) => (prev ? [...prev, pt] : [pt]))
    }
  }

  // Xử lý Mouse Up kết thúc thao tác
  const handleMouseUp = () => {
    if (isPanning) {
      setIsPanning(false)
      panStartRef.current = null
    }

    if (draggingCard) {
      setDraggingCard(null)
      dragStartRef.current = null
    }

    if (currentLine) {
      if (currentLine.length > 1) {
        setDrawingLines((prev) => [
          ...prev,
          {
            id: `line-${Date.now()}`,
            points: currentLine,
            color: '#38bdf8',
          },
        ])
      }
      setCurrentLine(null)
    }
  }

  // Bắt đầu kéo một thẻ Component Card
  const startDragCard = (e: React.MouseEvent, cardKey: 'card1' | 'card2' | 'card3') => {
    if (isSpacePressed || activeTool === 'hand' || activeTool === 'pencil') return
    e.stopPropagation()
    setSelectedElement(cardKey)
    setDraggingCard(cardKey)
    dragStartRef.current = {
      mouseX: e.clientX,
      mouseY: e.clientY,
      elemX: cardPositions[cardKey].x,
      elemY: cardPositions[cardKey].y,
    }
  }

  // Xóa toàn bộ nét vẽ bút chì
  const clearDrawings = () => {
    setDrawingLines([])
    setCurrentLine(null)
  }

  const handleSyncToAgent = () => {
    setSyncStatus('synced')
    setTimeout(() => setSyncStatus('idle'), 3000)
  }

  const renderSvgPath = (points: Point[]) => {
    if (!points.length) return ''
    return points.reduce((acc, pt, index) => {
      return index === 0 ? `M ${pt.x} ${pt.y}` : `${acc} L ${pt.x} ${pt.y}`
    }, '')
  }

  const isHandMode = isSpacePressed || activeTool === 'hand'

  return (
    <div className="flex h-full w-full flex-col bg-bg text-fg select-none overflow-hidden font-sans">
      {/* Top Canvas Toolbar */}
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-line bg-panel px-3.5">
        {/* Left: Studio Title & Tool Selectors */}
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1.5 pr-2.5 border-r border-line">
            <Shapes className="size-4 text-brand" />
            <span className="text-xs font-semibold text-fg">Design Canvas</span>
          </div>

          <div className="flex items-center gap-1 bg-panel2/60 p-0.5 rounded-lg border border-line">
            <button
              type="button"
              onClick={() => setActiveTool('select')}
              className={`flex size-7 items-center justify-center rounded-md text-xs transition cursor-pointer ${
                activeTool === 'select' && !isSpacePressed
                  ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
                  : 'text-muted hover:text-fg hover:bg-panel'
              }`}
              title="Select / Move Tool (V)"
            >
              <MousePointer className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setActiveTool('hand')}
              className={`flex size-7 items-center justify-center rounded-md text-xs transition cursor-pointer ${
                activeTool === 'hand' || isSpacePressed
                  ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
                  : 'text-muted hover:text-fg hover:bg-panel'
              }`}
              title="Hand Tool / Pan Canvas (H or Hold Space)"
            >
              <Hand className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setActiveTool('pencil')}
              className={`flex size-7 items-center justify-center rounded-md text-xs transition cursor-pointer ${
                activeTool === 'pencil'
                  ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
                  : 'text-muted hover:text-fg hover:bg-panel'
              }`}
              title="Pencil / Draw Annotation (P)"
            >
              <Pencil className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setActiveTool('wireframe')}
              className={`flex size-7 items-center justify-center rounded-md text-xs transition cursor-pointer ${
                activeTool === 'wireframe'
                  ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
                  : 'text-muted hover:text-fg hover:bg-panel'
              }`}
              title="Add UI Wireframe Block (R)"
            >
              <Square className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setActiveTool('text')}
              className={`flex size-7 items-center justify-center rounded-md text-xs transition cursor-pointer ${
                activeTool === 'text'
                  ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
                  : 'text-muted hover:text-fg hover:bg-panel'
              }`}
              title="Add Text / Label (T)"
            >
              <Type className="size-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setActiveTool('arrow')}
              className={`flex size-7 items-center justify-center rounded-md text-xs transition cursor-pointer ${
                activeTool === 'arrow'
                  ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
                  : 'text-muted hover:text-fg hover:bg-panel'
              }`}
              title="Flow Connector / Arrow (A)"
            >
              <MoveRight className="size-3.5" />
            </button>
          </div>

          {drawingLines.length > 0 && (
            <button
              type="button"
              onClick={clearDrawings}
              className="flex items-center gap-1 text-[11px] text-muted hover:text-rose-400 px-2 py-1 rounded bg-panel2/40 border border-line transition cursor-pointer ml-1"
              title="Clear all drawings"
            >
              <Trash2 className="size-3" />
              <span>Clear Sketch</span>
            </button>
          )}
        </div>

        {/* Center/Right: Zoom Controls & Sync Button */}
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1 bg-panel2/60 px-2 py-0.5 rounded-lg border border-line text-[11px] text-muted">
            <button
              type="button"
              onClick={() => setZoomLevel((z) => Math.max(50, z - 10))}
              className="p-1 hover:text-fg transition cursor-pointer"
              title="Zoom out"
            >
              <ZoomOut className="size-3" />
            </button>
            <span className="font-mono text-[11px] w-8 text-center">{zoomLevel}%</span>
            <button
              type="button"
              onClick={() => setZoomLevel((z) => Math.min(150, z + 10))}
              className="p-1 hover:text-fg transition cursor-pointer"
              title="Zoom in"
            >
              <ZoomIn className="size-3" />
            </button>
            <button
              type="button"
              onClick={() => {
                setZoomLevel(100)
                setPanOffset({ x: 0, y: 0 })
              }}
              className="p-1 hover:text-fg transition cursor-pointer ml-0.5"
              title="Reset zoom & pan"
            >
              <RotateCcw className="size-2.5" />
            </button>
          </div>

          <button
            type="button"
            onClick={handleSyncToAgent}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-semibold transition cursor-pointer shadow-xs ${
              syncStatus === 'synced'
                ? 'bg-emerald-600 text-white border border-emerald-500'
                : 'bg-brand text-white hover:bg-brand/90 border border-brand/60'
            }`}
          >
            {syncStatus === 'synced' ? (
              <>
                <CheckCircle2 className="size-3.5 text-white" />
                <span>Synced to Agent!</span>
              </>
            ) : (
              <>
                <Sparkles className="size-3.5 text-white animate-pulse" />
                <span>Send to Agent</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Main Canvas Area with Spacebar Pan, Pencil Drawing & Draggable Cards */}
      <div
        ref={containerRef}
        onMouseDown={handleCanvasMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        className={`canvas-grid-bg relative flex-1 overflow-hidden bg-bg bg-[radial-gradient(#27272a_1.2px,transparent_1.2px)] [background-size:20px_20px] ${
          isHandMode
            ? isPanning
              ? 'cursor-grabbing'
              : 'cursor-grab'
            : activeTool === 'pencil'
              ? 'cursor-crosshair'
              : 'cursor-default'
        }`}
      >
        {/* Canvas World Container transformed by Pan (x, y) and Zoom */}
        <div
          className="absolute inset-0 origin-top-left pointer-events-none"
          style={{
            transform: `translate(${panOffset.x}px, ${panOffset.y}px) scale(${zoomLevel / 100})`,
          }}
        >
          {/* SVG Layer for Freehand Pencil Drawings */}
          <svg className="absolute inset-0 w-[5000px] h-[5000px] pointer-events-none z-10">
            {drawingLines.map((line) => (
              <path
                key={line.id}
                d={renderSvgPath(line.points)}
                stroke={line.color}
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
                opacity="0.9"
              />
            ))}
            {currentLine && (
              <path
                d={renderSvgPath(currentLine)}
                stroke="#38bdf8"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
                fill="none"
                opacity="0.9"
              />
            )}
          </svg>

          {/* Card 1: UI Wireframe / Component Mockup (Draggable) */}
          <div
            style={{
              transform: `translate(${cardPositions.card1.x}px, ${cardPositions.card1.y}px)`,
            }}
            className={`pointer-events-auto absolute left-0 top-0 w-[380px] rounded-xl border bg-panel/95 backdrop-blur-md shadow-2xl transition-shadow z-20 ${
              selectedElement === 'card1'
                ? 'border-brand ring-2 ring-brand/30 shadow-brand/10'
                : 'border-line hover:border-zinc-500'
            }`}
          >
            {/* Card Drag Header */}
            <div
              onMouseDown={(e) => startDragCard(e, 'card1')}
              className="flex items-center justify-between border-b border-line/60 px-3.5 py-2 cursor-move hover:bg-panel2/50 rounded-t-xl"
            >
              <div className="flex items-center gap-1.5 text-xs font-medium text-fg">
                <GripHorizontal className="size-3 text-muted" />
                <Layers className="size-3.5 text-brand" />
                <span>Frontend UI Mockup</span>
              </div>
              <span className="rounded bg-brand/15 px-1.5 py-0.5 text-[9px] font-bold text-brand uppercase">
                Interactive
              </span>
            </div>

            <div className="p-3.5 space-y-3">
              <div>
                <label className="text-[10px] font-medium text-muted uppercase tracking-wider block mb-1">
                  Title (Direct Edit)
                </label>
                <input
                  type="text"
                  value={componentTitle}
                  onChange={(e) => setComponentTitle(e.target.value)}
                  className="w-full rounded-md border border-line bg-panel2 px-2.5 py-1 text-xs text-fg focus:border-brand focus:outline-none"
                />
              </div>

              <div className="rounded-lg border border-line bg-panel2/40 p-3">
                <div className="text-xs font-semibold text-fg mb-1">{componentTitle}</div>
                <p className="text-[11px] text-muted leading-relaxed mb-3">
                  Self-hosted AI computer environment with unified sandbox, live browser frame & VS Code integration.
                </p>
                <button
                  type="button"
                  onClick={() => setButtonLabel(buttonLabel === 'Explore Plans' ? 'Get Started' : 'Explore Plans')}
                  className="rounded-md bg-brand/20 border border-brand/40 px-2.5 py-1 text-[11px] font-medium text-brand hover:bg-brand/30 transition cursor-pointer"
                >
                  {buttonLabel}
                </button>
              </div>
            </div>
          </div>

          {/* Flow Connector Arrow connecting Card 1 to Card 2 */}
          <div
            style={{
              left: `${cardPositions.card1.x + 380}px`,
              top: `${cardPositions.card1.y + 110}px`,
              width: `${Math.max(20, cardPositions.card2.x - (cardPositions.card1.x + 380))}px`,
            }}
            className="absolute flex items-center pointer-events-none z-10"
          >
            <div className="flex-1 h-[2px] bg-brand/60" />
            <MoveRight className="size-4 text-brand -ml-2 shrink-0" />
          </div>

          {/* Card 2: Visual Agent Execution Flow (Draggable) */}
          <div
            style={{
              transform: `translate(${cardPositions.card2.x}px, ${cardPositions.card2.y}px)`,
            }}
            className={`pointer-events-auto absolute left-0 top-0 w-[340px] rounded-xl border bg-panel/95 backdrop-blur-md shadow-2xl transition-shadow z-20 ${
              selectedElement === 'card2'
                ? 'border-brand ring-2 ring-brand/30 shadow-brand/10'
                : 'border-line hover:border-zinc-500'
            }`}
          >
            {/* Card Drag Header */}
            <div
              onMouseDown={(e) => startDragCard(e, 'card2')}
              className="flex items-center justify-between border-b border-line/60 px-3.5 py-2 cursor-move hover:bg-panel2/50 rounded-t-xl"
            >
              <div className="flex items-center gap-1.5 text-xs font-medium text-fg">
                <GripHorizontal className="size-3 text-muted" />
                <Sliders className="size-3.5 text-amber-400" />
                <span>Agent Reasoning Flow</span>
              </div>
              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-bold text-amber-300 uppercase">
                Workflow
              </span>
            </div>

            <div className="p-3.5 space-y-2">
              <div className="flex items-center gap-2 rounded-lg border border-line bg-panel2/50 p-2 text-xs">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-brand/20 text-[10px] font-bold text-brand">
                  1
                </span>
                <span className="text-fg font-medium">User Visual Prompt</span>
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-line bg-panel2/50 p-2 text-xs">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-amber-500/20 text-[10px] font-bold text-amber-300">
                  2
                </span>
                <span className="text-fg font-medium">ReAct Plan Generator</span>
              </div>
              <div className="flex items-center gap-2 rounded-lg border border-line bg-panel2/50 p-2 text-xs">
                <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/20 text-[10px] font-bold text-emerald-300">
                  3
                </span>
                <span className="text-fg font-medium">Sandbox Tool Execution</span>
              </div>
            </div>
          </div>

          {/* Card 3: User Annotation Note (Draggable) */}
          <div
            style={{
              transform: `translate(${cardPositions.card3.x}px, ${cardPositions.card3.y}px)`,
            }}
            className={`pointer-events-auto absolute left-0 top-0 w-[500px] rounded-xl border bg-amber-500/10 border-amber-500/30 p-3.5 shadow-xl transition-shadow z-20 ${
              selectedElement === 'card3' ? 'ring-2 ring-amber-400/40' : ''
            }`}
          >
            {/* Card Drag Header */}
            <div
              onMouseDown={(e) => startDragCard(e, 'card3')}
              className="flex items-center justify-between pb-1.5 mb-1.5 cursor-move border-b border-amber-500/20"
            >
              <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-300">
                <GripHorizontal className="size-3 text-amber-400/60" />
                <Eye className="size-3.5" />
                <span>Annotation & Directive for Agent</span>
              </div>
              <span className="text-[10px] text-amber-400/70 font-mono">Draggable</span>
            </div>
            <p className="text-xs text-amber-200/90 leading-relaxed font-mono">
              💡 &quot;Agent: When user edits canvas wireframe above, automatically convert UI changes into React components and render live in sandbox.&quot;
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
