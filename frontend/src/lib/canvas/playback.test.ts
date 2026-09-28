import { describe, expect, it } from 'vitest'
import type { CanvasNode, CanvasScene } from './types'
import { createEmptyScene } from './scene'
import { applyCanvasAction, type CanvasAction } from './agent-protocol'
import { alignConnectorIds, cursorAt, diffSceneOps, frameAt, planPlayback, sameScene, PLAYBACK_DEFAULTS } from './playback'

function node(id: string, over: Partial<CanvasNode> = {}): CanvasNode {
  return {
    id,
    kind: 'card',
    shape: null,
    card: 'ui-mockup',
    x: 0,
    y: 0,
    width: 200,
    height: 120,
    title: '',
    body: '',
    url: null,
    style: { fill: '#111', stroke: '#333', strokeWidth: 1, radius: 12 },
    ...over,
  }
}

function connector(id: string, from: string, to: string): CanvasAction {
  return {
    type: 'CONNECT_NODES',
    connector: { id, fromNodeId: from, toNodeId: to, fromAnchor: 'right', toAnchor: 'left', stroke: '#3b82f6', strokeWidth: 2 },
  }
}

/** Bỏ id của op CONNECT_NODES — dựng lại đúng hình dạng backend phát ra (setdefault trên bản sao). */
function stripConnectorId(op: CanvasAction): CanvasAction {
  if (op.type !== 'CONNECT_NODES') return op
  const { id: _dropped, ...rest } = op.connector
  return { type: 'CONNECT_NODES', connector: rest }
}

/** Cảnh đích = cảnh đầu + lô op, tính bằng CHÍNH reducer của store (không tự viết tay). */
function apply(from: CanvasScene, ops: CanvasAction[]): CanvasScene {
  return ops.reduce((scene, op) => applyCanvasAction(scene, op), from)
}

