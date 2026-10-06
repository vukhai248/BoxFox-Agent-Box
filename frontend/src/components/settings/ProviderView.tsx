import { useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  ArrowDown,
  ArrowUp,
  BarChart3,
  Check,
  ChevronRight,
  Copy,
  Database,
  Gauge,
  KeyRound,
  LoaderCircle,
  LogIn,
  Plus,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  X,
} from 'lucide-react'
import { api } from '../../lib/providerApi'
import { routable } from '../../lib/routeOptions'
import { run, useProviderStore } from '../../store/providerStore'
import type {
  OAuthAttempt,
  ProviderConnection,
  ProviderDefault,
  ProviderDefinition,
  ProviderId,
  ProviderModel,
  ProviderSnapshot,
  RouteTarget,
  RouterAlias,
  RouterUsage,
} from '../../types/provider'
import { ProviderIcon } from '../providers/ProviderIcon'
import { Pill } from '../providers/ProviderStatus'
import { InferenceTest } from '../providers/InferenceTest'
import { OAuthConnectModal } from '../providers/OAuthConnectModal'
import { ModelManagerModal } from './ModelManagerModal'
import { ConnectionKeyRing, deleteBlockedReason, keyRingSize } from './ConnectionKeyRing'
import { ModelToggleList, ProviderModelList } from './ProviderModelList'
import { ProviderRail, type ProviderRailGroup } from './ProviderRail'
import { ApiProviderCatalogTable } from './ApiProviderCatalogTable'
import { ConnectedKeysPanel } from './ConnectedKeysPanel'
import { AddConnectionModal } from './AddConnectionModal'
import { SearchProviderPanel } from './SearchProviderPanel'

type ProviderTab = 'api' | 'router' | 'search'
type RouterSection = 'accounts' | 'models' | 'routing' | 'quota' | 'usage' | 'access'

/** The three tabs, in keyboard order. `Home`/`End` land on the ends of this list. */
const PROVIDER_TABS: ProviderTab[] = ['api', 'router', 'search']
const PROVIDER_TAB_LABELS: Record<ProviderTab, string> = { api: 'API', router: 'Router', search: 'Web Search' }

const field = 'w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-2 focus:ring-brand/15'
const secondary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-line bg-panel2 px-3 py-2 text-xs font-semibold text-fg transition hover:border-brand/60 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50'
const primary = 'inline-flex items-center justify-center gap-1.5 rounded-md bg-brand px-3 py-2 text-xs font-semibold text-brandfg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'


function providerFor(snapshot: ProviderSnapshot, id: string) {
  return snapshot.providers.find((provider) => provider.id === id)
}

function publicTargets(snapshot: ProviderSnapshot) {
  const direct = snapshot.connections.flatMap((connection) =>
    connection.models.filter((model) => routable(connection, model)).map((model) => ({
      id: `${connection.id}/${model.id}`,
      label: `${connection.name} / ${model.name}`,
      connectionId: connection.id,
      modelId: model.id,
    })),
  )
  return direct
}

/** The model a user types by hand: on, healthy, and marked as theirs. Asked of a connection with
 *  no row of its own, because `routable` answers "may this connection serve a model the provider
 *  never listed" in its last clause — the same clause the router routes with. */
const typedByHand: ProviderModel = { id: '', name: '', enabled: true, source: 'custom', capabilities: { streaming: 'unknown', tools: 'unknown', vision: 'unknown' } }

/**
 * The connections the provider level model list speaks for — one block per provider, one row per
 * model, merged across these connections.
 *
 * Both clauses call `routable`, the router's own rule, so this list can neither promise a target
 * the router would refuse nor drop one it takes:
 * - a model the router would route if it were switched ON (`enabled: true`): the rows stay put
 *   when the last one is switched off — this block holds the checkbox that switches it back on;
 * - a model typed by hand (`typedByHand`): a connection whose discovery failed or degraded routes
 *   exactly those, so its rows belong here; they used to disappear, and with a single connection
 *   the whole block with them (round 29 review). The same clause keeps a connection whose
 *   discovered list is still EMPTY listed, because `Add model` and `Manage models` live here.
 */
function modelListConnections(connections: ProviderConnection[]) {
  return connections.filter((connection) =>
    connection.models.some((model) => routable(connection, { ...model, enabled: true })) || routable(connection, typedByHand),
  )
}

function PublicStatus({ snapshot }: { snapshot: ProviderSnapshot }) {
  return (
    <div className="flex items-center gap-2 text-[11px] text-muted">
      <span className="size-2 rounded-full bg-emerald-500" />
      Router engine {snapshot.health.status} · v{snapshot.health.version}
    </div>
  )
}

export function ProviderView({ initialTab = 'router' }: { initialTab?: ProviderTab }) {
  const snapshot = useProviderStore((state) => state.snapshot)
  const loading = useProviderStore((state) => state.loading)
  const busy = useProviderStore((state) => state.busy)
  const error = useProviderStore((state) => state.error)
  const load = useProviderStore((state) => state.load)
  const [tab, setTab] = useState<ProviderTab>(initialTab)

  useEffect(() => setTab(initialTab), [initialTab])
  useEffect(() => { run(load().catch(() => undefined)) }, [load])

  return (
    <div className="min-h-full select-text bg-bg text-fg">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/95 px-4 pt-4 backdrop-blur sm:px-8 sm:pt-6">
        <div className="mx-auto flex max-w-6xl items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold">Provider</h1>
            <p className="mt-1 text-xs text-muted">Connect model providers and route requests through the native BoxFox router.</p>
          </div>
          <div className="flex items-center gap-3">
            {snapshot && <PublicStatus snapshot={snapshot} />}
          </div>
        </div>
        <div role="tablist" aria-label="Provider settings" className="mx-auto mt-5 flex max-w-6xl items-end gap-1">
          {PROVIDER_TABS.map((item, index) => (
            <button
              key={item}
              type="button"
              role="tab"
              id={`provider-tab-${item}`}
              aria-controls="provider-panel"
              aria-selected={tab === item}
              tabIndex={tab === item ? 0 : -1}
              onClick={() => setTab(item)}
              onKeyDown={(event) => {
                if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
                event.preventDefault()
                const next = event.key === 'Home'
                  ? PROVIDER_TABS[0]
                  : event.key === 'End'
                    ? PROVIDER_TABS[PROVIDER_TABS.length - 1]
                    : PROVIDER_TABS[(index + (event.key === 'ArrowRight' ? 1 : PROVIDER_TABS.length - 1)) % PROVIDER_TABS.length]
                setTab(next)
                document.getElementById(`provider-tab-${next}`)?.focus()
              }}
              className={`relative -mb-px min-w-28 rounded-t-xl border px-5 py-2.5 text-xs font-semibold transition focus:outline-none focus:ring-2 focus:ring-brand/40 ${tab === item ? 'border-line border-b-bg bg-bg text-fg' : 'border-transparent bg-panel/60 text-muted hover:bg-panel2 hover:text-fg'}`}
            >
              {PROVIDER_TAB_LABELS[item]}
            </button>
          ))}
        </div>
      </header>

      <main id="provider-panel" role="tabpanel" aria-labelledby={`provider-tab-${tab}`} className="mx-auto max-w-6xl p-4 sm:p-8">
        {error && <div role="alert" className="mb-5 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-xs text-red-700 dark:text-red-300">{error}</div>}
        {loading && !snapshot ? (
          <div className="flex items-center justify-center gap-2 py-20 text-xs text-muted"><LoaderCircle className="size-4 animate-spin" />Loading router state…</div>
        ) : !snapshot ? (
          <div className="rounded-xl border border-line bg-panel p-6 text-sm">Router engine is unavailable. Start BoxFox with the router launcher and retry.<button type="button" onClick={() => run(load())} className={`${secondary} mt-3 block`}>Retry connection</button></div>
        ) : tab === 'api' ? (
          <ApiPanel snapshot={snapshot} busy={busy} />
        ) : tab === 'router' ? (
          <RouterPanel snapshot={snapshot} busy={busy} />
        ) : (
          <SearchProviderPanel snapshot={snapshot} />
        )}
      </main>
    </div>
  )
}


function DefaultProviderCard({
  chosen,
  busy,
  onAddKey,
}: {
  chosen?: ProviderDefinition
  busy: boolean
  onAddKey?: () => void
}) {
  const request = useProviderStore((state) => state.request)
  const [formOpen, setFormOpen] = useState(chosen?.id === 'custom')
  const [name, setName] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const formId = useId()

  useEffect(() => {
    setFormOpen(chosen?.id === 'custom')
  }, [chosen?.id])

  const providerName = chosen?.name ?? 'API provider'

  const create = async () => {
    if (!chosen || !apiKey.trim()) return
    await request('/api/router/connections', 'POST', {
      providerId: chosen.id,
      name: name.trim() || chosen.name,
      apiKey: apiKey.trim(),
      ...(chosen.id === 'custom' ? { endpoint: endpoint.trim() } : {}),
    })
    setApiKey('')
    setName('')
    setEndpoint('')
    setFormOpen(false)
  }

  const canSubmit = Boolean(chosen) && Boolean(apiKey.trim()) && (chosen?.id !== 'custom' || Boolean(endpoint.trim()))
  const base = endpoint.trim().replace(/\/+$/, '') || '{base}'

  return (
    <article className="rounded-xl border border-line bg-panel p-3 sm:p-4 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-fg">No connection configured</p>
          <p className="text-[11px] text-muted">Add an API key to connect this provider and load models.</p>
        </div>
        <div className="flex items-center gap-2">
          {onAddKey && (
            <button
              type="button"
              onClick={onAddKey}
              className={primary}
            >
              <Plus className="size-3.5" />
              Add API key
            </button>
          )}
        </div>
      </div>

      {chosen && !isProviderRunnableV2(chosen) && (
        <p className="mt-2.5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] leading-4 text-amber-700 dark:text-amber-300">
          {chosen.name} has no runnable adapter in this build yet ({chosen.implementationStatus ?? chosen.availability ?? 'planned'}). A connection can be saved, but probing and routing stay unavailable until the adapter ships.
        </p>
      )}

      {formOpen && (
        <div id={formId} className="mt-2.5 rounded-xl border border-line/80 bg-panel2/40 p-3.5 sm:p-4 shadow-xs">
          <div className="mb-3 flex items-center justify-between border-b border-line/40 pb-2">
            <span className="text-xs font-semibold text-fg">New connection</span>
            <button
              type="button"
              onClick={() => setFormOpen(false)}
              className="rounded-md px-2 py-0.5 text-[11px] font-medium text-muted transition hover:bg-panel2 hover:text-fg"
            >
              Cancel
            </button>
          </div>
          <div className="grid gap-3 md:grid-cols-3">
            <label className="text-xs font-semibold">
              Connection name
              <input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={`My ${providerName}`}
                className={`${field} mt-1.5`}
              />
            </label>
            {chosen?.id === 'custom' && (
              <label className="text-xs font-semibold">
                Endpoint URL
                <input
                  value={endpoint}
                  onChange={(e) => setEndpoint(e.target.value)}
                  placeholder="http://127.0.0.1:8000/v1"
                  className={`${field} mt-1.5 font-mono`}
                />
                <span className="mt-1 block font-mono text-[10px] font-normal leading-4 text-muted">
                  Usually ends with /v1. The router calls {base}/models and {base}/chat/completions.
                </span>
              </label>
            )}
            <label className="text-xs font-semibold">
              API key
              <input
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Paste key"
                className={`${field} mt-1.5 font-mono`}
              />
            </label>
            {chosen?.id !== 'custom' && (
              <div className="flex items-end">
                <p className="pb-2 text-[11px] text-muted">Uses the provider&apos;s official endpoint.</p>
              </div>
            )}
          </div>
          <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 border-t border-line/40 pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                disabled={busy || !canSubmit}
                onClick={() => run(create())}
                className={primary}
              >
                <Plus className="size-3.5" />
                Add connection
              </button>
              <button type="button" onClick={() => setFormOpen(false)} className={secondary}>
                Cancel
              </button>
            </div>
            <p className="text-[11px] leading-4 text-muted">
              Saving probes the endpoint once. Model names are used exactly as the endpoint reports them.
            </p>
          </div>
        </div>
      )}

      <div className="mt-3 rounded-lg border border-line/60 bg-panel2/30 p-3 sm:p-3.5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[10px] font-mono uppercase tracking-wider text-muted">
            Keys on this connection <span className="ml-1.5 rounded-full border border-line bg-panel px-1.5 py-0.2 text-[10px] font-normal normal-case text-muted">0 keys</span>
          </p>
          <button
            type="button"
            onClick={() => (onAddKey ? onAddKey() : setFormOpen(true))}
            className={`${secondary} py-1 text-[11px]`}
          >
            <Plus className="size-3" />
            Add key
          </button>
        </div>
        <p className="mt-1 text-[11px] text-muted">Rotates automatically when a key runs out of quota.</p>
        <span className="sr-only">No API connection configured yet.</span>

        {!formOpen && (
          <div className="mt-3 flex flex-col items-center justify-center rounded-lg border border-dashed border-line/80 bg-panel/40 py-7 text-center">
            <div className="mb-2 flex size-10 items-center justify-center rounded-full bg-panel2 text-muted/50">
              <KeyRound className="size-5" />
            </div>
            <p className="text-xs font-medium text-fg">No key on this connection yet.</p>
            <p className="mt-0.5 text-[11px] text-muted">
              Add an API key to probe models and start routing.
            </p>
            <button
              type="button"
              onClick={() => (onAddKey ? onAddKey() : setFormOpen(true))}
              className={`${primary} mt-3.5 text-xs`}
            >
              <Plus className="size-3.5" />
              Add key
            </button>
          </div>
        )}
      </div>

      <p className="mt-2.5 text-[11px] text-muted">
        0 models · Data: live · Last sync never
      </p>
      <p className="mt-1 text-[10px] text-muted">
        Models synced: Never synced · Quota updated: No data · No quota data available
      </p>
    </article>
  )
}

