import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { InspectHttpError } from '../../lib/inspect'
import { ElementInspectorDrawer } from './ElementInspectorDrawer'
import type { InspectorDrawerState } from '../../hooks/useElementInspector'
import type { DesktopInspectResult, DomInspectResult, InspectLabel } from '../../types/inspect'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

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

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

function label(): InspectLabel {
  return {
    integrity: 'khong_tin_duoc',
    confidentiality: 'noi_bo',
    source_kind: 'screen_capture',
    source_uri: 'screen://element/0x1',
    tool_name: 'inspect_element',
    content_hash: 'sha256:x',
  }
}

/** Nhánh dom "đầy đủ" — có `attributes` ⇒ hiện khối Attributes:. */
function richDom(): DomInspectResult {
  return {
    type: 'dom',
    selector: 'span.text-sm.font-semibold',
    url: 'http://localhost:3100/',
    title: 'BoxFox — Agent Box',
    tagName: 'span',
    text: 'boxfox',
    attributes: { class: 'text-sm font-semibold' },
    html: '<span class="text-sm font-semibold">boxfox</span>',
    truncated: false,
    cssBox: { x: 24, y: 18, width: 64, height: 20 },
    screenBox: { x: 100, y: 90, width: 64, height: 20 },
    target: { windowId: '0x1', windowTitle: 'BoxFox — Agent Box - Google Chrome', targetId: 'mock-target-1' },
    label: label(),
  }
}

/** Nhánh dom "suy biến" — `attributes` rỗng ⇒ khối Attributes: PHẢI vắng hoàn toàn. */
function bareDom(): DomInspectResult {
  return {
    ...richDom(),
    selector: 'span',
    attributes: {},
    html: '<span>boxfox</span>',
    truncated: true,
  }
}

function desktopWithReason(): DesktopInspectResult {
  return {
    type: 'desktop',
    reason: 'outside_viewport',
    message: 'element inspect: Click outside viewport',
    appName: 'google-chrome',
    windowClass: 'Chromium',
    windowTitle: 'BoxFox — Agent Box - Google Chrome',
    windowId: '0x1',
    position: { x: 0, y: 0 },
    size: { width: 1280, height: 800 },
    pid: 4242,
    label: label(),
  }
}

