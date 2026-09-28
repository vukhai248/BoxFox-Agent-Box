/**
 * Test cho các primitive dùng chung (`components/ui.tsx`).
 *
 * Trọng tâm là `IconButton.variant` (Kế hoạch E2): `'ghost'` phải giữ NGUYÊN VĂN
 * chuỗi lớp cũ — mọi chỗ dùng hiện có không được đổi một pixel — còn `'pill'`
 * là biến thể mới cho thanh trên (có viền, để đứng cạnh các pill có viền sẵn).
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { IconButton } from './ui'

;(
  globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }
).IS_REACT_ACT_ENVIRONMENT = true

let roots: Root[] = []

function render(node: React.ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(node)
  })
  return host
}

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

/** Chuỗi lớp của bản `'ghost'` trước Kế hoạch E2 — chép nguyên văn. */
const GHOST_BASE =
  'inline-flex size-7 items-center justify-center rounded-md text-muted transition hover:bg-panel2 hover:text-fg'

function buttonOf(host: HTMLElement): HTMLButtonElement {
  const button = host.querySelector('button')
  if (!button) throw new Error('không có button')
  return button
}

describe('IconButton', () => {
  it("variant 'ghost' (mặc định) giữ nguyên văn chuỗi lớp cũ", () => {
    const host = render(
      <IconButton label="Nhãn">
        <span>x</span>
      </IconButton>,
    )
    const button = buttonOf(host)

    // Hai dấu cách cuối là hệ quả của đúng template cũ (`...text-fg ` + '' + ' '
    // + className) — chép y nguyên để chứng minh không đổi một lớp nào.
    expect(button.className).toBe(`${GHOST_BASE}  `)
    expect(button.className).not.toContain('border')
    expect(button.getAttribute('aria-pressed')).toBe('false')
    expect(button.getAttribute('title')).toBe('Nhãn')
    expect(button.getAttribute('aria-label')).toBe('Nhãn')
  })

  it("variant 'ghost' + active ⇒ thêm đúng 'bg-panel2 text-fg'", () => {
    const host = render(
      <IconButton label="Nhãn" active className="relative">
        <span>x</span>
      </IconButton>,
    )
    const button = buttonOf(host)
    expect(button.className).toBe(`${GHOST_BASE} bg-panel2 text-fg relative`)
    expect(button.getAttribute('aria-pressed')).toBe('true')
  })

  it("variant 'pill' có viền, kích cỡ thanh trên và trạng thái active theo 'brand'", () => {
    const host = render(
      <IconButton variant="pill" label="Ẩn bảng Workspace" className="relative">
        <span>x</span>
      </IconButton>,
    )
    const button = buttonOf(host)
    expect(button.className).toBe(
      'inline-flex h-[26px] w-[28px] items-center justify-center rounded-md border border-line/30 bg-panel2/60 text-muted transition hover:border-line/50 hover:bg-panel2 hover:text-fg  relative',
    )
    expect(button.getAttribute('aria-pressed')).toBe('false')
  })

  it("variant 'pill' + active ⇒ nền panel2, chữ sáng text-fg, không viền xanh", () => {
    const host = render(
      <IconButton variant="pill" active label="Hiện bảng Workspace" onClick={() => {}}>
        <span>x</span>
      </IconButton>,
    )
    const button = buttonOf(host)
    expect(button.className).toContain('bg-panel2 text-fg')
    expect(button.className).not.toContain('text-brand')
    expect(button.className).not.toContain('ring-brand')
    expect(button.getAttribute('aria-pressed')).toBe('true')
  })

  it('bấm thì gọi onClick một lần', () => {
    const onClick = vi.fn()
    const host = render(
      <IconButton variant="pill" label="Bấm" onClick={onClick}>
        <span>x</span>
      </IconButton>,
    )
    act(() => {
      buttonOf(host).click()
    })
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('`disabled` ⇒ nút thật sự bị chặn, `title` vẫn nói lý do, và không bấm được', () => {
    const onClick = vi.fn()
    const host = render(
      <IconButton
        variant="pill"
        label="Bảng Workspace không đủ chỗ ở bề rộng màn hình này"
        disabled
        testId="workspace-toggle"
        onClick={onClick}
      >
        <span>x</span>
      </IconButton>,
    )
    const button = buttonOf(host)
    expect(button.hasAttribute('disabled')).toBe(true)
    expect(button.getAttribute('title')).toBe('Bảng Workspace không đủ chỗ ở bề rộng màn hình này')
    expect(button.getAttribute('data-testid')).toBe('workspace-toggle')
    expect(button.className).toContain('cursor-not-allowed opacity-50')
    act(() => {
      button.click()
    })
    expect(onClick).not.toHaveBeenCalled()
  })
})