function ApiPanel({ snapshot, busy }: { snapshot: ProviderSnapshot; busy: boolean }) {
  const request = useProviderStore((state) => state.request)
  const definitions = snapshot.providers.filter((provider) => provider.authMethod === 'api_key')
  const [providerId, setProviderId] = useState(definitions[0]?.id ?? 'openrouter')
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [selectedProviderIdForAdd, setSelectedProviderIdForAdd] = useState<string | undefined>()

  const chosen = definitions.find((provider) => provider.id === providerId) ?? definitions[0]
  const connections = snapshot.connections.filter((c) => c.providerId === chosen?.id)

  const handleOpenAddModal = (id?: string) => {
    setSelectedProviderIdForAdd(id ?? chosen?.id)
    setAddModalOpen(true)
  }

  const handleToggleProviderEnabled = async (toggledProviderId: string, enabled: boolean) => {
    const providerConnections = snapshot.connections.filter((c) => c.providerId === toggledProviderId)
    if (providerConnections.length === 0) return
    await Promise.all(
      providerConnections.map((c) =>
        request(`/api/router/connections/${encodeURIComponent(c.id)}`, 'PATCH', { enabled })
      )
    )
  }

  const totalKeys = connections.reduce(
    (acc, conn) => acc + (conn.keys?.length ?? (conn.credentialPresent ? 1 : 0)),
    0,
  )

  return (
    <div className="space-y-4">
      <p className="text-[11px] leading-4 text-muted">
        Keys are sent directly to the BoxFox host router and are never returned to this page after save. Saving a key automatically probes the provider&apos;s live model inventory.
      </p>

      {/* 2-column layout: Left = Providers Catalog, Right = Selected Provider Details & Keys */}
      <div className="grid gap-6 lg:grid-cols-[380px_minmax(0,1fr)] xl:grid-cols-[420px_minmax(0,1fr)] items-start">
        {/* Left Column: API Providers Catalog Table */}
        <div className="min-w-0 h-[calc(100vh-210px)] min-h-[560px] max-h-[780px] flex flex-col sticky top-20">
          <ApiProviderCatalogTable
            providers={definitions}
            connections={snapshot.connections}
            selectedId={chosen?.id ?? ''}
            onSelect={(id) => setProviderId(id)}
            onToggleEnabled={handleToggleProviderEnabled}
          />
        </div>

        {/* Right Column: Selected Provider Connected Keys & Models */}
        <div className="min-w-0">
          <ConnectedKeysPanel
            selectedProvider={chosen}
            connectionsCount={connections.length}
            keysCount={totalKeys}
          >
            {connections.length === 0 ? (
              <DefaultProviderCard
                chosen={chosen}
                busy={busy}
                onAddKey={() => handleOpenAddModal(chosen?.id)}
              />
            ) : (
              <div className="space-y-4">
                {connections.map((connection) => (
                  <ConnectionCard
                    key={connection.id}
                    snapshot={snapshot}
                    connection={connection}
                  />
                ))}
                <ProviderModelList connections={modelListConnections(connections)} />
              </div>
            )}
          </ConnectedKeysPanel>
        </div>
      </div>

      {/* Add Connection / API Key Modal Popup */}
      <AddConnectionModal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        initialProviderId={selectedProviderIdForAdd}
        providers={definitions}
      />
    </div>
  )
}


/** `lastDiscoveryAttemptAt` is epoch ms; discovery failures are shown with local time. */
function shortEpoch(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
}

