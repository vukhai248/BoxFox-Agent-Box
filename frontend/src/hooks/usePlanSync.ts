import { useEffect } from 'react'
import { useAgentStore } from '../store/agentStore'
import { useHarnessChatStore } from '../store/harnessChatStore'
import { usePlanStore } from '../store/planStore'

export function usePlanSync() {
  const chatId = useAgentStore(s => s.activeSessionId)
  const run = useHarnessChatStore(s => s.sessions[chatId])
  const sid = run?.id ?? ''
  const events = run?.events
  const mode = run?.planMode
  const sync = usePlanStore(s => s.sync)
  useEffect(() => { sync(sid, { planMode: mode }, events ?? []) }, [sid, mode, events, sync])
}
