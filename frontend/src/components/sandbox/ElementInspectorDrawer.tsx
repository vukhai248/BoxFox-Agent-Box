/**
 * Ngăn kéo chi tiết của Element Selector (khung ④, F10) — hiện kết quả một
 * lần thanh tra: đang tải / lỗi / phần tử DOM / cửa sổ desktop.
 *
 * QUY TẮC BẮT BUỘC (mục 10.3, 12.6 kế hoạch):
 *   - Mọi chuỗi đến từ máy (`selector`, `text`, `html`, thuộc tính, `title`,
 *     `url`, `windowTitle`, `message`) PHẢI render qua `PlainText` — không có
 *     đường nào để một chỉ thị độc trong phần tử biến thành lệnh cho agent.
 *   - `integrity` LUÔN viết cứng là `khong_tin_duoc` ở đây — KHÔNG đọc từ
 *     `result.label.integrity` (quy tắc M1, dù box có trả giá trị khác).
 *   - KHÔNG có dòng `Source:` / nút "Open in IDE" ở đâu cả — hoãn sang Phase 2
 *     (mục 10.3): `data-boxfox-src` là dữ liệu do một trang web bất kỳ tự đặt,
 *     mở file theo đường dẫn đó mà chưa validate 4 lớp là một đường đi trọn
 *     vẹn từ dữ liệu web không tin được tới thao tác mở file nội bộ.
 *   - "Thêm vào hội thoại" hiện `disabled` khi đang tải (KHÔNG ẨN — tránh
 *     header nhảy layout), và HOÀN TOÀN VẮNG ở trạng thái lỗi (không có dữ
 *     liệu nào để đính kèm).
 *
 * Esc đóng ngăn kéo bất kể `armed` — đây là nửa còn lại của yêu cầu Esc; nửa
 * "Esc thoát chế độ chọn" nằm ở `ElementInspectorOverlay`. Theo quyết định Q5
 * (tự tắt `armed` ngay khi bấm điểm), hai trạng thái không bao giờ cùng lúc,
 * nên hai listener độc lập này không giẫm chân nhau.
 */
import { useEffect, useState, type ReactNode } from 'react'
import { AlertTriangle, X } from 'lucide-react'
import { useT, type TKey } from '../../i18n/context'
import { PlainText } from '../ui'
import { LabelDot } from '../LabelDot'
import { resolveBoxApiUrl } from '../../lib/boxApi'
import { InspectHttpError, type InspectErrorKind } from '../../lib/inspect'
import { isHostInspectErrorCode, type HostInspectErrorCode } from '../../lib/inspect/host'
import type { FramebufferPoint } from '../../lib/vnc/inspect'
import type { InspectorDrawerState } from '../../hooks/useElementInspector'
import type {
  DesktopInspectResult,
  DomInspectResult,
  InspectDesktopReason,
  InspectNote,
  UiaInspectResult,
} from '../../types/inspect'

/** Map mã máy `reason` (11 giá trị của box + 6 của host mode) → khoá i18n — Record chứ không nối chuỗi động, TKey vẫn kiểm được lúc biên dịch. */
const DESKTOP_REASON_KEY: Record<InspectDesktopReason, TKey> = {
  not_chromium: 'screen.inspector.drawer.desktopReason.not_chromium',
  outside_viewport: 'screen.inspector.drawer.desktopReason.outside_viewport',
  frame_extents_unknown: 'screen.inspector.drawer.desktopReason.frame_extents_unknown',
  devtools_docked: 'screen.inspector.drawer.desktopReason.devtools_docked',
  viewport_origin_unknown: 'screen.inspector.drawer.desktopReason.viewport_origin_unknown',
  no_cdp_target: 'screen.inspector.drawer.desktopReason.no_cdp_target',
  ambiguous_target: 'screen.inspector.drawer.desktopReason.ambiguous_target',
  cdp_unreachable: 'screen.inspector.drawer.desktopReason.cdp_unreachable',
  cdp_timeout: 'screen.inspector.drawer.desktopReason.cdp_timeout',
  no_node_at_point: 'screen.inspector.drawer.desktopReason.no_node_at_point',
  extract_failed: 'screen.inspector.drawer.desktopReason.extract_failed',
  // Host mode (Windows) — xem `sandbox/win/errors.py`.
  uia_unavailable: 'screen.inspector.drawer.desktopReason.uia_unavailable',
  uia_timeout: 'screen.inspector.drawer.desktopReason.uia_timeout',
  uia_provider_hang: 'screen.inspector.drawer.desktopReason.uia_provider_hang',
  uia_no_element: 'screen.inspector.drawer.desktopReason.uia_no_element',
  no_window_at_point: 'screen.inspector.drawer.desktopReason.no_window_at_point',
  window_identity_unavailable: 'screen.inspector.drawer.desktopReason.window_identity_unavailable',
}

