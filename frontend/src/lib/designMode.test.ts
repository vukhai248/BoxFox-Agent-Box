/**
 * Bài kiểm cho tầng chuẩn hoá thuần của chế độ `/design` (`src/lib/designMode.ts`).
 *
 * Điều quan trọng nhất: trường thiếu ⇒ giá trị rỗng, KHÔNG ném. Các giai đoạn P2–P4 của backend chạy
 * song song nên giao diện P1 phải chịu được payload cũ (chưa có `touchList`, `report`, `sceneVersion`).
 */
import { describe, expect, it } from 'vitest'
import {
  activeRun,
  activeStepIndex,
  asVersionString,
  designErrorKey,
  isDesignEvent,
  openExitPrompt,
  readDesignMode,
  readNotice,
  readPrompt,
  readPromptKind,
  readRun,
  readRuns,
  readTouchItem,
  readTouchList,
  runIsCancellable,
  runIsClosed,
  runIsPausable,
  runIsRunningInBackground,
  runIsSuspendable,
  runLabel,
  stepForPhase,
  DESIGN_MODE_OFF,
  DESIGN_STEPS,
  DESIGN_TERMINAL_STATUSES,
  PHASE_STEP,
} from './designMode'

describe('readDesignMode', () => {
  it('thiếu cấu hình ⇒ chế độ tắt, không ném', () => {
    expect(readDesignMode(undefined)).toEqual(DESIGN_MODE_OFF)
    expect(readDesignMode({})).toEqual(DESIGN_MODE_OFF)
    expect(readDesignMode({ designMode: null })).toEqual(DESIGN_MODE_OFF)
  })

  it('đọc đúng cấu hình server gửi', () => {
    expect(
      readDesignMode({ designMode: { on: true, since: 's', enteredBy: 'command', activeRunId: 'd-1', revision: 3 } }),
    ).toEqual({ on: true, since: 's', enteredBy: 'command', activeRunId: 'd-1', revision: 3, handoffDeliveredVersion: {} })
  })

  it('trường lạ không làm sập vòng đọc', () => {
    expect(readDesignMode({ designMode: { on: 'yes', revision: 'x', extra: 1 } }).on).toBe(false)
  })
})

describe('bước của run', () => {
  it('ánh xạ đủ tám giai đoạn, và mọi bước nằm trong DESIGN_STEPS', () => {
    expect(Object.keys(PHASE_STEP).sort()).toEqual(
      ['briefing', 'done', 'drawing', 'interviewing', 'reviewing', 'scaffolding', 'touch-list', 'handoff'].sort(),
    )
    for (const step of Object.values(PHASE_STEP)) expect(DESIGN_STEPS).toContain(step)
    expect(DESIGN_STEPS).toHaveLength(7)
  })

  it('stepForPhase lạ ⇒ bước đầu, không ném', () => {
    expect(stepForPhase('interviewing')).toBe('clarify')
    expect(stepForPhase('scaffolding')).toBe('write')
    expect(stepForPhase('never-heard-of-it')).toBe('clarify')
    expect(stepForPhase(null)).toBe('clarify')
  })

  it('chỉ số bước hiện tại theo giai đoạn', () => {
    expect(activeStepIndex('interviewing', 'scoping')).toBe(0)
    expect(activeStepIndex('drawing', 'designing')).toBe(3)
    expect(activeStepIndex('reviewing', 'reviewing')).toBe(5)
    // run đã đóng thì đứng ở bước cuối, bất kể giai đoạn còn lại là gì.
    expect(activeStepIndex('scaffolding', 'completed')).toBe(6)
    expect(activeStepIndex('scaffolding', 'cancelled')).toBe(6)
  })

  it('runLabel rút gọn id thành nhãn ngắn, id lạ vẫn trả về gì đó', () => {
    expect(runLabel('d-chat-panel-9f3a1c')).toBe('D-F3A1C')
    expect(runLabel('')).toBe('')
  })
})

