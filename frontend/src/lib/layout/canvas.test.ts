import { describe, expect, it } from 'vitest'
import { CANVAS_TOOLBAR_COMPACT_MAX_PX, isCompactCanvasToolbar } from './canvas'

describe('isCompactCanvasToolbar', () => {
  it('0 = chưa layout → false (không nháy compact sớm)', () => {
    expect(isCompactCanvasToolbar(0)).toBe(false)
  })

  it('dưới ngưỡng → compact', () => {
    expect(isCompactCanvasToolbar(200)).toBe(true)
    expect(isCompactCanvasToolbar(CANVAS_TOOLBAR_COMPACT_MAX_PX - 1)).toBe(true)
  })

  it('đúng ngưỡng trở lên → full', () => {
    expect(isCompactCanvasToolbar(CANVAS_TOOLBAR_COMPACT_MAX_PX)).toBe(false)
    expect(isCompactCanvasToolbar(CANVAS_TOOLBAR_COMPACT_MAX_PX + 1)).toBe(false)
    expect(isCompactCanvasToolbar(1200)).toBe(false)
  })
})
