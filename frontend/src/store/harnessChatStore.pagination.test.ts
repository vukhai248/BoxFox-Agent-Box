import { afterEach, beforeEach, expect, it, vi } from 'vitest'
const { api } = vi.hoisted(() => ({ api: vi.fn() }))
vi.mock('../lib/agentApi', () => ({ agentApi: api }))
import { useHarnessChatStore } from './harnessChatStore'
import { useMachineStore } from './machineStore'

beforeEach(() => {
  api.mockReset()
  useHarnessChatStore.setState({ sessions: { chat: { id: 'sid', status: 'idle', events: [], error: null } }, decisions: {}, intentSeq: {} })
})
afterEach(() => {
  useHarnessChatStore.setState({ sessions: {}, decisions: {}, intentSeq: {} })
  useMachineStore.setState({ bindings: {} })
})

it('hydrates the final child/assistant before adopting completed status and retains them after a second refresh', async () => {
  const first = Array.from({ length: 500 }, (_, i) => ({ seq: i + 1, type: 'usage', data: {}, created: i + 1 }))
  api.mockResolvedValueOnce({ id: 'sid', status: 'completed', events: first, hasMore: true, nextAfter: 500 })
    .mockResolvedValueOnce({ id: 'sid', status: 'completed', events: [
      { seq: 501, type: 'child', data: { sessionId: 'child', status: 'completed' }, created: 501 },
      { seq: 502, type: 'assistant', data: { text: 'Final result', thought: 'Final reasoning' }, created: 502 },
    ], hasMore: false, nextAfter: 502 })
  await useHarnessChatStore.getState().refresh('chat')
  const result = useHarnessChatStore.getState().sessions.chat
  expect(result.status).toBe('completed')
  expect(result.events).toHaveLength(502)
  expect(result.events.at(-1)?.data.thought).toBe('Final reasoning')
  api.mockResolvedValueOnce({ id: 'sid', status: 'completed', events: [] })
  await useHarnessChatStore.getState().refresh('chat')
  expect(api.mock.calls.at(-1)?.[0]).toBe('/sessions/sid?after=502')
  expect(useHarnessChatStore.getState().sessions.chat.events).toHaveLength(502)
})

it.each([false, true])('ignores a stale refresh after the second turn has been hydrated (older request fails: %s)', async fails => {
  let resolveOld!: (page: unknown) => void
  let rejectOld!: (error: Error) => void
  api.mockImplementationOnce(() => new Promise((resolve, reject) => { resolveOld = resolve; rejectOld = reject }))
  const oldRefresh = useHarnessChatStore.getState().refresh('chat')
  api.mockResolvedValueOnce({ id: 'sid', status: 'running', events: [
    { seq: 501, type: 'user', data: { text: 'Second turn', turn: 2 }, created: 501 },
    { seq: 502, type: 'assistant', data: { text: 'Second result', thought: 'Second reasoning' }, created: 502 },
  ], hasMore: false, nextAfter: 502 })
  await useHarnessChatStore.getState().refresh('chat')
  if (fails) rejectOld(new Error('Late connection failure'))
  else resolveOld({ id: 'sid', status: 'completed', events: [
    { seq: 1, type: 'assistant', data: { text: 'First result' }, created: 1 },
  ], hasMore: false, nextAfter: 1 })
  await oldRefresh
  const session = useHarnessChatStore.getState().sessions.chat
  expect(session.status).toBe('running')
  expect(session.error).toBeNull()
  expect(session.events.at(-1)?.data.thought).toBe('Second reasoning')
})

it('does not let a pending poll replace the starting state of a newly submitted second turn', async () => {
  let resolveOld!: (page: unknown) => void
  let resolveTurn!: (result: unknown) => void
  api.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
    .mockImplementationOnce(() => new Promise(resolve => { resolveTurn = resolve }))
  const oldRefresh = useHarnessChatStore.getState().refresh('chat')
  const send = useHarnessChatStore.getState().send('chat', 'Second turn', null)
  expect(useHarnessChatStore.getState().sessions.chat.status).toBe('starting')
  resolveOld({ id: 'sid', status: 'completed', events: [], hasMore: false, nextAfter: 0 })
  await oldRefresh
  expect(useHarnessChatStore.getState().sessions.chat.status).toBe('starting')
  api.mockResolvedValueOnce({ id: 'sid', status: 'running', events: [
    { seq: 1, type: 'user', data: { text: 'Second turn', turn: 2 }, created: 1 },
  ], hasMore: false, nextAfter: 1 })
  resolveTurn({ status: 'running' })
  await send
  expect(useHarnessChatStore.getState().sessions.chat.status).toBe('running')
})

it('does not starve slow history hydration when another periodic poll is already pending', async () => {
  let resolveFirst!: (page: unknown) => void
  let resolveSecond!: (page: unknown) => void
  api.mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
    .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
  const first = useHarnessChatStore.getState().refresh('chat')
  const second = useHarnessChatStore.getState().refresh('chat')
  resolveFirst({ id: 'sid', status: 'running', events: [
    { seq: 1, type: 'assistant', data: { text: 'History result', thought: 'History reasoning' }, created: 1 },
  ], hasMore: false, nextAfter: 1 })
  await first
  expect(useHarnessChatStore.getState().sessions.chat.events.at(-1)?.data.thought).toBe('History reasoning')
  resolveSecond({ id: 'sid', status: 'completed', events: [], hasMore: false, nextAfter: 0 })
  await second
  expect(useHarnessChatStore.getState().sessions.chat.status).toBe('running')
  expect(useHarnessChatStore.getState().sessions.chat.events).toHaveLength(1)
})
