import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'
import { useWorkspaceFiles } from './useWorkspaceFiles'
import type { UseWorkspaceFilesResult } from './useWorkspaceFiles'
import { useUiStore } from '../store/uiStore'
import type {
  WorkspaceContent,
  WorkspaceEntry,
  WorkspaceListing,
  WorkspaceRepository,
} from '../lib/workspace'

const mtime = '2026-08-28T12:00:00Z'

function dir(name: string): WorkspaceEntry {
  return { name, kind: 'dir', sizeBytes: 0, mtime, integrity: null, confidentiality: null, ext: null, language: null }
}

function file(name: string, ext = 'ts'): WorkspaceEntry {
  return {
    name,
    kind: 'file',
    sizeBytes: 8,
    mtime,
    integrity: 'duoc_nguoi_dung_cho_phep',
    confidentiality: 'cong_khai',
    ext,
    language: ext === 'py' ? 'python' : 'typescript',
  }
}

function listing(entries: WorkspaceEntry[], path = ''): WorkspaceListing {
  return { breadcrumb: [{ name: 'workspace', path }, ...(path ? [{ name: path, path }] : [])], entries }
}

const ROOT = listing([dir('src'), dir('tests'), dir('docs'), file('App.tsx'), file('plan.md', 'md')])
const SRC = listing([file('parser.py', 'py'), file('auth.py', 'py')], 'src')

function contentFor(path: string): WorkspaceContent {
  return { content: `// ${path}`, sizeBytes: path.length, mime: 'text/plain', language: 'typescript', binary: false }
}

/** Kho một repository đầy đủ, ghi đè theo `overrides`. */
function makeRepo(overrides?: Partial<WorkspaceRepository>): WorkspaceRepository {
  const base: WorkspaceRepository = {
    baseUrl: 'http://box.test',
    list: vi.fn(async (path: string) => (path === '' ? ROOT : SRC)),
    readText: vi.fn(async (path: string) => contentFor(path)),
    mediaUrl: (p: string) => `http://box.test/__box/file/media?path=${encodeURIComponent(p)}`,
    thumbnailUrl: (p: string) => `http://box.test/__box/file/thumbnail?path=${encodeURIComponent(p)}`,
    downloadUrl: (p: string) => `http://box.test/__box/file/download?path=${encodeURIComponent(p)}`,
    zip: vi.fn(async () => new Blob(['zip'])),
    upload: vi.fn(async (targetDir: string, filename: string) => ({ path: `${targetDir}/${filename}`, sizeBytes: 0 })),
    unzip: vi.fn(async () => ({ extracted: 0, skipped: 0, warnings: [] })),
  }
  return { ...base, ...overrides }
}

/** Đẩy hàng đợi microtask đủ nhiều để các hàm async trong hook chạy xong. */
async function settle() {
  await act(async () => {
    for (let i = 0; i < 6; i++) await Promise.resolve()
  })
}

