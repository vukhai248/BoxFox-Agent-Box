/**
 * Test cho client "đích CUA theo phiên".
 *
 * Tệp này khoá ĐÚNG hợp đồng route (path, method, body) — vì đó là toàn bộ lý do
 * lớp này tồn tại: backend đổi tên trường thì chỉ hai tệp phải sửa, và test này
 * là chỗ nói ra tên trường. Ca cuối khoá điều quan trọng nhất về lỗi: `ApiError.code`
 * phải đi qua nguyên vẹn, nếu không panel không dịch được `SCREEN_OCCLUDED`…
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '../agentApi'
import {
  CUA_POLL_MS,
  captureMachine,
  captureWindow,
  clearTarget,
  getTarget,
  isCuaTargetErrorCode,
  listWindows,
  setTarget,
  targetKey,
} from './target'
import type { CuaTargetState } from '../../types/desktopTarget'

function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number }): Response {
  return { ok: init?.ok ?? true, status: init?.status ?? 200, json: async () => body } as Response
}

/** Gọi fetch lần đầu và trả `[url, init]` để các ca soi cho gọn. */
function firstCall(mock: ReturnType<typeof vi.fn>): [string, RequestInit] {
  const call = mock.mock.calls[0] as [string, RequestInit]
  return call
}

function state(overrides: Partial<CuaTargetState> = {}): CuaTargetState {
  return {
    sessionId: 's-1',
    target: null,
    requestedBy: null,
    effective: null,
    activeWindow: null,
    scope: 'machine',
    cuaEnabled: true,
    revision: 3,
    activity: null,
    ...overrides,
  }
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('targetKey / isCuaTargetErrorCode', () => {
  it('khoá nhận dạng: rỗng khi chưa có đích, "machine" cho cả máy, "window:<id>" cho cửa sổ', () => {
    expect(targetKey(null)).toBe('')
    expect(targetKey(undefined)).toBe('')
    expect(targetKey({ kind: 'machine' })).toBe('machine')
    expect(targetKey({ kind: 'window', windowId: 394820 })).toBe('window:394820')
  })

  it('hwnd dạng số và dạng chuỗi là CÙNG một đích (backend có thể trả cả hai)', () => {
    expect(targetKey({ kind: 'window', windowId: '394820' })).toBe(targetKey({ kind: 'window', windowId: 394820 }))
  })

  it('chỉ nhận mã đã biết, mã lạ trả false', () => {
    expect(isCuaTargetErrorCode('SCREEN_OCCLUDED')).toBe(true)
    expect(isCuaTargetErrorCode('TARGET_REVISION_CONFLICT')).toBe(true)
    expect(isCuaTargetErrorCode('ELEMENT_STALE')).toBe(false)
    expect(isCuaTargetErrorCode(undefined)).toBe(false)
  })

  it('nhịp poll là 2 s (không websocket — đây là hằng số của cả cơ chế "theo agent")', () => {
    expect(CUA_POLL_MS).toBe(2000)
  })
})

describe('listWindows', () => {
  it('GET /machines/screen và trả mảng cửa sổ', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ windows: [{ windowId: 12, zOrder: 0, title: 'a.txt - Notepad', windowClass: 'Notepad', pid: 4, processName: 'notepad.exe', position: { x: 0, y: 0 }, size: { width: 800, height: 600 }, dpi: 96 }] }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const windows = await listWindows()
    expect(firstCall(fetchMock)[0]).toBe('/api/agent/machines/screen')
    expect(firstCall(fetchMock)[1].method).toBe('GET')
    expect(windows).toHaveLength(1)
    expect(windows[0].processName).toBe('notepad.exe')
  })

  it('payload thiếu `windows` (nền không hỗ trợ) ⇒ mảng rỗng, không ném', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ windows: null })))
    expect(await listWindows()).toEqual([])
  })

  it('409 HOST_SCREEN_UNAVAILABLE ⇒ ApiError giữ mã', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: 'no window list', code: 'HOST_SCREEN_UNAVAILABLE' }, { ok: false, status: 409 })),
    )
    await expect(listWindows()).rejects.toMatchObject({ name: 'ApiError', status: 409, code: 'HOST_SCREEN_UNAVAILABLE' })
  })
})

