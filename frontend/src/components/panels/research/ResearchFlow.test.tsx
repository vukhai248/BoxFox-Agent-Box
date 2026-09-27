/**
 * Bài kiểm luồng đầy đủ của chế độ `/research` (điều kiện nghiệm thu §7 P4):
 *
 *   bật mode → trả lời phỏng vấn nhiều câu trong MỘT lần gọi → sửa thẻ phạm vi → tắt mode chọn
 *   "Tạm dừng" → bật lại → tắt mode chọn "Tiếp tục chạy nền" → thấy chỉ báo run chạy nền → thẻ báo
 *   cáo hiện khi run xong.
 *
 * Phụ thêm: mỗi `kind` của `research_prompt` đều vẽ được, và pha của run đổi thì dòng thời gian đổi.
 *
 * Không dùng @testing-library (dự án không có): raw `createRoot` + `act`, đúng khuôn
 * `ChatInputBar.test.tsx`.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../../i18n'
import { useResearchStore } from '../../../store/researchStore'
import { useUiStore } from '../../../store/uiStore'
import { readJob, RESEARCH_MODE_OFF } from '../../../lib/researchMode'
import { ResearchPromptCard } from './ResearchPromptCard'
import { ScopeCard } from './ScopeCard'
import { ResearchComposerStatus } from './ResearchComposerStatus'
import { ResearchConversationCards } from './ResearchConversationCards'
import { ResearchReportCard } from './ResearchReportCard'
import { ResearchToggle } from './ResearchToggle'
import { RunTimeline } from './RunTimeline'
import { ResearchPanel } from '../ResearchPanel'
import { useHarnessChatStore } from '../../../store/harnessChatStore'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

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

function jsonResponse(body: unknown, status = 200): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response
}

function click(host: HTMLElement, selector: string): void {
  const node = host.querySelector<HTMLButtonElement>(selector)
  if (!node) throw new Error(`không thấy ${selector}`)
  act(() => {
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

/** Đặt giá trị cho input/textarea/select theo cách React nhìn thấy (native setter + sự kiện). */
function setFieldValue(node: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string): void {
  const proto = node instanceof HTMLSelectElement
    ? HTMLSelectElement.prototype
    : node instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype
  Object.getOwnPropertyDescriptor(proto, 'value')!.set!.call(node, value)
  act(() => {
    node.dispatchEvent(new Event(node instanceof HTMLSelectElement ? 'change' : 'input', { bubbles: true }))
  })
}

const scopePayload = {
  revision: 1,
  goal: { text: 'Data augmentation bằng diffusion cho ảnh y tế', status: 'assumed', source: { kind: 'agent' } },
  purpose: { text: '', status: 'assumed' },
  questions: [{ id: 'q1', text: 'Nhóm phương pháp dẫn đầu?', importance: 'high', status: 'unexplored' }],
  timePolicy: { velocity: 'fast', foundational: 'any', reason: '', status: 'assumed' },
  window: { velocity: 'fast', days: 630, start: '2025-01-01', end: '2026-09-25' },
  sourceKinds: [],
  exclusions: [{ text: 'Không dùng ảnh tự nhiên nói chung', status: 'confirmed', source: { kind: 'user' } }],
  outputs: ['Báo cáo cấu trúc + bảng so sánh'],
  depth: 'standard',
  tier: 2,
  budget: { proposedSeconds: 1680, hardCeilingSeconds: 1800, bigJob: false, approved: false },
  openQuestions: [
    { id: 'oq1', text: 'Bạn cần kết quả để chọn phương án hay bản đồ nghiên cứu?', blocking: true, affects: ['đầu ra'], answer: null, promptId: 'rp-interview' },
    { id: 'oq2', text: 'Phạm vi thời gian nào đúng?', blocking: true, affects: ['cửa sổ'], answer: null, promptId: 'rp-interview' },
  ],
}

