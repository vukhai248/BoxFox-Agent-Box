/**
 * Tab Design (P5) — vỏ gom năm ngăn của một run: Canvas · Brief · Nhánh · Soát · Báo cáo
 * (kế hoạch §8 P5, mockup `design-run-timeline.html`, `design-canvas-live-draw.html`,
 * `design-diff-batch-card.html`, `design-handoff-report-card.html`).
 *
 * Ngăn mặc định là Canvas nên mở tab Design vẫn thấy đúng cảnh như trước; bốn ngăn còn lại chỉ đọc
 * dữ liệu ĐÃ có trong `designStore` và hiện "chưa có" khi backend chưa gửi — không dựng số liệu giả.
 * Run đang xem do `selectActiveRun` chọn (run đang mở, hoặc run chưa đóng đầu tiên) — panel không
 * thêm API store mới.
 */
import { useState } from 'react'
import { useT, type TKey } from '../../../i18n/context'
import { runLabel, type DesignRun } from '../../../lib/designMode'
import { selectActiveRun, useDesignStore } from '../../../store/designStore'
import { DesignCanvasPanel } from '../DesignCanvasPanel'
import { DesignBatchDiffCard } from './DesignBatchDiffCard'
import { DesignBriefCard } from './DesignBriefCard'
import { DesignErrorNotice } from './DesignErrorNotice'
import { DesignHandoffCard } from './DesignHandoffCard'
import { DesignRunTimeline } from './DesignRunTimeline'

type DesignTabId = 'canvas' | 'brief' | 'branch' | 'review' | 'report'

/** Thứ tự ngăn — Canvas trước vì đó là việc đang diễn ra, phần còn lại là giấy tờ của run. */
const DESIGN_TABS: DesignTabId[] = ['canvas', 'brief', 'branch', 'review', 'report']

const TAB_LABEL_KEY: Record<DesignTabId, TKey> = {
  canvas: 'design.panelTabCanvas',
  brief: 'design.panelTabBrief',
  branch: 'design.panelTabBranch',
  review: 'design.panelTabReview',
  report: 'design.panelTabReport',
}

function ReviewPane({ run }: { run: DesignRun }) {
  const t = useT()
  const review = run.review
  if (!review) {
    return (
      <p data-testid="design-panel-review-empty" className="text-muted">
        {t('design.reviewEmpty')}
      </p>
    )
  }
  return (
    <section data-testid="design-panel-review" data-verdict={review.verdict} className="space-y-1">
      <header className="flex items-center gap-2">
        <span className="font-medium text-fg">{t('design.reviewTitle')}</span>
        <span className="text-muted">{t('design.reviewVersion', { version: review.version || 'v1' })}</span>
        <span className={review.verdict === 'passed' ? 'text-brand' : 'text-amber-300'}>
          {review.verdict === 'passed' ? t('design.handoffVerdictPassed') : t('design.handoffVerdictChanges')}
        </span>
      </header>
      {review.summary && <p className="text-fg">{review.summary}</p>}
    </section>
  )
}

export function DesignPanel() {
  const t = useT()
  const run = useDesignStore(selectActiveRun)
  const runs = useDesignStore((s) => s.runs)
  const report = useDesignStore((s) => (run ? s.reports[run.designId] ?? null : null))
  const [tab, setTab] = useState<DesignTabId>('canvas')

  const strip = (
    <div
      role="tablist"
      aria-label={t('design.panelTabsAria')}
      data-testid="design-panel-tabs"
      className="flex shrink-0 items-center gap-1 overflow-hidden border-b border-line px-1.5 py-1 text-[11px]"
    >
      {DESIGN_TABS.map((id) => (
        <button
          key={id}
          type="button"
          role="tab"
          aria-selected={tab === id}
          data-testid={`design-panel-tab-${id}`}
          onClick={() => setTab(id)}
          className={`rounded px-1.5 py-0.5 transition cursor-pointer ${
            tab === id ? 'border border-line bg-panel2 text-fg' : 'border border-transparent text-muted hover:text-fg'
          }`}
        >
          {t(TAB_LABEL_KEY[id])}
        </button>
      ))}
      {run && (
        <span data-testid="design-panel-run" className="ml-auto truncate pl-2 font-mono text-[10px] text-muted">
          {runLabel(run.designId)} · {run.status}
          {runs.length > 1 ? ` (${runs.length})` : ''}
        </span>
      )}
    </div>
  )

  if (tab === 'canvas') {
    return (
      <div data-testid="design-panel" data-tab="canvas" className="flex h-full w-full flex-col overflow-hidden">
        {strip}
        <div className="min-h-0 flex-1">
          <DesignCanvasPanel />
        </div>
      </div>
    )
  }

  return (
    <div
      data-testid="design-panel"
      data-tab={tab}
      className="flex h-full w-full flex-col overflow-hidden bg-bg font-sans"
    >
      {strip}
      <div className="min-h-0 flex-1 space-y-2 overflow-auto p-2 text-[11px]">
        <DesignErrorNotice />
        {!run ? (
          <p data-testid="design-panel-empty" className="text-muted">
            {t('design.panelEmpty')}
          </p>
        ) : tab === 'brief' ? (
          <>
            <DesignBriefCard run={run} />
            <DesignRunTimeline run={run} />
          </>
        ) : tab === 'branch' ? (
          <>
            <DesignBatchDiffCard designId={run.designId} batch={run.batch} revision={run.revision} />
            <DesignRunTimeline run={run} />
          </>
        ) : tab === 'review' ? (
          <ReviewPane run={run} />
        ) : (
          <DesignHandoffCard run={run} report={report} />
        )}
      </div>
    </div>
  )
}
