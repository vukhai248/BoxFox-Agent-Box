import { describe, expect, it } from 'vitest'
import { SandboxWorkspaceRepository } from './http'
import { MockWorkspaceRepository } from './mock'
import { createWorkspaceRepository, WorkspaceRepositoryHttpError } from './index'

/** Dựng env từ `import.meta.env` rồi ghi đè vài khóa — đủ kiểu cho factory mà không cần Vite. */
function env(overrides: Partial<ImportMetaEnv> = {}): ImportMetaEnv {
  return { ...import.meta.env, ...overrides }
}

describe('createWorkspaceRepository', () => {
  it('VITE_WORKSPACE_SOURCE=mock → MockWorkspaceRepository', () => {
    const repo = createWorkspaceRepository(env({ VITE_WORKSPACE_SOURCE: 'mock' }))
    expect(repo).toBeInstanceOf(MockWorkspaceRepository)
    expect(repo.baseUrl).toBe('mock://workspace')
  })

  it('không đặt nguồn → SandboxWorkspaceRepository dùng mặc định box API', () => {
    const repo = createWorkspaceRepository(env())
    expect(repo).toBeInstanceOf(SandboxWorkspaceRepository)
    expect(repo.baseUrl).toBe('http://localhost:8081')
  })

  it('VITE_BOX_API_URL tường minh → sandbox dùng URL đã trim dấu gạch', () => {
    const repo = createWorkspaceRepository(env({ VITE_BOX_API_URL: 'http://box.local:9000/' }))
    expect(repo).toBeInstanceOf(SandboxWorkspaceRepository)
    expect(repo.baseUrl).toBe('http://box.local:9000')
  })

  it('re-export WorkspaceRepositoryHttpError', () => {
    const err = new WorkspaceRepositoryHttpError(404, 'Không tìm thấy')
    expect(err.status).toBe(404)
    expect(err.message).toBe('Không tìm thấy')
  })
})

describe('MockWorkspaceRepository', () => {
  it('liệt kê gốc theo thứ tự dir-trước-file', async () => {
    const repo = new MockWorkspaceRepository()
    const out = await repo.list('')
    const names = out.entries.map((e) => e.name)
    // Thư mục (theo locale vi) trước, rồi file .env, plan.md.
    expect(names).toEqual(['docs', 'src', 'tests', 'vendor', '.env', 'plan.md'])
    expect(out.breadcrumb.map((c) => c.name)).toEqual(['workspace'])
  })

  it('liệt kê thư mục con có breadcrumb đầy đủ', async () => {
    const repo = new MockWorkspaceRepository()
    const out = await repo.list('src')
    expect(out.breadcrumb.map((c) => c.name)).toEqual(['workspace', 'src'])
    expect(out.entries.map((e) => e.name).sort()).toEqual(['auth.py', 'parser.py'])
  })

  it('readText phục vụ nội dung file từ node.content', async () => {
    const repo = new MockWorkspaceRepository()
    const out = await repo.readText('src/parser.py')
    expect(out.binary).toBe(false)
    expect(out.content).toContain('def find_group')
    expect(out.language).toBe('python')
  })

  it('mediaUrl/downloadUrl mã hoá path', () => {
    const repo = new MockWorkspaceRepository()
    expect(repo.mediaUrl('a/b.png')).toBe('mock://workspace/file/media?path=a%2Fb.png')
    expect(repo.downloadUrl('a/b.png')).toBe('mock://workspace/file/download?path=a%2Fb.png')
  })
})
