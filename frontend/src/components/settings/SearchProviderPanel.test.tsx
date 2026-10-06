import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useProviderStore } from '../../store/providerStore'
import type { ProviderSnapshot, SearchProviderId, SearchProviderView, SearchSnapshot } from '../../types/provider'
import { ProviderView } from './ProviderView'
import { SearchProviderModal } from './SearchProviderModal'
import { SEARCH_KEY_REVEAL_MS } from './SearchProviderPanel'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

/** The eight catalog entries exactly as the router describes them (router/src/search.mjs). */
const CATALOG: Array<Pick<SearchProviderView, 'id' | 'name' | 'requires' | 'optional' | 'envKeys' | 'icon'>> = [
  { id: 'brave', name: 'Brave Search', requires: ['apiKey'], optional: [], envKeys: ['BRAVE_API_KEY', 'BOXFOX_BRAVE_API_KEY'], icon: 'brave-search' },
  { id: 'tavily', name: 'Tavily', requires: ['apiKey'], optional: [], envKeys: ['TAVILY_API_KEY'], icon: 'tavily' },
  { id: 'exa', name: 'Exa', requires: ['apiKey'], optional: [], envKeys: ['EXA_API_KEY'], icon: 'exa' },
  { id: 'parallel', name: 'Parallel', requires: ['apiKey'], optional: [], envKeys: ['PARALLEL_API_KEY'], icon: null },
  { id: 'firecrawl', name: 'Firecrawl', requires: ['apiKey'], optional: [], envKeys: ['FIRECRAWL_API_KEY'], icon: 'firecrawl' },
  { id: 'searxng', name: 'SearXNG (self-hosted)', requires: ['endpoint'], optional: [], envKeys: ['BOXFOX_SEARXNG_URL'], icon: 'searxng' },
  { id: 'cloudflare', name: 'Cloudflare Web Search', requires: ['accountId', 'apiKey'], optional: [], envKeys: [], icon: 'cloudflare-ai' },
  { id: 'custom', name: 'Custom search endpoint', requires: ['endpoint'], optional: ['apiKey'], envKeys: [], icon: 'custom' },
]

const RAW_KEY = 'BSA12SECRET-VALUE-NEVER-RENDERED'

function providerView(over: Partial<SearchProviderView> & { id: SearchProviderId }): SearchProviderView {
  const base = CATALOG.find((entry) => entry.id === over.id)!
  return {
    ...base, credentialPresent: false, hasSecret: false, prefix: null, endpoint: null, accountId: null,
    lastTestedAt: null, lastTest: null, ...over,
  }
}

function searchPage(over: Partial<SearchSnapshot> = {}): ProviderSnapshot {
  return {
    providers: [], connections: [], aliases: [], keys: [], usage: [],
    defaultRoute: { connectionId: null, modelId: null, aliasId: null },
    health: { status: 'ok', version: 'test' },
    search: { activeProviderId: null, revision: 1, providers: CATALOG.map((entry) => providerView({ id: entry.id })), ...over },
  }
}

const configuredBrave = providerView({
  id: 'brave', credentialPresent: true, hasSecret: true, prefix: 'BSA12…',
  lastTestedAt: '2026-10-06T10:00:00.000Z',
  lastTest: { status: 'passed', httpStatus: 200, latencyMs: 412, code: null, message: null },
})

interface Call { path: string; method: string; body: Record<string, unknown> | null }

const json = (payload: unknown, status = 200) => new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } })

function withProvider(page: ProviderSnapshot, id: string, patch: Partial<SearchProviderView>): ProviderSnapshot {
  const search = page.search!
  return { ...page, search: { ...search, providers: search.providers.map((entry) => (entry.id === id ? { ...entry, ...patch } : entry)) } }
}

/** A tiny stand-in for the seven search routes, so the panel sees the router's answer to
 *  its own writes instead of a frozen page. `holdTest` keeps the test route pending. */
