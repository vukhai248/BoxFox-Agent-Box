/**
 * W12.MODEL.METADATA — T4 phía UI.
 *
 * Ba hợp đồng được ghim ở đây, đúng thứ người dùng nhìn thấy:
 *  1. Mức thinking hiện ra là mức MODEL công bố (metadata đọc từ provider), không phải
 *     mức mặc định toàn cục của harness; mức đã lưu mà model không công bố thì bị kéo
 *     về mức gần nhất ngay, trước khi lượt gửi đi.
 *  2. Chọn tay sống qua một lần làm mới snapshot — kể cả khi đang GHIM một connection
 *     (`model:<connectionId>:<modelId>` chỉ nằm trong `pins`), và cả khi lần làm mới
 *     mang thêm model mới rồi đổi `defaultRoute`.
 *  3. Model đang chọn biến mất khỏi inventory sau lần làm mới: UI rơi về `defaultRoute`
 *     (hoặc dòng đầu tiên còn dùng được), và `activeModelId` được ghi lại theo đích mới —
 *     không để nhãn trỏ vào một model không còn tồn tại.
 *
 * Render qua raw `createRoot` + `act`, đúng khuôn `ChatPanel.test.tsx` (dự án không dùng
 * @testing-library); mạng bị chặn bằng mock `agentApi`/`providerApi` như ở đó.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useHarnessStore } from '../../store/harnessStore'
import { useProviderStore } from '../../store/providerStore'
import { useRouterChatStore } from '../../store/routerChatStore'
import type { ProviderSnapshot } from '../../types/provider'
import { ChatPanel } from './ChatPanel'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { agentApiMock, providerApiMock } = vi.hoisted(() => ({
  agentApiMock: vi.fn(),
  providerApiMock: vi.fn(),
}))

// Chặn mọi truy cập mạng: mount `ChatPanel` là gọi provider snapshot + refresh phiên.
vi.mock('../../lib/agentApi', () => ({ agentApi: agentApiMock }))
vi.mock('../../lib/providerApi', () => ({
  api: providerApiMock,
  ProviderApiError: class ProviderApiError extends Error {},
}))

const MUSE = 'muse-spark-1.3-contributor-free'
const OTHER = 'other-free'
const MUSE_ROW = `provider:opencode:${MUSE}`
const MUSE_PIN = `model:c1:${MUSE}`

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

const model = (id: string, thinkingLevels?: string[]) => ({
  id, name: id, source: 'live', stale: false, contextWindow: 200_000,
  contextWindowSource: 'reported', thinkingType: thinkingLevels?.length ? 'effort' : 'none',
  defaultThinking: null, thinkingLevels, capabilities: {}, enabled: true, health: 'healthy',
})

const connection = (
  id: string,
  models: Array<ReturnType<typeof model>>,
  overrides: Record<string, unknown> = {},
) => ({
  id, providerId: 'opencode', name: `OpenCode Free (${id})`, endpoint: 'https://example.test',
  enabled: true, authState: 'ready', projectState: 'not_applicable', discoveryState: 'ready',
  inferenceState: 'ready', credentialPresent: true, email: null, accountLabel: null, projectId: null,
  revision: 1, autoSync: true, lastModelTestedAt: null, lastModelSyncAt: null, nextModelSyncAt: null,
  quota: null, error: null, models,
  ...overrides,
})

const snapshotWith = (
  connections: Array<ReturnType<typeof connection>>,
  defaultRoute: ProviderSnapshot['defaultRoute'] = { connectionId: null, modelId: null, aliasId: null },
): ProviderSnapshot => ({
  providers: [{ id: 'opencode', name: 'OpenCode Free' }],
  connections, providerConfigs: [], aliases: [], defaultRoute, keys: [], usage: [],
  health: { status: 'ok', version: '0.1.0' },
}) as unknown as ProviderSnapshot

/** Mở popover của picker rồi sang tab Single Models (popover nằm ở `document.body`). */
function openModels(host: HTMLElement) {
  const trigger = Array.from(host.querySelectorAll('button'))
    .find((b) => (b.getAttribute('title') ?? '').startsWith('Model:'))
  click(trigger)
  const modelsTab = Array.from(document.querySelectorAll('button'))
    .find((b) => (b.textContent ?? '').trim().endsWith('Single Models'))
  click(modelsTab)
}

