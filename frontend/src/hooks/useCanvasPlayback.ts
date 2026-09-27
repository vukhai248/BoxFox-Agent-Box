/**
 * Hook phát lại nét vẽ của Design Lead: biến lô op agent vừa gửi thành hoạt hình "đang vẽ".
 *
 * Vì sao tách khỏi `useDesignCanvas`: hook kia giữ cảnh + lịch sử undo, còn việc phát lại chỉ là
 * LỚP NHÌN — nó đọc `lastOps[designId]` (lô op gần nhất do store giữ), dựng kế hoạch qua
 * `planPlayback` rồi chạy `requestAnimationFrame`. Cảnh THẬT (`scene`) không bao giờ bị thay bằng
 * cảnh trung gian: hết hoạt hình, `displayScene` trở về đúng `scene`.
 *
 * Năm luật của lớp này:
 * 1. Chỉ phát lại op của AGENT (`actor:'user'` là tay chủ nhà vẽ — không diễn lại).
 * 2. Mỗi lô op chỉ phát MỘT lần (khoá `seq`), kể cả khi React render lại nhiều lần — nhưng lô op chỉ
 *    được coi là "đã phát" khi khung hình ĐẦU TIÊN đã vẽ ra, không phải lúc dựng kế hoạch: StrictMode
 *    (dev) chạy mount → cleanup → mount lại, lượt mount đầu bị huỷ TRƯỚC khung hình nào thì chủ nhà
 *    chưa thấy gì, nên lô op phải còn nguyên cho lượt sau diễn. Vì thế `playedSeqRef` và sổ bền
 *    `playedOpsSeq` (store) chỉ ghi ở khung hình đầu (xem `tick`).
 * 3. Không dựng được kế hoạch trung thực (`planPlayback` trả rỗng) thì hiện thẳng cảnh thật.
 * 4. Chủ nhà chạm canvas, hoặc bấm "Bỏ qua hiệu ứng" ⇒ nhảy NGAY về cảnh thật.
 * 5. Cảnh tới mà KHÔNG kèm op (payload chi tiết của run: tải lại trang, cảnh gieo lúc duyệt touch
 *    list) thì lấy chênh lệch `from → to` làm op (`diffSceneOps`) — vẫn là agent vẽ, không phải cảnh
 *    hiện ra đột ngột. Cảnh nguồn cho phép toán ấy do store gửi kèm lô op (`CanvasOpBatch.from`), nên
 *    luật này đúng CẢ khi canvas chỉ được mở SAU khi cảnh đã nằm sẵn trong store.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { CanvasAction, CanvasScene, CursorState } from '../lib/canvas'
import { diffSceneOps, drawnStepCount, drawStepCount, frameAt, planPlayback, sameScene, type DrawingPlan } from '../lib/canvas'
import { useDesignStore } from '../store/designStore'

/** Cảnh trung gian đang hiển thị trong lúc vẽ. */
interface PlaybackVisual {
  scene: CanvasScene
  cursor: CursorState
  activeIds: readonly string[]
  connectorProgress: Record<string, number>
  drawn: number
  total: number
}

export interface CanvasPlayback {
  /** Cảnh nên VẼ (đang vẽ dở hoặc cảnh thật — bằng nhau khi không phát). */
  displayScene: CanvasScene
  /** Con trỏ agent (world-space) khi đang vẽ; `null` khi rảnh. */
  cursor: CursorState | null
  activeIds: readonly string[]
  connectorProgress: Record<string, number>
  playing: boolean
  /** Số bước vẽ đã xong / tổng số bước vẽ của lô đang phát. */
  drawn: number
  total: number
  /** Bỏ hoạt hình, hiện cảnh thật ngay (chủ nhà chạm canvas hoặc bấm nút). */
  skip: () => void
}

const NO_IDS: readonly string[] = []
const NO_PROGRESS: Record<string, number> = {}

/**
 * Người dùng có bật "giảm chuyển động" không. jsdom KHÔNG có `window.matchMedia` (xem
 * `App.workspace.test.tsx`) nên phải kiểm tra hàm trước khi gọi — thiếu bước này, mọi bài test dựng
 * `DesignCanvasPanel` sẽ nổ.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

/** Một lần dò cho cả cặp: môi trường có `rAF` thì phải có `cAF` (trình duyệt và jsdom đều vậy). */
function hasFrames(): boolean {
  return typeof requestAnimationFrame === 'function' && typeof cancelAnimationFrame === 'function'
}

/** Đặt lịch khung hình kế tiếp — `rAF` khi có, `setTimeout` khi môi trường test không có. */
function scheduleFrame(callback: () => void): number {
  if (hasFrames()) return requestAnimationFrame(callback)
  return window.setTimeout(callback, 16)
}

function cancelFrame(handle: number): void {
  if (hasFrames()) cancelAnimationFrame(handle)
  else window.clearTimeout(handle)
}

