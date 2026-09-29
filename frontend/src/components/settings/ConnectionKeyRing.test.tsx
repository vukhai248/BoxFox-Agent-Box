// Round 29: a connection holds an ordered ring of keys and rotates inside itself when the
// provider answers 429. These cases pin the four rendered states, the countdown, the five
// router calls the ring makes (add, replace, remove, try, import), the empty ring, and the
// hard rule that no secret — and no key-shaped string inside an error line — reaches the page.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ProviderView } from './ProviderView'
import { useProviderStore } from '../../store/providerStore'
import type { ConnectionKey, ProviderConnection, ProviderModel, ProviderSnapshot } from '../../types/provider'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** A long, key-shaped value: the ring may keep its first six characters and nothing else. */
const SECRET = 'sk-or-v1-8f3c9d2e1b7a4c6f5e8d'
const ENDPOINT_KEY = '/api/router/connections/openrouter-key'

const providers: ProviderSnapshot['providers'] = [
  { id: 'openrouter', name: 'OpenRouter', authMethod: 'api_key', protocol: 'openai', icon: '/providers/openrouter.png', category: 'free', runtimeAvailable: true, availability: 'ready', routerVisible: true, defaultEndpoint: 'https://openrouter.ai/api/v1', discoveryClass: 'openai-compat' },
]

function model(id: string, over: Partial<ProviderModel> = {}): ProviderModel {
  return { id, name: id, enabled: true, source: 'live', capabilities: { streaming: 'verified', tools: 'verified', vision: 'unknown' }, ...over }
}

function key(over: Partial<ConnectionKey> & { id: string }): ConnectionKey {
  return { label: over.id, prefix: 'sk-or-', state: 'ready', cooldownUntil: null, resetAt: null, lastErrorCode: null, lastErrorMessage: null, lastUsedAt: null, ...over }
}

/** A connection whose snapshot carries a key ring; `keys` absent is the legacy shape. */
function connection(over: Partial<ProviderConnection> & { id: string; providerId: string; name: string }): ProviderConnection {
  return {
    endpoint: null, email: null, accountLabel: null, projectId: null, revision: 1, enabled: true, credentialPresent: true,
    authState: 'ready', projectState: 'not_applicable', discoveryState: 'ready', inferenceState: 'unknown',
    models: [model('gpt-5-mini')], lastTestedAt: null, error: null, quota: null, ...over,
  }
}

function snapshotWith(connections: ProviderConnection[]): ProviderSnapshot {
  return { providers, connections, aliases: [], keys: [], usage: [], defaultRoute: { connectionId: null, modelId: null, aliasId: null }, health: { status: 'ok', version: 'test' } }
}

const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'content-type': 'application/json' } })
const buttonIn = (scope: HTMLElement, text: string) => [...scope.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.trim() === text)
const ringRows = () => [...host.querySelectorAll<HTMLLIElement>('ul[role="list"] > li')]
/** The ring block itself, found by its own heading — the card around it holds other buttons. */
const ringBlock = () => [...host.querySelectorAll<HTMLParagraphElement>('p')].find((p) => p.textContent === 'Keys on this connection')!.closest<HTMLDivElement>('div.rounded-lg')!

function setValue(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

let root: Root
let host: HTMLDivElement
beforeEach(() => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  useProviderStore.setState({ snapshot: null, error: null, busy: false, loading: false })
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals(); vi.useRealTimers() })

const mount = () => act(async () => root.render(<ProviderView initialTab="api" />))

