import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Folder, FolderOpen, FolderPlus, X } from 'lucide-react'
import { useT } from '../../i18n/context'
import { useMachineStore } from '../../store/machineStore'
import { startMachineChat } from '../../lib/machineSession'

export function CreateProjectModal({onClose}: {onClose: () => void}) {
  const t = useT()
  const [name, setName] = useState('')
  const [path, setPath] = useState('')
  const [picking, setPicking] = useState(false)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const nameRef = useRef<HTMLInputElement>(null)
  const busy = picking || creating
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    nameRef.current?.focus()
    return () => previous?.focus()
  }, [])
  const pick = async () => {
    setPicking(true); setError(null)
    try {
      const selected = await useMachineStore.getState().selectFolder()
      if (selected) {setPath(selected); if (!name.trim()) setName(selected.split(/[\\/]/).filter(Boolean).pop() ?? '')}
      else setError(useMachineStore.getState().error)
    } finally {setPicking(false)}
  }
  const create = async () => {
    if (busy || !name.trim() || !path) return
    setCreating(true); setError(null)
    try {
      const store = useMachineStore.getState()
      const project = await store.register(path, name.trim())
      if (!project || !await store.configure('host', project.id)) {setError(useMachineStore.getState().error); return}
      startMachineChat({mode: 'host', revision: 1, projectId: project.id, workspace: project.path})
      onClose()
    } finally {setCreating(false)}
  }
  return createPortal(<div className="fixed inset-0 z-[80] flex items-center justify-center bg-black/50 p-4" onMouseDown={event => {if (event.target === event.currentTarget && !busy) onClose()}}>
    <div ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="create-project-title" className="w-full max-w-lg rounded-2xl border border-line bg-panel p-6 shadow-2xl" onKeyDown={event => {
      if (event.key === 'Escape') {event.stopPropagation(); if (!busy) onClose()}
      if (event.key === 'Tab') {
        const nodes = [...(dialogRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)') ?? [])]
        const first = nodes[0], last = nodes[nodes.length - 1]
        if (event.shiftKey && document.activeElement === first) {event.preventDefault(); last?.focus()}
        else if (!event.shiftKey && document.activeElement === last) {event.preventDefault(); first?.focus()}
      }
    }}>
      <div className="mb-5 flex items-center justify-between"><h2 id="create-project-title" className="text-lg font-semibold text-fg">{t('sidebar.createProject')}</h2><button disabled={busy} onClick={onClose} aria-label={t('common.close')} className="rounded p-1 text-muted hover:bg-panel2"><X className="size-4" /></button></div>
      <label className="flex items-center gap-3 rounded-lg border border-line bg-panel2 px-3 py-2.5 focus-within:border-brand"><Folder className="size-4 shrink-0 text-muted" /><input ref={nameRef} disabled={busy} maxLength={120} aria-label={t('sidebar.projectName')} placeholder={t('sidebar.projectName')} value={name} onChange={event => setName(event.target.value)} className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none" /></label>
      <h3 className="mt-5 mb-2 text-sm font-medium text-fg">{t('sidebar.sourceFolder')}</h3>
      <label className="flex items-center gap-3 rounded-lg border border-line bg-panel2 px-3 py-2.5 focus-within:border-brand">
        <FolderOpen className="size-4 shrink-0 text-muted" />
        <input disabled={busy} aria-label={t('sidebar.folderPath')} placeholder={t('sidebar.folderPathPlaceholder')} value={path} onChange={event => setPath(event.target.value)} className="min-w-0 flex-1 bg-transparent text-sm text-fg outline-none" />
      </label>
      <div className="mt-2 flex items-start gap-3">
        <button disabled={busy} onClick={() => void pick()} className="flex shrink-0 items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-xs text-fg hover:bg-panel"><FolderPlus className="size-4" />{t(picking ? 'sidebar.choosingFolder' : 'sidebar.addFolder')}</button>
        <p className="text-[11px] text-muted">{t('sidebar.folderPathHint')}</p>
      </div>
      {error && <p role="alert" className="mt-3 break-all text-xs text-red-400">{error}</p>}
      <div className="mt-6 flex justify-end gap-3"><button disabled={busy} onClick={onClose} className="rounded-lg px-4 py-2 text-xs text-muted hover:bg-panel2">{t('sidebar.cancelProject')}</button><button disabled={busy || !name.trim() || !path} onClick={() => void create()} className="rounded-lg bg-brand px-4 py-2 text-xs font-medium text-white disabled:opacity-40">{t(creating ? 'sidebar.creatingProject' : 'sidebar.createProject')}</button></div>
    </div>
  </div>, document.body)
}
