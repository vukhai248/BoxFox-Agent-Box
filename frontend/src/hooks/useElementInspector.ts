/**
 * Hook điều phối Element Selector / DOM Inspector (khung ④, F8).
 *
 * Sở hữu đúng ba việc, không hơn:
 *   1. Trạng thái "đã lên nòng" (`armed`) — người dùng đang chờ bấm điểm kế tiếp.
 *   2. Máy trạng thái của ngăn kéo kết quả (`drawer`): `loading` → `success` | `error`.
 *   3. `AbortController` của lượt gọi `InspectRepository.inspect()` đang chạy —
 *      huỷ lượt cũ khi có điểm bấm mới, và huỷ khi unmount.
 *
 * KHÔNG chạm DOM (đó là việc của `ElementInspectorOverlay`, F9) và KHÔNG biết
 * `composerStore` tồn tại (đó là việc của `SandboxScreenPanel`, F11 — "Thêm
 * vào hội thoại" là hành vi ghép nối giữa kết quả thanh tra và khung soạn
 * tin, không phải một phần của việc điều phối thanh tra).
 *
 * Quyết định Q5 (`v1-element-selector.md` §6): chọn xong TỰ TẮT chế độ chọn —
 * `handlePick()` tắt `armed` trước khi gọi `inspect()`, không chờ kết quả về.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { createInspectRepository, type InspectRepository } from '../lib/inspect'
import type { FramebufferPoint } from '../lib/vnc/inspect'
import type { InspectElementResult } from '../types/inspect'

export type InspectorDrawerState =
  | { status: 'loading'; point: FramebufferPoint }
  | { status: 'error'; point: FramebufferPoint; error: unknown }
  | { status: 'success'; point: FramebufferPoint; result: InspectElementResult }

export interface UseElementInspectorResult {
  /** `true` ⇒ cú bấm kế tiếp trên canvas bị lớp phủ chặn và đưa vào đây, không tới máy. */
  armed: boolean
  toggleArmed: () => void
  /** Tắt chế độ chọn mà KHÔNG đóng ngăn kéo — dùng khi Esc bấm lúc đang lên nòng. */
  disarm: () => void
  /** `null` ⇒ chưa từng thanh tra gì trong phiên này, ngăn kéo không hiện. */
  drawer: InspectorDrawerState | null
  /** Điểm framebuffer từ `ElementInspectorOverlay` (đã đổi toạ độ, đã lọc điểm ngoài canvas). */
  handlePick: (point: FramebufferPoint) => void
  /** Gọi lại đúng điểm vừa lỗi — dùng cho nút "Thử lại" trong ngăn kéo lỗi. */
  retry: () => void
  /** Đóng ngăn kéo VÀ huỷ lượt gọi đang chạy (nếu còn) — không tắt `armed` (đằng nào cũng đã tắt từ lúc pick). */
  closeDrawer: () => void
}

export function useElementInspector(repository?: InspectRepository): UseElementInspectorResult {
  const repo = useMemo(() => repository ?? createInspectRepository(), [repository])
  const [armed, setArmed] = useState(false)
  const [drawer, setDrawer] = useState<InspectorDrawerState | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  // Bản sao đồng bộ của `drawer` — để `retry()` đọc được điểm hiện tại mà
  // không phải gọi `setDrawer` với một hàm cập nhật có side-effect bên trong
  // (React có thể gọi hàm cập nhật đó nhiều hơn một lần).
  const drawerRef = useRef<InspectorDrawerState | null>(null)
  drawerRef.current = drawer

  // Huỷ lượt gọi đang chạy (nếu có) — dùng khi có điểm bấm mới, đóng ngăn kéo, hoặc unmount.
  const abortInFlight = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
  }, [])

  const runInspect = useCallback(
    (point: FramebufferPoint) => {
      abortInFlight()
      const controller = new AbortController()
      abortRef.current = controller
      setDrawer({ status: 'loading', point })

      repo
        .inspect(point, controller.signal)
        .then((result) => {
          if (controller.signal.aborted) return
          setDrawer({ status: 'success', point, result })
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return
          // `AbortError` của chính lượt này chỉ xảy ra nếu ai đó abort mà không
          // qua `abortInFlight` (không nên có) — vẫn bỏ qua để không hiện lỗi giả.
          if (error instanceof Error && error.name === 'AbortError') return
          setDrawer({ status: 'error', point, error })
        })
    },
    [repo, abortInFlight],
  )

  const handlePick = useCallback(
    (point: FramebufferPoint) => {
      setArmed(false) // Q5 — chọn xong tự tắt, không chờ kết quả về.
      runInspect(point)
    },
    [runInspect],
  )

  const toggleArmed = useCallback(() => setArmed((v) => !v), [])
  const disarm = useCallback(() => setArmed(false), [])

  const closeDrawer = useCallback(() => {
    abortInFlight()
    setDrawer(null)
  }, [abortInFlight])

  const retry = useCallback(() => {
    const current = drawerRef.current
    if (!current) return
    runInspect(current.point)
  }, [runInspect])

  // Huỷ lượt gọi còn dang dở khi hook bị gỡ (đổi tab, đóng panel…).
  useEffect(() => abortInFlight, [abortInFlight])

  return { armed, toggleArmed, disarm, drawer, handlePick, retry, closeDrawer }
}
