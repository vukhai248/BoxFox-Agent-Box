import { afterEach, describe, expect, it, vi } from 'vitest'
import { INSPECT_TIMEOUT_MS, SandboxInspectRepository } from './http'
import { InspectHttpError } from './types'

function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number }): Response {
  const ok = init?.ok ?? true
  const status = init?.status ?? 200
  return { ok, status, json: async () => body } as Response
}

const validDomPayload = {
  type: 'dom',
  selector: 'span',
  url: 'http://localhost:3100/',
  title: 'BoxFox',
  tagName: 'span',
  text: 'boxfox',
  html: '<span>boxfox</span>',
  truncated: false,
  attributes: {},
  cssBox: { x: 0, y: 0, width: 0, height: 0 },
  screenBox: { x: 0, y: 0, width: 0, height: 0 },
  target: { windowId: '0x1', windowTitle: 'Win', targetId: 'tgt-1' },
  label: {
    integrity: 'khong_tin_duoc',
    confidentiality: 'noi_bo',
    source_kind: 'screen_capture',
    source_uri: 'screen://element/0x1',
    tool_name: 'inspect_element',
    content_hash: '',
  },
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.useRealTimers()
})

describe('SandboxInspectRepository', () => {
  it('POST đúng URL, header, body', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(validDomPayload))
    vi.stubGlobal('fetch', fetchMock)
    await new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 10, y: 20 })
    expect(fetchMock).toHaveBeenCalledWith(
      'http://box.test/__box/inspect-element',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-BoxFox-Api-Key': 'k' },
        body: JSON.stringify({ x: 10, y: 20 }),
      }),
    )
  })

  it('200 + payload hợp lệ ⇒ trả kết quả đã parse', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(validDomPayload))
    vi.stubGlobal('fetch', fetchMock)
    const result = await new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 1, y: 2 })
    expect(result).toMatchObject({ type: 'dom', selector: 'span' })
  })

  it('200 + payload rác ⇒ ném InspectHttpError kind badResponse', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ garbage: true }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 1, y: 2 })).rejects.toMatchObject({
      kind: 'badResponse',
    })
  })

  it('403 ⇒ forbidden', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ error: 'no' }, { ok: false, status: 403 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 1, y: 2 })).rejects.toMatchObject({
      kind: 'forbidden',
      status: 403,
      message: 'no',
    })
  })

  it('404 ⇒ notFound', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, { ok: false, status: 404 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 1, y: 2 })).rejects.toMatchObject({
      kind: 'notFound',
      status: 404,
    })
  })

  it('500 ⇒ server', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}, { ok: false, status: 500 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 1, y: 2 })).rejects.toBeInstanceOf(
      InspectHttpError,
    )
  })

  it('fetch ném lỗi mạng (không phải AbortError) ⇒ network', async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError('failed to fetch'))
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 1, y: 2 })).rejects.toMatchObject({
      kind: 'network',
    })
  })

  it('AbortError (huỷ ngoài) ⇒ timeout', async () => {
    const abortError = new DOMException('Aborted', 'AbortError')
    const fetchMock = vi.fn().mockRejectedValue(abortError)
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxInspectRepository('http://box.test', 'k').inspect({ x: 1, y: 2 })).rejects.toMatchObject({
      kind: 'timeout',
    })
  })

  it('quá timeoutMs ⇒ tự abort request', async () => {
    vi.useFakeTimers()
    const fetchMock = vi.fn((_url: string, init: { signal: AbortSignal }) => {
      return new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    const promise = new SandboxInspectRepository('http://box.test', 'k', 100).inspect({ x: 1, y: 2 })
    const assertion = expect(promise).rejects.toMatchObject({ kind: 'timeout' })
    await vi.advanceTimersByTimeAsync(150)
    await assertion
  })

  it('signal ngoài bị huỷ ⇒ cầu nối abort request đang chạy', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn((_url: string, init: { signal: AbortSignal }) => {
      return new Promise((_resolve, reject) => {
        init.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
      })
    })
    vi.stubGlobal('fetch', fetchMock)
    const promise = new SandboxInspectRepository('http://box.test', 'k', INSPECT_TIMEOUT_MS).inspect(
      { x: 1, y: 2 },
      controller.signal,
    )
    const assertion = expect(promise).rejects.toMatchObject({ kind: 'timeout' })
    controller.abort()
    await assertion
  })
})
