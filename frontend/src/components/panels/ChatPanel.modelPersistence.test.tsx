import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { I18nProvider } from '../../i18n'
import { ChatPanel } from './ChatPanel'
import { useHarnessStore } from '../../store/harnessStore'
import { useProviderStore } from '../../store/providerStore'
import { useRouterChatStore } from '../../store/routerChatStore'
import type { ProviderSnapshot } from '../../types/provider'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

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

const mockSnapshot = {
  defaultRoute: {
    connectionId: 'conn-1',
    modelId: 'ling-3.0-flash-free',
    aliasId: null,
  },
  connections: [
    {
      id: 'conn-1',
      providerId: 'opencode',
      name: 'OpenCode Free (key 1)',
      enabled: true,
      authState: 'ready',
      auth: { kind: 'api_key', keyMask: 'sk-...123' },
      inferenceState: 'ready',
      discoveryState: 'ready',
      models: [
        { id: 'ling-3.0-flash-free', name: 'ling-3.0-flash-free', enabled: true },
        { id: 'space-bunny-free', name: 'space-bunny-free', enabled: true },
      ],
    },
  ],
  aliases: [],
} as unknown as ProviderSnapshot

describe('ChatPanel — khôi phục model đã lưu khi reload snapshot', () => {
  beforeEach(() => {
    roots = []
    document.body.innerHTML = ''
    useRouterChatStore.getState().setSelection(null)
  })

  afterEach(() => {
    for (const r of roots) act(() => r.unmount())
    roots = []
    document.body.innerHTML = ''
  })

  it('khi snapshot nạp xong, tự động khôi phục activeModelId đã lưu thay vì đè về defaultRoute', async () => {
    // Giả lập người dùng đã chọn space-bunny-free từ trước
    useHarnessStore.getState().setActiveModel('provider:opencode:space-bunny-free')

    // Nạp snapshot của provider
    act(() => {
      useProviderStore.setState({ snapshot: mockSnapshot })
    })

    const host = render(<ChatPanel />)

    // Selection trong routerChatStore phải là space-bunny-free, KHÔNG phải ling-3.0-flash-free
    const currentSelection = useRouterChatStore.getState().selection
    expect(currentSelection).not.toBeNull()
    expect((currentSelection as { modelId: string })?.modelId).toBe('space-bunny-free')

    // Chip ngoài composer phải hiển thị tên của space-bunny-free
    const modelChip = host.querySelector('[data-testid="composer-model-name"]')
    expect(modelChip?.textContent).toContain('space-bunny')
  })
})
