/**
 * Hợp đồng của tầng transport.
 *
 * Store CHỈ biết interface này. Nó không biết dữ liệu đến từ kịch bản mock
 * trong trình duyệt, từ WebSocket của backend, hay từ WebRTC. Nhờ vậy đổi
 * nguồn dữ liệu không phải sửa một dòng nào trong store hay component.
 */
import type { ClientCommand, ServerEvent } from '../../types/transport'

export type TransportStatus = 'disconnected' | 'connecting' | 'connected' | 'error'

export interface AgentTransport {
  connect(sessionId: string): Promise<void>
  disconnect(): void
  send(command: ClientCommand): void
  /** Trả về hàm bỏ đăng ký. */
  subscribe(handler: (event: ServerEvent) => void): () => void
  readonly status: TransportStatus
  /** Đăng ký nhận thay đổi trạng thái kết nối. Trả về hàm bỏ đăng ký. */
  onStatusChange(handler: (status: TransportStatus) => void): () => void
  /** 'mock' hoặc 'live' — chỉ để giao diện hiện băng cho người dùng biết. */
  readonly kind: 'mock' | 'live'
}

/** Phần chung: quản lý danh sách người nghe và trạng thái. */
export abstract class BaseTransport implements AgentTransport {
  abstract readonly kind: 'mock' | 'live'

  private eventHandlers = new Set<(event: ServerEvent) => void>()
  private statusHandlers = new Set<(status: TransportStatus) => void>()
  private currentStatus: TransportStatus = 'disconnected'

  get status(): TransportStatus {
    return this.currentStatus
  }

  abstract connect(sessionId: string): Promise<void>
  abstract disconnect(): void
  abstract send(command: ClientCommand): void

  subscribe(handler: (event: ServerEvent) => void): () => void {
    this.eventHandlers.add(handler)
    return () => this.eventHandlers.delete(handler)
  }

  onStatusChange(handler: (status: TransportStatus) => void): () => void {
    this.statusHandlers.add(handler)
    return () => this.statusHandlers.delete(handler)
  }

  protected emit(event: ServerEvent): void {
    for (const handler of this.eventHandlers) handler(event)
  }

  protected emitAll(events: readonly ServerEvent[]): void {
    for (const event of events) this.emit(event)
  }

  protected setStatus(status: TransportStatus): void {
    if (this.currentStatus === status) return
    this.currentStatus = status
    for (const handler of this.statusHandlers) handler(status)
  }
}
