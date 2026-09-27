/**
 * Dòng thời gian bảy bước của một run Design (P1, mockup `design-run-timeline.html`).
 *
 * Mỗi bước mang `data-step` và `data-active` để bài kiểm đọc được trạng thái mà không phải so chuỗi
 * hiển thị; run đã đóng thì luôn đứng ở bước cuối (bàn giao).
 */
import { useT } from '../../../i18n/context'
import {
  activeStepIndex,
  DESIGN_STEPS,
  runIsCancellable,
  runIsPausable,
  runIsSuspendable,
  runLabel,
  type DesignRun,
} from '../../../lib/designMode'
import { useDesignStore } from '../../../store/designStore'
import { STEP_LABEL_KEY } from './steps'

export function DesignRunTimeline({ run }: { run: DesignRun }) {
  const t = useT()
  const updateRun = useDesignStore((s) => s.updateRun)
  const index = activeStepIndex(run.phase, run.status)
  const pausable = runIsPausable(run)
  const suspendable = runIsSuspendable(run)
  const cancellable = runIsCancellable(run)
  const act = (action: 'pause' | 'resume' | 'cancel') =>
    void updateRun(run.designId, { action, revision: run.revision })
  return (
    <div
      data-testid="design-run-timeline"
      data-phase={run.phase}
      data-status={run.status}
      className="rounded-lg border border-line bg-panel2 p-2 text-[11px]"
    >
      <header className="mb-1.5 flex items-center gap-2">
        <span className="font-medium text-fg">{t('design.timelineTitle', { id: runLabel(run.designId) })}</span>
        <span className="text-muted">{t('design.timelinePhase', { step: t(STEP_LABEL_KEY[run.step]) })}</span>
      </header>
      {(run.batch || run.review) && (
        <p className="mb-1.5 flex flex-wrap items-center gap-2 text-[10px]">
          {run.batch && (
            <span data-testid="design-timeline-batch" data-status={run.batch.status} className="rounded border border-line px-1 py-0.5 text-muted">
              {t('design.timelineBatch', {
                index: run.batch.index,
                total: run.batch.total,
                status: run.batch.status,
              })}
            </span>
          )}
          {run.review && (
            <span data-testid="design-timeline-review" data-verdict={run.review.verdict} className="rounded border border-line px-1 py-0.5 text-muted">
              {t('design.timelineReview', { version: run.review.version || 'v1', verdict: run.review.verdict })}
            </span>
          )}
        </p>
      )}
      <ol className="flex flex-wrap items-center gap-1">
        {DESIGN_STEPS.map((step, position) => (
          <li
            key={step}
            data-step={step}
            data-active={position === index ? 'true' : 'false'}
            className={`rounded border px-1.5 py-0.5 ${
              position === index ? 'border-brand text-brand' : position < index ? 'border-line text-fg' : 'border-line text-muted'
            }`}
          >
            {t(STEP_LABEL_KEY[step])}
          </li>
        ))}
      </ol>
      {/* §5.8: điều khiển tác động lên RUN, không lên phiên. Run tạm dừng nói rõ nhánh và tệp đã ghi
          giữ nguyên, và hỏi "Tiếp tục run D-…?" trước khi mở lượt tiếp tục. */}
      {suspendable && (
        <p data-testid="design-run-resume-ask" className="mt-1.5 text-[10px] text-amber-300">
          {t('design.resumeAsk', { id: runLabel(run.designId) })}
        </p>
      )}
      {run.status === 'paused' && (
        <p data-testid="design-run-paused-note" className="mt-0.5 text-[10px] text-muted">
          {t('design.pausedNote')}
        </p>
      )}
      {(pausable || suspendable || cancellable) && (
        <footer className="mt-1.5 flex flex-wrap items-center gap-1 border-t border-line pt-1.5">
          {pausable && (
            <button
              type="button"
              data-testid="design-run-pause"
              onClick={() => act('pause')}
              className="rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
            >
              {t('design.runPause')}
            </button>
          )}
          {suspendable && (
            <button
              type="button"
              data-testid="design-run-resume"
              onClick={() => act('resume')}
              className="rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
            >
              {t('design.runResume')}
            </button>
          )}
          {cancellable && (
            <button
              type="button"
              data-testid="design-run-cancel"
              onClick={() => act('cancel')}
              className="rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
            >
              {t('design.runCancel')}
            </button>
          )}
        </footer>
      )}
    </div>
  )
}
