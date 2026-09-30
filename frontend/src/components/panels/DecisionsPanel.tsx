/**
 * Khung Quyết định & Phê duyệt Quyền (Decisions & Approvals Hub).
 *
 * Không còn dữ liệu demo: mọi hàng đọc thẳng từ `decision_requested` /
 * `decision_resolved` thật của harness (`useHarnessChatStore.decisions`) và trả
 * lời bằng `POST /api/agent/sessions/{id}/decisions` — không đi qua transport
 * mock, nên không có bộ đếm hạn nào do giao diện tự bịa.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ShieldAlert, CheckCircle2, XCircle, MessageSquare } from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { pendingDecisions, useHarnessChatStore } from '../../store/harnessChatStore'
import type { DecisionEntry, DecisionStatus, InterviewReply } from '../../store/harnessChatStore'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n/context'
import { useNow } from '../../hooks/useNow'
import { PermissionCard } from '../PermissionCard'
import { INTERVIEW_DECIDE, INTERVIEW_SUBMIT, interviewAnswerLabel } from '../InterviewCard'

type DecisionsFilter = 'all' | 'pending' | 'resolved'

/** Màu trạng thái dùng chung: emerald = đã duyệt, đỏ = từ chối/quá hạn, xám = huỷ/trả lời tự nhập. */
const STATUS_TONE: Record<DecisionStatus, string> = {
  approved: 'bg-emerald-500/15 text-emerald-400',
  rejected: 'bg-rose-500/15 text-rose-400',
  // P4 — chữ tự nhập: đã chốt nhưng trung tính, không nhuộm xanh "đã duyệt" cũng không nhuộm đỏ "từ chối".
  answered: 'bg-zinc-500/15 text-zinc-300',
  expired: 'bg-rose-500/15 text-rose-400',
  cancelled: 'bg-zinc-500/15 text-zinc-400',
  pending: 'bg-amber-500/20 text-amber-300',
}

