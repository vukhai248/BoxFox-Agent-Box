/**
 * Lớp phủ của Element Selector (khung ④, F9) — nằm ĐÈ lên canvas noVNC, không
 * bao giờ nằm TRONG cây DOM của nó và không bao giờ khiến container đổi kích
 * thước (F-3, mục 12 kế hoạch): container noVNC co giãn ⇒ `fit.ts:153` bắt
 * `rfb.resizeSession = true` đổi luôn độ phân giải màn hình thật, làm hỏng
 * `screenBox` vừa đo. Component này CHỈ tự định vị `absolute` bên trong một
 * cha `relative` đã có sẵn (`SandboxScreenPanel.tsx`), không chạm layout.
 *
 * Ba việc:
 *   1. Khi `armed`: một lớp bắt cú bấm che kín toàn khung (kể cả dải letterbox
 *      đen), `preventDefault()` + `stopPropagation()` MỌI `pointerdown` nhận
 *      được — noVNC không được thấy cú bấm này dưới bất kỳ hình thức nào.
 *   2. Khi `armed`: dải gợi ý nổi giữa khung + con trỏ crosshair, và nghe
 *      `Escape` ở mức `document` để gọi `onEscape`.
 *   3. Khi có `highlightBox` (bất kể `armed`): vẽ khung sáng quanh phần tử vừa
 *      thanh tra — vẫn hiện sau khi tự tắt chế độ chọn (Q5) vì ngăn kéo đang mở.
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import {
  canvasPointToFramebuffer,
  framebufferBoxToCanvasCss,
  type CssBox,
  type FramebufferPoint,
} from '../../lib/vnc/inspect'
import { useT } from '../../i18n/context'
import type { InspectBox } from '../../types/inspect'

export interface ElementInspectorOverlayProps {
  /** `true` ⇒ cú bấm kế tiếp bị lớp này bắt, không tới canvas bên dưới. */
  armed: boolean
  /** Ref tới div bọc `<canvas>` noVNC (`vnc.containerRef` của `useVncScreen`). */
  canvasContainerRef: React.RefObject<HTMLDivElement | null>
  /** Hộp bao framebuffer/X11 cần vẽ khung sáng — `null` ⇒ không vẽ gì. */
  highlightBox: InspectBox | null
  /** Nhãn ngắn cạnh khung sáng, ví dụ `span · 58×17` — bỏ trống thì không hiện nhãn. */
  highlightLabel?: string | null
  onPick: (point: FramebufferPoint) => void
  onEscape: () => void
}

