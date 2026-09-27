/**
 * Bài kiểm lát cắt canvas của `designStore` (P2, hợp đồng §9/§10).
 *
 * Nguồn sự thật là sự kiện `design_canvas` gộp nhiều op; store KHÔNG được vẽ dữ liệu bịa: op sai giao
 * thức hoặc op mà reducer từ chối đều bị bỏ và đếm vào `rejectedOps`, cảnh giữ nguyên.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { DESIGN_MODE_OFF } from '../lib/designMode'
import { selectScene, useDesignStore } from './designStore'

const DESIGN_ID = 'd-store-canvas'

/** Node tối thiểu để `parseCanvasMessage` chuẩn hoá được (thiếu field thì normalize điền mặc định). */
function node(id: string) {
  return { id, kind: 'card', x: 0, y: 0, width: 100, height: 80, title: id, body: '' }
}

function canvasEvent(ops: unknown[], sceneVersion = 1, actor = 'agent') {
  return {
    seq: sceneVersion,
    type: 'design_canvas',
    data: { designId: DESIGN_ID, seq: sceneVersion, actor, ops, sceneVersion },
  }
}

beforeEach(() => {
  useDesignStore.setState({
    sessionId: 's-store',
    mode: { ...DESIGN_MODE_OFF, on: true, activeRunId: DESIGN_ID },
    runs: [],
    activeRunId: DESIGN_ID,
    scenes: {},
    sceneActor: {},
    sceneVersion: 0,
    prompts: [],
    rejectedOps: 0,
    brief: {},
    exitChoice: null,
    reports: {},
    notices: [],
    pendingTurn: '',
    loading: false,
    error: null,
    lastEventSeq: 0,
  })
})

describe('designStore — canvas slice (P2)', () => {
  it('applies_valid_ops_and_counts_rejected', () => {
    useDesignStore.getState().applyEvent(
      canvasEvent([
        { type: 'CREATE_NODE', node: node('n1') },
        { type: 'CREATE_NODE', node: node('n2') },
        // Sai giao thức: không phải một op của `boxfox.canvas.v1`.
        { type: 'BỊA' },
        // Hợp giao thức nhưng node không tồn tại ⇒ reducer trả CHÍNH scene cũ ⇒ bị đếm.
        { type: 'UPDATE_NODE', nodeId: 'n-missing', patch: { title: 'x' } },
      ], 3),
    )

    const scene = selectScene(DESIGN_ID)(useDesignStore.getState())
    expect(scene.nodes.map((item) => item.id)).toEqual(['n1', 'n2'])
    expect(useDesignStore.getState().rejectedOps).toBe(2)
    expect(useDesignStore.getState().sceneVersion).toBe(3)
    expect(useDesignStore.getState().sceneActor[DESIGN_ID]).toBe('agent')
  })

  it('a valid op changes the scene; scene start empty for a run with no ops', () => {
    expect(selectScene(DESIGN_ID)(useDesignStore.getState()).nodes).toHaveLength(0)
    useDesignStore.getState().applyEvent(canvasEvent([{ type: 'CREATE_NODE', node: node('n1') }], 1))
    expect(selectScene(DESIGN_ID)(useDesignStore.getState()).nodes).toHaveLength(1)
    expect(useDesignStore.getState().rejectedOps).toBe(0)
  })

  it('records the actor of the last canvas event per run', () => {
    useDesignStore.getState().applyEvent(canvasEvent([{ type: 'CREATE_NODE', node: node('n1') }], 1, 'user'))
    expect(useDesignStore.getState().sceneActor[DESIGN_ID]).toBe('user')
  })
})

describe('designStore — thông báo nền và hàng đợi lượt main (P5 §5.2/§5.9)', () => {
  function noticeEvent(kind: string, seq: number) {
    return { seq, type: 'design_notice', data: { designId: DESIGN_ID, kind } }
  }

  it('mỗi sự kiện `design_notice` đúng một thẻ; poll lặp cùng seq không nhân đôi', () => {
    useDesignStore.getState().applyEvent(noticeEvent('background-done', 41))
    useDesignStore.getState().applyEvent(noticeEvent('background-done', 41))
    expect(useDesignStore.getState().notices).toEqual([
      { designId: DESIGN_ID, kind: 'background-done', seq: 41 },
    ])
    useDesignStore.getState().applyEvent(noticeEvent('needs-user', 42))
    expect(useDesignStore.getState().notices).toHaveLength(2)
  })

  it('design_notice thiếu designId bị bỏ thay vì dựng thẻ rỗng', () => {
    useDesignStore.getState().applyEvent({ seq: 43, type: 'design_notice', data: { kind: 'blocked' } })
    expect(useDesignStore.getState().notices).toHaveLength(0)
  })

  it('queueTurn: chuỗi rỗng huỷ xếp hàng; đổi phiên xoá cả thông báo lẫn hàng đợi', () => {
    useDesignStore.getState().queueTurn('gửi main')
    expect(useDesignStore.getState().pendingTurn).toBe('gửi main')
    useDesignStore.getState().queueTurn('')
    expect(useDesignStore.getState().pendingTurn).toBe('')

    useDesignStore.getState().applyEvent(noticeEvent('blocked', 44))
    useDesignStore.getState().queueTurn('x')
    useDesignStore.getState().clearSessionChange()
    expect(useDesignStore.getState().notices).toHaveLength(0)
    expect(useDesignStore.getState().pendingTurn).toBe('')
  })
})
