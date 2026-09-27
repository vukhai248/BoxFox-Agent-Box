/**
 * Các thẻ Design xuất hiện TRONG hội thoại (P1 + P3/P4/P5): lời hỏi phỏng vấn, lời hỏi ngoài phạm vi,
 * thẻ brief + danh sách chạm, thẻ diff theo lô, thẻ bàn giao, dòng thời gian bước. Chúng cùng đọc
 * `designStore`, cùng nằm ngay trên ô soạn tin, và thứ tự hiển thị phải ổn định:
 *
 *   lời hỏi chặn (không tính `exit-choice` — thẻ đó neo vào nút Design) → brief → lô ghi → bàn giao →
 *   dòng thời gian.
 *
 * Chỉ vẽ những gì đã có: `rejectedOps` chỉ được nói tới khi thực sự lớn hơn 0; lô/bàn giao chỉ hiện khi
 * run có dữ liệu tương ứng, không dựng số liệu giả.
 */
import { useT } from '../../../i18n/context'
import { DESIGN_TERMINAL_STATUSES } from '../../../lib/designMode'
import { selectActiveRun, useDesignStore } from '../../../store/designStore'
import { DesignBatchDiffCard } from './DesignBatchDiffCard'
import { DesignBriefCard } from './DesignBriefCard'
import { DesignHandoffCard } from './DesignHandoffCard'
import { DesignOutOfScopeCard } from './DesignOutOfScopeCard'
import { DesignPromptCard } from './DesignPromptCard'
import { DesignRunTimeline } from './DesignRunTimeline'

export function DesignConversationCards() {
  const t = useT()
  const mode = useDesignStore((s) => s.mode)
  const run = useDesignStore(selectActiveRun)
  const prompts = useDesignStore((s) => s.prompts)
  const brief = useDesignStore((s) => s.brief)
  const rejectedOps = useDesignStore((s) => s.rejectedOps)
  const reports = useDesignStore((s) => s.reports)
  if (!mode.on || !run) return null

  const openPrompts = prompts.filter(
    (prompt) => prompt.status === 'open' && prompt.kind !== 'exit-choice',
  )
  const report = reports[run.designId] ?? null
  const handoff = DESIGN_TERMINAL_STATUSES.includes(run.status) || report !== null

  return (
    <div className="space-y-2">
      {rejectedOps > 0 && (
        <p data-testid="design-rejected-ops" className="text-[11px] text-amber-300">
          {t('design.rejectCount', { count: rejectedOps })}
        </p>
      )}
      {openPrompts.map((prompt) =>
        prompt.kind === 'out-of-scope' ? (
          <DesignOutOfScopeCard key={prompt.promptId} run={run} prompt={prompt} />
        ) : (
          <DesignPromptCard key={prompt.promptId} prompt={prompt} />
        ),
      )}
      <DesignBriefCard run={run} brief={brief as Record<string, unknown>} />
      <DesignBatchDiffCard designId={run.designId} batch={run.batch} revision={run.revision} />
      {handoff && <DesignHandoffCard run={run} report={report} />}
      <DesignRunTimeline run={run} />
    </div>
  )
}
