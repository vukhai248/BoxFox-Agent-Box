import { I18nProvider } from '../../i18n'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { LongTaskControls } from './LongTaskControls'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import type { LongTask } from '../../types/longtask'
;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
const calls: { path: string; body: Record<string, unknown>; method?: string }[] = []
vi.mock('../../lib/agentApi', () => ({ agentApi: async (path: string, body: Record<string, unknown>, method?: string) => { calls.push({ path, body, method }); return { status: 'accepted' } } }))
let host: HTMLDivElement, root: Root
const task: LongTask = { runId: 'run', revision: 4, state: 'budget_exhausted', resumePolicy: 'manual', checkpointRef: 'cp',
  budget: { totalStepLimit: 20, totalStepsUsed: 20, activeTimeLimitMs: 600000, activeTimeUsedMs: 600000 },
  remainingBudget: { steps: 0, activeTimeMs: 0 }, pendingDecisionIds: ['budget-card'] }
const render = async (longtask?: LongTask | null, contractRef?: string) => {
  useHarnessChatStore.setState({ sessions: { sid: { id: 'sid', goalRevision: 1, contractRef, status: 'completed', events: [], error: null, ...(longtask === undefined ? {} : { longtask }) } } })
  await act(async () => { root.render(<I18nProvider><LongTaskControls chatId="sid" /></I18nProvider>) })
}
const click = async (element: HTMLElement) => { await act(async () => { element.click() }) }
const change = async (element: HTMLInputElement | HTMLSelectElement, value: string) => { await act(async () => {
  const setter = Object.getOwnPropertyDescriptor(element instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype, 'value')!.set!
  setter.call(element, value); element.dispatchEvent(new Event(element instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
}) }
beforeEach(() => { calls.length = 0; host = document.createElement('div'); document.body.append(host); root = createRoot(host); vi.spyOn(useHarnessChatStore.getState(), 'refresh').mockResolvedValue() })
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks() })
it('plain Q&A has no controls when backend fields are absent', async () => { await render(); expect(host.textContent).toBe('') })
it('opt-in starts with no policy and no budget selected', async () => {
  await render(null); await click(host.querySelector('button')!)
  expect(host.querySelector('select')?.value).toBe('')
  expect([...host.querySelectorAll('input')].every(input => input.value === '')).toBe(true)
  expect([...host.querySelectorAll('button')].at(-1)?.disabled).toBe(true)
})
it('explicit finite opt-in sends approved route and budgets', async () => {
  await render(null); await click(host.querySelector('button')!)
  await change(host.querySelector('select')!, 'safe_auto')
  const inputs = host.querySelectorAll('input'); await change(inputs[0], '25'); await change(inputs[1], '10')
  await click([...host.querySelectorAll('button')].at(-1)!)
  expect(calls[0].path).toBe('/sessions/sid/longtask'); expect(calls[0].method).toBe('PUT')
  expect(calls[0].body).toMatchObject({ enabled: true, resumePolicy: 'safe_auto', budget: { totalStepLimit: 25, activeTimeLimitMs: 600000 } })
})
it('exhausted task remains distinct from completed turn and shows checkpoint', async () => {
  await render(task); expect(host.textContent).toContain('budget_exhausted'); expect(host.textContent).toContain('completed'); expect(host.textContent).toContain('cp'); expect(host.textContent).toContain('20 / 20')
  // Ngân sách cạn chỉ mở lại bằng thẻ quyết định xin thêm: nút resume không được giả vờ chạy tiếp.
  const resume = [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent?.includes('Resume'))!
  expect(resume.disabled).toBe(true)
})
it('failed run is terminal: no resume/pause/cancel offered', async () => {
  await render({ ...task, state: 'failed', checkpointRef: null, pendingDecisionIds: [] })
  const actions = [...host.querySelectorAll<HTMLButtonElement>('button')].filter(b => /^(Resume|Pause|Cancel task)$/.test(b.textContent ?? ''))
  expect(actions).toHaveLength(3)
  expect(actions.every(b => b.disabled)).toBe(true)
})
it('opt-in takes contractRef from the session payload; the run view never carries one', async () => {
  // Run view thật chỉ có `contractHash`, không có `contractRef`; nếu component đọc trường phantom
  // của run view thì body sẽ là null thay vì giá trị session gửi.
  await render(null, 'contract-from-session')
  await click(host.querySelector('button')!)
  await change(host.querySelector('select')!, 'manual')
  const inputs = host.querySelectorAll('input'); await change(inputs[0], '25'); await change(inputs[1], '10')
  await click([...host.querySelectorAll('button')].at(-1)!)
  expect(calls[0].body.contractRef).toBe('contract-from-session')
})
it('a terminal run offers the setup form again and pins the NEW run to the session revision', async () => {
  // Run đã xong không còn là ngõ cụt: backend cho lập run mới, và bản ghim mới phải theo revision mục
  // tiêu HIỆN TẠI của phiên (1), không phải bản ghim cũ của run đã xong (7).
  await render({ ...task, state: 'completed', blockedReason: null, checkpointRef: null, pendingDecisionIds: [], goalRevision: 7 })
  const toggle = [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === 'Set up long task')!
  expect(toggle).toBeDefined()
  await click(toggle)
  await change(host.querySelector('select')!, 'manual')
  const inputs = host.querySelectorAll('input'); await change(inputs[0], '15'); await change(inputs[1], '5')
  await click([...host.querySelectorAll('button')].at(-1)!)
  expect(calls[0]).toMatchObject({ path: '/sessions/sid/longtask', method: 'PUT',
    body: { enabled: true, resumePolicy: 'manual', goalRevision: 1, budget: { totalStepLimit: 15, activeTimeLimitMs: 300000 } } })
})
it('re-pins a stale-parked run to the current contract without sending a budget', async () => {
  await render({ ...task, state: 'needs_user', blockedReason: 'LONGTASK_STALE', revision: 9 }, 'contract-from-session')
  const repin = [...host.querySelectorAll<HTMLButtonElement>('button')].find(b => b.textContent === 'Re-pin the task to the latest request')!
  expect(repin).toBeDefined()
  await click(repin)
  expect(calls).toHaveLength(1)
  expect(calls[0]).toMatchObject({ path: '/sessions/sid/longtask', method: 'PUT',
    body: { enabled: true, goalRevision: 1, contractRef: 'contract-from-session', expectedRevision: 9 } })
  // Ngân sách đã tiêu do backend giữ; đổi hạn mức trực tiếp bị từ chối nên không gửi kèm.
  expect('budget' in calls[0].body).toBe(false)
})
it('offers re-pin only for a needs_user run parked on LONGTASK_STALE', async () => {
  await render({ ...task, state: 'needs_user', blockedReason: 'LONGTASK_NO_PROGRESS' })
  expect(host.textContent).not.toContain('Re-pin the task to the latest request')
})
it('does not offer re-pin while the run is not parked for the owner', async () => {
  await render({ ...task, state: 'running', blockedReason: 'LONGTASK_STALE' })
  expect(host.textContent).not.toContain('Re-pin the task to the latest request')
})
it('shows the small-allowance reason as text, not as the raw code', async () => {
  await render({ ...task, state: 'needs_user', blockedReason: 'LONGTASK_BUDGET_TOO_SMALL' })
  expect(host.textContent).toContain('smaller than the upper bound of one turn')
  expect(host.textContent).not.toContain('LONGTASK_BUDGET_TOO_SMALL')
  // "hạn mức quá nhỏ" KHÁC "đã dùng hết ngân sách": câu của ca hết ngân sách không được lẫn vào.
  expect(host.textContent).not.toContain('finite budget is used up')
})
it('keeps the exhausted-budget reason distinct from the small-allowance one', async () => {
  await render({ ...task, state: 'budget_exhausted', blockedReason: 'LONGTASK_BUDGET_EXHAUSTED' })
  expect(host.textContent).toContain('finite budget is used up')
  expect(host.textContent).not.toContain('smaller than the upper bound of one turn')
})
it('keeps unknown reason codes verbatim instead of guessing text', async () => {
  // Mã lỗi lượt backend giữ nguyên (thay cho TURN_FAILED_<CLASS>) vẫn phải đọc được để tra cứu.
  await render({ ...task, state: 'needs_user', blockedReason: 'UPSTREAM_HTTP_502' })
  expect(host.textContent).toContain('UPSTREAM_HTTP_502')
})
it('resume accepted is not resumed; repeats retain invocation identity', async () => {
  await render({ ...task, state: 'interrupted' }); const resume = host.querySelector('button')!
  await click(resume); await click(resume)
  expect(calls[0].body).toMatchObject({ runId: 'run', action: 'resume', expectedRevision: 4 })
  expect(calls[0].body.invocationId).toBe(calls[1].body.invocationId)
  expect(host.textContent).toMatch(/Chưa xác nhận đã tiếp tục|not yet confirmed/)
})