const interviewPrompt = {
  promptId: 'rp-interview',
  researchId: 'R1',
  kind: 'interview',
  revision: 2,
  blocking: true,
  status: 'open',
  questions: [
    {
      id: 'oq1', text: 'Bạn cần kết quả để chọn phương án dùng ngay hay bản đồ nghiên cứu?', why: 'đổi hướng khảo sát',
      options: [{ id: 'o1', label: 'Chọn phương án dùng ngay' }, { id: 'o2', label: 'Bản đồ nghiên cứu' }],
      allowFreeText: true, affects: ['đầu ra'], required: true, blocking: true, answer: null,
    },
    {
      id: 'oq2', text: 'Phạm vi thời gian nào đúng với nhu cầu?', why: '',
      options: [{ id: 'o3', label: '24 tháng + nguồn nền tảng' }],
      allowFreeText: true, affects: ['cửa sổ'], required: true, blocking: true, answer: null,
    },
  ],
  actions: ['start', 'editScope'],
  note: '',
}

/**
 * Payload CHI TIẾT (`GET /api/agent/research/jobs/{id}`): `evidence/dossier/reviews/branches/coverage`
 * nằm ở CẤP TRÊN, KHÔNG lồng trong `job` — đúng như server thật (server.py `research_job_detail`).
 * Trước đây fixture lồng chúng vào `job`, che mất lỗi F2 (store chỉ đọc `payload.job`).
 */
function jobPayload(overrides: Record<string, unknown> = {}) {
  return {
    job: {
      research_id: 'R1', session_id: 's1', revision: 7, status: 'needs_user',
      phase: 'clarifying', background: false, usedSeconds: 754, budgetSeconds: 1800,
      scopeRevision: 1,
      state: {
        goal: 'Data augmentation bằng diffusion cho ảnh y tế', tier: 2, budgetSeconds: 1800,
        phase: 'clarifying', scope: scopePayload, prompts: [interviewPrompt],
        questions: [{ id: 'q1', text: 'Nhóm phương pháp dẫn đầu?', importance: 'high', status: 'unexplored' }],
        findings: [], blockedSources: [], methods: ['web_search', 'paper_citations'],
      },
      coverage: { counts: {}, unexplored: [], facets: [] },
    },
    scope: scopePayload,
    prompts: [interviewPrompt],
    questions: [],
    findings: [],
    blockedSources: [],
    evidence: [],
    dossier: null,
    reviews: [],
    ...overrides,
  }
}

/** Hàng của tuyến DANH SÁCH (`GET /research/jobs`) — mang sẵn evidence/dossier/reviews trên hàng. */
function jobRow(overrides: Record<string, unknown> = {}) {
  const { job } = jobPayload()
  return {
    ...job,
    origin: 'mode',
    remainingSeconds: Math.max(0, 1800 - job.usedSeconds),
    evidence: [], branches: [], dossier: null, reviews: [], facets: [],
    ...overrides,
  }
}

const listPayload = { jobs: [jobRow()] }

