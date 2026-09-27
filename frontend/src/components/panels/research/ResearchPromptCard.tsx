/**
 * `ResearchPromptCard` (kế hoạch §5.12) — lời hỏi NHIỀU CÂU, không chặn lượt, trả lời trong MỘT lần gọi.
 *
 * Vì sao không dùng `DecisionCard`: `ask_user` chỉ có một câu, chặn lượt, hết hạn 300 s — quá ngắn cho
 * phỏng vấn. Lời hỏi ở đây là dữ liệu bền trong `research_jobs.state.prompts[]`, trả lời qua
 * `POST /research/prompts/{id}/answer`, và mọi câu đi trong cùng một lần gọi.
 *
 * `kind`-aware: `exit-choice` là câu do SERVER tạo khi tắt mode (hai lựa chọn, không mặc định);
 * `interview`/`scope-change` là phỏng vấn thích ứng; `out-of-scope` và `budget` dùng cùng khung.
 */
import { useState } from 'react'
import { Check, X } from 'lucide-react'
import { useT, type TKey } from '../../../i18n/context'
import { useResearchStore } from '../../../store/researchStore'
import type { ResearchPrompt, ResearchPromptKind } from '../../../lib/researchMode'

const TITLE_KEY: Record<ResearchPromptKind, TKey> = {
  interview: 'research.promptInterview',
  'scope-change': 'research.promptScopeChange',
  'exit-choice': 'research.promptExit',
  'out-of-scope': 'research.promptOutOfScope',
  budget: 'research.promptBudget',
}

type AnswerDraft = { optionId?: string; text?: string }

/**
 * Lời hỏi nhiều câu thông thường (phỏng vấn / đổi phạm vi / ngoài phạm vi / ngân sách).
 *
 * Lời hỏi `exit-choice` KHÔNG đi qua đây: nó neo vào nút Research và do `ResearchComposerStatus`
 * (`ExitPrompt`) vẽ — một chỗ duy nhất, để nhánh thoát không bị hai nơi xử lý khác nhau.
 */
export function ResearchPromptCard({ prompt }: { prompt: ResearchPrompt }) {
  const t = useT()
  const answerPrompt = useResearchStore((s) => s.answerPrompt)
  const dismissPrompt = useResearchStore((s) => s.dismissPrompt)
  const [drafts, setDrafts] = useState<Record<string, AnswerDraft>>({})
  const [busy, setBusy] = useState(false)

  const blocking = prompt.questions.filter((question) => question.required)
  const unanswered = blocking.filter((question) => {
    const draft = drafts[question.id]
    return !draft || (!draft.optionId && !(draft.text ?? '').trim())
  })
  const canStart = unanswered.length === 0

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
        return { questionId: question.id, ...(draft.optionId ? { optionId: draft.optionId } : {}), ...(text ? { text } : {}) }
      })
      .filter((item): item is { questionId: string; optionId?: string; text?: string } => item !== null)
    await answerPrompt(prompt.promptId, { revision: prompt.revision, answers, start, approveBudget: start })
    setBusy(false)
  }

  // `exit-choice` do `ResearchComposerStatus.ExitPrompt` vẽ (một chỗ duy nhất). Tới đây thì chỉ còn
  // các loại lời hỏi nhiều câu; một `exit-choice` lọt vào cũng render như lời hỏi thường, không nhánh chết.
  return (
    <section
      data-testid="research-prompt-card"
      data-kind={prompt.kind}
      className="rounded-lg border border-line bg-panel2 p-2 text-[11px]"
    >
      <header className="flex items-center justify-between gap-2">
        <span className="font-medium text-fg">{t(TITLE_KEY[prompt.kind], { count: prompt.questions.length })}</span>
        <button
          type="button"
          data-testid="research-prompt-dismiss"
          aria-label={t('research.promptDismiss')}
          onClick={() => void dismissPrompt(prompt.promptId)}
          className="text-muted transition hover:text-fg cursor-pointer"
        >
          <X className="size-3" />
        </button>
      </header>

      <ol className="mt-1.5 space-y-2">
        {prompt.questions.map((question) => (
          <li key={question.id} data-testid="research-prompt-question">
            <p className="text-fg">
              {question.text}
              {question.required && <span className="ml-1 text-amber-400">{t('research.promptRequired')}</span>}
            </p>
            {question.why && <p className="text-muted">{question.why}</p>}
            {question.affects.length > 0 && (
              <p className="text-muted">{t('research.promptAffects', { list: question.affects.join(', ') })}</p>
            )}
            <div className="mt-1 flex flex-wrap gap-1.5">
              {question.options.map((option) => {
                const selected = drafts[question.id]?.optionId === option.id
                return (
                  <button
                    key={option.id}
                    type="button"
                    aria-pressed={selected}
                    onClick={() => setDraft(question.id, { optionId: option.id })}
                    className={`rounded border px-2 py-0.5 transition cursor-pointer ${
                      selected ? 'border-brand bg-brand/10 text-brand' : 'border-line text-fg hover:border-brand'
                    }`}
                  >
                    {option.label}
                    {option.cost && <span className="ml-1 text-muted">{option.cost}</span>}
                  </button>
                )
              })}
            </div>
            {question.allowFreeText && (
              <input
                type="text"
                aria-label={question.text}
                placeholder={t('research.promptFreeText')}
                value={drafts[question.id]?.text ?? ''}
                onChange={(event) => setDraft(question.id, { text: event.target.value })}
                className="mt-1 w-full rounded border border-line bg-bg px-1.5 py-0.5 text-[11px] text-fg outline-hidden focus:border-brand"
              />
            )}
          </li>
        ))}
      </ol>

      {prompt.note && <p className="mt-1.5 text-muted">{prompt.note}</p>}

      <footer className="mt-1.5 flex items-center gap-2">
        <button
          type="button"
          data-testid="research-prompt-submit"
          disabled={busy || !canStart}
          title={canStart ? t('research.promptSubmit') : t('research.promptSubmitLocked')}
          onClick={() => void submit(true)}
          className="inline-flex items-center gap-1 rounded bg-zinc-100 px-2 py-0.5 text-zinc-900 transition hover:bg-white disabled:opacity-40 cursor-pointer"
        >
          <Check className="size-3" />
          {t('research.promptStart')}
        </button>
        <button
          type="button"
          data-testid="research-prompt-answer"
          disabled={busy}
          onClick={() => void submit(false)}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('research.promptSubmit')}
        </button>
      </footer>
    </section>
  )
}
