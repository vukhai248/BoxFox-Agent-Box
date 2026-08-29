import { describe, expect, it } from 'vitest'
import type { CanvasNode } from './types'
import { boundsOfNode, boundsOfStroke, pointsToPath, screenToWorld, worldToScreen } from './geometry'

function node(over: Partial<CanvasNode> = {}): CanvasNode {
  return {
    id: 'n1',
    kind: 'shape',
    shape: 'rect',
    card: null,
    x: 10,
    y: 20,
    width: 30,
    height: 40,
    title: '',
    body: '',
    url: null,
    style: { fill: '#000', stroke: '#fff', strokeWidth: 1, radius: 0 },
    ...over,
  }
}

describe('screenToWorld', () => {
  it('zoom 100% + origin(0,0) + pan(0,0) giữ nguyên tọa độ', () => {
    expect(screenToWorld({ x: 100, y: 100 }, { scale: 1, pan: { x: 0, y: 0 }, origin: { x: 0, y: 0 } })).toEqual({ x: 100, y: 100 })
  })

  it('zoom 50% nhân đôi tọa độ', () => {
    expect(screenToWorld({ x: 10, y: 20 }, { scale: 0.5, pan: { x: 0, y: 0 }, origin: { x: 0, y: 0 } })).toEqual({ x: 20, y: 40 })
  })

  it('zoom 150% thu nhỏ tọa độ', () => {
    expect(screenToWorld({ x: 30, y: 15 }, { scale: 1.5, pan: { x: 0, y: 0 }, origin: { x: 0, y: 0 } })).toEqual({ x: 20, y: 10 })
  })

  it('trừ offset pan', () => {
    const view = { scale: 1, pan: { x: 50, y: -30 }, origin: { x: 0, y: 0 } }
    expect(screenToWorld({ x: 150, y: 70 }, view)).toEqual({ x: 100, y: 100 })
  })

  it('trừ origin (rect offset của container)', () => {
    const view = { scale: 1, pan: { x: 0, y: 0 }, origin: { x: 12, y: 8 } }
    expect(screenToWorld({ x: 212, y: 108 }, view)).toEqual({ x: 200, y: 100 })
  })
})

describe('worldToScreen', () => {
  it('là nghịch đảo của screenToWorld (round-trip ~1e-9)', () => {
    const view = { scale: 0.75, pan: { x: 42, y: -17 }, origin: { x: 3.5, y: 9.25 } }
    const screen = { x: 312.5, y: 88.125 }
    const world = screenToWorld(screen, view)
    const back = worldToScreen(world, view)
    expect(back.x).toBeCloseTo(screen.x, 9)
    expect(back.y).toBeCloseTo(screen.y, 9)
  })
})

describe('bounds', () => {
  it('boundsOfNode rect 30x40 tại (10,20)', () => {
    expect(boundsOfNode(node())).toEqual({ minX: 10, minY: 20, maxX: 40, maxY: 60 })
  })

  it('boundsOfNode kể cả ellipse (nội tiếp w x h)', () => {
    expect(boundsOfNode(node({ shape: 'ellipse' }))).toEqual({ minX: 10, minY: 20, maxX: 40, maxY: 60 })
  })

  it('boundsOfStroke min/max trên toàn bộ điểm', () => {
    expect(
      boundsOfStroke([
        { x: 0, y: 0 },
        { x: 10, y: -5 },
        { x: 3, y: 8 },
      ]),
    ).toEqual({ minX: 0, minY: -5, maxX: 10, maxY: 8 })
  })

  it('boundsOfStroke một điểm → box rỗng (min = max)', () => {
    expect(boundsOfStroke([{ x: 7, y: 9 }])).toEqual({ minX: 7, minY: 9, maxX: 7, maxY: 9 })
  })

  it('boundsOfStroke rỗng → box 0 hết', () => {
    expect(boundsOfStroke([])).toEqual({ minX: 0, minY: 0, maxX: 0, maxY: 0 })
  })
})

describe('pointsToPath', () => {
  it('nối các điểm thành path SVG', () => {
    expect(
      pointsToPath([
        { x: 0, y: 0 },
        { x: 10, y: -5 },
      ]),
    ).toBe('M 0 0 L 10 -5')
  })

  it('rỗng trả chuỗi rỗng', () => {
    expect(pointsToPath([])).toBe('')
  })
})
