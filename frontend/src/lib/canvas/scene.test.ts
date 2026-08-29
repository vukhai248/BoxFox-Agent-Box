import { describe, expect, it } from 'vitest'
import type { CanvasNode, CanvasScene } from './types'
import { createInitialScene, deserialize, removeNode, serialize } from './scene'

function node(id: string, kind: CanvasNode['kind'], over: Partial<CanvasNode> = {}): CanvasNode {
  return {
    id,
    kind,
    shape: kind === 'shape' ? (over.shape ?? 'rect') : null,
    card: kind === 'card' ? (over.card ?? 'ui-mockup') : null,
    x: 0,
    y: 0,
    width: 100,
    height: 50,
    title: '',
    body: '',
    url: kind === 'webview' ? 'https://example.com' : null,
    style: { fill: '#1c1c1c', stroke: '#3b82f6', strokeWidth: 2, radius: 8 },
    ...over,
  }
}

describe('createInitialScene', () => {
  it('seed 3 card (380/340/500) + 1 connector + không stroke', () => {
    const scene = createInitialScene()
    expect(scene.version).toBe(1)
    expect(scene.nodes).toHaveLength(3)
    expect(scene.nodes.map((n) => n.width)).toEqual([380, 340, 500])
    expect(scene.nodes.every((n) => n.kind === 'card')).toBe(true)
    expect(scene.connectors).toHaveLength(1)
    expect(scene.connectors[0]).toMatchObject({ id: 'conn-1', fromNodeId: 'node-c1', toNodeId: 'node-c2', fromAnchor: 'right', toAnchor: 'left' })
    expect(scene.strokes).toHaveLength(0)
  })
})

describe('serialize / deserialize round-trip', () => {
  it('giữ nguyên từng field cho node/connector/stroke', () => {
    const scene: CanvasScene = {
      version: 1,
      nodes: [
        node('a', 'shape', { x: 10, y: 20, width: 30, height: 40, style: { fill: '#f5f5f5', stroke: '#f59e0b', strokeWidth: 4, radius: 6 } }),
        node('b', 'card', { x: 100, y: 200, width: 380, height: 240, title: 'T', body: 'B' }),
        node('w', 'webview', { url: 'https://box.app' }),
      ],
      connectors: [
        { id: 'c1', fromNodeId: 'a', toNodeId: 'b', fromAnchor: 'right', toAnchor: 'left', stroke: '#3b82f6', strokeWidth: 2 },
      ],
      strokes: [{ id: 's1', points: [{ x: 0, y: 0 }, { x: 12, y: 4 }], color: '#10b981', width: 3 }],
    }
    expect(deserialize(serialize(scene))).toEqual(scene)
  })
})

describe('deserialize từ chối dữ liệu lạ', () => {
  it('JSON không phải object', () => {
    expect(() => deserialize('[1,2,3]')).toThrow()
    expect(() => deserialize('123')).toThrow()
  })

  it('thiếu mảng nodes/connectors/strokes', () => {
    expect(() => deserialize(JSON.stringify({ version: 1 }))).toThrow()
  })

  it('version khác 1', () => {
    expect(() => deserialize(JSON.stringify({ version: 2, nodes: [], connectors: [], strokes: [] }))).toThrow()
  })

  it('field lạ thừa bị bỏ qua (forward-compatible)', () => {
    const scene = deserialize(JSON.stringify({ version: 1, nodes: [], connectors: [], strokes: [], extra: true }))
    expect(scene).toEqual({ version: 1, nodes: [], connectors: [], strokes: [] })
  })
})

describe('removeNode', () => {
  it('xóa node đồng thời loại connector trỏ tới node đó, bất biến', () => {
    const scene: CanvasScene = {
      version: 1,
      nodes: [node('a', 'shape'), node('b', 'card')],
      connectors: [
        { id: 'c1', fromNodeId: 'a', toNodeId: 'b', fromAnchor: 'right', toAnchor: 'left', stroke: '#000', strokeWidth: 1 },
        { id: 'c2', fromNodeId: 'b', toNodeId: 'a', fromAnchor: 'left', toAnchor: 'right', stroke: '#000', strokeWidth: 1 },
      ],
      strokes: [],
    }
    const next = removeNode(scene, 'a')
    expect(next.nodes.map((n) => n.id)).toEqual(['b'])
    expect(next.connectors).toHaveLength(0)
    // scene gốc không đổi
    expect(scene.nodes).toHaveLength(2)
    expect(scene.connectors).toHaveLength(2)
  })
})

describe('deserialize loại connector mồ côi', () => {
  it('connector trỏ node không tồn tại bị loại, parse vẫn thành công', () => {
    const scene = deserialize(
      JSON.stringify({
        version: 1,
        nodes: [node('a', 'shape')],
        connectors: [
          { id: 'ok', fromNodeId: 'a', toNodeId: 'a', fromAnchor: 'right', toAnchor: 'left', stroke: '#000', strokeWidth: 1 },
          { id: 'orphan', fromNodeId: 'a', toNodeId: 'missing', fromAnchor: 'right', toAnchor: 'left', stroke: '#000', strokeWidth: 1 },
        ],
        strokes: [],
      }),
    )
    expect(scene.connectors.map((c) => c.id)).toEqual(['ok'])
  })
})
