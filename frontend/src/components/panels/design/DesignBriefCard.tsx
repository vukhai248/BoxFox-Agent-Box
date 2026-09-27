/**
 * Thẻ brief + danh sách chạm của một run Design (P1).
 *
 * Hai phần tách rõ vì hai việc khác nhau: brief là thứ Design Lead CHỐT với người dùng; danh sách
 * chạm là danh sách ĐƯỜNG DẪN sẽ bị ghi vào dự án, và chỉ được ghi SAU khi người dùng duyệt (nút
 * "Duyệt danh sách chạm" gửi `revision` đang thấy để một thẻ cũ không ghi đè bản mới).
 */
import { Check } from 'lucide-react'
import { useT, type TKey } from '../../../i18n/context'
import { useDesignStore } from '../../../store/designStore'
import { runLabel, type DesignRun } from '../../../lib/designMode'

/** Nhãn của sáu trường brief — một chỗ để component không phải ghép khoá i18n động. */
const BRIEF_LABEL_KEY: Record<string, TKey> = {
  goal: 'design.briefGoal',
  screen: 'design.briefScreen',
  platform: 'design.briefPlatform',
  project: 'design.briefProject',
  style: 'design.briefStyle',
  constraints: 'design.briefConstraints',
}

export function DesignBriefCard({ run, brief }: { run: DesignRun; brief?: Record<string, unknown> }) {
  const t = useT()
  const approve = useDesignStore((s) => s.approveTouchList)
  const source = brief ?? {}
  const rows: [string, string][] = [
    ['goal', typeof source.goal === 'string' ? source.goal : run.goal],
    ['screen', typeof source.screen === 'string' ? source.screen : ''],
    ['platform', typeof source.platform === 'string' ? source.platform : ''],
    ['project', typeof source.project === 'string' ? source.project : ''],
    ['style', typeof source.style === 'string' ? source.style : ''],
    ['constraints', Array.isArray(source.constraints) ? source.constraints.join(' · ') : ''],
  ]
  const filled = rows.filter(([, value]) => value.trim() !== '')
  const touchList = run.touchList
  const approved = touchList?.approvedAt ?? null
  return (
    <section
      data-testid="design-brief-card"
      data-approved={approved ? 'true' : 'false'}
      className="rounded-lg border border-line bg-panel2 p-2 text-[11px]"
    >
      <header className="flex items-center justify-between gap-2">
        <span className="font-medium text-fg">{t('design.briefTitle', { id: runLabel(run.designId) })}</span>
        <span className="text-muted">{t('design.timelinePhase', { step: run.step })}</span>
      </header>
      {filled.length === 0 ? (
        <p className="mt-1 text-muted">{t('design.briefEmpty')}</p>
      ) : (
        <dl className="mt-1 space-y-0.5">
          {filled.map(([key, value]) => (
            <div key={key} className="flex gap-2">
              <dt className="w-28 shrink-0 text-muted">{t(BRIEF_LABEL_KEY[key] ?? 'design.briefGoal')}</dt>
              <dd className="min-w-0 flex-1 text-fg">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      <div className="mt-2 border-t border-line pt-1.5">
        <p className="font-medium text-fg">
          {t('design.touchListTitle', { revision: touchList?.revision ?? 0 })}
        </p>
        {approved ? (
          <p data-testid="design-touch-list-approved" className="text-muted">
            {t('design.touchListApproved', { at: approved })}
          </p>
        ) : (
          <p data-testid="design-touch-list-waiting" className="text-muted">{t('design.touchListWaiting')}</p>
        )}
        {touchList && touchList.items.length > 0 ? (
          <ul className="mt-1 space-y-0.5">
            {touchList.items.map((item) => (
              <li key={item.id} className="flex items-baseline gap-1.5" data-status={item.status}>
                <span className="rounded border border-line px-1 text-[10px] text-muted">
                  {item.kind === 'new' ? t('design.touchKindNew') : t('design.touchKindInsert')}
                </span>
                <code className="truncate font-mono text-[10px] text-fg" title={item.path}>{item.path}</code>
                {item.reason && <span className="truncate text-muted">{item.reason}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-muted">{t('design.touchListEmpty')}</p>
        )}
        {touchList && !approved && touchList.items.length > 0 && (
          <button
            type="button"
            data-testid="design-touch-list-approve"
            onClick={() => void approve(run.designId, touchList.revision)}
            className="mt-1.5 inline-flex items-center gap-1 rounded border border-line bg-panel px-2 py-0.5 transition hover:border-brand cursor-pointer"
          >
            <Check className="size-3" />
            {t('design.touchApprove')}
          </button>
        )}
      </div>
    </section>
  )
}
