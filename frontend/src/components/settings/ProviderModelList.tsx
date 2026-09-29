// The model list of one provider: one row per model, however many connections serve it.
//
// Before round 29 every connection drew its own list, so two keys of the same provider
// showed the same model twice. Rows are now grouped by `model.id`; the first connection in
// the caller's order keeps the row (that order is `connectionOrder`, so the highest ranked
// account is the one a plain Test probes), and the row says how many connections serve it.
// A toggle therefore has to speak for every serving connection, sequentially, and a partial
// failure is printed instead of being swallowed.
//
// `ModelToggleList` (one connection per list) lives here too: the Router tab's legacy
// inventory still renders per connection and both variants share the same row body.
import { useEffect, useId, useRef, useState } from 'react'
import { Activity, ChevronDown, ChevronRight, Copy, Plus, RefreshCw, SlidersHorizontal, X } from 'lucide-react'
import { run, useProviderStore, type ModelProbeResult } from '../../store/providerStore'
import type { ProviderConnection, ProviderModel } from '../../types/provider'
import { CustomModelForm } from './CustomModelForm'
import { ModelManagerModal } from './ModelManagerModal'
import { InferenceTest } from '../providers/InferenceTest'

export interface ProviderModelRow {
  /** The row's model, taken from the first serving connection — every serving connection
   *  offers the same `model.id`, which is also the row's key. */
  model: ProviderModel
  /** Connections that offer this model, in the order the caller ranked them. */
  serving: ProviderConnection[]
}

/** One row per `model.id`, keeping the first connection that offers it. */
export function dedupeByModel(connections: ProviderConnection[]): ProviderModelRow[] {
  const rows = new Map<string, ProviderModelRow>()
  for (const connection of connections) {
    for (const model of connection.models) {
      const existing = rows.get(model.id)
      if (existing) { existing.serving.push(connection); continue }
      rows.set(model.id, { model, serving: [connection] })
    }
  }
  return [...rows.values()]
}

function modelLatencyTone(model: ProviderModel) {
  if (model.health === 'ready') return 'text-emerald-400'
  if (['unavailable', 'failed'].includes(model.health ?? '')) return 'text-rose-400'
  if (model.health === 'rate_limited' || model.health === 'slow') return 'text-amber-400'
  return 'text-muted'
}

/** The compact row prints only the number, so the title carries the status word and
 *  the reason: a failed probe must never be signalled by colour alone. */
function latencyTitle(model: ProviderModel) {
  if (!model.lastProbe) return 'Not tested yet — Test probes this model once'
  const status = model.lastProbe.status === 'passed' ? 'Passed' : 'Failed'
  const health = model.health && model.health !== 'unknown' ? ` · ${model.health}` : ''
  const http = Number.isFinite(model.lastProbe.httpStatus) ? ` · HTTP ${model.lastProbe.httpStatus}` : ''
  const reason = model.lastProbe.error ? ` · ${model.lastProbe.error}` : ''
  return `${status}${health}${http} · ${model.lastProbe.latencyMs} ms${reason}`
}

/** One list of model rows. `connections` is the anchor for actions that belong to a single
 *  connection (add a model by hand, open the manager); `rows` decides what is drawn. */
