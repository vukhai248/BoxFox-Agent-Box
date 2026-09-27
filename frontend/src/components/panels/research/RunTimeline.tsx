/**
 * Dòng thời gian run (mockup `run-status-timeline.html`, phương án được chọn ở §4.5).
 *
 * Bảy bước cố định, nhánh nghiên cứu kèm tiến độ nguồn/toàn văn, nguồn theo mức truy cập, bao phủ
 * facet, mâu thuẫn và ngân sách. Tạm dừng/Hủy chỉ áp dụng cho RUN (không phải phiên) — đi qua
 * `PATCH /research/jobs/{id}` với `action` là `pause`/`cancel`.
 */
import { Pause, Play, Square } from 'lucide-react'
import { useT, type TKey } from '../../../i18n/context'
import { useResearchStore } from '../../../store/researchStore'
import {
  activeStepIndex,
  jobIsActive,
  jobIsSuspendable,
  jobStatusKey,
  RESEARCH_STEPS,
  runLabel,
  type ResearchJob,
  type ResearchReview,
} from '../../../lib/researchMode'
import { formatClock, formatMinutes } from './format'
import { STEP_LABEL_KEY } from './steps'

const ACCESS_KEYS: { key: TKey; match: (level: string) => boolean }[] = [
  { key: 'research.accessFulltext', match: (level) => level === 'fulltext' || level === 'full-text' },
  { key: 'research.accessAbstract', match: (level) => level === 'abstract' },
  { key: 'research.accessSnippet', match: (level) => level === 'snippet' },
  { key: 'research.accessBlocked', match: (level) => level === 'blocked' },
]

function accessCounts(job: ResearchJob): Record<string, number> {
  const counts: Record<string, number> = {}
  for (const row of job.evidence) {
    const index = ACCESS_KEYS.findIndex((entry) => entry.match(row.accessLevel))
    const key = index >= 0 ? ACCESS_KEYS[index].key : 'research.accessSnippet'
    counts[key] = (counts[key] ?? 0) + 1
  }
  return counts
}

function stepStateLabel(t: ReturnType<typeof useT>, job: ResearchJob, index: number): string {
  if (job.status === 'completed') return t('research.stepDone')
  const active = activeStepIndex(job.phase, job.status)
  if (index < active) return t('research.stepDone')
  // Run tạm dừng/dở dang KHÔNG được vẽ là "đang chạy" — cùng luật `jobStatusKey` như badge đầu panel.
  if (index === active) return t(jobIsSuspendable(job) ? jobStatusKey(job) : 'research.statusRunning')
  return ''
}

/** Vòng phản biện theo luật bảng 4.8: vòng 1 `revise`, vòng 2 là soát lại sau sửa. */
export function critiqueLabel(t: ReturnType<typeof useT>, review: ResearchReview): string {
  const label = review.verdict === 'revise' || review.verdict === 'rejected' ? t('research.reportFailedCritique') : review.verdict
  return t('research.reviewRound', { n: review.version, mode: review.mode, verdict: label })
}

