/**
 * Lỗi HTTP của harness, mang theo cả `status`/`code`/`body` — không chỉ một câu chữ.
 *
 * Vì sao: chỗ gọi vẫn in `String(err)` khắp nơi, nên CÂU LỖI phải giữ nguyên như trước (kể cả
 * tiền tố mã lỗi); nhưng `POST /api/agent/plans/review` trả 409 kèm `{blocked, code, reason, remedy}`
 * mà một `Error` trơn thì nuốt mất — không phân biệt được "bị khoá vì chưa phản biện" với 409 vặt.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly body?: unknown

  constructor(message: string, status: number, code?: string, body?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.body = body
  }
}

export async function agentApi<T>(path: string, body?: unknown, method?: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/agent${path}`, {
    method: method ?? (body === undefined ? 'GET' : 'POST'),
    headers: { 'Content-Type': 'application/json', 'X-BoxFox-Admin': '1' },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    ...(signal ? { signal } : {}),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({ error: 'Harness engine unavailable. Start the BoxFox launcher.' }))
    const message = error.error ?? `Harness HTTP ${response.status}`
    // Giữ mã lỗi trong câu: người dùng thấy `SESSION_NOT_FOUND` thay vì một chữ "Not found"
    // không tra cứu được, và store nhận ra được phiên cũ để tự mở phiên mới.
    throw new ApiError(
      error.code && !message.startsWith(error.code) ? `${error.code}: ${message}` : message,
      response.status,
      typeof error.code === 'string' ? error.code : undefined,
      error,
    )
  }
  return response.json() as Promise<T>
}
