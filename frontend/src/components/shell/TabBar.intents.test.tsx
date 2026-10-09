/**
 * Huy hiệu trên thanh tab + hàng thông báo cạnh khung soạn tin — hai dấu hiệu
 * cho người dùng biết có ý định tự mở tab đang xếp hàng (hợp đồng §3: tab đích
 * hiện số đếm; mở tab là xoá hàng). Huy hiệu chỉ nói "đang chờ", hàng thông báo
 * nói thêm VÌ SAO (cổng nào đã chặn) và cho mở ngay bằng một cú bấm.
 *
 * Vẽ nguyên `App` (thanh tab nằm trong đó) với mạng đã chặn.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from '../../App'
import { I18nProvider } from '../../i18n'
import en from '../../i18n/en'
import { useAgentStore } from '../../store/agentStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useUiStore } from '../../store/uiStore'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { agentApiMock, providerApiMock } = vi.hoisted(() => ({ agentApiMock: vi.fn(), providerApiMock: vi.fn() }))

vi.mock('../../lib/agentApi', () => ({ agentApi: agentApiMock }))
vi.mock('../../lib/providerApi', () => ({
  api: providerApiMock,
  ProviderApiError: class ProviderApiError extends Error {},
}))

const EMPTY_SNAPSHOT = {
  providers: [],
  connections: [],
  providerConfigs: [],
  aliases: [],
  defaultRoute: { connectionId: null, modelId: null, aliasId: null },
  keys: [],
  usage: [],
  health: { status: 'ok', version: '0.1.0' },
}

let roots: Root[] = []
const fetchMock = vi.fn()

function render(): HTMLElement {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(
      <I18nProvider>
        <App />
      </I18nProvider>,
    )
  })
  return host
}

function tabBadge(host: HTMLElement, tab: string): HTMLElement | null {
  return host.querySelector(`[data-testid="tab-badge-${tab}"]`)
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  fetchMock.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({}) }))
  agentApiMock.mockReset()
  agentApiMock.mockImplementation(async () => ({ sessions: [] }))
  providerApiMock.mockReset()
  providerApiMock.mockImplementation(async () => EMPTY_SNAPSHOT)
  useHarnessChatStore.setState({ sessions: {}, decisions: {} })
  useUiStore.setState({
    openTabs: ['plan'],
    activeTab: 'plan',
    pendingIntents: [],
    pinnedTab: null,
    lastUserActivityAt: 0,
    autoOpenTabs: true,
    autoOpenOnlyWhenIdle: false,
    tabIntentTargets: {},
    planRevision: 0,
  })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('Thanh tab — huy hiệu ý định đang xếp hàng', () => {
  it('không có ý định nào thì tab Plan không có huy hiệu', () => {
    const host = render()

    expect(tabBadge(host, 'plan')).toBeNull()
  })

  it('ý định xếp hàng cho tab Plan thì tab đó mang số đếm', () => {
    useUiStore.setState({ autoOpenOnlyWhenIdle: true, lastUserActivityAt: Date.now() })
    const host = render()

    act(() => {
      const result = useUiStore.getState().requestTabIntent({ tab: 'plan', target: { identity: 'agent-box-plan' }, reason: 'plan_written' })
      expect(result).toBe('queued')
    })

    const badge = tabBadge(host, 'plan')
    expect(badge?.textContent).toBe('1')
  })

  it('người dùng mở tab thì hàng đợi của tab đó được xoá, huy hiệu biến mất', () => {
    useUiStore.setState({ autoOpenOnlyWhenIdle: true, lastUserActivityAt: Date.now(), openTabs: ['plan', 'decisions'] })
    const host = render()

    act(() => {
      useUiStore.getState().requestTabIntent({ tab: 'decisions', target: { requestId: 'd1' }, reason: 'decision_requested' })
    })
    expect(tabBadge(host, 'decisions')?.textContent).toBe('1')

    act(() => {
      useUiStore.getState().openTab('decisions')
    })

    expect(tabBadge(host, 'decisions')).toBeNull()
    expect(useUiStore.getState().pendingIntents).toEqual([])
  })

  it('quyết định harness đang chờ cũng tính vào huy hiệu của tab Decisions', () => {
    useUiStore.setState({ openTabs: ['plan', 'decisions'] })
    const host = render()

    act(() => {
      useAgentStore.setState({
        requests: {
          'req-1': { request_id: 'req-1', status: 'dang_cho', question: 'Cho phép chạy?' } as never,
        },
      })
    })

    expect(tabBadge(host, 'decisions')?.textContent).toBe('1')
  })
})

describe('Thanh tab — ý định xếp hàng cho tab Design', () => {
  it('ý định suy ra từ `design_canvas` đếm trên huy hiệu của tab Design', () => {
    useUiStore.setState({ openTabs: ['plan', 'design'], autoOpenOnlyWhenIdle: true, lastUserActivityAt: Date.now() })
    const host = render()

    act(() => {
      const result = useUiStore
        .getState()
        .requestTabIntent({ tab: 'design', target: { designId: 'design-1' }, reason: 'canvas_drawn' })
      expect(result).toBe('queued')
    })

    expect(tabBadge(host, 'design')?.textContent).toBe('1')
  })
})

describe('Khung chat — hàng thông báo ý định đang xếp hàng (N2)', () => {
  function queueDesignIntent() {
    useUiStore.setState({
      openTabs: ['plan', 'design'],
      activeTab: 'plan',
      autoOpenOnlyWhenIdle: true,
      lastUserActivityAt: Date.now(),
    })
    const host = render()
    act(() => {
      useUiStore
        .getState()
        .requestTabIntent({ tab: 'design', target: { designId: 'design-1' }, reason: 'canvas_drawn' })
    })
    return host
  }

  it('người dùng nhìn thấy hàng thông báo kèm tên tab và LÝ DO bị chặn', () => {
    const host = queueDesignIntent()

    const notice = host.querySelector('[data-testid="chat-pending-intent"]')
    expect(notice).not.toBeNull()
    expect(notice?.textContent).toContain('Design')
    // Cổng đã chặn ở đây là "người dùng đang bận" — lý do phải đọc được.
    expect(notice?.textContent).toContain(en.chat.pendingTabReasonUserBusy)
  })

  it('bấm "mở ngay" mở tab đang chờ; hàng đợi và hàng thông báo tự biến mất', () => {
    const host = queueDesignIntent()
    const open = host.querySelector<HTMLButtonElement>('[data-testid="chat-pending-intent-open"]')
    expect(open).not.toBeNull()

    act(() => {
      open?.click()
    })

    expect(useUiStore.getState().activeTab).toBe('design')
    expect(useUiStore.getState().pendingIntents).toEqual([])
    expect(useUiStore.getState().pendingIntentNotice).toBeNull()
    expect(host.querySelector('[data-testid="chat-pending-intent"]')).toBeNull()
  })

  it('bấm "bỏ qua" chỉ ẩn hàng thông báo — hàng đợi và huy hiệu vẫn còn', () => {
    const host = queueDesignIntent()
    const dismiss = host.querySelector<HTMLButtonElement>('[data-testid="chat-pending-intent-dismiss"]')
    expect(dismiss).not.toBeNull()

    act(() => {
      dismiss?.click()
    })

    expect(host.querySelector('[data-testid="chat-pending-intent"]')).toBeNull()
    expect(useUiStore.getState().pendingIntentNotice).toBeNull()
    expect(tabBadge(host, 'design')?.textContent).toBe('1')
  })
})
