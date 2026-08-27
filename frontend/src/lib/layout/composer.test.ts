import { describe, it, expect } from 'vitest'
import { COMPOSER_COMPACT_MAX_PX, isCompactComposer } from './composer'

describe('isCompactComposer', () => {
  it('hằng số ngưỡng đúng như plan (dư 13px so với 487 cần cho chế độ đầy đủ)', () => {
    expect(COMPOSER_COMPACT_MAX_PX).toBe(500)
  })

  it('width = 0 (chưa layout) → false, không nháy compact lúc mount', () => {
    expect(isCompactComposer(0)).toBe(false)
  })

  it('381 < ngưỡng compact cần (382) nhưng vẫn < ngưỡng hằng số → true', () => {
    expect(isCompactComposer(381)).toBe(true)
  })

  it('487 (ngưỡng cần cho chế độ đầy đủ) vẫn < 500 → true (còn compact)', () => {
    expect(isCompactComposer(487)).toBe(true)
  })

  it('499 (ngay dưới ngưỡng) → true', () => {
    expect(isCompactComposer(499)).toBe(true)
  })

  it('500 (đúng ngưỡng) → false, biên là nửa-mở [0, 500)', () => {
    expect(isCompactComposer(500)).toBe(false)
  })

  it('900 (rộng thoải mái) → false', () => {
    expect(isCompactComposer(900)).toBe(false)
  })
})
