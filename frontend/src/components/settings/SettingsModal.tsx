import { Globe, Terminal } from 'lucide-react'
import { useUiStore } from '../../store/uiStore'
import { SettingsSidebar } from './SettingsSidebar'
import { HarnessList } from './HarnessList'
import { HarnessEditor } from './HarnessEditor'
import { ScheduledSessionsView } from './ScheduledSessionsView'
import { AutomationsView } from './AutomationsView'
import { SecretsView } from './SecretsView'
import { BrowserView } from './BrowserView'
import { PullRequestsView } from './PullRequestsView'
import { AppearanceView } from './AppearanceView'
import { UsageView } from './UsageView'
import { ReferralsView } from './ReferralsView'
import { LlmApiKeysView } from './LlmApiKeysView'
import { SupportView } from './SupportView'

export function SettingsModal() {
  const isSettingsOpen = useUiStore((s) => s.isSettingsOpen)
  const settingsTab = useUiStore((s) => s.settingsTab)
  const editingHarnessId = useUiStore((s) => s.editingHarnessId)

  if (!isSettingsOpen) return null

  const renderContent = () => {
    if (editingHarnessId) {
      return <HarnessEditor harnessId={editingHarnessId} />
    }

    switch (settingsTab) {
      case 'harness':
        return <HarnessList />
      case 'instructions':
        return (
          <div className="p-8 max-w-4xl select-text">
            <h1 className="text-lg font-semibold mb-1 text-fg">Custom Instructions</h1>
            <p className="text-xs text-muted mb-4">
              Add global behavioral rules and system constraints for all agent sessions.
            </p>
            <textarea
              rows={8}
              placeholder="Enter instructions (e.g. Always write clean TypeScript code with strict checks)..."
              className="w-full rounded-md border border-line bg-panel p-3 text-xs text-fg outline-hidden focus:border-brand font-mono"
            />
          </div>
        )
      case 'skills':
        return (
          <div className="p-8 max-w-4xl select-text">
            <h1 className="text-lg font-semibold mb-1 text-fg">Skills & Capabilities</h1>
            <p className="text-xs text-muted mb-4">
              Manage custom toolkits and reusable skill packages.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div className="p-4 rounded-lg border border-line bg-panel">
                <div className="flex items-center gap-2 mb-1 text-blue-400">
                  <Globe className="size-4" />
                  <span className="font-medium text-fg text-xs">Web Search & Fetch</span>
                </div>
                <p className="text-xs text-muted">Fetch web page markdown and search queries.</p>
              </div>
              <div className="p-4 rounded-lg border border-line bg-panel">
                <div className="flex items-center gap-2 mb-1 text-emerald-400">
                  <Terminal className="size-4" />
                  <span className="font-medium text-fg text-xs">Sandbox Docker Shell</span>
                </div>
                <p className="text-xs text-muted">Isolated command execution with security leases.</p>
              </div>
            </div>
          </div>
        )
      case 'llm_api_keys':
        return <LlmApiKeysView />
      case 'scheduled_sessions':
        return <ScheduledSessionsView />
      case 'automations':
        return <AutomationsView />
      case 'secrets':
        return <SecretsView />
      case 'browser':
        return <BrowserView />
      case 'pull_requests':
        return <PullRequestsView />
      case 'appearance':
        return <AppearanceView />
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
    <div className="fixed inset-0 z-50 flex bg-black/90 backdrop-blur-xs text-fg animate-in fade-in duration-150">
      <div className="flex h-full w-full overflow-hidden bg-bg">
        <SettingsSidebar />
        <main className="flex-1 overflow-y-auto bg-bg">{renderContent()}</main>
      </div>
    </div>
  )
}
