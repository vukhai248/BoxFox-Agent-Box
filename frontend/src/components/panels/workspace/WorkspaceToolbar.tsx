/**
 * Thanh công cụ panel Files: breadcrumb + công tắc Explorer/Tree + ô tìm kiếm
 * + nút Tải lên / Làm mới. Ô tìm kiếm ẩn khi đang ở chế độ Tree (tree tự lọc
 * qua cây đang mở). Nút Tải lên kích hoạt <input type=file> ẩn.
 */
import { useRef } from 'react'
import { ArrowLeft, RefreshCw, Search, Upload } from 'lucide-react'
import { useT } from '../../../i18n/context'
import type { WorkspaceCrumb } from '../../../lib/workspace'
import type { WorkspaceMode, WorkspaceStatus } from '../../../hooks/useWorkspaceFiles'
import { Breadcrumb } from './Breadcrumb'
import { SegmentedSwitch } from './SegmentedSwitch'

interface WorkspaceToolbarProps {
  crumbs: WorkspaceCrumb[]
  onNavigate: (path: string) => void
  onBack: () => void
  canGoBack: boolean
  mode: WorkspaceMode
  onModeChange: (value: WorkspaceMode) => void
  search: string
  onSearchChange: (q: string) => void
  onUploadFiles: (files: FileList) => void
  onRefresh: () => void
  selectedCount: number
  status: WorkspaceStatus
}

export function WorkspaceToolbar({
  crumbs,
  onNavigate,
  onBack,
  canGoBack,
  mode,
  onModeChange,
  search,
  onSearchChange,
  onUploadFiles,
  onRefresh,
  selectedCount,
  status,
}: WorkspaceToolbarProps) {
  const t = useT()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const busy = status === 'loading' || status === 'refreshing'

  return (
    <div className="flex items-center gap-2 border-b border-line px-3 py-2">
      <button
        type="button"
        onClick={canGoBack ? onBack : undefined}
        disabled={!canGoBack}
        aria-label={t('workspace.goBack')}
        className={`inline-flex size-7 shrink-0 items-center justify-center rounded-md border border-line transition ${
          canGoBack ? 'text-muted hover:border-brand/40 hover:text-fg' : 'cursor-not-allowed opacity-30 text-muted'
        }`}
      >
        <ArrowLeft className="size-3.5" />
      </button>
      <Breadcrumb crumbs={crumbs} onNavigate={onNavigate} />
      {selectedCount > 0 && (
        <span className="shrink-0 rounded bg-panel2 px-1.5 py-0.5 text-[10px] font-medium text-muted">
          {t('workspace.selectedCount', { n: selectedCount })}
        </span>
      )}
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <SegmentedSwitch value={mode} onChange={onModeChange} />
        {mode === 'explorer' && (
          <div className="flex items-center gap-1.5 rounded-lg border border-line bg-panel2 px-2 py-1">
            <Search className="size-3.5 text-muted" aria-hidden="true" />
            <input
              type="search"
              value={search}
              onChange={(e) => onSearchChange(e.target.value)}
              placeholder={t('workspace.search')}
              className="w-32 bg-transparent text-[11px] text-fg outline-none placeholder:text-muted"
            />
          </div>
        )}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-[11px] font-medium text-muted transition hover:border-brand/40 hover:text-fg"
        >
          <Upload className="size-3.5" />
          <span className="hidden sm:inline">{t('workspace.upload')}</span>
        </button>
        <button
          type="button"
          onClick={onRefresh}
          aria-label={t('workspace.refresh')}
          className="inline-flex size-7 items-center justify-center rounded-md border border-line text-muted transition hover:border-brand/40 hover:text-fg"
        >
          <RefreshCw className={`size-3.5 ${busy ? 'animate-spin' : ''}`} />
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => {
            if (e.target.files) onUploadFiles(e.target.files)
            e.target.value = ''
          }}
        />
      </div>
    </div>
  )
}
