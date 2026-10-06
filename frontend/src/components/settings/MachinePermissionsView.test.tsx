/**
 * Test cho tab Settings → Machines → Machine & Permissions.
 *
 * Bốn hợp đồng phải giữ: (1) host mode với lease ở tay người phải hiện cảnh báo rõ;
 * (2) "Trả quyền cho agent" gọi đúng `POST /api/agent/desktop/lease` với `{action:'claim'}`;
 * (3) chế độ docker hiện thông báo đọc được thay vì vỡ (không gọi route quyền nào);
 * (4) `PUT` đổi chế độ quyền và `DELETE` thu hồi luật gửi đúng body.
 *
 * Theo mẫu `SearchProviderPanel.test.tsx`: dựng bằng `createRoot` + `act`, không thêm
 * thư viện test mới; `fetch` được thay bằng một stub có trạng thái để lần GET sau thao
 * tác thấy đúng kết quả của chính thao tác đó.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MachinePermissionsView } from './MachinePermissionsView'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

interface Call {
  path: string
  method: string
  body: Record<string, unknown> | null
}

const json = (payload: unknown, status = 200) =>
  new Response(JSON.stringify(payload), { status, headers: { 'content-type': 'application/json' } })

const HOST_EXECUTION = {
  mode: 'host',
  modeDefault: 'docker',
  modes: ['docker', 'host'],
  configured: 'host',
  scope: 'machine',
  permissionMode: 'ask',
  policy: true,
  cuaEnabled: true,
  lease: null,
  hardlineHits: 2,
  workspace: 'C:\\work',
}

const DOCKER_EXECUTION = {
  mode: 'docker',
  modeDefault: 'docker',
  modes: ['docker', 'host'],
  configured: 'docker',
  scope: null,
  permissionMode: null,
  policy: false,
  cuaEnabled: null,
  lease: null,
  hardlineHits: 0,
  workspace: null,
}

const LAYERS = [
  { layer: 'managed', file: 'C:\\BoxFox\\managed-settings.json', present: false, error: '' },
  { layer: 'profile', file: 'C:\\profile\\permissions.json', present: false, error: '' },
  { layer: 'user', file: 'C:\\Users\\me\\.boxfox\\settings.json', present: true, error: '' },
  { layer: 'project', file: 'C:\\work\\.boxfox\\settings.local.json', present: true, error: '' },
]

const RULE = 'terminal_exec(npm run build)'

function snapshot(mode = 'ask', scope = 'machine') {
  const capabilities =
    mode === 'trusted'
      ? { read: true, write: 'allow', exec: 'allow', cua: 'allow' }
      : mode === 'plan'
        ? { read: true, write: false, exec: false, cua: false }
        : { read: true, write: 'ask', exec: 'ask', cua: 'ask' }
  return {
    mode,
    modeDefault: 'ask',
    modes: ['plan', 'ask', 'auto', 'trusted'],
    capabilities,
    scope,
    scopeDefault: 'machine',
    scopes: ['workspace', 'machine'],
    workspace: 'C:\\work',
    layers: LAYERS,
    rules: { deny: [], ask: [], allow: [RULE] },
    ruleSources: { deny: [], ask: [], allow: [{ rule: RULE, layer: 'project', file: LAYERS[3].file }] },
    hardlineCount: 10,
    hardlineHits: 2,
    denialBreakerLimit: 3,
    auditFile: 'C:\\profile\\permissions-audit.jsonl',
    sessionRuleCount: 0,
  }
}

const LEASE_HUMAN = {
  holder: 'human',
  epoch: 7,
  generation: 3,
  hooksInstalled: true,
  mutexHeld: false,
  mutexName: 'Local\\BoxFoxDesktopInput-v1',
  since: '2026-10-06T10:00:00Z',
  reason: 'người dùng lấy lại quyền',
}

const PENDING = [
  {
    id: 'req-1',
    tool: 'terminal_exec',
    args: { command: 'npm run build' },
    reason: 'lệnh ghi ngoài workspace',
    sessionId: 'sess-9',
    createdAt: '2026-10-06T10:05:00Z',
  },
]

interface StubOptions {
  execution?: unknown
  /** PUT /permissions trả lỗi có mã thay vì snapshot. */
  failPut?: { status: number; code: string; message: string }
}

