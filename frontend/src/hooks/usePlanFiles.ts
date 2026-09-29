import { useCallback, useEffect, useRef, useState } from 'react'
import { agentApi } from '../lib/agentApi'
import { usePlanStore } from '../store/planStore'
import {
  DEFAULT_PLAN_GATE,
  PlanRepositoryHttpError,
  PlanReviewBlockedError,
  createPlanRepository,
  createPlanStatusClient,
  reconcilePlanSelection,
} from '../lib/plans'
import type {
  PlanDocument,
  PlanEvaluation,
  PlanGate,
  PlanManifest,
  PlanOwnership,
  PlanRepository,
  PlanReviewState,
  PlanSelection,
  PlanStatusClient,
  PlanStatusReview,
  PlanVerification,
  PlanWake,
} from '../lib/plans'
import { useUiStore } from '../store/uiStore'

export type PlanFilesStatus = 'loading' | 'ready' | 'empty' | 'error'

/** Quyết định người dùng đã lưu cho một bản plan (hợp đồng §2 `POST /api/agent/plans/review`). */
export type PlanReviewDecision = 'approved' | 'changes_requested'

export interface PlanReview {
  identity: string
  decision: PlanReviewDecision
  note: string
  updatedAt: number
}

export type PlanReviewStatus = 'idle' | 'saving' | 'error' | 'blocked'

/** Trạng thái gọi `POST /api/agent/plans/verify` (nhờ harness mở phiên phản biện). */
export type PlanVerifyStatus = 'idle' | 'running' | 'error'

/** Mặt phản biện CHƯA BIẾT — đúng hình dạng `readPlanVerification(undefined)` trả về. */
const UNKNOWN_VERIFICATION: PlanVerification = {
  state: 'unknown',
  at: null,
  criticSessionId: null,
  issues: [],
}

const NO_OWNER: PlanOwnership = { sessionId: null }

/**
 * Kết quả một lần ghi quyết định, đủ để nói thật chuyện gì xảy ra sau cú bấm: quyết định vào sổ
 * chưa, có mở được lượt chạy mới không, lượt đó là lượt nào. `resumed`/`recorded` giữ ba trạng thái
 * — `null` là "harness không nói", không được đọc thành "không mở".
 */
export interface PlanReviewResult {
  decision: PlanReviewDecision
  version: number
  note: string
  recorded: boolean | null
  forwarded: boolean | null
  resumed: boolean | null
  turnId: string | null
  /** Harness giải thích vì sao mở/không mở được lượt, kèm câu chữ của chính nó; `null` = harness cũ. */
  wake: PlanWake | null
  /** Chỉ ở chế độ `warn`: harness cho qua một bản chưa đạt phản biện — nói ra, không giấu. */
  approvalWarning: string | null
}

/**
 * Đọc `review` mà `GET /__box/plans` trả kèm mỗi bản ghi (hoặc `null`). Dữ liệu
 * tới từ mạng nên kiểm tra từng trường thay vì tin vào kiểu.
 *
 * Từ vòng 20 hàm này KHÔNG còn là nguồn kết luận "đã duyệt": `.reviews/` trên box rỗng trong khi
 * giao diện vẫn hiện hai nhóm "approved", vì nhãn cũ chỉ là vị trí trong danh sách version. Nguồn
 * thật là sổ duyệt của harness (`plan_reviews`), đọc qua `PlanStatusClient`. Giữ hàm lại vì nó mô
 * tả đúng hợp đồng của route box và còn dùng để đọc lại vết sau này.
 */
export function readPlanReview(entry: unknown): PlanReview | null {
  if (!entry || typeof entry !== 'object') return null
  const review = (entry as { review?: unknown }).review
  if (!review || typeof review !== 'object') return null
  const { identity, decision, note, updatedAt } = review as Record<string, unknown>
  if (typeof identity !== 'string') return null
  if (decision !== 'approved' && decision !== 'changes_requested') return null
  return {
    identity,
    decision,
    note: typeof note === 'string' ? note : '',
    updatedAt: typeof updatedAt === 'number' ? updatedAt : 0,
  }
}

