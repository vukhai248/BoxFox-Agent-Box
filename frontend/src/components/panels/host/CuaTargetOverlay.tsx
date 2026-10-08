/**
 * Khung ảnh + lớp phủ của panel "Màn hình máy": viền xanh quanh vùng agent đang
 * điều khiển, lớp bắt cú bấm khi "Chọn phần tử" lên nòng, và khung sáng phần tử
 * vừa thanh tra.
 *
 * Nguyên tắc bắt buộc (mục 6.1):
 *   - Viền là TRANG TRÍ: `aria-hidden="true"`, `pointer-events-none`. Mọi điều
 *     nó nói cũng phải có bằng chữ ở nơi khác (chip nhận dạng + chú giải) — trình
 *     đọc màn hình không bao giờ phải "đọc" một cái viền.
 *   - Chỉ MỘT phần tử bắt cú bấm (`ms-inspect-catcher`), và chỉ khi lên nòng.
 *   - Toạ độ: `activeWindow.rect` là màn hình VẬT LÝ, ảnh là một lát cắt tại
 *     `captureOrigin` — quy đổi nằm ở `lib/desktop/geometry.ts` (có test riêng).
 *     Không nhân `devicePixelRatio` ở đây.
 *   - Bấm vào dải letterbox quanh ảnh thì BỎ QUA (không tra vào pixel biên).
 */
