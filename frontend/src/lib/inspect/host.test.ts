/**
 * Test cho `HostInspectRepository` — đường thanh tra phần tử của host mode.
 *
 * Bốn điều tệp này khoá lại, đều là chỗ hai đường (box / harness) khác nhau thật:
 *   1. POST đúng `/api/agent/desktop/inspect-element` với `{x, y}` là toạ độ
 *      FRAMEBUFFER (panel đã cộng `captureOrigin` trước khi gọi).
 *   2. 409 `HUMAN_HAS_CONTROL` giữ nguyên `code` — ngăn kéo dịch theo mã, không
 *      theo `status`, vì cùng 409 còn có nghĩa khác ở route khác.
 *   3. Hết 8 s ⇒ `kind: 'timeout'` (không phải `network`): người dùng cần phân
 *      biệt "máy không trả lời" với "không gọi được harness".
 *   4. `signal` của bên gọi lan vào `fetch` — cơ chế huỷ lượt thanh tra cũ khi
 *      đổi đích dựa hoàn toàn vào điều này.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { HOST_INSPECT_ERROR_CODES, HostInspectRepository, isHostInspectErrorCode } from './host'
import { INSPECT_TIMEOUT_MS } from './http'

function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number }): Response {
  return { ok: init?.ok ?? true, status: init?.status ?? 200, json: async () => body } as Response
}

const UIA_PAYLOAD = {
  type: 'uia',
  name: 'Tệp',
  controlType: 'menu item',
  controlTypeId: 50011,
  automationId: 'FileMenu',
  className: 'MenuItem',
  helpText: '',
  isEnabled: true,
  isOffscreen: false,
  isPassword: false,
  bounds: { screenBox: { x: 10, y: 20, width: 42, height: 22 }, dpi: 96 },
  patterns: ['Invoke'],
  // `_window_id()` của backend trả CHUỖI (hwnd đã `str(int(hwnd))`).
  windowId: '394820',
  pid: 4,
  processName: 'notepad.exe',
  elementToken: 'tok-1',
  generation: 2,
  sourceId: 'src-1',
  frameId: 'f-1',
  geometryRevision: 7,
  label: {
    integrity: 'khong_tin_duoc',
    confidentiality: 'noi_bo',
    source_kind: 'screen_capture',
    source_uri: 'screen://element/394820',
    tool_name: 'inspect_element',
    content_hash: 'abc',
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('danh mục mã lỗi', () => {
  it('nhận mã host mode, từ chối mã của đường khác', () => {
    expect(isHostInspectErrorCode('HUMAN_HAS_CONTROL')).toBe(true)
    expect(isHostInspectErrorCode('PASSWORD_FIELD_REFUSED')).toBe(true)
    expect(isHostInspectErrorCode('SCREEN_OCCLUDED')).toBe(false)
    expect(isHostInspectErrorCode(undefined)).toBe(false)
  })

  it('không có mã trùng trong danh mục (bảng dịch trong ngăn kéo sẽ nuốt mất mã trùng)', () => {
    expect(new Set(HOST_INSPECT_ERROR_CODES).size).toBe(HOST_INSPECT_ERROR_CODES.length)
  })
})

describe('HostInspectRepository.inspect', () => {
  it('POST đúng URL, header và body {x, y}', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(UIA_PAYLOAD))
    vi.stubGlobal('fetch', fetchMock)
    await new HostInspectRepository().inspect({ x: 118, y: 96 })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/agent/desktop/inspect-element',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-BoxFox-Admin': '1' },
        body: JSON.stringify({ x: 118, y: 96 }),
      }),
    )
  })

  it('payload `uia` hợp lệ ⇒ trả `UiaInspectResult` đã parse (không còn badResponse)', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(UIA_PAYLOAD)))
    const result = await new HostInspectRepository().inspect({ x: 1, y: 2 })
    expect(result).toMatchObject({ type: 'uia', name: 'Tệp', controlType: 'menu item', elementToken: 'tok-1' })
  })

  it('409 HUMAN_HAS_CONTROL ⇒ InspectHttpError giữ nguyên code', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: 'human has control', code: 'HUMAN_HAS_CONTROL' }, { ok: false, status: 409 })),
    )
    const error = await new HostInspectRepository()
      .inspect({ x: 1, y: 2 })
      .catch((cause: unknown) => cause)
    expect(error).toMatchObject({ name: 'InspectHttpError', kind: 'network', status: 409, code: 'HUMAN_HAS_CONTROL' })
  })

  it('200 + payload rác ⇒ badResponse', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ garbage: true })))
    await expect(new HostInspectRepository().inspect({ x: 1, y: 2 })).rejects.toMatchObject({ kind: 'badResponse', status: 200 })
  })

  it('hết 8 s ⇒ kind timeout (không phải network), và mặc định đúng bằng INSPECT_TIMEOUT_MS', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const pending = new HostInspectRepository().inspect({ x: 1, y: 2 })
    const assertion = expect(pending).rejects.toMatchObject({ name: 'InspectHttpError', kind: 'timeout' })
    await vi.advanceTimersByTimeAsync(INSPECT_TIMEOUT_MS)
    await assertion
    expect(INSPECT_TIMEOUT_MS).toBe(8000)
  })

  it('abort của bên gọi lan vào fetch và KHÔNG bị báo thành timeout', async () => {
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const controller = new AbortController()
    const pending = new HostInspectRepository().inspect({ x: 1, y: 2 }, controller.signal)
    const assertion = expect(pending).rejects.toMatchObject({ kind: 'network' })
    controller.abort()
    await assertion
    expect((fetchMock.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true)
  })
})
