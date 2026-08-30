/**
 * `MockInspectRepository` — dữ liệu dựng sẵn cho Element Selector (khung ④),
 * dùng khi `VITE_ELEMENT_INSPECT_SOURCE=mock` (test/demo, KHÔNG cần box thật).
 *
 * Giả một viewport trình duyệt cố định bên trong framebuffer 1280×800 (khớp
 * `MOCK_VIEWPORT` của `lib/vnc` demo): bấm trong viewport ⇒ nhánh `dom`; bấm
 * ngoài viewport (thanh trình duyệt, taskbar…) ⇒ nhánh `desktop` với
 * `reason: 'outside_viewport'`, mô phỏng đúng suy biến MỀM ở §5.2.
 *
 * Mọi payload trả về ở đây phải đi qua `parseInspectElementResult()` được,
 * không được thành `null` — nếu không thì mock đã tự phá hợp đồng mà nó đang
 * mô phỏng cho.
 */
import type { DesktopInspectResult, DomInspectResult, InspectElementRequest, InspectElementResult, InspectLabel } from '../../types/inspect'
import type { InspectRepository } from './types'

export const MOCK_VIEWPORT = { x: 0, y: 96, width: 1280, height: 704 }
export const MOCK_DELAY_MS = 250

function withinViewport(point: InspectElementRequest): boolean {
  return (
    point.x >= MOCK_VIEWPORT.x &&
    point.x < MOCK_VIEWPORT.x + MOCK_VIEWPORT.width &&
    point.y >= MOCK_VIEWPORT.y &&
    point.y < MOCK_VIEWPORT.y + MOCK_VIEWPORT.height
  )
}

function buildLabel(): InspectLabel {
  return {
    integrity: 'khong_tin_duoc',
    confidentiality: 'noi_bo',
    source_kind: 'screen_capture',
    source_uri: 'screen://element/0x02600003',
    tool_name: 'inspect_element',
    content_hash: 'sha256:mock',
  }
}

/** Selector có class — nhánh "đầy đủ" của drawer (có khối `Attributes:`). */
function richDomResult(point: InspectElementRequest): DomInspectResult {
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
    screenBox: { x: point.x - 32, y: point.y - 10, width: 64, height: 20 },
    target: { windowId: '0x02600003', windowTitle: 'BoxFox — Agent Box - Google Chrome', targetId: 'mock-target-1' },
    label: buildLabel(),
  }
}

/** Selector trơn, `attributes` rỗng — nhánh "suy biến" (không có khối `Attributes:`). */
function bareDomResult(point: InspectElementRequest): DomInspectResult {
  return {
    ...richDomResult(point),
    selector: 'span',
    attributes: {},
    html: '<span>boxfox</span>',
  }
}

function desktopResult(_point: InspectElementRequest): DesktopInspectResult {
  return {
    type: 'desktop',
    reason: 'outside_viewport',
    message: 'element inspect: Click outside viewport',
    appName: 'google-chrome',
    windowClass: 'Chromium',
    windowTitle: 'BoxFox — Agent Box - Google Chrome',
    windowId: '0x02600003',
    position: { x: 0, y: 0 },
    size: { width: 1280, height: 800 },
    pid: 4242,
    label: buildLabel(),
  }
}

function delay(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException('Aborted', 'AbortError'))
      return
    }
    const timeoutId = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => {
      clearTimeout(timeoutId)
      reject(new DOMException('Aborted', 'AbortError'))
    })
  })
}

export class MockInspectRepository implements InspectRepository {
  constructor(private readonly delayMs: number = MOCK_DELAY_MS) {}

  async inspect(point: InspectElementRequest, signal?: AbortSignal): Promise<InspectElementResult> {
    await delay(this.delayMs, signal)
    if (!withinViewport(point)) return desktopResult(point)
    // Nửa trái viewport ⇒ mẫu đầy đủ (có class); nửa phải ⇒ mẫu trơn (không attributes).
    return point.x < MOCK_VIEWPORT.x + MOCK_VIEWPORT.width / 2 ? richDomResult(point) : bareDomResult(point)
  }
}