function ConnectionCard({
  snapshot,
  connection,
}: {
  snapshot: ProviderSnapshot
  connection: ProviderConnection
}) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const keyRing = Array.isArray(connection.keys) ? connection.keys : null
  const [managerOpen, setManagerOpen] = useState(false)
  const siblingConnections = snapshot.connections.filter((c) => c.providerId === connection.providerId)
  const handTyped = connection.models.filter((model) => model.source === 'custom')

  return (
    <article className="rounded-xl border border-line bg-panel p-3 sm:p-4">
      {['failed', 'degraded'].includes(connection.discoveryState) ? (
        <div className="mb-3 rounded-lg border border-rose-500/25 bg-rose-500/5 p-3 text-[11px] leading-4">
          <p className="font-semibold text-rose-600 dark:text-rose-400">Models could not be listed</p>
          {connection.error ? (
            <p className="mt-1 font-mono text-rose-700 dark:text-rose-300 break-all">{connection.error}</p>
          ) : (
            <p className="mt-1 text-muted">The endpoint did not return a model list. Retry, or add each model id by hand.</p>
          )}
          {shortEpoch(connection.lastDiscoveryAttemptAt) && (
            <p className="mt-1 text-muted">Last attempt: {shortEpoch(connection.lastDiscoveryAttemptAt)}</p>
          )}
          {connection.providerId === 'custom' && (
            <p className="mt-1 text-muted">Some gateways require a verified account before /models or /chat/completions works. The message above is the provider&apos;s own.</p>
          )}
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <button type="button" disabled={busy || !connection.credentialPresent} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/test`, 'POST'))} className={secondary}><RefreshCw className="size-3.5" />Retry</button>
            <button type="button" onClick={() => setManagerOpen(true)} className={secondary}><Plus className="size-3.5" />Add model by hand</button>
          </div>
        </div>
      ) : connection.error ? (
        <p className="mb-3 rounded-lg border border-rose-500/25 bg-rose-500/5 p-3 font-mono text-[11px] leading-4 text-rose-600 dark:text-rose-300 break-all">{connection.error}</p>
      ) : null}

      {['failed', 'degraded'].includes(connection.discoveryState) && handTyped.length > 0 && (
        <p className="mt-1.5 text-[11px] text-muted">{handTyped.length} model(s) added by hand — tested one by one.</p>
      )}

      {siblingConnections.length > 1 ? (
        <div className="mb-2">
          <span className="font-semibold text-xs text-fg">{connection.name}</span>
        </div>
      ) : (
        <span className="sr-only">{connection.name}</span>
      )}

      {keyRing ? (
        <ConnectionKeyRing connection={connection} />
      ) : !connection.credentialPresent ? (
        <p className="mt-2 text-[11px] leading-4 text-muted">No API key saved on this connection.</p>
      ) : connection.authState !== 'ready' ? (
        <p className="mt-2 text-[11px] leading-4 text-amber-700 dark:text-amber-300">Key saved on host; the provider refused it (auth {connection.authState}).</p>
      ) : null}

      {managerOpen && <ModelManagerModal connection={connection} initialShowCustomForm onClose={() => setManagerOpen(false)} />}
    </article>
  )
}


function RouterPanel({ snapshot, busy }: { snapshot: ProviderSnapshot; busy: boolean }) {
  const [section, setSection] = useState<RouterSection>('accounts')
  const items: Array<[RouterSection, string]> = [
    ['accounts', 'Providers'],
    ['models', 'Models'],
    ['routing', 'Routing'],
    ['quota', 'Quota Tracker'],
    ['usage', 'Usage & Analytics'],
    ['access', 'API Access'],
  ]
  return (
    <div className="grid gap-6 lg:grid-cols-[190px_minmax(0,1fr)]">
      <nav aria-label="Router sections" className="flex gap-1 overflow-x-auto lg:block lg:space-y-1">
        {items.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setSection(id)}
            className={`shrink-0 rounded-lg px-3 py-2 text-left text-xs font-semibold transition lg:w-full ${section === id ? 'bg-brand/10 text-brand ring-1 ring-brand/25' : 'text-muted hover:bg-panel2 hover:text-fg'}`}
          >
            {label}
          </button>
        ))}
      </nav>
      <div className="min-w-0">
        {section === 'accounts' && <AccountsSection snapshot={snapshot} />}
        {section === 'models' && <ModelsSection snapshot={snapshot} />}
        {section === 'routing' && <RoutingSection snapshot={snapshot} busy={busy} />}
        {section === 'quota' && <QuotaSection snapshot={snapshot} />}
        {section === 'usage' && <UsageSection snapshot={snapshot} />}
        {section === 'access' && <AccessSection snapshot={snapshot} busy={busy} />}
      </div>
    </div>
  )
}

function AccountsSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  return <RouterProvidersSection snapshot={snapshot} />
}

function RouterProvidersSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  const request = useProviderStore((state) => state.request)
  const load = useProviderStore((state) => state.load)
  const busy = useProviderStore((state) => state.busy)
  const [selectedProviderId, setSelectedProviderId] = useState<ProviderId | null>(null)
  const routerProviders = snapshot.providers.filter((provider) => provider.routerVisible !== false && providerCategoryValueV2(provider) !== 'api_key')
  const selectedProvider = routerProviders.find((provider) => provider.id === selectedProviderId) ?? null
  return <RouterProviderCatalogV2 snapshot={snapshot} providers={routerProviders} selectedProvider={selectedProvider} busy={busy} request={request} load={load} onSelect={setSelectedProviderId} onClear={() => setSelectedProviderId(null)} />
}

function isProviderRunnableV2(provider: ProviderDefinition) {
  const status = provider.implementationStatus ?? (provider.runtimeAvailable && provider.availability !== 'planned' ? 'ready' : 'planned')
  return provider.runtimeAvailable === true && ['ready', 'experimental'].includes(status)
}

function providerCategoryValueV2(provider: ProviderDefinition) {
  return provider.category ?? (provider.authMethod === 'oauth' ? 'oauth' : 'api_key')
}

function providerCategoryLabelV2(provider: ProviderDefinition) {
  if (providerCategoryValueV2(provider) === 'free') return 'Free Tier'
  if (providerCategoryValueV2(provider) === 'api_key') return 'API key'
  return 'OAuth'
}

/** The rail row meta the catalog cards used to print, per provider. */
function routerRailStatusLine(providerConnections: ProviderConnection[]) {
  if (providerConnections.length === 0) return 'No connections'
  const models = providerConnections.reduce((count, connection) => count + connection.models.length, 0)
  return `${providerConnections.length} connection${providerConnections.length === 1 ? '' : 's'} · ${models} models`
}

function RouterProviderCatalogV2({ snapshot, providers: routerProviders, selectedProvider, busy, request, load, onSelect, onClear }: { snapshot: ProviderSnapshot; providers: ProviderDefinition[]; selectedProvider: ProviderDefinition | null; busy: boolean; request: (path: string, method?: string, body?: unknown) => Promise<unknown>; load: () => Promise<void>; onSelect: (id: ProviderId) => void; onClear: () => void }) {
  const groups: ProviderRailGroup[] = [
    { id: 'oauth', label: 'OAuth accounts', providers: routerProviders.filter((provider) => providerCategoryValueV2(provider) === 'oauth') },
    { id: 'free', label: 'Free Tier', providers: routerProviders.filter((provider) => providerCategoryValueV2(provider) === 'free') },
  ]
  const routerProviderIds = new Set(routerProviders.map((provider) => provider.id))
  const connections = snapshot.connections.filter((connection) => routerProviderIds.has(connection.providerId))
  const models = connections.reduce((count, connection) => count + connection.models.length, 0)
  return <div className="space-y-3">
    <div className="flex flex-wrap items-end justify-between gap-3"><div><h2 className="text-sm font-semibold">Router providers</h2><p className="mt-1 max-w-2xl text-xs text-muted">Choose a provider to manage its account or connection, discover models, test inference, quota and routing settings in one detail view.</p></div><div className="flex items-center gap-2 rounded-full border border-line bg-panel2 px-3 py-1.5 text-[10px] text-muted"><ShieldCheck className="size-3.5 text-brand" />{routerProviders.length} providers</div></div>
    <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <ProviderRail label="Router providers" groups={groups} connections={snapshot.connections} selectedId={selectedProvider?.id ?? ''} onSelect={onSelect} statusLine={routerRailStatusLine} showModelCount={false} />
      <div className="min-w-0">
        {selectedProvider ? (
          <RouterProviderDetailV2 snapshot={snapshot} provider={selectedProvider} busy={busy} request={request} load={load} onBack={onClear} />
        ) : (
          <div className="space-y-3">
            <p className="rounded-lg border border-line bg-panel2 px-4 py-3 text-[11px] leading-4 text-muted">{`${connections.length} connection${connections.length === 1 ? '' : 's'} · ${models} models across these providers. Pick one on the left to manage its account, connections, model list, quota and routing order.`}</p>
            <div className="rounded-lg border border-line bg-panel2 px-4 py-3 text-[11px] text-muted">API-key providers remain available in the <span className="font-semibold text-fg">API</span> tab. Their connections still appear in shared Models, Routing and Usage views after configuration.</div>
          </div>
        )}
      </div>
    </div>
  </div>
}

function RouterProviderDetailV2({ snapshot, provider, busy, request, load, onBack }: { snapshot: ProviderSnapshot; provider: ProviderDefinition; busy: boolean; request: (path: string, method?: string, body?: unknown) => Promise<unknown>; load: () => Promise<void>; onBack: () => void }) {
  const [name, setName] = useState(provider.name)
  const [projectId, setProjectId] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [endpoint, setEndpoint] = useState(provider.defaultEndpoint ?? '')
  const [attempt, setAttempt] = useState<OAuthAttempt | null>(null)
  const popup = useRef<Window | null>(null)
  const runnable = isProviderRunnableV2(provider)
  const isOAuth = provider.authMethod === 'oauth' || ['antigravity', 'agy', 'codex', 'claude', 'github', 'cline'].includes(provider.id)
  const isAnonymous = provider.id === 'opencode' || provider.authModes?.includes('anonymous')
  const rawConnections = snapshot.connections.filter((connection) => connection.providerId === provider.id)
  const providerConfig = snapshot.providerConfigs?.find((value) => value.id === provider.id) ?? { id: provider.id, roundRobin: false, connectionOrder: [] }
  const rank = new Map(providerConfig.connectionOrder.map((id, index) => [id, index]))
  const connections = [...rawConnections].sort((a, b) => (rank.get(a.id) ?? Number.MAX_SAFE_INTEGER) - (rank.get(b.id) ?? Number.MAX_SAFE_INTEGER))
  // The provider level model list covers the same connections as the API tab's, by the same rule.
  const listedConnections = modelListConnections(connections)

  useEffect(() => { setName(provider.name); setProjectId(''); setApiKey(''); setEndpoint(provider.defaultEndpoint ?? ''); setAttempt(null) }, [provider.id, provider.name, provider.defaultEndpoint])
  useEffect(() => {
    if (!attempt || !['pending', 'exchanging'].includes(attempt.status)) return
    let cancelled = false
    const tick = async () => {
      try {
        const next = await api<OAuthAttempt>(`/api/router/oauth/attempts/${encodeURIComponent(attempt.id)}`)
        if (cancelled) return
        setAttempt(next)
        if (!['pending', 'exchanging'].includes(next.status)) { popup.current?.close(); popup.current = null; await load().catch(() => undefined) }
      } catch { /* durable connection state is refreshed by the next request */ }
    }
    const timer = window.setInterval(() => run(tick()), 900)
    run(tick())
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [attempt?.id, attempt?.status, load])

  const cancel = async () => {
    if (!attempt) return
    await api(`/api/router/oauth/attempts/${encodeURIComponent(attempt.id)}`, { method: 'DELETE' })
    popup.current?.close(); popup.current = null; setAttempt(null); await load().catch(() => undefined)
  }
  const connect = async (connectionId: string) => {
    if (attempt && ['pending', 'exchanging'].includes(attempt.status)) await cancel()
    const isDevice = provider.id === 'github' || provider.id === 'ghe-copilot'
    let openedPopup: Window | null = null
    if (!isDevice) {
      openedPopup = window.open('about:blank', 'boxfox-provider-oauth', 'popup,width=560,height=740')
      popup.current = openedPopup
    }
    try {
      const next = await api<OAuthAttempt>('/api/router/oauth/attempts', { method: 'POST', body: { connectionId } })
      setAttempt(next)
      if (openedPopup && next.authorizationUrl) {
        openedPopup.location.href = next.authorizationUrl
      }
    } catch (error) {
      openedPopup?.close()
      popup.current = null
      throw error
    }
  }
  const createConnection = async () => {
    const values: Record<string, unknown> = { providerId: provider.id, name: name.trim() || provider.name }
    if (isOAuth) {
      if (projectId.trim()) values.projectId = projectId.trim()
      if (apiKey.trim()) values.accessToken = apiKey.trim()
    } else if (isAnonymous) {
      /* No credentials needed for free community providers */
    } else {
      if (!apiKey.trim() || !endpoint.trim()) return
      values.apiKey = apiKey.trim(); values.endpoint = endpoint.trim()
    }
    const created = (await request('/api/router/connections', 'POST', values)) as ProviderConnection | undefined
    setName(provider.name); setProjectId(''); setApiKey('')
    if (isOAuth && !apiKey.trim() && created?.id) {
      await connect(created.id)
    }
  }
  const updateProviderRouting = (roundRobin: boolean, connectionOrder = connections.map((connection) => connection.id)) => request(`/api/router/providers/${encodeURIComponent(provider.id)}`, 'PUT', { roundRobin, connectionOrder })
  const moveConnection = (index: number, direction: -1 | 1) => {
    const order = connections.map((connection) => connection.id)
    const next = index + direction
    if (next < 0 || next >= order.length) return Promise.resolve()
    ;[order[index], order[next]] = [order[next], order[index]]
    return updateProviderRouting(providerConfig.roundRobin, order)
  }

  return <div className="space-y-5">
    <button type="button" onClick={onBack} className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted transition hover:text-fg"><ArrowUp className="size-3.5 -rotate-90" />Back to providers</button>
    <header className="flex flex-wrap items-start justify-between gap-4 rounded-xl border border-line bg-panel p-4 sm:p-5"><div className="flex items-center gap-3"><ProviderIcon providerId={provider.id} name={provider.name} className="size-12 rounded-lg border border-line bg-panel2 p-2" /><div><div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">{provider.name}</h2><Pill value={runnable ? 'ready' : 'pending'}>{provider.implementationStatus ?? (runnable ? 'ready' : 'planned')}</Pill></div><p className="mt-1 text-xs text-muted">{providerCategoryLabelV2(provider)} · discovery: {provider.discoveryClass ?? 'provider'}</p><div className="mt-2 flex flex-wrap gap-1.5">{(provider.authModes ?? [isOAuth ? 'oauth' : isAnonymous ? 'anonymous' : 'api_key']).map((mode) => <span key={mode} className="rounded-full border border-line bg-panel2 px-2 py-0.5 text-[10px] font-semibold uppercase text-muted">{mode.replace('_', ' ')}</span>)}</div></div></div><div className="text-right text-[10px] text-muted"><p>{connections.length} connection{connections.length === 1 ? '' : 's'}</p><p className="mt-1">{connections.reduce((count, connection) => count + connection.models.length, 0)} discovered models</p></div></header>
    {(provider.riskNotice || provider.authHint) && <section className="rounded-xl border border-amber-500/25 bg-amber-500/5 px-4 py-3 text-xs"><p className="font-semibold">Authentication and account notice</p><p className="mt-1 text-muted">{provider.authHint}{provider.riskNotice ? ` ${provider.riskNotice}` : ''}</p></section>}
    {!runnable ? <section className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4"><h3 className="text-sm font-semibold text-amber-800 dark:text-amber-200">Provider catalogued, adapter not integrated yet</h3><p className="mt-1 text-xs text-amber-800/80 dark:text-amber-100/80">This provider is included from the 9Router/OmniRoute catalog so BoxFox can expose its settings consistently. OAuth, credential storage and inference remain disabled until its executor is ported.</p><div className="mt-3 grid gap-2 sm:grid-cols-3"><div className="rounded-lg border border-amber-500/20 bg-panel/60 p-3 text-xs"><p className="font-semibold">Authentication</p><p className="mt-1 text-[10px] text-muted">{isOAuth ? 'OAuth flow pending' : isAnonymous ? 'Free tier' : 'API key flow pending'}</p></div><div className="rounded-lg border border-amber-500/20 bg-panel/60 p-3 text-xs"><p className="font-semibold">Model discovery</p><p className="mt-1 text-[10px] text-muted">{provider.discoveryClass ?? 'static-only'}</p></div><div className="rounded-lg border border-amber-500/20 bg-panel/60 p-3 text-xs"><p className="font-semibold">Routing</p><p className="mt-1 text-[10px] text-muted">Target disabled until verified</p></div></div></section> : <section className="rounded-xl border border-line bg-panel p-4 sm:p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-sm font-semibold">{isAnonymous ? 'Enable free provider' : isOAuth ? 'Add account' : 'Add connection'}</h3><p className="mt-1 text-xs text-muted">{isAnonymous ? 'This community provider is ready to use without an API key or account login.' : isOAuth ? 'Authorize with OAuth or import a session token / API key.' : 'The server verifies the credential and automatically requests the provider model inventory.'}</p></div><span className="rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2.5 py-1 text-[10px] font-semibold text-emerald-700 dark:text-emerald-300">{isAnonymous ? 'Free / No-Auth' : isOAuth ? 'OAuth / Import' : 'API key'}</span></div><div className="mt-4 grid gap-3 sm:grid-cols-2">{isAnonymous ? <div className="sm:col-span-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 text-xs"><p className="font-semibold text-emerald-700 dark:text-emerald-300">Ready to use</p><p className="mt-1 text-muted text-[11px]">No credentials or account registration required. Click Enable below to connect to the community model pool.</p></div> : isOAuth ? <><label className="text-xs font-semibold">Account name<input value={name} onChange={(event) => setName(event.target.value)} className={`${field} mt-1.5`} /></label>{provider.id === 'antigravity' ? <label className="text-xs font-semibold">Google Cloud project (optional)<input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="Auto-discover when possible" className={`${field} mt-1.5 font-mono`} /></label> : <label className="text-xs font-semibold">Session token / API Key (optional import)<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Paste session token / key to import" className={`${field} mt-1.5 font-mono`} /></label>}</> : <><label className="text-xs font-semibold">Connection name<input value={name} onChange={(event) => setName(event.target.value)} placeholder={`My ${provider.name}`} className={`${field} mt-1.5`} /></label><label className="text-xs font-semibold">API key<input type="password" autoComplete="off" value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder={provider.id === 'openrouter' ? 'sk-or-v1-...' : 'Paste key'} className={`${field} mt-1.5 font-mono`} /></label><label className="text-xs font-semibold sm:col-span-2">Endpoint<input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://provider.example/v1" className={`${field} mt-1.5 font-mono`} /><span className="mt-1 block text-[10px] font-normal text-muted">Default: {provider.defaultEndpoint ?? 'Enter the exact endpoint you control.'}{provider.id === 'openrouter' ? ' · Get key at openrouter.ai/settings/keys' : ''}</span></label></>}</div><button type="button" disabled={busy || (!isOAuth && !isAnonymous && (!apiKey.trim() || !endpoint.trim()))} onClick={() => run(createConnection())} className={`${primary} mt-4`}><Plus className="size-3.5" />{isAnonymous ? `Enable ${provider.name}` : isOAuth ? `Add ${provider.name} account` : 'Add connection'}</button></section>}
    <OAuthConnectModal
      isOpen={Boolean(attempt && ['pending', 'exchanging'].includes(attempt.status))}
      provider={provider}
      attempt={attempt}
      onClose={() => run(cancel())}
      onSuccess={() => {
        popup.current?.close()
        popup.current = null
        setAttempt(null)
        run(load())
      }}
    />
    <section className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Connections & models</h3>
          <p className="mt-1 text-xs text-muted">Each connection owns its credential, health state and discovered model list. Only verified enabled models can become routing targets.</p>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-muted">
            <input type="checkbox" disabled={busy || connections.length < 2} checked={providerConfig.roundRobin} onChange={(event) => run(updateProviderRouting(event.target.checked))} />
            Round robin accounts
          </label>
          <span className="text-[10px] text-muted">{connections.length} configured</span>
        </div>
      </div>
      {connections.length === 0 ? (
        <div className="space-y-3">
          <Empty text={`No ${provider.name} connection configured yet. Add an account or connection above to begin routing.`} />
          {CURATED_PREVIEWS[provider.id] && (
            <div className="rounded-xl border border-line bg-panel p-4">
              <div className="flex items-center justify-between gap-3 mb-3">
                <p className="text-xs font-semibold">Available Models (Curated Catalog)</p>
                <span className="text-[10px] text-muted">{CURATED_PREVIEWS[provider.id].length} models</span>
              </div>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {CURATED_PREVIEWS[provider.id].map((m) => (
                  <div key={m.id} className="rounded-lg border border-line bg-panel2 p-3 text-xs">
                    <span className="block font-semibold truncate">{m.name}</span>
                    <span className="block font-mono text-[10px] text-muted truncate mt-0.5">{m.id}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      ) : (
        connections.map((connection, index) => (
          <div key={connection.id} className="space-y-2">
            <div className="flex justify-end gap-1">
              <button type="button" aria-label={`Move ${connection.name} up`} disabled={busy || index === 0} onClick={() => run(moveConnection(index, -1))} className={secondary}><ArrowUp className="size-3.5" /></button>
              <button type="button" aria-label={`Move ${connection.name} down`} disabled={busy || index === connections.length - 1} onClick={() => run(moveConnection(index, 1))} className={secondary}><ArrowDown className="size-3.5" /></button>
            </div>
            {provider.id === 'antigravity' ? <AntigravityAccount connection={connection} onConnect={connect} /> : <OAuthOrApiConnectionCard connection={connection} provider={provider} onConnect={connect} />}
          </div>
        ))
      )}
      {/* One row per model for the whole provider, the same block the API tab renders. */}
      <ProviderModelList connections={listedConnections} />
    </section>
  </div>
}

const CURATED_PREVIEWS: Record<string, Array<{ id: string; name: string }>> = {
  claude: [
    { id: 'cc/claude-opus-5', name: 'Claude Opus 5' },
    { id: 'cc/claude-fable-5-1', name: 'Claude Fable 5.1' },
    { id: 'cc/claude-fable-5', name: 'Claude Fable 5' },
    { id: 'cc/claude-sonnet-5', name: 'Claude Sonnet 5' },
    { id: 'cc/claude-haiku-4-5-20251001', name: 'Claude 4.5 Haiku' },
  ],
  codex: [
    { id: 'gpt-6-astra', name: 'GPT-6 Astra' },
    { id: 'gpt-5.6-sol', name: 'GPT-5.6 Sol' },
    { id: 'gpt-5-neo', name: 'GPT-5 Neo' },
    { id: 'codex-mini-latest', name: 'Codex Mini Latest' },
  ],
  antigravity: [
    { id: 'gemini-3.1-pro-low', name: 'Gemini 3.1 Pro' },
    { id: 'gemini-3.8-flash-high', name: 'Gemini 3.8 Flash (High)' },
    { id: 'gemini-3.7-flash-high', name: 'Gemini 3.7 Flash (High)' },
    { id: 'gemini-3.6-flash-high', name: 'Gemini 3.6 Flash (High)' },
    { id: 'claude-sonnet-4-6', name: 'Claude 3.7 Sonnet (Thinking)' },
    { id: 'claude-opus-4-6-thinking', name: 'Claude 3.7 Opus (Thinking)' },
    { id: 'gpt-oss-120b-medium', name: 'GPT-OSS 120B (Medium)' },
  ],
  github: [
    { id: 'claude-3.5-sonnet', name: 'Claude 3.5 Sonnet' },
    { id: 'gpt-4o', name: 'GPT-4o' },
    { id: 'o1-preview', name: 'o1-preview' },
  ],
  cline: [
    { id: 'anthropic/claude-opus-4.7', name: 'Claude Opus 4.7' },
    { id: 'anthropic/claude-sonnet-4.6', name: 'Claude Sonnet 4.6' },
    { id: 'anthropic/claude-opus-4.6', name: 'Claude Opus 4.6' },
    { id: 'openai/gpt-5.3-codex', name: 'GPT-5.3 Codex' },
    { id: 'openai/gpt-5.4', name: 'GPT-5.4' },
    { id: 'google/gemini-3.1-pro-preview', name: 'Gemini 3.1 Pro Preview' },
    { id: 'google/gemini-3.1-flash-lite-preview', name: 'Gemini 3.1 Flash Lite' },
    { id: 'kwaipilot/kat-coder-pro', name: 'KAT Coder Pro' },
  ],
  opencode: [
    { id: 'muse-spark-1.2-contributor-free', name: 'Muse Spark 1.2 Contributor Free' },
    { id: 'muse-spark-1.3-contributor-free', name: 'Muse Spark 1.3 Contributor Free' },
  ],
  openrouter: [
    { id: 'google/gemini-2.0-flash-exp:free', name: 'Gemini 2.0 Flash (Free)' },
    { id: 'meta-llama/llama-3.3-70b-instruct:free', name: 'Llama 3.3 70B Instruct (Free)' },
    { id: 'deepseek/deepseek-r1:free', name: 'DeepSeek R1 (Free)' },
    { id: 'deepseek/deepseek-chat:free', name: 'DeepSeek V3 (Free)' },
    { id: 'openai/gpt-4o-mini', name: 'GPT-4o Mini' },
    { id: 'anthropic/claude-3.5-sonnet', name: 'Claude 3.5 Sonnet' },
  ],
}

function OAuthOrApiConnectionCard({
  connection,
  provider,
  onConnect,
}: {
  connection: ProviderConnection
  provider: ProviderDefinition
  onConnect: (id: string) => Promise<void>
}) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const [name, setName] = useState(connection.name)
  const [apiKey, setApiKey] = useState('')
  const [showKeyInput, setShowKeyInput] = useState(false)
  const isOAuth = provider.authMethod === 'oauth' || provider.authModes?.includes('oauth')
  // Same defensive read as the API card: no `keys` means the legacy single-key shape.
  const keyRing = Array.isArray(connection.keys) ? connection.keys : null
  const ringId = useId()

  useEffect(() => setName(connection.name), [connection.name])

  const saveApiKey = async () => {
    if (!apiKey.trim()) return
    await request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', {
      apiKey: apiKey.trim(),
    })
    setApiKey('')
    setShowKeyInput(false)
  }

  return (
    <article className="rounded-xl border border-line bg-panel p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          <ProviderIcon providerId={provider.id} name={provider.name} className="size-10" />
          <div>
            <h3 className="text-sm font-semibold">{connection.name}</h3>
            <p className="mt-0.5 text-xs text-muted">
              {connection.email ?? connection.accountLabel ?? (connection.credentialPresent ? 'Credential configured' : 'Not configured')}
            </p>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <Pill value={connection.authState}>auth {connection.authState}</Pill>
          <Pill value={connection.discoveryState}>models {connection.discoveryState}</Pill>
          <Pill value={connection.inferenceState}>inference {connection.inferenceState}</Pill>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            disabled={busy}
            checked={connection.autoSync !== false}
            onChange={(event) => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { autoSync: event.target.checked }))}
          />
          Auto-sync models
        </label>
        <label className="flex items-center gap-2 text-xs text-muted">
          <input
            type="checkbox"
            disabled={busy}
            checked={connection.enabled}
            onChange={(event) => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { enabled: event.target.checked }))}
          />
          Enabled
        </label>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
        <label className="text-xs font-semibold">
          Connection name
          <input value={name} onChange={(event) => setName(event.target.value)} className={`${field} mt-1.5`} />
        </label>
        <div className="flex items-end">
          <button
            type="button"
            disabled={busy || !name.trim() || name.trim() === connection.name}
            onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { name: name.trim() }))}
            className={secondary}
          >
            Save name
          </button>
        </div>
      </div>

      {/* One OAuth access token is not a ring, and a connection whose snapshot carries no `keys`
          array is the legacy single-key shape. Both branches keep today's single input. */}
      {showKeyInput && (isOAuth || !keyRing) && (
        <div id={ringId} className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
          <label className="text-xs font-semibold">
            {isOAuth ? 'Update session token / API key' : 'Update API key'}
            <input
              type="password"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder="Paste new token/key"
              className={`${field} mt-1.5 font-mono`}
            />
          </label>
          <div className="flex items-end gap-2">
            <button
              type="button"
              disabled={busy || !apiKey.trim()}
              onClick={() => run(saveApiKey())}
              className={primary}
            >
              <Save className="size-3.5" />
              Save
            </button>
            <button
              type="button"
              onClick={() => { setShowKeyInput(false); setApiKey('') }}
              className={secondary}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {showKeyInput && !isOAuth && keyRing && (
        <div id={ringId}>
          <ConnectionKeyRing connection={connection} />
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {isOAuth && (
          <button
            type="button"
            disabled={busy}
            onClick={() => run(onConnect(connection.id))}
            className={primary}
          >
            <LogIn className="size-3.5" />
            {connection.authState === 'ready' ? 'Reconnect' : 'Connect account'}
          </button>
        )}
        <button
          type="button"
          aria-expanded={showKeyInput}
          aria-controls={ringId}
          onClick={() => setShowKeyInput((val) => !val)}
          className={secondary}
        >
          <KeyRound className="size-3.5" />
          {keyRing && !isOAuth ? (showKeyInput ? 'Hide keys' : 'Show keys') : connection.credentialPresent ? 'Update key/token' : 'Set key/token'}
        </button>
        <button
          type="button"
          disabled={busy || !connection.credentialPresent}
          onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/models/refresh`, 'POST'))}
          className={secondary}
        >
          <RefreshCw className="size-3.5" />
          Refresh models
        </button>
        <button
          type="button"
          disabled={busy || !connection.credentialPresent}
          onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/quota`, 'GET'))}
          className={secondary}
        >
          Refresh quota
        </button>
        <button
          type="button"
          disabled={busy || keyRingSize(connection) > 0}
          onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'DELETE'))}
          className={`${secondary} text-red-600 dark:text-red-300`}
        >
          <Trash2 className="size-3.5" />
          Delete
        </button>
      </div>
      {deleteBlockedReason(connection) && <p className="mt-2 text-[10px] leading-4 text-muted">{deleteBlockedReason(connection)}</p>}

      {connection.error && <p className="mt-3 text-xs text-red-600 dark:text-red-300">{connection.error}</p>}

      {connection.credentialPresent && connection.authState === 'ready' ? (
        <>
          <InferenceTest key={connection.revision} connection={connection} />
        </>
      ) : (
        <div className="mt-4 rounded-xl border border-dashed border-line/70 bg-panel2/30 p-4 text-center text-xs text-muted space-y-1">
          <KeyRound className="size-4 text-muted/60 mx-auto mb-1" />
          <p className="font-semibold text-fg text-xs">Credentials Required</p>
          <p className="text-[11px] text-muted">
            Configure your API key or connection details above to load and test models.
          </p>
        </div>
      )}

      {connection.quota && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="text-xs font-semibold mb-3">Quota Limits</p>
          <QuotaFamilyBar quota={connection.quota} />
        </div>
      )}
    </article>
  )
}

function _LegacyAccountsSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  const request = useProviderStore((state) => state.request)
  const load = useProviderStore((state) => state.load)
  const busy = useProviderStore((state) => state.busy)
  const [selectedProviderId, setSelectedProviderId] = useState<ProviderId>('antigravity')
  const [name, setName] = useState('Antigravity')
  const [projectId, setProjectId] = useState('')
  const [attempt, setAttempt] = useState<OAuthAttempt | null>(null)
  const popup = useRef<Window | null>(null)

  useEffect(() => {
    if (!attempt || !['pending', 'exchanging'].includes(attempt.status)) return
    let cancelled = false
    const tick = async () => {
      try {
        const next = await api<OAuthAttempt>(`/api/router/oauth/attempts/${encodeURIComponent(attempt.id)}`)
        if (cancelled) return
        setAttempt(next)
        if (!['pending', 'exchanging'].includes(next.status)) {
          popup.current?.close()
          popup.current = null
          await load().catch(() => undefined)
        }
      } catch { /* store reload will expose durable state */ }
    }
    const timer = window.setInterval(() => run(tick()), 900)
    run(tick())
    return () => { cancelled = true; window.clearInterval(timer) }
  }, [attempt?.id, attempt?.status, load])

  const createAccount = async () => {
    await request('/api/router/connections', 'POST', { providerId: 'antigravity', name: name.trim() || 'Antigravity', ...(projectId.trim() ? { projectId: projectId.trim() } : {}) })
    setName('Antigravity')
    setProjectId('')
  }
  const connect = async (connectionId: string) => {
    if (attempt && ['pending', 'exchanging'].includes(attempt.status)) await cancel()
    popup.current = window.open('about:blank', 'boxfox-antigravity-oauth', 'popup,width=520,height=720')
    try {
      const next = await api<OAuthAttempt>('/api/router/oauth/attempts', { method: 'POST', body: { connectionId } })
      setAttempt(next)
      if (popup.current) popup.current.location.href = next.authorizationUrl
    } catch (error) {
      popup.current?.close(); popup.current = null
      throw error
    }
  }
  const cancel = async () => {
    if (!attempt) return
    await api(`/api/router/oauth/attempts/${encodeURIComponent(attempt.id)}`, { method: 'DELETE' })
    popup.current?.close(); popup.current = null; setAttempt(null); await load().catch(() => undefined)
  }

  const routerProviders = snapshot.providers.filter((provider) => provider.authMethod === 'oauth')
  const selectedProvider = routerProviders.find((provider) => provider.id === selectedProviderId) ?? routerProviders[0]
  const accounts = snapshot.connections.filter((connection) => connection.providerId === selectedProvider?.id)
  return (
    <div className="space-y-5">
      <RouterProviderCatalog snapshot={snapshot} selectedId={selectedProvider?.id} onSelect={setSelectedProviderId} />
      <div><h2 className="text-sm font-semibold">{selectedProvider?.name ?? 'Router'} accounts</h2><p className="mt-1 text-xs text-muted">OAuth credentials and project context stay on the BoxFox host. Choose a provider above to manage its connections.</p></div>
      <div className="rounded-xl border border-line bg-panel p-4">
        <div className="grid gap-3 sm:grid-cols-2"><label className="text-xs font-semibold">Account name<input value={name} onChange={(event) => setName(event.target.value)} className={`${field} mt-1.5`} /></label><label className="text-xs font-semibold">Google Cloud project (optional)<input value={projectId} onChange={(event) => setProjectId(event.target.value)} placeholder="Auto-discover when possible" className={`${field} mt-1.5 font-mono`} /></label></div>
        <button type="button" disabled={busy || selectedProvider?.id !== 'antigravity'} onClick={() => run(createAccount())} className={`${primary} mt-3`}><Plus className="size-3.5" />Add {selectedProvider?.name ?? 'router'} account</button>
      </div>
      {attempt && <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-brand/30 bg-brand/5 p-3 text-xs"><span>OAuth {attempt.status}{attempt.error ? ` · ${attempt.error}` : ''}</span>{['pending', 'exchanging'].includes(attempt.status) && <div className="flex gap-2"><a href={attempt.authorizationUrl} target="_blank" rel="noopener noreferrer" className={secondary}>Open sign-in</a><button type="button" onClick={() => run(cancel())} className={secondary}>Cancel OAuth</button></div>}</div>}
      {accounts.length === 0 ? <Empty text={`No ${selectedProvider?.name ?? 'router'} account configured.`} /> : accounts.map((connection) => <AntigravityAccount key={connection.id} connection={connection} onConnect={connect} />)}
    </div>
  )
}
void _LegacyAccountsSection

function RouterProviderCatalog({ snapshot, selectedId, onSelect }: { snapshot: ProviderSnapshot; selectedId?: ProviderId; onSelect: (id: ProviderId) => void }) {
  const providers = snapshot.providers.filter((provider) => provider.authMethod === 'oauth')
  return <section aria-label="Router provider catalog" className="space-y-3"><div className="flex items-end justify-between gap-3"><div><h2 className="text-sm font-semibold">OAuth providers</h2><p className="mt-1 text-xs text-muted">Select a provider first, then connect accounts and discover its available models.</p></div><ShieldCheck className="size-5 text-brand" /></div><div className="grid gap-3 sm:grid-cols-2">{providers.map((provider) => { const count = snapshot.connections.filter((connection) => connection.providerId === provider.id).length; return <button key={provider.id} type="button" aria-pressed={selectedId === provider.id} onClick={() => onSelect(provider.id)} className={`flex items-center gap-3 rounded-xl border p-4 text-left transition ${selectedId === provider.id ? 'border-brand bg-brand/5 ring-1 ring-brand/20' : 'border-line bg-panel hover:border-brand/40'}`}><ProviderIcon providerId={provider.id} name={provider.name} className="size-10" /><span className="min-w-0 flex-1"><span className="block text-sm font-semibold">{provider.name}</span><span className="mt-1 block text-[11px] text-muted">{count ? `${count} connected` : 'No connections'} Â· OAuth</span></span><ChevronRight className="size-4 shrink-0 text-muted" /></button> })}</div><p className="text-[11px] text-muted">API key providers are managed in the API tab. Additional OAuth integrations remain deferred until their adapters are implemented.</p></section>
}

function formatResetTime(resetAt?: string | null) {
  if (!resetAt) return null
  const diffMs = new Date(resetAt).getTime() - Date.now()
  if (diffMs <= 0) return 'Reset now'
  const diffMinutes = Math.floor(diffMs / 60000)
  const days = Math.floor(diffMinutes / 1440)
  const hours = Math.floor((diffMinutes % 1440) / 60)
  const minutes = diffMinutes % 60
  if (days > 0) return `in ${days}d ${hours}h ${minutes}m`
  if (hours > 0) return `in ${hours}h ${minutes}m`
  return `in ${minutes}m`
}

interface QuotaDisplayItem {
  id: string
  name: string
  usedPerThousand: number
  remainingPercent: number
  remainingFraction: number | null
  resetAt?: string | null
  isWeekly?: boolean
}

function getQuotaDisplayItems(quota: ProviderConnection['quota']): QuotaDisplayItem[] {
  if (!quota) return []
  const list: QuotaDisplayItem[] = []

  // Process weekly quotas
  if (quota.weekly && Array.isArray(quota.weekly)) {
    for (const w of quota.weekly) {
      const frac = typeof w.remainingFraction === 'number' && !Number.isNaN(w.remainingFraction) ? w.remainingFraction : 1
      list.push({
        id: `weekly-${w.id}`,
        name: w.name,
        usedPerThousand: Math.round((1 - frac) * 1000),
        remainingPercent: Math.round(frac * 100),
        remainingFraction: w.remainingFraction,
        resetAt: w.resetAt,
        isWeekly: true,
      })
    }
  }

  // Process models quota
  if (quota.models && Array.isArray(quota.models)) {
    const families = new Map<string, { name: string; frac: number; resetAt: string | null }>()
    for (const m of quota.models) {
      let key = m.quotaFamily || m.modelId
      let label = m.modelId
      if (m.modelId.includes('gemini') || m.quotaFamily === 'gemini') {
        key = 'gemini'
        label = 'Gemini (Flash / Pro)'
      } else if (m.modelId.includes('claude') || m.quotaFamily === 'claude_gpt') {
        if (m.modelId.includes('gpt')) {
          key = 'gpt'
          label = 'GPT-OSS 120B (Medium)'
        } else {
          key = 'claude'
          label = 'Claude (Sonnet / Opus)'
        }
      }
      const frac = typeof m.remainingFraction === 'number' && !Number.isNaN(m.remainingFraction) ? m.remainingFraction : 1
      const existing = families.get(key)
      if (!existing || frac < existing.frac) {
        families.set(key, { name: label, frac, resetAt: m.resetAt ?? null })
      }
    }
    for (const [key, val] of families.entries()) {
      list.push({
        id: `family-${key}`,
        name: val.name,
        usedPerThousand: Math.round((1 - val.frac) * 1000),
        remainingPercent: Math.round(val.frac * 100),
        remainingFraction: val.frac,
        resetAt: val.resetAt,
        isWeekly: false,
      })
    }
  }

  return list
}

function QuotaFamilyBar({ quota }: { quota: ProviderConnection['quota'] }) {
  const items = getQuotaDisplayItems(quota)
  if (!items.length) {
    return <p className="text-xs text-muted">No quota telemetry reported for this connection.</p>
  }
  return (
    <div className="space-y-2.5">
      {items.map((item) => {
        const toneColor =
          item.remainingPercent >= 60
            ? 'bg-emerald-500'
            : item.remainingPercent >= 25
              ? 'bg-amber-500'
              : 'bg-red-500'
        const textTone =
          item.remainingPercent >= 60
            ? 'text-emerald-600 dark:text-emerald-400'
            : item.remainingPercent >= 25
              ? 'text-amber-600 dark:text-amber-400'
              : 'text-red-600 dark:text-red-400'
        const resetLabel = formatResetTime(item.resetAt)

        return (
          <div key={item.id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line bg-panel2 px-3 py-2 text-xs">
            <div className="flex min-w-44 items-center gap-2">
              <span className={`size-2 rounded-full ${toneColor}`} />
              <span className="font-semibold text-fg">{item.name}</span>
            </div>
            <div className="flex items-center gap-3 font-mono text-[11px] text-muted">
              <span>{item.usedPerThousand} / 1.000</span>
            </div>
            <div className="h-2 min-w-32 flex-1 max-w-xs overflow-hidden rounded-full bg-panel border border-line/50">
              <div
                className={`h-full rounded-full transition-all duration-500 ${toneColor}`}
                style={{ width: `${Math.min(100, Math.max(0, item.remainingPercent))}%` }}
              />
            </div>
            <div className="flex items-center justify-end gap-3 min-w-28 text-right">
              <span className={`font-bold font-mono text-[11px] ${textTone}`}>{item.remainingPercent}%</span>
              {resetLabel && (
                <span className="text-[10px] text-muted">{resetLabel}</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function QuotaTrackerCard({ connection, snapshot }: { connection: ProviderConnection; snapshot: ProviderSnapshot }) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const provider = providerFor(snapshot, connection.providerId)
  const items = getQuotaDisplayItems(connection.quota)

  return (
    <article className="rounded-xl border border-line bg-panel p-4 sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 pb-3 border-b border-line">
        <div className="flex items-center gap-3">
          <ProviderIcon providerId={connection.providerId} name={provider?.name} className="size-9 rounded-lg border border-line bg-panel2 p-1.5" />
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-semibold">{connection.name}</h3>
              <Pill value={connection.authState}>{connection.authState}</Pill>
            </div>
            <p className="mt-0.5 text-xs text-muted">
              {connection.email ?? connection.accountLabel ?? provider?.name ?? connection.providerId}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-muted">{items.length} quota{items.length === 1 ? '' : 's'}</span>
          <button
            type="button"
            disabled={busy || !connection.credentialPresent}
            onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/quota`, 'GET'))}
            className={secondary}
            title="Refresh quota"
          >
            <RefreshCw className="size-3.5" />
          </button>
        </div>
      </div>
      <div className="mt-4">
        <QuotaFamilyBar quota={connection.quota} />
      </div>
      {connection.quota?.updatedAt && (
        <p className="mt-3 text-right text-[10px] text-muted">
          Last updated: {new Date(connection.quota.updatedAt).toLocaleTimeString()}
          {connection.quota.plan ? ` · ${connection.quota.plan}` : ''}
        </p>
      )}
    </article>
  )
}

function QuotaSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const accounts = snapshot.connections.filter((c) => c.enabled)

  const refreshAll = async () => {
    for (const c of accounts) {
      if (c.credentialPresent) {
        await request(`/api/router/connections/${encodeURIComponent(c.id)}/quota`, 'GET').catch(() => undefined)
      }
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Quota Tracker</h2>
          <p className="mt-1 text-xs text-muted">
            Track and manage your API quota limits, rate limits, and remaining resets across all connected accounts.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted">{accounts.length} active connection{accounts.length === 1 ? '' : 's'}</span>
          <button
            type="button"
            disabled={busy || accounts.length === 0}
            onClick={() => run(refreshAll())}
            className={secondary}
          >
            <RefreshCw className="size-3.5" />
            Refresh all quotas
          </button>
        </div>
      </div>

      {accounts.length === 0 ? (
        <Empty text="No active provider connections found. Connect an account in the Providers tab to track quota." />
      ) : (
        <div className="space-y-4">
          {accounts.map((connection) => (
            <QuotaTrackerCard key={connection.id} connection={connection} snapshot={snapshot} />
          ))}
        </div>
      )}
    </div>
  )
}

function AntigravityAccount({ connection, onConnect }: { connection: ProviderConnection; onConnect: (id: string) => Promise<void> }) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const [project, setProject] = useState(connection.projectId ?? '')
  const [name, setName] = useState(connection.name)
  useEffect(() => setProject(connection.projectId ?? ''), [connection.projectId, connection.revision])
  useEffect(() => setName(connection.name), [connection.name])
  return (
    <article className="rounded-xl border border-line bg-panel p-4 sm:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div className="flex items-center gap-3"><ProviderIcon providerId="antigravity" name="Antigravity" className="size-10" /><div><h3 className="text-sm font-semibold">{connection.name}</h3><p className="mt-0.5 text-xs text-muted">{connection.email ?? connection.accountLabel ?? 'Not signed in'}</p></div></div><div className="flex flex-wrap gap-1.5"><Pill value={connection.authState}>auth {connection.authState}</Pill><Pill value={connection.projectState}>project {connection.projectState}</Pill><Pill value={connection.discoveryState}>models {connection.discoveryState}</Pill></div></div>
      <div className="mt-4 flex flex-wrap gap-1.5"><Pill value={connection.inferenceState}>inference {connection.inferenceState}</Pill><label className="ml-auto flex items-center gap-2 text-xs text-muted"><input type="checkbox" disabled={busy} checked={connection.autoSync !== false} onChange={(event) => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { autoSync: event.target.checked }))} />Auto-sync models</label><label className="flex items-center gap-2 text-xs text-muted"><input type="checkbox" disabled={busy} checked={connection.enabled} onChange={(event) => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { enabled: event.target.checked }))} />Enabled</label></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]"><label className="text-xs font-semibold">Account name<input value={name} onChange={(event) => setName(event.target.value)} className={`${field} mt-1.5`} /></label><div className="flex items-end"><button type="button" disabled={busy || !name.trim()} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { name: name.trim() }))} className={secondary}>Save name</button></div></div>
      <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]"><label className="text-xs font-semibold">Project ID<input value={project} onChange={(event) => setProject(event.target.value)} placeholder="Required only when auto-discovery cannot resolve it" className={`${field} mt-1.5 font-mono`} /></label><div className="flex items-end"><button type="button" disabled={busy || !project.trim() || project.trim() === connection.projectId} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { projectId: project.trim() }))} className={secondary}><Save className="size-3.5" />Repair project</button></div></div>
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => run(onConnect(connection.id))} className={primary}><LogIn className="size-3.5" />{connection.authState === 'ready' ? 'Reconnect' : 'Connect account'}</button>
        <button type="button" disabled={busy || !connection.credentialPresent} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/models/refresh`, 'POST'))} className={secondary}><RefreshCw className="size-3.5" />Refresh models</button>
        <button type="button" disabled={busy || !connection.credentialPresent} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/quota`, 'GET'))} className={secondary}>Refresh quota</button>
        <button type="button" disabled={busy} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'DELETE'))} className={`${secondary} text-red-600 dark:text-red-300`}><Trash2 className="size-3.5" />Disconnect</button>
      </div>
      {connection.error && <p className="mt-3 text-xs text-red-600 dark:text-red-300">{connection.error}</p>}
      {connection.credentialPresent && connection.authState === 'ready' ? (
        <>
          <InferenceTest key={connection.revision} connection={connection} />
        </>
      ) : (
        <div className="mt-4 rounded-xl border border-dashed border-line/70 bg-panel2/30 p-4 text-center text-xs text-muted space-y-1">
          <LogIn className="size-4 text-muted/60 mx-auto mb-1" />
          <p className="font-semibold text-fg text-xs">Account Authorization Required</p>
          <p className="text-[11px] text-muted">
            Click <strong>{connection.authState === 'ready' ? 'Reconnect' : 'Connect account'}</strong> above to authorize and discover your models.
          </p>
        </div>
      )}
      <p className="mt-4 text-[11px] text-muted">Models synced: {connection.lastModelSyncAt ? new Date(connection.lastModelSyncAt).toLocaleString() : 'Never'} · Quota updated: {connection.quota?.updatedAt ? new Date(connection.quota.updatedAt).toLocaleString() : 'No data'}{connection.quota?.plan ? ` · Plan: ${connection.quota.plan}` : ''}{!connection.quota?.models.length && ' · No quota data available'}</p>
      {connection.quota && (
        <div className="mt-4 border-t border-line pt-4">
          <p className="text-xs font-semibold mb-3">Quota Limits</p>
          <QuotaFamilyBar quota={connection.quota} />
        </div>
      )}
    </article>
  )
}

