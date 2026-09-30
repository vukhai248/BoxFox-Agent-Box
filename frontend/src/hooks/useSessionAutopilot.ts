import { useMemo, useCallback } from 'react'
import { useAgentStore } from '../store/agentStore'
import { useHarnessChatStore } from '../store/harnessChatStore'
import { useAutopilotStore } from '../store/autopilotStore'
import { autopilotFrom } from '../lib/workGraph'

export interface UseSessionAutopilotOptions {
  fallback?: boolean
}

export function useSessionAutopilot(options?: UseSessionAutopilotOptions) {
  const chatId = useAgentStore((s) => s.activeSessionId)
  const session = useHarnessChatStore((s) => s.sessions[chatId])
  const sessionId = session?.id ?? (chatId || '')
  const events = useMemo(() => session?.events ?? [], [session?.events])

  const overrides = useAutopilotStore((s) => s.overrides)
  const busy = useAutopilotStore((s) => s.busy)
  const error = useAutopilotStore((s) => s.error)
  const toggle = useAutopilotStore((s) => s.toggleAutopilot)

  // Real backend autopilot fallback from session config or options.fallback
  const fallback = options?.fallback ?? session?.autopilot ?? false
  const eventAutopilot = useMemo(() => autopilotFrom(events, fallback), [events, fallback])

  // Optimistic override wins if present
  const hasOverride = sessionId ? typeof overrides[sessionId] === 'boolean' : false
  const autopilot = hasOverride ? overrides[sessionId] : eventAutopilot

  const toggleAutopilot = useCallback(async () => {
    if (!sessionId) return false
    return await toggle(sessionId, autopilot)
  }, [sessionId, autopilot, toggle])

  return {
    chatId,
    sessionId,
    autopilot,
    busy,
    error,
    toggleAutopilot,
  }
}