describe('planPlayback', () => {
  it('lô op rỗng thì không có hoạt hình', () => {
    const from = createEmptyScene()
    const plan = planPlayback({ ops: [], from, to: from })
    expect(plan.steps).toEqual([])
    expect(plan.totalMs).toBe(0)
    expect(plan.reducedMotion).toBe(true)
  })

  it('op không dựng nên cảnh sau (id trùng) thì trả kế hoạch rỗng, không bịa nét vẽ', () => {
    const from: CanvasScene = { ...createEmptyScene(), nodes: [node('a')] }
    const ops: CanvasAction[] = [{ type: 'CREATE_NODE', node: node('a', { x: 300 }) }]
    const to = apply(from, ops)
    expect(sameScene(to, from)).toBe(true) // reducer từ chối id trùng ⇒ cảnh không đổi
    const plan = planPlayback({ ops, from, to })
    expect(plan.totalMs).toBe(0)
    expect(plan.steps).toEqual([])
  })

  it('lô op dựng nên cảnh sau thì có con trỏ đi tới, node lớn dần và connector vẽ dần', () => {
    const from = createEmptyScene()
    const ops: CanvasAction[] = [
      { type: 'CREATE_NODE', node: node('n1', { x: 40, y: 60, title: 'Màn hình đăng nhập' }) },
      { type: 'CONNECT_NODES', connector: { fromNodeId: 'n1', toNodeId: 'n1', fromAnchor: 'right', toAnchor: 'left', stroke: '#3b82f6', strokeWidth: 2 } },
    ]
    const to = apply(from, ops)
    const plan = planPlayback({ ops, from, to, options: { speed: 1 } })
    expect(plan.reducedMotion).toBe(false)
    expect(plan.totalMs).toBeGreaterThan(0)
    expect(plan.steps.map((s) => s.kind)).toEqual(['move', 'create', 'settle', 'move', 'connect', 'settle'])
    expect(plan.steps[1].nodeId).toBe('n1')
  })

  it('con trỏ đi TỚI góc trên-trái của node — nơi người vẽ đặt bút', () => {
    const from = createEmptyScene()
    const ops: CanvasAction[] = [{ type: 'CREATE_NODE', node: node('n1', { x: 40, y: 60 }) }]
    const plan = planPlayback({ ops, from, to: apply(from, ops) })
    const create = plan.steps.find((s) => s.kind === 'create')!
    expect(create.at).toEqual({ x: 40, y: 60 })
  })

  it('op UPDATE_NODE và DELETE_NODE cũng có bước riêng', () => {
    const from: CanvasScene = { ...createEmptyScene(), nodes: [node('a'), node('b')] }
    const ops: CanvasAction[] = [
      { type: 'UPDATE_NODE', nodeId: 'b', patch: { title: 'Đã sửa', x: 500 } },
      { type: 'DELETE_NODE', nodeId: 'a' },
    ]
    const plan = planPlayback({ ops, from, to: apply(from, ops) })
    expect(plan.steps.filter((s) => s.kind === 'update')).toHaveLength(1)
    expect(plan.steps.filter((s) => s.kind === 'delete')).toHaveLength(1)
    expect(plan.steps.find((s) => s.kind === 'update')!.nodeId).toBe('b')
  })

  it('lô op dài bị ép dưới trần tổng thời lượng', () => {
    const from = createEmptyScene()
    const ops: CanvasAction[] = Array.from({ length: 24 }, (_, index) => ({
      type: 'CREATE_NODE' as const,
      node: node(`n${index}`, { x: 40 * (index % 8), y: 120 * Math.floor(index / 8), title: `Khối ${index}` }),
    }))
    const plan = planPlayback({ ops, from, to: apply(from, ops) })
    expect(plan.totalMs).toBeLessThanOrEqual(PLAYBACK_DEFAULTS.maxTotalMs + 1e-6)
    expect(plan.totalMs).toBeGreaterThan(0)
    expect(Math.max(...plan.steps.map((s) => s.endMs))).toBeLessThanOrEqual(plan.totalMs + 1e-6)
  })

  it('hệ số tốc độ rút ngắn thời lượng', () => {
    const from = createEmptyScene()
    const ops: CanvasAction[] = [{ type: 'CREATE_NODE', node: node('n1', { x: 800, y: 600, title: 'Nhanh' }) }]
    const to = apply(from, ops)
    const slow = planPlayback({ ops, from, to })
    const fast = planPlayback({ ops, from, to, options: { speed: 2 } })
    expect(fast.totalMs).toBeLessThan(slow.totalMs)
    expect(fast.totalMs).toBeCloseTo(slow.totalMs / 2, 5)
  })

  it('reducedMotion tắt hoạt hình nhưng vẫn trả đúng cảnh thật', () => {
    const from = createEmptyScene()
    const ops: CanvasAction[] = [{ type: 'CREATE_NODE', node: node('n1') }]
    const to = apply(from, ops)
    const plan = planPlayback({ ops, from, to, options: { reducedMotion: true } })
    expect(plan.totalMs).toBe(0)
    expect(plan.steps).toEqual([])
    const frame = frameAt(plan, 0)
    expect(frame.scene).toBe(to)
    expect(frame.cursor.visible).toBe(false)
    expect(frame.done).toBe(true)
  })

  it('tiêu đề dài kéo dài bước tạo node nhưng có trần gõ chữ', () => {
    const from = createEmptyScene()
    const short: CanvasAction[] = [{ type: 'CREATE_NODE', node: node('s', { title: 'A' }) }]
    const long: CanvasAction[] = [{ type: 'CREATE_NODE', node: node('l', { title: 'x'.repeat(500) }) }]
    const a = planPlayback({ ops: short, from, to: apply(from, short) })
    const b = planPlayback({ ops: long, from, to: apply(from, long) })
    const createA = a.steps.find((s) => s.kind === 'create')!
    const createB = b.steps.find((s) => s.kind === 'create')!
    expect(createB.endMs - createB.startMs).toBeGreaterThan(createA.endMs - createA.startMs)
    expect(createB.endMs - createB.startMs).toBeLessThanOrEqual(PLAYBACK_DEFAULTS.createMs + PLAYBACK_DEFAULTS.typingMaxMs + 1e-6)
  })
})

