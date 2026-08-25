/**
 * Menu đính kèm tài liệu (AttachmentPicker) tại nút [+] của Chat Input Bar.
 * - Upload from computer (Kích hoạt file picker để upload tệp từ máy).
 * - Google Drive (Tích hợp biểu tượng Google Drive và chọn file Drive).
 * 
 * HƯỚNG DẪN KẾT NỐI PRODUCTION:
 * - Đối với Computer File: Lắng nghe sự kiện `handleFileChange` -> Gửi Multipart POST `/api/upload` -> Trả về URL/hash gắn vào Session context.
 * - Đối với Google Drive: Tích hợp Google Picker API (`gapi.client.drive`) với OAuth token -> Trả về file metadata.
 */
import React, { useState, useRef, useEffect } from 'react'
import { Plus, Paperclip } from 'lucide-react'

export interface AttachedFile {
  id: string
  name: string
  source: 'computer' | 'drive'
  size?: string
}

export function AttachmentPicker({
  onAttach,
}: {
  onAttach: (file: AttachedFile) => void
}) {
  const [open, setOpen] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // Click outside to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
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

  const handleUploadComputer = () => {
    setOpen(false)
    fileInputRef.current?.click()
  }

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return
    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      onAttach({
        id: `file-${Date.now()}-${i}`,
        name: file.name,
        source: 'computer',
        size: `${(file.size / 1024).toFixed(0)} KB`,
      })
    }
    // Reset file input value
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleGoogleDrive = () => {
    setOpen(false)
    // Simulated Google Drive sample file picker
    onAttach({
      id: `drive-${Date.now()}`,
      name: 'Architecture_Blueprint_2026.gdoc',
      source: 'drive',
      size: 'Google Doc',
    })
  }

  return (
    <div className="relative inline-block" ref={popoverRef}>
      {/* Hidden native file input */}
      <input
        ref={fileInputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleFileChange}
      />

      {/* Trigger [+] Button */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className={`flex size-6 items-center justify-center rounded transition cursor-pointer select-none ${
          open
            ? 'bg-brand/15 text-brand shadow-xs'
            : 'text-muted hover:bg-panel hover:text-fg'
        }`}
        title="Add attachment / context"
      >
        <Plus className="size-3.5" />
      </button>

      {/* Popover Dropdown Menu (Opens upward) */}
      {open && (
        <div className="absolute bottom-full left-0 mb-2 w-56 rounded-2xl border border-line bg-panel p-1.5 shadow-2xl z-50 animate-in fade-in zoom-in-95 duration-150 select-none">
          <button
            type="button"
            onClick={handleUploadComputer}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-xs text-fg hover:bg-panel2 transition cursor-pointer"
          >
            <Paperclip className="size-4 text-muted" />
            <span className="font-medium">Upload from computer</span>
          </button>

          <button
            type="button"
            onClick={handleGoogleDrive}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-xs text-fg hover:bg-panel2 transition cursor-pointer"
          >
            {/* Google Drive 3-color Triangular Icon */}
            <svg className="size-4 shrink-0" viewBox="0 0 87.3 78" xmlns="http://www.w3.org/2000/svg">
              <path d="m6.6 66.85 3.85 6.65c.8 1.4 1.95 2.5 3.3 3.3l13.75-23.8H0c0 1.55.4 3.1 1.2 4.5z" fill="#0066da"/>
              <path d="M43.65 25 29.9 1.2c-1.35.8-2.5 1.9-3.3 3.3l-25.4 44A8.9 8.9 0 0 0 0 53h27.5z" fill="#00ac47"/>
              <path d="M73.55 76.8c1.35-.8 2.5-1.9 3.3-3.3l1.6-2.75 7.65-13.25c.8-1.4 1.2-2.95 1.2-4.5H59.8l5.85 10.15z" fill="#ea4335"/>
              <path d="M43.65 25 57.4 1.2C56.05.4 54.5 0 52.9 0H34.4c-1.6 0-3.15.45-4.5 1.2z" fill="#00832d"/>
              <path d="M59.8 53h27.5c0-1.55-.4-3.1-1.2-4.5L72.35 22.75c-.8-1.4-1.95-2.5-3.3-3.3L55.3 43.25z" fill="#2684fc"/>
              <path d="m27.5 53 13.75 23.8c1.35-.8 2.5-1.9 3.3-3.3l20.75-35.95c.8-1.4 1.2-2.95 1.2-4.55H27.5z" fill="#ffba00"/>
            </svg>
            <span className="font-medium">Google Drive</span>
          </button>
        </div>
      )}
    </div>
  )
}
