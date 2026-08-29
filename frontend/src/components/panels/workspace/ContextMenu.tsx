/**
 * Menu chuột phải trên một entry: Tải về / Nén ZIP & tải / Giải nén (chỉ khi
 * entry là .zip) / Mở trong VS Code Web. Đóng khi click ngoài hoặc nhấn Escape.
 */
import { Download, FileArchive, FolderOpen, Zap } from 'lucide-react'
import { useEffect, useRef } from 'react'
import { useT } from '../../../i18n/context'
import type { WorkspaceEntry } from '../../../lib/workspace'

interface ContextMenuProps {
  anchor: { x: number; y: number }
  path: string
  entry: WorkspaceEntry
  selectedCount: number
  onClose: () => void
  onDownload: (path: string) => void
  onZip: () => void
  onUnzip: (path: string) => void
  onOpenInIde: (path: string) => void
}

export function ContextMenu({
  anchor,
  path,
  entry,
  selectedCount,
  onClose,
  onDownload,
  onZip,
  onUnzip,
  onOpenInIde,
}: ContextMenuProps) {
  const t = useT()
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose()
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [onClose])

  // Giữ menu trong viewport.
  const maxLeft = Math.max(8, window.innerWidth - 224)
  const maxTop = Math.max(8, window.innerHeight - 180)
  const left = Math.min(anchor.x, maxLeft)
  const top = Math.min(anchor.y, maxTop)
  const isZip = entry.ext === 'zip'

  const run = (fn: () => void) => () => {
    fn()
    onClose()
  }

  return (
    <div
      ref={ref}
      role="menu"
      className="fixed z-50 w-52 rounded-lg border border-line bg-panel2 p-1 shadow-xl"
      style={{ left, top }}
    >
      <MenuItem icon={<Download className="size-3.5" />} onClick={run(() => onDownload(path))}>
        {t('workspace.context.download')}
      </MenuItem>
      <MenuItem icon={<FileArchive className="size-3.5" />} onClick={run(onZip)}>
        {t('workspace.context.zip')}
        {selectedCount > 1 && <span className="ml-1 text-muted">({selectedCount})</span>}
      </MenuItem>
      {isZip && (
        <MenuItem icon={<FolderOpen className="size-3.5" />} onClick={run(() => onUnzip(path))}>
          {t('workspace.context.unzip')}
        </MenuItem>
      )}
      <div className="my-1 h-px bg-line" />
      <MenuItem icon={<Zap className="size-3.5 text-brand" />} onClick={run(() => onOpenInIde(path))}>
        {t('workspace.context.openInIde')}
      </MenuItem>
    </div>
  )
}

function MenuItem({ icon, onClick, children }: { icon: React.ReactNode; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12px] text-fg transition hover:bg-panel"
    >
      <span className="shrink-0 text-muted">{icon}</span>
      <span className="truncate">{children}</span>
    </button>
  )
}
