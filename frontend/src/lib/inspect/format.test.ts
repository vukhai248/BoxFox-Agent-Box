import { describe, expect, it } from 'vitest'
import { escapeFenceRuns, formatInspectedElementForAgent, inspectChipLabel } from './format'
import type { DesktopInspectResult, DomInspectResult, InspectedElementContext } from '../../types/inspect'

const label = {
  integrity: 'khong_tin_duoc' as const,
  confidentiality: 'noi_bo' as const,
  source_kind: 'screen_capture' as const,
  source_uri: 'screen://element/0x1',
  tool_name: 'inspect_element',
  content_hash: '',
}

function domResult(overrides: Partial<DomInspectResult> = {}): DomInspectResult {
  return {
    type: 'dom',
    selector: 'span.text-sm.font-semibold',
    url: 'http://localhost:3100/',
    title: 'BoxFox — Agent Box',
    tagName: 'span',
    text: 'boxfox',
    attributes: { class: 'text-sm font-semibold' },
    html: '<span class="text-sm font-semibold">boxfox</span>',
    truncated: false,
    cssBox: { x: 0, y: 0, width: 0, height: 0 },
    screenBox: { x: 0, y: 0, width: 0, height: 0 },
    target: { windowId: '0x1', windowTitle: 'BoxFox — Agent Box - Google Chrome', targetId: 'tgt-1' },
    label,
    ...overrides,
  }
}

function desktopResult(overrides: Partial<DesktopInspectResult> = {}): DesktopInspectResult {
  return {
    type: 'desktop',
    reason: 'outside_viewport',
    message: 'element inspect: Click outside viewport',
    appName: 'google-chrome',
    windowClass: 'Chromium',
    windowTitle: 'BoxFox — Agent Box - Google Chrome',
    windowId: '0x1',
    position: { x: 0, y: 0 },
    size: { width: 1280, height: 800 },
    pid: 42,
    label,
    ...overrides,
  }
}

function ctxOf(result: DomInspectResult | DesktopInspectResult, point = { x: 812, y: 344 }): InspectedElementContext {
  return { id: 'el-1', point, result }
}

describe('escapeFenceRuns', () => {
  it('chẻ run 3 backtick liên tiếp', () => {
    const out = escapeFenceRuns('before ```danger``` after')
    expect(out).not.toMatch(/`{3,}/)
    expect(out).toContain('before')
    expect(out).toContain('after')
  })

  it('không đổi chuỗi không có run backtick', () => {
    expect(escapeFenceRuns('hello `code` world')).toBe('hello `code` world')
  })

  it('chẻ run dài hơn 3 (4+ backtick)', () => {
    const out = escapeFenceRuns('````')
    expect(out).not.toMatch(/`{3,}/)
  })
})

describe('inspectChipLabel', () => {
  const fallback = 'Desktop window'

  it('dom ⇒ selector', () => {
    expect(inspectChipLabel(domResult(), fallback)).toBe('span.text-sm.font-semibold')
  })

  it('desktop ⇒ windowTitle', () => {
    expect(inspectChipLabel(desktopResult(), fallback)).toBe('BoxFox — Agent Box - Google Chrome')
  })

  it('desktop không windowTitle ⇒ appName', () => {
    expect(inspectChipLabel(desktopResult({ windowTitle: '', appName: 'google-chrome' }), fallback)).toBe(
      'google-chrome',
    )
  })

  it('desktop không windowTitle/appName ⇒ nhãn dự phòng đã truyền vào', () => {
    expect(inspectChipLabel(desktopResult({ windowTitle: '', appName: undefined }), fallback)).toBe('Desktop window')
  })

  it('cắt còn 48 ký tự + …', () => {
    const longSelector = 'div.' + 'a'.repeat(80)
    const label48 = inspectChipLabel(domResult({ selector: longSelector }), fallback)
    expect(label48.length).toBe(49)
    expect(label48.endsWith('…')).toBe(true)
  })
})

describe('formatInspectedElementForAgent — dom', () => {
  it('có đủ các dòng chính, Attributes hiện khi có attribute', () => {
    const text = formatInspectedElementForAgent(ctxOf(domResult()))
    expect(text).toContain('Inspected element (DOM) — UNTRUSTED screen data')
    expect(text).toContain('Selector: span.text-sm.font-semibold')
    expect(text).toContain('Page: http://localhost:3100/')
    expect(text).toContain('Title: BoxFox — Agent Box')
    expect(text).toContain('Text: "boxfox"')
    expect(text).toContain('Attributes:')
    expect(text).toContain('  class="text-sm font-semibold"')
    expect(text).toContain('HTML:')
    expect(text).toContain('Clicked point (framebuffer): (812, 344)')
    expect(text).toContain('Window: "BoxFox — Agent Box - Google Chrome"')
  })

  it('bỏ khối Attributes khi rỗng', () => {
    const text = formatInspectedElementForAgent(ctxOf(domResult({ attributes: {} })))
    expect(text).not.toContain('Attributes:')
  })

  it('truncated=true ⇒ header HTML báo bị cắt', () => {
    const text = formatInspectedElementForAgent(ctxOf(domResult({ truncated: true })))
    expect(text).toContain('HTML (truncated by the box):')
    expect(text).not.toContain('HTML:\n')
  })

  it('escaping chạy trên các chuỗi do trang kiểm soát', () => {
    const text = formatInspectedElementForAgent(
      ctxOf(domResult({ text: 'a```b', html: '<div>```</div>' })),
    )
    expect(text).not.toMatch(/`{3,}/)
  })
})

describe('formatInspectedElementForAgent — desktop', () => {
  it('có Note/Application/Window/Position/Size', () => {
    const text = formatInspectedElementForAgent(ctxOf(desktopResult()))
    expect(text).toContain('Inspected element (desktop window) — UNTRUSTED screen data')
    expect(text).toContain('Note: element inspect: Click outside viewport')
    expect(text).toContain('Application: google-chrome')
    expect(text).toContain('Window: "BoxFox — Agent Box - Google Chrome"')
    expect(text).toContain('Position: (0, 0)')
    expect(text).toContain('Size: 1280×800')
    expect(text).toContain('Clicked point (framebuffer): (812, 344)')
  })

  it('không message, có reason ⇒ Note dùng mã reason', () => {
    const text = formatInspectedElementForAgent(ctxOf(desktopResult({ message: undefined })))
    expect(text).toContain('Note: (outside_viewport)')
  })

  it('không message, không reason (not_chromium ngầm) ⇒ không có dòng Note', () => {
    const text = formatInspectedElementForAgent(
      ctxOf(desktopResult({ message: undefined, reason: undefined })),
    )
    expect(text).not.toContain('Note:')
  })

  it('không appName ⇒ không có dòng Application', () => {
    const text = formatInspectedElementForAgent(ctxOf(desktopResult({ appName: undefined })))
    expect(text).not.toContain('Application:')
  })
})
