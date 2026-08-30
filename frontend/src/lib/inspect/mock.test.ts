import { describe, expect, it } from 'vitest'
import { MOCK_VIEWPORT, MockInspectRepository } from './mock'
import { parseInspectElementResult } from './parse'

describe('MockInspectRepository', () => {
  it('điểm trong viewport (nửa trái) ⇒ nhánh dom có class trong attributes', async () => {
    const repo = new MockInspectRepository(0)
    const result = await repo.inspect({ x: MOCK_VIEWPORT.x + 10, y: MOCK_VIEWPORT.y + 10 })
    expect(result.type).toBe('dom')
    expect(result.type === 'dom' && result.attributes.class).toBeTruthy()
  })

  it('điểm trong viewport (nửa phải) ⇒ nhánh dom KHÔNG có attributes (selector trơn)', async () => {
    const repo = new MockInspectRepository(0)
    const result = await repo.inspect({
      x: MOCK_VIEWPORT.x + MOCK_VIEWPORT.width - 10,
      y: MOCK_VIEWPORT.y + 10,
    })
    expect(result.type).toBe('dom')
    expect(result.type === 'dom' && Object.keys(result.attributes).length).toBe(0)
    expect(result.type === 'dom' && result.selector).toBe('span')
  })

  it('điểm ngoài viewport ⇒ nhánh desktop với message chính xác', async () => {
    const repo = new MockInspectRepository(0)
    const result = await repo.inspect({ x: MOCK_VIEWPORT.x, y: 10 })
    expect(result.type).toBe('desktop')
    expect(result.type === 'desktop' && result.message).toContain('element inspect: Click outside viewport')
  })

  it('mọi kết quả đều đi qua parseInspectElementResult mà không thành null', async () => {
    const repo = new MockInspectRepository(0)
    const inViewport = await repo.inspect({ x: MOCK_VIEWPORT.x + 10, y: MOCK_VIEWPORT.y + 10 })
    const outsideViewport = await repo.inspect({ x: MOCK_VIEWPORT.x, y: 10 })
    expect(parseInspectElementResult(inViewport)).not.toBeNull()
    expect(parseInspectElementResult(outsideViewport)).not.toBeNull()
  })

  it('tôn trọng signal đã abort ngay từ đầu', async () => {
    const controller = new AbortController()
    controller.abort()
    const repo = new MockInspectRepository(1000)
    await expect(repo.inspect({ x: 1, y: 1 }, controller.signal)).rejects.toMatchObject({ name: 'AbortError' })
  })
})
