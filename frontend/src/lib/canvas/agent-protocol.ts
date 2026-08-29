/**
 * Giao thức hai chiều giữa Design Canvas và Agent ("boxfox.canvas.v1").
 *
 * - User → Agent: message `scene` (gửi toàn bộ scene) và `directive` (chuột
 *   phải vào một component → "bảo agent sửa đúng component đó").
 * - Agent → UI: message `action` gồm 4 lệnh tối thiểu (CREATE_NODE/CONNECT_NODES/
 *   UPDATE_NODE/DELETE_NODE), reducer thuần `applyCanvasAction`.
 *
 * Việc nối transport thật (`agentStore.sendCommand`) sẽ điền ở hook
 * `useDesignCanvas` — xem TODO tại đó; hợp đồng JSON dưới đây đã sẵn sàng.
 */
import { newId } from './id'
import { deserialize, isAnchor, nodeById, removeNode, upsertNode } from './scene'
import type { CanvasConnector, CanvasNode, CanvasScene } from './types'

export const CANVAS_PROTOCOL = 'boxfox.canvas.v1'

/** Message User → Agent: gửi cảnh hiện tại. */
export interface CanvasSceneMessage {
  protocol: typeof CANVAS_PROTOCOL
  type: 'scene'
  scene: CanvasScene
}

/** Message User → Agent: chỉ thị "sửa đúng component này". */
export interface CanvasDirectiveMessage {
  protocol: typeof CANVAS_PROTOCOL
  type: 'directive'
  targetNodeId: string
  targetNodeTitle: string
  instruction: string
}

export type CanvasOutboundMessage = CanvasSceneMessage | CanvasDirectiveMessage

export function buildCanvasMessage(scene: CanvasScene): CanvasSceneMessage {
  // Trả về object có cấu trúc sẵn (scene bất biến — an toàn để serialize).
  return { protocol: CANVAS_PROTOCOL, type: 'scene', scene }
}

export function buildCanvasDirective(targetNodeId: string, targetNodeTitle: string, instruction: string): CanvasDirectiveMessage {
  return { protocol: CANVAS_PROTOCOL, type: 'directive', targetNodeId, targetNodeTitle, instruction }
}

/** Lệnh tác vụ tối thiểu Agent → UI (reducer thuần). */
export type CanvasAction =
  | { type: 'CREATE_NODE'; node: CanvasNode }
  | { type: 'CONNECT_NODES'; connector: Omit<CanvasConnector, 'id'> & { id?: string } }
  | { type: 'UPDATE_NODE'; nodeId: string; patch: Partial<CanvasNode> }
  | { type: 'DELETE_NODE'; nodeId: string }

/**
 * Áp dụng một `CanvasAction` lên scene (bất biến). Các lệnh không hợp lệ trả
 * scene cũ nguyên vẹn (không tự bịa dữ liệu): CREATE_NODE từ chối id trùng;
 * CONNECT_NODES từ chối nếu thiếu node tham chiếu; UPDATE_NODE từ chối node lạ;
 * DELETE_NODE xóa node + CASCADE mọi connector trỏ tới node đó.
 */
export function applyCanvasAction(scene: CanvasScene, action: CanvasAction): CanvasScene {
  switch (action.type) {
    case 'CREATE_NODE': {
      if (scene.nodes.some((n) => n.id === action.node.id)) return scene
      return { ...scene, nodes: [...scene.nodes, action.node] }
    }
    case 'CONNECT_NODES': {
      const hasBoth = scene.nodes.some((n) => n.id === action.connector.fromNodeId) && scene.nodes.some((n) => n.id === action.connector.toNodeId)
      if (!hasBoth) return scene
      const connector: CanvasConnector = { ...action.connector, id: action.connector.id ?? newId('conn') }
      return { ...scene, connectors: [...scene.connectors, connector] }
    }
    case 'UPDATE_NODE': {
      if (!nodeById(scene, action.nodeId)) return scene
      return upsertNode(scene, { ...nodeById(scene, action.nodeId)!, ...action.patch, id: action.nodeId })
    }
    case 'DELETE_NODE': {
      if (!nodeById(scene, action.nodeId)) return scene
      return removeNode(scene, action.nodeId)
    }
  }
}