describe('getTarget / setTarget / clearTarget', () => {
  it('GET kèm sessionId đã encode', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(state()))
    vi.stubGlobal('fetch', fetchMock)
    const result = await getTarget('phiên 1/2')
    expect(firstCall(fetchMock)[0]).toBe('/api/agent/machines/target?sessionId=phi%C3%AAn%201%2F2')
    expect(firstCall(fetchMock)[1].method).toBe('GET')
    expect(result.revision).toBe(3)
  })

  it('PUT đúng body của hợp đồng (kind/windowId/pid/consent/expectedRevision)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(state({ target: { kind: 'window', windowId: 42 } })))
    vi.stubGlobal('fetch', fetchMock)
    await setTarget({ sessionId: 's-1', kind: 'window', windowId: 42, pid: 7, consent: true, expectedRevision: 3 })
    const [url, init] = firstCall(fetchMock)
    expect(url).toBe('/api/agent/machines/target')
    expect(init.method).toBe('PUT')
    expect(JSON.parse(String(init.body))).toEqual({
      sessionId: 's-1',
      kind: 'window',
      windowId: 42,
      pid: 7,
      consent: true,
      expectedRevision: 3,
    })
  })

  it('PUT đích cả máy chỉ gửi kind + consent', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(state({ target: { kind: 'machine' } })))
    vi.stubGlobal('fetch', fetchMock)
    await setTarget({ sessionId: 's-1', kind: 'machine', consent: true })
    expect(JSON.parse(String(firstCall(fetchMock)[1].body))).toEqual({ sessionId: 's-1', kind: 'machine', consent: true })
  })

  it('DELETE không có body, sessionId nằm ở query', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(state({ target: null })))
    vi.stubGlobal('fetch', fetchMock)
    const result = await clearTarget('s-1')
    const [url, init] = firstCall(fetchMock)
    expect(url).toBe('/api/agent/machines/target?sessionId=s-1')
    expect(init.method).toBe('DELETE')
    expect(init.body).toBeUndefined()
    expect(result.target).toBeNull()
  })
})

describe('captureWindow / captureMachine', () => {
  it('POST /machines/screen với kind window kèm pid', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ image: 'x', mime: 'image/png', width: 1, height: 1, hash: 'h', snapshotId: 's', captureOrigin: { x: 0, y: 0 }, captureSize: { width: 1, height: 1 } }))
    vi.stubGlobal('fetch', fetchMock)
    await captureWindow({ windowId: '0x1f', pid: 9 })
    const [url, init] = firstCall(fetchMock)
    expect(url).toBe('/api/agent/machines/screen')
    expect(init.method).toBe('POST')
    expect(JSON.parse(String(init.body))).toEqual({ consent: true, kind: 'window', windowId: '0x1f', pid: 9 })
  })

  it('POST /machines/screen với kind machine — không có windowId', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ image: 'x', mime: 'image/png', width: 1, height: 1, hash: 'h', snapshotId: 's', captureOrigin: { x: -1920, y: 0 }, captureSize: { width: 3840, height: 1080 } }))
    vi.stubGlobal('fetch', fetchMock)
    const shot = await captureMachine()
    expect(JSON.parse(String(firstCall(fetchMock)[1].body))).toEqual({ consent: true, kind: 'machine' })
    expect(shot.captureOrigin).toEqual({ x: -1920, y: 0 })
  })

  it('lỗi giữ nguyên `code` để panel dịch theo mã', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ error: 'window is occluded', code: 'SCREEN_OCCLUDED' }, { ok: false, status: 409 })),
    )
    const error = await captureMachine().catch((cause: unknown) => cause)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe('SCREEN_OCCLUDED')
  })

  it('signal của bên gọi đi thẳng vào fetch (nền tảng của epoch guard)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(state()))
    vi.stubGlobal('fetch', fetchMock)
    const controller = new AbortController()
    await getTarget('s-1', controller.signal)
    expect(firstCall(fetchMock)[1].signal).toBe(controller.signal)
  })
})