describe('danh sách chạm', () => {
  it('rỗng ⇒ null, không dựng dữ liệu', () => {
    expect(readTouchList(undefined)).toBeNull()
    expect(readTouchList({})).toBeNull()
  })

  it('đọc item thiếu trường bằng giá trị rỗng', () => {
    expect(readTouchItem({}, 0)).toEqual({
      id: 't1',
      kind: 'new',
      path: '',
      reason: '',
      risk: 'low',
      status: 'proposed',
      sha256: null,
    })
  })

  it('đọc danh sách đầy đủ', () => {
    const list = readTouchList({
      revision: 3,
      designId: 'd-1',
      branch: { name: 'design/chat-20260927-0900', base: 'abc', status: 'proposed' },
      items: [{ id: 't1', kind: 'insert', path: 'src/ui/ChatPanel.tsx', reason: 'thêm nút', risk: 'low', status: 'proposed', sha256: null }],
      forbidden: ['.env'],
      approvedAt: null,
    })
    expect(list?.revision).toBe(3)
    expect(list?.items).toHaveLength(1)
    expect(list?.items[0].path).toBe('src/ui/ChatPanel.tsx')
    expect(list?.approvedAt).toBeNull()
  })
})

describe('lời hỏi', () => {
  it('thiếu promptId ⇒ null', () => {
    expect(readPrompt(undefined)).toBeNull()
    expect(readPrompt({})).toBeNull()
  })

  it('đọc câu hỏi và lựa chọn', () => {
    const prompt = readPrompt({
      promptId: 'dp-1',
      designId: 'd-1',
      kind: 'interview',
      status: 'open',
      revision: 1,
      questions: [{ id: 'dq-screen', text: 'Màn hình nào?', why: 'vì…', options: [{ id: 'a', label: 'A' }], allowFreeText: true, required: true }],
    })
    expect(prompt?.questions[0].id).toBe('dq-screen')
    expect(prompt?.questions[0].options[0].label).toBe('A')
  })
})

describe('run', () => {
  it('thiếu designId ⇒ null', () => {
    expect(readRun(undefined)).toBeNull()
    expect(readRun({})).toBeNull()
  })

  it('readRuns nhận cả mảng trần lẫn `{runs}`', () => {
    const one = { designId: 'd-1', status: 'scoping', phase: 'interviewing' }
    expect(readRuns({ runs: [one] })).toHaveLength(1)
    expect(readRuns([one, { nope: 1 }])).toHaveLength(1)
    expect(readRuns(null)).toEqual([])
  })

  it('bước là dẫn xuất của giai đoạn, không đọc từ payload', () => {
    const run = readRun({ designId: 'd-1', status: 'designing', phase: 'drawing' })
    expect(run?.step).toBe('draw')
    // `step` backend gửi (nếu hợp lệ) là thứ được tin, chỉ khi thiếu mới suy từ giai đoạn.
    expect(readRun({ designId: 'd-1', status: 'designing', phase: 'drawing', step: 'handoff' })?.step).toBe('handoff')
    expect(readRun({ designId: 'd-1', status: 'designing', phase: 'drawing', step: 'bịa' })?.step).toBe('draw')
  })

  it('activeRun theo id, id lạ thì lùi về run chưa đóng mới nhất', () => {
    const runs = [readRun({ designId: 'd-1', status: 'scoping', phase: 'interviewing' })!]
    expect(activeRun(runs, 'd-1')?.designId).toBe('d-1')
    // Id ghim không (còn) thấy: lùi về run chưa đóng, KHÔNG trả null — nền tảng vẫn còn việc để hiện.
    expect(activeRun(runs, 'd-9')?.designId).toBe('d-1')
    expect(activeRun(runs, null)?.designId).toBe('d-1')
    // Danh sách rỗng ⇒ null.
    expect(activeRun([], 'd-1')).toBeNull()
    expect(activeRun([], null)).toBeNull()
  })

  it('trạng thái kết thúc là danh sách đóng', () => {
    expect(DESIGN_TERMINAL_STATUSES).toEqual(['completed', 'partial', 'cancelled'])
  })
})

describe('sự kiện và lời hỏi thoát', () => {
  it('chỉ nhận sự kiện `design_*`', () => {
    expect(isDesignEvent({ type: 'design_run', data: {} })).toBe(true)
    expect(isDesignEvent({ type: 'research_run', data: {} })).toBe(false)
  })

  it('mở thẻ thoát khi một run còn lời hỏi exit-choice chưa trả lời', () => {
    const prompt = { promptId: 'dp-9', designId: 'd-1', kind: 'exit-choice', status: 'open', questions: [] }
    const withPrompt = [readRun({ designId: 'd-1', status: 'designing', phase: 'drawing', prompts: [prompt] })!]
    expect(openExitPrompt(withPrompt)?.promptId).toBe('dp-9')
    const answered = [readRun({ designId: 'd-1', status: 'designing', phase: 'drawing', prompts: [{ ...prompt, status: 'answered' }] })!]
    expect(openExitPrompt(answered)).toBeNull()
    expect(openExitPrompt([])).toBeNull()
  })
})

