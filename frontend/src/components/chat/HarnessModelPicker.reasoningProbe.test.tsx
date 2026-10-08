/**
 * Nhóm M — hàng model trong bảng chọn phải trả lời được "vì sao model này không có bộ chọn mức",
 * và phải có cách ĐO ngay tại chỗ.
 *
 * Lỗi gốc (chủ sở hữu báo): "chưa hiện thinking với model mới". Chuỗi nhân quả đo được: hàng model
 * của router để `thinkingSource: 'unknown'`/`thinkingType: 'none'` cho 44/48 model, harness đọc
 * hàng đó rồi BỎ mức thinking khi dựng request, nên provider không sinh suy luận và UI không có gì
 * để hiện. Bộ chọn mức chỉ hiện khi model công bố > 1 mức — nên với model mới, người dùng chỉ thấy
 * một điều khiển biến mất mà không có gì giải thích.
 *
 * Hợp đồng được khoá ở đây:
 * 1. Hàng chưa đo ⇒ dòng phụ nói `thinking: not measured` + nút `Measure thinking`.
 * 2. Bấm nút ⇒ POST `/api/router/connections/:id/models/:modelId/reasoning-probe` với cổng admin.
 * 3. Đo xong ⇒ nạp lại snapshot, và nếu đo được > 1 mức thì bộ chọn mức HIỆN (phép kiểm đầu-cuối).
 * 4. Hàng NHÓM dò MỌI connection định tuyến được: `thinkingLevels` của hàng nhóm là GIAO của các
 *    connection, nên dò một cái thì bộ chọn vẫn không hiện.
 * 5. Số đo cũ (`thinkingStale`) ⇒ nút hiện lại, dòng phụ nói rõ là số cũ.
 *
 * Render qua raw `createRoot` + `act` (dự án không dùng @testing-library). Popover nằm trong một
 * portal ở `document.body`, nên truy vấn phải hỏi `document`, không phải `host`.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useHarnessStore } from '../../store/harnessStore'
import { useProviderStore } from '../../store/providerStore'
import type { ProviderSnapshot } from '../../types/provider'
import { HarnessModelPicker } from './HarnessModelPicker'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const MODEL = 'fledge-alpha-free'
const PROVIDER_ROW = `provider:opencode:${MODEL}`

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

function click(el: Element | null | undefined) {
  if (!el) throw new Error('Không tìm thấy phần tử để bấm')
  act(() => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function byId(id: string): HTMLElement | null {
  return document.querySelector(`[data-component-id="${id}"]`)
}

/** Hàng cha của model — bỏ qua nút mở nhánh ghim (id bắt đầu bằng `model-row-`). */
function modelRows(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>('[data-component-id^="model-row-"]'))
    .filter((el) => !(el.getAttribute('data-component-id') ?? '').startsWith('model-row-pin-toggle-'))
}

/** Mở popover rồi sang tab Single Models. */
function openModels(host: HTMLElement) {
  const trigger = Array.from(host.querySelectorAll('button'))
    .find((b) => (b.getAttribute('title') ?? '').startsWith('Model:'))
  click(trigger)
  const modelsTab = Array.from(document.querySelectorAll('button'))
    .find((b) => (b.textContent ?? '').trim().endsWith('Single Models'))
  click(modelsTab)
}

const model = (id: string, overrides: Record<string, unknown> = {}) => ({
  id, name: id, source: 'live', stale: false, contextWindow: 1_000_000,
  contextWindowSource: 'reported', thinkingType: 'none', defaultThinking: null, thinkingLevels: [],
  thinkingSource: 'unknown', thinkingAsOf: null, thinkingEvidence: null,
  capabilities: {}, enabled: true, health: 'healthy',
  ...overrides,
})

const connection = (id: string, name: string, models: Array<ReturnType<typeof model>>) => ({
  id, providerId: 'opencode', name, endpoint: 'https://example.test',
  enabled: true, authState: 'ready', projectState: 'not_applicable',
  discoveryState: 'ready', inferenceState: 'ready', credentialPresent: true,
  email: null, accountLabel: null, projectId: null, revision: 1, autoSync: true,
  lastModelTestedAt: null, lastModelSyncAt: null, nextModelSyncAt: null, quota: null,
  error: null, models,
  keys: [{ id: `${id}-key1`, label: 'key 1', prefix: 'sk-', state: 'ready' }],
})

