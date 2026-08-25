import { useState } from 'react'
import {
  Globe,
  Plus,
  Info,
  Trash2,
  RefreshCw,
  X,
  ShieldCheck,
} from 'lucide-react'

export interface BrowserSnapshotItem {
  id: string
  name: string
  domains: string[]
  createdAt: string
  expiresIn: string
  active: boolean
}

const INITIAL_SNAPSHOTS: BrowserSnapshotItem[] = []

export function BrowserView() {
  const [snapshots, setSnapshots] = useState<BrowserSnapshotItem[]>(INITIAL_SNAPSHOTS)
  const [isModalOpen, setIsModalOpen] = useState(false)

  // Form State
  const [name, setName] = useState('')
  const [domainsInput, setDomainsInput] = useState('github.com, cloud.google.com, aws.amazon.com')
  const [isCapturing, setIsCapturing] = useState(false)

  const handleCreateSnapshot = () => {
    if (!name.trim()) return
    setIsCapturing(true)

    setTimeout(() => {
      const parsedDomains = domainsInput
        .split(',')
        .map((d) => d.trim())
        .filter(Boolean)

      const newSnapshot: BrowserSnapshotItem = {
        id: `SNAP-${Date.now().toString().slice(-4)}`,
        name: name.trim(),
        domains: parsedDomains.length > 0 ? parsedDomains : ['github.com', 'google.com'],
        createdAt: 'Just now',
        expiresIn: '30 days',
        active: true,
      }

      setSnapshots([newSnapshot])
      setIsCapturing(false)
      setIsModalOpen(false)
      setName('')
    }, 800)
  }

  const handleDelete = (id: string) => {
    setSnapshots((prev) => prev.filter((s) => s.id !== id))
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Machines</span>
        <span>›</span>
        <span className="text-fg font-semibold">Browser</span>
      </div>

      {/* Title & Description */}
      <div className="space-y-1.5 border-b border-line pb-4">
        <h1 className="text-xl font-bold text-fg">Browser Snapshots</h1>
        <p className="text-xs text-muted max-w-2xl leading-relaxed">
          Inject authenticated browser snapshots — cookies and local browser storage for agent runs. Only one snapshot can be active per account — creating a new one deactivates the previous.
        </p>

        {/* MFA / OTP Notice Banner */}
        <div className="flex items-start gap-2 rounded-lg border border-line bg-panel2 p-3 text-[11px] text-fg mt-2">
          <Info className="size-4 text-brand shrink-0 mt-0.5" />
          <span>Services that require MFA/OTP on every login may not work reliably with saved browser state.</span>
        </div>
      </div>

      {/* Snapshots Container */}
      {snapshots.length === 0 ? (
        <div className="flex min-h-[360px] flex-col items-center justify-center rounded-2xl border border-line bg-panel p-8 text-center shadow-xs">
          <div className="flex size-14 items-center justify-center rounded-2xl bg-panel2 text-muted border border-line mb-3 shadow-xs">
            <Globe className="size-7" />
          </div>

          <h2 className="text-base font-bold text-fg">No browser snapshots</h2>
          <p className="text-xs text-muted max-w-md mt-1 mb-5">
            Create a snapshot to give agents authenticated browser access to your services.
          </p>

          <button
            type="button"
            onClick={() => setIsModalOpen(true)}
            className="flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
          >
            <Plus className="size-3.5" />
            <span>New snapshot</span>
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">
              Active Browser Snapshot (1)
            </span>
            <button
              type="button"
              onClick={() => setIsModalOpen(true)}
              className="flex items-center gap-1.5 rounded-md bg-brand px-3 py-1.5 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
            >
              <Plus className="size-3.5" />
              <span>Replace snapshot</span>
            </button>
          </div>

          {snapshots.map((snap) => (
            <div
              key={snap.id}
              className="rounded-xl border border-line bg-panel p-5 space-y-4 shadow-xs transition hover:border-brand/40"
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex size-9 items-center justify-center rounded-lg bg-brand/15 text-brand border border-brand/30">
                    <Globe className="size-5" />
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-bold text-fg">{snap.name}</h3>
                      <span className="rounded bg-emerald-500/15 px-2 py-0.2 text-[9px] font-bold uppercase text-emerald-500 border border-emerald-500/30">
                        Active Snapshot
                      </span>
                    </div>
                    <p className="text-[11px] text-muted">
                      Created: {snap.createdAt} • Valid for {snap.expiresIn}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => handleDelete(snap.id)}
                  className="p-1.5 rounded-md text-muted hover:text-rose-500 hover:bg-rose-500/10 transition cursor-pointer"
                  title="Delete snapshot"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>

              {/* Domains Included */}
              <div className="space-y-1.5 pt-2 border-t border-line">
                <span className="text-[11px] font-semibold text-muted uppercase tracking-wider">
                  Authenticated Domains Stored:
                </span>
                <div className="flex flex-wrap gap-2 pt-1">
                  {snap.domains.map((dom, i) => (
                    <span
                      key={i}
                      className="flex items-center gap-1 rounded-md border border-line bg-panel2 px-2.5 py-1 text-xs font-mono text-fg"
                    >
                      <ShieldCheck className="size-3 text-emerald-500" />
                      <span>{dom}</span>
                    </span>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ========================================================================= */}
      {/* NEW SNAPSHOT MODAL */}
      {/* ========================================================================= */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="relative w-full max-w-lg rounded-2xl border border-line bg-panel p-6 shadow-2xl space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-line pb-3">
              <h3 className="text-base font-bold text-fg">Create Browser Snapshot</h3>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="text-muted hover:text-fg transition cursor-pointer p-1 rounded-md hover:bg-panel2"
              >
                <X className="size-4" />
              </button>
            </div>

            <p className="text-xs text-muted">
              Launch an isolated browser window to log in to target web services. Your authentication cookies and local storage tokens will be securely encrypted for agent execution.
            </p>

            {/* Snapshot Name */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Snapshot Label</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. GitHub & Cloud Platform Access"
                className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand"
                autoFocus
              />
            </div>

            {/* Domains */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">
                Target Domains to Capture (comma separated)
              </label>
              <input
                type="text"
                value={domainsInput}
                onChange={(e) => setDomainsInput(e.target.value)}
                placeholder="github.com, cloud.google.com"
                className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono"
              />
            </div>

            {/* Footer */}
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-line">
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="rounded-md border border-line bg-panel2 px-4 py-1.5 text-xs font-medium text-muted hover:text-fg transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreateSnapshot}
                disabled={!name.trim() || isCapturing}
                className="flex items-center gap-1.5 rounded-md bg-brand px-5 py-1.5 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 disabled:opacity-50 transition cursor-pointer"
              >
                {isCapturing ? (
                  <>
                    <RefreshCw className="size-3.5 animate-spin" />
                    <span>Capturing State...</span>
                  </>
                ) : (
                  <span>Launch & Capture Snapshot</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
