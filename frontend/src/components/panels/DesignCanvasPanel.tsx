/**
 * Design Canvas — panel duy nhất của tab Design (được `DesignPanel` ráp vào ngăn "Canvas").
 *
 * Toàn bộ logic nằm trong `useDesignCanvas` (scene bất biến + history) và các component `canvas/`;
 * tệp này chỉ ráp dải "canvas sống" + toolbar + stage, đo ngưỡng compact, và liệt kê node để chủ nhà
 * chỉ vào một node mà bảo agent sửa (P2, kế hoạch §5 bước 5).
 */
import { useRef } from 'react'
import { useCompactCanvasToolbar } from '../../hooks/useCompactCanvasToolbar'
import { useDesignCanvas } from '../../hooks/useDesignCanvas'
import { useT } from '../../i18n/context'
import { cardTitleFallback } from '../../lib/canvas'
import { selectActiveRun, useDesignStore } from '../../store/designStore'
import { CanvasStage } from './canvas/CanvasStage'
import { CanvasToolbar } from './canvas/CanvasToolbar'

/**
 * Dải "canvas sống": ai đang vẽ, bao nhiêu thao tác, bao nhiêu op bị bỏ. Đọc từ `designStore` nên
 * cùng một nguồn với thẻ hội thoại (P2).
 *
 * Luật trung thực: câu "đang vẽ" chỉ được nói khi lớp phát lại ĐANG chạy, hoặc khi run ở pha
 * `drawing` **và** agent đã thật sự gửi ít nhất một op (`lastOps`). Trước đây dải này chỉ đọc
 * `phase === 'drawing'` nên canvas rỗng vẫn hô "đang vẽ · 4 thao tác" (cảnh mẫu cứng).
 */
export function DesignCanvasLiveDraw({
  count,
  playing = false,
  drawn = 0,
  total = 0,
  onSkip,
}: {
  count: number
  playing?: boolean
  drawn?: number
  total?: number
  onSkip?: () => void
}) {
  const t = useT()
  const run = useDesignStore(selectActiveRun)
  const actor = useDesignStore((s) => (run ? s.sceneActor[run.designId] ?? '' : ''))
  const agentHasDrawn = useDesignStore((s) => {
    const batch = run ? s.lastOps[run.designId] : undefined
    return Boolean(batch && batch.actor === 'agent' && batch.ops.length > 0)
  })
  const rejectedOps = useDesignStore((s) => s.rejectedOps)
  // `drawing` = "canvas này là của agent ở pha vẽ", KHÔNG phải "đang có hoạt hình trên màn hình":
  // pha `drawing` mà lô op đã vẽ xong vẫn giữ `drawing=true` trong khi `playing=false`. Muốn hỏi
  // "có hoạt hình đang chạy không" thì đọc `data-playing`.
  const drawing = playing || (run?.phase === 'drawing' && agentHasDrawn)
  return (
    <div
      data-testid="design-canvas-live-draw"
      data-drawing={drawing ? 'true' : 'false'}
      data-playing={playing ? 'true' : 'false'}
      data-actor={actor || 'none'}
      className={`flex shrink-0 items-center gap-2 border-b px-2 py-1 text-[11px] ${
        drawing ? 'border-brand/40 bg-brand/5 text-brand' : 'border-line text-muted'
      }`}
    >
      <span className="font-medium">
        {playing
          ? t('design.canvasPlaying', { drawn, total })
          : count > 0
            ? t('design.canvasDrawing', { count })
            : t('design.canvasIdle')}
      </span>
      {actor && (
        <span data-testid="design-canvas-actor" className="font-mono text-[10px]">
          {actor === 'user' ? t('design.canvasActorUser') : t('design.canvasActorAgent')}
        </span>
      )}
      {playing && onSkip && (
        <button
          type="button"
          data-testid="design-canvas-skip"
          onClick={onSkip}
          className="rounded border border-brand/50 px-1.5 py-0.5 text-[10px] transition hover:bg-brand/10 cursor-pointer"
        >
          {t('design.canvasSkip')}
        </button>
      )}
      {rejectedOps > 0 && (
        <span data-testid="design-canvas-rejected" className="ml-auto text-amber-300">
          {t('design.rejectCount', { count: rejectedOps })}
        </span>
      )}
    </div>
  )
}

export function DesignCanvasPanel() {
  const t = useT()
  const canvas = useDesignCanvas()
  const toolbarRef = useRef<HTMLDivElement>(null)
  const compact = useCompactCanvasToolbar(toolbarRef)
  const count = canvas.scene.nodes.length + canvas.scene.connectors.length + canvas.scene.strokes.length

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-bg font-sans select-none">
      <DesignCanvasLiveDraw
        count={count}
        playing={canvas.playing}
        drawn={canvas.drawn}
        total={canvas.total}
        onSkip={canvas.skipPlayback}
      />
      <div ref={toolbarRef} className="shrink-0">
        <CanvasToolbar canvas={canvas} compact={compact} />
      </div>
      <CanvasStage canvas={canvas} />
      {count === 0 && !canvas.playing && (
        <div
          data-testid="design-canvas-empty"
          className="shrink-0 border-t border-line px-2 py-2 text-[11px] text-muted"
        >
          <p>{t('design.canvasEmptyHint')}</p>
          <button
            type="button"
            data-testid="design-canvas-draw-map"
            onClick={() => canvas.requestProjectMap()}
            className="mt-1 rounded border border-line px-1.5 py-0.5 transition hover:text-fg cursor-pointer"
          >
            {t('design.canvasDrawMap')}
          </button>
        </div>
      )}
      {canvas.scene.nodes.length > 0 && (
        <ul className="max-h-24 shrink-0 overflow-auto border-t border-line px-2 py-1 text-[11px]">
          {canvas.scene.nodes.map((node) => (
            <li key={node.id} className="flex items-center gap-2">
              <span className="truncate text-fg">{node.title || cardTitleFallback(node.card)}</span>
              <button
                type="button"
                data-testid="design-canvas-directive"
                onClick={() => canvas.instructAgent(node.id)}
                className="ml-auto shrink-0 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
              >
                {t('design.canvasDirective')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
