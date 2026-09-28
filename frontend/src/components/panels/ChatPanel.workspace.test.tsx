/**
 * Cột đọc 768 px khi bảng Workspace ẩn (Kế hoạch E2, việc 7).
 *
 * Cột chat giãn hết là việc của `App`; tệp này khoá phần nội dung: khi
 * `workspaceHidden` bật thì cả ba chỗ đọc được (thân cuộn, hộp soạn tin, hàng
 * của thanh ngữ cảnh) đều mang lớp đo `mx-auto w-full max-w-3xl`, và khi bảng
 * hiện thì lớp đó VẮNG — cột chat không được ngầm đổi bề rộng.
 *
 * Không khẳng định pixel (jsdom không có layout engine): khẳng định đúng hợp
 * đồng lớp, thứ duy nhất mã nguồn quyết định.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { READING_COLUMN_CLASS } from '../../lib/readingColumn'
import { useAgentStore } from '../../store/agentStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useRouterChatStore } from '../../store/routerChatStore'
import { useUiStore } from '../../store/uiStore'
import { ChatPanel } from './ChatPanel'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { agentApiMock, providerApiMock } = vi.hoisted(() => ({
  agentApiMock: vi.fn(),
  providerApiMock: vi.fn(),
}))

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
let host: HTMLElement

function render(): void {
  host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(
      <I18nProvider>
        <ChatPanel />
      </I18nProvider>,
    )
  })
}

/**
 * Các chỗ trong ChatPanel phải mang lớp đo: thân cuộn và hộp trong của khu soạn tin (`chat-input-bar`).
 */
function measuredNodes(): (Element | null)[] {
  return [
    host.querySelector('[data-testid="chat-reading-column"]'),
    host.querySelector('[data-testid="chat-input-bar"]'),
  ]
}

function demonstratesColumn(className: string): boolean {
  return READING_COLUMN_CLASS.split(' ').every((token) => className.includes(token))
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) })))
  agentApiMock.mockReset()
  agentApiMock.mockImplementation(async () => ({ sessions: [] }))
  providerApiMock.mockReset()
  providerApiMock.mockImplementation(async () => EMPTY_SNAPSHOT)
  useHarnessChatStore.setState({ sessions: {}, decisions: {} })
  useRouterChatStore.setState({ turns: [] })
  useAgentStore.setState({ activeSessionId: '' })
  useUiStore.setState({ workspaceHidden: false, openTabs: ['plan'] })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('bảng Workspace hiện ⇒ cột chat giữ nguyên', () => {
  it('không chỗ nào mang lớp đo 768 px', () => {
    render()

    const nodes = measuredNodes()
    // Cả ba chỗ đều phải tồn tại (nếu không, phép so lớp bên dưới là vô nghĩa).
    expect(nodes.filter((node) => node === null)).toEqual([])
    for (const node of nodes) {
      const className = node!.className
      expect(demonstratesColumn(className)).toBe(false)
    }
  })

  it('nội dung cũ vẫn nằm trong khung cuộn (không dựng lại cây)', () => {
    render()

    const scroll = host.querySelector('[data-testid="chat-scroll"]')
    expect(scroll).not.toBeNull()
    expect(scroll?.textContent).toBeTruthy()
  })
})

describe('bảng Workspace ẩn ⇒ nội dung gom vào cột 768 px ở giữa', () => {
  it('cả ba chỗ mang `mx-auto w-full max-w-3xl`', () => {
    useUiStore.setState({ workspaceHidden: true, openTabs: ['plan'] })
    render()

    for (const node of measuredNodes()) {
      expect(node!.className).toContain(READING_COLUMN_CLASS)
    }
  })

  it('bật/tắt công tắc không làm mất lớp của hai chỗ còn lại', () => {
    useUiStore.setState({ workspaceHidden: true, openTabs: ['plan'] })
    render()
    expect(host.querySelector('[data-testid="chat-input-bar"]')!.className).toContain(
      READING_COLUMN_CLASS,
    )

    act(() => {
      useUiStore.getState().setWorkspaceHidden(false)
    })

    expect(host.querySelector('[data-testid="chat-input-bar"]')!.className).not.toContain(
      READING_COLUMN_CLASS,
    )
    expect(host.querySelector('[data-testid="chat-reading-column"]')!.className).not.toContain(
      READING_COLUMN_CLASS,
    )
  })

  it('khi chưa mở tab nào (openTabs = []) ⇒ tự động gom vào giữa', () => {
    useUiStore.setState({ workspaceHidden: false, openTabs: [] })
    render()

    for (const node of measuredNodes()) {
      expect(node!.className).toContain(READING_COLUMN_CLASS)
    }
  })
})

