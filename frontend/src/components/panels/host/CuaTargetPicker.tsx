/**
 * Cột chọn đích của panel "Màn hình máy" (host mode).
 *
 * Một `role="radiogroup"` duy nhất chứa hai loại lựa chọn — "Cả máy" và từng
 * cửa sổ — đúng như mockup: người dùng đang chọn MỘT đích, nên hai nhóm tách
 * rời sẽ nói dối về bản chất lựa chọn (và trình đọc màn hình sẽ đọc hai nhóm
 * không liên quan tới nhau).
 *
 * Bốn trạng thái rỗng, KHÔNG gộp thành một câu "lỗi":
 *   - `loading`     — đang đọc
 *   - `empty`       — máy chưa mở cửa sổ nào (bình thường, không phải lỗi)
 *   - `unsupported` — nền tảng không có danh sách cửa sổ (Linux; `HOST_SCREEN_UNAVAILABLE`)
 *   - `error`       — lỗi khác, kèm nút thử lại
 */
import { AppWindow, Check, Loader2, Monitor, RefreshCw, Settings2 } from 'lucide-react'
import { useT } from '../../../i18n/context'
import { SectionLabel } from '../../ui'
import type { CuaTarget, CuaWindowId, HostWindowEntry } from '../../../types/desktopTarget'
import type { PermissionScope } from '../../../types/machinePermissions'

/** Trạng thái đọc danh sách cửa sổ — nguồn duy nhất cho cả picker và panel. */
export type WindowsState = 'idle' | 'loading' | 'ready' | 'empty' | 'unsupported' | 'error'

export interface CuaTargetPickerProps {
  windows: HostWindowEntry[]
  windowsState: WindowsState
  /** Thông điệp đã dịch cho trạng thái `error` (panel dịch theo mã lỗi). */
  windowsError?: string | null
  platform?: string | null
  scope: PermissionScope | null
  /**
   * Backend tính sẵn (`machine_router.py:_target_state`) — `scope === 'machine'`.
   * Vắng ⇒ picker tự suy từ `scope`; `null` ⇒ chưa biết, KHÔNG khoá.
   */
  machineAllowed?: boolean | null
  target: CuaTarget | null
  /** Cửa sổ agent đang thao tác — chỉ để đánh dấu "đang hiện" trong danh sách. */
  activeWindowId: CuaWindowId | null
  busy: boolean
  onRefreshWindows: () => void
  onPickMachine: () => void
  onPickWindow: (entry: HostWindowEntry) => void
  onOpenPermissions: () => void
}

function sameWindow(a: CuaWindowId | null, b: CuaWindowId | null | undefined): boolean {
  return a !== null && b !== null && b !== undefined && String(a) === String(b)
}

