/**
 * Cầu nối React cho kênh noVNC (plan §4, D-1).
 *
 * Chỗ duy nhất chạm vào DOM và `import.meta.env`. Vòng đời một lượt kết nối
 * nằm ở `src/lib/vnc/attempt.ts`, máy trạng thái thuần ở `src/lib/vnc/state.ts`;
 * panel (`SandboxScreenPanel.tsx`) chỉ đọc kết quả của hook này.
 */
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import {
  describeVncContextProblem,
  resolveScreenSource,
  resolveVncUrl,
  type ScreenSource,
} from '../lib/vnc/config'
import { startVncAttempt, type RfbLike, type VncAttempt } from '../lib/vnc/attempt'
import { applyScreenFit } from '../lib/vnc/fit'
import {
  disabledVncState,
  initialVncState,
  reduceVnc,
  retryDelayMs,
  VNC_CONNECT_TIMEOUT_MS,
  type VncOfflineReason,
  type VncPhase,
} from '../lib/vnc/state'

export interface UseVncScreenResult {
  containerRef: React.RefObject<HTMLDivElement | null>
  /** Nguồn khung hình đang chọn. `mock` ⇒ gói noVNC không được nạp. */
  source: ScreenSource
  phase: VncPhase
  reason: VncOfflineReason | null
  exhausted: boolean
  url: string
  /** Mốc thời gian (ms) của lần tự thử lại kế tiếp — dùng cho đếm ngược. `null` nếu không có. */
  retryAtMs: number | null
  frameSize: { width: number; height: number } | null
  /** `true` khi bàn phím/chuột đang bị canvas noVNC giữ. */
  controlling: boolean
  retry: () => void
  skip: () => void
  focusScreen: () => void
  /** Nhả bàn phím khỏi canvas noVNC (canvas ăn cả Tab nên phải có đường thoát). */
  releaseKeyboard: () => void
}

