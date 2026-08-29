/**
 * Lưới thẻ (Explorer) — duyệt MỘT thư mục. Thẻ thư mục có folder vàng; thẻ
 * ảnh/video hiện thumbnail; thẻ code hiện badge ngôn ngữ + dung lượng. Chọn
 * nhiều: click thường chọn+ xem trước, Ctrl/Cmd thêm/bớt, Shift chọn khoảng.
 * Kéo-thả file vào vùng trống → tải lên thư mục hiện tại.
 */
import { ArrowUp } from 'lucide-react'
import { useState, type MouseEvent, type ReactNode } from 'react'
import { useT } from '../../../i18n/context'
import { childPath } from '../../../lib/workspace/tree'
import { previewKindFor, type WorkspaceEntry, type WorkspaceRepository } from '../../../lib/workspace'
import type { WorkspaceStatus } from '../../../hooks/useWorkspaceFiles'
import { useDropZone } from './DragDrop'
import { IntegrityDot, entryIcon, formatBytes } from './entryView'

interface ExplorerGridProps {
  entries: WorkspaceEntry[]
  cwd: string
  selected: ReadonlySet<string>
  repository: WorkspaceRepository
  status: WorkspaceStatus
  error: string | null
  canGoUp: boolean
  onOpen: (path: string) => void
  onNavigate: (path: string) => void
  onToggleSelect: (path: string, additive: boolean) => void
  onSelectRange: (path: string) => void
  onUploadFiles: (files: FileList | File[]) => void
  onGoUp: () => void
  onContextMenu: (entry: WorkspaceEntry, x: number, y: number) => void
}

export function ExplorerGrid({
  entries,
  cwd,
  selected,
  repository,
  status,
  error,
  canGoUp,
  onOpen,
  onNavigate,
  onToggleSelect,
  onSelectRange,
  onUploadFiles,
  onGoUp,
  onContextMenu,
}: ExplorerGridProps) {
  const t = useT()
  const { isDragging, onDragOver, onDragLeave, onDrop } = useDropZone((files) => onUploadFiles(files))

  const handleClick = (e: MouseEvent, entry: WorkspaceEntry) => {
    const path = childPath(cwd, entry.name)
    const additive = e.metaKey || e.ctrlKey
    if (e.shiftKey) {
      onSelectRange(path)
      return
    }
    if (entry.kind === 'dir' && !additive) {
      onNavigate(path)
      return
    }
    if (additive) {
      onToggleSelect(path, true)
      if (entry.kind === 'file') onOpen(path)
      return
    }
    onToggleSelect(path, false)
    if (entry.kind === 'file') onOpen(path)
  }

  const handleContext = (e: MouseEvent, entry: WorkspaceEntry) => {
    e.preventDefault()
    onContextMenu(entry, e.clientX, e.clientY)
  }

  return (
    <div
      className="relative h-full overflow-auto p-3"
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      {error ? (
        <div className="flex h-full items-center justify-center p-6 text-center text-[12px] text-amber-400">
          {t('workspace.error')} <span className="ml-1 text-muted">· {error}</span>
        </div>
      ) : status === 'loading' && entries.length === 0 ? (
        <div className="flex h-full items-center justify-center text-[12px] text-muted">{t('workspace.loading')}</div>
      ) : entries.length === 0 ? (
        <div className="flex h-full items-center justify-center text-[12px] text-muted">{t('workspace.empty')}</div>
      ) : (
        <div className="grid grid-cols-[repeat(auto-fill,minmax(124px,1fr))] gap-2">
          {canGoUp && (
            <button
              type="button"
              onClick={onGoUp}
              className="flex flex-col items-center justify-center rounded-lg border border-dashed border-line p-2 text-muted transition hover:border-zinc-600 hover:text-fg"
            >
              <ArrowUp className="size-6" />
              <span className="mt-1 text-[10px]">..</span>
            </button>
          )}
          {entries.map((entry) => {
            const path = childPath(cwd, entry.name)
            const { Icon, className: iconClass } = entryIcon(entry)
            const kind = entry.kind === 'file' ? previewKindFor(entry) : null
            const showThumb = kind === 'image' || kind === 'video'
            return (
              <button
                key={path}
                type="button"
                onClick={(e) => handleClick(e, entry)}
                onContextMenu={(e) => handleContext(e, entry)}
                className={`group flex flex-col rounded-lg border bg-panel2/50 p-2 text-left transition ${
                  selected.has(path) ? 'border-brand ring-1 ring-brand' : 'border-line hover:border-zinc-600'
                }`}
              >
                <div className="relative mb-1.5 flex h-16 items-center justify-center overflow-hidden rounded-md bg-panel">
                  {showThumb ? (
                    <Thumb
                      src={repository.thumbnailUrl(path)}
                      alt={entry.name}
                      fallback={<Icon className={`size-7 ${iconClass}`} />}
                    />
                  ) : (
                    <Icon className={`size-7 ${iconClass}`} />
                  )}
                  {entry.integrity && (
                    <IntegrityDot integrity={entry.integrity} className="absolute right-1 top-1" />
                  )}
                </div>
                <div className="truncate font-mono text-[11px] text-fg">{entry.name}</div>
                <div className="mt-0.5 flex items-center gap-1 text-[10px] text-muted">
                  {entry.kind === 'file' && <span>{formatBytes(entry.sizeBytes)}</span>}
                  {entry.language && <span className="rounded bg-panel px-1 font-mono">{entry.language}</span>}
                </div>
              </button>
            )
          })}
        </div>
      )}

      {isDragging && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-md border-2 border-dashed border-brand bg-brand/10">
          <span className="rounded-md bg-panel px-3 py-1.5 text-[12px] font-medium text-brand">
            {t('workspace.dropHere')}
          </span>
        </div>
      )}
    </div>
  )
}

/** Ảnh thumbnail với fallback về icon khi URL lỗi (vd: nguồn mock). */
function Thumb({ src, alt, fallback }: { src: string; alt: string; fallback: ReactNode }) {
  const [failed, setFailed] = useState(false)
  if (failed) return <>{fallback}</>
  return <img src={src} alt={alt} loading="lazy" className="size-full object-cover" onError={() => setFailed(true)} />
}
