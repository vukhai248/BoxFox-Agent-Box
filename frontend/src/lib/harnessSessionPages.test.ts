import { afterEach, describe, expect, it, vi } from 'vitest'
import { readHarnessSessionPages } from './harnessSessionPages'

afterEach(() => vi.unstubAllGlobals())

const event = (seq: number, type = 'thought') => ({ seq, type, data: { text: `event-${seq}` }, created: seq })
function mockPages(pages: unknown[]) {
  const fetcher = vi.fn()
  for (const page of pages) fetcher.mockResolvedValueOnce({ ok: true, json: async () => page })
  vi.stubGlobal('fetch', fetcher)
  return fetcher
}

describe('complete harness event pagination', () => {
  it('loads the final thought/assistant after the first 500 events even when already completed', async () => {
    const first = Array.from({ length: 500 }, (_, i) => event(i + 1))
    const fetcher = mockPages([
      { status: 'completed', events: first, hasMore: true, nextAfter: 500 },
      { status: 'completed', events: [event(501, 'assistant'), event(502, 'finish')], hasMore: false, nextAfter: 502 },
    ])
    const result = await readHarnessSessionPages('child/one')
    expect(result.events).toHaveLength(502)
    expect(result.events.at(-2)?.type).toBe('assistant')
    expect(fetcher.mock.calls.map(call => call[0])).toEqual([
      '/api/agent/sessions/child%2Fone?after=0', '/api/agent/sessions/child%2Fone?after=500',
    ])
  })

  it('reads only the new tail and supports old responses without pagination metadata', async () => {
    const fetcher = mockPages([{ events: [event(10), event(11)] }])
    expect((await readHarnessSessionPages('child', 10)).events.map(item => item.seq)).toEqual([11])
    expect(fetcher.mock.calls[0][0]).toContain('after=10')
  })

  it.each([0, 9, undefined, NaN])('rejects a stuck or inconsistent cursor (%s)', async nextAfter => {
    const fetcher = mockPages([{ events: [event(1)], hasMore: true, nextAfter }])
    await expect(readHarnessSessionPages('child')).rejects.toThrow('SESSION_EVENTS_CURSOR_INVALID')
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('does not convert a failed later page to an empty successful history', async () => {
    const fetcher = mockPages([{ events: [event(1)], hasMore: true, nextAfter: 1 }])
    fetcher.mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ error: 'Unavailable' }) })
    await expect(readHarnessSessionPages('child')).rejects.toThrow('Unavailable')
  })

  it('stops before fetching another page if the viewer switches child', async () => {
    const controller = new AbortController()
    const fetcher = vi.fn().mockImplementation(async () => {
      controller.abort()
      return { ok: true, json: async () => ({ events: [event(1)], hasMore: true, nextAfter: 1 }) }
    })
    vi.stubGlobal('fetch', fetcher)
    await expect(readHarnessSessionPages('child', 0, controller.signal)).rejects.toThrow()
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})
