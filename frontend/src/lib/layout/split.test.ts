import { describe, it, expect } from 'vitest'
import { clampSplitRatio } from './split'

describe('clampSplitRatio', () => {
  it('container 920, minChat 400 → sàn chat giữ đúng 400px khi x rất nhỏ', () => {
    // width*0.45 = 414 > 400 nên luật 45% KHÔNG hạ sàn chat ở đây.
    const ratio = clampSplitRatio(-1000, 920, 400, 480)
    expect(ratio).toBeCloseTo(400 / 920, 6)
  })

  it('container 920, minWorkspace 480 → luật 45% hạ sàn workspace xuống 414px (920*0.45) khi x rất lớn', () => {
    // width*0.45 = 414 < 480 nên min(480, 414) = 414 mới là sàn thật áp dụng —
    // đúng công thức gốc ở Resizer.tsx (giữ nguyên, không đổi).
    const ratio = clampSplitRatio(10_000, 920, 400, 480)
    expect(ratio).toBeCloseTo((920 - 414) / 920, 6)
  })

  it('container 700 → luật 45% có hiệu lực cho cả hai phía (315px = 700*0.45 < cả 400 và 480)', () => {
    const lower = clampSplitRatio(-1000, 700, 400, 480)
    const upper = clampSplitRatio(10_000, 700, 400, 480)
    expect(lower).toBeCloseTo(0.45, 6)
    expect(upper).toBeCloseTo(0.55, 6)
  })

  it('container 0 → không NaN, trả về 0', () => {
    expect(clampSplitRatio(100, 0, 400, 480)).toBe(0)
    expect(Number.isNaN(clampSplitRatio(100, 0, 400, 480))).toBe(false)
  })

  it('x nằm giữa vùng cho phép → giữ nguyên, không bị kẹp', () => {
    const ratio = clampSplitRatio(460, 920, 400, 480)
    expect(ratio).toBeCloseTo(460 / 920, 6)
  })
})
