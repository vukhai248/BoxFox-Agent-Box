/**
 * Test cho panel "Màn hình máy" (host mode) — bề mặt chọn đích CUA của phiên.
 *
 * Cách test: `fetch` được thay bằng một MÁY CHỦ GIẢ có trạng thái (đích, danh sách
 * cửa sổ, lease, ảnh chụp). Nhờ vậy panel chạy đúng đường thật của nó —
 * `agentApi` → `lib/desktop/target.ts` → `lib/inspect/host.ts` — chứ không phải
 * một bản dựng lại bằng mock từng hàm. Hợp đồng route (path/method/body) được
 * khoá ở `lib/desktop/target.test.ts`; ở đây khoá HÀNH VI của panel.
 *
 * Bốn điều quan trọng nhất mà tệp này bảo vệ:
 *   1. **Không response cũ nào được vẽ** (ca "huỷ"): lượt chụp của đích cũ về
 *      muộn — kể cả khi `fetch` không huỷ được — cũng không được đè ảnh mới.
 *   2. **Theo agent**: đích đổi ở backend ⇒ panel đổi theo, nói rõ ai vừa đổi.
 *   3. **Nút chọn phần tử bị khoá khi người dùng giữ quyền**, kèm đường trả quyền
 *      ngay tại chỗ (route thanh tra đòi agent lease).
 *   4. **Không có danh sách cửa sổ (Linux) là trạng thái bình thường**, không
 *      phải một đống lỗi đỏ.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useAgentStore } from '../../store/agentStore'
import { useComposerStore } from '../../store/composerStore'
import { HostMachineScreen } from './HostMachineScreen'
import type { CuaActiveWindow, CuaTarget, HostWindowEntry } from '../../types/desktopTarget'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

// jsdom không layout: mọi `getBoundingClientRect()` mặc định là rect RỖNG, mà
// `lib/vnc/inspect.ts` cố tình coi rect rỗng là "chưa đo được" (trả `null`).
// Ghi đè ở mức prototype để khung ảnh có kích thước thật; ảnh 800×600 chiếm
// 400×300 CSS (tỉ lệ 2:1, đúng tình huống DPR = 2).
const IMG_RECT = { left: 100, top: 50, right: 500, bottom: 350, width: 400, height: 300 }
HTMLElement.prototype.getBoundingClientRect = () =>
  ({ ...IMG_RECT, x: IMG_RECT.left, y: IMG_RECT.top, toJSON() {} }) as DOMRect

const SESSION_ID = 'sess-1'

interface Call {
  url: string
  method: string
  body: unknown
}

interface Server {
  target: CuaTarget | null
  requestedBy: 'user' | 'agent' | null
  activeWindow: CuaActiveWindow | null
  scope: 'workspace' | 'machine'
  /** Cờ backend tính sẵn; `null` ⇒ bỏ hẳn khỏi payload để panel tự suy từ `scope`. */
  machineAllowed: boolean | null
  /** `true` ⇒ backend kiểm lại thấy cửa sổ đã chết: `effective: null`. */
  effectiveGone: boolean
  leaseHolder: 'agent' | 'human'
  /** `true` ⇒ máy KHÔNG báo cáo quyền điều khiển (Linux: chưa có `DesktopControl`). */
  leaseUnknown: boolean
  revision: number
  windows: HostWindowEntry[]
  windowsFailure: { error: string; code: string; status: number } | null
  inspectFailure: { error: string; code: string; status: number } | null
  calls: Call[]
  captureRequests: { consent: boolean; kind: string; windowId?: string | number }[]
  /** Lượt chụp đang bị treo (ca "huỷ") — test tự quyết định khi nào trả về. */
  heldCapture: { resolve: (value: Response) => void } | null
  /**
   * Lượt ĐỌC ĐÍCH đang bị treo. Ảnh chụp trạng thái được lấy NGAY LÚC GỌI, nên
   * khi test thả nó ra sau một `PUT`, nó về với trạng thái CŨ (đúng ca thật:
   * `fetch` không huỷ được một response đang bay).
   */
  heldTargetGet: { resolve: () => void } | null
}

let server: Server
let roots: Root[] = []

