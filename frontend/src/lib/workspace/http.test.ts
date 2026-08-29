import { describe, expect, it, vi } from 'vitest'
import { SandboxWorkspaceRepository, WorkspaceRepositoryHttpError } from './http'

function jsonResponse(body: unknown, init?: { ok?: boolean; status?: number }): Response {
  const ok = init?.ok ?? true
  const status = init?.status ?? 200
  return {
    ok,
    status,
    json: async () => body,
    blob: async () => new Blob(['zip-bytes']),
  } as Response
}

describe('SandboxWorkspaceRepository', () => {
  it('list mã hoá path vào query', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ breadcrumb: [], entries: [] }))
    vi.stubGlobal('fetch', fetchMock)
    await new SandboxWorkspaceRepository('http://box.test', 'k').list('frontend/src')
    expect(fetchMock).toHaveBeenCalledWith('http://box.test/__box/files?path=frontend%2Fsrc', { signal: undefined })
  })

  it('readText đánh dấu mã hoá path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ content: 'hi', sizeBytes: 2, mime: 'text/plain', language: 'python', binary: false }),
    )
    vi.stubGlobal('fetch', fetchMock)
    const out = await new SandboxWorkspaceRepository('http://box.test', 'k').readText('a/b.py')
    expect(fetchMock).toHaveBeenCalledWith('http://box.test/__box/file/content?path=a%2Fb.py', { signal: undefined })
    expect(out.content).toBe('hi')
  })

  it('mediaUrl/thumbnailUrl/downloadUrl mã hoá path mà không gọi fetch', () => {
    const repo = new SandboxWorkspaceRepository('http://box.test', 'k')
    expect(repo.mediaUrl('a/b.png')).toBe('http://box.test/__box/file/media?path=a%2Fb.png')
    expect(repo.thumbnailUrl('a/b.mp4')).toBe('http://box.test/__box/file/thumbnail?path=a%2Fb.mp4')
    expect(repo.downloadUrl('a/b.zip')).toBe('http://box.test/__box/file/download?path=a%2Fb.zip')
  })

  it('zip gửi POST JSON chứa paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(null))
    vi.stubGlobal('fetch', fetchMock)
    const blob = await new SandboxWorkspaceRepository('http://box.test', 'k').zip(['src', 'plan.md'])
    expect(fetchMock).toHaveBeenCalledWith('http://box.test/__box/files/zip', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paths: ['src', 'plan.md'] }),
      signal: undefined,
    })
    expect(blob.size).toBeGreaterThan(0)
  })

  it('upload kèm header X-BoxFox-Api-Key + octet-stream', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ path: 'up/x.txt', sizeBytes: 3 }))
    vi.stubGlobal('fetch', fetchMock)
    const body = new Blob(['abc'])
    const out = await new SandboxWorkspaceRepository('http://box.test', 'secret-key').upload('up', 'x.txt', body)
    expect(fetchMock).toHaveBeenCalledWith('http://box.test/__box/file/upload?path=up&name=x.txt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/octet-stream', 'X-BoxFox-Api-Key': 'secret-key' },
      body,
      signal: undefined,
    })
    expect(out).toEqual({ path: 'up/x.txt', sizeBytes: 3 })
  })

  it('unzip kèm header X-BoxFox-Api-Key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ extracted: 2, skipped: 0, warnings: [] }))
    vi.stubGlobal('fetch', fetchMock)
    const out = await new SandboxWorkspaceRepository('http://box.test', 'secret-key').unzip('a/b.zip')
    expect(fetchMock).toHaveBeenCalledWith('http://box.test/__box/file/unzip?path=a%2Fb.zip', {
      method: 'POST',
      headers: { 'X-BoxFox-Api-Key': 'secret-key' },
      signal: undefined,
    })
    expect(out.extracted).toBe(2)
  })

  it('lỗi HTTP ném WorkspaceRepositoryHttpError kèm thông báo từ payload', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ error: 'Không tìm thấy' }, { ok: false, status: 404 }))
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxWorkspaceRepository('http://box.test', 'k').list('missing')).rejects.toMatchObject({
      status: 404,
      message: 'Không tìm thấy',
    })
  })

  it('lỗi không phải JSON vẫn ném với status + thông báo mặc định', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new SyntaxError('not json')
      },
    } as unknown as Response)
    vi.stubGlobal('fetch', fetchMock)
    await expect(new SandboxWorkspaceRepository('http://box.test', 'k').readText('x')).rejects.toBeInstanceOf(
      WorkspaceRepositoryHttpError,
    )
  })
})