export interface PlanFilesState {
  status: PlanFilesStatus
  manifest: PlanManifest | null
  selection: PlanSelection | null
  document: PlanDocument | null
  error: string | null
  refresh: () => Promise<void>
  selectIdentity: (identity: string, version?: number) => void
  selectVersion: (version: number) => void
  /** Quyết định đã lưu cho bản đang chọn, đọc từ sổ duyệt của harness (`plan_reviews`). */
  selectedReview: PlanStatusReview | null
  /** Trạng thái thật của nhóm: `none | draft | submitted | approved | changes_requested | unknown`. */
  planState: PlanReviewState
  /** `true` = bản đã bị sửa sau khi duyệt, chuẩn thuận cũ không còn áp dụng. */
  reviewStale: boolean
  /** `false` = chỉ mục box không đọc được, chưa biết bản này có được chấm P1–P8 hay không. */
  indexAvailable: boolean
  /** Bản chấm P1–P8 của đúng bản đang chọn; `null` với bản cũ chưa từng được chấm. */
  evaluation: PlanEvaluation | null
  /**
   * Mặt phản biện của đúng bản đang chọn (`none | ok | revise | unknown`); `unknown` = chưa biết.
   * `null` = CHƯA đọc xong sổ cho bản này (vừa đổi bản) — khác hẳn `unknown` ("sổ không đọc được"),
   * nên giao diện không được vẽ mặt nào khi còn `null`.
   */
  verification: PlanVerification | null
  /** Phiên đang sở hữu bản kế hoạch — lượt chạy tiếp theo mở trong phiên này. */
  ownership: PlanOwnership
  /** Công tắc cổng duyệt harness đang chạy (`enforce | warn | off`) — nút Duyệt siết đúng bằng nó. */
  gate: PlanGate
  /**
   * `true` khi harness CHẮC CHẮN từ chối cú bấm, để giao diện không mời một cú bấm vô ích:
   *
   * - `verification === null` — đang đọc sổ cho bản mới: chưa biết thì chưa mở nút.
   * - `verification.state === 'none'` — harness nói rõ bản này chưa qua phiên phản biện.
   * - `verification.state === 'revise'` + `gate.verifyMode === 'enforce'` — bản còn lỗi phải sửa và
   *   harness chặn cứng: cú bấm chỉ đi tới 409. Ở `warn`/`off` thì KHÔNG khoá: harness cho qua thật,
   *   và cái giá của việc cho qua được nói ra bằng `approvalWarning`.
   *
   * `unknown` (harness cũ không trả trường) KHÔNG khoá: thà để harness trả 409 kèm lý do của chính nó
   * còn hơn giao diện tự khoá oan một đường vẫn hợp lệ.
   */
  approvalLocked: boolean
  /** Lỗi đọc trạng thái duyệt; hiện ở dải cảnh báo riêng, không lẫn với lỗi tải kế hoạch. */
  statusError: string | null
  /** `false` = quyết định đã vào sổ harness nhưng chưa chuyển được sang box; `null` = chưa ghi lần nào. */
  reviewForwarded: boolean | null
  reviewStatus: PlanReviewStatus
  reviewError: string | null
  /** Kết quả quyết định vừa gửi (`null` = chưa gửi lần nào trong bản đang xem). */
  reviewResult: PlanReviewResult | null
  /** 409 "bị khoá vì chưa phản biện" — giữ nguyên văn `code`/`reason`/`remedy` của harness. */
  reviewBlocked: PlanReviewBlockedError | null
  /** `running` = đã nhờ harness mở phiên phản biện, đang chờ nó nhận. */
  verifyStatus: PlanVerifyStatus
  verifyError: string | null
  /**
   * Nhờ harness mở phiên `plan-review` cho bản đang xem rồi đọc lại sổ. Thân trả về
   * (`recorded`/`resumed`/`turnId`) không được hứa hẹn gì ở đây: mặt phản biện chỉ đổi khi phiên đó
   * THẬT SỰ chạy xong, nên giao diện chờ sổ, không tự suy.
   */
  runVerification: () => Promise<void>
  /** Ghi quyết định duyệt / yêu cầu sửa xuống harness rồi tải lại kế hoạch + trạng thái. */
  submitReview: (decision: PlanReviewDecision, note?: string) => Promise<void>
}