import { useEffect, useLayoutEffect, useMemo, useRef, useState, type PointerEvent, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import { useT } from '../../../i18n/context'
import { cssBoxStyle, framebufferBoxToImageCss, imagePointToFramebuffer } from '../../../lib/desktop/geometry'
import type { CanvasRect, CssBox, FramebufferBox, FramebufferPoint } from '../../../lib/vnc/inspect'
import type { CuaActiveWindow, CuaTarget, HostSnapshot } from '../../../types/desktopTarget'

export interface CuaTargetOverlayProps {
  snapshot: HostSnapshot
  target: CuaTarget
  activeWindow: CuaActiveWindow | null
  /** `true` ⇒ lượt bấm kế tiếp thuộc về panel, không tới máy. */
  armed: boolean
  /** `true` ⇒ agent đang giữ quyền (đổi nhãn trên viền). */
  working: boolean
  /** Hộp framebuffer của phần tử vừa thanh tra (`dom.screenBox` / `uia.bounds.screenBox`). */
  highlightBox: FramebufferBox | null
  highlightLabel: string | null
  onPick: (point: FramebufferPoint) => void
  onEscape: () => void
  /** Ngăn kéo kết quả (component dùng chung) — nằm trong khung để định vị theo ảnh. */
  children?: ReactNode
}

function toCanvasRect(rect: DOMRect): CanvasRect {
  return { left: rect.left, top: rect.top, right: rect.right, bottom: rect.bottom, width: rect.width, height: rect.height }
}

/** Lớp phủ viền xanh — tách khỏi khối chọn để không lẫn hai loại "xanh". */
const TARGET_BORDER_CLASS =
  'pointer-events-none absolute rounded-md border-2 border-dashed border-cua shadow-[0_0_0_3px_rgba(56,189,248,0.25)] motion-safe:animate-[cua-target-glow_1.8s_ease-in-out_infinite] motion-reduce:animate-none'

export function CuaTargetOverlay({
  snapshot,
  target,
  activeWindow,
  armed,
  working,
  highlightBox,
  highlightLabel,
  onPick,
  onEscape,
  children,
}: CuaTargetOverlayProps) {
  const t = useT()
  const frameRef = useRef<HTMLDivElement | null>(null)
  const imgRef = useRef<HTMLImageElement | null>(null)
  // Đo lại rect sau khi ảnh có cỡ thật và mỗi khi khung đổi cỡ. `frameTick` chỉ
  // là "cò" để `useMemo` bên dưới tính lại — giá trị của nó không được đọc.
  const [frameTick, setFrameTick] = useState(0)
  const [reducedMotion, setReducedMotion] = useState(false)

  useEffect(() => {
    const query = typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia('(prefers-reduced-motion: reduce)')
      : null
    if (!query) return
    setReducedMotion(query.matches)
    const onChange = () => setReducedMotion(query.matches)
    query.addEventListener?.('change', onChange)
    return () => query.removeEventListener?.('change', onChange)
  }, [])

  useLayoutEffect(() => {
    const frame = frameRef.current
    if (!frame || typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(() => setFrameTick((v) => v + 1))
    observer.observe(frame)
    return () => observer.disconnect()
  }, [])

  useEffect(() => {
    const onResize = () => setFrameTick((v) => v + 1)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // Esc thoát chế độ chọn — cùng khuôn `ElementInspectorOverlay` của box.
  useEffect(() => {
    if (!armed) return
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onEscape()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [armed, onEscape])

  // Đo SAU khi DOM đã commit: lúc render đầu tiên `imgRef.current` còn là ảnh cũ
  // (hoặc null), nên đo trong `useMemo` sẽ ra "chưa đo được" và viền biến mất cho
  // tới khi ảnh bắn `onLoad`. `frameTick` là cò đo lại (ảnh load, khung đổi cỡ).
  const [measured, setMeasured] = useState<{ imageRect: CanvasRect; overlayRect: CanvasRect } | null>(null)

  useLayoutEffect(() => {
    const img = imgRef.current
    const frame = frameRef.current
    if (!img || !frame) {
      setMeasured(null)
      return
    }
    setMeasured({
      imageRect: toCanvasRect(img.getBoundingClientRect()),
      overlayRect: toCanvasRect(frame.getBoundingClientRect()),
    })
  }, [frameTick, snapshot.image, snapshot.width, snapshot.height])

  /** Viền mục tiêu: cửa sổ ⇒ ôm trọn ảnh; cả máy ⇒ đúng `activeWindow`, không đoán. */
  const targetStyle = useMemo<CssBox | { inset: 0 } | null>(() => {
    if (target.kind === 'window') return { inset: 0 }
    const rect = activeWindow?.rect
    if (!rect || !measured) return null
    const box = framebufferBoxToImageCss({
      box: rect,
      imageRect: measured.imageRect,
      overlayRect: measured.overlayRect,
      imageWidth: snapshot.width,
      imageHeight: snapshot.height,
      captureOrigin: snapshot.captureOrigin,
    })
    return box ? cssBoxStyle(box) : null
  }, [target, activeWindow, measured, snapshot])

  /** Viền phủ kín vùng chụp ⇒ chú giải nói "toàn bộ vùng đang chụp" mới đúng. */
  const coversWhole = useMemo(() => {
    if (!measured || !targetStyle || 'inset' in targetStyle) return false
    const { left = 0, top = 0, width = 0, height = 0 } = targetStyle
    return left <= 0.5 && top <= 0.5 && width >= measured.overlayRect.width - 0.5 && height >= measured.overlayRect.height - 0.5
  }, [targetStyle, measured])

  const highlightStyle = useMemo<CssBox | null>(() => {
    if (!highlightBox || !measured) return null
    const box = framebufferBoxToImageCss({
      box: highlightBox,
      imageRect: measured.imageRect,
      overlayRect: measured.overlayRect,
      imageWidth: snapshot.width,
      imageHeight: snapshot.height,
      captureOrigin: snapshot.captureOrigin,
    })
    return box ? cssBoxStyle(box) : null
  }, [highlightBox, measured, snapshot])

  function handlePointerDown(event: PointerEvent<HTMLDivElement>) {
    const img = imgRef.current
    if (!img) return
    const point = imagePointToFramebuffer({
      imageRect: toCanvasRect(img.getBoundingClientRect()),
      imageWidth: snapshot.width,
      imageHeight: snapshot.height,
      captureOrigin: snapshot.captureOrigin,
      clientX: event.clientX,
      clientY: event.clientY,
    })
    // `null` = bấm vào dải letterbox quanh ảnh ⇒ bỏ qua cú bấm hẳn.
    if (!point) return
    onPick(point)
  }

  const legend =
    target.kind === 'window'
      ? t('machineScreen.overlayLegendWindow', { title: target.title || t('machineScreen.pickWindow') })
      : targetStyle
        ? coversWhole
          ? t('machineScreen.overlayLegendWhole')
          : t('machineScreen.overlayLegendMachine')
        : t('machineScreen.overlayLegendMachineUnknown')

  return (
    <div className="flex min-h-0 flex-col gap-1">
      <div ref={frameRef} className="relative inline-block max-w-full" data-testid="ms-snapshot-frame">
        <img
          ref={imgRef}
          src={`data:${snapshot.mime || 'image/png'};base64,${snapshot.image}`}
          alt={t('machineScreen.snapshotAlt')}
          onLoad={() => setFrameTick((v) => v + 1)}
          className="block h-auto max-w-full rounded-md border border-line"
        />

        {targetStyle && (
          <div aria-hidden="true" data-testid="ms-target-overlay" className={TARGET_BORDER_CLASS} style={targetStyle} />
        )}

        {/* Nhãn trên viền — chữ, không chỉ màu (mục 6: viền không bao giờ là nơi
            duy nhất chứa thông tin). */}
        {targetStyle && working && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute bottom-2 left-2 inline-flex items-center gap-1.5 rounded-full bg-panel/90 px-2 py-0.5 text-[10px] font-semibold text-cua ring-1 ring-cua/40"
          >
            <span className="size-1.5 animate-pulse rounded-full bg-cua" />
            {t('machineScreen.targetWorkingHere')}
          </span>
        )}

        {armed && (
          <div
            role="button"
            tabIndex={0}
            aria-label={t('machineScreen.selectElementHint')}
            data-testid="ms-inspect-catcher"
            onPointerDown={handlePointerDown}
            onKeyDown={(event) => {
              if (event.key === 'Escape') onEscape()
            }}
            className="absolute inset-0 cursor-crosshair bg-brand/[0.04] ring-1 ring-inset ring-brand/35"
          />
        )}

        {highlightStyle && (
          <div
            aria-hidden="true"
            data-testid="ms-element-highlight"
            className="pointer-events-none absolute outline outline-1 outline-brand bg-brand/10"
            style={highlightStyle}
          />
        )}

        {highlightStyle && highlightLabel && (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute rounded bg-panel/90 px-1.5 py-0.5 text-[10px] font-semibold text-fg ring-1 ring-line"
            style={{ left: highlightStyle.left, top: (highlightStyle.top ?? 0) - 18 }}
          >
            {highlightLabel}
          </span>
        )}

        {children}
      </div>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted">
        <span className="inline-flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block size-3 rounded-sm border border-dashed border-cua bg-cua/15" />
          {legend}
        </span>
        {reducedMotion && <span>{t('machineScreen.overlayLegendReducedMotion')}</span>}
      </div>
    </div>
  )
}

/** Chú thích dùng lại ở khối ảnh trống (chưa có ảnh chụp) — cùng chữ, không viền. */
export function CuaSnapshotNote({ text }: { text: string }) {
  return (
    <p className="flex items-center gap-1.5 text-[11px] text-muted">
      <AlertTriangle className="size-3.5 shrink-0" aria-hidden="true" />
      {text}
    </p>
  )
}
