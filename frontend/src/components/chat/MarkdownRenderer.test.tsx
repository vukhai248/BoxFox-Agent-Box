import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it } from 'vitest'
import { MarkdownRenderer, makeStreamingSafe } from './MarkdownRenderer'

function renderMarkdown(content: string): HTMLElement {
  // React 19 yêu cầu cờ này để act đồng bộ trong jsdom.
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  act(() => {
    createRoot(host).render(<MarkdownRenderer variant="document" content={content} />)
  })
  return host
}

describe('MarkdownRenderer', () => {
  it('renders GFM, code, links, and KaTeX through the shared safe pipeline', () => {
    const host = renderMarkdown(
      '# Heading\n\n- [x] done\n\n| A | B |\n| - | - |\n| 1 | 2 |\n\n`inline`\n\n```\nplain\n```\n\n[Safe](https://example.com) $x^2$',
    )

    expect(host.querySelector('h1')?.textContent).toBe('Heading')
    const table = host.querySelector('table')
    const inlineCode = host.querySelector('p code')
    expect(table).toBeTruthy()
    expect(table?.className).toContain('w-full')
    expect(inlineCode?.className).toContain('inline-block')
    expect(host.querySelector('pre code')?.textContent).toContain('plain')
    expect(host.querySelector('a')?.getAttribute('rel')).toBe('noreferrer')
    expect(host.querySelector('.katex')).toBeTruthy()
    expect(host.querySelector('.markdown-body')?.className).toContain('max-w-3xl')
  })

  it('document variant is constrained to max-w-3xl', () => {
    const host = renderMarkdown('text')
    expect(host.querySelector('.markdown-body')?.className).toContain('max-w-3xl')
  })

  it('does not render raw HTML', () => {
    const host = renderMarkdown('<script>window.bad = true</script>')
    expect(host.querySelector('script')).toBeNull()
  })

  it('closes incomplete streaming fences without changing complete documents', () => {
    expect(makeStreamingSafe('```ts\nconst x = 1')).toBe('```ts\nconst x = 1\n```')
    expect(makeStreamingSafe('complete')).toBe('complete')
  })
})
