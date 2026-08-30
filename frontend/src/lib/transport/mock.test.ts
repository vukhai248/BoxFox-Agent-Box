import { describe, expect, it } from 'vitest'
import { MockTransport } from './mock'
import type { ServerEvent } from '../../types/transport'
import type { InspectedElementContext } from '../../types/inspect'

function elementCtx(id: string): InspectedElementContext {
  return {
    id,
    point: { x: 1, y: 2 },
    result: {
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
    },
  }
}

describe('MockTransport — user_message với elements', () => {
  it('không có elements ⇒ chỉ echo + system_note chung, không có label_added', async () => {
    const transport = new MockTransport()
    await transport.connect('s1')
    const events: ServerEvent[] = []
    transport.subscribe((event) => events.push(event))
    transport.send({ type: 'user_message', text: 'hello' })
    expect(events.some((e) => e.type === 'label_added')).toBe(false)
    expect(events.filter((e) => e.type === 'system_note')).toHaveLength(1)
  })

  it('có elements ⇒ phát label_added cho mỗi phần tử, TRƯỚC system_note, rồi system_note nói rõ số lượng', async () => {
    const transport = new MockTransport()
    await transport.connect('s1')
    const events: ServerEvent[] = []
    transport.subscribe((event) => events.push(event))
    transport.send({ type: 'user_message', text: 'xem cái này', elements: [elementCtx('a'), elementCtx('b')] })

    const labelAddedEvents = events.filter((e) => e.type === 'label_added')
    expect(labelAddedEvents).toHaveLength(2)
    expect(labelAddedEvents.every((e) => e.type === 'label_added' && e.chunk.integrity === 'khong_tin_duoc')).toBe(
      true,
    )

    const types = events.map((e) => e.type)
    const firstLabelAddedIndex = types.indexOf('label_added')
    const systemNoteIndex = types.indexOf('system_note')
    expect(firstLabelAddedIndex).toBeGreaterThanOrEqual(0)
    expect(systemNoteIndex).toBeGreaterThan(firstLabelAddedIndex)

    const note = events.find((e) => e.type === 'system_note')
    expect(note && note.type === 'system_note' && note.text).toContain('2')
  })
})
