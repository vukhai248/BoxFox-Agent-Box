/**
 * Các thẻ Design xuất hiện TRONG hội thoại (P1): lời hỏi phỏng vấn, thẻ brief + danh sách chạm, dòng
 * thời gian bước. Chúng cùng đọc `designStore`, cùng nằm ngay trên ô soạn tin, và thứ tự hiển thị phải
 * ổn định (lời hỏi chặn trước, rồi brief, rồi dòng thời gian).
 *
 * P1 chỉ vẽ những gì đã có: thẻ diff, thẻ bàn giao và bộ đếm op canvas bị bỏ là việc của P3/P4 —
 * `rejectedOps` chỉ được nói tới khi thực sự lớn hơn 0, vì canvas chưa nối ở P1.
 */
import { useT } from '../../../i18n/context'
import { selectActiveRun, useDesignStore } from '../../../store/designStore'
import { DesignBriefCard } from './DesignBriefCard'
import { DesignPromptCard } from './DesignPromptCard'
import { DesignRunTimeline } from './DesignRunTimeline'

export function DesignConversationCards() {
  const t = useT()
  const mode = useDesignStore((s) => s.mode)
  const run = useDesignStore(selectActiveRun)
  const prompts = useDesignStore((s) => s.prompts)
  const brief = useDesignStore((s) => s.brief)
  const rejectedOps = useDesignStore((s) => s.rejectedOps)
  if (!mode.on || !run) return null

  const openPrompts = prompts.filter(
    (prompt) => prompt.status === 'open' && prompt.kind !== 'exit-choice',
  )
  return (
    <div className="space-y-2">
      {rejectedOps > 0 && (
        <p data-testid="design-rejected-ops" className="text-[11px] text-amber-300">
          {t('design.rejectCount', { count: rejectedOps })}
        </p>
      )}
      {openPrompts.map((prompt) => (
        <DesignPromptCard key={prompt.promptId} prompt={prompt} />
      ))}
      <DesignBriefCard run={run} brief={brief as Record<string, unknown>} />
      <DesignRunTimeline run={run} />
    </div>
  )
}
