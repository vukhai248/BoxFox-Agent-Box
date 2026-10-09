/**
 * Thẻ xin quyền (PermissionCard).
 *
 * Một thẻ, hai đường:
 *  • Đường MOCK (transport demo): năm phần đúng thứ tự —
 *      1. Tool + tham số
 *      2. Nội dung nguyên văn (write_file hiện diff tự viết)
 *      3. Lý do — bằng tiếng người
 *      4. Nguồn gốc (derived_from) — bấm được
 *      5. Nút quyết định: 3 nút cho sạch, 4 nút cho bẩn
 *    Bộ đếm ngược 10 phút là của RIÊNG đường này. Hết giờ → "đã quá hạn — tính là
 *    TỪ CHỐI". Mock rút ngắn bằng hằng số, nhưng mặc định phải là 10 phút thật.
 *  • Đường THẬT (`decision_requested` của harness): bố cục/lớp CSS y hệt, nhưng
 *    bộ đếm đi theo `deadline` (epoch giây) do server gửi xuống — `ask_user` 300 s,
 *    `request_approval` 600 s — không có hạn 10 phút nào do giao diện tự bịa.
 */
import { useMemo, useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { useT } from '../i18n/context'
import { useNow } from '../hooks/useNow'
import { useAgentStore } from '../store/agentStore'
import { useUiStore } from '../store/uiStore'
import { PlainText, Chip, SectionLabel } from './ui'
// Integrity/Confidentiality values are used implicitly via PermissionRequest fields.
import type { PermissionRequest } from '../types/agent'
import type { PermissionButtonId } from '../lib/permissions'
import { getPermissionButtons } from '../lib/permissions'
import type { DiffLine } from '../types/agent'
import type { DecisionEntry, DecisionOption, InterviewReply } from '../store/harnessChatStore'
import { InterviewCard } from './InterviewCard'

export interface PermissionCardProps {
  /** Thẻ của transport mock (đường demo) — giữ nguyên hành vi cũ. */
  request?: PermissionRequest
  /** Quyết định THẬT của agent (`decision_requested`/`decision_resolved`). */
  decision?: DecisionEntry
  /**
   * Trả lời quyết định thật; `choice` là `id` trong `decision.options`.
   * P4 — lựa chọn tự nhập (`allowFreeText`) gửi kèm `note` là chữ chủ nhà đã gõ.
   */
  onAnswer?: (choice: string, note?: string, answers?: InterviewReply[]) => void
  /** Đang gửi câu trả lời → hàng này tạm khoá. */
  busy?: boolean
}

/**
 * Một thẻ, hai nguồn: thẻ xin quyền của transport mock (năm phần, nguyên trạng)
 * và quyết định thật của harness (cùng bố cục, cùng lớp CSS, dữ liệu thật).
 */
export function PermissionCard({ request, decision, onAnswer, busy = false }: PermissionCardProps) {
  if (decision?.kind === 'interview') return <InterviewCard decision={decision} onAnswer={onAnswer} busy={busy} />
  if (decision) return <DecisionCard decision={decision} onAnswer={onAnswer} busy={busy} />
  if (!request) return null
  return <TransportPermissionCard request={request} />
}

function TransportPermissionCard({ request }: { request: PermissionRequest }) {
  const t = useT()
  const now = useNow()
  const sendCommand = useAgentStore((s) => s.sendCommand)
  const openSource = useUiStore((s) => s.openSource)
  const [resolved, setResolved] = useState(false)

  const isResolved = resolved || request.status !== 'dang_cho'

  // Đếm ngược từ expires_at
  const expiresAtMs = useMemo(() => Date.parse(request.expires_at), [request.expires_at])
  const remaining = useMemo(() => Math.max(0, expiresAtMs - now), [expiresAtMs, now])
  const timedOut = remaining <= 0
  const remainingSec = Math.ceil(remaining / 1000)
  const remainingMin = Math.floor(remainingSec / 60)
  const remainingSecPart = remainingSec % 60

  const effectiveResolved = isResolved || timedOut

  const buttons = useMemo(
    () => (effectiveResolved ? [] : getPermissionButtons(request.context_dirty)),
    [effectiveResolved, request.context_dirty],
  )

  const handleClick = (button: PermissionButtonId) => {
    setResolved(true)
    sendCommand({
      type: 'permission_response',
      request_id: request.request_id,
      button,
    })
  }

  const isWriteFile = request.tool_name === 'write_file'

  return (
    <div
      className={`rounded-lg border-2 p-3 shadow-lg ${
        effectiveResolved
          ? 'border-line bg-bg'
          : timedOut
            ? 'border-red-500/50 bg-red-50 dark:bg-red-950/20'
            : 'border-amber-500/50 bg-bg shadow-amber-500/10'
      }`}
    >
      {/* 1. Tool + tham số */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Chip tone="brand">{request.tool_name}</Chip>
        <span className="text-[11px] font-mono text-muted">
          {Object.entries(request.params)
            .map(([k, v]) => `${k}=${v}`)
            .join('  ')}
        </span>
        {effectiveResolved && (
          <Chip
            tone={
              request.decision === 'tu_choi' || timedOut ? 'danger' : 'neutral'
            }
          >
            {timedOut
              ? 'Đã quá hạn'
              : request.decision
                ? t(
                    `permission.button.${request.decision}` as 'permission.button.cho_phep_mot_lan',
                  )
                : 'Đã quyết định'}
          </Chip>
        )}
      </div>

      {/* 2. Nội dung nguyên văn */}
      <SectionLabel>Nội dung</SectionLabel>
      <div className="mb-2 max-h-48 overflow-auto rounded border border-line bg-panel2 p-2">
        {isWriteFile && request.diff ? (
          <DiffView diff={request.diff} filePath={String(request.params['path'] ?? '')} />
        ) : (
          <PlainText text={request.raw_content ?? ''} />
        )}
      </div>

      {/* 3. Lý do */}
      <SectionLabel>Vì sao phải hỏi</SectionLabel>
      <p className="mb-2 text-[12px] leading-relaxed">{request.reason}</p>

      {/* 4. Nguồn gốc */}
      {request.derived_from.length > 0 && (
        <>
          <SectionLabel>Nguồn gốc</SectionLabel>
          <div className="mb-2 flex flex-wrap items-center gap-1.5">
            {request.derived_from.map((labelId) => (
              <button
                key={labelId}
                type="button"
                onClick={() => openSource(labelId)}
                className="rounded bg-panel2 px-1.5 py-px text-[11px] font-mono text-brand hover:underline"
              >
                {labelId}
              </button>
            ))}
          </div>
        </>
      )}

      {/* 5. Nút */}
      {!effectiveResolved && (
        <div className="flex flex-wrap items-center gap-2">
          {buttons.map((button) => (
            <PermissionButton
              key={button}
              button={button}
              onClick={handleClick}
            />
          ))}
          {/* Đồng hồ đếm ngược */}
          <span
            className={`ml-auto text-[11px] font-mono tabular-nums ${
              remaining < 60000 ? 'text-red-500' : 'text-muted'
            }`}
          >
            {remainingMin}:{String(remainingSecPart).padStart(2, '0')}
          </span>
        </div>
      )}
      {timedOut && !isResolved && (
        <p className="mt-2 text-[12px] font-medium text-red-600 dark:text-red-400">
          Yêu cầu đã quá hạn 10 phút — tự động tính là TỪ CHỐI.
        </p>
      )}
    </div>
  )
}

/**
 * Quyết định thật của agent. Cùng bố cục năm phần với thẻ mock: nhãn loại +
 * nội dung, "vì sao phải hỏi", các lựa chọn server gửi kèm và bộ đếm ngược
 * theo đúng `deadline` (epoch giây) — không có hạn 10 phút nào do giao diện bịa.
 */
function DecisionCard({
  decision,
  onAnswer,
  busy,
}: {
  decision: DecisionEntry
  onAnswer?: (choice: string, note?: string) => void
  busy: boolean
}) {
  const t = useT()
  const now = useNow()

  const deadlineMs = decision.deadline !== null ? decision.deadline * 1000 : null
  const remaining = deadlineMs === null ? null : Math.max(0, deadlineMs - now)
  const remainingSec = remaining === null ? null : Math.ceil(remaining / 1000)
  const remainingMin = remainingSec === null ? null : Math.floor(remainingSec / 60)
  const remainingSecPart = remainingSec === null ? null : remainingSec % 60

  const expired = decision.status === 'expired' || decision.resolvedReason === 'timeout'
  const isPending = decision.status === 'pending' && decision.actionable !== false
  const chosenLabel =
    decision.choice === null
      ? null
      : (decision.options.find((option) => option.id === decision.choice)?.label ?? decision.choice)
  const headline = decision.question ?? decision.action ?? ''

  const headlineLabel = decision.kind === 'budget' ? t('continuity.budgetDecision') : decision.kind === 'approval' ? t('decisions.kind.approval') : t('decisions.kind.question')

  const statusChip = () => {
    if (expired) return { tone: 'danger' as const, label: t('permission.timedOut') }
    if (decision.status === 'cancelled') return { tone: 'danger' as const, label: t('decisions.status.cancelled') }
    if (decision.status === 'rejected') return { tone: 'danger' as const, label: t('decisions.status.rejected') }
    // P4 — chữ tự nhập: đã chốt nhưng TRUNG TÍNH, không mượn nhãn "đã duyệt" của một cái gật đầu.
    if (decision.status === 'answered') return { tone: 'neutral' as const, label: t('decisions.status.answered') }
    if (decision.status === 'approved') return { tone: 'neutral' as const, label: t('decisions.status.approved') }
    return null
  }
  const chip = statusChip()

  return (
    <div
      className={`rounded-lg border-2 p-3 shadow-lg ${
        !isPending
          ? 'border-line bg-bg'
          : expired
            ? 'border-red-500/50 bg-red-50 dark:bg-red-950/20'
            : 'border-amber-500/50 bg-bg shadow-amber-500/10'
      }`}
    >
      {/* 1. Loại + đối tượng */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Chip tone="brand">{headlineLabel}</Chip>
        <span className="min-w-0 truncate text-[11px] font-mono text-muted" title={headline}>
          {headline}
        </span>
        {chip && <Chip tone={chip.tone}>{chip.label}</Chip>}
        {chosenLabel && <Chip tone="neutral">{chosenLabel}</Chip>}
      </div>

      {/* 2. Nội dung */}
      <SectionLabel>{t('permission.content')}</SectionLabel>
      <div className="mb-2 max-h-48 overflow-auto rounded border border-line bg-panel2 p-2">
        <PlainText text={headline} />
      </div>

      {decision.kind === 'budget' && <div className="mb-2 text-xs text-amber-400">
        <p>{t('continuity.budgetCheckpoint')}</p>
        {decision.options.filter(option => option.budgetDelta).map(option => <p key={option.id}>
          {option.label}: +{option.budgetDelta!.steps} {t('continuity.steps')} · +{option.budgetDelta!.activeTimeMs / 60000} {t('continuity.activeMinutes')}
        </p>)}
      </div>}
      {/* 3. Vì sao phải hỏi */}
      {decision.reason && (
        <>
          <SectionLabel>{t('permission.reason')}</SectionLabel>
          <p className="mb-2 text-[12px] leading-relaxed">{decision.reason}</p>
        </>
      )}

      {/* 4. Ghi chú kèm theo câu trả lời (nếu server trả về) */}
      {decision.note && (
        <>
          <SectionLabel>{t('decisions.noteLabel')}</SectionLabel>
          <p className="mb-2 text-[12px] leading-relaxed">{decision.note}</p>
        </>
      )}

      {/* 5. Lựa chọn + bộ đếm ngược theo deadline của server */}
      {isPending ? (
        <div className="flex flex-wrap items-center gap-2">
          {decision.options.map((option) =>
            // P4 — lựa chọn tự nhập mở ô gõ chữ rồi mới gửi; chọn nó mà bỏ trống là vô nghĩa
            // (route cũng từ chối bằng `DECISION_NOTE_REQUIRED`), nên nút gửi bị khoá khi rỗng.
            option.allowFreeText ? (
              <DecisionFreeTextOption
                key={option.id}
                option={option}
                disabled={busy}
                onSubmit={(choice, note) => onAnswer?.(choice, note)}
              />
            ) : (
              <DecisionOptionButton
                key={option.id}
                option={option}
                disabled={busy}
                onClick={() => onAnswer?.(option.id)}
              />
            ),
          )}
          {remainingMin !== null && remainingSecPart !== null && (
            <span
              className={`ml-auto text-[11px] font-mono tabular-nums ${
                remaining !== null && remaining < 60000 ? 'text-red-500' : 'text-muted'
              }`}
            >
              {remainingMin}:{String(remainingSecPart).padStart(2, '0')}
            </span>
          )}
          {busy && (
            <span className="flex items-center gap-1 text-[11px] text-muted" aria-live="polite">
              <LoaderCircle className="size-3 animate-spin" />
              <span>{t('decisions.sendingAnswer')}</span>
            </span>
          )}
        </div>
      ) : (
        expired && (
          <p className="mt-2 text-[12px] font-medium text-red-600 dark:text-red-400">
            {t('decisions.expiredNote')}
          </p>
        )
      )}
    </div>
  )
}

function DecisionOptionButton({
  option,
  disabled,
  onClick,
}: {
  option: DecisionOption
  disabled: boolean
  onClick: () => void
}) {
  const style =
    option.kind === 'reject'
      ? 'border-red-300 text-red-700 hover:bg-red-50 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/30'
      : option.kind === 'alternative'
        ? 'border-amber-400 text-amber-800 hover:bg-amber-50 dark:border-amber-600 dark:text-amber-200 dark:hover:bg-amber-950/30'
        : 'border-brand/50 text-brand hover:bg-brand/10'

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`rounded-md border px-2.5 py-1 text-[12px] font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${style}`}
    >
      {option.label}
    </button>
  )
}

/**
 * P4 — lựa chọn "tự nhập": nút mở ô chữ, chữ đã gõ đi cùng `choice` trong `note`.
 * `id` gửi đi vẫn là `option.id` (runtime thêm `id='other'` cho MỌI quyết định).
 */
function DecisionFreeTextOption({
  option,
  disabled,
  onSubmit,
}: {
  option: DecisionOption
  disabled: boolean
  onSubmit: (choice: string, note: string) => void
}) {
  const t = useT()
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const ready = text.trim().length > 0

  return (
    <div className="flex w-full flex-col gap-1.5" data-testid="decision-free-text">
      <DecisionOptionButton option={option} disabled={disabled} onClick={() => setOpen(true)} />
      {open && (
        <div className="flex items-end gap-2">
          <textarea
            data-testid="decision-free-text-input"
            value={text}
            rows={2}
            autoFocus
            disabled={disabled}
            placeholder={t('decisions.freeTextPlaceholder')}
            onChange={(event) => setText(event.target.value)}
            className="min-h-9 w-full resize-y rounded-md border border-line bg-panel2 px-2 py-1 text-[12px] text-fg outline-none focus:border-brand/60"
          />
          <button
            type="button"
            data-testid="decision-free-text-submit"
            disabled={disabled || !ready}
            onClick={() => onSubmit(option.id, text.trim())}
            className="rounded-md border border-brand/50 px-2.5 py-1 text-[12px] font-medium text-brand transition hover:bg-brand/10 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {t('decisions.freeTextSubmit')}
          </button>
        </div>
      )}
    </div>
  )
}

function PermissionButton({
  button,
  onClick,
}: {
  button: PermissionButtonId
  onClick: (button: PermissionButtonId) => void
}) {
  const t = useT()

  const style =
    button === 'tu_choi'
      ? 'border-red-300 text-red-700 hover:bg-red-50 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-950/30'
      : button === 'chuan_thuan_artifact'
        ? 'border-amber-400 text-amber-800 hover:bg-amber-50 dark:border-amber-600 dark:text-amber-200 dark:hover:bg-amber-950/30'
        : 'border-brand/50 text-brand hover:bg-brand/10'

  return (
    <button
      type="button"
      onClick={() => onClick(button)}
      className={`rounded-md border px-2.5 py-1 text-[12px] font-medium transition ${style}`}
    >
      {t(`permission.button.${button}` as 'permission.button.cho_phep_mot_lan')}
    </button>
  )
}

/* ------------------------------------------------------------------ */
/* Diff tự viết (không thư viện ngoài)                                 */
/* ------------------------------------------------------------------ */

function DiffView({ diff, filePath }: { diff: DiffLine[]; filePath: string }) {
  return (
    <div className="overflow-x-auto font-mono text-[11px] leading-relaxed">
      <p className="mb-1 border-b border-line pb-1 text-[10px] text-muted">{filePath}</p>
      {diff.map((dline, index) => (
        <div
          key={index}
          className={`whitespace-pre ${
            dline.kind === 'them'
              ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
              : dline.kind === 'bot'
                ? 'bg-red-500/10 text-red-700 dark:text-red-300'
                : ''
          }`}
        >
          <span className="mr-2 inline-block w-5 select-none text-right text-muted">
            {dline.kind === 'them' ? '+' : dline.kind === 'bot' ? '-' : ' '}
          </span>
          {dline.text}
        </div>
      ))}
    </div>
  )
}
