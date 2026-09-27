/**
 * `DesignPromptCard` (P1) — lời hỏi NHIỀU CÂU của phỏng vấn thiết kế, không chặn lượt, trả lời trong
 * MỘT lần gọi (`POST /design/prompts/{id}/answer`).
 *
 * Tối đa ba câu mỗi vòng (`DESIGN_INTERVIEW_MAX_QUESTIONS`); mỗi câu 2–5 lựa chọn kèm ô trả lời tự do.
 * Lời hỏi `exit-choice` KHÔNG đi qua đây: nó neo vào nút Design và do `DesignComposerStatus` vẽ — một
 * chỗ duy nhất, để nhánh thoát không bị hai nơi xử lý khác nhau (cùng luật với Research).
 */
import { useState } from 'react'
import { useT } from '../../../i18n/context'
import { useDesignStore } from '../../../store/designStore'
import type { DesignPrompt } from '../../../lib/designMode'

type AnswerDraft = { optionId?: string; text?: string }

export function DesignPromptCard({ prompt }: { prompt: DesignPrompt }) {
  const t = useT()
  const answerPrompt = useDesignStore((s) => s.answerPrompt)
  const [drafts, setDrafts] = useState<Record<string, AnswerDraft>>({})
  const [busy, setBusy] = useState(false)
  const answered = prompt.status === 'answered'

  // Chỉ câu `required` mới chặn; câu còn lại trả lời hay không đều được. Mặc định khi người dùng đã
  // gõ chữ: lựa chọn đứng trước, vì giới từ lựa chọn là thứ server ghi vào brief.
  const blocking = prompt.questions.filter((question) => question.required)
  const unanswered = blocking.filter((question) => {
    const draft = drafts[question.id]
    return !draft || (!draft.optionId && !(draft.text ?? '').trim())
  })
  const canSubmit = !answered && prompt.questions.length > 0 && unanswered.length === 0

  function setDraft(questionId: string, patch: AnswerDraft) {
    setDrafts((current) => ({ ...current, [questionId]: { ...current[questionId], ...patch } }))
  }

  async function submit(start: boolean) {
    setBusy(true)
    const answers = prompt.questions
      .map((question) => {
        const draft = drafts[question.id]
        if (!draft) return null
        const text = (draft.text ?? '').trim()
        if (!draft.optionId && !text) return null
        return {
          questionId: question.id,
          ...(draft.optionId ? { optionId: draft.optionId } : {}),
          ...(text ? { text } : {}),
        }
      })
      .filter((item): item is { questionId: string; optionId?: string; text?: string } => item !== null)
    await answerPrompt(prompt.promptId, { revision: prompt.revision, answers, start })
    setBusy(false)
  }

  return (
    <section
      data-testid="design-prompt-card"
      data-kind={prompt.kind}
      data-status={prompt.status}
      className="rounded-lg border border-line bg-panel2 p-2 text-[11px]"
    >
      <header className="flex items-center justify-between gap-2">
        <span className="font-medium text-fg">
          {prompt.kind === 'interview' ? t('design.promptKindInterview') : t('design.promptKindScope')}
        </span>
        <span className="text-muted">{answered ? t('design.promptAnswered') : t('design.promptOpen')}</span>
      </header>
      {prompt.questions.length === 0 ? (
        <p className="mt-1 text-muted">{t('design.promptNoQuestions')}</p>
      ) : (
        <ol className="mt-1.5 space-y-2">
          {prompt.questions.map((question) => {
            const draft = drafts[question.id] ?? {}
            return (
              <li key={question.id} data-question={question.id}>
                <p className="text-fg">{question.text}</p>
                {question.why && (
                  <p className="text-muted">
                    {t('design.promptWhy')} {question.why}
                  </p>
                )}
                <div className="mt-1 flex flex-wrap gap-1">
                  {question.options.map((option) => (
                    <button
                      key={option.id}
                      type="button"
                      data-option={option.id}
                      aria-pressed={draft.optionId === option.id}
                      disabled={answered || busy}
                      onClick={() => setDraft(question.id, { optionId: option.id })}
                      className={`rounded border px-1.5 py-0.5 transition disabled:opacity-60 cursor-pointer ${
                        draft.optionId === option.id ? 'border-brand text-brand' : 'border-line text-fg hover:border-brand'
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
                {question.allowFreeText && (
                  <input
                    type="text"
                    data-answer-input={question.id}
                    value={draft.text ?? ''}
                    disabled={answered || busy}
                    placeholder={t('design.promptAnswerPlaceholder')}
                    onChange={(event) => setDraft(question.id, { text: event.target.value })}
                    className="mt-1 w-full rounded border border-line bg-panel px-1.5 py-0.5 text-[11px] text-fg outline-hidden focus:border-brand disabled:opacity-60"
                  />
                )}
              </li>
            )
          })}
        </ol>
      )}
      {!answered && prompt.questions.length > 0 && (
        <div className="mt-1.5 flex gap-2">
          <button
            type="button"
            data-testid="design-prompt-submit"
            disabled={!canSubmit || busy}
            onClick={() => void submit(false)}
            className="rounded border border-brand bg-brand/10 px-2 py-0.5 text-brand transition disabled:opacity-50 cursor-pointer"
          >
            {t('design.promptSubmit')}
          </button>
          <button
            type="button"
            data-testid="design-prompt-start"
            disabled={!canSubmit || busy}
            onClick={() => void submit(true)}
            className="rounded border border-line bg-panel px-2 py-0.5 text-fg transition disabled:opacity-50 cursor-pointer"
          >
            {t('design.promptSubmitStart')}
          </button>
        </div>
      )}
    </section>
  )
}
