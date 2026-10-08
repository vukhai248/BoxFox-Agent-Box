/**
 * Thẻ phỏng vấn (`interview`) — nhiều câu hỏi làm rõ trong MỘT thẻ.
 *
 * Bố cục theo mẫu của chủ nhà: mỗi câu là một hàng Q1..Qn thu gọn được; câu đang mở hiện các
 * lựa chọn dạng radio (nhãn đậm + mô tả), thêm "Khác — tự nhập câu trả lời" và liên kết
 * "Để agent quyết định". Gửi đi là `{choice:'submit', answers:[{questionId, optionId|text}]}`;
 * câu bỏ trống hoặc chọn "để agent quyết định" do agent tự chọn (harness ghi `decidedBy:'agent'`).
 */
import { useMemo, useState } from 'react'
import { ChevronDown, CircleHelp, LoaderCircle, Sparkles } from 'lucide-react'
import { useT } from '../i18n/context'
import type { DecisionEntry, InterviewAnswer, InterviewQuestion, InterviewReply } from '../store/harnessChatStore'

/** Mã lựa chọn mà harness hiểu (runtime.INTERVIEW_SUBMIT / INTERVIEW_DECIDE / DECISION_OTHER_OPTION_ID). */
export const INTERVIEW_SUBMIT = 'submit'
export const INTERVIEW_DECIDE = 'decide'
export const INTERVIEW_OTHER = 'other'

type Draft = { optionId: string; text: string }

export interface InterviewCardProps {
  decision: DecisionEntry
  onAnswer?: (choice: string, note?: string, answers?: InterviewReply[]) => void
  busy?: boolean
}

function draftDone(draft: Draft | undefined): draft is Draft {
  if (!draft) return false
  return draft.optionId !== INTERVIEW_OTHER || draft.text.trim().length > 0
}

/** Bản nháp → câu trả lời gửi đi; câu chưa chọn thì không gửi (agent quyết định). */
export function interviewReplies(questions: InterviewQuestion[], drafts: Record<string, Draft>): InterviewReply[] {
  const replies: InterviewReply[] = []
  for (const question of questions) {
    const draft = drafts[question.id]
    if (!draftDone(draft)) continue
    replies.push(
      draft.optionId === INTERVIEW_OTHER
        ? { questionId: question.id, optionId: INTERVIEW_OTHER, text: draft.text.trim() }
        : { questionId: question.id, optionId: draft.optionId },
    )
  }
  return replies
}

/** Nhãn một câu trả lời đã chốt — dùng chung cho thẻ và lịch sử quyết định. */
export function interviewAnswerLabel(answer: InterviewAnswer, t: ReturnType<typeof useT>): string {
  if (answer.decidedBy !== 'agent') return answer.answer ?? ''
  return answer.recommended
    ? t('decisions.interview.agentDecidesWith', { option: answer.recommended })
    : t('decisions.interview.agentDecides')
}