function _LegacyModelsSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const models = snapshot.connections.filter((connection) => connection.models.length > 0)
  return <div className="space-y-4"><div><h2 className="text-sm font-semibold">Model inventory</h2><p className="mt-1 text-xs text-muted">Live discovery is the source of truth for availability. Enable only models BoxFox may route to.</p></div>{models.length === 0 ? <Empty text="Discover models from a connected provider first." /> : models.map((connection) => <article key={connection.id} className="rounded-xl border border-line bg-panel p-4"><div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><ProviderIcon providerId={connection.providerId} className="size-7" /><span className="text-xs font-semibold">{connection.name}</span></div><button type="button" disabled={busy || !connection.credentialPresent} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/models/refresh`, 'POST'))} className={secondary}><RefreshCw className="size-3.5" />Refresh</button></div><ModelToggleList connection={connection} /></article>)}</div>
}

function ModelsSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const models = snapshot.connections.filter((connection) => connection.models.length > 0)
  const sources = snapshot.providers.map((provider) => ({ provider, connections: snapshot.connections.filter((connection) => connection.providerId === provider.id) }))
  return <div className="space-y-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-sm font-semibold">Available models</h2><p className="mt-1 text-xs text-muted">Model inventory is discovered from each provider connection. BoxFox never routes to a model that has not been returned by the provider.</p></div><div className="flex items-center gap-1.5 rounded-full border border-line bg-panel2 px-2.5 py-1 text-[10px] text-muted"><Database className="size-3.5" />Live inventory</div></div><section className="rounded-xl border border-line bg-panel p-4"><div className="mb-3 flex items-center gap-2"><Server className="size-4 text-brand" /><h3 className="text-xs font-semibold">Provider sources</h3></div><div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{sources.map(({ provider, connections }) => <div key={provider.id} className="flex items-center gap-2 rounded-lg border border-line bg-panel2 px-3 py-2.5"><ProviderIcon providerId={provider.id} name={provider.name} className="size-7" /><div className="min-w-0 flex-1"><p className="truncate text-xs font-semibold">{provider.name}</p><p className="mt-0.5 text-[10px] text-muted">{connections.length ? `${connections.length} connection${connections.length === 1 ? '' : 's'}` : 'No connections'} · {connections.reduce((count, connection) => count + connection.models.length, 0)} models</p></div><span className={`size-2 rounded-full ${connections.some((connection) => connection.discoveryState === 'ready') ? 'bg-emerald-500' : 'bg-muted/50'}`} title={connections.some((connection) => connection.discoveryState === 'ready') ? 'Discovery ready' : 'Discovery required'} /></div>)}</div></section>{models.length === 0 ? <Empty text="No live models yet. Add a provider connection, finish OAuth/project setup, or use Refresh models; the model list will appear here automatically." /> : models.map((connection) => <article key={connection.id} className="rounded-xl border border-line bg-panel p-4"><div className="flex flex-wrap items-center justify-between gap-3"><div className="flex items-center gap-2"><ProviderIcon providerId={connection.providerId} name={providerFor(snapshot, connection.providerId)?.name} className="size-8" /><div><p className="text-xs font-semibold">{connection.name}</p><p className="mt-0.5 text-[10px] text-muted">{providerFor(snapshot, connection.providerId)?.name ?? connection.providerId} · {connection.models.length} discovered</p></div></div><button type="button" disabled={busy || !connection.credentialPresent} onClick={() => run(request(`/api/router/connections/${encodeURIComponent(connection.id)}/models/refresh`, 'POST'))} className={secondary}><RefreshCw className="size-3.5" />Refresh</button></div><ModelToggleList connection={connection} /></article>)}</div>
}

function RoutingSection({ snapshot, busy }: { snapshot: ProviderSnapshot; busy: boolean }) {
  const request = useProviderStore((state) => state.request)
  const targets = publicTargets(snapshot)
  const [aliasName, setAliasName] = useState('')
  const [strategy, setStrategy] = useState<RouterAlias['strategy']>('fallback')
  const [targetId, setTargetId] = useState(targets[0]?.id ?? '')
  const defaultValue = snapshot.defaultRoute.aliasId ? `a:${snapshot.defaultRoute.aliasId}` : snapshot.defaultRoute.connectionId && snapshot.defaultRoute.modelId ? `d:${snapshot.defaultRoute.connectionId}/${snapshot.defaultRoute.modelId}` : ''
  const [defaultSelection, setDefaultSelection] = useState(defaultValue)
  useEffect(() => { setTargetId((current) => targets.some((target) => target.id === current) ? current : (targets[0]?.id ?? '')); setDefaultSelection(defaultValue) }, [snapshot.defaultRoute.aliasId, snapshot.defaultRoute.connectionId, snapshot.defaultRoute.modelId, targets.length])

  const create = async () => {
    const target = targets.find((item) => item.id === targetId)
    if (!aliasName.trim() || !target) return
    await request('/api/router/aliases', 'POST', { name: aliasName.trim(), strategy, targets: [{ connectionId: target.connectionId, modelId: target.modelId }] })
    setAliasName('')
  }
  const setDefault = async () => {
    let body: ProviderDefault
    if (defaultSelection.startsWith('a:')) body = { aliasId: defaultSelection.slice(2), connectionId: null, modelId: null }
    else if (defaultSelection.startsWith('d:')) {
      const value = defaultSelection.slice(2); const match = targets.find((target) => target.id === value); if (!match) return
      body = { aliasId: null, connectionId: match.connectionId, modelId: match.modelId }
    } else return
    await request('/api/router/default', 'PUT', body)
  }

  return (
    <div className="space-y-5"><div><h2 className="text-sm font-semibold">Routing</h2><p className="mt-1 text-xs text-muted">Aliases expose stable public model names over one or more enabled targets.</p></div>
      <section className="rounded-xl border border-line bg-panel p-4"><h3 className="text-xs font-semibold">Default route</h3><div className="mt-3 flex flex-col gap-2 sm:flex-row"><select value={defaultSelection} onChange={(event) => setDefaultSelection(event.target.value)} className={field}><option value="">Choose default…</option>{targets.map((target) => <option key={`d:${target.id}`} value={`d:${target.id}`}>{target.label}</option>)}{snapshot.aliases.filter((alias) => alias.enabled).map((alias) => <option key={`a:${alias.id}`} value={`a:${alias.id}`}>Alias · {alias.name}</option>)}</select><button type="button" disabled={busy || !defaultSelection} onClick={() => run(setDefault())} className={primary}>Save default</button></div></section>
      <section className="rounded-xl border border-line bg-panel p-4"><h3 className="text-xs font-semibold">Create alias</h3><div className="mt-3 grid gap-2 sm:grid-cols-[1fr_150px_1.5fr_auto]"><input value={aliasName} onChange={(event) => setAliasName(event.target.value)} placeholder="fast-model" className={field} /><select value={strategy} onChange={(event) => setStrategy(event.target.value as RouterAlias['strategy'])} className={field}><option value="fallback">Fallback</option><option value="round_robin">Round robin</option></select><select value={targetId} onChange={(event) => setTargetId(event.target.value)} className={field}><option value="">Choose target…</option>{targets.map((target) => <option key={target.id} value={target.id}>{target.label}</option>)}</select><button type="button" disabled={busy || !aliasName.trim() || !targetId} onClick={() => run(create())} className={primary}><Plus className="size-3.5" />Add</button></div></section>
      {snapshot.aliases.length === 0 ? <Empty text="No routing aliases configured." /> : snapshot.aliases.map((alias) => <AliasCard key={alias.id} snapshot={snapshot} alias={alias} />)}
    </div>
  )
}

function AliasCard({ snapshot, alias }: { snapshot: ProviderSnapshot; alias: RouterAlias }) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const targets = publicTargets(snapshot)
  const [name, setName] = useState(alias.name)
  const [strategy, setStrategy] = useState(alias.strategy)
  const [addTarget, setAddTarget] = useState(targets.find((target) => !alias.targets.some((existing) => existing.connectionId === target.connectionId && existing.modelId === target.modelId))?.id ?? '')
  useEffect(() => { setName(alias.name); setStrategy(alias.strategy) }, [alias.name, alias.strategy])
  const patch = (nextTargets: RouteTarget[] = alias.targets, extra: Record<string, unknown> = {}) => request(`/api/router/aliases/${encodeURIComponent(alias.id)}`, 'PATCH', { name: name.trim() || alias.name, strategy, targets: nextTargets, enabled: alias.enabled, ...extra })
  const move = (index: number, direction: -1 | 1) => { const next = [...alias.targets]; const target = index + direction; if (target < 0 || target >= next.length) return; [next[index], next[target]] = [next[target], next[index]]; run(patch(next)) }
  const append = () => { const selected = targets.find((target) => target.id === addTarget); if (!selected) return; run(patch([...alias.targets, { connectionId: selected.connectionId, modelId: selected.modelId }])) }
  return <article className="rounded-xl border border-line bg-panel p-4"><div className="flex flex-wrap items-start justify-between gap-3"><div className="grid flex-1 gap-2 sm:grid-cols-[1fr_160px]"><input value={name} onChange={(event) => setName(event.target.value)} className={field} aria-label="Alias name" /><select value={strategy} onChange={(event) => setStrategy(event.target.value as RouterAlias['strategy'])} className={field}><option value="fallback">Fallback</option><option value="round_robin">Round robin</option></select></div><div className="flex gap-2"><button type="button" disabled={busy} onClick={() => run(patch())} className={secondary}><Save className="size-3.5" />Save</button><button type="button" disabled={busy} onClick={() => run(request(`/api/router/aliases/${encodeURIComponent(alias.id)}`, 'DELETE'))} className={`${secondary} text-red-600 dark:text-red-300`}><Trash2 className="size-3.5" /></button></div></div><label className="mt-3 flex items-center gap-2 text-xs text-muted"><input type="checkbox" checked={alias.enabled} onChange={(event) => run(patch(alias.targets, { enabled: event.target.checked }))} />Enabled</label><div className="mt-3 space-y-2">{alias.targets.map((target, index) => { const found = targets.find((item) => item.connectionId === target.connectionId && item.modelId === target.modelId); return <div key={`${target.connectionId}/${target.modelId}`} className="flex items-center justify-between gap-2 rounded-lg border border-line bg-panel2 px-3 py-2 text-xs"><span className="min-w-0 truncate">{found?.label ?? `${target.connectionId}/${target.modelId}`}</span><span className="flex shrink-0 gap-1"><button type="button" aria-label="Move target up" disabled={index === 0 || busy} onClick={() => move(index, -1)} className="rounded p-1 hover:bg-panel"><ArrowUp className="size-3.5" /></button><button type="button" aria-label="Move target down" disabled={index === alias.targets.length - 1 || busy} onClick={() => move(index, 1)} className="rounded p-1 hover:bg-panel"><ArrowDown className="size-3.5" /></button><button type="button" aria-label="Remove target" disabled={alias.targets.length === 1 || busy} onClick={() => run(patch(alias.targets.filter((_, i) => i !== index)))} className="rounded p-1 text-red-600 hover:bg-red-500/10"><X className="size-3.5" /></button></span></div> })}</div><div className="mt-3 flex gap-2"><select value={addTarget} onChange={(event) => setAddTarget(event.target.value)} className={field}><option value="">Add target…</option>{targets.filter((target) => !alias.targets.some((current) => current.connectionId === target.connectionId && current.modelId === target.modelId)).map((target) => <option key={target.id} value={target.id}>{target.label}</option>)}</select><button type="button" disabled={!addTarget || busy || alias.targets.length >= 16} onClick={append} className={secondary}><Plus className="size-3.5" />Target</button></div></article>
}

function _LegacyUsageSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  return <div className="space-y-4"><div><h2 className="text-sm font-semibold">Usage</h2><p className="mt-1 text-xs text-muted">Actual router requests recorded by the BoxFox engine.</p></div>{snapshot.usage.length === 0 ? <Empty text="No router requests recorded yet." /> : <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[760px] text-left text-xs"><thead className="bg-panel2 text-muted"><tr><th className="px-3 py-2">Time</th><th className="px-3 py-2">Target</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Latency</th><th className="px-3 py-2">Tokens</th><th className="px-3 py-2">Request</th></tr></thead><tbody>{snapshot.usage.map((usage) => <tr key={usage.id} className="border-t border-line"><td className="px-3 py-2">{new Date(usage.createdAt).toLocaleString()}</td><td className="px-3 py-2 font-mono">{usage.aliasId ?? (usage.connectionId && usage.modelId ? `${usage.connectionId.slice(0, 8)}…/${usage.modelId}` : '—')}</td><td className="px-3 py-2"><Pill value={usage.status}>{usage.status}</Pill></td><td className="px-3 py-2">{usage.latencyMs} ms</td><td className="px-3 py-2">{usage.inputTokens ?? '?'} / {usage.outputTokens ?? '?'}</td><td className="px-3 py-2 font-mono text-muted">{usage.requestId}</td></tr>)}</tbody></table></div>}</div>
}

// Kept out of the render tree while the original chat/settings migration is
// staged; these references keep TypeScript from treating the compatibility
// helpers as accidental declarations.
void _LegacyModelsSection
void _LegacyUsageSection

function formatTokenCount(value: number | null) {
  if (value === null) return 'No data'
  return new Intl.NumberFormat().format(value)
}

/**
 * A cost only means something with its provenance. `null` keeps the two honest
 * outcomes apart: a subscription connection is `Included in plan`, a metered
 * connection with no resolvable price is `No price` — never `$0`, which would be
 * a claim nobody made, and never `No data`, which reads as a missing field.
 */
function formatUsd(value: number | null, costMode?: 'metered' | 'included' | null) {
  if (value === null) return costMode === 'included' ? 'Included in plan' : 'No price'
  if (value === 0) return '$0'
  if (value < 0.0001) return '<$0.0001'
  return `$${value.toFixed(4)}`
}

// The basis a row's cost was stored with. Before costs carried a basis the router
// only recorded a number the provider itself reported, so an absent basis on a row
// that has a cost is `reported` — never an estimate.
function costBasisOf(item: RouterUsage) {
  return item.costBasis ?? (item.cost === null ? null : 'reported')
}

/** DeepSeek peak hours: 01:00–04:00 and 06:00–10:00 UTC, Monday–Friday. */
function deepSeekPeakAt(createdAt: string) {
  const at = new Date(createdAt)
  if (Number.isNaN(at.getTime())) return true
  const day = at.getUTCDay()
  if (day === 0 || day === 6) return false
  const minutes = at.getUTCHours() * 60 + at.getUTCMinutes()
  return (minutes >= 60 && minutes < 240) || (minutes >= 360 && minutes < 600)
}

/** The one caveat the shipped DeepSeek table cannot fix: its published peak windows
 *  exclude Chinese public holidays and BoxFox does not ship that calendar, so a
 *  holiday hour is priced as a working hour and can estimate up to 2× high. */
const PEAK_HOLIDAY_CAVEAT = 'Chinese public holidays are excluded from the published peak window and BoxFox does not track that calendar, so these hours can estimate up to 2× high.'

/** Why a cost number exists, in the provider's or the user's own words. */
function costNote(item: RouterUsage) {
  const basis = costBasisOf(item)
  if (basis === 'ping') return "Estimated from the price published in the provider's model list"
  if (basis === 'manual') return 'Estimated from the price you set for this model'
  if (basis === 'documented') {
    if (deepSeekPeakAt(item.createdAt)) return `Estimated from the documented DeepSeek price (peak). ${PEAK_HOLIDAY_CAVEAT}`
    const at = new Date(item.createdAt)
    const time = `${String(at.getUTCHours()).padStart(2, '0')}:${String(at.getUTCMinutes()).padStart(2, '0')}`
    return `Estimated from the documented DeepSeek price (off-peak at ${time} UTC). ${PEAK_HOLIDAY_CAVEAT}`
  }
  return 'Reported by the provider'
}

/** One cost cell: a reported number is a fact, an estimate says so in the cell. */
function UsageCost({ item, costMode }: { item: RouterUsage; costMode?: 'metered' | 'included' | null }) {
  if (item.cost === null) {
    return costMode === 'included'
      ? <span className="text-muted" title="This connection is a subscription: BoxFox does not bill per token here.">Included in plan</span>
      : <span className="text-muted" title="Set a price for this model in Providers → Manage models">No price</span>
  }
  const estimated = item.estimated ?? (costBasisOf(item) !== 'reported')
  if (!estimated) return <span className="font-semibold" title={costNote(item)}>{formatUsd(item.cost)}</span>
  return <span className="inline-flex items-baseline gap-1" title={costNote(item)}><span>{formatUsd(item.cost)}</span><span className="text-[9px] uppercase text-amber-500">est.</span></span>
}

function usageTotal(usage: ProviderSnapshot['usage'], field: 'inputTokens' | 'cachedTokens' | 'cacheCreationTokens' | 'reasoningTokens' | 'outputTokens' | 'totalTokens' | 'cost') {
  const values = usage.map((item) => item[field]).filter((value): value is number => typeof value === 'number' && Number.isFinite(value))
  return values.length ? values.reduce((sum, value) => sum + value, 0) : null
}

function UsageMetric({ label, value, detail, icon, tone = 'text-brand' }: { label: string; value: string; detail?: React.ReactNode; icon: React.ReactNode; tone?: string }) {
  return <div className="rounded-xl border border-line bg-panel p-4"><div className={`flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wide text-muted ${tone}`}>{icon}<span>{label}</span></div><p className="mt-2 text-xl font-semibold text-fg">{value}</p>{detail && <div className="mt-1 text-[10px] leading-4 text-muted">{detail}</div>}</div>
}

function UsageSection({ snapshot }: { snapshot: ProviderSnapshot }) {
  const usage = snapshot.usage
  const input = usageTotal(usage, 'inputTokens')
  const cached = usageTotal(usage, 'cachedTokens')
  const cacheCreation = usageTotal(usage, 'cacheCreationTokens')
  const reasoning = usageTotal(usage, 'reasoningTokens')
  const output = usageTotal(usage, 'outputTokens')
  const total = usageTotal(usage, 'totalTokens')
  const cost = usageTotal(usage, 'cost')
  const connectionById = useMemo(() => new Map(snapshot.connections.map((connection) => [connection.id, connection])), [snapshot.connections])
  // Counted by provenance, so the KPI says how much of the number is a fact:
  // `reported` rows are the provider's own cost, everything else is our estimate,
  // and the rest carry no price at all (including the subscription connections,
  // whose "Included in plan" is not a missing value).
  const reportedRows = usage.filter((item) => costBasisOf(item) === 'reported').length
  const estimatedRows = usage.filter((item) => {
    const basis = costBasisOf(item)
    return basis !== null && basis !== 'reported'
  }).length
  const includedRows = usage.filter((item) => item.cost === null && item.connectionId && connectionById.get(item.connectionId)?.costMode === 'included').length
  const noPriceRows = usage.filter((item) => item.cost === null).length - includedRows
  const kpiCostMode = usage.length > 0 && includedRows === usage.length ? 'included' : 'metered'
  const chartMax = Math.max(input ?? 0, output ?? 0, 1)
  return <div className="space-y-5">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><h2 className="text-sm font-semibold">Usage & analytics</h2><p className="mt-1 text-xs text-muted">Router requests recorded by BoxFox. Token fields stay unknown when the upstream does not report them.</p></div>
      <div className="flex items-center gap-1.5 rounded-full border border-line bg-panel2 px-2.5 py-1 text-[10px] text-muted"><Gauge className="size-3.5" />Last {usage.length} records</div>
    </div>
    {snapshot.connections.some((c) => c.quota && ((c.quota.models && c.quota.models.length > 0) || (c.quota.weekly && c.quota.weekly.length > 0))) && (
      <section className="rounded-xl border border-line bg-panel p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3 mb-3">
          <div className="flex items-center gap-2">
            <Gauge className="size-4 text-brand" />
            <h3 className="text-xs font-semibold">Live Quota Limits</h3>
          </div>
          <span className="text-[10px] text-muted">Remaining quota per account</span>
        </div>
        <div className="space-y-4">
          {snapshot.connections
            .filter((c) => c.quota && ((c.quota.models && c.quota.models.length > 0) || (c.quota.weekly && c.quota.weekly.length > 0)))
            .map((connection) => (
              <div key={connection.id} className="space-y-2">
                <div className="flex items-center gap-2 text-xs font-semibold">
                  <ProviderIcon providerId={connection.providerId} className="size-4" />
                  <span>{connection.name}</span>
                  <span className="text-[10px] font-normal text-muted">{connection.email ?? ''}</span>
                </div>
                <QuotaFamilyBar quota={connection.quota} />
              </div>
            ))}
        </div>
      </section>
    )}
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><UsageMetric label="Recorded requests" value={String(usage.length)} icon={<BarChart3 className="size-3.5" />} /><UsageMetric label="Input tokens" value={formatTokenCount(input)} icon={<Database className="size-3.5" />} /><UsageMetric label="Cached tokens" value={formatTokenCount(cached)} icon={<Database className="size-3.5" />} /><UsageMetric label="Output tokens" value={formatTokenCount(output)} icon={<Server className="size-3.5" />} /><UsageMetric label="Estimated cost" value={formatUsd(cost, kpiCostMode)} detail={<><span>{`Reported ${reportedRows} · Estimated ${estimatedRows} · No price ${noPriceRows}`}</span>{includedRows > 0 && <span>{` · Included ${includedRows}`}</span>}{estimatedRows > 0 && <span className="ml-1 font-semibold text-amber-500" title="Some rows carry a cost BoxFox estimated from a published price, not one the provider reported.">Includes estimates</span>}</>} icon={<Gauge className="size-3.5" />} tone="text-amber-500" /></div><section className="rounded-xl border border-line bg-panel p-4"><div className="flex items-center justify-between gap-3"><div><h3 className="text-xs font-semibold">Token composition</h3><p className="mt-1 text-[10px] text-muted">Input includes cache-read and cache-write tokens when the provider reports them.</p></div><span className="text-[10px] text-muted">Total {formatTokenCount(total)}</span></div><div className="mt-4 space-y-3"><div className="flex items-center gap-3 text-[11px]"><span className="w-20 text-muted">Input</span><div className="h-2 flex-1 overflow-hidden rounded-full bg-panel2"><div className="h-full rounded-full bg-brand" style={{ width: `${Math.round(((input ?? 0) / chartMax) * 100)}%` }} /></div><span className="w-20 text-right font-mono">{formatTokenCount(input)}</span></div><div className="flex items-center gap-3 text-[11px]"><span className="w-20 text-muted">Output</span><div className="h-2 flex-1 overflow-hidden rounded-full bg-panel2"><div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.round(((output ?? 0) / chartMax) * 100)}%` }} /></div><span className="w-20 text-right font-mono">{formatTokenCount(output)}</span></div></div><div className="mt-4 flex flex-wrap gap-3 text-[10px] text-muted"><span>Cache write: {formatTokenCount(cacheCreation)}</span><span>Reasoning: {formatTokenCount(reasoning)}</span></div></section>{usage.length === 0 ? <Empty text="No router requests recorded yet. Token and cost analytics will appear after a completed inference." /> : <div className="overflow-x-auto rounded-xl border border-line"><table className="w-full min-w-[1020px] text-left text-xs"><thead className="bg-panel2 text-muted"><tr><th className="px-3 py-2">Time</th><th className="px-3 py-2">Target</th><th className="px-3 py-2">Status</th><th className="px-3 py-2 text-right">Input</th><th className="px-3 py-2 text-right">Cached</th><th className="px-3 py-2 text-right">Output</th><th className="px-3 py-2 text-right">Total</th><th className="px-3 py-2 text-right">Cost</th><th className="px-3 py-2">Latency</th><th className="px-3 py-2">Request</th></tr></thead><tbody>{usage.map((item) => { const connection = item.connectionId ? snapshot.connections.find((candidate) => candidate.id === item.connectionId) : null; const provider = connection ? providerFor(snapshot, connection.providerId) : null; return <tr key={item.id} className="border-t border-line"><td className="px-3 py-2">{new Date(item.createdAt).toLocaleString()}</td><td className="px-3 py-2"><div className="flex items-center gap-2"><ProviderIcon providerId={connection?.providerId ?? 'custom'} name={provider?.name} className="size-5" /><span className="min-w-0"><span className="block max-w-48 truncate font-semibold">{connection?.name ?? item.connectionId ?? 'Router'}</span><span className="block max-w-48 truncate font-mono text-[10px] text-muted">{item.aliasId ?? item.modelId ?? 'default'}</span></span></div></td><td className="px-3 py-2"><Pill value={item.status}>{item.status}</Pill></td><td className="px-3 py-2 text-right font-mono">{formatTokenCount(item.inputTokens)}</td><td className="px-3 py-2 text-right font-mono">{formatTokenCount(item.cachedTokens)}</td><td className="px-3 py-2 text-right font-mono">{formatTokenCount(item.outputTokens)}</td><td className="px-3 py-2 text-right font-mono">{formatTokenCount(item.totalTokens)}</td><td className="px-3 py-2 text-right font-mono"><UsageCost item={item} costMode={connection?.costMode} /></td><td className="px-3 py-2">{item.latencyMs} ms</td><td className="px-3 py-2 font-mono text-muted">{item.requestId}</td></tr> })}</tbody></table></div>}</div>
}

