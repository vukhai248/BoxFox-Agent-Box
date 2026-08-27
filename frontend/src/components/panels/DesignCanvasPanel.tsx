/**
 * Interactive Design Canvas & Visual Flow Studio (DesignCanvasPanel).
 * - Cho phép người dùng trực quan hóa giao diện (UI Wireframe / Mockup),
 *   vẽ luồng hoạt động (Flow Diagram), và ghi chú trực tiếp lên canvas để Agent thao tác.
 */
import { useState } from 'react'
import {
  Shapes,
  MousePointer,
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
} from 'lucide-react'

type ToolMode = 'select' | 'wireframe' | 'text' | 'arrow' | 'draw'

export function DesignCanvasPanel() {
  const [activeTool, setActiveTool] = useState<ToolMode>('select')
  const [zoomLevel, setZoomLevel] = useState(100)
  const [syncStatus, setSyncStatus] = useState<'idle' | 'synced'>('idle')
  const [selectedElement, setSelectedElement] = useState<string | null>('card-1')

  // Trạng thái thử nghiệm các trường chỉnh sửa trực tiếp trên canvas
  const [componentTitle, setComponentTitle] = useState('Agent Box — Smart AI Workspace')
  const [buttonLabel, setButtonLabel] = useState('Explore Plans')

  const handleSyncToAgent = () => {
    setSyncStatus('synced')
    setTimeout(() => setSyncStatus('idle'), 3000)
  }

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
                activeTool === 'select'
                  ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
                  : 'text-muted hover:text-fg hover:bg-panel'
              }`}
              title="Select / Move Tool (V)"
            >
              <MousePointer className="size-3.5" />
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
              onClick={() => setZoomLevel(100)}
              className="p-1 hover:text-fg transition cursor-pointer ml-0.5"
              title="Reset zoom"
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

      {/* Main Canvas Area with Dot Grid */}
      <div className="relative flex-1 overflow-auto bg-bg bg-[radial-gradient(#27272a_1px,transparent_1px)] [background-size:18px_18px] p-8">
        <div
          className="relative min-w-[800px] min-h-[600px] transition-transform duration-75 origin-top-left"
          style={{ transform: `scale(${zoomLevel / 100})` }}
        >
          {/* Card 1: UI Wireframe / Component Mockup */}
          <div
            onClick={() => setSelectedElement('card-1')}
            className={`absolute left-8 top-8 w-[380px] rounded-xl border bg-panel/90 backdrop-blur-md p-4 shadow-xl transition cursor-pointer ${
              selectedElement === 'card-1'
                ? 'border-brand ring-2 ring-brand/30 shadow-brand/10'
                : 'border-line hover:border-zinc-500'
            }`}
          >
            <div className="flex items-center justify-between border-b border-line/60 pb-2 mb-3">
              <div className="flex items-center gap-1.5 text-xs font-medium text-fg">
                <Layers className="size-3.5 text-brand" />
                <span>Frontend UI Mockup</span>
              </div>
              <span className="rounded bg-brand/15 px-1.5 py-0.5 text-[9px] font-bold text-brand uppercase">
                Interactive
              </span>
            </div>

            <div className="space-y-3">
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

          {/* Flow Connector Arrow */}
          <div className="absolute left-[400px] top-[140px] flex items-center gap-1 text-brand">
            <div className="w-16 h-[2px] bg-brand/60" />
            <MoveRight className="size-4 text-brand -ml-2" />
          </div>

          {/* Card 2: Visual Agent Execution Flow */}
          <div
            onClick={() => setSelectedElement('card-2')}
            className={`absolute left-[480px] top-8 w-[340px] rounded-xl border bg-panel/90 backdrop-blur-md p-4 shadow-xl transition cursor-pointer ${
              selectedElement === 'card-2'
                ? 'border-brand ring-2 ring-brand/30 shadow-brand/10'
                : 'border-line hover:border-zinc-500'
            }`}
          >
            <div className="flex items-center justify-between border-b border-line/60 pb-2 mb-3">
              <div className="flex items-center gap-1.5 text-xs font-medium text-fg">
                <Sliders className="size-3.5 text-amber-400" />
                <span>Agent Reasoning Flow</span>
              </div>
              <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-[9px] font-bold text-amber-300 uppercase">
                Workflow
              </span>
            </div>

            <div className="space-y-2">
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

          {/* Card 3: User Annotation Note */}
          <div
            onClick={() => setSelectedElement('card-3')}
            className={`absolute left-8 top-[320px] w-[500px] rounded-xl border bg-amber-500/10 border-amber-500/30 p-3.5 shadow-lg transition cursor-pointer ${
              selectedElement === 'card-3' ? 'ring-2 ring-amber-400/40' : ''
            }`}
          >
            <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-300 mb-1">
              <Eye className="size-3.5" />
              <span>Annotation & Directive for Agent</span>
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
