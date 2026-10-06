// Cửa ngõ của cả khối Settings: mọi tab id phải còn thân của nó, và ô chỉ dẫn chưa lưu
// phải hỏi một lần trước khi bị bỏ lại phía sau (Esc / đổi tab / đóng).
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useOwnerSettingsStore } from '../../store/ownerSettingsStore'
import { useSessionRecordStore } from '../../store/sessionRecordStore'
import { useUiStore } from '../../store/uiStore'
import { SettingsModal } from './SettingsModal'
import type { SettingTabId } from '../../types/harness'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const RUNTIME_INFO = {
  tools: ['file_read', 'terminal_exec'],
  toolGroups: [],
  limits: { instructionsChars: 12000, maxStepsDefault: 16, maxStepsMax: 60, deadlineDefaultSeconds: 180, deadlineMaxSeconds: 600, childMaxSteps: 10, childDeadlineSeconds: 120 },
}
const ROUTER_STATE = {
  providers: [],
  connections: [],
  aliases: [],
  keys: [],
  usage: [],
  defaultRoute: { connectionId: null, modelId: null, aliasId: null },
  health: { status: 'ok', version: 'test' },
}

/** Thân thật của từng nhánh `renderContent()`; tab nào chưa có view thì rơi về câu mặc định. */
const TAB_BODIES: Array<{ id: SettingTabId; marker?: string }> = [
  { id: 'harness', marker: 'Harness' },
  { id: 'instructions', marker: 'Directives sent to the main agent' },
  { id: 'skills' },
  { id: 'provider', marker: 'Provider' },
  { id: 'llm_api_keys', marker: 'Provider' },
  { id: 'router', marker: 'Provider' },
  { id: 'scheduled_sessions', marker: 'Scheduled Sessions' },
  { id: 'automations', marker: 'Automations' },
  { id: 'configuration' },
  { id: 'machine_permissions', marker: 'Machine & Permissions' },
  { id: 'secrets', marker: 'Secrets' },
  { id: 'browser', marker: 'Browser Snapshots' },
  { id: 'integrations' },
  { id: 'pull_requests' },
  { id: 'appearance', marker: 'Appearance' },
  { id: 'api' },
  { id: 'billing' },
  { id: 'usage' },
  { id: 'referrals', marker: 'Referrals & Credits' },
  { id: 'support', marker: 'Support & Resources' },
  { id: 'account' },
  { id: 'notifications', marker: 'Notifications' },
]

const PLACEHOLDER = 'Configure parameters and integrations for this section.'

let root: Root
let host: HTMLDivElement
const calls: Array<{ url: string; method: string; body: Record<string, unknown> | null }> = []
let stored = { instructions: 'Be brief.', revision: 4 }

const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } })
const pristineOwner = useOwnerSettingsStore.getState()

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  calls.length = 0
  stored = { instructions: 'Be brief.', revision: 4 }
  useOwnerSettingsStore.setState(pristineOwner, true)
  useSessionRecordStore.getState().reset()
  useUiStore.getState().closeSettings()
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: RequestInit = {}) => {
    const method = init.method ?? 'GET'
    calls.push({ url: String(url), method, body: typeof init.body === 'string' ? JSON.parse(init.body) : null })
    if (String(url).endsWith('/runtime-info')) return json(RUNTIME_INFO)
    if (String(url).includes('/api/router/state')) return json(ROUTER_STATE)
    if (method === 'PUT') {
      const body = JSON.parse(String(init.body)) as { instructions: string }
      stored = { instructions: body.instructions, revision: stored.revision + 1 }
      return json(stored)
    }
    if (String(url).endsWith('/owner-settings')) return json(stored)
    return json({})
  }))
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

const flush = async () => { await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) }) }
const open = async (tab: SettingTabId) => {
  act(() => { useUiStore.getState().openSettings(tab) })
  await act(async () => {
    root.render(
      <I18nProvider>
        <SettingsModal />
      </I18nProvider>,
    )
  })
  await flush()
}
const testid = (id: string) => host.querySelector<HTMLElement>(`[data-testid="${id}"]`)
const main = () => host.querySelector('main')!
const box = () => host.querySelector<HTMLTextAreaElement>('textarea')!
const click = async (element: HTMLElement) => {
  await act(async () => { element.dispatchEvent(new MouseEvent('click', { bubbles: true })); await Promise.resolve() })
  await flush()
}
const navButton = (label: string) =>
  [...host.querySelectorAll<HTMLButtonElement>('aside button')].find((candidate) => candidate.textContent?.trim() === label)!
function type(element: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!
  act(() => { setter.call(element, value); element.dispatchEvent(new Event('input', { bubbles: true })) })
}
const escape = async () => {
  await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true })); await Promise.resolve() })
  await flush()
}

describe('SettingsModal', () => {
  it('renders a real body for every settings tab id', async () => {
    for (const tab of TAB_BODIES) {
      await open(tab.id)
      const body = main().textContent?.trim() ?? ''
      expect(body.length, `tab ${tab.id} rendered an empty body`).toBeGreaterThan(20)
      if (tab.marker) {
        expect(body, `tab ${tab.id} lost its own body`).toContain(tab.marker)
      } else {
        // Bốn tab chưa có view riêng dùng câu mặc định; các tab còn lại không được rơi vào đó.
        const fallsBackByDesign = ['configuration', 'integrations', 'api', 'billing'].includes(tab.id)
        if (!fallsBackByDesign) expect(body, `tab ${tab.id} fell through to the default body`).not.toContain(PLACEHOLDER)
      }
    }
  })

  it('keeps an unsaved box: Escape asks once with Save · Discard · Stay', async () => {
    await open('instructions')
    type(box(), 'Be brief. Always prove it.')

    await escape()
    expect(testid('settings-guard-stay')).toBeTruthy()
    expect(useUiStore.getState().isSettingsOpen).toBe(true)

    // Esc trong lúc câu hỏi đang mở là "ở lại": không tự đóng, không tự lưu.
    await escape()
    expect(testid('settings-guard-stay')).toBeFalsy()
    expect(useUiStore.getState().isSettingsOpen).toBe(true)
    expect(useOwnerSettingsStore.getState().draft).toBe('Be brief. Always prove it.')

    await escape()
    await click(testid('settings-guard-stay')!)
    expect(testid('settings-guard-stay')).toBeFalsy()
    expect(useUiStore.getState().isSettingsOpen).toBe(true)
    expect(box().value).toBe('Be brief. Always prove it.')

    await escape()
    await click(testid('settings-guard-discard')!)
    expect(useUiStore.getState().isSettingsOpen).toBe(false)
    expect(useOwnerSettingsStore.getState().draft).toBe('Be brief.')
  })

  it('asks before switching tabs, and saves the box before leaving it', async () => {
    await open('instructions')
    type(box(), 'Be brief. Always prove it.')

    await click(navButton('Skills'))
    expect(useUiStore.getState().settingsTab).toBe('instructions')
    expect(testid('settings-guard-save')).toBeTruthy()

    await click(testid('settings-guard-save')!)
    expect(calls.find((call) => call.method === 'PUT')?.body).toEqual({ instructions: 'Be brief. Always prove it.', revision: 4 })
    expect(useUiStore.getState().settingsTab).toBe('skills')
    expect(useOwnerSettingsStore.getState().draft).toBe('Be brief. Always prove it.')
  })

  it('closes straight away when the box is not dirty', async () => {
    await open('instructions')
    await click(navButton('Back to app'))
    expect(testid('settings-guard-stay')).toBeFalsy()
    expect(useUiStore.getState().isSettingsOpen).toBe(false)
  })
})
