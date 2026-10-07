import { useEffect, useState } from 'react'
import { agentApi } from '../../lib/agentApi'
import { useComposerStore } from '../../store/composerStore'
import type { InspectedElementContext } from '../../types/inspect'

interface WindowTarget { windowId: string | number; pid: number; title: string }
interface Snapshot { image: string; width: number; height: number; hash: string; snapshotId: string }
export function HostMachineScreen() {
  const [windows, setWindows] = useState<WindowTarget[]>([])
  const [selected, setSelected] = useState('')
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [armed, setArmed] = useState(false)
  const [element, setElement] = useState<InspectedElementContext | null>(null)
  useEffect(() => {
    const cancel = (event: KeyboardEvent) => { if (event.key === 'Escape') { setArmed(false); setElement(null) } }
    window.addEventListener('keydown', cancel)
    return () => window.removeEventListener('keydown', cancel)
  }, [])
  const refresh = async () => {
    setBusy(true)
    try { const value = await agentApi<{windows: WindowTarget[]}>('/machines/screen'); setWindows(value.windows); setError(null); setSnapshot(null) }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const capture = async () => {
    const target = windows.find(w => String(w.windowId) === selected)
    if (!target) return
    setBusy(true); setSnapshot(null); setElement(null); setArmed(false)
    try { setSnapshot(await agentApi<Snapshot>('/machines/screen', {windowId: target.windowId, pid: target.pid, consent: true})); setError(null) }
    catch (e) { setError(String(e)) } finally { setBusy(false) }
  }
  const inspect = async (event: React.MouseEvent<HTMLImageElement>) => {
    if (!armed || !snapshot) return
    const target = windows.find(w => String(w.windowId) === selected)
    if (!target) return
    const box = event.currentTarget.getBoundingClientRect()
    // The image uses its intrinsic aspect ratio; there is no letterboxed pointer mapping.
    const x = Math.floor((event.clientX - box.left) * snapshot.width / box.width)
    const y = Math.floor((event.clientY - box.top) * snapshot.height / box.height)
    setBusy(true)
    try {
      const result = await agentApi<Pick<InspectedElementContext, 'point' | 'result'>>('/machines/screen', {action: 'inspect', windowId: target.windowId, pid: target.pid, consent: true, snapshotId: snapshot.snapshotId, x, y})
      setElement({...result, id: crypto.randomUUID()}); setArmed(false); setError(null)
    } catch (e) { setError(String(e)); setElement(null) } finally { setBusy(false) }
  }
  return <section className="flex h-full flex-col gap-3 p-4 text-xs">
    <header className="font-semibold">Machine screen · This machine</header>
    <p className="text-muted">Choose a window and grant a snapshot preview. Nothing is captured automatically. Mouse/keyboard control is not enabled in this checkpoint.</p>
    <div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => void refresh()} className="rounded border border-line px-3 py-1">Choose window</button>
      <select aria-label="Host preview window" value={selected} onChange={e => { setSelected(e.target.value); setSnapshot(null); setArmed(false); setElement(null) }} className="min-w-0 max-w-xs rounded border border-line bg-panel2 px-2">
        <option value="">Select a window</option>{windows.map(w => <option key={w.windowId} value={String(w.windowId)}>{w.title || String(w.windowId)}</option>)}</select>
      <button disabled={busy || !selected} onClick={() => void capture()} className="rounded border border-line px-3 py-1">Allow preview / Refresh snapshot</button>
      <button onClick={() => { setSnapshot(null); setSelected(''); setArmed(false); setElement(null) }} className="rounded border border-line px-3 py-1">Revoke preview</button>
      <button disabled={!snapshot || busy} onClick={() => { setArmed(!armed); setElement(null) }} className="rounded border border-line px-3 py-1">{armed ? 'Cancel selection' : 'Select Element'}</button>
    </div>
    {error && <p role="alert" className="text-red-400">{error}</p>}
    {snapshot && <><p className="text-muted">Snapshot · Untrusted data · {snapshot.width}×{snapshot.height}</p><div className="min-h-0 flex-1 overflow-auto"><img src={`data:image/png;base64,${snapshot.image}`} onClick={event => void inspect(event)} alt="Selected host window snapshot" className={`h-auto max-w-full ${armed ? 'cursor-crosshair' : ''}`} /></div></>}
    {element && <div className="rounded border border-line p-3"><p>Desktop Element · Untrusted data</p><p className="break-all">{element.result.type === 'desktop' ? element.result.windowTitle : ''}</p>
      <p className="text-muted">Window metadata fallback; UIA/DOM selection is not yet connected.</p>
      <button className="mt-2 rounded border border-line px-3 py-1" onClick={() => { useComposerStore.getState().addPendingElement(element); setElement(null) }}>Add to Chat</button></div>}
  </section>
}
