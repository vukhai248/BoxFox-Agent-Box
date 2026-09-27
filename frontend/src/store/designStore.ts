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
  parseCanvasMessage,
  type CanvasAction,
  type CanvasScene,
} from '../lib/canvas'
import { asBool, asNumber, asRecord, asString } from '../lib/researchMode'
import {
  activeRun,
  DESIGN_MODE_OFF,
  isDesignEvent,
  openExitPrompt,
  readBatch,
  readDesignMode,
  readPrompt,
  readReview,
  readRun,
  readRuns,
  stepForPhase,
  type DesignMode,
  type DesignPrompt,
  type DesignRun,
  type Json,
} from '../lib/designMode'
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

interface DesignState {
  sessionId: string
  mode: DesignMode
  runs: DesignRun[]
  /** Run đang mở (mode trỏ tới) — client giữ để thẻ bàn giao biết run nào đang xem. */
  activeRunId: string
  /** `designId -> CanvasScene` do sự kiện `design_canvas` dựng nên. */
  scenes: Record<string, CanvasScene>
  /** `designId -> actor` của sự kiện `design_canvas` gần nhất (`'agent'`/`'user'`/…). */
  sceneActor: Record<string, string>
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
  /** Lời hỏi 409 khi tắt mode lúc run còn chạy: có thì phải neo thẻ vào nút Design. */
  exitChoice: DesignExitChoice | null
  loading: boolean
  error: string | null
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
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
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
    phaseHistory: current?.phaseHistory ?? [],
    // Lô ghi/soát độc lập: nhận từ sự kiện nếu backend gửi kèm, ngược lại giữ cái đang có
    // (tuyến chi tiết `refreshDetail` là nguồn chính).
    batch: readBatch(data.batch) ?? current?.batch ?? null,
    review: readReview(data.review) ?? current?.review ?? null,
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
  sceneActor: {},
  sceneVersion: 0,
  prompts: [],
  rejectedOps: 0,
  brief: {},
  reports: {},
  exitChoice: null,
  loading: false,
  error: null,
  lastEventSeq: 0,

  applyEvent: (event) => {
    const data = asRecord(event.data)
    if (event.type === 'design_mode') {
      set({ mode: { ...get().mode, on: asBool(data.on), enteredBy: asString(data.by) } })
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
      if (prompt.kind === 'exit-choice' && prompt.status === 'open') {
        set({ exitChoice: { code: 'DESIGN_EXIT_CHOICE_REQUIRED', prompt, message: prompt.note } })
      }
    }
    // `design_notice` (P6) chưa có hình dạng chốt cho giao diện — bỏ qua thay vì đoán.
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
    let scene = get().scenes[designId] ?? createEmptyScene()
    let rejected = get().rejectedOps
    for (const raw of ops) {
      const action = parseCanvasOp(raw)
      if (!action) {
        rejected += 1
        continue
      }
      const next = applyCanvasAction(scene, action)
      // Reducer trả CHÍNH object cũ khi op không hợp lệ (id trùng/node lạ) ⇒ op đó bị bỏ.
      if (next === scene) rejected += 1
      else scene = next
    }
    const actor = asString(data.actor) || get().sceneActor[designId] || ''
    const version = asNumber(data.sceneVersion) ?? asNumber(data.seq) ?? get().sceneVersion
    set({
      scenes: { ...get().scenes, [designId]: scene },
      sceneActor: actor ? { ...get().sceneActor, [designId]: actor } : get().sceneActor,
      sceneVersion: Math.max(get().sceneVersion, version),
      rejectedOps: rejected,
    })
  },

  clearSessionChange: () => set({
    runs: [],
    prompts: [],
    scenes: {},
    sceneActor: {},
    sceneVersion: 0,
    brief: {},
    reports: {},
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
      set({
        runs,
        error: null,
        loading: false,
        prompts: mergePrompts(get().prompts, runs.flatMap((run) => run.prompts)),
        exitChoice: exitPrompt
          ? { code: 'DESIGN_EXIT_CHOICE_REQUIRED', prompt: exitPrompt, message: exitPrompt.note }
          : get().exitChoice?.prompt.status === 'open' ? get().exitChoice : null,
      })
      const foreground = activeRun(runs, get().mode.activeRunId || get().activeRunId)
      if (foreground) void get().refreshDetail(foreground.designId)
    } catch (error) {
      set({ error: message(error), loading: false })
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
        // Lô ghi: backend đang gọi nó là `diff` (`{files, patchPath, at}`, §6.5) — nhận cả hai tên.
        batch: job.batch ?? envelope.batch ?? job.diff ?? envelope.diff,
        review: job.review ?? envelope.review,
      })
      if (!run) return
      set({
        runs: get().runs.some((item) => item.designId === designId)
          ? get().runs.map((item) => (item.designId === designId ? run : item))
          : [...get().runs, run],
        brief: asRecord(envelope.brief),
        error: null,
      })
    } catch (error) {
      set({ error: message(error) })
    }
  },

  setMode: async (on, by) => {
    const sessionId = get().sessionId
    if (!sessionId) return 'error'
    // Đang có lời hỏi thoát chưa chọn thì bấm nút lần nữa KHÔNG được gửi thêm một PUT không `prompt`
    // — mỗi lần như vậy server lại tạo thêm một lời hỏi `exit-choice` mở mãi mãi.
    if (!on && get().exitChoice) return 'exit-choice'
    try {
      const outcome = await setDesignMode(sessionId, { on, by })
      if (outcome.kind === 'exit-choice') {
        set({ exitChoice: outcome.choice })
        return 'exit-choice'
      }
      set({ exitChoice: null, mode: readDesignMode({ designMode: outcome.result.mode }) })
      void get().refresh()
      return 'ok'
    } catch (error) {
      set({ error: message(error) })
      return 'error'
    }
  },

  resolveExit: async (choice) => {
    const sessionId = get().sessionId
    const previous = get().exitChoice
    const active = previous?.prompt.designId || get().mode.activeRunId
    set({ exitChoice: null })
    if (!sessionId) {
      set({ exitChoice: previous })
      return
    }
    try {
      const outcome = await setDesignMode(sessionId, {
        on: false, by: 'toggle', exitChoice: choice, activeRun: choice,
        ...(previous ? { prompt: previous.prompt } : {}),
      })
      if (outcome.kind === 'ok') set({ mode: readDesignMode({ designMode: outcome.result.mode }) })
      if (active) void get().refreshDetail(active)
      void get().refresh()
    } catch (error) {
      set({ exitChoice: previous, error: message(error) })
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
      set({ error: message(error) })
      return false
    }
  },

  updateRun: async (designId, body) => {
    try {
      await patchDesignRun(designId, body)
      void get().refreshDetail(designId)
      return true
    } catch (error) {
      set({ error: message(error) })
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
      set({ error: message(error) })
      return false
    }
  },
}))

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
