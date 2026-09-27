/**
 * `PermissionCard` phục vụ hai đường: thẻ của transport mock (giữ nguyên như
 * trước) và thẻ quyết định thật của harness. Test này khoá đường thứ hai:
 * bộ đếm chỉ lấy từ `deadline` của server, trạng thái quá hạn đến từ
 * `decision_resolved`, và bấm một lựa chọn chỉ gọi `onAnswer(optionId)` —
 * KHÔNG phát lệnh `permission_response` nào qua transport.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../i18n'
import { useAgentStore } from '../store/agentStore'
import type { DecisionEntry } from '../store/harnessChatStore'
import { PermissionCard } from './PermissionCard'

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

function decision(overrides: Partial<DecisionEntry> = {}): DecisionEntry {
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

beforeEach(() => {
  localStorage.clear()
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('PermissionCard — thẻ quyết định thật', () => {
  it('bấm một lựa chọn trả về đúng id, không phát lệnh transport nào', () => {
    const sendCommand = vi.fn()
    useAgentStore.setState({ sendCommand })
    const onAnswer = vi.fn()
    const host = render(<PermissionCard decision={decision()} onAnswer={onAnswer} />)

    const button = Array.from(host.querySelectorAll('button')).find((item) =>
      item.textContent?.includes('Giữ trong harness'),
    )
    act(() => {
      button?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onAnswer).toHaveBeenCalledWith('in-harness')
    expect(sendCommand).not.toHaveBeenCalled()
  })

  it('bộ đếm ngược chỉ lấy từ `deadline` của server', () => {
    const host = render(<PermissionCard decision={decision({ deadline: Date.now() / 1000 + 185 })} />)

    expect(host.textContent).toMatch(/3:0[45]/)
    // Không còn nhãn "10 phút" do giao diện tự bịa.
    expect(host.textContent).not.toContain('10:00')
  })

  it('đang gửi thì khoá lựa chọn và nói rõ đang gửi', () => {
    const onAnswer = vi.fn()
    const host = render(<PermissionCard decision={decision()} onAnswer={onAnswer} busy />)

    const buttons = Array.from(host.querySelectorAll('button'))
    expect(buttons.every((button) => (button as HTMLButtonElement).disabled)).toBe(true)

    act(() => {
      buttons[0]?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onAnswer).not.toHaveBeenCalled()
    expect(host.textContent).toContain('Sending your answer')
  })

  it('quá hạn: không còn nút chọn, hiện lý do tự động từ chối', () => {
    const host = render(
      <PermissionCard
        decision={decision({ status: 'rejected', choice: 'reject', resolvedReason: 'timeout', resolvedAt: 1_758_299_000 })}
      />,
    )

    expect(host.textContent).toContain('Past the deadline')
    expect(host.textContent).toContain('Không chọn gì') // lựa chọn đã ghi nhận
    expect(host.querySelectorAll('button')).toHaveLength(0)
  })

  it('kết quả đã chốt hiện kèm ghi chú của server', () => {
    const host = render(
      <PermissionCard
        decision={decision({
          status: 'approved',
          choice: 'in-harness',
          note: 'chốt phương án gọn',
          resolvedReason: 'user',
          resolvedAt: 1_758_300_100,
        })}
      />,
    )

    expect(host.textContent).toContain('Approved')
    expect(host.textContent).toContain('Giữ trong harness')
    expect(host.textContent).toContain('chốt phương án gọn')
  })

  it('câu trả lời tự nhập hiện trung tính, không đội lốt "đã duyệt" hay "bị từ chối"', () => {
    const host = render(
      <PermissionCard
        decision={decision({
          status: 'answered',
          choice: 'in-harness',
          note: 'Không đồng ý, sửa lại phần X',
          resolvedReason: 'user',
          resolvedAt: 1_758_300_200,
        })}
      />,
    )

    expect(host.textContent).toContain('Answered')
    expect(host.textContent).not.toContain('Approved')
    expect(host.textContent).not.toContain('Rejected')
    expect(host.textContent).toContain('Không đồng ý, sửa lại phần X')
  })

  it('yêu cầu phê duyệt hiện hành động thật và lý do agent đưa ra', () => {
    const host = render(
      <PermissionCard
        decision={decision({
          kind: 'approval',
          question: null,
          action: 'write_file(path=/etc/hosts)',
          reason: 'Đường dẫn ngoài vùng được ghi tự do',
        })}
      />,
    )

    expect(host.textContent).toContain('write_file(path=/etc/hosts)')
    expect(host.textContent).toContain('Đường dẫn ngoài vùng được ghi tự do')
  })

  it('không có quyết định và không có yêu cầu transport thì không vẽ gì', () => {
    const host = render(<PermissionCard />)

    expect(host.textContent).toBe('')
  })
})
