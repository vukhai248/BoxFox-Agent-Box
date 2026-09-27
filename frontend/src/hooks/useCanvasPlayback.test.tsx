/**
 * Những luật VÒNG ĐỜI của lớp phát lại (`useCanvasPlayback`) — phần dễ vỡ nhất của vòng 3 vì nó
 * giữ tham chiếu qua nhiều khung hình. `DesignFlow.test.tsx` chỉ chạm tới nó qua giao diện, nên ở
 * đây khoá trực tiếp bốn ca: cảnh mới tới giữa lúc đang vẽ, vòng poll gửi lại đúng cảnh cũ, tay
 * chủ nhà vẽ, và tháo hook giữa lúc vẽ.
 */
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCanvasPlayback, type CanvasPlayback } from './useCanvasPlayback'
import { createEmptyScene, type CanvasAction, type CanvasNode, type CanvasScene } from '../lib/canvas'
import { useDesignStore } from '../store/designStore'

const DESIGN_ID = 'design-lifecycle'
const EMPTY = createEmptyScene()

function node(id: string, over: Partial<CanvasNode> = {}): CanvasNode {
  return {
    id,
    kind: 'card',
    shape: null,
    card: 'ui-mockup',
    x: 40,
    y: 60,
    width: 200,
    height: 120,
    title: id,
    body: '',
    url: null,
    style: { fill: '#111', stroke: '#333', strokeWidth: 1, radius: 12 },
    ...over,
  }
}

function create(id: string): CanvasAction {
  return { type: 'CREATE_NODE', node: node(id) }
}

function sceneWith(...nodes: CanvasNode[]): CanvasScene {
  return { ...createEmptyScene(), nodes }
}

/** Một lô op + cảnh đi kèm, đúng cách store giao chúng cho hook. */
function put(scene: CanvasScene, ops: CanvasAction[], actor: 'agent' | 'user', seq: number) {
  useDesignStore.setState({
    scenes: { [DESIGN_ID]: scene },
    sceneSeq: { [DESIGN_ID]: seq },
    sceneActor: { [DESIGN_ID]: actor },
    lastOps: { [DESIGN_ID]: { actor, ops, seq } },
    rejectedOps: 0,
  })
}

function mount(options?: { reducedMotion?: boolean }) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const out: { value: CanvasPlayback | null } = { value: null }

  function Probe() {
    const scene = useDesignStore((state) => state.scenes[DESIGN_ID]) ?? EMPTY
    out.value = useCanvasPlayback({ scene, designId: DESIGN_ID, reducedMotion: options?.reducedMotion })
    return null
  }

  act(() => {
    root.render(<Probe />)
  })

  return {
    get value(): CanvasPlayback {
      if (!out.value) throw new Error('Hook did not render.')
      return out.value
    },
    unmount() {
      act(() => root.unmount())
      host.remove()
    },
  }
}

function tracked<T extends { unmount: () => void }>(entry: T): T {
  mounted.push(entry)
  return entry
}

let mounted: { unmount: () => void }[] = []

