/**
 * Test (c): hàm quyết định số nút trên PermissionCard.
 * Bẩn → 4 nút, Sạch → 3 nút.
 */
import { describe, it, expect } from 'vitest'
import { getPermissionButtons } from './permissions'

describe('getPermissionButtons', () => {
  it('context clean → 3 buttons, no chuan_thuan_artifact', () => {
    const buttons = getPermissionButtons(false)
    expect(buttons).toHaveLength(3)
    expect(buttons).not.toContain('chuan_thuan_artifact')
    expect(buttons).toContain('cho_phep_mot_lan')
    expect(buttons).toContain('cap_giay_phep')
    expect(buttons).toContain('tu_choi')
  })

  it('context dirty → 4 buttons, includes chuan_thuan_artifact', () => {
    const buttons = getPermissionButtons(true)
    expect(buttons).toHaveLength(4)
    expect(buttons).toContain('chuan_thuan_artifact')
    expect(buttons).toContain('cho_phep_mot_lan')
    expect(buttons).toContain('cap_giay_phep')
    expect(buttons).toContain('tu_choi')
  })
})
