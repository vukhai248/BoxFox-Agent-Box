/**
 * Lời gọi HTTP của chế độ `/design` (P1 — vỏ chế độ).
 *
 * Bọc mỏng `agentApi` để mọi nơi gọi cùng một chữ ký, và để route 409
 * `DESIGN_EXIT_CHOICE_REQUIRED` (kèm lời hỏi `exit-choice`) trả về như DỮ LIỆU chứ không ném —
 * giao diện cần chính lời hỏi đó để dựng thẻ neo vào nút Design.
 */
import { ApiError, agentApi } from './agentApi'
import type { CanvasOutboundMessage } from './canvas'
import { readPrompt, type DesignPrompt } from './designMode'

export interface DesignPromptAnswerItem {
  questionId: string
  optionId?: string
  text?: string
}

export interface DesignPromptAnswerBody {
  answers: DesignPromptAnswerItem[]
  /** `true` ở câu trả lời cuối của phỏng vấn ⇒ run rời pha `interviewing`. */
  start?: boolean
  /** Khoá lạc quan của lời hỏi đang thấy (như mọi nhánh ghi khác). */
  revision?: number
}

export interface DesignExitChoice {
  code: string
  prompt: DesignPrompt
  message: string
}

/** `GET /api/agent/design/runs?sessionId=` */
export function fetchDesignRuns(sessionId: string): Promise<{ runs: unknown[] }> {
  return agentApi(`/design/runs?sessionId=${encodeURIComponent(sessionId)}`)
}

/** `GET /api/agent/design/runs/{id}` — chi tiết một run cho tab Design. */
export function fetchDesignRun(designId: string): Promise<Record<string, unknown>> {
  return agentApi(`/design/runs/${encodeURIComponent(designId)}`)
}

/**
 * `PATCH /api/agent/design/runs/{id}` — `pause | resume | cancel | scope | touch-list`.
 * Mọi nhánh ghi đều gửi kèm `revision` đang thấy (khoá lạc quan của hàng `design_jobs` hoặc của
 * chính `touchList.revision` tuỳ nhánh).
 */
export function patchDesignRun(
  designId: string,
  body: { action: string; revision?: number } & Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return agentApi(`/design/runs/${encodeURIComponent(designId)}`, body, 'PATCH')
}

/** `POST /api/agent/design/runs/{id}/touch-list/approve` — duyệt cả danh sách chạm. */
export function approveTouchList(
  designId: string,
  body: { revision: number } & Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return agentApi(`/design/runs/${encodeURIComponent(designId)}/touch-list/approve`, body)
}

/** `POST /api/agent/design/prompts/{id}/answer` — mọi câu trả lời trong MỘT lần gọi. */
export function answerDesignPrompt(
  promptId: string,
  body: DesignPromptAnswerBody,
): Promise<Record<string, unknown>> {
  return agentApi(`/design/prompts/${encodeURIComponent(promptId)}/answer`, body)
}

export interface DesignModeResult {
  on: boolean
  mode: Record<string, unknown>
  activeRunId?: string
}

export interface SetDesignModeBody {
  on: boolean
  by?: 'toggle' | 'command'
  /** `'pause'` hoặc `'background'` — bắt buộc khi tắt mode lúc run còn hoạt động. */
  exitChoice?: 'pause' | 'background'
  activeRun?: 'pause' | 'background'
}

export type SetDesignModeOutcome =
  | { kind: 'ok'; result: DesignModeResult }
  | { kind: 'exit-choice'; choice: DesignExitChoice }

/**
 * `PUT /api/agent/sessions/{sid}/design-mode`.
 *
 * Tắt mode khi run còn hoạt động mà thiếu lựa chọn ⇒ server trả 409
 * `DESIGN_EXIT_CHOICE_REQUIRED` kèm `{prompt}`; ta trả về `exit-choice` thay vì ném, vì đây là một
 * bước của luồng, không phải lỗi.
 */
export async function setDesignMode(
  sessionId: string,
  body: SetDesignModeBody,
): Promise<SetDesignModeOutcome> {
  try {
    const result = await agentApi<DesignModeResult>(
      `/sessions/${encodeURIComponent(sessionId)}/design-mode`,
      body,
      'PUT',
    )
    return { kind: 'ok', result }
  } catch (error) {
    if (error instanceof ApiError && error.status === 409) {
      const prompt = readPrompt((error.body as Record<string, unknown> | undefined)?.prompt)
      if (prompt) {
        return {
          kind: 'exit-choice',
          choice: { code: error.code ?? 'DESIGN_EXIT_CHOICE_REQUIRED', prompt, message: error.message },
        }
      }
    }
    throw error
  }
}

/**
 * `POST /api/agent/sessions/{sid}/canvas` — thân là một thông điệp `boxfox.canvas.v1`:
 * `buildCanvasMessage(scene)` (ảnh chụp cảnh) hoặc `buildCanvasDirective(...)` (chỉ thị cho node).
 */
export function postCanvas(
  sessionId: string,
  body: CanvasOutboundMessage | Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return agentApi(`/sessions/${encodeURIComponent(sessionId)}/canvas`, body)
}
