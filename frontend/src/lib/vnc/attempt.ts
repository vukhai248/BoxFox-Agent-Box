/**
 * Vòng đời MỘT lượt kết nối noVNC.
 *
 * Vì sao tách ra khỏi hook: bug nguy hiểm nhất ở đây không phải bug hiển thị
 * mà là rò socket. Nếu để logic này nằm trong `useEffect`, các đường "bỏ chờ",
 * "quá hạn", "thử lại tay" đều không chạy cleanup của effect, và một
 * `import('@novnc/novnc')` giải quyết muộn vẫn kịp tạo `new RFB(...)` sau khi
 * lượt đó đã bị huỷ — một kết nối vô hình, không ai đóng, không hiện trên UI.
 *
 * Nên: mọi thứ thuộc một lượt (instance RFB, timer quá hạn, các listener) đều
 * do đúng lượt đó sở hữu, và `abort()` là cửa duy nhất để dập nó. Không dùng
 * ref dùng chung, nên không có cách nào dập nhầm instance của lượt khác.
 *
 * `RFB` và timer đều được tiêm vào ⇒ test được bằng vitest với đồng hồ tay và
 * một `RFB` giả, không cần trình duyệt, không cần canvas, không cần socket.
 */
import type { VncEvent } from './state'

export interface RfbEventMap {
  connect: { detail?: unknown }
  disconnect: { detail: { clean: boolean } }
  securityfailure: { detail: { status: number; reason?: string } }
  credentialsrequired: { detail: { types: string[] } }
}

/** Phần bề mặt của `RFB` mà code này thực sự dùng (xem `src/types/novnc.d.ts`). */
export interface RfbLike {
  viewOnly: boolean
  scaleViewport: boolean
  clipViewport: boolean
  resizeSession: boolean
  showDotCursor: boolean
  background: string
  disconnect(): void
  focus(options?: FocusOptions): void
  blur(): void
  addEventListener<K extends keyof RfbEventMap>(
    type: K,
    listener: (event: RfbEventMap[K]) => void,
  ): void
  removeEventListener<K extends keyof RfbEventMap>(
    type: K,
    listener: (event: RfbEventMap[K]) => void,
  ): void
}

/**
 * CHỈ dựng instance, không cấu hình gì.
 *
 * `new RFB(...)` mở WebSocket ngay trong constructor, nên phải trả instance về
 * cho controller sở hữu TRƯỚC khi ai đó chạm vào các setter. Nếu gộp cả phần
 * cấu hình vào đây và một setter nổ, controller chưa kịp giữ instance nào để mà
 * đóng — socket đó thành mồ côi.
 */
export type RfbFactory = (target: Element, url: string) => RfbLike

/** Cấu hình instance sau khi controller đã sở hữu nó. Được phép nổ. */
export type RfbConfigurer = (rfb: RfbLike) => void

export interface VncTimer {
  set(fn: () => void, ms: number): number
  clear(id: number): void
}

export const realTimer: VncTimer = {
  set: (fn, ms) => setTimeout(fn, ms) as unknown as number,
  clear: (id) => clearTimeout(id),
}

export interface VncAttemptDeps {
  /** Nạp `RFB` (thường là `import('@novnc/novnc')`) rồi trả về factory. */
  loadRfb: () => Promise<RfbFactory>
  /** Đặt các thuộc tính của RFB (viewOnly, scaleViewport, …). Chạy sau khi đã sở hữu instance. */
  configureRfb?: RfbConfigurer
  /** Lấy phần tử DOM để noVNC vẽ vào. `null` ⇒ lượt này thất bại với `error`. */
  getTarget: () => Element | null
  url: string
  timeoutMs: number
  timer?: VncTimer
  /** Đẩy sự kiện vào reducer. KHÔNG bao giờ được gọi sau khi `abort()`. */
  onEvent: (event: VncEvent) => void
  /** Gọi đúng một lần khi kênh đã dựng xong, để hook cầm instance mà focus/blur. */
  onLive?: (rfb: RfbLike) => void
}

export interface VncAttempt {
  /** Dập lượt này: gỡ listener, xoá timer, đóng RFB. Không phát sự kiện nào. */
  abort(): void
  /** Instance RFB nếu lượt này đã dựng xong, ngược lại `null`. */
  getRfb(): RfbLike | null
}

type AttemptStatus = 'pending' | 'live' | 'done'

