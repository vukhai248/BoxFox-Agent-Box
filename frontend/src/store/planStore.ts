import { create } from 'zustand'
import { answerPlan, executePlan, fetchPlanRuns, planAction, readPlanRun, setPlanMode, type PlanAnswer, type PlanMode, type PlanRun } from '../lib/planApi'
import { useHarnessChatStore } from './harnessChatStore'
import { useAgentStore } from './agentStore'

interface State {
  sessionId: string; mode: PlanMode; runs: PlanRun[]; error: string | null; saving: boolean
  sync: (sid: string, config: unknown, events: readonly { type: string; data: Record<string, unknown> }[]) => void
  refresh: () => Promise<void>
  toggle: (on: boolean) => Promise<void>
  answer: (run: PlanRun, answers: PlanAnswer[]) => Promise<boolean>
  action: (run: PlanRun, action: string) => Promise<boolean>
  execute: (run: PlanRun) => Promise<boolean>
}
const OFF: PlanMode = { on: false, activeRunId: null }
const merge = (runs: PlanRun[], next: PlanRun): PlanRun[] => {
  const old = runs.find(r => r.runId === next.runId)
  if (old && old.revision > next.revision) return runs
  return [next, ...runs.filter(r => r.runId !== next.runId)]
}
const errorText = (e: unknown) => e instanceof Error ? e.message : String(e)

export const usePlanStore = create<State>((set, get) => {
  const mutate = async (operation: (id: string) => Promise<{ run: PlanRun }>) => {
    if (get().saving) return false
    const sid = get().sessionId
    set({ saving: true, error: null })
    try {
      const result = await operation(crypto.randomUUID())
      if (get().sessionId === sid) set(s => ({ runs: merge(s.runs, result.run) }))
      const chatId = useAgentStore.getState().activeSessionId
      await useHarnessChatStore.getState().refresh(chatId)
      return true
    } catch (e) {
      if (get().sessionId === sid) set({ error: errorText(e) })
      await get().refresh()
      return false
    } finally {
      if (get().sessionId === sid) set({ saving: false })
    }
  }
  return {
    sessionId: '', mode: OFF, runs: [], error: null, saving: false,
    sync: (sid, config, events) => {
      const changed = sid !== get().sessionId
      if (changed) set({ sessionId: sid, mode: OFF, runs: [], error: null, saving: false })
      const raw = config && typeof config === 'object' ? (config as Record<string, unknown>).planMode : null
      let nextMode = raw && typeof raw === 'object' ? { on: (raw as PlanMode).on === true, activeRunId: (raw as PlanMode).activeRunId ?? null } : OFF
      let runs = get().runs
      for (const event of events) {
        if (event.type === 'plan_mode') nextMode = { on: event.data.on === true, activeRunId: typeof event.data.activeRunId === 'string' ? event.data.activeRunId : null }
        if (event.type === 'plan_run') {
          const run = readPlanRun(event.data)
          if (run) runs = merge(runs, run)
        }
      }
      if (raw && typeof raw === 'object') nextMode = { on: (raw as PlanMode).on === true, activeRunId: (raw as PlanMode).activeRunId ?? null }
      set({ mode: nextMode, runs })
      if (changed && sid) void get().refresh()
    },
    refresh: async () => {
      const sid = get().sessionId
      if (!sid) return
      try {
        const result = await fetchPlanRuns(sid)
        if (get().sessionId === sid) set(s => ({ runs: result.runs.reduce((all, raw) => {
          const run = readPlanRun(raw)
          return run ? merge(all, run) : all
        }, s.runs) }))
      } catch (e) { if (get().sessionId === sid) set({ error: errorText(e) }) }
    },
    toggle: async on => {
      const chatId = useAgentStore.getState().activeSessionId
      const sid = useHarnessChatStore.getState().sessions[chatId]?.id
      try {
        if (!sid) {
          await useHarnessChatStore.getState().send(chatId, '/plan', null)
        } else {
          const result = await setPlanMode(sid, on)
          if (get().sessionId === sid) set(s => ({ mode: result.mode, runs: result.run ? merge(s.runs, result.run) : s.runs, error: null }))
        }
        await useHarnessChatStore.getState().refresh(chatId)
      } catch (e) { set({ error: errorText(e) }) }
    },
    answer: (run, answers) => mutate(id => answerPlan(run, answers, id)),
    action: (run, action) => mutate(id => planAction(run, action, id)),
    execute: run => mutate(id => executePlan(run, id)),
  }
})
