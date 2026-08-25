/**
 * Nhận màn hình máy ảo qua WebRTC.
 *
 * Signaling (offer/answer/ICE) KHÔNG mở kết nối riêng — nó đi chung đúng cái
 * WebSocket đã có, bằng ba sự kiện `screen_offer` / `screen_answer` /
 * `screen_ice`. Ít cổng mở hơn, và mọi thứ vẫn nằm trong ranh giới đã kiểm
 * `Origin` một lần (mục 12.6).
 *
 * Backend chưa có nên đường này chưa chạy; thất bại thì rơi về màn hình mô
 * phỏng và báo rõ cho người dùng biết đang xem bản mô phỏng — KHÔNG bao giờ
 * hiện màn hình giả mà giả vờ là thật.
 */
import type { ClientCommand, ServerEvent } from '../../types/transport'

/** Kênh signaling — thực tế là chính `AgentTransport`. */
export interface SignalingChannel {
  send(command: ClientCommand): void
  subscribe(handler: (event: ServerEvent) => void): () => void
}

export interface WebRtcScreenCallbacks {
  /** Có khung hình thật. Gắn stream này vào <video autoplay muted playsinline>. */
  onStream: (stream: MediaStream) => void
  /** Không nối được — giao diện phải hiện băng "đang xem màn hình mô phỏng". */
  onFallback: (reason: string) => void
}

const ICE_SERVERS: RTCIceServer[] = [
  // Máy tự host trong LAN thì không cần STUN công cộng; để rỗng cho bản mặc
  // định để không có lưu lượng nào rời máy ngoài ý muốn.
]

export class WebRtcScreenTransport {
  private pc: RTCPeerConnection | null = null
  private unsubscribe: (() => void) | null = null

  constructor(
    private readonly signaling: SignalingChannel,
    private readonly callbacks: WebRtcScreenCallbacks,
  ) {}

  /** Bắt đầu chờ offer từ máy ảo. Chỉ NHẬN màn hình, không gửi gì lên. */
  start(): void {
    if (typeof RTCPeerConnection === 'undefined') {
      this.callbacks.onFallback('Trình duyệt không hỗ trợ WebRTC')
      return
    }

    let pc: RTCPeerConnection
    try {
      pc = new RTCPeerConnection({ iceServers: ICE_SERVERS })
    } catch {
      this.callbacks.onFallback('Không tạo được RTCPeerConnection')
      return
    }
    this.pc = pc

    pc.ontrack = (event: RTCTrackEvent) => {
      const stream = event.streams[0]
      if (stream) this.callbacks.onStream(stream)
    }

    pc.onicecandidate = (event: RTCPeerConnectionIceEvent) => {
      if (event.candidate) {
        this.signaling.send({ type: 'screen_ice', candidate: JSON.stringify(event.candidate) })
      }
    }

    pc.onconnectionstatechange = () => {
      if (pc.connectionState === 'failed' || pc.connectionState === 'disconnected') {
        this.callbacks.onFallback(`Kết nối WebRTC ở trạng thái ${pc.connectionState}`)
      }
    }

    this.unsubscribe = this.signaling.subscribe((event) => {
      void this.handleSignal(event)
    })
  }

  private async handleSignal(event: ServerEvent): Promise<void> {
    const pc = this.pc
    if (!pc) return

    try {
      if (event.type === 'screen_offer') {
        await pc.setRemoteDescription({ type: 'offer', sdp: event.sdp })
        const answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        this.signaling.send({ type: 'screen_answer', sdp: answer.sdp ?? '' })
      } else if (event.type === 'screen_answer') {
        await pc.setRemoteDescription({ type: 'answer', sdp: event.sdp })
      } else if (event.type === 'screen_ice') {
        const candidate: unknown = JSON.parse(event.candidate)
        await pc.addIceCandidate(candidate as RTCIceCandidateInit)
      }
    } catch (error) {
      this.callbacks.onFallback(
        `Signaling WebRTC lỗi: ${error instanceof Error ? error.message : 'không rõ'}`,
      )
    }
  }

  stop(): void {
    this.unsubscribe?.()
    this.unsubscribe = null
    this.pc?.close()
    this.pc = null
  }
}