/**
 * Nạp snapshot TRƯỚC khi render rồi mới mount: `ChatPanel` gọi `load()` khi mount, mà bản
 * mock dưới đây trả về đúng snapshot đang có trong store — nên một lần `load` nền không
 * bao giờ ghi đè lần làm mới mà test vừa dựng.
 */
function renderWith(snapshot: ProviderSnapshot): HTMLElement {
  useProviderStore.setState({ snapshot })
  return render(<ChatPanel />)
}

const chipName = (host: HTMLElement) => host.querySelector('[data-testid="composer-model-name"]')?.textContent ?? ''
/** Nhãn trên chip bị CẮT theo mockup 03 (`pinned: … · muse-spark-1.3-c…`); tên đầy đủ nằm ở `title`. */
const chipTitle = (host: HTMLElement) => Array.from(host.querySelectorAll('button'))
  .find((b) => (b.getAttribute('title') ?? '').startsWith('Model:'))?.getAttribute('title') ?? ''
const modelRow = (id: string) => document.querySelector(`[data-component-id="model-row-${id}"]`)
/** Chỉ những nút MỨC trong dải chọn mức (bỏ nút ghim/Unpin của nhánh ghim). */
const LEVELS = /^(none|minimal|low|medium|high|xhigh|max)$/i
const thinkingButtons = (row: Element | null) => Array.from(row?.querySelectorAll('button') ?? [])
  .map((b) => (b.textContent ?? '').trim())
  .filter((text) => LEVELS.test(text))

beforeEach(() => {
  localStorage.clear()
  roots = []
  document.body.innerHTML = ''
  useRouterChatStore.setState({ turns: [], selection: null, isSending: false, activeTurnId: null })
  useHarnessStore.setState({ activeType: 'model', thinkingLevel: 'medium' })
  agentApiMock.mockReset()
  agentApiMock.mockImplementation(async (path: string) => {
    if (String(path).includes('/sessions')) return { id: 'sess-1', status: 'idle', events: [] }
    return {}
  })
  providerApiMock.mockReset()
  // Không có mạng: `/api/router/state` trả về snapshot đang nằm trong store.
  providerApiMock.mockImplementation(async () => useProviderStore.getState().snapshot ?? snapshotWith([]))
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  useProviderStore.setState({ snapshot: null })
  vi.restoreAllMocks()
})

describe('W12/T4 — mức thinking hiện ra là mức model công bố', () => {
  it('kéo mức đã lưu không được model công bố về mức gần nhất, và chỉ hiện mức thật', () => {
    const before = snapshotWith([
      connection('c1', [model(MUSE, ['max', 'high', 'low'])]),
      connection('c2', [model(MUSE, ['high', 'low'])]),
    ])
    useRouterChatStore.getState().setSelection({ kind: 'provider', providerId: 'opencode', modelId: MUSE })
    useHarnessStore.getState().setActiveModel(MUSE_ROW)
    useHarnessStore.getState().setThinkingLevel('medium')

    const host = renderWith(before)

    // 'medium' không có trong giao mức của nhóm (max/high/low ∩ high/low = high/low), và mức gần
    // nhất tính theo THINKING_ORDER là 'low' (cùng khoảng cách thì chọn mức thấp hơn).
    expect(useHarnessStore.getState().thinkingLevel).toBe('low')
    expect(chipTitle(host)).toContain(MUSE)
    expect(chipName(host)).toContain('muse-spark-1.3')

    openModels(host)
    const row = modelRow(MUSE_ROW)
    expect(row).not.toBeNull()
    // Nhãn dòng đang chọn chỉ có đúng mức model công bố — không có 'max' (chỉ c1 có) và không có 'medium'.
    expect(thinkingButtons(row)).toEqual(['high', 'low'])
    expect(row?.textContent).toContain('Thinking:')
  })

  it('model không công bố mức nào thì không có dải chọn mức, và mức đang lưu không bị đổi thành mức bịa', () => {
    const before = snapshotWith([connection('c1', [model(OTHER)])])
    useRouterChatStore.getState().setSelection({ kind: 'provider', providerId: 'opencode', modelId: OTHER })
    useHarnessStore.getState().setActiveModel(`provider:opencode:${OTHER}`)

    const host = renderWith(before)
    openModels(host)

    const row = modelRow(`provider:opencode:${OTHER}`)
    expect(row).not.toBeNull()
    expect(row?.textContent).not.toContain('Thinking:')
    expect(thinkingButtons(row)).toEqual([])
    // Mức đang lưu là mức mặc định toàn cục: model không công bố gì thì UI giữ nguyên yêu cầu,
    // harness tự bỏ nó — nhưng dải chọn mức thì không được bịa ra.
    expect(useHarnessStore.getState().thinkingLevel).toBe('medium')
    expect(chipName(host)).toContain(OTHER)
  })
})

