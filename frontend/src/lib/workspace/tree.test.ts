import { describe, expect, it } from 'vitest'
import {
  childPath,
  findNode,
  flattenVisible,
  mergeListing,
  sortEntries,
  toggleExpand,
  type WorkspaceTree,
} from './tree'
import type { WorkspaceEntry, WorkspaceListing } from './types'

const mtime = '2026-08-28T12:00:00Z'

function dir(name: string): WorkspaceEntry {
  return { name, kind: 'dir', sizeBytes: 0, mtime, integrity: null, confidentiality: null, ext: null, language: null }
}

function file(name: string): WorkspaceEntry {
  return { name, kind: 'file', sizeBytes: 10, mtime, integrity: null, confidentiality: null, ext: 'ts', language: 'typescript' }
}

function listing(entries: WorkspaceEntry[]): WorkspaceListing {
  return { breadcrumb: [{ name: 'workspace', path: '' }], entries }
}

describe('sortEntries', () => {
  it('đặt thư mục trước file rồi sắp theo tên', () => {
    const out = sortEntries([file('zeta.ts'), dir('src'), file('app.ts'), dir('docs')])
    expect(out.map((e) => e.name)).toEqual(['docs', 'src', 'app.ts', 'zeta.ts'])
  })

  it('không thay đổi mảng gốc', () => {
    const input = [file('zeta.ts'), dir('src')]
    sortEntries(input)
    expect(input.map((e) => e.name)).toEqual(['zeta.ts', 'src'])
  })
})

describe('childPath', () => {
  it('gốc + tên → chỉ tên', () => {
    expect(childPath('', 'src')).toBe('src')
  })
  it('cha có path → nối bằng slash', () => {
    expect(childPath('frontend/src', 'App.tsx')).toBe('frontend/src/App.tsx')
  })
})

describe('mergeListing', () => {
  it('path rỗng thay thế toàn bộ cấp gốc, sắp ổn định', () => {
    const roots = mergeListing('', listing([dir('src'), file('App.tsx')]), [])
    expect(roots.map((r) => r.node.name)).toEqual(['src', 'App.tsx'])
    expect(roots[0]!.path).toBe('src')
    expect(roots[0]!.loaded).toBe(false)
    expect(roots[0]!.expanded).toBe(false)
    expect(roots[1]!.loaded).toBe(true) // file vốn đã "nạp xong"
  })

  it('path con → gắn con vào nút đúng, đánh dấu loaded + expanded', () => {
    let roots = mergeListing('', listing([dir('src')]), [])
    roots = mergeListing('src', listing([file('parser.py'), file('auth.py')]), roots)
    const src = findNode(roots, 'src')
    expect(src?.expanded).toBe(true)
    expect(src?.loaded).toBe(true)
    expect(src?.children.map((c) => c.node.name)).toEqual(['auth.py', 'parser.py'])
    expect(src?.children[0]!.path).toBe('src/auth.py')
  })

  it('không đụng nhánh anh em khác', () => {
    let roots = mergeListing('', listing([dir('src'), dir('docs')]), [])
    roots = mergeListing('src', listing([file('a.py')]), roots)
    const docs = findNode(roots, 'docs')
    expect(docs?.loaded).toBe(false)
    expect(docs?.children).toHaveLength(0)
  })

  it('tự dựng chuỗi tổ tiên khi nạp thẳng đường dẫn sâu (chưa liệt kê root)', () => {
    // Mount với selectedFilePath: chỉ gọi mergeListing(parent,...) trên cây rỗng.
    const roots = mergeListing('src/apps', listing([file('main.ts')]), [])
    // Tổ tiên 'src' là dir tạm chưa nạp, 'apps' đã nạp và chứa file.
    const src = findNode(roots, 'src')
    expect(src).not.toBeNull()
    expect(src?.node.kind).toBe('dir')
    expect(src?.loaded).toBe(false)
    expect(src?.expanded).toBe(true)
    const apps = findNode(roots, 'src/apps')
    expect(apps?.loaded).toBe(true)
    expect(apps?.expanded).toBe(true)
    expect(apps?.children.map((c) => c.node.name)).toEqual(['main.ts'])
    expect(findNode(roots, 'src/apps/main.ts')?.node.name).toBe('main.ts')
  })
})

describe('toggleExpand', () => {
  it('đảo expanded mà không đổi con', () => {
    let roots = mergeListing('', listing([dir('src')]), [])
    roots = mergeListing('src', listing([file('a.py')]), roots)
    expect(findNode(roots, 'src')?.expanded).toBe(true)
    roots = toggleExpand('src', roots)
    expect(findNode(roots, 'src')?.expanded).toBe(false)
    expect(findNode(roots, 'src')?.children).toHaveLength(1)
  })
})

describe('findNode', () => {
  it('trả null cho path rỗng', () => {
    expect(findNode([], '')).toBeNull()
  })
  it('tìm nút lồng sâu', () => {
    let roots = mergeListing('', listing([dir('src')]), [])
    roots = mergeListing('src', listing([file('a.py')]), roots)
    expect(findNode(roots, 'src/a.py')?.node.name).toBe('a.py')
  })
  it('trả null khi đường dẫn không tồn tại', () => {
    const roots = mergeListing('', listing([dir('src')]), [])
    expect(findNode(roots, 'nope')).toBeNull()
    expect(findNode(roots, 'src/missing.py')).toBeNull()
  })
})

describe('flattenVisible', () => {
  it('chỉ duỗi con của nút đang mở', () => {
    let roots: WorkspaceTree[] = mergeListing('', listing([dir('src'), dir('docs')]), [])
    roots = mergeListing('src', listing([file('a.py'), file('b.py')]), roots)
    // 'docs' chưa mở → con ẩn; 'src' mở → con hiện ở depth 1
    const flat = flattenVisible(roots)
    expect(flat.map((f) => f.node.node.name)).toEqual(['docs', 'src', 'a.py', 'b.py'])
    expect(flat.map((f) => f.depth)).toEqual([0, 0, 1, 1])
  })
  it('đóng src → con biến khỏi danh sách phẳng', () => {
    let roots = mergeListing('', listing([dir('src')]), [])
    roots = mergeListing('src', listing([file('a.py')]), roots)
    roots = toggleExpand('src', roots)
    expect(flattenVisible(roots).map((f) => f.node.node.name)).toEqual(['src'])
  })
})