function makeServer(overrides: Partial<Server> = {}): Server {
  return {
    target: null,
    requestedBy: null,
    activeWindow: null,
    scope: 'machine',
    machineAllowed: null,
    effectiveGone: false,
    leaseHolder: 'agent',
    leaseUnknown: false,
    revision: 3,
    windows: [
      { windowId: 12, zOrder: 0, title: 'a.txt - Notepad', windowClass: 'Notepad', pid: 4, processName: 'notepad.exe', position: { x: 0, y: 0 }, size: { width: 800, height: 600 }, dpi: 96 },
      { windowId: 99, zOrder: 1, title: 'BoxFox — Google Chrome', windowClass: 'Chrome_WidgetWin_1', pid: 8, processName: 'chrome.exe', position: { x: 900, y: 0 }, size: { width: 1280, height: 800 }, dpi: 96 },
    ],
    windowsFailure: null,
    inspectFailure: null,
    calls: [],
    captureRequests: [],
    heldCapture: null,
    heldTargetGet: null,
    ...overrides,
  }
}

function json(body: unknown, init?: { ok?: boolean; status?: number }): Response {
  return { ok: init?.ok ?? true, status: init?.status ?? 200, json: async () => body } as Response
}

function leaseBody() {
  return {
    holder: server.leaseHolder,
    epoch: 4,
    generation: 2,
    hooksInstalled: true,
    mutexHeld: false,
    mutexName: null,
    since: null,
    reason: 'test',
  }
}

function targetStateBody() {
  return {
    sessionId: SESSION_ID,
    target: server.target,
    requestedBy: server.requestedBy,
    effective: server.effectiveGone ? null : server.target,
    effectiveReason: server.effectiveGone ? 'window_gone' : null,
    activeWindow: server.activeWindow,
    scope: server.scope,
    ...(server.machineAllowed === null ? {} : { machineAllowed: server.machineAllowed }),
    cuaEnabled: true,
    revision: server.revision,
    activity: null,
  }
}

function snapshotBody(kind: string, windowId?: string | number) {
  return kind === 'machine'
    ? { image: 'MACHINE', mime: 'image/png', width: 1920, height: 1080, hash: 'hash-machine', snapshotId: 'snap-m', untrusted: true, captureOrigin: { x: 0, y: 0 }, captureSize: { width: 1920, height: 1080 } }
    : { image: `WINDOW-${windowId}`, mime: 'image/png', width: 800, height: 600, hash: `hash-window-${windowId}`, snapshotId: `snap-w-${windowId}`, untrusted: true, captureOrigin: { x: -100, y: 20 }, captureSize: { width: 800, height: 600 } }
}

function uiaPayload() {
  return {
    type: 'uia',
    name: 'Tệp',
    controlType: 'menu item',
    automationId: 'FileMenu',
    className: 'MenuItem',
    helpText: '',
    isEnabled: true,
    isOffscreen: false,
    isPassword: false,
    bounds: { screenBox: { x: 118, y: 96, width: 42, height: 22 }, dpi: 120 },
    patterns: ['Invoke'],
    windowId: '12',
    pid: 4,
    processName: 'notepad.exe',
    elementToken: 'tok-1',
    generation: 1,
    sourceId: 'src-1',
    frameId: 'f-1',
    geometryRevision: 7,
    label: { integrity: 'khong_tin_duoc', confidentiality: 'noi_bo', source_kind: 'screen_capture', source_uri: 'screen://element/12', tool_name: 'inspect_element', content_hash: 'x' },
  }
}

