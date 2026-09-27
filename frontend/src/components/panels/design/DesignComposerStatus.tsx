/**
 * Khối trạng thái Design nằm TRONG ô soạn tin (P1).
 *
 * Hai trạng thái loại trừ nhau:
 * 1. server vừa trả 409 `DESIGN_EXIT_CHOICE_REQUIRED` (hoặc có lời hỏi `exit-choice` mở) ⇒ thẻ thoát,
 *    hai lựa chọn, KHÔNG mặc định (mockup `design-exit-choice.html`);
 * 2. chế độ đang bật ⇒ dải "Design đang bật · run … · bước …" + nút Tắt.
 *
 * Mọi chữ lấy từ `design.*`; component không viết cứng tiếng Việt.
 */
import { PenTool } from 'lucide-react'
import { useT, type TKey } from '../../../i18n/context'
import { selectActiveRun, useDesignStore } from '../../../store/designStore'
import { runLabel, stepForPhase } from '../../../lib/designMode'
import { STEP_LABEL_KEY } from './steps'

type T = (key: TKey, vars?: Record<string, string | number>) => string

function stepLabel(t: T, phase: string): string {
  return t(STEP_LABEL_KEY[stepForPhase(phase)])
}

/** Lời hỏi thoát chế độ — neo ngay trên ô nhập, hai lựa chọn không có mặc định. */
function ExitChoice() {
  const t = useT()
  const exitChoice = useDesignStore((s) => s.exitChoice)
  const runs = useDesignStore((s) => s.runs)
  const resolveExit = useDesignStore((s) => s.resolveExit)
  const clearExitChoice = useDesignStore((s) => s.clearExitChoice)
  if (!exitChoice) return null
  const run = runs.find((item) => item.designId === exitChoice.prompt.designId) ?? null
  // Luật "không mặc định": chỉ vẽ `background` khi server còn mời nó. Một lời hỏi cũ chỉ còn `pause`
  // thì giao diện cũng chỉ được hiện `pause`.
  const options = exitChoice.prompt.questions[0]?.options ?? []
  const showBackground = options.length === 0 || options.some((option) => option.id === 'background')
  return (
    <div
      data-testid="design-exit-choice"
      role="alertdialog"
      aria-label={t('design.exitChoiceTitle')}
      className="mb-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px]"
    >
      <p className="font-medium text-amber-300">{t('design.exitTitle')}</p>
      <p className="mt-0.5 text-muted">
        {run
          ? t('design.exitBody', { id: runLabel(run.designId), step: stepLabel(t, run.phase) })
          : exitChoice.prompt.questions[0]?.text ?? ''}
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
          onClick={clearExitChoice}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('design.exitCancel')}
        </button>
        <span className="text-muted">{t('design.exitNoDefault')}</span>
      </div>
    </div>
  )
}

/** Toàn bộ khối trạng thái trong ô soạn tin. */
export function DesignComposerStatus() {
  const t = useT()
  const mode = useDesignStore((s) => s.mode)
  const run = useDesignStore(selectActiveRun)
  const exitChoice = useDesignStore((s) => s.exitChoice)
  const setMode = useDesignStore((s) => s.setMode)
  if (exitChoice) return <ExitChoice />
  if (!mode.on) return null
  const done = run !== null && (run.status === 'completed' || run.status === 'cancelled')
  return (
    <div
      data-testid="design-mode-strip"
      className="mb-2 flex items-center gap-2 rounded-lg border border-brand/30 bg-brand/5 px-2 py-1.5 text-[11px] text-brand"
    >
      <PenTool className="size-3 shrink-0" />
      <span className="font-medium">{t('design.stripRunning')}</span>
      {run && (
        <span className="truncate font-mono text-[10px] text-muted" title={run.designId}>
          {done
            ? t('design.stripDone', { id: runLabel(run.designId) })
            : t('design.stripRun', { id: runLabel(run.designId), step: stepLabel(t, run.phase) })}
        </span>
      )}
      <button
        type="button"
        data-testid="design-mode-strip-off"
        onClick={() => void setMode(false, 'toggle')}
        className="ml-auto shrink-0 rounded border border-line px-1.5 py-0.5 text-muted transition hover:text-fg cursor-pointer"
      >
        {t('design.turnOff')}
      </button>
    </div>
  )
}
