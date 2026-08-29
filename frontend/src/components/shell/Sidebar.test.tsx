import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { MOCK_SESSIONS } from '../../lib/mock/sessions'
import { Sidebar } from './Sidebar'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT =
  true

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

function fireClick(el: Element) {
  act(() => {
    el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function buttonWithText(host: HTMLElement, text: string): HTMLButtonElement | undefined {
  return [...host.querySelectorAll('button')].find((b) => b.textContent?.trim() === text)
}

function buttonContaining(host: HTMLElement, text: string): HTMLButtonElement | undefined {
  return [...host.querySelectorAll('button')].find((b) => b.textContent?.includes(text))
}

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

beforeEach(() => {
  useAgentStore.setState({
    sessions: MOCK_SESSIONS.map((s) => ({ ...s })),
    activeSessionId: 's-04',
  })
  useUiStore.setState({ searchOpen: false, sessionTab: 'recent', sidebarCollapsed: false })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

describe('Sidebar', () => {
  it('toggles pin from the session context menu and sorts pinned first', () => {
    const host = render(<Sidebar />)

    // Mở menu `...` của "Run Agentic RAG project" (s-02, chưa ghim).
    fireClick(host.querySelector('[data-testid="session-menu-s-02"]')!)
    const pinItem = buttonWithText(host, 'Pin session')
    expect(pinItem).toBeTruthy()
    fireClick(pinItem!)

    const sessions = useAgentStore.getState().sessions
    expect(sessions.find((s) => s.session_id === 's-02')?.is_pinned).toBe(true)
    // Các phiên được ghim đứng trước phiên chưa ghim (s-01 đã ghim sẵn nên vẫn đứng đầu).
    expect(sessions[0].is_pinned).toBe(true)
    expect(sessions[1].is_pinned).toBe(true)
    expect(sessions.findIndex((s) => s.session_id === 's-02')).toBeLessThan(
      sessions.findIndex((s) => s.session_id === 's-03'),
    )
  })

  it('renames a session inline from the context menu', () => {
    const host = render(<Sidebar />)

    fireClick(host.querySelector('[data-testid="session-menu-s-04"]')!)
    fireClick(buttonWithText(host, 'Rename')!)

    const input = host.querySelector<HTMLInputElement>('[data-testid="session-rename-input"]')
    expect(input).toBeTruthy()

    act(() => {
      setInputValue(input!, 'Renamed Session')
      input!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    })

    expect(
      useAgentStore.getState().sessions.find((s) => s.session_id === 's-04')?.title,
    ).toBe('Renamed Session')
  })

  it('shows group folders in the Groups tab and expands them', () => {
    useUiStore.setState({ sessionTab: 'groups' })
    const host = render(<Sidebar />)

    // Header nhóm hiển thị (chưa cần mở rộng).
    expect(buttonContaining(host, 'Infrastructure')).toBeTruthy()
    expect(buttonContaining(host, 'AI Projects')).toBeTruthy()

    // Phiên trong nhóm chưa hiện cho tới khi mở accordion.
    expect(host.textContent).not.toContain('Machine Setup')

    fireClick(buttonContaining(host, 'Infrastructure')!)
    expect(host.textContent).toContain('Machine Setup')
  })
})
