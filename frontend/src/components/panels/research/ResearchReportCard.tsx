/**
 * Thẻ báo cáo (mockup `report-handoff.html`, và biến thể trong `background-run-indicator.html`).
 *
 * Dùng cho cả hai đường: run hoàn tất khi chế độ đang bật, và run chạy nền kết thúc sau khi người
 * dùng đã tắt chế độ. Đường dẫn hồ sơ in ĐÚNG dạng `.research/<slug>-<yyyymmdd-hhmm>/v<N>-<id>.md`
 * do server trả về — không tự dựng lại (bảng 4.8).
 *
 * "Dùng cho plan" (§4.5 + §5.10): TẮT chế độ (nếu đang bật), rồi gửi MỘT lượt main đúng nội dung
 * "Lập plan dựa trên báo cáo research <id> v<N>". Kế hoạch có nêu `researchDependencies` trong siêu
 * dữ liệu lượt, nhưng tuyến `POST /sessions/{sid}/turns` không có kênh siêu dữ liệu; khối bàn giao
 * research→main được chèn vào lượt main kế tiếp đã mang sẵn researchId/version/hash và dặn mô hình
 * truyền `researchDependencies` cho `write_plan`. Vì vậy KHÔNG bịa thêm trường siêu dữ liệu, KHÔNG
 * gọi `showTab`. Các nút Đào sâu/Cập nhật đi qua `PATCH /research/jobs/{id}` (`deepen`/`refresh`, §5.12).
 */
import { useState } from 'react'
import { useT } from '../../../i18n/context'
import { useUiStore } from '../../../store/uiStore'
import { useHarnessChatStore } from '../../../store/harnessChatStore'
import { useResearchStore } from '../../../store/researchStore'
import { runLabel, STATUS_TONE_CLASS, jobStatusKey, jobStatusTone, type ResearchJob } from '../../../lib/researchMode'
import { formatClock } from './format'
import { critiqueLabel } from './RunTimeline'

