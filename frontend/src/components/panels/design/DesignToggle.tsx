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
import { runIsRunningInBackground } from '../../../lib/designMode'

export function DesignToggle({ compact }: { compact?: boolean }) {
  const t = useT()
  const mode = useDesignStore((s) => s.mode)
  const runs = useDesignStore((s) => s.runs)
  const setMode = useDesignStore((s) => s.setMode)
  // P1 — màn "Phiên mới" chưa có phiên nào: `setMode` trả `'error'` mà không nói gì, nên nút phải
  // KHÔNG bao giờ trông bấm được rồi im lặng. Chọn cách xử lý giống các điều khiển khác của ô soạn
  // tin (nút Gửi khoá bằng `disabled`): khoá nút + chú thích đọc được, vi + en.
  const sessionId = useDesignStore((s) => s.sessionId)
  const noSession = !sessionId

  const background = runs.filter(runIsRunningInBackground).length
  const label = mode.on ? t('design.toggleOff') : t('design.toggleOn')
  const tone = mode.on ? 'on' : background > 0 ? 'background' : 'off'
  const hint = noSession ? t('design.toggleNoSession') : t('design.toggleHint')

  return (
    <button
      type="button"
      data-testid="composer-design-toggle"
      data-no-session={noSession ? 'true' : undefined}
      disabled={noSession}
      aria-disabled={noSession}
      onClick={() => {
        if (noSession) return
        void setMode(!mode.on, 'toggle')
      }}
      className={`relative flex items-center gap-1.5 rounded px-2 py-0.5 text-[11px] font-medium transition ${
        mode.on
          ? 'bg-panel2 text-fg border border-line'
          : 'text-muted hover:bg-panel hover:text-fg border border-transparent'
      } ${noSession ? 'cursor-not-allowed opacity-40 hover:bg-transparent hover:text-muted' : 'cursor-pointer'}`}
      title={hint}
      aria-label={label}
      aria-pressed={mode.on}
    >
      <PenTool className="size-3" />
      {!compact && <span>{t('design.name')}</span>}
      {/* Chú thích đọc được bằng trình đọc màn hình khi chưa có phiên — lý do nút bị khoá. */}
      {noSession && (
        <span data-testid="design-no-session-note" className="sr-only">
          {hint}
        </span>
      )}
      {/* Chấm trạng thái: xanh khi chế độ bật; hổ phách khi chỉ còn run chạy nền. */}
      <span
        data-testid="design-toggle-dot"
        data-tone={tone}
        className={`size-1.5 rounded-full ${
          mode.on ? 'bg-brand shadow-xs' : background > 0 ? 'bg-amber-400' : 'bg-muted/40'
        }`}
      />
      {/* §5.2: chế độ tắt mà còn run nền ⇒ chú thích đọc được bằng trình đọc màn hình. */}
      {!mode.on && background > 0 && (
        <span data-testid="design-background-note" className="sr-only">
          {t('design.backgroundRuns', { count: background })}
        </span>
      )}
    </button>
  )
}