export function InterviewCard({ decision, onAnswer, busy = false }: InterviewCardProps) {
  const t = useT()
  const questions = useMemo(() => decision.questions ?? [], [decision.questions])
  const pending = decision.status === 'pending'
  const [open, setOpen] = useState(0)
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})
  const done = questions.filter((question) => draftDone(drafts[question.id])).length
  // "Khác" đã chọn mà để trống thì chặn gửi, để câu đó không lặng lẽ rơi về agent.
  const emptyOther = questions.some((question) => {
    const draft = drafts[question.id]
    return draft?.optionId === INTERVIEW_OTHER && !draftDone(draft)
  })
  const disabled = busy || !pending || !onAnswer || decision.actionable === false

  const answersById = useMemo(
    () => new Map((decision.answers ?? []).map((answer) => [answer.questionId, answer])),
    [decision.answers],
  )

  const choose = (index: number, optionId: string) => {
    const question = questions[index]
    setDrafts((current) => ({
      ...current,
      [question.id]: { optionId, text: current[question.id]?.text ?? '' },
    }))
    // Chọn xong một lựa chọn thường thì mở câu kế tiếp chưa trả lời, như mẫu.
    if (optionId !== INTERVIEW_OTHER) {
      const order = [...questions.keys()].map((step) => (index + 1 + step) % questions.length)
      const next = order.find((position) => position !== index && !draftDone(drafts[questions[position].id]))
      if (next !== undefined) setOpen(next)
    }
  }

  const submit = () => onAnswer?.(INTERVIEW_SUBMIT, undefined, interviewReplies(questions, drafts))

  return (
    <div
      className="overflow-hidden rounded-xl border border-line bg-panel shadow-sm"
      data-testid="interview-card"
      data-decision-id={decision.id}
    >
      {decision.title && (
        <div className="flex items-center gap-2 border-b border-line px-4 py-2.5 text-[12px] font-semibold text-fg">
          <Sparkles className="size-3.5 text-brand" />
          <span>{decision.title}</span>
          {pending && (
            <span className="ml-auto text-[11px] font-normal text-muted" data-testid="interview-progress">
              {t('decisions.interview.progress', { done: String(done), total: String(questions.length) })}
            </span>
          )}
        </div>
      )}
      {questions.map((question, index) => {
        const expanded = pending ? open === index : true
        const draft = drafts[question.id]
        const resolved = answersById.get(question.id)
        const bodyId = `${decision.id}-${question.id}-body`
        const whyId = `${decision.id}-${question.id}-why`
        return (
          <section
            key={question.id}
            className={index > 0 ? 'border-t border-line' : ''}
            data-testid="interview-question"
            data-question-id={question.id}
          >
            <button
              type="button"
              className="flex w-full items-center gap-3 px-4 py-3 text-left"
              onClick={() => setOpen(index)}
              aria-expanded={expanded}
              aria-controls={pending && expanded ? bodyId : undefined}
            >
              <span
                className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${
                  expanded ? 'bg-brand/15 text-brand' : 'bg-panel2 text-muted'
                }`}
              >
                Q{index + 1}
              </span>
              <span className={`flex-1 text-[13px] ${expanded ? 'text-fg' : 'text-muted'}`}>{question.question}</span>
              {question.rationale && expanded ? (
                <span title={`${t('decisions.interview.why')}: ${question.rationale}`} className="text-muted" aria-hidden>
                  <CircleHelp className="size-4" />
                </span>
              ) : (
                !expanded && (
                  <span className="rounded-md bg-panel2 p-1 text-muted">
                    <ChevronDown className="size-3.5" />
                  </span>
                )
              )}
            </button>
            {!pending && resolved && (
              <p className="px-4 pb-3 pl-14 text-[12px] text-fg" data-testid="interview-answer">
                {interviewAnswerLabel(resolved, t)}
              </p>
            )}
            {pending && expanded && question.rationale && (
              <p id={whyId} className="px-4 pb-2 pl-14 text-[11px] text-muted" data-testid="interview-rationale">
                {t('decisions.interview.why')}: {question.rationale}
              </p>
            )}
            {pending && expanded && (
              <div
                id={bodyId}
                className="flex flex-col gap-2 px-4 pb-3"
                role="radiogroup"
                aria-label={question.question}
                aria-describedby={question.rationale ? whyId : undefined}
              >
                {question.options.map((option) => (
                  <InterviewOptionRow
                    key={option.id}
                    name={`${decision.id}-${question.id}`}
                    label={option.label}
                    description={option.description}
                    recommended={option.recommended}
                    checked={draft?.optionId === option.id}
                    disabled={disabled}
                    onSelect={() => choose(index, option.id)}
                    testId={`interview-option-${question.id}-${option.id}`}
                  />
                ))}
                <InterviewOptionRow
                  name={`${decision.id}-${question.id}`}
                  label={t('decisions.interview.other')}
                  description={t('decisions.interview.otherHint')}
                  checked={draft?.optionId === INTERVIEW_OTHER}
                  disabled={disabled}
                  onSelect={() => choose(index, INTERVIEW_OTHER)}
                  testId={`interview-option-${question.id}-other`}
                />
                {draft?.optionId === INTERVIEW_OTHER && (
                  <textarea
                    data-testid={`interview-other-input-${question.id}`}
                    value={draft.text}
                    rows={2}
                    autoFocus
                    disabled={disabled}
                    placeholder={t('decisions.interview.otherPlaceholder')}
                    onChange={(event) =>
                      setDrafts((current) => ({
                        ...current,
                        [question.id]: { optionId: INTERVIEW_OTHER, text: event.target.value },
                      }))
                    }
                    className="min-h-9 w-full resize-y rounded-lg border border-line bg-panel2 px-3 py-2 text-[12px] text-fg outline-none focus:border-brand/60"
                  />
                )}
                <div className="flex justify-end">
                  <button
                    type="button"
                    disabled={disabled}
                    data-testid={`interview-decide-${question.id}`}
                    aria-pressed={draft?.optionId === INTERVIEW_DECIDE}
                    onClick={() => choose(index, INTERVIEW_DECIDE)}
                    className={`text-[12px] font-semibold transition hover:text-brand disabled:opacity-50 ${
                      draft?.optionId === INTERVIEW_DECIDE ? 'text-brand' : 'text-fg'
                    }`}
                  >
                    {t('decisions.interview.decideOne')}
                  </button>
                </div>
              </div>
            )}
          </section>
        )
      })}
      {pending && (
        <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line px-4 py-3">
          {busy && (
            <span className="mr-auto flex items-center gap-1 text-[11px] text-muted" aria-live="polite">
              <LoaderCircle className="size-3 animate-spin" />
              {t('decisions.sendingAnswer')}
            </span>
          )}
          <button
            type="button"
            disabled={disabled}
            data-testid="interview-decide-all"
            onClick={() => onAnswer?.(INTERVIEW_DECIDE)}
            className="text-[12px] font-semibold text-muted transition hover:text-fg disabled:opacity-50"
          >
            {t('decisions.interview.decide')}
          </button>
          <button
            type="button"
            disabled={disabled || done === 0 || emptyOther}
            title={emptyOther ? t('decisions.interview.otherPlaceholder') : undefined}
            data-testid="interview-submit"
            onClick={submit}
            className="rounded-lg bg-brand px-3 py-1.5 text-[12px] font-semibold text-white transition hover:bg-brand/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('decisions.interview.submit')}
          </button>
        </div>
      )}
    </div>
  )
}

function InterviewOptionRow({
  name,
  label,
  description,
  recommended = false,
  checked,
  disabled,
  onSelect,
  testId,
}: {
  name: string
  label: string
  description: string
  recommended?: boolean
  checked: boolean
  disabled: boolean
  onSelect: () => void
  testId: string
}) {
  const t = useT()
  return (
    <label
      data-testid={testId}
      className={`flex cursor-pointer items-start gap-3 rounded-lg border px-3 py-2.5 transition ${
        checked ? 'border-brand/60 bg-brand/10' : 'border-transparent bg-panel2 hover:border-line'
      } ${disabled ? 'cursor-not-allowed opacity-60' : ''}`}
    >
      <input
        type="radio"
        name={name}
        checked={checked}
        disabled={disabled}
        onChange={onSelect}
        className="mt-1 size-3.5 accent-[var(--color-brand,#6366f1)]"
      />
      <span className="flex min-w-0 flex-col gap-0.5">
        <span className="flex items-center gap-2 text-[13px] font-semibold text-fg">
          {label}
          {recommended && (
            <span className="rounded bg-emerald-500/15 px-1.5 py-px text-[10px] font-medium text-emerald-400">
              {t('decisions.interview.recommended')}
            </span>
          )}
        </span>
        {description && <span className="text-[12px] text-muted">{description}</span>}
      </span>
    </label>
  )
}
