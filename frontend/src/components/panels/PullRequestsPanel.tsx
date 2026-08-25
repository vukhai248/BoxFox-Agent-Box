/**
 * Khung Pull Requests phong cách GitHub / Devin.
 */
import { useState } from 'react'
import {
  GitPullRequest,
  CheckCircle2,
  FileCode,
  GitBranch,
} from 'lucide-react'

interface MockPR {
  id: number
  title: string
  branch: string
  status: 'open' | 'merged' | 'draft'
  author: string
  timeAgo: string
  filesChanged: number
  additions: number
  deletions: number
  description: string
}

const MOCK_PRS: MockPR[] = []

export function PullRequestsPanel() {
  const [selectedPrId, setSelectedPrId] = useState<number | null>(null)

  const selectedPr = MOCK_PRS.find((p) => p.id === selectedPrId) ?? MOCK_PRS[0] ?? null

  if (MOCK_PRS.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-8 text-center text-muted bg-panel">
        <GitPullRequest className="size-8 text-muted/40 mb-2" />
        <p className="text-xs font-semibold text-fg">No pull requests</p>
        <p className="text-[11px] text-muted mt-0.5">
          Pull requests will appear here when branches are created or synced.
        </p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col bg-panel select-text">
      {/* Top Header */}
      <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
        <div className="flex items-center gap-2">
          <GitPullRequest className="size-4 text-brand" />
          <h2 className="text-xs font-semibold text-fg">Pull Requests ({MOCK_PRS.length})</h2>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-[10px] font-medium text-emerald-400 border border-emerald-500/30">
            CI: All checks passed
          </span>
        </div>
      </div>

      <div className="flex min-h-0 flex-1">
        {/* Left PR list */}
        <div className="w-80 shrink-0 border-r border-line overflow-y-auto p-2.5 space-y-1.5">
          {MOCK_PRS.map((pr) => {
            const isSelected = selectedPrId === pr.id
            return (
              <div
                key={pr.id}
                onClick={() => setSelectedPrId(pr.id)}
                className={`p-2.5 rounded-lg border transition cursor-pointer ${
                  isSelected
                    ? 'border-brand bg-brand/5 shadow-xs'
                    : 'border-line bg-panel2/30 hover:bg-panel2/70 hover:border-line'
                }`}
              >
                <div className="flex items-center justify-between gap-1 mb-1">
                  <span className="font-mono text-[11px] text-muted">#{pr.id}</span>
                  <span
                    className={`rounded px-1.5 py-0.2 text-[9px] font-bold uppercase tracking-wider ${
                      pr.status === 'open'
                        ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                        : 'bg-purple-500/15 text-purple-400 border border-purple-500/30'
                    }`}
                  >
                    {pr.status}
                  </span>
                </div>
                <h4 className="text-xs font-medium text-fg line-clamp-2 leading-snug">{pr.title}</h4>
                <div className="mt-2 flex items-center justify-between text-[10px] text-muted">
                  <span className="flex items-center gap-1">
                    <GitBranch className="size-2.5" />
                    {pr.branch}
                  </span>
                  <span>{pr.timeAgo}</span>
                </div>
              </div>
            )
          })}
        </div>

        {/* Right PR details */}
        <div className="min-w-0 flex-1 overflow-y-auto p-6 space-y-5">
          <div>
            <div className="flex items-center gap-2">
              <span className="rounded bg-emerald-500/15 px-2 py-0.5 text-xs font-semibold text-emerald-400 border border-emerald-500/30 flex items-center gap-1">
                <GitPullRequest className="size-3" />
                Open
              </span>
              <h1 className="text-sm font-semibold text-fg">{selectedPr.title}</h1>
              <span className="text-xs font-mono text-muted">#{selectedPr.id}</span>
            </div>
            <p className="mt-1 text-xs text-muted">
              {selectedPr.author} wants to merge 1 commit into <code className="text-brand font-mono text-[11px]">main</code> from <code className="text-brand font-mono text-[11px]">{selectedPr.branch}</code>
            </p>
          </div>

          {/* PR Description Card */}
          <div className="rounded-lg border border-line bg-panel2/30 p-4 space-y-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted">Description</h3>
            <p className="text-xs leading-relaxed text-fg">{selectedPr.description}</p>
          </div>

          {/* Changed Files Summary */}
          <div className="space-y-2">
            <h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted">
              Files Changed ({selectedPr.filesChanged})
            </h3>
            <div className="space-y-1.5">
              <div className="flex items-center justify-between rounded-md border border-line bg-panel px-3 py-2 text-xs">
                <div className="flex items-center gap-2">
                  <FileCode className="size-3.5 text-brand" />
                  <span className="font-mono text-fg">src/parser.py</span>
                </div>
                <span className="font-mono text-[11px] text-emerald-400 font-semibold">+11 / -2</span>
              </div>
              <div className="flex items-center justify-between rounded-md border border-line bg-panel px-3 py-2 text-xs">
                <div className="flex items-center gap-2">
                  <FileCode className="size-3.5 text-brand" />
                  <span className="font-mono text-fg">tests/test_parser.py</span>
                </div>
                <span className="font-mono text-[11px] text-emerald-400 font-semibold">+3 / -0</span>
              </div>
            </div>
          </div>

          {/* CI Checks Card */}
          <div className="rounded-lg border border-emerald-500/30 bg-emerald-500/5 p-3.5 flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <CheckCircle2 className="size-4 text-emerald-400" />
              <div>
                <p className="text-xs font-semibold text-emerald-300">All automated checks have passed</p>
                <p className="text-[11px] text-muted">14 unit tests passed in 0.04s via isolated sandbox container.</p>
              </div>
            </div>
            <button
              type="button"
              className="rounded-md bg-zinc-100 px-3 py-1.5 text-xs font-semibold text-zinc-900 shadow-xs hover:bg-white transition cursor-pointer"
            >
              Merge Pull Request
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
