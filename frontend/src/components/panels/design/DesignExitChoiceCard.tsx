/**
 * `DesignExitChoiceCard` (P1/P5) — lời hỏi tắt chế độ Design khi run còn chạy, hai lựa chọn có hệ quả
 * rõ ràng và KHÔNG có lựa chọn mặc định (mockup `design-exit-choice.html`).
 *
 * Vì sao tách thành component riêng: cùng một thẻ được dùng ở hai chỗ — dải trong ô soạn tin
 * (`DesignComposerStatus`) và luồng hội thoại (`DesignConversationCards`) — nên chỉ có một nguồn chữ
 * và một bộ `data-testid`, không để hai nơi xử lý nhánh thoát khác nhau.
 */
import { useT } from '../../../i18n/context'
import { runLabel, type DesignPrompt, type DesignRun } from '../../../lib/designMode'
import { useDesignStore } from '../../../store/designStore'
import { stepForPhase } from '../../../lib/designMode'
import { STEP_LABEL_KEY } from './steps'

export function DesignExitChoiceCard({
  prompt,
  run = null,
  onCancel,
}: {
  prompt: DesignPrompt
  run?: DesignRun | null
  onCancel?: () => void
}) {
  const t = useT()
  const resolveExit = useDesignStore((s) => s.resolveExit)
  const clearExitChoice = useDesignStore((s) => s.clearExitChoice)
  const options = prompt.questions[0]?.options ?? []
  // Luật "không mặc định": chỉ vẽ `background` khi server còn mời nó.
  const showBackground = options.length === 0 || options.some((option) => option.id === 'background')
  const cancel = onCancel ?? clearExitChoice
  const step = run ? t(STEP_LABEL_KEY[stepForPhase(run.phase)]) : ''

  return (
    <section
      data-testid="design-exit-choice"
      data-kind={prompt.kind}
      role="alertdialog"
      aria-label={t('design.exitChoiceTitle')}
      className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px]"
    >
      <p className="font-medium text-amber-700 dark:text-amber-300">{t('design.exitTitle')}</p>
      <p className="mt-0.5 text-muted">
        {run
          ? t('design.exitBody', { id: runLabel(run.designId), step })
          : prompt.questions[0]?.text ?? ''}
      </p>
      <div className="mt-1.5 space-y-1">
        <button
          type="button"
          data-testid="design-exit-pause"
          onClick={() => void resolveExit('pause')}
          className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand cursor-pointer"
        >
          <span className="font-medium text-fg">{t('design.exitPause')}</span>
          <span className="ml-1 text-muted">{t('design.exitPauseHint')}</span>
        </button>
        {showBackground && (
          <button
            type="button"
            data-testid="design-exit-background"
            onClick={() => void resolveExit('background')}
            className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand cursor-pointer"
          >
            <span className="font-medium text-fg">{t('design.exitBackground')}</span>
            <span className="ml-1 text-muted">{t('design.exitBackgroundHint')}</span>
          </button>
        )}
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-2">
        <button
          type="button"
          data-testid="design-exit-cancel"
          onClick={cancel}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('design.exitCancel')}
        </button>
        <span className="text-muted">{t('design.exitNoDefault')}</span>
      </div>
    </section>
  )
}
