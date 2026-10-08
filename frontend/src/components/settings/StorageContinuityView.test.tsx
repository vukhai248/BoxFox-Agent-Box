import { I18nProvider } from '../../i18n'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { StorageContinuityView } from './StorageContinuityView'
;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let host: HTMLDivElement, root: Root
let validation = 'draft', fail = false, outcome = 'deleted'
const calls: { path: string; body?: Record<string, unknown> }[] = []
vi.mock('../../lib/agentApi', () => ({ agentApi: async (path: string, body?: Record<string, unknown>) => {
  calls.push({ path, body })
  if (path.includes('/history/storage')) return { bytes: 4_300_000_000, level: 'warning', bySession: { sid: 1_200_000_000 }, measuredAt: '2026-10-08', measurementComplete: false }
  if (path.endsWith('/deletion-preview')) {
    if (fail) throw new Error('CAPSULE_WRITE_FAILED')
    return { operationId: 'op', expectedRevision: 'a'.repeat(64), capsuleId: 'cap', sessionIds: ['sid', 'child'], estimatedReclaimBytes: 1_200_000_000,
      retainedSummary: 'Goal, unresolved blocker, next steps', validation: { status: validation, errors: [] }, warnings: ['Raw references become tombstones'] }
  }
  if (path.endsWith('/deletion-confirm')) return { status: outcome }
  return { id: 'sid', deletionRevision: 'a'.repeat(64) }
} }))
const render = async () => { await act(async () => { root.render(<I18nProvider><StorageContinuityView sessionId="sid" /></I18nProvider>) }) }
const button = (label: string) => [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes(label))!
const click = async (element: HTMLElement) => { await act(async () => { element.click() }) }
beforeEach(() => { validation = 'draft'; fail = false; outcome = 'deleted'; calls.length = 0; host = document.createElement('div'); document.body.append(host); root = createRoot(host) })
afterEach(async () => { await act(async () => root.unmount()); host.remove() })
it('shows decimal global GB, contribution and incomplete measurement; deletion starts disabled', async () => {
  await render()
  expect(host.textContent).toContain('4.30 GB'); expect(host.textContent).toContain('1.20 GB')
  expect(host.textContent).toMatch(/chưa đầy đủ|incomplete/)
  expect(button('Delete raw history').disabled).toBe(true)
  expect(calls[0].path).toContain('callerSessionId=sid')
})
it('draft capsule cannot enable acknowledgment or deletion', async () => {
  await render(); await click(button('Create preview'))
  expect(host.querySelector<HTMLInputElement>('input')?.disabled).toBe(true)
  expect(button('Delete raw history').disabled).toBe(true)
  expect(calls.find(c => c.path.endsWith('/deletion-preview'))?.body).toEqual({ mode: 'history_only', expectedRevision: 'a'.repeat(64) })
  expect(calls.some(c => c.path.endsWith('/deletion-confirm'))).toBe(false)
})
it('verified capsule plus acknowledgment still needs final confirmation before deletion', async () => {
  validation = 'validated'; await render(); await click(button('Create preview'))
  expect(button('Delete raw history').disabled).toBe(true)
  await click(host.querySelector('input')!); await click(button('Delete raw history'))
  expect(calls.some(c => c.path.endsWith('/deletion-confirm'))).toBe(false)
  await click(button('Confirm deletion'))
  expect(calls.find(c => c.path.endsWith('/deletion-confirm'))?.body).toEqual({ operationId: 'op', expectedRevision: 'a'.repeat(64), confirm: true })
})
it('capsule write failure retains raw and keeps deletion disabled', async () => {
  fail = true; await render(); await click(button('Create preview'))
  expect(host.textContent).toContain('CAPSULE_WRITE_FAILED'); expect(button('Delete raw history').disabled).toBe(true)
  expect(calls.some(c => c.path.endsWith('/deletion-confirm'))).toBe(false)
})
it('cleanup_pending does not claim reclaimed space and blocks another delete', async () => {
  validation = 'validated'; outcome = 'cleanup_pending'; await render(); await click(button('Create preview'))
  await click(host.querySelector('input')!); await click(button('Delete raw history')); await click(button('Confirm deletion'))
  expect(host.textContent).toMatch(/dọn file còn chờ|cleanup is pending/)
  expect(button('Create preview').disabled).toBe(true)
})
