/**
 * Adapter HTTP của host mode cho Element Selector — `POST /api/agent/desktop/inspect-element`.
 *
 * Vì sao là một repository RIÊNG thay vì thêm nhánh vào `SandboxInspectRepository`:
 * hai đường có ba khác biệt thật, không phải chi tiết cài đặt —
 *
 *   1. **Xác thực**: box dùng `X-BoxFox-Api-Key` + `baseUrl` cấu hình; harness đi
 *      qua `agentApi` (cùng origin, header `X-BoxFox-Admin`).
 *   2. **Hình dạng lỗi**: harness trả `{error, code}` với `code` là MÃ MÁY
 *      (`HUMAN_HAS_CONTROL`, `ELEMENT_STALE`, …) — ngăn kéo dịch theo mã đó.
 *   3. **Ngữ nghĩa 409**: box không có lease người/agent, harness thì có.
 *
 * `useElementInspector(repo)` nhận repository qua tham số đúng để chỗ này không
 * phải sửa hook dùng chung.
 */
import { ApiError, agentApi } from '../agentApi'
import { INSPECT_TIMEOUT_MS } from './http'
import { parseInspectElementResult } from './parse'
import { InspectHttpError, type InspectErrorKind, type InspectRepository } from './types'
import type { InspectElementRequest, InspectElementResult } from '../../types/inspect'

/**
 * Mã lỗi host mode mà ngăn kéo có câu dịch riêng (`hostError.*`).
 *
 * Danh sách này KHÔNG phải bản sao của `sandbox/win/errors.py` — nó là những mã
 * mà `POST /desktop/inspect-element` thật sự có thể trả về (route gắn
 * `getattr(exc, 'code', …)`, nên đây là các mã của tầng nền tảng Windows).
 */
export const HOST_INSPECT_ERROR_CODES = [
  'ELEMENT_STALE',
  'SOURCE_CHANGED',
  'SOURCE_IDENTITY_UNAVAILABLE',
  'CONTROL_BUSY',
  'DESKTOP_LOCKED',
  'HUMAN_HAS_CONTROL',
  'HUMAN_TOOK_OVER',
  'UIA_UNAVAILABLE',
  'UIA_TIMEOUT',
  'UIA_PROVIDER_HANG',
  'UIPI_BLOCKED',
  'SESSION_NOT_INTERACTIVE',
  'UNSUPPORTED_IN_HOST_MODE',
  'PASSWORD_FIELD_REFUSED',
  'WINDOW_MINIMIZED',
  'WINDOW_CLOAKED',
  'WINDOW_IDENTITY_UNAVAILABLE',
  'CAPTURE_FAILED',
  'OS_PERMISSION_REQUIRED',
  'INSPECT_POINT_INVALID',
  'INSPECT_FAILED',
] as const

export type HostInspectErrorCode = (typeof HOST_INSPECT_ERROR_CODES)[number]

/** `true` khi `code` là mã host mode đã biết. */
export function isHostInspectErrorCode(code: string | undefined): code is HostInspectErrorCode {
  return !!code && (HOST_INSPECT_ERROR_CODES as readonly string[]).includes(code)
}

/** Phân loại lỗi dùng chung `InspectErrorKind` — chỉ là đường lùi khi mã lạ. */
function statusToErrorKind(status: number): InspectErrorKind {
  if (status === 403) return 'forbidden'
  if (status === 404) return 'notFound'
  if (status >= 500) return 'server'
  return 'network'
}

export class HostInspectRepository implements InspectRepository {
  constructor(private readonly timeoutMs: number = INSPECT_TIMEOUT_MS) {}

  async inspect(point: InspectElementRequest, signal?: AbortSignal): Promise<InspectElementResult> {
    const controller = new AbortController()
    const forwardAbort = () => controller.abort()
    signal?.addEventListener('abort', forwardAbort)
    // Cầu nối `setTimeout` + `AbortController` (KHÔNG `AbortSignal.timeout()`):
    // cần hợp nhất hai nguồn huỷ — hết 8 s, và bên gọi bấm điểm mới.
    const timeoutId = setTimeout(() => controller.abort(), this.timeoutMs)

    try {
      let payload: unknown
      try {
        payload = await agentApi<unknown>('/desktop/inspect-element', point, 'POST', controller.signal)
      } catch (cause) {
        if (controller.signal.aborted && !signal?.aborted) {
          throw new InspectHttpError('timeout', 0, 'Yêu cầu thanh tra phần tử đã hết thời gian chờ.')
        }
        if (cause instanceof ApiError) {
          // Giữ NGUYÊN `code`: ngăn kéo dịch theo mã trước, `kind` chỉ là đường lùi.
          throw new InspectHttpError(statusToErrorKind(cause.status), cause.status, cause.message, cause.code)
        }
        throw new InspectHttpError('network', 0, 'Không gọi được harness để thanh tra phần tử.')
      }

      const result = parseInspectElementResult(payload)
      if (!result) {
        throw new InspectHttpError('badResponse', 200, 'Phản hồi thanh tra phần tử sai hình dạng.')
      }
      return result
    } finally {
      clearTimeout(timeoutId)
      signal?.removeEventListener('abort', forwardAbort)
    }
  }
}