describe('W12/T4 — chọn tay sống qua lần làm mới snapshot', () => {
  it('giữ nguyên đích đã GHIM khi lần làm mới thêm model mới và đổi defaultRoute', () => {
    const before = snapshotWith([
      connection('c1', [model(MUSE, ['high', 'low'])]),
      connection('c2', [model(MUSE, ['high', 'low'])]),
    ])
    useRouterChatStore.getState().setSelection({ kind: 'model', connectionId: 'c1', modelId: MUSE })
    useHarnessStore.getState().setActiveModel(MUSE_PIN)

    const host = renderWith(before)
    expect(chipTitle(host)).toContain(MUSE)
    expect(chipName(host)).toContain('pinned: OpenCode Free (c1)')

    // Lần dò kế tiếp: hai connection cũ vẫn còn model, thêm một model mới, và `defaultRoute`
    // trỏ sang model mới đó — đúng thứ dễ đè lên lựa chọn tay nhất.
    const after = snapshotWith([
      connection('c1', [model(MUSE, ['high', 'low']), model(OTHER)]),
      connection('c2', [model(MUSE, ['high', 'low']), model(OTHER)]),
    ], { connectionId: 'c2', modelId: OTHER, aliasId: null })
    act(() => {
      useProviderStore.setState({ snapshot: after })
    })

    expect(useRouterChatStore.getState().selection).toEqual({ kind: 'model', connectionId: 'c1', modelId: MUSE })
    expect(useHarnessStore.getState().activeModelId).toBe(MUSE_PIN)
    expect(chipTitle(host)).toContain(MUSE)
    expect(chipTitle(host)).not.toContain(OTHER)
    // Lần làm mới không được biến mỗi lần render thành một lượt dò provider.
    expect(providerApiMock).toHaveBeenCalledTimes(1)
  })

  it('chọn lại một model khác thì lựa chọn mới thắng lần làm mới sau đó', () => {
    const before = snapshotWith([
      connection('c1', [model(MUSE, ['high', 'low']), model(OTHER)]),
      connection('c2', [model(MUSE, ['high', 'low']), model(OTHER)]),
    ])
    useRouterChatStore.getState().setSelection({ kind: 'model', connectionId: 'c1', modelId: MUSE })
    useHarnessStore.getState().setActiveModel(MUSE_PIN)

    const host = renderWith(before)
    openModels(host)
    click(modelRow(`provider:opencode:${OTHER}`))

    expect(useRouterChatStore.getState().selection).toEqual({ kind: 'provider', providerId: 'opencode', modelId: OTHER })
    expect(useHarnessStore.getState().activeModelId).toBe(`provider:opencode:${OTHER}`)

    // Làm mới lần nữa (vẫn còn cả hai model): lựa chọn vừa bấm phải đứng yên.
    act(() => {
      useProviderStore.setState({ snapshot: before })
    })
    expect(useRouterChatStore.getState().selection).toEqual({ kind: 'provider', providerId: 'opencode', modelId: OTHER })
    expect(chipName(host)).toContain(OTHER)
  })
})

