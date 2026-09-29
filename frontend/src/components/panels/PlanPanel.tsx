/**
 * Khung ② — Kế hoạch (Plan Panel) phong cách BoxFox / Devin.
 * Cập nhật: Thay toàn bộ native select bằng Custom Dark Dropdown Popover, nút Approve tone trắng xám sang trọng.
 */
import { useState, useMemo, useRef, useEffect } from 'react'
import { PlanWorkflowView } from './plan/PlanWorkflowView'
import { usePlanStore } from '../../store/planStore'
import {
  Link,
  Copy,
  Check,
  Sparkles,
  ChevronDown,
  ChevronRight,
  X,
  FileCode,
  Shield,
  ArrowRight,
  ArrowLeft,
  CircleCheck,
  GitBranch,
  TriangleAlert,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { PlainText } from '../ui'
import { MarkdownRenderer } from '../chat/MarkdownRenderer'
import { usePlanFiles } from '../../hooks/usePlanFiles'
import { useT, type TKey } from '../../i18n/context'
import { planRejection, planStamp } from '../../lib/plans'
import type { PlanReviewState } from '../../lib/plans'
import { PlanEvalCard } from './PlanEvalCard'
import { PlanReviewCard, VERIFY_CHIP, type KnownVerificationState } from './PlanReviewCard'
import type { DiffLine } from '../../types/agent'

/** Chip trạng thái duyệt thật: nguồn là sổ duyệt của harness, không phải vị trí trong dropdown. */
const STATE_LABELS: Record<PlanReviewState, TKey> = {
  none: 'plan.state.none',
  draft: 'plan.state.draft',
  submitted: 'plan.state.submitted',
  approved: 'plan.state.approved',
  changes_requested: 'plan.state.changes_requested',
  unknown: 'plan.state.unknown',
}

const STATE_CHIP_BASE =
  'inline-flex items-center gap-1 rounded px-1.5 py-px text-[10px] font-semibold tracking-wide'

const STATE_CHIP_CLASSES: Record<PlanReviewState, string> = {
  approved: 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/40',
  changes_requested: 'bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/40',
  submitted: 'border border-line bg-panel2 text-muted',
  draft: 'border border-line bg-panel2 text-muted',
  none: 'border border-line bg-panel2 text-muted',
  unknown: 'border border-line bg-panel2 text-muted',
}

/** Câu giải thích cho chip phản biện — nhãn và màu ở `VERIFY_CHIP` của `PlanReviewCard`. */
const VERIFY_CHIP_TITLES: Record<KnownVerificationState, TKey> = {
  none: 'plan.verify.chip.noneTitle',
  ok: 'plan.verify.chip.okTitle',
  revise: 'plan.verify.chip.reviseTitle',
}

/** Id của dòng lý do khoá duyệt — nút `disabled` không hiện `title`, nên nối bằng `aria-describedby`. */
const APPROVE_BLOCKED_ID = 'plan-approve-blocked'

/**
 * Id của hai NHÃN NHÌN THẤY của hai ô mới. Ô chỉ có `placeholder` thì trình đọc màn hình không có
 * tên để đọc (và `placeholder` biến mất ngay khi gõ), nên ô trỏ vào đúng cái tiêu đề đang hiện.
 */
const APPROVE_CONDITIONS_LABEL_ID = 'plan-approve-conditions-label'
const CHANGES_TITLE_ID = 'plan-request-changes-title'

export function PlanPanel() {
  const t = useT()
  const mode = useAgentStore((s) => s.mode)
  const workspace = useAgentStore((s) => s.planWorkspace)
  const endorsed = useAgentStore((s) => s.planEndorsed)
  const proposal = useAgentStore((s) => s.proposal)
  const sendCommand = useAgentStore((s) => s.sendCommand)
  // M9: khung chat chỉ thấy lượt của PHIÊN ĐANG MỞ (ChatPanel poll theo activeSessionId), nên phải
  // nói được lượt mới mở ở phiên nào. Danh sách phiên đọc từ store — không đoán id.
  const activeSessionId = useAgentStore((s) => s.activeSessionId)
  const agentSessions = useAgentStore((s) => s.sessions)
  const setActiveSessionId = useAgentStore((s) => s.setActiveSessionId)

  const planViewMode = useUiStore((s) => s.planViewMode)
  const setPlanViewMode = useUiStore((s) => s.setPlanViewMode)
  const planSubTab = useUiStore((s) => s.planSubTab)
  const setPlanSubTab = useUiStore((s) => s.setPlanSubTab)
  const showFeedbackBanner = useUiStore((s) => s.showFeedbackBanner)
  const setShowFeedbackBanner = useUiStore((s) => s.setShowFeedbackBanner)
  /** Ý định tự mở tab của agent có thể chỉ đích danh một identity/version. */
  const planTarget = useUiStore((s) => s.tabIntentTargets.plan)

  /** Nguồn plan duy nhất: thư mục .plans của sandbox (không còn danh sách version giả). */
  const planFiles = usePlanFiles()
  const workflowRun = usePlanStore(s => s.runs.find(r =>
    (r.document?.identity === planFiles.selection?.identity && r.document?.version === planFiles.selection?.version) ||
    r.documents?.some(d => d.identity === planFiles.selection?.identity && d.version === planFiles.selection?.version)))
  const selectedPlan = planFiles.manifest?.plans.find((p) => p.identity === planFiles.selection?.identity)
  const selectedFileVersion = selectedPlan?.versions.find((v) => v.version === planFiles.selection?.version)

  /** Danh sách version để render trong dropdown: chỉ lấy từ manifest thật. */
  const versionItems = (selectedPlan?.versions ?? []).map((v) => ({
    key: v.version,
    // Nhãn trần `v3`: chữ `(draft)`/`(approved)` của box gán theo VỊ TRÍ, không theo quyết định nào
    // của người dùng (BUG-5) — trạng thái thật đã có chip riêng cạnh đó.
    label: v.label,
    /**
     * Dòng thứ hai: cha–con khai trong **header của chính file đó** (`declaredParent`), đúng như mock
     * trạng thái (f). Chỉ file có header (`headerStatus === 'ok'`) mới được nói; file legacy/mismatch
     * thì để trống thay vì đoán `Parent: none` — cùng luật "không bịa" như thẻ P1–P8.
     */
    parent:
      v.headerStatus === 'ok'
        ? v.declaredParent == null
          ? t('plan.parentNone')
          : `${t('plan.parentRowLabel')} v${v.declaredParent}`
        : null,
    isCurrent: v.version === planFiles.selection?.version,
    onSelect: () => planFiles.selectVersion(v.version),
  }))

  /**
   * Chuỗi cha–con của bản đang xem. Nguồn 1: bản chấm P2 (`evaluation.parentVersion`) khi có. Nguồn 2:
   * header của file (`declaredParent`) — cần cho trạng thái (f), vì mock yêu cầu thấy `Bản trước: vN`
   * ngay cả khi bản đó chưa được chấm P1–P8 (mọi bản hôm nay đều `evaluation: null`).
   */
  const headerParent =
    selectedFileVersion?.headerStatus === 'ok' ? selectedFileVersion.declaredParent ?? null : null
  const lineageVersion = planFiles.evaluation?.parentVersion ?? headerParent

  /**
   * Quyết định còn hiệu lực. Bản bị sửa sau khi duyệt (`reviewStale`) thì chuẩn thuận cũ KHÔNG còn
   * tính — nút quay về nhãn trung tính để người dùng không tưởng kế hoạch đang được phép chạy.
   */
  const reviewInForce = planFiles.reviewStale ? null : planFiles.selectedReview
  const approvedInForce = reviewInForce?.decision === 'approved'
  const changesRequestedInForce = reviewInForce?.decision === 'changes_requested'
  const reviewVersion = planFiles.selectedReview?.version ?? planFiles.selection?.version ?? null
  const reviewStamp = [
    reviewVersion === null ? null : `v${reviewVersion}`,
    planStamp(planFiles.selectedReview?.decidedAt),
  ]
    .filter(Boolean)
    .join(' · ')
  /** Câu từ chối của lần ghi bị cổng cứng chặn (mã + số đo + cách sửa), hoặc `null`. */
  const rejection = planRejection(planFiles.evaluation, t)

  /**
   * Mặt phản biện của bản đang xem (sổ phản biện của harness). `unknown` = harness cũ không khai
   * trường: KHÔNG vẽ chip và KHÔNG khoá duyệt — thà để harness trả 409 kèm lý do của chính nó.
   * `null` = vừa đổi bản, sổ của bản mới còn đang đọc: cũng không vẽ gì — không mượn mặt của bản cũ.
   */
  const verification = planFiles.verification
  const verificationState = verification?.state ?? null
  const verifyChipState: KnownVerificationState | null =
    verificationState === 'none' || verificationState === 'ok' || verificationState === 'revise'
      ? verificationState
      : null
  const verifyStamp = planStamp(verification?.at)
  const selectionVersion = planFiles.selection?.version ?? null
  const versionLabel = selectionVersion === null ? '—' : `v${selectionVersion}`

  /**
   * Lý do nút Duyệt bị khoá, theo đúng thứ tự của cái đang biết:
   * 1. harness đã chặn ở 409: nguyên văn `remedy` của nó, không dịch lại;
   * 2. sổ của bản mới còn đang đọc: nói đúng là đang đọc (không mượn kết luận của bản cũ);
   * 3. `revise` + cổng `enforce`: nói rõ verdict, rằng harness từ chối, và hai cách gỡ;
   * 4. còn lại: bản chưa có phiên phản biện nào.
   */
  const approveBlockedReason = planFiles.reviewBlocked?.remedy.trim()
    ? planFiles.reviewBlocked.remedy.trim()
    : verification === null
      ? t('plan.verify.reading', { version: versionLabel })
      : verification.state === 'revise'
        ? t('plan.verify.reviseLocked', { version: versionLabel, critic: t('plan.verify.critic') })
        : t('plan.verify.locked', { version: versionLabel })
  const semanticReady = workflowRun?.review?.verdict === 'ok' &&
    workflowRun.review.briefRevision === workflowRun.briefRevision &&
    workflowRun.document?.version === planFiles.selection?.version &&
    !workflowRun.questions.some(q => q.status === 'open' && q.field !== '__approval__') &&
    ['active', 'needs_user'].includes(workflowRun.status)
  const approveLocked = planFiles.approvalLocked || (!!workflowRun && !semanticReady)

  /**
   * Dòng kết quả quyết định. Harness trả kèm `wake.{state,code,message}` — câu chữ của CHÍNH NÓ về
   * việc mở lượt — nên ở đây ưu tiên `wake.state`: chỉ `opened` mới là "đang mở lượt"; `busy` /
   * `duplicate` / `missing` / `failed` đều KHÔNG mở lượt mới, và câu giải thích của harness được in
   * nguyên văn ở dòng dưới. Harness cũ (không có `wake`) lùi về đúng bit `resumed` như trước.
   */
  const reviewResult = planFiles.reviewResult
  const wake = reviewResult?.wake ?? null
  const wakeOpenedTurn = wake ? wake.state === 'opened' : reviewResult?.resumed === true
  const wakeText = wake?.message?.trim() ? wake.message.trim() : null
  const sentTurnText = reviewResult
    ? reviewResult.decision === 'changes_requested'
      ? t('plan.decisions.sent.changes', { version: reviewResult.version })
      : reviewResult.note.trim()
        ? t('plan.decisions.sent.approvedWithNote')
        : t('plan.decisions.sent.approved')
    : null
  const decisionSentText = !sentTurnText
    ? null
    : wake
      ? wake.state === 'opened'
        ? sentTurnText
        : t('plan.decisions.sent.notResumed')
      : reviewResult?.resumed === null
        ? t('plan.decisions.sent.unknown')
        : reviewResult?.resumed === false
          ? t('plan.decisions.sent.notResumed')
          : sentTurnText
  const decisionSentMeta = reviewResult
    ? [
        reviewResult.turnId ? t('plan.decisions.sent.turn', { turn: reviewResult.turnId }) : null,
        planFiles.ownership.sessionId
          ? t('plan.decisions.sent.session', { session: planFiles.ownership.sessionId })
          : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : ''

  /** Phiên sở hữu kế hoạch (harness khai ở `ownership`), chỉ hiện khi KHÁC phiên đang mở. */
  const ownerSessionId = planFiles.ownership.sessionId
  const ownerDiffers = Boolean(ownerSessionId) && ownerSessionId !== activeSessionId
  const ownerInList = ownerSessionId
    ? agentSessions.some((session) => session.session_id === ownerSessionId)
    : false

  const targetIdentity = typeof planTarget?.identity === 'string' ? planTarget.identity : null
  const targetVersion = typeof planTarget?.version === 'number' ? planTarget.version : undefined
  const selectIdentity = planFiles.selectIdentity
  useEffect(() => {
    if (!targetIdentity) return
    selectIdentity(targetIdentity, targetVersion)
  }, [selectIdentity, targetIdentity, targetVersion])

  const [copied, setCopied] = useState(false)
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null)
  /** Popup "duyệt kèm điều kiện" — một mũi tên nhỏ cạnh nút Duyệt, không phải nút thứ hai. */
  const [approveNoteOpen, setApproveNoteOpen] = useState(false)
  const [approveNote, setApproveNote] = useState('')
  /** Hộp lý do sửa — mở ngay dưới hàng công cụ, gửi kèm quyết định (BUG-3). */
  const [changesFormOpen, setChangesFormOpen] = useState(false)
  const [changesNote, setChangesNote] = useState('')
  const [identityMenuOpen, setIdentityMenuOpen] = useState(false)
  const [versionMenuOpen, setVersionMenuOpen] = useState(false)
  const identityMenuRef = useRef<HTMLDivElement>(null)
  const versionMenuRef = useRef<HTMLDivElement>(null)
  const approveNoteRef = useRef<HTMLDivElement>(null)

  /**
   * Điều kiện / lý do sửa gõ cho MỘT bản chỉ đúng với bản đó: đổi bản thì hai ô và hai popup phải
   * sạch, nếu không một điều kiện gõ cho v1 sẽ được gửi kèm quyết định của v2 (chữ vẫn là chữ của
   * bản cũ, chỉ có số version đổi — người đọc không thể biết).
   */
  const selectionKey = planFiles.selection
    ? `${planFiles.selection.identity}:${planFiles.selection.version}`
    : null
  const previousSelectionKey = useRef<string | null>(null)
  useEffect(() => {
    const previous = previousSelectionKey.current
    previousSelectionKey.current = selectionKey
    if (previous === null || previous === selectionKey) return
    setApproveNote('')
    setChangesNote('')
    setApproveNoteOpen(false)
    setChangesFormOpen(false)
  }, [selectionKey])

  const currentPlan = mode === 'ACT' && endorsed ? endorsed : workspace

  const renderedDetailedContent = useMemo(() => {
    if (planFiles.document) {
      return <MarkdownRenderer content={planFiles.document.markdown} variant="document" />
    }
    if (currentPlan) {
      return (
        <div className="text-xs leading-relaxed">
          <PlainText text={currentPlan.full_text} />
        </div>
      )
    }
    return null
  }, [planFiles.document, currentPlan])

  const diffChunks: DiffLine[] = useMemo(() => {
    // Return empty diff when no modifications are present
    return []
  }, [])

  const selectedStep = useMemo(() => {
    if (!currentPlan?.steps || !selectedStepId) return null
    return currentPlan.steps.find((s) => s.id === selectedStepId) ?? null
  }, [currentPlan, selectedStepId])

  // Click outside to close popovers — popup "duyệt kèm điều kiện" đi cùng luật với hai menu kia.
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      const target = e.target as Node
      if (identityMenuRef.current && !identityMenuRef.current.contains(target)) {
        setIdentityMenuOpen(false)
      }
      if (versionMenuRef.current && !versionMenuRef.current.contains(target)) {
        setVersionMenuOpen(false)
      }
      if (approveNoteRef.current && !approveNoteRef.current.contains(target)) {
        setApproveNoteOpen(false)
      }
    }
    if (identityMenuOpen || versionMenuOpen || approveNoteOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [identityMenuOpen, versionMenuOpen, approveNoteOpen])

  /**
   * Escape đóng popup điều kiện mà KHÔNG xoá chữ đã gõ (mở lại vẫn còn) — xoá chữ là việc của nút
   * Huỷ, còn đóng chỉ là đóng.
   */
  useEffect(() => {
    if (!approveNoteOpen) return
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setApproveNoteOpen(false)
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [approveNoteOpen])

  /**
   * Duyệt kế hoạch thật: ghi vào container (`POST /__box/plans/review`) khi tab
   * đang xem một file kế hoạch thật; đường demo cũ chỉ còn khi không có file.
   */
  const handleApprove = () => {
    // Bản chưa qua phản biện thì không gửi gì cả — kể cả khi nút bị bật bằng đường khác.
    if (approveLocked) return
    if (planFiles.document) {
      void planFiles.submitReview('approved')
      return
    }
    if (proposal) {
      sendCommand({
        type: 'mode_switch_confirm',
        accepted: true,
      })
    } else if (mode === 'PLAN') {
      sendCommand({ type: 'scenario_step' })
    }
  }

  /** Ghi chú điều kiện: ô trống vẫn là duyệt thường — không dựng điều kiện rỗng. */
  const handleApproveWithNote = () => {
    if (approveLocked) return
    const note = approveNote.trim()
    setApproveNote('')
    setApproveNoteOpen(false)
    if (planFiles.document) {
      void planFiles.submitReview('approved', note)
      return
    }
    handleApprove()
  }

  /**
   * Lần bấm đầu KHÔNG gửi gì: mở hộp lý do (BUG-3 — trước đây gửi đi một quyết định rỗng chữ).
   * Gửi khi nào là do người dùng: ô trống vẫn gửi được (lượt chạy vẫn mở), chỉ là không có lý do.
   */
  const handleRequestChanges = () => {
    if (!planFiles.document) return
    setChangesFormOpen(true)
  }

  const handleSubmitChanges = () => {
    if (!planFiles.document) return
    const note = changesNote.trim()
    setChangesNote('')
    setChangesFormOpen(false)
    void planFiles.submitReview('changes_requested', note)
  }

  const handleRunVerification = () => {
    void planFiles.runVerification()
  }

  const handleCopy = () => {
    const text = planFiles.document?.markdown ?? currentPlan?.full_text
    if (text) {
      void navigator.clipboard.writeText(text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    }
  }

  const handleNavigateStep = (direction: 'prev' | 'next') => {
    if (!currentPlan?.steps || !selectedStepId) return
    const currentIndex = currentPlan.steps.findIndex((s) => s.id === selectedStepId)
    if (currentIndex === -1) return
    const nextIndex = direction === 'next' ? currentIndex + 1 : currentIndex - 1
    if (nextIndex >= 0 && nextIndex < currentPlan.steps.length) {
      setSelectedStepId(currentPlan.steps[nextIndex].id)
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden bg-panel select-text">
      <div className="max-h-72 overflow-y-auto shrink-0"><PlanWorkflowView document={planFiles.selection} /></div>
      {/* Sub-Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-panel px-4 py-2">
        <div className="flex items-center gap-2.5">
          {/* Document Title Selector — dùng danh sách plan từ sandbox khi có */}
          <div className="relative min-w-0" ref={identityMenuRef}>
            <button
              type="button"
              onClick={() => setIdentityMenuOpen((o) => !o)}
              disabled={!planFiles.manifest?.plans.length}
              className="flex max-w-56 items-center gap-1.5 rounded-md px-2 py-1 text-xs font-semibold text-fg transition hover:bg-panel2 disabled:cursor-default disabled:text-muted cursor-pointer"
              title={selectedPlan?.identity ?? 'Agent Box — Plan Document'}
            >
              <span className="truncate">{selectedPlan?.identity ?? 'Agent Box — Plan Document'}</span>
              <ChevronDown className="size-3 shrink-0 text-muted" />
            </button>
            {identityMenuOpen && planFiles.manifest && (
              <div className="absolute left-0 top-full z-40 mt-1 max-h-64 w-56 overflow-y-auto rounded-lg border border-line bg-panel2 p-1 shadow-xl animate-in fade-in zoom-in-95 duration-100">
                {planFiles.manifest.plans.map((plan) => {
                  const isCurrent = plan.identity === planFiles.selection?.identity
                  return (
                    <button
                      key={plan.identity}
                      type="button"
                      onClick={() => {
                        planFiles.selectIdentity(plan.identity)
                        setIdentityMenuOpen(false)
                      }}
                      className={`flex w-full items-center justify-between gap-2 rounded px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
                        isCurrent ? 'bg-panel font-medium text-fg' : 'text-muted hover:bg-panel hover:text-fg'
                      }`}
                    >
                      <span className="truncate">{plan.identity}</span>
                      {isCurrent && <Check className="size-3 shrink-0 text-brand" />}
                    </button>
                  )
                })}
              </div>
            )}
          </div>

          {/* Custom Sleek Version Dropdown Popover */}
          <div className="relative inline-block" ref={versionMenuRef}>
            <button
              type="button"
              onClick={() => setVersionMenuOpen(!versionMenuOpen)}
              className="flex items-center gap-1.5 rounded-md border border-line bg-panel2 px-2.5 py-1 text-xs font-medium text-fg outline-hidden transition hover:border-zinc-500 cursor-pointer"
            >
              <span>{selectedFileVersion ? selectedFileVersion.label : t('plan.noVersions')}</span>
              <ChevronDown className="size-3 text-muted" />
            </button>

            {versionMenuOpen && (
              <div className="absolute left-0 top-full z-40 mt-1 w-36 overflow-hidden rounded-lg border border-line bg-panel2 p-1 shadow-xl animate-in fade-in zoom-in-95 duration-100">
                {versionItems.length === 0 && (
                  <p className="px-2.5 py-1.5 text-xs text-muted">{t('plan.noVersions')}</p>
                )}
                {versionItems.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    onClick={() => {
                      item.onSelect()
                      setVersionMenuOpen(false)
                    }}
                    className={`flex w-full items-center justify-between rounded px-2.5 py-1.5 text-left text-xs transition cursor-pointer ${
                      item.isCurrent ? 'bg-panel font-medium text-fg' : 'text-muted hover:bg-panel hover:text-fg'
                    }`}
                  >
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">{item.label}</span>
                      {item.parent && (
                        <span className="truncate font-mono text-[10px] text-muted">{item.parent}</span>
                      )}
                    </span>
                    {item.isCurrent && <Check className="size-3 shrink-0 text-brand" />}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Hai chip đọc từ SỔ của harness, không đọc từ tên file: chip trạng thái duyệt, rồi tới
              chip phản biện (chỉ hiện khi harness có khai mặt `verification`). */}
          {planFiles.document && (
            <>
              <span
                data-component-id="plan-state-chip"
                data-testid="plan-state-chip"
                title={t('plan.state.title')}
                className={`${STATE_CHIP_BASE} ${STATE_CHIP_CLASSES[planFiles.planState]}`}
              >
                {t(STATE_LABELS[planFiles.planState])}
              </span>
              {planFiles.reviewStale && (
                <span
                  data-component-id="plan-state-stale"
                  data-testid="plan-state-stale"
                  title={t('plan.state.staleTitle')}
                  className={`${STATE_CHIP_BASE} bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/40`}
                >
                  {t('plan.state.stale')}
                </span>
              )}
              {/* Mặt phản biện: `none` = vàng, `ok` = xanh, `revise` = đỏ. `unknown` (harness cũ)
                  thì không chip — im lặng đúng hơn một lời khẳng định sai. */}
              {verifyChipState && (
                <span
                  data-component-id="plan-review-chip"
                  data-testid="plan-review-chip"
                  title={t(VERIFY_CHIP_TITLES[verifyChipState])}
                  className={`${STATE_CHIP_BASE} ${VERIFY_CHIP[verifyChipState].classes}`}
                >
                  {t(VERIFY_CHIP[verifyChipState].label, {
                    critic: t('plan.verify.critic'),
                    stamp: verifyStamp ?? '',
                  })}
                </span>
              )}
            </>
          )}

          {/* Plan | Diff Toggle */}
          <div className="flex items-center rounded-md border border-line bg-panel2 p-0.5">
            <button
              type="button"
              onClick={() => setPlanViewMode('plan')}
              className={`rounded px-2.5 py-0.5 text-xs font-medium transition cursor-pointer ${
                planViewMode === 'plan'
                  ? 'bg-panel text-fg shadow-xs'
                  : 'text-muted hover:text-fg'
              }`}
            >
              Plan
            </button>
            <button
              type="button"
              onClick={() => setPlanViewMode('diff')}
              className={`rounded px-2.5 py-0.5 text-xs font-medium transition cursor-pointer ${
                planViewMode === 'diff'
                  ? 'bg-panel text-fg shadow-xs'
                  : 'text-muted hover:text-fg'
              }`}
            >
              Diff
            </button>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Share Button */}
          <button
            type="button"
            className="flex items-center gap-1.5 rounded-md border border-line px-2.5 py-1 text-xs font-medium text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
          >
            <Link className="size-3" />
            <span>Share</span>
          </button>

          {/* Copy Button */}
          <button
            type="button"
            onClick={handleCopy}
            className="rounded-md border border-line p-1 text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
            title="Copy plan text"
          >
            {copied ? <Check className="size-3.5 text-emerald-400" /> : <Copy className="size-3.5" />}
          </button>

          {/* Yêu cầu sửa — chỉ có nghĩa khi đang xem một file kế hoạch thật. */}
          {planFiles.document && (
            <button
              type="button"
              data-testid="plan-request-changes"
              onClick={handleRequestChanges}
              disabled={planFiles.reviewStatus === 'saving'}
              className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-xs font-medium transition cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 ${
                changesRequestedInForce
                  ? 'border-amber-500/40 bg-amber-500/15 text-amber-300'
                  : 'border-line text-muted hover:bg-panel2 hover:text-fg'
              }`}
            >
              <ArrowLeft className="size-3" />
              <span>
                {changesRequestedInForce ? t('plan.changesRequestedStored') : t('plan.requestChanges')}
              </span>
            </button>
          )}

          {/* Approve + MỘT mũi tên nhỏ mở popup "duyệt kèm điều kiện" (không phải nút thứ hai). */}
          <div ref={approveNoteRef} className="relative flex items-center">
            <button
              type="button"
              data-testid="plan-approve"
              data-component-id="plan-approve-button"
              onClick={handleApprove}
              // Khoá khi: đang ở Act, đang ghi, hoặc bản này CHƯA qua phiên phản biện
              // (`verification.state === 'none'`). Harness cũ không khai mặt phản biện thì KHÔNG khoá.
              disabled={(mode === 'ACT' && !workflowRun) || planFiles.reviewStatus === 'saving' || approveLocked}
              data-disabled-reason={approveLocked ? 'plan-not-reviewed' : undefined}
              aria-label={approveLocked ? t('plan.verify.lockedAria') : undefined}
              aria-describedby={approveLocked ? APPROVE_BLOCKED_ID : undefined}
              className={`flex items-center gap-1.5 rounded-md px-3.5 py-1 text-xs font-semibold transition shadow-xs cursor-pointer disabled:cursor-not-allowed ${
                approveLocked
                  ? 'bg-panel2 text-muted border border-line opacity-60'
                  : (mode === 'ACT' && !workflowRun) || approvedInForce
                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                    : 'bg-zinc-100 text-zinc-900 hover:bg-white active:scale-98'
              }`}
            >
              <Check className="size-3.5" />
              <span>
                {mode === 'ACT' && !workflowRun
                  ? 'Approved (ACT)'
                  : approvedInForce
                    ? t('plan.approvedStored')
                    : t('plan.approvePlan')}
              </span>
            </button>

            {planFiles.document && (
              <button
                type="button"
                data-testid="plan-approve-note-toggle"
                data-component-id="plan-approve-conditions-toggle"
                title={t('plan.decisions.chevronTitle')}
                aria-label={t('plan.decisions.chevronTitle')}
                aria-expanded={approveNoteOpen}
                disabled={(mode === 'ACT' && !workflowRun) || planFiles.reviewStatus === 'saving' || approveLocked}
                onClick={() => setApproveNoteOpen((open) => !open)}
                className="ml-0.5 rounded-md border border-line px-1 py-1 text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ChevronDown className="size-3" />
              </button>
            )}

            {planFiles.document && approveNoteOpen && (
              <div
                data-component-id="plan-approve-conditions-popover"
                data-testid="plan-approve-note-popover"
                className="absolute right-0 top-full z-40 mt-1 w-80 space-y-2 rounded-lg border border-line bg-panel2 p-3 text-left shadow-xl animate-in fade-in zoom-in-95 duration-100"
              >
                <div id={APPROVE_CONDITIONS_LABEL_ID} className="text-xs font-semibold text-fg">
                  {t('plan.decisions.conditionsLabel')}
                </div>
                <p className="text-[11px] leading-relaxed text-muted">{t('plan.decisions.conditionsHint')}</p>
                <textarea
                  data-component-id="plan-approve-conditions-input"
                  data-testid="plan-approve-note"
                  aria-labelledby={APPROVE_CONDITIONS_LABEL_ID}
                  rows={3}
                  value={approveNote}
                  onChange={(event) => setApproveNote(event.target.value)}
                  placeholder={t('plan.decisions.conditionsPlaceholder')}
                  className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-xs text-fg outline-hidden focus:border-zinc-500"
                />
                <div className="flex items-center justify-end gap-2">
                  <button
                    type="button"
                    data-component-id="plan-approve-conditions-cancel"
                    data-testid="plan-approve-note-cancel"
                    onClick={() => {
                      setApproveNote('')
                      setApproveNoteOpen(false)
                    }}
                    className="rounded-md border border-line px-2.5 py-1 text-xs text-muted transition hover:bg-panel hover:text-fg cursor-pointer"
                  >
                    {t('plan.decisions.cancel')}
                  </button>
                  <button
                    type="button"
                    data-testid="plan-approve-with-note"
                    onClick={handleApproveWithNote}
                    className="rounded-md bg-zinc-100 px-3 py-1 text-xs font-semibold text-zinc-900 transition hover:bg-white cursor-pointer"
                  >
                    {t('plan.decisions.conditionsSubmit')}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Vì sao nút Duyệt bị khoá — ẩn hiển thị thị giác (sr-only) để giải phóng diện tích theo yêu cầu user */}
      {planFiles.document && approveLocked && (
        <div
          data-component-id="plan-approve-blocked-reason"
          data-testid="plan-approve-blocked"
          id={APPROVE_BLOCKED_ID}
          role="status"
          className="sr-only"
        >
          <Shield className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 flex-1">{approveBlockedReason}</span>
        </div>
      )}

      {/* Hộp lý do sửa: mở ngay dưới hàng công cụ, lý do đi cùng quyết định vào lượt chạy (BUG-3). */}
      {planFiles.document && changesFormOpen && (
        <div
          data-component-id="plan-request-changes-form"
          data-testid="plan-changes-form"
          className="space-y-2 border-b border-line bg-panel2/30 px-4 py-2"
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span id={CHANGES_TITLE_ID} className="text-[11px] font-semibold text-fg">
              {t('plan.decisions.changesTitle')}
            </span>
            <span className="font-mono text-[10px] text-muted">
              {t('plan.decisions.changesFor', { version: selectionVersion ?? '—' })}
            </span>
          </div>
          <textarea
            data-component-id="plan-request-changes-input"
            data-testid="plan-changes-note"
            aria-labelledby={CHANGES_TITLE_ID}
            rows={3}
            value={changesNote}
            onChange={(event) => setChangesNote(event.target.value)}
            placeholder={t('plan.decisions.changesPlaceholder')}
            className="w-full rounded-md border border-line bg-panel px-2 py-1.5 text-xs text-fg outline-hidden focus:border-zinc-500"
          />
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              data-component-id="plan-request-changes-cancel"
              data-testid="plan-changes-cancel"
              onClick={() => {
                setChangesNote('')
                setChangesFormOpen(false)
              }}
              className="rounded-md border border-line px-2.5 py-1 text-xs text-muted transition hover:bg-panel hover:text-fg cursor-pointer"
            >
              {t('plan.decisions.cancel')}
            </button>
            <button
              type="button"
              data-component-id="plan-request-changes-submit"
              data-testid="plan-changes-submit"
              onClick={handleSubmitChanges}
              className="rounded-md bg-zinc-100 px-3 py-1 text-xs font-semibold text-zinc-900 transition hover:bg-white cursor-pointer"
            >
              {t('plan.decisions.changesSubmit')}
            </button>
          </div>
        </div>
      )}

      {/* Bản đã bị sửa sau khi duyệt: chuẩn thuận cũ không còn áp dụng, agent phải xin lại. */}
      {planFiles.reviewStale && (
        <div
          data-component-id="plan-review-stale"
          data-testid="plan-review-stale"
          className="flex items-start gap-2 border-b border-line bg-amber-500/10 px-4 py-1.5 text-xs text-amber-300"
        >
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 flex-1">
            <span className="font-semibold">{t('plan.staleReview.title')}</span>
            <span className="text-muted">{t('plan.staleReview.body')}</span>
          </span>
          {reviewStamp && (
            <span className="shrink-0 font-mono text-[10px] text-muted">{reviewStamp}</span>
          )}
        </div>
      )}

      {/* Lần ghi bị cổng cứng chặn: mã từ chối + số đo + cách sửa, chỉ hiện đúng một lần ở đây. */}
      {rejection && (
        <div
          data-component-id="plan-eval-rejected"
          data-testid="plan-eval-rejected"
          className="flex items-start gap-2 border-b border-line bg-rose-500/5 px-4 py-1.5 text-xs text-rose-400"
        >
          <Shield className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 leading-relaxed">
            <b className="font-semibold">
              {rejection.version === null
                ? t('plan.eval.rejectedTitleGeneric')
                : t('plan.eval.rejectedTitle', { version: rejection.version })}
            </b>{' '}
            <span className="font-mono text-[11px]">
              {rejection.prefix}: ({rejection.code})
            </span>
            <br />
            <span className="text-muted">
              {[rejection.measure, rejection.remedy].filter(Boolean).join(' — ')}
            </span>
          </span>
          {rejection.stamp && (
            <span className="shrink-0 font-mono text-[10px] text-muted">{rejection.stamp}</span>
          )}
        </div>
      )}

      {/* Quyết định đang có hiệu lực, đọc từ sổ duyệt chứ không từ `.reviews` của box. */}
      {reviewInForce && (
        <div
          data-component-id="plan-review-strip"
          data-testid="plan-review-strip"
          className={`flex items-center gap-2 border-b border-line bg-panel2/40 px-4 py-1.5 text-xs ${
            approvedInForce ? 'text-emerald-400' : 'text-amber-300'
          }`}
        >
          {approvedInForce ? (
            <CircleCheck className="size-3.5 shrink-0" />
          ) : (
            <Shield className="size-3.5 shrink-0" />
          )}
          <span className="shrink-0 font-semibold">
            {approvedInForce ? t('plan.state.approved') : t('plan.state.changes_requested')}
          </span>
          {reviewInForce.note.trim() ? (
            <span className="truncate italic text-fg">“{reviewInForce.note.trim()}”</span>
          ) : (
            <span className="truncate text-muted">{t('plan.reviewStoredNote')}</span>
          )}
          {reviewStamp && (
            <span className="ml-auto shrink-0 font-mono text-[10px] text-muted">{reviewStamp}</span>
          )}
        </div>
      )}

      {/* Quyết định đã vào sổ harness nhưng chưa chuyển được sang box — nói thật, không im lặng. */}
      {planFiles.reviewForwarded === false && (
        <div
          data-testid="plan-review-not-forwarded"
          className="flex items-start gap-2 border-b border-line bg-amber-500/10 px-4 py-1.5 text-xs text-amber-300"
        >
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 flex-1">{t('plan.notForwarded')}</span>
        </div>
      )}

      {/* Harness CHẶN quyết định (409 `blocked: true`): mã + lý do + cách sửa, NGUYÊN VĂN của harness. */}
      {planFiles.reviewBlocked && (
        <div
          data-testid="plan-review-blocked"
          role="alert"
          className="flex items-start gap-2 border-b border-line bg-rose-500/5 px-4 py-1.5 text-xs text-rose-400"
        >
          <Shield className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 leading-relaxed">
            <b className="font-semibold">{t('plan.verify.blockedTitle')}</b>{' '}
            <span className="font-mono text-[11px]">({planFiles.reviewBlocked.code})</span>
            <br />
            <span className="text-muted">
              {[planFiles.reviewBlocked.reason.trim(), planFiles.reviewBlocked.remedy.trim()]
                .filter(Boolean)
                .join(' — ')}
            </span>
          </span>
        </div>
      )}

      {/* Bản chưa đạt phản biện mà harness VẪN cho qua (`BOXFOX_PLAN_VERIFY=warn`): nói ra, không giấu. */}
      {reviewResult?.approvalWarning && (
        <div
          data-testid="plan-approval-warning"
          role="status"
          className="flex items-start gap-2 border-b border-line bg-amber-500/10 px-4 py-1.5 text-xs text-amber-300"
        >
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 leading-relaxed">
            <span className="font-semibold">{t('plan.verify.warnTitle')}</span>{' '}
            <span className="text-muted">{reviewResult.approvalWarning.trim()}</span>
          </span>
        </div>
      )}

      {/* Quyết định vừa gửi: nói thật chuyện gì xảy ra sau cú bấm (BUG-2/BUG-7 nhìn từ giao diện). */}
      {decisionSentText && (
        <div
          data-testid="plan-decision-sent"
          role="status"
          className="flex items-center gap-2 border-b border-line bg-panel2/40 px-4 py-1.5 text-xs text-muted"
        >
          <CircleCheck
            className={`size-3.5 shrink-0 ${wakeOpenedTurn ? 'text-emerald-400' : 'text-muted'}`}
          />
          <span className="min-w-0 flex-1 truncate">{decisionSentText}</span>
          {decisionSentMeta && (
            <span className="shrink-0 font-mono text-[10px] text-muted">{decisionSentMeta}</span>
          )}
        </div>
      )}

      {/* Vì sao mở/không mở được lượt — câu của harness, in NGUYÊN VĂN, không viết lại thành câu chung. */}
      {decisionSentText && wakeText && (
        <div
          data-testid="plan-decision-wake"
          role="status"
          className="flex items-start gap-2 border-b border-line bg-panel2/40 px-4 py-1.5 text-xs text-muted"
        >
          <GitBranch className="mt-0.5 size-3.5 shrink-0" />
          <span className="min-w-0 flex-1 leading-relaxed">
            <span className="font-semibold text-fg">{t('plan.decisions.sent.wakeTitle')}</span>{' '}
            {wakeText}
          </span>
          {wake?.code && (
            <span className="shrink-0 font-mono text-[10px] text-muted">{wake.code}</span>
          )}
        </div>
      )}

      {/* M9: lượt mới mở ở phiên sở hữu — khung chat chỉ thấy lượt khi đang mở đúng phiên đó. */}
      {ownerDiffers && (
        <div
          data-testid="plan-owner-hint"
          role="status"
          className="flex items-center gap-2 border-b border-line bg-panel2/40 px-4 py-1.5 text-xs text-muted"
        >
          <GitBranch className="size-3.5 shrink-0" />
          <span id="plan-owner-hint-text" className="min-w-0 flex-1 truncate">
            {ownerInList
              ? t('plan.owner.hint', { session: ownerSessionId ?? '' })
              : t('plan.owner.notInList', { session: ownerSessionId ?? '' })}
          </span>
          <button
            type="button"
            data-testid="plan-owner-open"
            disabled={!ownerInList}
            data-disabled-reason={ownerInList ? undefined : 'session-not-in-list'}
            title={ownerInList ? t('plan.owner.openTitle') : undefined}
            aria-label={t('plan.owner.openTitle')}
            aria-describedby="plan-owner-hint-text"
            onClick={() => {
              // Chỉ đổi phiên đang mở bằng hàm có sẵn — không tạo phiên mới, không thêm vòng poll.
              if (ownerInList && ownerSessionId) setActiveSessionId(ownerSessionId)
            }}
            className={`shrink-0 rounded border px-2 py-0.5 text-[11px] transition ${
              ownerInList
                ? 'cursor-pointer border-line text-fg hover:border-brand hover:text-brand'
                : 'cursor-not-allowed border-line text-muted opacity-60'
            }`}
          >
            {t('plan.owner.open')}
          </button>
        </div>
      )}

      {/* Sub-tabs: Overview | Detailed Plan (when in Plan view) */}
      {planViewMode === 'plan' && (
        <div className="flex items-center gap-1 border-b border-line bg-panel2/20 px-4 py-0.5">
          <button
            type="button"
            onClick={() => setPlanSubTab('overview')}
            className={`border-b-2 px-3 py-1.5 text-xs font-medium transition cursor-pointer ${
              planSubTab === 'overview'
                ? 'border-brand text-fg'
                : 'border-transparent text-muted hover:text-fg'
            }`}
          >
            Overview
          </button>
          <button
            type="button"
            onClick={() => setPlanSubTab('detailed')}
            className={`border-b-2 px-3 py-1.5 text-xs font-medium transition cursor-pointer ${
              planSubTab === 'detailed'
                ? 'border-brand text-fg'
                : 'border-transparent text-muted hover:text-fg'
            }`}
          >
            Detailed Plan
          </button>
        </div>
      )}

      {/* Inline Comment Suggestion Banner */}
      {showFeedbackBanner && (
        <div className="flex items-center justify-between border-b border-line bg-panel2/40 px-4 py-1.5 text-xs text-muted">
          <div className="flex items-center gap-2">
            <Sparkles className="size-3.5 text-brand" />
            <span>Select text to ask a follow-up or add an inline comment</span>
          </div>
          <button
            type="button"
            onClick={() => setShowFeedbackBanner(false)}
            className="rounded p-0.5 text-muted hover:text-fg cursor-pointer"
          >
            <X className="size-3.5" />
          </button>
        </div>
      )}

      {/* Không đọc được sổ duyệt (route chưa có / thiếu quyền / mất mạng): nói đúng thế, không
          rơi về nhãn "đã duyệt" theo vị trí như trước. */}
      {planFiles.statusError && (
        <div
          data-testid="plan-status-error"
          className="flex items-center gap-2 border-b border-line bg-panel2/40 px-4 py-1.5 text-xs text-rose-400"
        >
          <Shield className="size-3.5 shrink-0" />
          <span className="truncate">
            {t('plan.statusError')}: {planFiles.statusError}
          </span>
        </div>
      )}

      {/* Lỗi ghi quyết định duyệt kế hoạch (route harness chưa có → 404/400). */}
      {planFiles.reviewStatus === 'error' && planFiles.reviewError && (
        <div
          data-testid="plan-review-error"
          className="flex items-center gap-2 border-b border-line bg-panel2/40 px-4 py-1.5 text-xs text-rose-400"
        >
          <Shield className="size-3.5 shrink-0" />
          <span className="truncate">
            {t('plan.reviewError')}: {planFiles.reviewError}
          </span>
        </div>
      )}

      {/* Main Content Area */}
      <div className="min-h-0 flex-1 overflow-hidden">
        {planViewMode === 'diff' ? (
          /* Diff View */
          diffChunks.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center text-muted">
              <FileCode className="size-8 text-muted/40 mb-2" />
              <p className="text-xs font-semibold text-fg">No file diff available</p>
              <p className="text-[11px] text-muted mt-0.5">Diff comparisons will appear once files are modified in Act mode.</p>
            </div>
          ) : (
            <div className="h-full overflow-y-auto p-6 space-y-3">
              <div className="flex items-center justify-between border-b border-line pb-2">
                <span className="font-mono text-xs font-semibold text-fg flex items-center gap-1.5">
                  <FileCode className="size-3.5 text-brand" />
                  Workspace Diff Changes
                </span>
              </div>
              <div className="overflow-x-auto rounded-md border border-line bg-bg p-3.5 font-mono text-xs leading-relaxed">
                {diffChunks.map((line, i) => (
                  <div
                    key={i}
                    className={`px-2 py-0.5 ${
                      line.kind === 'them'
                        ? 'bg-emerald-500/15 text-emerald-300'
                        : line.kind === 'bot'
                          ? 'bg-rose-500/15 text-rose-300 line-through'
                          : 'text-muted'
                    }`}
                  >
                    <span className="mr-3 select-none text-[10px] opacity-40">
                      {line.kind === 'them' ? '+' : line.kind === 'bot' ? '-' : ' '}
                    </span>
                    {line.text}
                  </div>
                ))}
              </div>
            </div>
          )
        ) : !currentPlan && !planFiles.document ? (
          /* Empty State — nói thật là thư mục .plans chưa có gì. */
          <div
            data-testid="plan-empty"
            className="flex h-full flex-col items-center justify-center p-8 text-center"
          >
            <FileCode className="mb-2 size-8 text-muted/40" />
            <p className="text-xs font-semibold text-fg">
              {planFiles.status === 'loading' ? t('plan.loading') : t('plan.emptyTitle')}
            </p>
            <p className="mt-0.5 max-w-md text-[11px] text-muted">
              {planFiles.status === 'error' ? (planFiles.error ?? t('plan.emptyBody')) : t('plan.emptyBody')}
            </p>
          </div>
        ) : planSubTab === 'overview' ? (
          /* Overview View (Split view if step selected) */
          <div className="flex h-full min-h-0">
            {/* Left Side: Summary & Compact Step List */}
            <div
              className={`h-full overflow-y-auto p-6 transition-all duration-200 ${
                selectedStep ? 'w-1/2 border-r border-line' : 'w-full min-w-0'
              }`}
            >
              <div className="space-y-5">
                <div>
                  <h1 className="text-base font-semibold text-fg">
                    {planFiles.document ? planFiles.document.identity : 'Agent Plan Summary'}
                  </h1>
                  <p className="mt-0.5 text-xs text-muted">
                    {planFiles.document ? (
                      <>
                        File location: <code className="text-brand font-mono text-[11px]">.plans/{planFiles.document.relativePath}</code>
                      </>
                    ) : (
                      <>
                        Full architectural blueprint: <code className="text-brand font-mono text-[11px]">/docs/plan/agent-box-plan.md</code>
                      </>
                    )}
                  </p>
                  {/* Bản trước: chuỗi cha–con của bản đang xem — bản chấm P2 nếu có, còn không thì lấy
                      thẳng header của file (`declaredParent`) như mock trạng thái (f). */}
                  {lineageVersion != null && (
                    <p className="mt-1 flex items-center gap-1.5 text-[11px] text-muted">
                      <GitBranch className="size-3 shrink-0" />
                      <span>{t('plan.parentVersion')}</span>
                      <span className="font-mono text-fg">v{lineageVersion}</span>
                    </p>
                  )}
                </div>

                {/* Thẻ ĐẦU cột Overview: phiên phản biện độc lập đã đọc bản này chưa, và nó nêu gì.
                    Trên cả metadata và lưới P1–P8, vì đây là điều kiện để được duyệt. */}
                {/* `verification === null` (vừa đổi bản, sổ còn đang đọc) vẫn có thẻ: nó có mặt
                    riêng cho tình huống đó và KHÔNG vẽ mặt nào của bản cũ. */}
                {planFiles.document && (
                  <PlanReviewCard
                    verification={verification}
                    version={selectionVersion}
                    path={planFiles.document.relativePath}
                    runPending={planFiles.verifyStatus === 'running'}
                    runError={planFiles.verifyError}
                    onRun={handleRunVerification}
                  />
                )}

                {/* Overview Highlights Card */}
                <div className="rounded-lg border border-line bg-panel2/30 p-3.5 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <h2 className="text-[11px] font-semibold text-fg uppercase tracking-wider">
                      {planFiles.document ? 'Plan Metadata & Status' : 'Architecture Scope'}
                    </h2>
                    {planFiles.document && (
                      <span className="rounded bg-panel px-2 py-0.5 text-[10px] font-mono text-brand border border-line">
                        {planFiles.document.label}
                      </span>
                    )}
                  </div>
                  {planFiles.document ? (
                    <div className="space-y-2 text-xs text-muted">
                      <p className="leading-relaxed">
                        {t('plan.sourceNotice')}
                      </p>
                      <div className="grid grid-cols-2 gap-2 pt-1 font-mono text-[11px]">
                        <div>{t('plan.size')}: <span className="text-fg">{(planFiles.document.sizeBytes / 1024).toFixed(1)} KB</span></div>
                        <div>{t('plan.updated')}: <span className="text-fg">{new Date(planFiles.document.modifiedAt).toLocaleTimeString()}</span></div>
                      </div>
                      <div className="pt-2">
                        <button
                          type="button"
                          onClick={() => setPlanSubTab('detailed')}
                          className="inline-flex items-center gap-1.5 rounded-md bg-panel border border-line px-2.5 py-1 text-xs font-medium text-fg hover:bg-panel2 hover:border-zinc-500 transition cursor-pointer"
                        >
                          <span>{t('plan.viewFull')}</span>
                          <ArrowRight className="size-3 text-brand" />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="text-xs leading-relaxed text-muted">
                        Self-hosted <strong>AI Computer</strong> with runtime Information-Flow Control (IFC).
                      </p>
                      <ul className="list-disc space-y-0.5 pl-4 text-xs text-muted">
                        <li>All inputs tagged with provenance labels (Integrity, Confidentiality).</li>
                        <li>Outbound actions gated by scoped, time-bound leases (30-min plan lease).</li>
                      </ul>
                    </>
                  )}
                </div>

                {/* Đánh giá P1–P8 của chính bản đang xem. Bản cũ chưa từng được chấm thì thẻ này tự
                    thu về một dòng nhắc mờ (xem `PlanEvalCard`), không khung rỗng. */}
                {planFiles.document && (
                  <PlanEvalCard
                    evaluation={planFiles.evaluation}
                    indexAvailable={planFiles.indexAvailable}
                    identity={planFiles.document.identity}
                  />
                )}

                {/* Compact Steps List */}
                {currentPlan?.steps && currentPlan.steps.length > 0 && (
                  <div className="space-y-1.5">
                    <div className="flex items-center justify-between pb-1 text-xs font-semibold text-fg">
                      <span>Execution Steps ({currentPlan.steps.length})</span>
                      <span className="text-[11px] font-normal text-muted">Click step to inspect</span>
                    </div>

                    <div className="space-y-1">
                      {currentPlan.steps.map((step) => {
                        const isSelected = selectedStepId === step.id
                        const isDone = step.status === 'xong'
                        return (
                          <div
                            key={step.id}
                            onClick={() => setSelectedStepId(isSelected ? null : step.id)}
                            className={`group flex items-center justify-between rounded-md border p-2.5 text-xs transition cursor-pointer ${
                              isSelected
                                ? 'border-zinc-500 bg-panel2/80 shadow-xs'
                                : 'border-line bg-panel hover:bg-panel2 hover:border-zinc-700'
                            }`}
                          >
                            <div className="flex items-center gap-2.5 min-w-0 flex-1">
                              <span
                                className={`flex size-5 shrink-0 items-center justify-center rounded font-mono text-[10px] font-bold ${
                                  isDone
                                    ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                                    : 'bg-panel2 text-brand border border-line'
                                }`}
                              >
                                {step.id}
                              </span>
                              <span className="truncate font-medium text-fg">{step.description}</span>
                            </div>

                            <div className="flex items-center gap-2 ml-2 shrink-0">
                              <span className="rounded bg-panel2 px-1.5 py-0.2 text-[10px] font-mono text-muted border border-line">
                                {step.risk_level}
                              </span>
                              <span
                                className={`rounded px-1.5 py-0.2 text-[10px] font-medium uppercase tracking-wider ${
                                  isDone
                                    ? 'bg-emerald-500/15 text-emerald-400'
                                    : 'bg-panel2 text-muted'
                                }`}
                              >
                                {isDone ? 'DONE' : 'PENDING'}
                              </span>
                              <ChevronRight
                                className={`size-3.5 text-muted transition group-hover:translate-x-0.5 ${
                                  isSelected ? 'rotate-90 text-brand' : ''
                                }`}
                              />
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                )}
              </div>
            </div>

            {/* Right Side: Step Inspector Split Drawer */}
            {selectedStep && (
              <div className="w-1/2 h-full overflow-y-auto bg-panel2/20 p-5 flex flex-col justify-between border-l border-line animate-in fade-in slide-in-from-right-4 duration-150">
                <div className="space-y-4">
                  {/* Inspector Header */}
                  <div className="flex items-center justify-between border-b border-line pb-3">
                    <div className="flex items-center gap-2">
                      <span className="flex size-6 items-center justify-center rounded-md bg-panel2 font-mono text-xs font-bold text-brand border border-line">
                        {selectedStep.id}
                      </span>
                      <h3 className="text-xs font-semibold text-fg">Step Details & Trace</h3>
                    </div>
                    <button
                      type="button"
                      onClick={() => setSelectedStepId(null)}
                      className="rounded p-1 text-muted hover:bg-panel2 hover:text-fg cursor-pointer"
                      title="Close Inspector"
                    >
                      <X className="size-3.5" />
                    </button>
                  </div>

                  {/* Step Metadata Card */}
                  <div className="rounded-lg border border-line bg-panel p-3.5 space-y-3">
                    <div>
                      <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Goal</span>
                      <p className="mt-1 text-xs text-fg font-medium leading-relaxed">{selectedStep.description}</p>
                    </div>

                    <div className="grid grid-cols-2 gap-3 pt-2 border-t border-line/60">
                      <div>
                        <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Target Resources</span>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {selectedStep.resources.map((res, i) => (
                            <span key={i} className="rounded bg-panel2 px-1.5 py-0.5 text-[11px] font-mono text-fg border border-line">
                              {res}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div>
                        <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Security Policy</span>
                        <div className="mt-1 flex items-center gap-1.5">
                          <Shield className="size-3 text-brand" />
                          <span className="text-xs font-medium text-fg">{selectedStep.risk_level}</span>
                          <span className="text-[10px] text-muted">({selectedStep.out_of_scope ? 'Out of lease' : 'In plan lease'})</span>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Execution Trace / Output Mock */}
                  <div className="space-y-1.5">
                    <span className="text-[10px] font-semibold text-muted uppercase tracking-wider">Resource Trace / Diff</span>
                    <div className="rounded-md border border-line bg-bg p-3 font-mono text-[11px] leading-relaxed text-zinc-300 overflow-x-auto">
                      <div className="text-muted pb-1">// Target: {selectedStep.resources.join(', ')}</div>
                      <div className="text-emerald-400">+ Integrity: VERIFIED_CLEAN</div>
                      <div className="text-zinc-400">+ Confidentiality: RESTRICTED_WORKSPACE</div>
                      <div className="text-muted pt-1">// Status: {selectedStep.status === 'xong' ? 'Completed successfully' : 'Queued for execution'}</div>
                    </div>
                  </div>
                </div>

                {/* Footer Step Navigation */}
                <div className="flex items-center justify-between border-t border-line pt-3 mt-4">
                  <button
                    type="button"
                    onClick={() => handleNavigateStep('prev')}
                    className="flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
                  >
                    <ArrowLeft className="size-3" />
                    <span>Previous</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => handleNavigateStep('next')}
                    className="flex items-center gap-1 rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
                  >
                    <span>Next</span>
                    <ArrowRight className="size-3" />
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Detailed Plan View — file sandbox nếu có, ngược lại dùng store */
          <div className="h-full w-full min-w-0 overflow-y-auto p-6 space-y-4">
            {renderedDetailedContent}
            {mode === 'ACT' && endorsed && (
              <div className="mt-4 rounded-md border border-zinc-700 bg-panel2/50 p-3 text-xs text-muted">
                Plan endorsed by user at {endorsed.created_at}. 30-minute plan-scoped lease is active.
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
