import { useEffect, useRef, useState, type FormEvent } from 'react'
import { LoaderCircle, Play, X } from 'lucide-react'
import { useProviderStore, type ModelProbeResult } from '../../store/providerStore'
import type { ProviderConnection } from '../../types/provider'

/** A probe result plus the latency the form measured; the store only reports latency on success. */
type TestOutcome =
  | { status: 'passed'; latencyMs: number }
  | { status: 'failed'; httpStatus: number; code: string; message: string; latencyMs: number }

const field = 'w-full rounded border border-line bg-panel px-2.5 py-1 text-xs text-fg outline-hidden focus:border-brand focus:ring-1 focus:ring-brand/40'
const smallButton = 'inline-flex shrink-0 items-center gap-1.5 rounded border border-line bg-panel px-2.5 py-1 text-[11px] font-medium text-fg transition hover:border-brand/60 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50'

/** A code from the router's error envelope earns one honest sentence beside the raw message. */
function codeHint(code: string) {
  if (code === 'AUTH') return 'The key was rejected upstream. Replace it in Edit, then test again.'
  if (code === 'MODEL_NOT_FOUND') return 'The gateway does not know this model id — check the spelling.'
  return null
}

/**
 * The one place a hand-typed model id is declared, used by the model manager modal
 * and by the `Add model` disclosure on the API connection card. The router stores,
 * sends and displays the id exactly as typed, so the form never rewrites it — it
 * declares it (`customModel`) and then proves it (`POST …/models/{id}/test`).
 *
 * The probe goes through the store's `probeModel` action: it returns its result
 * instead of throwing and never touches the global `busy`/`error` state, so one
 * slow upstream ping (up to 90 s) cannot freeze the rest of the form.
 */
