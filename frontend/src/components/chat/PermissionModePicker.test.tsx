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
    mode: 'ask', modeDefault: 'ask', modes: ['plan', 'ask', 'auto', 'trusted'],
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
      snapshot = permissionSnapshot({ ...snapshot, ...(body ?? {}) })
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
    expect(chip()?.textContent).toContain('Ask first')
  })

  it('đổi mức cho phép thì ghi xuống tầng `user` và cập nhật nhãn', async () => {
    await render()
    await act(async () => chip()?.click())
    await act(async () => menuItem('Auto')?.click())
    expect(puts).toEqual([{ mode: 'auto', layer: 'user' }])
    expect(chip()?.dataset.permissionMode).toBe('auto')
    expect(chip()?.textContent).toContain('Auto')
  })

  it('đổi phạm vi sang cả máy', async () => {
    await render()
    await act(async () => chip()?.click())
    await act(async () => menuItem('Whole machine')?.click())
    expect(puts).toEqual([{ scope: 'machine', layer: 'user' }])
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

  // Phạm vi `machine` chỉ bỏ câu hỏi ngoài folder, KHÔNG nới chỗ công cụ tệp được chạm tới.
  // Dòng gợi ý phải nói đúng như vậy, nếu không người dùng tưởng đã mở khoá cả ổ đĩa.
  it('gợi ý phạm vi nói rõ công cụ tệp vẫn ở trong folder', async () => {
    await render()
    await act(async () => chip()?.click())
    const hint = () => host.querySelector('[data-testid="composer-permission-scope"]')?.textContent ?? ''
    expect(hint()).toContain('File tools stay inside it')
    // Đổi phạm vi thì menu đóng lại (giá trị đã lưu) — mở lại để đọc câu của mức mới.
    await act(async () => menuItem('Whole machine')?.click())
    await act(async () => chip()?.click())
    expect(hint()).toContain('Do not ask')
    expect(hint()).toContain('File tools stay inside it')
  })

  it('ghi lỗi thì giữ nguyên mức cũ và nói ra cho người dùng', async () => {
    putError = new Error('PERMISSION_LAYER_UNKNOWN: tầng `user` không tồn tại')
    await render()
    await act(async () => chip()?.click())
    await act(async () => menuItem('Trusted')?.click())
    expect(chip()?.dataset.permissionMode).toBe('ask')
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('PERMISSION_LAYER_UNKNOWN')
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
