/**
 * Same-origin gateway of BoxFox Desktop (Alpha) — plan §6 PR-2 / D2.
 *
 * The Electron window loads ONE origin: `http://127.0.0.1:<gateway port>`. This server
 * is that origin. It serves the built UI and proxies, under the same origin:
 *
 *   /api/agent*   → harness   (agent API, SSE streams)
 *   /api/router*  → router    (model router admin + inference)
 *   /v1*          → router    (OpenAI-compatible inference)
 *   /__box/*      → box       (docker mode) or the harness desktop API (host mode)
 *   /__tty/*      → box       (docker mode; terminal websocket)
 *   /api/desktop/*            gateway-local identity/health for the UI
 *
 * Security (alpha):
 *   - binds loopback only;
 *   - strict Host allowlist: exactly `127.0.0.1:<port>` / `localhost:<port>`;
 *   - Origin allowlist: the same two origins, and an Origin header is REQUIRED on
 *     every state-changing method (POST/PUT/PATCH/DELETE) — a foreign local page
 *     cannot drive the app even though the port is loopback;
 *   - CSP + `X-Content-Type-Options: nosniff` + `Referrer-Policy: no-referrer` on
 *     every UI response; no wildcard anywhere;
 *   - `X-BoxFox-Admin: 1` is injected by the gateway itself (the gateway is the trust
 *     boundary; the UI does not need to hold the harness/router admin header);
 *   - the per-machine admin token is injected as `X-BoxFox-Api-Key` on box requests,
 *     so the bundled container shares the machine's secret, not the committed dev one.
 */

import * as fs from 'node:fs'
import * as http from 'node:http'
import * as net from 'node:net'
import * as path from 'node:path'
import type { Duplex } from 'node:stream'
import type { ExecutionMode, PortMap } from './profile'

export type RouteTarget = 'harness' | 'router' | 'box' | 'desktop' | 'unsupported'

export interface GatewayUpstreams {
  harness: string
  router: string
  box: string
}

export interface DesktopIdentity {
  app: string
  version: string
  mode: ExecutionMode
  ports: PortMap
  adminToken: string
}

export interface GatewayOptions {
  port: number
  host?: string
  uiDir: string
  mode: ExecutionMode
  upstreams: GatewayUpstreams
  identity: DesktopIdentity
  status?: () => unknown
  log?: (line: string) => void
}

export interface Gateway {
  server: http.Server
  url: string
  listen(): Promise<void>
  close(): Promise<void>
}

const HOP_BY_HOP = new Set([
  'connection',
  'keep-alive',
  'proxy-authenticate',
  'proxy-authorization',
  'te',
  'trailer',
  'transfer-encoding',
  'upgrade',
])

export function allowedHosts(port: number): string[] {
  return [`127.0.0.1:${port}`, `localhost:${port}`]
}

export function allowedOrigins(port: number): string[] {
  return [`http://127.0.0.1:${port}`, `http://localhost:${port}`]
}

/**
 * Routing table of the gateway, as data so tests can assert it directly.
 * Returns `null` for everything that is not an upstream surface (static UI).
 */
export function routeFor(pathname: string, mode: ExecutionMode): RouteTarget | null {
  const path = pathname || '/'
  if (path === '/api/desktop' || path.startsWith('/api/desktop/')) return 'desktop'
  if (path === '/api/agent' || path.startsWith('/api/agent/')) return 'harness'
  if (path === '/api/router' || path.startsWith('/api/router/')) return 'router'
  if (path === '/v1' || path.startsWith('/v1/')) return 'router'
  if (path === '/__box' || path.startsWith('/__box/')) return mode === 'docker' ? 'box' : 'harness'
  if (path === '/__tty' || path.startsWith('/__tty/')) return mode === 'docker' ? 'box' : 'unsupported'
  return null
}

/**
 * Host mode has no container: the box surface maps onto the harness desktop API
 * (`/__box/inspect-element` → `/api/agent/desktop/inspect-element`, plan H6).
 */
export function hostDesktopPath(pathname: string): string {
  const rest = pathname.replace(/^\/__box\/?/, '')
  return `/api/agent/desktop/${rest}`
}

export function contentSecurityPolicy(port: number): string {
  const ws = `ws://127.0.0.1:${port} ws://localhost:${port}`
  return [
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self' data:",
    `connect-src 'self' ${ws} http://localhost:${port}`,
    "media-src 'self' blob: data:",
    "worker-src 'self' blob:",
    "frame-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ')
}

const CONTENT_TYPES: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.map': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.ico': 'image/x-icon',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
  '.ttf': 'font/ttf',
  '.wasm': 'application/wasm',
  '.txt': 'text/plain; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.mp4': 'video/mp4',
  '.webm': 'video/webm',
}

function sendJson(res: http.ServerResponse, status: number, body: unknown): void {
  const payload = `${JSON.stringify(body)}\n`
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Content-Length': Buffer.byteLength(payload),
    'Cache-Control': 'no-store',
  })
  res.end(payload)
}

