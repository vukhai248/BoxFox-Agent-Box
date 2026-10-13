/**
 * Thẻ đánh giá P1–P8 của tab Plan (mục 5, kế hoạch vòng 20).
 *
 * Vì sao phải có: `.reviews/` trên box rỗng mà giao diện vẫn hiện hai nhóm "approved" — nhãn cũ gán
 * theo VỊ TRÍ trong danh sách version chứ không theo quyết định nào của người dùng. Thẻ này đọc
 * `evaluation` thật do `plan_eval.py` chấm: mỗi chiều một dòng trạng thái + số đo, một dòng tổng,
 * và khi bị cổng cứng chặn thì nói rõ `written: false` + mã từ chối + cách sửa.
 *
 * Bản bị chặn được nhận ra từ `rejected`/`gatesFailed`, KHÔNG từ `hardGate`: theo
 * `scripts/eval/rubric.py::hard_gate_ok`, `hardGate: true` nghĩa là MỌI cổng cứng đều đạt.
 */
import { Shield } from 'lucide-react'
import { useT, type TKey } from '../../i18n/context'
import {
  EVAL_DIMENSIONS,
  PLAN_MAX_CHARS,
  planCount,
  planMeasure,
  planMeasureText,
  planStamp,
} from '../../lib/plans'
import type { PlanEvalDimension, PlanEvalLevel, PlanEvaluation } from '../../lib/plans'

interface PlanEvalCardProps {
  evaluation: PlanEvaluation | null
  /** `false` = chỉ mục box không đọc được: chưa biết bản này có được chấm hay không. */
  indexAvailable: boolean
  /** Nhóm đang xem, dùng khi payload thiếu `identity`. */
  identity: string
}

const DIMENSION_LABELS: Record<PlanEvalDimension, TKey> = {
  P1: 'plan.eval.P1',
  P2: 'plan.eval.P2',
  P3: 'plan.eval.P3',
  P4: 'plan.eval.P4',
  P5: 'plan.eval.P5',
  P6: 'plan.eval.P6',
  P7: 'plan.eval.P7',
  P8: 'plan.eval.P8',
}

const HEADER_SOURCE_LABELS: Record<string, TKey> = {
  model: 'plan.eval.headerSource.model',
  synthesized: 'plan.eval.headerSource.synthesized',
  mismatch: 'plan.eval.headerSource.mismatch',
}

const VERDICT_LABELS: Record<string, TKey> = {
  pass: 'plan.eval.verdict.pass',
  conditional: 'plan.eval.verdict.conditional',
  fail: 'plan.eval.verdict.fail',
}

const VERDICT_CLASSES: Record<string, string> = {
  pass: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/40',
  conditional: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/40',
  fail: 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/40',
}

/** Mức 0/1/2 → màu badge; `null` (payload thiếu) giữ màu trung tính chứ không đoán là 0. */
const LEVEL_CLASSES: Record<'0' | '1' | '2' | 'unknown', string> = {
  '2': 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30',
  '1': 'bg-amber-500/15 text-amber-300 border border-amber-500/40',
  '0': 'bg-rose-500/15 text-rose-400 border border-rose-500/40',
  unknown: 'bg-panel2 text-muted border border-line',
}

const MONO_BADGE = 'rounded-full bg-panel px-2 py-0.5 text-[11px] font-mono text-brand border border-line'

