/**
 * Nhà máy transport DUY NHẤT.
 *
 * LUẬT KIẾN TRÚC: store và component KHÔNG được biết đang dùng transport nào.
 * Chúng chỉ nhận `ServerEvent` và phát `ClientCommand`. Mọi chỗ cần transport
 * đều đi qua hàm dưới đây, không `new MockTransport()` rải rác.
 *
 * Chọn bằng biến môi trường:
 *   VITE_TRANSPORT=mock  (mặc định) — kịch bản demo trong trình duyệt
 *   VITE_TRANSPORT=live            — WebSocket tới VITE_AGENT_WS_URL
 */
import { MockTransport } from './mock'
import { WebSocketTransport } from './websocket'
import type { AgentTransport } from './types'

export type { AgentTransport, TransportStatus } from './types'
export { MockTransport } from './mock'
export { WebSocketTransport, parseServerEvent } from './websocket'
export { WebRtcScreenTransport } from './webrtc'
export type { SignalingChannel, WebRtcScreenCallbacks } from './webrtc'

export function createTransport(): AgentTransport {
  const mode = import.meta.env.VITE_TRANSPORT ?? 'mock'
  if (mode === 'live') {
    const url = import.meta.env.VITE_AGENT_WS_URL ?? 'ws://127.0.0.1:8765'
    return new WebSocketTransport(url)
  }
  return new MockTransport()
}
