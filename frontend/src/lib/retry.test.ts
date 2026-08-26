/**
 * Test cho mẩu logic thử lại dùng chung (khung ④ và tab IDE cùng dùng).
 */
import { describe, it, expect } from 'vitest'
import { retrySecondsLeft } from './retry'

describe('retrySecondsLeft', () => {
  it('4.2s còn lại → 5 (làm tròn lên); quá hạn → 0 (không âm)', () => {
    expect(retrySecondsLeft(4200, 0)).toBe(5)
    expect(retrySecondsLeft(1000, 5000)).toBe(0)
  })
})
