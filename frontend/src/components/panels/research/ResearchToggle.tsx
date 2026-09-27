/**
 * Nút Research trong thanh công cụ của ô soạn tin — biến thể `composer-toggle-toolbar-pill.html`
 * (phương án được chọn ở §4.2). Trạng thái lấy từ `session.config.researchMode` (server), không
 * phải state cục bộ, nên mở app lại vẫn đúng.
 *
 * Khi chế độ tắt mà còn run chạy nền: nút mang chấm trạng thái và bấm vào mở tab Research
 * (mockup `background-run-indicator.html`).
 */
import { Microscope } from 'lucide-react'
import { useT } from '../../../i18n/context'
import { useUiStore } from '../../../store/uiStore'
import { useResearchStore } from '../../../store/researchStore'
import { jobIsRunningInBackground } from '../../../lib/researchMode'

export function ResearchToggle({ compact }: { compact?: boolean }) {
  const t = useT()
  const mode = useResearchStore((s) => s.mode)
  const jobs = useResearchStore((s) => s.jobs)
  const setMode = useResearchStore((s) => s.setMode)
  const showTab = useUiStore((s) => s.showTab)

  const background = jobs.filter(jobIsRunningInBackground).length
  const label = mode.on ? t('research.toggleOff') : t('research.toggleOn')
  const title = background > 0 && !mode.on ? t('research.backgroundBadge', { count: background }) : t('research.toggleHint')

  function handleClick() {
    // Chế độ đang tắt mà còn run chạy nền ⇒ mở bảng Research để xem/tạm dừng run đó,
    // thay vì bật chế độ bằng một cú bấm không chủ ý.
    if (!mode.on && background > 0) {
      showTab('research')
      return
    }
    void setMode(!mode.on, 'toggle')
  }

  return (
    <button
      type="button"
      data-testid="composer-research-toggle"
      onClick={handleClick}
      className={`relative flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium transition cursor-pointer ${
        mode.on
          ? 'bg-panel2 text-fg border border-line'
          : 'text-muted hover:bg-panel hover:text-fg border border-transparent'
      }`}
      title={title}
      aria-label={label}
      aria-pressed={mode.on}
    >
      <Microscope className="size-3" />
      {!compact && <span>{t('research.name')}</span>}
      {/* Chấm trạng thái: xanh khi chế độ bật; hổ phách khi chỉ còn run chạy nền. */}
      <span
        className={`size-1.5 rounded-full ${
          mode.on ? 'bg-brand shadow-xs' : background > 0 ? 'bg-amber-400' : 'bg-muted/40'
        }`}
      />
      {background > 0 && !mode.on && (
        <span data-testid="research-background-dot" className="sr-only">
          {t('research.backgroundBadge', { count: background })}
        </span>
      )}
    </button>
  )
}