export function RunTimeline({ job }: { job: ResearchJob }) {
  const t = useT()
  const updateJob = useResearchStore((s) => s.updateJob)
  const active = activeStepIndex(job.phase, job.status)
  const counts = accessCounts(job)

  return (
    <section data-testid="research-run-timeline" className="rounded-lg border border-line bg-panel p-2 text-[11px]">
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-fg">
          {t('research.run', { id: runLabel(job.researchId) })} · {t(STEP_LABEL_KEY[RESEARCH_STEPS[active]] ?? 'research.stepClarify')}
        </span>
        <span className="rounded border border-line px-1 py-px text-[10px] text-muted">
          {t('research.tierBadge', { tier: job.tier })}
        </span>
        <span className="ml-auto font-mono text-[10px] text-muted">
          {formatClock(job.usedSeconds)} / {formatClock(job.budgetSeconds)}
        </span>
        {jobIsActive(job) && (
          <div className="flex items-center gap-1">
            {/* Run tạm dừng/dở dang: nút "Tạm dừng" vô nghĩa — "Tiếp tục" là đường DUY NHẤT quay lại. */}
            {jobIsSuspendable(job) ? (
              <button
                type="button"
                data-testid="research-timeline-resume"
                onClick={() => void updateJob(job.researchId, { action: 'resume', revision: job.revision })}
                className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
              >
                <Play className="size-2.5" />
                {t('research.resumeRun')}
              </button>
            ) : (
              <button
                type="button"
                data-testid="research-timeline-pause"
                onClick={() => void updateJob(job.researchId, { action: 'pause', revision: job.revision })}
                className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
              >
                <Pause className="size-2.5" />
                {t('research.pauseRun')}
              </button>
            )}
            <button
              type="button"
              data-testid="research-timeline-cancel"
              onClick={() => void updateJob(job.researchId, { action: 'cancel', revision: job.revision })}
              className="inline-flex items-center gap-1 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
            >
              <Square className="size-2.5" />
              {t('research.cancelRun')}
            </button>
          </div>
        )}
      </header>
      <p className="mt-0.5 text-muted">
        {t('research.runSubtitle', {
          sources: job.evidence.length,
          branches: job.branches.length,
          claims: job.findings.length,
        })}
      </p>

      <ol className="mt-1.5 flex flex-wrap gap-1" data-testid="research-run-steps">
        {RESEARCH_STEPS.map((step, index) => {
          const state = stepStateLabel(t, job, index)
          return (
            <li
              key={step}
              data-step={step}
              data-active={index === active}
              className={`rounded border px-1.5 py-0.5 ${
                index === active ? 'border-brand bg-brand/10 text-brand' : index < active ? 'border-line text-fg' : 'border-line/60 text-muted'
              }`}
            >
              {t(STEP_LABEL_KEY[step])}
              {state && <span className="ml-1 text-[9px] text-muted">{state}</span>}
            </li>
          )
        })}
      </ol>

      {job.branches.length > 0 && (
        <section className="mt-1.5">
          <h4 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.branches')}</h4>
          <ul className="mt-0.5 space-y-0.5">
            {job.branches.map((branch) => (
              <li key={branch.sessionId} className="flex items-center gap-2 text-fg">
                <span className="truncate">{branch.goal || branch.questionId || branch.sessionId.slice(0, 8)}</span>
                <span className="ml-auto shrink-0 text-[10px] text-muted">
                  {branch.status === 'started' ? t('research.branchSearching') : t('research.branchDone')}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-[10px] text-muted">{t('research.branchSources', { sources: job.evidence.length, fulltext: counts['research.accessFulltext'] ?? 0 })}</p>
        </section>
      )}

      <section className="mt-1.5">
        <h4 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.sourcesByAccess')}</h4>
        <ul className="mt-0.5 flex flex-wrap gap-2" data-testid="research-access-counts">
          {ACCESS_KEYS.map((entry) => (
            <li key={entry.key} className="text-fg">
              <span className="mr-1 font-mono">{counts[entry.key] ?? 0}</span>
              <span className="text-muted">{t(entry.key)}</span>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-1.5">
        <h4 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.coverage')}</h4>
        {job.coverage.facets.length === 0 ? (
          <p className="text-muted">{t('research.coverageEmpty')}</p>
        ) : (
          <ul className="mt-0.5 space-y-0.5">
            {job.coverage.facets.map((facet) => (
              <li key={facet.id} className="flex items-center gap-2 text-fg">
                <span className="truncate">{facet.label || facet.id}</span>
                <span className="ml-auto shrink-0 text-[10px] text-muted">
                  {facet.status === 'saturated' || facet.status === 'searched'
                    ? t('research.stepDone')
                    : facet.status === 'blocked' || facet.status === 'thin'
                      ? t('research.coverageMissing')
                      : t('research.coveragePartial')}
                </span>
              </li>
            ))}
          </ul>
        )}
        {job.coverage.unexplored.length > 0 && (
          <p className="text-muted">{job.coverage.unexplored.join(' · ')}</p>
        )}
      </section>

      {job.blockedSources.length > 0 && (
        <p className="mt-1.5 text-amber-300" data-testid="research-conflicts">
          {t('research.conflicts', { count: job.blockedSources.length })}
        </p>
      )}

      <p className="mt-1.5 text-muted">
        {t('research.budgetRemaining', {
          used: formatClock(job.usedSeconds),
          budget: formatClock(job.budgetSeconds),
          remaining: formatClock(Math.max(0, job.budgetSeconds - job.usedSeconds)),
        })}
      </p>
      {job.budgetSeconds > 0 && (
        <p className="text-[10px] text-muted">
          {t('research.budgetCeiling', { tier: job.tier, minutes: formatMinutes(job.budgetSeconds) })}
        </p>
      )}

      {job.reviews.length > 0 && (
        <ul className="mt-1.5 space-y-0.5 text-[10px] text-muted">
          {job.reviews.map((review) => (
            <li key={`${review.version}-${review.mode}`}>{critiqueLabel(t, review)}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
