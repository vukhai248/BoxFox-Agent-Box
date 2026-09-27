/**
 * Dòng thời gian bảy bước của một run Design (P1, mockup `design-run-timeline.html`).
 *
 * Mỗi bước mang `data-step` và `data-active` để bài kiểm đọc được trạng thái mà không phải so chuỗi
 * hiển thị; run đã đóng thì luôn đứng ở bước cuối (bàn giao).
 */
import { useT } from '../../../i18n/context'
import { activeStepIndex, DESIGN_STEPS, runLabel, type DesignRun } from '../../../lib/designMode'
import { STEP_LABEL_KEY } from './steps'

export function DesignRunTimeline({ run }: { run: DesignRun }) {
  const t = useT()
  const index = activeStepIndex(run.phase, run.status)
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
    </div>
  )
}
