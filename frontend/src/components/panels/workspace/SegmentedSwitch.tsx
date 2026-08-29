/**
 * Công tắc hai trạng thái Explorer (lưới) / Tree (cây) — icon lucide, không emoji.
 * Kiểu pill: nền panel2, viền line, padding 0.5, bo tròn.
 */
import { FolderTree, LayoutGrid } from 'lucide-react'
import { useT } from '../../../i18n/context'
import type { WorkspaceMode } from '../../../hooks/useWorkspaceFiles'

interface SegmentedSwitchProps {
  value: WorkspaceMode
  onChange: (value: WorkspaceMode) => void
}

export function SegmentedSwitch({ value, onChange }: SegmentedSwitchProps) {
  const t = useT()
  return (
    <div className="flex shrink-0 items-center gap-0.5 rounded-lg border border-line bg-panel2 p-0.5">
      <SegmentButton
        active={value === 'explorer'}
        onClick={() => onChange('explorer')}
        icon={<LayoutGrid className="size-3.5" />}
        label={t('workspace.explorer')}
      />
      <SegmentButton
        active={value === 'tree'}
        onClick={() => onChange('tree')}
        icon={<FolderTree className="size-3.5" />}
        label={t('workspace.tree')}
      />
    </div>
  )
}

function SegmentButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium transition ${
        active ? 'bg-panel text-fg shadow-sm' : 'text-muted hover:text-fg'
      }`}
    >
      {icon}
      <span>{label}</span>
    </button>
  )
}
