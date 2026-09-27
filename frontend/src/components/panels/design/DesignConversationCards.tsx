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
import { selectActiveRun, useDesignStore } from '../../../store/designStore'
import { DesignBatchDiffCard } from './DesignBatchDiffCard'
import { DesignBriefCard } from './DesignBriefCard'
import { DesignHandoffCard } from './DesignHandoffCard'
import { DesignNoticeCard } from './DesignNoticeCard'
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
  const notices = useDesignStore((s) => s.notices)
  if (!mode.on || !run) return null

  const openPrompts = prompts.filter(
    (prompt) => prompt.status === 'open' && prompt.kind !== 'exit-choice',
  )
  const report = reports[run.designId] ?? null
  // Thẻ bàn giao chỉ đến khi có báo cáo THẬT: một run đóng chưa phát `design_report` không được
  // dựng thẻ "chưa có báo cáo" chồng lên — thông báo nền mới là thứ nói run đã xong.
  const handoff = report !== null
  const runNotices = notices.filter((notice) => notice.designId === run.designId)

  return (
    <div className="space-y-2">
      {rejectedOps > 0 && (
        <p data-testid="design-rejected-ops" className="text-[11px] text-amber-300">
          {t('design.rejectCount', { count: rejectedOps })}
        </p>
      )}
      {runNotices.map((notice) => (
        <DesignNoticeCard key={`${notice.designId}:${notice.seq}:${notice.kind}`} notice={notice} />
      ))}
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
