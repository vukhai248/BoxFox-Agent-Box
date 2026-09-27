/**
 * Lời gọi HTTP của chế độ `/research` (P4 — giao diện).
 *
 * Bọc mỏng `agentApi` để mọi nơi gọi cùng một chữ ký, và để route 409
 * `RESEARCH_EXIT_CHOICE_REQUIRED` (kèm lời hỏi `exit-choice`) trả về như DỮ LIỆU chứ không ném —
 * giao diện cần chính lời hỏi đó để dựng thẻ neo vào nút Research.
 */
import { ApiError, agentApi } from './agentApi'
import { readPrompt, type ResearchPrompt } from './researchMode'

export interface ResearchPromptAnswerItem {
  questionId: string
  optionId?: string
  text?: string
}

export interface ResearchPromptAnswerBody {
  revision?: number
  answers: ResearchPromptAnswerItem[]
  approveBudget?: boolean
  start?: boolean
}

export interface ResearchExitChoice {
  code: string
  prompt: ResearchPrompt
  message: string
}

/** `GET /api/agent/research/jobs?sessionId=` */
export function fetchResearchJobs(sessionId: string): Promise<{ jobs: unknown[] }> {
  return agentApi(`/research/jobs?sessionId=${encodeURIComponent(sessionId)}`)
}

/** `GET /api/agent/research/jobs/{id}` — chi tiết một run cho tab Research. */
export function fetchResearchJobDetail(researchId: string): Promise<Record<string, unknown>> {
  return agentApi(`/research/jobs/${encodeURIComponent(researchId)}`)
}

/**
 * `PATCH /api/agent/research/jobs/{id}` — pause/resume/cancel/prioritize/skip/budget, và (hợp đồng
 * §5.12) `scope` để sửa thẻ phạm vi kèm `revision` mong đợi.
 */
export function patchResearchJob(
  researchId: string,
  body: { action: string; revision?: number } & Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return agentApi(`/research/jobs/${encodeURIComponent(researchId)}`, body, 'PATCH')
}

export interface ResearchModeResult {
  on: boolean
  mode: Record<string, unknown>
  activeRunId?: string
  prompt?: unknown
  exitChoice?: string | null
}

export interface SetResearchModeBody {
  on: boolean
  by?: 'toggle' | 'command'
  /** `'pause'` hoặc `'background'` — bắt buộc khi tắt mode lúc run còn hoạt động. */
  exitChoice?: 'pause' | 'background'
  activeRun?: 'pause' | 'background'
  /**
   * F7: gửi lại lời hỏi `exit-choice` đã nhận để server DÙNG LẠI nó thay vì tạo thêm một lời hỏi
   * mới (server chỉ dựng lời hỏi khi `prompt.promptId` vắng).
   */
  prompt?: ResearchPrompt
}

export type SetResearchModeOutcome =
  | { kind: 'ok'; result: ResearchModeResult }
  | { kind: 'exit-choice'; choice: ResearchExitChoice }

/**
 * `PUT /api/agent/sessions/{sid}/research-mode`.
 *
 * Tắt mode khi run còn hoạt động mà thiếu lựa chọn ⇒ server trả 409
 * `RESEARCH_EXIT_CHOICE_REQUIRED` kèm `{prompt}`; ta trả về `exit-choice` thay vì ném, vì đây là
 * một bước của luồng, không phải lỗi.
 */
export async function setResearchMode(
  sessionId: string,
  body: SetResearchModeBody,
): Promise<SetResearchModeOutcome> {
  try {
    const result = await agentApi<ResearchModeResult>(
      `/sessions/${encodeURIComponent(sessionId)}/research-mode`,
      body,
      'PUT',
    )
    return { kind: 'ok', result }
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      const prompt = readPrompt((error.body as Record<string, unknown> | undefined)?.prompt)
      if (prompt) {
        return { kind: 'exit-choice', choice: { code: error.code ?? 'RESEARCH_EXIT_CHOICE_REQUIRED', prompt, message: error.message } }
      }
    }
    throw error
  }
}

/** `POST /api/agent/research/prompts/{id}/answer` — mọi câu trả lời trong MỘT lần gọi. */
export function answerResearchPrompt(
  promptId: string,
  body: ResearchPromptAnswerBody,
): Promise<Record<string, unknown>> {
  return agentApi(`/research/prompts/${encodeURIComponent(promptId)}/answer`, body)
}

/** `POST /api/agent/research/prompts/{id}/dismiss` — đóng lời hỏi mà không chọn (không đổi gì). */
export function dismissResearchPrompt(promptId: string): Promise<Record<string, unknown>> {
  return agentApi(`/research/prompts/${encodeURIComponent(promptId)}/dismiss`, {})
}
