import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { ProviderView } from './ProviderView'
import { useProviderStore } from '../../store/providerStore'
import type { ConnectionKey, ProviderConnection, ProviderModel, ProviderSnapshot, RouterUsage } from '../../types/provider'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const snapshot: ProviderSnapshot = {
  providers: [
    { id: 'antigravity', name: 'Antigravity', authMethod: 'oauth', protocol: 'antigravity', icon: '/providers/antigravity.png', category: 'oauth', runtimeAvailable: true, availability: 'ready', routerVisible: true, discoveryClass: 'account-live' },
    { id: 'claude', name: 'Claude Code', authMethod: 'oauth', protocol: 'claude-code', icon: '/providers/claude.png', category: 'oauth', runtimeAvailable: false, availability: 'planned', routerVisible: true, discoveryClass: 'account-live' },
    { id: 'openrouter', name: 'OpenRouter', authMethod: 'api_key', protocol: 'openai', icon: '/providers/openrouter.png', category: 'free', runtimeAvailable: true, availability: 'ready', routerVisible: true, defaultEndpoint: 'https://openrouter.ai/api/v1', discoveryClass: 'openai-compat' },
    { id: 'openai', name: 'OpenAI', authMethod: 'api_key', protocol: 'openai', icon: '/providers/openai.svg' },
    { id: 'anthropic', name: 'Anthropic', authMethod: 'api_key', protocol: 'anthropic', icon: '/providers/anthropic.svg' },
    { id: 'gemini', name: 'Google Gemini', authMethod: 'api_key', protocol: 'gemini', icon: '/providers/gemini.svg' },
    { id: 'custom', name: 'OpenAI-compatible', authMethod: 'api_key', protocol: 'openai', icon: '/providers/custom.svg' },
  ], connections: [], aliases: [], keys: [], usage: [], defaultRoute: { connectionId: null, modelId: null, aliasId: null }, health: { status: 'ok', version: 'test' },
}
let root: Root
let host: HTMLDivElement
beforeEach(() => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  useProviderStore.setState({ snapshot, error: null, busy: false, loading: false })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(snapshot), { headers: { 'content-type': 'application/json' } })))
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals() })
type ProviderTab = 'api' | 'router' | 'search'
/** The tab always renders inside the app's i18n provider — the Web Search tab speaks
 *  through `useT()`, while the API/Router copy stays the English it always was. */
async function render(tab: ProviderTab) { await act(async () => root.render(<I18nProvider><ProviderView initialTab={tab} /></I18nProvider>)) }

/** The same render with another snapshot — the page reads the store, not the fetch reply. */
async function renderPage(page: ProviderSnapshot, tab: ProviderTab) {
  useProviderStore.setState({ snapshot: page, error: null, busy: false, loading: false })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(page), { headers: { 'content-type': 'application/json' } })))
  await render(tab)
}

