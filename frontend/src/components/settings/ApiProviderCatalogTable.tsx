import { useId, useMemo, useRef, useState } from 'react'
import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import type { ProviderConnection, ProviderDefinition } from '../../types/provider'
import { ProviderIcon } from '../providers/ProviderIcon'

function providerConnections(connections: ProviderConnection[], providerId: string) {
  return connections.filter((connection) => connection.providerId === providerId)
}

function providerStatusLine(providerConnectionList: ProviderConnection[]) {
  if (providerConnectionList.length === 0) return 'No connection · needs key'
  const readyCount = providerConnectionList.filter((connection) => connection.authState === 'ready').length
  if (readyCount > 0) return `${readyCount} connection ready`
  if (providerConnectionList.some((connection) => connection.authState === 'expired')) return 'auth expired'
  if (providerConnectionList.some((connection) => connection.discoveryState === 'failed')) return 'models failed'
  if (providerConnectionList.some((connection) => connection.inferenceState === 'failed')) return 'inference failed'
  return 'auth required'
}

export function ApiProviderCatalogTable({
  providers,
  connections,
  selectedId,
  onSelect,
  onToggleEnabled,
}: {
  providers: ProviderDefinition[]
  connections: ProviderConnection[]
  selectedId: string
  onSelect: (id: string) => void
  onToggleEnabled?: (providerId: string, enabled: boolean) => void
}) {
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const rowRefs = useRef<Array<HTMLButtonElement | null>>([])
  const baseId = useId()

  const normalized = query.trim().toLowerCase()
  const searching = normalized.length > 0

  const groups = useMemo(() => [
    { id: 'free', label: 'Free Tier', providers: providers.filter((p) => p.category === 'free') },
    { id: 'api-keys', label: 'API keys', providers: providers.filter((p) => p.category !== 'free') },
  ], [providers])

  const matches = (p: ProviderDefinition) => `${p.name} ${p.id}`.toLowerCase().includes(normalized)

  const visibleGroups = useMemo(() => {
    return groups
      .map((group) => {
        const matched = searching ? group.providers.filter(matches) : group.providers
        const isCollapsed = Boolean(collapsed[group.id]) && !searching
        const shown = isCollapsed ? [] : matched
        return { ...group, matched, shown, collapsed: isCollapsed }
      })
      .filter((group) => group.providers.length > 0 && (!searching || group.matched.length > 0))
  }, [groups, searching, collapsed, normalized])

  const rows = visibleGroups.flatMap((group) => group.shown.map((provider) => ({ group, provider })))

  const moveFocus = (event: React.KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const last = rows.length - 1
    if (last < 0) return
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
        ? last
        : event.key === 'ArrowDown'
        ? Math.min(index + 1, last)
        : Math.max(index - 1, 0)
    onSelect(rows[next].provider.id)
    rowRefs.current[next]?.focus()
  }

  const totalConnected = providers.filter(
    (p) => providerConnections(connections, p.id).length > 0,
  ).length

  return (
    <div className="flex h-full flex-col rounded-2xl border border-line bg-panel shadow-xs min-h-0">
      {/* Table header with Search & stats */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line/60 p-4">
        <div>
          <h3 className="text-sm font-bold text-fg">API Providers Catalog</h3>
          <p className="mt-0.5 text-xs text-muted">
            {totalConnected} connected · {providers.length} providers
          </p>
        </div>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
          <input
            aria-label="Search providers"
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search providers…"
            className="w-48 sm:w-64 rounded-lg border border-line bg-panel2 py-1.5 pl-8 pr-3 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand/20"
          />
        </div>
      </div>

      {rows.length === 0 && (
        <div className="p-8 text-center text-xs text-muted">
          No provider matches "{query.trim()}".
        </div>
      )}

      {/* Catalog Group Sections */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 min-h-0">
        {visibleGroups.map((group) => {
          const groupBodyId = `${baseId}-${group.id}`
          return (
            <div key={group.id} className="rounded-xl border border-line/70 bg-panel2/20 p-2.5">
              {/* Group Heading Button with aria-controls & count */}
              <button
                type="button"
                aria-expanded={!group.collapsed}
                aria-controls={groupBodyId}
                onClick={() => setCollapsed((curr) => ({ ...curr, [group.id]: !curr[group.id] }))}
                className="mb-2 flex w-full items-center justify-between rounded-lg px-2.5 py-1 text-xs font-bold uppercase tracking-wider text-muted transition hover:text-fg"
              >
                <span>
                  {group.label} ({group.providers.length})
                </span>
                <span className="flex items-center gap-1 text-[11px] normal-case text-muted">
                  {group.collapsed ? <ChevronRight className="size-3.5" /> : <ChevronDown className="size-3.5" />}
                </span>
              </button>

              <div id={groupBodyId} className="space-y-1">
                {group.shown.map((provider) => {
                  const list = providerConnections(connections, provider.id)
                  const index = rows.findIndex((row) => row.provider.id === provider.id)
                  const selected = provider.id === selectedId

                  return (
                    <div
                      key={provider.id}
                      className={`flex flex-wrap items-center justify-between gap-2 rounded-xl p-2.5 transition ${
                        selected
                          ? 'border border-brand/40 bg-brand/10 shadow-2xs'
                          : 'border border-line/60 bg-panel hover:border-line hover:bg-panel2/50'
                      }`}
                    >
                      {/* Selectable Row Button */}
                      <button
                        ref={(element) => {
                          rowRefs.current[index] = element
                        }}
                        type="button"
                        data-provider-row={provider.id}
                        aria-current={selected ? 'true' : undefined}
                        onClick={() => onSelect(provider.id)}
                        onKeyDown={(event) => moveFocus(event, index)}
                        className="flex flex-1 items-center gap-3 text-left min-w-0"
                      >
                        <div className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-line/60 bg-panel2 p-1 shadow-2xs">
                          <ProviderIcon providerId={provider.id} name={provider.name} className="size-5" />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="truncate text-xs font-semibold text-fg">
                              {provider.name}
                            </span>
                            <span className="font-mono text-[10px] text-muted">({provider.id})</span>
                          </div>
                          <span className="mt-0.5 block truncate text-[11px] text-muted">
                            {providerStatusLine(list)}
                          </span>
                        </div>
                      </button>

                      {/* On/Off Toggle Switch */}
                      <div className="flex shrink-0 items-center pl-2">
                        {list.length > 0 ? (
                          <button
                            type="button"
                            role="switch"
                            aria-checked={list.some((c) => c.enabled)}
                            onClick={(e) => {
                              e.stopPropagation()
                              const isCurrentlyEnabled = list.some((c) => c.enabled)
                              onToggleEnabled?.(provider.id, !isCurrentlyEnabled)
                            }}
                            title={list.some((c) => c.enabled) ? `Disable ${provider.name}` : `Enable ${provider.name}`}
                            aria-label={list.some((c) => c.enabled) ? `Disable ${provider.name}` : `Enable ${provider.name}`}
                            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-hidden focus:ring-2 focus:ring-blue-500 focus:ring-offset-1 ${
                              list.some((c) => c.enabled) ? 'bg-blue-600' : 'bg-zinc-300 dark:bg-zinc-600'
                            }`}
                          >
                            <span
                              className={`pointer-events-none inline-block size-4 transform rounded-full bg-white shadow-md ring-0 transition duration-200 ease-in-out ${
                                list.some((c) => c.enabled) ? 'translate-x-4' : 'translate-x-0'
                              }`}
                            />
                          </button>
                        ) : (
                          <div
                            title="No connection configured"
                            className="relative inline-flex h-5 w-9 shrink-0 opacity-25 cursor-not-allowed rounded-full border-2 border-transparent bg-zinc-300 dark:bg-zinc-700"
                          >
                            <span className="pointer-events-none inline-block size-4 rounded-full bg-white shadow-xs" />
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )
        })}
      </div>

      {/* Footer info */}
      <div className="border-t border-line/60 bg-panel2/20 px-4 py-2.5 text-[11px] text-muted flex items-center justify-between">
        <span>Showing all {providers.length} available providers</span>
        <span>Select a provider to manage keys</span>
      </div>
    </div>
  )
}
