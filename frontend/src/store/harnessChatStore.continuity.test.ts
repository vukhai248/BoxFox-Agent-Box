import { expect, it, vi } from 'vitest'
import { canonicalDecisionEntries, mergeCanonicalDecisions, useHarnessChatStore } from './harnessChatStore'
import { newerTask, capsuleVerified } from '../types/longtask'
const cards = canonicalDecisionEntries([{ decisionId: 'same-id', revision: 3, kind: 'approval', question: 'Inspect?', deadline: 12345,
  options: [{ id: 'inspect', label: 'Inspect only', kind: 'approve' }], status: 'pending' }])
it('restores same ID, revision and original deadline without event replay', () => {
  expect(cards[0]).toMatchObject({ id: 'same-id', revision: 3, deadline: 12345, restored: true, status: 'pending', choice: null })
})
it('stale pending never rewinds a settled outcome', () => {
  const settled = { ...cards[0], status: 'approved' as const, revision: 4 }
  expect(mergeCanonicalDecisions([settled], [], cards)[0]).toBe(settled)
})
it('lower revision outcomes never overwrite newer canonical cards', () => {
  const fresh = { ...cards[0], revision: 5 }
  const old = { ...cards[0], status: 'expired' as const, revision: 2 }
  expect(mergeCanonicalDecisions([fresh], [old], [fresh])[0].revision).toBe(5)
})
it('missing canonical pending ID becomes non-actionable rather than replaying approval', () => {
  expect(mergeCanonicalDecisions(cards, [], [])[0].actionable).toBe(false)
})
it('late task snapshots do not rewind revisions', () => {
  const task = { runId: 'r', revision: 4, state: 'interrupted', resumePolicy: 'manual' as const }
  expect(newerTask(task, { ...task, revision: 3, state: 'running' })).toBe(task)
})
it('verification requires capsule identity, operation, revision and zero errors', () => {
  const p = { operationId: 'op', capsuleId: 'cap', expectedRevision: 'a'.repeat(64), sessionIds: ['sid'], estimatedReclaimBytes: 0, retainedSummary: '', validation: { status: 'validated' } }
  expect(capsuleVerified(p)).toBe(true)
  expect(capsuleVerified({ ...p, capsuleId: undefined })).toBe(false)
  expect(capsuleVerified({ ...p, expectedRevision: undefined })).toBe(false)
  expect(capsuleVerified({ ...p, validation: { status: 'draft' } })).toBe(false)
  expect(capsuleVerified({ ...p, validation: { status: 'validated', errors: ['missing goal'] } })).toBe(false)
})

const requests: string[] = []
let failHydration = false
vi.mock('../lib/agentApi', () => ({ agentApi: async (path: string) => {
  requests.push(path)
  if (path.includes('/decisions?')) {
    if (failHydration) throw new Error('DECISION_STORAGE_UNAVAILABLE')
    return path.includes('after=next')
      ? { decisions: [{ decisionId: 'card-2', revision: 2, kind: 'question', question: 'Next?', options: [] }], hasMore: false }
      : { decisions: [{ decisionId: 'card-1', revision: 1, kind: 'approval', question: 'Inspect?', options: [] }], nextAfter: 'next', hasMore: true }
  }
  return { id: 'hydrate', status: 'interrupted', config: {}, events: [], longtask: null, goalRevision: 1 }
} }))
it('refresh paginates canonical decisions even when events contain no request', async () => {
  requests.length = 0; failHydration = false
  useHarnessChatStore.setState({ sessions: { hydrate: { id: 'hydrate', status: 'interrupted', events: [], error: null, longtask: null } }, decisions: {} })
  await useHarnessChatStore.getState().refresh('hydrate')
  expect(requests.filter(path => path.includes('/decisions?'))).toHaveLength(2)
  expect(useHarnessChatStore.getState().decisions.hydrate.map(card => card.id)).toEqual(['card-1', 'card-2'])
  expect(useHarnessChatStore.getState().sessions.hydrate.goalRevision).toBe(1)
})
it('an already-hydrated running session does not re-request decisions every poll', async () => {
  requests.length = 0; failHydration = false
  useHarnessChatStore.setState({ sessions: { hydrate: { id: 'hydrate', status: 'running', events: [], error: null, longtask: null, decisionsHydrated: true } }, decisions: { hydrate: cards } })
  await useHarnessChatStore.getState().refresh('hydrate')
  expect(requests.filter(path => path.includes('/decisions?'))).toHaveLength(0)
  expect(useHarnessChatStore.getState().sessions.hydrate.decisionsHydrated).toBe(true)
  expect(useHarnessChatStore.getState().decisions.hydrate[0]).toBe(cards[0])
  expect(useHarnessChatStore.getState().decisions.hydrate[0].actionable).toBe(true)
})
it('failed durable hydration does not leave cached approvals actionable', async () => {
  failHydration = true
  useHarnessChatStore.setState({ sessions: { hydrate: { id: 'hydrate', status: 'interrupted', events: [], error: null, longtask: null } }, decisions: { hydrate: cards } })
  await useHarnessChatStore.getState().refresh('hydrate')
  expect(useHarnessChatStore.getState().decisions.hydrate[0].actionable).toBe(false)
  expect(useHarnessChatStore.getState().sessions.hydrate.error).toContain('DECISION_STORAGE_UNAVAILABLE')
  failHydration = false
})