function ModelListBody({ rows, connections, providerScoped = false }: { rows: ProviderModelRow[]; connections: ProviderConnection[]; providerScoped?: boolean }) {
  const request = useProviderStore((state) => state.request)
  const probeModel = useProviderStore((state) => state.probeModel)
  const busy = useProviderStore((state) => state.busy)
  const [showManagerModal, setShowManagerModal] = useState(false)
  const [selectedModelForModal, setSelectedModelForModal] = useState<string | undefined>(undefined)
  const [managerConnection, setManagerConnection] = useState<ProviderConnection | undefined>(undefined)
  const [addModelOpen, setAddModelOpen] = useState(false)
  const [inferenceOpen, setInferenceOpen] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [probing, setProbing] = useState<string[]>([])
  const [probeResults, setProbeResults] = useState<Record<string, ModelProbeResult>>({})
  const [partialFailure, setPartialFailure] = useState<{ modelId: string; message: string } | null>(null)
  const addModelId = useId()
  const inferenceId = useId()
  const controllers = useRef<Set<AbortController>>(new Set())
  const checkboxes = useRef<Map<string, HTMLInputElement | null>>(new Map())

  const refreshAll = async () => {
    setRefreshing(true)
    try {
      await Promise.all(
        connections.map((c) =>
          request(`/api/router/connections/${encodeURIComponent(c.id)}/test`, 'POST').catch(() => undefined),
        ),
      )
    } finally {
      setRefreshing(false)
    }
  }

  // A probe can outlive the card (the state reload can unmount it), so every probe
  // owns an AbortController that is aborted when this list goes away.
  useEffect(() => () => { controllers.current.forEach((controller) => controller.abort()); controllers.current.clear() }, [])

  const isEnabledOn = (row: ProviderModelRow, connection: ProviderConnection) => connection.models.some((model) => model.id === row.model.id && model.enabled)
  const enabledCount = rows.filter((row) => row.serving.every((connection) => isEnabledOn(row, connection))).length
  const verified = rows.filter((row) => row.model.health === 'ready')
  // Prices are per model, so the block says how many of them carry one before the
  // user opens Manage models — a blank cost column is otherwise a surprise.
  const priced = rows.filter((row) => row.model.pricing != null).length

  // A checkbox that a partial toggle left half-on must say so: `indeterminate` is a DOM
  // property with no React prop, so it is written after every render.
  useEffect(() => {
    for (const row of rows) {
      const input = checkboxes.current.get(row.model.id)
      if (!input) continue
      const enabled = row.serving.filter((connection) => isEnabledOn(row, connection)).length
      input.indeterminate = enabled > 0 && enabled < row.serving.length
    }
  })

  /** Toggle one row on every serving connection, one PATCH at a time. Sequential on
   *  purpose: the URL and the body stay readable in the network log, and a failure stops
   *  nothing — the row reports how many connections took the change. */
  const patchRow = async (row: ProviderModelRow, enabled: boolean) => {
    let done = 0
    for (const connection of row.serving) {
      const current = connection.models.filter((model) => model.enabled).map((model) => model.id)
      const next = enabled ? [...new Set([...current, row.model.id])] : current.filter((id) => id !== row.model.id)
      try {
        await request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { enabledModelIds: next })
        done += 1
      } catch { /* the page banner already carries the router's own message */ }
    }
    setPartialFailure(done === row.serving.length ? null : { modelId: row.model.id, message: `${enabled ? 'Enabled' : 'Disabled'} in ${done} of ${row.serving.length} connections.` })
  }
  const toggle = (row: ProviderModelRow) => patchRow(row, !row.serving.every((connection) => isEnabledOn(row, connection)))
  const disable = (row: ProviderModelRow) => patchRow(row, false)
  const disableAll = async () => {
    let done = 0
    for (const connection of connections) {
      try {
        await request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', { enabledModelIds: [] })
        done += 1
      } catch { /* the page banner already carries the router's own message */ }
    }
    setPartialFailure(done === connections.length ? null : { modelId: '', message: `Disabled in ${done} of ${connections.length} connections.` })
  }
  const copyModel = (modelId: string) => navigator.clipboard?.writeText(modelId) ?? Promise.resolve()
  const testModel = async (row: ProviderModelRow) => {
    const controller = new AbortController()
    controllers.current.add(controller)
    setProbing((current) => (current.includes(row.model.id) ? current : [...current, row.model.id]))
    try {
      // The highest ranked connection is the one the router would use for this model.
      const result = await probeModel(row.serving[0].id, row.model.id, controller.signal)
      setProbeResults((current) => ({ ...current, [row.model.id]: result }))
    } finally {
      controllers.current.delete(controller)
      setProbing((current) => current.filter((id) => id !== row.model.id))
    }
  }
  // A hand-added model and the manager belong to one connection: the first one serving it.
  const openManager = (connection: ProviderConnection | undefined, modelId?: string) => {
    setManagerConnection(connection)
    setSelectedModelForModal(modelId)
    setShowManagerModal(true)
  }

  const capabilityChips = (model: ProviderModel) => {
    const vision = model.capabilities.vision
    const reasoning = model.capabilities.reasoning
    const isFree = model.id.includes(':free') || model.id === 'openrouter/free'
    return (
      <>
        {isFree && <span className="shrink-0 rounded border border-emerald-500/20 bg-emerald-500/10 px-1 font-mono text-[9px] text-emerald-400">free</span>}
        {model.source === 'custom' && <span className="shrink-0 rounded border border-brand/20 bg-brand/10 px-1 font-mono text-[9px] text-brand">custom</span>}
        <span className={`shrink-0 rounded border px-1 font-mono text-[9px] ${vision === 'verified' ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-400' : 'border-line bg-panel text-muted'}`}>
          {vision === 'verified' ? 'vision' : `vision ${vision}`}
        </span>
        {(reasoning === 'verified' || reasoning === 'reported') && <span className="hidden shrink-0 rounded border border-brand/20 bg-brand/10 px-1 font-mono text-[9px] text-brand lg:inline">reasoning</span>}
      </>
    )
  }

  return (
    <div className="mt-2 rounded-lg border border-line/60 bg-panel2/30 p-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <p className="text-[10px] font-mono uppercase text-muted">Models</p>
          <span className="rounded-full border border-line bg-panel px-2 py-0.5 font-mono text-[10px] text-muted">{enabledCount} / {rows.length} active</span>
          {verified.length > 0 && <span className="hidden items-center gap-1 font-mono text-[10px] text-emerald-400 sm:flex"><span className="size-1.5 rounded-full bg-emerald-400" />{verified.length} verified ready</span>}<span className="hidden items-center gap-1 font-mono text-[10px] text-muted sm:flex" title="Models that carry a price — reported by the provider, published in its model list, or set by you. Manage models sets the rest.">Prices {priced} / {rows.length} models</span>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <button
            type="button"
            disabled={busy || refreshing || !connections.some((c) => c.credentialPresent)}
            onClick={() => void refreshAll()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel px-2 py-1 text-[11px] font-medium text-fg transition hover:bg-panel2 disabled:opacity-50"
          >
            <RefreshCw className={`size-3 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh models
          </button>
          {enabledCount > 0 && <button type="button" disabled={busy} onClick={() => void disableAll()} className="rounded px-2 py-1 text-[11px] text-muted transition hover:text-rose-400 disabled:opacity-50">Disable all</button>}
          <button type="button" aria-expanded={addModelOpen} aria-controls={addModelId} onClick={() => setAddModelOpen((current) => !current)} className="inline-flex items-center gap-1 rounded-lg border border-line bg-panel px-2 py-1 text-[11px] font-medium text-fg transition hover:bg-panel2"><Plus className="size-3" />Add model</button>
          <button type="button" onClick={() => openManager(connections[0])} className="inline-flex items-center gap-1.5 rounded-lg border border-brand/40 bg-brand/15 px-2.5 py-1 text-[11px] font-semibold text-brand transition hover:bg-brand/25"><SlidersHorizontal className="size-3.5" />Manage models</button>
        </div>
      </div>
      {providerScoped && <p className="mt-1 text-[10px] leading-4 text-muted">One row per model · served by {connections.length} connection{connections.length === 1 ? '' : 's'}.</p>}

      {addModelOpen && (
        <div id={addModelId} className="mt-2 rounded-lg border border-dashed border-line/70 bg-panel2/40 p-2.5">
          {/* The same form the model manager uses, with its own declare-then-probe Test. */}
          {connections[0] && <CustomModelForm connection={connections[0]} onCancel={() => setAddModelOpen(false)} />}
        </div>
      )}

      <p role="status" className="sr-only">{probing.length > 0 ? `Testing ${probing.join(', ')}…` : ''}</p>

      {rows.length === 0 ? (
        <p className="px-1 py-3 text-[11px] text-muted">No models discovered yet. Refresh models or add a model by hand.</p>
      ) : (
        <div className="mt-2 max-h-72 divide-y divide-line/10 overflow-y-auto pr-1">
          {rows.map((row) => {
            const result = probeResults[row.model.id]
            const isProbing = probing.includes(row.model.id)
            const checked = row.serving.every((connection) => isEnabledOn(row, connection))
            return (
              <div key={row.model.id}>
                <div className="flex min-h-[28px] flex-wrap items-center gap-2 py-0.5 text-[11px]">
                  <input type="checkbox" ref={(input) => { checkboxes.current.set(row.model.id, input) }} disabled={busy} checked={checked} onChange={() => void toggle(row)} aria-label={`Enable ${row.model.id}`} className="size-3 shrink-0 accent-blue-500" />
                  <span className="min-w-0 max-w-[16rem] truncate font-medium text-fg" title={row.model.name}>{row.model.name}</span>
                  <span className="hidden min-w-0 max-w-[14rem] truncate font-mono text-[10px] text-muted md:inline" title={row.model.id}>{row.model.id}</span>
                  {row.serving.length > 1 && <span className="shrink-0 rounded border border-line bg-panel px-1 font-mono text-[9px] text-muted" title={row.serving.map((connection) => connection.name).join(', ')}>{row.serving.length} connections</span>}
                  {capabilityChips(row.model)}
                  {row.model.thinkingLevels && row.model.thinkingLevels.length > 0 && <span className="hidden shrink-0 font-mono text-[9px] text-muted xl:inline">{row.model.thinkingLevels.join(' · ')}</span>}
                  <span className={`ml-auto shrink-0 font-mono text-[10px] ${modelLatencyTone(row.model)}`} title={latencyTitle(row.model)}>{isProbing ? 'Testing…' : row.model.lastProbe ? `${row.model.lastProbe.latencyMs} ms` : 'Untested'}</span>
                  <button type="button" aria-busy={isProbing} disabled={busy || isProbing} onClick={() => void testModel(row)} className="shrink-0 rounded border border-line bg-panel px-1.5 py-0.5 text-[10px] font-medium text-fg transition hover:bg-panel2 hover:text-brand disabled:opacity-50">{isProbing ? 'Testing…' : 'Test'}</button>
                  <button type="button" aria-label={`Copy ${row.model.id}`} title="Copy model ID" onClick={() => run(copyModel(row.model.id))} className="shrink-0 rounded p-1 text-muted transition hover:bg-panel2 hover:text-fg"><Copy className="size-3" /></button>
                  <button type="button" aria-label={`Manage ${row.model.id}`} title="Manage this model" onClick={() => openManager(row.serving[0], row.model.id)} className="shrink-0 rounded p-1 text-muted transition hover:bg-panel2 hover:text-fg"><SlidersHorizontal className="size-3.5" /></button>
                  <button type="button" title="Remove from active models" onClick={() => void disable(row)} className="shrink-0 rounded p-1 text-muted transition hover:bg-panel2 hover:text-rose-400"><X className="size-3" /></button>
                </div>
                {result && (
                  <p className={`pb-1 pl-5 font-mono text-[10px] ${result.status === 'passed' ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {result.status === 'passed' ? `Answered BOXFOX_OK · ${result.latencyMs} ms` : `HTTP ${result.httpStatus} · ${result.code} · ${result.message}`}
                    {row.serving.length > 1 && ` · Tested via ${row.serving[0].name}`}
                  </p>
                )}
                {partialFailure?.modelId === row.model.id && <p className="pb-1 pl-5 text-[10px] text-rose-400">{partialFailure.message}</p>}
              </div>
            )
          })}
        </div>
      )}
      {partialFailure && partialFailure.modelId === '' && <p className="px-1 pt-1 text-[10px] text-rose-400">{partialFailure.message}</p>}

      {/* Inference verification: under the ping table */}
      {connections.some((c) => c.credentialPresent && c.authState === 'ready') && (
        <div className="mt-3 border-t border-line/60 pt-2">
          <button
            type="button"
            aria-expanded={inferenceOpen}
            aria-controls={inferenceId}
            onClick={() => setInferenceOpen((current) => !current)}
            className="flex w-full items-center justify-between gap-2 rounded-md px-1 py-1 text-left text-[11px] font-semibold text-muted transition hover:text-fg"
          >
            <div className="flex items-center gap-2">
              <Activity className="size-3.5 text-brand" />
              <span>Test inference</span>
            </div>
            <span className="flex items-center gap-1.5 font-mono text-[10px] font-normal normal-case">
              {connections[0]?.inferenceState}
              {inferenceOpen ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}
            </span>
          </button>
          {inferenceOpen && connections[0] && (
            <div id={inferenceId} className="mt-1">
              <InferenceTest key={connections[0].revision} connection={connections[0]} />
            </div>
          )}
        </div>
      )}

      {showManagerModal && managerConnection && (
        <ModelManagerModal
          connection={managerConnection}
          initialSelectedModelId={selectedModelForModal}
          onClose={() => setShowManagerModal(false)}
        />
      )}
    </div>
  )
}

/** One row per model across every ready connection of a provider. */
export function ProviderModelList({ connections }: { connections: ProviderConnection[] }) {
  if (connections.length === 0) return null
  return <ModelListBody rows={dedupeByModel(connections)} connections={connections} providerScoped />
}

/** The per-connection list the Router tab's legacy inventory still renders. */
export function ModelToggleList({ connection }: { connection: ProviderConnection }) {
  return <ModelListBody rows={dedupeByModel([connection])} connections={[connection]} />
}
