import { create } from 'zustand'
import { setAutopilot as setAutopilotApi } from '../lib/workGraph'
import { useAgentStore } from './agentStore'
import { useHarnessChatStore } from './harnessChatStore'

interface AutopilotState {
  /** Optimistic overrides per session ID */
  overrides: Record<string, boolean>
  busy: boolean
  error: string | null
  setOverride: (sessionId: string, on: boolean | null) => void
  toggleAutopilot: (sessionId: string, currentOn: boolean) => Promise<boolean>
}

export const useAutopilotStore = create<AutopilotState>((set) => ({
  overrides: {},
  busy: false,
  error: null,
  setOverride: (sessionId, on) =>
    set((s) => {
      if (on === null) {
        const next = { ...s.overrides }
        delete next[sessionId]
        return { overrides: next }
      }
      return { overrides: { ...s.overrides, [sessionId]: on } }
    }),
  toggleAutopilot: async (sessionId, currentOn) => {
    if (!sessionId) return false
    const nextOn = !currentOn
    set((s) => ({
      busy: true,
      error: null,
      overrides: { ...s.overrides, [sessionId]: nextOn },
    }))
    try {
      const res = await setAutopilotApi(sessionId, nextOn)
      set((s) => ({
        overrides: { ...s.overrides, [sessionId]: res.on },
      }))
      const chatId = useAgentStore.getState().activeSessionId
      if (chatId) {
        await useHarnessChatStore.getState().refresh(chatId)
      }
      return true
    } catch (err) {
      set((s) => ({
        error: err instanceof Error ? err.message : String(err),
        overrides: { ...s.overrides, [sessionId]: currentOn }, // rollback
      }))
      return false
    } finally {
      set({ busy: false })
    }
  },
}))
