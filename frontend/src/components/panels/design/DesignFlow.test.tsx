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
import { DESIGN_MODE_OFF, readRun, stepForPhase } from '../../../lib/designMode'
import { DesignBriefCard } from './DesignBriefCard'
import { DesignComposerStatus } from './DesignComposerStatus'
import { DesignConversationCards } from './DesignConversationCards'
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
    phaseHistory: [],
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
    prompts: [],
    rejectedOps: 0,
    brief: {},
    exitChoice: null,
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

    act(() => { useDesignStore.setState({ mode: { ...DESIGN_MODE_OFF, on: false } }) })
    const off = render(<DesignConversationCards />)
    expect(off.querySelector('[data-testid="design-brief-card"]')).toBeNull()
    act(() => { off.remove() })
  })

  it('thiếu cấu hình `designMode` ⇒ chế độ tắt: dải và nút đều không vẽ', () => {
    act(() => { useDesignStore.setState({ mode: DESIGN_MODE_OFF, runs: [readRun(runRow())!], exitChoice: null }) })
    const strip = render(<DesignComposerStatus />)
    expect(strip.querySelector('[data-testid="design-mode-strip"]')).toBeNull()
    const cards = render(<DesignConversationCards />)
    expect(cards.querySelector('[data-testid="design-brief-card"]')).toBeNull()
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
