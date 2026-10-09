/**
 * Client của "đích CUA theo phiên" — bọc ba route target + hai route ảnh chụp
 * thành hàm có kiểu (mục 2.2 của `v1-cua-target.md`).
 *
 * Vì sao có lớp này thay vì gọi `agentApi` thẳng trong panel: hợp đồng route còn
 * đang chạy song song với lát backend, nên tên trường chỉ được xuất hiện ở ĐÚNG
 * hai tệp (`types/desktopTarget.ts` + tệp này). Backend đổi tên ⇒ sửa hai tệp.
 *
 * KHÔNG dùng `AbortSignal.timeout()`: nó không có trong jsdom (test) và làm
 * `AbortError` khó phân biệt với abort do đổi đích — panel cần phân biệt đúng
 * hai thứ đó. Bên gọi luôn truyền `signal` của mình (epoch guard ở panel).
 */
import { agentApi } from '../agentApi'
import type { CuaTarget, CuaTargetRequest, CuaTargetState, HostSnapshot, HostWindowEntry } from '../../types/desktopTarget'

/** Nhịp theo dõi đích của agent: 2 s, chỉ khi tab đang hiện (không websocket). */
export const CUA_POLL_MS = 2_000

/**
 * Mã lỗi của ba route target (mục 2.2) — panel dịch theo mã, không phô chuỗi thô
 * của backend. `SCREEN_CONSENT_REQUIRED`/`SCREEN_TARGET_CHANGED`/
 * `SCREEN_SNAPSHOT_STALE`/`SCREEN_OCCLUDED` là của route `screen` đã có.
 */
export const CUA_TARGET_ERROR_CODES = [
  'TARGET_KIND_INVALID',
  'TARGET_CONSENT_REQUIRED',
  'CUA_MACHINE_SCOPE_REQUIRED',
  'SESSION_NOT_FOUND',
  'HOST_SESSION_REQUIRED',
  'TARGET_UNKNOWN',
  'TARGET_CHANGED',
  'TARGET_REVISION_CONFLICT',
  'CUA_UNAVAILABLE',
  'HOST_SCREEN_UNAVAILABLE',
  'SCREEN_CONSENT_REQUIRED',
  'SCREEN_TARGET_CHANGED',
  'SCREEN_SNAPSHOT_STALE',
  'SCREEN_OCCLUDED',
] as const

export type CuaTargetErrorCode = (typeof CUA_TARGET_ERROR_CODES)[number]

/** `true` khi `code` là mã đã biết của nhóm route target/ảnh chụp. */
export function isCuaTargetErrorCode(code: string | undefined): code is CuaTargetErrorCode {
  return !!code && (CUA_TARGET_ERROR_CODES as readonly string[]).includes(code)
}

/**
 * Khoá nhận dạng đích — dùng để biết "đích vừa đổi" giữa hai lần poll.
 *
 * So sánh qua `String(windowId)` vì backend có thể trả HWND dạng số hoặc chuỗi;
 * `'123'` và `123` là CÙNG một cửa sổ, không được coi là hai đích khác nhau.
 */
export function targetKey(target: CuaTarget | null | undefined): string {
  if (!target) return ''
  if (target.kind === 'machine') return 'machine'
  return `window:${String(target.windowId)}`
}

/** Danh sách cửa sổ đang mở — `GET /api/agent/machines/screen` (route đã có). */
export async function listWindows(signal?: AbortSignal): Promise<HostWindowEntry[]> {
  const payload = await agentApi<{ windows?: HostWindowEntry[] | null }>('/machines/screen', undefined, 'GET', signal)
  return Array.isArray(payload?.windows) ? payload.windows : []
}

/** Đích hiện tại của phiên + cửa sổ agent đang thao tác. */
export async function getTarget(sessionId: string, signal?: AbortSignal): Promise<CuaTargetState> {
  return agentApi<CuaTargetState>(`/machines/target?sessionId=${encodeURIComponent(sessionId)}`, undefined, 'GET', signal)
}

/** Đặt đích (người dùng bấm trong panel ⇒ `consent: true`). */
export async function setTarget(request: CuaTargetRequest, signal?: AbortSignal): Promise<CuaTargetState> {
  return agentApi<CuaTargetState>('/machines/target', request, 'PUT', signal)
}

/** Thu hồi đích của phiên — `DELETE /api/agent/machines/target?sessionId=…`. */
export async function clearTarget(sessionId: string, signal?: AbortSignal): Promise<CuaTargetState> {
  return agentApi<CuaTargetState>(`/machines/target?sessionId=${encodeURIComponent(sessionId)}`, undefined, 'DELETE', signal)
}

/**
 * Chụp một cửa sổ. `pid` đi kèm `windowId` để backend kiểm lại hwnd còn đúng
 * tiến trình không (hwnd bị tái dùng là chuyện thật trên Windows).
 */
export async function captureWindow(
  { windowId, pid }: { windowId: string | number; pid?: number },
  signal?: AbortSignal,
): Promise<HostSnapshot> {
  return agentApi<HostSnapshot>('/machines/screen', { consent: true, kind: 'window', windowId, pid }, 'POST', signal)
}

/** Chụp toàn màn hình ảo — chỉ dùng khi đích là `kind: 'machine'`. */
export async function captureMachine(signal?: AbortSignal): Promise<HostSnapshot> {
  return agentApi<HostSnapshot>('/machines/screen', { consent: true, kind: 'machine' }, 'POST', signal)
}