/** Stub có trạng thái: lần GET sau mỗi thao tác thấy đúng kết quả của thao tác đó. */
function serverStub(options: StubOptions = {}) {
  const calls: Call[] = []
  const state = {
    snapshot: snapshot(),
    rules: { rules: { deny: [], ask: [], allow: [RULE] }, sources: { deny: [], ask: [], allow: [{ rule: RULE, layer: 'project', file: LAYERS[3].file }] }, layers: LAYERS },
    lease: { ...LEASE_HUMAN },
    pending: PENDING.map((item) => ({ ...item })),
  }

  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const path = String(url)
    const method = init.method ?? 'GET'
    const body = init.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null
    calls.push({ path, method, body })

    if (path.endsWith('/api/agent/health')) {
      return json({ execution: options.execution ?? HOST_EXECUTION })
    }
    if (path.endsWith('/permissions/rules') && method === 'DELETE') {
      const rule = String(body?.rule)
      state.rules = {
        ...state.rules,
        rules: { ...state.rules.rules, allow: state.rules.rules.allow.filter((value) => value !== rule) },
        sources: { ...state.rules.sources, allow: state.rules.sources.allow.filter((value) => value.rule !== rule) },
      }
      return json({ ok: true, message: 'đã xoá 1 mục' })
    }
    if (path.endsWith('/permissions/rules')) return json(state.rules)
    if (path.endsWith('/permissions/pending')) return json({ pending: state.pending })
    if (path.endsWith('/permissions/decide')) {
      state.pending = state.pending.filter((item) => item.tool !== body?.tool)
      return json({
        tool: body?.tool,
        sessionId: body?.sessionId ?? null,
        outcome: body?.decision === 'deny' ? 'deny' : 'allow',
        reason: 'quyết định từ thẻ duyệt',
        rule: '',
        layer: 'user',
        decision: body?.decision,
      })
    }
    if (path.endsWith('/api/agent/permissions') && method === 'PUT') {
      if (options.failPut) {
        return json({ code: options.failPut.code, error: options.failPut.message }, options.failPut.status)
      }
      state.snapshot = {
        ...state.snapshot,
        ...(body?.mode ? { mode: String(body.mode), capabilities: snapshot(String(body.mode), String(body?.scope ?? state.snapshot.scope)).capabilities } : {}),
        ...(body?.scope ? { scope: String(body.scope) } : {}),
      }
      return json(state.snapshot)
    }
    if (path.endsWith('/api/agent/permissions')) return json(state.snapshot)
    if (path.endsWith('/api/agent/desktop/lease') && method === 'POST') {
      state.lease =
        body?.action === 'claim'
          ? { ...state.lease, holder: 'agent', epoch: state.lease.epoch + 1, reason: 'người dùng trả quyền cho agent' }
          : { ...state.lease, holder: 'human', epoch: state.lease.epoch + 1 }
      return json(state.lease)
    }
    if (path.endsWith('/api/agent/desktop/lease')) return json(state.lease)
    return json({})
  })
  vi.stubGlobal('fetch', fetchMock)
  return calls
}

let root: Root
let host: HTMLDivElement

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const settle = async (times = 3) => {
  for (let index = 0; index < times; index += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })
  }
}

async function render() {
  await act(async () => {
    root.render(<MachinePermissionsView />)
  })
  await settle()
}

async function click(element: HTMLElement) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
  await settle()
}

function selectValue(select: HTMLSelectElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
  setter.call(select, value)
  select.dispatchEvent(new Event('change', { bubbles: true }))
}

const testid = (id: string) => host.querySelector<HTMLElement>(`[data-testid="${id}"]`)
const buttonIn = (scope: HTMLElement, text: string) =>
  [...scope.querySelectorAll<HTMLButtonElement>('button')].find((button) => button.textContent?.trim() === text)