/**
 * Map mã máy của host mode (`code` trong body lỗi) → khoá i18n.
 *
 * Tra bảng này TRƯỚC `ERROR_KIND_KEY`: cùng một 409 có thể là "bạn đang giữ
 * quyền" (mời trả quyền) hoặc "phần tử đã cũ" (mời chụp lại) — câu theo `kind`
 * chỉ nói được "bị từ chối", không nói được phải làm gì tiếp.
 */
const HOST_ERROR_KEY: Record<HostInspectErrorCode, TKey> = {
  ELEMENT_STALE: 'screen.inspector.drawer.hostError.ELEMENT_STALE',
  SOURCE_CHANGED: 'screen.inspector.drawer.hostError.SOURCE_CHANGED',
  SOURCE_IDENTITY_UNAVAILABLE: 'screen.inspector.drawer.hostError.SOURCE_IDENTITY_UNAVAILABLE',
  CONTROL_BUSY: 'screen.inspector.drawer.hostError.CONTROL_BUSY',
  DESKTOP_LOCKED: 'screen.inspector.drawer.hostError.DESKTOP_LOCKED',
  HUMAN_HAS_CONTROL: 'screen.inspector.drawer.hostError.HUMAN_HAS_CONTROL',
  HUMAN_TOOK_OVER: 'screen.inspector.drawer.hostError.HUMAN_TOOK_OVER',
  UIA_UNAVAILABLE: 'screen.inspector.drawer.hostError.UIA_UNAVAILABLE',
  UIA_TIMEOUT: 'screen.inspector.drawer.hostError.UIA_TIMEOUT',
  UIA_PROVIDER_HANG: 'screen.inspector.drawer.hostError.UIA_PROVIDER_HANG',
  UIPI_BLOCKED: 'screen.inspector.drawer.hostError.UIPI_BLOCKED',
  SESSION_NOT_INTERACTIVE: 'screen.inspector.drawer.hostError.SESSION_NOT_INTERACTIVE',
  UNSUPPORTED_IN_HOST_MODE: 'screen.inspector.drawer.hostError.UNSUPPORTED_IN_HOST_MODE',
  PASSWORD_FIELD_REFUSED: 'screen.inspector.drawer.hostError.PASSWORD_FIELD_REFUSED',
  WINDOW_MINIMIZED: 'screen.inspector.drawer.hostError.WINDOW_MINIMIZED',
  WINDOW_CLOAKED: 'screen.inspector.drawer.hostError.WINDOW_CLOAKED',
  WINDOW_IDENTITY_UNAVAILABLE: 'screen.inspector.drawer.hostError.WINDOW_IDENTITY_UNAVAILABLE',
  CAPTURE_FAILED: 'screen.inspector.drawer.hostError.CAPTURE_FAILED',
  OS_PERMISSION_REQUIRED: 'screen.inspector.drawer.hostError.OS_PERMISSION_REQUIRED',
  INSPECT_POINT_INVALID: 'screen.inspector.drawer.hostError.INSPECT_POINT_INVALID',
  INSPECT_FAILED: 'screen.inspector.drawer.hostError.INSPECT_FAILED',
}

/** Map mã máy `notes` C3 (§5.3/§5.6) → khoá i18n — 5 giá trị, cùng khuôn Record để TKey vẫn được kiểm lúc biên dịch. */
const NOTE_KEY: Record<InspectNote, TKey> = {
  shadow_dom: 'screen.inspector.drawer.note.shadow_dom',
  iframe_boundary: 'screen.inspector.drawer.note.iframe_boundary',
  selector_not_unique: 'screen.inspector.drawer.note.selector_not_unique',
  shadow_closed: 'screen.inspector.drawer.note.shadow_closed',
  truncated_ancestors: 'screen.inspector.drawer.note.truncated_ancestors',
}