/**
 * Mở một lượt kết nối. Luôn trả về ngay (việc nạp gói là bất đồng bộ).
 *
 * Đúng một sự kiện kết thúc được phát cho mỗi lượt: `timeout`, `closed`,
 * `failed`, hoặc không có gì cả nếu bị `abort()`. `connected` là sự kiện giữa
 * đường nên sau nó vẫn có thể có `closed`.
 */
export function startVncAttempt(deps: VncAttemptDeps): VncAttempt {
  const timer = deps.timer ?? realTimer
  let status: AttemptStatus = 'pending'
  let rfb: RfbLike | null = null
  let timeoutId: number | null = null
  /** Các cặp [type, listener] đã gắn — gỡ trước khi disconnect. */
  const listeners: Array<() => void> = []

  const clearTimer = () => {
    if (timeoutId !== null) {
      timer.clear(timeoutId)
      timeoutId = null
    }
  }

  /**
   * Gỡ listener TRƯỚC khi đóng, để `disconnect()` của mình không tự vọng lại,
   * và bỏ tham chiếu instance ngay để canvas/buffer của noVNC được thu hồi
   * (lượt kết thúc bằng lỗi vĩnh viễn không làm `seq` tăng, nên hook còn giữ
   * attempt này khá lâu).
   *
   * `closeTransport = false` khi chính phía kia đã đóng: noVNC 1.7.0 đã chuyển
   * sang trạng thái `disconnected` trước khi bắn event, gọi `disconnect()`
   * lần nữa chỉ để nó log "Bad transition to disconnecting state".
   */
  const teardown = (closeTransport: boolean) => {
    clearTimer()
    while (listeners.length > 0) listeners.pop()?.()
    const instance = rfb
    rfb = null
    if (instance && closeTransport) {
      try {
        instance.disconnect()
      } catch {
        // đã đóng rồi — không có gì phải làm thêm
      }
    }
  }

  /** Kết thúc lượt này và phát đúng một sự kiện. */
  const settle = (event: VncEvent, closeTransport = true) => {
    if (status === 'done') return
    status = 'done'
    teardown(closeTransport)
    deps.onEvent(event)
  }

  timeoutId = timer.set(() => {
    timeoutId = null
    settle({ type: 'timeout' })
  }, deps.timeoutMs)

  const on = <K extends keyof RfbEventMap>(
    instance: RfbLike,
    type: K,
    listener: (event: RfbEventMap[K]) => void,
  ) => {
    instance.addEventListener(type, listener)
    listeners.push(() => instance.removeEventListener(type, listener))
  }

  void deps
    .loadRfb()
    .then((createRfb) => {
      // Lượt đã kết thúc (bỏ chờ / quá hạn / unmount) trong lúc chờ nạp gói:
      // tuyệt đối không tạo RFB, nếu không sẽ có một socket không ai sở hữu.
      if (status !== 'pending') return

      const target = deps.getTarget()
      if (!target) {
        settle({ type: 'failed', reason: 'error' })
        return
      }

      let instance: RfbLike
      try {
        instance = createRfb(target, deps.url)
      } catch {
        settle({ type: 'failed', reason: 'error' })
        return
      }
      // Sở hữu instance NGAY, trước mọi thứ có thể nổ: socket đã mở từ trong
      // constructor rồi.
      rfb = instance
      try {
        deps.configureRfb?.(instance)
      } catch {
        settle({ type: 'failed', reason: 'error' })
        return
      }

      on(instance, 'connect', () => {
        if (status !== 'pending') return
        clearTimer()
        status = 'live'
        deps.onLive?.(instance)
        deps.onEvent({ type: 'connected' })
      })
      // Phía kia đã đóng: chỉ gỡ listener, không gọi `disconnect()` lần nữa.
      on(instance, 'disconnect', () => settle({ type: 'closed' }, false))
      on(instance, 'securityfailure', () => settle({ type: 'failed', reason: 'security' }))
      on(instance, 'credentialsrequired', () => settle({ type: 'failed', reason: 'credentials' }))
    })
    .catch(() => {
      // Gói lỗi (thiếu, sai đường dẫn, chunk 404): rơi về mô phỏng, không làm
      // vỡ panel demo.
      settle({ type: 'failed', reason: 'error' })
    })

  return {
    abort() {
      if (status === 'done') return
      status = 'done'
      teardown(true)
    },
    getRfb() {
      return status === 'live' ? rfb : null
    },
  }
}
