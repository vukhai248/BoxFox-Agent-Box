/**
 * Kiểm thử tính năng viền sáng (active border) của ChatInputBar:
 * - Viền sáng (`border-zinc-500 ring-1`) CHỈ xuất hiện khi ô textarea thật sự đang focus (có dấu | nhấp nháy).
 * - Khi người dùng bấm vào các nút công cụ (chọn model, đính kèm, quick ask, 3 chấm, mic, gửi...),
 *   khung ngoài của chat bar KHÔNG ĐƯỢC có viền sáng.
 * - Khi textarea bị blur, viền sáng lập tức biến mất và trở về `border-line/80`.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { I18nProvider } from '../../i18n'
import { ChatInputBar } from './ChatInputBar'

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

describe('ChatInputBar — viền sáng của khung chat', () => {
  beforeEach(() => {
    roots = []
    document.body.innerHTML = ''
  })

  afterEach(() => {
    for (const r of roots) act(() => r.unmount())
    roots = []
    document.body.innerHTML = ''
  })

  it('ban đầu không có viền sáng và có viền mặc định border-line/80', () => {
    const host = render(<ChatInputBar />)
    const bar = host.querySelector<HTMLElement>('[data-testid="chat-input-bar"]')
    expect(bar).not.toBeNull()
    expect(bar?.className).toContain('border-line/80')
    expect(bar?.className).not.toContain('border-zinc-500')
    expect(bar?.className).not.toContain('ring-1')
  })

  it('khi bấm vào nút công cụ (ví dụ nút model picker), khung chat KHÔNG được có viền sáng', () => {
    const host = render(<ChatInputBar />)
    const bar = host.querySelector<HTMLElement>('[data-testid="chat-input-bar"]')
    const modelBtn = Array.from(host.querySelectorAll('button')).find((b) =>
      (b.getAttribute('title') ?? '').startsWith('Model:') || (b.getAttribute('title') ?? '').startsWith('Harness:'),
    )
    expect(modelBtn).toBeDefined()

    // Focus / click nút model
    act(() => {
      modelBtn?.focus()
      modelBtn?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    // Khung chat bên ngoài KHÔNG được có viền sáng
    expect(bar?.className).toContain('border-line/80')
    expect(bar?.className).not.toContain('border-zinc-500')
    expect(bar?.className).not.toContain('ring-1')
  })

  it('khi textarea nhận focus, khung chat có viền sáng border-zinc-500 ring-1', () => {
    const host = render(<ChatInputBar />)
    const bar = host.querySelector<HTMLElement>('[data-testid="chat-input-bar"]')
    const textarea = host.querySelector<HTMLTextAreaElement>('textarea')
    expect(textarea).not.toBeNull()

    // Focus textarea
    act(() => {
      textarea?.focus()
      textarea?.dispatchEvent(new FocusEvent('focus'))
    })

    expect(bar?.className).toContain('border-zinc-500')
    expect(bar?.className).toContain('ring-1')
    expect(bar?.className).not.toContain('border-line/80')

    // Blur textarea đang active trong DOM (expanded textarea)
    const activeTextarea = host.querySelector<HTMLTextAreaElement>('textarea')
    act(() => {
      activeTextarea?.blur()
      activeTextarea?.dispatchEvent(new FocusEvent('blur'))
    })

    expect(bar?.className).toContain('border-line/80')
    expect(bar?.className).not.toContain('border-zinc-500')
    expect(bar?.className).not.toContain('ring-1')
  })
})
