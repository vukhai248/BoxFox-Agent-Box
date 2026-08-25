/**
 * Thanh bên trái — phong cách BoxFox / Devin.
 */
import {
  ChevronsUpDown,
  ListFilter,
  LogOut,
  PanelLeft,
  Plus,
  Search,
  Settings,
  UserRound,
  Sparkles,
  Lock,
  FileText,
} from 'lucide-react'
import type { ReactNode } from 'react'
import { useT } from '../../i18n/context'
import { useUiStore } from '../../store/uiStore'
import { useAgentStore } from '../../store/agentStore'
import { MOCK_ACCOUNT } from '../../lib/mock/sessions'
import type { SessionSummary } from '../../types/session'
import { ShortcutsPopover } from '../chat/ShortcutsPopover'

export function Sidebar() {
  const t = useT()
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const accountMenuOpen = useUiStore((s) => s.accountMenuOpen)
  const setAccountMenuOpen = useUiStore((s) => s.setAccountMenuOpen)
  const sessionTab = useUiStore((s) => s.sessionTab)
  const setSessionTab = useUiStore((s) => s.setSessionTab)
  const openSettings = useUiStore((s) => s.openSettings)
  const sessions = useAgentStore((s) => s.sessions)
  const activeSessionId = useAgentStore((s) => s.activeSessionId)

  if (collapsed) {
    return (
      <aside className="flex w-14 shrink-0 flex-col items-center gap-3 border-r border-line bg-panel py-3 select-none">
        <div className="flex size-7 items-center justify-center rounded-lg bg-blue-600/10 text-blue-400 font-bold">
          <Sparkles className="size-4" />
        </div>
        <button
          type="button"
          onClick={toggleSidebar}
          className="rounded-md p-1.5 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
          title={t('common.expandSidebar')}
        >
          <PanelLeft className="size-4" />
        </button>
        <button
          type="button"
          className="rounded-md p-1.5 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
          title={t('sidebar.newSession')}
        >
          <Plus className="size-4" />
        </button>
        <div className="mt-auto flex flex-col items-center gap-2">
          <button
            type="button"
            onClick={() => openSettings('harness')}
            className="rounded-md p-1.5 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
            title={t('sidebar.settings')}
          >
            <Settings className="size-4" />
          </button>
          <span
            className="flex size-6 items-center justify-center rounded-full bg-blue-600/20 text-[10px] font-bold text-blue-400"
            title={MOCK_ACCOUNT.email}
          >
            {MOCK_ACCOUNT.initials}
          </span>
        </div>
      </aside>
    )
  }

  return (
    <aside className="flex w-[260px] shrink-0 flex-col border-r border-line bg-panel select-none">
      {/* Top Header: Brand Logo + Actions */}
      <div className="flex items-center justify-between px-3.5 py-3">
        <div className="flex items-center gap-2">
          <div className="flex size-6 items-center justify-center rounded-md bg-blue-600/10 text-blue-400 font-bold">
            <Sparkles className="size-3.5" />
          </div>
          <span className="text-sm font-semibold tracking-tight text-fg">boxfox</span>
        </div>
        <div className="flex items-center gap-0.5">
          <button
            type="button"
            className="rounded-md p-1 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
            title="Search"
          >
            <Search className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={toggleSidebar}
            className="rounded-md p-1 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
            title={t('common.collapseSidebar')}
          >
            <PanelLeft className="size-3.5" />
          </button>
        </div>
      </div>

      {/* Account Info Box */}
      <div className="relative px-2.5 py-1">
        <button
          type="button"
          onClick={() => setAccountMenuOpen(!accountMenuOpen)}
          className="flex w-full items-center gap-2.5 rounded-md border border-line bg-panel2/40 px-2.5 py-1.5 text-left transition hover:bg-panel2 cursor-pointer"
        >
          <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-600/20 text-[9px] font-bold text-blue-400">
            {MOCK_ACCOUNT.initials}
          </span>
          <span className="min-w-0 flex-1 truncate text-xs text-muted">
            {MOCK_ACCOUNT.email}
          </span>
          <ChevronsUpDown className="size-3 shrink-0 text-muted" />
        </button>

        {accountMenuOpen && (
          <div className="absolute left-2.5 right-2.5 z-30 mt-1 overflow-hidden rounded-lg border border-line bg-panel p-1 shadow-xl">
            <MenuItem
              icon={<UserRound className="size-3.5" />}
              label="Account Profile"
              onClick={() => setAccountMenuOpen(false)}
            />
            <MenuItem
              icon={<Settings className="size-3.5" />}
              label="Settings"
              onClick={() => {
                setAccountMenuOpen(false)
                openSettings()
              }}
            />
            <MenuItem
              icon={<LogOut className="size-3.5" />}
              label="Sign Out"
              onClick={() => setAccountMenuOpen(false)}
            />
          </div>
        )}
      </div>

      {/* New Session Button */}
      <div className="px-2.5 pt-2 pb-1">
        <button
          type="button"
          className="flex w-full items-center justify-center gap-1.5 rounded-md bg-panel2 border border-line px-3 py-1.5 text-xs font-medium text-fg transition hover:bg-panel2/80 cursor-pointer"
        >
          <Plus className="size-3.5 text-blue-400" />
          <span>New Session</span>
        </button>
      </div>

      {/* All Sessions Navigation Header */}
      <div className="px-2.5 pt-2">
        <div className="flex items-center justify-between pb-1.5 text-xs font-medium text-fg">
          <span>All Sessions</span>
        </div>

        <div className="flex items-center gap-1 border-b border-line pb-1">
          <button
            type="button"
            onClick={() => setSessionTab('recent')}
            className={`rounded px-2 py-0.5 text-xs font-medium transition cursor-pointer ${
              sessionTab === 'recent'
                ? 'bg-panel2 text-fg'
                : 'text-muted hover:text-fg'
            }`}
          >
            Recent
          </button>
          <button
            type="button"
            onClick={() => setSessionTab('groups')}
            className={`rounded px-2 py-0.5 text-xs font-medium transition cursor-pointer ${
              sessionTab === 'groups'
                ? 'bg-panel2 text-fg'
                : 'text-muted hover:text-fg'
            }`}
          >
            Groups
          </button>
          <button
            type="button"
            className="ml-auto rounded p-1 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
            title="Filter"
          >
            <ListFilter className="size-3" />
          </button>
        </div>
      </div>

      {/* Sessions List */}
      <div className="mt-1 min-h-0 flex-1 overflow-y-auto px-2 space-y-0.5">
        {sessionTab === 'groups' ? (
          <p className="px-2 py-8 text-center text-xs text-muted">No group folders</p>
        ) : (
          sessions.map((session) => (
            <SessionRow
              key={session.session_id}
              session={session}
              active={session.session_id === activeSessionId}
            />
          ))
        )}
      </div>

      {/* Bottom Footer: Settings & Shortcuts */}
      <div className="border-t border-line p-2 space-y-0.5">
        <button
          type="button"
          onClick={() => openSettings('harness')}
          className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
        >
          <Settings className="size-3.5" />
          <span>Settings</span>
        </button>
        <ShortcutsPopover variant="sidebar" />
      </div>
    </aside>
  )
}

