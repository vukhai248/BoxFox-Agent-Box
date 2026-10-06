import {
  ArrowLeft,
  User,
  Sliders,
  FileText,
  Sparkles,
  Route,
  Calendar,
  Cpu,
  Lock,
  Globe,
  Zap,
  Bell,
  GitPullRequest,
  Palette,
  Terminal,
  CreditCard,
  BarChart3,
  Gift,
  CircleHelp,
  ShieldCheck,
} from 'lucide-react'
import { useUiStore } from '../../store/uiStore'
import type { SettingSectionId, SettingTabId } from '../../types/harness'

interface NavItem {
  id: SettingTabId
  label: string
  icon: React.ComponentType<{ className?: string }>
}

interface NavSection {
  id: SettingSectionId
  title: string
  items: NavItem[]
}

const SECTIONS: NavSection[] = [
  {
    id: 'ACCOUNT',
    title: 'ACCOUNT',
    items: [
      { id: 'account', label: 'Account', icon: User },
      { id: 'notifications', label: 'Notifications', icon: Bell },
    ],
  },
  {
    id: 'AGENTS',
    title: 'AGENTS',
    items: [
      { id: 'harness', label: 'Harness', icon: Sliders },
      { id: 'instructions', label: 'Instructions', icon: FileText },
      { id: 'skills', label: 'Skills', icon: Sparkles },
      { id: 'provider', label: 'Provider', icon: Route },
      { id: 'scheduled_sessions', label: 'Scheduled Sessions', icon: Calendar },
      { id: 'automations', label: 'Automations', icon: Zap },
    ],
  },
  {
    id: 'MACHINES',
    title: 'MACHINES',
    items: [
      { id: 'configuration', label: 'Configuration', icon: Cpu },
      { id: 'machine_permissions', label: 'Machine & Permissions', icon: ShieldCheck },
      { id: 'secrets', label: 'Secrets', icon: Lock },
      { id: 'browser', label: 'Browser', icon: Globe },
    ],
  },
  {
    id: 'FEATURES',
    title: 'FEATURES',
    items: [
      { id: 'integrations', label: 'Integrations', icon: Zap },
      { id: 'pull_requests', label: 'Pull Requests', icon: GitPullRequest },
      { id: 'appearance', label: 'Appearance', icon: Palette },
    ],
  },
  {
    id: 'ADMINISTRATION',
    title: 'ADMINISTRATION',
    items: [
      { id: 'api', label: 'API', icon: Terminal },
      { id: 'billing', label: 'Billing', icon: CreditCard },
      { id: 'usage', label: 'Usage', icon: BarChart3 },
      { id: 'referrals', label: 'Referrals', icon: Gift },
      { id: 'support', label: 'Support & Docs', icon: CircleHelp },
    ],
  },
]

export function SettingsSidebar() {
  const settingsTab = useUiStore((s) => s.settingsTab)
  const setSettingsTab = useUiStore((s) => s.setSettingsTab)
  const closeSettings = useUiStore((s) => s.closeSettings)

  return (
    <aside className="flex max-h-34 w-full shrink-0 flex-col border-b border-line bg-panel select-none sm:max-h-none sm:w-60 sm:border-r sm:border-b-0">
      <div className="shrink-0 border-b border-line p-1.5 sm:p-3">
        <button
          type="button"
          onClick={closeSettings}
          className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
        >
          <ArrowLeft className="size-3.5" />
          <span>Back to app</span>
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden whitespace-nowrap p-2 sm:overflow-y-auto sm:whitespace-normal sm:p-2.5 sm:space-y-4">
        {SECTIONS.map((section) => (
          <div key={section.id} className="inline-block align-top sm:block">
            <h3 className="hidden px-2 py-1 text-[10px] font-semibold tracking-wider text-muted/70 uppercase sm:block">
              {section.title}
            </h3>
            <div className="mt-0.5 flex gap-1 sm:block sm:space-y-0.5">
              {section.items.map((item) => {
                const isActive = settingsTab === item.id
                const Icon = item.icon
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSettingsTab(item.id, section.id)}
                    className={`flex shrink-0 items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs transition cursor-pointer sm:w-full ${
                      isActive
                        ? 'bg-panel2 font-medium text-fg shadow-xs ring-1 ring-line'
                        : 'text-muted hover:bg-panel2/60 hover:text-fg'
                    }`}
                  >
                    <Icon className={`size-3.5 ${isActive ? 'text-fg' : 'text-muted'}`} />
                    <span>{item.label}</span>
                  </button>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </aside>
  )
}
