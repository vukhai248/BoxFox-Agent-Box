/**
 * Đảm bảo 5 key `composer.*` mới (placeholder, placeholderShort, quickAsk,
 * autopilot, autopilotHint) tồn tại và không rỗng ở cả hai locale — thiếu
 * key ở `vi.ts` đã bị chặn ở compile time (xem `context.ts`), nhưng test
 * này còn chặn cả trường hợp giá trị rỗng lọt qua.
 */
import { describe, it, expect } from 'vitest'
import en from './en'
import vi from './vi'

const COMPOSER_KEYS = ['placeholder', 'placeholderShort', 'quickAsk', 'autopilot', 'autopilotHint', 'uploadingAttachments', 'sendSteer', 'steerHint', 'steerQueued'] as const

describe('composer i18n keys', () => {
  it.each(COMPOSER_KEYS)('en.composer.%s tồn tại và không rỗng', (key) => {
    expect(en.composer[key]).toBeTypeOf('string')
    expect(en.composer[key].length).toBeGreaterThan(0)
  })

  it.each(COMPOSER_KEYS)('vi.composer.%s tồn tại và không rỗng', (key) => {
    expect(vi.composer[key]).toBeTypeOf('string')
    expect(vi.composer[key].length).toBeGreaterThan(0)
  })

  // Trục mạng (đợt 1b): nhãn phải nói đây là câu hỏi trước khi ra mạng, không phải tường lửa —
  // người dùng phải hiểu đúng phạm vi bảo vệ trước khi tắt nó.
  it('giữ nguyên văn nhãn trục mạng ở bản tiếng Việt', () => {
    expect(vi.composer.permission.sectionNetwork).toBe('Mạng')
    expect(vi.composer.permission.network.restricted).toBe('Hỏi trước khi ra mạng')
    expect(vi.composer.permission.network.enabled).toBe('Cho phép ra mạng')
  })

  it.each(['vi', 'en'] as const)('%s: nhãn và gợi ý trục mạng đều không rỗng', (locale) => {
    const pack = locale === 'vi' ? vi : en
    const permission = pack.composer.permission
    expect(permission.sectionNetwork.length).toBeGreaterThan(0)
    expect(permission.network.restricted.length).toBeGreaterThan(0)
    expect(permission.network.enabled.length).toBeGreaterThan(0)
    expect(permission.hint.networkRestricted.length).toBeGreaterThan(0)
    expect(permission.hint.networkEnabled.length).toBeGreaterThan(0)
    expect(permission.scopeHint.workspace.length).toBeGreaterThan(0)
    expect(permission.scopeHint.machine.length).toBeGreaterThan(0)
  })

  // Vòng 27 / C-5 — ba câu này là hợp đồng với kế hoạch (đợt 7): nút Gửi khi lượt đang chạy,
  // dòng gợi ý dưới ô nhập, và dòng xác nhận sau khi chỉ thị đã vào hàng.
  it('giữ nguyên văn ba câu chỉ thị giữa lượt ở bản tiếng Việt', () => {
    expect(vi.composer.sendSteer).toBe('Gửi cho lượt đang chạy')
    expect(vi.composer.steerHint).toBe('áp dụng ở bước kế tiếp')
    expect(vi.composer.steerQueued).toBe('đã xếp hàng · sẽ áp ở bước kế')
  })
})