function routerStub(initial: ProviderSnapshot, options: { holdTest?: Promise<void> } = {}) {
  const calls: Call[] = []
  let current = initial
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = String(url)
    const method = init.method ?? 'GET'
    const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
    calls.push({ path, method, body })
    if (path.endsWith('/test')) {
      if (options.holdTest) await options.holdTest
      return json({ ok: true, providerId: 'brave', status: 200, latencyMs: 412, code: null, message: null, sample: { title: 'BoxFox', url: 'https://example.test/' } })
    }
    if (path.endsWith('/reveal')) {
      const id = path.split('/search/providers/')[1].split('/')[0]
      return json({ id, key: RAW_KEY })
    }
    if (method === 'PUT' && path === '/api/router/search/active') {
      const activeProviderId = body?.providerId ?? null
      current = { ...current, search: { ...current.search!, activeProviderId: activeProviderId as SearchProviderId | null, revision: current.search!.revision + 1 } }
      return json({ activeProviderId, revision: current.search!.revision })
    }
    if (method === 'POST' && path === '/api/router/search/providers') {
      const providerId = String(body?.providerId) as SearchProviderId
      const apiKey = typeof body?.apiKey === 'string' ? body.apiKey : ''
      current = withProvider(current, providerId, {
        credentialPresent: true, hasSecret: Boolean(apiKey) || Boolean(body?.accountId),
        prefix: apiKey ? `${apiKey.slice(0, 6)}…` : null,
        endpoint: typeof body?.endpoint === 'string' ? body.endpoint : null,
        accountId: typeof body?.accountId === 'string' ? body.accountId : null,
      })
      return json(current.search!.providers.find((entry) => entry.id === providerId), 201)
    }
    if (method === 'PATCH' && path.includes('/search/providers/')) {
      const id = path.split('/search/providers/')[1]
      const patch: Partial<SearchProviderView> = {}
      if (typeof body?.endpoint === 'string') patch.endpoint = body.endpoint
      if (typeof body?.accountId === 'string') patch.accountId = body.accountId
      if (typeof body?.apiKey === 'string' && body.apiKey) {
        patch.hasSecret = true
        patch.prefix = `${body.apiKey.slice(0, 6)}…`
      }
      current = withProvider(current, id, patch)
      return json(current.search!.providers.find((entry) => entry.id === id))
    }
    if (method === 'DELETE' && path.includes('/search/providers/')) {
      const id = path.split('/search/providers/')[1]
      const search = current.search!
      current = {
        ...current,
        search: {
          ...search,
          activeProviderId: search.activeProviderId === id ? null : search.activeProviderId,
          providers: search.providers.map((entry) => (entry.id === id ? providerView({ id: entry.id }) : entry)),
        },
      }
      return json({ deleted: true })
    }
    return json(current)
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

let root: Root
let host: HTMLDivElement
beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  useProviderStore.setState({ snapshot: null, error: null, busy: false, loading: false })
})

/** The tab exactly as the Settings surface mounts it. */
async function renderPanel(page: ProviderSnapshot) {
  useProviderStore.setState({ snapshot: page, error: null, busy: false, loading: false })
  await act(async () => root.render(<I18nProvider><ProviderView initialTab="search" /></I18nProvider>))
}

async function renderModal(provider: SearchProviderView, onClose = () => undefined) {
  await act(async () => root.render(<I18nProvider><SearchProviderModal provider={provider} onClose={onClose} /></I18nProvider>))
}

const rowFor = (id: string) => host.querySelector<HTMLElement>(`[data-search-provider="${id}"]`)!
const buttonIn = (scope: HTMLElement, text: string) => [...scope.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.trim() === text)

