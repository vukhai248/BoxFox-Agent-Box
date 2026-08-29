/**
 * View "Account" trong Settings — hiển thị hồ sơ người dùng và gói tài khoản.
 *
 * Đây là bản MOCK: chưa có backend auth/billing thật. Email hiển thị lấy từ
 * `uiStore.userEmail` (người dùng nhập ở Notifications); khi trống thì hiện
 * fallback "undefined user" giống thanh bên. Gói & mô hình triển khai (chạy
 * cloud trên máy người dùng hay deploy làm sản phẩm bán) chưa chốt nên để mock.
 */
import { User, Mail, HardDrive, BadgeCheck } from 'lucide-react'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n/context'
import { MOCK_ACCOUNT } from '../../lib/mock/sessions'

export function AccountView() {
  const t = useT()
  const userEmail = useUiStore((s) => s.userEmail)
  const displayEmail = userEmail.trim() || t('sidebar.undefinedUser')

  return (
    <div className="p-8 max-w-3xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Account</span>
        <span>›</span>
        <span className="text-fg font-semibold">Account</span>
      </div>

      {/* Header */}
      <div className="space-y-1 border-b border-line pb-4">
        <h1 className="text-xl font-bold text-fg flex items-center gap-2">
          <User className="size-4 text-brand" />
          Account
        </h1>
        <p className="text-xs text-muted">
          Your profile, plan, and device where the box runs.
        </p>
      </div>

      {/* Profile */}
      <div className="rounded-xl border border-line bg-panel p-5">
        <div className="flex items-center gap-4">
          <div className="flex size-12 items-center justify-center rounded-full bg-brand/15 text-sm font-bold text-brand">
            {MOCK_ACCOUNT.initials}
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-fg">{MOCK_ACCOUNT.displayName}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-xs text-muted">
              <Mail className="size-3" />
              <span className="truncate">{displayEmail}</span>
            </div>
          </div>
        </div>
        <div className="mt-4 flex items-center gap-2 rounded-md border border-line bg-panel2/50 px-3 py-2 text-xs text-muted">
          <HardDrive className="size-3.5" />
          <span>{MOCK_ACCOUNT.workspace}</span>
        </div>
      </div>

      {/* Plan (mock) */}
      <div className="rounded-xl border border-line bg-panel p-5 space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-fg">
            <BadgeCheck className="size-4 text-brand" />
            Current plan
          </div>
          <span className="rounded-full border border-brand/30 bg-brand/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-brand">
            Mock
          </span>
        </div>
        <div className="text-xs text-fg">Free — local machine</div>
        <p className="text-[11px] leading-relaxed text-muted">
          Account, plan &amp; billing are mocked. The deployment model is not
          decided yet — whether BoxFox runs as cloud on the user&apos;s own machine or
          is deployed as a product to sell — so plan tiers and pricing are placeholders.
        </p>
      </div>

      {/* Mock note */}
      <p className="rounded-md border border-line bg-amber-500/5 px-3 py-2 text-[11px] text-muted">
        MOCK — no real authentication or billing backend is wired yet. This view only
        previews where account settings will live.
      </p>
    </div>
  )
}
