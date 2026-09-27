/**
 * F7 (đợt soát 2026-09-27) — chip tên model trong ô soạn phải là MỘT hàng.
 *
 * Lỗi gốc (vòng kiểm thử thứ bảy ghi nhận ở bố cục 1440×900): với tên model dài
 * (`OpenCode Free · mimo-v2.5-free`) chip xuống ba hàng, làm ô soạn cao bất thường và lệch hàng so
 * với các nút cạnh đó. jsdom không có bố cục, nên hợp đồng ở đây là hợp đồng THẬT của bản vá: chip
 * co lại được (`min-w-0` + trần bề rộng), phần tên tự cắt bằng dấu ba chấm (`truncate` + `max-w-`),
 * các mảnh còn lại không co (`shrink-0`) — và tên đầy đủ vẫn đọc được ở tooltip.
 *
 * Ca dài nhất là phiên ĐANG GHIM một connection: nhãn `pinned: OpenCode Free (key 2) · …` dài hơn
 * hẳn nhãn thường, nên đó là ca phải khoá lại trước.
 */
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { useHarnessStore } from '../../store/harnessStore'
import { useProviderStore } from '../../store/providerStore'
import type { ProviderSnapshot } from '../../types/provider'
import { HarnessModelPicker } from './HarnessModelPicker'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const MUSE = 'muse-spark-1.3-contributor-free'
const PROVIDER_ROW = `provider:opencode:${MUSE}`
/** Nhãn hàng cha = provider · tên model — đúng chuỗi dài mà lỗi gốc nhắc tới. */
const GROUP_NAME = `OpenCode Free · ${MUSE}`
const TAIL = MUSE.slice(0, 14)

let roots: Root[] = []

function render(node: React.ReactNode): HTMLElement {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  roots.push(root)
  act(() => {
    root.render(<I18nProvider>{node}</I18nProvider>)
  })
  return host
}

function trigger(host: HTMLElement): HTMLButtonElement {
  const button = Array.from(host.querySelectorAll('button'))
    .find((b) => (b.getAttribute('title') ?? '').startsWith('Model:'))
  if (!button) throw new Error('Không tìm thấy chip model trong ô soạn')
  return button
}

function nameSpan(chip: HTMLElement): HTMLElement {
  const span = chip.querySelector<HTMLElement>('[data-testid="composer-model-name"]')
  if (!span) throw new Error('Không tìm thấy phần tên model trong chip')
  return span
}

const model = (id: string) => ({
  id, name: id, source: 'live', stale: false, contextWindow: 1_000_000,
  contextWindowSource: 'reported', thinkingType: 'effort', defaultThinking: null,
  thinkingLevels: ['low', 'medium', 'high'], capabilities: {}, enabled: true, health: 'healthy',
})

const connection = (id: string, name: string) => ({
  id, providerId: 'opencode', name, endpoint: 'https://example.test',
  enabled: true, authState: 'ready', projectState: 'not_applicable', discoveryState: 'ready',
  inferenceState: 'ready', credentialPresent: true, email: null, accountLabel: null, projectId: null,
  revision: 1, autoSync: true, lastModelTestedAt: null, lastModelSyncAt: null, nextModelSyncAt: null,
  quota: null, error: null, models: [model(MUSE)],
  keys: [{ id: `${id}-key1`, label: 'key 1', prefix: 'sk-', state: 'ready' }],
})

const snapshot = (): ProviderSnapshot => ({
  providers: [{ id: 'opencode', name: 'OpenCode Free' }],
  connections: [connection('c1', 'OpenCode Free (key 1)'), connection('c2', 'OpenCode Free (key 2)')],
  providerConfigs: [], aliases: [], defaultRoute: null, keys: [], usage: [],
  health: { status: 'ok', version: '0.1.0' },
}) as unknown as ProviderSnapshot

