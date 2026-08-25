/**
 * Transport thật qua WebSocket.
 *
 * Backend chưa tồn tại nên đường này chưa chạy được, NHƯNG code phải hoàn
 * chỉnh và biên dịch sạch — để lúc backend xong chỉ cần đổi biến môi trường,
 * không phải viết lại.
 *
 * Có hai thứ dễ bị bỏ quên nên làm luôn:
 *  1. Tự nối lại với backoff tăng dần (1s → 2s → 4s → … tối đa 15s).
 *  2. Hàng đợi lệnh khi chưa connected — lệnh gửi lúc mất mạng không bị mất.
 *
 * Kiểm `Origin` và chỉ nghe loopback là việc của phía backend (mục 12.6).
 */
import type { ClientCommand, ServerEvent } from '../../types/transport'
import { BaseTransport } from './types'

const BACKOFF_START_MS = 1000
const BACKOFF_MAX_MS = 15000

export class WebSocketTransport extends BaseTransport {
  readonly kind = 'live' as const

  private socket: WebSocket | null = null
  private sessionId = ''
  private queue: ClientCommand[] = []
  private backoffMs = BACKOFF_START_MS
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private closedByUs = false

  constructor(private readonly baseUrl: string) {
    super()
  }

  connect(sessionId: string): Promise<void> {
    this.sessionId = sessionId
    this.closedByUs = false
    return this.open()
  }

  private open(): Promise<void> {
    return new Promise((resolve) => {
      this.setStatus('connecting')
      const url = `${this.baseUrl.replace(/\/$/, '')}/ws/session/${encodeURIComponent(this.sessionId)}`

      let socket: WebSocket
      try {
        socket = new WebSocket(url)
      } catch {
        this.setStatus('error')
        this.scheduleReconnect()
        resolve()
        return
      }
      this.socket = socket

      socket.onopen = () => {
        this.backoffMs = BACKOFF_START_MS
        this.setStatus('connected')
        this.flushQueue()
        resolve()
      }

      socket.onmessage = (raw: MessageEvent<string>) => {
        const event = parseServerEvent(raw.data)
        if (event) this.emit(event)
      }

      socket.onerror = () => {
        this.setStatus('error')
      }

      socket.onclose = () => {
        this.socket = null
        if (this.closedByUs) {
          this.setStatus('disconnected')
          return
        }
        this.setStatus('disconnected')
        this.scheduleReconnect()
        resolve()
      }
    })
  }

  disconnect(): void {
    this.closedByUs = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.socket?.close()
    this.socket = null
    this.setStatus('disconnected')
  }

  send(command: ClientCommand): void {
    if (this.socket && this.socket.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(command))
      return
    }
    // Chưa nối được: xếp hàng, gửi lại ngay khi nối lại xong.
    this.queue.push(command)
  }

  private flushQueue(): void {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) return
    const pending = this.queue
    this.queue = []
    for (const command of pending) this.socket.send(JSON.stringify(command))
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer || this.closedByUs) return
    const delay = this.backoffMs
    this.backoffMs = Math.min(this.backoffMs * 2, BACKOFF_MAX_MS)
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      void this.open()
    }, delay)
  }
}

/**
 * Đọc một sự kiện từ dây. Dữ liệu từ mạng KHÔNG được tin: chỉ nhận khi có
 * trường `type` là chuỗi, còn lại bỏ qua và không làm sập giao diện.
 */
export function parseServerEvent(raw: string): ServerEvent | null {
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return null
    const type = (parsed as { type?: unknown }).type
    if (typeof type !== 'string') return null
    return parsed as ServerEvent
  } catch {
    return null
  }
}
