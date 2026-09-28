/**
 * P5 — `/btw` phải xuất hiện trong gợi ý `/` ở MỌI chế độ (kể cả khi một mode đang bật), vì nó
 * không mở lượt vai nào: nó chỉ hỏi thêm giữa lượt. Test này khoá cả danh sách lọc lẫn kết quả
 * thật của hook (popup dựng từ `commands` của store).
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useCommandsStore } from '../../store/commandsStore'
import { MODE_COMMANDS, useSlashCompletion } from './useSlashCompletion'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const { agentApiMock } = vi.hoisted(() => ({ agentApiMock: vi.fn() }))
vi.mock('../../lib/agentApi', () => ({ agentApi: agentApiMock }))

const COMMANDS = [
  { slug: 'btw', description: 'Hỏi thêm mà không cắt lượt', kind: 'builtin', enabled: true },
  { slug: 'plan', description: 'Use plan specialist', kind: 'builtin', enabled: true },
]

let roots: Root[] = []

async function renderHook(input: string, options?: { modeOnly?: boolean }) {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  const out: { value: ReturnType<typeof useSlashCompletion> | null } = { value: null }
  function Probe() {
    out.value = useSlashCompletion(input, () => {}, options)
    return null
  }
  // `act` bất đồng bộ để cú `load()` của hook kịp chạy xong trong cùng một nhịp — không có
  // cảnh báo "update not wrapped in act" và popup được dựng từ danh sách ĐÃ nạp.
  await act(async () => {
    root.render(<Probe />)
  })
  return out
}

function popupSlugs(hook: ReturnType<typeof useSlashCompletion>): string[] {
  const popup = hook.popup
  if (!popup) return []
  const children = (popup as { props: { children: unknown } }).props.children
  return Array.isArray(children) ? children.map((child) => String((child as { key: string }).key)) : []
}

beforeEach(() => {
  useCommandsStore.setState({ commands: COMMANDS, custom: [], error: null })
  agentApiMock.mockReset()
  agentApiMock.mockImplementation(async () => ({ commands: COMMANDS, custom: [] }))
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  vi.restoreAllMocks()
})

describe('useSlashCompletion — P5 `/btw`', () => {
  it('`/btw` nằm trong danh sách lệnh dùng được khi một mode đang bật', () => {
    expect(MODE_COMMANDS.has('btw')).toBe(true)
  })

  it('gợi ý `/btw` hiện ở chế độ thường', async () => {
    const out = await renderHook('/btw')

    expect(out.value?.expanded).toBe(true)
    expect(popupSlugs(out.value!)).toEqual(['btw'])
  })

  it('gợi ý `/btw` vẫn hiện khi chế độ mode đang bật (`modeOnly`)', async () => {
    const out = await renderHook('/btw', { modeOnly: true })

    // `/plan` là lệnh vai nên bị lọc khỏi chế độ mode; `/btw` thì không.
    expect(popupSlugs(out.value!)).toEqual(['btw'])
  })

  it('gõ `/p` ở chế độ mode không thấy `/plan` nhưng thấy `/btw` khi khớp', async () => {
    const byPlan = await renderHook('/p', { modeOnly: true })
    expect(popupSlugs(byPlan.value!)).toEqual([])
    const byBtw = await renderHook('/bt', { modeOnly: true })
    expect(popupSlugs(byBtw.value!)).toEqual(['btw'])
  })
})