/** Message Agent → UI: chứa một `action`. */
export interface CanvasActionMessage {
  protocol: typeof CANVAS_PROTOCOL
  type: 'action'
  action: CanvasAction
}

export type CanvasInboundMessage = CanvasActionMessage

export type ParsedCanvasMessage = CanvasOutboundMessage | CanvasInboundMessage

/**
 * Parse một message JSON (chuỗi hoặc object). Trả `null` nếu sai protocol,
 * sai type hoặc nội dung không hợp lệ (fail-safe cho dữ liệu lạ từ backend).
 */
export function parseCanvasMessage(json: string | unknown): ParsedCanvasMessage | null {
  let raw: unknown = json
  if (typeof json === 'string') {
    try {
      raw = JSON.parse(json)
    } catch {
      return null
    }
  }
  if (typeof raw !== 'object' || raw === null) return null
  const rec = raw as Record<string, unknown>
  if (rec.protocol !== CANVAS_PROTOCOL) return null

  if (rec.type === 'scene' && rec.scene !== undefined) {
    try {
      return { protocol: CANVAS_PROTOCOL, type: 'scene', scene: deserialize(rec.scene) }
    } catch {
      return null
    }
  }

  if (rec.type === 'directive') {
    return {
      protocol: CANVAS_PROTOCOL,
      type: 'directive',
      targetNodeId: typeof rec.targetNodeId === 'string' ? rec.targetNodeId : '',
      targetNodeTitle: typeof rec.targetNodeTitle === 'string' ? rec.targetNodeTitle : '',
      instruction: typeof rec.instruction === 'string' ? rec.instruction : '',
    }
  }

  if (rec.type === 'action') {
    const action = parseAction(rec.action)
    return action ? { protocol: CANVAS_PROTOCOL, type: 'action', action } : null
  }

  return null
}

function parseAction(raw: unknown): CanvasAction | null {
  if (typeof raw !== 'object' || raw === null) return null
  const a = raw as Record<string, unknown>
  switch (a.type) {
    case 'CREATE_NODE': {
      try {
        // Tái dùng normalize node của scene bằng cách bọc node thành scene tạm.
        const scene = deserialize({ version: 1, nodes: [a.node], connectors: [], strokes: [] })
        const node = scene.nodes[0]
        return node ? { type: 'CREATE_NODE', node } : null
      } catch {
        return null
      }
    }
    case 'CONNECT_NODES': {
      const c = a.connector
      if (typeof c !== 'object' || c === null) return null
      const cc = c as Record<string, unknown>
      const connector: Omit<CanvasConnector, 'id'> & { id?: string } = {
        fromNodeId: typeof cc.fromNodeId === 'string' ? cc.fromNodeId : '',
        toNodeId: typeof cc.toNodeId === 'string' ? cc.toNodeId : '',
        fromAnchor: isAnchor(cc.fromAnchor) ? cc.fromAnchor : 'center',
        toAnchor: isAnchor(cc.toAnchor) ? cc.toAnchor : 'center',
        stroke: typeof cc.stroke === 'string' ? cc.stroke : '#3b82f6',
        strokeWidth: typeof cc.strokeWidth === 'number' ? cc.strokeWidth : 2,
      }
      if (typeof cc.id === 'string') connector.id = cc.id
      return { type: 'CONNECT_NODES', connector }
    }
    case 'UPDATE_NODE': {
      if (typeof a.nodeId !== 'string' || typeof a.patch !== 'object' || a.patch === null) return null
      return { type: 'UPDATE_NODE', nodeId: a.nodeId, patch: a.patch as Partial<CanvasNode> }
    }
    case 'DELETE_NODE': {
      if (typeof a.nodeId !== 'string') return null
      return { type: 'DELETE_NODE', nodeId: a.nodeId }
    }
    default:
      return null
  }
}
