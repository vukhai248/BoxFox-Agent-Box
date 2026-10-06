import { create } from 'zustand'
import { api, ProviderApiError } from '../lib/providerApi'
import {
  searchActivePath,
  searchProviderPath,
  searchProviderRevealPath,
  searchProviderTestPath,
} from '../lib/searchProviderPaths'
import type { ProviderSnapshot, SearchProviderId, SearchTestResult } from '../types/provider'

export type ModelProbeResult =
  | { status: 'passed'; latencyMs: number }
  | { status: 'failed'; httpStatus: number; code: string; message: string }

interface ProviderStore {
  snapshot: ProviderSnapshot | null
  loading: boolean
  busy: boolean
  error: string | null
  load: () => Promise<void>
  request: (path: string, method?: string, body?: unknown) => Promise<unknown>
  probeModel: (connectionId: string, modelId: string, signal?: AbortSignal) => Promise<ModelProbeResult>
  deleteSearchProvider: (providerId: SearchProviderId) => Promise<unknown>
  setActiveSearchProvider: (providerId: SearchProviderId | null) => Promise<unknown>
  revealSearchProvider: (providerId: SearchProviderId) => Promise<string>
  testSearchProvider: (providerId: SearchProviderId, signal?: AbortSignal) => Promise<SearchTestResult>
}

function errorMessage(error: unknown) {
  if (error instanceof ProviderApiError || error instanceof Error) return error.message
  return 'Router request failed.'
}

/** The one place a background action reports a refusal: the message goes to this store's
 *  `error`, which the Settings page draws in its banner — callers do not repeat it. */
export function run(action: Promise<unknown>) {
  void action.catch((error) => useProviderStore.setState({ error: errorMessage(error) }))
}

let loadRevision = 0
let pendingRequests = 0

export const useProviderStore = create<ProviderStore>((set, get) => ({
  snapshot: null,
  loading: false,
  busy: false,
  error: null,
  load: async () => {
    const revision = ++loadRevision
    set({ loading: true, error: null })
    try {
      const snapshot = await api<ProviderSnapshot>('/api/router/state')
      if (revision === loadRevision) set({ snapshot, loading: false })
    } catch (error) {
      if (revision === loadRevision) set({ snapshot: null, loading: false, error: errorMessage(error) })
      throw error
    }
  },
  request: async (path, method = 'POST', body) => {
    pendingRequests++
    set({ busy: true, error: null })
    try {
      const result = await api(path, { method, body })
      // A successful mutation must not lose a one-time key if state refresh fails.
      await get().load().catch(() => undefined)
      return result
    } catch (error) {
      // Mutations such as a model probe can persist useful state even when the
      // probe itself fails (for example rate_limited/unavailable). Reload that
      // state so the card reports the durable result rather than “Not tested”.
      await get().load().catch(() => undefined)
      set({ error: errorMessage(error) })
      throw error
    } finally {
      pendingRequests--
      set({ busy: pendingRequests > 0 })
    }
  },
  /**
   * Probe one model. Deliberately does NOT go through `request()`: one upstream
   * ping can take up to 90 s, and `request()` would hold the global `busy` flag
   * (freezing every button on the screen) and paint the global error banner for a
   * failure that the model row already reports next to the button that caused it.
   * The result is returned to the caller; the router persists health/lastProbe
   * even on failure, so the state reload in `finally` is what makes it durable.
   */
  probeModel: async (connectionId, modelId, signal) => {
    const started = performance.now()
    try {
      await api(`/api/router/connections/${encodeURIComponent(connectionId)}/models/${encodeURIComponent(modelId)}/test`, { method: 'POST', signal })
      return { status: 'passed', latencyMs: Math.round(performance.now() - started) }
    } catch (error) {
      if (error instanceof ProviderApiError) return { status: 'failed', httpStatus: error.status, code: error.code, message: error.message }
      return { status: 'failed', httpStatus: 0, code: 'REQUEST_FAILED', message: errorMessage(error) }
    } finally {
      await get().load().catch(() => undefined)
    }
  },
  /**
   * Search-provider writes. Both go through `request()`: they are quick, the caller
   * wants the global banner for a refusal, and `request()` reloads the snapshot so the
   * panel never shows a state the router has already left.
   */
  deleteSearchProvider: (providerId) => get().request(searchProviderPath(providerId), 'DELETE'),
  setActiveSearchProvider: (providerId) => get().request(searchActivePath(), 'PUT', { providerId }),
  /**
   * The raw key exists for exactly as long as the caller keeps it: this action returns it
   * and never stores it, so the secret cannot leak through a snapshot, a re-render or a
   * second panel.
   */
  revealSearchProvider: async (providerId) => {
    const result = await api<{ id: string; key: string }>(searchProviderRevealPath(providerId), { method: 'POST' })
    return typeof result?.key === 'string' ? result.key : ''
  },
  /**
   * Test one search provider. Deliberately does NOT go through `request()`: an upstream
   * test can take up to 15 s, and `request()` would hold the global `busy` flag (freezing
   * every button on the panel) and paint the global error banner for a verdict that the
   * provider row already shows. The verdict is returned to the caller; the router records
   * `lastTest`/`lastTestedAt` even on failure, so the reload in `finally` makes it durable.
   */
  testSearchProvider: async (providerId, signal) => {
    try {
      const result = await api<SearchTestResult>(searchProviderTestPath(providerId), { method: 'POST', signal })
      return {
        ok: Boolean(result?.ok),
        providerId: result?.providerId ?? providerId,
        status: result?.status ?? null,
        latencyMs: result?.latencyMs ?? null,
        code: result?.code ?? null,
        message: result?.message ?? null,
        sample: result?.sample ?? null,
      }
    } catch (error) {
      if (error instanceof ProviderApiError) {
        return { ok: false, providerId, status: error.status, latencyMs: null, code: error.code, message: error.message, sample: null }
      }
      return { ok: false, providerId, status: null, latencyMs: null, code: 'REQUEST_FAILED', message: errorMessage(error), sample: null }
    } finally {
      await get().load().catch(() => undefined)
    }
  },
}))
