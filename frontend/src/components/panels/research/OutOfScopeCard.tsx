/**
 * Thẻ "ngoài phạm vi" (mockup `out-of-scope.html`, §4.7).
 *
 * Research **không tự thoát chế độ** và không tự sửa code. Thẻ cho ba đường, trong đó đường thoát
 * chế độ tách thành HAI nút con vì khi tắt chế độ phải chọn số phận run, không có mặc định (bảng 4.8):
 * "Thoát chế độ · tạm dừng run", "Thoát chế độ · run chạy nền", và "Giữ trong research".
 *
 * Thoát chế độ đi qua `resolveExit` của store (nó gọi `PUT .../research-mode` với `exitChoice`);
 * "Giữ trong research" trả lời lời hỏi `out-of-scope` bằng chính lựa chọn tương ứng.
 */
import { useState } from 'react'
import { useT } from '../../../i18n/context'
import { useResearchStore } from '../../../store/researchStore'
import { runLabel, stepForPhase, type ResearchJob, type ResearchPrompt } from '../../../lib/researchMode'
import { formatClock } from './format'
import { STEP_LABEL_KEY } from './steps'

/** Id / nhãn hợp lệ cho lựa chọn "ở lại trong research" (server gửi id khác nhau tuỳ nguồn). */
const KEEP_IDS = ['keep', 'stay', 'research']
const KEEP_LABEL = /giữ|keep|stay|research/i

/**
 * Lựa chọn "giữ trong research" của lời hỏi `out-of-scope`.
 *
 * KHÔNG chọn theo một id cứng `'keep'`: chấp nhận `keep|stay|research` (không phân biệt hoa/thường),
 * rồi tới lựa chọn có nhãn/id nói rõ việc ở lại. Không suy được thì trả `null` để người dùng tự chọn,
 * thay vì gửi một câu trả lời đoán bừa.
 */
function keepOption(prompt: ResearchPrompt | null) {
  const options = prompt?.questions[0]?.options ?? []
  return options.find((option) => KEEP_IDS.includes(option.id.toLowerCase()))
    ?? options.find((option) => KEEP_LABEL.test(`${option.id} ${option.label}`))
    ?? null
}

export function OutOfScopeCard({ job, prompt }: { job: ResearchJob | null; prompt?: ResearchPrompt | null }) {
  const t = useT()
  const resolveExit = useResearchStore((s) => s.resolveExit)
  const answerPrompt = useResearchStore((s) => s.answerPrompt)
  const dismissPrompt = useResearchStore((s) => s.dismissPrompt)
  const [error, setError] = useState('')
  const run = job ? runLabel(job.researchId) : ''

  async function keepInResearch() {
    if (!prompt) return
    const keep = keepOption(prompt)
    if (!keep) {
      setError(t('research.outOfScopeKeepChoose'))
      return
    }
    setError('')
    const ok = await answerPrompt(prompt.promptId, {
      revision: prompt.revision,
      answers: [{ questionId: prompt.questions[0]?.id ?? '', optionId: keep.id }],
      start: false,
    })
    // Lời gọi hỏng (409 revision cũ, mạng lỗi…) ⇒ GIỮ thẻ và nói ra; không đóng lời hỏi để quyết định
    // của người dùng không bị nuốt mất.
    if (!ok) {
      setError(t('research.outOfScopeKeepFailed'))
      return
    }
    await dismissPrompt(prompt.promptId)
  }

  return (
    <section
      data-testid="research-out-of-scope-card"
      className="rounded-lg border border-amber-500/40 bg-amber-500/5 p-2 text-[11px]"
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-amber-300">{t('research.promptOutOfScope')}</span>
        {job && (
          <span className="ml-auto font-mono text-[10px] text-muted">
            {formatClock(job.usedSeconds)} / {formatClock(job.budgetSeconds)}
          </span>
        )}
      </header>
      {job && (
        <p className="mt-0.5 text-muted">
          {t('research.stripRun', { id: run, step: t(STEP_LABEL_KEY[stepForPhase(job.phase)]) })}
        </p>
      )}
      <p className="mt-1 text-fg">{t('research.outOfScopeNoAuto')}</p>
      <p className="text-muted">{t('research.outOfScopeExitHint')}</p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        <button
          type="button"
          data-testid="research-out-of-scope-exit-pause"
          onClick={() => void resolveExit('pause')}
          className="rounded border border-line bg-panel px-2 py-0.5 transition hover:border-brand cursor-pointer"
        >
          {t('research.outOfScopeExitPause')}
        </button>
        <button
          type="button"
          data-testid="research-out-of-scope-exit-background"
          onClick={() => void resolveExit('background')}
          className="rounded border border-line bg-panel px-2 py-0.5 transition hover:border-brand cursor-pointer"
        >
          {t('research.outOfScopeExitBackground')}
        </button>
        <button
          type="button"
          data-testid="research-out-of-scope-keep"
          disabled={!prompt}
          onClick={() => void keepInResearch()}
          className="rounded border border-line bg-panel px-2 py-0.5 transition hover:border-brand disabled:opacity-40 cursor-pointer"
        >
          {t('research.outOfScopeKeep')}
        </button>
      </div>
      <p className="mt-1 text-muted">{t('research.outOfScopeKeepHint')}</p>
      {error && <p className="mt-1 text-amber-300" role="alert" data-testid="research-out-of-scope-error">{error}</p>}
      <p className="mt-1 text-muted">{t('research.outOfScopeNoAssumptions')} {t('research.promptNote')}</p>
    </section>
  )
}
