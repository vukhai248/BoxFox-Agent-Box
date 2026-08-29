/**
 * Breadcrumb điều hướng: workspace > frontend > src > ... mỗi đoạn là nút bấm.
 * Đoạn đường dẫn dùng font-mono (JetBrains Mono).
 */
import { ChevronRight } from 'lucide-react'
import type { WorkspaceCrumb } from '../../../lib/workspace'

interface BreadcrumbProps {
  crumbs: WorkspaceCrumb[]
  onNavigate: (path: string) => void
}

export function Breadcrumb({ crumbs, onNavigate }: BreadcrumbProps) {
  return (
    <nav className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto text-[11px]" aria-label="breadcrumb">
      {crumbs.map((crumb, i) => {
        const isLast = i === crumbs.length - 1
        return (
          <span key={crumb.path || `root-${i}`} className="flex shrink-0 items-center gap-0.5">
            {i > 0 && <ChevronRight className="size-3 shrink-0 text-muted" aria-hidden="true" />}
            <button
              type="button"
              onClick={() => onNavigate(crumb.path)}
              className={`rounded px-1 py-0.5 font-mono transition hover:bg-panel2 hover:text-fg ${
                isLast ? 'text-fg' : 'text-muted'
              }`}
            >
              {crumb.name}
            </button>
          </span>
        )
      })}
    </nav>
  )
}
