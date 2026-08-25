/**
 * VS Code-Style Workspace File Explorer & Code Studio.
 * - Cột trái: Cây thư mục đa cấp chuẩn VS Code, icon màu nhận diện theo định dạng, nhãn bảo mật IFC, lọc tìm kiếm.
 * - Cột phải: Trình đọc mã nguồn chuyên nghiệp với hệ thống File Tabs, Breadcrumb, Line Numbers, và thẻ Clearance.
 */
import { useState, useMemo, useEffect } from 'react'
import {
  Folder,
  FolderOpen,
  FileCode,
  FileText,
  KeyRound,
  FileJson,
  File,
  ChevronRight,
  ChevronDown,
  X,
  Copy,
  Check,
  Search,
  Minimize2,
  Maximize2,
  WrapText,
  Code2,
  Sparkles,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { LabelDot } from '../LabelDot'
import type { FileNode } from '../../types/ui'

// Helper: Lấy icon và màu tương ứng với đuôi file
function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase() || ''
  if (filename === '.env' || filename.endsWith('.env')) {
    return <KeyRound className="size-3.5 text-amber-500 shrink-0" />
  }
  if (['py', 'pyw'].includes(ext)) {
    return <FileCode className="size-3.5 text-blue-400 shrink-0" />
  }
  if (['ts', 'tsx', 'js', 'jsx'].includes(ext)) {
    return <Code2 className="size-3.5 text-cyan-400 shrink-0" />
  }
  if (['md', 'markdown', 'txt', 'rst'].includes(ext)) {
    return <FileText className="size-3.5 text-emerald-400 shrink-0" />
  }
  if (['json', 'yaml', 'yml', 'toml'].includes(ext)) {
    return <FileJson className="size-3.5 text-orange-400 shrink-0" />
  }
  return <File className="size-3.5 text-muted shrink-0" />
}

// Helper: Tìm node file theo đường dẫn
function findFileByPath(nodes: FileNode[], path: string): FileNode | null {
  for (const node of nodes) {
    if (node.path === path) return node
    if (node.children) {
      const found = findFileByPath(node.children, path)
      if (found) return found
    }
  }
  return null
}

// Helper: Lấy toàn bộ file lá
function getAllLeafFiles(nodes: FileNode[]): FileNode[] {
  const result: FileNode[] = []
  function traverse(list: FileNode[]) {
    for (const n of list) {
      if (n.kind === 'file') result.push(n)
      if (n.children) traverse(n.children)
    }
  }
  traverse(nodes)
  return result
}

