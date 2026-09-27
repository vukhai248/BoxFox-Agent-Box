/**
 * Bài kiểm cho tầng chuẩn hoá thuần của chế độ `/research` (`src/lib/researchMode.ts`).
 *
 * Điều quan trọng nhất: trường thiếu ⇒ giá trị rỗng, KHÔNG ném. Backend P1/P2/P3 chạy song song nên
 * giao diện phải chịu được payload cũ (chưa có `accessLevel`, `window`, `coverage`, …).
 */
import { describe, expect, it } from 'vitest'
import {
  activeJob,
  activeStepIndex,
  assumedItems,
  blockingOpenQuestions,
  confirmedItems,
  isResearchEvent,
  jobIsRunningInBackground,
  openPrompts,
  preferredPrompt,
  readJob,
  readJobs,
  readPrompt,
  readResearchMode,
  readScope,
  researchActivity,
  runLabel,
  stepForPhase,
  RESEARCH_MODE_OFF,
} from './researchMode'

describe('readResearchMode', () => {
  it('thiếu cấu hình ⇒ chế độ tắt, không ném', () => {
    expect(readResearchMode(undefined)).toEqual(RESEARCH_MODE_OFF)
    expect(readResearchMode({})).toEqual(RESEARCH_MODE_OFF)
    expect(readResearchMode({ researchMode: null })).toEqual(RESEARCH_MODE_OFF)
  })

  it('đọc đúng cấu hình server gửi', () => {
    expect(readResearchMode({ researchMode: { on: true, since: 's', enteredBy: 'command', activeRunId: 'R1', revision: 4 } }))
      .toEqual({ on: true, since: 's', enteredBy: 'command', activeRunId: 'R1', revision: 4, handoffDeliveredVersion: {} })
  })

  it('đọc `handoffDeliveredVersion`: chỉ nhận chữ/số, ép về chuỗi, bỏ giá trị lạ', () => {
    const mode = readResearchMode({
      researchMode: { on: true, handoffDeliveredVersion: { R1: '3', R2: 4, R3: null, R4: { v: 1 }, R5: true } },
    })
    expect(mode.handoffDeliveredVersion).toEqual({ R1: '3', R2: '4' })
    // Không phải bản đồ ⇒ rỗng, KHÔNG ném.
    expect(readResearchMode({ researchMode: { on: true, handoffDeliveredVersion: 'rác' } }).handoffDeliveredVersion).toEqual({})
    expect(readResearchMode({ researchMode: { on: true } }).handoffDeliveredVersion).toEqual({})
  })
})

describe('readPrompt', () => {
  it('lời hỏi không có id ⇒ null', () => {
    expect(readPrompt({ kind: 'interview' })).toBeNull()
    expect(readPrompt(undefined)).toBeNull()
  })

  it('giữ đủ năm kiểu lời hỏi', () => {
    for (const kind of ['interview', 'scope-change', 'exit-choice', 'out-of-scope', 'budget']) {
      const prompt = readPrompt({ promptId: 'rp-1', kind, questions: [{ id: 'q1', text: 't' }] })
      expect(prompt?.kind).toBe(kind)
    }
  })

  it('kind lạ rơi về interview thay vì ném', () => {
    expect(readPrompt({ promptId: 'rp-1', kind: 'weird' })?.kind).toBe('interview')
  })

  it('câu hỏi thiếu trường vẫn đọc được, `required` mặc định true', () => {
    const prompt = readPrompt({ promptId: 'rp-1', questions: [{ id: 'q1', text: 't', options: 'không phải mảng' }] })
    expect(prompt?.questions[0]).toMatchObject({ id: 'q1', required: true, blocking: true, options: [], allowFreeText: true, answer: null })
  })

  it('openPrompts/preferredPrompt chỉ trả lời hỏi còn mở', () => {
    const prompts = [
      readPrompt({ promptId: 'a', kind: 'interview', status: 'answered' })!,
      readPrompt({ promptId: 'b', kind: 'exit-choice', status: 'open' })!,
      readPrompt({ promptId: 'c', kind: 'interview', status: 'open' })!,
    ]
    expect(openPrompts(prompts).map((prompt) => prompt.promptId)).toEqual(['b', 'c'])
    expect(preferredPrompt(prompts, 'interview')?.promptId).toBe('c')
    expect(preferredPrompt(prompts, 'budget')).toBeNull()
  })
})