export function CuaTargetPicker({
  windows,
  windowsState,
  windowsError,
  platform,
  scope,
  machineAllowed,
  target,
  activeWindowId,
  busy,
  onRefreshWindows,
  onPickMachine,
  onPickWindow,
  onOpenPermissions,
}: CuaTargetPickerProps) {
  const t = useT()
  // `scope === null` = chưa đọc xong `/health` ⇒ KHÔNG khoá (khoá khi chưa biết
  // là khoá oan: người dùng phải chờ một nhịp mới bấm được). `machineAllowed` là
  // câu trả lời của backend cho đúng câu hỏi này, nên nó thắng khi có mặt — và
  // vì nó là cờ DƯƠNG, phải đảo lại mới ra "khoá".
  const machineLocked =
    machineAllowed === null || machineAllowed === undefined
      ? scope !== null && scope !== 'machine'
      : !machineAllowed
  const listUnsupported = windowsState === 'unsupported'
  const loading = windowsState === 'loading'
  const machineSelected = target?.kind === 'machine'

  const machineSub = machineLocked
    ? t('machineScreen.wholeMachineLocked')
    : listUnsupported
      ? t('machineScreen.wholeMachineOnly')
      : t('machineScreen.wholeMachineHint')

  return (
    <div
      className="flex min-h-0 flex-col gap-2"
      role="radiogroup"
      aria-label={t('machineScreen.sectionTarget')}
      data-testid="ms-target-picker"
    >
      <SectionLabel>{t('machineScreen.sectionTarget')}</SectionLabel>

      <button
        type="button"
        role="radio"
        aria-checked={machineSelected}
        aria-disabled={machineLocked || busy}
        disabled={machineLocked || busy}
        onClick={onPickMachine}
        data-testid="ms-target-machine"
        title={machineLocked ? t('machineScreen.errorTargetScope') : undefined}
        className={`flex w-full items-start gap-2 rounded-lg border px-2 py-2 text-left ${
          machineSelected ? 'border-cua/60 bg-cua/10' : 'border-line bg-panel2/60 hover:bg-panel2'
        } ${machineLocked || busy ? 'cursor-not-allowed opacity-60' : ''}`}
      >
        <span className="mt-0.5 shrink-0 text-muted" aria-hidden="true">
          <Monitor className="size-4" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[12px] font-semibold">{t('machineScreen.pickWholeMachine')}</span>
          <span className="block text-[11px] leading-snug text-muted">{machineSub}</span>
        </span>
        {machineSelected && (
          <span className="mt-0.5 shrink-0 text-cua" aria-hidden="true">
            <Check className="size-4" />
          </span>
        )}
      </button>

      {machineLocked && (
        <button
          type="button"
          onClick={onOpenPermissions}
          data-testid="ms-open-permissions"
          className="inline-flex items-center gap-1.5 self-start rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
        >
          <Settings2 className="size-3.5" aria-hidden="true" />
          {t('machineScreen.openPermissions')}
        </button>
      )}

      <div className="flex shrink-0 items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
          {windowsState === 'ready'
            ? t('machineScreen.windowListCount', { count: windows.length })
            : t('machineScreen.windowListTitle')}
        </span>
        <button
          type="button"
          aria-label={t('machineScreen.windowListRefreshTitle')}
          title={t('machineScreen.windowListRefreshTitle')}
          disabled={busy || loading}
          onClick={onRefreshWindows}
          data-testid="ms-window-list-refresh"
          className="rounded-md p-1 text-muted hover:bg-panel2 hover:text-fg disabled:cursor-not-allowed disabled:opacity-50"
        >
          <RefreshCw className={`size-3.5 ${loading ? 'animate-spin' : ''}`} aria-hidden="true" />
        </button>
      </div>

      <div
        className="min-h-0 flex-1 space-y-1 overflow-auto"
        aria-label={t('machineScreen.pickWindow')}
        title={t('machineScreen.windowListAria')}
        data-testid="ms-window-list"
      >
        {loading && windows.length === 0 && (
          <p className="flex items-center gap-2 px-1 py-2 text-[11px] text-muted" role="status">
            <Loader2 className="size-3.5 animate-spin" aria-hidden="true" />
            {t('machineScreen.windowListLoading')}
          </p>
        )}

        {listUnsupported && (
          <div
            className="rounded-lg border border-dashed border-line px-2 py-2 text-[11px] leading-snug text-muted"
            data-testid="ms-window-list-unsupported"
          >
            <p className="font-semibold text-fg">{t('machineScreen.windowListEmpty')}</p>
            <p className="mt-0.5">{t('machineScreen.windowListUnsupported')}</p>
            <p className="mt-1 font-mono text-[10px]">
              {t('machineScreen.windowListPlatform', { platform: platform ?? 'unknown' })}
            </p>
          </div>
        )}

        {windowsState === 'error' && (
          <div
            className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-2 py-2 text-[11px] leading-snug text-amber-800 dark:text-amber-200"
            data-testid="ms-window-list-error"
          >
            <p className="font-semibold">{t('machineScreen.windowListEmpty')}</p>
            <p className="mt-0.5 break-words">{windowsError ?? t('machineScreen.errorScreenUnavailable')}</p>
            <button
              type="button"
              onClick={onRefreshWindows}
              className="mt-1 rounded border border-current px-2 py-0.5 font-semibold"
            >
              {t('machineScreen.windowListRefresh')}
            </button>
          </div>
        )}

        {(windowsState === 'empty' || (windowsState === 'ready' && windows.length === 0)) && (
          <div
            className="rounded-lg border border-dashed border-line px-2 py-2 text-[11px] leading-snug text-muted"
            data-testid="ms-window-list-empty"
          >
            <p className="font-semibold text-fg">{t('machineScreen.windowListEmpty')}</p>
            <p className="mt-0.5">{t('machineScreen.windowListEmptyHint')}</p>
          </div>
        )}

        {windows.map((entry) => {
          const selected = target?.kind === 'window' && sameWindow(target.windowId, entry.windowId)
          const isActive = sameWindow(activeWindowId, entry.windowId)
          return (
            <button
              key={String(entry.windowId)}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={busy}
              onClick={() => onPickWindow(entry)}
              data-testid={`ms-window-option-${String(entry.windowId)}`}
              className={`flex w-full items-start gap-2 rounded-lg border px-2 py-1.5 text-left ${
                selected ? 'border-cua/60 bg-cua/10' : 'border-transparent hover:bg-panel2'
              } ${busy ? 'cursor-not-allowed opacity-60' : ''}`}
            >
              <span className="mt-0.5 shrink-0 text-muted" aria-hidden="true">
                <AppWindow className="size-3.5" />
              </span>
              <span className="min-w-0 flex-1">
                {/* Tiêu đề cửa sổ là dữ liệu không tin được ⇒ chỉ đổ vào text node. */}
                <span className="block truncate text-[12px]" title={entry.title}>
                  {entry.title || t('machineScreen.windowListTitle')}
                </span>
                <span className="block truncate font-mono text-[10px] text-muted">
                  {t('machineScreen.windowMeta', {
                    process: entry.processName || entry.windowClass || '—',
                    windowId: String(entry.windowId),
                  })}
                  {isActive ? ` · ${t('machineScreen.windowActiveFlag')}` : ''}
                </span>
              </span>
              {selected && (
                <span className="mt-0.5 shrink-0 text-cua" aria-hidden="true">
                  <Check className="size-3.5" />
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
