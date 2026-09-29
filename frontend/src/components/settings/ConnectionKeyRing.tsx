// The key ring of one connection: an ordered list of keys, each with its own state,
// countdown and per-key actions. Round 29 moved the router from one credential per
// connection to a ring inside one connection, rotating only when the provider answers
// 429 — this block is the only place that ring is drawn.
//
// Two rules govern this file:
//   1. A secret never reaches the DOM. The router sends only `prefix` (a few leading
//      characters) and an already-safe `lastErrorMessage`; `maskPrefix` and `scrub` keep
//      that true even if a future router sends more.
//   2. The UI renders state, it never invents it. A key whose cooldown has passed stays
//      `cooling` until the snapshot says otherwise, and an unknown state stays `unknown`.
//
// A connection whose snapshot carries no `keys` array is the legacy single-key shape:
// `ProviderView` keeps today's `Replace API key` input for it and never mounts this block.
import { useEffect, useRef, useState } from 'react'
import { Check, Copy, Eye, EyeOff, KeyRound, Plus, RefreshCw, Save, Trash2 } from 'lucide-react'
import { api } from '../../lib/providerApi'
import { run, useProviderStore } from '../../store/providerStore'
import type { ConnectionKey, ProviderConnection } from '../../types/provider'
import { connectionKeyPath, connectionKeyRevealPath, connectionKeysImportPath, connectionKeysPath, connectionKeyTryPath } from '../../lib/routerKeyPaths'
import { Pill } from '../providers/ProviderStatus'

// Every sentence this block can print, in one place. The Settings screens are hard-coded
// English and have no i18n layer of their own (`ProviderView.tsx` calls no `t()`), so the
// copy lives here instead of inventing a second string system for one panel.
const COPY = {
  heading: 'Keys on this connection',
  hint: 'Rotates automatically when a key runs out of quota.',
  addKey: 'Add key',
  addHeading: 'New key',
  replaceHeading: 'Replace key',
  keyName: 'Key name',
  keyNamePlaceholder: 'e.g. key 2',
  secret: 'API key',
  secretPlaceholder: 'Paste the key here',
  nameHint: 'Leave it blank to use the default name "Key <n>".',
  secretHint: 'The key is never shown again after save — this page keeps a few leading characters only.',
  secretOptional: 'This provider accepts an empty key; saving adds an anonymous key to the ring.',
  saveHint: 'Saving probes the provider model list once. The key goes to the end of the rotation.',
  save: 'Save',
  cancel: 'Cancel',
  replaceKey: 'Replace key',
  removeKey: 'Remove key',
  tryNow: 'Try now',
  inUse: 'in use',
  empty: 'No key on this connection yet.',
  stateReady: 'ready',
  stateCooling: 'cooling',
  stateExhausted: 'quota exhausted',
  stateError: 'error',
  stateUnknown: 'unknown',
  checking: 'checking…',
  quotaOpens: 'quota opens',
  lastUsed: 'last used',
  mergeLabel: 'Merge keys from',
  mergeAction: 'Merge into this connection',
  merging: 'Merging…',
  mergeConfirm: (count: number, source: string) => `Move ${count} key${count === 1 ? '' : 's'} from "${source}" into this connection. The router moves them; the secret never leaves the server.`,
  moved: (count: number, target: string) => `${count} key${count === 1 ? '' : 's'} moved to "${target}". Delete this connection if you no longer need it.`,
  deleteBlocked: (count: number) => `Remove the ${count} key${count === 1 ? '' : 's'} on this connection first — delete would drop ${count === 1 ? 'it' : 'them'}.`,
  announceCooling: (label: string, at: string) => `${label} is cooling — it rejoins rotation at ${at}.`,
  announceExhausted: (label: string, at: string) => `${label} has no quota left${at ? ` — it reopens at ${at}` : ''}.`,
  announceError: (label: string) => `${label} failed: the provider refused the last call.`,
  announceReady: (label: string) => `${label} is ready again.`,
}

