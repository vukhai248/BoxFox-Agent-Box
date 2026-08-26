import { describe, it, expect } from 'vitest'
import {
  IDE_MAX_ATTEMPTS,
  IDE_RETRY_DELAYS_MS,
  ideRetryDelayMs,
  initialIdeState,
  offIdeState,
  reduceIde,
  type IdeState,
} from './state'

/** Đưa máy trạng thái tới lượt thất bại thứ `n` (n = 1 là lần đầu). */
function afterFailures(n: number): IdeState {
  let state = initialIdeState
  for (let i = 0; i < n; i++) {
    if (i > 0) state = reduceIde(state, { type: 'probeStarted' })
    state = reduceIde(state, { type: 'failed', reason: 'unreachable' })
  }
  return state
}

describe('reduceIde', () => {
  it('trạng thái đầu là probing, chưa có lý do gì', () => {
    expect(initialIdeState.phase).toBe('probing')
    expect(initialIdeState.reason).toBe(null)
  })

  it('reachable → live và trả ngân sách thử lại về đầy', () => {
    const state = reduceIde(afterFailures(2), { type: 'probeStarted' })
    const live = reduceIde(state, { type: 'reachable' })
    expect(live.phase).toBe('live')
    expect(live.attempt).toBe(1)
    expect(live.exhausted).toBe(false)
  })

  it('probeStarted từ offline mới tăng attempt; từ probing thì không', () => {
    const failed = afterFailures(1)
    expect(failed.attempt).toBe(1)
    const again = reduceIde(failed, { type: 'probeStarted' })
    expect(again.attempt).toBe(2)
    // Đang probing mà lại probeStarted (StrictMode chạy effect hai lần) → không đốt lượt.
    expect(reduceIde(again, { type: 'probeStarted' }).attempt).toBe(2)
  })

  it('mỗi probeStarted bump seq để hook mở một lượt thăm dò mới', () => {
    const a = reduceIde(initialIdeState, { type: 'probeStarted' })
    expect(a.seq).toBe(initialIdeState.seq + 1)
    expect(reduceIde(a, { type: 'manualRetry' }).seq).toBe(a.seq + 1)
  })

  it('hết IDE_MAX_ATTEMPTS lượt → exhausted, không tự thử nữa', () => {
    const last = afterFailures(IDE_MAX_ATTEMPTS)
    expect(last.attempt).toBe(IDE_MAX_ATTEMPTS)
    expect(last.exhausted).toBe(true)
    expect(ideRetryDelayMs(last)).toBe(null)
  })

  it('chưa hết lượt → còn khoảng nghỉ, lấy đúng theo thứ tự IDE_RETRY_DELAYS_MS', () => {
    expect(ideRetryDelayMs(afterFailures(1))).toBe(IDE_RETRY_DELAYS_MS[0])
    expect(ideRetryDelayMs(afterFailures(2))).toBe(IDE_RETRY_DELAYS_MS[1])
    expect(ideRetryDelayMs(afterFailures(3))).toBe(IDE_RETRY_DELAYS_MS[2])
  })

  it('mixedContent là lý do chết hẳn: exhausted ngay lượt đầu', () => {
    const state = reduceIde(initialIdeState, { type: 'failed', reason: 'mixedContent' })
    expect(state.phase).toBe('offline')
    expect(state.exhausted).toBe(true)
    expect(ideRetryDelayMs(state)).toBe(null)
  })

  it('thất bại lần hai trong cùng một lượt không đẩy trạng thái đi tiếp', () => {
    const failed = afterFailures(1)
    expect(reduceIde(failed, { type: 'failed', reason: 'timeout' })).toBe(failed)
  })

  it('manualRetry đặt lại attempt về 1 kể cả khi đã exhausted', () => {
    const retried = reduceIde(afterFailures(IDE_MAX_ATTEMPTS), { type: 'manualRetry' })
    expect(retried.phase).toBe('probing')
    expect(retried.attempt).toBe(1)
    expect(retried.exhausted).toBe(false)
  })

  it('offIdeState: offline vì bị tắt, không phải vì lỗi, và không thử lại', () => {
    expect(offIdeState.phase).toBe('offline')
    expect(offIdeState.reason).toBe('off')
    expect(offIdeState.exhausted).toBe(true)
    expect(ideRetryDelayMs(offIdeState)).toBe(null)
  })

  it('manualRetry khi nguồn đang tắt → không đổi gì (nếu đổi sẽ treo ở probing mãi)', () => {
    // Nguồn `off` thì hook không bao giờ fetch, nên chuyển sang probing là ngõ cụt.
    expect(reduceIde(offIdeState, { type: 'manualRetry' })).toBe(offIdeState)
  })

  it('ideRetryDelayMs chỉ có giá trị ở phase offline', () => {
    expect(ideRetryDelayMs(initialIdeState)).toBe(null)
    expect(ideRetryDelayMs(reduceIde(initialIdeState, { type: 'reachable' }))).toBe(null)
  })
})
