import { describe, expect, it, vi } from 'vitest'
import { desktopGatewayProxy } from './desktopProxy'

describe('web uses desktop gateway', () => {
  it('keeps standalone web as default and shares every desktop API/WS route when opted in', () => {
    expect(desktopGatewayProxy(undefined)).toBeUndefined()
    const routes = desktopGatewayProxy('http://127.0.0.1:64557')!
    expect(Object.keys(routes)).toEqual(['/api/agent', '/api/router', '/api/desktop', '/v1', '/__box', '/__tty'])
    for (const route of Object.values(routes)) expect(route).toMatchObject({ target: 'http://127.0.0.1:64557', ws: true })
  })

  it.each(['https://localhost:10', 'http://example.com:10', 'http://localhost', 'http://user:password@localhost:10', 'http://localhost:10/path'])('rejects non-loopback or ambiguous gateway %s', value => {
    expect(() => desktopGatewayProxy(value)).toThrow()
  })

  it('rewrites only its own browser Origin, including WS, preserving foreign/missing headers for gateway validation', () => {
    const listeners = new Map<string, (proxy: { setHeader: typeof setHeader }, req: { headers: Record<string, string> }) => void>()
    const setHeader = vi.fn()
    const route = desktopGatewayProxy('http://127.0.0.1:64557')!['/api/agent']
    const server = { on: (kind: string, listener: never) => listeners.set(kind, listener) }
    route.configure!(server as never, route)
    for (const kind of ['proxyReq', 'proxyReqWs']) {
      listeners.get(kind)!({ setHeader }, { headers: { host: 'localhost:3110', origin: 'http://localhost:3110' } })
      expect(setHeader).toHaveBeenLastCalledWith('Origin', 'http://127.0.0.1:64557')
      setHeader.mockClear()
      for (const origin of ['https://foreign.example', 'http://localhost:9999', '']) {
        listeners.get(kind)!({ setHeader }, { headers: { host: 'localhost:3110', origin } })
        expect(setHeader).not.toHaveBeenCalled()
      }
    }
  })
})
