import { describe, it, expect } from 'vitest'
import { COMPOSER_COMPACT_MAX_PX, isCompactComposer } from './composer'

describe('isCompactComposer', () => {
  it('hằng số ngưỡng đúng như plan (dư 14px so với 626 cần cho chế độ đầy đủ)', () => {
    expect(COMPOSER_COMPACT_MAX_PX).toBe(640)
  })

  it('width = 0 (chưa layout) → false, không nháy compact lúc mount', () => {
    expect(isCompactComposer(0)).toBe(false)
  })

  it('381 < ngưỡng compact cần (382) nhưng vẫn < ngưỡng hằng số → true', () => {
    expect(isCompactComposer(381)).toBe(true)
  })

  it('487 (ngưỡng cần cho chế độ đầy đủ CŨ) vẫn < 640 → true (còn compact)', () => {
    expect(isCompactComposer(487)).toBe(true)
  })

  it('626 (ngưỡng cần cho chế độ đầy đủ, đã đo lại) vẫn < 640 → true', () => {
    expect(isCompactComposer(626)).toBe(true)
  })

  it('639 (ngay dưới ngưỡng) → true', () => {
    expect(isCompactComposer(639)).toBe(true)
  })

  it('640 (đúng ngưỡng) → false, biên là nửa-mở [0, 640)', () => {
    expect(isCompactComposer(640)).toBe(false)
  })

  it('900 (rộng thoải mái) → false', () => {
    expect(isCompactComposer(900)).toBe(false)
  })
})
