/**
 * Design Canvas — view mỏng. Toàn bộ logic nằm trong `useDesignCanvas` (scene
 * bất biến + history) và các component `canvas/`; panel này chỉ ráp toolbar +
 * stage và đo ngưỡng compact. Import ở `App.tsx` giữ nguyên (named export).
 */
import { useRef } from 'react'
import { useCompactCanvasToolbar } from '../../hooks/useCompactCanvasToolbar'
import { useDesignCanvas } from '../../hooks/useDesignCanvas'
import { CanvasStage } from './canvas/CanvasStage'
import { CanvasToolbar } from './canvas/CanvasToolbar'

export function DesignCanvasPanel() {
  const canvas = useDesignCanvas()
  const toolbarRef = useRef<HTMLDivElement>(null)
  const compact = useCompactCanvasToolbar(toolbarRef)

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-bg font-sans select-none">
      <div ref={toolbarRef} className="shrink-0">
        <CanvasToolbar canvas={canvas} compact={compact} />
      </div>
      <CanvasStage canvas={canvas} />
    </div>
  )
}
