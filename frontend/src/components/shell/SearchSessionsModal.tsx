/**
 * Command Palette "Search Sessions" — mở bằng Ctrl/Cmd+K hoặc nút tìm kiếm ở header
 * Sidebar. Lọc phiên realtime, quick action + session actions, điều hướng bằng
 * ↑/↓/Enter/Esc, footer hiển thị phím tắt.
 *
 * Backend chưa có nên `New session`, `Assign session`, `Fork session` là mock
 * (chỉ đóng modal); `Pin` và `Archive` tác động lên phiên đang được đánh dấu.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Archive, CornerDownLeft, GitFork, Pin, Plus, Search, UserPlus, X } from 'lucide-react'
import { useT } from '../../i18n/context'
import { useUiStore } from '../../store/uiStore'
import { useAgentStore } from '../../store/agentStore'
import type { SessionSummary } from '../../types/session'

type NavEntry = { kind: 'newSession' } | { kind: 'session'; session: SessionSummary }

export function SearchSessionsModal() {
  const t = useT()
  const searchOpen = useUiStore((s) => s.searchOpen)
  const closeSearch = useUiStore((s) => s.closeSearch)
  const sessions = useAgentStore((s) => s.sessions)
  const activeSessionId = useAgentStore((s) => s.activeSessionId)
  const setActiveSessionId = useAgentStore((s) => s.setActiveSessionId)
  const pinSession = useAgentStore((s) => s.pinSession)
  const archiveSession = useAgentStore((s) => s.archiveSession)

  const [query, setQuery] = useState('')
  const [filterMe, setFilterMe] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  // Ctrl/Cmd+K mở (hoặc đóng) palette — gắn ở cấp cửa sổ để hoạt động cả khi đóng.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        const s = useUiStore.getState()
        if (s.searchOpen) s.closeSearch()
        else s.openSearch()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  // Reset khi mở lại palette.
  useEffect(() => {
    if (searchOpen) {
      setQuery('')
      setFilterMe(false)
      setActiveIndex(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [searchOpen])

  const filteredSessions = useMemo(() => {
    const q = query.trim().toLowerCase()
    return sessions.filter((session) => {
      if (session.is_archived) return false
      if (filterMe && session.assigned_to !== 'Me (Khai Vu)') return false
      if (q && !session.title.toLowerCase().includes(q)) return false
      return true
    })
  }, [sessions, query, filterMe])

  const nav: NavEntry[] = useMemo(
    () => [
      { kind: 'newSession' },
      ...filteredSessions.map((session) => ({ kind: 'session', session }) as NavEntry),
    ],
    [filteredSessions],
  )

  // Phiên được đánh dấu hiện tại (mục tiêu cho Pin/Archive).
  const highlightedSession = useMemo(() => {
    const entry = nav[activeIndex]
    if (entry && entry.kind === 'session') return entry.session
    return filteredSessions[0] ?? sessions.find((s) => s.session_id === activeSessionId)
  }, [nav, activeIndex, filteredSessions, sessions, activeSessionId])

  useEffect(() => {
    if (activeIndex >= nav.length) setActiveIndex(Math.max(0, nav.length - 1))
  }, [nav.length, activeIndex])

  const activateEntry = (entry: NavEntry) => {
    if (entry.kind === 'newSession') {
      // mock: chưa có backend tạo phiên.
      closeSearch()
      return
    }
    setActiveSessionId(entry.session.session_id)
    closeSearch()
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex((i) => Math.min(nav.length - 1, i + 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex((i) => Math.max(0, i - 1))
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const entry = nav[activeIndex]
      if (entry) activateEntry(entry)
    } else if (e.key === 'Escape') {
      e.preventDefault()
      closeSearch()
    }
  }

  if (!searchOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 pt-[15vh] backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) closeSearch()
      }}
    >
      <div
        className="w-[min(560px,calc(100vw-2rem))] overflow-hidden rounded-2xl border border-line bg-panel shadow-2xl animate-in fade-in zoom-in-95 duration-150"
        onKeyDown={onKeyDown}
      >
        {/* Search input */}
        <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2.5">
          <Search className="size-4 shrink-0 text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => {
              setQuery(e.target.value)
              setActiveIndex(0)
            }}
            placeholder={t('searchPalette.placeholder')}
            className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none placeholder:text-muted/70"
          />
          <button
            type="button"
            onClick={() => setFilterMe(!filterMe)}
            className={`flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition cursor-pointer ${
              filterMe
                ? 'border-brand/60 bg-brand/10 text-brand'
                : 'border-line text-muted hover:text-fg'
            }`}
          >
            {t('searchPalette.filterMe')}
            {filterMe && <X className="size-3" />}
          </button>
        </div>

        {/* Results */}
        <div className="max-h-[50vh] overflow-y-auto p-1.5">
          {/* Quick actions */}
          <div className="px-2 pb-1 pt-1 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
            {t('searchPalette.quickActions')}
          </div>
          <button
            type="button"
            onMouseEnter={() => setActiveIndex(0)}
            onClick={() => activateEntry({ kind: 'newSession' })}
            className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition cursor-pointer ${
              activeIndex === 0 ? 'bg-panel2 text-fg' : 'text-muted hover:bg-panel2/60'
            }`}
          >
            <Plus className="size-4 text-brand" />
            <span className="flex-1">{t('searchPalette.newSession')}</span>
            <CornerDownLeft className="size-3.5 text-muted/60" />
          </button>

          {/* Session actions */}
          <div className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
            {t('searchPalette.sessionActions')}
          </div>
          <div className="grid grid-cols-2 gap-1 px-1">
            <PaletteAction
              icon={<UserPlus className="size-3.5" />}
              label={t('searchPalette.assign')}
              onClick={closeSearch}
            />
            <PaletteAction
              icon={<GitFork className="size-3.5" />}
              label={t('searchPalette.fork')}
              onClick={closeSearch}
            />
            <PaletteAction
              icon={<Pin className="size-3.5" />}
              label={t('searchPalette.pin')}
              onClick={() => {
                if (highlightedSession) pinSession(highlightedSession.session_id)
                closeSearch()
              }}
            />
            <PaletteAction
              icon={<Archive className="size-3.5" />}
              label={t('searchPalette.archive')}
              onClick={() => {
                if (highlightedSession) archiveSession(highlightedSession.session_id)
                closeSearch()
              }}
            />
          </div>

          {/* Recent sessions */}
          <div className="px-2 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-muted/70">
            {t('searchPalette.recentSessions')}
          </div>
          <div className="space-y-0.5">
            {filteredSessions.length === 0 ? (
              <p className="px-2.5 py-6 text-center text-xs text-muted">
                {t('searchPalette.noResults')}
              </p>
            ) : (
              filteredSessions.map((session, i) => {
                // nav[0] = quick action, nên index của session = i + 1.
                const idx = i + 1
                return (
                  <button
                    key={session.session_id}
                    type="button"
                    onMouseEnter={() => setActiveIndex(idx)}
                    onClick={() => activateEntry({ kind: 'session', session })}
                    className={`flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition cursor-pointer ${
                      activeIndex === idx ? 'bg-panel2 text-fg' : 'text-muted hover:bg-panel2/60'
                    }`}
                  >
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-600/20 text-[9px] font-bold text-blue-400">
                      {session.initials}
                    </span>
                    <span className="min-w-0 flex-1 truncate text-sm">{session.title}</span>
                    {session.is_pinned && <Pin className="size-3 shrink-0 text-muted/70" />}
                    <span className="shrink-0 text-[11px] text-muted/70">
                      {session.relative_time}
                    </span>
                  </button>
                )
              })
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-line px-3.5 py-2 text-[11px] text-muted/70">
          <span>Select [↑] [↓]</span>
          <span>close [esc]</span>
          <span>open menu [ctrl] + [k]</span>
        </div>
      </div>
    </div>
  )
}

function PaletteAction({
  icon,
  label,
  onClick,
}: {
  icon: React.ReactNode
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded-lg border border-line/60 bg-panel2/40 px-2.5 py-1.5 text-left text-xs text-muted transition hover:border-brand/40 hover:text-fg cursor-pointer"
    >
      {icon}
      <span className="truncate">{label}</span>
    </button>
  )
}
