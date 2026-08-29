import { describe, expect, it } from 'vitest'
import type { CanvasNode } from './types'
import { createEmptyScene } from './scene'
import { applyCanvasAction, buildCanvasMessage, buildCanvasDirective, CANVAS_PROTOCOL, parseCanvasMessage } from './agent-protocol'

function node(id: string, over: Partial<CanvasNode> = {}): CanvasNode {
  return {
    id,
    kind: 'shape',
    shape: 'rect',
    card: null,
    x: 0,
    y: 0,
    width: 100,
    height: 50,
    title: '',
    body: '',
    url: null,
    style: { fill: '#000', stroke: '#fff', strokeWidth: 1, radius: 0 },
    ...over,
  }
}

function base() {
  return { version: 1 as const, nodes: [node('a'), node('b')], connectors: [], strokes: [] }
}

describe('applyCanvasAction', () => {
  it('CREATE_NODE thêm node', () => {
    const scene = base()
    const next = applyCanvasAction(scene, { type: 'CREATE_NODE', node: node('c') })
    expect(next.nodes.map((n) => n.id)).toEqual(['a', 'b', 'c'])
  })

  it('CREATE_NODE từ chối id trùng', () => {
    const scene = base()
    const next = applyCanvasAction(scene, { type: 'CREATE_NODE', node: node('a') })
    expect(next.nodes).toHaveLength(2)
  })

  it('CONNECT_NODES thêm connector (tự sinh id) và từ chối thiếu node', () => {
    const scene = base()
    const ok = applyCanvasAction(scene, { type: 'CONNECT_NODES', connector: { fromNodeId: 'a', toNodeId: 'b', fromAnchor: 'right', toAnchor: 'left', stroke: '#000', strokeWidth: 1 } })
    expect(ok.connectors).toHaveLength(1)
    expect(ok.connectors[0].id).toBeTruthy()

    const rejected = applyCanvasAction(scene, { type: 'CONNECT_NODES', connector: { fromNodeId: 'a', toNodeId: 'missing', fromAnchor: 'right', toAnchor: 'left', stroke: '#000', strokeWidth: 1 } })
    expect(rejected.connectors).toHaveLength(0)
  })

  it('UPDATE_NODE merge patch, từ chối node lạ', () => {
    const scene = base()
    const ok = applyCanvasAction(scene, { type: 'UPDATE_NODE', nodeId: 'a', patch: { title: 'Mới' } })
    expect(ok.nodes.find((n) => n.id === 'a')?.title).toBe('Mới')

    const rejected = applyCanvasAction(scene, { type: 'UPDATE_NODE', nodeId: 'zzz', patch: { title: 'X' } })
    expect(rejected).toEqual(scene)
  })

  it('DELETE_NODE xóa node + cascade connector', () => {
    const scene = applyCanvasAction(base(), { type: 'CONNECT_NODES', connector: { fromNodeId: 'a', toNodeId: 'b', fromAnchor: 'right', toAnchor: 'left', stroke: '#000', strokeWidth: 1 } })
    const next = applyCanvasAction(scene, { type: 'DELETE_NODE', nodeId: 'a' })
    expect(next.nodes.map((n) => n.id)).toEqual(['b'])
    expect(next.connectors).toHaveLength(0)
  })
})

describe('build / parse', () => {
  it('buildCanvasMessage có protocol đúng và round-trip qua parse', () => {
    const scene = base()
    const msg = buildCanvasMessage(scene)
    expect(msg.protocol).toBe(CANVAS_PROTOCOL)
    expect(parseCanvasMessage(JSON.stringify(msg))).toMatchObject({ type: 'scene', scene })
  })

  it('buildCanvasDirective chứa target + instruction', () => {
    const d = buildCanvasDirective('a', 'Tiêu đề', 'Lệnh')
    expect(d).toMatchObject({ protocol: CANVAS_PROTOCOL, type: 'directive', targetNodeId: 'a', targetNodeTitle: 'Tiêu đề', instruction: 'Lệnh' })
  })

  it('parse từ chối message sai protocol / JSON lỗi', () => {
    expect(parseCanvasMessage('not-json')).toBeNull()
    expect(parseCanvasMessage(JSON.stringify({ protocol: 'lạ', type: 'scene' }))).toBeNull()
  })
})

describe('createEmptyScene', () => {
  it('cảnh rỗng', () => {
    expect(createEmptyScene()).toEqual({ version: 1, nodes: [], connectors: [], strokes: [] })
  })
})
