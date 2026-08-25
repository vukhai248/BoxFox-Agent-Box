import React, { useState, useRef } from 'react'
import {
  Lock,
  Plus,
  Upload,
  Edit2,
  Trash2,
  X,
  Check,
} from 'lucide-react'
import { TagMultiSelect } from './CustomSelect'

export interface SecretItem {
  id: string
  name: string
  value?: string
  note?: string
  scope: string
  label?: string
  visibility: 'team' | 'personal'
  sensitive: boolean
  updatedAt?: string
}

const INITIAL_SECRETS: SecretItem[] = []

const REPO_OPTIONS = ['All repositories', 'cloud-agent-p', 'backend-api', 'agentbox-core']

export function SecretsView() {
  const [secrets, setSecrets] = useState<SecretItem[]>(INITIAL_SECRETS)

  // Modals
  const [isAddOpen, setIsAddOpen] = useState(false)
  const [editingSecret, setEditingSecret] = useState<SecretItem | null>(null)

  // Add Modal Form State
  const [rawEnvText, setRawEnvText] = useState('')
  const [visibility, setVisibility] = useState<'team' | 'personal'>('team')
  const [scopes, setScopes] = useState<string[]>(['All repositories'])
  const [label, setLabel] = useState('')
  const [importSuccessCount, setImportSuccessCount] = useState<number | null>(null)

  // Edit Modal Form State
  const [editValue, setEditValue] = useState('')
  const [editNote, setEditNote] = useState('')
  const [editScopes, setEditScopes] = useState<string[]>(['All repositories'])
  const [editLabel, setEditLabel] = useState('')
  const [editSensitive, setEditSensitive] = useState(true)

  const fileInputRef = useRef<HTMLInputElement>(null)

  // Parse .env text helper
  const parseEnvContent = (text: string): { name: string; value: string; note: string }[] => {
    const lines = text.split('\n')
    const results: { name: string; value: string; note: string }[] = []
    let pendingComment = ''

    for (const rawLine of lines) {
      const line = rawLine.trim()
      if (!line) {
        pendingComment = ''
        continue
      }

      if (line.startsWith('#')) {
        pendingComment = line.replace(/^#+\s*/, '')
        continue
      }

      const eqIdx = line.indexOf('=')
      if (eqIdx > 0) {
        const key = line.slice(0, eqIdx).trim()
        let remainder = line.slice(eqIdx + 1).trim()
        let inlineComment = ''

        const commentIdx = remainder.indexOf('#')
        if (commentIdx > 0) {
          inlineComment = remainder.slice(commentIdx + 1).trim()
          remainder = remainder.slice(0, commentIdx).trim()
        }

        // strip surrounding quotes
        let val = remainder
        if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
          val = val.slice(1, -1)
        }

        const note = inlineComment || pendingComment
        if (key) {
          results.push({ name: key, value: val, note })
        }
        pendingComment = ''
      } else if (!line.includes('=')) {
        results.push({ name: line, value: '', note: pendingComment })
        pendingComment = ''
      }
    }

    return results
  }

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (event) => {
      const content = event.target?.result as string
      if (content) {
        setRawEnvText(content)
      }
    }
    reader.readAsText(file)
  }

  const handleSaveAddSecrets = () => {
    const parsed = parseEnvContent(rawEnvText)
    if (parsed.length === 0) return

    const newItems: SecretItem[] = parsed.map((p, idx) => ({
      id: `SEC-${Date.now()}-${idx}`,
      name: p.name,
      value: p.value,
      note: p.note || undefined,
      scope: scopes.join(', '),
      label: label.trim() || undefined,
      visibility,
      sensitive: true,
      updatedAt: 'Just now',
    }))

    setSecrets((prev) => [...newItems, ...prev])
    setImportSuccessCount(newItems.length)

    setTimeout(() => {
      setIsAddOpen(false)
      setRawEnvText('')
      setLabel('')
      setScopes(['All repositories'])
      setImportSuccessCount(null)
    }, 600)
  }

  const handleOpenEdit = (sec: SecretItem) => {
    setEditingSecret(sec)
    setEditValue(sec.value || '')
    setEditNote(sec.note || '')
    setEditScopes(sec.scope ? sec.scope.split(', ').map((s) => s.trim()) : ['All repositories'])
    setEditLabel(sec.label || '')
    setEditSensitive(sec.sensitive ?? true)
  }

  const handleSaveEdit = () => {
    if (!editingSecret) return
    setSecrets((prev) =>
      prev.map((s) =>
        s.id === editingSecret.id
          ? {
              ...s,
              value: editValue || s.value,
              note: editNote || undefined,
              scope: editScopes.join(', '),
              label: editLabel.trim() || undefined,
              sensitive: editSensitive,
              updatedAt: 'Just now',
            }
          : s,
      ),
    )
    setEditingSecret(null)
  }

  const handleDeleteSecret = (id: string) => {
    setSecrets((prev) => prev.filter((s) => s.id !== id))
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Machines</span>
        <span>›</span>
        <span className="text-fg font-semibold">Secrets</span>
      </div>

      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-line pb-4">
        <div>
          <h1 className="text-xl font-bold text-fg">Secrets</h1>
          <p className="text-xs text-muted mt-0.5">
            Manage environment variables and API keys available to agent execution sandboxes.
          </p>
        </div>

        <button
          type="button"
          onClick={() => setIsAddOpen(true)}
          className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
        >
          <Plus className="size-3.5" />
          <span>Add Secrets</span>
        </button>
      </div>

      {/* Secrets Table or Empty State */}
      {secrets.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center rounded-xl border border-line bg-panel shadow-xs">
          <div className="flex size-12 items-center justify-center rounded-xl bg-brand/10 text-brand mb-3">
            <Lock className="size-6" />
          </div>
          <h3 className="text-sm font-semibold text-fg">No secrets configured</h3>
          <p className="text-xs text-muted max-w-md mt-1 mb-4">
            Add environment variables and API keys to make them accessible inside agent sandboxes and background containers.
          </p>
          <button
            type="button"
            onClick={() => setIsAddOpen(true)}
            className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
          >
            <Plus className="size-3.5" />
            <span>Add Secrets</span>
          </button>
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-line bg-panel shadow-xs">
          <table className="w-full text-left text-xs">
            <thead className="border-b border-line bg-panel2/60 text-[11px] font-semibold text-muted">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Note</th>
                <th className="px-4 py-3">Scope</th>
                <th className="px-4 py-3">Label</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/60">
              {secrets.map((sec) => (
                <tr key={sec.id} className="transition hover:bg-panel2/30">
                  <td className="px-4 py-3 font-mono font-medium text-fg flex items-center gap-2">
                    <Lock className="size-3 text-muted" />
                    <span>{sec.name}</span>
                  </td>
                  <td className="px-4 py-3 text-muted text-[11px]">
                    {sec.note || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded bg-panel2 border border-line px-2 py-0.5 text-[11px] font-mono text-fg">
                      {sec.scope}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-muted font-mono text-[11px]">
                    {sec.label || '—'}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        type="button"
                        onClick={() => handleOpenEdit(sec)}
                        className="p-1 rounded text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
                        title="Edit secret"
                      >
                        <Edit2 className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteSecret(sec.id)}
                        className="p-1 rounded text-muted hover:text-rose-500 hover:bg-rose-500/10 transition cursor-pointer"
                        title="Delete secret"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ========================================================================= */}
      {/* ADD SECRETS MODAL */}
      {/* ========================================================================= */}
      {isAddOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="relative w-full max-w-xl rounded-2xl border border-line bg-panel p-6 shadow-2xl space-y-4">
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-line pb-3">
              <h3 className="text-sm font-bold text-fg">Add Secrets</h3>
              <button
                type="button"
                onClick={() => setIsAddOpen(false)}
                className="text-muted hover:text-fg transition cursor-pointer p-1 rounded-md hover:bg-panel2"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* Input / Textarea Box for raw .env or secret name */}
            <div className="space-y-2.5">
              <div className="relative">
                <textarea
                  rows={2}
                  value={rawEnvText}
                  onChange={(e) => setRawEnvText(e.target.value)}
                  placeholder="Paste your .env or type a secret name (optional)"
                  className="w-full rounded-lg border border-line bg-panel2 px-3.5 py-2.5 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand focus:ring-1 focus:ring-brand font-mono resize-y"
                  autoFocus
                />
              </div>

              {/* Upload .env file button */}
              <div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".env,text/plain"
                  onChange={handleFileUpload}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  className="flex items-center gap-1.5 rounded-lg border border-line bg-panel2 px-3 py-1.5 text-xs font-semibold text-fg hover:bg-panel hover:text-fg transition cursor-pointer"
                >
                  <Upload className="size-3.5 text-muted" />
                  <span>Upload .env file</span>
                </button>
              </div>
            </div>

            {/* Expected .env format info card */}
            <div className="rounded-xl border border-line bg-panel2 p-3 text-[11px] font-mono text-muted space-y-1">
              <span className="font-semibold text-fg block mb-1">Expected .env format</span>
              <p className="text-muted"># Note shown above the secret</p>
              <p className="text-fg">API_KEY=your_value <span className="text-muted"># Inline note</span></p>
              <p className="text-fg">DB_HOST="localhost"</p>
              <p className="text-[10px] text-muted pt-1 leading-relaxed font-sans">
                Comments directly above a variable, or inline using # note, prefill its Note field. Notes are stored and shown in plain text.
              </p>
            </div>

            {/* Visibility Pills */}
            <div className="flex items-center gap-3 pt-1">
              <span className="text-xs font-medium text-fg">Visibility:</span>
              <div className="flex items-center rounded-lg border border-line bg-panel2 p-0.5">
                <button
                  type="button"
                  onClick={() => setVisibility('team')}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition cursor-pointer ${
                    visibility === 'team'
                      ? 'bg-panel text-fg font-semibold border border-line shadow-xs'
                      : 'text-muted hover:text-fg'
                  }`}
                >
                  Team shared
                </button>
                <button
                  type="button"
                  onClick={() => setVisibility('personal')}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition cursor-pointer ${
                    visibility === 'personal'
                      ? 'bg-panel text-fg font-semibold border border-line shadow-xs'
                      : 'text-muted hover:text-fg'
                  }`}
                >
                  Personal
                </button>
              </div>
            </div>

            {/* Apply to (Custom Tag Multi-Select) */}
            <div className="space-y-1.5">
              <span className="text-xs font-medium text-fg">Apply to:</span>
              <TagMultiSelect
                values={scopes}
                onChange={setScopes}
                options={REPO_OPTIONS}
              />
            </div>

            {/* Label (optional) */}
            <div className="space-y-1">
              <label className="block text-xs font-medium text-fg">Label (optional)</label>
              <input
                type="text"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. staging"
                className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono"
              />
              <p className="text-[10px] text-muted">
                For example, label staging exports <code className="text-fg font-mono">DATABASE_URL__STAGING</code>.
              </p>
            </div>

            {/* Footer Buttons */}
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-line">
              <button
                type="button"
                onClick={() => setIsAddOpen(false)}
                className="rounded-md border border-line bg-panel2 px-4 py-1.5 text-xs font-medium text-muted hover:text-fg transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveAddSecrets}
                disabled={!rawEnvText.trim()}
                className="flex items-center gap-1.5 rounded-md bg-brand px-5 py-1.5 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 disabled:opacity-50 transition cursor-pointer"
              >
                {importSuccessCount !== null ? (
                  <>
                    <Check className="size-3.5" />
                    <span>Imported {importSuccessCount} Secrets!</span>
                  </>
                ) : (
                  <span>Save</span>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* EDIT SECRET MODAL */}
      {/* ========================================================================= */}
      {editingSecret && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="relative w-full max-w-lg rounded-2xl border border-line bg-panel p-6 shadow-2xl space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between border-b border-line pb-3">
              <div>
                <h3 className="text-sm font-bold text-fg">
                  Edit secret: {editingSecret.name}
                </h3>
                <p className="text-xs text-muted mt-0.5">
                  Update the value, note, sensitivity, or scope of this secret.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setEditingSecret(null)}
                className="text-muted hover:text-fg transition cursor-pointer p-1 rounded-md hover:bg-panel2"
              >
                <X className="size-4" />
              </button>
            </div>

            {/* New Secret Value */}
            <div className="space-y-1">
              <label className="block text-xs font-semibold text-fg">
                New secret value
              </label>
              <textarea
                rows={4}
                value={editValue}
                onChange={(e) => setEditValue(e.target.value)}
                placeholder="Paste new secret value"
                className="w-full rounded-lg border border-line bg-panel2 p-3 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono"
              />
              <p className="text-[10px] text-muted">
                An existing value is configured and hidden. Leave this field untouched to keep the current value.
              </p>
            </div>

            {/* Note (optional) */}
            <div className="space-y-1">
              <label className="block text-xs font-semibold text-fg">Note (optional)</label>
              <input
                type="text"
                value={editNote}
                onChange={(e) => setEditNote(e.target.value)}
                placeholder="What is this secret used for?"
                className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand"
              />
            </div>

            {/* Apply to (Custom Tag Multi-Select) */}
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Apply to</label>
              <TagMultiSelect
                values={editScopes}
                onChange={setEditScopes}
                options={REPO_OPTIONS}
              />
            </div>

            {/* Label (optional) */}
            <div className="space-y-1">
              <label className="block text-xs font-semibold text-fg">Label (optional)</label>
              <input
                type="text"
                value={editLabel}
                onChange={(e) => setEditLabel(e.target.value)}
                placeholder="e.g. staging"
                className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono"
              />
            </div>

            {/* Sensitive Switch */}
            <div className="rounded-lg border border-line bg-panel2 p-3 flex items-center justify-between">
              <div>
                <span className="text-xs font-semibold text-fg">Sensitive</span>
                <p className="text-[10px] text-muted">Sensitive secrets are redacted in the UI.</p>
              </div>
              <button
                type="button"
                onClick={() => setEditSensitive(!editSensitive)}
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                  editSensitive ? 'bg-brand border-brand' : 'bg-panel border-line'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                    editSensitive ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {/* Footer Buttons */}
            <div className="flex items-center justify-end gap-3 pt-3 border-t border-line">
              <button
                type="button"
                onClick={() => setEditingSecret(null)}
                className="rounded-md border border-line bg-panel2 px-4 py-1.5 text-xs font-medium text-muted hover:text-fg transition cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveEdit}
                className="rounded-md bg-brand px-5 py-1.5 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
              >
                Update secret
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
