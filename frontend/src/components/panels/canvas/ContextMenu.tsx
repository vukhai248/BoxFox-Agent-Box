/**
 * Menu chuột phải trên một component: "Bảo agent sửa đúng component này"
 * (instructAgent → directive), Duplicate và Delete.
 */
import { MessageSquareText, Copy, Trash2 } from 'lucide-react'

interface ContextMenuProps {
  x: number
  y: number
  nodeTitle: string
  onInstruct: () => void
  onDuplicate: () => void
  onDelete: () => void
  onClose: () => void
}

export function ContextMenu({ x, y, nodeTitle, onInstruct, onDuplicate, onDelete, onClose }: ContextMenuProps) {
  return (
    <div
      className="fixed z-50 w-64 overflow-hidden rounded-lg border border-line bg-panel shadow-2xl"
      style={{ left: x, top: y }}
      onContextMenu={(e) => e.preventDefault()}
    >
      <div className="border-b border-line px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-muted truncate">
        {nodeTitle || 'Component'}
      </div>
      <button
        type="button"
        onClick={() => {
          onInstruct()
          onClose()
        }}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-fg hover:bg-panel2 transition cursor-pointer"
      >
        <MessageSquareText className="size-3.5 text-brand" />
        Ask agent to fix this component
      </button>
      <button
        type="button"
        onClick={() => {
          onDuplicate()
          onClose()
        }}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-fg hover:bg-panel2 transition cursor-pointer"
      >
        <Copy className="size-3.5 text-muted" />
        Duplicate
      </button>
      <button
        type="button"
        onClick={() => {
          onDelete()
          onClose()
        }}
        className="flex w-full items-center gap-2 px-3 py-2 text-xs text-rose-400 hover:bg-rose-500/10 transition cursor-pointer"
      >
        <Trash2 className="size-3.5" />
        Delete
      </button>
    </div>
  )
}
