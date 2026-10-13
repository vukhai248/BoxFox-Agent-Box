import { useEffect, useRef, useState } from 'react'
import { nextCopyName, useHarnessStore } from '../../store/harnessStore'
import type { Harness } from '../../types/harness'

interface HarnessDuplicateDialogProps {
  source: Harness
  /** Toàn bộ danh sách, để tên gợi ý và cảnh báo trùng tên đọc đúng dữ liệu thật. */
  harnesses: Harness[]
  onCancel: () => void
  onDone: (newId: string, name: string, openInEditor: boolean) => void
}

/**
 * Hộp thoại nhân bản dùng chung cho dòng built-in trong danh sách và màn
 * read-only. `cloneHarness` chạy đồng bộ trên localStorage nên không có spinner;
 * tên gợi ý quét cả họ `(Copy)` để hai dòng không bao giờ trùng tên.
 */
export function HarnessDuplicateDialog({ source, harnesses, onCancel, onDone }: HarnessDuplicateDialogProps) {
  const cloneHarness = useHarnessStore((s) => s.cloneHarness)
  const saveHarness = useHarnessStore((s) => s.saveHarness)

  const takenNames = harnesses.map((h) => h.name)
  const [name, setName] = useState(() => nextCopyName(source.name, takenNames))
  const [openInEditor, setOpenInEditor] = useState(true)
  const dialogRef = useRef<HTMLDivElement>(null)
  const opener = useRef<HTMLElement | null>(document.activeElement instanceof HTMLElement ? document.activeElement : null)

  useEffect(() => {
    const dialog = dialogRef.current
    const fields = dialog?.querySelectorAll<HTMLElement>('input,button')
    fields?.[0]?.focus()
    const keyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCancel()
      }
    }
    document.addEventListener('keydown', keyDown)
    return () => {
      document.removeEventListener('keydown', keyDown)
      opener.current?.focus()
    }
  }, [onCancel])

  const typed = name.trim()
  const collides = typed.length > 0 && takenNames.includes(typed)
  const effectiveName = typed.length === 0 ? nextCopyName(source.name, takenNames) : collides ? nextCopyName(typed, takenNames) : typed

  const handleDuplicate = () => {
    const newId = cloneHarness(source.id)
    const cloned = useHarnessStore.getState().harnesses.find((h) => h.id === newId)
    // Store đã tự tránh trùng tên; chỉ ghi lại khi người dùng gõ tên khác gợi ý.
    if (cloned && cloned.name !== effectiveName) saveHarness({ ...cloned, name: effectiveName })
    onDone(newId, effectiveName, openInEditor)
  }

  return (
    <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60 p-4" role="presentation">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="duplicate-harness-title"
        className="w-full max-w-md rounded-xl border border-line bg-bg p-5 shadow-2xl"
      >
        <h2 id="duplicate-harness-title" className="text-base font-bold">
          Duplicate harness
        </h2>

        <dl className="mt-4 space-y-1 rounded-lg border border-line bg-panel2 p-3 text-xs">
          <div className="flex items-start justify-between gap-3">
            <dt className="text-muted">Source</dt>
            <dd className="text-right font-medium">
              {source.name}
              {source.isBuiltIn ? ' · built-in' : ' · copy'}
            </dd>
          </div>
          <div className="flex items-start justify-between gap-3">
            <dt className="text-muted">Copies</dt>
            <dd className="text-right font-medium">
              {source.subagents.filter((s) => s.enabled).length} specialists · every setting and prompt
            </dd>
          </div>
        </dl>

        <label htmlFor="copy-name" className="mt-4 block text-xs font-medium text-muted">
          Name for the copy
        </label>
        <input
          id="copy-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          className="mt-1.5 w-full rounded-md border border-line bg-panel px-3 py-2 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
        />
        {collides && (
          <div className="mt-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs">
            <p className="font-semibold">A copy with that name already exists</p>
            <p className="mt-1 text-muted">
              {typed} is already in your list, so a number was added to keep the two apart — the
              picker in the composer only shows names. It will be saved as {effectiveName}.
            </p>
          </div>
        )}

        <div className="mt-4 flex items-start gap-2">
          <input
            id="open-copy-in-editor"
            type="checkbox"
            checked={openInEditor}
            onChange={(event) => setOpenInEditor(event.target.checked)}
            className="mt-0.5 accent-brand"
          />
          <label htmlFor="open-copy-in-editor" className="cursor-pointer text-xs">
            <span className="font-medium">Open the copy in the editor</span>
            <span className="mt-0.5 block text-muted">
              On by default, because the only reason to duplicate is to change something.
            </span>
          </label>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-line px-3 py-2 text-xs font-semibold hover:bg-panel2 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleDuplicate}
            className="rounded-md bg-brand px-3 py-2 text-xs font-semibold text-brandfg hover:opacity-90 cursor-pointer"
          >
            Duplicate
          </button>
        </div>
      </div>
    </div>
  )
}
