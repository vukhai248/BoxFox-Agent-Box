/**
 * Chế độ Tree — cây lồng nhau với vạch lùi (border-l từng cấp), chevron xoay khi
 * mở, và chấm provenance cho file (emerald = sạch, amber = ngoài/chưa xác minh).
 * Khóa React ổn định theo `path` để giữ cuộn. Nạp con lười qua `onExpand`.
 */
import { ChevronRight } from 'lucide-react'
import { type MouseEvent } from 'react'
import { useT } from '../../../i18n/context'
import { extOf, languageForExt } from '../../../lib/workspace'
import { flattenVisible, type TreeData, type WorkspaceTree } from '../../../lib/workspace/tree'
import type { WorkspaceEntry } from '../../../lib/workspace'
import { IntegrityDot, entryIcon } from './entryView'

interface TreeViewProps {
  tree: WorkspaceTree[]
  expanded: ReadonlySet<string>
  selected: ReadonlySet<string>
  onExpand: (path: string) => void
  onOpen: (path: string) => void
  onToggleSelect: (path: string, additive: boolean) => void
  onSelectRange: (path: string) => void
  onContextMenu: (entry: WorkspaceEntry, x: number, y: number) => void
  error: string | null
}

/** Đọc trường hiển thị từ TreeData (WorkspaceEntry hoặc FileNode). */
function readEntry(node: TreeData): WorkspaceEntry {
  if ('ext' in node) return node as WorkspaceEntry
  const ext = node.kind === 'file' ? extOf(node.name) : null
  return {
    name: node.name,
    kind: node.kind,
    sizeBytes: 0,
    mtime: '',
    integrity: node.integrity ?? null,
    confidentiality: node.confidentiality ?? null,
    ext,
    language: node.kind === 'file' ? languageForExt(ext) : null,
  }
}

export function TreeView({
  tree,
  expanded,
  selected,
  onExpand,
  onOpen,
  onToggleSelect,
  onSelectRange,
  onContextMenu,
  error,
}: TreeViewProps) {
  const t = useT()
  const flat = flattenVisible(tree)

  const handleActivate = (e: MouseEvent, path: string, isDir: boolean) => {
    const additive = e.metaKey || e.ctrlKey
    if (e.shiftKey) {
      onSelectRange(path)
      return
    }
    if (isDir) {
      if (additive) onToggleSelect(path, true)
      else onExpand(path)
      return
    }
    if (additive) onToggleSelect(path, true)
    else onToggleSelect(path, false)
    onOpen(path)
  }

  const handleContext = (e: MouseEvent, entry: WorkspaceEntry) => {
    e.preventDefault()
    onContextMenu(entry, e.clientX, e.clientY)
  }

  if (error) {
    return <div className="flex h-full items-center justify-center p-6 text-[12px] text-amber-400">{t('workspace.error')}</div>
  }
  if (flat.length === 0) {
    return <div className="flex h-full items-center justify-center text-[12px] text-muted">{t('workspace.empty')}</div>
  }

  return (
    <div className="h-full overflow-auto p-1.5">
      {flat.map(({ node, depth }) => {
        const entry = readEntry(node.node)
        const isDir = entry.kind === 'dir'
        const isOpen = expanded.has(node.path)
        const { Icon, className: iconClass } = entryIcon(entry)
        return (
          <div key={node.path} className="flex items-stretch">
            {Array.from({ length: depth }).map((_, i) => (
              <span key={i} className="w-4 shrink-0 border-l border-line" aria-hidden="true" />
            ))}
            <button
              type="button"
              onClick={(e) => handleActivate(e, node.path, isDir)}
              onContextMenu={(e) => handleContext(e, entry)}
              className={`flex flex-1 items-center gap-1 rounded-md px-1.5 py-1 text-left text-[12px] transition ${
                selected.has(node.path) ? 'bg-brand/15 text-fg ring-1 ring-brand/40' : 'text-fg hover:bg-panel2'
              }`}
            >
              {isDir ? (
                <ChevronRight
                  className={`size-3.5 shrink-0 text-muted transition-transform ${isOpen ? 'rotate-90' : ''}`}
                  aria-hidden="true"
                />
              ) : (
                <span className="w-3.5 shrink-0" />
              )}
              <Icon className={`size-3.5 shrink-0 ${iconClass}`} />
              <span className="truncate font-mono">{entry.name}</span>
              {entry.integrity && <IntegrityDot integrity={entry.integrity} className="ml-auto" />}
            </button>
          </div>
        )
      })}
    </div>
  )
}
