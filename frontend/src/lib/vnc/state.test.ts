/**
 * Test cho máy trạng thái noVNC (logic thuần, không DOM).
 *
 * Vòng đời kết nối thật được test riêng ở `attempt.test.ts`.
 */
import { describe, it, expect } from 'vitest'
import {
  disabledVncState,
  initialVncState,
  reduceVnc,
  retryDelayMs,
  VNC_MAX_ATTEMPTS,
  type VncState,
} from './state'

describe('initialVncState', () => {
  it('bắt đầu ở connecting, attempt = 1, seq = 0', () => {
    expect(initialVncState.phase).toBe('connecting')
    expect(initialVncState.attempt).toBe(1)
    expect(initialVncState.seq).toBe(0)
    expect(initialVncState.exhausted).toBe(false)
  })
})

describe('reduceVnc', () => {
  it('connected → live, reason = null, attempt về 1', () => {
    const next = reduceVnc(initialVncState, { type: 'connected' })
    expect(next.phase).toBe('live')
    expect(next.reason).toBeNull()
    expect(next.attempt).toBe(1)
    expect(next.exhausted).toBe(false)
  })

  it('timeout ở lần 1 → offline/timeout, chưa exhausted, retryDelayMs = 3000', () => {
    const next = reduceVnc(initialVncState, { type: 'timeout' })
    expect(next.phase).toBe('offline')
    expect(next.reason).toBe('timeout')
    expect(next.exhausted).toBe(false)
    expect(retryDelayMs(next)).toBe(3000)
  })

  it('chuỗi timeout → connectStarted → timeout → connectStarted → timeout cho khoảng nghỉ đúng 3000, 8000, 20000', () => {
    let state: VncState = initialVncState
    state = reduceVnc(state, { type: 'timeout' })
    expect(retryDelayMs(state)).toBe(3000)
    state = reduceVnc(state, { type: 'connectStarted' })
    state = reduceVnc(state, { type: 'timeout' })
    expect(retryDelayMs(state)).toBe(8000)
    state = reduceVnc(state, { type: 'connectStarted' })
    state = reduceVnc(state, { type: 'timeout' })
    expect(retryDelayMs(state)).toBe(20000)
  })

  it('tới lần thứ 4 thất bại → exhausted = true, retryDelayMs = null', () => {
    let state: VncState = initialVncState
    for (let i = 0; i < VNC_MAX_ATTEMPTS; i++) {
      state = reduceVnc(state, { type: 'timeout' })
      if (i < VNC_MAX_ATTEMPTS - 1) {
        state = reduceVnc(state, { type: 'connectStarted' })
      }
    }
    expect(state.exhausted).toBe(true)
    expect(retryDelayMs(state)).toBeNull()
  })

  it('kênh đang live bị phía kia đóng → vẫn còn nguyên ngân sách 3 lượt thử lại (D-7)', () => {
    const live = reduceVnc(initialVncState, { type: 'connected' })
    const next = reduceVnc(live, { type: 'closed' })
    expect(next.phase).toBe('offline')
    expect(next.reason).toBe('closed')
    expect(next.attempt).toBe(1)
    expect(next.exhausted).toBe(false)
    expect(retryDelayMs(next)).toBe(3000)
  })

  it('closed khi đang offline → trả về đúng object cũ (không đổi lý do)', () => {
    const offline = reduceVnc(initialVncState, { type: 'timeout' })
    const next = reduceVnc(offline, { type: 'closed' })
    expect(next).toBe(offline)
  })

  it("failed: các lý do cấu hình/khả năng → exhausted = true, thử lại vô nghĩa", () => {
    for (const reason of [
      'security',
      'credentials',
      'mixedContent',
      'insecureContext',
      'unsupported',
    ] as const) {
      const next = reduceVnc(initialVncState, { type: 'failed', reason })
      expect(next.phase).toBe('offline')
      expect(next.reason).toBe(reason)
      expect(next.exhausted).toBe(true)
    }
  })

  it("skip → offline/skipped, exhausted = true; manualRetry sau đó → connecting, attempt = 1, seq tăng", () => {
    const skipped = reduceVnc(initialVncState, { type: 'skip' })
    expect(skipped.phase).toBe('offline')
    expect(skipped.reason).toBe('skipped')
    expect(skipped.exhausted).toBe(true)

    const retried = reduceVnc(skipped, { type: 'manualRetry' })
    expect(retried.phase).toBe('connecting')
    expect(retried.attempt).toBe(1)
    expect(retried.exhausted).toBe(false)
    expect(retried.seq).toBeGreaterThan(skipped.seq)
  })
})

describe('disabledVncState', () => {
  it('nguồn mô phỏng: offline/disabled, không hẹn thử lại', () => {
    expect(disabledVncState.phase).toBe('offline')
    expect(disabledVncState.reason).toBe('disabled')
    expect(disabledVncState.exhausted).toBe(true)
    expect(retryDelayMs(disabledVncState)).toBeNull()
  })
})