describe('ElementInspectorDrawer', () => {
  it('trạng thái loading: có aria-busy, spinner, KHÔNG có badge không tin được, nút Thêm vào hội thoại bị disabled nhưng vẫn hiện', () => {
    const state: InspectorDrawerState = { status: 'loading', point: { x: 10, y: 20 } }
    const onAddToChat = vi.fn()
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={onAddToChat} />,
    )
    const body = host.querySelector('[aria-busy="true"]')
    expect(body).toBeTruthy()
    expect(host.textContent).toContain('(10, 20)')
    const addButton = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Add to Chat')
    expect(addButton).toBeTruthy()
    expect((addButton as HTMLButtonElement).disabled).toBe(true)
  })

  it('trạng thái lỗi: KHÔNG có nút Thêm vào hội thoại, có nút Thử lại gọi onRetry, và lỗi InspectHttpError dịch theo kind (không phô message thô)', () => {
    const state: InspectorDrawerState = {
      status: 'error',
      point: { x: 1, y: 2 },
      error: new InspectHttpError('server', 504, 'Yêu cầu thanh tra phần tử thất bại (504).'),
    }
    const onRetry = vi.fn()
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={onRetry} onAddToChat={vi.fn()} />,
    )
    const addButton = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Add to Chat')
    expect(addButton).toBeUndefined()
    expect(host.textContent).toContain('The box failed while handling the inspect request.')
    expect(host.textContent).not.toContain('Yêu cầu thanh tra phần tử thất bại (504).')
    const retryButton = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Retry')!
    act(() => {
      retryButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('nhánh dom đầy đủ: hiện khối Attributes:, KHÔNG có dòng Source:/Open in IDE', () => {
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result: richDom() }
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={vi.fn()} />,
    )
    expect(host.textContent).toContain('span.text-sm.font-semibold')
    expect(host.textContent).toContain('class="text-sm font-semibold"')
    expect(host.textContent).not.toMatch(/Source:/)
    expect(host.textContent).not.toMatch(/Open in IDE/)
  })

  it('nhánh dom suy biến: attributes rỗng ⇒ khối Attributes: vắng hoàn toàn; truncated ⇒ hiện ghi chú cắt ngắn', () => {
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result: bareDom() }
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={vi.fn()} />,
    )
    expect(host.textContent).not.toContain('Attributes:')
    expect(host.textContent).toContain('The box truncated this content.')
  })

  it('nhánh dom có notes: hiện dòng Lưu ý đã dịch theo mã note', () => {
    const result: DomInspectResult = { ...richDom(), notes: ['shadow_dom'] }
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result }
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={vi.fn()} />,
    )
    expect(host.textContent).toContain('Note:')
    expect(host.textContent).toContain('The element lives inside a Shadow DOM — outer code cannot see it.')
  })

  it('nội dung phần tử chứa HTML độc: render trơ, không tạo element script/img', () => {
    const result: DomInspectResult = {
      ...richDom(),
      text: '</pre><script>alert(1)</script>',
      html: '<img src=x onerror=alert(2)>',
    }
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result }
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={vi.fn()} />,
    )
    expect(host.querySelector('script')).toBeNull()
    expect(host.querySelector('img')).toBeNull()
    expect(host.textContent).toContain('</pre><script>alert(1)</script>')
  })

  it('nhánh desktop: ưu tiên bản dịch của reason (không phải message thô của box) làm banner cảnh báo', () => {
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result: desktopWithReason() }
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={vi.fn()} />,
    )
    // reason 'outside_viewport' dịch sang câu tiếng Việt cố định — KHÔNG phải chuỗi `message` thô của box.
    expect(host.textContent).toContain('The click landed outside the page content area')
    expect(host.textContent).not.toContain('element inspect: Click outside viewport')
    expect(host.textContent).toContain('google-chrome')
    expect(host.textContent).toContain('BoxFox — Agent Box - Google Chrome')
  })

  it('nhánh desktop: reason vắng ⇒ lùi về message thô của box (qua PlainText)', () => {
    const result: DesktopInspectResult = { ...desktopWithReason(), reason: undefined }
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result }
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={vi.fn()} />,
    )
    expect(host.textContent).toContain('element inspect: Click outside viewport')
  })

  it('Escape đóng ngăn kéo (gọi onClose) bất kể trạng thái', () => {
    const state: InspectorDrawerState = { status: 'loading', point: { x: 1, y: 2 } }
    const onClose = vi.fn()
    render(<ElementInspectorDrawer state={state} onClose={onClose} onRetry={vi.fn()} onAddToChat={vi.fn()} />)
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('bấm nút đóng (X) gọi onClose', () => {
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result: richDom() }
    const onClose = vi.fn()
    const host = render(
      <ElementInspectorDrawer state={state} onClose={onClose} onRetry={vi.fn()} onAddToChat={vi.fn()} />,
    )
    const closeButton = host.querySelector('button[aria-label="Close"]')!
    act(() => {
      closeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('nhánh thành công: bấm Thêm vào hội thoại gọi onAddToChat', () => {
    const state: InspectorDrawerState = { status: 'success', point: { x: 1, y: 2 }, result: richDom() }
    const onAddToChat = vi.fn()
    const host = render(
      <ElementInspectorDrawer state={state} onClose={vi.fn()} onRetry={vi.fn()} onAddToChat={onAddToChat} />,
    )
    const addButton = Array.from(host.querySelectorAll('button')).find((b) => b.textContent === 'Add to Chat')!
    act(() => {
      addButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onAddToChat).toHaveBeenCalledTimes(1)
  })
})