describe('alignConnectorIds', () => {
  it('gán id của connector trong cảnh thật khi op thiếu id (backend setdefault trên bản sao)', () => {
    const from: CanvasScene = { ...createEmptyScene(), nodes: [node('a'), node('b')] }
    const withId: CanvasAction = connector('c1', 'a', 'b')
    const withoutId: CanvasAction = stripConnectorId(withId)
    const to = apply(from, [withId])
    const aligned = alignConnectorIds([withoutId], from, to)
    expect((aligned[0] as { connector: { id?: string } }).connector.id).toBe('c1')
  })

  it('kế hoạch vẫn phát được khi op CONNECT_NODES thiếu id', () => {
    const from: CanvasScene = { ...createEmptyScene(), nodes: [node('a'), node('b')] }
    const withId = connector('c1', 'a', 'b')
    const stripped = stripConnectorId(withId)
    const to = apply(from, [withId as unknown as CanvasAction])
    const plan = planPlayback({ ops: [stripped], from, to })
    expect(plan.steps.map((s) => s.kind)).toEqual(['move', 'connect', 'settle'])
    expect(plan.steps.find((s) => s.kind === 'connect')!.connectorId).toBe('c1')
  })

  it('giữ nguyên op khi id đã có sẵn', () => {
    const from: CanvasScene = { ...createEmptyScene(), nodes: [node('a'), node('b')] }
    const op = connector('c1', 'a', 'b')
    const aligned = alignConnectorIds([op], from, apply(from, [op]))
    expect(aligned[0]).toBe(op)
  })

  it('gán id theo HAI ĐẦU của nét, không tin vào thứ tự trong cảnh', () => {
    const from: CanvasScene = { ...createEmptyScene(), nodes: [node('a'), node('b'), node('c')] }
    const to: CanvasScene = {
      ...from,
      connectors: [
        { id: 'c2', fromNodeId: 'b', toNodeId: 'c', fromAnchor: 'right', toAnchor: 'left', stroke: '#3b82f6', strokeWidth: 2 },
        { id: 'c1', fromNodeId: 'a', toNodeId: 'b', fromAnchor: 'right', toAnchor: 'left', stroke: '#3b82f6', strokeWidth: 2 },
      ],
    }
    const aligned = alignConnectorIds(
      [stripConnectorId(connector('c1', 'a', 'b')), stripConnectorId(connector('c2', 'b', 'c'))],
      from,
      to,
    )
    expect(aligned.map((op) => (op.type === 'CONNECT_NODES' ? op.connector.id : null))).toEqual(['c1', 'c2'])
  })

  it('hai nét cùng hai đầu thì lùi về đúng vị trí thêm', () => {
    const from: CanvasScene = { ...createEmptyScene(), nodes: [node('a'), node('b')] }
    const to = apply(from, [connector('x1', 'a', 'b'), connector('x2', 'a', 'b')])
    const aligned = alignConnectorIds([stripConnectorId(connector('x1', 'a', 'b')), stripConnectorId(connector('x2', 'a', 'b'))], from, to)
    expect(aligned.map((op) => (op.type === 'CONNECT_NODES' ? op.connector.id : null))).toEqual(['x1', 'x2'])
  })
})