/** Map phân loại lỗi `InspectErrorKind` (6 giá trị) → khoá i18n — KHÔNG phô chuỗi `message` thô do box dựng. */
const ERROR_KIND_KEY: Record<InspectErrorKind, TKey> = {
  timeout: 'screen.inspector.drawer.errorKind.timeout',
  forbidden: 'screen.inspector.drawer.errorKind.forbidden',
  notFound: 'screen.inspector.drawer.errorKind.notFound',
  server: 'screen.inspector.drawer.errorKind.server',
  badResponse: 'screen.inspector.drawer.errorKind.badResponse',
  network: 'screen.inspector.drawer.errorKind.network',
}

export interface ElementInspectorDrawerProps {
  state: InspectorDrawerState
  onClose: () => void
  onRetry: () => void
  onAddToChat: () => void
}

export function ElementInspectorDrawer({ state, onClose, onRetry, onAddToChat }: ElementInspectorDrawerProps) {
  const t = useT()

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  const title =
    state.status === 'loading'
      ? t('screen.inspector.drawer.loadingTitle')
      : state.status === 'error'
        ? t('screen.inspector.drawer.errorTitle')
        : state.result.type === 'dom'
          ? t('screen.inspector.drawer.domTitle')
          : state.result.type === 'uia'
            ? t('screen.inspector.drawer.uiaTitle')
            : t('screen.inspector.drawer.desktopTitle')

  return (
    <div
      role="dialog"
      aria-label={title}
      data-testid="inspector-drawer"
      className="pointer-events-auto absolute inset-x-2 bottom-2 z-10 flex max-h-[70%] flex-col overflow-hidden rounded-lg border border-line bg-panel shadow-xl"
    >
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
        <div className="flex min-w-0 items-center gap-2">
          {state.status === 'loading' && (
            <span
              className="size-3.5 shrink-0 animate-spin rounded-full border-2 border-line border-t-brand"
              aria-hidden="true"
            />
          )}
          {state.status === 'error' && (
            <AlertTriangle className="size-4 shrink-0 text-amber-500" aria-hidden="true" />
          )}
          <h3 className="truncate text-[13px] font-semibold">{title}</h3>
          {state.status === 'success' && (
            <span className="inline-flex shrink-0 items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.5 text-[11px] font-medium text-amber-700 ring-1 ring-amber-500/40 dark:text-amber-300">
              <LabelDot integrity="khong_tin_duoc" />
              {t('screen.inspector.drawer.untrustedBadge')}
            </span>
          )}
        </div>
        <button
          type="button"
          aria-label={t('common.close')}
          onClick={onClose}
          className="shrink-0 rounded-md p-1 text-muted hover:bg-panel2 hover:text-fg"
        >
          <X className="size-4" />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-auto p-3 text-[12px]" aria-busy={state.status === 'loading'}>
        {state.status === 'loading' && <LoadingBody point={state.point} />}
        {state.status === 'error' && <ErrorBody error={state.error} onRetry={onRetry} />}
        {state.status === 'success' && state.result.type === 'dom' && <DomBody result={state.result} />}
        {state.status === 'success' && state.result.type === 'uia' && <UiaBody result={state.result} />}
        {state.status === 'success' && state.result.type === 'desktop' && <DesktopBody result={state.result} />}
      </div>

      {state.status !== 'error' && (
        <div className="flex shrink-0 justify-end gap-2 border-t border-line px-3 py-2">
          <button
            type="button"
            disabled={state.status === 'loading'}
            onClick={onAddToChat}
            className="rounded-md bg-brand px-3 py-1.5 text-[11px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('screen.inspector.drawer.addToChat')}
          </button>
        </div>
      )}
    </div>
  )
}

function LoadingBody({ point }: { point: FramebufferPoint }) {
  const t = useT()
  return (
    <div className="space-y-3">
      <p role="status" className="text-[11px] text-muted">
        {t('screen.inspector.drawer.loadingNote', { x: point.x, y: point.y })}
      </p>
      <div className="space-y-1.5" aria-hidden="true">
        <div className="h-3 w-3/4 animate-pulse rounded bg-panel2" />
        <div className="h-3 w-1/2 animate-pulse rounded bg-panel2" />
        <div className="h-16 w-full animate-pulse rounded bg-panel2" />
      </div>
    </div>
  )
}

