/**
 * Hàm thuần dựng/quản lý cây thư mục cho chế độ Tree.
 *
 * Cây được nạp lười: `mergeListing` gắn con vào một nút thư mục sau khi `list()`
 * trả về. `flattenVisible` duỗi cây thành danh sách phẳng ổn định (để render với
 * vạch lùi + số cấp), tôn trọng `expanded` trên từng nút.
 */
import type { FileNode, FileNodeKind } from '../../types/ui'
import type { WorkspaceEntry, WorkspaceListing } from './types'

/** Dữ liệu nút — có thể là `WorkspaceEntry` (từ listing) hoặc `FileNode` (mock seed). */
export type TreeData = WorkspaceEntry | FileNode

export interface WorkspaceTree {
  /** Đường dẫn tương đối đầy đủ — dùng làm id ổn định cho React key. */
  path: string
  node: TreeData
  expanded: boolean
  /** `true` khi con đã được nạp (thư mục) hoặc vốn là file. */
  loaded: boolean
  children: WorkspaceTree[]
}

export interface FlatNode {
  node: WorkspaceTree
  depth: number
}

export function nodeName(node: TreeData): string {
  return node.name
}
export function nodeKind(node: TreeData): FileNodeKind {
  return node.kind
}
export function isDir(node: TreeData): boolean {
  return node.kind === 'dir'
}

/** Sắp xếp: thư mục trước file, rồi theo tên (locale vi). */
export function sortEntries<T extends { name: string; kind: FileNodeKind }>(entries: readonly T[]): T[] {
  return [...entries].sort((a, b) => {
    if (a.kind !== b.kind) return a.kind === 'dir' ? -1 : 1
    return a.name.localeCompare(b.name, 'vi')
  })
}

export function childPath(parentPath: string, name: string): string {
  return parentPath ? `${parentPath}/${name}` : name
}

/** Phần tên cuối của một đường dẫn tương đối (sau dấu `/` cuối cùng). */
export function basename(path: string): string {
  const i = path.lastIndexOf('/')
  return i < 0 ? path : path.slice(i + 1)
}

function sortTreeNodes(nodes: WorkspaceTree[]): WorkspaceTree[] {
  return [...nodes].sort((a, b) => {
    if (a.node.kind !== b.node.kind) return a.node.kind === 'dir' ? -1 : 1
    return a.node.name.localeCompare(b.node.name, 'vi')
  })
}

function entriesToChildren(parentPath: string, entries: readonly WorkspaceEntry[]): WorkspaceTree[] {
  return sortEntries(entries).map((entry) => ({
    path: childPath(parentPath, entry.name),
    node: entry,
    expanded: false,
    loaded: entry.kind !== 'dir',
    children: [],
  }))
}

/** Cập nhật (bất biến, dọc theo đường dẫn) nút tại `path` bằng `fn`. */
function updateAtPath(
  roots: WorkspaceTree[],
  path: string,
  fn: (node: WorkspaceTree) => WorkspaceTree,
): WorkspaceTree[] {
  const segments = path.split('/')
  const walk = (nodes: WorkspaceTree[], depth: number): WorkspaceTree[] => {
    const seg = segments[depth]!
    return nodes.map((node) => {
      if (node.node.name === seg) {
        if (depth === segments.length - 1) return fn(node)
        return { ...node, children: walk(node.children, depth + 1) }
      }
      return node
    })
  }
  return walk(roots, 0)
}

/** Nút thư mục tạm (chưa nạp) để dựng chuỗi tổ tiên khi mở trực tiếp một đường dẫn sâu. */
function dirPlaceholder(path: string, name: string): WorkspaceTree {
  return {
    path,
    node: { path, name, kind: 'dir' },
    expanded: true,
    loaded: false,
    children: [],
  }
}

/**
 * Đảm bảo chuỗi thư mục tổ tiên của `segments` tồn tại trong cây. Nếu thiếu một
 * tổ tiên (do chưa từng liệt kê root), dựng nút dir tạm `loaded=false, expanded=true`
 * để `mergeListing` có chỗ gắn con — giữ cho chế độ Tree không trống khi mount với
 * `selectedFilePath` mà chỉ nạp thẳng thư mục cha.
 */
function ensureAncestors(
  nodes: WorkspaceTree[],
  segments: string[],
  depth: number,
  basePath: string,
): WorkspaceTree[] {
  if (depth >= segments.length) return nodes
  const seg = segments[depth]!
  const segPath = childPath(basePath, seg)
  const index = nodes.findIndex((n) => n.node.name === seg)
  if (index >= 0) {
    const found = nodes[index]!
    const nextChildren = ensureAncestors(found.children, segments, depth + 1, segPath)
    if (nextChildren === found.children) return nodes
    const next = nodes.slice()
    next[index] = { ...found, children: nextChildren }
    return next
  }
  const placeholder = dirPlaceholder(segPath, seg)
  const nextChildren =
    depth === segments.length - 1 ? placeholder.children : ensureAncestors([], segments, depth + 1, segPath)
  return [...nodes, { ...placeholder, children: nextChildren }]
}

/**
 * Gắn kết quả `list(path)` vào cây. Với root (`path === ''`) thay thế toàn bộ cấp
 * gốc; với thư mục con thì gắn con, đánh dấu `loaded` + `expanded` (tự dựng chuỗi
 * tổ tiên nếu thiếu).
 */
export function mergeListing(path: string, listing: WorkspaceListing, roots: WorkspaceTree[]): WorkspaceTree[] {
  if (path === '') return entriesToChildren('', listing.entries)
  const chained = ensureAncestors(roots, path.split('/'), 0, '')
  return updateAtPath(chained, path, (node) => ({
    ...node,
    expanded: true,
    loaded: true,
    children: entriesToChildren(path, listing.entries),
  }))
}

/** Đảo `expanded` của nút tại `path`. */
export function toggleExpand(path: string, roots: WorkspaceTree[]): WorkspaceTree[] {
  return updateAtPath(roots, path, (node) => ({ ...node, expanded: !node.expanded }))
}

/** Tìm nút theo đường dẫn đầy đủ, hoặc `null`. */
export function findNode(roots: WorkspaceTree[], path: string): WorkspaceTree | null {
  if (path === '') return null
  const segments = path.split('/')
  let level = roots
  for (let depth = 0; depth < segments.length; depth++) {
    const seg = segments[depth]!
    const found = level.find((node) => node.node.name === seg)
    if (!found) return null
    if (depth === segments.length - 1) return found
    level = found.children
  }
  return null
}

/** Duỗi cây thành danh sách phẳng theo thứ tự ổn định, chỉ xuống cấp con của nút đang mở. */
export function flattenVisible(roots: WorkspaceTree[]): FlatNode[] {
  const out: FlatNode[] = []
  const walk = (nodes: WorkspaceTree[], depth: number) => {
    for (const node of sortTreeNodes(nodes)) {
      out.push({ node, depth })
      if (node.expanded && node.children.length > 0) {
        walk(node.children, depth + 1)
      }
    }
  }
  walk(roots, 0)
  return out
}
