/**
 * `DesignBatchDiffCard` (P3/P5) — một LÔ ghi các tệp đã chạm trên nhánh thiết kế (mockup
 * `design-diff-batch-card.html`).
 *
 * Thẻ chỉ đọc dữ liệu đã chuẩn hoá (`DesignBatch`) và gửi đúng `revision` đang thấy khi duyệt/hoàn tác
 * (`PATCH /api/agent/design/runs/{id}`) — khoá lạc quan, không bao giờ ghi mù. Khi run chưa có lô nào
 * thì thẻ hiện "chưa có lô" và KHÔNG bịa nút duyệt.
 */
import { useT } from '../../../i18n/context'
import type { DesignBatch } from '../../../lib/designMode'
import { useDesignStore } from '../../../store/designStore'

export function DesignBatchDiffCard({
  designId,
  batch,
  revision,
}: {
  designId: string
  batch: DesignBatch | null
  revision?: number
}) {
  const t = useT()
  const updateRun = useDesignStore((s) => s.updateRun)
  const index = batch?.index ?? 0

  function act(action: string) {
    if (!batch) return
    void updateRun(designId, { action, revision: revision ?? batch.revision })
  }

  return (
    <section
      data-testid="design-diff-batch-card"
      data-status={batch?.status ?? 'none'}
      className="rounded-lg border border-line bg-panel2 p-2 text-[11px]"
    >
      <header className="flex items-center justify-between gap-2">
        <span className="font-medium text-fg">
          {batch
            ? t('design.batchTitle', { index, total: batch.total, count: batch.files.length })
            : t('design.batchEmpty')}
        </span>
        {batch && (
          <span className="shrink-0 font-mono text-[10px]">
            <span className="text-emerald-400">{`+${batch.added}`}</span>{' '}
            <span className="text-rose-400">{`−${batch.removed}`}</span>
          </span>
        )}
      </header>
      {batch && (
        <>
          {batch.status && (
            <p className="mt-0.5 text-muted">{t('design.batchStatus', { status: batch.status })}</p>
          )}
          <ul className="mt-1 space-y-0.5">
            {batch.files.map((file) => (
              <li key={file.path} data-path={file.path} className="flex items-center gap-1 font-mono text-[10px]">
                <span className="truncate text-fg">{file.path}</span>
                <span className="ml-auto shrink-0 text-emerald-400">{`+${file.added}`}</span>
                <span className="shrink-0 text-rose-400">{`−${file.removed}`}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1 font-mono text-[10px] text-muted">
            {t('design.batchPatch', { path: batch.patchPath })}
          </p>
          <div className="mt-1.5 flex gap-1">
            <button
              type="button"
              data-testid="design-batch-approve"
              onClick={() => act('approve-batch')}
              className="rounded border border-brand px-2 py-0.5 text-brand transition hover:bg-brand/10 cursor-pointer"
            >
              {t('design.batchApprove', { index })}
            </button>
            <button
              type="button"
              data-testid="design-batch-revert"
              onClick={() => act('revert-batch')}
              className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
            >
              {t('design.batchRevert', { index })}
            </button>
          </div>
        </>
      )}
    </section>
  )
}
