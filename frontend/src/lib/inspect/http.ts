/**
 * Adapter HTTP cho `POST /__box/inspect-element` (khung ④, Element Selector).
 *
 * Theo đúng mẫu `lib/workspace/http.ts`: class + `X-BoxFox-Api-Key` cho request
 * ghi + lớp lỗi riêng. Khác biệt bắt buộc: timeout **8000 ms** dựng bằng
 * `AbortController` + `setTimeout` + `clearTimeout` trong `finally` — KHÔNG
 * dùng `AbortSignal.timeout()` vì hàm đó không cho cầu nối thêm một `signal`
 * do BÊN GỌI truyền vào (huỷ khi người dùng bấm điểm mới trước khi yêu cầu cũ
 * xong, xem hook điều phối F8).
 */
import type { InspectElementRequest, InspectElementResult } from '../../types/inspect'
import { parseInspectElementResult, parseInspectErrorBody } from './parse'
import { InspectHttpError, type InspectErrorKind, type InspectRepository } from './types'

export const INSPECT_TIMEOUT_MS = 8_000

/**
 * KHÔNG dùng `cause instanceof Error` — `DOMException` (thứ `fetch` ném khi
 * `AbortController.abort()`) không kế thừa `Error` trong jsdom (môi trường
 * test), dù có trong hầu hết trình duyệt thật. Kiểm tra `name` trực tiếp để
 * hành vi giống nhau ở cả hai môi trường.
 */
function isAbortError(cause: unknown): boolean {
  return typeof cause === 'object' && cause !== null && (cause as { name?: unknown }).name === 'AbortError'
}

function statusToErrorKind(status: number): InspectErrorKind {
  if (status === 403) return 'forbidden'
  if (status === 404) return 'notFound'
  if (status >= 500) return 'server'
  return 'network'
}

/** `{"error":"..."}` theo mẫu `lib/workspace/http.ts:100-110` — không phải JSON thì giữ mặc định. */
async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload: unknown = await response.json()
    return parseInspectErrorBody(payload) ?? `Yêu cầu thanh tra phần tử thất bại (${response.status}).`
  } catch {
    return `Yêu cầu thanh tra phần tử thất bại (${response.status}).`
  }
}

export class SandboxInspectRepository implements InspectRepository {
  constructor(
    private readonly baseUrl: string,
    private readonly apiKey: string,
    private readonly timeoutMs: number = INSPECT_TIMEOUT_MS,
  ) {}

  async inspect(point: InspectElementRequest, signal?: AbortSignal): Promise<InspectElementResult> {
    const controller = new AbortController()
    const forwardAbort = () => controller.abort()
    signal?.addEventListener('abort', forwardAbort)
    const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs)

    try {
      let response: Response
      try {
        response = await fetch(`${this.baseUrl}/__box/inspect-element`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'X-BoxFox-Api-Key': this.apiKey },
          body: JSON.stringify(point),
          signal: controller.signal,
        })
      } catch (cause) {
        if (isAbortError(cause)) {
          throw new InspectHttpError('timeout', 0, 'Yêu cầu thanh tra phần tử đã hết thời gian chờ.')
        }
        throw new InspectHttpError('network', 0, 'Không gọi được máy sandbox.')
      }

      if (!response.ok) {
        const message = await readErrorMessage(response)
        throw new InspectHttpError(statusToErrorKind(response.status), response.status, message)
      }

      const payload: unknown = await response.json()
      const result = parseInspectElementResult(payload)
      if (!result) {
        throw new InspectHttpError('badResponse', response.status, 'Phản hồi thanh tra phần tử sai hình dạng.')
      }
      return result
    } finally {
      clearTimeout(timeoutId)
      signal?.removeEventListener('abort', forwardAbort)
    }
  }
}