describe('thông báo nền và trạng thái điều khiển được', () => {
  it('readNotice: thiếu designId ⇒ null; kind lạ rơi về `blocked`, không ném', () => {
    expect(readNotice({ kind: 'background-done' }, 5)).toBeNull()
    expect(readNotice({ designId: 'd-1', kind: 'background-done' }, 5)).toEqual({
      designId: 'd-1', kind: 'background-done', seq: 5,
    })
    expect(readNotice({ designId: 'd-1', kind: 'bịa' }, 6)?.kind).toBe('blocked')
  })

  it('runIsRunningInBackground: chỉ run nền CHƯA đóng', () => {
    const run = readRun({ designId: 'd-1', status: 'designing', phase: 'drawing', background: true })!
    expect(runIsRunningInBackground(run)).toBe(true)
    expect(runIsRunningInBackground({ ...run, status: 'completed' })).toBe(false)
    expect(runIsRunningInBackground({ ...run, background: false })).toBe(false)
  })

  it('runIsPausable/runIsSuspendable/runIsCancellable: đúng bốn trạng thái chạy + ba trạng thái tiếp tục', () => {
    const run = readRun({ designId: 'd-1', status: 'designing', phase: 'drawing' })!
    expect(runIsPausable(run)).toBe(true)
    expect(runIsPausable({ ...run, status: 'paused' })).toBe(false)
    expect(runIsSuspendable({ ...run, status: 'paused' })).toBe(true)
    expect(runIsSuspendable({ ...run, status: 'partial' })).toBe(true)
    expect(runIsSuspendable({ ...run, status: 'needs_user' })).toBe(true)
    expect(runIsSuspendable(run)).toBe(false)
    expect(runIsCancellable(run)).toBe(true)
    expect(runIsCancellable({ ...run, status: 'completed' })).toBe(false)
    expect(runIsCancellable({ ...run, status: 'cancelled' })).toBe(false)
  })

  it('runIsClosed: `partial` cũng là trạng thái ĐÓNG (một luật dùng chung với dòng thời gian)', () => {
    expect(runIsClosed('completed')).toBe(true)
    expect(runIsClosed('partial')).toBe(true)
    expect(runIsClosed('cancelled')).toBe(true)
    expect(runIsClosed('designing')).toBe(false)
    expect(activeStepIndex('scaffolding', 'partial')).toBe(DESIGN_STEPS.length - 1)
  })
})

describe('chuẩn hoá phiên bản và loại lời hỏi (P5)', () => {
  it('asVersionString nhận cả số lẫn chuỗi; rỗng/rác ⇒ chuỗi rỗng', () => {
    expect(asVersionString('v2')).toBe('v2')
    expect(asVersionString(2)).toBe('2')
    expect(asVersionString(0)).toBe('0')
    expect(asVersionString(null)).toBe('')
    expect(asVersionString({})).toBe('')
  })

  it('readPromptKind: giữ loại backend thật, loại lạ ⇒ `unknown` (không đoán bừa)', () => {
    expect(readPromptKind('touch-list')).toBe('touch-list')
    expect(readPromptKind('out-of-scope')).toBe('out-of-scope')
    expect(readPromptKind('bịa')).toBe('unknown')
    expect(readPromptKind(undefined)).toBe('unknown')
  })
})

describe('câu đọc được cho mã lỗi tầng worker (vi + en)', () => {
  it('mọi mã worker còn thiếu đều có khoá i18n trong bảng', () => {
    for (const code of [
      'DESIGN_PATH_INVALID',
      'DESIGN_WRITE_INVALID',
      'DESIGN_REVERT_INVALID',
      'DESIGN_REVERT_FAILED',
      'DESIGN_BASE_INVALID',
      'DESIGN_GIT_TIMEOUT',
    ] as const) {
      expect(designErrorKey(code)).toBe(`design.errors.${code}`)
    }
  })

  it('mã đã có từ trước KHÔNG đổi tên/khoá; mã lạ vẫn rơi về thông điệp thô (dự phòng giữ nguyên)', () => {
    expect(designErrorKey('DESIGN_WRITE_EXISTS')).toBe('design.errors.DESIGN_WRITE_EXISTS')
    expect(designErrorKey('DESIGN_ANCHOR_NOT_UNIQUE')).toBe('design.errors.DESIGN_ANCHOR_NOT_UNIQUE')
    expect(designErrorKey('DESIGN_BỊA')).toBeNull()
    expect(designErrorKey('')).toBeNull()
  })
})
