/**
 * Bài kiểm cho lớp gọi HTTP của chế độ `/research`.
 *
 * Trọng tâm: 409 `RESEARCH_EXIT_CHOICE_REQUIRED` phải trả về như DỮ LIỆU (`kind: 'exit-choice'`) kèm
 * lời hỏi đã chuẩn hoá — giao diện cần chính nó để dựng thẻ neo vào nút Research. Mọi lỗi khác vẫn ném.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from './agentApi'
import { setResearchMode } from './researchApi'

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status < 400,
    status,
    json: async () => body,
  } as unknown as Response
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('setResearchMode', () => {
  it('bật thành công ⇒ trả mode đã chuẩn hoá', async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ mode: { on: true, activeRunId: 'R1', revision: 2 } }))
    vi.stubGlobal('fetch', fetchMock)
    const outcome = await setResearchMode('s1', { on: true, by: 'toggle' })
    expect(outcome.kind).toBe('ok')
    expect(fetchMock).toHaveBeenCalledWith('/api/agent/sessions/s1/research-mode', expect.objectContaining({ method: 'PUT' }))
  })

  it('tắt khi run còn chạy ⇒ 409 đọc thành exit-choice kèm prompt', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({
      error: 'Run đang chạy',
      code: 'RESEARCH_EXIT_CHOICE_REQUIRED',
      prompt: {
        promptId: 'rp-exit', researchId: 'R1', kind: 'exit-choice', revision: 3, status: 'open',
        questions: [{ id: 'exit', text: 'Bạn muốn run này thế nào?', allowFreeText: false, options: [{ id: 'pause', label: 'Tạm dừng' }, { id: 'background', label: 'Chạy nền' }] }],
      },
    }, 409)))
    const outcome = await setResearchMode('s1', { on: false, by: 'toggle' })
    expect(outcome.kind).toBe('exit-choice')
    if (outcome.kind !== 'exit-choice') throw new Error('unreachable')
    expect(outcome.choice.prompt.kind).toBe('exit-choice')
    expect(outcome.choice.prompt.questions[0].options.map((option) => option.id)).toEqual(['pause', 'background'])
    expect(outcome.choice.prompt.questions[0].allowFreeText).toBe(false)
  })

  it('409 nhưng thiếu prompt ⇒ vẫn ném, không nuốt lỗi', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: 'lạ', code: 'RESEARCH_OTHER' }, 409)))
    await expect(setResearchMode('s1', { on: false })).rejects.toBeInstanceOf(ApiError)
  })

  it('công tắc tắt ở server (409 RESEARCH_MODE_UNAVAILABLE) ⇒ ném', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse({ error: 'switched off', code: 'RESEARCH_MODE_UNAVAILABLE' }, 409)))
    await expect(setResearchMode('s1', { on: true })).rejects.toBeInstanceOf(ApiError)
  })
})