export function useCanvasPlayback(input: {
  scene: CanvasScene
  designId: string
  reducedMotion?: boolean
}): CanvasPlayback {
  const { scene, designId } = input
  const batch = useDesignStore((state) => (designId ? state.lastOps[designId] : undefined))
  const actor = useDesignStore((state) => (designId ? state.sceneActor[designId] : undefined))
  const [visual, setVisual] = useState<PlaybackVisual | null>(null)
  // Cảnh THẬT đã biết gần nhất — mốc xuất phát cho kế hoạch của lô op kế tiếp.
  const settledRef = useRef<CanvasScene>(scene)
  // Lô op đã phát XONG trong các lượt mount trước (sổ nhanh của riêng hook; sổ bền nằm ở store).
  const playedSeqRef = useRef(0)
  const planRef = useRef<DrawingPlan | null>(null)
  const rafRef = useRef(0)
  const reducedRef = useRef(false)
  reducedRef.current = input.reducedMotion ?? prefersReducedMotion()

  /** Dừng hoạt hình đang chạy (nếu có) và trả về cảnh thật. */
  const stop = useCallback(() => {
    if (rafRef.current) cancelFrame(rafRef.current)
    rafRef.current = 0
    planRef.current = null
    setVisual(null)
  }, [])

  useEffect(() => stop, [stop])

  useEffect(() => {
    const from = settledRef.current
    // Lô op CHƯA ai phát (kể cả khi nó tới từ payload, xem `CanvasOpBatch.from`). Phải xét TRƯỚC hàng
    // rào "cảnh không đổi" bên dưới: canvas mở SAU khi cảnh đã nằm sẵn trong store (chủ nhà ở tab
    // Brief lúc agent vẽ) thì `scene === from` ngay từ khung hình đầu, nhưng lô op ấy vẫn chưa được
    // diễn lần nào — nuốt nó nghĩa là canvas hiện ra đã vẽ xong, không có con trỏ, không có nút Bỏ qua.
    const played = Math.max(playedSeqRef.current, useDesignStore.getState().playedOpsSeq[designId] ?? 0)
    const fresh = batch && batch.ops.length > 0 && batch.seq > played ? batch : undefined
    // Cảnh XUẤT PHÁT của kế hoạch: cảnh nguồn đi kèm lô op (store ghi lúc reduce, hoặc cảnh trước khi
    // nhận cảnh từ payload); không có thì lấy mốc cảnh thật gần nhất.
    const origin = fresh?.from ?? from
    // Vòng poll có thể gửi lại ĐÚNG cảnh ấy dưới object mới: bỏ qua theo GIÁ TRỊ (`sameScene`), nếu
    // không thì mỗi vòng lại cập nhật mốc và cắt ngang hoạt hình đang chạy.
    if (!fresh && (scene === from || sameScene(scene, from))) return
    settledRef.current = scene
    // Tay chủ nhà vẽ thì không diễn lại — cảnh của họ hiện thẳng.
    if (actor === 'user') {
      if (planRef.current) stop()
      return
    }
    let ops: CanvasAction[]
    if (fresh) {
      ops = fresh.ops
    } else if (batch && batch.ops.length > 0) {
      // Lô cũ đã phát xong (render lại, sự kiện phát lại): không diễn lại.
      return
    } else {
      // Không có lô op: cảnh tới từ payload run ⇒ tự dựng op từ chênh lệch cảnh.
      ops = diffSceneOps(from, scene)
    }
    const plan = planPlayback({ ops, from: origin, to: scene, options: { reducedMotion: reducedRef.current } })
    if (plan.steps.length === 0) {
      if (planRef.current) stop()
      return
    }
    // Lô mới tới giữa lúc đang vẽ: bỏ hoạt hình cũ rồi vẽ tiếp từ cảnh thật vừa nhận.
    if (planRef.current) stop()
    const total = drawStepCount(plan)
    const startedAt = Date.now()
    const first = plan.steps[0].at
    planRef.current = plan
    setVisual({ scene: plan.from, cursor: { visible: true, x: first.x, y: first.y, pressed: false }, activeIds: NO_IDS, connectorProgress: NO_PROGRESS, drawn: 0, total })
    let booked = false
    const tick = () => {
      const elapsed = Date.now() - startedAt
      if (!booked && fresh) {
        // Khung hình ĐẦU TIÊN đã thực sự chạy ⇒ hoạt hình này là thật với chủ nhà: ghi sổ để nhịp
        // sau (và lần lắp lại canvas) không diễn lại nữa. Ghi ở ĐÂY chứ không phải lúc dựng kế hoạch
        // vì StrictMode (dev) chạy mount → cleanup → mount lại: lượt mount đầu bị huỷ trước khung
        // hình nào thì chủ nhà chưa thấy gì, lô op phải còn nguyên cho lượt sau diễn.
        booked = true
        playedSeqRef.current = fresh.seq
        useDesignStore.getState().markOpsPlayed(designId, fresh.seq)
      }
      if (elapsed >= plan.totalMs) {
        rafRef.current = 0
        planRef.current = null
        setVisual(null)
        return
      }
      const frame = frameAt(plan, elapsed)
      setVisual({
        scene: frame.scene,
        cursor: frame.cursor,
        activeIds: frame.activeIds,
        connectorProgress: frame.connectorProgress,
        drawn: drawnStepCount(plan, elapsed),
        total,
      })
      rafRef.current = scheduleFrame(tick)
    }
    rafRef.current = scheduleFrame(tick)
  }, [scene, batch, actor, stop])

  const skip = useCallback(() => {
    if (!planRef.current) return
    stop()
  }, [stop])

  return {
    displayScene: visual?.scene ?? scene,
    cursor: visual?.cursor ?? null,
    activeIds: visual?.activeIds ?? NO_IDS,
    connectorProgress: visual?.connectorProgress ?? NO_PROGRESS,
    playing: visual !== null,
    drawn: visual?.drawn ?? 0,
    total: visual?.total ?? 0,
    skip,
  }
}
