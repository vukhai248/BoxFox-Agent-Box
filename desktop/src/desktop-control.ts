/**
 * Desktop-control requests issued from the tray (D3): "Trả quyền cho agent" and
 * "Dừng khẩn".
 *
 * Both call the harness lease route (`POST /api/agent/desktop/lease`, plan §4.4 / H7)
 * through the harness itself, not through the UI. The tray must never crash or block on
 * that call:
 *
 *   - docker mode has no host lease — the harness answers 409 and the tray reports it;
 *   - a harness build without the route answers 404;
 *   - a stopped harness fails at the socket.
 *
 * Every outcome is returned as data (`ok`, `status`, `error`, `body`) and the caller
 * decides what to show the user.
 */

export type DesktopControlAction = 'claim' | 'stop'

export interface DesktopControlRequest {
  /** Base URL of the harness, e.g. `http://127.0.0.1:<harness port>`. */
  baseUrl: string
  action: DesktopControlAction
  /** Free-text reason recorded by the lease; defaults to `tray`. */
  reason?: string
  /**
   * Origin presented to the harness. The app sets `BOXFOX_UI_ORIGINS` to the gateway
   * origins, so the gateway URL is always allowlisted.
   */
  origin?: string
  fetchImpl?: typeof fetch
  timeoutMs?: number
}

export interface DesktopControlResult {
  ok: boolean
  action: DesktopControlAction
  /** HTTP status, or `null` when the request never reached the harness. */
  status: number | null
  /** Structured code from the harness body (`code`/`error`), when it sent one. */
  error: string | null
  /** Parsed JSON body when the harness answered with one. */
  body: unknown
}

export const DESKTOP_LEASE_PATH = '/api/agent/desktop/lease'

function errorFromBody(body: unknown, status: number): string {
  if (body !== null && typeof body === 'object') {
    const record = body as Record<string, unknown>
    if (typeof record.code === 'string' && record.code !== '') return record.code
    if (typeof record.error === 'string' && record.error !== '') return record.error
  }
  if (status === 409) return 'The request was rejected (409).'
  return `The harness answered HTTP ${status}.`
}

/**
 * POST one lease action. Never throws: transport errors, timeouts and non-2xx answers
 * all come back as `{ ok: false }` with the reason filled in.
 */
export async function requestDesktopControl(input: DesktopControlRequest): Promise<DesktopControlResult> {
  const action = input.action
  const fetchImpl = input.fetchImpl ?? fetch
  const timeoutMs = input.timeoutMs ?? 5_000
  const url = `${input.baseUrl.replace(/\/+$/, '')}${DESKTOP_LEASE_PATH}`
  const headers: Record<string, string> = {
    'content-type': 'application/json',
    // The harness boundary requires the admin marker on every non-health route.
    'X-BoxFox-Admin': '1',
  }
  if (input.origin) headers.origin = input.origin
  try {
    const response = await fetchImpl(url, {
      method: 'POST',
      headers,
      body: JSON.stringify({ action, reason: input.reason ?? 'tray' }),
      signal: AbortSignal.timeout(timeoutMs),
    })
    const text = await response.text().catch(() => '')
    let body: unknown = null
    if (text.trim() !== '') {
      try {
        body = JSON.parse(text)
      } catch {
        body = text
      }
    }
    if (!response.ok) {
      return { ok: false, action, status: response.status, error: errorFromBody(body, response.status), body }
    }
    return { ok: true, action, status: response.status, error: null, body }
  } catch (error) {
    return { ok: false, action, status: null, error: (error as Error).message, body: null }
  }
}

/** Human-readable one-liner for logs and message boxes. */
export function describeControlResult(result: DesktopControlResult): string {
  const label = result.action === 'claim' ? 'Trả quyền cho agent' : 'Dừng khẩn'
  if (result.ok) return `${label}: đã gửi tới harness (HTTP ${result.status}).`
  if (result.status === 409) {
    return `${label}: harness từ chối (409 — chế độ docker giữ quyền chuột/phím trong container).`
  }
  if (result.status === 404) {
    return `${label}: harness bản này chưa có route lease (404) — lớp CUA chưa nằm trong build.`
  }
  return `${label}: không thực hiện được (${result.error ?? 'không rõ nguyên nhân'}).`
}
