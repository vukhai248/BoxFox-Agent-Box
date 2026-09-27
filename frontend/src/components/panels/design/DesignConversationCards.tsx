/**
 * Các thẻ Design xuất hiện TRONG hội thoại (P1 + P3/P4/P5): lời hỏi phỏng vấn, lời hỏi ngoài phạm vi,
 * thẻ brief + danh sách chạm, thẻ diff theo lô, thẻ bàn giao, dòng thời gian bước. Chúng cùng đọc
 * `designStore`, cùng nằm ngay trên ô soạn tin, và thứ tự hiển thị phải ổn định:
 *
 *   lời hỏi chặn (không tính `exit-choice` — thẻ đó neo vào nút Design) → brief → lô ghi → bàn giao →
 *   dòng thời gian.
 *
 * Chỉ vẽ những gì ĐÃ CÓ và đúng vòng đời của nó: các thẻ thuộc run ĐANG chạy (lời hỏi/brief/lô/dòng
 * thời gian) chỉ hiện khi chế độ bật; còn thông báo nền và thẻ bàn giao phải hiện được cả khi chế độ
 * TẮT — đó chính là lúc backend phát chúng sau một run chạy nền. `rejectedOps` chỉ được nói tới khi
 * thực sự lớn hơn 0; lô/bàn giao chỉ hiện khi run có dữ liệu tương ứng, không dựng số liệu giả.
 */
import { useT } from '../../../i18n/context'
import { selectActiveRun, useDesignStore } from '../../../store/designStore'
import { DesignBatchDiffCard } from './DesignBatchDiffCard'
import { DesignBriefCard } from './DesignBriefCard'
import { DesignErrorNotice } from './DesignErrorNotice'
import { DesignHandoffCard } from './DesignHandoffCard'
import { DesignNoticeCard } from './DesignNoticeCard'
import { DesignOutOfScopeCard } from './DesignOutOfScopeCard'
import { DesignPromptCard } from './DesignPromptCard'
import { DesignRunTimeline } from './DesignRunTimeline'

export function DesignConversationCards() {
  const t = useT()
  const mode = useDesignStore((s) => s.mode)
  const run = useDesignStore(selectActiveRun)
  const runs = useDesignStore((s) => s.runs)
  const prompts = useDesignStore((s) => s.prompts)
  const brief = useDesignStore((s) => s.brief)
  const rejectedOps = useDesignStore((s) => s.rejectedOps)
  const reports = useDesignStore((s) => s.reports)
  const notices = useDesignStore((s) => s.notices)
  const error = useDesignStore((s) => s.error)

  // Thẻ của run đang chạy chỉ có nghĩa khi chế độ bật; thông báo nền và báo cáo bàn giao thì không —
  // chúng đến khi run nền đã xong, tức lúc `mode.on` là false (P5 cổng "thẻ báo cáo hiện khi xong").
  const liveRun = mode.on ? run : null
  const reportEntries = Object.entries(reports)
  if (!liveRun && notices.length === 0 && reportEntries.length === 0 && !error) return null

  const openPrompts = liveRun
    ? prompts.filter((prompt) => prompt.status === 'open' && prompt.kind !== 'exit-choice')
    : []

  return (
    <div className="space-y-2">
      <DesignErrorNotice />
      {liveRun && rejectedOps > 0 && (
        <p data-testid="design-rejected-ops" className="text-[11px] text-amber-300">
          {t('design.rejectCount', { count: rejectedOps })}
        </p>
      )}
      {notices.map((notice) => (
        <DesignNoticeCard key={`${notice.designId}:${notice.seq}:${notice.kind}`} notice={notice} />
      ))}
      {liveRun &&
        openPrompts.map((prompt) =>
          prompt.kind === 'out-of-scope' ? (
            <DesignOutOfScopeCard key={prompt.promptId} run={liveRun} prompt={prompt} />
          ) : (
            <DesignPromptCard key={prompt.promptId} prompt={prompt} />
          ),
        )}
      {liveRun && (
        <>
          <DesignBriefCard run={liveRun} brief={brief as Record<string, unknown>} />
          <DesignBatchDiffCard designId={liveRun.designId} batch={liveRun.batch} revision={liveRun.revision} />
        </>
      )}
      {/* Thẻ bàn giao chỉ đến khi có báo cáo THẬT cho run ấy; run đóng chưa phát `design_report` không
          được dựng thẻ "chưa có báo cáo" chồng lên — thông báo nền mới là thứ nói run đã xong. */}
      {reportEntries.map(([designId, report]) => {
        const reportRun = runs.find((item) => item.designId === designId) ?? null
        return reportRun ? <DesignHandoffCard key={designId} run={reportRun} report={report} /> : null
      })}
      {liveRun && <DesignRunTimeline run={liveRun} />}
    </div>
  )
}
