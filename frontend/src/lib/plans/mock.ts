import type { PlanDocument, PlanManifest, PlanRepository } from './types'

const modifiedAt = '2026-08-27T00:00:00Z'

const manifest: PlanManifest = {
  plans: [
    {
      identity: 'plan-browser-demo',
      relativeDirectory: '',
      slug: 'plan-browser-demo',
      versions: [
        {
          version: 1,
          label: 'v1',
          relativePath: 'v1-plan-browser-demo.md',
          sizeBytes: 604,
          modifiedAt,
          status: 'approved',
        },
      ],
    },
  ],
  ignoredCount: 0,
  warnings: ['Mock plan source is active.'],
}

const markdown = `# Plan browser demo

This mock document is available only for frontend development.

- Choose a plan identity
- Select a version
- Refresh when sandbox files change

| Item | Status |
| --- | --- |
| Repository | Ready |

\`inline code\` and $T(n)=O(n)$ render with the shared Markdown renderer.`

/** Adapter chỉ cho unit test hoặc demo UI; sản phẩm mặc định luôn dùng sandbox. */
export class MockPlanRepository implements PlanRepository {
  async list(): Promise<PlanManifest> {
    return manifest
  }

  async read(identity: string, version: number): Promise<PlanDocument> {
    const plan = manifest.plans.find((item) => item.identity === identity)
    const item = plan?.versions.find((candidate) => candidate.version === version)
    if (!plan || !item) throw new Error('Mock plan document not found.')
    return { ...item, identity, markdown }
  }
}
