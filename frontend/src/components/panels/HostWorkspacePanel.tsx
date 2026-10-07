import { useEffect, useState } from 'react'
import { useActiveMachine } from '../../hooks/useActiveMachine'
import { agentApi } from '../../lib/agentApi'
import { useMachineStore } from '../../store/machineStore'
import { useUiStore } from '../../store/uiStore'

interface Entry { name: string; path: string; directory: boolean }
export function HostWorkspacePanel({ view }: { view: 'files' | 'editor' | 'terminal' }) {
  const machine = useActiveMachine()
  const project = useMachineStore(s => s.configuration?.projects.find(p => p.id === machine.projectId))
  const [entries, setEntries] = useState<Entry[]>([])
  const [directory, setDirectory] = useState('.')
  const [path, setPath] = useState('')
  const [content, setContent] = useState('')
  const [hash, setHash] = useState('')
  const [dirty, setDirty] = useState(false)
  const [command, setCommand] = useState('')
  const [output, setOutput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const base = `/machines/projects/${encodeURIComponent(machine.projectId ?? '')}`
  const browse = async (folder: string) => {
    try { const result = await agentApi<{entries: Entry[]}>(`${base}/files?path=${encodeURIComponent(folder)}`); setEntries(result.entries); setDirectory(folder); setError(null) }
    catch (e) { setError(String(e)) }
  }
  useEffect(() => {
    setPath(''); setContent(''); setHash(''); setDirty(false); setOutput(''); setCommand(''); setEntries([]); setError(null)
    if (machine.projectId && view !== 'terminal') void browse('.')
  }, [machine.projectId, view])
  const open = async (entry: Entry) => {
    if (entry.directory) { void browse(entry.path); return }
    if (dirty && !window.confirm('Discard unsaved edits?')) return
    try {
      const file = await agentApi<{content: string; hash: string}>(`${base}/file?path=${encodeURIComponent(entry.path)}`)
      setPath(entry.path); setContent(file.content); setHash(file.hash); setDirty(false); setError(null)
    } catch (e) { setError(String(e)) }
  }
  const save = async () => {
    setBusy(true)
    try { const result = await agentApi<{hash: string}>(`${base}/file`, {path, content, hash}); setHash(result.hash); setDirty(false); setError(null) }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const run = async () => {
    setBusy(true); setOutput('')
    try { const result = await agentApi<Record<string, unknown>>(`${base}/command`, {command}); setOutput(String(result.content ?? JSON.stringify(result))); setError(null) }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  if (!machine.projectId) return <section className="space-y-3 p-4 text-xs">
    <p>Select a project folder in Settings → Machines → Configuration.</p>
    <button onClick={() => useUiStore.getState().openSettings('configuration')} className="rounded border border-line px-3 py-1">Open Configuration</button>
  </section>
  return <div className="flex h-full flex-col gap-3 p-4 text-xs">
    <header className="break-all font-semibold">{view === 'terminal' ? 'Host command runner' : 'IDE · Local files'} · {project?.path}</header>
    {error && <p role="alert" className="text-red-400">{error}</p>}
    {view === 'terminal' ? <>
      <p className="text-muted">PowerShell on Windows. Runs as your user account; no OS sandbox. This checkpoint is a command runner, not an interactive terminal.</p>
      <textarea aria-label="Host command" value={command} onChange={e => setCommand(e.target.value)} rows={3} className="rounded border border-line bg-panel2 p-2 font-mono" />
      <button disabled={busy || !project?.trusted || !command.trim()} onClick={() => void run()} className="self-start rounded border border-line px-3 py-1">{busy ? 'Running…' : 'Run command'}</button>
      {!project?.trusted && <p className="text-muted">Trust this folder in Configuration before running commands.</p>}
      <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap font-mono">{output}</pre>
    </> : <div className="flex min-h-0 flex-1 gap-3">
      <aside className="w-48 shrink-0 overflow-auto border-r border-line pr-2">
        <button onClick={() => void browse(directory.includes('/') ? directory.slice(0, directory.lastIndexOf('/')) : '.')} className="mb-2 text-muted">↑ Parent folder</button>
        {entries.map(entry => <button key={entry.path} onClick={() => void open(entry)} className="block w-full truncate py-1 text-left">{entry.directory ? '▸ ' : ''}{entry.name}</button>)}
      </aside><div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-center justify-between"><span>{path || 'Select a UTF-8 file'}{dirty ? ' · modified' : ''}</span>
          <button disabled={!path || !dirty || busy || !project?.trusted} onClick={() => void save()} className="rounded border border-line px-3 py-1">Save</button></div>
        <textarea aria-label="Local file editor" value={content} disabled={!path} onChange={e => { setContent(e.target.value); setDirty(true) }} className="min-h-0 flex-1 resize-none rounded border border-line bg-panel2 p-3 font-mono text-xs" spellCheck={false} />
      </div></div>}
  </div>
}
