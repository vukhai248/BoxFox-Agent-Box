import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useDesignCanvas, type DesignCanvas } from './useDesignCanvas'
import { boundsOfNode, PALETTE } from '../lib/canvas'
import { DESIGN_MODE_OFF } from '../lib/designMode'
import { useDesignStore } from '../store/designStore'

/** Mount hook bằng tạo root + component Probe (khuôn `useWorkspaceFiles.test.tsx`). */
function mount() {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  let latest: DesignCanvas | null = null

  function Probe() {
    latest = useDesignCanvas()
    return null
  }

  act(() => {
    root.render(<Probe />)
  })

  return {
    get state(): DesignCanvas {
      if (!latest) throw new Error('Hook did not render.')
      return latest
    },
    unmount() {
      act(() => root.unmount())
      host.remove()
    },
  }
}

const lastNodeId = (s: DesignCanvas) => s.scene.nodes[s.scene.nodes.length - 1].id

describe('useDesignCanvas', () => {
  it('addShape tạo node shape với style mặc định và kích thước mặc định', () => {
    const hook = mount()
    const before = hook.state.scene.nodes.length
    act(() => hook.state.addShape('rect'))
    const nodes = hook.state.scene.nodes
    expect(nodes).toHaveLength(before + 1)
    const created = nodes[nodes.length - 1]
    expect(created.kind).toBe('shape')
    expect(created.shape).toBe('rect')
    expect(created.style.stroke).toBe(PALETTE.brand)
    expect(created.width).toBe(160)
    expect(created.height).toBe(120)
    hook.unmount()
  })

  it('moveSelection dịch node theo delta và commit=true ghi history', () => {
    const hook = mount()
    act(() => hook.state.addShape('rect'))
    const id = lastNodeId(hook.state)
    const beforeX = hook.state.scene.nodes.find((n) => n.id === id)!.x
    act(() => hook.state.select(id))
    act(() => hook.state.moveSelection({ x: 10, y: 20 }, true))
    const n = hook.state.scene.nodes.find((n) => n.id === id)!
    expect(n.x).toBe(beforeX + 10)
    expect(n.y).toBe(-60 + 20)
    hook.unmount()
  })

  it('deleteSelection xóa node đồng thời loại connector trỏ tới node đó', () => {
    const hook = mount()
    act(() => hook.state.addShape('rect'))
    const id = lastNodeId(hook.state)
    act(() => hook.state.addConnector(id, 'node-c1'))
    expect(hook.state.scene.connectors.some((c) => c.fromNodeId === id)).toBe(true)
    act(() => hook.state.select(id))
    act(() => hook.state.deleteSelection())
    expect(hook.state.scene.nodes.some((n) => n.id === id)).toBe(false)
    expect(hook.state.scene.connectors.some((c) => c.fromNodeId === id || c.toNodeId === id)).toBe(false)
    hook.unmount()
  })

  it('select additive gộp nhiều id; selectNone rỗng; select thường chỉ còn 1', () => {
    const hook = mount()
    act(() => hook.state.select('node-c1'))
    act(() => hook.state.select('node-c2', true))
    expect([...hook.state.selection].sort()).toEqual(['node-c1', 'node-c2'])
    act(() => hook.state.selectNone())
    expect(hook.state.selection.size).toBe(0)
    act(() => hook.state.select('node-c1'))
    expect([...hook.state.selection]).toEqual(['node-c1'])
    hook.unmount()
  })

  it('undo/redo lùi add + move theo đúng thứ tự, canUndo/canRedo đổi đúng', () => {
    const hook = mount()
    expect(hook.state.canUndo).toBe(false)
    act(() => hook.state.addShape('rect'))
    expect(hook.state.canUndo).toBe(true)
    const id = lastNodeId(hook.state)
    act(() => hook.state.select(id))
    act(() => hook.state.moveSelection({ x: 30, y: 0 }, true))

    act(() => hook.state.undo()) // lùi move
    expect(hook.state.scene.nodes.find((n) => n.id === id)!.x).toBe(-80)

    act(() => hook.state.undo()) // lùi add
    expect(hook.state.scene.nodes.some((n) => n.id === id)).toBe(false)

    expect(hook.state.canRedo).toBe(true)
    act(() => hook.state.redo()) // thêm lại
    expect(hook.state.scene.nodes.some((n) => n.id === id)).toBe(true)
    hook.unmount()
  })

  it('history giới hạn: đẩy > 50 bước thì undo tối đa 50 bước', () => {
    const hook = mount()
    for (let i = 0; i < 55; i++) act(() => hook.state.addShape('rect'))
    let count = 0
    while (hook.state.canUndo) {
      act(() => hook.state.undo())
      count += 1
    }
    expect(count).toBe(50)
    hook.unmount()
  })

  it('stroke độc lập: 1 nét, move cả điểm, đổi màu, xóa — chỉ commit một lần', () => {
    const hook = mount()
    act(() => hook.state.startStroke({ x: 0, y: 0 }))
    act(() => hook.state.extendStroke({ x: 10, y: 5 }))
    act(() => hook.state.extendStroke({ x: 20, y: 3 }))
    act(() => hook.state.endStroke())

    const strokes = hook.state.scene.strokes
    expect(strokes).toHaveLength(1)
    expect(strokes[0].points).toHaveLength(3)

    const strokeId = strokes[0].id
    act(() => hook.state.select(strokeId))
    act(() => hook.state.moveSelection({ x: 5, y: -2 }, true))
    const moved = hook.state.scene.strokes[0]
    expect(moved.points[0]).toEqual({ x: 5, y: -2 })
    expect(moved.points[2]).toEqual({ x: 25, y: 1 })

    act(() => hook.state.recolorStroke(strokeId, '#ff0000'))
    expect(hook.state.scene.strokes[0].color).toBe('#ff0000')

    act(() => hook.state.deleteSelection())
    expect(hook.state.scene.strokes).toHaveLength(0)

    // start/extend KHÔNG commit; cả nét chỉ ghi đúng 1 bước (endStroke). Sau đó
    // moveSelection(true) và deleteSelection mỗi cái 1 bước → tổng 3 bước undo.
    act(() => hook.state.undo()) // lùi deleteSelection: stroke hiện lại
    expect(hook.state.scene.strokes).toHaveLength(1)
    act(() => hook.state.undo()) // lùi moveSelection: vẫn 1 stroke
    expect(hook.state.scene.strokes).toHaveLength(1)
    act(() => hook.state.undo()) // lùi endStroke: về scene rỗng stroke
    expect(hook.state.scene.strokes).toHaveLength(0)
    expect(hook.state.canUndo).toBe(false)
    hook.unmount()
  })

  it('resizeNode đổi kích thước đúng; commit=false không ghi history, commit=true thì undo khôi phục', () => {
    const hook = mount()
    act(() => hook.state.addShape('rect'))
    const id = lastNodeId(hook.state)
    const canUndoBefore = hook.state.canUndo

    act(() => hook.state.resizeNode(id, { width: 300 }, false))
    expect(hook.state.scene.nodes.find((n) => n.id === id)!.width).toBe(300)
    expect(hook.state.canUndo).toBe(canUndoBefore)

    act(() => hook.state.resizeNode(id, { width: 200, height: 100 }, true))
    const n = hook.state.scene.nodes.find((n) => n.id === id)!
    expect(n.width).toBe(200)
    expect(n.height).toBe(100)
    expect(boundsOfNode(n)).toEqual({ minX: n.x, minY: n.y, maxX: n.x + 200, maxY: n.y + 100 })

    act(() => hook.state.undo())
    expect(hook.state.scene.nodes.find((n) => n.id === id)!.width).toBe(300)
    hook.unmount()
  })
})