export function FileTreePanel() {
  const files = useAgentStore((s) => s.files)
  const selectedPath = useUiStore((s) => s.selectedFilePath)
  const selectFile = useUiStore((s) => s.selectFile)

  // Danh sách các file đang mở dạng Tab
  const [openTabs, setOpenTabs] = useState<string[]>(['src/parser.py'])
  const [activeTabPath, setActiveTabPath] = useState<string>('src/parser.py')
  const [searchQuery, setSearchQuery] = useState('')
  const [copied, setCopied] = useState(false)
  const [wrapText, setWrapText] = useState(false)
  const [explorerCollapsed, setExplorerCollapsed] = useState(false)
  const [treeExpanded, setTreeExpanded] = useState<Record<string, boolean>>({
    src: true,
    tests: true,
    vendor: true,
    'vendor/lib': true,
  })

  // Tự động mở tab khi selectedFilePath từ nơi khác gọi vào
  useEffect(() => {
    if (selectedPath) {
      setOpenTabs((prev) => (prev.includes(selectedPath) ? prev : [...prev, selectedPath]))
      setActiveTabPath(selectedPath)
    }
  }, [selectedPath])

  // File đang được active
  const activeFileNode = useMemo(() => {
    if (!activeTabPath) return null
    return findFileByPath(files, activeTabPath)
  }, [files, activeTabPath])

  // Xử lý khi bấm vào 1 file trong cây
  const handleSelectFile = (path: string) => {
    selectFile(path)
    if (!openTabs.includes(path)) {
      setOpenTabs((prev) => [...prev, path])
    }
    setActiveTabPath(path)
  }

  // Đóng 1 tab
  const handleCloseTab = (e: React.MouseEvent, path: string) => {
    e.stopPropagation()
    const nextTabs = openTabs.filter((p) => p !== path)
    setOpenTabs(nextTabs)
    if (activeTabPath === path) {
      const newActive = nextTabs[nextTabs.length - 1] || ''
      setActiveTabPath(newActive)
      selectFile(newActive)
    }
  }

  const handleCopyCode = () => {
    if (activeFileNode?.content) {
      navigator.clipboard.writeText(activeFileNode.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    }
  }

  const toggleFolder = (path: string) => {
    setTreeExpanded((prev) => ({ ...prev, [path]: !prev[path] }))
  }

  const handleCollapseAll = () => {
    setTreeExpanded({})
  }

  const handleExpandAll = () => {
    const allDirs: Record<string, boolean> = {}
    function collect(list: FileNode[]) {
      for (const n of list) {
        if (n.kind === 'dir') {
          allDirs[n.path] = true
          if (n.children) collect(n.children)
        }
      }
    }
    collect(files)
    setTreeExpanded(allDirs)
  }

  // Danh sách file đã lọc khi search
  const leafFiles = useMemo(() => getAllLeafFiles(files), [files])
  const filteredLeafFiles = useMemo(() => {
    if (!searchQuery.trim()) return []
    const q = searchQuery.toLowerCase()
    return leafFiles.filter((f) => f.path.toLowerCase().includes(q) || f.name.toLowerCase().includes(q))
  }, [leafFiles, searchQuery])

  // Đếm số dòng nội dung file
  const fileLines = useMemo(() => {
    if (!activeFileNode?.content) return []
    return activeFileNode.content.split('\n')
  }, [activeFileNode])

  return (
    <div className="flex h-full min-h-0 bg-bg text-fg select-none overflow-hidden">
      {/* ========================================================================= */}
      {/* LEFT COLUMN: VS CODE FILE EXPLORER (260px) */}
      {/* ========================================================================= */}
      {!explorerCollapsed ? (
        <aside className="w-64 shrink-0 border-r border-line bg-panel flex flex-col min-h-0">
          {/* Explorer Header */}
          <div className="flex items-center justify-between px-3 py-2 border-b border-line bg-panel2/60">
            <span className="text-[11px] font-bold tracking-wider uppercase text-muted">
              Explorer
            </span>
            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={handleExpandAll}
                className="rounded p-1 text-muted hover:text-fg hover:bg-panel transition cursor-pointer"
                title="Expand All Folders"
              >
                <Maximize2 className="size-3" />
              </button>
              <button
                type="button"
                onClick={handleCollapseAll}
                className="rounded p-1 text-muted hover:text-fg hover:bg-panel transition cursor-pointer"
                title="Collapse All Folders"
              >
                <Minimize2 className="size-3" />
              </button>
              <button
                type="button"
                onClick={() => setExplorerCollapsed(true)}
                className="rounded p-1 text-muted hover:text-fg hover:bg-panel transition cursor-pointer"
                title="Hide Explorer"
              >
                <X className="size-3" />
              </button>
            </div>
          </div>

          {/* Search Filter Input */}
          <div className="p-2 border-b border-line bg-panel2/30">
            <div className="relative flex items-center rounded-md border border-line bg-panel px-2 py-1">
              <Search className="size-3 text-muted mr-1.5 shrink-0" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search files..."
                className="w-full bg-transparent text-[11px] text-fg placeholder:text-muted outline-hidden"
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="text-muted hover:text-fg"
                >
                  <X className="size-3" />
                </button>
              )}
            </div>
          </div>

          {/* Root Project Header */}
          <div className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-bold text-fg/80 border-b border-line/40 bg-panel2/20">
            <ChevronDown className="size-3.5 text-muted" />
            <span className="truncate uppercase tracking-wider text-[10px]">WORKSPACE: CLOUD-AGENT-P</span>
          </div>

          {/* Tree View Content */}
          <div className="flex-1 overflow-y-auto py-1 px-1 text-xs">
            {searchQuery.trim() ? (
              <div className="space-y-0.5">
                <div className="px-2 py-1 text-[10px] font-bold uppercase tracking-wider text-muted">
                  Search Results ({filteredLeafFiles.length})
                </div>
                {filteredLeafFiles.map((file) => (
                  <button
                    key={file.path}
                    type="button"
                    onClick={() => handleSelectFile(file.path)}
                    className={`flex w-full items-center justify-between rounded-md px-2 py-1 text-left text-xs transition cursor-pointer ${
                      activeTabPath === file.path
                        ? 'bg-brand/15 text-brand font-semibold'
                        : 'text-muted hover:bg-panel2 hover:text-fg'
                    }`}
                  >
                    <div className="flex items-center gap-1.5 truncate">
                      {getFileIcon(file.name)}
                      <span className="truncate">{file.path}</span>
                    </div>
                    {file.integrity && (
                      <LabelDot integrity={file.integrity} confidentiality={file.confidentiality} />
                    )}
                  </button>
                ))}
              </div>
            ) : files.length === 0 ? (
              <div className="flex flex-col items-center justify-center p-6 text-center text-muted">
                <Folder className="size-6 text-muted/40 mb-2" />
                <p className="text-xs font-semibold text-fg">No files loaded</p>
                <p className="text-[10px] text-muted">Workspace files will appear once connected.</p>
              </div>
            ) : (
              files.map((node) => (
                <VSCodeTreeNode
                  key={node.path}
                  node={node}
                  depth={0}
                  selectedPath={activeTabPath}
                  expandedMap={treeExpanded}
                  onToggleFolder={toggleFolder}
                  onSelectFile={handleSelectFile}
                />
              ))
            )}
          </div>
        </aside>
      ) : (
        <button
          type="button"
          onClick={() => setExplorerCollapsed(false)}
          className="w-7 shrink-0 border-r border-line bg-panel flex flex-col items-center py-3 text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
          title="Show File Explorer"
        >
          <Folder className="size-4" />
        </button>
      )}

      {/* ========================================================================= */}
      {/* RIGHT COLUMN: VS CODE CODE EDITOR STUDIO */}
      {/* ========================================================================= */}
      <main className="flex-1 flex flex-col min-w-0 bg-panel overflow-hidden">
        {/* Top File Tabs Bar */}
        <div className="flex items-center border-b border-line bg-panel2/60 overflow-x-auto no-scrollbar select-none">
          {openTabs.map((tabPath) => {
            const fileName = tabPath.split('/').pop() || tabPath
            const isActive = activeTabPath === tabPath

            return (
              <div
                key={tabPath}
                onClick={() => {
                  setActiveTabPath(tabPath)
                  selectFile(tabPath)
                }}
                className={`group relative flex items-center gap-2 border-r border-line px-3.5 py-2 text-xs transition cursor-pointer ${
                  isActive
                    ? 'bg-panel text-fg font-semibold border-t-2 border-t-brand shadow-xs'
                    : 'bg-panel2/40 text-muted hover:text-fg hover:bg-panel2'
                }`}
              >
                {getFileIcon(fileName)}
                <span className="truncate max-w-[140px]">{fileName}</span>
                <button
                  type="button"
                  onClick={(e) => handleCloseTab(e, tabPath)}
                  className="rounded p-0.5 text-muted opacity-60 hover:opacity-100 hover:bg-panel2 hover:text-fg transition ml-1"
                  title="Close file (Ctrl+W)"
                >
                  <X className="size-3" />
                </button>
              </div>
            )
          })}

          {openTabs.length === 0 && (
            <div className="px-4 py-2 text-xs text-muted italic">No files open</div>
          )}
        </div>

        {/* Active Editor / Code Viewer */}
        {activeFileNode ? (
          <div className="flex-1 flex flex-col min-h-0 overflow-hidden bg-panel">
            {/* Editor Subheader: Breadcrumb & Actions */}
            <div className="flex items-center justify-between border-b border-line px-4 py-2 bg-panel2/30 text-xs select-none">
              {/* Breadcrumb Path */}
              <div className="flex items-center gap-1.5 font-mono text-[11px] text-muted truncate">
                <span>workspace</span>
                {activeFileNode.path.split('/').map((seg, idx, arr) => (
                  <span key={seg} className="flex items-center gap-1.5">
                    <span>›</span>
                    <span className={idx === arr.length - 1 ? 'font-bold text-fg' : ''}>{seg}</span>
                  </span>
                ))}
                <span className="ml-2 rounded bg-panel px-1.5 py-0.2 text-[10px] font-mono text-muted border border-line">
                  {fileLines.length} lines • {activeFileNode.content?.length || 0} bytes
                </span>
              </div>

              {/* Right Side: Security Clearance Badge & Actions */}
              <div className="flex items-center gap-3">
                {/* Security Tag */}
                <div className="flex items-center gap-2 rounded-md bg-panel border border-line px-2 py-1 text-[11px]">
                  <LabelDot integrity={activeFileNode.integrity} confidentiality={activeFileNode.confidentiality} />
                  <span className="font-mono text-[10px] text-fg font-semibold">
                    {activeFileNode.integrity === 'duoc_nguoi_dung_cho_phep' ? (
                      <span className="text-emerald-500">Authorized</span>
                    ) : (
                      <span className="text-amber-500">Untrusted</span>
                    )}
                  </span>
                  <span>•</span>
                  <span className="font-mono text-[10px] text-muted capitalize">
                    {activeFileNode.confidentiality || 'Internal'}
                  </span>
                </div>

                {/* Wrap Toggle */}
                <button
                  type="button"
                  onClick={() => setWrapText(!wrapText)}
                  className={`rounded-md p-1.5 text-xs transition cursor-pointer border ${
                    wrapText
                      ? 'bg-brand/15 text-brand border-brand/40'
                      : 'border-line bg-panel text-muted hover:text-fg'
                  }`}
                  title="Toggle Word Wrap"
                >
                  <WrapText className="size-3.5" />
                </button>

                {/* Copy Code */}
                <button
                  type="button"
                  onClick={handleCopyCode}
                  className="flex items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 py-1 text-xs font-semibold text-fg hover:border-brand transition cursor-pointer shadow-xs"
                  title="Copy File Content"
                >
                  {copied ? (
                    <>
                      <Check className="size-3.5 text-emerald-500" />
                      <span className="text-emerald-500">Copied</span>
                    </>
                  ) : (
                    <>
                      <Copy className="size-3.5" />
                      <span>Copy</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {/* Code Body with Line Numbers */}
            <div className="flex-1 min-h-0 overflow-auto flex text-xs font-mono select-text bg-panel">
              {/* Line Numbers Gutter */}
              <div className="select-none py-4 px-3 text-right text-muted/50 border-r border-line/50 bg-panel2/20 font-mono text-xs leading-relaxed min-w-[42px]">
                {fileLines.map((_, idx) => (
                  <div key={idx} className="h-5 leading-5 text-[11px]">
                    {idx + 1}
                  </div>
                ))}
              </div>

              {/* Code Lines Container */}
              <div
                className={`flex-1 py-4 px-4 text-fg leading-relaxed font-mono text-xs overflow-x-auto select-text ${
                  wrapText ? 'whitespace-pre-wrap break-words' : 'whitespace-pre'
                }`}
              >
                {fileLines.map((line, idx) => (
                  <div key={idx} className="h-5 leading-5 select-text hover:bg-panel2/40 px-1 rounded-xs">
                    {line || ' '}
                  </div>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Empty State (When no file is selected) */
          <div className="flex-1 flex flex-col items-center justify-center p-8 text-center bg-panel select-none">
            <div className="flex size-14 items-center justify-center rounded-2xl bg-brand/10 text-brand border border-brand/20 mb-4 shadow-xs">
              <Sparkles className="size-7" />
            </div>
            <h3 className="text-base font-bold text-fg">BoxFox Code Studio</h3>
            <p className="text-xs text-muted max-w-sm mt-1 mb-6">
              Select a file from the Explorer on the left to inspect syntax, analyze provenance labels, or verify code changes.
            </p>

            <div className="grid grid-cols-1 gap-2 text-xs text-muted font-mono bg-panel2 p-4 rounded-xl border border-line text-left">
              <div className="flex items-center gap-3">
                <span className="rounded bg-panel px-1.5 py-0.5 text-fg border border-line">Click File</span>
                <span>Open in editor tab</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="rounded bg-panel px-1.5 py-0.5 text-fg border border-line">Search</span>
                <span>Filter workspace tree</span>
              </div>
              <div className="flex items-center gap-3">
                <span className="rounded bg-panel px-1.5 py-0.5 text-fg border border-line">IFC Dot</span>
                <span>Inspect security clearance</span>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

// Subcomponent: Recursive Tree Node
function VSCodeTreeNode({
  node,
  depth,
  selectedPath,
  expandedMap,
  onToggleFolder,
  onSelectFile,
}: {
  node: FileNode
  depth: number
  selectedPath: string
  expandedMap: Record<string, boolean>
  onToggleFolder: (path: string) => void
  onSelectFile: (path: string) => void
}) {
  const isDir = node.kind === 'dir'
  const isExpanded = !!expandedMap[node.path]
  const isSelected = selectedPath === node.path

  return (
    <div>
      <button
        type="button"
        onClick={() => (isDir ? onToggleFolder(node.path) : onSelectFile(node.path))}
        className={`group flex w-full items-center justify-between rounded-md py-1 pr-2 text-left text-xs transition cursor-pointer ${
          isSelected
            ? 'bg-brand/15 text-brand font-semibold shadow-xs'
            : 'text-muted hover:bg-panel2 hover:text-fg'
        }`}
        style={{ paddingLeft: `${depth * 14 + 6}px` }}
      >
        <div className="flex items-center gap-1.5 min-w-0 flex-1">
          {/* Chevron for folder */}
          {isDir ? (
            <span className="text-muted/70 group-hover:text-fg">
              {isExpanded ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
            </span>
          ) : (
            <span className="w-3.5 shrink-0" />
          )}

          {/* Icon */}
          {isDir ? (
            isExpanded ? (
              <FolderOpen className="size-3.5 text-amber-400 shrink-0" />
            ) : (
              <Folder className="size-3.5 text-amber-400 shrink-0" />
            )
          ) : (
            getFileIcon(node.name)
          )}

          {/* Name */}
          <span className="truncate text-xs">{node.name}</span>
        </div>

        {/* Security IFC Dot for files */}
        {!isDir && node.integrity && (
          <div className="shrink-0 ml-1">
            <LabelDot integrity={node.integrity} confidentiality={node.confidentiality} />
          </div>
        )}
      </button>

      {/* Children if open */}
      {isDir && isExpanded && node.children && (
        <div className="space-y-0.5">
          {node.children.map((child) => (
            <VSCodeTreeNode
              key={child.path}
              node={child}
              depth={depth + 1}
              selectedPath={selectedPath}
              expandedMap={expandedMap}
              onToggleFolder={onToggleFolder}
              onSelectFile={onSelectFile}
            />
          ))}
        </div>
      )}
    </div>
  )
}
