/**
 * Thanh bên trái — phong cách BoxFox / Devin.
 *
 * Ngoài danh sách phiên, từ bản này Sidebar còn có:
 * - Nút tìm kiếm mở Command Palette (Search Sessions).
 * - Menu ngữ cảnh `...` cho từng phiên: Pin/Unpin, Rename, Add to group, Assign, Archive.
 * - Tab Groups dạng accordion, nhóm phiên theo `group_name`.
 */
import {
  Bell,
  ChevronsUpDown,
  ChevronDown,
  ChevronRight,
  Archive,
  FileText,
  Folder,
  FolderPlus,
  ListFilter,
  Lock,
  LogOut,
  MoreHorizontal,
  PanelLeft,
  Pencil,
  Pin,
  PinOff,
  Plus,
  Search,
  Settings,
  Sparkles,
  UserPlus,
  UserRound,
} from 'lucide-react'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useT } from '../../i18n/context'
import { useUiStore } from '../../store/uiStore'
import { useAgentStore } from '../../store/agentStore'
import { ASSIGNEES, MOCK_ACCOUNT } from '../../lib/mock/sessions'
import type { SessionSummary } from '../../types/session'
import { ShortcutsPopover } from '../chat/ShortcutsPopover'

export function Sidebar() {
  const t = useT()
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const openSearch = useUiStore((s) => s.openSearch)
  const accountMenuOpen = useUiStore((s) => s.accountMenuOpen)
  const setAccountMenuOpen = useUiStore((s) => s.setAccountMenuOpen)
  const sessionTab = useUiStore((s) => s.sessionTab)
  const setSessionTab = useUiStore((s) => s.setSessionTab)
  const openSettings = useUiStore((s) => s.openSettings)
  const userEmail = useUiStore((s) => s.userEmail)
  const notifyOnComplete = useUiStore((s) => s.notifyOnComplete)
  const sessions = useAgentStore((s) => s.sessions)
  const activeSessionId = useAgentStore((s) => s.activeSessionId)
  const setActiveSessionId = useAgentStore((s) => s.setActiveSessionId)

  // Chỉ mở 1 menu `...` tại một thời điểm, quản lý ở cấp Sidebar.
  const [menuOpenId, setMenuOpenId] = useState<string | null>(null)

  const visibleSessions = sessions.filter((s) => !s.is_archived)

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
            title={userEmail || t('sidebar.undefinedUser')}
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
            onClick={openSearch}
            className="rounded-md p-1 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
            title={t('common.search')}
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
            {userEmail || t('sidebar.undefinedUser')}
          </span>
          {notifyOnComplete && (
            <Bell
              className="size-3 shrink-0 text-brand"
              aria-label={t('notifications.title')}
            />
          )}
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
              icon={<Bell className="size-3.5" />}
              label={t('notifications.title')}
              onClick={() => {
                setAccountMenuOpen(false)
                openSettings('notifications')
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
          <GroupsAccordion
            sessions={visibleSessions}
            activeSessionId={activeSessionId}
            menuOpenId={menuOpenId}
            setMenuOpenId={setMenuOpenId}
            onOpen={setActiveSessionId}
          />
        ) : (
          visibleSessions.map((session) => (
            <SessionRow
              key={session.session_id}
              session={session}
              active={session.session_id === activeSessionId}
              menuOpen={menuOpenId === session.session_id}
              onToggleMenu={() =>
                setMenuOpenId(menuOpenId === session.session_id ? null : session.session_id)
              }
              onOpen={() => setActiveSessionId(session.session_id)}
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

/** Nhóm phiên theo `group_name`; phiên không nhóm gom vào một nhóm ngầm. */
function GroupsAccordion({
  sessions,
  activeSessionId,
  menuOpenId,
  setMenuOpenId,
  onOpen,
}: {
  sessions: SessionSummary[]
  activeSessionId: string
  menuOpenId: string | null
  setMenuOpenId: (id: string | null) => void
  onOpen: (id: string) => void
}) {
  const t = useT()
  const groupNames = [...new Set(sessions.map((s) => s.group_name).filter((g): g is string => !!g))]
  const ungrouped = sessions.filter((s) => !s.group_name)

  return (
    <div className="space-y-0.5 py-1">
      {groupNames.map((name) => (
        <GroupSection
          key={name}
          name={name}
          sessions={sessions.filter((s) => s.group_name === name)}
          activeSessionId={activeSessionId}
          menuOpenId={menuOpenId}
          setMenuOpenId={setMenuOpenId}
          onOpen={onOpen}
        />
      ))}
      {ungrouped.length > 0 && (
        <GroupSection
          name={t('sessionMenu.groupUngrouped')}
          sessions={ungrouped}
          activeSessionId={activeSessionId}
          menuOpenId={menuOpenId}
          setMenuOpenId={setMenuOpenId}
          onOpen={onOpen}
        />
      )}
    </div>
  )
}

function GroupSection({
  name,
  sessions,
  activeSessionId,
  menuOpenId,
  setMenuOpenId,
  onOpen,
}: {
  name: string
  sessions: SessionSummary[]
  activeSessionId: string
  menuOpenId: string | null
  setMenuOpenId: (id: string | null) => void
  onOpen: (id: string) => void
}) {
  const [open, setOpen] = useState(false)

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-xs font-medium text-muted transition hover:bg-panel2/50 hover:text-fg cursor-pointer"
      >
        {open ? (
          <ChevronDown className="size-3 shrink-0" />
        ) : (
          <ChevronRight className="size-3 shrink-0" />
        )}
        <Folder className="size-3 shrink-0 text-blue-400/70" />
        <span className="min-w-0 flex-1 truncate text-left">{name}</span>
        <span className="text-[10px] font-mono text-muted/70">{sessions.length}</span>
      </button>

      {open && (
        <div className="mt-0.5 space-y-0.5 pl-4">
          {sessions.map((session) => (
            <SessionRow
              key={session.session_id}
              session={session}
              active={session.session_id === activeSessionId}
              menuOpen={menuOpenId === session.session_id}
              onToggleMenu={() =>
                setMenuOpenId(menuOpenId === session.session_id ? null : session.session_id)
              }
              onOpen={() => onOpen(session.session_id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

function SessionRow({
  session,
  active,
  menuOpen,
  onToggleMenu,
  onOpen,
}: {
  session: SessionSummary
  active: boolean
  menuOpen: boolean
  onToggleMenu: () => void
  onOpen: () => void
}) {
  const t = useT()
  const pinSession = useAgentStore((s) => s.pinSession)
  const renameSession = useAgentStore((s) => s.renameSession)
  const setSessionGroup = useAgentStore((s) => s.setSessionGroup)
  const assignSession = useAgentStore((s) => s.assignSession)
  const archiveSession = useAgentStore((s) => s.archiveSession)
  const sessions = useAgentStore((s) => s.sessions)

  const rootRef = useRef<HTMLDivElement>(null)
  const renameInputRef = useRef<HTMLInputElement>(null)

  const [renaming, setRenaming] = useState(false)
  const [draft, setDraft] = useState(session.title)
  const [submenu, setSubmenu] = useState<'group' | 'assign' | null>(null)
  const [creatingGroup, setCreatingGroup] = useState(false)
  const [newGroupName, setNewGroupName] = useState('')

  const existingGroups = [...new Set(sessions.map((s) => s.group_name).filter((g): g is string => !!g))]

  // Đóng menu `...` khi click ra ngoài.
  useEffect(() => {
    if (!menuOpen) return
    const onMouseDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        onToggleMenu()
      }
    }
    document.addEventListener('mousedown', onMouseDown)
    return () => document.removeEventListener('mousedown', onMouseDown)
  }, [menuOpen, onToggleMenu])

  // Reset trạng thái con khi menu mở lại.
  useEffect(() => {
    if (!menuOpen) {
      setSubmenu(null)
      setCreatingGroup(false)
    }
  }, [menuOpen])

  // Focus input rename khi bắt đầu sửa.
  useEffect(() => {
    if (renaming) renameInputRef.current?.focus()
  }, [renaming])

  const startRename = () => {
    setDraft(session.title)
    setRenaming(true)
  }

  const commitRename = () => {
    renameSession(session.session_id, draft.trim() || session.title)
    setRenaming(false)
  }

  const cancelRename = () => {
    setRenaming(false)
    setDraft(session.title)
  }

  const createGroup = () => {
    const name = newGroupName.trim()
    if (name) setSessionGroup(session.session_id, name)
    setNewGroupName('')
    setCreatingGroup(false)
    setSubmenu(null)
    onToggleMenu()
  }

  const isBlocked = session.status === 'cho_nguoi_dung'

  return (
    <div ref={rootRef} className="group relative" data-testid={`session-row-${session.session_id}`}>
      <div
        className={`flex items-center rounded-md border transition cursor-pointer ${
          active
            ? 'bg-panel2 border-line/80 shadow-xs'
            : 'hover:bg-panel2/50 border-transparent'
        }`}
      >
        <div
          role="button"
          tabIndex={0}
          onClick={onOpen}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
              e.preventDefault()
              onOpen()
            }
          }}
          className="flex min-w-0 flex-1 flex-col gap-1 px-2 py-1.5 text-left cursor-pointer"
        >
          <div className="flex min-w-0 flex-1 items-center gap-1">
            {session.is_pinned && <Pin className="size-3 shrink-0 text-muted/80" />}
            {renaming ? (
              <input
                ref={renameInputRef}
                data-testid="session-rename-input"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onClick={(e) => e.stopPropagation()}
                onKeyDown={(e) => {
                  e.stopPropagation()
                  if (e.key === 'Enter') commitRename()
                  else if (e.key === 'Escape') cancelRename()
                }}
                onBlur={commitRename}
                className="min-w-0 flex-1 rounded border border-brand/60 bg-panel px-1 py-0.5 text-xs font-medium text-fg outline-none"
              />
            ) : (
              <span className="min-w-0 flex-1 truncate text-xs font-medium text-fg">
                {session.title}
              </span>
            )}
            <span className="shrink-0 text-[10px] text-muted">{session.relative_time}</span>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {isBlocked ? (
              <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-1.5 py-0.2 text-[9px] font-bold uppercase tracking-wider text-amber-400">
                <span className="size-1 rounded-full bg-amber-400 animate-pulse" />
                BLOCKED
              </span>
            ) : session.status === 'idle' ? (
              <span className="inline-flex items-center gap-1 rounded bg-panel px-1.5 py-0.2 text-[9px] font-bold uppercase tracking-wider text-muted border border-line">
                <span className="size-1 rounded-full bg-zinc-500" />
                IDLE
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

            {typeof session.step_count === 'number' && session.step_count > 0 && (
              <span className="inline-flex items-center rounded bg-panel px-1 py-0.2 text-[9px] font-mono text-muted border border-line">
                {session.step_count} steps
              </span>
            )}
          </div>
        </div>

        <button
          type="button"
          onClick={onToggleMenu}
          aria-label="Session actions"
          data-testid={`session-menu-${session.session_id}`}
          className={`mr-1 shrink-0 rounded p-1 text-muted transition cursor-pointer ${
            menuOpen
              ? 'opacity-100 bg-panel text-fg'
              : 'opacity-0 group-hover:opacity-100 hover:bg-panel hover:text-fg'
          }`}
        >
          <MoreHorizontal className="size-3.5" />
        </button>
      </div>

      {menuOpen && (
        <div className="absolute right-0 top-full z-40 mt-1 w-48 overflow-hidden rounded-lg border border-line bg-panel/95 p-1 shadow-xl backdrop-blur">
          <MenuItem
            icon={<PinOff className="size-3.5" />}
            label={session.is_pinned ? t('sessionMenu.unpin') : t('sessionMenu.pin')}
            onClick={() => {
              pinSession(session.session_id)
              onToggleMenu()
            }}
          />
          <MenuItem
            icon={<Pencil className="size-3.5" />}
            label={t('sessionMenu.rename')}
            onClick={() => {
              onToggleMenu()
              startRename()
            }}
          />

          {/* Add to group ▸ */}
          <div>
            <MenuItem
              icon={<Folder className="size-3.5" />}
              label={t('sessionMenu.addToGroup')}
              chevron
              onClick={() => setSubmenu(submenu === 'group' ? null : 'group')}
            />
            {submenu === 'group' && (
              <div className="ml-2 border-l border-line pl-1.5">
                {existingGroups.map((group) => (
                  <MenuItem
                    key={group}
                    icon={<Folder className="size-3.5" />}
                    label={group}
                    onClick={() => {
                      setSessionGroup(session.session_id, group)
                      onToggleMenu()
                    }}
                  />
                ))}
                {creatingGroup ? (
                  <div className="flex items-center gap-1 px-2 py-1">
                    <FolderPlus className="size-3.5 shrink-0 text-muted" />
                    <input
                      autoFocus
                      value={newGroupName}
                      onChange={(e) => setNewGroupName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') createGroup()
                        else if (e.key === 'Escape') setCreatingGroup(false)
                      }}
                      onBlur={createGroup}
                      placeholder={t('sessionMenu.createGroup')}
                      className="min-w-0 flex-1 rounded border border-brand/60 bg-panel px-1 py-0.5 text-[11px] text-fg outline-none"
                    />
                  </div>
                ) : (
                  <MenuItem
                    icon={<FolderPlus className="size-3.5" />}
                    label={`+ ${t('sessionMenu.createGroup')}`}
                    onClick={() => setCreatingGroup(true)}
                  />
                )}
              </div>
            )}
          </div>

          {/* Assign ▸ */}
          <div>
            <MenuItem
              icon={<UserPlus className="size-3.5" />}
              label={t('sessionMenu.assign')}
              chevron
              onClick={() => setSubmenu(submenu === 'assign' ? null : 'assign')}
            />
            {submenu === 'assign' && (
              <div className="ml-2 border-l border-line pl-1.5">
                {ASSIGNEES.map((assignee) => (
                  <MenuItem
                    key={assignee}
                    icon={<UserRound className="size-3.5" />}
                    label={assignee}
                    onClick={() => {
                      assignSession(session.session_id, assignee)
                      onToggleMenu()
                    }}
                  />
                ))}
              </div>
            )}
          </div>

          <div className="my-1 h-px bg-line" />
          <MenuItem
            icon={<Archive className="size-3.5" />}
            label={t('sessionMenu.archive')}
            onClick={() => {
              archiveSession(session.session_id)
              onToggleMenu()
            }}
          />
        </div>
      )}
    </div>
  )
}

function MenuItem({
  icon,
  label,
  onClick,
  chevron,
}: {
  icon: ReactNode
  label: string
  onClick?: () => void
  chevron?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
    >
      {icon}
      <span className="min-w-0 flex-1 truncate">{label}</span>
      {chevron && <ChevronRight className="size-3 shrink-0 text-muted/70" />}
    </button>
  )
}
