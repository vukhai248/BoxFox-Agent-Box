/**
 * Máy trạng thái của tab IDE (probing / live / offline).
 *
 * Logic thuần, không React, không DOM — `src/hooks/useIdeFrame.ts` nối nó với
 * React và với `fetch`.
 *
 * Vì sao KHÔNG dùng lại `src/lib/vnc/state.ts`: reducer của noVNC mang đúng
 * ngữ nghĩa của RFB (bắt tay bảo mật, đòi mật khẩu, phía kia đóng socket, bỏ
 * chờ để xem mô phỏng). Vòng đời ở đây chỉ có "gọi thử một lần xem code-server
 * có trả lời không", nên gộp hai thứ lại sẽ tạo ra một reducer mà nửa số nhánh
 * không bao giờ chạy — khó đọc hơn là hai reducer nhỏ.
 *
 * Chính sách thử lại giống khung ④ để người dùng không phải học hai kiểu:
 * 1 lần đầu + 3 lần tự thử lại, rồi dừng và chờ bấm "Thử kết nối lại".
 */

export type IdePhase = 'probing' | 'live' | 'offline'

export type IdeOfflineReason =
  /** code-server không trả lời (box tắt, hoặc cổng chưa mở). */
  | 'unreachable'
  /** Có mở được nhưng không trả lời trong thời hạn. */
  | 'timeout'
  /** Trang HTTPS không nhúng được iframe `http://`. */
  | 'mixedContent'
  /** `VITE_IDE_SOURCE=off` — chưa từng thử nối, đây không phải lỗi. */
  | 'off'

export interface IdeState {
  phase: IdePhase
  reason: IdeOfflineReason | null
  attempt: number
  exhausted: boolean
  /** Tăng mỗi lần cần thăm dò lại; hook dùng làm dependency của effect thăm dò. */
  seq: number
}

export type IdeEvent =
  | { type: 'probeStarted' }
  | { type: 'reachable' }
  | { type: 'failed'; reason: IdeOfflineReason }
  /** Người dùng bấm "Thử kết nối lại" hoặc "Nạp lại IDE" — cùng một việc: thăm dò rồi mount lại iframe. */
  | { type: 'manualRetry' }

export const IDE_PROBE_TIMEOUT_MS = 4000
export const IDE_RETRY_DELAYS_MS = [3000, 8000, 20000]
/** 1 lần đầu + 3 lần tự thử lại. */
export const IDE_MAX_ATTEMPTS = 4

export const initialIdeState: IdeState = {
  phase: 'probing',
  reason: null,
  attempt: 1,
  exhausted: false,
  seq: 0,
}

/** Trạng thái khi nguồn là `off`: không thăm dò, không thử lại. */
export const offIdeState: IdeState = {
  phase: 'offline',
  reason: 'off',
  attempt: 1,
  exhausted: true,
  seq: 0,
}

export function reduceIde(state: IdeState, event: IdeEvent): IdeState {
  switch (event.type) {
    case 'probeStarted':
      return {
        ...state,
        phase: 'probing',
        reason: null,
        attempt: state.phase === 'offline' ? state.attempt + 1 : state.attempt,
        exhausted: false,
        seq: state.seq + 1,
      }

    case 'reachable':
      return { ...state, phase: 'live', reason: null, attempt: 1, exhausted: false }

    case 'failed': {
      // Lỗi cấu hình chứ không phải box tạm ngưng ⇒ thử lại vô nghĩa.
      if (event.reason === 'mixedContent') {
        return { ...state, phase: 'offline', reason: event.reason, exhausted: true }
      }
      if (state.phase === 'offline') return state
      return {
        ...state,
        phase: 'offline',
        reason: event.reason,
        exhausted: state.attempt >= IDE_MAX_ATTEMPTS,
      }
    }

    case 'manualRetry':
      // Nguồn là `off` thì không có gì để thăm dò: hook không bao giờ gọi fetch,
      // nên chuyển sang 'probing' sẽ treo panel ở màn "đang mở editor" mãi mãi.
      if (state.reason === 'off') return state
      return {
        ...state,
        phase: 'probing',
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
export function ideRetryDelayMs(state: IdeState): number | null {
  if (state.phase !== 'offline' || state.exhausted) return null
  return IDE_RETRY_DELAYS_MS[state.attempt - 1] ?? null
}
