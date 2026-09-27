/**
 * Tab Research (mockup `research-panel.html`) — sáu mục: Phạm vi · Kế hoạch & bao phủ · Nguồn ·
 * Claim & bằng chứng · Phản biện · Báo cáo.
 *
 * Vòng hỏi 5000 ms đã bị BỎ (bảng 4.8/§5.12): dữ liệu đến từ `researchStore`, và store chỉ gọi
 * mạng khi có sự kiện `research_*` mới trên luồng sự kiện phiên (xem `useResearchSync`).
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useT, type TKey } from '../../i18n/context'
import { useResearchStore } from '../../store/researchStore'
import { useUiStore } from '../../store/uiStore'
import {
  activeJob,
  jobIsActive,
  jobIsRunningInBackground,
  jobIsSuspendable,
  jobStatusKey,
  jobStatusTone,
  runLabel,
  STATUS_TONE_CLASS,
  stepForPhase,
  type ResearchEvidenceRow,
  type ResearchJob,
} from '../../lib/researchMode'
import { formatClock } from './research/format'
import { ResearchPromptCard } from './research/ResearchPromptCard'
import { ResearchReportCard } from './research/ResearchReportCard'
import { RunTimeline, critiqueLabel } from './research/RunTimeline'
import { ScopeCard } from './research/ScopeCard'
import { STEP_LABEL_KEY } from './research/steps'

type TabKey = 'scope' | 'plan' | 'sources' | 'claims' | 'review' | 'report'

const TAB_LABEL: Record<TabKey, TKey> = {
  scope: 'research.tabScope',
  plan: 'research.tabPlan',
  sources: 'research.tabSources',
  claims: 'research.tabClaims',
  review: 'research.tabReview',
  report: 'research.tabReport',
}

const TABS: TabKey[] = ['scope', 'plan', 'sources', 'claims', 'review', 'report']

const RELATION_LABEL: Record<string, TKey> = {
  supports: 'research.relationSupports',
  contradicts: 'research.relationContradicts',
  context: 'research.relationContext',
  insufficient: 'research.relationInsufficient',
}

const ACCESS_LABEL: Record<string, TKey> = {
  fulltext: 'research.accessFulltext',
  abstract: 'research.accessAbstract',
  snippet: 'research.accessSnippet',
  blocked: 'research.accessBlocked',
}

/** Mức truy cập canonical — server có thể gửi `full-text` hoặc `fulltext`; chuẩn hoá một lần. */
function accessLevel(level: string): 'fulltext' | 'abstract' | 'snippet' | 'blocked' {
  if (level === 'fulltext' || level === 'full-text') return 'fulltext'
  if (level === 'abstract') return 'abstract'
  if (level === 'blocked') return 'blocked'
  return 'snippet'
}

function accessKey(level: string): TKey {
  return ACCESS_LABEL[accessLevel(level)]
}

/** Nhóm hàng bằng chứng theo mức truy cập — "Nguồn theo mức truy cập" của mockup. */
function groupByAccess(rows: ResearchEvidenceRow[]): { key: TKey; rows: ResearchEvidenceRow[] }[] {
  const buckets = new Map<TKey, ResearchEvidenceRow[]>()
  for (const row of rows) {
    const key = accessKey(row.accessLevel)
    const bucket = buckets.get(key) ?? []
    bucket.push(row)
    buckets.set(key, bucket)
  }
  return [...buckets.entries()].map(([key, value]) => ({ key, rows: value }))
}

function EvidenceRow({ row }: { row: ResearchEvidenceRow }) {
  const t = useT()
  const isUrl = /^https?:\/\//i.test(row.url)
  return (
    <li data-testid="research-evidence-row" className="rounded border border-line p-1.5">
      <div className="flex items-start gap-1.5">
        <span className="font-mono text-[10px] text-muted">{row.rowId}</span>
        <span className="min-w-0 flex-1 text-fg">{row.claim}</span>
        <span className="shrink-0 rounded border border-line px-1 text-[10px] text-muted">
          {t(accessKey(row.accessLevel))}
        </span>
      </div>
      <p className="mt-0.5 text-[10px] text-muted">
        {row.relation ? t(RELATION_LABEL[row.relation] ?? 'research.relationUnknown') : t('research.relationUnknown')}
        {row.publishedAt ? ` · ${row.publishedAt}` : ''}
        {row.originCluster ? ` · ${t('research.evidenceOrigin')} ${row.originCluster}` : ''}
      </p>
      {row.excerpt && <p className="mt-0.5 text-muted">{row.excerpt}</p>}
      {isUrl && (
        <a href={row.url} target="_blank" rel="noreferrer" className="text-[10px] text-brand hover:underline">
          {row.url}
        </a>
      )}
      {row.confidence && (
        <p className="text-[10px] text-muted">{t('research.confidenceLabel', { level: t(`research.confidence${row.confidence === 'high' ? 'High' : row.confidence === 'low' ? 'Low' : 'Medium'}` as TKey) })}</p>
      )}
    </li>
  )
}