/** Hook cho manifest/content, giữ lựa chọn khi refresh và bỏ mọi response cũ. */
export function usePlanFiles(
  repository?: PlanRepository,
  statusClient?: PlanStatusClient,
): PlanFilesState {
  const defaultRepository = useRef<PlanRepository | null>(null)
  if (!defaultRepository.current) defaultRepository.current = createPlanRepository()
  const activeRepository = repository ?? defaultRepository.current
  const defaultStatusClient = useRef<PlanStatusClient | null>(null)
  if (!defaultStatusClient.current) defaultStatusClient.current = createPlanStatusClient()
  const activeStatusClient = statusClient ?? defaultStatusClient.current
  const [manifest, setManifest] = useState<PlanManifest | null>(null)
  const [selection, setSelection] = useState<PlanSelection | null>(null)
  const [document, setDocument] = useState<PlanDocument | null>(null)
  const [status, setStatus] = useState<PlanFilesStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const [reviewStatus, setReviewStatus] = useState<PlanReviewStatus>('idle')
  const [reviewError, setReviewError] = useState<string | null>(null)
  const [reviewForwarded, setReviewForwarded] = useState<boolean | null>(null)
  const [planState, setPlanState] = useState<PlanReviewState>('unknown')
  const [reviewStale, setReviewStale] = useState(false)
  const [indexAvailable, setIndexAvailable] = useState(true)
  const [evaluation, setEvaluation] = useState<PlanEvaluation | null>(null)
  const [selectedReview, setSelectedReview] = useState<PlanStatusReview | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  // `null` = chưa đọc xong sổ cho bản đang chọn (khác `UNKNOWN_VERIFICATION` = "không đọc được").
  const [verification, setVerification] = useState<PlanVerification | null>(null)
  const [ownership, setOwnership] = useState<PlanOwnership>(NO_OWNER)
  const [gate, setGate] = useState<PlanGate>(DEFAULT_PLAN_GATE)
  const [reviewResult, setReviewResult] = useState<PlanReviewResult | null>(null)
  const [reviewBlocked, setReviewBlocked] = useState<PlanReviewBlockedError | null>(null)
  const [verifyStatus, setVerifyStatus] = useState<PlanVerifyStatus>('idle')
  const [verifyError, setVerifyError] = useState<string | null>(null)
  // `plan_written` của agent làm số này tăng → manifest được tải lại; lần nạp
  // khi mount vẫn giữ nguyên.
  const planRevision = useUiStore((s) => s.planRevision)
  const workflowRevision = usePlanStore(s => s.runs.find(r =>
    (r.document?.identity === selection?.identity && r.document?.version === selection?.version) ||
    r.documents?.some(d => d.identity === selection?.identity && d.version === selection?.version))?.revision ?? 0)
  const generationRef = useRef(0)
  // Lượt đọc trạng thái có bộ đếm riêng: tải manifest không được vô hiệu hoá một lượt đọc sổ duyệt
  // đang bay, và ngược lại.
  const statusGenerationRef = useRef(0)
  const selectionRef = useRef<PlanSelection | null>(null)
  // Bản mà dòng kết quả / dải "bị khoá" đang nói tới: đổi bản thì hai thứ đó hết đúng.
  const statusSelectionRef = useRef<string | null>(null)
  const refreshRef = useRef<(() => Promise<void>) | null>(null)

  useEffect(() => {
    selectionRef.current = selection
  }, [selection])

  /** Dòng kết quả + dải "bị khoá" nói về MỘT bản cụ thể; đổi bản thì chúng hết đúng. */
  const clearReviewFacts = useCallback(() => {
    setReviewResult(null)
    setReviewBlocked(null)
    setReviewStatus((current) => (current === 'blocked' ? 'idle' : current))
  }, [])

  /**
   * Mọi thứ SUY TỪ KẾT LUẬN của một bản cụ thể (trạng thái nhóm, chuẩn thuận, điểm P1–P8, mặt phản
   * biện, chủ phiên) — đổi bản là chúng hết đúng ngay, không đợi lượt đọc sổ của bản mới trả lời.
   *
   * Vì sao phải xoá trước khi đọc: giữ lại kết luận của bản cũ trong lúc chờ mạng là lần duy nhất
   * giao diện tự dựng một lời khẳng định chưa ai nói (verdict của v1 in trên đầu v2, nút khoá theo
   * bản cũ). Và vì sao KHÔNG đặt `unknown` thay chỗ: `unknown` là một câu khác — "sổ không đọc
   * được" — trong khi chỗ này chỉ là "chưa trả lời"; `verification = null` nói đúng điều đó.
   */
  const clearStatusFacts = useCallback(() => {
    setPlanState('unknown')
    setReviewStale(false)
    setIndexAvailable(true)
    setEvaluation(null)
    setSelectedReview(null)
    setVerification(null)
    setOwnership(NO_OWNER)
  }, [])

  const resetStatus = useCallback(() => {
    statusGenerationRef.current += 1
    statusSelectionRef.current = null
    setStatusError(null)
    setGate(DEFAULT_PLAN_GATE)
    clearStatusFacts()
    clearReviewFacts()
  }, [clearReviewFacts, clearStatusFacts])

  /**
   * Đọc trạng thái duyệt thật + bản chấm P1–P8 cho đúng bản đang chọn.
   *
   * Hỏng đường này (`/api/agent/plans/status` chưa có, thiếu quyền, mất mạng) thì trạng thái là
   * `unknown` và chỉ có một dải cảnh báo — tuyệt đối không rơi về `approved` theo vị trí như trước.
   */
  const loadStatus = useCallback(
    async (nextSelection: PlanSelection | null) => {
      if (!nextSelection) {
        resetStatus()
        return
      }
      const generation = ++statusGenerationRef.current
      const selectionKey = `${nextSelection.identity}:${nextSelection.version}`
      if (statusSelectionRef.current !== selectionKey) {
        statusSelectionRef.current = selectionKey
        // Bản đổi: bỏ hết kết luận của bản cũ ngay, rồi mới hỏi sổ (xem `clearStatusFacts`).
        clearStatusFacts()
        clearReviewFacts()
      }
      try {
        const report = await activeStatusClient.read(nextSelection.identity, nextSelection.version)
        if (generation !== statusGenerationRef.current) return
        setPlanState(report.state)
        setReviewStale(report.reviewStale)
        setIndexAvailable(report.indexAvailable)
        setEvaluation(report.evaluation)
        setSelectedReview(report.review)
        setVerification(report.verification)
        setOwnership(report.ownership)
        setGate(report.gate)
        setStatusError(null)
      } catch (cause) {
        if (generation !== statusGenerationRef.current) return
        setPlanState('unknown')
        setReviewStale(false)
        setIndexAvailable(false)
        setEvaluation(null)
        // Không đọc được sổ duyệt thì không có quyết định nào để hiện: thà nói "không đọc được"
        // còn hơn giữ lại một quyết định cũ và để người dùng tưởng nó còn hiệu lực.
        setSelectedReview(null)
        // Không đọc được sổ thì cũng không biết mặt phản biện của bản này: để `unknown`, không đoán.
        setVerification(UNKNOWN_VERIFICATION)
        setOwnership(NO_OWNER)
        setStatusError(messageFor(cause))
      }
    },
    [activeStatusClient, resetStatus, clearReviewFacts, clearStatusFacts],
  )

  const loadDocument = useCallback(
    async (nextSelection: PlanSelection, retryOnMissing: boolean) => {
      const generation = ++generationRef.current
      setDocument(null)
      setStatus('loading')
      setError(null)
      try {
        const nextDocument = await activeRepository.read(nextSelection.identity, nextSelection.version)
        if (generation !== generationRef.current) return
        setDocument(nextDocument)
        setStatus('ready')
        await loadStatus(nextSelection)
      } catch (cause) {
        if (generation !== generationRef.current) return
        if (retryOnMissing && cause instanceof PlanRepositoryHttpError && cause.status === 404) {
          void refreshRef.current?.()
          return
        }
        setError(messageFor(cause))
        setStatus('error')
      }
    },
    [activeRepository, loadStatus],
  )

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current
    setStatus('loading')
    setError(null)
    try {
      const nextManifest = await activeRepository.list()
      if (generation !== generationRef.current) return
      const nextSelection = reconcilePlanSelection(nextManifest, selectionRef.current)
      setManifest(nextManifest)
      setSelection(nextSelection)
      setDocument(null)
      if (!nextSelection) {
        setStatus('empty')
        resetStatus()
        return
      }

      const nextDocument = await activeRepository.read(nextSelection.identity, nextSelection.version)
      if (generation !== generationRef.current) return
      setDocument(nextDocument)
      setStatus('ready')
      await loadStatus(nextSelection)
    } catch (cause) {
      if (generation !== generationRef.current) return
      if (cause instanceof PlanRepositoryHttpError && cause.status === 404) {
        // File có thể biến mất giữa list/read; refresh manifest đúng một lần.
        try {
          const retryManifest = await activeRepository.list()
          if (generation !== generationRef.current) return
          const retrySelection = reconcilePlanSelection(retryManifest, selectionRef.current)
          setManifest(retryManifest)
          setSelection(retrySelection)
          if (!retrySelection) {
            setDocument(null)
            setStatus('empty')
            resetStatus()
            return
          }
          const retryDocument = await activeRepository.read(retrySelection.identity, retrySelection.version)
          if (generation !== generationRef.current) return
          setDocument(retryDocument)
          setStatus('ready')
          await loadStatus(retrySelection)
          return
        } catch (retryCause) {
          if (generation !== generationRef.current) return
          setError(messageFor(retryCause))
          setStatus('error')
          return
        }
      }
      setError(messageFor(cause))
      setStatus('error')
    }
  }, [activeRepository, loadStatus, resetStatus])

  refreshRef.current = refresh

  useEffect(() => {
    void refresh()
    return () => {
      generationRef.current += 1
      statusGenerationRef.current += 1
    }
  }, [refresh, planRevision])
  useEffect(() => {
    if (selectionRef.current && workflowRevision) void loadStatus(selectionRef.current)
  }, [workflowRevision, loadStatus])

  const selectIdentity = useCallback(
    (identity: string, version?: number) => {
      const plan = manifest?.plans.find((item) => item.identity === identity)
      if (!plan) return
      // Ngữ cảnh của ý định tự mở tab có thể chỉ đích danh một version; không có
      // thì lấy bản mới nhất như trước.
      const target =
        version !== undefined ? plan.versions.find((item) => item.version === version) : undefined
      const chosen = target ?? plan.versions[0]
      if (!chosen) return
      const nextSelection = { identity, version: chosen.version }
      setSelection(nextSelection)
      void loadDocument(nextSelection, true)
    },
    [loadDocument, manifest],
  )

  const selectVersion = useCallback(
    (version: number) => {
      if (!selection || selection.version === version) return
      const plan = manifest?.plans.find((item) => item.identity === selection.identity)
      if (!plan?.versions.some((item) => item.version === version)) return
      const nextSelection = { identity: selection.identity, version }
      setSelection(nextSelection)
      void loadDocument(nextSelection, true)
    },
    [loadDocument, manifest, selection],
  )

  const runVerification = useCallback(async () => {
    const current = selectionRef.current
    if (!current) return
    setVerifyStatus('running')
    setVerifyError(null)
    try {
      await agentApi<unknown>('/plans/verify', { identity: current.identity, version: current.version })
      // Kết quả chỉ hiện qua sổ phản biện — đọc lại, không tự vẽ "đã phản biện".
      await refresh()
      setVerifyStatus('idle')
    } catch (cause) {
      setVerifyStatus('error')
      setVerifyError(messageFor(cause))
    }
  }, [refresh])

  const submitReview = useCallback(
    async (decision: PlanReviewDecision, note = '') => {
      const current = selectionRef.current
      if (!current) {
        setReviewStatus('error')
        setReviewError('PLAN_REVIEW_NO_SELECTION: no plan document is selected')
        return
      }
      setReviewStatus('saving')
      setReviewError(null)
      setReviewForwarded(null)
      setReviewResult(null)
      setReviewBlocked(null)
      try {
        // Ghi vào SỔ DUYỆT của harness (kèm số version, để duyệt v1 không làm v2 thành đã duyệt);
        // harness tự chuyển tiếp sang box và trả `forwarded`.
        const workflow = usePlanStore.getState().runs.find(r => r.document?.identity === current.identity && r.document?.version === current.version)
        const reviewArgs: Parameters<PlanStatusClient['submitReview']> = [
          current.identity,
          current.version,
          decision,
          note,
        ]
        if (workflow?.document) reviewArgs[4] = { revision: workflow.revision, contentHash: workflow.document.contentHash, invocationId: crypto.randomUUID() }
        const outcome = await activeStatusClient.submitReview(...reviewArgs)
        setReviewForwarded(outcome.forwarded)
        setReviewResult({
          decision,
          version: current.version,
          note,
          recorded: outcome.recorded,
          forwarded: outcome.forwarded,
          resumed: outcome.resumed,
          turnId: outcome.turnId,
          // Lời giải thích của harness đi nguyên qua: `resumed` chỉ là một bit, `wake` mới nói vì sao.
          wake: outcome.wake ?? null,
          approvalWarning: outcome.approvalWarning ?? null,
        })
        await refresh()
        await usePlanStore.getState().refresh()
        setReviewStatus('idle')
      } catch (cause) {
        if (cause instanceof PlanReviewBlockedError) {
          // 409: quyết định KHÔNG vào sổ. Vẫn đọc lại sổ harness — sổ là nguồn sự thật, và nó có thể
          // vừa đổi vì một phiên phản biện vừa chạy xong.
          setReviewStatus('blocked')
          setReviewBlocked(cause)
          await refresh()
          return
        }
        setReviewStatus('error')
        setReviewError(messageFor(cause))
      }
    },
    [activeStatusClient, refresh],
  )

  return {
    status,
    manifest,
    selection,
    document,
    error,
    refresh,
    selectIdentity,
    selectVersion,
    selectedReview,
    planState,
    reviewStale,
    indexAvailable,
    evaluation,
    verification,
    ownership,
    gate,
    approvalLocked: approvalLockedFor(verification, gate),
    statusError,
    reviewForwarded,
    reviewStatus,
    reviewError,
    reviewResult,
    reviewBlocked,
    verifyStatus,
    verifyError,
    runVerification,
    submitReview,
  }
}

function messageFor(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'Unable to load plan files.'
}

/**
 * Nút Duyệt có bị khoá không — câu trả lời phải TRÙNG với câu harness sẽ trả lời, nếu không giao diện
 * mời một cú bấm chắc chắn bị từ chối (`revise` + `enforce`), hoặc khoá một đường harness vẫn cho qua
 * (`revise` + `warn`/`off`).
 */
function approvalLockedFor(verification: PlanVerification | null, gate: PlanGate): boolean {
  if (!verification) return true
  if (verification.state === 'none') return true
  return verification.state === 'revise' && gate.verifyMode === 'enforce'
}
