import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { usePlanFiles } from './usePlanFiles'
import type { PlanFilesState } from './usePlanFiles'
import type { PlanDocument, PlanManifest, PlanRepository } from '../lib/plans'

const modifiedAt = '2026-08-27T00:00:00Z'

function manifest(identity: string, versions: number[]): PlanManifest {
  return {
    plans: [
      {
        identity,
        relativeDirectory: '',
        slug: identity,
        versions: versions.map((version, index) => ({
          version,
          label: `v${version}`,
          relativePath: `v${version}-${identity}.md`,
          sizeBytes: version,
          modifiedAt,
          status: index === 0 && versions.length > 1 ? 'draft' : 'approved',
        })),
      },
    ],
    ignoredCount: 0,
    warnings: [],
  }
}

function documentFor(identity: string, version: number): PlanDocument {
  return {
    identity,
    version,
    label: `v${version}`,
    relativePath: `v${version}-${identity}.md`,
    markdown: `# ${identity} ${version}`,
    sizeBytes: version,
    modifiedAt,
    status: 'approved',
  }
}

async function mount(repository: PlanRepository) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  let latest: PlanFilesState | null = null

  function Probe() {
    latest = usePlanFiles(repository)
    return null
  }

  await act(async () => {
    root.render(<Probe />)
  })

  return {
    get state() {
      if (!latest) throw new Error('Hook did not render.')
      return latest
    },
    async unmount() {
      await act(async () => root.unmount())
      host.remove()
    },
  }
}

describe('usePlanFiles', () => {
  it('loads the default latest version and falls back after refresh removes the selection', async () => {
    const repository: PlanRepository = {
      list: vi.fn().mockResolvedValueOnce(manifest('demo', [2, 1])).mockResolvedValueOnce(manifest('demo', [2])),
      read: vi.fn(async (identity, version) => documentFor(identity, version)),
    }
    const hook = await mount(repository)

    expect(hook.state.status).toBe('ready')
    expect(hook.state.selection).toEqual({ identity: 'demo', version: 2 })

    await act(async () => {
      hook.state.selectVersion(1)
    })
    expect(hook.state.selection).toEqual({ identity: 'demo', version: 1 })

    await act(async () => {
      await hook.state.refresh()
    })
    expect(hook.state.status).toBe('ready')
    expect(hook.state.selection).toEqual({ identity: 'demo', version: 2 })
    expect(hook.state.document?.markdown).toBe('# demo 2')
    await hook.unmount()
  })

  it('ignores a stale document response when a newer refresh completes', async () => {
    let resolveFirstRead: ((value: PlanDocument) => void) | undefined
    const firstRead = new Promise<PlanDocument>((resolve) => {
      resolveFirstRead = resolve
    })
    const repository: PlanRepository = {
      list: vi.fn().mockResolvedValueOnce(manifest('old', [1])).mockResolvedValueOnce(manifest('new', [2])),
      read: vi.fn().mockReturnValueOnce(firstRead).mockResolvedValueOnce(documentFor('new', 2)),
    }
    const hook = await mount(repository)

    expect(hook.state.status).toBe('loading')
    await act(async () => {
      await hook.state.refresh()
    })
    expect(hook.state.document?.identity).toBe('new')

    await act(async () => {
      resolveFirstRead?.(documentFor('old', 1))
      await firstRead
    })
    expect(hook.state.document?.identity).toBe('new')
    expect(hook.state.selection).toEqual({ identity: 'new', version: 2 })
    await hook.unmount()
  })
})