function installFetch() {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? 'GET'
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined
    server.calls.push({ url, method, body })

    if (url === '/api/agent/health') {
      return json({
        execution: {
          mode: 'host',
          modeDefault: 'host',
          modes: ['host'],
          configured: 'host',
          scope: server.scope,
          permissionMode: 'ask',
          policy: true,
          cuaEnabled: true,
          lease: server.leaseUnknown ? null : leaseBody(),
          hardlineHits: 0,
          workspace: null,
        },
      })
    }

    if (url === '/api/agent/machines/screen' && method === 'GET') {
      if (server.windowsFailure) {
        return json({ error: server.windowsFailure.error, code: server.windowsFailure.code }, { ok: false, status: server.windowsFailure.status })
      }
      return json({ windows: server.windows })
    }

    if (url.startsWith('/api/agent/machines/target')) {
      if (method === 'GET') {
        if (server.heldTargetGet) {
          const stale = json(targetStateBody())
          return new Promise<Response>((resolve) => {
            server.heldTargetGet = { resolve: () => resolve(stale) }
          })
        }
        return json(targetStateBody())
      }
      if (method === 'PUT') {
        server.target = body?.kind === 'machine' ? { kind: 'machine' } : { kind: 'window', windowId: body?.windowId as string | number, pid: body?.pid as number | undefined }
        server.requestedBy = 'user'
        server.revision += 1
        return json(targetStateBody())
      }
      if (method === 'DELETE') {
        server.target = null
        server.requestedBy = null
        server.activeWindow = null
        server.revision += 1
        return json(targetStateBody())
      }
    }

    if (url === '/api/agent/machines/screen' && method === 'POST') {
      const kind = String(body?.kind ?? 'machine')
      const windowId = body?.windowId as string | number | undefined
      server.captureRequests.push({ consent: Boolean(body?.consent), kind, windowId })
      if (server.heldCapture) {
        // Treo lượt chụp này lại: `fetch` KHÔNG tôn trọng `signal` (đúng thực tế
        // — một response đang bay vẫn về), nên chỉ epoch guard cứu được.
        return new Promise<Response>((resolve) => {
          server.heldCapture = { resolve }
        })
      }
      return json(snapshotBody(kind, windowId))
    }

    if (url === '/api/agent/desktop/inspect-element') {
      if (server.inspectFailure) {
        return json({ error: server.inspectFailure.error, code: server.inspectFailure.code }, { ok: false, status: server.inspectFailure.status })
      }
      return json(uiaPayload())
    }

    if (url === '/api/agent/desktop/lease') {
      if (server.leaseUnknown) {
        return json({ error: 'desktop control chưa bật', code: 'CUA_UNAVAILABLE' }, { ok: false, status: 409 })
      }
      if (body?.action === 'claim') server.leaseHolder = 'agent'
      return json(leaseBody())
    }

    throw new Error(`Máy chủ giả không biết đường này: ${method} ${url}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

async function settle(rounds = 8) {
  await act(async () => {
    for (let i = 0; i < rounds; i += 1) await Promise.resolve()
  })
}

interface Harness {
  host: HTMLElement
  text: () => string
  query: <T extends Element = Element>(selector: string) => T | null
  testId: <T extends Element = Element>(id: string) => T | null
  click: (selector: string) => void
  unmount: () => void
}

function renderPanel(): Harness {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(
      <I18nProvider>
        <HostMachineScreen />
      </I18nProvider>,
    )
  })
  return {
    host,
    text: () => host.textContent ?? '',
    query: (selector) => host.querySelector(selector),
    testId: (id) => host.querySelector(`[data-testid="${id}"]`),
    click: (selector) => {
      const node = host.querySelector(selector)
      if (!node) throw new Error(`Không thấy ${selector}`)
      act(() => {
        node.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
    },
    unmount: () => act(() => root.unmount()),
  }
}

/**
 * Mở menu chọn đích trên THANH TIÊU ĐỀ. Danh sách cửa sổ không còn nằm thường
 * trực trong thân panel — nó nằm trong menu này, nên mọi ca muốn bấm vào một lựa
 * chọn đều phải mở menu trước.
 */
function openPicker(panel: Harness) {
  if (panel.testId('ms-picker-popover')) return
  panel.click('[data-testid="ms-change-target"]')
}

/** Chọn một cửa sổ rồi để panel chụp xong — dùng chung cho nhiều ca. */
async function pickWindow(panel: Harness, windowId: string | number = 12) {
  openPicker(panel)
  panel.click(`[data-testid="ms-window-option-${windowId}"]`)
  await settle()
}

beforeEach(() => {
  vi.useFakeTimers()
  server = makeServer()
  installFetch()
  useAgentStore.setState({ activeSessionId: SESSION_ID })
  useComposerStore.setState({ pendingElements: [] })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('chưa có đích', () => {
  it('hiện lời dẫn + danh sách cửa sổ, và "Làm mới" đọc lại danh sách', async () => {
    const panel = renderPanel()
    await settle()

    expect(panel.text()).toContain('Machine screen')
    expect(panel.text()).toContain('Pick the window you want the agent to work in')
    // Bộ chọn nằm trong menu của thanh tiêu đề: chưa mở thì chưa có lựa chọn nào.
    expect(panel.testId('ms-target-picker')).toBeNull()
    openPicker(panel)
    expect(panel.testId('ms-target-picker')).not.toBeNull()
    expect(panel.testId('ms-target-machine')).not.toBeNull()
    expect(panel.testId('ms-window-option-12')).not.toBeNull()
    expect(panel.testId('ms-window-option-99')).not.toBeNull()
    // Chưa có đích ⇒ chưa có ảnh, và nói rõ vì sao.
    expect(panel.testId('ms-snapshot-frame')).toBeNull()
    expect(panel.text()).toContain('No live image yet')

    const before = server.calls.filter((call) => call.url === '/api/agent/machines/screen' && call.method === 'GET').length
    panel.click('[data-testid="ms-window-list-refresh"]')
    await settle()
    const after = server.calls.filter((call) => call.url === '/api/agent/machines/screen' && call.method === 'GET').length
    expect(after).toBe(before + 1)
  })

  it('danh sách rỗng ⇒ câu "chưa mở cửa sổ nào", không phải lỗi', async () => {
    server = makeServer({ windows: [] })
    installFetch()
    const panel = renderPanel()
    await settle()
    openPicker(panel)
    expect(panel.testId('ms-window-list-empty')).not.toBeNull()
    expect(panel.testId('ms-window-list-error')).toBeNull()
  })

  it('nền tảng không có danh sách cửa sổ (Linux) ⇒ câu giải thích, không phải đống lỗi đỏ', async () => {
    server = makeServer({ windowsFailure: { error: 'no window list on this platform', code: 'HOST_SCREEN_UNAVAILABLE', status: 409 } })
    installFetch()
    const panel = renderPanel()
    await settle()
    openPicker(panel)

    const block = panel.testId('ms-window-list-unsupported')
    expect(block).not.toBeNull()
    expect(block?.textContent).toContain('Windows-only')
    // Không phô mã máy cho người dùng, và không có khối lỗi.
    expect(panel.text()).not.toContain('HOST_SCREEN_UNAVAILABLE')
    expect(panel.testId('ms-window-list-error')).toBeNull()
    // "Cả máy" vẫn là lựa chọn thật trên nền tảng này.
    expect(panel.text()).toContain('Whole machine')
    expect(panel.testId('ms-target-machine')?.hasAttribute('disabled')).toBe(false)
  })
})

describe('chọn đích', () => {
  it('chọn một cửa sổ ⇒ PUT đúng body, rồi tải ảnh của đúng cửa sổ đó', async () => {
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)

    const put = server.calls.find((call) => call.method === 'PUT')
    expect(put?.url).toBe('/api/agent/machines/target')
    expect(put?.body).toEqual({ sessionId: SESSION_ID, kind: 'window', windowId: 12, pid: 4, consent: true, expectedRevision: 3 })

    expect(server.captureRequests).toEqual([{ consent: true, kind: 'window', windowId: 12 }])
    const img = panel.testId<HTMLImageElement>('ms-snapshot-frame')?.querySelector('img')
    expect(img?.getAttribute('src')).toBe('data:image/png;base64,WINDOW-12')
    expect(panel.text()).toContain('a.txt - Notepad')
    expect(panel.text()).toContain('notepad.exe · windowId 12')
    expect(panel.testId('ms-target-identity')).not.toBeNull()
  })

  it('chọn "Cả máy" ⇒ PUT {kind: machine} + chụp toàn màn hình', async () => {
    const panel = renderPanel()
    await settle()
    openPicker(panel)
    panel.click('[data-testid="ms-target-machine"]')
    await settle()

    const put = server.calls.find((call) => call.method === 'PUT')
    expect(put?.body).toEqual({ sessionId: SESSION_ID, kind: 'machine', consent: true, expectedRevision: 3 })
    expect(server.captureRequests).toEqual([{ consent: true, kind: 'machine', windowId: undefined }])
    expect(panel.testId<HTMLImageElement>('ms-snapshot-frame')?.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,MACHINE')
  })

  it('phạm vi quyền `workspace` ⇒ "Cả máy" bị khoá kèm lý do, và KHÔNG gọi PUT', async () => {
    server = makeServer({ scope: 'workspace' })
    installFetch()
    const panel = renderPanel()
    await settle()
    openPicker(panel)

    const machine = panel.testId<HTMLButtonElement>('ms-target-machine')
    expect(machine?.disabled).toBe(true)
    expect(machine?.getAttribute('aria-disabled')).toBe('true')
    expect(panel.text()).toContain('Needs the Whole machine permission scope.')
    expect(panel.testId('ms-open-permissions')).not.toBeNull()

    // Bấm vào nút bị khoá: React bỏ qua cú bấm trên form control disabled.
    panel.click('[data-testid="ms-target-machine"]')
    await settle()
    expect(server.calls.some((call) => call.method === 'PUT')).toBe(false)
  })

  it('`machineAllowed` của backend thắng `/health`: cho phép thì mở, cấm thì khoá', async () => {
    // `/health` nói `workspace` nhưng đích của phiên nói cả máy được phép.
    server = makeServer({ scope: 'workspace', machineAllowed: true })
    installFetch()
    let panel = renderPanel()
    await settle()
    openPicker(panel)
    expect(panel.testId<HTMLButtonElement>('ms-target-machine')?.disabled).toBe(false)
    panel.unmount()

    // Chiều ngược lại: quyền đã là `machine` nhưng phiên vẫn cấm cả máy.
    server = makeServer({ scope: 'machine', machineAllowed: false })
    panel = renderPanel()
    await settle()
    openPicker(panel)
    const machine = panel.testId<HTMLButtonElement>('ms-target-machine')
    expect(machine?.disabled).toBe(true)
    expect(panel.text()).toContain('Needs the Whole machine permission scope.')
    expect(panel.testId('ms-open-permissions')).not.toBeNull()
  })

  it('backend kiểm lại thấy cửa sổ đã chết (`effective: null`) ⇒ xoá ảnh cũ, báo chọn lại, ngừng chụp', async () => {
    const panel = renderPanel()
    await settle()
    await pickWindow(panel)
    expect(panel.testId<HTMLImageElement>('ms-snapshot-frame')?.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,WINDOW-12')

    // Cửa sổ bị đóng (hoặc hwnd bị tiến trình khác dùng lại): backend nói đích đã mất.
    server.effectiveGone = true
    const capturesBefore = server.captureRequests.length
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    await settle()

    // Ảnh của cửa sổ đã chết KHÔNG được giữ lại trên màn hình.
    expect(panel.testId('ms-snapshot-frame')).toBeNull()
    expect(panel.text()).not.toContain('WINDOW-12')
    expect(panel.text()).toContain('The target window is gone — pick again.')
    // Và nhịp sau không thử chụp lại cửa sổ đã chết nữa.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    await settle()
    expect(server.captureRequests.length).toBe(capturesBefore)
  })

  it('lượt đọc đích về muộn KHÔNG kéo panel lùi về trạng thái cũ (revision đơn điệu)', async () => {
    const panel = renderPanel()
    await settle()

    // Nhịp poll bị treo ở tầng mạng, mang trạng thái CŨ (chưa có đích, revision 3).
    server.heldTargetGet = { resolve: () => {} }
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    await settle()

    // Trong lúc nó đang bay, người dùng chọn cửa sổ 12 ⇒ PUT áp revision 4.
    await pickWindow(panel, 12)
    expect(server.revision).toBe(4)
    expect(panel.testId('ms-target-identity')?.textContent).toContain('a.txt - Notepad')

    // Lượt đọc cũ về muộn: phải bị bỏ qua, không được vẽ đè.
    server.heldTargetGet?.resolve()
    server.heldTargetGet = null
    await settle()

    expect(panel.testId('ms-target-identity')?.textContent).toContain('a.txt - Notepad')
    expect(panel.text()).not.toContain('No target yet')

    // Và revision KHÔNG lùi: lượt PUT sau vẫn gửi số mới (4), không phải 3.
    await pickWindow(panel, 99)
    const put = [...server.calls].reverse().find((call) => call.method === 'PUT')
    expect((put?.body as { expectedRevision?: number } | undefined)?.expectedRevision).toBe(4)
  })

  it('chưa có phiên ⇒ không gọi route đích, hiện trạng thái rỗng trung tính', async () => {
    useAgentStore.setState({ activeSessionId: '' })
    server = makeServer()
    installFetch()
    const panel = renderPanel()
    await settle()
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4000)
    })
    await settle()

    expect(server.calls.some((call) => call.url.startsWith('/api/agent/machines/target'))).toBe(false)
    expect(panel.testId('ms-no-session')).not.toBeNull()
    expect(panel.text()).toContain('No session open yet')
    expect(panel.text()).not.toContain('Session not found')
    // Bộ chọn đích vẫn mở được, nhưng không nhận cú bấm (PUT với `sessionId` rỗng là 404).
    openPicker(panel)
    expect(panel.testId('ms-target-picker')).not.toBeNull()
    expect(panel.testId<HTMLButtonElement>('ms-target-machine')?.disabled).toBe(true)
    expect(panel.testId<HTMLButtonElement>('ms-window-option-12')?.disabled).toBe(true)
  })

  it('cửa sổ đang hoạt động nằm NGOÀI vùng chụp ⇒ không vẽ viền nào', async () => {
    server = makeServer({
      target: { kind: 'machine' },
      activeWindow: { windowId: 5, title: 'Off-screen', rect: { x: 5000, y: 5000, width: 100, height: 100 } },
    })
    installFetch()
    const panel = renderPanel()
    await settle()

    // Ảnh 1920 × 1080, cửa sổ ở (5000, 5000) ⇒ không có phần nào nhìn thấy được.
    expect(panel.testId('ms-snapshot-frame')).not.toBeNull()
    expect(panel.testId('ms-target-overlay')).toBeNull()
  })

  it('lỗi đặt đích ⇒ câu dịch theo MÃ MÁY, không phải chuỗi thô', async () => {
    server = makeServer({ windowsFailure: null })
    installFetch()
    const panel = renderPanel()
    await settle()

    // Cửa sổ vừa biến mất giữa hai nhịp đọc.
    const original = globalThis.fetch
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url === '/api/agent/machines/target' && (init?.method ?? 'GET') === 'PUT') {
          return json({ error: 'window is gone', code: 'TARGET_UNKNOWN' }, { ok: false, status: 409 })
        }
        return original(url, init)
      }),
    )
    await pickWindow(panel, 99)
    expect(panel.text()).toContain('The target window is gone — pick again.')
  })
})

describe('theo agent', () => {
  it('đích đổi ở backend ⇒ panel đổi theo, nói rõ ai vừa đổi, và chụp lại', async () => {
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)
    expect(server.captureRequests).toHaveLength(1)

    // Agent tự xin cửa sổ Chrome (đổi ở backend, panel chưa biết).
    server.target = { kind: 'window', windowId: 99, pid: 8, title: 'BoxFox — Google Chrome', processName: 'chrome.exe' }
    server.requestedBy = 'agent'
    server.revision += 1

    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    await settle()

    expect(panel.text()).toContain('BoxFox — Google Chrome')
    expect(panel.text()).toContain('The agent switched to this window.')
    expect(server.captureRequests).toHaveLength(2)
    expect(server.captureRequests[1]).toEqual({ consent: true, kind: 'window', windowId: 99 })
    expect(panel.testId<HTMLImageElement>('ms-snapshot-frame')?.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,WINDOW-99')
  })

  it('nhịp poll 2 giây tự đọc lại đích (không cần focus)', async () => {
    const panel = renderPanel()
    await settle()
    const before = server.calls.filter((call) => call.url.startsWith('/api/agent/machines/target') && call.method === 'GET').length

    server.target = { kind: 'machine' }
    server.requestedBy = 'agent'
    server.revision += 1

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000)
    })
    await settle()

    const after = server.calls.filter((call) => call.url.startsWith('/api/agent/machines/target') && call.method === 'GET').length
    expect(after).toBeGreaterThan(before)
    // Nhãn đích nằm trên NÚT CHỌN ở thanh tiêu đề, không còn là chip riêng.
    expect(panel.testId('ms-change-target')?.textContent).toContain('Whole machine')
  })

  it('lượt chụp của đích CŨ về muộn ⇒ không được vẽ đè ảnh mới (epoch guard)', async () => {
    const panel = renderPanel()
    await settle()

    // Lượt chụp cho cửa sổ 12 bị treo ở tầng mạng.
    server.heldCapture = { resolve: () => {} }
    openPicker(panel)
    panel.click('[data-testid="ms-window-option-12"]')
    await settle()
    expect(panel.testId('ms-snapshot-frame')).toBeNull()

    // Đang treo thì agent đổi sang cả máy ⇒ panel chụp lại (lượt này về ngay).
    const held = server.heldCapture
    server.heldCapture = null
    server.target = { kind: 'machine' }
    server.requestedBy = 'agent'
    server.revision += 1
    act(() => {
      window.dispatchEvent(new Event('focus'))
    })
    await settle()
    expect(panel.testId<HTMLImageElement>('ms-snapshot-frame')?.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,MACHINE')

    // Giờ response cũ mới về — ảnh cũ TUYỆT ĐỐI không được paint.
    await act(async () => {
      held?.resolve(json(snapshotBody('window', 12)))
      await Promise.resolve()
    })
    await settle()
    expect(panel.testId<HTMLImageElement>('ms-snapshot-frame')?.querySelector('img')?.getAttribute('src')).toBe('data:image/png;base64,MACHINE')
    expect(panel.text()).not.toContain('WINDOW-12')
  })
})

describe('thu hồi đích', () => {
  it('DELETE, xoá ảnh, đóng ngăn kéo, quay về màn chọn đích', async () => {
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)

    // Soi một phần tử để có ngăn kéo mở.
    panel.click('[data-testid="ms-select-element"]')
    await settle()
    const catcher = panel.testId('ms-inspect-catcher')
    act(() => {
      catcher?.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 300, clientY: 200 }))
    })
    await settle()
    expect(panel.testId('inspector-drawer')).not.toBeNull()

    panel.click('[data-testid="ms-revoke"]')
    await settle()

    const del = server.calls.find((call) => call.method === 'DELETE')
    expect(del?.url).toBe(`/api/agent/machines/target?sessionId=${SESSION_ID}`)
    expect(panel.testId('ms-snapshot-frame')).toBeNull()
    expect(panel.testId('inspector-drawer')).toBeNull()
    expect(panel.text()).toContain('No target yet')
    expect(panel.text()).toContain('No live image yet')
  })
})

describe('lớp phủ viền xanh', () => {
  it('đích là cửa sổ ⇒ viền ôm trọn ảnh (inset), aria-hidden, có lớp reduced-motion', async () => {
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)

    const overlay = panel.testId('ms-target-overlay')
    expect(overlay).not.toBeNull()
    expect(overlay?.getAttribute('aria-hidden')).toBe('true')
    expect(overlay?.getAttribute('style') ?? '').toContain('inset')
    // Khoá hồi quy: tắt chuyển động thì viền đứng yên nhưng vẫn sáng.
    expect(overlay?.className).toContain('motion-reduce:animate-none')
    expect(overlay?.className).toContain('pointer-events-none')
    expect(panel.text()).toContain('Blue border = the area the agent drives')
  })

  it('đích cả máy + activeWindow ⇒ viền theo đúng tỉ lệ ảnh (đã trừ captureOrigin)', async () => {
    server = makeServer({
      target: { kind: 'machine' },
      requestedBy: 'user',
      activeWindow: { windowId: 99, pid: 8, title: 'Chrome', processName: 'chrome.exe', rect: { x: 200, y: 100, width: 400, height: 200 } },
    })
    installFetch()
    const panel = renderPanel()
    await settle()

    const overlay = panel.testId('ms-target-overlay')
    expect(overlay).not.toBeNull()
    // Ảnh 1920×1080 nằm trong khung 400×300 ⇒ tỉ lệ 5/24; captureOrigin (0,0).
    // left = 200 × 400/1920 = 41.67 → '41.6667px'… chỉ cần đúng tỉ lệ, không
    // phải đúng pixel, nên so bằng số.
    const style = (overlay as HTMLElement).style
    expect(Number.parseFloat(style.left)).toBeCloseTo((200 * 400) / 1920, 3)
    expect(Number.parseFloat(style.top)).toBeCloseTo((100 * 300) / 1080, 3)
    expect(Number.parseFloat(style.width)).toBeCloseTo((400 * 400) / 1920, 3)
    expect(Number.parseFloat(style.height)).toBeCloseTo((200 * 300) / 1080, 3)
  })

  it('đích cả máy mà chưa biết cửa sổ nào ⇒ KHÔNG vẽ viền, chỉ nói bằng chữ', async () => {
    server = makeServer({ target: { kind: 'machine' }, requestedBy: 'user', activeWindow: null })
    installFetch()
    const panel = renderPanel()
    await settle()
    expect(panel.testId('ms-target-overlay')).toBeNull()
    expect(panel.text()).toContain('not known yet')
  })
})

describe('chọn phần tử', () => {
  it('lên nòng rồi bấm điểm ⇒ POST toạ độ framebuffer, thẻ UIA, và "Thêm vào hội thoại"', async () => {
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)

    const select = panel.testId<HTMLButtonElement>('ms-select-element')
    expect(select?.disabled).toBe(false)
    panel.click('[data-testid="ms-select-element"]')
    await settle()
    expect(select?.getAttribute('aria-pressed')).toBe('true')
    expect(panel.text()).toContain('nothing is sent to the machine')

    // clientX/Y giữa ảnh: rect (100,50) + 200×150 CSS ⇒ 400×300 pixel ảnh
    // ⇒ cộng captureOrigin (-100, 20) ⇒ (300, 320).
    act(() => {
      panel.testId('ms-inspect-catcher')?.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 300, clientY: 200 }))
    })
    await settle()

    const inspect = server.calls.find((call) => call.url === '/api/agent/desktop/inspect-element')
    expect(inspect?.body).toEqual({ x: 300, y: 320 })

    // Ngăn kéo hiện thẻ UIA, và chế độ chọn tự tắt sau cú bấm (Q5).
    expect(panel.testId('inspector-drawer')).not.toBeNull()
    expect(panel.text()).toContain('UIA Element')
    expect(panel.text()).toContain('Tệp')
    expect(panel.testId('ms-inspect-catcher')).toBeNull()
    // Khung sáng phần tử nằm đúng chỗ trong khung ảnh.
    expect(panel.testId('ms-element-highlight')).not.toBeNull()

    const add = [...panel.host.querySelectorAll('button')].find((button) => button.textContent === 'Add to Chat')
    act(() => {
      add?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await settle()

    const pending = useComposerStore.getState().pendingElements
    expect(pending).toHaveLength(1)
    expect(pending[0].point).toEqual({ x: 300, y: 320 })
    expect(pending[0].result).toMatchObject({ type: 'uia', name: 'Tệp' })
    // Ngăn kéo đóng lại sau khi thêm — chip nằm ở khung soạn tin, không ở đây.
    expect(panel.testId('inspector-drawer')).toBeNull()
  })

  it('máy không báo cáo quyền điều khiển ⇒ băng trạng thái trung tính, không nhận vơ là "bạn"', async () => {
    // Linux chưa có `DesktopControl`: `/health` trả `lease: null` và route lease 409. Panel KHÔNG được
    // nói "Bạn đang giữ quyền" (trong khi phần chú thích lại nói agent đang làm việc) — hai câu đó
    // mâu thuẫn nhau, và người dùng đọc câu đầu.
    server = makeServer({ leaseUnknown: true })
    installFetch()
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)

    expect(panel.text()).toContain('Control not reported')
    expect(panel.text()).not.toContain('You hold control')
    expect(panel.text()).not.toContain('Agent is working')
    expect(panel.text()).toContain('This machine does not report who holds control')
    // Không có quyền nào để trả, nên nút trả quyền không được mời.
    expect(panel.testId('ms-lease-claim')).toBeNull()
  })

  it('người dùng đang giữ quyền ⇒ nút chọn bị khoá + đường trả quyền ngay tại chỗ', async () => {
    server = makeServer({ leaseHolder: 'human' })
    installFetch()
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)

    const select = panel.testId<HTMLButtonElement>('ms-select-element')
    expect(select?.disabled).toBe(true)
    expect(select?.getAttribute('title')).toBe('Hand control back to the agent before selecting an element.')
    expect(panel.text()).toContain('You hold control')

    panel.click('[data-testid="ms-lease-claim"]')
    await settle()

    const leaseCall = server.calls.find((call) => call.url === '/api/agent/desktop/lease')
    expect(leaseCall?.body).toEqual({ action: 'claim' })
    // Trả xong ⇒ mở khoá được nút chọn.
    expect(panel.testId<HTMLButtonElement>('ms-select-element')?.disabled).toBe(false)
    expect(panel.text()).toContain('Agent is working')
  })

  it('ELEMENT_STALE ⇒ ngăn kéo dịch theo mã máy và có nút Thử lại', async () => {
    const panel = renderPanel()
    await settle()
    await pickWindow(panel, 12)

    server.inspectFailure = { error: 'element is stale', code: 'ELEMENT_STALE', status: 409 }
    panel.click('[data-testid="ms-select-element"]')
    await settle()
    act(() => {
      panel.testId('ms-inspect-catcher')?.dispatchEvent(new MouseEvent('pointerdown', { bubbles: true, clientX: 300, clientY: 200 }))
    })
    await settle()

    expect(panel.text()).toContain('The element is stale for this capture')
    expect(panel.text()).not.toContain('ELEMENT_STALE: element is stale')

    // "Thử lại" gọi lại đúng điểm vừa lỗi, và lần này thành công.
    server.inspectFailure = null
    const retry = [...panel.host.querySelectorAll('button')].find((button) => button.textContent === 'Retry')
    act(() => {
      retry?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    await settle()
    expect(panel.text()).toContain('Tệp')
    expect(server.calls.filter((call) => call.url === '/api/agent/desktop/inspect-element')).toHaveLength(2)
  })
})