function JobHeader({ job }: { job: ResearchJob }) {
  const t = useT()
  const updateJob = useResearchStore((s) => s.updateJob)
  const suspendable = jobIsSuspendable(job)
  return (
    <header className="mb-2 rounded-lg border border-line bg-panel p-2">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-fg">{job.goal || t('research.name')}</h2>
        <span
          data-testid="research-status-badge"
          data-status={job.status}
          className={`rounded px-1 py-px text-[10px] font-medium ${STATUS_TONE_CLASS[jobStatusTone(job)]}`}
        >
          {t(jobStatusKey(job))}
        </span>
        <span className="ml-auto font-mono text-[10px] text-muted">
          {formatClock(job.usedSeconds)} / {formatClock(job.budgetSeconds)}
        </span>
      </div>
      <p className="mt-0.5 text-[11px] text-muted">
        {t('research.stripRun', { id: runLabel(job.researchId), step: t(STEP_LABEL_KEY[stepForPhase(job.phase)]) })} ·{' '}
        {t('research.runSubtitle', { sources: job.evidence.length, branches: job.branches.length, claims: job.findings.length })}
      </p>
      {jobIsActive(job) && (
        <div className="mt-1 flex gap-1.5">
          {/* Run tạm dừng/dở dang: nút "Tạm dừng" vô nghĩa và nút "Tiếp tục" là đường DUY NHẤT quay lại
              (`PATCH … {action:'resume'}`); Huỷ vẫn còn. */}
          {suspendable ? (
            <button
              type="button"
              data-testid="research-panel-resume"
              onClick={() => void updateJob(job.researchId, { action: 'resume', revision: job.revision })}
              className="rounded border border-brand/40 bg-brand/10 px-1.5 py-0.5 text-[11px] text-brand transition hover:bg-brand/20 cursor-pointer"
            >
              {t('research.resumeRun')}
            </button>
          ) : (
            <button
              type="button"
              data-testid="research-panel-pause"
              onClick={() => void updateJob(job.researchId, { action: 'pause', revision: job.revision })}
              className="rounded border border-line px-1.5 py-0.5 text-[11px] text-muted transition hover:text-fg cursor-pointer"
            >
              {t('research.pauseRun')}
            </button>
          )}
          <button
            type="button"
            data-testid="research-panel-cancel"
            onClick={() => void updateJob(job.researchId, { action: 'cancel', revision: job.revision })}
            className="rounded border border-line px-1.5 py-0.5 text-[11px] text-muted transition hover:text-fg cursor-pointer"
          >
            {t('research.cancelRun')}
          </button>
          <span className="text-[10px] text-muted">{t('research.scopeOnly')}</span>
        </div>
      )}
    </header>
  )
}