function setValue(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('Search provider panel', () => {
  it('renders the eight providers, the default choice and the built-in explanation', async () => {
    routerStub(searchPage())
    await renderPanel(searchPage())

    expect(host.querySelectorAll('[data-search-provider]')).toHaveLength(9)
    for (const entry of CATALOG) expect(host.textContent).toContain(entry.name)
    expect(host.textContent).toContain('Default — built-in search (SearXNG)')
    expect(host.textContent).toContain('No API key needed')
    expect(host.textContent).toContain('In use: Default — built-in search (SearXNG)')
    expect(host.textContent).toContain('0/8 configured')
    expect(host.textContent).toContain('Or set BRAVE_API_KEY, BOXFOX_BRAVE_API_KEY on the host')
  })

  it('shows the stored prefix and never the raw key', async () => {
    routerStub(searchPage({ providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))) }))
    await renderPanel(searchPage({ providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))) }))

    expect(rowFor('brave').textContent).toContain('Saved · BSA12…')
    expect(host.textContent).not.toContain(RAW_KEY)
    expect(JSON.stringify(useProviderStore.getState().snapshot)).not.toContain(RAW_KEY)
  })

  it('selecting a provider sends PUT /api/router/search/active', async () => {
    const page = searchPage({ providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))) })
    const calls = routerStub(page)
    await renderPanel(page)

    await act(async () => buttonIn(rowFor('brave'), 'Use this')!.click())

    expect(calls).toContainEqual({ path: '/api/router/search/active', method: 'PUT', body: { providerId: 'brave' } })
    expect(host.textContent).toContain('In use: Brave Search')
  })

  it('the default row offers the switch back only while a named provider is active', async () => {
    const page = searchPage({
      activeProviderId: 'brave',
      providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))),
    })
    const calls = routerStub(page)
    await renderPanel(page)

    // Brave is in use: the header says so, and the Default row must offer "Use this"
    // instead of claiming to be the source in use itself.
    expect(host.textContent).toContain('In use: Brave Search')
    expect(buttonIn(rowFor('default'), 'Use this')).not.toBeUndefined()
    expect(rowFor('default').textContent).not.toContain('In use')

    await act(async () => buttonIn(rowFor('default'), 'Use this')!.click())

    expect(calls).toContainEqual({ path: '/api/router/search/active', method: 'PUT', body: { providerId: null } })
    expect(host.textContent).toContain('In use: Default — built-in search (SearXNG)')
    expect(buttonIn(rowFor('default'), 'Use this')).toBeUndefined()
    expect(rowFor('default').textContent).toContain('In use')
  })

  it('the modal posts the documented body for an api key provider', async () => {
    const page = searchPage()
    const calls = routerStub(page)
    await renderPanel(page)

    act(() => buttonIn(rowFor('brave'), 'Add key')!.click())
    const dialog = host.querySelector<HTMLElement>('[role="dialog"]')!
    expect(dialog.textContent).toContain('Add API key')
    await act(async () => setValue(dialog.querySelector<HTMLInputElement>('input[type="password"]')!, 'brave-key-123'))
    await act(async () => buttonIn(dialog, 'Save key')!.click())

    expect(calls).toContainEqual({ path: '/api/router/search/providers', method: 'POST', body: { providerId: 'brave', apiKey: 'brave-key-123' } })
    expect(host.querySelector('[role="dialog"]')).toBeNull()
    expect(rowFor('brave').textContent).toContain('Saved · brave-…')
  })

  it('the cloudflare form asks for both the account id and the key', async () => {
    await renderModal(providerView({ id: 'cloudflare' }))

    const dialog = host.querySelector<HTMLElement>('[role="dialog"]')!
    expect(dialog.textContent).toContain('Account ID')
    expect(dialog.textContent).toContain('API key')
    const save = () => buttonIn(dialog, 'Save key')!
    expect(save().disabled).toBe(true)

    await act(async () => setValue(dialog.querySelector<HTMLInputElement>('input[type="text"]')!, '8f14e45fceea167a'))
    expect(save().disabled).toBe(true)
    await act(async () => setValue(dialog.querySelector<HTMLInputElement>('input[type="password"]')!, 'cf-token'))
    expect(save().disabled).toBe(false)
  })

  it('reveal asks the router and hides the key again after the timeout', async () => {
    vi.useFakeTimers()
    const page = searchPage({ providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))) })
    const calls = routerStub(page)
    await renderPanel(page)

    await act(async () => buttonIn(rowFor('brave'), 'Reveal')!.click())

    expect(calls).toContainEqual({ path: '/api/router/search/providers/brave/reveal', method: 'POST', body: null })
    expect(rowFor('brave').textContent).toContain(RAW_KEY)
    expect(buttonIn(rowFor('brave'), 'Hide')).not.toBeUndefined()

    act(() => { vi.advanceTimersByTime(SEARCH_KEY_REVEAL_MS) })
    expect(host.textContent).not.toContain(RAW_KEY)
    expect(buttonIn(rowFor('brave'), 'Reveal')).not.toBeUndefined()
  })

  it('the test button reports the verdict without freezing the panel', async () => {
    let release: () => void = () => undefined
    const hold = new Promise<void>((resolve) => { release = resolve })
    const page = searchPage({ providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))) })
    routerStub(page, { holdTest: hold })
    await renderPanel(page)

    act(() => buttonIn(rowFor('brave'), 'Test')!.click())

    // The call is in flight: the global busy flag stays down, so the rest of the panel
    // (and every other settings surface) remains usable.
    expect(useProviderStore.getState().busy).toBe(false)
    expect(buttonIn(rowFor('brave'), 'Testing…')).not.toBeUndefined()
    expect(buttonIn(rowFor('brave'), 'Edit')!.disabled).toBe(false)

    await act(async () => { release() })
    expect(rowFor('brave').textContent).toContain('Passed · 412 ms')
    expect(useProviderStore.getState().busy).toBe(false)
  })

  it('deleting the active provider returns the selection to default', async () => {
    const page = searchPage({
      activeProviderId: 'brave',
      providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))),
    })
    const calls = routerStub(page)
    await renderPanel(page)
    expect(host.textContent).toContain('In use: Brave Search')

    await act(async () => buttonIn(rowFor('brave'), 'Delete')!.click())

    expect(calls).toContainEqual({ path: '/api/router/search/providers/brave', method: 'DELETE', body: null })
    expect(host.textContent).toContain('In use: Default — built-in search (SearXNG)')
    expect(rowFor('brave').textContent).toContain('Not configured')
    expect(rowFor('brave').textContent).not.toContain('BSA12…')
  })

  it('deleting a provider drops its fresh verdict and the revealed key with it', async () => {
    const page = searchPage({ providers: CATALOG.map((entry) => (entry.id === 'brave' ? configuredBrave : providerView({ id: entry.id }))) })
    routerStub(page)
    await renderPanel(page)

    await act(async () => buttonIn(rowFor('brave'), 'Reveal')!.click())
    expect(rowFor('brave').textContent).toContain(RAW_KEY)
    await act(async () => buttonIn(rowFor('brave'), 'Test')!.click())
    expect(rowFor('brave').textContent).toContain('Passed · 412 ms')

    await act(async () => buttonIn(rowFor('brave'), 'Delete')!.click())

    // The credential is gone from the router, so nothing about it may stay on screen:
    // not the test verdict, not the raw key.
    expect(rowFor('brave').textContent).toContain('Not configured')
    expect(rowFor('brave').textContent).not.toContain('Passed')
    expect(host.textContent).not.toContain(RAW_KEY)
  })

  it('a snapshot without a search section shows the disconnected state', async () => {
    const page = searchPage()
    delete page.search
    routerStub(page)
    await renderPanel(page)

    expect(host.textContent).toContain('Router not connected')
    expect(host.textContent).toContain('Update the router and reload this page')
    expect(host.querySelectorAll('[data-search-provider]')).toHaveLength(0)
  })

  it('the searxng form validates the endpoint url', async () => {
    const page = searchPage()
    routerStub(page)
    await renderPanel(page)

    act(() => buttonIn(rowFor('searxng'), 'Add key')!.click())
    const dialog = host.querySelector<HTMLElement>('[role="dialog"]')!
    const endpoint = dialog.querySelector<HTMLInputElement>('input[type="text"]')!
    const save = () => buttonIn(dialog, 'Save key')!

    await act(async () => setValue(endpoint, 'ftp://127.0.0.1:8888'))
    expect(dialog.textContent).toContain('must be a valid http/https URL')
    expect(save().disabled).toBe(true)

    await act(async () => setValue(endpoint, 'http://127.0.0.1:8888'))
    expect(save().disabled).toBe(false)
    expect(dialog.textContent).not.toContain('must be a valid http/https URL')
  })

  it('a custom endpoint without a key can be saved', async () => {
    const page = searchPage()
    const calls = routerStub(page)
    await renderPanel(page)

    act(() => buttonIn(rowFor('custom'), 'Add key')!.click())
    const dialog = host.querySelector<HTMLElement>('[role="dialog"]')!
    const endpoint = dialog.querySelector<HTMLInputElement>('input[type="text"]')!
    const save = () => buttonIn(dialog, 'Save key')!

    expect(save().disabled).toBe(true)                    // endpoint bắt buộc, còn trống
    await act(async () => setValue(endpoint, 'http://127.0.0.1:9999/search'))
    expect(save().disabled).toBe(false)                   // `optional: ['apiKey']` KHÔNG được chặn Lưu

    await act(async () => save().click())
    const posted = calls.find((call) => call.method === 'POST' && call.path === '/api/router/search/providers')
    expect(posted?.body).toEqual({ providerId: 'custom', endpoint: 'http://127.0.0.1:9999/search' })
  })

  it('the edit form saves with an empty key field and never sends an empty apiKey', async () => {
    const calls = routerStub(searchPage())
    const onClose = vi.fn()
    await renderModal(configuredBrave, onClose)

    const dialog = host.querySelector<HTMLElement>('[role="dialog"]')!
    const save = buttonIn(dialog, 'Save key')!
    expect(save.disabled).toBe(false)                     // đã có khoá lưu sẵn ⇒ không cần gõ lại

    await act(async () => save.click())
    const patched = calls.find((call) => call.method === 'PATCH')
    expect(patched?.path).toBe('/api/router/search/providers/brave')
    expect(patched?.body).toEqual({})                     // thiếu `apiKey` ⇒ router giữ nguyên khoá cũ
    expect(onClose).toHaveBeenCalled()
  })
})