async function mount(repository: WorkspaceRepository) {
  ;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
  // Tránh selectedFilePath còn sót từ test trước can thiệp vào mount đầu.
  useUiStore.getState().clearSelectedFile()
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  let latest: UseWorkspaceFilesResult | null = null

  function Probe() {
    latest = useWorkspaceFiles(repository)
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

describe('useWorkspaceFiles', () => {
  it('nạp danh sách gốc khi mount', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    expect(hook.state.cwd).toBe('')
    expect(hook.state.status).toBe('idle')
    expect(hook.state.filteredEntries.map((e) => e.name)).toEqual(['src', 'tests', 'docs', 'App.tsx', 'plan.md'])
    expect(repo.list).toHaveBeenCalledWith('', expect.any(AbortSignal))
    await hook.unmount()
  })

  it('navigate cập nhật cwd + danh sách mới', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.navigateTo('src')
    })
    await settle()

    expect(hook.state.cwd).toBe('src')
    expect(hook.state.filteredEntries.map((e) => e.name).sort()).toEqual(['auth.py', 'parser.py'])
    await hook.unmount()
  })

  it('expand nạp lười con vào cây và đánh dấu đã mở', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.expand('src')
    })
    await settle()

    expect(hook.state.expanded.has('src')).toBe(true)
    expect(repo.list).toHaveBeenCalledWith('src', expect.any(AbortSignal))
    const srcNode = hook.state.tree.find((n) => n.node.name === 'src')
    expect(srcNode?.loaded).toBe(true)
    expect(srcNode?.children.map((c) => c.node.name).sort()).toEqual(['auth.py', 'parser.py'])
    await hook.unmount()
  })

  it('chọn nhiều additive bật/tắt từng đường dẫn', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.toggleSelect('src')
    })
    expect([...hook.state.selected]).toEqual(['src'])

    await act(async () => {
      hook.state.toggleSelect('docs', true)
    })
    expect([...hook.state.selected].sort()).toEqual(['docs', 'src'])

    // Bật lại src (additive) → bỏ chọn src.
    await act(async () => {
      hook.state.toggleSelect('src', true)
    })
    expect([...hook.state.selected]).toEqual(['docs'])
    await hook.unmount()
  })

  it('open tải nội dung text cho file code', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.open('src/parser.py')
    })
    await settle()

    expect(hook.state.previewPath).toBe('src/parser.py')
    expect(hook.state.previewKind).toBe('code')
    expect(hook.state.previewContent?.content).toBe('// src/parser.py')
    expect(repo.readText).toHaveBeenCalledWith('src/parser.py', expect.any(AbortSignal))
    await hook.unmount()
  })

  it('bỏ response cũ khi navigate mới hoàn thành trước', async () => {
    let resolveRoot: ((value: WorkspaceListing) => void) | undefined
    const slowRoot = new Promise<WorkspaceListing>((resolve) => {
      resolveRoot = resolve
    })
    const repo = makeRepo({
      // Lần gọi 1 (mount → list('')) chậm; lần 2 (navigate → list('src')) nhanh.
      list: vi.fn().mockReturnValueOnce(slowRoot).mockResolvedValueOnce(SRC),
    })
    const hook = await mount(repo)
    expect(hook.state.status).toBe('loading')

    await act(async () => {
      hook.state.navigateTo('src')
    })
    await settle()
    expect(hook.state.cwd).toBe('src')

    // Response gốc đến muộn — phải bị drop, cwd không quay về ''.
    await act(async () => {
      resolveRoot?.(ROOT)
      await slowRoot
    })
    await settle()
    expect(hook.state.cwd).toBe('src')
    await hook.unmount()
  })

  it('open từ Tree View đồng bộ cwd về thư mục cha', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.open('src/parser.py')
    })
    await settle()

    expect(hook.state.cwd).toBe('src')
    expect(hook.state.previewPath).toBe('src/parser.py')
    await hook.unmount()
  })

  it('openInIde giữ gốc workspace và mở đúng file qua payload openFile', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.openInIde('src/parser.py')
    })

    const ideUrl = useUiStore.getState().ideLaunchUrl
    expect(ideUrl).not.toBeNull()
    const url = new URL(ideUrl!)
    expect(url.origin).toBe('http://localhost:8081')
    expect(url.searchParams.get('folder')).toBe('/home/agent/workspace')
    const decoded = JSON.parse(decodeURIComponent(url.searchParams.get('payload')!))
    expect(decoded).toEqual([
      ['gotoLineMode', 'true'],
      ['openFile', 'vscode-remote://localhost:8081/home/agent/workspace/src/parser.py'],
    ])
    await hook.unmount()
  })

  it('navigateTo đóng preview đang mở (hết kẹt overlay)', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.open('src/parser.py')
    })
    await settle()
    expect(hook.state.previewPath).toBe('src/parser.py')

    await act(async () => {
      hook.state.navigateTo('docs')
    })
    await settle()
    expect(hook.state.previewPath).toBeNull()
    expect(hook.state.cwd).toBe('docs')
    await hook.unmount()
  })

  it('setMode đóng preview khi chuyển Explorer ↔ Tree', async () => {
    const repo = makeRepo()
    const hook = await mount(repo)
    await settle()

    await act(async () => {
      hook.state.open('src/parser.py')
    })
    await settle()
    expect(hook.state.previewPath).toBe('src/parser.py')

    await act(async () => {
      hook.state.setMode('tree')
    })
    expect(hook.state.mode).toBe('tree')
    expect(hook.state.previewPath).toBeNull()
    await hook.unmount()
  })
})