export function PlanEvalCard({ evaluation, indexAvailable, identity }: PlanEvalCardProps) {
  const t = useT()

  // Chỉ mục không đọc được: chưa biết bản này có được chấm hay không, nên chỉ nói đúng thế —
  // không hiện một thẻ điểm rỗng và cũng không gán cho nó nhãn `legacy`.
  if (!indexAvailable) return <DimRow testId="plan-eval-unavailable" text={t('plan.eval.unavailable')} chip={t('plan.eval.unavailableChip')} />

  // Bản cũ chưa từng được chấm: một dòng nhắc mờ, không khung rỗng, không dải cảnh báo.
  if (!evaluation) return <DimRow testId="plan-eval-empty" text={t('plan.eval.legacy')} chip={t('plan.eval.legacyChip')} />

  // Bị chặn = có mã từ chối, hoặc có cổng cứng ở mức 0 (không suy từ `hardGate`).
  const blocked = evaluation.rejected !== null || evaluation.gatesFailed.length > 0
  const stamp = planStamp(evaluation.evaluatedAt)
  const rubric = evaluation.rubric
  const score = evaluation.total === null ? t('plan.eval.scoreUnknown') : `${planCount(evaluation.total)}/${planCount(evaluation.maxTotal)}`
  const keywords = planMeasure(evaluation.measures, 'noteKeywords')
  const echoed = planMeasure(evaluation.measures, 'noteKeywordsEchoed')

  return (
    <div
      data-component-id="plan-eval-card"
      data-testid="plan-eval-card"
      className="rounded-lg border border-line bg-panel2/30 p-3.5 space-y-2.5"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[11px] font-semibold text-fg uppercase tracking-wider">
          {blocked
            ? t('plan.eval.titleOf', { version: evaluation.version ?? '—' })
            : t('plan.eval.title')}
        </h2>
        <div className="flex items-center gap-1.5">
          {blocked && (
            <span
              data-component-id="plan-eval-written"
              className="rounded-full px-1.5 py-px text-[11px] font-semibold bg-rose-500/15 text-rose-400 border border-rose-500/40"
            >
              {t('plan.eval.notWritten')}
            </span>
          )}
          {evaluation.verdict && (
            <span
              data-component-id="plan-verdict-chip"
              data-testid="plan-verdict-chip"
              className={`rounded px-1.5 py-px text-[11px] font-semibold ${VERDICT_CLASSES[evaluation.verdict]}`}
            >
              {t(VERDICT_LABELS[evaluation.verdict])}
            </span>
          )}
          <span className={MONO_BADGE}>{[score, rubric].filter(Boolean).join(' · ')}</span>
        </div>
      </div>

      <p className="text-[11px] text-muted leading-relaxed">
        {blocked ? t('plan.eval.rubricRejected') : t('plan.eval.rubric')}
      </p>

      {blocked && <MeasuresBox evaluation={evaluation} />}

      <div className="grid grid-cols-2 gap-1.5">
        {EVAL_DIMENSIONS.map((dimension) => {
          const level = evaluation.levels[dimension]
          const detail = criterionDetail(dimension, evaluation, identity, t)
          return (
            <div
              key={dimension}
              data-component-id={`plan-eval-${dimension.toLowerCase()}`}
              data-testid={`plan-eval-${dimension.toLowerCase()}`}
              className="rounded-md border border-line bg-panel p-2 space-y-1"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="font-mono text-[11px] font-bold text-muted">{dimension}</span>
                  <span className="truncate text-[11px] font-medium text-fg">
                    {t(DIMENSION_LABELS[dimension])}
                  </span>
                </span>
                <span
                  className={`shrink-0 rounded px-1.5 py-px font-mono text-[11px] font-semibold ${
                    LEVEL_CLASSES[levelText(level)]
                  }`}
                >
                  {level === null ? '?/2' : `${level}/2`}
                </span>
              </div>
              <div className="truncate font-mono text-[11px] text-muted" title={detail}>
                {detail}
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex items-center justify-between gap-2 border-t border-line pt-2 font-mono text-[11px] text-muted">
        <span data-component-id="plan-eval-note-keywords">
          {keywords
            ? t('plan.eval.noteKeywords', { echoed: echoed ?? 0, keywords })
            : t('plan.eval.noteKeywordsNone')}
        </span>
        {stamp && (
          <span>{blocked ? t('plan.eval.measuredAt', { stamp }) : t('plan.eval.evaluatedAt', { stamp })}</span>
        )}
      </div>
    </div>
  )
}

function levelText(level: PlanEvalLevel | null): '0' | '1' | '2' | 'unknown' {
  return level === 0 || level === 1 || level === 2 ? (`${level}` as '0' | '1' | '2') : 'unknown'
}

/** Dòng nhắc một hàng: bản chưa chấm / chưa đọc được chỉ mục. Không khung, không cảnh báo. */
function DimRow({ testId, text, chip }: { testId: string; text: string; chip: string }) {
  return (
    <div
      data-component-id={testId}
      data-testid={testId}
      className="flex items-center gap-2 rounded-lg border border-line bg-panel2/30 px-3.5 py-2.5 text-[11px] text-muted"
    >
      <Shield className="size-3.5 shrink-0" />
      <span className="min-w-0 flex-1">{text}</span>
      <span className="rounded-full bg-panel px-2 py-0.5 text-[11px] font-mono text-muted border border-line">
        {chip}
      </span>
    </div>
  )
}

/**
 * Số đo của lần chấm bị chặn. Cố ý in đúng giá trị `hardGate` thay vì giá trị mockup ghi: mockup
 * hiện `hardGate: true` cho một bản bị chặn, còn `plan_eval.py` đặt `true` = mọi cổng đều đạt, nên
 * đọc thẳng payload mới không nói ngược với chính bản chấm.
 */
function MeasuresBox({ evaluation }: { evaluation: PlanEvaluation }) {
  const measures = evaluation.measures
  const chars = planMeasure(measures, 'chars')
  const steps = planMeasure(measures, 'steps')
  const anchored = planMeasure(measures, 'stepsAnchored')
  const facts = planMeasure(measures, 'externalFacts')
  const sourced = planMeasure(measures, 'externalFactsSourced')
  const overMax = chars !== null && chars > PLAN_MAX_CHARS
  return (
    <div
      data-component-id="plan-eval-measures"
      data-testid="plan-eval-measures"
      className="grid grid-cols-2 gap-1.5 rounded-md border border-line bg-panel p-2.5 font-mono text-[11px] text-muted"
    >
      <div>
        written: <span className="text-rose-400">{String(evaluation.written)}</span>
      </div>
      <div>
        hardGate: <span className={evaluation.hardGate ? 'text-emerald-400' : 'text-rose-400'}>{String(evaluation.hardGate)}</span>
      </div>
      {evaluation.gatesFailed.length > 0 && (
        <div>
          gatesFailed: <span className="text-rose-400">{evaluation.gatesFailed.join(', ')}</span>
        </div>
      )}
      <div>
        version: <span className="text-fg">{evaluation.version ?? '—'}</span> · parentVersion:{' '}
        <span className="text-fg">{evaluation.parentVersion ?? '—'}</span>
      </div>
      <div>
        chars:{' '}
        <span className={overMax ? 'text-rose-400' : 'text-fg'}>{planCount(chars) ?? '—'}</span>
        {overMax && <> &gt; {planCount(PLAN_MAX_CHARS)}</>}
      </div>
      <div>
        steps: {planCount(steps) ?? '—'} · stepsAnchored: {planCount(anchored) ?? '—'}
      </div>
      <div>
        externalFacts: {planCount(facts) ?? '—'} · externalFactsSourced: {planCount(sourced) ?? '—'}
      </div>
    </div>
  )
}


/** Dòng số đo của một chiều: ưu tiên `evidence` thật của bản chấm, thiếu thì ghép từ `measures`. */
function criterionDetail(
  dimension: PlanEvalDimension,
  evaluation: PlanEvaluation,
  identity: string,
  t: ReturnType<typeof useT>,
): string {
  const measures = evaluation.measures
  const evidence = evaluation.evidence.find((item) => item.code === dimension)?.excerpt
  const level = evaluation.levels[dimension]
  switch (dimension) {
    case 'P1': {
      const source = planMeasureText(measures, 'headerSource')
      const label = (source && HEADER_SOURCE_LABELS[source]) ? t(HEADER_SOURCE_LABELS[source]) : t('plan.eval.headerSource.unknown')
      return `versionHeader · ${evidence ?? label}`
    }
    case 'P2': {
      if (evaluation.parentVersion === null) return `parentChain · ${t('plan.eval.parentNotRequired')}`
      if (level === 2) return `parentChain · ${t('plan.eval.parentChangeSection', { version: evaluation.parentVersion })}`
      return `parentChain · ${evidence ?? t('plan.eval.parentUntraceable', { version: evaluation.parentVersion })}`
    }
    case 'P3':
      return `structure · ${evidence ?? (level === 2 ? t('plan.eval.structureOk') : t('plan.eval.structureThin'))}`
    case 'P4': {
      const steps = planMeasure(measures, 'steps')
      if (steps === null) return `executability · ${t('plan.eval.stepsAnchoredUnknown')}`
      const anchored = planMeasure(measures, 'stepsAnchored') ?? 0
      return `executability · ${t('plan.eval.stepsAnchored', { anchored, steps })}`
    }
    case 'P5': {
      const layer = evaluation.layer.P5 === 'judge' ? 'plan.eval.layer.judge' : 'plan.eval.layer.oracle'
      return `scopeHonesty · ${t(layer)}`
    }
    case 'P6': {
      const facts = planMeasure(measures, 'externalFacts')
      if (!facts) return `evidence · ${t('plan.eval.externalFactsNone')}`
      const sourced = planMeasure(measures, 'externalFactsSourced') ?? 0
      return `evidence · ${t('plan.eval.externalFactsSourced', { sourced, facts })}`
    }
    case 'P7': {
      const chars = planMeasure(measures, 'chars')
      const ratio = planMeasure(measures, 'repetition')
      const parts: string[] = []
      if (chars !== null) {
        const value = planCount(chars) ?? `${chars}`
        parts.push(
          chars > PLAN_MAX_CHARS
            ? t('plan.eval.charsOverMax', { chars: value, max: planCount(PLAN_MAX_CHARS) ?? '' })
            : t('plan.eval.chars', { chars: value }),
        )
      }
      if (ratio !== null) parts.push(t('plan.eval.repetition', { ratio: ratio.toFixed(2) }))
      return `signal · ${parts.join(' · ') || t('plan.eval.stepsAnchoredUnknown')}`
    }
    case 'P8':
      return `identityHygiene · ${evidence ?? t('plan.eval.identityMatch', { identity: evaluation.identity || identity })}`
    default:
      return dimension
  }
}