/** Hợp đồng bố cục của chip: co được, cắt được, các mảnh khác không co. */
function assertOneRowContract(chip: HTMLButtonElement) {
  expect(chip.className).toContain('min-w-0')
  expect(chip.className).toContain('max-w-[260px]')
  expect(chip.className).toContain('items-center')

  const name = nameSpan(chip)
  expect(name.className).toContain('truncate')
  expect(name.className).toContain('max-w-[170px]')
  expect((name.textContent ?? '').length).toBeGreaterThan(0)

  // `className` của SVG không phải chuỗi (`SVGAnimatedString`), nên đọc qua thuộc tính.
  const classes = (el: Element) => el.getAttribute('class') ?? ''
  for (const child of Array.from(chip.children)) {
    if (child === name || child.contains(name)) continue
    const shrink = classes(child).includes('shrink-0')
      || Array.from(child.querySelectorAll('*')).every((el) => classes(el).includes('shrink-0'))
    expect(shrink, `mảnh ${classes(child)} phải là shrink-0`).toBe(true)
  }
}

beforeEach(() => {
  useHarnessStore.getState().setActiveModel(PROVIDER_ROW)
  useProviderStore.setState({ snapshot: snapshot() })
})

afterEach(() => {
  for (const root of roots) act(() => root.unmount())
  roots = []
  document.body.innerHTML = ''
  useProviderStore.setState({ snapshot: null })
  vi.restoreAllMocks()
})

describe('HarnessModelPicker — chip model ở ô soạn là một hàng', () => {
  it('model thường: chip co lại được, tên dài tự cắt thay vì đẩy các nút cạnh nó', () => {
    const host = render(<HarnessModelPicker />)
    const chip = trigger(host)

    assertOneRowContract(chip)

    const title = chip.getAttribute('title') ?? ''
    expect(title).toContain(`Model: ${GROUP_NAME}`)
    expect(title).toContain('(opencode)')
  })

  it('phiên ĐANG GHIM (nhãn dài nhất): vẫn một hàng, và tooltip nói cả connection lẫn tên model', () => {
    useHarnessStore.getState().setActiveModel(`model:c2:${MUSE}`)
    const host = render(<HarnessModelPicker />)
    const chip = trigger(host)

    assertOneRowContract(chip)
    // Nhãn ghim là chuỗi dài nhất mà chip phải chứa trong một hàng.
    expect(chip.textContent).toContain('pinned: OpenCode Free (key 2)')
    expect(chip.textContent).toContain(TAIL)

    const title = chip.getAttribute('title') ?? ''
    expect(title).toContain(`Model: ${GROUP_NAME}`, 'tên đầy đủ của model')
    expect(title).toContain('(opencode)')
    expect(title).toContain('pinned OpenCode Free (key 2)', 'connection đã ghim')
  })

  it('nhánh harness: chip giữ nguyên hợp đồng một hàng, nhãn chỉ là con số', () => {
    // Nhánh này không có chuỗi dài nào để xuống hàng, nhưng nó dùng CHUNG chip với nhánh model —
    // nên hợp đồng (co được ở chip, mọi mảnh khác `shrink-0`) phải đúng ở đây nữa.
    useHarnessStore.getState().setActiveHarness('open-model-harness-copy-1')
    const harness = useHarnessStore.getState().getHarnessById('open-model-harness-copy-1')
    const host = render(<HarnessModelPicker />)
    const chip = Array.from(host.querySelectorAll('button'))
      .find((b) => (b.getAttribute('title') ?? '').startsWith('Harness:'))
    if (!chip) throw new Error('Không tìm thấy chip harness trong ô soạn')

    expect(chip.className).toContain('min-w-0')
    expect(chip.className).toContain('max-w-[260px]')
    const classes = (el: Element) => el.getAttribute('class') ?? ''
    for (const child of Array.from(chip.children)) {
      const own = classes(child)
      const nested = Array.from(child.querySelectorAll('*')).map(classes).join(' ')
      expect(`${own} ${nested}`, 'mọi mảnh của chip phải là shrink-0').toContain('shrink-0')
    }

    const enabled = harness?.subagents.filter((s) => s.enabled).length ?? 1
    expect(chip.textContent).toContain(String(enabled))
    expect(chip.getAttribute('title') ?? '').toContain('sub-agents')
  })
})
