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
  remainingBudget: { totalStepLimit: 20, totalStepsUsed: 20, remainingSteps: 0 }, pendingDecisionIds: ['budget-card'] }
const render = async (longtask?: LongTask | null) => {
  useHarnessChatStore.setState({ sessions: { sid: { id: 'sid', goalRevision: 1, status: 'completed', events: [], error: null, ...(longtask === undefined ? {} : { longtask }) } } })
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
it('resume accepted is not resumed; repeats retain invocation identity', async () => {
  await render({ ...task, state: 'interrupted' }); const resume = host.querySelector('button')!
  await click(resume); await click(resume)
  expect(calls[0].body).toMatchObject({ runId: 'run', action: 'resume', expectedRevision: 4 })
  expect(calls[0].body.invocationId).toBe(calls[1].body.invocationId)
  expect(host.textContent).toMatch(/Chưa xác nhận đã tiếp tục|not yet confirmed/)
})
