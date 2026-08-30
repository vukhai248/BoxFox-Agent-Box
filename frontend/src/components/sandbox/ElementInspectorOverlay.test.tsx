import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { ElementInspectorOverlay } from './ElementInspectorOverlay'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// jsdom không tự layout nên mọi `getBoundingClientRect()` mặc định trả về
// hình chữ nhật rỗng (width/height = 0). `framebufferBoxToCanvasCss` coi rect
// rỗng là "chưa đo được" và cố tình trả `null` (xem `inspect.ts`) — điều này
// đúng khi phần tử thật sự chưa layout, nhưng làm sai lệch test vì overlay
// (một `<div>` không có rect riêng) không đại diện cho trường hợp đó. Ghi đè
// mặc định ở mức prototype để overlay có kích thước hợp lý (khớp container
// 640×400 CSS mô phỏng ở `buildCanvasContainer`); `canvas` vẫn tự ghi đè rect
// riêng trên instance của nó (ưu tiên hơn prototype) nên không bị ảnh hưởng.
HTMLElement.prototype.getBoundingClientRect = () =>
  ({ left: 0, top: 0, right: 640, bottom: 400, width: 640, height: 400, x: 0, y: 0, toJSON() {} }) as DOMRect

let roots: Root[] = []

function render(node: React.ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(<I18nProvider>{node}</I18nProvider>)
  })
  return host
}

/** Canvas 1280×800 chiếm đúng 640×400 CSS trên trang (tỉ lệ 2:1, mô phỏng DPR=2). */
function buildCanvasContainer(): { container: HTMLDivElement; canvas: HTMLCanvasElement } {
  const container = document.createElement('div')
  const canvas = document.createElement('canvas')
  canvas.width = 1280
  canvas.height = 800
  container.append(canvas)
  document.body.append(container)
  canvas.getBoundingClientRect = () =>
    ({ left: 10, top: 20, right: 650, bottom: 420, width: 640, height: 400, x: 10, y: 20, toJSON() {} }) as DOMRect
  return { container, canvas }
}

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

describe('ElementInspectorOverlay', () => {
  it('KHÔNG render lớp bắt cú bấm khi chưa armed', () => {
    const { container } = buildCanvasContainer()
    const ref = { current: container }
    const host = render(
      <ElementInspectorOverlay
        armed={false}
        canvasContainerRef={ref}
        highlightBox={null}
        onPick={vi.fn()}
        onEscape={vi.fn()}
      />,
    )
    expect(host.querySelector('[data-testid="inspector-click-catcher"]')).toBeNull()
  })

  it('pointerdown khi armed bị preventDefault (noVNC không thấy cú bấm) và tính đúng điểm framebuffer', () => {
    const { container } = buildCanvasContainer()
    const ref = { current: container }
    const onPick = vi.fn()
    const host = render(
      <ElementInspectorOverlay
        armed
        canvasContainerRef={ref}
        highlightBox={null}
        onPick={onPick}
        onEscape={vi.fn()}
      />,
    )
    const catcher = host.querySelector('[data-testid="inspector-click-catcher"]')!

    // clientX=330,clientY=220 ⇒ giữa canvas theo CSS (10+320, 20+200) ⇒ scale ×2 ⇒ (640,400) framebuffer.
    const event = new MouseEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      clientX: 330,
      clientY: 220,
    })
    let dispatched = true
    act(() => {
      dispatched = catcher.dispatchEvent(event)
    })

    // `dispatchEvent` trả `false` khi `defaultPrevented` — đây CHÍNH LÀ bằng chứng
    // noVNC (nằm dưới overlay) không bao giờ thấy cú bấm này.
    expect(dispatched).toBe(false)
    expect(event.defaultPrevented).toBe(true)
    expect(onPick).toHaveBeenCalledWith({ x: 640, y: 400 })
  })

  it('bấm ra ngoài canvas (dải letterbox) vẫn preventDefault nhưng KHÔNG gọi onPick', () => {
    const { container } = buildCanvasContainer()
    const ref = { current: container }
    const onPick = vi.fn()
    const host = render(
      <ElementInspectorOverlay
        armed
        canvasContainerRef={ref}
        highlightBox={null}
        onPick={onPick}
        onEscape={vi.fn()}
      />,
    )
    const catcher = host.querySelector('[data-testid="inspector-click-catcher"]')!
    const event = new MouseEvent('pointerdown', {
      bubbles: true,
      cancelable: true,
      clientX: 0,
      clientY: 0,
    })
    act(() => {
      catcher.dispatchEvent(event)
    })

    expect(event.defaultPrevented).toBe(true)
    expect(onPick).not.toHaveBeenCalled()
  })

  it('Escape khi armed gọi onEscape', () => {
    const { container } = buildCanvasContainer()
    const ref = { current: container }
    const onEscape = vi.fn()
    render(
      <ElementInspectorOverlay
        armed
        canvasContainerRef={ref}
        highlightBox={null}
        onPick={vi.fn()}
        onEscape={onEscape}
      />,
    )

    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(onEscape).toHaveBeenCalledTimes(1)
  })

  it('Escape KHÔNG gọi onEscape khi chưa armed', () => {
    const { container } = buildCanvasContainer()
    const ref = { current: container }
    const onEscape = vi.fn()
    render(
      <ElementInspectorOverlay
        armed={false}
        canvasContainerRef={ref}
        highlightBox={null}
        onPick={vi.fn()}
        onEscape={onEscape}
      />,
    )

    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(onEscape).not.toHaveBeenCalled()
  })

  it('vẽ khung sáng đúng vị trí CSS khi có highlightBox, kể cả sau khi đã tự tắt armed', () => {
    const { container } = buildCanvasContainer()
    const ref = { current: container }
    const host = render(
      <ElementInspectorOverlay
        armed={false}
        canvasContainerRef={ref}
        highlightBox={{ x: 640, y: 400, width: 128, height: 64 }}
        highlightLabel="span · 64×32"
        onPick={vi.fn()}
        onEscape={vi.fn()}
      />,
    )
    const box = host.querySelector('[data-testid="inspector-highlight-box"]') as HTMLElement
    expect(box).toBeTruthy()
    // scale = 640/1280 = 0.5 ⇒ left = 10(canvasRect.left-overlayRect.left=0 vì overlay không đặt rect riêng ⇒ 10) + 640*0.5
    expect(box.style.left).toBe('330px')
    expect(box.style.top).toBe('220px')
    expect(box.style.width).toBe('64px')
    expect(box.style.height).toBe('32px')
    expect(box.textContent).toBe('span · 64×32')
  })

  it('highlightBox null ⇒ không vẽ khung sáng', () => {
    const { container } = buildCanvasContainer()
    const ref = { current: container }
    const host = render(
      <ElementInspectorOverlay
        armed={false}
        canvasContainerRef={ref}
        highlightBox={null}
        onPick={vi.fn()}
        onEscape={vi.fn()}
      />,
    )
    expect(host.querySelector('[data-testid="inspector-highlight-box"]')).toBeNull()
  })
})