function SessionRow({ session, active }: { session: SessionSummary; active: boolean }) {
  const isBlocked = session.status === 'cho_nguoi_dung'
  return (
    <button
      type="button"
      className={`group w-full rounded-md px-2 py-1.5 text-left transition cursor-pointer ${
        active
          ? 'bg-panel2 border border-line/80 shadow-xs'
          : 'hover:bg-panel2/50 border border-transparent'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="min-w-0 flex-1 truncate text-xs font-medium text-fg">
          {session.title}
        </span>
        <span className="shrink-0 text-[10px] text-muted">{session.relative_time}</span>
      </div>

      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        {isBlocked ? (
          <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.2 text-[9px] font-bold uppercase tracking-wider text-amber-400">
            <span className="size-1 rounded-full bg-amber-400 animate-pulse" />
            BLOCKED
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 rounded bg-panel px-1.5 py-0.2 text-[9px] font-medium text-muted border border-line">
            <span className="size-1 rounded-full bg-emerald-400" />
            {session.mode}
          </span>
        )}

        <span className="inline-flex items-center gap-0.5 rounded bg-blue-500/10 px-1 py-0.2 text-[9px] font-medium text-blue-400">
          <FileText className="size-2.5" />
          <span>Plan</span>
        </span>

        {session.active_lease_count > 0 && (
          <span className="inline-flex items-center gap-0.5 rounded bg-panel px-1 py-0.2 text-[9px] font-mono text-muted border border-line">
            <Lock className="size-2.5" />
            <span>{session.active_lease_count}</span>
          </span>
        )}
      </div>
    </button>
  )
}

function MenuItem({
  icon,
  label,
  onClick,
}: {
  icon: ReactNode
  label: string
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
