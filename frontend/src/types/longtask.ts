/** Canonical task state is separate from the streaming turn. Missing fields are unknown, not unlimited. */
export interface LongTask {
  runId: string
  state: string
  revision: number
  goalRevision?: number
  contractRevision?: number
  contractRef?: string
  resumePolicy: 'manual' | 'safe_auto'
  budget?: { totalStepLimit: number; totalStepsUsed: number; activeTimeLimitMs: number; activeTimeUsedMs: number }
  remainingBudget?: {
    steps?: number; activeTimeMs?: number
    totalStepLimit?: number; totalStepsUsed?: number; remainingSteps?: number
    activeTimeLimitMs?: number; activeTimeUsedMs?: number; remainingActiveTimeMs?: number
  }
  blockedReason?: string | null
  checkpointRef?: string | Record<string, unknown> | null
  pendingDecisionIds?: string[]
}
export interface StorageSnapshot {
  bytes: number | null
  level: 'normal' | 'warning' | 'elevated'
  measurementComplete: boolean
  measuredAt: string | number
  bySession?: Record<string, number> | { sessionId: string; bytes: number }[]
}
export interface DeletionPreview {
  operationId: string
  expectedRevision?: string
  sessionIds: string[]
  estimatedReclaimBytes: number
  retainedSummary: unknown
  capsuleId?: string
  validation: { status: string; errors?: string[] }
  warnings?: string[]
}
export function capsuleVerified(preview: DeletionPreview | null): boolean {
  return !!preview?.operationId && !!preview.capsuleId && preview.validation?.status === 'validated'
    && !(preview.validation.errors?.length) && typeof preview.expectedRevision === 'string' && /^[a-f0-9]{64}$/.test(preview.expectedRevision)
}
export function newerTask(previous: LongTask | null | undefined, incoming: LongTask | null | undefined) {
  if (incoming === undefined) return previous
  if (previous && incoming && previous.runId === incoming.runId && previous.revision > incoming.revision) return previous
  return incoming
}