describe('frameAt', () => {
  const ops: CanvasAction[] = [
    { type: 'CREATE_NODE', node: node('n1', { x: 40, y: 60, title: 'Màn hình A', body: 'mô tả A' }) },
    { type: 'CREATE_NODE', node: node('n2', { x: 400, y: 60, title: 'Màn hình B' }) },
    connector('c1', 'n1', 'n2'),
  ]
  const from = createEmptyScene()
  const to = apply(from, ops)
  const plan = planPlayback({ ops, from, to })

  it('hết thời lượng trả ĐÚNG cảnh thật (cùng một object)', () => {
    const frame = frameAt(plan, plan.totalMs)
    expect(frame.scene).toBe(plan.to)
    expect(frame.done).toBe(true)
    expect(frame.cursor.visible).toBe(false)
    expect(sameScene(frame.scene, to)).toBe(true)
  })

  it('thời điểm 0 chưa có node nào — con trỏ mới đứng ở góc đặt bút', () => {
    const frame = frameAt(plan, 0)
    expect(frame.scene.nodes).toHaveLength(0)
    expect(frame.cursor.visible).toBe(true)
    expect(frame.cursor.pressed).toBe(false)
    expect(frame.done).toBe(false)
  })

  it('giữa bước tạo node: node đang lớn dần rồi tới lượt chữ hiện dần', () => {
    const create = plan.steps.find((s) => s.kind === 'create')!
    const span = create.endMs - create.startMs
    // 20% thời lượng: khung đang lớn dần, chữ chưa gõ ký tự nào.
    const growing = frameAt(plan, create.startMs + span * 0.2)
    const partial = growing.scene.nodes.find((n) => n.id === 'n1')!
    expect(partial.width).toBeGreaterThan(0)
    expect(partial.width).toBeLessThan(200)
    expect(partial.height).toBeGreaterThan(0)
    expect(partial.height).toBeLessThan(120)
    expect(partial.title).toBe('')
    expect(growing.activeIds).toContain('n1')
    // 80% thời lượng: khung đã đủ, chữ đang hiện dần từng ký tự.
    const typing = frameAt(plan, create.startMs + span * 0.8)
    const typed = typing.scene.nodes.find((n) => n.id === 'n1')!
    expect(typed.title.length).toBeGreaterThan(0)
    expect(typed.title.length).toBeLessThan('Màn hình A'.length)
    expect('Màn hình A'.startsWith(typed.title)).toBe(true)
  })

  it('số node chỉ tăng theo thời gian (không nhấp nháy ngược)', () => {
    let previous = 0
    for (let t = 0; t <= plan.totalMs; t += plan.totalMs / 60) {
      const count = frameAt(plan, t).scene.nodes.length
      expect(count).toBeGreaterThanOrEqual(previous)
      previous = count
    }
    expect(previous).toBe(to.nodes.length)
  })

  it('giữa bước connect: connector đã có mặt nhưng tiến độ nằm trong khoảng 0..1', () => {
    const connect = plan.steps.find((s) => s.kind === 'connect')!
    const frame = frameAt(plan, (connect.startMs + connect.endMs) / 2)
    expect(Object.keys(frame.connectorProgress)).toEqual(['c1'])
    expect(frame.connectorProgress.c1).toBeGreaterThan(0)
    expect(frame.connectorProgress.c1).toBeLessThan(1)
    expect(frame.scene.connectors).toHaveLength(1)
    expect(frame.activeIds).toContain('c1')
  })

  it('giữa bước xóa: node teo lại và connector trỏ tới nó biến mất ngay', () => {
    const del: CanvasAction[] = [{ type: 'DELETE_NODE', nodeId: 'n1' }]
    const plan2 = planPlayback({ ops: del, from: to, to: apply(to, del) })
    const step = plan2.steps.find((s) => s.kind === 'delete')!
    const frame = frameAt(plan2, (step.startMs + step.endMs) / 2)
    const shrinking = frame.scene.nodes.find((n) => n.id === 'n1')!
    expect(shrinking.width).toBeLessThan(200)
    expect(shrinking.width).toBeGreaterThanOrEqual(0)
    expect(frame.scene.connectors).toHaveLength(0)
  })

  it('giữa bước update: hình học nội suy giữa cũ và mới', () => {
    const patch: CanvasAction[] = [{ type: 'UPDATE_NODE', nodeId: 'n2', patch: { x: 900, width: 320 } }]
    const plan3 = planPlayback({ ops: patch, from: to, to: apply(to, patch) })
    const step = plan3.steps.find((s) => s.kind === 'update')!
    const frame = frameAt(plan3, (step.startMs + step.endMs) / 2)
    const moving = frame.scene.nodes.find((n) => n.id === 'n2')!
    expect(moving.x).toBeGreaterThan(400)
    expect(moving.x).toBeLessThan(900)
    expect(moving.width).toBeGreaterThan(200)
    expect(moving.width).toBeLessThan(320)
  })

  it('mọi khung hình đều là cảnh hợp lệ (node id duy nhất, connector không mồ côi)', () => {
    for (let t = 0; t <= plan.totalMs; t += plan.totalMs / 40) {
      const scene = frameAt(plan, t).scene
      expect(new Set(scene.nodes.map((n) => n.id)).size).toBe(scene.nodes.length)
      const ids = new Set(scene.nodes.map((n) => n.id))
      for (const c of scene.connectors) {
        expect(ids.has(c.fromNodeId)).toBe(true)
        expect(ids.has(c.toNodeId)).toBe(true)
      }
    }
  })
})

describe('cursorAt', () => {
  it('đi theo cung lệch khỏi đường thẳng ở giữa, và về ĐÚNG đích ở cuối', () => {
    const plan = planPlayback({
      ops: [{ type: 'CREATE_NODE', node: node('n1', { x: 600, y: 400 }) }],
      from: createEmptyScene(),
      to: apply(createEmptyScene(), [{ type: 'CREATE_NODE', node: node('n1', { x: 600, y: 400 }) }]),
    })
    const move = plan.steps.find((s) => s.kind === 'move')!
    // Con trỏ xuất phát ở gốc (0,0) rồi đi tới (600,400): ở giữa đường phải lệch khỏi đường thẳng.
    const mid = cursorAt(move, (move.startMs + move.endMs) / 2)
    const straightMid = { x: 300, y: 200 }
    expect(Math.hypot(mid.x - straightMid.x, mid.y - straightMid.y)).toBeGreaterThan(4)
    expect(cursorAt(move, move.endMs)).toEqual({ x: 600, y: 400 })
  })

  it('bước không phải move thì con trỏ đứng ở điểm neo', () => {
    const plan = planPlayback({
      ops: [{ type: 'CREATE_NODE', node: node('n1', { x: 40, y: 60 }) }],
      from: createEmptyScene(),
      to: apply(createEmptyScene(), [{ type: 'CREATE_NODE', node: node('n1', { x: 40, y: 60 }) }]),
    })
    const create = plan.steps.find((s) => s.kind === 'create')!
    expect(cursorAt(create, (create.startMs + create.endMs) / 2)).toEqual({ x: 40, y: 60 })
  })
})

