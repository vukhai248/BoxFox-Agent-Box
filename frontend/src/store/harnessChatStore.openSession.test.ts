// Đường gửi: phiên mới phải mang theo chỉ dẫn của chủ sở hữu và các núm của harness,
// nhưng chỉ gửi trường nào harness thật sự đặt — thiếu trường là engine tự quyết.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const calls: Array<{ path: string; body: Record<string, unknown> | null; method: string }> = []
let ownerSettings: { instructions: string; revision: number } | null = { instructions: 'Be brief.', revision: 4 }
let duringCatalogLoad: (() => void) | null = null

vi.mock('../lib/agentApi', () => ({
  agentApi: async (path: string, body?: unknown, method?: string) => {
    calls.push({ path, body: (body ?? null) as Record<string, unknown> | null, method: method ?? (body === undefined ? 'GET' : 'POST') })
    if (path === '/owner-settings') {
      if (!ownerSettings) throw new Error('Harness engine unavailable. Start the BoxFox launcher.')
      return ownerSettings
    }
    if (path === '/catalog') { duringCatalogLoad?.(); return { skills: [] } }
    if (path === '/skill-settings') return { enabled: [], revision: 0, initialized: true }
    if (path === '/sessions') return { id: 'sid-open-1', status: 'queued', events: [], config: { contextWindow: 200000, contextWindowSource: 'catalog' } }
    if (path.endsWith('/turns')) return {}
    if (path === '/runtime-info') return {}
    return { id: 'sid-open-1', status: 'running', events: [] }
  },
}))

import { useHarnessChatStore } from './harnessChatStore'
import { useHarnessStore } from './harnessStore'
import { useOwnerSettingsStore } from './ownerSettingsStore'
import { useSessionRecordStore } from './sessionRecordStore'
import { useMachineStore } from './machineStore'

const CHAT = 'chat-open-session'
const pristineHarness = useHarnessStore.getState()
const pristineOwner = useOwnerSettingsStore.getState()
const sessionBody = () => calls.find((call) => call.path === '/sessions')?.body ?? {}

beforeEach(() => {
  calls.length = 0
  duringCatalogLoad = null
  ownerSettings = { instructions: 'Be brief.', revision: 4 }
  useHarnessStore.setState(pristineHarness, true)
  useOwnerSettingsStore.setState(pristineOwner, true)
  useSessionRecordStore.getState().reset()
  useHarnessChatStore.setState({ sessions: {} })
  useMachineStore.setState({ configuration: null, bindings: {}, error: null })
  localStorage.clear()
})

afterEach(() => {
  useHarnessChatStore.setState({ sessions: {} })
  localStorage.clear()
})

const send = async () => useHarnessChatStore.getState().send(CHAT, 'hello', null)
const sendWith = async (selection: Parameters<ReturnType<typeof useHarnessChatStore.getState>['send']>[2]) =>
  useHarnessChatStore.getState().send(CHAT, 'hello', selection)

