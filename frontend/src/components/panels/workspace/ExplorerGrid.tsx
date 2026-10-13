/**
 * Lưới thẻ (Explorer) — duyệt MỘT thư mục. Thẻ thư mục có folder vàng; thẻ
 * ảnh/video hiện thumbnail; thẻ code hiện badge ngôn ngữ + dung lượng. Chọn
 * nhiều: click thường chọn+ xem trước, Ctrl/Cmd thêm/bớt, Shift chọn khoảng.
 * Kéo-thả file vào vùng trống → tải lên thư mục hiện tại; kéo một thẻ thả vào
 * thẻ thư mục → DI CHUYỂN entry vào đó.
 */
import { ArrowUp } from 'lucide-react'
import { useState, type DragEvent, type MouseEvent, type ReactNode } from 'react'
import { useT } from '../../../i18n/context'
import { childPath } from '../../../lib/workspace/tree'
import { previewKindFor, type WorkspaceEntry, type WorkspaceRepository } from '../../../lib/workspace'
import type { WorkspaceStatus } from '../../../hooks/useWorkspaceFiles'
import { acceptsPathDrop, draggedPath, startPathDrag, useDropZone } from './DragDrop'
import { EntryLabelDots, RenameInput, entryIcon, formatBytes } from './entryView'

