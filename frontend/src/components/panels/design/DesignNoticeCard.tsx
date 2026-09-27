/**
 * `DesignNoticeCard` (P5 §5.2) — một thẻ nhỏ cho mỗi sự kiện `design_notice` (§9).
 *
 * Vì sao là thẻ RIÊNG thay vì mở luôn thẻ báo cáo: thông báo chỉ nói "có chuyện để bạn biết"
 * (run nền xong / run cần bạn trả lời / run bị chặn); báo cáo bàn giao chỉ đến khi backend thật sự
 * phát `design_report`. Gộp hai thứ lại sẽ dựng thẻ báo cáo rỗng khi chưa có báo cáo.
 */
import { useT, type TKey } from '../../../i18n/context'
import { runLabel, type DesignNotice } from '../../../lib/designMode'

const NOTICE_KEY: Record<DesignNotice['kind'], TKey> = {
  'background-done': 'design.noticeBackgroundDone',
  'needs-user': 'design.noticeNeedsUser',
  blocked: 'design.noticeBlocked',
}

export function DesignNoticeCard({ notice }: { notice: DesignNotice }) {
  const t = useT()
  return (
    <section
      data-testid="design-notice-card"
      data-kind={notice.kind}
      className="rounded-lg border border-line bg-panel2 px-2 py-1 text-[11px] text-muted"
    >
      {t(NOTICE_KEY[notice.kind], { id: runLabel(notice.designId) })}
    </section>
  )
}
