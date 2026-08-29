/**
 * Thanh công cụ Design Canvas: cụm tool (select/hand/pencil) + shape picker +
 * chèn nhanh (rect/card/arrow) + webview + Clear/Send + zoom. Tự co về icon-only
 * khi hẹp (`compact` do `useCompactCanvasToolbar` đo). Giữ đúng ngôn ngữ thiết kế
 * BoxFox: English label, lucide icon, dark tokens, brand #3b82f6.
 */
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  Diamond,
  Eye,
  Globe,
  Hand,
  Layers,
  MousePointer,
  MoveRight,
  Pencil,
  Plus,
  RotateCcw,
  Shapes,
  Sliders,
  Sparkles,
  Square,
  Trash2,
  Triangle,
  Type,
  ZoomIn,
  ZoomOut,
} from 'lucide-react'
import { useState } from 'react'
import type { DesignCanvas } from '../../../hooks/useDesignCanvas'

interface CanvasToolbarProps {
  canvas: DesignCanvas
  compact: boolean
}

type DropdownId = 'shapes' | 'cards' | null

export function CanvasToolbar({ canvas, compact }: CanvasToolbarProps) {
  const [dropdown, setDropdown] = useState<DropdownId>(null)
  const { activeTool } = canvas

  function toolButtonClass(active: boolean): string {
    return `flex size-7 items-center justify-center rounded-md text-xs transition cursor-pointer ${
      active
        ? 'bg-brand/20 text-brand font-medium shadow-2xs border border-brand/40'
        : 'text-muted hover:text-fg hover:bg-panel'
    }`
  }

  return (
    <div className="relative flex h-11 shrink-0 items-center justify-between border-b border-line bg-panel px-3.5">
      <div className="flex items-center gap-2">
        <div className="flex items-center pr-2 border-r border-line" title="Design Canvas">
          <Shapes className="size-4 text-brand" />
        </div>

        {/* Cụm công cụ chính */}
        <div className="flex items-center gap-1 bg-panel2/60 p-0.5 rounded-lg border border-line">
          <button type="button" onClick={() => canvas.setTool('select')} className={toolButtonClass(activeTool === 'select')} title="Select / Move (V)">
            <MousePointer className="size-3.5" />
          </button>
          <button type="button" onClick={() => canvas.setTool('hand')} className={toolButtonClass(activeTool === 'hand')} title="Hand / Pan (H or Space)">
            <Hand className="size-3.5" />
          </button>
          <button type="button" onClick={() => canvas.setTool('pencil')} className={toolButtonClass(activeTool === 'pencil')} title="Pencil / Draw (P)">
            <Pencil className="size-3.5" />
          </button>

          {/* Shape picker (Rect/Ellipse/Triangle/Diamond) */}
          <div className="relative">
            <button
              type="button"
              onClick={() => setDropdown(dropdown === 'shapes' ? null : 'shapes')}
              className="flex items-center gap-0.5 rounded-md px-1.5 text-muted hover:text-fg hover:bg-panel transition cursor-pointer h-7"
              title="Add shape"
            >
              <Square className="size-3.5" />
              <ChevronDown className="size-3" />
            </button>
            {dropdown === 'shapes' && (
              <>
                <div className="fixed inset-0 z-20" onClick={() => setDropdown(null)} />
                <div className="absolute left-0 top-8 z-30 w-36 rounded-lg border border-line bg-panel p-1 shadow-2xl">
                  {(
                    [
                      { kind: 'rect', Icon: Square, label: 'Rectangle' },
                      { kind: 'ellipse', Icon: Circle, label: 'Ellipse' },
                      { kind: 'triangle', Icon: Triangle, label: 'Triangle' },
                      { kind: 'diamond', Icon: Diamond, label: 'Diamond' },
                    ] as const
                  ).map(({ kind, Icon, label }) => (
                    <button
                      key={kind}
                      type="button"
                      onClick={() => {
                        canvas.addShape(kind)
                        setDropdown(null)
                      }}
                      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-fg hover:bg-panel2 transition cursor-pointer"
                    >
                      <Icon className="size-3.5 text-brand" />
                      {label}
                    </button>
                  ))}
                </div>
              </>
            )}
          </div>

          <button type="button" onClick={() => canvas.addShape('rect')} className={toolButtonClass(false)} title="Add Rect (R)">
            <Square className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => canvas.addCard('directive-annotation')}
            className={toolButtonClass(false)}
            title="Add annotation card (T)"
          >
            <Type className="size-3.5" />
          </button>
          <button type="button" onClick={() => canvas.setTool('arrow')} className={toolButtonClass(activeTool === 'arrow')} title="Connector (A)">
            <MoveRight className="size-3.5" />
          </button>
        </div>

        {/* Nút "+" thêm card & web preview */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setDropdown(dropdown === 'cards' ? null : 'cards')}
            className="flex size-7 items-center justify-center rounded-md text-xs text-muted hover:text-fg hover:bg-panel transition cursor-pointer border border-line bg-panel2/40"
            title="Add card or web preview"
          >
            <Plus className="size-3.5" />
          </button>
          {dropdown === 'cards' && (
            <>
              <div className="fixed inset-0 z-20" onClick={() => setDropdown(null)} />
              <div className="absolute left-0 top-8 z-30 w-56 rounded-lg border border-line bg-panel p-1 shadow-2xl">
                {(
                  [
                    { kind: 'ui-mockup', label: 'UI Mockup', Icon: Layers, color: 'text-brand' },
                    { kind: 'agent-reasoning-flow', label: 'Agent Reasoning Flow', Icon: Sliders, color: 'text-amber-400' },
                    { kind: 'directive-annotation', label: 'Directive Annotation', Icon: Eye, color: 'text-amber-300' },
                    { kind: 'webview', label: 'Live Web Preview', Icon: Globe, color: 'text-sky-400' },
                  ] as const
                ).map(({ kind, label, Icon, color }) => (
                  <button
                    key={kind}
                    type="button"
                    onClick={() => {
                      if (kind === 'webview') {
                        canvas.addWebview('https://example.com')
                      } else {
                        canvas.addCard(kind)
                      }
                      setDropdown(null)
                    }}
                    className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs text-fg hover:bg-panel2 transition cursor-pointer"
                  >
                    <Icon className={`size-3.5 ${color}`} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {canvas.scene.strokes.length > 0 && (
          <button
            type="button"
            onClick={canvas.clearStrokes}
            className={`flex items-center gap-1 text-[11px] text-muted hover:text-rose-400 rounded bg-panel2/40 border border-line transition cursor-pointer ${
              compact ? 'size-7 justify-center px-0' : 'px-2 py-1 ml-1'
            }`}
            title="Clear all sketches"
          >
            <Trash2 className="size-3" />
            {!compact && <span>Clear</span>}
          </button>
        )}
      </div>

      {/* Send to Agent */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => canvas.sendToAgent()}
          className={`flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-md text-xs font-semibold transition cursor-pointer shadow-xs ${
            canvas.syncStatus === 'synced'
              ? 'bg-emerald-600 text-white border border-emerald-500'
              : 'bg-brand text-white hover:bg-brand/90 border border-brand/60'
          } ${compact ? 'size-7 justify-center px-0' : 'px-2.5 py-1'}`}
          title={canvas.syncStatus === 'synced' ? 'Scene synced with agent' : 'Send scene to agent'}
        >
          {canvas.syncStatus === 'synced' ? (
            <CheckCircle2 className="size-3.5 text-white" />
          ) : (
            <Sparkles className="size-3.5 text-white animate-pulse" />
          )}
          {!compact && <span>{canvas.syncStatus === 'synced' ? 'Synced' : 'Send to Agent'}</span>}
        </button>
      </div>
    </div>
  )
}