function setValue(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function model(id: string, over: Partial<ProviderModel> = {}): ProviderModel {
  return { id, name: id, enabled: true, capabilities: { streaming: 'reported', tools: 'reported', vision: 'unknown' }, ...over }
}

function connection(over: Partial<ProviderConnection> & { id: string; providerId: string; name: string }): ProviderConnection {
  return {
    endpoint: null, email: null, accountLabel: null, projectId: null, revision: 1, enabled: true, credentialPresent: true,
    authState: 'ready', projectState: 'not_applicable', discoveryState: 'ready', inferenceState: 'unknown',
    lastTestedAt: null, error: null, quota: null, models: [], ...over,
  }
}

function connectionKey(over: Partial<ConnectionKey> & { id: string }): ConnectionKey {
  return { label: over.id, prefix: 'sk-or-', state: 'ready', cooldownUntil: null, resetAt: null, lastErrorCode: null, lastErrorMessage: null, lastUsedAt: null, ...over }
}

const twoProviderSnapshot: ProviderSnapshot = {
  ...snapshot,
  connections: [
    connection({ id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key', models: [model('a'), model('b'), model('c')] }),
    connection({ id: 'openai-key', providerId: 'openai', name: 'OpenAI key', models: [model('d')] }),
  ],
}

/** One provider, two connections that both failed to list models and both carry a model typed
 *  by hand: the first kept a key the provider accepted (the router routes that model), the
 *  second has no accepted key (the router routes nothing there). */
const handTypedSnapshot: ProviderSnapshot = {
  ...snapshot,
  connections: [
    connection({
      id: 'openrouter-hand', providerId: 'openrouter', name: 'OpenRouter by hand', discoveryState: 'failed',
      models: [model('muse-spark-1.3-contributor-free', { source: 'custom' })],
    }),
    connection({
      id: 'openrouter-refused', providerId: 'openrouter', name: 'OpenRouter refused', discoveryState: 'failed',
      authState: 'required', credentialPresent: false,
      models: [model('ghost-model', { source: 'custom' })],
    }),
  ],
}

const railRows = () => [...document.querySelectorAll<HTMLButtonElement>('[data-provider-row]')]
const selectedRows = () => railRows().filter((row) => row.getAttribute('aria-current') === 'true').map((row) => row.getAttribute('data-provider-row'))
const buttonIn = (scope: HTMLElement, text: string) => [...scope.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.trim() === text)

/** The Router tab with one `openrouter` connection, its card open — the non-OAuth card that
 *  owns the key ring. `keys` absent is the legacy snapshot the pre-round-29 router serves. */
async function renderRouterCard(row: ProviderConnection) {
  const page: ProviderSnapshot = { ...snapshot, connections: [row] }
  const calls: Array<{ url: string; method: string; body: unknown }> = []
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    calls.push({ url: String(url), method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : null })
    return new Response(JSON.stringify(page), { headers: { 'content-type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetchMock)
  useProviderStore.setState({ snapshot: page, error: null, busy: false, loading: false })
  await render('router')
  act(() => host.querySelector<HTMLButtonElement>('[data-provider-row="openrouter"]')!.click())
  return calls
}

function usageRow(over: Partial<RouterUsage> & { id: string }): RouterUsage {
  return {
    requestId: `req-${over.id}`, connectionId: null, modelId: null, aliasId: null, clientKeyId: null, status: 'passed', latencyMs: 120,
    inputTokens: null, cachedTokens: null, cacheCreationTokens: null, reasoningTokens: null, outputTokens: null, totalTokens: null,
    cost: null, error: null, createdAt: '2026-09-20T02:00:00.000Z', ...over,
  }
}

// One row per provenance, plus the two nulls that must stay distinguishable.
const costSnapshot: ProviderSnapshot = {
  ...snapshot,
  providers: [...snapshot.providers, { id: 'deepseek', name: 'DeepSeek', authMethod: 'api_key', protocol: 'openai', icon: '/providers/deepseek.svg' }],
  connections: [
    connection({ id: 'deepseek-connection', providerId: 'deepseek', name: 'DeepSeek', costMode: 'metered', models: [model('deepseek-flash')] }),
    connection({ id: 'antigravity-connection', providerId: 'antigravity', name: 'Antigravity account', costMode: 'included', models: [model('gemini-3.8-flash-high')] }),
  ],
  usage: [
    usageRow({ id: 'documented', connectionId: 'deepseek-connection', modelId: 'deepseek-flash', cost: 0.000079, costBasis: 'documented', estimated: true, inputTokens: 11965, cachedTokens: 11776, outputTokens: 25, createdAt: '2026-09-20T11:00:00.000Z' }),
    usageRow({ id: 'peak', connectionId: 'deepseek-connection', modelId: 'deepseek-flash', cost: 0.00021, costBasis: 'documented', estimated: true, createdAt: '2026-09-18T02:30:00.000Z' }),
    usageRow({ id: 'reported', connectionId: 'openrouter', modelId: '~deepseek/deepseek-pro-latest', cost: 0.00624294528, costBasis: 'reported', estimated: false, createdAt: '2026-09-20T15:01:57.574Z' }),
    usageRow({ id: 'unpriced', connectionId: 'deepseek-connection', modelId: 'deepseek-v4-pro', createdAt: '2026-09-20T12:30:00.000Z' }),
    usageRow({ id: 'included', connectionId: 'antigravity-connection', modelId: 'gemini-3.8-flash-high', createdAt: '2026-09-20T12:31:00.000Z' }),
    usageRow({ id: 'free', connectionId: 'deepseek-connection', modelId: 'deepseek-flash', cost: 0, costBasis: 'reported', estimated: false, createdAt: '2026-09-20T12:32:00.000Z' }),
  ],
}

/** The Cost cell of the usage row carrying `requestId`. */
function costCell(requestId: string) {
  const row = [...host.querySelectorAll('tr')].find((candidate) => candidate.textContent?.includes(requestId))!
  return [...row.querySelectorAll('td')][7]
}

/** The title of that cell — how BoxFox explains where the number came from. */
function costTitle(requestId: string) {
  return costCell(requestId).querySelector('[title]')?.getAttribute('title') ?? null
}

async function renderUsage() {
  useProviderStore.setState({ snapshot: costSnapshot, error: null, busy: false, loading: false })
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(costSnapshot), { headers: { 'content-type': 'application/json' } })))
  await render('router')
  const usage = [...host.querySelectorAll('button')].find(button => button.textContent === 'Usage & Analytics')!
  act(() => usage.click())
}

describe('Provider UI', () => {
  it('exposes api, router and web search tabs and walks all three with the keyboard', async () => {
    await render('api')
    expect([...host.querySelectorAll('[role="tab"]')].map((tab) => tab.textContent)).toEqual(['API', 'Router', 'Web Search'])
    const press = (id: string, key: string) =>
      act(() => host.querySelector<HTMLButtonElement>(`#provider-tab-${id}`)!.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })))
    const selected = () => host.querySelector('[role="tab"][aria-selected="true"]')?.id

    press('api', 'End')
    expect(selected()).toBe('provider-tab-search')
    expect(host.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe('provider-tab-search')
    press('search', 'ArrowRight')
    expect(selected()).toBe('provider-tab-api')
    press('api', 'ArrowLeft')
    expect(selected()).toBe('provider-tab-search')
    press('search', 'Home')
    expect(selected()).toBe('provider-tab-api')
  })
  it('renders the web search tab inside the provider surface', async () => {
    const withSearch: ProviderSnapshot = {
      ...snapshot,
      search: {
        activeProviderId: 'brave',
        revision: 3,
        providers: [
          { id: 'brave', name: 'Brave Search', requires: ['apiKey'], optional: [], envKeys: ['BRAVE_API_KEY'], icon: 'brave-search', credentialPresent: true, hasSecret: true, prefix: 'BSA12…', endpoint: null, accountId: null, lastTestedAt: null, lastTest: null },
          { id: 'searxng', name: 'SearXNG (self-hosted)', requires: ['endpoint'], optional: [], envKeys: ['BOXFOX_SEARXNG_URL'], icon: 'searxng', credentialPresent: false, hasSecret: false, prefix: null, endpoint: null, accountId: null, lastTestedAt: null, lastTest: null },
        ],
      },
    }
    await renderPage(withSearch, 'search')

    expect(host.textContent).toContain('Search API sources')
    expect(host.textContent).toContain('In use: Brave Search')
    expect(host.querySelector('[data-search-provider="default"]')).not.toBeNull()
    expect(host.querySelector('[data-search-provider="brave"]')!.textContent).toContain('Saved · BSA12…')
    expect(host.textContent).toContain('SearXNG (self-hosted)')
    // The provider surface's own chrome is untouched by the new tab.
    expect(host.textContent).toContain('Router engine ok')
  })
  it('shows all API adapters with local icons and no redundant close button', async () => {
    await render('api')
    expect([...host.querySelectorAll('img')].map(image => image.alt)).toEqual(['OpenRouter icon', 'OpenAI icon', 'Anthropic icon', 'Google Gemini icon', 'OpenAI-compatible icon'])
    expect(host.querySelector('[aria-label*="Close"]')).toBeNull()
    expect(host.textContent).toContain('Router engine ok')
    expect(host.textContent).toContain('No API connection configured yet.')
  })
  it('switches top-level tabs with arrow keys and binds the active tabpanel', async () => {
    await render('api')
    const apiTab = host.querySelector<HTMLButtonElement>('#provider-tab-api')!
    act(() => apiTab.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
    expect(host.querySelector('#provider-tab-router')?.getAttribute('aria-selected')).toBe('true')
    expect(host.querySelector('[role="tabpanel"]')?.getAttribute('aria-labelledby')).toBe('provider-tab-router')
    expect(host.textContent).toContain('Router providers')
  })
  it('provides common router management and an OpenAI-compatible endpoint example', async () => {
    await render('router')
    const access = [...host.querySelectorAll('button')].find(button => button.textContent === 'API Access')!
    act(() => access.click())
    expect(host.textContent).toContain('BoxFox endpoint')
    expect(host.textContent).toContain('/v1/chat/completions')
    expect(host.textContent).toContain('YOUR_BOXFOX_KEY')
    expect(host.textContent).toContain('No client keys created.')
  })
  it('shows the router provider catalog and honest empty model inventory before login', async () => {
    await render('router')
    expect(host.textContent).toContain('OAuth accounts')
    expect(host.textContent).toContain('No connections')
    const antigravity = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('Antigravity'))!
    act(() => antigravity.click())
    expect(host.textContent).toContain('Connections & models')
    expect(host.textContent).toContain('Add account')
    const back = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('Back to providers'))!
    act(() => back.click())
    expect(host.textContent).toContain('Claude Code')
    const models = [...host.querySelectorAll('button')].find(button => button.textContent === 'Models')!
    act(() => models.click())
    expect(host.textContent).toContain('Available models')
    expect(host.textContent).toContain('Provider sources')
    expect(host.textContent).toContain('No live models yet.')
  })
  it('shows token analytics with unknown values until a provider reports usage', async () => {
    await render('router')
    const usage = [...host.querySelectorAll('button')].find(button => button.textContent === 'Usage & Analytics')!
    act(() => usage.click())
    expect(host.textContent).toContain('Usage & analytics')
    expect(host.textContent).toContain('Input tokens')
    expect(host.textContent).toContain('Token composition')
    expect(host.textContent).toContain('No data')
  })
  it('lists every API provider in a rail whose group headings carry a count and a single current row', async () => {
    await render('api')
    expect(railRows().map(row => row.getAttribute('data-provider-row'))).toEqual(['openrouter', 'openai', 'anthropic', 'gemini', 'custom'])
    expect(selectedRows()).toEqual(['openrouter'])
    const headings = [...host.querySelectorAll<HTMLButtonElement>('button[aria-controls]')].filter(button => /Free Tier|API keys/.test(button.textContent ?? ''))
    expect(headings).toHaveLength(2)
    expect(headings[0].textContent).toContain('Free Tier')
    expect(headings[0].textContent).toContain('1')
    expect(headings[1].textContent).toContain('API keys')
    expect(headings[1].textContent).toContain('4')
    expect(railRows()[0].textContent).toContain('No connection · needs key')
  })
  it('narrows the rail to the searched provider and follows the selection in the pane header', async () => {
    await render('api')
    const search = host.querySelector<HTMLInputElement>('input[aria-label="Search providers"]')!
    await act(async () => { setValue(search, 'zzz') })
    expect(host.textContent).toContain('No provider matches "zzz".')
    await act(async () => { setValue(search, 'gemini') })
    expect(railRows().map(row => row.getAttribute('data-provider-row'))).toEqual(['gemini'])
    expect(host.querySelector('h2')!.textContent).toBe('OpenRouter')
    act(() => railRows()[0].click())
    expect(host.querySelector('h2')!.textContent).toBe('Google Gemini')
    expect(selectedRows()).toEqual(['gemini'])
  })
  it('shows only the selected provider connections and marks the other provider row with its own counts', async () => {
    useProviderStore.setState({ snapshot: twoProviderSnapshot, error: null, busy: false, loading: false })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(twoProviderSnapshot), { headers: { 'content-type': 'application/json' } })))
    await render('api')
    expect(host.querySelector('[data-provider-row="openrouter"]')!.textContent).toContain('1 connection ready')
    expect(host.querySelector('[data-provider-row="openai"]')!.textContent).toContain('1 connection ready')
    expect(host.textContent).toContain('2 connected')
    expect(host.textContent).toContain('OpenRouter key')
    expect(host.textContent).not.toContain('OpenAI key')
    act(() => host.querySelector<HTMLButtonElement>('[data-provider-row="openai"]')!.click())
    expect(host.textContent).toContain('OpenAI key')
    expect(host.textContent).not.toContain('OpenRouter key')
  })
  it('moves the current provider row with ArrowDown', async () => {
    await render('api')
    act(() => railRows()[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })))
    expect(selectedRows()).toEqual(['openai'])
    act(() => railRows()[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'End', bubbles: true })))
    expect(selectedRows()).toEqual(['custom'])
  })
  it('displays all providers in groups without disclosure buttons', async () => {
    const wide: ProviderSnapshot = {
      ...snapshot,
      providers: [
        ...snapshot.providers.filter(provider => provider.authMethod !== 'api_key'),
        ...['openrouter', 'openai', 'anthropic', 'gemini', 'custom', 'groq', 'mistral'].map((id, index) => ({
          id, name: id, authMethod: 'api_key' as const, protocol: 'openai' as const, icon: `/providers/${id}.svg`, ...(index === 0 ? { category: 'free' as const } : {}),
        })),
      ],
    }
    useProviderStore.setState({ snapshot: wide, error: null, busy: false, loading: false })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(wide), { headers: { 'content-type': 'application/json' } })))
    await render('api')
    expect(railRows()).toHaveLength(7)
    const more = [...host.querySelectorAll<HTMLButtonElement>('button[aria-controls]')].find(button => button.textContent?.includes('Show'))
    expect(more).toBeUndefined()
  })
  it('lists the router providers in the same rail, marks the selection and counts each group', async () => {
    await render('router')
    expect(railRows().map(row => row.getAttribute('data-provider-row'))).toEqual(['antigravity', 'claude', 'openrouter'])
    expect(selectedRows()).toEqual([])
    const headings = [...host.querySelectorAll<HTMLButtonElement>('button[aria-controls]')].filter(button => /OAuth accounts|Free Tier/.test(button.textContent ?? ''))
    expect(headings).toHaveLength(2)
    expect(headings[0].textContent).toContain('OAuth accounts')
    expect(headings[0].textContent).toContain('2')
    expect(headings[1].textContent).toContain('Free Tier')
    expect(headings[1].textContent).toContain('1')
    expect(host.querySelector('[data-provider-rail]')!.textContent).toContain('No connections')
    expect(host.textContent).toContain('Pick one on the left')
    expect(host.textContent).toContain('API-key providers remain available in the API tab.')
    act(() => host.querySelector<HTMLButtonElement>('[data-provider-row="claude"]')!.click())
    expect(selectedRows()).toEqual(['claude'])
    expect(host.textContent).toContain('Connections & models')
    act(() => host.querySelector<HTMLButtonElement>('[data-provider-row="openrouter"]')!.click())
    expect(selectedRows()).toEqual(['openrouter'])
    expect(host.textContent).toContain('Free Tier · discovery: openai-compat')
    expect(host.textContent).toContain('Add connection')
  })
  it('keeps the single-key input on the router tab when the snapshot carries no key ring', async () => {
    // The owner's live router is still the build without key rings: the connection has a
    // credential and no `keys` array. That card must keep the one input that router honours.
    const calls = await renderRouterCard(connection({ id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key' }))
    // The tab also holds the provider's own `Add connection` form, which has a key field of its
    // own; every assertion below is scoped to the connection card.
    const card = () => buttonIn(host, 'Update key/token')!.closest<HTMLElement>('article')!
    expect(card().textContent).not.toContain('Keys on this connection')
    expect(card().textContent).not.toContain('No key on this connection yet.')
    expect(card().querySelector('input[type="password"]')).toBeNull()

    act(() => buttonIn(card(), 'Update key/token')!.click())
    expect(card().textContent).toContain('Update API key')
    const field = card().querySelector<HTMLInputElement>('input[type="password"]')!
    act(() => setValue(field, 'sk-or-v1-legacy'))
    await act(async () => buttonIn(card(), 'Save')!.click())

    const patched = calls.filter((call) => call.method === 'PATCH')
    expect(patched.map((call) => call.url)).toEqual(['/api/router/connections/openrouter-key'])
    expect(patched[0].body).toEqual({ apiKey: 'sk-or-v1-legacy' })
    expect(card().querySelector('input[type="password"]')).toBeNull()
  })
  it('mounts the key ring on the router tab and drops the duplicate single-key input', async () => {
    await renderRouterCard(connection({
      id: 'openrouter-key', providerId: 'openrouter', name: 'OpenRouter key',
      keys: [connectionKey({ id: 'key-1', label: 'Key 1' })],
    }))
    act(() => buttonIn(host, 'Show keys')!.click())
    const card = buttonIn(host, 'Hide keys')!.closest<HTMLElement>('article')!

    expect(card.textContent).toContain('Keys on this connection')
    expect(card.textContent).toContain('1 keys')
    expect(card.textContent).not.toContain('Update API key')
    expect(card.textContent).not.toContain('No key on this connection yet.')
    expect(card.querySelector('input[type="password"]')).toBeNull()
  })
  it("keeps a failed listing's hand-typed models in the provider model list", async () => {
    // The router routes a model the user typed by hand even when the connection could not list
    // its models (`validTarget` in router/src/service.mjs); `routable` answers with that rule.
    // Asking `discoveryState === 'ready'` alone dropped this connection's row, its Test button
    // and its toggle entirely (round 29 review).
    await renderPage(handTypedSnapshot, 'api')
    expect(host.textContent).toContain('One row per model · served by 1 connection.')
    expect(host.querySelector('input[aria-label="Enable muse-spark-1.3-contributor-free"]')).not.toBeNull()
    expect(host.textContent).toContain('muse-spark-1.3-contributor-free')
    // A connection the router cannot reach contributes nothing — not even the block's empty
    // state, because the block is the list itself, not a placeholder for missing connections.
    expect(host.querySelector('input[aria-label="Enable ghost-model"]')).toBeNull()
    expect(host.textContent).not.toContain('ghost-model')
  })
  it('renders the same model list on the router tab for a failed listing', async () => {
    // The router tab computes its own connection list; the two tabs must agree on who is in it.
    await renderPage(handTypedSnapshot, 'router')
    act(() => host.querySelector<HTMLButtonElement>('[data-provider-row="openrouter"]')!.click())
    expect(host.textContent).toContain('One row per model · served by 1 connection.')
    expect(host.querySelector('input[aria-label="Enable muse-spark-1.3-contributor-free"]')).not.toBeNull()
    expect(host.querySelector('input[aria-label="Enable ghost-model"]')).toBeNull()
  })
  it('offers a failed listing\u2019s hand-typed model as a routing target and no unreachable one', async () => {
    // The same rule feeds the Routing and alias pickers: a target offered there must be one the
    // router accepts, and one it accepts must not be missing.
    await renderPage(handTypedSnapshot, 'router')
    act(() => [...host.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent === 'Routing')!.click())
    const options = [...host.querySelectorAll('option')].map((option) => option.textContent)
    expect(options).toContain('OpenRouter by hand / muse-spark-1.3-contributor-free')
    expect(options.some((label) => label?.includes('ghost-model'))).toBe(false)
  })
  it('labels every cost cell with its provenance and says when no price is known', async () => {
    await renderUsage()
    const documented = costCell('req-documented')
    expect(documented.textContent).toContain('<$0.0001')
    expect(documented.textContent).toContain('est.')
    // The published peak window excludes Chinese public holidays and that calendar is
    // not shipped, so the tooltip that names the source also names the caveat.
    expect(costTitle('req-documented')).toContain('Estimated from the documented DeepSeek price (off-peak at 11:00 UTC)')
    expect(costTitle('req-documented')).toContain('Chinese public holidays are excluded from the published peak window')
    const peak = costCell('req-peak')
    expect(peak.textContent).toContain('$0.0002')
    expect(peak.textContent).toContain('est.')
    expect(costTitle('req-peak')).toContain('Estimated from the documented DeepSeek price (peak)')
    expect(costTitle('req-peak')).toContain('estimate up to 2× high')
    const reported = costCell('req-reported')
    expect(reported.textContent).toBe('$0.0062')
    expect(costTitle('req-reported')).toBe('Reported by the provider')
    const free = costCell('req-free')
    expect(free.textContent).toBe('$0')
    expect(costTitle('req-free')).toBe('Reported by the provider')
    expect(costCell('req-unpriced').textContent).toBe('No price')
    expect(costTitle('req-unpriced')).toBe('Set a price for this model in Providers → Manage models')
    expect(costCell('req-included').textContent).toBe('Included in plan')
    expect(costTitle('req-included')).toContain('subscription')
    expect(host.textContent).toContain('Reported 2 · Estimated 2 · No price 1 · Included 1')
    expect(host.textContent).toContain('Includes estimates')
    expect(host.textContent).toContain('$0.0065')
  })
  it('counts the models that carry a price on the connection card', async () => {
    const priced: ProviderSnapshot = {
      ...snapshot,
      providers: [{ id: 'deepseek', name: 'DeepSeek', authMethod: 'api_key', protocol: 'openai', icon: '/providers/deepseek.svg' }, ...snapshot.providers],
      connections: [
        connection({
          id: 'deepseek-connection', providerId: 'deepseek', name: 'DeepSeek',
          models: [
            model('deepseek-flash', { pricing: { currency: 'USD', unit: 'per_million_tokens', input: 0.28, cachedInput: null, output: 0.42, source: 'ping' } }),
            model('deepseek-v4-pro'),
          ],
        }),
      ],
    }
    useProviderStore.setState({ snapshot: priced, error: null, busy: false, loading: false })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(priced), { headers: { 'content-type': 'application/json' } })))
    await render('api')
    expect(selectedRows()).toEqual(['deepseek'])
    const chip = [...host.querySelectorAll('span')].find(span => span.textContent?.startsWith('Prices'))!
    expect(chip.textContent).toBe('Prices 1 / 2 models')
    expect(chip.getAttribute('title')).toContain('Manage models sets the rest.')
  })
})
