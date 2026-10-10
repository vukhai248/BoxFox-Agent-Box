/**
 * Nút chọn quyền ở thanh chat. Bài kiểm tra chạy qua `agentApi` GIẢ nên nó kiểm luôn hợp đồng
 * `GET/PUT /api/agent/permissions` của `lib/permissions/http.ts`, không chỉ phần hiển thị.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { PermissionModePicker } from './PermissionModePicker'
import { useAgentStore } from '../../store/agentStore'
import { useMachineStore, type MachineBinding, type MachineConfiguration } from '../../store/machineStore'

const { api } = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('../../lib/agentApi', () => ({ agentApi: api }))
;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const HOST_BINDING: MachineBinding = { mode: 'host', revision: 1, projectId: 'a', workspace: 'D:\\projects\\App A' }
const DOCKER_BINDING_LOCAL: MachineBinding = { mode: 'docker', revision: 1, projectId: null, workspace: null }

let root: Root
let host: HTMLDivElement
let snapshot: Record<string, unknown>
let putError: Error | null
let puts: Array<Record<string, unknown>>
const originalMachine = useMachineStore.getState()
const originalAgent = useAgentStore.getState()

function permissionSnapshot(overrides: Record<string, unknown> = {}) {
  return {
    mode: 'ask', modeDefault: 'ask', modes: ['ask', 'auto', 'trusted'],
    capabilities: { read: true, write: 'ask', exec: 'ask', cua: 'ask' },
    scope: 'workspace', scopeDefault: 'machine', scopes: ['workspace', 'machine'],
    network: 'restricted', networkDefault: 'restricted', networks: ['restricted', 'enabled'],
    workspace: 'D:\\projects\\App A', layers: [], rules: { deny: [], ask: [], allow: [] },
    ruleSources: {}, hardlineCount: 12, hardlineHits: 0, denialBreakerLimit: 3,
    auditFile: '', sessionRuleCount: 0,
    ...overrides,
  }
}

async function render() {
  await act(async () => {
    root.render(
      <I18nProvider>
        <PermissionModePicker />
      </I18nProvider>,
    )
  })
  await act(async () => {})
}

function chip(): HTMLButtonElement | null {
  return host.querySelector<HTMLButtonElement>('[data-testid="composer-permission"]')
}

function menuItem(text: string): HTMLButtonElement | undefined {
  return [...host.querySelectorAll<HTMLButtonElement>('[role="menuitemradio"]')]
    .find((button) => button.textContent?.includes(text))
}

beforeEach(() => {
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
  snapshot = permissionSnapshot()
  putError = null
  puts = []
  useAgentStore.setState({ activeSessionId: 's1' })
  useMachineStore.setState({
    ...originalMachine,
    configuration: { revision: 1, mode: 'host', projectId: 'a', projects: [] } as MachineConfiguration,
    bindings: { s1: HOST_BINDING },
    error: null,
  })
  api.mockReset()
  api.mockImplementation(async (path: string, body?: Record<string, unknown>, method?: string) => {
    if (path !== '/permissions') throw new Error(`unexpected path ${path}`)
    if (method === 'PUT') {
      if (putError) throw putError
      puts.push(body ?? {})
      snapshot = permissionSnapshot({ ...snapshot, ...(body ?? {}),
        scope: (body?.mode ?? snapshot.mode) === 'trusted' ? 'machine' : 'workspace' })
    }
    return snapshot
  })
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  useMachineStore.setState(originalMachine, true)
  useAgentStore.setState(originalAgent, true)
  vi.restoreAllMocks()
})

describe('PermissionModePicker', () => {
  it('không hiện ở chế độ docker — máy này không có động cơ quyền', async () => {
    useMachineStore.setState({ bindings: { s1: DOCKER_BINDING_LOCAL } })
    await render()
    expect(chip()).toBeNull()
    expect(api).not.toHaveBeenCalled()
  })

  it('hiện mức hiện hành của máy và đọc từ /permissions', async () => {
    await render()
    expect(api).toHaveBeenCalledWith('/permissions')
    expect(chip()?.dataset.permissionMode).toBe('ask')
    expect(chip()?.textContent).toContain('Request approval')
  })

  it('đổi mức cho phép thì ghi xuống tầng `user` và cập nhật nhãn', async () => {
    await render()
    await act(async () => chip()?.click())
    await act(async () => menuItem('Auto')?.click())
    expect(puts).toEqual([{ mode: 'auto', layer: 'user' }])
    expect(chip()?.dataset.permissionMode).toBe('auto')
    expect(chip()?.textContent).toContain('Auto')
  })

  it('Full access derives whole-machine scope without a separate chooser', async () => {
    await render()
    await act(async () => chip()?.click())
    expect(menuItem('Whole machine')).toBeUndefined()
    await act(async () => menuItem('Full access')?.click())
    expect(puts).toEqual([{ mode: 'trusted', layer: 'user' }])
    expect(chip()?.dataset.permissionScope).toBe('machine')
    expect(chip()?.title).toContain('Whole machine')
  })

  // Trục mạng là câu hỏi thứ ba trong menu. Nó phải ghi được xuống máy chủ và hiện lại trên
  // chip, nếu không người dùng không biết mình vừa tắt tiếng hỏi của các lệnh ra mạng.
  it('đổi mức mạng và ghi xuống tầng `user`', async () => {
    await render()
    expect(chip()?.dataset.permissionNetwork).toBe('restricted')
    await act(async () => chip()?.click())
    await act(async () => menuItem('Allow network access')?.click())
    expect(puts).toEqual([{ network: 'enabled', layer: 'user' }])
    expect(chip()?.dataset.permissionNetwork).toBe('enabled')
  })

  it('offers exactly three levels, no Scope section and unchanged Internet choices', async () => {
    await render()
    await act(async () => chip()?.click())
    expect(host.querySelectorAll('[role="menuitemradio"]')).toHaveLength(5)
    for (const label of ['Request approval', 'Auto approve', 'Full access', 'Ask before network access', 'Allow network access']) {
      expect(menuItem(label)).toBeDefined()
    }
    expect(host.querySelector('[data-testid="composer-permission-scope"]')).toBeNull()
    expect(menuItem('Read only')).toBeUndefined()
  })

  it('ghi lỗi thì giữ nguyên mức cũ và nói ra cho người dùng', async () => {
    putError = new Error('PERMISSION_LAYER_UNKNOWN: tầng `user` không tồn tại')
    await render()
    await act(async () => chip()?.click())
    await act(async () => menuItem('Full access')?.click())
    expect(chip()?.dataset.permissionMode).toBe('ask')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('PERMISSION_LAYER_UNKNOWN')
  })

  // Đường ĐỌC: máy đã bật mạng từ trước thì chip phải nói đúng ngay lần vẽ đầu, không chỉ sau khi
  // người dùng vừa bấm đổi.
  it('đọc mức mạng đã lưu ngay từ lần vẽ đầu', async () => {
    snapshot = permissionSnapshot({ network: 'enabled' })
    await render()
    expect(chip()?.dataset.permissionNetwork).toBe('enabled')
    await act(async () => chip()?.click())
    expect(menuItem('Allow network access')?.getAttribute('aria-checked')).toBe('true')
  })

  // Máy chủ không trả `network` trong phản hồi PUT (bản cũ, hoặc route bỏ sót trường): chip phải
  // giữ đúng giá trị vừa chọn, không được hiện 'unknown'.
  it('phản hồi PUT thiếu `network` thì giữ giá trị vừa chọn', async () => {
    api.mockImplementation(async (path: string, body?: Record<string, unknown>, method?: string) => {
      if (path !== '/permissions') throw new Error(`unexpected path ${path}`)
      if (method === 'PUT') {
        const response: Record<string, unknown> = { ...permissionSnapshot({ ...snapshot, ...(body ?? {}) }) }
        delete response.network
        snapshot = response
        return snapshot
      }
      return snapshot
    })
    await render()
    await act(async () => chip()?.click())
    await act(async () => menuItem('Allow network access')?.click())
    expect(chip()?.dataset.permissionNetwork).toBe('enabled')
    expect(host.querySelector('[role="alert"]')).toBeNull()
  })

  it('lỗi khi đổi mạng thì trả mức mạng về giá trị cũ', async () => {
    putError = new Error('PERMISSION_NETWORK_UNKNOWN: giá trị mạng không hợp lệ')
    await render()
    await act(async () => chip()?.click())
    await act(async () => menuItem('Allow network access')?.click())
    expect(chip()?.dataset.permissionNetwork).toBe('restricted')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('PERMISSION_NETWORK_UNKNOWN')
  })
})
