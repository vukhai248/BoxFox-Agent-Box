import { describe, expect, it } from 'vitest'
import type { Anchor, CanvasConnector, CanvasNode } from './types'
import { anchorPoint, connectorPath, nearestAnchors } from './connectors'

function node(id: string, x: number, y: number, width: number, height: number): CanvasNode {
  return {
    id,
    kind: 'card',
    shape: null,
    card: 'ui-mockup',
    x,
    y,
    width,
    height,
    title: '',
    body: '',
    url: null,
    style: { fill: '#000', stroke: '#fff', strokeWidth: 1, radius: 0 },
  }
}

describe('anchorPoint', () => {
  const n = node('n', 0, 0, 100, 50)
  it('neo đúng 5 vị trí', () => {
    expect(anchorPoint(n, 'top')).toEqual({ x: 50, y: 0 })
    expect(anchorPoint(n, 'right')).toEqual({ x: 100, y: 25 })
    expect(anchorPoint(n, 'bottom')).toEqual({ x: 50, y: 50 })
    expect(anchorPoint(n, 'left')).toEqual({ x: 0, y: 25 })
    expect(anchorPoint(n, 'center')).toEqual({ x: 50, y: 25 })
  })
})

describe('nearestAnchors', () => {
  it('cặp nằm ngang → right/left', () => {
    const a = node('a', 0, 0, 100, 50)
    const b = node('b', 200, 0, 100, 50)
    expect(nearestAnchors(a, b)).toEqual({ from: 'right', to: 'left' })
  })

  it('cặp thẳng đứng → bottom/top', () => {
    const a = node('a', 0, 0, 100, 50)
    const b = node('b', 0, 120, 100, 50)
    expect(nearestAnchors(a, b)).toEqual({ from: 'bottom', to: 'top' })
  })

  it('cặp chéo rộng ngang → right/left', () => {
    const a = node('a', 0, 0, 100, 50)
    const b = node('b', 300, 200, 100, 50)
    expect(nearestAnchors(a, b)).toEqual({ from: 'right', to: 'left' })
  })

  it('cặp chéo cao dọc → bottom/top', () => {
    const a = node('a', 0, 0, 100, 50)
    const b = node('b', 60, 200, 100, 50)
    expect(nearestAnchors(a, b)).toEqual({ from: 'bottom', to: 'top' })
  })

  it('cặp đè nhau một phần trả cặp hợp lệ, không center, deterministic', () => {
    const a = node('a', 0, 0, 100, 50)
    const b = node('b', 40, 0, 100, 50)
    const first = nearestAnchors(a, b)
    const second = nearestAnchors(a, b)
    const anchors: Anchor[] = ['top', 'right', 'bottom', 'left', 'center']
    expect(anchors).toContain(first.from)
    expect(anchors).toContain(first.to)
    expect(first.from).not.toBe('center')
    expect(first.to).not.toBe('center')
    expect(first).toEqual(second)
  })
})

describe('connectorPath recompute sau khi move', () => {
  it('endpoint bám theo cạnh neo đã chọn khi node di chuyển', () => {
    const movedA = node('a', 30, 40, 100, 50)
    const b = node('b', 200, 0, 100, 50)
    const connector: CanvasConnector = {
      id: 'c1',
      fromNodeId: 'a',
      toNodeId: 'b',
      fromAnchor: 'right',
      toAnchor: 'left',
      stroke: '#3b82f6',
      strokeWidth: 2,
    }
    const from = anchorPoint(movedA, 'right')
    const d = connectorPath(connector, [movedA, b])
    expect(from).toEqual({ x: 130, y: 65 })
    expect(d.startsWith(`M ${from.x} ${from.y}`)).toBe(true)
    // thân + 2 cánh arrowhead = 3 đoạn (3 chữ M)
    expect(d.split('M').length - 1).toBe(3)
  })
})
