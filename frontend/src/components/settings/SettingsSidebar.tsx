import {
  ArrowLeft,
  Sliders,
  FileText,
  Sparkles,
  KeyRound,
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
    id: 'AGENTS',
    title: 'AGENTS',
    items: [
      { id: 'harness', label: 'Harness', icon: Sliders },
      { id: 'instructions', label: 'Instructions', icon: FileText },
      { id: 'skills', label: 'Skills', icon: Sparkles },
      { id: 'llm_api_keys', label: 'LLM API Keys', icon: KeyRound },
      { id: 'scheduled_sessions', label: 'Scheduled Sessions', icon: Calendar },
      { id: 'automations', label: 'Automations', icon: Zap },
    ],
  },
  {
    id: 'MACHINES',
    title: 'MACHINES',
    items: [
      { id: 'configuration', label: 'Configuration', icon: Cpu },
      { id: 'secrets', label: 'Secrets', icon: Lock },
      { id: 'browser', label: 'Browser', icon: Globe },
    ],
  },
  {
    id: 'FEATURES',
    title: 'FEATURES',
    items: [
      { id: 'integrations', label: 'Integrations', icon: Zap },
      { id: 'notifications', label: 'Notifications', icon: Bell },
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
    <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-panel select-none">
      <div className="border-b border-line p-3">
        <button
          type="button"
          onClick={closeSettings}
          className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
        >
          <ArrowLeft className="size-3.5" />
          <span>Back to app</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-2.5 space-y-4">
        {SECTIONS.map((section) => (
          <div key={section.id}>
            <h3 className="px-2 py-1 text-[10px] font-semibold tracking-wider text-muted/70 uppercase">
              {section.title}
            </h3>
            <div className="mt-0.5 space-y-0.5">
              {section.items.map((item) => {
                const isActive = settingsTab === item.id
                const Icon = item.icon
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => setSettingsTab(item.id, section.id)}
                    className={`flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-xs transition cursor-pointer ${
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
