/**
 * DecisionsPanel — tab này phải chạy bằng dữ liệu THẬT.
 *
 * Trước đây tab vẽ `INITIAL_DEMO_REQUESTS` / `INITIAL_DEMO_GROUPS` (rỗng) cùng
 * một bản `PermissionCard` riêng có "15 Minutes Scoped" bịa ra. Test này khoá
 * lại hợp đồng mới: hàng đọc từ `useHarnessChatStore.decisions`, trả lời bằng
 * `answerDecision` (`POST …/decisions`), không đụng transport mock, và trạng
 * thái quá hạn đến từ `decision_resolved`, không từ đồng hồ cục bộ.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useAgentStore } from '../../store/agentStore'
import type { DecisionEntry, HarnessEvent } from '../../store/harnessChatStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useUiStore } from '../../store/uiStore'
import { DecisionsPanel } from './DecisionsPanel'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { agentApiMock } = vi.hoisted(() => ({ agentApiMock: vi.fn() }))
vi.mock('../../lib/agentApi', () => ({ agentApi: agentApiMock }))

const CHAT_ID = 'chat-decisions-panel'

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

function entry(overrides: Partial<DecisionEntry> = {}): DecisionEntry {
  return {
    id: 'd1',
    kind: 'question',
    question: 'Chỉ mục phiên nên nằm ở đâu?',
    action: null,
    reason: null,
    options: [
      { id: 'in-harness', label: 'Giữ trong harness', kind: 'approve' },
      { id: 'in-router', label: 'Chuyển vào router', kind: 'alternative' },
      { id: 'reject', label: 'Không chọn gì', kind: 'reject' },
    ],
    deadline: Date.now() / 1000 + 300,
    defaultChoice: 'reject',
    status: 'pending',
    choice: null,
    note: null,
    resolvedReason: null,
    resolvedAt: null,
    requestedAt: Date.now() / 1000,
    ...overrides,
  }
}

function seedDecisions(decisions: DecisionEntry[]) {
  useHarnessChatStore.setState({
    sessions: {
      [CHAT_ID]: { id: 'sess-d', status: 'awaiting_decision', events: [] as HarnessEvent[], error: null },
    },
    decisions: { [CHAT_ID]: decisions },
  })
}

function click(el: Element | null) {
  act(() => {
    el?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function typeInto(textarea: HTMLTextAreaElement, text: string) {
  const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')!.set!
  nativeSetter.call(textarea, text)
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

beforeEach(() => {
  localStorage.clear()
  useAgentStore.setState({ activeSessionId: CHAT_ID })
  useHarnessChatStore.setState({ sessions: {}, decisions: {}, intentSeq: {} })
  useUiStore.setState({ tabIntentTargets: {}, pendingIntents: [] })
  agentApiMock.mockReset()
  agentApiMock.mockImplementation(async () => ({
    status: 'resolved',
    decisionId: 'd1',
    choice: 'in-harness',
    outcome: 'approved',
  }))
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  useHarnessChatStore.setState({ sessions: {}, decisions: {}, intentSeq: {} })
  vi.restoreAllMocks()
})

describe('DecisionsPanel — quyết định thật', () => {
  it('vẽ câu hỏi thật và không còn nút Reset Demo', () => {
    seedDecisions([entry()])
    const host = render(<DecisionsPanel />)

    expect(host.textContent).toContain('Chỉ mục phiên nên nằm ở đâu?')
    expect(host.textContent).toContain('Giữ trong harness')
    expect(host.textContent).not.toContain('Reset Demo')
    expect(host.textContent).not.toContain('15 Minutes Scoped')
    expect(host.querySelector('[data-tab-badge]')).toBeNull()
  })

  it('trả lời một câu hỏi bằng đúng route của harness', async () => {
    seedDecisions([entry()])
    const host = render(<DecisionsPanel />)

    const approve = Array.from(host.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Giữ trong harness'),
    ) as HTMLButtonElement | undefined
    expect(approve).toBeTruthy()

    await act(async () => {
      approve?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const decisionCalls = agentApiMock.mock.calls.filter(([path]) => String(path).endsWith('/decisions'))
    expect(decisionCalls).toHaveLength(1)
    expect(decisionCalls[0][0]).toBe('/sessions/sess-d/decisions')
    expect(decisionCalls[0][1]).toEqual({ decisionId: 'd1', choice: 'in-harness' })

    // Cập nhật ngay tại chỗ: hàng biến khỏi danh sách đang chờ.
    expect(useHarnessChatStore.getState().decisions[CHAT_ID][0].status).toBe('approved')
    expect(host.textContent).toContain('Nothing is waiting for you')
  })

  it('lỗi của route hiện inline và hàng vẫn đang chờ', async () => {
    agentApiMock.mockImplementation(async () => {
      throw new Error('DECISION_ALREADY_RESOLVED: đã trả lời rồi')
    })
    seedDecisions([entry()])
    const host = render(<DecisionsPanel />)

    const reject = Array.from(host.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Không chọn gì'),
    )
    await act(async () => {
      reject?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(useHarnessChatStore.getState().sessions[CHAT_ID].error).toContain('DECISION_ALREADY_RESOLVED')
    expect(host.textContent).toContain('Chỉ mục phiên nên nằm ở đâu?')
    // ... và lỗi phải hiện NGAY TRONG panel này (nơi người dùng vừa bấm), không
    // chỉ nằm ở cột chat — hàng quay về "đang chờ" nên nếu không có dải này thì
    // cú bấm trông như không có chuyện gì xảy ra.
    const strip = host.querySelector('[data-testid="decision-answer-error"]')
    expect(strip).toBeTruthy()
    expect(strip?.textContent).toContain('Could not send your answer')
    expect(strip?.textContent).toContain('DECISION_ALREADY_RESOLVED')
  })

  it('trả lời thành công thì KHÔNG hiện dải lỗi', async () => {
    seedDecisions([entry()])
    const host = render(<DecisionsPanel />)

    const approve = Array.from(host.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Giữ trong harness'),
    )
    await act(async () => {
      approve?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(useHarnessChatStore.getState().decisions[CHAT_ID][0].status).toBe('approved')
    expect(host.querySelector('[data-testid="decision-answer-error"]')).toBeNull()
  })

  it('quyết định quá hạn hiện đúng trạng thái từ `decision_resolved`', () => {
    seedDecisions([
      entry({ status: 'rejected', choice: 'reject', resolvedReason: 'timeout', resolvedAt: 1_758_299_000 }),
    ])
    const host = render(<DecisionsPanel />)

    // Bộ lọc mặc định là "đang chờ" → mục đã xong nằm ở lịch sử.
    expect(host.textContent).toContain('Nothing is waiting for you')
    click(host.querySelector('[data-testid="decisions-filter-resolved"]'))
    expect(host.textContent).toContain('Expired')
    expect(host.textContent).toContain('Timed out — rejected automatically')
    expect(host.textContent).not.toContain('10:00')
  })

  it('hàng trả lời tự nhập hiện trung tính: không "đã duyệt", không "bị từ chối"', () => {
    seedDecisions([
      entry({
        status: 'answered',
        choice: 'in-harness',
        note: 'Không đồng ý, sửa lại phần X',
        resolvedReason: 'user',
        resolvedAt: 1_758_300_200,
      }),
    ])
    const host = render(<DecisionsPanel />)

    click(host.querySelector('[data-testid="decisions-filter-resolved"]'))
    expect(host.textContent).toContain('Answered')
    expect(host.textContent).not.toContain('Approved')
    expect(host.textContent).not.toContain('Rejected')
    expect(host.textContent).toContain('Không đồng ý, sửa lại phần X')
    // Biểu tượng trung tính: hàng tự nhập không mang dấu X đỏ của "bị từ chối".
    const row = host.querySelector('[data-decision-id="d1"]')
    expect(row?.querySelector('svg.lucide-message-square')).not.toBeNull()
    expect(row?.querySelector('svg.lucide-circle-x')).toBeNull()
  })

  it('bộ đếm hạn lấy từ `deadline` của server', () => {
    seedDecisions([entry({ deadline: Date.now() / 1000 + 125 })])
    const host = render(<DecisionsPanel />)

    // 125 giây → "2:05"; không có mốc 10 phút nào do giao diện tự dựng.
    expect(host.textContent).toMatch(/2:0[45]/)
    expect(host.textContent).not.toContain('10:00')
  })

  it('lọc "đã xong" và "tất cả" dùng đúng số lượng thật', () => {
    seedDecisions([
      entry(),
      entry({ id: 'd2', status: 'approved', choice: 'in-harness', resolvedReason: 'user' }),
    ])
    const host = render(<DecisionsPanel />)

    expect(host.textContent).toContain('Resolved (1)')
    click(host.querySelector('[data-testid="decisions-filter-all"]'))
    expect(host.textContent).toContain('Chỉ mục phiên nên nằm ở đâu?')
    expect(host.textContent).toContain('Approved')
  })

  it('lựa chọn tự nhập (`other`) khoá nút khi rỗng và gửi kèm chữ đã gõ', async () => {
    // P4 — runtime luôn thêm lựa chọn tự nhập; chọn nó MÀ BỎ TRỐNG là vô nghĩa (route trả
    // `DECISION_NOTE_REQUIRED`), nên nút gửi bị khoá cho tới khi có chữ.
    agentApiMock.mockImplementation(async () => ({
      status: 'resolved',
      decisionId: 'd1',
      choice: 'other',
      outcome: 'approved',
    }))
    seedDecisions([
      entry({
        options: [
          { id: 'in-harness', label: 'Giữ trong harness', kind: 'approve' },
          { id: 'reject', label: 'Không chọn gì', kind: 'reject' },
          { id: 'other', label: 'Khác (tự nhập)', kind: 'alternative', allowFreeText: true },
        ],
      }),
    ])
    const host = render(<DecisionsPanel />)

    const open = Array.from(host.querySelectorAll('button')).find((button) =>
      button.textContent?.includes('Khác (tự nhập)'),
    )
    expect(open).toBeTruthy()
    expect(host.querySelector('[data-testid="decision-free-text-input"]')).toBeNull()
    click(open ?? null)

    const input = host.querySelector('[data-testid="decision-free-text-input"]') as HTMLTextAreaElement | null
    expect(input).toBeTruthy()
    const submit = () => host.querySelector('[data-testid="decision-free-text-submit"]') as HTMLButtonElement
    expect(submit().disabled).toBe(true)

    await act(async () => {
      typeInto(input!, '   ')
    })
    expect(submit().disabled).toBe(true)

    await act(async () => {
      typeInto(input!, '  Chọn phương án C  ')
    })
    expect(submit().disabled).toBe(false)

    await act(async () => {
      submit().dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    const decisionCalls = agentApiMock.mock.calls.filter(([path]) => String(path).endsWith('/decisions'))
    expect(decisionCalls).toHaveLength(1)
    expect(decisionCalls[0][1]).toEqual({ decisionId: 'd1', choice: 'other', note: 'Chọn phương án C' })
    expect(useHarnessChatStore.getState().decisions[CHAT_ID][0].note).toBe('Chọn phương án C')
  })

  it('đích của ý định mở tab (`requestId`) thì cuộn tới đúng thẻ đó', () => {
    const scrollIntoView = vi.fn()
    Element.prototype.scrollIntoView = scrollIntoView as unknown as Element['scrollIntoView']
    useUiStore.setState({ tabIntentTargets: { decisions: { requestId: 'd2' } } })
    seedDecisions([entry(), entry({ id: 'd2', question: 'Câu hỏi thứ hai' })])

    render(<DecisionsPanel />)

    expect(scrollIntoView).toHaveBeenCalled()
  })
})