function AccessSection({ snapshot, busy }: { snapshot: ProviderSnapshot; busy: boolean }) {
  const request = useProviderStore((state) => state.request)
  const models = useMemo(() => [...publicTargets(snapshot).map((target) => ({ id: target.id, label: target.label })), ...snapshot.aliases.filter((alias) => alias.enabled).map((alias) => ({ id: alias.name, label: `Alias · ${alias.name}` }))], [snapshot])
  const [name, setName] = useState('')
  const [allowed, setAllowed] = useState<string[]>([])
  const [rawKey, setRawKey] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)
  const endpoint = `${window.location.origin}/v1`
  const example = `curl ${endpoint}/chat/completions \\\n  -H "Authorization: Bearer YOUR_BOXFOX_KEY" \\\n  -H "Content-Type: application/json" \\\n  -d '{"model":"YOUR_ALIAS_OR_MODEL_ID","messages":[{"role":"user","content":"Hello"}],"stream":true}'`
  const create = async () => {
    const result = await request('/api/router/keys', 'POST', { name: name.trim(), allowedModels: allowed }) as { key: string }
    setRawKey(result.key); setName(''); setAllowed([]); setCopied(false)
  }
  const copy = async () => { if (!rawKey) return; await navigator.clipboard.writeText(rawKey); setCopied(true) }
  return <div className="space-y-5"><div><h2 className="text-sm font-semibold">API Access</h2><p className="mt-1 text-xs text-muted">Use <code className="rounded bg-panel2 px-1">/v1/chat/completions</code> and <code className="rounded bg-panel2 px-1">/v1/models</code> with a BoxFox Bearer key.</p></div><section><p>BoxFox endpoint</p><code>{endpoint}</code><pre style={{overflowX: 'auto', fontSize: 11, marginTop: 12}}>{example}</pre></section>{rawKey && <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-4"><p className="text-xs font-semibold text-amber-800 dark:text-amber-200">Copy this key now. BoxFox will not show the raw value again.</p><div className="mt-2 flex gap-2"><input readOnly value={rawKey} className={`${field} font-mono`} /><button type="button" onClick={() => run(copy())} className={secondary}>{copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}{copied ? 'Copied' : 'Copy'}</button></div></div>}<section className="rounded-xl border border-line bg-panel p-4"><label className="text-xs font-semibold">Key name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Local client" className={`${field} mt-1.5`} /></label><div className="mt-4"><p className="text-xs font-semibold">Allowed models</p><p className="mt-1 text-[11px] text-muted">Leave every option unchecked to allow all enabled targets.</p><div className="mt-2 grid gap-2 sm:grid-cols-2">{models.map((model) => <label key={model.id} className="flex items-center gap-2 rounded-md border border-line bg-panel2 px-3 py-2 text-xs"><input type="checkbox" checked={allowed.includes(model.id)} onChange={() => setAllowed((current) => current.includes(model.id) ? current.filter((id) => id !== model.id) : [...current, model.id])} /><span className="min-w-0 truncate" title={model.id}>{model.label}</span></label>)}</div></div><button type="button" disabled={busy || !name.trim()} onClick={() => run(create())} className={`${primary} mt-4`}><KeyRound className="size-3.5" />Create client key</button></section><section className="space-y-2">{snapshot.keys.length === 0 ? <Empty text="No client keys created." /> : snapshot.keys.map((key) => <div key={key.id} className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-panel p-4"><div><p className="text-xs font-semibold">{key.name}</p><p className="mt-1 text-[11px] text-muted"><span className="font-mono">{key.prefix}…</span> · {key.allowedModels.length ? `${key.allowedModels.length} allowed model(s)` : 'All enabled models'} · {key.lastUsedAt ? `last used ${new Date(key.lastUsedAt).toLocaleString()}` : 'never used'}</p></div><button type="button" disabled={busy || !key.enabled} onClick={() => run(request(`/api/router/keys/${encodeURIComponent(key.id)}`, 'DELETE'))} className={`${secondary} text-red-600 dark:text-red-300`}>{key.enabled ? 'Revoke' : 'Revoked'}</button></div>)}</section></div>
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-xl border border-dashed border-line bg-panel/50 px-5 py-8 text-center text-xs text-muted">{text}</div>
}
