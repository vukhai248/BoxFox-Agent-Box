/**
 * Panel "Workspace Files" — kết nối hook useWorkspaceFiles với toolbar, lưới/
 * cây, overlay xem trước và menu chuột phải. Trạng thái menu giữ ở đây (cần
 * selected set + các thao tác từ hook).
 */
import { useState } from 'react'
import { useT } from '../../../i18n/context'
import { useWorkspaceFiles, type WorkspaceStatus } from '../../../hooks/useWorkspaceFiles'
import { childPath } from '../../../lib/workspace/tree'
import type { WorkspaceCrumb, WorkspaceEntry } from '../../../lib/workspace'
import { ContextMenu } from './ContextMenu'
import { ExplorerGrid } from './ExplorerGrid'
import { PreviewStudio } from './PreviewStudio'
import { TreeView } from './TreeView'
import { WorkspaceToolbar } from './WorkspaceToolbar'

interface MenuState {
  entry: WorkspaceEntry
  path: string
  x: number
  y: number
}

const ROOT_CRUMB: WorkspaceCrumb[] = [{ name: 'workspace', path: '' }]

export function WorkspaceFilesPanel() {
  const t = useT()
  const ws = useWorkspaceFiles()
  const [menu, setMenu] = useState<MenuState | null>(null)

  const crumbs = ws.listing?.breadcrumb ?? ROOT_CRUMB
  const onUploadFiles = (files: FileList | File[]) => ws.upload(files, ws.cwd)
  const canGoBack = ws.previewPath !== null || ws.cwd !== ''
  const handleBack = () => (ws.previewPath ? ws.closePreview() : ws.goUp())

  const openContextMenu = (entry: WorkspaceEntry, x: number, y: number) => {
    setMenu({ entry, path: childPath(ws.cwd, entry.name), x, y })
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="text-[13px] font-semibold">{t('workspace.title')}</h2>
        <StatusBadge status={ws.status} />
      </div>

      <WorkspaceToolbar
        crumbs={crumbs}
        onNavigate={ws.navigateTo}
        onBack={handleBack}
        canGoBack={canGoBack}
        mode={ws.mode}
        onModeChange={ws.setMode}
        search={ws.search}
        onSearchChange={ws.setSearch}
        onUploadFiles={onUploadFiles}
        onRefresh={ws.refresh}
        selectedCount={ws.selected.size}
        status={ws.status}
      />

      <div className="relative min-h-0 flex-1 overflow-hidden">
        {ws.mode === 'explorer' ? (
          <ExplorerGrid
            entries={ws.filteredEntries}
            cwd={ws.cwd}
            selected={ws.selected}
            repository={ws.repository}
            status={ws.status}
            error={ws.error}
            canGoUp={ws.cwd !== ''}
            onOpen={ws.open}
            onNavigate={ws.navigateTo}
            onToggleSelect={ws.toggleSelect}
            onSelectRange={ws.selectRange}
            onUploadFiles={onUploadFiles}
            onGoUp={ws.goUp}
            onContextMenu={openContextMenu}
          />
        ) : (
          <TreeView
            tree={ws.tree}
            expanded={ws.expanded}
            selected={ws.selected}
            onExpand={ws.expand}
            onOpen={ws.open}
            onToggleSelect={ws.toggleSelect}
            onSelectRange={ws.selectRange}
            onContextMenu={openContextMenu}
            error={ws.error}
          />
        )}

        {ws.previewPath && (
          <PreviewStudio
            path={ws.previewPath}
            entry={ws.previewEntry}
            content={ws.previewContent}
            kind={ws.previewKind}
            repository={ws.repository}
            onClose={ws.closePreview}
            onOpenInIde={ws.openInIde}
          />
        )}
      </div>

      {menu && (
        <ContextMenu
          anchor={{ x: menu.x, y: menu.y }}
          path={menu.path}
          entry={menu.entry}
          selectedCount={ws.selected.size}
          onClose={() => setMenu(null)}
          onDownload={ws.download}
          onZip={ws.zipSelected}
          onUnzip={ws.unzip}
          onOpenInIde={ws.openInIde}
        />
      )}
    </div>
  )
}

function StatusBadge({ status }: { status: WorkspaceStatus }) {
  const t = useT()
  if (status === 'loading') return <span className="text-[11px] text-muted">{t('workspace.loading')}</span>
  if (status === 'refreshing') return <span className="text-[11px] text-muted">{t('workspace.refresh')}</span>
  if (status === 'error') return <span className="text-[11px] text-amber-400">{t('workspace.error')}</span>
  return null
}