const snapshotWith = (connections: Array<ReturnType<typeof connection>>): ProviderSnapshot => ({
  providers: [{ id: 'opencode', name: 'OpenCode Free' }],
  connections,
  providerConfigs: [],
  aliases: [],
  defaultRoute: null,
  keys: [],
  usage: [],
  health: { status: 'ok', version: '0.1.0' },
}) as unknown as ProviderSnapshot

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status,
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Router giả: `POST …/reasoning-probe` trả kết quả và GHI số đo vào snapshot (đúng như router
 * thật ghi vào hàng model), `GET /api/router/state` trả snapshot hiện tại. Mọi request được ghi
 * lại để khoá đường dẫn + cổng admin.
 */
function routerStub(options: {
  probe?: (modelId: string) => { status: number; body: unknown }
  onProbe?: (modelId: string) => void
} = {}) {
  const calls: Array<{ url: string; method: string; headers: Record<string, string> }> = []
  let snapshot = snapshotWith([connection('c1', 'OpenCode Free (key 1)', [model(MODEL)])])
  const fetchMock = vi.fn(async (url: string, init: { method?: string; headers?: Record<string, string> } = {}) => {
    const target = String(url)
    calls.push({ url: target, method: init.method ?? 'GET', headers: init.headers ?? {} })
    if (target.includes('/reasoning-probe')) {
      const modelId = decodeURIComponent(target.split('/models/')[1].split('/')[0])
      options.onProbe?.(modelId)
      const verdict = options.probe?.(modelId) ?? { status: 200, body: { status: 'supports', thinkingLevels: ['minimal', 'low', 'medium', 'high'], samples: 5, reasoningChars: 412, reasoningTokens: 0 } }
      return json(verdict.body, verdict.status)
    }
    return json(snapshot)
  })
  return {
    calls,
    fetchMock,
    setSnapshot: (next: ProviderSnapshot) => { snapshot = next },
    connection: () => snapshot.connections[0],
  }
}

