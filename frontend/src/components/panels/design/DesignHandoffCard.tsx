/**
 * `DesignHandoffCard` (P4/P5) — báo cáo bàn giao của một run Design (mockup
 * `design-handoff-report-card.html`).
 *
 * Thẻ gom những gì đã CHỐT: nhánh thiết kế + base sha, vị trí bản thiết kế (`.design/<slug>/…md`),
 * danh sách tệp đã ghi, kết quả soát độc lập, việc còn lại, rồi bốn lối ra. Chỉ hiện khi có dữ liệu
 * thật — thiếu thì hiện "chưa có báo cáo", không dựng số liệu giả.
 */
import { useState } from 'react'
import { useT } from '../../../i18n/context'
import { asRecord, asString, runLabel, type DesignRun, type Json } from '../../../lib/designMode'
import { useDesignStore } from '../../../store/designStore'
import { useUiStore } from '../../../store/uiStore'

function stringList(value: unknown): string[] {
  return (Array.isArray(value) ? value : []).filter((item): item is string => typeof item === 'string')
}

export function DesignHandoffCard({
  run,
  report = null,
}: {
  run: DesignRun
  report?: Json | null
}) {
  const t = useT()
  const setMode = useDesignStore((s) => s.setMode)
  const queueTurn = useDesignStore((s) => s.queueTurn)
  const showTab = useUiStore((s) => s.showTab)
  const [needsChoice, setNeedsChoice] = useState(false)
  const row = asRecord(report)
  const branchRow = asRecord(row.branch)
  const branch = asString(branchRow.name) || asString(row.branch) || run.touchList?.branch.name || ''
  const base = asString(branchRow.base) || run.touchList?.branch.base || ''
  const path = asString(row.path)
  const version = asString(row.version)
  const verdict = asString(row.verdict) || run.review?.verdict || ''
  const written = (run.touchList?.items ?? []).filter((item) => item.status === 'written')
  const remaining = stringList(row.nextSteps)
  const empty = !branch && !path && written.length === 0 && !verdict

  /**
   * "Dùng cho plan" (§5.7): thoát chế độ (nếu run còn hoạt động thì theo luật §5.1) rồi nộp MỘT lượt
   * main mang khối bàn giao. Lượt chỉ được nộp khi chế độ đã tắt — nếu server còn đòi chọn thoát thì
   * tin nhắn nằm trong hàng đợi của store và được xả ngay sau khi chủ nhà chọn xong.
   */
  async function useForPlan(): Promise<void> {
    setNeedsChoice(false)
    queueTurn(t('design.handoffUseForPlanTurn', { id: runLabel(run.designId), version: version || 'v1' }))
    const outcome = await setMode(false, 'command')
    if (outcome === 'exit-choice') setNeedsChoice(true)
    else if (outcome === 'error') queueTurn('')
  }

  if (empty) {
    return (
      <section data-testid="design-handoff-card" data-status="empty" className="rounded-lg border border-line bg-panel2 p-2 text-[11px]">
        <span className="font-medium text-fg">{t('design.handoffTitle')}</span>
        <p className="mt-0.5 text-muted">{t('design.handoffEmpty')}</p>
      </section>
    )
  }

  return (
    <section data-testid="design-handoff-card" data-status={verdict || 'pending'} className="rounded-lg border border-brand/30 bg-brand/5 p-2 text-[11px]">
      <header className="flex items-center justify-between gap-2">
        <span className="font-medium text-brand">{t('design.handoffTitle')}</span>
        {version && <span className="font-mono text-[10px] text-muted">v{version}</span>}
      </header>
      {branch && (
        <p data-testid="design-handoff-branch" className="mt-1 text-fg">
          <span className="text-muted">{t('design.handoffBranch')}: </span>
          <span className="font-mono">{branch}</span>
          {base && <span className="ml-1 text-muted">{t('design.handoffBase', { sha: base })}</span>}
        </p>
      )}
      {path && (
        <p data-testid="design-handoff-path" className="mt-0.5 text-fg">
          <span className="text-muted">{t('design.handoffDesign')}: </span>
          <span className="font-mono">{path}</span>
        </p>
      )}
      {written.length > 0 && (
        <div className="mt-1">
          <p className="text-muted">{t('design.handoffTouches')}</p>
          <ul className="mt-0.5 space-y-0.5">
            {written.map((item) => (
              <li key={item.id} data-path={item.path} className="truncate font-mono text-[10px] text-fg">
                {item.path}
              </li>
            ))}
          </ul>
        </div>
      )}
      {verdict && (
        <p
          data-testid="design-handoff-verdict"
          data-verdict={verdict}
          className="mt-1 text-fg"
        >
          <span className="text-muted">{t('design.handoffReview', { version: version || 'v1' })}: </span>
          {verdict === 'passed' ? t('design.handoffVerdictPassed') : t('design.handoffVerdictChanges')}
        </p>
      )}
      {remaining.length > 0 && (
        <div className="mt-1" data-testid="design-handoff-remaining">
          <p className="text-muted">{t('design.handoffRemaining')}</p>
          <ul className="mt-0.5 list-disc pl-4 text-fg">
            {remaining.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-1.5 flex flex-wrap gap-1">
        <button
          type="button"
          data-testid="design-handoff-open-branch"
          onClick={() => showTab('design')}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('design.handoffOpenBranch')}
        </button>
        <button
          type="button"
          data-testid="design-handoff-open-design"
          onClick={() => showTab('design')}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('design.handoffOpenDesign')}
        </button>
        <button
          type="button"
          data-testid="design-handoff-use-plan"
          onClick={() => void useForPlan()}
          className="rounded border border-line px-2 py-0.5 text-muted transition hover:text-fg cursor-pointer"
        >
          {t('design.handoffUseForPlan')}
        </button>
        <button
          type="button"
          data-testid="design-handoff-done"
          onClick={() => void setMode(false, 'toggle')}
          className="rounded border border-brand px-2 py-0.5 text-brand transition hover:bg-brand/10 cursor-pointer"
        >
          {t('design.handoffExit')}
        </button>
      </div>
      {needsChoice && (
        <p data-testid="design-handoff-hint" className="mt-1 text-[10px] text-amber-300">
          {t('design.handoffUseForPlanNeedsChoice')}
        </p>
      )}
    </section>
  )
}