describe('openSession — đường gửi mang chỉ dẫn', () => {
  it('snapshots the selected environment before asynchronous catalog loading', async () => {
    useMachineStore.setState({configuration: {mode: 'host', revision: 4, projectId: 'project-a', projects: []}})
    duringCatalogLoad = () => useMachineStore.setState({configuration: {mode: 'docker', revision: 5, projectId: null, projects: []}})
    await send()
    expect(sessionBody().machineSelection).toEqual({mode: 'host', projectId: 'project-a'})
  })
  it('uses the project draft binding even if the default environment changes before sending', async () => {
    useMachineStore.getState().bind(CHAT, {mode: 'host', revision: 1, projectId: 'project-b', workspace: 'D:\\projects\\B'})
    useMachineStore.setState({configuration: {mode: 'docker', revision: 7, projectId: null, projects: []}})
    await send()
    expect(sessionBody().machineSelection).toEqual({mode: 'host', projectId: 'project-b'})
  })
  it('uses an explicit Docker draft even if the default is a host project', async () => {
    useMachineStore.getState().bind(CHAT, {mode: 'docker', revision: 1, projectId: null, workspace: '/home/agent/workspace'})
    useMachineStore.setState({configuration: {mode: 'host', revision: 4, projectId: 'project-a', projects: []}})
    await send()
    expect(sessionBody().machineSelection).toEqual({mode: 'docker', projectId: null})
  })
  it('carries the owner directives and the harness id, and books the session', async () => {
    await send()

    expect(sessionBody().instructions).toBe('Be brief.')
    expect(sessionBody().harnessId).toBe('open-model-harness-copy-1')

    const record = useSessionRecordStore.getState().get('sid-open-1')
    expect(record).toMatchObject({ harnessId: 'open-model-harness-copy-1', instructionsChars: 9 })
    expect(record?.directivesSkipped).toBeUndefined()
  })

  it('omits the engine knobs a harness never set', async () => {
    await send()

    expect(sessionBody()).not.toHaveProperty('maxSteps')
    expect(sessionBody()).not.toHaveProperty('deadlineSeconds')
    expect(sessionBody()).not.toHaveProperty('tools')
  })

  it('sends the knobs only when the harness sets them, clamped to the engine range', async () => {
    const id = 'open-model-harness-copy-1'
    useHarnessStore.getState().setHarnessTuning(id, { maxSteps: 999, deadlineSeconds: 12, tools: ['file_read'] })

    await send()

    expect(sessionBody()).toMatchObject({ maxSteps: 60, deadlineSeconds: 12, tools: ['file_read'] })
    // Đường gửi đọc đúng harness đang dùng, không phải bản ghi đầu tiên trong danh sách.
    useHarnessStore.getState().setActiveHarness('open-model-harness')
    calls.length = 0
    await send()
    expect(sessionBody()).not.toHaveProperty('maxSteps')
  })

  it('still opens the session when the directives cannot be read, and says so', async () => {
    ownerSettings = null

    await send()

    expect(calls.some((call) => call.path === '/sessions')).toBe(true)
    expect(sessionBody()).not.toHaveProperty('instructions')
    const record = useSessionRecordStore.getState().get('sid-open-1')
    expect(record?.instructionsChars).toBe(0)
    expect(record?.directivesSkipped).toContain('Harness engine unavailable')
    expect(useOwnerSettingsStore.getState().loadError).toContain('Harness engine unavailable')
  })

  // Vòng 29 — tuyến `{providerId, modelId}`: một phiên ghim cả nhóm connection, router tự chạy
  // luân phiên và tự chuyển khoá khi hết hạn mức. Phiên cũ vẫn gửi cặp `{connectionId, modelId}`.
  it('gửi providerId + modelId và KHÔNG gửi connectionId', async () => {
    await sendWith({ kind: 'provider', providerId: 'opencode', modelId: 'muse-spark-1.3-contributor-free' })

    expect(sessionBody()).toMatchObject({ providerId: 'opencode', modelId: 'muse-spark-1.3-contributor-free' })
    expect(sessionBody()).not.toHaveProperty('connectionId')
  })

  it('chế độ một-model ghi tuyến provider vào model/singleModel', async () => {
    useHarnessStore.setState({ activeType: 'model' })

    await sendWith({ kind: 'provider', providerId: 'opencode', modelId: 'm1' })

    expect(sessionBody()).toMatchObject({ model: 'provider:opencode:m1', singleModel: 'provider:opencode:m1' })
  })

  it('phiên ghim một connection vẫn gửi đúng cặp cũ, không thêm providerId', async () => {
    await sendWith({ kind: 'model', connectionId: 'c1', modelId: 'm1' })

    expect(sessionBody()).toMatchObject({ connectionId: 'c1', modelId: 'm1' })
    expect(sessionBody()).not.toHaveProperty('providerId')
  })

  it('reads the directives once and reuses them for later sessions', async () => {
    await send()
    calls.length = 0
    localStorage.clear()
    useHarnessChatStore.setState({ sessions: {} })
    useSessionRecordStore.getState().reset()

    await send()

    expect(calls.filter((call) => call.path === '/owner-settings')).toHaveLength(0)
    expect(sessionBody().instructions).toBe('Be brief.')
  })
})
