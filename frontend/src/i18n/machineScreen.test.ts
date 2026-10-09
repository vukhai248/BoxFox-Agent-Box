/**
 * Test khoá i18n của panel "Màn hình máy".
 *
 * Vì sao có tệp riêng thay vì tin vào `tsc`: `en.ts` được khai `SameShape<typeof vi>`
 * nên thiếu khoá là lỗi biên dịch, nhưng HAI thứ `tsc` không bắt được:
 *   - chuỗi RỖNG (khoá tồn tại nhưng người dùng thấy khoảng trắng);
 *   - khoá bị đặt vào nhánh sai (ví dụ `hostError` lồng trong `machineScreen`),
 *     vẫn đủ kiểu nhưng `lookup('hostError.HUMAN_HAS_CONTROL')` trả `undefined`
 *     và ngăn kéo in ra chính chuỗi khoá.
 *
 * Tệp cũng chốt NGUYÊN VĂN vài câu an toàn: đây là những câu nói với người dùng
 * rằng panel chỉ xem / rằng agent không thể tự vượt quyền — đổi chữ ở đây là đổi
 * một lời hứa, phải là quyết định có chủ ý chứ không phải trôi theo refactor.
 */
import { describe, expect, it } from 'vitest'
import vi from './vi'
import en from './en'
import { lookup } from './context'

/** Mọi đường dẫn tới lá chuỗi của một object lồng nhau. */
function leafKeys(node: unknown, prefix = ''): string[] {
  if (typeof node !== 'object' || node === null) return []
  const out: string[] = []
  for (const [key, value] of Object.entries(node as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key
    if (typeof value === 'string') out.push(path)
    else out.push(...leafKeys(value, path))
  }
  return out
}

const LOCALES: [string, unknown][] = [
  ['vi', vi],
  ['en', en],
]

describe('cây khoá của panel Màn hình máy', () => {
  it('mọi khoá `machineScreen.*` có mặt và không rỗng ở CẢ HAI locale', () => {
    const viKeys = leafKeys((vi as Record<string, unknown>).machineScreen)
    const enKeys = leafKeys((en as Record<string, unknown>).machineScreen)
    expect(viKeys.length).toBeGreaterThan(50)
    expect(enKeys).toEqual(viKeys)
    for (const [lang, dict] of LOCALES) {
      for (const key of viKeys) {
        const value = lookup(dict, `machineScreen.${key}`)
        expect(value, `${lang}: machineScreen.${key}`).toBeTruthy()
        expect(value?.trim(), `${lang}: machineScreen.${key} chỉ có khoảng trắng`).not.toBe('')
      }
    }
  })

  it('mọi mã lỗi host mode có câu dịch ở cả hai locale', () => {
    // Danh sách viết thẳng ở đây (không import từ `lib/inspect/host.ts`) để một
    // lần xoá mã ở lớp HTTP cũng phải là một lần sửa test này.
    const codes = [
      'ELEMENT_STALE',
      'SOURCE_CHANGED',
      'SOURCE_IDENTITY_UNAVAILABLE',
      'CONTROL_BUSY',
      'DESKTOP_LOCKED',
      'HUMAN_HAS_CONTROL',
      'HUMAN_TOOK_OVER',
      'UIA_UNAVAILABLE',
      'UIA_TIMEOUT',
      'UIA_PROVIDER_HANG',
      'UIPI_BLOCKED',
      'SESSION_NOT_INTERACTIVE',
      'UNSUPPORTED_IN_HOST_MODE',
      'PASSWORD_FIELD_REFUSED',
      'WINDOW_MINIMIZED',
      'WINDOW_CLOAKED',
      'WINDOW_IDENTITY_UNAVAILABLE',
      'CAPTURE_FAILED',
      'OS_PERMISSION_REQUIRED',
      'INSPECT_POINT_INVALID',
      'INSPECT_FAILED',
    ]
    for (const [lang, dict] of LOCALES) {
      for (const code of codes) {
        expect(lookup(dict, `screen.inspector.drawer.hostError.${code}`), `${lang}: hostError.${code}`).toBeTruthy()
      }
    }
    expect(Object.keys((vi as { screen: { inspector: { drawer: { hostError: object } } } }).screen.inspector.drawer.hostError).sort()).toEqual([...codes].sort())
  })

  it('6 lý do Windows mới có câu dịch, và `not_chromium` vẫn còn (không xoá nhầm)', () => {
    const added = ['uia_unavailable', 'uia_timeout', 'uia_provider_hang', 'uia_no_element', 'no_window_at_point', 'window_identity_unavailable']
    for (const [lang, dict] of LOCALES) {
      for (const reason of added) {
        expect(lookup(dict, `screen.inspector.drawer.desktopReason.${reason}`), `${lang}: ${reason}`).toBeTruthy()
      }
      expect(lookup(dict, 'screen.inspector.drawer.desktopReason.not_chromium')).toBeTruthy()
    }
  })

  it('nhãn mới của nhánh UIA có mặt ở cả hai locale', () => {
    const keys = ['uiaTitle', 'uiaDisclaimer', 'nameLabel', 'controlTypeLabel', 'classLabel', 'automationIdLabel', 'boundsLabel', 'patternsLabel', 'uiaDisabled', 'uiaOffscreen', 'uiaPassword']
    for (const [lang, dict] of LOCALES) {
      expect(lookup(dict, 'screen.inspector.chipUiaFallback'), `${lang}: chipUiaFallback`).toBeTruthy()
      for (const key of keys) {
        expect(lookup(dict, `screen.inspector.drawer.${key}`), `${lang}: screen.inspector.drawer.${key}`).toBeTruthy()
      }
    }
  })
})

describe('nguyên văn những câu an toàn', () => {
  it('câu mô tả chế độ chọn nói rõ cú bấm KHÔNG tới máy', () => {
    expect(lookup(vi, 'machineScreen.selectElementHint')).toBe(
      'Bấm vào một phần tử trong ảnh để thanh tra. Bấm Esc để thoát.',
    )
    expect(lookup(vi, 'machineScreen.noteSelectArmed')).toContain('không gửi gì tới máy')
    expect(lookup(en, 'machineScreen.selectElementHint')).toBe('Click an element in the image to inspect it. Press Esc to exit.')
    expect(lookup(en, 'machineScreen.noteSelectArmed')).toContain('nothing is sent to the machine')
  })

  it('câu khoá lựa chọn "Cả máy" nói rõ thiếu phạm vi quyền nào', () => {
    expect(lookup(vi, 'machineScreen.wholeMachineLocked')).toBe('Cần phạm vi quyền Cả máy.')
    expect(lookup(en, 'machineScreen.wholeMachineLocked')).toBe('Needs the Whole machine permission scope.')
  })

  it('câu khoá nút chọn phần tử khi người dùng giữ quyền nói đúng việc phải làm', () => {
    expect(lookup(vi, 'machineScreen.selectElementLeaseLocked')).toBe('Trả quyền cho agent trước khi chọn phần tử.')
    expect(lookup(en, 'machineScreen.selectElementLeaseLocked')).toBe('Hand control back to the agent before selecting an element.')
  })

  it('ảnh chụp luôn được gọi đúng tên: dữ liệu không tin được', () => {
    expect(lookup(vi, 'machineScreen.snapshotUntrusted')).toContain('không tin được')
    expect(lookup(en, 'machineScreen.snapshotUntrusted')).toContain('untrusted')
  })
})
