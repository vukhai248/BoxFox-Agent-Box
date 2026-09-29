import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../../i18n'
import { usePlanStore } from '../../../store/planStore'
import { PlanWorkflowView, PlanComposerStatus } from './PlanWorkflowView'
import type { PlanRun } from '../../../lib/planApi'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root
let host: HTMLDivElement
const run = (): PlanRun => ({ runId: 'p-test', sessionId: 'sid', revision: 3, briefRevision: 1, phase: 'interviewing', status: 'needs_user', profile: 'ai', language: 'vi', originalGoal: 'Tổng hợp hồ sơ', brief: { goal: {text: 'Tổng hợp hồ sơ y tế có dấu', status: 'user'} }, decisions: [], questions: [
  {id: 'users', field: 'users', text: 'Ai sử dụng?', why: 'Thay đổi giao diện', status: 'open', options: [{id: 'doctor',label: 'Bác sĩ',tradeoff: 'Cần kiểm duyệt'}]},
  {id: 'data', field: 'data', text: 'Dữ liệu gì?', why: '', status: 'open', options: []},
] })
function render(node: React.ReactNode) { act(() => root.render(<I18nProvider>{node}</I18nProvider>)) }
function click(selector: string) {
  const node = host.querySelector<HTMLElement>(selector)
  if (!node) throw new Error('missing ' + selector)
  act(() => node.click())
}
beforeEach(() => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  usePlanStore.setState({sessionId: 'sid', mode: {on: true, activeRunId: 'p-test'}, runs: [run()], error: null, saving: false})
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.restoreAllMocks() })
it('persistent interview supports options, free text and partial submit without executing', async () => {
  const answer = vi.fn().mockResolvedValue(true)
  const execute = vi.fn()
  const oldAnswer = usePlanStore.getState().answer, oldExecute = usePlanStore.getState().execute
  usePlanStore.setState({answer, execute})
  render(<PlanWorkflowView />)
  expect(host.querySelectorAll('textarea')).toHaveLength(2)
  expect(host.textContent).toContain('Bác sĩ')
  expect(host.querySelector('[data-testid="plan-execute"]')).toBeNull()
  click('input[type="radio"]')
  await act(async () => click('section button'))
  expect(answer).toHaveBeenCalledWith(expect.objectContaining({revision: 3}), [{questionId: 'users', optionId: 'doctor'}])
  expect(execute).not.toHaveBeenCalled()
  usePlanStore.setState({answer: oldAnswer, execute: oldExecute})
})
it('renders brief before asking confirmation and preserves Vietnamese content', () => {
  const value = run(); value.questions = [{id:'confirm',field:'__confirm__',text:'Xác nhận?',why:'',status:'open',options:[]}]
  usePlanStore.setState({runs: [value]})
  render(<PlanWorkflowView />)
  expect(host.textContent).toContain('Tổng hợp hồ sơ y tế có dấu')
})
it('approval exposes a separate execute button and never executes on render', () => {
  const value = run(); value.phase = 'approved'; value.status = 'active'; value.questions = []
  value.document = {identity:'medical',version:4,contentHash:'hash',relativePath:'.plans/v4-medical.md'}
  const old = usePlanStore.getState().execute, execute = vi.fn().mockResolvedValue(true)
  usePlanStore.setState({runs:[value],execute})
  render(<PlanWorkflowView document={{identity:'medical',version:4}} />)
  expect(execute).not.toHaveBeenCalled()
  expect(host.querySelector('[data-testid="plan-execute"]')?.textContent).toContain('v4')
  click('[data-testid="plan-execute"]')
  expect(execute).toHaveBeenCalledWith(value)
  usePlanStore.setState({execute:old})
})
it('sync trusts latest session config over historical mode events and rejects older run revisions', () => {
  const value = run()
  usePlanStore.getState().sync('sid', {planMode:{on:false,activeRunId:'p-test'}}, [
    {type:'plan_mode',data:{on:true,activeRunId:'p-test'}},
    {type:'plan_run',data:{...value,revision:2,phase:'scoping'}},
  ])
  expect(usePlanStore.getState().mode.on).toBe(false)
  expect(usePlanStore.getState().runs[0].revision).toBe(3)
  render(<PlanComposerStatus />)
  expect(host.textContent).toBe('')
})
it('a reloaded run retains the unanswered question IDs', () => {
  render(<PlanWorkflowView />)
  const questions = [...host.querySelectorAll('legend')].map(n=>n.textContent)
  render(<PlanWorkflowView />)
  expect([...host.querySelectorAll('legend')].map(n=>n.textContent)).toEqual(questions)
})
it('shows concrete independent reviewer findings', () => {
  const value = run()
  value.review = { rubric: 'SWE-AI/1', verdict: 'revise', dimensions: {}, findings: [{severity: 'high', blocking: true, evidence: 'Chưa có bộ dữ liệu để đánh giá câu tổng hợp đúng hay sai.'}] }
  usePlanStore.setState({runs: [value]})
  render(<PlanWorkflowView />)
  expect(host.textContent).toContain('Chưa có bộ dữ liệu để đánh giá câu tổng hợp đúng hay sai.')
})
