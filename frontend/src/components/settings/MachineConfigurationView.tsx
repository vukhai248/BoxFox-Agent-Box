import { useEffect, useState } from 'react'
import { FolderOpen } from 'lucide-react'
import { useMachineStore } from '../../store/machineStore'
import { useAgentStore } from '../../store/agentStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { startMachineChat } from '../../lib/machineSession'
import { configuredBinding } from '../../store/machineStore'

export function MachineConfigurationView() {
  const { configuration, error, load, configure, register, trust, bindings } = useMachineStore()
  const chatId = useAgentStore(s => s.activeSessionId)
  const existing = useHarnessChatStore(s => s.sessions[chatId]?.id)
  const binding = bindings[chatId]
  const mode = binding?.mode ?? (existing ? 'docker' : configuration?.mode ?? 'docker')
  const projectId = binding?.projectId ?? (!existing ? configuration?.projectId : null)
  const project = configuration?.projects.find(p => p.id === projectId)
  const [busy, setBusy] = useState(false)
  const [path, setPath] = useState('')
  useEffect(() => { void load() }, [load])
  const select = async (nextMode: 'host' | 'docker', nextProject: string | null = projectId ?? null) => {
    setBusy(true)
    try {
      if (await configure(nextMode, nextProject)) {
        // A saved session keeps its binding. Switching creates a new chat, never mutates old work.
        if (existing || binding) startMachineChat(configuredBinding())
      }
    } finally { setBusy(false) }
  }
  const choose = async (manual = false) => {
    setBusy(true)
    try {
      const selected = await register(manual ? path : undefined)
      if (selected && await configure('host', selected.id)) {
        if (existing || binding) startMachineChat(configuredBinding())
        setPath('')
      }
    } finally { setBusy(false) }
  }
  return <section className="max-w-3xl space-y-4 p-8">
    <h2 className="text-xs font-semibold text-fg">Execution environment</h2>
    <div className="flex gap-2">
      {(['host', 'docker'] as const).map(value => <button key={value} type="button" aria-pressed={mode === value} disabled={busy || !configuration}
        onClick={() => void select(value)} className={`rounded-lg border px-3 py-1.5 text-xs ${mode === value ? 'border-brand bg-brand/10 text-fg' : 'border-line text-muted'}`}>
        {value === 'host' ? 'IDE · This machine' : 'Docker · Isolated'}</button>)}
    </div>
    {mode === 'host' && <div className="space-y-2">
      <button type="button" disabled={busy || !configuration} onClick={() => void choose()} className="flex items-center gap-2 rounded-lg border border-line px-3 py-1.5 text-xs text-fg">
        <FolderOpen className="size-3.5" />{busy ? 'Opening…' : 'Choose folder'}</button>
      {project && <div className="text-[11px] text-muted break-all">{project.path}</div>}
      <details className="text-[11px] text-muted"><summary>Enter folder path</summary><div className="mt-2 flex gap-1">
        <input aria-label="Project folder path" value={path} onChange={e => setPath(e.target.value)} className="min-w-0 flex-1 rounded border border-line bg-panel px-2 py-1" placeholder="D:\\projects\\my-app" />
        <button type="button" disabled={!path.trim() || busy} onClick={() => void choose(true)}>Add</button></div></details>
      {!!configuration?.projects.length && <select aria-label="Local project" className="w-full rounded border border-line bg-panel p-1 text-xs" value={projectId ?? ''} disabled={busy} onChange={e => void select('host', e.target.value || null)}>
        <option value="">No project selected</option>{configuration.projects.map(p => <option key={p.id} value={p.id}>{p.name} · {p.path}</option>)}</select>}
      {project && <label className="flex items-start gap-2 text-[11px] text-muted"><input type="checkbox" checked={project.trusted} onChange={e => void trust(project.id, e.target.checked)} />
        Trust this folder for writes/commands. Host commands run as your Windows account; they are not OS sandboxed.</label>}
    </div>}
    <p className="text-[10px] text-muted">Changing environment/folder starts a new chat. Existing sessions keep their environment.</p>
    {error && <p role="alert" className="break-all text-xs text-red-400">{error}</p>}
  </section>
}