export function ResearchPanel() {
  const t = useT()
  const jobs = useResearchStore((s) => s.jobs)
  const detail = useResearchStore((s) => s.detail)
  const detailId = useResearchStore((s) => s.detailId)
  const mode = useResearchStore((s) => s.mode)
  const error = useResearchStore((s) => s.error)
  const refreshDetail = useResearchStore((s) => s.refreshDetail)
  const [tab, setTab] = useState<TabKey>('scope')
  const [accessFilter, setAccessFilter] = useState('')

  // F4: thẻ báo cáo của một run (kể cả run chạy nền) mở tab này kèm `researchId`. Không đọc đích thì
  // panel có thể hiện một run KHÁC (run tiền cảnh). Chỉ áp dụng MỘT lần cho mỗi đích để người dùng
  // vẫn tự chuyển run được sau đó.
  const researchTarget = useUiStore((s) => s.tabIntentTargets.research)
  const targetId = typeof researchTarget?.researchId === 'string' ? researchTarget.researchId : null
  const appliedTargetRef = useRef<string | null>(null)
  useEffect(() => {
    if (!targetId || appliedTargetRef.current === targetId) return
    appliedTargetRef.current = targetId
    void refreshDetail(targetId)
  }, [targetId, refreshDetail])

  const job = useMemo(() => {
    const fromDetail = detail && detail.researchId === detailId ? detail : null
    return fromDetail ?? activeJob(jobs, mode.activeRunId)
  }, [detail, detailId, jobs, mode.activeRunId])

  const openPrompt = useMemo(() => {
    if (!job) return null
    return job.prompts.find((prompt) => prompt.status === 'open' && prompt.kind !== 'exit-choice') ?? null
  }, [job])

  if (!job) {
    return (
      <section className="h-full overflow-y-auto p-4 text-sm text-fg" aria-label={t('research.name')}>
        <p className="text-muted">{t('research.noJob')}</p>
        {error && <p className="mt-2 rounded bg-red-500/10 p-2 text-red-400" role="alert">{error}</p>}
      </section>
    )
  }

  const filtered = accessFilter ? job.evidence.filter((row) => accessLevel(row.accessLevel) === accessFilter) : job.evidence
  const groups = groupByAccess(filtered)
  const relations = job.evidence.reduce(
    (acc, row) => {
      if (row.relation === 'supports') acc.supports += 1
      else if (row.relation === 'contradicts') acc.contradicts += 1
      else if (row.relation === 'shared') acc.shared += 1
      return acc
    },
    { supports: 0, contradicts: 0, shared: 0 },
  )

  return (
    <section className="flex h-full flex-col overflow-hidden text-sm text-fg" aria-label={t('research.name')}>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {error && <p className="mb-2 rounded bg-red-500/10 p-2 text-red-400" role="alert">{error}</p>}
        <JobHeader job={job} />
        {/* Table 4.8 dòng 9: run chạy nền vẫn phải có chỗ nói ra ở TAB Research —
            nút Research và dải trong composer đã có, đây là chỗ thứ ba. */}
        {jobIsRunningInBackground(job) && !mode.on && (
          <p
            data-testid="research-background-line"
            className="mb-2 rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-300"
          >
            {t('research.backgroundRunning')}
          </p>
        )}

        <nav className="mb-2 flex flex-wrap gap-1" role="tablist" aria-label={t('research.name')}>
          {TABS.map((key) => (
            <button
              key={key}
              type="button"
              role="tab"
              data-testid={`research-tab-${key}`}
              aria-selected={tab === key}
              onClick={() => {
                setTab(key)
                void refreshDetail(job.researchId)
              }}
              className={`rounded border px-2 py-0.5 text-[11px] transition cursor-pointer ${
                tab === key ? 'border-brand bg-brand/10 text-brand' : 'border-line text-muted hover:text-fg'
              }`}
            >
              {t(TAB_LABEL[key])}
              {key === 'sources' && job.evidence.length > 0 && <span className="ml-1">{job.evidence.length}</span>}
              {key === 'claims' && job.findings.length > 0 && <span className="ml-1">{job.findings.length}</span>}
              {key === 'review' && job.prompts.some((prompt) => prompt.status === 'open') && (
                <span className="ml-1">({job.prompts.filter((prompt) => prompt.status === 'open').length})</span>
              )}
              {key === 'report' && job.dossier && <span className="ml-1">{t('research.reportVersion', { n: job.dossier.version })}</span>}
            </button>
          ))}
        </nav>

        {tab === 'scope' && (
          <div className="space-y-2">
            {job.scope ? (
              <ScopeCard job={job} scope={job.scope} prompt={openPrompt} />
            ) : (
              <p className="text-muted">{t('research.planEmpty')}</p>
            )}
            <RunTimeline job={job} />
          </div>
        )}

        {tab === 'plan' && (
          <div className="space-y-2 text-[11px]">
            <section className="rounded-lg border border-line bg-panel p-2">
              <h3 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.planQuestions')}</h3>
              {job.questions.length === 0 ? (
                <p className="text-muted">{t('research.planEmpty')}</p>
              ) : (
                <ul className="mt-0.5 space-y-1">
                  {job.questions.map((question) => (
                    <li key={question.id} className="rounded border border-line p-1.5">
                      <div className="flex items-start gap-2">
                        <span className="min-w-0 flex-1 text-fg">{question.text}</span>
                        <span className="shrink-0 text-[10px] text-muted">{question.status} · {question.importance}</span>
                      </div>
                      {question.note && <p className="text-muted">{question.note}</p>}
                      <div className="mt-0.5 flex gap-2 text-[10px]">
                        <button
                          type="button"
                          onClick={() => void useResearchStore.getState().updateJob(job.researchId, { action: 'prioritize', questionId: question.id, importance: 'high', revision: job.revision })}
                          className="text-brand hover:underline cursor-pointer"
                        >
                          {t('research.edit')}
                        </button>
                        <button
                          type="button"
                          onClick={() => void useResearchStore.getState().updateJob(job.researchId, { action: 'skip', questionId: question.id, revision: job.revision })}
                          className="text-muted hover:underline cursor-pointer"
                        >
                          {t('research.hide')}
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="rounded-lg border border-line bg-panel p-2">
              <h3 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.planFacets')}</h3>
              {job.coverage.facets.length === 0 ? (
                <p className="text-muted">{t('research.coverageEmpty')}</p>
              ) : (
                <ul className="mt-0.5 space-y-0.5">
                  {job.coverage.facets.map((facet) => (
                    <li key={facet.id} className="flex items-center gap-2 text-fg">
                      <span className="truncate">{facet.label || facet.id}</span>
                      <span className="ml-auto shrink-0 text-[10px] text-muted">{facet.status} · {facet.evidenceCount}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            {job.methods.length > 0 && (
              <section className="rounded-lg border border-line bg-panel p-2">
                <h3 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.planMethods')}</h3>
                <p className="text-fg">{job.methods.join(' · ')}</p>
              </section>
            )}
          </div>
        )}

        {tab === 'sources' && (
          <div className="space-y-2 text-[11px]">
            {job.evidence.length === 0 ? (
              <p className="text-muted">{t('research.sourcesEmpty')}</p>
            ) : (
              groups.map((group) => (
                <section key={group.key} className="rounded-lg border border-line bg-panel p-2">
                  <h3 className="text-[10px] font-medium tracking-wide text-muted uppercase">
                    {t(group.key)} · {group.rows.length}
                  </h3>
                  <ul className="mt-0.5 space-y-1">
                    {group.rows.map((row) => (
                      <EvidenceRow key={row.rowId} row={row} />
                    ))}
                  </ul>
                </section>
              ))
            )}
            {job.blockedSources.length > 0 && (
              <section className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2">
                <h3 className="text-[10px] font-medium tracking-wide text-amber-300 uppercase">{t('research.accessBlocked')}</h3>
                <ul className="mt-0.5 space-y-0.5">
                  {job.blockedSources.map((source, index) => (
                    <li key={`${source.url}-${index}`} className="text-fg">
                      <a href={source.url} target="_blank" rel="noreferrer" className="text-brand hover:underline">{source.url}</a>
                      {source.impact && <span className="ml-1 text-muted">{source.impact}</span>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}

        {tab === 'claims' && (
          <div className="space-y-2 text-[11px]">
            <div className="flex flex-wrap items-center gap-2">
              <label className="text-muted" htmlFor="research-access-filter">{t('research.evidenceFilter')}</label>
              <select
                id="research-access-filter"
                value={accessFilter}
                onChange={(event) => setAccessFilter(event.target.value)}
                className="rounded border border-line bg-bg px-1 py-0.5 text-fg"
              >
                <option value="">{t('research.evidenceFilter')}</option>
                <option value="fulltext">{t('research.accessFulltext')}</option>
                <option value="abstract">{t('research.accessAbstract')}</option>
                <option value="snippet">{t('research.accessSnippet')}</option>
                <option value="blocked">{t('research.accessBlocked')}</option>
              </select>
              <span className="text-muted">
                {t('research.evidenceRelation', { supports: relations.supports, contradicts: relations.contradicts, shared: relations.shared })}
              </span>
            </div>
            {job.findings.length > 0 && (
              <section className="rounded-lg border border-line bg-panel p-2">
                <h3 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.reportConclusions')}</h3>
                <ol className="mt-0.5 space-y-0.5">
                  {job.findings.map((finding, index) => (
                    <li key={`${finding}-${index}`} className="text-fg">{finding}</li>
                  ))}
                </ol>
              </section>
            )}
            {filtered.length === 0 ? (
              <p className="text-muted">{t('research.evidenceEmpty')}</p>
            ) : (
              <ul className="space-y-1">
                {filtered.map((row) => (
                  <EvidenceRow key={row.rowId} row={row} />
                ))}
              </ul>
            )}
          </div>
        )}

        {tab === 'review' && (
          <div className="space-y-2 text-[11px]">
            {openPrompt && <ResearchPromptCard prompt={openPrompt} />}
            <section className="rounded-lg border border-line bg-panel p-2">
              <h3 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.reportReviews')}</h3>
              {job.reviews.length === 0 ? (
                <p className="text-muted">{t('research.reviewEmpty')}</p>
              ) : (
                <ul className="mt-0.5 space-y-0.5">
                  {job.reviews.map((review) => (
                    <li key={`${review.version}-${review.mode}`} className="text-fg">{critiqueLabel(t, review)}</li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        )}

        {tab === 'report' && (
          <div className="space-y-2">
            {job.dossier ? (
              <ResearchReportCard job={job} inBackground={mode.on === false && job.background} />
            ) : (
              <p className="text-muted">{t('research.reportEmpty')}</p>
            )}
          </div>
        )}
      </div>
    </section>
  )
}