function ErrorBody({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const t = useT()
  const [showHelp, setShowHelp] = useState(false)
  const boxUrl = resolveBoxApiUrl()
  // Thứ tự tra: MÃ MÁY của host mode (`ELEMENT_STALE`, `HUMAN_HAS_CONTROL`, …) →
  // `InspectErrorKind` (đường của box) → `message` thô. `message` (đã qua
  // `PlainText`) chỉ còn là dự phòng cho lỗi KHÔNG phải `InspectHttpError` —
  // vẫn an toàn vì không đi vào cây HTML.
  const detail =
    error instanceof InspectHttpError
      ? isHostInspectErrorCode(error.code)
        ? t(HOST_ERROR_KEY[error.code])
        : t(ERROR_KIND_KEY[error.kind])
      : error instanceof Error
        ? error.message
        : String(error)

  return (
    <div>
      <div
        role="alert"
        className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-amber-800 dark:text-amber-200"
      >
        <p className="text-[12px] font-bold uppercase tracking-wide">
          {t('screen.inspector.drawer.errorBannerTitle')}
        </p>
        <p className="mt-1 text-[11px] leading-relaxed">
          {t('screen.inspector.drawer.errorBannerBody', { url: boxUrl })}
        </p>
        <PlainText text={detail} className="mt-1 text-[11px]" />
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={onRetry}
            className="rounded-md bg-fg px-3 py-1.5 text-[11px] font-semibold text-bg"
          >
            {t('screen.inspector.drawer.retry')}
          </button>
          <button
            type="button"
            aria-expanded={showHelp}
            onClick={() => setShowHelp((v) => !v)}
            className="rounded-md border border-line px-3 py-1.5 text-[11px] font-semibold text-muted hover:text-fg"
          >
            {t('screen.howToStartBox')}
          </button>
        </div>
        {showHelp && (
          <div className="mt-2 rounded-md bg-panel2 p-2 text-[11px] text-muted">
            <p>{t('screen.howToStartBoxBody')}</p>
            <code className="mt-1 block rounded bg-panel px-2 py-1">
              cd deploy/docker &amp;&amp; docker compose up -d
            </code>
          </div>
        )}
      </div>
      <p className="mt-2 text-[11px] text-muted">{t('screen.inspector.drawer.errorEmptyNote')}</p>
    </div>
  )
}

function DomBody({ result }: { result: DomInspectResult }) {
  const t = useT()
  const attributeEntries = Object.entries(result.attributes)
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-muted">{t('screen.inspector.drawer.domDisclaimer')}</p>
      <PlainText text={result.selector} className="rounded bg-panel2 px-2 py-1 font-semibold" />
      <Field label={t('screen.inspector.drawer.pageLabel')}>
        <PlainText text={result.url} />
      </Field>
      <Field label={t('screen.inspector.drawer.textLabel')}>
        <PlainText text={`"${result.text}"`} />
      </Field>
      {attributeEntries.length > 0 && (
        <Field label={t('screen.inspector.drawer.attributesLabel')}>
          <PlainText text={attributeEntries.map(([key, value]) => `${key}="${value}"`).join('\n')} />
        </Field>
      )}
      <Field label={t('screen.inspector.drawer.htmlLabel')}>
        <PlainText text={result.html} />
        {result.truncated && (
          <p className="mt-1 text-[11px] text-muted">{t('screen.inspector.drawer.truncatedNote')}</p>
        )}
      </Field>
      {result.notes && result.notes.length > 0 && (
        <Field label={t('screen.inspector.drawer.noteLabel')}>
          <PlainText
            text={result.notes.map((note) => t(NOTE_KEY[note])).join('\n')}
            className="text-[11px] text-muted"
          />
        </Field>
      )}
    </div>
  )
}

/**
 * Nhánh desktop — ưu tiên bản dịch của `reason` (mã máy, đã biết trước) hơn
 * `message` (chuỗi do box tự dựng, chỉ dùng khi `reason` vắng — xem chú thích
 * `InspectDesktopReason`/`message` ở `types/inspect.ts`).
 */