/** Router giả cho toàn bộ API research: ghi lại lời gọi, trả payload theo tuyến. */
function stubApi(overrides: { modeResponse?: () => Response } = {}) {
  const calls: { url: string; body: Record<string, unknown> | null }[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const target = String(url)
    const body = init?.body ? JSON.parse(String(init.body)) as Record<string, unknown> : null
    calls.push({ url: target, body })
    if (target.includes('/research-mode')) {
      if (overrides.modeResponse) return overrides.modeResponse()
      const on = Boolean(body?.on)
      if (!on && !body?.exitChoice) {
        return jsonResponse({
          error: 'Run đang chạy', code: 'RESEARCH_EXIT_CHOICE_REQUIRED',
          prompt: {
            promptId: 'rp-exit', researchId: 'R1', kind: 'exit-choice', revision: 3, status: 'open',
            questions: [{ id: 'exit', text: 'Bạn muốn run này thế nào?', allowFreeText: false, required: true, blocking: true,
              options: [{ id: 'pause', label: 'Tạm dừng run' }, { id: 'background', label: 'Tiếp tục chạy nền' }] }],
          },
        }, 409)
      }
      return jsonResponse({ mode: { on, activeRunId: 'R1', revision: 4 } })
    }
    if (target.includes('/research/jobs?sessionId=')) return jsonResponse(listPayload)
    if (target.includes('/research/jobs/R1')) return jsonResponse(jobPayload())
    if (target.includes('/research/prompts/')) return jsonResponse({ ok: true })
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}

beforeEach(() => {
  useResearchStore.setState({
    sessionId: 's1',
    mode: { ...RESEARCH_MODE_OFF, on: true, activeRunId: 'R1', revision: 3 },
    jobs: [],
    detail: null,
    detailId: '',
    loading: false,
    error: null,
    lastEventSeq: 0,
    exitChoice: null,
    statusCard: null,
    seenSeqBySession: {},
  })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  useUiStore.setState({ tabIntentTargets: {} })
  useHarnessChatStore.setState({ sessions: {} })
  vi.unstubAllGlobals()
})

describe('luồng chế độ Research', () => {
  it('chạy trọn đường: bật → trả lời phỏng vấn một lần → sửa thẻ → tắt Tạm dừng → bật lại → tắt chạy nền → chỉ báo nền → thẻ báo cáo', async () => {
    const api = stubApi()
    // 1. Dải trạng thái khi chế độ đang bật, kèm nhãn run + bước.
    const strip = render(<ResearchComposerStatus />)
    expect(strip.querySelector('[data-testid="research-mode-strip"]')).toBeTruthy()
    act(() => { strip.remove() })

    // 2. Trả lời HAI câu của phỏng vấn trong MỘT lần gọi.
    const interview = render(<ResearchPromptCard prompt={interviewPrompt as never} />)
    const submit = interview.querySelector<HTMLButtonElement>('[data-testid="research-prompt-submit"]')
    expect(submit?.disabled).toBe(true) // còn câu chặn chưa trả lời thì nút Bắt đầu khoá
    click(interview, 'button[aria-pressed="false"]')
    const optionButtons = interview.querySelectorAll('button[aria-pressed]')
    act(() => { (optionButtons[optionButtons.length - 1] as HTMLButtonElement).dispatchEvent(new MouseEvent('click', { bubbles: true })) })
    await act(async () => {
      interview.querySelector<HTMLButtonElement>('[data-testid="research-prompt-submit"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const answerCalls = api.calls.filter((call) => call.url.includes('/research/prompts/rp-interview/answer'))
    expect(answerCalls).toHaveLength(1)
    expect(answerCalls[0].body?.answers).toHaveLength(2)
    expect(answerCalls[0].body?.start).toBe(true)
    act(() => { interview.remove() })

    // 3. Sửa thẻ phạm vi: dòng NGÂN SÁCH đi qua `action:'budget'` (trần cứng thực thi), dòng ĐỘ SÂU
    //    đi qua `action:'scope'`; cả hai kèm `revision` đang thấy.
    const scope = render(<ScopeCard job={readJob(jobPayload().job)} scope={{ ...scopePayload } as never} prompt={interviewPrompt as never} />)
    const rowEdit = (row: string) => `[data-row="${row}"] [data-testid="research-scope-edit"]`
    const rowSave = (row: string) => `[data-row="${row}"] [data-testid="research-scope-save"]`
    const rowSaveClick = async (row: string) => {
      await act(async () => {
        scope.querySelector<HTMLButtonElement>(rowSave(row))!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
    }

    // 3a. Ngân sách: nhập số PHÚT ⇒ gửi `budgetSeconds` (giây) của trần cứng, KHÔNG phải nhãn hiển thị.
    click(scope, rowEdit('budget'))
    const budgetInput = scope.querySelector<HTMLInputElement>('[data-row="budget"] input[type="number"]')!
    expect(budgetInput.value).toBe('30') // 1800 giây trần cứng = 30 phút
    setFieldValue(budgetInput, '28')
    await rowSaveClick('budget')
    const budgetCalls = api.calls.filter((call) => call.body?.action === 'budget')
    expect(budgetCalls).toHaveLength(1)
    expect(budgetCalls[0].body?.budgetSeconds).toBe(28 * 60)

    // 3b. Độ sâu: chọn trong ô chọn ⇒ `scope.depth` là giá trị máy, không phải chuỗi nhãn.
    click(scope, rowEdit('depth'))
    const depthSelect = scope.querySelectorAll<HTMLSelectElement>('[data-row="depth"] select')[1]
    setFieldValue(depthSelect, 'deep')
    await rowSaveClick('depth')
    const patchCalls = api.calls.filter((call) => call.body?.action === 'scope')
    expect(patchCalls).toHaveLength(1)
    expect(patchCalls[0].body?.revision).toBe(1)
    expect((patchCalls[0].body?.scope as Record<string, unknown>)?.depth).toBe('deep')
    act(() => { scope.remove() })

    // 4. Tắt chế độ, run còn chạy ⇒ server đòi chọn; người dùng chọn "Tạm dừng".
    const toggle = render(<ResearchToggle />)
    await act(async () => {
      toggle.querySelector<HTMLButtonElement>('[data-testid="composer-research-toggle"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const exit = render(<ResearchComposerStatus />)
    expect(exit.querySelector('[data-testid="research-exit-prompt"]')).toBeTruthy()
    expect(useResearchStore.getState().mode.on).toBe(true) // mode chưa đổi khi chưa chọn
    await act(async () => {
      exit.querySelector<HTMLButtonElement>('[data-testid="research-exit-pause"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const pauseCall = api.calls.find((call) => call.body?.exitChoice === 'pause')
    expect(pauseCall).toBeTruthy()
    expect(useResearchStore.getState().mode.on).toBe(false)
    act(() => { exit.remove(); toggle.remove() })

    // 5. Bật lại rồi tắt chọn "Tiếp tục chạy nền".
    await act(async () => { await useResearchStore.getState().setMode(true, 'toggle') })
    expect(useResearchStore.getState().mode.on).toBe(true)
    await act(async () => { await useResearchStore.getState().setMode(false, 'toggle') })
    expect(useResearchStore.getState().exitChoice).not.toBeNull()
    await act(async () => { await useResearchStore.getState().resolveExit('background') })
    expect(api.calls.some((call) => call.body?.exitChoice === 'background')).toBe(true)

    // 6. Run chạy nền: chỉ báo nền hiện trong ô soạn tin.
    useResearchStore.setState({
      jobs: [{
        researchId: 'R1', sessionId: 's1', revision: 8, status: 'researching', phase: 'searching',
        origin: 'mode', background: true, scopeRevision: 2, usedSeconds: 900, remainingSeconds: 900,
        budgetSeconds: 1800, tier: 2, goal: 'g', output: '', methods: [], questions: [],
        findings: [], blockedSources: [], branches: [], evidence: [], dossier: null, reviews: [],
        coverage: { counts: {}, unexplored: [], facets: [] }, prompts: [], scope: null,
      }],
    })
    const background = render(<ResearchComposerStatus />)
    expect(background.querySelector('[data-testid="research-background-strip"]')).toBeTruthy()
    act(() => { background.remove() })

    // 7. Run xong ⇒ thẻ báo cáo trong hội thoại.
    const doneJob = {
      ...jobPayload().job,
      status: 'completed',
      state: { ...jobPayload().job.state, background: true, prompts: [] },
      prompts: [],
      dossier: { relative_path: '.research/diffusion-med-imaging-20260925-0942/v3-8f21c4.md', version: 3, gate: 'pass', critique: 'accept-with-conditions' },
      reviews: [{ version: 1, mode: 'critique', verdict: 'revise' }, { version: 2, mode: 'critique', verdict: 'accept-with-conditions' }],
      evidence: [{ rowId: 'S12', claim: 'Bước lọc mẫu quan trọng hơn kích thước mô hình', url: 'https://x', accessLevel: 'fulltext', relation: 'supports', confidence: 'high' }],
    }
    useResearchStore.setState({ jobs: [readJob(doneJob)] })
    const cards = render(<ResearchConversationCards suggest={null} />)
    const report = cards.querySelector('[data-testid="research-report-card"]')
    expect(report).toBeTruthy()
    expect(cards.textContent).toContain('.research/diffusion-med-imaging-20260925-0942/v3-8f21c4.md')
    expect(report?.getAttribute('data-background')).toBe('true')
    act(() => { cards.remove() })
  })

  it('mỗi `kind` của research_prompt vẽ được; exit-choice chỉ có hai lựa chọn, không mặc định', () => {
    for (const kind of ['interview', 'scope-change', 'budget', 'out-of-scope'] as const) {
      const host = render(<ResearchPromptCard prompt={{ ...interviewPrompt, kind } as never} />)
      expect(host.querySelector(`[data-testid="research-prompt-card"][data-kind="${kind}"]`)).toBeTruthy()
      act(() => { host.remove() })
    }
    // F7: `exit-choice` chỉ còn MỘT chỗ vẽ — `ResearchComposerStatus.ExitPrompt` (qua `exitChoice`).
    const exitPrompt = {
      promptId: 'rp-exit', researchId: 'R1', kind: 'exit-choice', revision: 3, status: 'open', blocking: false,
      createdAt: '', actions: ['chooseExit'], note: '', questions: [{
        id: 'exit', text: 'Bạn muốn run này thế nào?', why: '', allowFreeText: false, affects: [],
        required: true, blocking: true, answer: null,
        options: [{ id: 'pause', label: 'Tạm dừng run', cost: null }, { id: 'background', label: 'Tiếp tục chạy nền', cost: null }],
      }],
    }
    useResearchStore.setState({
      exitChoice: { code: 'RESEARCH_EXIT_CHOICE_REQUIRED', message: '', prompt: exitPrompt as never },
    })
    const exit = render(<ResearchComposerStatus />)
    expect(exit.querySelector('[data-testid="research-exit-prompt"]')).toBeTruthy()
    // Không mặc định: cả hai lựa chọn đều hiện và không nút nào ở trạng thái đã chọn.
    const pauseButton = exit.querySelector('[data-testid="research-exit-pause"]')
    const backgroundButton = exit.querySelector('[data-testid="research-exit-background"]')
    expect(pauseButton).toBeTruthy()
    expect(backgroundButton).toBeTruthy()
    expect(pauseButton?.getAttribute('aria-pressed')).toBeNull()
    expect(backgroundButton?.getAttribute('aria-pressed')).toBeNull()
    expect(exit.textContent).toContain('Pause the run')
    expect(exit.textContent).toContain('Keep running in background')
    act(() => { exit.remove() })

    // Server chỉ mời `pause` (background bị tắt) ⇒ KHÔNG hiện nút chạy nền.
    useResearchStore.setState({
      exitChoice: {
        code: 'RESEARCH_EXIT_CHOICE_REQUIRED', message: '',
        prompt: { ...exitPrompt, questions: [{ ...exitPrompt.questions[0], options: [{ id: 'pause', label: 'Tạm dừng run', cost: null }] }] } as never,
      },
    })
    const paused = render(<ResearchComposerStatus />)
    expect(paused.querySelector('[data-testid="research-exit-pause"]')).toBeTruthy()
    expect(paused.querySelector('[data-testid="research-exit-background"]')).toBeNull()
    act(() => { paused.remove() })
  })


  it('tab Research đọc từ store và KHÔNG tự hỏi mạng (đã bỏ vòng 5000 ms)', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(jobPayload()))
    vi.stubGlobal('fetch', fetchMock)
    useResearchStore.setState({ jobs: [readJob(jobPayload().job)] })
    const host = render(<ResearchPanel />)
    // Sáu mục của `research-panel.html`.
    for (const tab of ['scope', 'plan', 'sources', 'claims', 'review', 'report']) {
      expect(host.querySelector(`[data-testid="research-tab-${tab}"]`)).toBeTruthy()
    }
    // Chờ quá một "chu kỳ" của vòng hỏi cũ: nếu còn `setInterval(…, 5000)` thì đã có lời gọi.
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 150)) })
    expect(fetchMock).not.toHaveBeenCalled()
    act(() => { host.remove() })
  })

  it('F4: đích `researchId` mở tab Research chọn ĐÚNG run đó, không phải run đang xem', async () => {
    const fetchMock = vi.fn(async (url: string) => {
      if (String(url).includes('/research/jobs/R2')) {
        return jsonResponse(jobPayload({ job: { ...jobPayload().job, research_id: 'R2' } }))
      }
      return jsonResponse(jobPayload())
    })
    vi.stubGlobal('fetch', fetchMock)
    useResearchStore.setState({
      jobs: [
        readJob({ ...jobPayload().job, research_id: 'R1' }),
        readJob({ ...jobPayload().job, research_id: 'R2' }),
      ],
      detailId: 'R1',
    })
    useUiStore.setState({ tabIntentTargets: { research: { researchId: 'R2' } } })
    const host = render(<ResearchPanel />)
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)) })
    expect(fetchMock.mock.calls.some((call) => String(call[0]).includes('/research/jobs/R2'))).toBe(true)
    expect(useResearchStore.getState().detailId).toBe('R2')
    act(() => { host.remove() })
  })

  it('run chạy nền hiện dòng riêng ở tab Research khi mode đã tắt', async () => {
    useResearchStore.setState({
      sessionId: 's1',
      mode: { ...RESEARCH_MODE_OFF, on: false, activeRunId: '' },
      jobs: [readJob({ ...jobPayload().job, status: 'researching', phase: 'searching', background: true })],
    })
    const host = render(<ResearchPanel />)
    expect(host.querySelector('[data-testid="research-background-line"]')).toBeTruthy()
    act(() => { host.remove() })
  })

  it('dòng thời gian đổi theo pha của run', () => {
    const searching = render(<RunTimeline job={readJob({ ...jobPayload().job, status: 'researching', phase: 'searching' })} />)
    const active = searching.querySelector('[data-step="search"]')
    expect(active?.getAttribute('data-active')).toBe('true')
    act(() => { searching.remove() })
    const done = render(<RunTimeline job={readJob({ ...jobPayload().job, status: 'completed', phase: 'completed' })} />)
    expect(done.querySelector('[data-step="done"]')?.getAttribute('data-active')).toBe('true')
    act(() => { done.remove() })
  })
})

/** Thẻ báo cáo hoàn tất kèm hồ sơ — dùng cho D-1/D-5. */
function completedJob() {
  return readJob({
    ...jobPayload().job,
    status: 'completed',
    dossier: { relative_path: '.research/x/v3-abc.md', version: 3, gate: 'pass', critique: '' },
  })
}

describe('sửa lỗi vòng kiểm thử trình duyệt (D-1, D-3, D-4, D-5)', () => {
  it('D-1: nút "Cập nhật" của thẻ báo cáo có `data-testid`', () => {
    const host = render(<ResearchReportCard job={completedJob()} />)
    expect(host.querySelector('[data-testid="research-report-update"]')).toBeTruthy()
    act(() => { host.remove() })
  })

  it('D-3: run `paused` hiện ĐÚNG nhãn trạng thái + nút Tiếp tục ở panel và thẻ phạm vi', async () => {
    const api = stubApi()
    const paused = readJob({ ...jobPayload().job, status: 'paused', revision: 7 })
    useResearchStore.setState({ jobs: [paused], mode: { ...RESEARCH_MODE_OFF, on: true, activeRunId: 'R1' } })

    const panel = render(<ResearchPanel />)
    const badge = panel.querySelector('[data-testid="research-status-badge"]')
    expect(badge?.getAttribute('data-status')).toBe('paused')
    expect(badge?.textContent).toContain('Paused')
    // Tạm dừng rồi thì nút "Tạm dừng" vô nghĩa — chỉ còn "Tiếp tục" và "Hủy".
    expect(panel.querySelector('[data-testid="research-panel-pause"]')).toBeNull()
    await act(async () => {
      panel.querySelector<HTMLButtonElement>('[data-testid="research-panel-resume"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const panelResume = api.calls.find((call) => call.body?.action === 'resume')
    expect(panelResume?.body?.revision).toBe(7)
    act(() => { panel.remove() })

    // Thẻ phạm vi: cùng nhãn, kèm dòng hỏi "Tiếp tục run X?" và nút resume gửi cùng patch.
    const scopeHost = render(<ScopeCard job={paused} scope={{ ...scopePayload } as never} />)
    expect(scopeHost.querySelector('[data-testid="research-scope-status-badge"]')?.getAttribute('data-status')).toBe('paused')
    expect(scopeHost.querySelector('[data-testid="research-scope-resume-ask"]')?.textContent).toContain('Run R-R1 is paused')
    expect(scopeHost.querySelector('[data-testid="research-run-pause"]')).toBeNull()
    await act(async () => {
      scopeHost.querySelector<HTMLButtonElement>('[data-testid="research-scope-resume"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(api.calls.filter((call) => call.body?.action === 'resume')).toHaveLength(2)
    act(() => { scopeHost.remove() })
  })

  it('D-4: thẻ `/research status` vẽ `message` và nút × gỡ nó', () => {
    useResearchStore.setState({
      sessionId: 's1',
      mode: { ...RESEARCH_MODE_OFF, on: false },
      statusCard: {
        researchId: 'R1', message: 'R1 · researching · pha searching', status: 'researching',
        phase: 'searching', background: false, seq: 7,
      },
    })
    const host = render(<ResearchConversationCards suggest={null} />)
    const card = host.querySelector('[data-testid="research-status-card"]')
    expect(card).toBeTruthy()
    expect(card?.textContent).toContain('pha searching')
    expect(card?.textContent).toContain('Search')
    click(host, '[data-testid="research-status-card-dismiss"]')
    expect(host.querySelector('[data-testid="research-status-card"]')).toBeNull()
    expect(useResearchStore.getState().statusCard).toBeNull()
    act(() => { host.remove() })
  })

  it('D-5: "Dùng cho plan" tắt mode rồi gửi lượt main đúng nội dung', async () => {
    // Run đã xong ⇒ không có lời hỏi thoát, PUT trả về ngay.
    const api = stubApi({ modeResponse: () => jsonResponse({ mode: { on: false, activeRunId: 'R1', revision: 5 } }) })
    useHarnessChatStore.setState({ sessions: { s1: { id: 'sid-1', status: 'idle', events: [], error: null } } })
    useResearchStore.setState({ sessionId: 's1', mode: { ...RESEARCH_MODE_OFF, on: true, activeRunId: 'R1' } })

    const host = render(<ResearchReportCard job={completedJob()} />)
    const button = host.querySelector<HTMLButtonElement>('[data-testid="research-report-use-for-plan"]')!
    expect(button.disabled).toBe(false)
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const modeCall = api.calls.find((call) => call.url.includes('/research-mode'))
    expect(modeCall?.body).toMatchObject({ on: false })
    const turnCall = api.calls.find((call) => call.url.includes('/turns'))
    expect(turnCall?.body?.prompt).toContain('R1')
    expect(turnCall?.body?.prompt).toContain('v3')
    act(() => { host.remove() })
  })

  it('D-5: server đòi chọn số phận run (409) ⇒ KHÔNG gửi lượt plan', async () => {
    // Mặc định của `stubApi`: tắt mode khi chưa có `exitChoice` ⇒ 409 kèm lời hỏi thoát.
    const api = stubApi()
    useHarnessChatStore.setState({ sessions: { s1: { id: 'sid-1', status: 'idle', events: [], error: null } } })
    useResearchStore.setState({ sessionId: 's1', mode: { ...RESEARCH_MODE_OFF, on: true, activeRunId: 'R1' } })

    const host = render(<ResearchReportCard job={completedJob()} />)
    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-testid="research-report-use-for-plan"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(api.calls.some((call) => call.url.includes('/research-mode'))).toBe(true)
    expect(api.calls.some((call) => call.url.includes('/turns'))).toBe(false)
    expect(useResearchStore.getState().exitChoice).not.toBeNull()
    act(() => { host.remove() })
  })
})

describe('sửa lỗi vòng 2 (D-3, D-5, exit-choice, thứ tự gọi)', () => {
  it('D-3: dòng thời gian của run `paused` hiện ĐÚNG nhãn + nút Tiếp tục, gửi PATCH `resume`', async () => {
    const api = stubApi()
    const paused = readJob({ ...jobPayload().job, status: 'paused', revision: 7 })
    const host = render(<RunTimeline job={paused} />)
    // Bước đang chạy KHÔNG được vẽ là "đang chạy" khi run đã tạm dừng.
    const activeStep = host.querySelector('[data-step][data-active="true"]')
    expect(activeStep?.textContent).toContain('Paused')
    // "Tạm dừng" vô nghĩa với run đã tạm dừng — chỉ còn "Tiếp tục" và "Hủy".
    expect(host.querySelector('[data-testid="research-timeline-pause"]')).toBeNull()
    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-testid="research-timeline-resume"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const resume = api.calls.find((call) => call.body?.action === 'resume')
    expect(resume?.body?.revision).toBe(7)
    expect(host.querySelector('[data-testid="research-timeline-cancel"]')).toBeTruthy()
    act(() => { host.remove() })
  })

  it('D-3: thẻ báo cáo của run `partial` hiện nhãn "Partial" (không phải DONE)', () => {
    const partial = readJob({
      ...jobPayload().job,
      status: 'partial',
      dossier: { relative_path: '.research/x/v3-abc.md', version: 3, gate: 'pass', critique: '' },
    })
    const host = render(<ResearchReportCard job={partial} />)
    const badge = host.querySelector('[data-testid="research-report-status"]')
    expect(badge?.getAttribute('data-status')).toBe('partial')
    expect(badge?.textContent).toContain('Partial')
    expect(host.querySelector('[data-testid="research-report-status"]')?.textContent).not.toContain('DONE')
    act(() => { host.remove() })
  })

  it('D-5: phiên bản hồ sơ đã bàn giao ⇒ nút khoá, bấm KHÔNG gửi PUT lẫn POST', async () => {
    const api = stubApi()
    useHarnessChatStore.setState({ sessions: { s1: { id: 'sid-1', status: 'idle', events: [], error: null } } })
    useResearchStore.setState({
      sessionId: 's1',
      mode: { ...RESEARCH_MODE_OFF, on: true, activeRunId: 'R1', handoffDeliveredVersion: { R1: '3' } },
    })
    const host = render(<ResearchReportCard job={completedJob()} />)
    const button = host.querySelector<HTMLButtonElement>('[data-testid="research-report-use-for-plan"]')!
    expect(button.disabled).toBe(true)
    expect(button.getAttribute('data-handoff')).toBe('done')
    expect(button.textContent).toContain('Handed off to plan')
    await act(async () => {
      button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(api.calls.some((call) => call.url.includes('/research-mode'))).toBe(false)
    expect(api.calls.some((call) => call.url.includes('/turns'))).toBe(false)
    act(() => { host.remove() })
  })

  it('D-5: bấm "Dùng cho plan" gửi PUT research-mode TRƯỚC rồi mới POST /turns', async () => {
    const api = stubApi({ modeResponse: () => jsonResponse({ mode: { on: false, activeRunId: 'R1', revision: 5 } }) })
    useHarnessChatStore.setState({ sessions: { s1: { id: 'sid-1', status: 'idle', events: [], error: null } } })
    useResearchStore.setState({ sessionId: 's1', mode: { ...RESEARCH_MODE_OFF, on: true, activeRunId: 'R1' } })

    const host = render(<ResearchReportCard job={completedJob()} />)
    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-testid="research-report-use-for-plan"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const modeIndex = api.calls.findIndex((call) => call.url.includes('/research-mode'))
    const turnIndex = api.calls.findIndex((call) => call.url.includes('/turns'))
    expect(modeIndex).toBeGreaterThanOrEqual(0)
    expect(turnIndex).toBeGreaterThan(modeIndex)
    act(() => { host.remove() })
  })

  it('exit-choice: đường thoát hiện dòng nhắc thay vì im lặng, và không gửi lượt', async () => {
    // Mặc định `stubApi`: tắt mode ⇒ 409 kèm lời hỏi thoát.
    const api = stubApi()
    useHarnessChatStore.setState({ sessions: { s1: { id: 'sid-1', status: 'idle', events: [], error: null } } })
    useResearchStore.setState({ sessionId: 's1', mode: { ...RESEARCH_MODE_OFF, on: true, activeRunId: 'R1' } })

    const host = render(<ResearchReportCard job={completedJob()} />)
    expect(host.querySelector('[data-testid="research-use-for-plan-needs-choice"]')).toBeNull()
    await act(async () => {
      host.querySelector<HTMLButtonElement>('[data-testid="research-report-use-for-plan"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const hint = host.querySelector('[data-testid="research-use-for-plan-needs-choice"]')
    expect(hint).toBeTruthy()
    expect(hint?.textContent).toContain('Choose what happens to the running run')
    expect(api.calls.some((call) => call.url.includes('/turns'))).toBe(false)
    act(() => { host.remove() })
  })
})
