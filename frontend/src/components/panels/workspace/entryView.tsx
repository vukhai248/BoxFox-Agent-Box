/**
 * Tiện ích hiển thị chung cho lưới Explorer và cây Tree: định dạng dung lượng
 * và chọn icon+màu theo loại file. Tiếng Việt ở comment, English ở định danh.
 */
import { File, FileCode, FileText, Film, Folder, Image as ImageIcon, Music } from 'lucide-react'
import type { ComponentType } from 'react'
import { useT } from '../../../i18n/context'
import { INTEGRITY_META } from '../../../lib/labels'
import { previewKindFor } from '../../../lib/workspace'
import type { Integrity } from '../../../types/labels'

export function formatBytes(bytes: number): string {
  if (!bytes) return '0 B'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

interface EntryLike {
  kind: 'file' | 'dir'
  ext: string | null
  language: string | null
}

export interface EntryIcon {
  Icon: ComponentType<{ className?: string }>
  className: string
}

/** Icon + màu cho một entry. Thư mục dùng folder vàng; file theo loại xem trước. */
export function entryIcon(entry: EntryLike): EntryIcon {
  if (entry.kind === 'dir') return { Icon: Folder, className: 'text-amber-400' }
  switch (previewKindFor(entry)) {
    case 'image':
      return { Icon: ImageIcon, className: 'text-sky-400' }
    case 'video':
      return { Icon: Film, className: 'text-violet-400' }
    case 'audio':
      return { Icon: Music, className: 'text-pink-400' }
    case 'pdf':
      return { Icon: FileText, className: 'text-red-400' }
    case 'markdown':
      return { Icon: FileText, className: 'text-brand' }
    case 'code':
      return { Icon: FileCode, className: 'text-brand' }
    case 'text':
      return { Icon: FileText, className: 'text-muted' }
    default:
      return { Icon: File, className: 'text-muted' }
  }
}

/**
 * Chấm provenance cho file workspace. Dùng màu của `INTEGRITY_META` (emerald =
 * sạch, amber = ngoài/chưa xác minh — GIỮ amber theo quy ước app, không đổi đỏ)
 * kèm `title` tiếng Việt để không bao giờ chỉ truyền bằng màu.
 */
export function IntegrityDot({ integrity, className = '' }: { integrity: Integrity; className?: string }) {
  const t = useT()
  const meta = INTEGRITY_META[integrity]
  const title =
    integrity === 'duoc_nguoi_dung_cho_phep'
      ? t('workspace.integrity.clean')
      : t('workspace.integrity.unverified')
  return (
    <span
      className={`size-2 shrink-0 rounded-full ${meta.dotClass} ${className}`}
      title={title}
      aria-label={title}
      role="img"
    />
  )
}
