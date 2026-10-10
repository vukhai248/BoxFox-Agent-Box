/**
 * Bản ghi của sub-agent không được nhân đôi văn bản.
 *
 * Lỗi người dùng gặp: khung "Sub-agent" in lại toàn bộ câu trả lời một lần cho mỗi
 * token, vì harness cũ phát `assistant_delta`/`thought` dạng TÍCH LUỸ còn panel chỉ
 * biết cộng chuỗi (`output += text`). Bản sửa: panel ghép theo tiền tố
 * (`lib/streamText.appendStreamText`), nên đúng cho cả event tích luỹ lẫn mảnh rời.
 *
 * Kiểm kèm: `tool_end` phải khớp đúng tool call đã mở. Harness phát khoá `id`,
 * không phải `tool_call_id`; trước đây panel đọc sai khoá nên kết quả công cụ
 * không bao giờ gắn vào dòng của nó và mọi dòng đứng ở trạng thái "đang chạy".
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useAgentStore } from '../../store/agentStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useUiStore } from '../../store/uiStore'
import { SubagentInspectorPanel, buildSubagentTimeline } from './SubagentInspectorPanel'
import type { HarnessEvent } from '../../store/harnessChatStore'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const CHAT_ID = 'chat-subagents-stream'
const CHILD_ID = 'child-stream'

let roots: Root[] = []
const fetchMock = vi.fn()

function child(seq: number, sessionId: string) {
  return {
    seq,
    type: 'child',
    data: { sessionId, role: 'Research', status: 'started', goal: 'việc của research' },
    created: seq,
  }
}

/** Event do harness phát: `text` là văn bản TÍCH LUỸ (hành vi cũ vẫn còn trong DB). */
function cumulativeEvents() {
  return [
    { seq: 1, type: 'assistant_delta', data: { text: 'Kế hoạch chi' }, created: 1 },
    { seq: 2, type: 'assistant_delta', data: { text: 'Kế hoạch chi tiết cho' }, created: 2 },
    { seq: 3, type: 'assistant_delta', data: { text: 'Kế hoạch chi tiết cho Medical Record Retrieval Agent' }, created: 3 },
  ]
}

async function renderWith(events: unknown[], fetcher?: (url: string) => Promise<unknown>): Promise<HTMLElement> {
  fetchMock.mockImplementation(fetcher ?? (async () => ({ ok: true, status: 200, json: async () => ({ events }) })))
  useHarnessChatStore.setState({
    sessions: {
      [CHAT_ID]: { id: 'sess-1', status: 'running', events: [child(1, CHILD_ID)], error: null },
    },
  })
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(
      <I18nProvider>
        <SubagentInspectorPanel />
      </I18nProvider>,
    )
  })
  await act(async () => {
    await Promise.resolve()
  })
  return host
}

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', fetchMock)
  fetchMock.mockReset()
  useAgentStore.setState({ activeSessionId: CHAT_ID })
  useUiStore.setState({ tabIntentTargets: {}, openTabs: ['subagents'], activeTab: 'subagents' })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  useHarnessChatStore.setState({ sessions: {} })
  vi.unstubAllGlobals()
})