export function CustomModelForm({
  connection,
  onDeclared,
  onCancel,
}: {
  connection: ProviderConnection
  onDeclared?: (modelId: string) => void
  onCancel?: () => void
}) {
  const request = useProviderStore((state) => state.request)
  const probeModel = useProviderStore((state) => state.probeModel)
  const [modelId, setModelId] = useState('')
  const [name, setName] = useState('')
  const [vision, setVision] = useState(false)
  const [reasoning, setReasoning] = useState(false)
  const [running, setRunning] = useState(false)
  const [testedId, setTestedId] = useState('')
  const [result, setResult] = useState<TestOutcome | null>(null)
  const [declareError, setDeclareError] = useState<string | null>(null)
  const controllers = useRef<Set<AbortController>>(new Set())

  // A 90 s probe can outlive the form (the state reload can close the modal), so
  // every probe owns an AbortController that is aborted when the form goes away.
  useEffect(() => () => { controllers.current.forEach((controller) => controller.abort()); controllers.current.clear() }, [])

  const declaredId = modelId.trim()

  /** Step one: declare the id. The router keeps it verbatim and enables the row. */
  const declare = (id: string) => request(`/api/router/connections/${encodeURIComponent(connection.id)}`, 'PATCH', {
    customModel: { id, name: name.trim() || id, capabilities: { vision, reasoning } },
  })

  const test = async (id: string, reset: boolean) => {
    if (!id || running) return
    setRunning(true); setResult(null); setDeclareError(null); setTestedId(id)
    const controller = new AbortController()
    controllers.current.add(controller)
    try {
      await declare(id)
      onDeclared?.(id)
      // The declaration is the durable half: a failed probe never loses the name.
      if (reset) { setModelId(''); setName(''); setVision(false); setReasoning(false) }
      const started = performance.now()
      const outcome: ModelProbeResult = await probeModel(connection.id, id, controller.signal)
      const latencyMs = outcome.status === 'passed' ? outcome.latencyMs : Math.round(performance.now() - started)
      setResult({ ...outcome, latencyMs } as TestOutcome)
    } catch (error) {
      setDeclareError(error instanceof Error ? error.message : 'Router request failed.')
    } finally {
      controllers.current.delete(controller)
      setRunning(false)
    }
  }

  const submit = (event: FormEvent) => { event.preventDefault(); void test(declaredId, true) }

  const httpStatus = result ? (result.status === 'passed' ? 200 : result.httpStatus) : null
  const latencyMs = result?.latencyMs ?? null
  return (
    <form onSubmit={submit} className="space-y-2.5 text-xs">
      <div className="flex items-center justify-between">
        <span className="font-semibold text-fg">Add Custom Model Identifier</span>
        {onCancel && (
          <button type="button" aria-label="Close the custom model form" onClick={onCancel} className="text-muted transition hover:text-fg">
            <X className="size-3.5" />
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="text-[11px] font-semibold uppercase text-muted">Model ID / Slug</label>
          <div className="mt-1 flex items-center gap-1.5">
            <input
              type="text"
              required
              placeholder="e.g. meta-llama/llama-3.3-70b-instruct"
              value={modelId}
              onChange={(event) => setModelId(event.target.value)}
              className={`${field} font-mono`}
            />
            <button
              type="button"
              aria-busy={running}
              disabled={running || !connection.credentialPresent || !declaredId}
              onClick={() => void test(declaredId, false)}
              className={smallButton}
            >
              {running ? <LoaderCircle className="size-3.5 animate-spin" /> : <Play className="size-3" />}
              {running ? 'Testing…' : 'Test'}
            </button>
          </div>
          {!connection.credentialPresent && (
            <p className="mt-1 text-[11px] leading-4 text-amber-700 dark:text-amber-300">Save an API key on this connection first, then test a model id.</p>
          )}
        </div>
        <div>
          <label className="text-[11px] font-semibold uppercase text-muted">Display Name</label>
          <input
            type="text"
            placeholder="e.g. Llama 3.3 70B"
            value={name}
            onChange={(event) => setName(event.target.value)}
            className={`${field} mt-1`}
          />
        </div>
      </div>

      <div className="flex items-center justify-between pt-1">
        <div className="flex items-center gap-3 text-[11px] text-muted">
          <label className="flex cursor-pointer items-center gap-1.5">
            <input type="checkbox" checked={vision} onChange={(event) => setVision(event.target.checked)} className="rounded" />
            Vision
          </label>
          <label className="flex cursor-pointer items-center gap-1.5">
            <input type="checkbox" checked={reasoning} onChange={(event) => setReasoning(event.target.checked)} className="rounded" />
            Reasoning
          </label>
        </div>

        <button
          type="submit"
          disabled={running || !declaredId}
          className="cursor-pointer rounded bg-brand px-3 py-1 text-[11px] font-semibold text-brandfg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Add &amp; Test
        </button>
      </div>

      {declareError && (
        <p role="alert" className="rounded border border-red-500/30 bg-red-500/10 px-2.5 py-1.5 font-mono text-[11px] leading-4 text-red-600 dark:text-red-300">{declareError}</p>
      )}

      {running && (
        <p role="status" className="font-mono text-[11px] text-muted">Pinging {connection.name} / {testedId}…</p>
      )}

      {result && (
        <div role="status" aria-live="polite" className="space-y-1.5 rounded border border-line bg-panel2/60 px-2.5 py-2">
          <div className="flex flex-wrap items-center gap-2 font-mono text-[11px]">
            <span className={`font-semibold ${result.status === 'passed' ? 'text-emerald-400' : 'text-rose-400'}`}>
              {result.status === 'passed' ? `Passed · ${latencyMs} ms` : `Failed · HTTP ${httpStatus}`}
            </span>
            <span className="text-muted">HTTP {httpStatus}</span>
            <span className="text-muted">Latency {latencyMs} ms</span>
            <span className="text-muted">Answered {result.status === 'passed' ? 'BOXFOX_OK' : 'no'}</span>
          </div>
          <p className="font-mono text-[11px] text-muted">Target: {connection.name} / {testedId}</p>
          {result.status === 'failed' && (
            <>
              <p className="font-mono text-[11px] leading-4 text-rose-600 dark:text-rose-300">{result.message}</p>
              {codeHint(result.code) && <p className="text-[11px] leading-4 text-muted">{codeHint(result.code)}</p>}
            </>
          )}
        </div>
      )}

      <p className="text-[11px] leading-4 text-muted">The name is kept as typed. You can add it anyway — it stays <span className="font-semibold text-fg">Untested</span> until a test passes.</p>
    </form>
  )
}
