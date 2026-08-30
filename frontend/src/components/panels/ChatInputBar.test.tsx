import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useAgentStore } from '../../store/agentStore'
import { useComposerStore } from '../../store/composerStore'
import { ChatInputBar } from './ChatInputBar'
import type { ClientCommand } from '../../types/transport'
import type { InspectedElementContext, InspectLabel } from '../../types/inspect'

// `ChatInputBar` render qua raw `createRoot`, đúng khuôn đã dùng ở
// `ElementInspectorDrawer.test.tsx` — dự án này không dùng @testing-library.
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

function label(): InspectLabel {
  return {
    integrity: 'khong_tin_duoc',
    confidentiality: 'noi_bo',
    source_kind: 'screen_capture',
    source_uri: 'screen://element/0x1',
    tool_name: 'inspect_element',
    content_hash: 'sha256:x',
  }
}

function elementContext(id = 'el-1'): InspectedElementContext {
  return {
    id,
    point: { x: 10, y: 20 },
    result: {
      type: 'dom',
      selector: 'button.submit',
      url: 'http://localhost:3100/',
      title: 't',
      tagName: 'button',
      text: 'Submit',
      attributes: {},
      html: '<button class="submit">Submit</button>',
      truncated: false,
      cssBox: { x: 0, y: 0, width: 1, height: 1 },
      screenBox: { x: 0, y: 0, width: 1, height: 1 },
      target: { windowId: 'w1', windowTitle: 'title', targetId: 't1' },
      label: label(),
    },
  }
}

function findSendButton(host: HTMLElement): HTMLButtonElement {
  return host.querySelector('button[title="Send prompt (Enter)"]') as HTMLButtonElement
}

/**
 * Gán giá trị textarea rồi bắn `input` — React theo dõi `value` qua một
 * tracker gắn trên chính setter gốc của DOM, nên gán `.value = ` trực tiếp bị
 * tracker coi là "không đổi" và bỏ qua onChange. Phải gọi qua setter GỐC
 * (trước khi React ghi đè) để tracker nhận ra giá trị đã đổi thật.
 */
function typeInto(textarea: HTMLTextAreaElement, text: string) {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    'value',
  )!.set!
  nativeSetter.call(textarea, text)
  textarea.dispatchEvent(new Event('input', { bubbles: true }))
}

beforeEach(() => {
  useComposerStore.setState({ pendingElements: [] })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  useComposerStore.setState({ pendingElements: [] })
  vi.unstubAllEnvs()
})

describe('ChatInputBar — element context chips (plan §8-F12)', () => {
  it('không có chip khi pendingElements rỗng, và nút Gửi bị disable khi ô trống', () => {
    const host = render(<ChatInputBar />)
    expect(host.textContent).not.toContain('button.submit')
    expect(findSendButton(host).disabled).toBe(true)
  })

  it('hiện chip cho mỗi phần tử đang chờ, nhãn rút từ inspectChipLabel', () => {
    useComposerStore.setState({ pendingElements: [elementContext()] })
    const host = render(<ChatInputBar />)
    expect(host.textContent).toContain('button.submit')
  })

  it('nút Gửi KHÔNG bị disable khi có phần tử đang chờ dù ô nhập trống và không có file đính kèm', () => {
    useComposerStore.setState({ pendingElements: [elementContext()] })
    const host = render(<ChatInputBar />)
    expect(findSendButton(host).disabled).toBe(false)
  })

  it('bấm nút xoá trên chip gọi removePendingElement và chip biến mất', () => {
    useComposerStore.setState({ pendingElements: [elementContext('el-remove')] })
    const host = render(<ChatInputBar />)
    const removeButton = host.querySelector('button[aria-label="Remove attached element"]') as HTMLButtonElement
    expect(removeButton).toBeTruthy()
    act(() => {
      removeButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(useComposerStore.getState().pendingElements).toHaveLength(0)
    expect(host.textContent).not.toContain('button.submit')
  })

  it('gửi tin: `elements` đi vào ClientCommand có cấu trúc, KHÔNG bị nối vào text, và hàng chờ được dọn sau khi gửi', () => {
    const el = elementContext()
    useComposerStore.setState({ pendingElements: [el] })
    let sentCommand: ClientCommand | undefined
    useAgentStore.setState({
      sendCommand: (command) => {
        sentCommand = command
      },
    })

    const host = render(<ChatInputBar />)
    const sendButton = findSendButton(host)
    act(() => {
      sendButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(sentCommand?.type).toBe('user_message')
    if (sentCommand?.type === 'user_message') {
      expect(sentCommand.elements).toEqual([el])
      expect(sentCommand.text).not.toContain('button.submit')
    }
    expect(useComposerStore.getState().pendingElements).toHaveLength(0)
  })

  it('gửi tin khi KHÔNG có phần tử đang chờ: ClientCommand không mang trường `elements`', () => {
    let sentCommand: ClientCommand | undefined
    useAgentStore.setState({
      sendCommand: (command) => {
        sentCommand = command
      },
    })
    const host = render(<ChatInputBar />)
    const textarea = host.querySelector('textarea') as HTMLTextAreaElement
    act(() => {
      typeInto(textarea, 'hello')
    })
    const sendButton = findSendButton(host)
    act(() => {
      sendButton.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(sentCommand?.type).toBe('user_message')
    if (sentCommand?.type === 'user_message') {
      expect(sentCommand.elements).toBeUndefined()
    }
  })

  it('chế độ live + có phần tử đang chờ ⇒ hiện ghi chú "chưa có nơi tiêu thụ"', () => {
    vi.stubEnv('VITE_TRANSPORT', 'live')
    useComposerStore.setState({ pendingElements: [elementContext()] })
    const host = render(<ChatInputBar />)
    expect(host.textContent).toContain('LIVE mode has no consumer for attached elements yet')
  })

  it('chế độ mock (mặc định test) + có phần tử đang chờ ⇒ KHÔNG hiện ghi chú chế độ live', () => {
    useComposerStore.setState({ pendingElements: [elementContext()] })
    const host = render(<ChatInputBar />)
    expect(host.textContent).not.toContain('LIVE mode has no consumer')
  })
})
