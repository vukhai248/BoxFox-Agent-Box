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
import { runIsClosed, runLabel, stepForPhase } from '../../../lib/designMode'
import { DesignErrorNotice } from './DesignErrorNotice'
import { DesignExitChoiceCard } from './DesignExitChoiceCard'
import { STEP_LABEL_KEY } from './steps'

type T = (key: TKey, vars?: Record<string, string | number>) => string

function stepLabel(t: T, phase: string): string {
  return t(STEP_LABEL_KEY[stepForPhase(phase)])
}

/** Toàn bộ khối trạng thái trong ô soạn tin. */
export function DesignComposerStatus() {
  const t = useT()
  const mode = useDesignStore((s) => s.mode)
  const run = useDesignStore(selectActiveRun)
  const runs = useDesignStore((s) => s.runs)
  const exitChoice = useDesignStore((s) => s.exitChoice)
  const setMode = useDesignStore((s) => s.setMode)
  // Lời hỏi thoát chỉ được vẽ khi chế độ CÒN BẬT: `mode.on === false` mà vẫn còn lời hỏi mở (ví dụ
  // payload cũ chưa kịp đóng) KHÔNG được dựng thẻ — chủ nhà đã quyết rồi thì không hỏi lại.
  if (exitChoice && mode.on) {
    const exitRun = runs.find((item) => item.designId === exitChoice.prompt.designId) ?? run
    return (
      <div className="mb-2">
        <DesignErrorNotice />
        <DesignExitChoiceCard prompt={exitChoice.prompt} run={exitRun} />
      </div>
    )
  }
  if (!mode.on) return null
  // `partial` là trạng thái ĐÓNG (cùng luật với `activeStepIndex` của dòng thời gian): run đóng dù
  // đóng dở vẫn không còn "đang ở bước" nào để hiện.
  const done = run !== null && runIsClosed(run.status)
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
