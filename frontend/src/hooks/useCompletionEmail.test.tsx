/**
 * Kiểm tra chuỗi "box xong task → gửi email mock": hook `useCompletionEmail` ghi
 * `completionEmail` khi phiên đang mở CHUYỂN sang `xong` và người dùng đã bật
 * công tắc + nhập email; và `CompletionEmailNotice` render đúng subject/body.
 *
 * Kịch bản mock không thể chạy hết `task_finished` qua UI hiện tại (điều khiển
 * demo đã bị gỡ ở lần refactor trước — không còn nút "Bước tiếp" ở chế độ ACT),
 * nên test này bơm trực tiếp sự kiện `task_finished` vào store để xác minh logic.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { I18nProvider } from '../i18n'
import { useAgentStore } from '../store/agentStore'
import { useUiStore } from '../store/uiStore'
import { ACTIVE_SESSION_ID, MOCK_SESSIONS } from '../lib/mock/sessions'
import { useCompletionEmail } from './useCompletionEmail'
import { CompletionEmailNotice } from '../components/CompletionEmailNotice'

function mount(node: React.ReactNode): { host: HTMLElement; root: Root } {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  void act(() => {
    root.render(node)
  })
  return { host, root }
}

function Probe() {
  useCompletionEmail()
  return null
}

beforeEach(() => {
  useAgentStore.setState({
    sessions: [...MOCK_SESSIONS],
    activeSessionId: ACTIVE_SESSION_ID,
    messages: [],
  })
  useUiStore.setState({
    userEmail: '',
    notifyOnComplete: false,
    completionEmail: null,
  })
})

afterEach(() => {
  document.body.innerHTML = ''
})

describe('useCompletionEmail', () => {
  it('ghi completionEmail khi xong task + bật công tắc + có email', async () => {
    useUiStore.setState({ userEmail: 'khai@example.com', notifyOnComplete: true })
    await act(async () => {
      mount(<I18nProvider><Probe /></I18nProvider>)
    })
    await act(async () => {
      useAgentStore.getState().applyEvent({ type: 'task_finished', reason: 'Safe completion' })
    })

    const email = useUiStore.getState().completionEmail
    expect(email).not.toBeNull()
    expect(email!.to).toBe('khai@example.com')
    expect(email!.lang).toBe('en')
    expect(email!.title).toBe('New Session')
  })

  it('không ghi khi chưa bật công tắc', async () => {
    useUiStore.setState({ userEmail: 'khai@example.com', notifyOnComplete: false })
    await act(async () => {
      mount(<I18nProvider><Probe /></I18nProvider>)
    })
    await act(async () => {
      useAgentStore.getState().applyEvent({ type: 'task_finished', reason: 'Safe completion' })
    })
    expect(useUiStore.getState().completionEmail).toBeNull()
  })

  it('không ghi khi email rỗng', async () => {
    useUiStore.setState({ userEmail: '', notifyOnComplete: true })
    await act(async () => {
      mount(<I18nProvider><Probe /></I18nProvider>)
    })
    await act(async () => {
      useAgentStore.getState().applyEvent({ type: 'task_finished', reason: 'Safe completion' })
    })
    expect(useUiStore.getState().completionEmail).toBeNull()
  })

  it('không ghi khi reason=reset (reset kịch bản đưa về dang_chay)', async () => {
    useUiStore.setState({ userEmail: 'khai@example.com', notifyOnComplete: true })
    await act(async () => {
      mount(<I18nProvider><Probe /></I18nProvider>)
    })
    await act(async () => {
      useAgentStore.getState().applyEvent({ type: 'task_finished', reason: 'reset' })
    })
    expect(useUiStore.getState().completionEmail).toBeNull()
  })
})

describe('CompletionEmailNotice', () => {
  it('render subject, người nhận và danh sách việc đã làm', async () => {
    useUiStore.setState({
      completionEmail: {
        to: 'khai@example.com',
        at: '2026-08-29T00:00:00Z',
        lang: 'en',
        title: 'Build login',
        work: [
          { tool: 'read_file', target: 'src/parser.py' },
          { tool: 'run_command', target: 'pytest' },
        ],
      },
    })

    const { host } = mount(<I18nProvider><CompletionEmailNotice /></I18nProvider>)

    expect(host.textContent).toContain('khai@example.com')
    expect(host.textContent).toContain('Completed: Build login')
    expect(host.textContent).toContain('Read file — src/parser.py')
    expect(host.textContent).toContain('Run command — pytest')
    expect(host.textContent).toContain('Work done:')
  })
})