describe('SubagentInspectorPanel — văn bản streaming', () => {
  it('reads every page of completed output, including final reasoning beyond event 500', async () => {
    const first = Array.from({ length: 500 }, (_, index) => ({ seq: index + 1, type: 'usage', data: {}, created: index + 1 }))
    const host = await renderWith([], async url => ({ ok: true, status: 200, json: async () => url.includes('after=500')
      ? { events: [{ seq: 501, type: 'assistant', data: { text: 'Complete result', thought: 'Final reasoning', final: true }, created: 501 }], hasMore: false, nextAfter: 501 }
      : { events: first, hasMore: true, nextAfter: 500 } }))
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(host.textContent).toContain('Complete result')
    const toggle = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('Thinking'))!
    act(() => toggle.click())
    expect(host.textContent).toContain('Final reasoning')
  })

  it('keeps expanded reasoning when the child finishes and main receives a second user turn', async () => {
    const host = await renderWith([{ seq: 10, type: 'thought', data: { text: 'Draft reasoning' }, created: 10 }])
    const toggle = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('Thinking'))!
    act(() => toggle.click())
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    fetchMock.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({ events: [
      { seq: 11, type: 'assistant', data: { text: 'Final result', thought: 'Canonical reasoning', final: true }, created: 11 },
    ] }) }))
    const updates = [child(1, CHILD_ID), { ...child(2, CHILD_ID), data: { sessionId: CHILD_ID, role: 'Research', status: 'completed' } }]
    await act(async () => {
      useHarnessChatStore.setState({ sessions: { [CHAT_ID]: { id: 'sess-1', status: 'running', events: updates, error: null } } })
      await Promise.resolve()
    })
    expect(host.textContent).toContain('Canonical reasoning')
    expect(toggle.isConnected).toBe(true)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    await act(async () => {
      useHarnessChatStore.setState({ sessions: { [CHAT_ID]: { id: 'sess-1', status: 'running', events: [...updates,
        { seq: 3, type: 'user', data: { text: 'Continue', turn: 2 }, created: 3 }], error: null } } })
      await Promise.resolve()
    })
    expect(host.textContent).toContain('Canonical reasoning')
    expect(host.textContent).toContain('Final result')
    expect(toggle.isConnected).toBe(true)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
  })

  it('refreshes a reused child when a second completion arrives with unchanged completed status', async () => {
    const host = await renderWith([{ seq: 10, type: 'assistant', data: { text: 'First result', thought: 'First reasoning' }, created: 10 }])
    const completed = (seq: number) => ({ ...child(seq, CHILD_ID), data: { sessionId: CHILD_ID, role: 'Research', status: 'completed' } })
    await act(async () => {
      useHarnessChatStore.setState({ sessions: { [CHAT_ID]: { id: 'sess-1', status: 'running', events: [completed(2)], error: null } } })
      await Promise.resolve()
    })
    fetchMock.mockClear()
    fetchMock.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({ events: [
      { seq: 11, type: 'step', data: {}, created: 11 },
      { seq: 12, type: 'assistant', data: { text: 'Second result', thought: 'Second reasoning' }, created: 12 },
    ] }) }))
    await act(async () => {
      useHarnessChatStore.setState({ sessions: { [CHAT_ID]: { id: 'sess-1', status: 'running', events: [completed(2), completed(3)], error: null } } })
      await Promise.resolve()
    })
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0][0]).toContain('after=10')
    expect(host.textContent).toContain('Second result')
    const toggles = [...host.querySelectorAll('button')].filter(button => button.textContent?.includes('Thinking'))
    act(() => toggles.at(-1)?.click())
    expect(host.textContent).toContain('Second reasoning')
  })

  it('reports fetch failures instead of claiming no synthesis was returned', async () => {
    const host = await renderWith([], async () => ({ ok: false, status: 503, json: async () => ({ error: 'Unavailable' }) }))
    expect(host.querySelector('[role="alert"]')?.textContent).toContain('Unable to load complete sub-agent history')
    expect(host.textContent).not.toContain('No synthesis text returned')
  })

  it('ignores a late response from the previously selected child', async () => {
    let resolveOld!: (response: unknown) => void
    const host = await renderWith([], async url => url.includes('second-child')
      ? { ok: true, status: 200, json: async () => ({ events: [{ seq: 20, type: 'assistant', data: { text: 'Second child result' }, created: 20 }] }) }
      : new Promise(resolve => { resolveOld = resolve }))
    await act(async () => {
      useHarnessChatStore.setState({ sessions: { [CHAT_ID]: { id: 'sess-1', status: 'running', events: [child(2, 'second-child')], error: null } } })
      await Promise.resolve()
    })
    expect(host.textContent).toContain('Second child result')
    await act(async () => {
      resolveOld({ ok: true, status: 200, json: async () => ({ events: [{ seq: 10, type: 'assistant', data: { text: 'Old child result' }, created: 10 }] }) })
      await Promise.resolve()
    })
    expect(host.textContent).toContain('Second child result')
    expect(host.textContent).not.toContain('Old child result')
  })

  it('refreshes a resumed child on a later turn even while its earlier reasoning is pinned open', async () => {
    const host = await renderWith([{ seq: 10, type: 'assistant', data: { text: 'First result', thought: 'First reasoning' }, created: 10 }])
    const toggle = [...host.querySelectorAll('button')].find(button => button.textContent?.includes('Thinking'))!
    act(() => toggle.click())
    fetchMock.mockClear()
    fetchMock.mockImplementation(async () => ({ ok: true, status: 200, json: async () => ({ events: [
      { seq: 11, type: 'step', data: {}, created: 11 },
      { seq: 12, type: 'assistant', data: { text: 'Resumed result', thought: 'Resumed reasoning' }, created: 12 },
    ] }) }))
    await act(async () => {
      useHarnessChatStore.setState({ sessions: { [CHAT_ID]: { id: 'sess-1', status: 'running', events: [
        child(1, CHILD_ID),
        { seq: 2, type: 'user', data: { text: 'Continue', turn: 2 }, created: 2 },
        { ...child(3, CHILD_ID), data: { sessionId: CHILD_ID, role: 'Research', status: 'completed', turn: 2 } },
      ], error: null } } })
      await Promise.resolve()
    })
    expect(fetchMock.mock.calls[0][0]).toContain('after=10')
    expect(host.textContent).toContain('Resumed result')
    expect(host.textContent).toContain('First reasoning')
    expect(toggle.isConnected).toBe(true)
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
  })

  it('merges interleaved legacy snapshots into one reasoning block and one text row', async () => {
    const events = [
      { seq: 1, type: 'turn_start', data: {}, created: 1 },
      { seq: 2, type: 'thought', data: { text: 'Inspect ' }, created: 2 },
      { seq: 3, type: 'thought', data: { text: 'files.' }, created: 3 },
      { seq: 4, type: 'assistant_delta', data: { text: 'I have all ' }, created: 4 },
      { seq: 5, type: 'assistant_delta', data: { text: 'three files.' }, created: 5 },
      { seq: 6, type: 'thought', data: { text: 'Inspect files.' }, created: 6 },
      { seq: 7, type: 'usage', data: {}, created: 7 },
      { seq: 8, type: 'assistant', data: { text: 'I have all three files.', thought: 'Inspect files.', final: false }, created: 8 },
    ]
    const timeline = buildSubagentTimeline(events)
    expect(timeline.map(item => item.kind)).toEqual(['thought', 'text'])
    expect(timeline[0].thoughtText).toBe('Inspect files.')
    expect(timeline[1].text).toBe('I have all three files.')
    expect(buildSubagentTimeline([...events, ...events])).toEqual(timeline)
    const host = await renderWith(events)
    const toggles = [...host.querySelectorAll('button')].filter(button => button.textContent?.includes('Thinking'))
    expect(toggles).toHaveLength(1)
    act(() => toggles[0].dispatchEvent(new MouseEvent('click', { bubbles: true })))
    expect(host.textContent?.split('Inspect files.').length).toBe(2)
    expect(host.textContent?.split('I have all three files.').length).toBe(2)
  })

  it('keeps identical responses in distinct model steps, including histories without markers', () => {
    for (const marked of [true, false]) {
      let seq = 0
      const event = (type: string, data: Record<string, unknown> = {}): HarnessEvent => ({ seq: ++seq, type, data, created: seq })
      const events = [1, 2].flatMap(() => [
        ...(marked ? [event('step'), event('turn_start')] : []),
        event('thought', { text: 'Same thought' }),
        event('assistant_delta', { text: 'Same answer' }),
        event('assistant', { text: 'Same answer', thought: 'Same thought', final: false }),
      ])
      const items = buildSubagentTimeline(events)
      expect(items.filter(item => item.kind === 'thought').map(item => item.thoughtText)).toEqual(['Same thought', 'Same thought'])
      expect(items.filter(item => item.kind === 'text').map(item => item.text)).toEqual(['Same answer', 'Same answer'])
    }
  })

  it('replaces rewritten snapshots and retains completed steps/tools when retry resets an attempt', () => {
    let seq = 0
    const event = (type: string, data: Record<string, unknown> = {}): HarnessEvent => ({ seq: ++seq, type, data, created: seq })
    const items = buildSubagentTimeline([
      event('assistant', { text: 'Earlier', thought: 'Earlier thought', final: false }),
      event('tool_start', { id: 'read', name: 'file_read' }),
      event('tool_end', { id: 'read', result: { content: 'ok' } }),
      event('step'), event('thought', { text: 'Abandoned thought' }),
      event('assistant_delta', { text: 'Abandoned text' }),
      event('notice', { reset: true }),
      event('thought', { text: 'Draft' }), event('assistant_delta', { text: 'Draft answer' }),
      event('thought', { text: 'Revised thought', snapshot: true }),
      event('assistant', { text: 'Revised answer', thought: 'Revised thought', final: true }),
    ])
    expect(items.map(item => item.kind)).toEqual(['thought', 'text', 'tool_group', 'thought', 'text'])
    expect(items.filter(item => item.kind === 'thought').map(item => item.thoughtText)).toEqual(['Earlier thought', 'Revised thought'])
    expect(items.filter(item => item.kind === 'text').map(item => item.text)).toEqual(['Earlier', 'Revised answer'])
    expect(items[2].tools?.[0]).toMatchObject({ isRunning: false })
  })

  it('event tích luỹ chỉ hiện câu trả lời một lần', async () => {
    const host = await renderWith(cumulativeEvents())
    const text = host.textContent ?? ''
    const occurrences = text.split('Kế hoạch chi').length - 1
    expect(occurrences).toBe(1)
    expect(text).toContain('Kế hoạch chi tiết cho Medical Record Retrieval Agent')
  })

  it('event từng mảnh rời được ghép lại đầy đủ', async () => {
    const host = await renderWith([
      { seq: 1, type: 'assistant_delta', data: { text: 'Kế hoạch chi' }, created: 1 },
      { seq: 2, type: 'assistant_delta', data: { text: ' tiết cho' }, created: 2 },
      { seq: 3, type: 'assistant_delta', data: { text: ' agent' }, created: 3 },
    ])
    expect(host.textContent ?? '').toContain('Kế hoạch chi tiết cho agent')
  })

  it('luồng suy nghĩ tích luỹ không bị lặp khi mở khối Thinking', async () => {
    const host = await renderWith([
      { seq: 1, type: 'thought', data: { text: 'Cần đọc file' }, created: 1 },
      { seq: 2, type: 'thought', data: { text: 'Cần đọc file rồi tóm tắt' }, created: 2 },
    ])
    const toggle = [...host.querySelectorAll('button')].find((button) =>
      (button.textContent ?? '').includes('Thinking'),
    )
    expect(toggle, 'khối Thinking phải có nút mở').toBeTruthy()
    act(() => {
      toggle?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    const text = host.textContent ?? ''
    expect(text.split('Cần đọc file').length - 1).toBe(1)
    expect(text).toContain('Cần đọc file rồi tóm tắt')
  })

  it('bản ghi chuẩn `assistant` sau các delta không in câu trả lời lần hai', async () => {
    const host = await renderWith([
      { seq: 1, type: 'assistant_delta', data: { text: 'Kế hoạch chi' }, created: 1 },
      { seq: 2, type: 'assistant_delta', data: { text: ' tiết cho agent' }, created: 2 },
      { seq: 3, type: 'assistant', data: { text: 'Kế hoạch chi tiết cho agent', final: true }, created: 3 },
    ])
    const text = host.textContent ?? ''
    expect(text.split('Kế hoạch chi').length - 1).toBe(1)
  })

  it('notice thử lại xoá bộ đệm, không dán câu trả lời mới vào phần đã bỏ', async () => {
    // Harness đứt socket giữa câu trả lời rồi thử lại: phần văn bản của lần thử hỏng bị bỏ.
    const host = await renderWith([
      { seq: 1, type: 'assistant_delta', data: { text: 'Kế hoạch chi tiết cho agent ghi hồ sơ' }, created: 1 },
      { seq: 2, type: 'notice', data: { code: 'UPSTREAM_RETRY', reset: true, message: 'thử lại' }, created: 2 },
      { seq: 3, type: 'assistant_delta', data: { text: 'Xin chào' }, created: 3 },
      { seq: 4, type: 'assistant', data: { text: 'Xin chào, đây là kế hoạch mới' }, created: 4 },
    ])
    const text = host.textContent ?? ''
    expect(text).toContain('Xin chào, đây là kế hoạch mới')
    expect(text).not.toContain('ghi hồ sơXin chào')
    expect(text).not.toContain('Kế hoạch chi tiết cho agent ghi hồ sơ')
  })

  it('tool_end gắn đúng tool call theo khoá `id` của harness', async () => {
    const host = await renderWith([
      { seq: 1, type: 'tool_start', data: { id: 'call_1', name: 'terminal_exec', args: { command: 'ls' } }, created: 1 },
      { seq: 2, type: 'tool_end', data: { id: 'call_1', name: 'terminal_exec', result: { stdout: 'ok' } }, created: 2 },
    ])
    const text = host.textContent ?? ''
    expect(text).toContain('terminal_exec')
    // `tool_end` khớp được theo `id` ⇒ dòng rời trạng thái "running" và hiện "exit 0".
    // Trước bản sửa, panel đọc khoá `tool_call_id` (không tồn tại) nên dòng đứng mãi ở "running".
    expect(text).toContain('exit 0')
  })
})