function desktopNoteText(result: DesktopInspectResult, t: (key: TKey, vars?: Record<string, string | number>) => string): string | null {
  if (result.reason) return t(DESKTOP_REASON_KEY[result.reason])
  if (result.message) return result.message
  return null
}

function DesktopBody({ result }: { result: DesktopInspectResult }) {
  const t = useT()
  const note = desktopNoteText(result, t)
  return (
    <div className="space-y-2">
      <p className="text-[11px] text-muted">{t('screen.inspector.drawer.desktopDisclaimer')}</p>
      {note && (
        <div
          role="alert"
          className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-[11px] text-amber-800 dark:text-amber-200"
        >
          <PlainText text={note} />
        </div>
      )}
      {result.appName && (
        <Field label={t('screen.inspector.drawer.applicationLabel')}>
          <PlainText text={result.appName} />
        </Field>
      )}
      <Field label={t('screen.inspector.drawer.windowLabel')}>
        <PlainText text={`"${result.windowTitle}"`} />
      </Field>
      <Field label={t('screen.inspector.drawer.positionLabel')}>
        <PlainText text={`(${result.position.x}, ${result.position.y})`} />
      </Field>
      <Field label={t('screen.inspector.drawer.sizeLabel')}>
        <PlainText text={`${result.size.width}×${result.size.height}`} />
      </Field>
    </div>
  )
}

/**
 * Nhánh `uia` (host mode, Windows) — thẻ "Phần tử UIA".
 *
 * Ba cờ trạng thái gom vào MỘT khối `noteLabel` thay vì mỗi cờ một dòng: người
 * dùng cần thấy ngay "phần tử này có bị tắt / ngoài tầm nhìn / là ô mật khẩu
 * không", không cần ba dòng rời. Cờ `isPassword` luôn được nói ra — đó là ranh
 * giới an toàn, không phải chi tiết kỹ thuật.
 */
function UiaBody({ result }: { result: UiaInspectResult }) {
  const t = useT()
  const flags: string[] = []
  if (!result.isEnabled) flags.push(t('screen.inspector.drawer.uiaDisabled'))
  if (result.isOffscreen) flags.push(t('screen.inspector.drawer.uiaOffscreen'))
  if (result.isPassword) flags.push(t('screen.inspector.drawer.uiaPassword'))
  const bounds = result.bounds.screenBox

  return (
    <div className="space-y-2">
      <p className="text-[11px] text-muted">{t('screen.inspector.drawer.uiaDisclaimer')}</p>
      <Field label={t('screen.inspector.drawer.nameLabel')}>
        <PlainText text={result.name} className="font-semibold" />
      </Field>
      <Field label={t('screen.inspector.drawer.controlTypeLabel')}>
        <PlainText text={result.controlType} />
      </Field>
      {result.className && (
        <Field label={t('screen.inspector.drawer.classLabel')}>
          <PlainText text={result.className} />
        </Field>
      )}
      {result.automationId && (
        <Field label={t('screen.inspector.drawer.automationIdLabel')}>
          <PlainText text={result.automationId} />
        </Field>
      )}
      <Field label={t('screen.inspector.drawer.boundsLabel')}>
        <PlainText
          text={`x ${bounds.x} · y ${bounds.y} · ${bounds.width} × ${bounds.height}${result.bounds.dpi ? ` · dpi ${result.bounds.dpi}` : ''}`}
        />
      </Field>
      {result.patterns.length > 0 && (
        <Field label={t('screen.inspector.drawer.patternsLabel')}>
          <PlainText text={result.patterns.join(', ')} />
        </Field>
      )}
      {flags.length > 0 && (
        <Field label={t('screen.inspector.drawer.noteLabel')}>
          <PlainText text={flags.join('\n')} className="text-[11px] text-muted" />
        </Field>
      )}
      <Field label={t('screen.inspector.drawer.windowLabel')}>
        <PlainText text={`windowId ${result.windowId}`} />
      </Field>
    </div>
  )
}

/** Khối nhãn + nội dung (nội dung PHẢI qua `PlainText`) — gộp khuôn lặp lại của `DomBody`/`DesktopBody`. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="text-[11px] font-semibold text-muted">{label}</div>
      {children}
    </div>
  )
}