describe('sameScene', () => {
  it('phân biệt được cảnh khác nhau ở từng trường', () => {
    const a: CanvasScene = { ...createEmptyScene(), nodes: [node('a')] }
    const b: CanvasScene = { ...createEmptyScene(), nodes: [node('a')] }
    expect(sameScene(a, b)).toBe(true)
    expect(sameScene(a, { ...createEmptyScene(), nodes: [node('a', { x: 1 })] })).toBe(false)
    expect(sameScene(a, { ...createEmptyScene(), nodes: [node('a', { style: { fill: '#fff', stroke: '#333', strokeWidth: 1, radius: 12 } })] })).toBe(false)
    expect(sameScene(a, { ...createEmptyScene(), nodes: [node('a'), node('b')] })).toBe(false)
  })
})

describe('diffSceneOps', () => {
  const base = () => apply(createEmptyScene(), [
    { type: 'CREATE_NODE', node: node('n1') },
    { type: 'CREATE_NODE', node: node('n2', { x: 400 }) },
    connector('c1', 'n1', 'n2'),
  ])

  it('cảnh tới KHÔNG kèm op vẫn dựng được op đúng (payload chi tiết của run)', () => {
    const from = base()
    const to = apply(from, [
      { type: 'CREATE_NODE', node: node('n3', { x: 800 }) },
      { type: 'UPDATE_NODE', nodeId: 'n1', patch: { title: 'Màn hình A' } },
      connector('c2', 'n2', 'n3'),
    ])
    const ops = diffSceneOps(from, to)
    // Chênh lệch phải nói ĐÚNG cảnh đích: chính `planPlayback` là trọng tài (nó đòi mọi op được
    // reducer chấp nhận và cảnh dựng lại phải BẰNG cảnh thật).
    expect(apply(from, ops)).toEqual(to)
    expect(planPlayback({ ops, from, to }).steps.length).toBeGreaterThan(0)
  })

  it('cảnh giống nhau ⇒ không op nào (không diễn lại cảnh cũ)', () => {
    const from = base()
    expect(diffSceneOps(from, apply(from, []))).toEqual([])
  })

  it('node bị xoá ⇒ có DELETE_NODE, và nét nối mồ côi do cascade nên không cần op riêng', () => {
    const from = base()
    const to = apply(from, [{ type: 'DELETE_NODE', nodeId: 'n2' }])
    const ops = diffSceneOps(from, to)
    expect(ops).toEqual([{ type: 'DELETE_NODE', nodeId: 'n2' }])
    expect(apply(from, ops)).toEqual(to)
  })

  it('nét nối biến mất mà hai đầu còn sống ⇒ thà không có hoạt hình còn hơn vẽ sai', () => {
    const from = base()
    const to: CanvasScene = { ...from, connectors: [] }
    expect(diffSceneOps(from, to)).toEqual([])
  })

  it('nét bút chì đổi ⇒ không op nào (bốn lệnh hiện có không diễn tả được nét)', () => {
    const from = base()
    const to: CanvasScene = { ...from, strokes: [{ id: 's1', color: '#fff', width: 2, points: [{ x: 1, y: 1 }, { x: 9, y: 9 }] }] }
    expect(diffSceneOps(from, to)).toEqual([])
  })

  it('cảnh gieo (rỗng → ba thẻ + hai nét) dựng thành kế hoạch vẽ được', () => {
    const from = createEmptyScene()
    const to = apply(from, [
      { type: 'CREATE_NODE', node: node('seed-workspace', { x: 40, y: 40, width: 380, height: 180 }) },
      { type: 'CREATE_NODE', node: node('seed-screen', { x: 520, y: 40, width: 380, height: 180 }) },
      { type: 'CREATE_NODE', node: node('seed-touch-1', { x: 960, y: 40, width: 380, height: 130 }) },
      connector('c1', 'seed-workspace', 'seed-screen'),
      connector('c2', 'seed-screen', 'seed-touch-1'),
    ])
    const ops = diffSceneOps(from, to)
    expect(ops).toHaveLength(5)
    expect(apply(from, ops)).toEqual(to)
    const plan = planPlayback({ ops, from, to })
    expect(plan.to).toEqual(to)
    expect(plan.steps.filter((step) => step.kind === 'connect')).toHaveLength(2)
  })
})
