import type { ReactNode } from 'react'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ChatMoreOptionsPicker } from './ChatMoreOptionsPicker'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let roots: Root[] = []

function renderHelper(node: ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(node)
  })
  return host
}

function click(el: Element | null | undefined) {
  act(() => {
    el?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

describe('ChatMoreOptionsPicker', () => {
  const onToggleAutopilot = vi.fn()
  const onToggleRepo = vi.fn()

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    for (const root of roots) act(() => root.unmount())
    roots = []
    document.body.innerHTML = ''
  })

  it('renders trigger button [ ⋮ ]', () => {
    const host = renderHelper(
      <ChatMoreOptionsPicker
        autopilotEnabled={false}
        onToggleAutopilot={onToggleAutopilot}
        selectedRepoIds={['minndty4-pixel/BoxFox-Agent-Box']}
        onToggleRepo={onToggleRepo}
      />,
    )
    const trigger = host.querySelector('[data-testid="chat-more-options-btn"]')
    expect(trigger).not.toBeNull()
  })

  it('opens popup menu on click and displays Repositories and Autopilot', () => {
    const host = renderHelper(
      <ChatMoreOptionsPicker
        autopilotEnabled={false}
        onToggleAutopilot={onToggleAutopilot}
        selectedRepoIds={['minndty4-pixel/BoxFox-Agent-Box']}
        onToggleRepo={onToggleRepo}
      />,
    )

    const trigger = host.querySelector('[data-testid="chat-more-options-btn"]')
    click(trigger)

    const menu = document.querySelector('[data-testid="chat-more-menu"]')
    expect(menu).not.toBeNull()
    expect(menu?.textContent).toContain('Repositories')
    expect(menu?.textContent).toContain('Autopilot')
    expect(menu?.textContent).toContain('1 selected')
  })

  it('toggles autopilot switch when clicking switch or autopilot row', () => {
    const host = renderHelper(
      <ChatMoreOptionsPicker
        autopilotEnabled={false}
        onToggleAutopilot={onToggleAutopilot}
        selectedRepoIds={['minndty4-pixel/BoxFox-Agent-Box']}
        onToggleRepo={onToggleRepo}
      />,
    )

    const trigger = host.querySelector('[data-testid="chat-more-options-btn"]')
    click(trigger)

    const switchBtn = document.querySelector('[data-testid="more-menu-autopilot-switch"]')
    click(switchBtn)
    expect(onToggleAutopilot).toHaveBeenCalledTimes(1)
  })

  it('navigates to repo list when clicking Repositories item and allows going back', () => {
    const host = renderHelper(
      <ChatMoreOptionsPicker
        autopilotEnabled={false}
        onToggleAutopilot={onToggleAutopilot}
        selectedRepoIds={['minndty4-pixel/BoxFox-Agent-Box']}
        onToggleRepo={onToggleRepo}
      />,
    )

    const trigger = host.querySelector('[data-testid="chat-more-options-btn"]')
    click(trigger)

    const repoItem = document.querySelector('[data-testid="more-menu-repos-item"]')
    click(repoItem)

    // Trong view repos
    const searchInput = document.querySelector('input[placeholder="Search repositories..."]')
    expect(searchInput).not.toBeNull()
    expect(document.body.textContent).toContain('minndty4-pixel/BoxFox-Agent-Box')

    // Bấm Back quay lại menu
    const backBtn = document.querySelector('[data-testid="repo-back-btn"]')
    click(backBtn)

    const menu = document.querySelector('[data-testid="chat-more-menu"]')
    expect(menu?.textContent).toContain('Repositories')
    expect(menu?.textContent).toContain('Autopilot')
  })
})
