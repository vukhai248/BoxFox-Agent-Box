/**
 * Trạng thái chế độ `/design` của phiên đang mở (P1 — vỏ chế độ).
 *
 * Vì sao cần store riêng: cùng khuôn `researchStore` — nguồn sự thật là sự kiện `design_*` trên luồng
 * sự kiện phiên (vòng 1200 ms của `ChatPanel`); component đọc store, và chỉ gọi mạng khi có sự kiện
 * mới hoặc chế độ vừa đổi. `hooks/useDesignSync` là cầu nối duy nhất đẩy dữ liệu vào đây.
 *
 * Cảnh canvas do agent vẽ đến qua sự kiện `design_canvas` (P2) — store giữ chúng trong `scenes`,
 * KHÔNG tự bịa op nào: op sai thì bỏ và tăng `rejectedOps`.
 */
import { create } from 'zustand'
import {
  applyCanvasAction,
  CANVAS_PROTOCOL,
  createEmptyScene,
  diffSceneOps,
  parseCanvasMessage,
  type CanvasAction,
  type CanvasScene,
} from '../lib/canvas'
import { ApiError } from '../lib/agentApi'
import { asBool, asNumber, asRecord, asString } from '../lib/researchMode'
import {
  activeRun,
  DESIGN_MODE_OFF,
  isDesignEvent,
  openExitPrompt,
  readBatch,
  readCanvasScene,
  readDesignMode,
  readNotice,
  readPrompt,
  readReview,
  readRun,
  readRuns,
  stepForPhase,
  type DesignMode,
  type DesignNotice,
  type DesignPrompt,
  type DesignRun,
  type Json,
} from '../lib/designMode'
import { useHarnessChatStore } from './harnessChatStore'
import {
  answerDesignPrompt,
  approveTouchList,
  fetchDesignRun,
  fetchDesignRuns,
  patchDesignRun,
  setDesignMode,
  type DesignExitChoice,
  type DesignPromptAnswerBody,
} from '../lib/designApi'

/** Sự kiện phiên ở hình dạng store cần — khớp `HarnessEvent` nhưng không phụ thuộc nó. */
export interface DesignEvent {
  seq: number
  type: string
  data: Record<string, unknown>
  created?: number
}

/**
 * Lỗi gần nhất của một nhánh ghi: giữ CẢ mã (để giao diện dịch thành câu đọc được, §7.6) lẫn thông
 * điệp thô (dự phòng khi mã lạ). Trước đây chỉ giữ chuỗi thô nên mọi từ chối đều hiện như nút chết.
 */
export interface DesignError {
  code: string
  message: string
}

/** Lô op canvas gần nhất của một run — chỗ phát lại đọc để dựng nét vẽ dần. */
export interface CanvasOpBatch {
  actor: string
  ops: CanvasAction[]
  /** `seq` của sự kiện `design_canvas` sinh ra lô này (khoá chống phát lại hai lần). */
  seq: number
}

