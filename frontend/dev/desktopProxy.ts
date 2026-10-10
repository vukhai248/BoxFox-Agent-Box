import type { ProxyOptions } from 'vite'

/** Server-only opt-in: use the desktop gateway instead of a second harness/profile. */
export function desktopGatewayProxy(value: string | undefined): Record<string, ProxyOptions> | undefined {
  if (!value) return undefined
  const gateway = new URL(value)
  if (gateway.protocol !== 'http:' || !['127.0.0.1', 'localhost'].includes(gateway.hostname)
    || !gateway.port || gateway.username || gateway.password || gateway.pathname !== '/' || gateway.search || gateway.hash) {
    throw new Error('BOXFOX_DESKTOP_GATEWAY must be an HTTP loopback origin with an explicit port')
  }
  const proxy: ProxyOptions = {
    target: gateway.origin,
    changeOrigin: true,
    ws: true,
    configure(server) {
      const forwardOwnOrigin = (upstream: { setHeader: (key: string, value: string) => void }, request: { headers: { host?: string; origin?: string } }) => {
        // Preserve foreign/missing Origin for the desktop gateway's validation.
        if (request.headers.origin === `http://${request.headers.host}`
          && /^(localhost|127\.0\.0\.1):\d+$/.test(request.headers.host ?? '')) {
          upstream.setHeader('Origin', gateway.origin)
        }
      }
      server.on('proxyReq', forwardOwnOrigin)
      server.on('proxyReqWs', forwardOwnOrigin)
    },
  }
  return Object.fromEntries(['/api/agent', '/api/router', '/api/desktop', '/v1', '/__box', '/__tty'].map(route => [route, proxy]))
}
