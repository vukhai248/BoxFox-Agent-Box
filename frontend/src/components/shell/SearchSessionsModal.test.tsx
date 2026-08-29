import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { MOCK_SESSIONS } from '../../lib/mock/sessions'
import { SearchSessionsModal } from './SearchSessionsModal'

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

function setInputValue(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')!.set!
  setter.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function openViaShortcut() {
  act(() => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'k', ctrlKey: true }))
  })
}

beforeEach(() => {
  useAgentStore.setState({
    sessions: MOCK_SESSIONS.map((s) => ({ ...s })),
    activeSessionId: 's-04',
  })
  useUiStore.setState({ searchOpen: false })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

describe('SearchSessionsModal', () => {
  it('opens and closes with Ctrl/Cmd+K', () => {
    const host = render(<SearchSessionsModal />)
    expect(useUiStore.getState().searchOpen).toBe(false)

    openViaShortcut()
    expect(useUiStore.getState().searchOpen).toBe(true)
    expect(host.textContent).toContain('Quick actions')

    // Bấm lại Ctrl+K để đóng.
    openViaShortcut()
    expect(useUiStore.getState().searchOpen).toBe(false)
    expect(host.textContent).toBe('')
  })

  it('closes on Escape', () => {
    useUiStore.setState({ searchOpen: true })
    const host = render(<SearchSessionsModal />)
    const input = host.querySelector('input')
    expect(input).toBeTruthy()

    act(() => {
      input!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    })
    expect(useUiStore.getState().searchOpen).toBe(false)
  })

  it('filters sessions by query', () => {
    useUiStore.setState({ searchOpen: true })
    const host = render(<SearchSessionsModal />)
    const input = host.querySelector('input')!

    act(() => setInputValue(input, 'docker'))

    expect(host.textContent).toContain('Setup docker repo')
    expect(host.textContent).not.toContain('Machine Setup')
    expect(host.textContent).not.toContain('Run Agentic RAG project')
  })

  it('navigates with ArrowDown and opens a session on Enter', () => {
    useUiStore.setState({ searchOpen: true })
    const host = render(<SearchSessionsModal />)
    const input = host.querySelector('input')!

    act(() => setInputValue(input, 'machine'))
    act(() => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true }))
    })
    act(() => {
      input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    })

    expect(useAgentStore.getState().activeSessionId).toBe('s-03')
    expect(useUiStore.getState().searchOpen).toBe(false)
  })
})