export function ElementInspectorOverlay({
  armed,
  canvasContainerRef,
  highlightBox,
  highlightLabel,
  onPick,
  onEscape,
}: ElementInspectorOverlayProps) {
  const t = useT()
  const overlayRef = useRef<HTMLDivElement>(null)
  // Không có `ResizeObserver` nào bắt được "toạ độ CSS của canvas đổi mà kích
  // thước container thì không" (ví dụ scaleViewport co lại) — tick này ép tính
  // lại rect ở MỌI lần container hoặc window đổi kích thước.
  const [resizeTick, setResizeTick] = useState(0)

  useEffect(() => {
    const container = canvasContainerRef.current
    if (!container) return
    // jsdom (môi trường test) không có `ResizeObserver` — bỏ qua theo dõi resize
    // ở đó, giống khuôn mẫu đã dùng ở `useCompactCanvasToolbar.ts`/`useVncScreen.ts`.
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setResizeTick((v) => v + 1))
    observer.observe(container)
    const onWindowResize = () => setResizeTick((v) => v + 1)
    window.addEventListener('resize', onWindowResize)
    return () => {
      observer.disconnect()
      window.removeEventListener('resize', onWindowResize)
    }
  }, [canvasContainerRef])

  // Esc thoát chế độ chọn — chỉ nghe khi đang `armed` (drawer không thể đang mở
  // cùng lúc, xem quyết định Q5 ở `useElementInspector.handlePick`).
  useEffect(() => {
    if (!armed) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onEscape()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [armed, onEscape])

  const [highlightCssBox, setHighlightCssBox] = useState<CssBox | null>(null)

  // CỐ Ý dùng `useLayoutEffect` + `useState`, KHÔNG `useMemo`: ở lần render
  // ĐẦU TIÊN (ví dụ mount thẳng với `highlightBox` đã có sẵn), `overlayRef`
  // vẫn còn `null` lúc thân hàm render chạy — ref chỉ được gắn ở pha commit,
  // SAU render. Một `useMemo` tính trong pha render sẽ vĩnh viễn thấy
  // `overlayRef.current === null` ở lượt đó và trả `null`, và vì deps của nó
  // (`highlightBox`, `resizeTick`) không đổi tiếp theo, khung sáng sẽ không
  // bao giờ hiện cho tới khi có resize khác kéo tới. `useLayoutEffect` chạy
  // SAU commit (ref đã gắn) và TRƯỚC khi trình duyệt sơn khung hình, nên tính
  // đúng ngay từ lần đầu mà không nhấp nháy.
  useLayoutEffect(() => {
    if (!highlightBox) {
      setHighlightCssBox(null)
      return
    }
    const canvas = canvasContainerRef.current?.querySelector('canvas')
    const overlay = overlayRef.current
    if (!canvas || !overlay) {
      setHighlightCssBox(null)
      return
    }
    setHighlightCssBox(
      framebufferBoxToCanvasCss({
        box: highlightBox,
        canvasRect: canvas.getBoundingClientRect(),
        overlayRect: overlay.getBoundingClientRect(),
        canvasWidth: canvas.width,
        canvasHeight: canvas.height,
      }),
    )
    // `resizeTick` không được đọc bên trong nhưng PHẢI ở deps: nó là tín hiệu
    // duy nhất báo "rect có thể đã đổi, tính lại".
  }, [highlightBox, resizeTick, canvasContainerRef])

  function handlePointerDown(event: React.PointerEvent<HTMLDivElement>) {
    // Chặn TUYỆT ĐỐI trước, bất kể cú bấm có tra ra điểm hợp lệ hay không —
    // noVNC không được thấy cú bấm này dưới bất kỳ hình thức nào.
    event.preventDefault()
    event.stopPropagation()

    const canvas = canvasContainerRef.current?.querySelector('canvas')
    if (!canvas) return
    const rect = canvas.getBoundingClientRect()
    const point = canvasPointToFramebuffer({
      rect,
      canvasWidth: canvas.width,
      canvasHeight: canvas.height,
      clientX: event.clientX,
      clientY: event.clientY,
    })
    // `null` ⇒ bấm vào dải letterbox đen — bỏ qua hẳn, KHÔNG gọi `onPick`,
    // KHÔNG tự tắt `armed` (người dùng còn cơ hội bấm lại đúng canvas).
    if (point) onPick(point)
  }

  return (
    <div ref={overlayRef} className="pointer-events-none absolute inset-0">
      {armed && (
        <div
          role="button"
          tabIndex={0}
          aria-label={t('screen.inspector.canvasArmedLabel')}
          data-testid="inspector-click-catcher"
          onPointerDown={handlePointerDown}
          className="pointer-events-auto absolute inset-0 cursor-crosshair bg-brand/[0.04] ring-1 ring-inset ring-brand/35"
        />
      )}
      {armed && (
        // `top-11` thay vì `top-3`: nhường chỗ cho dải "đã lên nòng" mà
        // `SandboxScreenPanel` vẽ tuyệt đối ở mép trên canvas (mục review F-3).
        <span className="pointer-events-none absolute left-1/2 top-11 -translate-x-1/2 rounded-full bg-brand px-3 py-1 text-[11px] font-semibold text-white shadow">
          {t('screen.inspector.hintPill')}
        </span>
      )}
      {highlightCssBox && (
        <div
          data-testid="inspector-highlight-box"
          className="pointer-events-none absolute outline outline-1 outline-brand bg-brand/10"
          style={{
            left: highlightCssBox.left,
            top: highlightCssBox.top,
            width: highlightCssBox.width,
            height: highlightCssBox.height,
          }}
        >
          {highlightLabel && (
            <span className="absolute left-[-1px] top-[calc(100%+3px)] whitespace-nowrap rounded bg-brand px-1.5 py-0.5 font-mono text-[10px] text-white">
              {highlightLabel}
            </span>
          )}
        </div>
      )}
    </div>
  )
}
