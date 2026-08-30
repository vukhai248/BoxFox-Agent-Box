import { describe, expect, it } from 'vitest'
import { parseInspectElementResult, parseInspectErrorBody } from './parse'
import { INSPECTED_ELEMENT_CONFIDENTIALITY, INSPECTED_ELEMENT_TOOL } from './chunk'

function validDomPayload(overrides: Record<string, unknown> = {}) {
  return {
    type: 'dom',
    selector: 'span.text-sm',
    url: 'http://localhost:3100/',
    title: 'BoxFox',
    tagName: 'span',
    text: 'boxfox',
    html: '<span class="text-sm">boxfox</span>',
    truncated: false,
    attributes: { class: 'text-sm' },
    cssBox: { x: 1, y: 2, width: 3, height: 4 },
    screenBox: { x: 5, y: 6, width: 7, height: 8 },
    notes: ['shadow_dom'],
    shadowHostSelector: null,
    target: { windowId: '0x1', windowTitle: 'Win', targetId: 'tgt-1' },
    label: {
      integrity: 'duoc_nguoi_dung_cho_phep',
      confidentiality: 'noi_bo',
      source_kind: 'screen_capture',
      source_uri: 'screen://element/0x1',
      tool_name: 'inspect_element',
      content_hash: 'sha256:abc',
    },
    ...overrides,
  }
}

function validDesktopPayload(overrides: Record<string, unknown> = {}) {
  return {
    type: 'desktop',
    reason: 'outside_viewport',
    message: 'Click outside viewport',
    appName: 'google-chrome',
    windowClass: 'Chromium',
    windowTitle: 'Win',
    windowId: '0x1',
    position: { x: 0, y: 0 },
    size: { width: 100, height: 200 },
    pid: 42,
    label: {
      integrity: 'khong_tin_duoc',
      confidentiality: 'noi_bo',
      source_kind: 'screen_capture',
      source_uri: 'screen://element/0x1',
      tool_name: 'inspect_element',
      content_hash: '',
    },
    ...overrides,
  }
}

describe('parseInspectElementResult — dom', () => {
  it('parse payload dom hợp lệ giữ đủ trường', () => {
    const result = parseInspectElementResult(validDomPayload())
    expect(result).toMatchObject({
      type: 'dom',
      selector: 'span.text-sm',
      attributes: { class: 'text-sm' },
      notes: ['shadow_dom'],
      shadowHostSelector: null,
    })
  })

  it('bỏ qua khoá lạ ở cấp cao nhất', () => {
    const result = parseInspectElementResult(validDomPayload({ source: { file: 'x', line: 1, column: 2 } }))
    expect(result).not.toBeNull()
    expect(result).not.toHaveProperty('source')
  })

  it('selector sai kiểu ⇒ null', () => {
    expect(parseInspectElementResult(validDomPayload({ selector: 42 }))).toBeNull()
  })

  it('url sai kiểu ⇒ null', () => {
    expect(parseInspectElementResult(validDomPayload({ url: null }))).toBeNull()
  })

  it('truncated không phải boolean ⇒ mặc định false', () => {
    const result = parseInspectElementResult(validDomPayload({ truncated: 'yes' }))
    expect(result).toMatchObject({ truncated: false })
  })

  it('attributes không phải object ⇒ {}', () => {
    const result = parseInspectElementResult(validDomPayload({ attributes: 'nope' }))
    expect(result).toMatchObject({ attributes: {} })
  })

  it('attributes lọc bỏ giá trị không phải string', () => {
    const result = parseInspectElementResult(validDomPayload({ attributes: { a: 'ok', b: 42, c: null } }))
    expect(result).toMatchObject({ attributes: { a: 'ok' } })
  })

  it('cssBox/screenBox méo ⇒ về {0,0,0,0}', () => {
    const result = parseInspectElementResult(validDomPayload({ cssBox: null, screenBox: 'nope' }))
    expect(result).toMatchObject({
      cssBox: { x: 0, y: 0, width: 0, height: 0 },
      screenBox: { x: 0, y: 0, width: 0, height: 0 },
    })
  })

  it('target thiếu ⇒ ba khoá rỗng', () => {
    const result = parseInspectElementResult(validDomPayload({ target: undefined }))
    expect(result).toMatchObject({ target: { windowId: '', windowTitle: '', targetId: '' } })
  })

  it('notes không phải array ⇒ undefined', () => {
    const result = parseInspectElementResult(validDomPayload({ notes: 'nope' }))
    expect(result && 'notes' in result ? (result as { notes?: unknown }).notes : undefined).toBeUndefined()
  })

  it('notes lọc bỏ mã không thuộc bảng chuẩn', () => {
    const result = parseInspectElementResult(validDomPayload({ notes: ['shadow_dom', 'made_up'] }))
    expect(result).toMatchObject({ notes: ['shadow_dom'] })
  })

  it('shadowHostSelector string giữ nguyên, giá trị lạ ⇒ undefined', () => {
    const withString = parseInspectElementResult(validDomPayload({ shadowHostSelector: '#host' }))
    expect(withString).toMatchObject({ shadowHostSelector: '#host' })
    const withGarbage = parseInspectElementResult(validDomPayload({ shadowHostSelector: 42 }))
    expect((withGarbage as { shadowHostSelector?: unknown } | null)?.shadowHostSelector).toBeUndefined()
  })

  it('QUY TẮC M1 — integrity luôn khong_tin_duoc dù box trả giá trị khác', () => {
    const result = parseInspectElementResult(
      validDomPayload({ label: { ...validDomPayload().label, integrity: 'duoc_nguoi_dung_cho_phep' } }),
    )
    expect(result?.label.integrity).toBe('khong_tin_duoc')
  })

  it('label.confidentiality không hợp lệ ⇒ rơi về hằng dự phòng', () => {
    const result = parseInspectElementResult(
      validDomPayload({ label: { ...validDomPayload().label, confidentiality: 'made_up' } }),
    )
    expect(result?.label.confidentiality).toBe(INSPECTED_ELEMENT_CONFIDENTIALITY)
  })

  it('label.source_kind không hợp lệ ⇒ rơi về screen_capture', () => {
    const result = parseInspectElementResult(
      validDomPayload({ label: { ...validDomPayload().label, source_kind: 'made_up' } }),
    )
    expect(result?.label.source_kind).toBe('screen_capture')
  })

  it('label.tool_name rỗng ⇒ rơi về hằng dự phòng', () => {
    const result = parseInspectElementResult(validDomPayload({ label: { ...validDomPayload().label, tool_name: '' } }))
    expect(result?.label.tool_name).toBe(INSPECTED_ELEMENT_TOOL)
  })
})

