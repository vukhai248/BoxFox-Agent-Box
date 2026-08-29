/**
 * View cài đặt Notifications: nơi người dùng nhập email nhận thông báo và
 * bật/tắt "gửi email mock khi box hoàn thành task". Đây chỉ là email MOCK —
 * backend AI đang tạm gác nên không có mail thật nào được gửi đi.
 */
import { Bell, Mail } from 'lucide-react'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n/context'
import { CustomCheckbox } from './CustomCheckbox'

export function NotificationsView() {
  const t = useT()
  const userEmail = useUiStore((s) => s.userEmail)
  const setUserEmail = useUiStore((s) => s.setUserEmail)
  const notifyOnComplete = useUiStore((s) => s.notifyOnComplete)
  const setNotifyOnComplete = useUiStore((s) => s.setNotifyOnComplete)

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Account</span>
        <span>›</span>
        <span className="text-fg font-semibold">{t('notifications.title')}</span>
      </div>

      {/* Header */}
      <div className="space-y-1 border-b border-line pb-4">
        <h1 className="text-xl font-bold text-fg flex items-center gap-2">
          <Bell className="size-4 text-brand" />
          {t('notifications.title')}
        </h1>
        <p className="text-xs text-muted">{t('notifications.subtitle')}</p>
      </div>

      {/* Email input */}
      <div className="space-y-2">
        <label
          htmlFor="notify-email"
          className="flex items-center gap-2 text-xs font-medium text-fg"
        >
          <Mail className="size-3.5 text-muted" />
          {t('notifications.emailLabel')}
        </label>
        <input
          id="notify-email"
          type="email"
          value={userEmail}
          onChange={(e) => setUserEmail(e.target.value)}
          placeholder={t('notifications.emailPlaceholder')}
          aria-label={t('notifications.emailLabel')}
          className="w-full rounded-md border border-line bg-panel px-3 py-2 text-xs text-fg outline-hidden focus:border-brand placeholder:text-muted/60"
        />
        <p className="text-[11px] text-muted">{t('notifications.emailHint')}</p>
      </div>

      {/* Toggle */}
      <div className="rounded-lg border border-line bg-panel p-4">
        <CustomCheckbox
          checked={notifyOnComplete}
          onChange={() => setNotifyOnComplete(!notifyOnComplete)}
          label={t('notifications.toggleLabel')}
          description={t('notifications.toggleDesc')}
          className="items-start"
        />
      </div>

      {/* Mock note */}
      <p className="rounded-md border border-line bg-amber-500/5 px-3 py-2 text-[11px] text-muted">
        {t('notifications.mockNote')}
      </p>
    </div>
  )
}
