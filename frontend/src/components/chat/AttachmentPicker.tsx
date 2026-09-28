/**
 * Menu đính kèm tài liệu & ngữ cảnh (AttachmentPicker / Action Palette) tại nút [+] của Chat Input Bar.
 * - Files & Folders: Tải ảnh, tệp văn bản / mã nguồn hoặc toàn bộ thư mục dự án (webkitdirectory).
 * - Repositories: Chọn kho lưu trữ git đính kèm phiên.
 * - Modes & Goals: Kích hoạt nhanh Autopilot, Plan mode, Research mode, Design mode.
 * - Google Drive: chưa nối — hiển thị trạng thái "Not connected / Chưa kết nối".
 *
 * Hai bất biến của đợt 22 (BUG-39, BUG-40 — `docs/plan/…`, kế hoạch v1 Phần A):
 * 1. Popover render qua `createPortal` vào `document.body` — hàng công cụ của
 *    `ChatInputBar` có `overflow-hidden`, nên popover `absolute` bị CẮT và mục
 *    menu không bấm được. Cách chữa là portal + vị trí tính từ `getBoundingClientRect()`.
 * 2. Đối tượng `File` thật được GIỮ trong `AttachedFile.file` (kèm
 *    `sizeBytes`/`relativePath`) — tệp gửi nội dung thật lên box.
 */
import { useEffect, useRef, useState, useContext } from 'react'
import { createPortal } from 'react-dom'
import {
  Plus,
  Paperclip,
  FolderUp,
  GitFork,
  Target,
  Lightbulb,
  Microscope,
  Palette,
  ChevronRight,
} from 'lucide-react'
import { RepoPickerView } from './RepoPicker'
import { I18nContext, lookup, interpolate } from '../../i18n/context'
import en from '../../i18n/en'

export interface AttachedFile {
  id: string
  name: string
  source: 'computer' | 'drive'
  size?: string
  dataUrl?: string
  /** Đối tượng File thật — nguồn duy nhất để gửi nội dung lên box (BUG-40). */
  file?: File
  /** `webkitRelativePath` khi chọn cả thư mục; `undefined` khi chọn tệp lẻ. */
  relativePath?: string
  /** Kích thước thật theo byte (`file.size`); trần phía client đếm theo trường này. */
  sizeBytes?: number
}

/** Trần phía client (kế hoạch v1 Phần A, A2.3): chặn trước khi tốn một lượt gửi. */
export const MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
export const MAX_ATTACHMENTS_PER_TURN = 20
export const MAX_ATTACHMENT_BYTES_PER_TURN = 100 * 1024 * 1024