const EMPTY_PENDING: ReadonlySet<string> = new Set()
const EMPTY_ERRORS: ReadonlyMap<string, string> = new Map()

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
  /** Chuột phải trên vùng trống (kể cả thư mục rỗng) → tạo mới trong `cwd`. */
  onContextMenuBackground?: (x: number, y: number) => void
  /** Thẻ đang có thao tác ghi chạy — khoá tương tác trên thẻ đó. */
  pendingPaths?: ReadonlySet<string>
  /** Lỗi của thao tác ghi gần nhất theo từng mục — hiện qua tooltip của thẻ. */
  entryErrors?: ReadonlyMap<string, string>
  /** Đường dẫn đang đổi tên tại chỗ (ô nhập thay cho tên). */
  renamingPath?: string | null
  onRenameCommit?: (path: string, name: string) => void
  onRenameCancel?: () => void
  /** Thả một entry đang kéo vào thư mục `destination`. */
  onMove?: (path: string, destination: string) => void
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
  onContextMenuBackground,
  pendingPaths = EMPTY_PENDING,
  entryErrors = EMPTY_ERRORS,
  renamingPath = null,
  onRenameCommit,
  onRenameCancel,
  onMove,
}: ExplorerGridProps) {
  const t = useT()
  const { isDragging, onDragOver, onDragLeave, onDrop } = useDropZone((files) => onUploadFiles(files))
  const [dropTarget, setDropTarget] = useState<string | null>(null)

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
    e.stopPropagation()
    onContextMenu(entry, e.clientX, e.clientY)
  }

  // Vùng trống của lưới (kể cả thư mục rỗng / đang lỗi).
  const handleBackgroundContext = (e: MouseEvent) => {
    if (!onContextMenuBackground) return
    e.preventDefault()
    onContextMenuBackground(e.clientX, e.clientY)
  }

  const handleDragOver = (e: DragEvent<HTMLElement>, destination: string) => {
    if (!acceptsPathDrop(e, destination)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDropTarget(destination)
  }

  const handleDrop = (e: DragEvent<HTMLElement>, destination: string) => {
    setDropTarget(null)
    if (!acceptsPathDrop(e, destination)) return
    e.preventDefault()
    onMove?.(draggedPath(e), destination)
  }

  return (
    <div
      className="relative h-full overflow-auto p-3"
      onContextMenu={handleBackgroundContext}
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
              onDragOver={(e) => handleDragOver(e, parentOfCwd(cwd))}
              onDragLeave={() => setDropTarget(null)}
              onDrop={(e) => handleDrop(e, parentOfCwd(cwd))}
              className={`flex flex-col items-center justify-center rounded-lg border border-dashed p-2 text-muted transition hover:border-zinc-600 hover:text-fg ${
                dropTarget === parentOfCwd(cwd) ? 'border-brand' : 'border-line'
              }`}
            >
              <ArrowUp className="size-6" />
              <span className="mt-1 text-[11px]">..</span>
            </button>
          )}
          {entries.map((entry) => {
            const path = childPath(cwd, entry.name)
            const { Icon, className: iconClass } = entryIcon(entry)
            const kind = entry.kind === 'file' ? previewKindFor(entry) : null
            const showThumb = kind === 'image' || kind === 'video'
            const isPending = pendingPaths.has(path)
            const entryError = entryErrors.get(path)
            const isRenaming = renamingPath === path
            const cardClass = `group flex flex-col rounded-lg border bg-panel2/50 p-2 text-left transition ${
              selected.has(path) ? 'border-brand ring-1 ring-brand' : 'border-line hover:border-zinc-600'
            }${dropTarget === path ? ' border-brand ring-1 ring-brand' : ''}${isPending ? ' opacity-60' : ''}`
            const body = (
              <>
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
                  {/* Cả hai nhãn provenance — cùng nhãn i18n với chấm của thanh
                      công cụ (`LabelDot`), không còn chỉ integrity như trước. */}
                  <EntryLabelDots entry={entry} className="absolute right-1 top-1" />
                </div>
                {isRenaming ? (
                  <RenameInput
                    initialValue={entry.name}
                    ariaLabel={t('workspace.renameAria')}
                    onCommit={(name) => onRenameCommit?.(path, name)}
                    onCancel={() => onRenameCancel?.()}
                    className="font-mono text-[11px]"
                  />
                ) : (
                  <div className="truncate font-mono text-[11px] text-fg">{entry.name}</div>
                )}
                <div className="mt-0.5 flex items-center gap-1 text-[11px] text-muted">
                  {entry.kind === 'file' && <span>{formatBytes(entry.sizeBytes)}</span>}
                  {entry.language && <span className="rounded bg-panel px-1 font-mono">{entry.language}</span>}
                </div>
              </>
            )
            const dragProps = {
              draggable: !isRenaming,
              onDragStart: (e: DragEvent<HTMLElement>) => startPathDrag(e, path),
            }
            const dropProps =
              entry.kind === 'dir'
                ? {
                    onDragOver: (e: DragEvent<HTMLElement>) => handleDragOver(e, path),
                    onDragLeave: () => setDropTarget(null),
                    onDrop: (e: DragEvent<HTMLElement>) => handleDrop(e, path),
                  }
                : {}
            return isRenaming ? (
              // Ô nhập không được lồng trong <button>; div dưới đây giữ nguyên lớp CSS.
              <div key={path} role="group" className={cardClass} {...dragProps} {...dropProps}>
                {body}
              </div>
            ) : (
              <button
                key={path}
                type="button"
                disabled={isPending}
                title={entryError}
                onClick={(e) => handleClick(e, entry)}
                onContextMenu={(e) => handleContext(e, entry)}
                className={cardClass}
                {...dragProps}
                {...dropProps}
              >
                {body}
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

/** Thư mục cha của `path` — đích thả của ô `..` trong lưới. */
function parentOfCwd(cwd: string): string {
  const i = cwd.lastIndexOf('/')
  return i < 0 ? '' : cwd.slice(0, i)
}

/** Ảnh thumbnail với fallback về icon khi URL lỗi (vd: nguồn mock). */
function Thumb({ src, alt, fallback }: { src: string; alt: string; fallback: ReactNode }) {
  const [failed, setFailed] = useState(false)
  if (failed) return <>{fallback}</>
  return <img src={src} alt={alt} loading="lazy" className="size-full object-cover" onError={() => setFailed(true)} />
}