export function useVncScreen(override?: ScreenSource): UseVncScreenResult {
  // `override` cho phép panel tự đổi nguồn tại chỗ (nút Live box/Demo) mà vẫn
  // giữ nguyên mặc định từ env khi không có lựa chọn của người dùng.
  const source = useMemo(
    () => override ?? resolveScreenSource(import.meta.env),
    [override],
  )
  const enabled = source === 'novnc'
  const [state, dispatch] = useReducer(reduceVnc, enabled ? initialVncState : disabledVncState)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const attemptRef = useRef<VncAttempt | null>(null)
  const [frameSize, setFrameSize] = useState<{ width: number; height: number } | null>(null)
  const [retryAtMs, setRetryAtMs] = useState<number | null>(null)
  const [controlling, setControlling] = useState(false)

  const url = useMemo(() => resolveVncUrl(import.meta.env), [])

  const abortAttempt = useCallback(() => {
    attemptRef.current?.abort()
    attemptRef.current = null
    setFrameSize(null)
    setControlling(false)
  }, [])

  // Effect A — mở/đóng một lượt kết nối. `state.seq` chỉ tăng ở
  // `connectStarted` / `manualRetry`, cả hai đều đặt phase='connecting'.
  useEffect(() => {
    if (!enabled) return

    if (typeof WebSocket === 'undefined') {
      dispatch({ type: 'failed', reason: 'unsupported' })
      return
    }

    // Chặn TRƯỚC khi nạp gói: `core/rfb.js` của noVNC chỉ log cảnh báo rồi chạy
    // tiếp trong ngữ cảnh không an toàn, và vỡ ở chỗ khó đọc hơn nhiều.
    const problem = describeVncContextProblem({
      pageProtocol: window.location.protocol,
      isSecureContext: window.isSecureContext,
      url,
    })
    if (problem) {
      dispatch({ type: 'failed', reason: problem })
      return
    }

    const attempt = startVncAttempt({
      url,
      timeoutMs: VNC_CONNECT_TIMEOUT_MS,
      getTarget: () => containerRef.current,
      loadRfb: async () => {
        const { default: RFB } = await import('@novnc/novnc')
        // Chỉ dựng — `new RFB(...)` mở socket ngay, nên phải trả về liền để
        // controller sở hữu nó trước khi cấu hình.
        return (target, targetUrl) => new RFB(target, targetUrl, { shared: true })
      },
      configureRfb: applyScreenFit,
      onLive: () => {
        const canvas = containerRef.current?.querySelector('canvas')
        if (canvas) setFrameSize({ width: canvas.width, height: canvas.height })
      },
      onEvent: dispatch,
    })
    attemptRef.current = attempt

    return () => {
      attempt.abort()
      if (attemptRef.current === attempt) attemptRef.current = null
      setFrameSize(null)
      setControlling(false)
    }
  }, [enabled, url, state.seq])

  // Effect B — hẹn thử lại tự động khi đang offline và còn lượt.
  useEffect(() => {
    const delay = retryDelayMs(state)
    if (delay === null) {
      setRetryAtMs(null)
      return
    }
    setRetryAtMs(Date.now() + delay)
    const id = setTimeout(() => dispatch({ type: 'connectStarted' }), delay)
    return () => clearTimeout(id)
  }, [state.phase, state.attempt, state.exhausted])

  // Effect C — theo dõi quyền điều khiển trên chính canvas của noVNC.
  // `focusin`/`focusout` nổi bọt lên container; `onBlur` của wrapper thì không
  // dùng được vì noVNC chuyển focus từ wrapper xuống canvas con của nó.
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const onFocusIn = () => setControlling(true)
    const onFocusOut = () => setControlling(false)
    container.addEventListener('focusin', onFocusIn)
    container.addEventListener('focusout', onFocusOut)
    return () => {
      container.removeEventListener('focusin', onFocusIn)
      container.removeEventListener('focusout', onFocusOut)
    }
  }, [])

  // Effect D — theo dõi kích thước FRAMEBUFFER THẬT để cập nhật nhãn.
  //
  // Việc fit KHÔNG nằm ở đây: `resizeSession` (xem `lib/vnc/fit.ts`) lo phần đó,
  // và noVNC tự có `ResizeObserver` riêng trên canvas của nó nên không cần ai
  // đánh thức. Bản cũ ở đây bắn `window.dispatchEvent(new Event('resize'))` —
  // noVNC 1.7.0 không đăng ký listener `resize` nào trên `window`, nên dòng đó
  // vô tác dụng với noVNC mà lại làm mọi listener resize khác của app chạy oan.
  //
  // Quan sát CẢ container VÀ canvas con:
  //   - container: bắt lúc người dùng đang kéo Resizer.
  //   - canvas   : khi server đổi phân giải xong, noVNC gọi `display.resize()`
  //                làm đổi `canvas.width/height`. Không có event `desktopsize`
  //                nào để nghe, nên đây là cách duy nhất biết phân giải mới.
  // Đọc `canvas.width/height` (thuộc tính, = kích thước framebuffer), KHÔNG phải
  // kích thước CSS — đó mới là bằng chứng "phân giải đổi thật", không phải scale.
  useEffect(() => {
    if (!enabled) return
    if (state.phase !== 'live') return
    const el = containerRef.current
    if (!el) return
    if (typeof ResizeObserver === 'undefined') return
    let raf = 0
    const ro = new ResizeObserver(() => {
      cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => {
        const canvas = el.querySelector('canvas')
        if (!canvas) return
        const next = { width: canvas.width, height: canvas.height }
        // Chỉ set khi ĐỔI: RO bắn liên tục trong lúc kéo, mà framebuffer chỉ đổi
        // mỗi ~100ms (noVNC tự rate-limit) → tránh render lặp vô ích.
        setFrameSize((prev) =>
          prev && prev.width === next.width && prev.height === next.height ? prev : next,
        )
      })
    })
    ro.observe(el)
    const canvas = el.querySelector('canvas')
    if (canvas) ro.observe(canvas)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [enabled, state.phase])

  const retry = useCallback(() => {
    abortAttempt()
    dispatch({ type: 'manualRetry' })
  }, [abortAttempt])

  const skip = useCallback(() => {
    // `skip` không tăng `seq` nên cleanup của Effect A KHÔNG chạy — phải tự dập
    // lượt đang chờ, nếu không nó vẫn nối xong trong bóng tối.
    abortAttempt()
    dispatch({ type: 'skip' })
  }, [abortAttempt])

  const withRfb = (fn: (rfb: RfbLike) => void) => {
    const rfb = attemptRef.current?.getRfb()
    if (rfb) fn(rfb)
  }

  const focusScreen = useCallback(() => {
    withRfb((rfb) => rfb.focus({ preventScroll: true }))
  }, [])

  const releaseKeyboard = useCallback(() => {
    withRfb((rfb) => rfb.blur())
    setControlling(false)
  }, [])

  return {
    containerRef,
    source,
    phase: state.phase,
    reason: state.reason,
    exhausted: state.exhausted,
    url,
    retryAtMs,
    frameSize,
    controlling,
    retry,
    skip,
    focusScreen,
    releaseKeyboard,
  }
}
