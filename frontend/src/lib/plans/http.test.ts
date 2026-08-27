import { describe, expect, it, vi } from 'vitest'
import { SandboxPlanRepository } from './http'

describe('SandboxPlanRepository', () => {
  it('loads the manifest from the sandbox endpoint and derives presentation status', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        plans: [
          {
            identity: 'demo',
            relativeDirectory: '',
            slug: 'demo',
            versions: [
              { version: 2, label: 'v2', relativePath: 'v2-demo.md', sizeBytes: 2, modifiedAt: '', status: 'approved' },
              { version: 1, label: 'v1', relativePath: 'v1-demo.md', sizeBytes: 1, modifiedAt: '', status: 'draft' },
            ],
          },
        ],
        ignoredCount: 0,
        warnings: [],
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    const result = await new SandboxPlanRepository('http://box.test/').list()

    expect(fetchMock).toHaveBeenCalledWith('http://box.test/__box/plans', { signal: undefined })
    expect(result.plans[0]!.versions.map((version) => version.status)).toEqual(['draft', 'approved'])
  })

  it('reads the full content payload shape, including the backend label', async () => {
    const content = {
      identity: 'nested/demo',
      version: 12,
      label: 'v12',
      relativePath: 'nested/v12-demo.md',
      markdown: '# Demo',
      sizeBytes: 120,
      modifiedAt: '2026-08-27T00:00:00Z',
      status: 'draft' as const,
    }
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => content })
    vi.stubGlobal('fetch', fetchMock)

    const result = await new SandboxPlanRepository('http://box.test').read('nested/demo', 12)

    expect(fetchMock).toHaveBeenCalledWith('http://box.test/__box/plans/content?identity=nested%2Fdemo&version=12', {
      signal: undefined,
    })
    expect(result).toEqual(content)
  })
})