describe('Connection key ring', () => {
  it('shows an empty ring as one honest sentence plus the way to add the first key', async () => {
    const empty = connection({ id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key', keys: [] })
    vi.stubGlobal('fetch', vi.fn(async () => json(snapshotWith([empty]))))
    useProviderStore.setState({ snapshot: snapshotWith([empty]) })
    await mount()

    expect(host.textContent).toContain('Keys on this connection')
    expect(host.textContent).toContain('0 keys')
    expect(host.textContent).toContain('Rotates automatically when a key runs out of quota.')
    expect(host.textContent).toContain('No key on this connection yet.')
    expect(buttonIn(ringBlock(), 'Add key')).toBeTruthy()
  })

  it('adds a key with exactly one POST, keeps the secret out of the page and forgets it after save', async () => {
    const before = connection({ id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key', keys: [key({ id: 'key-1', label: 'Key 1' })] })
    let state = snapshotWith([before])
    const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
      if (init.method === 'POST' && String(url).endsWith('/keys')) {
        state = snapshotWith([connection({ ...before, revision: 2, keys: [...before.keys!, key({ id: 'key-2', label: 'Key 2' })] })])
        return json(state.connections[0], 201)
      }
      return json(state)
    })
    vi.stubGlobal('fetch', fetchMock)
    useProviderStore.setState({ snapshot: state })
    await mount()

    act(() => buttonIn(ringBlock(), 'Add key')!.click())
    const form = ringBlock()
    const label = [...form.querySelectorAll<HTMLInputElement>('input')].find((input) => input.type !== 'password')!
    const secret = form.querySelector<HTMLInputElement>('input[type="password"]')!
    act(() => { setValue(label, 'Key 2'); setValue(secret, SECRET) })
    expect(secret.value).toBe(SECRET)
    await act(async () => buttonIn(form, 'Save')!.click())

    const created = fetchMock.mock.calls.filter((call) => String(call[0]).endsWith('/keys') && (call[1] as RequestInit | undefined)?.method === 'POST')
    expect(created).toHaveLength(1)
    expect(created[0][0]).toBe(`${ENDPOINT_KEY}/keys`)
    expect(JSON.parse(String((created[0][1] as RequestInit).body))).toEqual({ key: SECRET, label: 'Key 2' })
    expect(ringRows()).toHaveLength(2)
    expect(host.textContent).toContain('Key 2')
    expect(host.textContent).not.toContain(SECRET)
    expect(host.querySelector<HTMLInputElement>('input[type="password"]')?.value ?? '').toBe('')
  })

  it('closes the form after a refused save and leaves the message to the page banner', async () => {
    const before = connection({ id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key', keys: [key({ id: 'key-1', label: 'Key 1' })] })
    const message = 'Key rejected by the provider.'
    const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
      if (init.method === 'POST' && String(url).endsWith('/keys')) return json({ error: { code: 'AUTH', message, retryable: false } }, 403)
      return json(snapshotWith([before]))
    })
    vi.stubGlobal('fetch', fetchMock)
    useProviderStore.setState({ snapshot: snapshotWith([before]) })
    await mount()

    act(() => buttonIn(ringBlock(), 'Add key')!.click())
    const field = ringBlock().querySelector<HTMLInputElement>('input[type="password"]')!
    act(() => setValue(field, SECRET))
    expect(field.value).toBe(SECRET)
    await act(async () => buttonIn(ringBlock(), 'Save')!.click())

    expect(fetchMock.mock.calls.some((call) => call[0] === `${ENDPOINT_KEY}/keys` && call[1]?.method === 'POST')).toBe(true)
    // The banner says what the router said; the form is gone and the typed secret with it.
    expect(host.textContent).toContain(message)
    expect(ringBlock().textContent).not.toContain(SECRET)
    expect(host.querySelector('input[type="password"]')).toBeNull()
  })

  it('removes one key with DELETE and shows the empty ring again when it was the last', async () => {
    const before = connection({ id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key', keys: [key({ id: 'key-1', label: 'Key 1' })] })
    let state = snapshotWith([before])
    const fetchMock = vi.fn(async (_url: string, init: RequestInit = {}) => {
      if (init.method === 'DELETE') {
        state = snapshotWith([connection({ ...before, revision: 2, credentialPresent: false, authState: 'required', keys: [] })])
        return json(state.connections[0])
      }
      return json(state)
    })
    vi.stubGlobal('fetch', fetchMock)
    useProviderStore.setState({ snapshot: state })
    await mount()

    await act(async () => buttonIn(ringRows()[0], 'Remove key')!.click())
    const removed = fetchMock.mock.calls.filter((call) => (call[1] as RequestInit | undefined)?.method === 'DELETE')
    expect(removed).toHaveLength(1)
    expect(removed[0][0]).toBe(`${ENDPOINT_KEY}/keys/key-1`)
    expect(host.textContent).toContain('No key on this connection yet.')
    expect(buttonIn(ringBlock(), 'Add key')).toBeTruthy()
  })

  it('counts a cooling key down every second and lets Try now take it out of the cooldown', async () => {
    vi.useFakeTimers()
    const parked = connection({
      id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key',
      keys: [key({ id: 'key-1', label: 'Key 1', state: 'cooling', cooldownUntil: Date.now() + 30_000, lastErrorCode: 'RATE_LIMIT', lastErrorMessage: '429 rate limit' })],
    })
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit = {}) => json(snapshotWith([parked])))
    vi.stubGlobal('fetch', fetchMock)
    useProviderStore.setState({ snapshot: snapshotWith([parked]) })
    await mount()

    expect(host.textContent).toMatch(/cooling · \d/)
    expect(host.textContent).toContain('30s')
    expect(host.textContent).toContain('429 rate limit')
    await act(async () => { vi.advanceTimersByTime(1000) })
    expect(host.textContent).toContain('29s')

    await act(async () => buttonIn(ringRows()[0], 'Try now')!.click())
    expect(fetchMock.mock.calls.some((call) => call[0] === `${ENDPOINT_KEY}/keys/key-1/try` && (call[1] as RequestInit).method === 'POST')).toBe(true)
  })

  it('labels a quota parking as exhausted and says when the quota opens', async () => {
    const parked = connection({
      id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key',
      keys: [key({ id: 'key-1', label: 'Key 1', state: 'exhausted', cooldownUntil: Date.now() + 60_000, resetAt: Date.now() + 3_600_000 })],
    })
    vi.stubGlobal('fetch', vi.fn(async () => json(snapshotWith([parked]))))
    useProviderStore.setState({ snapshot: snapshotWith([parked]) })
    await mount()

    expect(host.textContent).toContain('quota exhausted')
    expect(host.textContent).toContain('quota opens ')
    expect(buttonIn(ringRows()[0], 'Try now')).toBeTruthy()
  })

  it('prints one line for a failed key and keeps its code in the title', async () => {
    // Deliberately free of long unbroken runs: `scrub` redacts those (case 7 below).
    const message = 'Provider rejected the saved key with HTTP 403.'
    const broken = connection({
      id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key',
      keys: [key({ id: 'key-1', label: 'Key 1', state: 'error', lastErrorCode: 'AUTH', lastErrorMessage: message, lastUsedAt: Date.now() - 60_000 })],
    })
    vi.stubGlobal('fetch', vi.fn(async () => json(snapshotWith([broken]))))
    useProviderStore.setState({ snapshot: snapshotWith([broken]) })
    await mount()

    expect(host.textContent).toContain('error')
    expect(host.textContent).toContain(message)
    expect(host.textContent).toContain('AUTH')
    expect(host.textContent).toContain('last used ')
    const line = [...host.querySelectorAll<HTMLSpanElement>('span')].find((span) => span.textContent === message)!
    expect(line.getAttribute('title')).toBe('AUTH')
  })

  it('never prints a whole key: only leading characters survive, and a key-shaped error line is redacted', async () => {
    const leaky = connection({
      id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key',
      keys: [key({ id: 'key-1', label: 'Key 1', prefix: SECRET, state: 'error', lastErrorCode: 'UPSTREAM_HTTP', lastErrorMessage: `Upstream rejected ${SECRET} for this model.` })],
    })
    vi.stubGlobal('fetch', vi.fn(async () => json(snapshotWith([leaky]))))
    useProviderStore.setState({ snapshot: snapshotWith([leaky]) })
    await mount()

    expect(host.textContent).not.toContain(SECRET)
    expect(host.textContent).toContain('sk-or-…')
    expect(host.textContent).toContain('<redacted>')
  })

  it('handles a connection the router did not decorate without crashing', async () => {
    const legacy = connection({ id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key' })
    vi.stubGlobal('fetch', vi.fn(async () => json(snapshotWith([legacy]))))
    useProviderStore.setState({ snapshot: snapshotWith([legacy]) })
    await mount()

    expect(host.textContent).not.toContain('Keys on this connection')
    expect(host.querySelector('input[type="password"]')).toBeNull()
  })
})