const field = 'w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-2 focus:ring-brand/15'
const secondary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-line bg-panel2 px-3 py-2 text-xs font-semibold text-fg transition hover:border-brand/60 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50'
const primary = 'inline-flex items-center justify-center gap-1.5 rounded-md bg-brand px-3 py-2 text-xs font-semibold text-brandfg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'
const rowButton = 'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted hover:text-brand hover:bg-brand/5 border border-transparent hover:border-brand/20 transition disabled:cursor-not-allowed disabled:opacity-50'
const rowButtonDanger = 'inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-medium text-muted hover:text-rose-600 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 transition disabled:cursor-not-allowed disabled:opacity-50'

/** What may leave this block for one key: at most six characters of the secret, always
 *  with the ellipsis so a short prefix cannot be mistaken for the whole value. */
export function maskPrefix(value?: string | null) {
  const text = typeof value === 'string' ? value : ''
  return `${text.slice(0, 6)}…`
}

/** A router error line is the provider's own text. Anything long and unbroken is treated
 *  as a possible secret and replaced, and the line is cut to one readable row. */
export function scrub(value?: string | null) {
  const text = typeof value === 'string' ? value : ''
  return text.replace(/\s+/g, ' ').trim().slice(0, 160).replace(/\S{20,}/g, '<redacted>')
}

/** How many keys a connection still holds — the UI half of the two-layer delete rule. */
export function keyRingSize(connection: ProviderConnection) {
  return Array.isArray(connection.keys) ? connection.keys.length : 0
}

/** Why the Delete button is off, or `null` when it is safe to delete. The router refuses
 *  the same delete with `409 KEYS_PRESENT`, so this line only says it earlier. */
export function deleteBlockedReason(connection: ProviderConnection) {
  const count = keyRingSize(connection)
  return count > 0 ? COPY.deleteBlocked(count) : null
}

