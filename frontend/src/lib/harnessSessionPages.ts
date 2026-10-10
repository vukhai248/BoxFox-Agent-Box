import { agentApi } from './agentApi'
import type { HarnessEvent } from '../store/harnessChatStore'

export interface HarnessSessionPage {
  events: HarnessEvent[]
  hasMore?: boolean
  nextAfter?: number
}

/** Read the complete event tail before presenting a completed session as hydrated. */
export async function readHarnessSessionPages<T extends HarnessSessionPage>(
  sessionId: string, after = 0, signal?: AbortSignal,
): Promise<T> {
  const events: HarnessEvent[] = []
  const seen = new Set<string>()
  let cursor = after
  for (;;) {
    signal?.throwIfAborted()
    const page = await agentApi<T>(`/sessions/${encodeURIComponent(sessionId)}?after=${cursor}`, undefined, undefined, signal)
    if (!Array.isArray(page.events)) throw new Error('SESSION_EVENTS_INVALID: missing event page')
    for (const event of page.events) {
      const identity = `${event.seq}:${event.type}`
      if (event.seq <= after || seen.has(identity)) continue
      seen.add(identity)
      events.push(event)
    }
    if (page.hasMore !== true) return { ...page, events }
    const next = page.nextAfter
    if (typeof next !== 'number' || !Number.isFinite(next) || next <= cursor
      || next !== page.events.at(-1)?.seq) {
      throw new Error('SESSION_EVENTS_CURSOR_INVALID: event pagination did not advance')
    }
    cursor = next
  }
}