describe('useCanvasPlayback — vòng đời', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useDesignStore.setState({
      runs: [],
      scenes: {},
      sceneSeq: {},
      sceneActor: {},
      lastOps: {},
      playedOpsSeq: {},
      rejectedOps: 0,
      error: null,
    })
  })

  afterEach(() => {
    // Mọi hook còn gắn đều nghe cùng một store: không tháo hết thì ca sau sẽ có nhiều hoạt hình
    // cùng chạy và số khung hình còn lại không còn nghĩa gì.
    for (const entry of mounted) entry.unmount()
    mounted = []
    vi.clearAllTimers()
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('canvas mở SAU khi lô op đã vào store: vẫn vẽ dần từ CẢNH NGUỒN, và không diễn lại khi mở lại', () => {
    // Đúng thứ store giao cho hook sau lượt duyệt khi canvas đang ĐÓNG: cảnh cuối đã nằm sẵn trong
    // store, kèm lô op suy từ chênh lệch + cảnh nguồn (`from`). Vòng kiểm thử bắt được ca này: hook
    // mount ra với `scene === from` nên hàng rào "cảnh không đổi" nuốt luôn lô op ⇒ canvas hiện ra đã
    // vẽ xong, không con trỏ, không nút Bỏ qua.
    act(() => {
      useDesignStore.setState({
        scenes: { [DESIGN_ID]: sceneWith(node('n1')) },
        sceneSeq: { [DESIGN_ID]: 1 },
        sceneActor: { [DESIGN_ID]: 'agent' },
        lastOps: { [DESIGN_ID]: { actor: 'agent', ops: [create('n1')], seq: 1, from: EMPTY } },
        playedOpsSeq: {},
        rejectedOps: 0,
      })
    })
    const host = tracked(mount())
    expect(host.value.playing).toBe(true)
    // Cảnh đang vẽ dở bắt đầu từ cảnh NGUỒN (trống) — không phải cảnh cuối hiện ra đột ngột.
    expect(host.value.displayScene.nodes).toHaveLength(0)
    expect(host.value.cursor).not.toBeNull()
    act(() => {
      vi.advanceTimersByTime(8000)
    })
    expect(host.value.playing).toBe(false)
    expect(host.value.displayScene.nodes.map((entry) => entry.id)).toEqual(['n1'])

    // Mở lại canvas (đổi tab rồi quay lại): lô op đã diễn MỘT lần ⇒ không diễn lại lần nữa.
    host.unmount()
    const again = tracked(mount())
    expect(again.value.playing).toBe(false)
    expect(again.value.displayScene.nodes.map((entry) => entry.id)).toEqual(['n1'])
  })

  it('cảnh mới tới giữa lúc đang vẽ: bỏ hoạt hình cũ rồi vẽ tiếp từ cảnh THẬT', () => {
    const host = tracked(mount())
    act(() => put(sceneWith(node('n1')), [create('n1')], 'agent', 1))
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(host.value.playing).toBe(true)

    // Lô thứ hai tới khi lô đầu còn đang vẽ.
    act(() => put(sceneWith(node('n1'), node('n2')), [create('n2')], 'agent', 2))
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(host.value.playing).toBe(true)
    // Kế hoạch mới chỉ có MỘT bước vẽ (n2) — không phát lại cả n1.
    expect(host.value.total).toBe(1)

    act(() => {
      vi.advanceTimersByTime(8000)
    })
    expect(host.value.playing).toBe(false)
    expect(host.value.cursor).toBeNull()
    expect(host.value.displayScene.nodes.map((entry) => entry.id)).toEqual(['n1', 'n2'])
  })

  it('vòng poll gửi lại ĐÚNG cảnh cũ: không cắt ngang hoạt hình đang chạy', () => {
    const host = tracked(mount())
    act(() => put(sceneWith(node('n1')), [create('n1')], 'agent', 1))
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(host.value.playing).toBe(true)

    // Cùng nội dung, object mới (đúng kiểu một vòng đồng bộ gửi lại).
    act(() => put(sceneWith(node('n1')), [create('n1')], 'agent', 1))
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(host.value.playing).toBe(true)
    expect(host.value.total).toBe(1)
  })

  it('tay chủ nhà vẽ (actor user): hiện thẳng cảnh, không diễn lại', () => {
    const host = tracked(mount())
    act(() => put(sceneWith(node('owner-1')), [create('owner-1')], 'user', 3))
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(host.value.playing).toBe(false)
    expect(host.value.cursor).toBeNull()
    expect(host.value.displayScene.nodes.map((entry) => entry.id)).toEqual(['owner-1'])
  })

  it('reducedMotion: hiện thẳng cảnh thật, không dựng con trỏ', () => {
    const host = tracked(mount({ reducedMotion: true }))
    act(() => put(sceneWith(node('n1')), [create('n1')], 'agent', 1))
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(host.value.playing).toBe(false)
    expect(host.value.cursor).toBeNull()
    expect(host.value.displayScene.nodes.map((entry) => entry.id)).toEqual(['n1'])
  })

  it('tháo hook giữa lúc vẽ: hoạt hình dừng ngay, không còn khung hình nào chạy tiếp', () => {
    const host = tracked(mount())
    act(() => put(sceneWith(node('n1')), [create('n1')], 'agent', 1))
    act(() => {
      vi.advanceTimersByTime(80)
    })
    expect(host.value.playing).toBe(true)
    host.unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
})
