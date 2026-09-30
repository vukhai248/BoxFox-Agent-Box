/**
 * Work Graph + thẻ phỏng vấn — hợp đồng giao diện của lớp điều phối mới.
 *
 * Khoá lại: (1) thẻ `interview` dựng từ `decision_requested` thật và gửi đúng
 * `{choice:'submit', answers}` / `{choice:'decide'}`; (2) bảng Work Graph dựng từ event
 * `work_graph` (ảnh chụp có revision cao hơn thắng), hiện nút, đợt DAG, vòng review; công
 * tắc Autopilot gọi `PUT /autopilot`; (3) tab Work Graph chỉ tự mở ở lần đầu một lượt xuất hiện.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../../i18n'
import { useAgentStore } from '../../../store/agentStore'
import type { HarnessEvent } from '../../../store/harnessChatStore'
import { dispatchTabIntents, parseDecisions, useHarnessChatStore } from '../../../store/harnessChatStore'
import { useUiStore } from '../../../store/uiStore'
import { collectWorkRuns, parseWorkRun } from '../../../lib/workGraph'
import { interviewReplies } from '../../InterviewCard'
import { DecisionsPanel } from '../DecisionsPanel'
import { WorkGraphPanel, nodeStatus } from './WorkGraphPanel'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { agentApiMock } = vi.hoisted(() => ({ agentApiMock: vi.fn() }))
vi.mock('../../../lib/agentApi', () => ({ agentApi: agentApiMock }))

const CHAT_ID = 'chat-work-graph'
let roots: Root[] = []

function render(node: React.ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(<I18nProvider>{node}</I18nProvider>)
  })
  return host
}

function ev(seq: number, type: string, data: Record<string, unknown>): HarnessEvent {
  return { seq, type, data, created: 1000 + seq }
}

const QUESTIONS = [
  {
    id: 'q1',
    question: 'Plan tập trung vào kết quả nào?',
    rationale: 'Phạm vi quyết định số sub-plan.',
    options: [
      { id: 'both', label: 'Cả kiến trúc và giao diện', description: 'Plan cơ chế và UI', recommended: true },
      { id: 'arch', label: 'Chỉ kiến trúc agent', description: 'Contract, routing, review loop', recommended: false },
    ],
  },
  {
    id: 'q2',
    question: 'Áp dụng vào repository nào?',
    rationale: '',
    options: [
      { id: 'boxfox', label: 'BoxFox', description: '', recommended: false },
      { id: 'other-repo', label: 'Repo khác', description: '', recommended: false },
    ],
  },
]

const INTERVIEW_REQUEST = ev(1, 'decision_requested', {
  decisionId: 'iv1',
  kind: 'interview',
  title: 'Câu hỏi làm rõ',
  question: 'Câu hỏi làm rõ',
  questions: QUESTIONS,
  options: [
    { id: 'submit', label: 'Gửi câu trả lời', kind: 'approve' },
    { id: 'decide', label: 'Để agent quyết định', kind: 'alternative' },
  ],
  deadline: Date.now() / 1000 + 900,
  defaultChoice: 'decide',
  runId: 'w-1',
})

function run(revision: number, overrides: Record<string, unknown> = {}) {
  return {
    runId: 'w-1',
    sessionId: 'sess-w',
    title: 'Rework orchestrator',
    goal: 'Main agent plans with review loops',
    flow: 'plan',
    status: 'discovering',
    revision,
    autopilot: false,
    updatedAt: 100 + revision,
    nodes: [
      {
        id: 'E1',
        kind: 'explore',
        title: 'Map runtime',
        goal: 'Find delegation code',
        dependsOn: [],
        acceptance: ['file:line evidence'],
        tests: [],
        files: [],
        stages: {
          produce: {
            status: 'accepted',
            attempts: 2,
            preview: 'Found runtime.py:6600',
            rounds: [
              { attempt: 1, producerRole: 'explore', reviewerRole: 'review', verdict: 'revise', findings: 'Missing line numbers', knowledge: [] },
              { attempt: 2, producerRole: 'explore', reviewerRole: 'review', verdict: 'ok', findings: 'Good', knowledge: [{ role: 'research', question: 'aiohttp limits?', status: 'done' }] },
            ],
          },
        },
      },
      {
        id: 'P1',
        kind: 'plan',
        title: 'Engine sub-plan',
        goal: 'Plan the engine',
        dependsOn: ['E1'],
        acceptance: [],
        tests: ['pytest tests/unit/test_work_graph.py'],
        files: ['work_graph.py'],
        stages: { produce: { status: 'running', attempts: 1, preview: '', rounds: [] }, execute: { status: 'pending', attempts: 0, preview: '', rounds: [] } },
      },
      {
        id: 'P2',
        kind: 'plan',
        title: 'UI sub-plan',
        goal: 'Plan the panel',
        dependsOn: ['E1'],
        acceptance: [],
        tests: [],
        files: [],
        stages: { produce: { status: 'pending', attempts: 0, preview: '', rounds: [] }, execute: { status: 'pending', attempts: 0, preview: '', rounds: [] } },
      },
    ],
    waves: [['P1', 'P2']],
    issues: [],
    review: { status: null, rounds: [] },
    documents: [],
    approval: null,
    ship: null,
    history: [{ at: 101, event: 'created', detail: 'flow=plan' }],
    ...overrides,
  }
}

function click(el: Element | null | undefined) {
  act(() => {
    el?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function typeInto(textarea: HTMLTextAreaElement, text: string) {
  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!
  act(() => {
    nativeSetter.call(textarea, text)
    textarea.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

beforeEach(() => {
  localStorage.clear()
  useAgentStore.setState({ activeSessionId: CHAT_ID })
  useHarnessChatStore.setState({ sessions: {}, decisions: {}, intentSeq: {} })
  useUiStore.setState({ tabIntentTargets: {}, pendingIntents: [] })
  agentApiMock.mockReset()
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('thẻ phỏng vấn', () => {
  it('parseDecisions dựng câu hỏi và nhận câu trả lời đã chốt', () => {
    const resolved = ev(2, 'decision_resolved', {
      decisionId: 'iv1',
      status: 'answered',
      choice: 'submit',
      answers: [
        { questionId: 'q1', question: 'Plan tập trung vào kết quả nào?', optionId: 'both', answer: 'Cả kiến trúc và giao diện', decidedBy: 'user' },
        { questionId: 'q2', question: 'Áp dụng vào repository nào?', optionId: 'decide', answer: null, decidedBy: 'agent', recommended: 'BoxFox' },
      ],
    })
    const [pending] = parseDecisions([INTERVIEW_REQUEST])
    expect(pending.kind).toBe('interview')
    expect(pending.questions?.map((q) => q.id)).toEqual(['q1', 'q2'])
    expect(pending.questions?.[0].options[0]).toMatchObject({ id: 'both', recommended: true })
    expect(pending.workRunId).toBe('w-1')
    const [done] = parseDecisions([INTERVIEW_REQUEST, resolved])
    expect(done.status).toBe('answered')
    expect(done.answers?.[1]).toMatchObject({ decidedBy: 'agent', recommended: 'BoxFox' })
  })

  it('interviewReplies bỏ câu chưa chọn và câu "Khác" rỗng', () => {
    const questions = parseDecisions([INTERVIEW_REQUEST])[0].questions!
    expect(
      interviewReplies(questions, { q1: { optionId: 'other', text: '  ' }, q2: { optionId: 'boxfox', text: '' } }),
    ).toEqual([{ questionId: 'q2', optionId: 'boxfox' }])
    expect(interviewReplies(questions, { q1: { optionId: 'other', text: 'chỉ UI' } })).toEqual([
      { questionId: 'q1', optionId: 'other', text: 'chỉ UI' },
    ])
  })

  it('chọn một lựa chọn, tự nhập câu kia, rồi gửi đúng answers', async () => {
    useHarnessChatStore.setState({
      sessions: { [CHAT_ID]: { id: 'sess-w', status: 'awaiting_decision', events: [INTERVIEW_REQUEST], error: null } },
      decisions: { [CHAT_ID]: parseDecisions([INTERVIEW_REQUEST]) },
    })
    agentApiMock.mockImplementation(async () => ({
      status: 'resolved',
      decisionId: 'iv1',
      choice: 'submit',
      outcome: 'answered',
      answers: [
        { questionId: 'q1', optionId: 'arch', answer: 'Chỉ kiến trúc agent', decidedBy: 'user' },
        { questionId: 'q2', optionId: 'other', answer: 'repo nội bộ', decidedBy: 'user' },
      ],
    }))
    const host = render(<DecisionsPanel />)
    const card = host.querySelector('[data-testid="interview-card"]')
    expect(card).toBeTruthy()
    expect(card?.textContent).toContain('Plan tập trung vào kết quả nào?')
    expect(card?.textContent).toContain('Chỉ kiến trúc agent')
    // Q2 thu gọn: lựa chọn của nó chưa hiện.
    expect(host.querySelector('[data-testid="interview-option-q2-boxfox"]')).toBeNull()

    click(host.querySelector('[data-testid="interview-option-q1-arch"] input'))
    // Chọn xong Q1 thì Q2 tự mở.
    click(host.querySelector('[data-testid="interview-option-q2-other"] input'))
    const other = host.querySelector('[data-testid="interview-other-input-q2"]') as HTMLTextAreaElement
    expect(other).toBeTruthy()
    typeInto(other, 'repo nội bộ')
    expect(host.querySelector('[data-testid="interview-progress"]')?.textContent).toContain('2/2')

    await act(async () => {
      host.querySelector('[data-testid="interview-submit"]')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const calls = agentApiMock.mock.calls.filter(([path]) => String(path).endsWith('/decisions'))
    expect(calls).toHaveLength(1)
    expect(calls[0][1]).toEqual({
      decisionId: 'iv1',
      choice: 'submit',
      answers: [
        { questionId: 'q1', optionId: 'arch' },
        { questionId: 'q2', optionId: 'other', text: 'repo nội bộ' },
      ],
    })
    const stored = useHarnessChatStore.getState().decisions[CHAT_ID][0]
    expect(stored.status).toBe('answered')
    expect(stored.answers?.[1].answer).toBe('repo nội bộ')
  })

  it('"Để agent quyết định" gửi choice decide, không kèm answers', async () => {
    useHarnessChatStore.setState({
      sessions: { [CHAT_ID]: { id: 'sess-w', status: 'awaiting_decision', events: [INTERVIEW_REQUEST], error: null } },
      decisions: { [CHAT_ID]: parseDecisions([INTERVIEW_REQUEST]) },
    })
    agentApiMock.mockImplementation(async () => ({ status: 'resolved', decisionId: 'iv1', choice: 'decide', outcome: 'answered' }))
    const host = render(<DecisionsPanel />)
    await act(async () => {
      host.querySelector('[data-testid="interview-decide-all"]')?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const calls = agentApiMock.mock.calls.filter(([path]) => String(path).endsWith('/decisions'))
    expect(calls[0][1]).toEqual({ decisionId: 'iv1', choice: 'decide' })
  })

  it('"Khác" để trống chặn gửi; "để agent quyết định" từng câu gửi optionId decide', async () => {
    useHarnessChatStore.setState({
      sessions: { [CHAT_ID]: { id: 'sess-w', status: 'awaiting_decision', events: [INTERVIEW_REQUEST], error: null } },
      decisions: { [CHAT_ID]: parseDecisions([INTERVIEW_REQUEST]) },
    })
    agentApiMock.mockImplementation(async () => ({ status: 'resolved', decisionId: 'iv1', choice: 'submit', outcome: 'answered' }))
    const host = render(<DecisionsPanel />)
    click(host.querySelector('[data-testid="interview-option-q1-arch"] input'))
    click(host.querySelector('[data-testid="interview-option-q2-other"] input'))
    const submit = host.querySelector('[data-testid="interview-submit"]') as HTMLButtonElement
    expect(submit.disabled).toBe(true)
    const decideOne = host.querySelector('[data-testid="interview-decide-q2"]') as HTMLButtonElement
    click(decideOne)
    expect(decideOne.getAttribute('aria-pressed')).toBe('true')
    expect(submit.disabled).toBe(false)
    await act(async () => {
      submit.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const calls = agentApiMock.mock.calls.filter(([path]) => String(path).endsWith('/decisions'))
    expect(calls[0][1]).toEqual({
      decisionId: 'iv1',
      choice: 'submit',
      answers: [
        { questionId: 'q1', optionId: 'arch' },
        { questionId: 'q2', optionId: 'decide' },
      ],
    })
  })
})

describe('Work Graph', () => {
  it('parseWorkRun bỏ ảnh chụp thiếu runId; collectWorkRuns giữ revision cao nhất', () => {
    expect(parseWorkRun({ title: 'x' })).toBeNull()
    const runs = collectWorkRuns(
      [ev(1, 'work_graph', run(3, { status: 'verified' })), ev(2, 'work_graph', run(2, { status: 'drafting' }))],
      [parseWorkRun(run(1))!],
    )
    expect(runs).toHaveLength(1)
    expect(runs[0].status).toBe('verified')
    expect(runs[0].revision).toBe(3)
    expect(nodeStatus(runs[0].nodes[1])).toBe('running')
    expect(nodeStatus(runs[0].nodes[0])).toBe('accepted')
  })

  it('bảng hiện nút, đợt song song, vòng review và bật Autopilot qua PUT', async () => {
    agentApiMock.mockImplementation(async (path: string, body?: unknown, method?: string) => {
      if (String(path).endsWith('/work')) return { enabled: true, autopilot: false, runs: [] }
      if (String(path).endsWith('/autopilot')) return { on: (body as { on: boolean }).on, method }
      return {}
    })
    useHarnessChatStore.setState({
      sessions: { [CHAT_ID]: { id: 'sess-w', status: 'running', events: [ev(5, 'work_graph', run(4))], error: null } },
    })
    const host = render(<WorkGraphPanel />)
    await act(async () => {})
    expect(host.querySelector('[data-testid="work-run"]')?.getAttribute('data-run-status')).toBe('discovering')
    const nodes = Array.from(host.querySelectorAll('[data-testid="work-node"]')).map((node) => node.getAttribute('data-node-id'))
    expect(nodes).toEqual(['E1', 'P1', 'P2'])
    const wave = host.querySelector('[data-testid="work-wave"]')
    expect(wave?.textContent).toContain('P1')
    expect(wave?.textContent).toContain('P2')

    // Mở E1: hai vòng review, vòng revise mở sẵn nhận xét.
    click(host.querySelector('[data-node-id="E1"] button'))
    const rounds = host.querySelectorAll('[data-testid="work-round"]')
    expect(rounds).toHaveLength(2)
    expect(rounds[0].getAttribute('data-verdict')).toBe('revise')
    expect(rounds[0].textContent).toContain('Missing line numbers')

    const toggle = host.querySelector('[data-testid="work-autopilot-toggle"]') as HTMLButtonElement
    expect(toggle.getAttribute('aria-checked')).toBe('false')
    await act(async () => {
      toggle.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const put = agentApiMock.mock.calls.find(([path]) => String(path).endsWith('/autopilot'))
    expect(put).toEqual(['/sessions/sess-w/autopilot', { on: true }, 'PUT'])
    expect(toggle.getAttribute('aria-checked')).toBe('true')
  })

  it('parseWorkRun đọc documents dạng object {path}', () => {
    const parsed = parseWorkRun({ ...run(1), documents: [{ path: '.plans/work/plan.md', identity: 'x', version: 1 }, 'a.md', {}] })
    expect(parsed?.documents).toEqual(['.plans/work/plan.md', 'a.md'])
  })

  it('bảng trống khi chưa có lượt nào', async () => {
    agentApiMock.mockImplementation(async () => ({ enabled: true, autopilot: false, runs: [] }))
    useHarnessChatStore.setState({ sessions: { [CHAT_ID]: { id: 'sess-w', status: 'idle', events: [], error: null } } })
    const host = render(<WorkGraphPanel />)
    await act(async () => {})
    expect(host.querySelector('[data-testid="work-empty"]')).toBeTruthy()
  })

  it('tab Work Graph tự mở ở lần đầu một lượt xuất hiện, không mở lại mỗi ảnh chụp', () => {
    const request = vi.spyOn(useUiStore.getState(), 'requestTabIntent')
    const first = [ev(1, 'work_graph', run(1))]
    dispatchTabIntents({ allEvents: first, freshEvents: first, lastSeq: 0, firstHydration: false })
    const all = [...first, ev(2, 'work_graph', run(2))]
    dispatchTabIntents({ allEvents: all, freshEvents: [all[1]], lastSeq: 1, firstHydration: false })
    const workCalls = request.mock.calls.filter(([intent]) => intent.tab === 'work')
    expect(workCalls).toHaveLength(1)
    expect(workCalls[0][0].target).toEqual({ runId: 'w-1' })
  })
})