/** The clock time a cooldown or a quota window ends. */
function clockTime(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function stateOf(key: ConnectionKey) {
  return ['ready', 'cooling', 'exhausted', 'error'].includes(key.state) ? key.state : 'unknown'
}

function stateLabel(key: ConnectionKey) {
  const state = stateOf(key)
  if (state === 'cooling') {
    const at = clockTime(key.cooldownUntil)
    return at ? `${COPY.stateCooling} · ${at}` : COPY.stateCooling
  }
  if (state === 'exhausted') return COPY.stateExhausted
  if (state === 'error') return COPY.stateError
  if (state === 'ready') return COPY.stateReady
  return COPY.stateUnknown
}

/**
 * Where a connection's keys went. `request()` reloads the whole snapshot, so the card a
 * merge emptied sees its own ring go empty with no record of who took the keys; this
 * receipt is that record. It is page-local by design: after an app reload the source card
 * shows a plain empty ring, which is also the truth on the host.
 */
const movedKeys = new Map<string, { count: number; target: string }>()

export function ConnectionKeyRing({ connection }: { connection: ProviderConnection }) {
  const request = useProviderStore((state) => state.request)
  const snapshot = useProviderStore((state) => state.snapshot)
  const busy = useProviderStore((state) => state.busy)
  const keys = Array.isArray(connection.keys) ? connection.keys : []
  const provider = snapshot?.providers.find((value) => value.id === connection.providerId)
  const anonymous = connection.providerId === 'opencode' || provider?.authModes?.includes('anonymous') === true
  const [showInput, setShowInput] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [label, setLabel] = useState('')
  const [secret, setSecret] = useState('')
  const [showInputSecret, setShowInputSecret] = useState(false)
  const [revealedSecrets, setRevealedSecrets] = useState<Map<string, string>>(new Map())
  const [visibleKeyIds, setVisibleKeyIds] = useState<Set<string>>(new Set())
  const [loadingKeyId, setLoadingKeyId] = useState<string | null>(null)
  const [copiedKeyId, setCopiedKeyId] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const [trying, setTrying] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [tick, setTick] = useState(() => Date.now())
  const coolingUntil = keys.reduce((latest, key) => Math.max(latest, Number(key.cooldownUntil) || 0), 0)
  const stateSignature = keys.map((key) => `${key.id}:${key.state}`).join('|')
  const previousStates = useRef<Map<string, ConnectionKey['state']> | null>(null)

  const fetchSecret = async (keyId: string): Promise<string> => {
    if (revealedSecrets.has(keyId)) return revealedSecrets.get(keyId)!
    try {
      const res = await api<{ id: string; key: string }>(connectionKeyRevealPath(connection.id, keyId), { method: 'GET' })
      const secretValue = typeof res?.key === 'string' ? res.key : ''
      setRevealedSecrets((prev) => new Map(prev).set(keyId, secretValue))
      return secretValue
    } catch {
      return ''
    }
  }

  const toggleVisibility = async (key: ConnectionKey) => {
    if (visibleKeyIds.has(key.id)) {
      setVisibleKeyIds((prev) => {
        const next = new Set(prev)
        next.delete(key.id)
        return next
      })
    } else {
      setLoadingKeyId(key.id)
      try {
        await fetchSecret(key.id)
        setVisibleKeyIds((prev) => new Set(prev).add(key.id))
      } finally {
        setLoadingKeyId(null)
      }
    }
  }

  const copyKey = async (target: ConnectionKey) => {
    try {
      let secretValue = revealedSecrets.get(target.id)
      if (!secretValue) {
        secretValue = await fetchSecret(target.id)
      }
      const textToCopy = secretValue || target.prefix || target.label
      await navigator.clipboard.writeText(textToCopy)
      setCopiedKeyId(target.id)
      setTimeout(() => setCopiedKeyId((curr) => (curr === target.id ? null : curr)), 1500)
    } catch { /* clipboard fallback */ }
  }

  // ONE interval for the whole ring, only while a cooldown is still in the future: every
  // cooling key counts down on the same beat. The beat checks the deadline itself, so the
  // interval stops once the last cooldown expires instead of re-rendering forever.
  useEffect(() => {
    if (coolingUntil <= Date.now()) return
    const timer = window.setInterval(() => {
      if (coolingUntil <= Date.now()) { window.clearInterval(timer); return }
      setTick(Date.now())
    }, 1000)
    return () => window.clearInterval(timer)
  }, [coolingUntil])

  // The live region reports transitions only — never the ticking seconds, which would be
  // read aloud every second.
  useEffect(() => {
    const before = previousStates.current
    previousStates.current = new Map(keys.map((key) => [key.id, key.state]))
    if (!before) return
    const changed = keys.find((key) => before.has(key.id) && before.get(key.id) !== key.state)
    if (!changed) return
    const at = clockTime(changed.cooldownUntil) ?? clockTime(changed.resetAt)
    if (changed.state === 'ready') setAnnouncement(COPY.announceReady(changed.label))
    else if (changed.state === 'cooling') setAnnouncement(COPY.announceCooling(changed.label, at ?? ''))
    else if (changed.state === 'exhausted') setAnnouncement(COPY.announceExhausted(changed.label, at ?? ''))
    else if (changed.state === 'error') setAnnouncement(COPY.announceError(changed.label))
  }, [stateSignature])

  const siblings = (snapshot?.connections ?? []).filter((entry) => entry.providerId === connection.providerId && entry.id !== connection.id && keyRingSize(entry) > 0)
  const moved = keys.length === 0 ? movedKeys.get(connection.id) : undefined

  const openAdd = () => { setEditingId(null); setLabel(''); setSecret(''); setShowInputSecret(false); setShowInput(true) }
  const openReplace = (key: ConnectionKey) => { setEditingId(key.id); setLabel(key.label); setSecret(''); setShowInputSecret(false); setShowInput(true) }
  const closeInput = () => { setShowInput(false); setEditingId(null); setLabel(''); setSecret(''); setShowInputSecret(false) }
  const submit = async () => {
    const value = secret.trim()
    if (!value && !anonymous) return
    const body: Record<string, unknown> = {}
    if (value) body.key = value
    if (label.trim()) body.label = label.trim()
    setSending(true)
    try {
      // The secret is in the request body and nowhere else: no state keeps it after this.
      await request(editingId ? connectionKeyPath(connection.id, editingId) : connectionKeysPath(connection.id), editingId ? 'PATCH' : 'POST', body)
    } catch { /* the page banner carries the router's own message */ }
    finally {
      // A failed save closes the form too: the banner is the only error surface, so the typed
      // secret must not stay in state or in the password field.
      setSending(false)
      closeInput()
    }
  }
  const removeKey = (keyId: string) => request(connectionKeyPath(connection.id, keyId), 'DELETE')
  // `Try now` is not gated on the global `busy` (a single key test must not freeze the
  // page); it only disables itself while its own request runs.
  const tryKey = async (keyId: string) => {
    setTrying(keyId)
    try { await request(connectionKeyTryPath(connection.id, keyId), 'POST') }
    catch { /* the page banner carries the router's own message */ }
    finally { setTrying(null) }
  }

  const keyRow = (key: ConnectionKey) => {
    const state = stateOf(key)
    const remaining = Math.max(0, Math.ceil((Number(key.cooldownUntil) - tick) / 1000))
    const details: string[] = []
    const resetAt = clockTime(key.resetAt)
    if (resetAt) details.push(`${COPY.quotaOpens} ${resetAt}`)
    // Note: lastUsed is removed to keep all key rows perfectly aligned
    if (key.lastErrorCode && state !== 'ready') details.push(key.lastErrorCode)
    const message = state === 'ready' ? '' : scrub(key.lastErrorMessage)

    const isVisible = visibleKeyIds.has(key.id)
    const isLoading = loadingKeyId === key.id
    const fullSecret = revealedSecrets.get(key.id)
    const keyDisplay = isVisible
      ? (fullSecret || (key.prefix ? `${key.prefix} (no secret stored)` : '(no secret stored)'))
      : '••••••••••••••••'

    return (
      <li key={key.id} aria-label={`Key ${key.label || maskPrefix(key.prefix)}`} className="group flex flex-wrap items-center justify-between gap-3 px-3.5 py-2.5 transition hover:bg-panel2/40">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <KeyRound className="size-3.5 text-muted/60 shrink-0" />
          <div className="flex items-center gap-1 rounded border border-line/60 bg-panel2 px-2 py-0.5 max-w-[20rem]">
            <span className="font-mono text-xs font-semibold text-fg truncate" title={isVisible && fullSecret ? fullSecret : `Key ${key.label}`}>
              {isLoading ? 'loading…' : keyDisplay}
            </span>
            <button
              type="button"
              disabled={isLoading}
              onClick={() => void toggleVisibility(key)}
              aria-label={isVisible ? `Hide key ${key.label}` : `Show key ${key.label}`}
              title={isVisible ? 'Hide key' : 'Show key'}
              className="ml-1 rounded p-0.5 text-muted transition hover:bg-panel hover:text-fg disabled:opacity-50"
            >
              {isLoading ? <RefreshCw className="size-3 animate-spin" /> : isVisible ? <EyeOff className="size-3" /> : <Eye className="size-3" />}
            </button>
            <button
              type="button"
              onClick={() => void copyKey(key)}
              aria-label={`Copy key ${key.label}`}
              title={copiedKeyId === key.id ? 'Copied!' : 'Copy key'}
              className="rounded p-0.5 text-muted transition hover:bg-panel hover:text-fg"
            >
              {copiedKeyId === key.id ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}
            </button>
          </div>
          <span className="min-w-0 max-w-[14rem] truncate text-xs font-medium text-fg" title={key.label}>{key.label}</span>
          {state === 'unknown'
            ? <span className="inline-flex rounded-full border border-line bg-panel2 px-2 py-0.5 text-[10px] font-semibold text-muted">{stateLabel(key)}</span>
            : <Pill value={state === 'error' ? 'failed' : state}>{stateLabel(key)}</Pill>}
          {state === 'cooling' && (remaining > 0
            ? <span aria-hidden="true" className="font-mono text-[10px] text-amber-600 dark:text-amber-400 font-semibold">{remaining}s</span>
            : <span className="font-mono text-[10px] text-muted/60">{COPY.checking}</span>)}
          {connection.activeKeyId === key.id && (
            <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
              <span className="size-1.5 rounded-full bg-emerald-500 animate-pulse" />
              {COPY.inUse}
            </span>
          )}
          {(details.length > 0 || message) && (
            <div className="flex flex-wrap items-center gap-2 text-[10px] text-muted ml-1">
              {details.length > 0 && <span>{details.join(' · ')}</span>}
              {message && <span className="min-w-0 max-w-full truncate font-mono text-rose-600 dark:text-rose-400" title={key.lastErrorCode ?? undefined}>{message}</span>}
            </div>
          )}
        </div>

        <div className="ml-auto flex items-center gap-1">
          <button type="button" onClick={() => openReplace(key)} aria-label={`${COPY.replaceKey} ${key.label}`} className={rowButton}><KeyRound className="size-3" />{COPY.replaceKey}</button>
          <button type="button" disabled={busy} onClick={() => run(removeKey(key.id))} aria-label={`${COPY.removeKey} ${key.label}`} className={rowButtonDanger}><Trash2 className="size-3" />{COPY.removeKey}</button>
          {state !== 'ready' && <button type="button" disabled={trying === key.id} aria-busy={trying === key.id} onClick={() => void tryKey(key.id)} aria-label={`Try ${key.label} now`} className={rowButton}><RefreshCw className="size-3" />{COPY.tryNow}</button>}
        </div>
      </li>
    )
  }

  return (
    <div className="mt-3.5 rounded-lg border-t border-line/60 pt-3">
      <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
        <div className="flex min-w-0 items-center gap-2">
          <KeyRound className="size-3.5 text-brand" />
          <p className="text-[10px] font-mono uppercase font-semibold text-muted tracking-wider">{COPY.heading}</p>
          <span className="rounded-full border border-line/60 bg-panel px-2 py-0.5 font-mono text-[10px] text-muted">{keys.length} keys</span>
        </div>
        <button type="button" onClick={openAdd} className={secondary}><Plus className="size-3.5" />{COPY.addKey}</button>
      </div>
      <p className="text-[11px] leading-4 text-muted">{COPY.hint}</p>
      <p role="status" aria-live="polite" className="sr-only">{announcement}</p>

      {keys.length === 0 ? (
        <div className="mt-3 rounded-lg border border-dashed border-line/80 bg-panel/30 px-4 py-6 text-center transition-all">
          <div className="mx-auto mb-2 flex size-8 items-center justify-center rounded-full bg-panel2 text-muted">
            <KeyRound className="size-4 opacity-50" />
          </div>
          <p className="text-xs font-medium text-muted">{COPY.empty}</p>
          <button type="button" onClick={openAdd} className={`${primary} mt-3 shadow-xs`}><Plus className="size-3.5" />{COPY.addKey}</button>
          {moved && <p className="mt-2 text-xs text-emerald-600 dark:text-emerald-300">{COPY.moved(moved.count, moved.target)}</p>}
        </div>
      ) : (
        <div className="mt-3 space-y-2">
          <ul role="list" className="divide-y divide-line/40 rounded-lg border border-line/70 bg-panel overflow-hidden shadow-2xs">
            {keys.map(keyRow)}
          </ul>
          {siblings.length > 0 && (
            <div className="pt-1">
              <MergeKeysRow connection={connection} siblings={siblings} />
            </div>
          )}
        </div>
      )}

      {showInput && (
        <div className="mt-3 rounded-xl border border-line/80 bg-panel p-3.5 shadow-xs transition-all">
          <div className="flex items-center gap-1.5 border-b border-line/40 pb-2">
            <KeyRound className="size-3.5 text-brand" />
            <p className="text-[10px] font-mono uppercase font-semibold text-muted">{editingId ? COPY.replaceHeading : COPY.addHeading}</p>
          </div>
          <div className="mt-2.5 grid gap-3 sm:grid-cols-2">
            <label className="text-xs font-semibold text-fg">{COPY.keyName}
              <input value={label} onChange={(event) => setLabel(event.target.value)} placeholder={COPY.keyNamePlaceholder} className={`${field} mt-1.5`} />
              <span className="mt-1 block text-[10px] font-normal leading-4 text-muted">{COPY.nameHint}</span>
            </label>
            <label className="text-xs font-semibold text-fg">{COPY.secret}
              <div className="relative mt-1.5">
                <input
                  type={showInputSecret ? 'text' : 'password'}
                  autoComplete="off"
                  value={secret}
                  onChange={(event) => setSecret(event.target.value)}
                  placeholder={COPY.secretPlaceholder}
                  className={`${field} font-mono pr-8`}
                />
                <button
                  type="button"
                  onClick={() => setShowInputSecret((s) => !s)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted transition hover:bg-panel hover:text-fg"
                  title={showInputSecret ? 'Hide key' : 'Show key'}
                  aria-label={showInputSecret ? 'Hide key' : 'Show key'}
                >
                  {showInputSecret ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
              </div>
              <span className="mt-1 block text-[10px] font-normal leading-4 text-muted">{anonymous ? COPY.secretOptional : COPY.secretHint}</span>
            </label>
          </div>
          <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 border-t border-line/40 pt-3">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" disabled={sending || (!secret.trim() && !anonymous)} aria-busy={sending} onClick={() => run(submit())} className={primary}><Save className="size-3.5" />{COPY.save}</button>
              <button type="button" onClick={closeInput} className={secondary}>{COPY.cancel}</button>
            </div>
            <p className="text-[10px] leading-4 text-muted">{COPY.saveHint}</p>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Merge the keys of another connection of the same provider into this ring. The UI sends
 * one id; the router moves the credential rows on the host. Nothing is deleted here — the
 * source keeps its card, in its empty state, and its Delete button becomes usable in case
 * the owner does not need that shell any more.
 */
function MergeKeysRow({ connection, siblings }: { connection: ProviderConnection; siblings: ProviderConnection[] }) {
  const request = useProviderStore((state) => state.request)
  const [fromId, setFromId] = useState('')
  const [merging, setMerging] = useState(false)
  const source = siblings.find((entry) => entry.id === fromId) ?? siblings[0]
  const count = keyRingSize(source)

  const merge = async () => {
    if (!source || count === 0) return
    setMerging(true)
    // Recorded before the request: the snapshot reload that follows is what re-renders the
    // source card, and it must find the receipt already in place.
    movedKeys.set(source.id, { count, target: connection.name })
    try {
      await request(connectionKeysImportPath(connection.id), 'POST', { fromConnectionId: source.id })
    } catch {
      movedKeys.delete(source.id)
    } finally {
      setMerging(false)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <label className="text-[10px] text-muted">
        <span className="sr-only">{COPY.mergeLabel}</span>
        <select aria-label={COPY.mergeLabel} value={source?.id ?? ''} onChange={(event) => setFromId(event.target.value)} className="rounded-md border border-line bg-panel px-2 py-1.5 text-[11px] text-fg outline-hidden focus:border-brand">
          {siblings.map((entry) => <option key={entry.id} value={entry.id}>{entry.name} · {keyRingSize(entry)} key{keyRingSize(entry) === 1 ? '' : 's'}</option>)}
        </select>
      </label>
      <button type="button" disabled={merging} aria-busy={merging} onClick={() => run(merge())} className={secondary}><KeyRound className="size-3.5" />{merging ? COPY.merging : COPY.mergeAction}</button>
      <p className="text-[10px] leading-4 text-muted">{source ? COPY.mergeConfirm(count, source.name) : ''}</p>
    </div>
  )
}
