/**
 * Nút Design trong thanh công cụ của ô soạn tin (P1).
 *
 * Trạng thái lấy từ `session.config.designMode` (server), không phải state cục bộ, nên mở app lại
 * vẫn đúng. Bấm khi chế độ đang tắt ⇒ bật; bấm khi đang bật mà còn run hoạt động ⇒ server trả 409
 * kèm lời hỏi `exit-choice` (store giữ nó, `DesignComposerStatus` vẽ thẻ thoát).
 */
import { PenTool } from 'lucide-react'
import { useT } from '../../../i18n/context'
import { useDesignStore } from '../../../store/designStore'
import { DESIGN_TERMINAL_STATUSES } from '../../../lib/designMode'

export function DesignToggle({ compact }: { compact?: boolean }) {
  const t = useT()
  const mode = useDesignStore((s) => s.mode)
  const runs = useDesignStore((s) => s.runs)
  const setMode = useDesignStore((s) => s.setMode)

  const background = runs.filter(
    (run) => run.background && !DESIGN_TERMINAL_STATUSES.includes(run.status),
  ).length
  const label = mode.on ? t('design.toggleOff') : t('design.toggleOn')

  return (
    <button
      type="button"
      data-testid="composer-design-toggle"
      onClick={() => void setMode(!mode.on, 'toggle')}
      className={`relative flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium transition cursor-pointer ${
        mode.on
          ? 'bg-panel2 text-fg border border-line'
          : 'text-muted hover:bg-panel hover:text-fg border border-transparent'
      }`}
      title={t('design.toggleHint')}
      aria-label={label}
      aria-pressed={mode.on}
    >
      <PenTool className="size-3" />
      {!compact && <span>{t('design.name')}</span>}
      {/* Chấm trạng thái: xanh khi chế độ bật; hổ phách khi chỉ còn run chạy nền. */}
      <span
        className={`size-1.5 rounded-full ${
          mode.on ? 'bg-brand shadow-xs' : background > 0 ? 'bg-amber-400' : 'bg-muted/40'
        }`}
      />
    </button>
  )
}
