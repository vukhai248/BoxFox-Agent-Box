/**
 * Thanh trên — bảng 4.8 dòng 11 (#6079).
 *
 * Mockup hiện `38.2k tokens · 12:06`: token + THỜI GIAN, không có USD. Vòng đánh giá chạy trên
 * route miễn phí, nên `$0.00` là một con số bịa — USD chỉ được hiện khi route có giá, tức khi
 * backend thật sự trả về một mức giá dương.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { I18nProvider } from './i18n'
import { TopBar } from './App'

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

beforeEach(() => {
  roots = []
})

afterEach(() => {
  act(() => {
    roots.forEach((root) => root.unmount())
  })
  document.body.innerHTML = ''
})

function budgetLine(budget: { steps: number; tokens: number; costUsd: number; capUsd: number }, elapsedSeconds: number): string {
  const host = render(
    <TopBar
      title="Diffusion data augmentation"
      mode="ACT"
      taskEpoch={3}
      budget={budget}
      elapsedSeconds={elapsedSeconds}
      context={{ integrity_floor: 'khong_tin_duoc', confidentiality_ceiling: 'cong_khai' }}
      workspaceHidden={false}
      workspaceToggleDisabled={false}
      hiddenIntentCount={0}
      queuedViewLabel=""
      onToggleWorkspace={() => {}}
    />,
  )
  return host.querySelector('[data-testid="topbar-budget"]')?.textContent ?? ''
}

describe('thanh trên: token + thời gian, USD chỉ khi route có giá', () => {
  // `I18nProvider` mặc định là 'en' (giống các bài kiểm khác của dự án).
  it('route miễn phí ⇒ chỉ token và thời gian, KHÔNG có USD', () => {
    const text = budgetLine({ steps: 12, tokens: 38_200, costUsd: 0, capUsd: 0 }, 726)
    expect(text).toBe('38.2k tokens · 12:06')
    expect(text).not.toContain('$')
  })

  it('route có giá ⇒ USD xuất hiện, kèm trần khi có trần', () => {
    const withCap = budgetLine({ steps: 12, tokens: 38_200, costUsd: 0.62, capUsd: 0.5 }, 726)
    expect(withCap).toBe('38.2k tokens · 12:06 · $0.62 / cap $0.50')
    const withoutCap = budgetLine({ steps: 12, tokens: 38_200, costUsd: 0.62, capUsd: 0 }, 45)
    expect(withoutCap).toBe('38.2k tokens · 00:45 · $0.62')
  })
})
