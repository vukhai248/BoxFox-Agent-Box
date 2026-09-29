import { useId, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import type { ProviderConnection, ProviderDefinition, ProviderId } from '../../types/provider'
import { ProviderIcon } from '../providers/ProviderIcon'

export interface ProviderRailGroup {
  id: string
  label: string
  providers: ProviderDefinition[]
}

function providerConnections(connections: ProviderConnection[], providerId: string) {
  return connections.filter((connection) => connection.providerId === providerId)
}

/** One honest status line per provider, read from data the snapshot already holds. */
function providerStatusLine(providerConnectionList: ProviderConnection[]) {
  if (providerConnectionList.length === 0) return 'No connection · needs key'
  const readyCount = providerConnectionList.filter((connection) => connection.authState === 'ready').length
  if (readyCount > 0) return `${readyCount} connection ready`
  if (providerConnectionList.some((connection) => connection.authState === 'expired')) return 'auth expired'
  if (providerConnectionList.some((connection) => connection.discoveryState === 'failed')) return 'models failed'
  if (providerConnectionList.some((connection) => connection.inferenceState === 'failed')) return 'inference failed'
  return 'auth required'
}

export function ProviderRail({
  label,
  groups,
  connections,
  selectedId,
  onSelect,
  statusLine = providerStatusLine,
  showModelCount = true,
}: {
  label: string
  groups: ProviderRailGroup[]
  connections: ProviderConnection[]
  selectedId: string
  onSelect: (id: ProviderId) => void
  /** Row summary. The API tab defaults to an auth-readiness sentence; the Router
      tab keeps the wording its catalog cards used (`n connections · m models`). */
  statusLine?: (providerConnections: ProviderConnection[]) => string
  /** The trailing `N models` chip, for a caller whose summary already carries it. */
  showModelCount?: boolean
}) {
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [mobileOpen, setMobileOpen] = useState(false)
  const rowRefs = useRef<Array<HTMLButtonElement | null>>([])
  const baseId = useId()
  const navId = `${baseId}-rail`

  const normalized = query.trim().toLowerCase()
  const searching = normalized.length > 0
  const totalProviders = groups.reduce((count, group) => count + group.providers.length, 0)
  const connectedCount = groups.reduce(
    (count, group) => count + group.providers.filter((provider) => providerConnections(connections, provider.id).length > 0).length,
    0,
  )
  const selectedName = groups.flatMap((group) => group.providers).find((provider) => provider.id === selectedId)?.name ?? 'No provider'

  const matches = (provider: ProviderDefinition) => `${provider.name} ${provider.id}`.toLowerCase().includes(normalized)
  const visibleGroups = groups
    .map((group) => {
      const matched = searching ? group.providers.filter(matches) : group.providers
      const isCollapsed = Boolean(collapsed[group.id]) && !searching
      const shown = isCollapsed ? [] : matched
      return { ...group, matched, shown, collapsed: isCollapsed }
    })
    .filter((group) => group.providers.length > 0 && (!searching || group.matched.length > 0))
  const rows = visibleGroups.flatMap((group) => group.shown.map((provider) => ({ group, provider })))

  const moveFocus = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const last = rows.length - 1
    if (last < 0) return
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? last : event.key === 'ArrowDown' ? Math.min(index + 1, last) : Math.max(index - 1, 0)
    onSelect(rows[next].provider.id)
    rowRefs.current[next]?.focus()
  }

  const body = (
    <>
      <div className="mb-2 px-1">
        <p className="text-[10px] font-mono uppercase text-muted">Providers</p>
        <p className="mt-1 text-xs font-semibold text-fg">
          {connectedCount} connected <span className="text-muted">·</span> <span className="font-normal text-muted">{totalProviders} providers</span>
        </p>
      </div>
      <div className="relative mb-2">
        <Search className="pointer-events-none absolute left-2 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
        <input
          aria-label="Search providers"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search providers…"
          className="w-full rounded-lg border border-line bg-panel2 py-1.5 pl-7 pr-2 text-xs text-fg outline-hidden transition focus:border-brand"
        />
      </div>
      {rows.length === 0 && <p className="px-1 py-3 text-[11px] leading-4 text-muted">{`No provider matches "${query.trim()}".`}</p>}
      {visibleGroups.map((group) => {
        const groupBodyId = `${baseId}-${group.id}`
        return (
          <div key={group.id} className="mb-1">
            <button
              type="button"
              aria-expanded={!group.collapsed}
              aria-controls={groupBodyId}
              onClick={() => setCollapsed((current) => ({ ...current, [group.id]: !current[group.id] }))}
              className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-[10px] font-mono uppercase text-muted transition hover:text-fg"
            >
              <span className="truncate">{group.label}</span>
              <span className="flex shrink-0 items-center gap-1 normal-case">
                {group.providers.length}
                {group.collapsed ? <ChevronRight className="size-3" /> : <ChevronDown className="size-3" />}
              </span>
            </button>
            <div id={groupBodyId} className="space-y-0.5">
              {group.shown.map((provider) => {
                const list = providerConnections(connections, provider.id)
                const index = rows.findIndex((row) => row.provider.id === provider.id)
                const selected = provider.id === selectedId
                return (
                  <button
                    key={provider.id}
                    ref={(element) => { rowRefs.current[index] = element }}
                    type="button"
                    data-provider-row={provider.id}
                    aria-current={selected ? 'true' : undefined}
                    onClick={() => onSelect(provider.id)}
                    onKeyDown={(event) => moveFocus(event, index)}
                    className={`flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left transition ${selected ? 'bg-brand/10 text-brand ring-1 ring-brand/25' : 'text-fg hover:bg-panel2'}`}
                  >
                    <ProviderIcon providerId={provider.id} name={provider.name} className="size-5" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-xs font-semibold">{provider.name}</span>
                      <span className="mt-0.5 block truncate text-[10px] text-muted">{statusLine(list)}</span>
                    </span>
                    {showModelCount && (
                      <span className="shrink-0 pt-0.5 text-right text-[10px] font-mono text-muted" title={`${list.reduce((count, connection) => count + connection.models.length, 0)} models`}>
                        {list.reduce((count, connection) => count + connection.models.length, 0)} models
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
          </div>
        )
      })}
    </>
  )

  return (
    <div>
      <button
        type="button"
        aria-expanded={mobileOpen}
        aria-controls={navId}
        onClick={() => setMobileOpen((current) => !current)}
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-line bg-panel px-3 py-2 text-xs font-semibold text-fg lg:hidden"
      >
        <span className="min-w-0 truncate">{`Providers (${totalProviders}) · ${selectedName}`}</span>
        {mobileOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
      </button>
      {/* Measured at 1440x900: the settings chrome above the rail is 190 px and the
          pane keeps 32 px of bottom padding, so a taller cap pushed the whole
          settings pane into a 14 px scroll. 15rem leaves ~18 px of slack. */}
      <nav
        id={navId}
        aria-label={label}
        data-provider-rail
        className={`${mobileOpen ? 'mt-2 block' : 'hidden'} rounded-xl border border-line bg-panel p-2 lg:sticky lg:top-4 lg:mt-0 lg:block lg:max-h-[calc(100vh-15rem)] lg:overflow-y-auto`}
      >
        {body}
      </nav>
    </div>
  )
}
