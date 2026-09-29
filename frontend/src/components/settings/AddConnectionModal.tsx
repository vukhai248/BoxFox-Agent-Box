import { useEffect, useState } from 'react'
import { Eye, EyeOff, Plus, X } from 'lucide-react'
import { run, useProviderStore } from '../../store/providerStore'
import type { ProviderDefinition } from '../../types/provider'
import { ProviderIcon } from '../providers/ProviderIcon'

const field = 'w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-2 focus:ring-brand/15'
const secondary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-line bg-panel2 px-3 py-2 text-xs font-semibold text-fg transition hover:border-brand/60 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50'
const primary = 'inline-flex items-center justify-center gap-1.5 rounded-md bg-brand px-3 py-2 text-xs font-semibold text-brandfg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'

export function AddConnectionModal({
  open,
  onClose,
  initialProviderId,
  providers,
}: {
  open: boolean
  onClose: () => void
  initialProviderId?: string
  providers: ProviderDefinition[]
}) {
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const [providerId, setProviderId] = useState(initialProviderId ?? providers[0]?.id ?? 'openai')
  const [name, setName] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [endpoint, setEndpoint] = useState('')
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (initialProviderId) {
      setProviderId(initialProviderId)
    }
  }, [initialProviderId])

  if (!open) return null

  const chosen = providers.find((p) => p.id === providerId) ?? providers[0]
  const canSubmit = Boolean(chosen) && Boolean(apiKey.trim()) && (chosen?.id !== 'custom' || Boolean(endpoint.trim()))
  const base = endpoint.trim().replace(/\/+$/, '') || '{base}'

  const handleCreate = async () => {
    if (!chosen || !apiKey.trim()) return
    setError(null)
    try {
      await request('/api/router/connections', 'POST', {
        providerId: chosen.id,
        name: name.trim() || chosen.name,
        apiKey: apiKey.trim(),
        ...(chosen.id === 'custom' ? { endpoint: endpoint.trim() } : {}),
      })
      setApiKey('')
      setName('')
      setEndpoint('')
      onClose()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to add connection')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
      <div className="w-full max-w-lg rounded-2xl border border-line bg-panel p-5 shadow-xl sm:p-6 animate-in fade-in zoom-in-95 duration-150">
        <div className="flex items-center justify-between border-b border-line/50 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-line/60 bg-panel2 p-1">
              <ProviderIcon providerId={chosen?.id ?? ''} name={chosen?.name} className="size-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-fg">Add API Key</h2>
              <p className="text-[11px] text-muted">Connect a model provider via API key</p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1 text-muted transition hover:bg-panel2 hover:text-fg"
          >
            <X className="size-4" />
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-300">
            {error}
          </div>
        )}

        <div className="mt-4 space-y-3.5">
          <label className="block text-xs font-semibold">
            Provider
            <select
              value={providerId}
              onChange={(e) => setProviderId(e.target.value)}
              className={`${field} mt-1.5 cursor-pointer`}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name} ({p.id})
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-semibold">
            Connection name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={chosen ? `My ${chosen.name}` : 'Connection name'}
              className={`${field} mt-1.5`}
            />
          </label>

          {chosen?.id === 'custom' && (
            <label className="block text-xs font-semibold">
              Endpoint URL
              <input
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                placeholder="http://127.0.0.1:8000/v1"
                className={`${field} mt-1.5 font-mono`}
              />
              <span className="mt-1 block font-mono text-[10px] font-normal leading-4 text-muted">
                Usually ends with /v1. The router calls {base}/models and {base}/chat/completions.
              </span>
            </label>
          )}

          <label className="block text-xs font-semibold">
            API key
            <div className="relative mt-1.5">
              <input
                type={showKey ? 'text' : 'password'}
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="Paste your API key here"
                className={`${field} font-mono pr-8`}
              />
              <button
                type="button"
                onClick={() => setShowKey((s) => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted transition hover:bg-panel hover:text-fg"
                title={showKey ? 'Hide key' : 'Show key'}
                aria-label={showKey ? 'Hide key' : 'Show key'}
              >
                {showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
              </button>
            </div>
            {chosen?.id !== 'custom' && (
              <span className="mt-1 block text-[11px] font-normal text-muted">
                Uses the official endpoint for {chosen?.name}.
              </span>
            )}
          </label>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2 border-t border-line/40 pt-4">
          <button type="button" onClick={onClose} className={secondary}>
            Cancel
          </button>
          <button
            type="button"
            disabled={busy || !canSubmit}
            onClick={() => run(handleCreate())}
            className={primary}
          >
            <Plus className="size-3.5" />
            Add key
          </button>
        </div>
      </div>
    </div>
  )
}
