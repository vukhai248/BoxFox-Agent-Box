/**
 * Công tắc bảng Workspace trên thanh trên (Kế hoạch E2, việc 6 + 7).
 *
 * Bảng Workspace và màn Máy là MỘT cột phải, nên công tắc này ẩn/hiện đúng cột
 * đó: cả thanh tab lẫn tab đang chọn đi theo, cột chat giãn hết (`flex 1 1 0%`),
 * và `splitRatio` không bị đụng — hiện lại là về đúng tỉ lệ cũ.
 *
 * Vẽ nguyên `App` với mạng đã chặn, đúng khuôn `TabBar.intents.test.tsx`.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { I18nProvider } from './i18n'
import { useAgentStore } from './store/agentStore'
import { useHarnessChatStore } from './store/harnessChatStore'
import { useUiStore } from './store/uiStore'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { agentApiMock, providerApiMock } = vi.hoisted(() => ({
  agentApiMock: vi.fn(),
  providerApiMock: vi.fn(),
}))

vi.mock('./lib/agentApi', () => ({ agentApi: agentApiMock }))
vi.mock('./lib/providerApi', () => ({
  api: providerApiMock,
  ProviderApiError: class ProviderApiError extends Error {},
}))

/** Bề rộng cửa sổ mà bài test đang giả lập; `0` = chưa đo được (bố cục đầy đủ). */
const viewport = { width: 1440 }

vi.mock('./components/shell/useViewportWidth', () => ({
  NARROW_VIEWPORT_MAX_PX: 1024,
  COMPACT_VIEWPORT_MAX_PX: 768,
  isNarrowViewport: (width: number) => width > 0 && width < 1024,
  isCompactViewport: (width: number) => width > 0 && width < 768,
  useViewportWidth: () => viewport.width,
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
let host: HTMLElement

function render(): void {
  host = document.createElement('div')
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
}

function moreBtn(): HTMLElement | null {
  return host.querySelector('[data-testid="workspace-more-btn"]')
}

function pane(): HTMLElement | null {
  return host.querySelector('[data-testid="workspace-pane"]')
}

function resizer(): HTMLElement | null {
  return host.querySelector('[role="separator"]')
}

function chatColumn(): HTMLElement {
  return host.querySelector('[data-testid="chat-column"]')!
}

function openWorkspaceFromMenu(label: string): void {
  const more = moreBtn()
  act(() => more?.click())
  const item = [...host.querySelectorAll('button')].find(
    (button) => button.textContent?.includes(label) && button !== more,
  )
  act(() => item?.click())
}

beforeEach(() => {
  viewport.width = 1440
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) })))
  agentApiMock.mockReset()
  agentApiMock.mockImplementation(async () => ({ sessions: [] }))
  providerApiMock.mockReset()
  providerApiMock.mockImplementation(async () => EMPTY_SNAPSHOT)
  useHarnessChatStore.setState({ sessions: {}, decisions: {} })
  useAgentStore.setState({ activeSessionId: '', requests: {} })
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
    workspaceHidden: false,
    splitRatio: 0.46,
  })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('Nút More (...) trên thanh TopBar', () => {
  it('nút ... có mặt trên TopBar', () => {
    render()
    expect(moreBtn()).not.toBeNull()
  })

  it('bấm nút ... mở dropdown menu chọn workspace', () => {
    render()
    act(() => moreBtn()!.click())

    const text = host.textContent
    expect(text).toContain('Workspaces')
    expect(text).toContain('Sandbox Controls')
    expect(text).toContain('Machine')
    expect(text).toContain('Network')
  })
})

describe('Cơ chế tự động đóng/mở Workspace theo Devin', () => {
  it('khi có tab mở (openTabs > 0) ⇒ cột phải và Resizer hiển thị', () => {
    useUiStore.setState({ openTabs: ['plan'], activeTab: 'plan' })
    render()

    expect(pane()).not.toBeNull()
    expect(resizer()).not.toBeNull()
    expect(chatColumn().style.flex).toBe('0.46 0 0%')
  })

  it('khi không có tab nào mở (openTabs = []) ⇒ workspace tự đóng, chat giãn 100%', () => {
    useUiStore.setState({ openTabs: [], activeTab: null })
    render()

    expect(pane()).toBeNull()
    expect(resizer()).toBeNull()
    expect(chatColumn().style.flex).toBe('1 1 0%')
  })

  it('bấm chọn workspace từ menu ... ⇒ tab được mở và workspace tự động hiển thị', () => {
    useUiStore.setState({ openTabs: [], activeTab: null })
    render()
    expect(pane()).toBeNull()

    openWorkspaceFromMenu('Decisions & Approvals')

    expect(pane()).not.toBeNull()
    expect(useUiStore.getState().openTabs).toContain('decisions')
    expect(useUiStore.getState().activeTab).toBe('decisions')
  })
})
