/**
 * Thẻ chuyển chế độ Plan → Act (ModeSwitchCard).
 * Tái cấu trúc chuẩn BoxFox Design System (Semantic Design Tokens).
 * 1. Bundled Scope Callout (Xanh lá / Đỏ khi từ chối)
 * 2. Full Plan Blueprint Viewer
 * 3. Influencing Source Labels (Interactive link badges)
 * 4. Out-of-Scope Warning Items
 * 5. Action Buttons ("Switch to Act" / "Edit Plan")
 */
import { useMemo } from 'react'
import {
  ShieldCheck,
  ShieldAlert,
  FileCode,
  ArrowRight,
  Clock,
  Edit3,
  AlertTriangle,
  Sparkles,
} from 'lucide-react'
import { useAgentStore } from '../store/agentStore'
import { useUiStore } from '../store/uiStore'
import { buildBundledScopeLine } from '../lib/scope'
import type { ModeSwitchProposal } from '../types/agent'

interface Props {
  proposal: ModeSwitchProposal
  /** Bật trạng thái "Controller từ chối cấp giấy phép gộp" (cho demo mock). */
  rejectBundle?: boolean
}

export function ModeSwitchCard({ proposal, rejectBundle = false }: Props) {
  const sendCommand = useAgentStore((s) => s.sendCommand)
  const openSource = useUiStore((s) => s.openSource)

  const plan = proposal.plan

  const scopeLine = useMemo(
    () => buildBundledScopeLine(rejectBundle ? { ...proposal, bundled_lease_rejected: true } : proposal),
    [proposal, rejectBundle],
  )

  const outOfScopeSteps = plan.steps.filter((s) => s.out_of_scope)

  const handleAccept = () => {
    sendCommand({ type: 'mode_switch_confirm', accepted: true })
  }

  const handleEdit = () => {
    sendCommand({ type: 'mode_switch_confirm', accepted: false })
  }

  const effectiveRejected = rejectBundle || proposal.bundled_lease_rejected

  return (
    <div className="rounded-2xl border border-line bg-panel p-6 shadow-xl space-y-5 animate-in fade-in zoom-in-98 duration-150 select-text">
      {/* 1. Header Title & Badge */}
      <div className="flex items-center justify-between border-b border-line pb-3">
        <div className="flex items-center gap-2.5">
          <div className="flex size-7 items-center justify-center rounded-lg bg-brand/15 text-brand border border-brand/30">
            <Sparkles className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-fg">Mode Switch Proposal: Plan → Act</h3>
            <p className="text-xs text-muted">Review implementation blueprint and authorize scoped execution lease.</p>
          </div>
        </div>

        <span className="rounded-full bg-amber-500/15 border border-amber-500/30 px-2.5 py-0.5 font-mono text-[10px] font-bold text-amber-600 dark:text-amber-400">
          PLAN MODE
        </span>
      </div>

      {/* 2. Dòng phạm vi đã gộp (Bundled Scope Callout) */}
      <div
        className={`rounded-xl p-4 text-xs font-medium leading-relaxed flex items-start gap-3 border shadow-xs ${
          effectiveRejected
            ? 'border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300'
            : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-800 dark:text-emerald-300'
        }`}
      >
        {effectiveRejected ? (
          <ShieldAlert className="size-4.5 text-rose-500 shrink-0 mt-0.5" />
        ) : (
          <ShieldCheck className="size-4.5 text-emerald-500 shrink-0 mt-0.5" />
        )}
        <div className="flex-1">
          <p className="font-semibold text-xs mb-0.5">
            {effectiveRejected ? 'Bundled Lease Rejected' : 'Scoped Lease Boundaries'}
          </p>
          <p>{scopeLine}</p>
        </div>
      </div>

      {/* 3. Toàn văn bản kế hoạch (Full Plan Text Viewer) */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs font-bold text-muted">
          <span className="uppercase tracking-wider">Implementation Blueprint</span>
          <span className="font-mono text-[10px] text-muted">plan.md • {plan.steps.length} steps</span>
        </div>

        <div className="max-h-64 overflow-y-auto rounded-xl border border-line bg-panel2 p-4 font-mono text-xs leading-relaxed text-fg whitespace-pre-wrap select-text shadow-inner">
          {plan.full_text}
        </div>
      </div>

      {/* 4. Danh sách nguồn (Influencing Sources) */}
      {plan.derived_from.length > 0 && (
        <div className="space-y-1.5">
          <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
            Sources Influencing This Plan
          </span>
          <div className="flex flex-wrap items-center gap-2">
            {plan.derived_from.map((labelId) => (
              <button
                key={labelId}
                type="button"
                onClick={() => openSource(labelId)}
                className="flex items-center gap-1.5 rounded-lg border border-line bg-panel2 px-2.5 py-1 text-xs font-mono font-bold text-brand hover:border-brand hover:bg-panel transition cursor-pointer shadow-xs"
                title={`Inspect provenance artifact ${labelId}`}
              >
                <FileCode className="size-3.5" />
                <span>{labelId}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 5. Các bước tô đỏ (Out of scope warning) */}
      {outOfScopeSteps.length > 0 && (
        <div className="space-y-2">
          <div className="flex items-center gap-1.5 text-xs font-bold text-rose-500 uppercase tracking-wider">
            <AlertTriangle className="size-3.5" />
            <span>Out of Scope Steps (Egress / Untrusted)</span>
          </div>

          <div className="space-y-1.5">
            {outOfScopeSteps.map((step) => (
              <div
                key={step.id}
                className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3.5 py-2 text-xs text-rose-700 dark:text-rose-300 flex items-start gap-2 shadow-xs"
              >
                <span className="font-mono font-bold">{step.id}:</span>
                <span className="flex-1">{step.description}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 6. Action Buttons Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-line">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={handleAccept}
            className="flex items-center gap-1.5 rounded-xl bg-brand px-5 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 active:scale-98 transition cursor-pointer"
          >
            <span>Switch to Act</span>
            <ArrowRight className="size-3.5" />
          </button>

          <button
            type="button"
            onClick={handleEdit}
            className="flex items-center gap-1.5 rounded-xl border border-line bg-panel2 px-4 py-2 text-xs font-semibold text-muted hover:text-fg hover:border-brand/50 hover:bg-panel active:scale-98 transition cursor-pointer shadow-xs"
          >
            <Edit3 className="size-3.5" />
            <span>Edit Plan</span>
          </button>
        </div>

        {proposal.proposed_lease && (
          <div className="flex items-center gap-1.5 text-xs font-mono text-muted">
            <Clock className="size-3.5 text-muted" />
            <span>Lease valid for {proposal.proposed_lease.duration_minutes} min (Rule N5)</span>
          </div>
        )}
      </div>
    </div>
  )
}
