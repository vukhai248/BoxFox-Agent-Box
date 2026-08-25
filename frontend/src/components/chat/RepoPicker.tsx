/**
 * Bộ chọn Repository cho Session (RepoPicker Popover).
 * Chuẩn phong cách BoxFox Design System:
 * - Nút Trigger hiển thị [ 🔀 {count} ˅ ]
 * - Popover mở lên trên với ô tìm kiếm Search + nút X xóa nhanh
 * - Phân nhóm: Configured (Đã cấu hình) & Not set up (Chưa thiết lập)
 * - Tương thích hoàn hảo Light/Dark mode, hỗ trợ phím ESC và click outside.
 * 
 * HƯỚNG DẪN KẾT NỐI PRODUCTION:
 * - Thay thế `INITIAL_REPOS` bằng API endpoint: `GET /api/user/repositories` (qua GitHub App / GitLab OAuth).
 * - Khi user thay đổi chọn repo -> Gửi `POST /api/sessions/:id/repositories` để cập nhật ngữ cảnh repo vào session.
 */
import { useState, useRef, useEffect, useMemo } from 'react'
import {
  GitFork,
  Search,
  Check,
  ChevronDown,
  X,
} from 'lucide-react'

export interface RepoItem {
  id: string
  fullName: string
  configured: boolean
}

const INITIAL_REPOS: RepoItem[] = []

export function RepoPicker() {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [selectedRepoIds, setSelectedRepoIds] = useState<string[]>([])
  const popoverRef = useRef<HTMLDivElement>(null)

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }

    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      document.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  const toggleRepo = (id: string) => {
    setSelectedRepoIds((prev) =>
      prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id],
    )
  }

  const filteredRepos = useMemo(() => {
    if (!search.trim()) return INITIAL_REPOS
    const q = search.toLowerCase()
    return INITIAL_REPOS.filter((r) => r.fullName.toLowerCase().includes(q))
  }, [search])

  const configuredRepos = useMemo(
    () => filteredRepos.filter((r) => r.configured),
    [filteredRepos],
  )
  const unconfiguredRepos = useMemo(
    () => filteredRepos.filter((r) => !r.configured),
    [filteredRepos],
  )

  const selectedCount = selectedRepoIds.length

  return (
    <div className="relative inline-block" ref={popoverRef}>
      {/* Trigger Button */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs font-medium transition cursor-pointer border select-none ${
          open || selectedCount > 0
            ? 'border-brand/40 bg-brand/10 text-fg shadow-xs'
            : 'border-line bg-panel2/80 text-muted hover:border-brand/30 hover:bg-panel hover:text-fg'
        }`}
        title="Select repositories for this session"
      >
        <GitFork className="size-3.5 text-brand" />
        <span className="font-mono font-semibold text-fg">{selectedCount || 0}</span>
        <ChevronDown className={`size-3 text-muted transition-transform duration-200 ${open ? 'rotate-180 text-brand' : ''}`} />
      </button>

      {/* Popover Dropdown (Opens upward) */}
      {open && (
        <div className="absolute bottom-full left-0 mb-2 w-80 sm:w-96 rounded-2xl border border-line bg-panel p-3 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-150 select-none">
          {/* Header Search Bar */}
          <div className="relative mb-2.5">
            <Search className="absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted" />
            <input
              type="text"
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search repositories..."
              className="w-full rounded-xl border border-line bg-panel2 pl-8 pr-7 py-1.5 text-xs text-fg placeholder:text-muted/60 outline-hidden focus:border-brand focus:ring-1 focus:ring-brand/30 transition font-sans select-text"
            />
            {search && (
              <button
                type="button"
                onClick={() => setSearch('')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted hover:text-fg transition p-0.5 cursor-pointer"
              >
                <X className="size-3" />
              </button>
            )}
          </div>

          {/* Repository Lists */}
          <div className="max-h-64 overflow-y-auto space-y-3 pr-1">
            {/* Group 1: Configured */}
            {configuredRepos.length > 0 && (
              <div className="space-y-1">
                <span className="text-[11px] font-semibold text-muted px-2">Configured</span>
                <div className="space-y-0.5 pt-0.5">
                  {configuredRepos.map((repo) => {
                    const isSelected = selectedRepoIds.includes(repo.id)
                    return (
                      <button
                        key={repo.id}
                        type="button"
                        onClick={() => toggleRepo(repo.id)}
                        className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
                          isSelected
                            ? 'bg-panel2 text-fg font-medium'
                            : 'text-muted hover:bg-panel2/60 hover:text-fg'
                        }`}
                      >
                        {/* Checkbox */}
                        <div
                          className={`flex size-4 shrink-0 items-center justify-center rounded border transition ${
                            isSelected
                              ? 'border-brand bg-brand text-brandfg'
                              : 'border-line bg-panel'
                          }`}
                        >
                          {isSelected && <Check className="size-3 stroke-[3]" />}
                        </div>

                        {/* GitFork Icon */}
                        <GitFork className={`size-3.5 shrink-0 ${isSelected ? 'text-brand' : 'text-muted'}`} />

                        {/* Repo Full Name */}
                        <span className="truncate font-mono text-[11px] text-fg">{repo.fullName}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Group 2: Not set up */}
            {unconfiguredRepos.length > 0 && (
              <div className="space-y-1 pt-1 border-t border-line/50">
                <span className="text-[11px] font-semibold text-muted px-2">Not set up</span>
                <div className="space-y-0.5 pt-0.5">
                  {unconfiguredRepos.map((repo) => {
                    const isSelected = selectedRepoIds.includes(repo.id)
                    return (
                      <button
                        key={repo.id}
                        type="button"
                        onClick={() => toggleRepo(repo.id)}
                        className={`flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
                          isSelected
                            ? 'bg-panel2 text-fg font-medium'
                            : 'text-muted hover:bg-panel2/60 hover:text-fg'
                        }`}
                      >
                        {/* Checkbox */}
                        <div
                          className={`flex size-4 shrink-0 items-center justify-center rounded border transition ${
                            isSelected
                              ? 'border-brand bg-brand text-brandfg'
                              : 'border-line bg-panel'
                          }`}
                        >
                          {isSelected && <Check className="size-3 stroke-[3]" />}
                        </div>

                        {/* GitFork Icon */}
                        <GitFork className={`size-3.5 shrink-0 ${isSelected ? 'text-brand' : 'text-muted'}`} />

                        {/* Repo Full Name */}
                        <span className="truncate font-mono text-[11px] text-fg">{repo.fullName}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            )}

            {filteredRepos.length === 0 && (
              <div className="py-8 text-center text-xs text-muted space-y-1">
                <GitFork className="size-6 text-muted/40 mx-auto mb-1" />
                <p className="font-semibold text-fg">
                  {search ? 'No repositories found' : 'No repositories connected'}
                </p>
                <p className="text-[11px] text-muted">
                  {search
                    ? `No matches for "${search}"`
                    : 'Connect GitHub or VCS to bind repositories to this session.'}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