function securityHeaders(port: number): Record<string, string> {
  return {
    'Content-Security-Policy': contentSecurityPolicy(port),
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
  }
}

function serveStatic(req: http.IncomingMessage, res: http.ServerResponse, uiDir: string, port: number): void {
  const method = (req.method ?? 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') {
    sendJson(res, 405, { error: 'Method not allowed' })
    return
  }
  let pathname: string
  try {
    pathname = decodeURIComponent(new URL(req.url ?? '/', 'http://127.0.0.1').pathname)
  } catch {
    sendJson(res, 400, { error: 'Bad request' })
    return
  }
  if (pathname.includes('\0')) {
    sendJson(res, 400, { error: 'Bad request' })
    return
  }
  const root = path.resolve(uiDir)
  const requested = path.resolve(root, `.${pathname}`)
  if (requested !== root && !requested.startsWith(root + path.sep)) {
    sendJson(res, 403, { error: 'Path outside the UI bundle' })
    return
  }
  let file = requested
  let stat: fs.Stats | null = null
  try {
    stat = fs.statSync(file)
    if (stat.isDirectory()) file = path.join(file, 'index.html')
  } catch {
    stat = null
  }
  if (stat === null || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    // SPA fallback: extension-less paths render the app shell.
    if (path.extname(pathname) !== '') {
      sendJson(res, 404, { error: 'Not found' })
      return
    }
    file = path.join(root, 'index.html')
    if (!fs.existsSync(file)) {
      sendJson(res, 404, { error: 'UI bundle is missing (run build-app).' })
      return
    }
  }
  const type = CONTENT_TYPES[path.extname(file).toLowerCase()] ?? 'application/octet-stream'
  const isShell = path.basename(file) === 'index.html'
  res.writeHead(200, {
    'Content-Type': type,
    'Content-Length': fs.statSync(file).size,
    'Cache-Control': isShell ? 'no-store' : 'public, max-age=3600',
    ...securityHeaders(port),
  })
  if (method === 'HEAD') {
    res.end()
    return
  }
  fs.createReadStream(file).pipe(res)
}

interface ProxyContext {
  mode: ExecutionMode
  upstreams: GatewayUpstreams
  identity: DesktopIdentity
  port: number
  log: (line: string) => void
}

function upstreamFor(target: RouteTarget, ctx: ProxyContext): { base: URL; origin: 'client' | 'upstream' } | null {
  switch (target) {
    case 'harness':
      return { base: new URL(ctx.upstreams.harness), origin: 'client' }
    case 'router':
      // The router's production Origin allowlist contains only :3100 and its own
      // port, so the gateway presents the router's own origin on its behalf.
      return { base: new URL(ctx.upstreams.router), origin: 'upstream' }
    case 'box':
      return { base: new URL(ctx.upstreams.box), origin: 'client' }
    default:
      return null
  }
}

function targetPath(target: RouteTarget, pathname: string): string {
  if (target === 'harness' && pathname.startsWith('/__box')) return hostDesktopPath(pathname)
  return pathname
}

function proxyHeaders(
  req: http.IncomingMessage,
  target: RouteTarget,
  upstream: URL,
  originMode: 'client' | 'upstream',
  ctx: ProxyContext,
): http.OutgoingHttpHeaders {
  const headers: http.OutgoingHttpHeaders = {}
  for (const [key, value] of Object.entries(req.headers)) {
    const lower = key.toLowerCase()
    if (HOP_BY_HOP.has(lower) || lower === 'host' || lower === 'origin' || value === undefined) continue
    headers[key] = value
  }
  headers.host = upstream.host
  if (originMode === 'upstream') headers.origin = upstream.origin
  else if (typeof req.headers.origin === 'string') headers.origin = req.headers.origin
  if (target === 'harness' || target === 'router') headers['x-boxfox-admin'] = '1'
  if (target === 'box') headers['x-boxfox-api-key'] = ctx.identity.adminToken
  return headers
}

function proxyHttp(req: http.IncomingMessage, res: http.ServerResponse, target: RouteTarget, ctx: ProxyContext): void {
  const resolved = upstreamFor(target, ctx)
  if (!resolved) {
    sendJson(res, 501, { error: `${target} is not available in ${ctx.mode} mode` })
    return
  }
  const pathname = new URL(req.url ?? '/', 'http://127.0.0.1').pathname
  const upstreamPath = `${targetPath(target, pathname)}${(req.url ?? '').slice(pathname.length) || ''}`
  const options: http.RequestOptions = {
    protocol: resolved.base.protocol,
    hostname: resolved.base.hostname,
    port: resolved.base.port,
    method: req.method,
    path: upstreamPath,
    headers: proxyHeaders(req, target, resolved.base, resolved.origin, ctx),
  }
  const upstreamReq = http.request(options, (upstreamRes) => {
    const headers: http.OutgoingHttpHeaders = {}
    for (const [key, value] of Object.entries(upstreamRes.headers)) {
      if (HOP_BY_HOP.has(key.toLowerCase()) || value === undefined) continue
      headers[key] = value
    }
    res.writeHead(upstreamRes.statusCode ?? 502, headers)
    upstreamRes.pipe(res)
  })
  upstreamReq.on('error', (error) => {
    ctx.log(`[gateway] upstream ${target} failed: ${error.message}`)
    if (!res.headersSent) sendJson(res, 502, { error: `${target} upstream unavailable` })
    else res.end()
  })
  req.on('aborted', () => upstreamReq.destroy())
  req.pipe(upstreamReq)
}

