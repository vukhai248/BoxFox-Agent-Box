import { describe, expect, it } from 'vitest'
import { buildInspectedElementChunk, INSPECTED_ELEMENT_CONFIDENTIALITY, INSPECTED_ELEMENT_TOOL } from './chunk'
import { formatInspectedElementForAgent } from './format'
import type { DomInspectResult, InspectedElementContext } from '../../types/inspect'
import { CONFIDENTIALITY, INTEGRITY } from '../../types/labels'
import type { ContextState } from '../../types/context'
import { reduce, type AgentState } from '../../store/agentStore'

function domResult(overrides: Partial<DomInspectResult> = {}): DomInspectResult {
  return {
    type: 'dom',
    selector: 'span.text-sm',
    url: 'http://localhost:3100/',
    title: 'BoxFox',
    tagName: 'span',
    text: 'boxfox',
    attributes: {},
    html: '<span class="text-sm">boxfox</span>',
    truncated: false,
    cssBox: { x: 0, y: 0, width: 0, height: 0 },
    screenBox: { x: 0, y: 0, width: 0, height: 0 },
    target: { windowId: '0x1', windowTitle: 'Win', targetId: 'tgt-1' },
    label: {
      integrity: 'duoc_nguoi_dung_cho_phep',
      confidentiality: 'bi_mat',
      source_kind: 'user_input',
      source_uri: 'ignored',
      tool_name: '',
      content_hash: 'sha256:xyz',
    },
    ...overrides,
  }
}

function ctxOf(overrides: Partial<InspectedElementContext> = {}): InspectedElementContext {
  return { id: 'el-1', point: { x: 10, y: 20 }, result: domResult(), ...overrides }
}

describe('buildInspectedElementChunk', () => {
  it('integrity luôn khong_tin_duoc dù result.label.integrity là gì', () => {
    const chunk = buildInspectedElementChunk(ctxOf())
    expect(chunk.integrity).toBe('khong_tin_duoc')
  })

  it('confidentiality luôn bằng hằng, không đọc từ result.label', () => {
    const chunk = buildInspectedElementChunk(ctxOf())
    expect(chunk.confidentiality).toBe(INSPECTED_ELEMENT_CONFIDENTIALITY)
  })

  it('provenance.source_kind luôn screen_capture', () => {
    const chunk = buildInspectedElementChunk(ctxOf())
    expect(chunk.provenance.source_kind).toBe('screen_capture')
  })

  it('provenance.source_uri dựng từ windowId (nhánh dom)', () => {
    const chunk = buildInspectedElementChunk(ctxOf())
    expect(chunk.provenance.source_uri).toBe('screen://element/0x1')
  })

  it('provenance.source_uri dựng từ windowId (nhánh desktop)', () => {
    const ctx = ctxOf({
      result: {
        type: 'desktop',
        windowTitle: 'Win',
        windowId: '0x2',
        position: { x: 0, y: 0 },
        size: { width: 1, height: 1 },
        label: domResult().label,
      },
    })
    const chunk = buildInspectedElementChunk(ctx)
    expect(chunk.provenance.source_uri).toBe('screen://element/0x2')
  })

  it('provenance.tool_name luôn là hằng INSPECTED_ELEMENT_TOOL, không đọc label.tool_name', () => {
    const chunk = buildInspectedElementChunk(ctxOf())
    expect(chunk.provenance.tool_name).toBe(INSPECTED_ELEMENT_TOOL)

    const custom = ctxOf({ result: domResult({ label: { ...domResult().label, tool_name: 'custom' } }) })
    expect(buildInspectedElementChunk(custom).provenance.tool_name).toBe(INSPECTED_ELEMENT_TOOL)
  })

  it('provenance.content_hash truyền thẳng từ label', () => {
    const chunk = buildInspectedElementChunk(ctxOf())
    expect(chunk.provenance.content_hash).toBe('sha256:xyz')
  })

  it('provenance.derived_from luôn []', () => {
    expect(buildInspectedElementChunk(ctxOf()).provenance.derived_from).toEqual([])
  })

  it('step_count=0, endorsed=false', () => {
    const chunk = buildInspectedElementChunk(ctxOf())
    expect(chunk.step_count).toBe(0)
    expect(chunk.endorsed).toBe(false)
  })

  it('content bằng formatInspectedElementForAgent(ctx)', () => {
    const ctx = ctxOf()
    expect(buildInspectedElementChunk(ctx).content).toBe(formatInspectedElementForAgent(ctx))
  })

  it('label_id tất định lbl-inspect-<id>, lặp lại cho ra cùng giá trị', () => {
    const ctx = ctxOf({ id: 'el-42' })
    expect(buildInspectedElementChunk(ctx).provenance.label_id).toBe('lbl-inspect-el-42')
    expect(buildInspectedElementChunk(ctx).provenance.label_id).toBe('lbl-inspect-el-42')
  })

  it('created_at lấy từ tham số now, không phải Date.now thật', () => {
    const chunk = buildInspectedElementChunk(ctxOf(), () => '2020-01-01T00:00:00.000Z')
    expect(chunk.provenance.created_at).toBe('2020-01-01T00:00:00.000Z')
  })
})

describe('buildInspectedElementChunk + agentStore.reduce — tích hợp', () => {
  it('label_added với chunk này kéo integrity_floor xuống khong_tin_duoc', () => {
    const startContext: ContextState = {
      chunks: [],
      integrity_floor: INTEGRITY.USER_AUTHORIZED,
      confidentiality_ceiling: CONFIDENTIALITY.PUBLIC,
    }
    const state = { context: startContext } as unknown as AgentState
    const chunk = buildInspectedElementChunk(ctxOf())
    const patch = reduce(state, { type: 'label_added', chunk })
    expect(patch.context?.integrity_floor).toBe('khong_tin_duoc')
  })
})
