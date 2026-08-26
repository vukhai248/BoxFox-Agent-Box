import { describe, expect, it } from 'vitest'
import { DEFAULT_BOX_TTY_URL, resolveBoxTtyUrl } from './config'

describe('resolveBoxTtyUrl', () => {
  it('mặc định đi qua ide-proxy, không mở port mới', () => {
    expect(resolveBoxTtyUrl({})).toBe(DEFAULT_BOX_TTY_URL)
    expect(DEFAULT_BOX_TTY_URL).toContain(':8081/__tty/ws')
  })

  it('ưu tiên biến env tường minh', () => {
    expect(
      resolveBoxTtyUrl({ VITE_BOX_TTY_URL: 'ws://10.0.0.5:8081/__tty/ws' }),
    ).toBe('ws://10.0.0.5:8081/__tty/ws')
  })
})
