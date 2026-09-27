/**
 * `DesignOutOfScopeCard` (P5) — yêu cầu rơi NGOÀI phạm vi thiết kế: hai lối ra rõ ràng, không có lối
 * nào mặc định (cùng luật với thẻ thoát chế độ).
 *
 * - "Tạm thoát để main xử lý": trả lời lời hỏi rồi để lượt main tiếp nhận yêu cầu.
 * - "Giữ trong design": ghi nhận yêu cầu như một phần phạm vi của run.
 */
import { useT } from '../../../i18n/context'
import { runLabel, type DesignPrompt, type DesignRun } from '../../../lib/designMode'
import { useDesignStore } from '../../../store/designStore'

export function DesignOutOfScopeCard({ run, prompt }: { run: DesignRun; prompt: DesignPrompt }) {
  const t = useT()
  const answerPrompt = useDesignStore((s) => s.answerPrompt)
  const question = prompt.questions[0]

  function answer(optionId: string) {
    if (!question) return
    void answerPrompt(prompt.promptId, {
      revision: prompt.revision,
      answers: [{ questionId: question.id, optionId }],
    })
  }

  return (
    <section
      data-testid="design-out-of-scope"
      data-kind={prompt.kind}
      className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px]"
    >
      <p className="font-medium text-amber-300">
        {t('design.oosTitle')}
        <span className="ml-1 font-mono text-[10px] text-muted">{runLabel(run.designId)}</span>
      </p>
      <p className="mt-0.5 text-muted">{question?.text || t('design.oosBody')}</p>
      <div className="mt-1.5 space-y-1">
        <button
          type="button"
          data-testid="design-out-of-scope-exit"
          onClick={() => answer('exit')}
          className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand cursor-pointer"
        >
          <span className="font-medium text-fg">{t('design.oosExit')}</span>
          <span className="ml-1 text-muted">{t('design.oosExitHint')}</span>
        </button>
        <button
          type="button"
          data-testid="design-out-of-scope-keep"
          onClick={() => answer('keep')}
          className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand cursor-pointer"
        >
          <span className="font-medium text-fg">{t('design.oosKeep')}</span>
          <span className="ml-1 text-muted">{t('design.oosKeepHint')}</span>
        </button>
      </div>
    </section>
  )
}