/**
 * P2 — hai chiều vận chuyển (kế hoạch §6.4). Người dùng → agent đi qua đường
 * thật `lib/designApi.postCanvas` (`/api/agent/sessions/{sid}/canvas`), KHÔNG
 * dùng `agentStore`/`ClientCommand` cũ. Hôm nay hook chỉ `setLastSentMessage`
 * nên hai bài này ĐỎ; xanh khi hook thực sự POST.
 */
describe('useDesignCanvas — transport (P2)', () => {
  const calls: { url: string; body: Record<string, unknown> | null; method: string }[] = []

  beforeEach(() => {
    calls.length = 0
    useDesignStore.setState({
      sessionId: 's-canvas',
      mode: { ...DESIGN_MODE_OFF, on: true, activeRunId: 'd-canvas' },
      runs: [],
      activeRunId: 'd-canvas',
      scenes: {},
      rejectedOps: 0,
    })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        calls.push({
          url: String(input),
          body: init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null,
          method: init?.method ?? 'GET',
        })
        return { ok: true, status: 200, json: async () => ({ ok: true, sceneVersion: 1 }) } as unknown as Response
      }),
    )
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    useDesignStore.setState({ sessionId: '' })
  })

  it('sendToAgent_posts_scene', async () => {
    const hook = mount()
    act(() => hook.state.addShape('rect'))

    await act(async () => {
      hook.state.sendToAgent()
    })

    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('POST')
    expect(calls[0].url).toContain('/api/agent/sessions/s-canvas/canvas')
    expect(calls[0].body?.protocol).toBe('boxfox.canvas.v1')
    expect(calls[0].body?.type).toBe('scene')
    const sent = calls[0].body?.scene as { nodes: unknown[] } | undefined
    expect(sent?.nodes.length).toBeGreaterThan(0)
    hook.unmount()
  })

  it('instructAgent_posts_directive', async () => {
    const hook = mount()
    act(() => hook.state.addShape('rect'))
    const id = lastNodeId(hook.state)

    await act(async () => {
      hook.state.instructAgent(id)
    })

    expect(calls).toHaveLength(1)
    expect(calls[0].method).toBe('POST')
    expect(calls[0].url).toContain('/api/agent/sessions/s-canvas/canvas')
    expect(calls[0].body?.protocol).toBe('boxfox.canvas.v1')
    expect(calls[0].body?.type).toBe('directive')
    expect(calls[0].body?.targetNodeId).toBe(id)
    hook.unmount()
  })
})
