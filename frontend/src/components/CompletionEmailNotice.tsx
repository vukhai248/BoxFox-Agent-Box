/**
 * Banner xem trước email mock "đã gửi" — hiện khi `useCompletionEmail` ghi một
 * `completionEmail` vào `uiStore`. Có nút đóng; nội dung dựng lại từ helper
 * `buildCompletionEmail` theo `lang` đã chốt lúc gửi.
 */
import { Mail, X } from 'lucide-react'
import { useUiStore } from '../store/uiStore'
import { useT } from '../i18n/context'
import { buildCompletionEmail } from '../lib/notifyEmail'

export function CompletionEmailNotice() {
  const t = useT()
  const completionEmail = useUiStore((s) => s.completionEmail)
  const setCompletionEmail = useUiStore((s) => s.setCompletionEmail)

  if (!completionEmail) return null

  const { subject, body } = buildCompletionEmail(
    completionEmail.lang,
    completionEmail.title,
    completionEmail.work,
  )

  return (
    <div className="fixed bottom-4 right-4 z-[60] w-80 select-text rounded-lg border border-line bg-panel shadow-2xl shadow-black/40">
      <div className="flex items-center gap-2 border-b border-line px-3 py-2">
        <Mail className="size-3.5 text-brand" />
        <span className="flex-1 text-xs font-semibold text-fg">
          {t('notifications.noticeTitle')}
        </span>
        <button
          type="button"
          onClick={() => setCompletionEmail(null)}
          className="rounded p-0.5 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
          aria-label={t('notifications.dismiss')}
          title={t('notifications.dismiss')}
        >
          <X className="size-3.5" />
        </button>
      </div>

      <div className="space-y-2 px-3 py-2.5 text-xs">
        <p className="text-muted">
          {t('notifications.noticeTo', { email: completionEmail.to })}
        </p>
        <div className="rounded border border-line bg-panel2/60 p-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted">
            {t('notifications.emailLabel')}
          </p>
          <p className="mt-1 font-medium text-fg">{subject}</p>
          <p className="mt-1.5 whitespace-pre-wrap text-muted">{body}</p>
        </div>
      </div>
    </div>
  )
}