function handleUpgrade(req: http.IncomingMessage, socket: Duplex, head: Buffer, ctx: ProxyContext): void {
  const host = req.headers.host ?? ''
  const origin = req.headers.origin
  if (!allowedHosts(ctx.port).includes(host)) {
    socket.destroy()
    return
  }
  if (origin !== undefined && !allowedOrigins(ctx.port).includes(origin)) {
    socket.destroy()
    return
  }
  const pathname = new URL(req.url ?? '/', 'http://127.0.0.1').pathname
  const target = routeFor(pathname, ctx.mode)
  const resolved = target ? upstreamFor(target, ctx) : null
  if (!target || !resolved) {
    socket.end('HTTP/1.1 501 Not Implemented\r\nConnection: close\r\n\r\n')
    return
  }
  const upstreamPath = `${targetPath(target, pathname)}${(req.url ?? '').slice(pathname.length) || ''}`
  const upstream = net.connect(Number(resolved.base.port || 80), resolved.base.hostname, () => {
    const headers: string[] = []
    for (const [key, value] of Object.entries(proxyHeaders(req, target, resolved.base, resolved.origin, ctx))) {
      if (Array.isArray(value)) for (const item of value) headers.push(`${key}: ${item}`)
      else if (value !== undefined) headers.push(`${key}: ${value}`)
    }
    upstream.write(`GET ${upstreamPath} HTTP/1.1\r\n${headers.join('\r\n')}\r\n\r\n`)
    if (head.length > 0) upstream.write(head)
    upstream.pipe(socket)
    socket.pipe(upstream)
  })
  upstream.on('error', (error) => {
    ctx.log(`[gateway] websocket upstream ${target} failed: ${error.message}`)
    socket.destroy()
  })
  socket.on('error', () => upstream.destroy())
  socket.on('close', () => upstream.destroy())
}

export function createGateway(options: GatewayOptions): Gateway {
  const port = options.port
  const host = options.host ?? '127.0.0.1'
  const log = options.log ?? (() => undefined)
  const ctx: ProxyContext = {
    mode: options.mode,
    upstreams: options.upstreams,
    identity: options.identity,
    port,
    log,
  }
  const server = http.createServer((req, res) => {
    const hostHeader = req.headers.host ?? ''
    if (!allowedHosts(port).includes(hostHeader)) {
      sendJson(res, 403, { error: 'Host not allowed' })
      return
    }
    const origin = req.headers.origin
    if (origin !== undefined && !allowedOrigins(port).includes(origin)) {
      sendJson(res, 403, { error: 'Origin not allowed' })
      return
    }
    const method = (req.method ?? 'GET').toUpperCase()
    if (method !== 'GET' && method !== 'HEAD' && origin === undefined) {
      sendJson(res, 403, { error: 'Origin required for state-changing requests' })
      return
    }
    let pathname: string
    try {
      pathname = new URL(req.url ?? '/', 'http://127.0.0.1').pathname
    } catch {
      sendJson(res, 400, { error: 'Bad request' })
      return
    }
    const target = routeFor(pathname, options.mode)
    if (target === null) {
      serveStatic(req, res, options.uiDir, port)
      return
    }
    if (target === 'desktop') {
      if (pathname === '/api/desktop/identity') {
        sendJson(res, 200, {
          app: options.identity.app,
          version: options.identity.version,
          mode: options.identity.mode,
          ports: options.identity.ports,
          adminToken: options.identity.adminToken,
        })
        return
      }
      if (pathname === '/api/desktop/health') {
        sendJson(res, 200, { mode: options.identity.mode, services: options.status?.() ?? null })
        return
      }
      sendJson(res, 404, { error: 'Unknown desktop endpoint' })
      return
    }
    if (target === 'unsupported') {
      sendJson(res, 501, { error: `The terminal bridge is not available in ${options.mode} mode` })
      return
    }
    proxyHttp(req, res, target, ctx)
  })
  server.on('upgrade', (req, socket, head) => handleUpgrade(req, socket, head, ctx))
  server.on('clientError', (_error, socket) => {
    socket.end('HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n')
  })
  const url = `http://${host}:${port}`
  return {
    server,
    url,
    listen: () =>
      new Promise((resolve, reject) => {
        server.once('error', reject)
        server.listen(port, host, () => {
          server.removeListener('error', reject)
          log(`[gateway] listening on ${url}`)
          resolve()
        })
      }),
    close: () =>
      new Promise((resolve) => {
        server.closeAllConnections?.()
        server.close(() => resolve())
      }),
  }
}