interface DesignState {
  sessionId: string
  mode: DesignMode
  runs: DesignRun[]
  /** Run đang mở (mode trỏ tới) — client giữ để thẻ bàn giao biết run nào đang xem. */
  activeRunId: string
  /** `designId -> CanvasScene` do sự kiện `design_canvas` dựng nên. */
  scenes: Record<string, CanvasScene>
  /**
   * `designId -> canvasSeq` mà cảnh đang giữ đã bao gồm.
   *
   * Vì sao cần: cảnh có HAI nguồn — sự kiện `design_canvas` (reduce op) và payload CHI TIẾT của run
   * (`canvasScene`, tải lại trang vẫn thấy canvas). Thiếu bộ đếm này, một sự kiện phát lại có thể
   * được áp LẦN HAI lên cảnh vừa nhận từ payload (op bị chối oan, badge "N op bị bỏ" nói dối).
   */
  sceneSeq: Record<string, number>
  /** `designId -> actor` của sự kiện `design_canvas` gần nhất (`'agent'`/`'user'`/…). */
  sceneActor: Record<string, string>
  /**
   * `designId -> lô op` của sự kiện `design_canvas` gần nhất (`seq` + actor + op ĐÃ nhận).
   *
   * Vì sao store phải giữ: store giảm op vào `scenes`, nên cảnh cuối là thứ duy nhất còn lại — tầng
   * phát lại (`useCanvasPlayback`) cần CHÍNH lô op ấy để dựng nét vẽ dần, và không được bịa lại nó.
   * Chỉ op đã qua `parseCanvasOp` + được reducer chấp nhận mới nằm đây.
   */
  lastOps: Record<string, CanvasOpBatch>
  /** `sceneVersion` lớn nhất đã thấy — nguồn sự thật cho nhãn "cảnh ở bản N". */
  sceneVersion: number
  /** Lời hỏi đang thấy, gộp mọi run (nền + chi tiết) — một chỗ cho thẻ lời hỏi. */
  prompts: DesignPrompt[]
  /** Số op canvas bị bỏ vì sai giao thức (A3) — không bao giờ vẽ dữ liệu bịa. */
  rejectedOps: number
  /** Brief của run đang mở (`state.brief` từ tuyến chi tiết). */
  brief: Json
  /** `designId -> payload` báo cáo bàn giao gần nhất (P4). */
  reports: Record<string, Json>
  /**
   * Thông báo nền `design_notice` (§9) theo thứ tự đến — mỗi sự kiện đúng MỘT thẻ, khoá chống
   * trùng là `(designId, kind, seq)`. Store KHÔNG suy diễn thêm loại thông báo nào.
   */
  notices: DesignNotice[]
  /**
   * Tin nhắn chờ nộp thành lượt main sau khi thoát chế độ (ra khỏi phạm vi / dùng cho plan). Vì sao
   * tách khỏi component: lượt chỉ được nộp khi thoát chế độ THÀNH CÔNG — nếu server còn đòi chọn thoát
   * (§5.1) thì tin nhắn nằm đây và được xả ở `resolveExit`.
   */
  pendingTurn: string
  /** Lời hỏi 409 khi tắt mode lúc run còn chạy: có thì phải neo thẻ vào nút Design. */
  exitChoice: DesignExitChoice | null
  loading: boolean
  error: DesignError | null
  /**
   * `seq` lớn nhất của sự kiện `design_*` đã xử lý. Phiên CHƯA có khoá ở đây là phiên chưa từng
   * nhận payload có sự kiện, nên payload đầu tiên (một ảnh chụp lịch sử) không được coi là tin mới.
   */
  lastEventSeq: number

