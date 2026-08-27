/**
 * Đảm bảo 5 key `composer.*` mới (placeholder, placeholderShort, quickAsk,
 * autopilot, autopilotHint) tồn tại và không rỗng ở cả hai locale — thiếu
 * key ở `vi.ts` đã bị chặn ở compile time (xem `context.ts`), nhưng test
 * này còn chặn cả trường hợp giá trị rỗng lọt qua.
 */
import { describe, it, expect } from 'vitest'
import en from './en'
import vi from './vi'

const COMPOSER_KEYS = ['placeholder', 'placeholderShort', 'quickAsk', 'autopilot', 'autopilotHint'] as const

describe('composer i18n keys', () => {
  it.each(COMPOSER_KEYS)('en.composer.%s tồn tại và không rỗng', (key) => {
    expect(en.composer[key]).toBeTypeOf('string')
    expect(en.composer[key].length).toBeGreaterThan(0)
  })

  it.each(COMPOSER_KEYS)('vi.composer.%s tồn tại và không rỗng', (key) => {
    expect(vi.composer[key]).toBeTypeOf('string')
    expect(vi.composer[key].length).toBeGreaterThan(0)
  })
})