describe('parseInspectElementResult — desktop', () => {
  it('parse payload desktop hợp lệ giữ đủ trường', () => {
    const result = parseInspectElementResult(validDesktopPayload())
    expect(result).toMatchObject({ type: 'desktop', reason: 'outside_viewport', windowId: '0x1' })
  })

  it('windowTitle/windowId sai kiểu ⇒ null', () => {
    expect(parseInspectElementResult(validDesktopPayload({ windowId: 99 }))).toBeNull()
  })

  it('reason lạ ⇒ undefined (không ném)', () => {
    const result = parseInspectElementResult(validDesktopPayload({ reason: 'made_up' }))
    expect((result as { reason?: unknown } | null)?.reason).toBeUndefined()
  })

  it('position/size méo ⇒ về mặc định 0', () => {
    const result = parseInspectElementResult(validDesktopPayload({ position: null, size: 'nope' }))
    expect(result).toMatchObject({ position: { x: 0, y: 0 }, size: { width: 0, height: 0 } })
  })

  it('pid sai kiểu ⇒ undefined', () => {
    const result = parseInspectElementResult(validDesktopPayload({ pid: 'nope' }))
    expect((result as { pid?: unknown } | null)?.pid).toBeUndefined()
  })
})

describe('parseInspectElementResult — chung', () => {
  it('payload không phải object ⇒ null', () => {
    expect(parseInspectElementResult('nope')).toBeNull()
    expect(parseInspectElementResult(null)).toBeNull()
    expect(parseInspectElementResult([1, 2, 3])).toBeNull()
  })

  it('type lạ ⇒ null', () => {
    expect(parseInspectElementResult({ type: 'made_up' })).toBeNull()
  })
})

describe('parseInspectErrorBody', () => {
  it('rút error string', () => {
    expect(parseInspectErrorBody({ error: 'Không tìm thấy' })).toBe('Không tìm thấy')
  })

  it('error sai kiểu ⇒ null', () => {
    expect(parseInspectErrorBody({ error: 42 })).toBeNull()
  })

  it('payload không phải object ⇒ null', () => {
    expect(parseInspectErrorBody('nope')).toBeNull()
    expect(parseInspectErrorBody(null)).toBeNull()
  })
})