describe('MachinePermissionsView', () => {
  it('host mode, lease ở tay người: hiện cảnh báo rõ và trạng thái lease', async () => {
    serverStub()
    await render()

    expect(testid('mp-execution-mode')?.textContent).toBe('host')
    expect(testid('mp-execution-configured')?.textContent).toBe('host')
    expect(testid('mp-execution-default')?.textContent).toBe('docker')
    expect(testid('mp-lease-holder')?.textContent).toBe('Bạn đang điều khiển')

    const warning = testid('mp-human-warning')
    expect(warning).not.toBeNull()
    expect(warning?.textContent).toContain('Bạn đang giữ quyền điều khiển desktop')
    expect(warning?.textContent).toContain('agent không chụp được màn hình')
    // Thẻ duyệt đang chờ ⇒ cảnh báo nói rõ agent đang chờ.
    expect(warning?.textContent).toContain('Agent đang chờ 1 thẻ duyệt')

    expect(host.textContent).toContain('epoch 7')
    expect(host.textContent).toContain('generation 3')
    expect(host.textContent).toContain('đã cài')
  })

  it('bấm "Trả quyền cho agent" gọi POST /api/agent/desktop/lease với {action:"claim"}', async () => {
    const calls = serverStub()
    await render()

    await click(testid('mp-claim')!)

    expect(calls).toContainEqual({
      path: '/api/agent/desktop/lease',
      method: 'POST',
      body: { action: 'claim' },
    })
    // GET lại sau thao tác: băng lease đổi theo, cảnh báo biến mất.
    expect(testid('mp-lease-holder')?.textContent).toBe('Agent đang điều khiển')
    expect(testid('mp-human-warning')).toBeNull()
  })

  it('chế độ docker: hiện thông báo đọc được, không gọi route quyền nào', async () => {
    const calls = serverStub({ execution: DOCKER_EXECUTION })
    await render()

    expect(testid('mp-execution-mode')?.textContent).toBe('docker')
    const notice = testid('mp-unavailable')
    expect(notice).not.toBeNull()
    expect(notice?.textContent).toContain('chỉ có ở host mode')
    expect(testid('mp-error')).toBeNull()
    expect(calls.some((call) => call.path.includes('/permissions'))).toBe(false)
    expect(calls.some((call) => call.path.includes('/desktop/lease'))).toBe(false)
  })

  it('đổi chế độ quyền: PUT đúng body và bảng năng lực đổi theo', async () => {
    const calls = serverStub()
    await render()

    await act(async () => {
      selectValue(testid('mp-mode') as HTMLSelectElement, 'trusted')
    })
    await settle()

    expect(calls).toContainEqual({
      path: '/api/agent/permissions',
      method: 'PUT',
      body: { mode: 'trusted', layer: 'user' },
    })
    expect(testid('mp-capability-cua')?.textContent).toBe('Cho phép')
  })

  it('PUT lỗi: hiện mã lỗi thay vì vỡ', async () => {
    serverStub({ failPut: { status: 409, code: 'PERMISSION_WRITE_FAILED', message: 'không ghi được tệp luật' } })
    await render()

    await act(async () => {
      selectValue(testid('mp-mode') as HTMLSelectElement, 'auto')
    })
    await settle()

    expect(testid('mp-error')?.textContent).toContain('PERMISSION_WRITE_FAILED')
  })

  it('thu hồi luật: hỏi xác nhận rồi DELETE đúng {rule, layer}', async () => {
    const calls = serverStub()
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    await render()

    const row = host.querySelector<HTMLElement>(`[data-rule="${RULE}"]`)
    expect(row).not.toBeNull()
    expect(row?.textContent).toContain('tầng project')
    expect(row?.textContent).toContain('settings.local.json')

    await click(buttonIn(row!, 'Thu hồi')!)

    expect(confirmSpy).toHaveBeenCalled()
    expect(calls).toContainEqual({
      path: '/api/agent/permissions/rules',
      method: 'DELETE',
      body: { rule: RULE, layer: 'project' },
    })
    expect(host.querySelector(`[data-rule="${RULE}"]`)).toBeNull()
  })

  it('huỷ xác nhận thì không gọi DELETE', async () => {
    const calls = serverStub()
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    await render()

    const row = host.querySelector<HTMLElement>(`[data-rule="${RULE}"]`)!
    await click(buttonIn(row, 'Thu hồi')!)

    expect(calls.some((call) => call.method === 'DELETE')).toBe(false)
    expect(host.querySelector(`[data-rule="${RULE}"]`)).not.toBeNull()
  })

  it('thẻ duyệt: "Luôn cho phép" gửi decide với decision allow_always', async () => {
    const calls = serverStub()
    await render()

    const card = host.querySelector<HTMLElement>('[data-testid="mp-pending"] article')!
    expect(card.textContent).toContain('terminal_exec')
    expect(card.textContent).toContain('npm run build')

    await click(buttonIn(card, 'Luôn cho phép')!)

    expect(calls).toContainEqual({
      path: '/api/agent/permissions/decide',
      method: 'POST',
      body: {
        tool: 'terminal_exec',
        args: { command: 'npm run build' },
        sessionId: 'sess-9',
        decision: 'allow_always',
        actor: 'user',
      },
    })
  })

  it('Dừng khẩn gọi POST với {action:"stop"}', async () => {
    const calls = serverStub()
    await render()

    await click(testid('mp-stop')!)

    expect(calls).toContainEqual({
      path: '/api/agent/desktop/lease',
      method: 'POST',
      body: { action: 'stop' },
    })
  })
})
