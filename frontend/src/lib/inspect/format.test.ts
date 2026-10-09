import { describe, expect, it } from 'vitest'
import { escapeFenceRuns, formatInspectedElementForAgent, inspectChipLabel } from './format'
import type { DesktopInspectResult, DomInspectResult, InspectedElementContext, UiaInspectResult } from '../../types/inspect'

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

function uiaResult(overrides: Partial<UiaInspectResult> = {}): UiaInspectResult {
  return {
    type: 'uia',
    name: 'Tệp',
    controlType: 'menu item',
    controlTypeId: 50011,
    automationId: 'FileMenu',
    className: 'MenuItem',
    helpText: '',
    isEnabled: true,
    isOffscreen: false,
    isPassword: false,
    bounds: { screenBox: { x: 118, y: 96, width: 42, height: 22 }, dpi: 120 },
    patterns: ['Invoke'],
    windowId: '394820',
    pid: 4,
    processName: 'notepad.exe',
    elementToken: 'tok-1',
    generation: 2,
    sourceId: 'src-1',
    frameId: 'f-1',
    geometryRevision: 7,
    label,
    ...overrides,
  }
}

function ctxOf(
  result: DomInspectResult | UiaInspectResult | DesktopInspectResult,
  point = { x: 812, y: 344 },
): InspectedElementContext {
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

describe('inspectChipLabel — uia', () => {
  const fallback = 'UIA element'

  it('có name ⇒ dùng name', () => {
    expect(inspectChipLabel(uiaResult(), fallback)).toBe('Tệp')
  })

  it('name rỗng ⇒ lùi về controlType (control UIA không tên là chuyện thường)', () => {
    expect(inspectChipLabel(uiaResult({ name: '' }), fallback)).toBe('menu item')
  })

  it('name và controlType đều rỗng ⇒ nhãn dự phòng ĐÃ DỊCH', () => {
    expect(inspectChipLabel(uiaResult({ name: '', controlType: '' }), 'Phần tử UIA')).toBe('Phần tử UIA')
  })

  it('name dài ⇒ cắt còn 48 ký tự + dấu …', () => {
    const label = inspectChipLabel(uiaResult({ name: 'x'.repeat(80) }), fallback)
    expect(label).toHaveLength(49)
    expect(label.endsWith('…')).toBe(true)
  })
})

describe('formatInspectedElementForAgent — uia', () => {
  it('có nhánh UIA riêng, nói rõ dữ liệu màn hình không tin được', () => {
    const text = formatInspectedElementForAgent(ctxOf(uiaResult()))
    expect(text).toContain('Inspected element (UIA) — UNTRUSTED screen data')
    expect(text).toContain('Name: Tệp')
    expect(text).toContain('Control type: menu item')
    expect(text).toContain('Class: MenuItem')
    expect(text).toContain('Automation ID: FileMenu')
    expect(text).toContain('Bounds (screen): x 118 · y 96 · 42 × 22')
    expect(text).toContain('Patterns: Invoke')
    expect(text).toContain('Enabled: yes · Offscreen: no')
    expect(text).toContain('Process: notepad.exe')
    expect(text).toContain('Window id: 394820')
    expect(text).toContain('Clicked point (framebuffer): (812, 344)')
  })

  it('ô mật khẩu ⇒ có câu nói rõ nội dung không bao giờ bị đọc/điều khiển', () => {
    const text = formatInspectedElementForAgent(ctxOf(uiaResult({ isPassword: true })))
    expect(text).toContain('Password field: content is never read or driven.')
  })

  it('không mật khẩu ⇒ không có câu đó', () => {
    expect(formatInspectedElementForAgent(ctxOf(uiaResult()))).not.toContain('Password field:')
  })

  it('phần tử bị tắt / ngoài màn hình ⇒ cờ nói đúng', () => {
    const text = formatInspectedElementForAgent(ctxOf(uiaResult({ isEnabled: false, isOffscreen: true })))
    expect(text).toContain('Enabled: no · Offscreen: yes')
  })

  it('trường rỗng thì bỏ dòng, không in nhãn trống', () => {
    const text = formatInspectedElementForAgent(
      ctxOf(uiaResult({ className: '', automationId: '', helpText: '', patterns: [], processName: undefined, windowId: '' })),
    )
    expect(text).not.toContain('Class:')
    expect(text).not.toContain('Automation ID:')
    expect(text).not.toContain('Patterns:')
    expect(text).not.toContain('Process:')
    expect(text).not.toContain('Window id:')
  })

  it('escaping fence chạy trên MỌI chuỗi do ứng dụng kiểm soát (name/class/helpText)', () => {
    const text = formatInspectedElementForAgent(
      ctxOf(uiaResult({ name: 'a```b', className: '```', helpText: 'x```y', patterns: ['````'] })),
    )
    expect(text).not.toMatch(/`{3,}/)
  })
})