describe('W12/T4 — model đang chọn biến mất sau lần làm mới', () => {
  it('rơi về defaultRoute khi model cũ không còn trong inventory', () => {
    const before = snapshotWith([
      connection('c1', [model(MUSE, ['high', 'low'])]),
      connection('c2', [model(MUSE, ['high', 'low'])]),
    ])
    useRouterChatStore.getState().setSelection({ kind: 'model', connectionId: 'c1', modelId: MUSE })
    useHarnessStore.getState().setActiveModel(MUSE_PIN)

    const host = renderWith(before)
    expect(chipTitle(host)).toContain(MUSE)

    const after = snapshotWith([
      connection('c1', [model(OTHER)]),
      connection('c2', [model(OTHER)]),
    ], { connectionId: 'c1', modelId: OTHER, aliasId: null })
    act(() => {
      useProviderStore.setState({ snapshot: after })
    })

    // `defaultRoute` vẫn là dạng connectionId/modelId nên phải tra được hàng con (pin) của nhóm.
    expect(useRouterChatStore.getState().selection).toEqual({ kind: 'model', connectionId: 'c1', modelId: OTHER })
    expect(useHarnessStore.getState().activeModelId).toBe(`model:c1:${OTHER}`)
    expect(chipTitle(host)).toContain(OTHER)
    expect(chipName(host)).not.toContain('muse')
  })

  it('không còn defaultRoute thì rơi về dòng đầu tiên còn dùng được, không giữ nhãn cũ', () => {
    const before = snapshotWith([
      connection('c1', [model(MUSE, ['high', 'low'])]),
      connection('c2', [model(MUSE, ['high', 'low'])]),
    ])
    useRouterChatStore.getState().setSelection({ kind: 'model', connectionId: 'c1', modelId: MUSE })
    useHarnessStore.getState().setActiveModel(MUSE_PIN)

    const host = renderWith(before)

    const after = snapshotWith([connection('c1', [model(OTHER)])])
    act(() => {
      useProviderStore.setState({ snapshot: after })
    })

    expect(useRouterChatStore.getState().selection).toEqual({ kind: 'provider', providerId: 'opencode', modelId: OTHER })
    expect(useHarnessStore.getState().activeModelId).toBe(`provider:opencode:${OTHER}`)
    expect(chipName(host)).toContain(OTHER)
  })

  it('lần làm mới hỏng vẫn giữ đích gõ tay: hàng còn định tuyến được thì lựa chọn đứng yên', () => {
    const before = snapshotWith([
      connection('c1', [model(MUSE, ['high', 'low'])]),
      connection('c2', [model(MUSE, ['high', 'low'])]),
    ])
    useRouterChatStore.getState().setSelection({ kind: 'model', connectionId: 'c1', modelId: MUSE })
    useHarnessStore.getState().setActiveModel(MUSE_PIN)

    const host = renderWith(before)
    expect(chipTitle(host)).toContain(MUSE)

    // Dò hỏng: router giữ last-good, gắn `stale`, và chỉ model GÕ TAY còn định tuyến được
    // (`validTarget`) — nên hàng vẫn sống và phiên ghim không được rơi về đâu khác.
    const degraded = snapshotWith([
      connection('c1', [{ ...model(MUSE, ['high', 'low']), source: 'custom', stale: true }], { discoveryState: 'degraded', error: 'offline' }),
      connection('c2', [{ ...model(MUSE, ['high', 'low']), source: 'custom', stale: true }], { discoveryState: 'degraded', error: 'offline' }),
    ])
    act(() => {
      useProviderStore.setState({ snapshot: degraded })
    })

    expect(useRouterChatStore.getState().selection).toEqual({ kind: 'model', connectionId: 'c1', modelId: MUSE })
    expect(useHarnessStore.getState().activeModelId).toBe(MUSE_PIN)
    expect(chipTitle(host)).toContain(MUSE)

    openModels(host)
    expect(modelRow(MUSE_ROW)).not.toBeNull()
    // Cả hai connection đều đang chạy danh sách gõ tay — hàng nói ra thay vì gộp im lặng.
    expect(modelRow(MUSE_ROW)?.textContent).toContain('2 hand-typed')
  })
})
