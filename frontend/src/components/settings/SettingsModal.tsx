import { useEffect, useRef, useState } from 'react'
import { useT } from '../../i18n/context'
import { useOwnerSettingsStore } from '../../store/ownerSettingsStore'
import { useUiStore } from '../../store/uiStore'
import { SettingsSidebar } from './SettingsSidebar'
import { HarnessList } from './HarnessList'
import { HarnessEditor } from './HarnessEditor'
import { ScheduledSessionsView } from './ScheduledSessionsView'
import { AutomationsView } from './AutomationsView'
import { SecretsView } from './SecretsView'
import { MachinePermissionsView } from './MachinePermissionsView'
import { BrowserView } from './BrowserView'
import { PullRequestsView } from './PullRequestsView'
import { AppearanceView } from './AppearanceView'
import { AccountView } from './AccountView'
import { NotificationsView } from './NotificationsView'
import { UsageView } from './UsageView'
import { ReferralsView } from './ReferralsView'
import { ProviderView } from './ProviderView'
import { SupportView } from './SupportView'
import { SkillsView } from './SkillsView'
import { InstructionsTab } from './InstructionsTab'

export function SettingsModal() {
  const isSettingsOpen = useUiStore((s) => s.isSettingsOpen)
  const settingsTab = useUiStore((s) => s.settingsTab)
  const editingHarnessId = useUiStore((s) => s.editingHarnessId)
  const providerInitialTab = useUiStore((s) => s.providerInitialTab)
  const closeSettings = useUiStore((s) => s.closeSettings)
  const t = useT()
  const dialogRef = useRef<HTMLDivElement>(null)
  // Rời tab khi còn chỉ dẫn chưa lưu thì hỏi một lần: Save · Discard · Stay.
  const [pendingLeave, setPendingLeave] = useState<HTMLElement | null | undefined>(undefined)
  const guardOpen = useRef(false)
  const saveDraft = useOwnerSettingsStore((s) => s.save)
  const discardDraft = useOwnerSettingsStore((s) => s.discard)

  useEffect(() => {
    if (!isSettingsOpen) return
    const previous = document.activeElement as HTMLElement | null
    dialogRef.current?.querySelector<HTMLElement>('button')?.focus()
    // Bắt ở pha capture: nút điều hướng trong sidebar không tự hỏi được, mà sửa sidebar là việc của nhánh khác.
    const navigate = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null
      const aside = dialogRef.current?.querySelector('aside')
      if (!target || !aside || !aside.contains(target)) return
      if (!useOwnerSettingsStore.getState().isDirty()) return
      event.preventDefault()
      event.stopPropagation()
      setPendingLeave(target.closest('button'))
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        // Lần Esc đầu mở câu hỏi; Esc lần nữa khi câu hỏi đang mở nghĩa là "ở lại".
        if (guardOpen.current) setPendingLeave(undefined)
        else if (useOwnerSettingsStore.getState().isDirty()) setPendingLeave(null)
        else closeSettings()
      }
      if (event.key !== 'Tab') return
      const items = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]') ?? [])].filter(el => el.getClientRects().length)
      const first = items[0], last = items.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }
    const node = dialogRef.current
    node?.addEventListener('click', navigate, true)
    window.addEventListener('keydown', key)
    return () => {
      node?.removeEventListener('click', navigate, true)
      window.removeEventListener('keydown', key)
      previous?.focus()
    }
  }, [isSettingsOpen, closeSettings])

  guardOpen.current = pendingLeave !== undefined

  if (!isSettingsOpen) return null

  const leave = () => {
    const attempt = pendingLeave
    setPendingLeave(undefined)
    if (attempt instanceof HTMLElement) attempt.click()
    else closeSettings()
  }
  const saveAndLeave = async () => {
    const saved = await saveDraft()
    if (saved) leave()
    else setPendingLeave(undefined)
  }

  const renderContent = () => {
    if (editingHarnessId) {
      return <HarnessEditor harnessId={editingHarnessId} />
    }

    switch (settingsTab) {
      case 'harness':
        return <HarnessList />
      case 'instructions':
        return <InstructionsTab />
      case 'skills':
        return <SkillsView />
      case 'llm_api_keys':
        return <ProviderView initialTab="api" />
      case 'router':
        return <ProviderView initialTab="router" />
      case 'provider':
        return <ProviderView initialTab={providerInitialTab} />
      case 'scheduled_sessions':
        return <ScheduledSessionsView />
      case 'automations':
        return <AutomationsView />
      case 'secrets':
        return <SecretsView />
      case 'machine_permissions':
        return <MachinePermissionsView />
      case 'browser':
        return <BrowserView />
      case 'pull_requests':
        return <PullRequestsView />
      case 'appearance':
        return <AppearanceView />
      case 'account':
        return <AccountView />
      case 'notifications':
        return <NotificationsView />
      case 'usage':
        return <UsageView />
      case 'referrals':
        return <ReferralsView />
      case 'support':
        return <SupportView />
      default:
        return (
          <div className="p-8 max-w-4xl select-text">
            <h1 className="text-lg font-semibold mb-1 text-fg capitalize">
              {settingsTab.replace(/_/g, ' ')}
            </h1>
            <p className="text-xs text-muted">
              Configure parameters and integrations for this section.
            </p>
          </div>
        )
    }
  }

  return (
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Settings" className="fixed inset-0 z-50 flex bg-black/90 backdrop-blur-xs text-fg animate-in fade-in duration-150">
      <div className="flex h-full w-full flex-col overflow-hidden bg-bg sm:flex-row">
        <SettingsSidebar />
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto overflow-x-hidden bg-bg">{renderContent()}</main>
      </div>
      {pendingLeave !== undefined ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-black/60 p-6">
          <div role="alertdialog" aria-modal="true" aria-label={t('instructions.guardTitle')} className="w-full max-w-sm rounded-xl border border-line bg-panel p-5 shadow-xl">
            <h2 className="text-sm font-semibold text-fg">{t('instructions.guardTitle')}</h2>
            <p className="mt-1 text-xs text-muted">{t('instructions.guardBody')}</p>
            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                data-testid="settings-guard-save"
                onClick={() => void saveAndLeave()}
                className="rounded-md bg-brand px-3 py-1.5 text-xs font-medium text-white cursor-pointer"
              >
                {t('instructions.guardSave')}
              </button>
              <button
                type="button"
                data-testid="settings-guard-discard"
                onClick={() => { discardDraft(); leave() }}
                className="rounded-md border border-line bg-panel2 px-3 py-1.5 text-xs text-fg cursor-pointer"
              >
                {t('instructions.guardDiscard')}
              </button>
              <button
                type="button"
                data-testid="settings-guard-stay"
                onClick={() => setPendingLeave(undefined)}
                className="rounded-md border border-line bg-panel2 px-3 py-1.5 text-xs text-muted cursor-pointer"
              >
                {t('instructions.guardStay')}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