export function ResearchReportCard({ job, inBackground }: { job: ResearchJob; inBackground?: boolean }) {
  const t = useT()
  const showTab = useUiStore((s) => s.showTab)
  const updateJob = useResearchStore((s) => s.updateJob)
  // Nút "Dùng cho plan" phải đổi trạng thái khi vòng 1200 ms làm mới `session.config.researchMode`:
  // đăng ký `mode` để React vẽ lại khi `handoffDeliveredVersion` đổi.
  const mode = useResearchStore((s) => s.mode)
  // Trong khi gửi lượt plan thì khoá nút: gửi hai lần mở hai lượt main cùng nội dung.
  const [busy, setBusy] = useState(false)
  // Lời hỏi thoát còn mở: nút chưa gửi được, hiện một dòng nhắc thay vì im lặng.
  const [needsChoice, setNeedsChoice] = useState(false)

  const dossier = job.dossier
  if (!dossier && job.status !== 'completed') return null
  const latestReview = job.reviews.at(-1)
  const incomplete = latestReview?.verdict === 'revise' || latestReview?.verdict === 'rejected'
  // `deepen` bắt buộc có đích: facet của run, hoặc câu hỏi. Không có đích thì không gửi (server 400).
  const deepenTarget = job.coverage.facets[0]?.id ?? job.questions[0]?.id ?? ''
  // Bàn giao đã xong cho ĐÚNG phiên bản hồ sơ đang thấy ⇒ nút chỉ còn để đọc, bấm không gửi gì.
  const delivered = dossier !== null && mode.handoffDeliveredVersion[job.researchId] === String(dossier.version)

  /**
   * Nút "Dùng cho plan" (§4.5 + §5.10): (1) tắt chế độ nếu đang bật; (2) gửi lượt main. Khi server
   * đòi người dùng chọn số phận run (`exit-choice`) hoặc PUT hỏng (`error`) thì DỪNG — thẻ thoát đã
   * sở hữu lựa chọn của người dùng, tuyệt đối không gửi lượt trong trường hợp đó.
   */
  async function useForPlan() {
    if (!dossier || busy || delivered) return
    setBusy(true)
    try {
      const store = useResearchStore.getState()
      if (store.mode.on) {
        // Bấm nút không phải hành động gạt toggle ở ô soạn tin ⇒ `by: 'command'`.
        const outcome = await store.setMode(false, 'command')
        if (outcome === 'exit-choice') {
          setNeedsChoice(true)
          return
        }
        if (outcome === 'error') return
      }
      const sessionId = useResearchStore.getState().sessionId
      if (!sessionId) return
      const text = t('research.useForPlanTurn', { id: job.researchId, version: dossier.version })
      await useHarnessChatStore.getState().send(sessionId, text, null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      data-testid="research-report-card"
      data-background={inBackground ? 'true' : 'false'}
      className="rounded-lg border border-emerald-500/40 bg-emerald-500/5 p-2 text-[11px]"
    >
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-emerald-300">{t('research.reportTitle', { goal: job.goal || runLabel(job.researchId) })}</span>
        {dossier && (
          <span className="rounded border border-line px-1 py-px text-[10px] text-muted">
            {t('research.reportVersion', { n: dossier.version })}
          </span>
        )}
        <span
          data-testid="research-report-status"
          data-status={job.status}
          className={`ml-auto rounded px-1 py-px text-[10px] font-medium ${STATUS_TONE_CLASS[jobStatusTone(job)]}`}
        >
          {t(jobStatusKey(job))}
        </span>
      </header>
      <p className="mt-0.5 text-muted" data-testid="research-report-meta">
        {t('research.reportMeta', {
          id: runLabel(job.researchId),
          tier: job.tier,
          branches: job.branches.length,
          sources: job.evidence.length,
          used: formatClock(job.usedSeconds),
          budget: formatClock(job.budgetSeconds),
        })}
      </p>
      {dossier && (
        <p className="mt-0.5 font-mono text-[10px] text-muted" data-testid="research-report-path">
          {t('research.reportPath', { version: dossier.version, path: dossier.relativePath })}
        </p>
      )}
      {latestReview && (
        <p className="mt-0.5 text-muted" data-testid="research-report-critique">
          {t('research.reportCritique', { verdict: incomplete ? t('research.reportFailedCritique') : latestReview.verdict })}
        </p>
      )}

      {job.findings.length > 0 && (
        <div className="mt-1.5">
          <h4 className="text-[10px] font-medium tracking-wide text-muted uppercase">
            {t('research.reportConclusions')}
          </h4>
          <ol className="mt-0.5 space-y-0.5">
            {job.findings.slice(0, 3).map((finding, index) => (
              <li key={`${finding}-${index}`} className="flex gap-1.5 text-fg">
                <span className="text-muted">{index + 1}</span>
                <span>{finding}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {job.reviews.length > 0 && (
        <div className="mt-1.5">
          <h4 className="text-[10px] font-medium tracking-wide text-muted uppercase">{t('research.reportReviews')}</h4>
          <ul className="mt-0.5 space-y-0.5 text-muted">
            {job.reviews.map((review) => (
              <li key={`${review.version}-${review.mode}`}>{critiqueLabel(t, review)}</li>
            ))}
          </ul>
        </div>
      )}
      {job.blockedSources.length > 0 && (
        <p className="mt-1 text-[10px] text-amber-300">
          {t('research.conflicts', { count: job.blockedSources.length })}
        </p>
      )}

      {needsChoice && (
        <p className="mt-1 text-[10px] text-amber-300" data-testid="research-use-for-plan-needs-choice">
          {t('research.useForPlanNeedsChoice')}
        </p>
      )}

      <footer className="mt-1.5 flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          data-testid="research-report-use-for-plan"
          data-busy={busy ? 'true' : 'false'}
          data-handoff={delivered ? 'done' : 'ready'}
          disabled={!dossier || busy || delivered}
          onClick={() => void useForPlan()}
          className="rounded bg-zinc-100 px-2 py-0.5 text-zinc-900 transition hover:bg-white disabled:opacity-40 cursor-pointer"
        >
          {delivered ? t('research.handoffDone') : t('research.reportUseForPlan')}
        </button>
        <button
          type="button"
          data-testid="research-report-deepen"
          disabled={!deepenTarget}
          onClick={() => void updateJob(job.researchId, {
            action: 'deepen', revision: job.revision,
            ...(job.coverage.facets[0]?.id ? { facetId: job.coverage.facets[0].id } : { questionId: deepenTarget }),
          })}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg disabled:opacity-40 cursor-pointer"
        >
          {t('research.reportDeepen')}
        </button>
        <button
          type="button"
          data-testid="research-report-update"
          onClick={() => void updateJob(job.researchId, { action: 'refresh', revision: job.revision })}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('research.reportUpdate')}
        </button>
        <button
          type="button"
          data-testid="research-report-open"
          onClick={() => showTab('research', { researchId: job.researchId })}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('research.openReport')}
        </button>
      </footer>
    </section>
  )
}
