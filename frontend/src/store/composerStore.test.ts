import { beforeEach, describe, expect, it } from 'vitest'
import { useComposerStore } from './composerStore'
import type { DomInspectResult, InspectedElementContext } from '../types/inspect'

function elementCtx(id: string): InspectedElementContext {
  const result: DomInspectResult = {
    type: 'dom',
    selector: 'span',
    url: 'http://localhost:3100/',
    title: 'BoxFox',
    tagName: 'span',
    text: 'boxfox',
    attributes: {},
    html: '<span>boxfox</span>',
    truncated: false,
    cssBox: { x: 0, y: 0, width: 0, height: 0 },
    screenBox: { x: 0, y: 0, width: 0, height: 0 },
    target: { windowId: '0x1', windowTitle: 'Win', targetId: 'tgt-1' },
    label: {
      integrity: 'khong_tin_duoc',
      confidentiality: 'noi_bo',
      source_kind: 'screen_capture',
      source_uri: 'screen://element/0x1',
      tool_name: 'inspect_element',
      content_hash: '',
    },
  }
  return { id, point: { x: 1, y: 2 }, result }
}

beforeEach(() => {
  useComposerStore.setState({ pendingElements: [] })
})

describe('useComposerStore', () => {
  it('bắt đầu rỗng', () => {
    expect(useComposerStore.getState().pendingElements).toEqual([])
  })

  it('hai lần addPendingElement giữ đúng thứ tự bấm', () => {
    const { addPendingElement } = useComposerStore.getState()
    addPendingElement(elementCtx('a'))
    addPendingElement(elementCtx('b'))
    expect(useComposerStore.getState().pendingElements.map((e) => e.id)).toEqual(['a', 'b'])
  })

  it('removePendingElement xoá đúng một phần tử', () => {
    const { addPendingElement, removePendingElement } = useComposerStore.getState()
    addPendingElement(elementCtx('a'))
    addPendingElement(elementCtx('b'))
    removePendingElement('a')
    expect(useComposerStore.getState().pendingElements.map((e) => e.id)).toEqual(['b'])
  })

  it('clearPendingElements làm rỗng danh sách', () => {
    const { addPendingElement, clearPendingElements } = useComposerStore.getState()
    addPendingElement(elementCtx('a'))
    clearPendingElements()
    expect(useComposerStore.getState().pendingElements).toEqual([])
  })

  it('bấm hai lần cùng một phần tử không chống trùng — hai id khác nhau, hai chip', () => {
    const { addPendingElement } = useComposerStore.getState()
    addPendingElement(elementCtx('a'))
    addPendingElement(elementCtx('a-2'))
    expect(useComposerStore.getState().pendingElements).toHaveLength(2)
  })

  it('removePendingElement với id không tồn tại là no-op', () => {
    const { addPendingElement, removePendingElement } = useComposerStore.getState()
    addPendingElement(elementCtx('a'))
    removePendingElement('does-not-exist')
    expect(useComposerStore.getState().pendingElements.map((e) => e.id)).toEqual(['a'])
  })
})