beforeEach(() => {
  useHarnessStore.getState().setActiveModel(PROVIDER_ROW)
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  useProviderStore.setState({ snapshot: null })
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('HarnessModelPicker — dò reasoning ngay tại hàng model', () => {
  it('hàng chưa đo nói ra vì sao không có bộ chọn mức, và bày nút đo', () => {
    useProviderStore.setState({ snapshot: snapshotWith([connection('c1', 'OpenCode Free (key 1)', [model(MODEL)])]) })
    const host = render(<HarnessModelPicker />)
    openModels(host)

    const row = modelRows()[0]
    expect(row.textContent).toContain('thinking: not measured')
    expect(byId(`thinking-probe-${PROVIDER_ROW}`)?.textContent).toContain('Measure thinking')
    expect(row.textContent).not.toContain('Thinking:')
  })

  it('bấm nút ⇒ POST đúng route với cổng admin, rồi bộ chọn mức HIỆN khi đo được 4 mức', async () => {
    const stub = routerStub({
      // Router thật ghi số đo vào hàng model; snapshot sau đó là thứ bộ chọn mức đọc.
      onProbe: () => stub.setSnapshot(snapshotWith([
        connection('c1', 'OpenCode Free (key 1)', [model(MODEL, {
          thinkingType: 'effort', thinkingLevels: ['minimal', 'low', 'medium', 'high'],
          thinkingSource: 'probe', thinkingAsOf: '2026-10-08', thinkingEvidence: 'probe 2026-10-08: 5/5 mẫu trả reasoning',
        })]),
      ])),
    })
    vi.stubGlobal('fetch', stub.fetchMock)
    useProviderStore.setState({ snapshot: snapshotWith([connection('c1', 'OpenCode Free (key 1)', [model(MODEL)])]) })
    const host = render(<HarnessModelPicker />)
    openModels(host)

    await act(async () => {
      byId(`thinking-probe-${PROVIDER_ROW}`)!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const probeCall = stub.calls.find((call) => call.url.includes('/reasoning-probe'))
    expect(probeCall?.url).toBe(`/api/router/connections/c1/models/${MODEL}/reasoning-probe`)
    expect(probeCall?.method).toBe('POST')
    expect(probeCall?.headers['X-BoxFox-Admin']).toBe('1')

    // Phép kiểm đầu-cuối của nhóm M: số đo xong ⇒ bộ chọn mức tự hiện, không cần F5.
    const row = modelRows()[0]
    expect(row.textContent).toContain('Thinking:')
    for (const level of ['minimal', 'low', 'medium', 'high']) {
      expect(row.textContent).toContain(level)
    }
    expect(row.textContent).toContain('thinking: probe 2026-10-08')
    expect(byId(`thinking-probe-${PROVIDER_ROW}`)).toBeNull()
    expect(byId(`thinking-probe-note-${PROVIDER_ROW}`)?.textContent).toContain('4 levels measured')
  })

  it('hàng NHÓM dò mọi connection định tuyến được — mức của hàng nhóm là GIAO của các connection', async () => {
    const stub = routerStub()
    vi.stubGlobal('fetch', stub.fetchMock)
    useProviderStore.setState({
      snapshot: snapshotWith([
        connection('c1', 'OpenCode Free (key 1)', [model(MODEL)]),
        connection('c2', 'OpenCode Free (key 2)', [model(MODEL)]),
      ]),
    })
    const host = render(<HarnessModelPicker />)
    openModels(host)

    await act(async () => {
      byId(`thinking-probe-${PROVIDER_ROW}`)!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const probed = stub.calls.filter((call) => call.url.includes('/reasoning-probe')).map((call) => call.url)
    expect(probed).toEqual([
      `/api/router/connections/c1/models/${MODEL}/reasoning-probe`,
      `/api/router/connections/c2/models/${MODEL}/reasoning-probe`,
    ])
  })

  it('số đo cũ (thinkingStale) ⇒ nút hiện lại và dòng phụ nói rõ là số cũ', () => {
    useProviderStore.setState({
      snapshot: snapshotWith([connection('c1', 'OpenCode Free (key 1)', [model(MODEL, {
        thinkingType: 'effort', thinkingLevels: ['minimal', 'low', 'medium', 'high'],
        thinkingSource: 'probe', thinkingAsOf: '2026-01-01', thinkingStale: true,
      })])]),
    })
    const host = render(<HarnessModelPicker />)
    openModels(host)

    const row = modelRows()[0]
    expect(row.textContent).toContain('thinking: probe 2026-01-01')
    expect(row.textContent).toContain('(old)')
    expect(byId(`thinking-probe-${PROVIDER_ROW}`)?.textContent).toContain('Measure thinking')
    // Bộ chọn mức vẫn còn: cờ "cũ" không được xoá một điều khiển đang chạy.
    expect(row.textContent).toContain('Thinking:')
  })

  it('router từ chối ⇒ câu trả lời nằm ở hàng đó, không ném ra ngoài và không đóng bảng chọn', async () => {
    const stub = routerStub({
      probe: () => ({ status: 403, body: { error: { code: 'FORBIDDEN', message: 'Admin header required.' } } }),
    })
    vi.stubGlobal('fetch', stub.fetchMock)
    useProviderStore.setState({ snapshot: snapshotWith([connection('c1', 'OpenCode Free (key 1)', [model(MODEL)])]) })
    const host = render(<HarnessModelPicker />)
    openModels(host)

    await act(async () => {
      byId(`thinking-probe-${PROVIDER_ROW}`)!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(byId(`thinking-probe-note-${PROVIDER_ROW}`)?.textContent).toContain('Admin header required.')
    expect(modelRows()).toHaveLength(1)
    expect(byId(`thinking-probe-${PROVIDER_ROW}`)?.textContent).toContain('Measure thinking')
  })

  it('kết quả lỗi hạ tầng được nói đúng trạng thái, không thành lời hứa', async () => {
    const stub = routerStub({ probe: () => ({ status: 200, body: { status: 'rate_limited', samples: 1, retryAfterMs: 60000 } }) })
    vi.stubGlobal('fetch', stub.fetchMock)
    useProviderStore.setState({ snapshot: snapshotWith([connection('c1', 'OpenCode Free (key 1)', [model(MODEL)])]) })
    const host = render(<HarnessModelPicker />)
    openModels(host)

    await act(async () => {
      byId(`thinking-probe-${PROVIDER_ROW}`)!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(byId(`thinking-probe-note-${PROVIDER_ROW}`)?.textContent).toContain('rate limited')
    expect(byId(`thinking-facts-${PROVIDER_ROW}`)?.textContent).toContain('not measured')
  })
})