/** Kích thước hiển thị trên chip — không hiện chuỗi byte thô. */
export function formatAttachmentSize(bytes?: number): string {
  if (!bytes || bytes <= 0) return '0 KB'
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

/** Tên đường dẫn rút gọn cho chip: giữ đuôi, cắt đầu khi quá dài. */
export function shortenAttachmentPath(path: string, max = 28): string {
  if (path.length <= max) return path
  return `…${path.slice(path.length - max + 1)}`
}

const PANEL_WIDTH = 384
const PANEL_HEIGHT = 380

export interface AttachmentPickerProps {
  onAttach: (file: AttachedFile) => void
  /** Số tệp đã nằm trong chip của lượt này (trần `MAX_ATTACHMENTS_PER_TURN`). */
  existingCount?: number
  /** Tổng byte đã nằm trong chip của lượt này (trần `MAX_ATTACHMENT_BYTES_PER_TURN`). */
  existingBytes?: number
  // Quick Actions optional integrations
  onToggleAutopilot?: () => void
  autopilotEnabled?: boolean
  onSelectPlan?: () => void
  onToggleResearch?: () => void
  researchEnabled?: boolean
  onToggleDesign?: () => void
  designEnabled?: boolean
  selectedRepoIds?: string[]
  onToggleRepo?: (id: string) => void
}

export function AttachmentPicker({
  onAttach,
  existingCount = 0,
  existingBytes = 0,
  onToggleAutopilot,
  autopilotEnabled = false,
  onSelectPlan,
  onToggleResearch,
  researchEnabled = false,
  onToggleDesign,
  designEnabled = false,
  selectedRepoIds: externalRepoIds,
  onToggleRepo,
}: AttachmentPickerProps) {
  const i18n = useContext(I18nContext)
  const t = i18n?.t ?? ((key: string, vars?: Record<string, string | number>) => {
    const raw = lookup(en, key) ?? key
    return interpolate(raw, vars)
  })
  const [open, setOpen] = useState(false)
  const [view, setView] = useState<'menu' | 'repos'>('menu')
  const [error, setError] = useState<string | null>(null)
  const [panelPosition, setPanelPosition] = useState<{ left: number; width: number; bottom: number } | null>(null)
  const [localRepoIds, setLocalRepoIds] = useState<string[]>([])
  const triggerRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const imageInputRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const idSeqRef = useRef(0)

  const selectedRepoIds = externalRepoIds ?? localRepoIds
  const defaultToggleRepo = (id: string) => {
    setLocalRepoIds((prev) =>
      prev.includes(id) ? prev.filter((r) => r !== id) : [...prev, id],
    )
  }

  // Ngoài-click kiểm cả nút trigger [+] lẫn panel
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as Node
      if (triggerRef.current?.contains(target)) return
      if (panelRef.current?.contains(target)) return
      setOpen(false)
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }

    if (open) {
      document.addEventListener('mousedown', handleClickOutside)
      document.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [open])

  // Reset view về menu khi đóng
  useEffect(() => {
    if (!open) {
      setView('menu')
    }
  }, [open])

  // Vị trí panel bám theo chat-input-bar để có bề rộng bằng thanh chat
  useEffect(() => {
    if (!open) return

    const updatePosition = () => {
      const trigger = triggerRef.current
      if (!trigger) return

      const chatBar = trigger.closest('[data-testid="chat-input-bar"]') as HTMLElement | null
      if (chatBar) {
        const cRect = chatBar.getBoundingClientRect()
        const bottom = Math.max(8, window.innerHeight - cRect.top + 8)
        setPanelPosition({
          left: cRect.left,
          width: cRect.width,
          bottom,
        })
      } else {
        const rect = trigger.getBoundingClientRect()
        const maxBottom = Math.max(8, window.innerHeight - PANEL_HEIGHT - 8)
        setPanelPosition({
          left: Math.max(8, Math.min(rect.left, window.innerWidth - PANEL_WIDTH - 8)),
          width: PANEL_WIDTH,
          bottom: Math.min(Math.max(8, window.innerHeight - rect.top + 8), maxBottom),
        })
      }
    }

    updatePosition()
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open])

  const handleFiles = (files: FileList | null, isFolder = false) => {
    if (!files || files.length === 0) return
    const list = Array.from(files)
    const problems: string[] = []
    let acceptedCount = existingCount
    let acceptedBytes = existingBytes
    const emit = (file: File, dataUrl?: string) => {
      idSeqRef.current += 1
      const relativePath = isFolder
        ? (file as File & { webkitRelativePath?: string }).webkitRelativePath || undefined
        : undefined
      const attached: AttachedFile = {
        id: `${dataUrl ? 'img' : 'file'}-${Date.now()}-${idSeqRef.current}`,
        name: file.name,
        source: 'computer',
        size: formatAttachmentSize(file.size),
        sizeBytes: file.size,
        file,
        relativePath,
        dataUrl,
      }
      onAttach(attached)
    }

    for (const file of list) {
      if (file.size > MAX_ATTACHMENT_BYTES) {
        problems.push(
          `File "${file.name}" (${(file.size / (1024 * 1024)).toFixed(1)} MB) exceeds 25 MB limit / vượt trần 25 MB`,
        )
        continue
      }
      if (acceptedCount >= MAX_ATTACHMENTS_PER_TURN) {
        problems.push(
          `Exceeds 20 files per turn / 20 tệp mỗi lượt (current: ${acceptedCount})`,
        )
        continue
      }
      if (acceptedBytes + file.size > MAX_ATTACHMENT_BYTES_PER_TURN) {
        problems.push(
          `Exceeds 100 MB per turn / 100 MB mỗi lượt (current: ${(acceptedBytes / (1024 * 1024)).toFixed(1)} MB)`,
        )
        continue
      }

      acceptedCount += 1
      acceptedBytes += file.size

      if (file.type.startsWith('image/')) {
        const reader = new FileReader()
        reader.onload = (e) => {
          const dataUrl = e.target?.result as string
          emit(file, dataUrl)
        }
        reader.readAsDataURL(file)
      } else {
        emit(file)
      }
    }

    if (problems.length > 0) {
      setError(problems.join(' · '))
      setOpen(true)
    } else {
      setError(null)
      setOpen(false)
    }
  }

  const handleUploadFile = () => {
    fileInputRef.current?.click()
    setOpen(false)
  }

  const handleUploadFolder = () => {
    folderInputRef.current?.click()
    setOpen(false)
  }

  return (
    <div className="relative inline-block">
      {/* Hidden File Inputs */}
      <input
        ref={imageInputRef}
        type="file"
        accept="image/*"
        multiple
        data-testid="attach-image-input"
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files)
          if (imageInputRef.current) imageInputRef.current.value = ''
        }}
      />
      <input
        ref={fileInputRef}
        type="file"
        multiple
        data-testid="attach-file-input"
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files)
          if (fileInputRef.current) fileInputRef.current.value = ''
        }}
      />
      <input
        ref={folderInputRef}
        type="file"
        multiple
        // @ts-expect-error webkitdirectory is standard in browsers
        webkitdirectory=""
        data-testid="attach-folder-input"
        className="hidden"
        onChange={(e) => {
          handleFiles(e.target.files, true)
          if (folderInputRef.current) folderInputRef.current.value = ''
        }}
      />

      {/* Trigger [+] Button */}
      <button
        ref={triggerRef}
        data-testid="attach-trigger"
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex size-6 items-center justify-center rounded transition cursor-pointer select-none ${
          open
            ? 'bg-brand/15 text-brand shadow-xs'
            : 'text-muted hover:bg-panel hover:text-fg'
        }`}
        title="Thêm đính kèm / Tệp tin / Hình ảnh"
        aria-label="Add attachments, files or actions"
      >
        <Plus className="size-3.5" />
      </button>

      {/* Popover Dropdown Menu (Opens upward) — portal ra document.body */}
      {open &&
        panelPosition &&
        createPortal(
          <div
            ref={panelRef}
            data-testid="attach-menu"
            className="fixed z-50 max-h-[440px] overflow-y-auto rounded-2xl border border-line bg-panel p-1.5 shadow-2xl animate-in fade-in zoom-in-95 duration-150 select-none"
            style={{ left: panelPosition.left, width: panelPosition.width, bottom: panelPosition.bottom }}
          >
            {view === 'repos' ? (
              <RepoPickerView
                selectedRepoIds={selectedRepoIds}
                onToggleRepo={onToggleRepo ?? defaultToggleRepo}
                onBack={() => setView('menu')}
              />
            ) : (
              <div className="space-y-0.5">
                {/* Section 1: Add */}
                <div className="px-2.5 py-1 text-[10px] font-semibold text-muted uppercase tracking-wider">
                  {t('composer.attachMenu.add')}
                </div>

                {error && (
                  <div
                    data-testid="attach-error"
                    className="mx-1.5 mb-1 rounded-xl border border-rose-500/40 bg-rose-500/10 px-2.5 py-1.5 text-[10px] leading-relaxed text-rose-400"
                  >
                    {error}
                  </div>
                )}

                {/* 1. Upload Files & Folders */}
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    data-testid="attach-files-item"
                    onClick={handleUploadFile}
                    className="flex flex-1 items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer text-fg hover:bg-panel2/70 select-none"
                  >
                    <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-emerald-500/10 text-emerald-500">
                      <Paperclip className="size-3.5" />
                    </div>
                    <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
                      <span className="font-medium text-fg">{t('composer.attachMenu.filesAndFolders')}</span>
                      <span className="text-[11px] text-muted truncate">{t('composer.attachMenu.filesAndFoldersDesc')}</span>
                    </div>
                  </button>
                  <button
                    type="button"
                    data-testid="attach-folder-btn"
                    onClick={handleUploadFolder}
                    title={t('composer.attachMenu.uploadFolder')}
                    className="flex size-7 shrink-0 items-center justify-center rounded-lg text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
                  >
                    <FolderUp className="size-3.5" />
                  </button>
                </div>

                {/* 2. Repositories */}
                <button
                  type="button"
                  data-testid="attach-repo-item"
                  onClick={() => setView('repos')}
                  className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer text-fg hover:bg-panel2/70 select-none"
                >
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-blue-500/10 text-blue-500">
                    <GitFork className="size-3.5" />
                  </div>
                  <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
                    <span className="font-medium text-fg">{t('composer.attachMenu.repositories')}</span>
                    <span className="text-[11px] text-muted truncate">{t('composer.attachMenu.repositoriesDesc')}</span>
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    {selectedRepoIds.length > 0 && (
                      <span className="rounded bg-brand/15 px-1.5 py-0.2 font-mono text-[10px] font-semibold text-brand">
                        {selectedRepoIds.length}
                      </span>
                    )}
                    <ChevronRight className="size-3.5 text-muted" />
                  </div>
                </button>

                <div className="my-1 border-t border-line/60" />

                {/* Section 2: Modes & Goals */}
                <div className="px-2.5 py-1 text-[10px] font-semibold text-muted uppercase tracking-wider">
                  {t('composer.attachMenu.modesAndGoals')}
                </div>

                {/* 3. Autopilot */}
                <button
                  type="button"
                  data-testid="attach-autopilot-item"
                  onClick={() => {
                    onToggleAutopilot?.()
                    setOpen(false)
                  }}
                  className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer text-fg hover:bg-panel2/70 select-none"
                >
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-amber-500/10 text-amber-500">
                    <Target className="size-3.5" />
                  </div>
                  <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
                    <span className="font-medium text-fg">{t('composer.attachMenu.autopilot')}</span>
                    <span className="text-[11px] text-muted truncate">{t('composer.attachMenu.autopilotDesc')}</span>
                  </div>
                  {autopilotEnabled && (
                    <span className="size-1.5 rounded-full bg-brand shadow-xs shrink-0" />
                  )}
                </button>

                {/* 4. Plan mode */}
                <button
                  type="button"
                  data-testid="attach-plan-item"
                  onClick={() => {
                    onSelectPlan?.()
                    setOpen(false)
                  }}
                  className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer text-fg hover:bg-panel2/70 select-none"
                >
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-amber-400/10 text-amber-400">
                    <Lightbulb className="size-3.5" />
                  </div>
                  <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
                    <span className="font-medium text-fg">{t('composer.attachMenu.planMode')}</span>
                    <span className="text-[11px] text-muted truncate">{t('composer.attachMenu.planModeDesc')}</span>
                  </div>
                </button>

                {/* 5. Research mode */}
                <button
                  type="button"
                  data-testid="attach-research-item"
                  onClick={() => {
                    onToggleResearch?.()
                    setOpen(false)
                  }}
                  className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer text-fg hover:bg-panel2/70 select-none"
                >
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-blue-400/10 text-blue-400">
                    <Microscope className="size-3.5" />
                  </div>
                  <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
                    <span className="font-medium text-fg">{t('composer.attachMenu.researchMode')}</span>
                    <span className="text-[11px] text-muted truncate">{t('composer.attachMenu.researchModeDesc')}</span>
                  </div>
                  {researchEnabled && (
                    <span className="size-1.5 rounded-full bg-blue-400 shadow-xs shrink-0" />
                  )}
                </button>

                {/* 6. Design mode */}
                <button
                  type="button"
                  data-testid="attach-design-item"
                  onClick={() => {
                    onToggleDesign?.()
                    setOpen(false)
                  }}
                  className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs transition cursor-pointer text-fg hover:bg-panel2/70 select-none"
                >
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-purple-400/10 text-purple-400">
                    <Palette className="size-3.5" />
                  </div>
                  <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
                    <span className="font-medium text-fg">{t('composer.attachMenu.designMode')}</span>
                    <span className="text-[11px] text-muted truncate">{t('composer.attachMenu.designModeDesc')}</span>
                  </div>
                  {designEnabled && (
                    <span className="size-1.5 rounded-full bg-purple-400 shadow-xs shrink-0" />
                  )}
                </button>

                <div className="my-1 border-t border-line/60" />

                {/* Section 3: Integrations */}
                <div className="px-2.5 py-1 text-[10px] font-semibold text-muted uppercase tracking-wider">
                  {t('composer.attachMenu.integrations')}
                </div>

                {/* 7. Google Drive */}
                <button
                  type="button"
                  disabled
                  aria-disabled="true"
                  data-testid="attach-drive-item"
                  className="flex w-full cursor-not-allowed items-center gap-2.5 rounded-xl px-2.5 py-1.5 text-left text-xs text-muted opacity-60 select-none"
                >
                  <div className="flex size-6 shrink-0 items-center justify-center rounded-lg bg-panel2">
                    <svg className="size-3.5 shrink-0" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
                      <path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
                      <path d="M43.65 25 29.9 1.2c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44A8.9 8.9 0 0 0 0 53h27.5z" fill="#00ac47"/>
                      <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8l5.85 10.15z" fill="#ea4335"/>
                      <path d="M43.65 25 57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>
                      <path d="M59.8 53h27.5c0-1.55-.4-3.1-1.2-4.5L72.35 22.75c-.8-1.4-1.95-2.5-3.3-3.3L55.3 43.25z" fill="#2684fc"/>
                      <path d="m27.5 53 13.75 23.8c1.35-.8 2.5-1.9 3.3-3.3l20.75-35.95c.8-1.4 1.2-2.95 1.2-4.55H27.5z" fill="#ffba00"/>
                    </svg>
                  </div>
                  <div className="flex min-w-0 flex-1 items-baseline gap-2 truncate">
                    <span className="font-medium text-muted">{t('composer.attachMenu.googleDrive')}</span>
                    <span className="text-[11px] text-muted truncate">Not connected · Chưa kết nối</span>
                  </div>
                </button>

                {/* Chân bảng: cách đóng + tệp chỉ gửi sau khi lên box */}
                <div
                  data-testid="attach-menu-hint"
                  className="px-2.5 pb-1 pt-1.5 text-[10px] leading-relaxed text-muted border-t border-line/60 mt-1"
                >
                  Press Esc to close · Esc để đóng · tệp chỉ được gửi sau khi lên tới box (
                  <span className="font-mono text-zinc-400">/__box/file/upload</span>)
                </div>
              </div>
            )}
          </div>,
          document.body,
        )}
    </div>
  )
}
