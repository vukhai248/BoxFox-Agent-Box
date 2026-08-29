/**
 * Adapter mock cho test/demo — dựng từ cây `FileNode` của kịch bản.
 *
 * Chuyển `FileNode` → `WorkspaceEntry`, phục vụ `readText` từ `node.content`
 * (hoặc văn bản mẫu tổng hợp khi thiếu). `zip` trả Blob chứa JSON tên file —
 * đủ cho unit test, không nén thật.
 */
import type { FileNode } from '../../types/ui'
import { buildWorkspace } from '../mock/workspace'
import { extOf, languageForExt } from './languages'
import { basename, childPath, sortEntries } from './tree'
import type { WorkspaceContent, WorkspaceCrumb, WorkspaceEntry, WorkspaceListing, WorkspaceRepository } from './types'

function toEntry(node: FileNode): WorkspaceEntry {
  const ext = node.kind === 'file' ? extOf(node.name) : null
  return {
    name: node.name,
    kind: node.kind,
    sizeBytes: node.content ? node.content.length : 0,
    mtime: '2026-08-27T00:00:00Z',
    integrity: node.integrity ?? null,
    confidentiality: node.confidentiality ?? null,
    ext,
    language: node.kind === 'file' ? languageForExt(ext) : null,
  }
}

function buildBreadcrumb(path: string): WorkspaceCrumb[] {
  const crumbs: WorkspaceCrumb[] = [{ name: 'workspace', path: '' }]
  if (path === '') return crumbs
  let walked = ''
  for (const seg of path.split('/')) {
    walked = walked ? `${walked}/${seg}` : seg
    crumbs.push({ name: seg, path: walked })
  }
  return crumbs
}

function synthesizedSample(path: string): string {
  return `# ${basename(path)}\n\n(Không có nội dung xem trước trong mock.)\n`
}

export class MockWorkspaceRepository implements WorkspaceRepository {
  readonly baseUrl = 'mock://workspace'
  private readonly roots: FileNode[]

  constructor() {
    // Trạng thái "đã sửa parser + đã có plan" — đủ phong phú để demo hai chế độ xem.
    this.roots = buildWorkspace({ parserFixed: true, withPlan: true, authInjected: false })
  }

  async list(path: string): Promise<WorkspaceListing> {
    const entries = this.entriesAt(path)
    return { breadcrumb: buildBreadcrumb(path), entries: sortEntries(entries) }
  }

  async readText(path: string): Promise<WorkspaceContent> {
    const node = this.findFile(path)
    const content = node?.content ?? synthesizedSample(path)
    return {
      content,
      sizeBytes: content.length,
      mime: 'text/plain',
      language: languageForExt(extOf(basename(path))),
      binary: false,
    }
  }

  mediaUrl(path: string): string {
    return `mock://workspace/file/media?path=${encodeURIComponent(path)}`
  }
  thumbnailUrl(path: string): string {
    return `mock://workspace/file/thumbnail?path=${encodeURIComponent(path)}`
  }
  downloadUrl(path: string): string {
    return `mock://workspace/file/download?path=${encodeURIComponent(path)}`
  }

  async zip(paths: string[]): Promise<Blob> {
    return new Blob([JSON.stringify({ paths }, null, 2)], { type: 'application/json' })
  }

  async upload(targetDir: string, filename: string): Promise<{ path: string; sizeBytes: number }> {
    return { path: childPath(targetDir, filename), sizeBytes: 0 }
  }

  async unzip(path: string): Promise<{ extracted: number; skipped: number; warnings: string[] }> {
    return { extracted: 0, skipped: 0, warnings: [`Mock: không giải nén thật ${path}`] }
  }

  private navigate(path: string): FileNode | null {
    if (path === '') return null
    let level: FileNode[] = this.roots
    let current: FileNode | null = null
    for (const seg of path.split('/')) {
      const found = level.find((node) => node.name === seg)
      if (!found) return null
      current = found
      level = found.children ?? []
    }
    return current
  }

  private entriesAt(path: string): WorkspaceEntry[] {
    if (path === '') return this.roots.map(toEntry)
    const dir = this.navigate(path)
    if (!dir || dir.kind !== 'dir' || !dir.children) return []
    return dir.children.map(toEntry)
  }

  private findFile(path: string): FileNode | null {
    const node = this.navigate(path)
    return node && node.kind === 'file' ? node : null
  }
}
