import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it } from 'vitest'
import { useElementInspector, type UseElementInspectorResult } from './useElementInspector'
import type { InspectRepository } from '../lib/inspect'
import type { InspectElementRequest, InspectElementResult } from '../types/inspect'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let roots: Root[] = []

function domResult(): InspectElementResult {
  return {
    type: 'dom',
    selector: 'span',
    url: 'http://localhost:3100/',
    title: 't',
    tagName: 'span',
    text: 'boxfox',
    attributes: {},
    html: '<span>boxfox</span>',
    truncated: false,
    cssBox: { x: 0, y: 0, width: 1, height: 1 },
    screenBox: { x: 0, y: 0, width: 1, height: 1 },
    target: { windowId: 'w1', windowTitle: 'title', targetId: 't1' },
    label: {
      integrity: 'khong_tin_duoc',
      confidentiality: 'noi_bo',
      source_kind: 'screen_capture',
      source_uri: 'screen://element/w1',
      tool_name: 'inspect_element',
      content_hash: 'sha256:x',
    },
  }
}

/** Repository giả — kiểm soát tay thời điểm resolve/reject để test race và huỷ. */
class DeferredRepository implements InspectRepository {
  calls: { point: InspectElementRequest; signal?: AbortSignal }[] = []
  private pending: { resolve: (r: InspectElementResult) => void; reject: (e: unknown) => void }[] = []

  inspect(point: InspectElementRequest, signal?: AbortSignal): Promise<InspectElementResult> {
    this.calls.push({ point, signal })
    return new Promise((resolve, reject) => {
      this.pending.push({ resolve, reject })
      signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
    })
  }

  resolveNth(index: number, result: InspectElementResult) {
    this.pending[index]?.resolve(result)
  }

  rejectNth(index: number, error: unknown) {
    this.pending[index]?.reject(error)
  }
}

async function mount(repo?: InspectRepository) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  let latest: UseElementInspectorResult | null = null

  function Probe() {
    latest = useElementInspector(repo)
    return null
  }

  await act(async () => {
    root.render(<Probe />)
  })

  return {
    get state() {
      if (!latest) throw new Error('Hook did not render.')
      return latest
    },
  }
}

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
})

describe('useElementInspector', () => {
  it('bắt đầu tắt chế độ chọn và không có ngăn kéo', async () => {
    const hook = await mount(new DeferredRepository())
    expect(hook.state.armed).toBe(false)
    expect(hook.state.drawer).toBeNull()
  })

  it('toggleArmed lật trạng thái lên nòng', async () => {
    const hook = await mount(new DeferredRepository())
    await act(async () => hook.state.toggleArmed())
    expect(hook.state.armed).toBe(true)
    await act(async () => hook.state.toggleArmed())
    expect(hook.state.armed).toBe(false)
  })

  it('handlePick tắt armed ngay (Q5) và mở ngăn kéo ở trạng thái loading', async () => {
    const repo = new DeferredRepository()
    const hook = await mount(repo)
    await act(async () => hook.state.toggleArmed())
    expect(hook.state.armed).toBe(true)

    await act(async () => hook.state.handlePick({ x: 10, y: 20 }))
    expect(hook.state.armed).toBe(false)
    expect(hook.state.drawer).toEqual({ status: 'loading', point: { x: 10, y: 20 } })
  })

  it('khi inspect() thành công, ngăn kéo chuyển sang success với đúng kết quả', async () => {
    const repo = new DeferredRepository()
    const hook = await mount(repo)
    const result = domResult()

    await act(async () => hook.state.handlePick({ x: 1, y: 2 }))
    await act(async () => {
      repo.resolveNth(0, result)
      await Promise.resolve()
    })

    expect(hook.state.drawer).toEqual({ status: 'success', point: { x: 1, y: 2 }, result })
  })

  it('khi inspect() thất bại, ngăn kéo chuyển sang error kèm lỗi gốc', async () => {
    const repo = new DeferredRepository()
    const hook = await mount(repo)
    const err = new Error('boom')

    await act(async () => hook.state.handlePick({ x: 1, y: 2 }))
    await act(async () => {
      repo.rejectNth(0, err)
      await Promise.resolve().catch(() => {})
    })

    expect(hook.state.drawer).toEqual({ status: 'error', point: { x: 1, y: 2 }, error: err })
  })

  it('điểm bấm mới huỷ lượt gọi cũ — kết quả cũ resolve muộn không ghi đè kết quả mới', async () => {
    const repo = new DeferredRepository()
    const hook = await mount(repo)

    await act(async () => hook.state.handlePick({ x: 1, y: 1 }))
    await act(async () => hook.state.handlePick({ x: 2, y: 2 }))
    expect(repo.calls[0].signal?.aborted).toBe(true)

    const secondResult = domResult()
    await act(async () => {
      repo.resolveNth(1, secondResult)
      await Promise.resolve()
    })
    // Resolve muộn của lượt đầu (đã bị abort) không được ghi đè trạng thái hiện tại.
    await act(async () => {
      repo.resolveNth(0, domResult())
      await Promise.resolve().catch(() => {})
    })

    expect(hook.state.drawer).toEqual({ status: 'success', point: { x: 2, y: 2 }, result: secondResult })
  })

  it('closeDrawer đóng ngăn kéo và huỷ lượt gọi đang chạy', async () => {
    const repo = new DeferredRepository()
    const hook = await mount(repo)

    await act(async () => hook.state.handlePick({ x: 1, y: 1 }))
    await act(async () => hook.state.closeDrawer())

    expect(hook.state.drawer).toBeNull()
    expect(repo.calls[0].signal?.aborted).toBe(true)
  })

  it('retry gọi lại đúng điểm vừa lỗi', async () => {
    const repo = new DeferredRepository()
    const hook = await mount(repo)

    await act(async () => hook.state.handlePick({ x: 5, y: 6 }))
    await act(async () => {
      repo.rejectNth(0, new Error('fail'))
      await Promise.resolve().catch(() => {})
    })
    expect(hook.state.drawer?.status).toBe('error')

    await act(async () => hook.state.retry())
    expect(hook.state.drawer).toEqual({ status: 'loading', point: { x: 5, y: 6 } })
    expect(repo.calls).toHaveLength(2)
    expect(repo.calls[1].point).toEqual({ x: 5, y: 6 })
  })

  it('disarm tắt chế độ chọn mà không đụng ngăn kéo', async () => {
    const repo = new DeferredRepository()
    const hook = await mount(repo)
    await act(async () => hook.state.toggleArmed())
    await act(async () => hook.state.disarm())
    expect(hook.state.armed).toBe(false)
  })

  it('unmount huỷ lượt gọi đang chạy', async () => {
    const repo = new DeferredRepository()
    const host = document.createElement('div')
    document.body.append(host)
    const root = createRoot(host)
    let latest: UseElementInspectorResult | null = null

    function Probe() {
      latest = useElementInspector(repo)
      return null
    }

    await act(async () => {
      root.render(<Probe />)
    })
    await act(async () => latest!.handlePick({ x: 1, y: 1 }))
    await act(async () => root.unmount())

    expect(repo.calls[0].signal?.aborted).toBe(true)
    host.remove()
  })

  it('dùng createInspectRepository() làm mặc định khi không truyền repository', async () => {
    const hook = await mount()
    expect(hook.state.armed).toBe(false)
    expect(hook.state.drawer).toBeNull()
  })
})