export function DecisionsPanel() {
  const t = useT()
  const now = useNow()
  const chatId = useAgentStore((s) => s.activeSessionId)
  const storedDecisions = useHarnessChatStore((s) => s.decisions[chatId])
  const answerDecision = useHarnessChatStore((s) => s.answerDecision)
  const decisionsTarget = useUiStore((s) => s.tabIntentTargets.decisions)

  const [activeFilter, setActiveFilter] = useState<DecisionsFilter>('pending')
  const [sendingId, setSendingId] = useState<string | null>(null)
  // Lỗi của lần trả lời vừa rồi. `answerDecision` đẩy lỗi của route vào
  // `sessions[id].error` (khung chat), nhưng người dùng đang thao tác Ở ĐÂY nên
  // panel phải tự hiện lỗi — nếu không hàng chỉ quay về "đang chờ" như chưa có
  // chuyện gì xảy ra (đường kế hoạch đã có dải `plan-review-error`).
  const [answerError, setAnswerError] = useState<{ id: string; message: string } | null>(null)

  const decisions = useMemo(() => storedDecisions ?? [], [storedDecisions])
  const pendingList = useMemo(() => pendingDecisions(decisions), [decisions])
  const resolvedList = useMemo(
    () => decisions.filter((decision) => decision.status !== 'pending').slice().reverse(),
    [decisions],
  )

  const totalPending = pendingList.length
  const totalResolved = resolvedList.length

  // Hạn gần nhất trong các câu hỏi đang chờ (epoch giây → ms). Không có hạn thì
  // không dựng bộ đếm.
  const soonestDeadlineMs = useMemo(() => {
    const stamps = pendingList
      .map((decision) => decision.deadline)
      .filter((value): value is number => typeof value === 'number')
    if (stamps.length === 0) return null
    return Math.min(...stamps) * 1000
  }, [pendingList])
  const remainingMs = soonestDeadlineMs === null ? null : Math.max(0, soonestDeadlineMs - now)
  const remainingSec = remainingMs === null ? null : Math.ceil(remainingMs / 1000)

  // Ý định tự mở tab có thể chỉ đích danh một yêu cầu — cuộn tới đúng hàng đó.
  const targetRequestId =
    typeof decisionsTarget?.requestId === 'string' ? decisionsTarget.requestId : null
  const targetRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (!targetRequestId) return
    targetRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [targetRequestId, totalPending])

  const handleAnswer = useCallback(
    async (decision: DecisionEntry, choice: string, note?: string, answers?: InterviewReply[]) => {
      setSendingId(decision.id)
      setAnswerError(null)
      try {
        // P4 — lựa chọn tự nhập gửi kèm chữ đã gõ; các lựa chọn khác vẫn đi đường cũ (`note` rỗng).
        await answerDecision(chatId, decision.id, choice, note, answers)
        // `answerDecision` không ném: nó ghi lỗi thật của route vào store. Hàng
        // chỉ quay về "đang chờ" khi lần trả lời thất bại, nên lỗi chỉ hiện khi
        // đúng hàng đó vẫn còn chờ.
        const state = useHarnessChatStore.getState()
        const stillPending =
          (state.decisions[chatId] ?? []).find((item) => item.id === decision.id)?.status === 'pending'
        const error = state.sessions[chatId]?.error
        if (stillPending && error) setAnswerError({ id: decision.id, message: error })
      } finally {
        setSendingId(null)
      }
    },
    [answerDecision, chatId],
  )

  const statusLabel = (decision: DecisionEntry) =>
    decision.resolvedReason === 'timeout' || decision.status === 'expired'
      ? t('decisions.status.expired')
      : decision.status === 'approved'
        ? t('decisions.status.approved')
        : decision.status === 'answered'
          ? t('decisions.status.answered')
          : decision.status === 'rejected'
            ? t('decisions.status.rejected')
            : decision.status === 'cancelled'
              ? t('decisions.status.cancelled')
              : t('decisions.status.pending')

  const reasonLabel = (decision: DecisionEntry) =>
    decision.resolvedReason === 'timeout'
      ? t('decisions.reason.timeout')
      : decision.resolvedReason === 'session_cancelled'
        ? t('decisions.reason.session_cancelled')
        : t('decisions.reason.user')

  return (
    <div className="flex h-full flex-col overflow-hidden bg-panel select-text">
      {/* Header Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-[#13151b] px-5 py-3 select-none">
        <div className="flex items-center gap-2.5">
          <div className="flex size-7 items-center justify-center rounded-lg bg-amber-500/15 text-amber-400 border border-amber-500/30">
            <ShieldAlert className="size-4" />
          </div>
          <div>
            <h2 className="text-xs font-semibold text-fg">{t('decisions.title')}</h2>
            <p className="text-[10px] text-muted">{t('decisions.subtitle')}</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Filter Pills */}
          <div className="flex items-center rounded-lg border border-line bg-panel2/60 p-0.5">
            <button
              type="button"
              data-testid="decisions-filter-pending"
              onClick={() => setActiveFilter('pending')}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition cursor-pointer ${
                activeFilter === 'pending'
                  ? 'bg-panel text-white shadow-xs font-semibold'
                  : 'text-muted hover:text-fg'
              }`}
            >
              <span>{t('decisions.filterPending')}</span>
              <span className="flex size-4 items-center justify-center rounded-full bg-amber-500/20 font-mono text-[10px] font-bold text-amber-300">
                {totalPending}
              </span>
            </button>

            <button
              type="button"
              data-testid="decisions-filter-resolved"
              onClick={() => setActiveFilter('resolved')}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition cursor-pointer ${
                activeFilter === 'resolved'
                  ? 'bg-panel text-white shadow-xs font-semibold'
                  : 'text-muted hover:text-fg'
              }`}
            >
              <span>
                {t('decisions.filterResolved')} ({totalResolved})
              </span>
            </button>

            <button
              type="button"
              data-testid="decisions-filter-all"
              onClick={() => setActiveFilter('all')}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition cursor-pointer ${
                activeFilter === 'all'
                  ? 'bg-panel text-white shadow-xs font-semibold'
                  : 'text-muted hover:text-fg'
              }`}
            >
              <span>{t('decisions.filterAll')}</span>
            </button>
          </div>
        </div>
      </div>

      {/* Main Scrollable Content */}
      <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-6">
        {/* PENDING SECTION */}
        {(activeFilter === 'pending' || activeFilter === 'all') && (
          <div className="space-y-5">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-muted">
              <span>
                {t('decisions.pendingSection')} ({totalPending})
              </span>
              <span className="text-[10px] font-mono text-amber-400">
                {t('decisions.awaitingUser')}
              </span>
            </div>

            {/* Lỗi của lần trả lời vừa rồi — cùng kiểu dải với `plan-review-error`
                của tab Plan, để người dùng thấy ngay tại chỗ mình vừa bấm. */}
            {answerError && (
              <div
                data-testid="decision-answer-error"
                className="flex items-center gap-2 rounded-lg border border-rose-500/40 bg-rose-500/5 px-3 py-1.5 text-xs text-rose-400"
              >
                <ShieldAlert className="size-3.5 shrink-0" />
                <span className="min-w-0 flex-1 truncate">
                  {t('decisions.answerError')}: {answerError.message}
                </span>
              </div>
            )}

            {/* Băng báo agent đang bị chặn — chỉ hiện khi có yêu cầu thật đang chờ. */}
            {totalPending > 0 && (
              <div className="relative flex items-start gap-2.5 rounded-lg border border-amber-500/45 bg-amber-500/5 px-3 py-2.5">
                <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-amber-500" />
                <div className="min-w-0 flex-1 pl-1.5">
                  <div className="flex items-center gap-2 text-xs font-semibold text-amber-700 dark:text-amber-300">
                    <span className="size-1.5 rounded-full bg-amber-500 animate-pulse" />
                    <span>{t('chat.decisionWaiting')}</span>
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted">
                    {t('decisions.awaitingUser')} — {totalPending} ×{' '}
                    {t(`decisions.kind.${pendingList[0]?.kind ?? 'question'}` as 'decisions.kind.question')}
                  </p>
                </div>
                {remainingSec !== null && (
                  <div className="text-right shrink-0">
                    <div
                      className={`font-mono text-sm font-semibold ${
                        remainingSec * 1000 < 60000 ? 'text-red-500' : 'text-amber-600 dark:text-amber-300'
                      }`}
                    >
                      {Math.floor(remainingSec / 60)}:{String(remainingSec % 60).padStart(2, '0')}
                    </div>
                    <div className="text-[9px] uppercase tracking-wider text-muted">
                      {t('decisions.deadline')}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Quyết định thật của agent: mỗi hàng là một `decision_requested`. */}
            {pendingList.map((decision) => (
              <div
                key={decision.id}
                data-decision-id={decision.id}
                ref={decision.id === targetRequestId ? targetRef : undefined}
              >
                <PermissionCard
                  decision={decision}
                  busy={sendingId === decision.id}
                  onAnswer={(choice, note, answers) => void handleAnswer(decision, choice, note, answers)}
                />
              </div>
            ))}

            {totalPending === 0 && (
              <div
                data-testid="decisions-empty-pending"
                className="flex flex-col items-center justify-center p-8 text-center rounded-xl border border-line/60 bg-[#12141a]"
              >
                <CheckCircle2 className="size-8 text-emerald-400 mb-2" />
                <h4 className="text-xs font-semibold text-fg">{t('decisions.emptyTitle')}</h4>
                <p className="text-[11px] text-muted mt-0.5">{t('decisions.emptyBody')}</p>
              </div>
            )}
          </div>
        )}

        {/* RESOLVED HISTORY SECTION */}
        {(activeFilter === 'resolved' || activeFilter === 'all') && (
          <div className="space-y-3 pt-2">
            <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-muted border-t border-line/60 pt-4">
              <span>
                {t('decisions.historySection')} ({totalResolved})
              </span>
              <span className="text-[10px] font-mono text-muted">{t('decisions.historyNote')}</span>
            </div>

            <div className="space-y-3">
              {resolvedList.map((decision) => {
                const choiceLabel =
                  decision.choice === null
                    ? null
                    : decision.kind === 'interview' && decision.choice === INTERVIEW_SUBMIT
                      ? t('decisions.interview.submit')
                      : decision.kind === 'interview' && decision.choice === INTERVIEW_DECIDE
                        ? t('decisions.interview.decide')
                        : (decision.options.find((option) => option.id === decision.choice)?.label ??
                          decision.choice)
                const approved = decision.status === 'approved'
                // P4 — hàng trả lời tự nhập đã chốt nhưng không phải một lời duyệt: biểu tượng
                // trung tính, không được đội lốt XCircle (đỏ = "bị từ chối").
                const answered = decision.status === 'answered'

                return (
                  <div
                    key={decision.id}
                    data-decision-id={decision.id}
                    className="flex items-center justify-between rounded-lg border border-line bg-panel2/30 p-3 text-xs"
                  >
                    <div className="flex items-center gap-2.5 min-w-0 flex-1">
                      {approved ? (
                        <CheckCircle2 className="size-4 text-emerald-400 shrink-0" />
                      ) : answered ? (
                        <MessageSquare className="size-4 text-zinc-400 shrink-0" />
                      ) : (
                        <XCircle className="size-4 text-rose-400 shrink-0" />
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono font-bold text-zinc-300">
                            #{decision.id}
                          </span>
                          <span className="truncate text-zinc-200 font-medium">
                            {decision.question ?? decision.action ?? ''}
                          </span>
                        </div>
                        <p className="text-[11px] text-muted truncate">
                          {t(`decisions.kind.${decision.kind}` as 'decisions.kind.question')}
                          {choiceLabel ? ` · ${choiceLabel}` : ''} · {reasonLabel(decision)}
                          {decision.note ? ` · ${decision.note}` : ''}
                        </p>
                        {decision.kind === 'interview' && (decision.answers?.length ?? 0) > 0 && (
                          <ul className="mt-1 space-y-0.5 text-[11px] text-zinc-300" data-testid="interview-history-answers">
                            {decision.answers!.map((answer) => (
                              <li key={answer.questionId} className="truncate">
                                <span className="text-muted">{answer.question ?? answer.questionId}: </span>
                                {interviewAnswerLabel(answer, t)}
                              </li>
                            ))}
                          </ul>
                        )}
                      </div>
                    </div>
                    <span
                      className={`rounded px-2 py-0.5 font-mono text-[10px] font-semibold uppercase ${STATUS_TONE[decision.status]}`}
                    >
                      {statusLabel(decision)}
                    </span>
                  </div>
                )
              })}

              {totalResolved === 0 && (
                <p data-testid="decisions-empty-history" className="text-[11px] text-muted">
                  {t('decisions.emptyHistory')}
                </p>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

