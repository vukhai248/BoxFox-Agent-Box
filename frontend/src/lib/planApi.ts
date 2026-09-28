import { agentApi } from './agentApi'

export interface PlanQuestion {
  id: string; field: string; text: string; why: string; status: string
  options: { id: string; label: string; tradeoff: string }[]; answer?: string
}
export interface PlanItem { text: string; status: string; source?: { kind: string }; reason?: string }
export interface PlanRun {
  runId: string; sessionId: string; revision: number; briefRevision: number
  phase: string; status: string; profile: string; language: string; originalGoal: string
  brief: Record<string, PlanItem>; decisions: (PlanItem & { id: string })[]
  questions: PlanQuestion[]; blocker?: string
  executionStatus?: string
  switchAnswer?: string
  document?: { identity: string; version: number; contentHash: string; relativePath: string } | null
  documents?: { identity: string; version: number; contentHash: string }[]
  review?: { rubric: string; verdict: string; briefRevision?: number; dimensions: Record<string, { status: string; evidence: string }>; findings?: { severity: string; blocking: boolean; evidence: string }[] } | null
}
export interface PlanMode { on: boolean; activeRunId: string | null }
export interface PlanAnswer { questionId: string; optionId?: string; text?: string }

export function readPlanRun(value: unknown): PlanRun | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Record<string, unknown>
  if (typeof row.runId !== 'string' || typeof row.revision !== 'number' || !Array.isArray(row.questions)) return null
  if (!row.brief || typeof row.brief !== 'object' || Array.isArray(row.brief) || !Array.isArray(row.decisions)) return null
  if (row.questions.some(q => !q || typeof q !== 'object' || typeof q.id !== 'string' || !Array.isArray(q.options))) return null
  return value as PlanRun
}
export const fetchPlanRuns = (sid: string) => agentApi<{ runs: PlanRun[] }>(`/plans/runs?sessionId=${encodeURIComponent(sid)}`)
export const setPlanMode = (sid: string, on: boolean) => agentApi<{ mode: PlanMode; run: PlanRun | null }>(`/sessions/${encodeURIComponent(sid)}/plan-mode`, { on }, 'PUT')
export const answerPlan = (run: PlanRun, answers: PlanAnswer[], invocationId: string) =>
  agentApi<{ run: PlanRun; queued: boolean }>(`/plans/runs/${encodeURIComponent(run.runId)}/answers`, { revision: run.revision, answers, invocationId })
export const planAction = (run: PlanRun, action: string, invocationId: string) =>
  agentApi<{ run: PlanRun; queued: boolean }>(`/plans/runs/${encodeURIComponent(run.runId)}/actions`, { action, revision: run.revision, invocationId })
export const executePlan = (run: PlanRun, invocationId: string) =>
  agentApi<{ run: PlanRun; queued: boolean; duplicate?: boolean }>('/plans/execute', { ...run.document, revision: run.revision, invocationId })