  /** Áp MỘT sự kiện `design_*` vào trạng thái (thuần, không gọi mạng). */
  applyEvent: (event: DesignEvent) => void
  /** Áp một sự kiện `design_canvas`: reduce từng op, đếm op bị bỏ. */
  applyCanvas: (event: DesignEvent) => void
  /** Xoá dữ liệu của phiên TRƯỚC khi đổi phiên (jobs/prompts/brief/lỗi/thẻ thoát). */
  clearSessionChange: () => void
  sync: (sessionId: string, config: unknown, events: readonly DesignEvent[]) => void
  refresh: () => Promise<void>
  refreshDetail: (designId: string) => Promise<void>
  setMode: (on: boolean, by: 'toggle' | 'command') => Promise<'ok' | 'exit-choice' | 'error'>
  resolveExit: (choice: 'pause' | 'background') => Promise<void>
  clearExitChoice: () => void
  approveTouchList: (designId: string, revision: number, answers?: DesignPromptAnswerBody) => Promise<boolean>
  updateRun: (designId: string, body: { action: string; revision?: number } & Record<string, unknown>) => Promise<boolean>
  answerPrompt: (promptId: string, body: DesignPromptAnswerBody) => Promise<boolean>
  /** Xếp một tin nhắn main để nộp sau khi thoát chế độ; chuỗi rỗng = huỷ xếp hàng. */
  queueTurn: (text: string) => void
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** Lỗi → `{code, message}`: `ApiError` mang mã trong `code`; lỗi khác chỉ có thông điệp. */
function readError(error: unknown): DesignError {
  if (error instanceof ApiError) return { code: error.code ?? '', message: error.message }
  return { code: '', message: message(error) }
}

/** Bước hiển thị từ payload `design_run` — backend gửi `step`, thiếu thì suy từ pha. */
function stepOf(data: Json, phase: string) {
  const text = asString(data.step)
  return text ? (text as DesignRun['step']) : stepForPhase(phase)
}

/** Ghép payload `design_run` (sự kiện) vào một hàng run đã biết. */
function mergeRun(current: DesignRun | null, data: Json): DesignRun | null {
  const designId = asString(data.designId) || current?.designId || ''
  if (!designId) return current
  const phase = asString(data.phase) || current?.phase || ''
  return {
    designId,
    sessionId: current?.sessionId ?? '',
    status: (asString(data.status) || current?.status || 'scoping') as DesignRun['status'],
    phase,
    step: stepOf(data, phase),
    origin: asString(data.origin) || current?.origin || '',
    background: data.background === undefined ? (current?.background ?? false) : asBool(data.background),
    revision: asNumber(data.revision) ?? current?.revision ?? 0,
    goal: current?.goal ?? '',
    touchListRevision: current?.touchListRevision ?? 0,
    touchList: current?.touchList ?? null,
    prompts: current?.prompts ?? [],
    // Lô ghi/soát độc lập: nhận từ sự kiện nếu backend gửi kèm, ngược lại giữ cái đang có
    // (tuyến chi tiết `refreshDetail` là nguồn chính).
    batch: readBatch(data.batch) ?? current?.batch ?? null,
    review: readReview(data.review) ?? current?.review ?? null,
    // Sự kiện `design_run` KHÔNG mang cảnh (payload gọn) — giữ cảnh đang biết, chờ tuyến chi tiết.
    canvasScene: current?.canvasScene ?? null,
    canvasSeq: current?.canvasSeq ?? 0,
    canvasActor: current?.canvasActor ?? 'agent',
  }
}

/**
 * Parse MỘT op canvas từ `unknown`; `null` khi sai hình dạng.
 *
 * Vì sao bọc `parseCanvasMessage` thay vì tự đoán trường: giao thức canvas đã đông cứng, nên một op
 * trần chỉ hợp lệ nếu parse được thành `CanvasActionMessage` của `boxfox.canvas.v1`.
 */
export function parseCanvasOp(value: unknown): CanvasAction | null {
  const parsed = parseCanvasMessage({ protocol: CANVAS_PROTOCOL, type: 'action', action: value })
  return parsed && parsed.type === 'action' ? parsed.action : null
}

export const useDesignStore = create<DesignState>((set, get) => ({
  sessionId: '',
  mode: DESIGN_MODE_OFF,
  runs: [],
  activeRunId: '',
  scenes: {},
  sceneSeq: {},
  sceneActor: {},
  lastOps: {},
  sceneVersion: 0,
  prompts: [],
  rejectedOps: 0,
  brief: {},
  reports: {},
  notices: [],
  pendingTurn: '',
  exitChoice: null,
  loading: false,
  error: null,
  lastEventSeq: 0,

  applyEvent: (event) => {
    const data = asRecord(event.data)
    if (event.type === 'design_mode') {
      const on = asBool(data.on)
      set({
        mode: { ...get().mode, on, enteredBy: asString(data.by) },
        // Chế độ vừa TẮT ⇒ lời hỏi thoát không còn nghĩa: xoá NGAY, không đợi lần tải sau dựng lại thẻ.
        ...(on ? {} : { exitChoice: null }),
      })
      return
    }
    if (event.type === 'design_canvas') {
      get().applyCanvas(event)
      return
    }
    if (event.type === 'design_run' || event.type === 'design_scope') {
      const designId = asString(data.designId)
      if (!designId) return
      const current = get().runs.find((run) => run.designId === designId) ?? null
      const merged = event.type === 'design_run'
        ? mergeRun(current, data)
        : current
          ? { ...current, revision: asNumber(data.revision) ?? current.revision }
          : null
      if (!merged) return
      const runs = get().runs.some((run) => run.designId === designId)
        ? get().runs.map((run) => (run.designId === designId ? merged : run))
        : [...get().runs, merged]
      set({ runs, activeRunId: get().mode.activeRunId || get().activeRunId || designId })
      return
    }
    if (event.type === 'design_prompt') {
      const prompt = readPrompt({ ...data, questions: data.questions })
      if (!prompt) return
      const prompts = get().prompts.some((item) => item.promptId === prompt.promptId)
        ? get().prompts.map((item) => (item.promptId === prompt.promptId ? prompt : item))
        : [...get().prompts, prompt]
      set({ prompts })
      // Thẻ thoát CHỈ có nghĩa khi chế độ còn BẬT: server đóng lời hỏi là fix chính, còn đây là lớp
      // phòng thủ phía client — một lời hỏi `exit-choice` còn mở không bao giờ được dựng thẻ sau khi
      // chế độ đã tắt (nếu không, chủ nhà chọn xong vẫn thấy thẻ quay lại và phải chọn lần nữa).
      if (prompt.kind === 'exit-choice' && prompt.status === 'open' && get().mode.on) {
        set({ exitChoice: { code: 'DESIGN_EXIT_CHOICE_REQUIRED', prompt, message: prompt.note } })
      }
    }
    if (event.type === 'design_notice') {
      const notice = readNotice(data, event.seq)
      if (!notice) return
      // Poll có thể bơm lại cùng `seq`; khoá chống trùng giữ đúng MỘT thẻ cho mỗi sự kiện (§9).
      const duplicate = get().notices.some(
        (item) => item.designId === notice.designId && item.kind === notice.kind && item.seq === notice.seq,
      )
      if (duplicate) return
      set({ notices: [...get().notices, notice] })
      return
    }
    if (event.type === 'design_report') {
      const designId = asString(data.designId)
      if (!designId) return
      set({ reports: { ...get().reports, [designId]: data } })
    }
  },

  applyCanvas: (event) => {
    const data = asRecord(event.data)
    const designId = asString(data.designId)
    if (!designId) return
    const ops = Array.isArray(data.ops) ? data.ops : []
    const incoming = asNumber(data.sceneVersion) ?? asNumber(data.seq) ?? 0
    // Sự kiện phát lại mà cảnh đang giữ ĐÃ bao gồm (cảnh nhận từ payload chi tiết, hoặc vòng poll cũ)
    // ⇒ bỏ qua NGUYÊN sự kiện: áp lại lần hai sẽ tạo op bị chối oan và làm badge đếm sai.
    if (incoming > 0 && incoming <= (get().sceneSeq[designId] ?? 0)) return
    const actor = asString(data.actor) || get().sceneActor[designId] || ''
    // `actor:'user'` mang cảnh chủ nhà nhưng KHÔNG mang op (IF-1): nhận thẳng cảnh ấy làm nền, rồi
    // reduce các op còn lại lên trên — nhờ vậy cảnh store chứa node/nét của chủ nhà và op agent sau
    // đó cập nhật đúng node ấy thay vì bị chối oan.
    const adopted = actor === 'user' ? readCanvasScene(data.scene) : null
    let scene = adopted ?? get().scenes[designId] ?? createEmptyScene()
    let rejected = get().rejectedOps
    const accepted: CanvasAction[] = []
    for (const raw of ops) {
      const action = parseCanvasOp(raw)
      if (!action) {
        rejected += 1
        continue
      }
      const next = applyCanvasAction(scene, action)
      // Reducer trả CHÍNH object cũ khi op không hợp lệ (id trùng/node lạ) ⇒ op đó bị bỏ.
      if (next === scene) rejected += 1
      else {
        scene = next
        accepted.push(action)
      }
    }
    const version = asNumber(data.sceneVersion) ?? asNumber(data.seq) ?? get().sceneVersion
    set({
      scenes: { ...get().scenes, [designId]: scene },
      sceneSeq: { ...get().sceneSeq, [designId]: Math.max(get().sceneSeq[designId] ?? 0, version) },
      sceneActor: actor ? { ...get().sceneActor, [designId]: actor } : get().sceneActor,
      lastOps: { ...get().lastOps, [designId]: { actor, ops: accepted, seq: event.seq } },
      sceneVersion: Math.max(get().sceneVersion, version),
      rejectedOps: rejected,
    })
  },

  clearSessionChange: () => set({
    runs: [],
    prompts: [],
    scenes: {},
    sceneSeq: {},
    sceneActor: {},
    lastOps: {},
    sceneVersion: 0,
    brief: {},
    reports: {},
    notices: [],
    pendingTurn: '',
    activeRunId: '',
    exitChoice: null,
    rejectedOps: 0,
    error: null,
    lastEventSeq: 0,
  }),

  sync: (sessionId, config, events) => {
    const switched = sessionId !== get().sessionId
    if (switched) get().clearSessionChange()
    const mode = readDesignMode(config)
    const mark = switched ? 0 : get().lastEventSeq
    const fresh = events.filter((event) => isDesignEvent(event) && event.seq > mark)
    set({
      sessionId,
      mode,
      activeRunId: mode.activeRunId || (switched ? '' : get().activeRunId),
      prompts: switched ? [] : get().prompts,
      // Chế độ tắt theo config ⇒ thẻ thoát đang hiện cũng phải biến mất.
      exitChoice: mode.on ? get().exitChoice : null,
      lastEventSeq: events.reduce(
        (max, event) => (isDesignEvent(event) ? Math.max(max, event.seq) : max),
        switched ? 0 : get().lastEventSeq,
      ),
    })
    for (const event of fresh) get().applyEvent(event)
    if (switched || fresh.length > 0 || mode.on) void get().refresh()
  },

  refresh: async () => {
    const sessionId = get().sessionId
    if (!sessionId) return
    set({ loading: true })
    try {
      const runs = readRuns(await fetchDesignRuns(sessionId))
      const exitPrompt = openExitPrompt(runs)
      // Chỉ giữ/dựng lại thẻ thoát khi chế độ còn BẬT: sau khi chủ nhà đã chọn lối thoát, `refresh()`
      // (và `sync()` gọi nó) có thể còn thấy lời hỏi mở trong payload run nếu server chưa kịp đóng —
      // khi đó thẻ KHÔNG được vẽ lại, và nó cũng tự biến mất vì `mode.on` đã là false.
      const modeOn = get().mode.on
      set({
        runs,
        error: null,
        loading: false,
        prompts: mergePrompts(get().prompts, runs.flatMap((run) => run.prompts)),
        exitChoice: !modeOn
          ? null
          : exitPrompt
            ? { code: 'DESIGN_EXIT_CHOICE_REQUIRED', prompt: exitPrompt, message: exitPrompt.note }
            : get().exitChoice?.prompt.status === 'open' ? get().exitChoice : null,
      })
      const foreground = activeRun(runs, get().mode.activeRunId || get().activeRunId)
      if (foreground) void get().refreshDetail(foreground.designId)
    } catch (error) {
      set({ error: readError(error), loading: false })
    }
  },

  refreshDetail: async (designId) => {
    if (!designId) return
    try {
      const envelope = asRecord(await fetchDesignRun(designId))
      const job = asRecord(envelope.job)
      const run = readRun({
        ...job,
        prompts: envelope.prompts ?? job.prompts,
        touchList: envelope.touchList ?? job.touchList,
        batch: job.batch ?? envelope.batch,
        review: job.review ?? envelope.review,
      })
      if (!run) return
      // Cảnh từ payload CHI TIẾT: nguồn duy nhất dựng lại được canvas khi cửa sổ sự kiện không còn lô
      // op đầu (tải lại trang). Chỉ nhận khi nó MỚI HƠN cảnh đang giữ — cảnh dựng từ sự kiện là
      // nguồn sống, không được để một vòng fetch cũ ghi đè ngược.
      const held = get().sceneSeq[designId] ?? 0
      const adopt = run.canvasScene !== null && run.canvasScene.nodes.length + run.canvasScene.connectors.length > 0
        && run.canvasSeq > held
      // Vòng kiểm thử bắt được: nhận cảnh mà QUÊN người vẽ thì (a) chip "do agent vẽ" không bao giờ
      // hiện (`agentHasDrawn` đọc `lastOps`), và (b) sự kiện `design_canvas` cùng số thứ tự tới sau bị
      // guard chống phát lại bỏ NGUYÊN, nên lô op ấy không bao giờ vào store — canvas không được vẽ
      // dần. Nên nhận cảnh thì ghi luôn CẢ HAI: người vẽ (`canvasActor` của payload) và lô op suy ra
      // từ chênh lệch cảnh cũ → cảnh vừa nhận (đúng đường mà hook phát lại dùng khi cảnh không kèm op).
      const adoptedOps = adopt
        ? diffSceneOps(get().scenes[designId] ?? createEmptyScene(), run.canvasScene as CanvasScene)
        : []
      set({
        runs: get().runs.some((item) => item.designId === designId)
          ? get().runs.map((item) => (item.designId === designId ? run : item))
          : [...get().runs, run],
        brief: asRecord(envelope.brief),
        error: null,
        ...(adopt ? {
          scenes: { ...get().scenes, [designId]: run.canvasScene as CanvasScene },
          sceneSeq: { ...get().sceneSeq, [designId]: run.canvasSeq },
          sceneActor: { ...get().sceneActor, [designId]: run.canvasActor },
          lastOps: { ...get().lastOps,
                     [designId]: { actor: run.canvasActor, ops: adoptedOps, seq: run.canvasSeq } },
        } : {}),
      })
    } catch (error) {
      set({ error: readError(error) })
    }
  },

  setMode: async (on, by) => {
    const sessionId = get().sessionId
    if (!sessionId) return 'error'
    // Đang có lời hỏi thoát chưa chọn thì bấm nút lần nữa KHÔNG được gửi thêm một PUT tắt chế độ:
    // chốt giữ ở đây (không phải trên thân request — server chỉ đọc `by`/`activeRun`) nên không có
    // lời hỏi `exit-choice` thứ hai nào được sinh ra.
    if (!on && get().exitChoice) return 'exit-choice'
    try {
      const outcome = await setDesignMode(sessionId, { on, by })
      if (outcome.kind === 'exit-choice') {
        set({ exitChoice: outcome.choice })
        return 'exit-choice'
      }
      set({ exitChoice: null, mode: readDesignMode({ designMode: outcome.result.mode }) })
      // Thoát chế độ thành công ⇒ xả tin nhắn main đang chờ (ra khỏi phạm vi / dùng cho plan).
      if (!on) void deliverPendingTurn()
      void get().refresh()
      return 'ok'
    } catch (error) {
      set({ error: readError(error) })
      return 'error'
    }
  },

  resolveExit: async (choice) => {
    const sessionId = get().sessionId
    const previous = get().exitChoice
    // Chốt chống nộp trùng: lối thoát chỉ có nghĩa khi ĐANG có lời hỏi chờ. Lần chọn thứ hai — kể cả
    // double-click trong cùng một nhịp, trước khi React kịp gỡ thẻ — thấy `exitChoice` đã bị xoá ở
    // lần đầu nên trả về ngay, KHÔNG gửi thêm `PUT …/design-mode` và không nộp thêm lượt main.
    if (!previous) return
    const active = previous.prompt.designId || get().mode.activeRunId
    set({ exitChoice: null })
    if (!sessionId) {
      set({ exitChoice: previous })
      return
    }
    try {
      const outcome = await setDesignMode(sessionId, {
        on: false, by: 'toggle', exitChoice: choice, activeRun: choice,
      })
      if (outcome.kind === 'ok') {
        set({ mode: readDesignMode({ designMode: outcome.result.mode }) })
        // Chọn xong lối thoát ⇒ chế độ đã tắt, tin nhắn main chờ từ trước được nộp ngay.
        void deliverPendingTurn()
      }
      if (active) void get().refreshDetail(active)
      void get().refresh()
    } catch (error) {
      set({ exitChoice: previous, error: readError(error) })
    }
  },

  clearExitChoice: () => set({ exitChoice: null }),

  approveTouchList: async (designId, revision, answers) => {
    try {
      await approveTouchList(designId, { revision, ...(answers ? { answers: answers.answers } : {}) })
      void get().refreshDetail(designId)
      void get().refresh()
      return true
    } catch (error) {
      set({ error: readError(error) })
      return false
    }
  },

  updateRun: async (designId, body) => {
    try {
      await patchDesignRun(designId, body)
      void get().refreshDetail(designId)
      return true
    } catch (error) {
      set({ error: readError(error) })
      return false
    }
  },

  answerPrompt: async (promptId, body) => {
    try {
      await answerDesignPrompt(promptId, body)
      const active = get().mode.activeRunId || get().activeRunId
      if (active) void get().refreshDetail(active)
      void get().refresh()
      return true
    } catch (error) {
      set({ error: readError(error) })
      return false
    }
  },

  queueTurn: (text) => set({ pendingTurn: text }),
}))

/**
 * Nộp tin nhắn main đang chờ (nếu có) và xoá hàng đợi TRƯỚC khi gửi — một tin nhắn chỉ được nộp một
 * lần. Chỉ gọi sau khi chế độ đã tắt THÀNH CÔNG; còn lời hỏi thoát chưa chọn thì tin nhắn ở lại.
 */
async function deliverPendingTurn(): Promise<void> {
  const { pendingTurn, sessionId } = useDesignStore.getState()
  if (!pendingTurn || !sessionId) return
  useDesignStore.setState({ pendingTurn: '' })
  await useHarnessChatStore.getState().send(sessionId, pendingTurn, null)
}

/** Gộp lời hỏi từ nhiều nguồn (giữ cái MỚI nhất theo `promptId`). */
function mergePrompts(current: readonly DesignPrompt[], incoming: readonly DesignPrompt[]): DesignPrompt[] {
  const map = new Map<string, DesignPrompt>()
  for (const prompt of [...current, ...incoming]) map.set(prompt.promptId, prompt)
  return [...map.values()]
}

/** Run đang mở đọc từ store. */
export function selectActiveRun(state: DesignState): DesignRun | null {
  return activeRun(state.runs, state.mode.activeRunId || state.activeRunId)
}

/** Cảnh canvas của một run (`createEmptyScene` khi chưa có op nào). */
export function selectScene(designId: string) {
  return (state: DesignState): CanvasScene => state.scenes[designId] ?? createEmptyScene()
}
