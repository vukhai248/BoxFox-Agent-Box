/**
 * Bài kiểm luồng đầy đủ của chế độ `/design` (P1):
 *
 *   bật mode → run mở ra và dải trạng thái hiện đúng run + bước → trả lời phỏng vấn nhiều câu trong
 *   MỘT lần gọi → thẻ brief + danh sách chạm, duyệt cả danh sách bằng `revision` đang thấy → tắt mode
 *   lúc run còn chạy, chọn "Tạm dừng" (không có lựa chọn mặc định) → dòng thời gian đổi theo giai đoạn.
 *
 * Không dùng @testing-library (dự án không có): raw `createRoot` + `act`, đúng khuôn
 * `ResearchFlow.test.tsx` và `ChatInputBar.test.tsx`.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../../i18n'
import { useDesignStore, selectActiveRun, parseCanvasOp } from '../../../store/designStore'
import { useHarnessChatStore } from '../../../store/harnessChatStore'
import { useUiStore } from '../../../store/uiStore'
import { DESIGN_MODE_OFF, readRun, readBatch, readPrompt, stepForPhase, type DesignBatch } from '../../../lib/designMode'
import { DesignBatchDiffCard } from './DesignBatchDiffCard'
import { DesignBriefCard } from './DesignBriefCard'
import { DesignCanvasPanel } from '../DesignCanvasPanel'
import { DesignComposerStatus } from './DesignComposerStatus'
import { DesignConversationCards } from './DesignConversationCards'
import { DesignExitChoiceCard } from './DesignExitChoiceCard'
import { DesignHandoffCard } from './DesignHandoffCard'
import { DesignOutOfScopeCard } from './DesignOutOfScopeCard'
import { DesignPanel } from './DesignPanel'
import { DesignPromptCard } from './DesignPromptCard'
import { DesignRunTimeline } from './DesignRunTimeline'
import { DesignToggle } from './DesignToggle'

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

/** Đặt giá trị cho input theo cách React nhìn thấy (native setter + sự kiện). */
function setFieldValue(node: HTMLInputElement, value: string): void {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(node, value)
  act(() => {
    node.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

const DESIGN_ID = 'd-chat-panel-9f3a1c'

const interviewPrompt = {
  promptId: 'dp-interview',
  designId: DESIGN_ID,
  kind: 'interview',
  status: 'open',
  revision: 2,
  createdAt: '',
  note: '',
  actions: ['start'],
  questions: [
    {
      id: 'dq-screen',
      text: 'Màn hình nào cần thiết kế?',
      why: 'đổi hướng phác thảo',
      options: [{ id: 'o1', label: 'Màn hình chat' }, { id: 'o2', label: 'Bảng điều khiển' }],
      allowFreeText: true,
      required: true,
      answer: null,
    },
    {
      id: 'dq-platform',
      text: 'Chạy trên nền tảng nào?',
      why: '',
      options: [{ id: 'o3', label: 'Web' }],
      allowFreeText: true,
      required: true,
      answer: null,
    },
  ],
}

const touchList = {
  revision: 3,
  designId: DESIGN_ID,
  branch: { name: 'design/chat-panel-20260927-0900', base: 'abc1234', status: 'proposed' },
  items: [
    { id: 't1', kind: 'new', path: 'src/ui/ChatPanel.tsx', reason: 'màn hình chat mới', risk: 'low', status: 'proposed', sha256: null },
  ],
  forbidden: ['.env'],
  approvedAt: null,
}

/** Hàng run như tuyến danh sách trả về (đã camelCase). */
function runRow(overrides: Record<string, unknown> = {}) {
  return {
    designId: DESIGN_ID,
    sessionId: 's1',
    status: 'scoping',
    phase: 'interviewing',
    origin: 'mode',
    background: false,
    revision: 7,
    goal: 'thiết kế màn hình chat',
    touchListRevision: 3,
    touchList,
    prompts: [interviewPrompt],
    ...overrides,
  }
}

/** Router giả cho toàn bộ API design: ghi lại lời gọi, trả payload theo tuyến. */
function stubApi(overrides: { modeResponse?: () => Response } = {}) {
  const calls: { url: string; body: Record<string, unknown> | null; method: string }[] = []
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const target = String(url)
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
    calls.push({ url: target, body, method: init?.method ?? 'GET' })
    if (target.includes('/design-mode')) {
      if (overrides.modeResponse) return overrides.modeResponse()
      const on = Boolean(body?.on)
      // Tắt mode lúc run còn chạy mà CHƯA chọn ⇒ 409 kèm lời hỏi `exit-choice` (không mặc định).
      if (!on && !body?.exitChoice) {
        return jsonResponse(
          {
            error: 'Run đang chạy',
            code: 'DESIGN_EXIT_CHOICE_REQUIRED',
            prompt: {
              promptId: 'dp-exit',
              designId: DESIGN_ID,
              kind: 'exit-choice',
              status: 'open',
              revision: 4,
              questions: [
                {
                  id: 'exit',
                  text: 'Bạn muốn run này thế nào?',
                  allowFreeText: false,
                  required: true,
                  options: [
                    { id: 'pause', label: 'Tạm dừng run' },
                    { id: 'background', label: 'Tiếp tục chạy nền' },
                  ],
                },
              ],
            },
          },
          409,
        )
      }
      return jsonResponse({ mode: { on, activeRunId: DESIGN_ID, revision: 5 } })
    }
    if (target.includes('/design/runs?sessionId=')) return jsonResponse({ runs: [runRow()] })
    if (target.includes('/touch-list/approve')) return jsonResponse({ ok: true })
    if (target.includes('/design/prompts/') && target.includes('/answer')) return jsonResponse({ ok: true })
    if (target.includes('/design/runs/')) {
      return jsonResponse({ job: runRow(), prompts: [interviewPrompt], touchList, brief: { goal: 'thiết kế màn hình chat', screen: 'màn hình chat' } })
    }
    return jsonResponse({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return { fetchMock, calls }
}

beforeEach(() => {
  useDesignStore.setState({
    sessionId: 's1',
    mode: { ...DESIGN_MODE_OFF, on: true, activeRunId: DESIGN_ID, revision: 4 },
    runs: [],
    activeRunId: DESIGN_ID,
    scenes: {},
    sceneActor: {},
    sceneVersion: 0,
    prompts: [],
    rejectedOps: 0,
    brief: {},
    exitChoice: null,
    reports: {},
    notices: [],
    pendingTurn: '',
    loading: false,
    error: null,
    lastEventSeq: 0,
  })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.unstubAllGlobals()
})

describe('luồng chế độ Design', () => {
  it('chạy trọn đường: dải trạng thái → trả lời phỏng vấn một lần → duyệt danh sách chạm → tắt chọn Tạm dừng', async () => {
    const api = stubApi()

    // 1. Nút Design: đang bật ⇒ nhãn "Tắt chế độ Design".
    const toggle = render(<DesignToggle />)
    const button = toggle.querySelector('[data-testid="composer-design-toggle"]')
    expect(button).toBeTruthy()
    expect(button?.getAttribute('aria-pressed')).toBe('true')
    expect(button?.textContent).toContain('Design')
    act(() => { toggle.remove() })

    // 2. Run mở ra từ sự kiện phiên ⇒ dải trạng thái hiện nhãn run + bước (không tự bịa).
    act(() => {
      useDesignStore.getState().applyEvent({
        seq: 11,
      type: 'design_run',
        data: { designId: DESIGN_ID, status: 'scoping', phase: 'interviewing', origin: 'mode', revision: 1 },
      })
    })
    const strip = render(<DesignComposerStatus />)
    const stripNode = strip.querySelector('[data-testid="design-mode-strip"]')
    expect(stripNode).toBeTruthy()
    // I18nProvider mặc định tiếng Anh — nhãn bước lấy từ `design.stepClarify`, không hard-code.
    expect(stripNode?.textContent).toContain('Clarify the request')
    expect(stripNode?.textContent).toContain('D-F3A1C')
    act(() => { strip.remove() })

    // 3. Trả lời HAI câu chặn trong MỘT lần gọi; nút gửi khoá khi còn câu chưa trả lời.
    const interview = render(<DesignPromptCard prompt={{ ...interviewPrompt, questions: interviewPrompt.questions.map((q) => ({ ...q, why: q.why, answer: null })) } as never} />)
    expect(interview.querySelector('[data-testid="design-prompt-card"]')).toBeTruthy()
    expect(interview.querySelector<HTMLButtonElement>('[data-testid="design-prompt-submit"]')?.disabled).toBe(true)
    click(interview, '[data-question="dq-screen"] button[data-option="o1"]')
    click(interview, '[data-question="dq-platform"] button[data-option="o3"]')
    expect(interview.querySelector<HTMLButtonElement>('[data-testid="design-prompt-submit"]')?.disabled).toBe(false)
    await act(async () => {
      interview.querySelector<HTMLButtonElement>('[data-testid="design-prompt-submit"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const answerCalls = api.calls.filter((call) => call.url.includes('/design/prompts/dp-interview/answer'))
    expect(answerCalls).toHaveLength(1)
    expect(answerCalls[0].body?.answers).toHaveLength(2)
    expect(answerCalls[0].body?.start).toBe(false)
    act(() => { interview.remove() })

    // 3b. Trả lời tự do cũng tạo câu trả lời, không cần chọn lựa chọn.
    const freeText = render(<DesignPromptCard prompt={{ ...interviewPrompt, questions: [interviewPrompt.questions[0]] } as never} />)
    setFieldValue(freeText.querySelector<HTMLInputElement>('[data-answer-input="dq-screen"]')!, 'màn hình chat mới')
    await act(async () => {
      freeText.querySelector<HTMLButtonElement>('[data-testid="design-prompt-start"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const startCall = api.calls.filter((call) => call.url.includes('/design/prompts/dp-interview/answer')).at(-1)
    expect(startCall?.body?.start).toBe(true)
    expect((startCall?.body?.answers as { text?: string }[])[0].text).toBe('màn hình chat mới')
    act(() => { freeText.remove() })

    // 4. Thẻ brief + danh sách chạm; duyệt gửi ĐÚNG `revision` đang thấy (khoá lạc quan).
    act(() => { useDesignStore.setState({ runs: [readRun(runRow())!] }) })
    const brief = render(<DesignBriefCard run={readRun(runRow())!} brief={{ screen: 'màn hình chat' }} />)
    expect(brief.querySelector('[data-testid="design-brief-card"]')?.getAttribute('data-approved')).toBe('false')
    expect(brief.querySelector('[data-testid="design-touch-list-waiting"]')).toBeTruthy()
    expect(brief.textContent).toContain('src/ui/ChatPanel.tsx')
    await act(async () => {
      brief.querySelector<HTMLButtonElement>('[data-testid="design-touch-list-approve"]')!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const approveCall = api.calls.find((call) => call.url.includes('/touch-list/approve'))
    expect(approveCall?.body?.revision).toBe(3)
    expect(approveCall?.method).toBe('POST')
    act(() => { brief.remove() })

    // 5. Tắt mode lúc run còn chạy ⇒ server đòi chọn; KHÔNG có lựa chọn mặc định nào được chọn sẵn.
    await act(async () => {
      await useDesignStore.getState().setMode(false, 'toggle')
    })
    expect(useDesignStore.getState().mode.on).toBe(true) // chưa chọn thì mode chưa đổi
    const exit = render(<DesignComposerStatus />)
    expect(exit.querySelector('[data-testid="design-exit-choice"]')).toBeTruthy()
    const pause = exit.querySelector('[data-testid="design-exit-pause"]')
    const background = exit.querySelector('[data-testid="design-exit-background"]')
    expect(pause).toBeTruthy()
    expect(background).toBeTruthy()
    expect(pause?.getAttribute('aria-pressed')).toBeNull()
    expect(background?.getAttribute('aria-pressed')).toBeNull()
    await act(async () => {
      pause!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const exitCall = api.calls.find((call) => call.body?.exitChoice === 'pause')
    expect(exitCall).toBeTruthy()
    expect(useDesignStore.getState().exitChoice).toBeNull()
    expect(useDesignStore.getState().mode.on).toBe(false)
    act(() => { exit.remove() })
  })

  it('exit-choice: server chỉ mời `pause` thì KHÔNG hiện nút chạy nền; tắt bằng nút Tắt cũng đòi chọn', async () => {
    stubApi({
      modeResponse: () =>
        jsonResponse(
          {
            error: 'Run đang chạy',
            code: 'DESIGN_EXIT_CHOICE_REQUIRED',
            prompt: {
              promptId: 'dp-exit',
              designId: DESIGN_ID,
              kind: 'exit-choice',
              status: 'open',
              revision: 4,
              questions: [
                {
                  id: 'exit',
                  text: 'Bạn muốn run này thế nào?',
                  allowFreeText: false,
                  required: true,
                  options: [{ id: 'pause', label: 'Tạm dừng run' }],
                },
              ],
            },
          },
          409,
        ),
    })
    const strip = render(<DesignComposerStatus />)
    await act(async () => {
      click(strip, '[data-testid="design-mode-strip-off"]')
      await Promise.resolve()
    })
    expect(useDesignStore.getState().exitChoice).not.toBeNull()
    // Render lại sau khi lời hỏi đã về: chỉ nút `pause`.
    await act(async () => {})
    expect(useDesignStore.getState().exitChoice?.prompt.questions[0].options).toHaveLength(1)
    act(() => { strip.remove() })
  })

  it('dòng thời gian đổi theo giai đoạn; run đã đóng đứng ở bước bàn giao', () => {
    const interviewing = render(<DesignRunTimeline run={readRun(runRow())!} />)
    expect(interviewing.querySelector('[data-testid="design-run-timeline"]')?.getAttribute('data-phase')).toBe('interviewing')
    expect(interviewing.querySelector('[data-step="clarify"]')?.getAttribute('data-active')).toBe('true')
    act(() => { interviewing.remove() })

    const drawing = render(<DesignRunTimeline run={readRun(runRow({ status: 'designing', phase: 'drawing', touchList: null }))!} />)
    expect(drawing.querySelector('[data-step="draw"]')?.getAttribute('data-active')).toBe('true')
    act(() => { drawing.remove() })

    const done = render(<DesignRunTimeline run={readRun(runRow({ status: 'completed', phase: 'done' }))!} />)
    expect(done.querySelector('[data-step="handoff"]')?.getAttribute('data-active')).toBe('true')
    act(() => { done.remove() })
  })

  it('thẻ trong hội thoại: lời hỏi trước, brief + dòng thời gian sau; tắt mode thì không vẽ gì', () => {
    act(() => {
      useDesignStore.setState({ runs: [readRun(runRow())!], prompts: [readRun(runRow())!.prompts[0]], brief: { screen: 'chat' } })
    })
    const host = render(<DesignConversationCards />)
    expect(host.querySelector('[data-testid="design-prompt-card"]')).toBeTruthy()
    expect(host.querySelector('[data-testid="design-brief-card"]')).toBeTruthy()
    expect(host.querySelector('[data-testid="design-run-timeline"]')).toBeTruthy()
    act(() => { host.remove() })

    act(() => {
      useDesignStore.setState({
        mode: { ...DESIGN_MODE_OFF, on: false },
        notices: [{ designId: DESIGN_ID, kind: 'needs-user', seq: 61 }],
      })
    })
    const off = render(<DesignConversationCards />)
    // Thẻ của run đang chạy KHÔNG vẽ khi chế độ tắt…
    expect(off.querySelector('[data-testid="design-brief-card"]')).toBeNull()
    // …nhưng thông báo nền VẪN vẽ: đó chính là lúc backend phát nó (run nền đã xong).
    expect(off.querySelector('[data-testid="design-notice-card"]')).toBeTruthy()
    act(() => { off.remove() })
  })

  it('thiếu cấu hình `designMode` ⇒ chế độ tắt: dải và nút đều không vẽ', () => {
    act(() => {
      useDesignStore.setState({
        mode: DESIGN_MODE_OFF,
        runs: [readRun(runRow())!],
        exitChoice: null,
        notices: [{ designId: DESIGN_ID, kind: 'blocked', seq: 62 }],
      })
    })
    const strip = render(<DesignComposerStatus />)
    expect(strip.querySelector('[data-testid="design-mode-strip"]')).toBeNull()
    const cards = render(<DesignConversationCards />)
    expect(cards.querySelector('[data-testid="design-brief-card"]')).toBeNull()
    // Thông báo nền không phụ thuộc công tắc chế độ.
    expect(cards.querySelector('[data-testid="design-notice-card"]')).toBeTruthy()
    const toggle = render(<DesignToggle />)
    expect(toggle.querySelector('[data-testid="composer-design-toggle"]')?.getAttribute('aria-pressed')).toBe('false')
    act(() => { strip.remove(); cards.remove(); toggle.remove() })
  })

  it('P2 để lại dấu vết đúng: op canvas hợp lệ được nhận, op sai bị đếm chứ không vẽ', () => {
    expect(parseCanvasOp({ type: 'CREATE_NODE', node: { id: 'n1' } })).not.toBeNull()
    expect(parseCanvasOp({ type: 'NOPE' })).toBeNull()
    act(() => {
      useDesignStore.getState().applyEvent({
        seq: 12,
      type: 'design_canvas',
        data: {
          designId: DESIGN_ID,
          ops: [
            { type: 'CREATE_NODE', node: { id: 'n1', kind: 'ui-mockup', x: 0, y: 0, width: 10, height: 10, title: 't', body: '' } },
            { type: 'BỊA' },
          ],
        },
      })
    })
    expect(useDesignStore.getState().rejectedOps).toBe(1)
    expect(useDesignStore.getState().scenes[DESIGN_ID]?.nodes).toHaveLength(1)
  })

  it('selectActiveRun ưu tiên run ghim trong `mode.activeRunId`', () => {
    const selected = selectActiveRun(useDesignStore.getState())
    expect(selected).toBeNull() // chưa có run nào trong store
    act(() => { useDesignStore.setState({ runs: [readRun(runRow())!] }) })
    expect(selectActiveRun(useDesignStore.getState())?.designId).toBe(DESIGN_ID)
  })

  it('ánh xạ giai đoạn → bước là một nguồn duy nhất', () => {
    expect(stepForPhase('touch-list')).toBe('approve')
    expect(stepForPhase('scaffolding')).toBe('write')
    expect(stepForPhase('reviewing')).toBe('review')
  })
})

/** Lô ghi thật như backend trả (`batch` trong payload run). */
function batchRow(overrides: Record<string, unknown> = {}): DesignBatch {
  return readBatch({
    index: 2,
    total: 3,
    status: 'proposed',
    revision: 5,
    patchPath: '.design/chat-panel/diff.patch',
    added: 8,
    removed: 1,
    files: [
      { path: 'src/ui/ChatPanel.tsx', status: 'insert', added: 2, removed: 0 },
      { path: 'src/styles/tokens.css', status: 'insert', added: 6, removed: 1 },
    ],
    ...overrides,
  })!
}

const outOfScopePrompt = {
  promptId: 'dp-oos',
  designId: DESIGN_ID,
  kind: 'out-of-scope',
  status: 'open',
  revision: 6,
  createdAt: '',
  note: '',
  actions: [],
  questions: [
    {
      id: 'oos',
      text: 'Yêu cầu này nằm ngoài phạm vi thiết kế.',
      allowFreeText: false,
      required: true,
      options: [
        { id: 'exit', label: 'Tạm thoát để main xử lý' },
        { id: 'keep', label: 'Giữ trong design' },
      ],
    },
  ],
}

describe('thẻ P5 của chế độ Design', () => {
  it('batch_diff_card_renders_files: danh sách tệp +/−, đường patch, và hai nút gửi đúng action', async () => {
    const api = stubApi()
    const host = render(<DesignBatchDiffCard designId={DESIGN_ID} batch={batchRow()} revision={5} />)

    const card = host.querySelector('[data-testid="design-diff-batch-card"]')
    expect(card).toBeTruthy()
    expect(card?.textContent).toContain('src/ui/ChatPanel.tsx')
    expect(card?.textContent).toContain('src/styles/tokens.css')
    expect(card?.textContent).toContain('.design/chat-panel/diff.patch')
    expect(card?.textContent).toContain('+8')
    expect(card?.textContent).toContain('−1')

    await act(async () => {
      click(host, '[data-testid="design-batch-approve"]')
    })
    expect(api.calls.find((call) => call.body?.action === 'approve-batch')).toBeTruthy()

    await act(async () => {
      click(host, '[data-testid="design-batch-revert"]')
    })
    expect(api.calls.find((call) => call.body?.action === 'revert-batch')).toBeTruthy()
    act(() => { host.remove() })
  })

  it('batch card khi chưa có lô: vẫn có thẻ nhưng không bịa nút duyệt/hoàn tác', () => {
    const host = render(<DesignBatchDiffCard designId={DESIGN_ID} batch={null} revision={5} />)
    expect(host.querySelector('[data-testid="design-diff-batch-card"]')).toBeTruthy()
    expect(host.querySelector('[data-testid="design-batch-approve"]')).toBeNull()
    expect(host.querySelector('[data-testid="design-batch-revert"]')).toBeNull()
    act(() => { host.remove() })
  })

  it('handoff card: nhánh + base, đường design-md, danh sách chạm đã ghi, phán quyết soát độc lập', () => {
    const run = readRun(
      runRow({
        status: 'completed',
        phase: 'done',
        touchList: {
          ...touchList,
          approvedAt: '2026-09-27T09:00:00Z',
          items: [{ ...touchList.items[0], status: 'written' }],
        },
        review: { version: 'v1', verdict: 'passed', summary: 'không lệch hợp đồng' },
      }),
    )!
    const host = render(
      <DesignHandoffCard
        run={run}
        report={{ branch: { name: 'design/chat-panel-20260927-0900', base: 'abc1234' }, path: '.design/chat-panel/v1-design.md', version: 'v1', summary: 'xong' }}
      />,
    )
    const card = host.querySelector('[data-testid="design-handoff-card"]')
    expect(card).toBeTruthy()
    expect(card?.textContent).toContain('design/chat-panel-20260927-0900')
    expect(card?.textContent).toContain('abc1234')
    expect(card?.textContent).toContain('.design/chat-panel/v1-design.md')
    expect(card?.textContent).toContain('src/ui/ChatPanel.tsx')
    expect(host.querySelector('[data-testid="design-handoff-verdict"]')?.getAttribute('data-verdict')).toBe('passed')
    expect(host.querySelector('[data-testid="design-handoff-done"]')).toBeTruthy()
    act(() => { host.remove() })
  })

  it('out-of-scope card: đúng hai đường, không có đường nào mặc định', () => {
    const run = readRun(runRow({ status: 'scoping', phase: 'interviewing', prompts: [outOfScopePrompt] }))!
    // Đi qua đúng tầng chuẩn hoá (`readPrompt`) thay vì prompt dựng tay.
    const prompt = readPrompt(outOfScopePrompt)!
    const host = render(<DesignOutOfScopeCard run={run} prompt={prompt} />)
    expect(host.querySelector('[data-testid="design-out-of-scope"]')).toBeTruthy()
    expect(host.querySelector('[data-testid="design-out-of-scope"]')?.getAttribute('data-pinned')).toBe('true')
    expect(host.querySelector('[data-testid="design-out-of-scope-exit"]')?.hasAttribute('disabled')).toBe(false)
    expect(host.querySelector('[data-testid="design-out-of-scope-keep"]')?.hasAttribute('disabled')).toBe(false)
    expect(host.querySelector('[data-testid="design-out-of-scope-exit"]')?.getAttribute('aria-pressed')).toBeNull()
    expect(host.querySelector('[data-testid="design-out-of-scope-keep"]')?.getAttribute('aria-pressed')).toBeNull()
    act(() => { host.remove() })
  })

  it('out-of-scope thiếu id ghim ⇒ khoá hai nút và nói rõ, KHÔNG đoán theo vị trí', () => {
    const run = readRun(runRow({ status: 'scoping', phase: 'interviewing' }))!
    const prompt = readPrompt({
      promptId: 'dp-unpinned',
      designId: DESIGN_ID,
      kind: 'out-of-scope',
      status: 'open',
      revision: 1,
      questions: [
        {
          id: 'oos',
          text: 'Yêu cầu ngoài phạm vi.',
          allowFreeText: false,
          required: true,
          options: [{ id: 'a', label: 'Một' }, { id: 'b', label: 'Hai' }],
        },
      ],
    })!
    const host = render(<DesignOutOfScopeCard run={run} prompt={prompt} />)
    expect(host.querySelector('[data-testid="design-out-of-scope"]')?.getAttribute('data-pinned')).toBe('false')
    expect(host.querySelector('[data-testid="design-out-of-scope-exit"]')?.hasAttribute('disabled')).toBe(true)
    expect(host.querySelector('[data-testid="design-out-of-scope-keep"]')?.hasAttribute('disabled')).toBe(true)
    expect(host.querySelector('[data-testid="design-out-of-scope-unpinned"]')).toBeTruthy()
    act(() => { host.remove() })
  })

  it('exit-choice card: hai lựa chọn kèm hệ quả, KHÔNG chọn sẵn', () => {
    const prompt = {
      promptId: 'dp-exit',
      designId: DESIGN_ID,
      kind: 'exit-choice',
      status: 'open',
      revision: 7,
      createdAt: '',
      note: '',
      actions: [],
      questions: [
        {
          id: 'exit',
          text: 'Run còn đang chạy.',
          allowFreeText: false,
          required: true,
          options: [
            { id: 'pause', label: 'Tạm dừng run' },
            { id: 'background', label: 'Tiếp tục chạy nền' },
          ],
        },
      ],
    }
    const host = render(<DesignExitChoiceCard prompt={prompt as never} run={readRun(runRow({ background: false }))} />)
    const pause = host.querySelector('[data-testid="design-exit-pause"]')
    const background = host.querySelector('[data-testid="design-exit-background"]')
    expect(pause).toBeTruthy()
    expect(background).toBeTruthy()
    expect(pause?.getAttribute('aria-pressed')).toBeNull()
    expect(background?.getAttribute('aria-pressed')).toBeNull()
    expect(host.textContent).toContain('Pause the run')
    expect(host.textContent).toContain('Keep running in background')
    act(() => { host.remove() })
  })

  it('canvas panel: hiện trạng thái Design Lead đang vẽ + đếm op bị từ chối', () => {
    act(() => {
      useDesignStore.setState({
        runs: [readRun(runRow({ status: 'designing', phase: 'drawing', touchList: null }))!],
        sceneActor: { [DESIGN_ID]: 'agent' },
        rejectedOps: 2,
      })
      useDesignStore.getState().applyEvent({
        seq: 20,
        type: 'design_canvas',
        data: {
          designId: DESIGN_ID,
          actor: 'agent',
          sceneVersion: 1,
          ops: [
            { type: 'CREATE_NODE', node: { id: 'n1', kind: 'ui-mockup', x: 0, y: 0, width: 10, height: 10, title: 't', body: '' } },
          ],
        },
      })
    })
    const host = render(<DesignCanvasPanel />)
    const live = host.querySelector('[data-testid="design-canvas-live-draw"]')
    expect(live).toBeTruthy()
    expect(live?.getAttribute('data-drawing')).toBe('true')
    expect(live?.getAttribute('data-actor')).toBe('agent')
    expect(live?.textContent).toContain('Design Lead')
    expect(live?.textContent).toContain('2')
    act(() => { host.remove() })
  })
})

describe('tab Design (P5)', () => {
  it('panel_shows_five_panes_and_switches_to_brief', () => {
    act(() => {
      useDesignStore.setState({ runs: [readRun(runRow({ status: 'briefing', phase: 'briefing' }))!] })
    })
    const host = render(<DesignPanel />)

    expect(host.querySelector('[data-testid="design-panel"]')?.getAttribute('data-tab')).toBe('canvas')
    for (const tab of ['canvas', 'brief', 'branch', 'review', 'report']) {
      expect(host.querySelector(`[data-testid="design-panel-tab-${tab}"]`)).toBeTruthy()
    }
    expect(host.querySelector('[data-testid="design-panel-run"]')?.textContent).toContain('D-')

    click(host, '[data-testid="design-panel-tab-brief"]')
    const panel = host.querySelector('[data-testid="design-panel"]')
    expect(panel?.getAttribute('data-tab')).toBe('brief')
    expect(host.querySelector('[data-testid="design-brief-card"]')).toBeTruthy()

    click(host, '[data-testid="design-panel-tab-review"]')
    expect(host.querySelector('[data-testid="design-panel-review-empty"]')).toBeTruthy()
    act(() => { host.remove() })
  })

  it('panel_keeps_an_empty_state_without_any_run', () => {
    const host = render(<DesignPanel />)
    click(host, '[data-testid="design-panel-tab-report"]')
    expect(host.querySelector('[data-testid="design-panel-empty"]')).toBeTruthy()
    expect(host.querySelector('[data-testid="design-handoff-card"]')).toBeFalsy()
    act(() => { host.remove() })
  })
})

/** Bấm một nút có xử lý async rồi để microtask chạy xong. */
async function clickAsync(host: HTMLElement, selector: string): Promise<void> {
  const node = host.querySelector<HTMLButtonElement>(selector)
  if (!node) throw new Error(`không thấy ${selector}`)
  await act(async () => {
    node.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await act(async () => {})
}

/** Phiên chat có id sẵn để `send` không phải mở phiên mới (bài kiểm chỉ soi lời gọi mạng). */
function seedSession(): void {
  useHarnessChatStore.setState((state) => ({
    sessions: {
      ...state.sessions,
      s1: {
        ...(state.sessions['s1'] ?? { id: null, status: 'idle', events: [], error: null }),
        id: 'sess-1',
        status: 'idle',
      },
    },
  }))
}

describe('thông báo, chạy nền và điều khiển run (P5 §5.1/§5.2/§5.6/§5.8/§5.9)', () => {
  it('design_notice: đúng MỘT thẻ thông báo cho mỗi sự kiện, không nhân đôi thẻ báo cáo', () => {
    act(() => {
      useDesignStore.setState({ runs: [readRun(runRow({ status: 'completed', phase: 'done' }))!] })
    })
    act(() => {
      const event = { seq: 31, type: 'design_notice', data: { designId: DESIGN_ID, kind: 'background-done' } }
      useDesignStore.getState().applyEvent(event)
      // Cùng một sự kiện được bơm lại (poll trùng seq) KHÔNG được dựng thẻ thứ hai.
      useDesignStore.getState().applyEvent(event)
    })
    const host = render(<DesignConversationCards />)
    const cards = host.querySelectorAll('[data-testid="design-notice-card"]')
    expect(cards).toHaveLength(1)
    expect(cards[0].getAttribute('data-kind')).toBe('background-done')
    // Run đóng nhưng CHƯA có `design_report` ⇒ không được dựng thẻ bàn giao "rỗng" chồng lên.
    expect(host.querySelector('[data-testid="design-handoff-card"]')).toBeNull()
    act(() => { host.remove() })
  })

  it('run chạy nền khi chế độ tắt: chấm hổ phách + chú thích; bật lại đưa run về tiền cảnh', async () => {
    const api = stubApi()
    act(() => {
      useDesignStore.setState({
        mode: { ...DESIGN_MODE_OFF },
        activeRunId: '',
        runs: [readRun(runRow({ status: 'designing', phase: 'drawing', background: true }))!],
      })
    })
    const host = render(<DesignToggle />)
    const note = host.querySelector('[data-testid="design-background-note"]')
    expect(note?.textContent).toContain('1')
    expect(host.querySelector('[data-testid="design-toggle-dot"]')?.getAttribute('data-tone')).toBe('background')

    await clickAsync(host, '[data-testid="composer-design-toggle"]')
    const onCall = api.calls.find((call) => call.url.includes('/design-mode') && call.body?.on === true)
    expect(onCall).toBeTruthy()
    expect(useDesignStore.getState().mode.on).toBe(true)
    expect(useDesignStore.getState().mode.activeRunId).toBe(DESIGN_ID)
    act(() => { host.remove() })
  })

  it('điều khiển run: tạm dừng / tiếp tục / huỷ gửi PATCH; run tạm dừng nói rõ nhánh và tệp giữ nguyên', async () => {
    const api = stubApi()
    const active = render(<DesignRunTimeline run={readRun(runRow({ status: 'designing', phase: 'drawing' }))!} />)
    expect(active.querySelector('[data-testid="design-run-pause"]')).toBeTruthy()
    await clickAsync(active, '[data-testid="design-run-pause"]')
    expect(api.calls.find((call) => call.body?.action === 'pause')).toBeTruthy()

    await clickAsync(active, '[data-testid="design-run-cancel"]')
    expect(api.calls.find((call) => call.body?.action === 'cancel')).toBeTruthy()

    const paused = render(<DesignRunTimeline run={readRun(runRow({ status: 'paused', phase: 'drawing' }))!} />)
    expect(paused.querySelector('[data-testid="design-run-resume-ask"]')?.textContent).toContain('D-')
    expect(paused.querySelector('[data-testid="design-run-paused-note"]')?.textContent).toBeTruthy()
    expect(paused.querySelector('[data-testid="design-run-pause"]')).toBeNull()
    await clickAsync(paused, '[data-testid="design-run-resume"]')
    expect(api.calls.find((call) => call.body?.action === 'resume')).toBeTruthy()
    act(() => { active.remove(); paused.remove() })
  })

  it('exit-choice: 409 dựng thẻ, KHÔNG chọn sẵn, đóng lời hỏi mà không chọn thì không đổi gì', async () => {
    const api = stubApi()
    act(() => {
      useDesignStore.setState({ runs: [readRun(runRow())!] })
    })
    await act(async () => {
      await useDesignStore.getState().setMode(false, 'toggle')
    })
    expect(useDesignStore.getState().exitChoice).not.toBeNull()

    const strip = render(<DesignComposerStatus />)
    expect(strip.querySelector('[data-testid="design-exit-choice"]')).toBeTruthy()
    expect(strip.querySelector('[data-testid="design-exit-pause"]')?.getAttribute('aria-pressed')).toBeNull()
    expect(strip.querySelector('[data-testid="design-exit-background"]')?.getAttribute('aria-pressed')).toBeNull()

    await clickAsync(strip, '[data-testid="design-exit-cancel"]')
    expect(useDesignStore.getState().exitChoice).toBeNull()
    expect(useDesignStore.getState().mode.on).toBe(true)
    expect(api.calls.filter((call) => call.body?.exitChoice).length).toBe(0)
    act(() => { strip.remove() })
  })

  it('out-of-scope: "Tạm thoát" theo luật thoát rồi nộp lượt main; "Giữ" chỉ trả lời', async () => {
    const api = stubApi()
    seedSession()
    const run = readRun(runRow({ status: 'scoping', phase: 'interviewing', prompts: [outOfScopePrompt] }))!
    act(() => {
      useDesignStore.setState({ runs: [run], prompts: [run.prompts[0]] })
    })
    const cards = render(<DesignConversationCards />)
    const strip = render(<DesignComposerStatus />)

    await clickAsync(cards, '[data-testid="design-out-of-scope-exit"]')
    expect(api.calls.some((call) => call.url.includes('/design/prompts/dp-oos/answer'))).toBe(true)
    // Run còn hoạt động ⇒ server đòi chọn thoát: thẻ thoát hiện, CHƯA nộp lượt nào.
    expect(useDesignStore.getState().exitChoice).not.toBeNull()
    expect(api.calls.some((call) => call.url.includes('/turns'))).toBe(false)

    // Chọn "Tạm dừng" ⇒ chế độ tắt và tin nhắn được nộp thành lượt main.
    await clickAsync(strip, '[data-testid="design-exit-pause"]')
    const turn = api.calls.find((call) => call.url.includes('/turns'))
    expect(turn).toBeTruthy()
    expect(String(turn?.body?.prompt)).toContain('Yêu cầu này')
    expect(useDesignStore.getState().mode.on).toBe(false)
    act(() => { cards.remove(); strip.remove() })
  })

  it('out-of-scope: "Giữ trong design" chỉ trả lời, chế độ vẫn bật', async () => {
    const api = stubApi()
    const run = readRun(runRow({ status: 'scoping', phase: 'interviewing', prompts: [outOfScopePrompt] }))!
    act(() => {
      useDesignStore.setState({ runs: [run], prompts: [run.prompts[0]] })
    })
    const cards = render(<DesignConversationCards />)
    await clickAsync(cards, '[data-testid="design-out-of-scope-keep"]')
    const answer = api.calls.find((call) => call.url.includes('/design/prompts/dp-oos/answer'))
    expect(answer).toBeTruthy()
    expect((answer?.body?.answers as { optionId: string }[])[0].optionId).toBe('keep')
    expect(useDesignStore.getState().mode.on).toBe(true)
    expect(api.calls.some((call) => call.url.includes('/turns'))).toBe(false)
    act(() => { cards.remove() })
  })

  it('out-of-scope: "Tạm thoát" nộp lại TIN NHẮN GỐC của chủ nhà (`meta.request`)', async () => {
    const api = stubApi({ modeResponse: () => jsonResponse({ mode: { on: false, activeRunId: '', revision: 6 } }) })
    seedSession()
    // IF-2: `meta.request` giữ nguyên văn tin nhắn gốc — khác với câu chữ của Design Lead (`question.text`).
    const prompt = readPrompt({ ...outOfScopePrompt, meta: { request: 'làm luôn trang thanh toán' } })!
    const run = readRun(runRow({ status: 'scoping', phase: 'interviewing', prompts: [outOfScopePrompt] }))!
    act(() => {
      useDesignStore.setState({ runs: [run], prompts: [prompt] })
    })
    const cards = render(<DesignConversationCards />)
    await clickAsync(cards, '[data-testid="design-out-of-scope-exit"]')
    const turn = api.calls.find((call) => call.url.includes('/turns'))
    expect(turn).toBeTruthy()
    expect(String(turn?.body?.prompt)).toContain('làm luôn trang thanh toán')
    expect(useDesignStore.getState().mode.on).toBe(false)
    act(() => { cards.remove() })
  })

  it('out-of-scope: trả lời bị từ chối ⇒ KHÔNG xếp lượt main và KHÔNG tắt chế độ', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          jsonResponse({ error: 'Lời hỏi này đã được trả lời rồi.', code: 'DESIGN_PROMPT_ANSWERED' }, 409),
      ),
    )
    seedSession()
    const run = readRun(runRow({ status: 'scoping', phase: 'interviewing', prompts: [outOfScopePrompt] }))!
    act(() => {
      useDesignStore.setState({ runs: [run], prompts: [run.prompts[0]] })
    })
    const cards = render(<DesignConversationCards />)
    await clickAsync(cards, '[data-testid="design-out-of-scope-exit"]')
    expect(useDesignStore.getState().mode.on).toBe(true)
    expect(useDesignStore.getState().pendingTurn).toBe('')
    act(() => { cards.remove() })
  })

  it('thẻ bàn giao: "Dùng cho plan" thoát chế độ rồi nộp lượt main có khối bàn giao', async () => {
    const api = stubApi({ modeResponse: () => jsonResponse({ mode: { on: false, activeRunId: '', revision: 6 } }) })
    seedSession()
    const run = readRun(runRow({ status: 'completed', phase: 'done' }))!
    const host = render(
      <DesignHandoffCard
        run={run}
        report={{ branch: { name: 'design/chat-panel-x', base: 'abc1234' }, path: '.design/chat-panel/v1-design.md', version: 'v1', summary: 'xong' }}
      />,
    )
    await clickAsync(host, '[data-testid="design-handoff-use-plan"]')
    expect(api.calls.find((call) => call.url.includes('/design-mode') && call.body?.on === false)).toBeTruthy()
    const turn = api.calls.find((call) => call.url.includes('/turns'))
    expect(turn).toBeTruthy()
    expect(String(turn?.body?.prompt)).toContain('D-')
    expect(useDesignStore.getState().mode.on).toBe(false)
    act(() => { host.remove() })
  })

  it('thẻ bàn giao: "Mở nhánh"/"Mở bản thiết kế" mở tab Design; "Thoát" tắt chế độ', async () => {
    const api = stubApi()
    const run = readRun(runRow({ status: 'completed', phase: 'done' }))!
    const host = render(
      <DesignHandoffCard
        run={run}
        report={{ branch: { name: 'design/chat-panel-x', base: 'abc1234' }, path: '.design/chat-panel/v1-design.md', version: 'v1', summary: 'xong' }}
      />,
    )
    await clickAsync(host, '[data-testid="design-handoff-open-branch"]')
    expect(useUiStore.getState().activeTab).toBe('design')
    await clickAsync(host, '[data-testid="design-handoff-done"]')
    expect(api.calls.find((call) => call.url.includes('/design-mode') && call.body?.on === false)).toBeTruthy()
    act(() => { host.remove() })
  })

  it('ngăn Soát của tab Design: hiện phán quyết, bản và tóm tắt của vòng soát độc lập', () => {
    act(() => {
      useDesignStore.setState({
        runs: [
          readRun(
            runRow({ status: 'completed', phase: 'done', review: { version: 'v1', verdict: 'passed', summary: 'không lệch hợp đồng' } }),
          )!,
        ],
      })
    })
    const host = render(<DesignPanel />)
    click(host, '[data-testid="design-panel-tab-review"]')
    const pane = host.querySelector('[data-testid="design-panel-review"]')
    expect(pane).toBeTruthy()
    expect(pane?.getAttribute('data-verdict')).toBe('passed')
    expect(pane?.textContent).toContain('v1')
    expect(pane?.textContent).toContain('không lệch hợp đồng')
    act(() => { host.remove() })
  })
})

describe('sửa lỗi soát chế độ Design (P5)', () => {
  it('chế độ TẮT: thông báo nền và thẻ bàn giao vẫn hiện khi run nền xong', () => {
    act(() => {
      useDesignStore.setState({
        mode: { ...DESIGN_MODE_OFF, on: false },
        activeRunId: DESIGN_ID,
        runs: [readRun(runRow({ status: 'completed', phase: 'done' }))!],
        notices: [{ designId: DESIGN_ID, kind: 'background-done', seq: 71 }],
        reports: {
          [DESIGN_ID]: { version: 2, branch: { name: 'design/chat', base: 'abc1234' }, path: '.design/chat/v2.md', verdict: 'passed' },
        },
      })
    })
    const host = render(<DesignConversationCards />)
    expect(host.querySelector('[data-testid="design-notice-card"]')?.getAttribute('data-kind')).toBe('background-done')
    expect(host.querySelector('[data-testid="design-handoff-card"]')).toBeTruthy()
    // Thẻ thuộc run đang chạy vẫn bị chặn khi chế độ tắt.
    expect(host.querySelector('[data-testid="design-brief-card"]')).toBeNull()
    expect(host.querySelector('[data-testid="design-run-timeline"]')).toBeNull()
    act(() => { host.remove() })
  })

  it('báo cáo `version` dạng SỐ không bị dán nhãn v1', () => {
    const run = readRun(runRow({ status: 'completed', phase: 'done' }))!
    const host = render(
      <DesignHandoffCard
        run={run}
        report={{ version: 2, branch: { name: 'design/chat', base: 'abc1234' }, path: '.design/chat/v2.md', verdict: 'passed' }}
      />,
    )
    expect(host.textContent).toContain('v2')
    expect(host.textContent).not.toContain('v1')
    act(() => { host.remove() })
  })

  it('loại lời hỏi lạ hiện nhãn riêng, KHÔNG bị gán nhầm thành phỏng vấn', () => {
    const touch = readPrompt({ promptId: 'dp-t', designId: DESIGN_ID, kind: 'touch-list', status: 'open', revision: 1, questions: [] })!
    const unknown = readPrompt({ promptId: 'dp-u', designId: DESIGN_ID, kind: 'bịa', status: 'open', revision: 1, questions: [] })!
    const touchHost = render(<DesignPromptCard prompt={touch} />)
    expect(touchHost.textContent).toContain('Touch list')
    const unknownHost = render(<DesignPromptCard prompt={unknown} />)
    expect(unknownHost.textContent).toContain('Prompt of an unknown kind')
    act(() => { touchHost.remove(); unknownHost.remove() })
  })

  it('`partial` là trạng thái ĐÓNG trên CẢ dải lẫn dòng thời gian', () => {
    const run = readRun(runRow({ status: 'partial', phase: 'scaffolding' }))!
    act(() => {
      useDesignStore.setState({ runs: [run], mode: { ...DESIGN_MODE_OFF, on: true, activeRunId: DESIGN_ID } })
    })
    const strip = render(<DesignComposerStatus />)
    // "run finished" (tiếng Anh mặc định của I18nProvider) — không còn "đang ở bước Bàn giao".
    expect(strip.querySelector('[data-testid="design-mode-strip"]')?.textContent).toContain('run finished')
    const timeline = render(<DesignRunTimeline run={run} />)
    expect(timeline.querySelector('[data-step="handoff"]')?.getAttribute('data-active')).toBe('true')
    act(() => { strip.remove(); timeline.remove() })
  })

  it('từ chối ghi ⇒ hiện CÂU LỖI đọc được (mã → i18n) thay vì nút chết', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          jsonResponse(
            { error: 'Danh sách chạm đã đổi; hãy tải lại rồi duyệt lại.', code: 'DESIGN_TOUCH_LIST_REVISION_STALE' },
            409,
          ),
      ),
    )
    const run = readRun(runRow())!
    act(() => {
      useDesignStore.setState({ runs: [run], mode: { ...DESIGN_MODE_OFF, on: true, activeRunId: DESIGN_ID } })
    })
    const host = render(<DesignConversationCards />)
    await clickAsync(host, '[data-testid="design-touch-list-approve"]')
    const error = host.querySelector('[data-testid="design-error"]')
    expect(error?.getAttribute('data-code')).toBe('DESIGN_TOUCH_LIST_REVISION_STALE')
    expect(error?.textContent).toContain('touch list changed')
    act(() => { host.remove() })
  })
})