describe('readScope', () => {
  it('thẻ rỗng/hỏng ⇒ null, không ném', () => {
    expect(readScope(undefined)).toBeNull()
    expect(readScope(null)).toBeNull()
    expect(readScope({})).toBeNull()
  })

  it('tách đúng hai danh sách xác nhận/giả định', () => {
    const scope = readScope({
      revision: 1,
      goal: { text: 'mục tiêu', status: 'assumed' },
      purpose: { text: 'việc dùng', status: 'confirmed' },
      exclusions: [{ text: 'loại trừ', status: 'confirmed' }, { text: 'giả định nữa', status: 'assumed' }],
    })
    expect(confirmedItems(scope).map((item) => item.text)).toEqual(['việc dùng', 'loại trừ'])
    expect(assumedItems(scope).map((item) => item.text)).toEqual(['mục tiêu', 'giả định nữa'])
  })

  it('câu chặn đã trả lời thì không còn chặn', () => {
    const scope = readScope({
      revision: 1,
      openQuestions: [
        { id: 'q1', text: 'còn mở', blocking: true, options: [], affects: [], answer: null, promptId: 'rp-1' },
        { id: 'q2', text: 'đã trả lời', blocking: false, answer: { text: 'chọn A', status: 'confirmed' } },
      ],
    })
    expect(blockingOpenQuestions(scope).map((item) => item.id)).toEqual(['q1'])
  })

  it('đọc cửa sổ thời gian và ghi chú velocity sai', () => {
    const scope = readScope({ revision: 0, timePolicy: { velocity: 'fast', note: 'velocity lạ' }, window: { days: 630 } })
    expect(scope?.window?.days).toBe(630)
    expect(scope?.timePolicy?.note).toBe('velocity lạ')
    expect(readScope({ revision: 0 })?.window).toBeNull()
  })
})

describe('bước của run', () => {
  it('ánh xạ pha → bước, pha lạ rơi về bước đầu', () => {
    expect(stepForPhase('clarifying')).toBe('clarify')
    expect(stepForPhase('searching')).toBe('search')
    expect(stepForPhase('synthesizing')).toBe('synthesize')
    expect(stepForPhase('verifying')).toBe('critique')
    // `revising`: một phán quyết `revise` mở bước Tổng hợp, không được rơi về bước 0 (`clarify`)
    // như trước bản vá này (đợt soát `3dc745f`, finding 1). `deep-reading` là tên pha của §5.2.
    expect(stepForPhase('revising')).toBe('synthesize')
    expect(stepForPhase('deep-reading')).toBe('read')
  })

  it('run xong thì đứng ở bước cuối', () => {
    expect(activeStepIndex('reading', 'completed')).toBe(6)
    expect(activeStepIndex('reading', 'researching')).toBe(3)
  })

  it('nhãn run suy từ research_id', () => {
    expect(runLabel('job-20260925-abcdef123')).toBe('R-EF123')
    expect(runLabel('')).toBe('')
  })
})

describe('readJob', () => {
  it('payload tối thiểu vẫn dựng được hàng, không ném', () => {
    const job = readJob({ research_id: 'R1' })
    expect(job.researchId).toBe('R1')
    expect(job.evidence).toEqual([])
    expect(job.dossier).toBeNull()
    expect(job.coverage).toEqual({ counts: {}, unexplored: [], facets: [] })
  })

  it('đọc hàng bằng chứng với trường P2 còn thiếu', () => {
    const job = readJob({ research_id: 'R1', evidence: [{ rowId: 'r1', claim: 'c', url: 'u' }] })
    expect(job.evidence[0]).toMatchObject({ rowId: 'r1', accessLevel: '', relation: '', confidence: '' })
  })

  it('readJobs bỏ qua payload không phải mảng', () => {
    expect(readJobs({ jobs: 'không phải mảng' })).toEqual([])
    expect(readJobs({ jobs: [{ research_id: 'R1' }] })).toHaveLength(1)
  })

  it('run nền chỉ tính khi còn hoạt động', () => {
    const background = readJob({ research_id: 'R1', status: 'researching', state: { background: true } })
    expect(jobIsRunningInBackground(background)).toBe(true)
    const finished = readJob({ research_id: 'R1', status: 'completed', state: { background: true } })
    expect(jobIsRunningInBackground(finished)).toBe(false)
  })

  it('activeJob ưu tiên run theo activeRunId, rồi run còn hoạt động', () => {
    const jobs = readJobs({ jobs: [{ research_id: 'A', status: 'completed' }, { research_id: 'B', status: 'researching' }] })
    expect(activeJob(jobs, 'A')?.researchId).toBe('A')
    expect(activeJob(jobs, '')?.researchId).toBe('B')
    expect(activeJob([], 'A')).toBeNull()
  })
})

describe('dòng công cụ gom', () => {
  it('chỉ đếm tool_start nên một lời gọi không bị tính hai lần', () => {
    const activity = researchActivity([
      { type: 'tool_start', data: { name: 'web_search' } },
      { type: 'tool_end', data: { name: 'web_search' } },
      { type: 'tool_start', data: { name: 'paper_citations' } },
      { type: 'tool_start', data: { name: 'web_fetch' } },
      { type: 'tool_start', data: { name: 'file_read' } },
    ])
    expect(activity).toEqual({ searches: 2, reads: 1 })
  })

  it('chỉ sự kiện `research_*` mới buộc tải lại', () => {
    expect(isResearchEvent({ type: 'research_scope' })).toBe(true)
    expect(isResearchEvent({ type: 'source_add' })).toBe(false)
    expect(isResearchEvent({ type: 'tool_start' })).toBe(false)
  })
})
