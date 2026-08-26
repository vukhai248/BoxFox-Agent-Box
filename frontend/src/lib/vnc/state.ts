/**
 * Máy trạng thái của kênh noVNC (connecting / live / offline).
 *
 * Logic thuần, không React, không DOM — `src/lib/vnc/attempt.ts` giữ vòng đời
 * một lượt kết nối, `src/hooks/useVncScreen.ts` nối hai thứ đó với React
 * (plan §4, quyết định D-1).
 *
 * Chính sách thử lại (D-7): 1 lần đầu + 3 lần tự thử lại, mỗi lần chờ tối đa
 * `VNC_CONNECT_TIMEOUT_MS`, khoảng nghỉ giữa các lần lấy từ
 * `VNC_RETRY_DELAYS_MS`. Hết lượt → `exhausted = true`, dừng và chờ người
 * dùng bấm "Thử kết nối lại". Không thử lại vô hạn vì mỗi lần thất bại
 * trình duyệt tự ghi một dòng đỏ WebSocket vào console (không tắt được).
 */

export type VncPhase = 'connecting' | 'live' | 'offline'

export type VncOfflineReason =
  | 'timeout'
  | 'closed'
  | 'security'
  | 'credentials'
  | 'mixedContent'
  | 'insecureContext'
  | 'unsupported'
  | 'error'
  | 'skipped'
  /** Nguồn khung hình đang là `mock` — chưa từng thử nối, đây không phải lỗi. */
  | 'disabled'

export interface VncState {
  phase: VncPhase
  reason: VncOfflineReason | null
  attempt: number
  exhausted: boolean
  /** Tăng mỗi lần cần mở kết nối mới — hook dùng làm dependency của effect nối. */
  seq: number
}

export type VncEvent =
  | { type: 'connectStarted' }
  | { type: 'connected' }
  | { type: 'timeout' }
  /**
   * Phía kia đóng kênh ngoài ý muốn.
   *
   * Không mang cờ `clean` của noVNC: noVNC báo `clean: true` cả khi container
   * đóng một socket đã dựng xong, nên dùng cờ đó để đoán "người dùng tự đóng"
   * là sai và sẽ giết luôn 3 lượt thử lại mà D-7 đã hứa. Việc mình tự đóng
   * (skip / unmount / retry tay) do `abort()` của attempt xử lý và KHÔNG bao
   * giờ phát sự kiện này.
   */
  | { type: 'closed' }
  | { type: 'failed'; reason: VncOfflineReason }
  | { type: 'skip' }
  | { type: 'manualRetry' }

export const VNC_CONNECT_TIMEOUT_MS = 5000
export const VNC_RETRY_DELAYS_MS = [3000, 8000, 20000]
/** 1 lần đầu + 3 lần tự thử lại. */
export const VNC_MAX_ATTEMPTS = 4

export const initialVncState: VncState = {
  phase: 'connecting',
  reason: null,
  attempt: 1,
  exhausted: false,
  seq: 0,
}

/** Trạng thái khi nguồn khung hình là `mock`: không nối, không thử lại. */
export const disabledVncState: VncState = {
  phase: 'offline',
  reason: 'disabled',
  attempt: 1,
  exhausted: true,
  seq: 0,
}

/** Những lý do mà thử lại vô nghĩa (lỗi cấu hình/khả năng, không phải box tạm ngưng). */
const TERMINAL_REASONS: readonly VncOfflineReason[] = [
  'security',
  'credentials',
  'mixedContent',
  'insecureContext',
  'unsupported',
  'disabled',
]

export function reduceVnc(state: VncState, event: VncEvent): VncState {
  switch (event.type) {
    case 'connectStarted':
      return {
        ...state,
        phase: 'connecting',
        reason: null,
        attempt: state.phase === 'offline' ? state.attempt + 1 : state.attempt,
        exhausted: false,
        seq: state.seq + 1,
      }

    case 'connected':
      return { ...state, phase: 'live', reason: null, attempt: 1, exhausted: false }

    case 'timeout': {
      if (state.phase === 'offline') return state
      return {
        ...state,
        phase: 'offline',
        reason: 'timeout',
        exhausted: state.attempt >= VNC_MAX_ATTEMPTS,
      }
    }

    case 'closed': {
      if (state.phase === 'offline') return state
      // Kênh đang live bị rơi ⇒ ngân sách thử lại tính lại từ đầu (`connected`
      // đã đặt attempt = 1), nên vẫn còn đủ 3 lượt như D-7 hứa.
      return {
        ...state,
        phase: 'offline',
        reason: 'closed',
        exhausted: state.attempt >= VNC_MAX_ATTEMPTS,
      }
    }

    case 'failed': {
      if (TERMINAL_REASONS.includes(event.reason)) {
        return { ...state, phase: 'offline', reason: event.reason, exhausted: true }
      }
      // reason === 'error' — cư xử như `closed`
      if (state.phase === 'offline') return state
      return {
        ...state,
        phase: 'offline',
        reason: event.reason,
        exhausted: state.attempt >= VNC_MAX_ATTEMPTS,
      }
    }

    case 'skip':
      return { ...state, phase: 'offline', reason: 'skipped', exhausted: true }

    case 'manualRetry':
      return {
        ...state,
        phase: 'connecting',
        reason: null,
        attempt: 1,
        exhausted: false,
        seq: state.seq + 1,
      }

    default:
      return state
  }
}

/** `null` nếu không ở trạng thái chờ thử lại tự động; ngược lại số ms cần chờ. */
export function retryDelayMs(state: VncState): number | null {
  if (state.phase !== 'offline' || state.exhausted) return null
  return VNC_RETRY_DELAYS_MS[state.attempt - 1] ?? null
}
