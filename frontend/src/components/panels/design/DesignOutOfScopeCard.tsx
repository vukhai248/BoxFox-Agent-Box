/**
 * `DesignOutOfScopeCard` (P5) — yêu cầu rơi NGOÀI phạm vi thiết kế: hai lối ra rõ ràng, không có lối
 * nào mặc định (cùng luật với thẻ thoát chế độ).
 *
 * - "Tạm thoát để main xử lý": trả lời lời hỏi rồi để lượt main tiếp nhận yêu cầu.
 * - "Giữ trong design": ghi nhận yêu cầu như một phần phạm vi của run.
 *
 * Hai lựa chọn đọc theo ID ĐÃ GHIM (IF-2: `'exit'`/`'keep'`), KHÔNG dò bằng regex hay vị trí — với
 * nhãn mờ, đoán theo thứ tự có thể trả lời "keep" trong khi giao diện hiện "thoát". Thiếu id ghim thì
 * thẻ khoá lại và nói rõ, thay vì đoán.
 */
import { useState } from 'react'
import { useT } from '../../../i18n/context'
import { asRecord, asString, runLabel, type DesignPrompt, type DesignPromptOption, type DesignRun } from '../../../lib/designMode'
import { useDesignStore } from '../../../store/designStore'

export function DesignOutOfScopeCard({ run, prompt }: { run: DesignRun; prompt: DesignPrompt }) {
  const t = useT()
  const answerPrompt = useDesignStore((s) => s.answerPrompt)
  const setMode = useDesignStore((s) => s.setMode)
  const queueTurn = useDesignStore((s) => s.queueTurn)
  const [needsChoice, setNeedsChoice] = useState(false)
  const question = prompt.questions[0]
  const options = question?.options ?? []
  const exitOption = options.find((option) => option.id === 'exit')
  const keepOption = options.find((option) => option.id === 'keep')
  const pinned = Boolean(question && exitOption && keepOption)
  // §5.9: nộp lại TIN NHẮN GỐC của chủ nhà (`meta.request`), không phải câu chữ của Design Lead.
  const request = asString(asRecord(prompt.meta).request) || question?.text || prompt.note || ''

  /** Trả lời một lựa chọn; trả `false` khi server từ chối (thẻ lỗi của store sẽ hiện câu đọc được). */
  async function answer(option: DesignPromptOption | undefined): Promise<boolean> {
    if (!question || !option) return false
    return answerPrompt(prompt.promptId, {
      revision: prompt.revision,
      answers: [{ questionId: question.id, optionId: option.id }],
    })
  }

  /**
   * §5.9 — tắt chế độ (nếu run hoạt động thì theo luật thoát §5.8) rồi nộp lại yêu cầu thành một
   * lượt main KHÔNG mang giả định chưa xác nhận của run. Tin nhắn chỉ được nộp khi chế độ đã tắt
   * thành công, nên nó đi qua hàng đợi của store (`queueTurn`) chứ không gửi thẳng. Trả lời thất bại
   * thì DỪNG: không xếp lượt, không tắt chế độ khi lời hỏi ngoài phạm vi vẫn còn mở.
   */
  async function exitToMain(): Promise<void> {
    if (!(await answer(exitOption))) return
    queueTurn(t('design.oosExitTurn', { request }))
    const outcome = await setMode(false, 'toggle')
    if (outcome === 'exit-choice') setNeedsChoice(true)
    else if (outcome === 'error') queueTurn('')
  }

  async function keepInDesign(): Promise<void> {
    setNeedsChoice(false)
    await answer(keepOption)
  }

  return (
    <section
      data-testid="design-out-of-scope"
      data-kind={prompt.kind}
      data-pinned={pinned ? 'true' : 'false'}
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
          disabled={!pinned}
          onClick={() => void exitToMain()}
          className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand disabled:opacity-60 cursor-pointer"
        >
          <span className="font-medium text-fg">{t('design.oosExit')}</span>
          <span className="ml-1 text-muted">{t('design.oosExitHint')}</span>
        </button>
        <button
          type="button"
          data-testid="design-out-of-scope-keep"
          disabled={!pinned}
          onClick={() => void keepInDesign()}
          className="block w-full rounded border border-line bg-panel px-2 py-1 text-left transition hover:border-brand disabled:opacity-60 cursor-pointer"
        >
          <span className="font-medium text-fg">{t('design.oosKeep')}</span>
          <span className="ml-1 text-muted">{t('design.oosKeepHint')}</span>
        </button>
      </div>
      {!pinned && (
        <p data-testid="design-out-of-scope-unpinned" className="mt-1 text-[10px] text-amber-300">
          {t('design.oosUnpinned')}
        </p>
      )}
      {needsChoice && (
        <p data-testid="design-out-of-scope-hint" className="mt-1 text-[10px] text-amber-300">
          {t('design.oosExitQueued')}
        </p>
      )}
    </section>
  )
}
