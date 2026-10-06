import { useState } from 'react'
import { Eye, EyeOff, KeyRound, Plus, X } from 'lucide-react'
import { useT, type TKey, type TVars } from '../../i18n/context'
import { ProviderApiError } from '../../lib/providerApi'
import { searchProviderPath, searchProvidersPath } from '../../lib/searchProviderPaths'
import { run, useProviderStore } from '../../store/providerStore'
import type { SearchProviderView } from '../../types/provider'
import { ProviderIcon } from '../providers/ProviderIcon'

const field = 'w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-2 focus:ring-brand/15'
const secondary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-line bg-panel2 px-3 py-2 text-xs font-semibold text-fg transition hover:border-brand/60 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50'
const primary = 'inline-flex items-center justify-center gap-1.5 rounded-md bg-brand px-3 py-2 text-xs font-semibold text-brandfg transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50'

/** Every router refusal this dialog can produce, in the user's language. A code the
 *  dictionary does not know is shown as-is rather than swallowed. */
const ERROR_KEYS: Record<string, TKey> = {
  INVALID_ENDPOINT: 'providerSearch.errors.INVALID_ENDPOINT',
  CREDENTIAL_REQUIRED: 'providerSearch.errors.CREDENTIAL_REQUIRED',
  ALREADY_CONFIGURED: 'providerSearch.errors.ALREADY_CONFIGURED',
  NOT_FOUND: 'providerSearch.errors.NOT_FOUND',
  INVALID_REQUEST: 'providerSearch.errors.INVALID_REQUEST',
  REQUEST_FAILED: 'providerSearch.errors.REQUEST_FAILED',
}

/**
 * The sentence a router error or a test verdict gets on screen. The router's own message
 * wins when it has one (it names the upstream status); otherwise the code is translated,
 * and an unknown code is printed instead of being hidden.
 */
export function searchErrorLabel(t: (key: TKey, vars?: TVars) => string, code: string | null | undefined, message?: string | null) {
  if (message) return message
  if (code && ERROR_KEYS[code]) return t(ERROR_KEYS[code])
  return code || t('providerSearch.errors.REQUEST_FAILED')
}

/** Only http/https, no credentials, no query — the same shape the router's own
 *  `validateEndpoint()` accepts, checked here so the user is told before the round-trip. */
export function endpointIsValid(value: string) {
  try {
    const url = new URL(value.trim())
    return (url.protocol === 'http:' || url.protocol === 'https:') && url.username === '' && url.password === '' && url.search === '' && url.hash === ''
  } catch {
    return false
  }
}

/**
 * Add or edit one search-provider entry. Which fields appear is decided by the catalog's
 * `requires`/`optional` lists, not by a hard-coded table here — a new field on the router
 * side shows up as soon as the catalog names it.
 *
 * Editing never sends the stored key back: the current key is shown as the router's
 * `prefix`, and the input starts empty. An empty input means "keep the stored key".
 */
export function SearchProviderModal({
  provider,
  onClose,
}: {
  provider: SearchProviderView
  onClose: () => void
}) {
  const t = useT()
  const request = useProviderStore((state) => state.request)
  const busy = useProviderStore((state) => state.busy)
  const editing = provider.credentialPresent
  const wantsApiKey = provider.requires.includes('apiKey') || provider.optional.includes('apiKey')
  const wantsEndpoint = provider.requires.includes('endpoint') || provider.optional.includes('endpoint')
  const wantsAccountId = provider.requires.includes('accountId') || provider.optional.includes('accountId')
  const [apiKey, setApiKey] = useState('')
  const [endpoint, setEndpoint] = useState(provider.endpoint ?? '')
  const [accountId, setAccountId] = useState(provider.accountId ?? '')
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const endpointMissing = wantsEndpoint && provider.requires.includes('endpoint') && !endpoint.trim()
  const endpointInvalid = wantsEndpoint && endpoint.trim() !== '' && !endpointIsValid(endpoint)
  // Chỉ `requires` mới chặn Lưu. `custom` khai `optional: ['apiKey']` (endpoint tự do, khoá Bearer tuỳ
  // chọn), nên bắt nó phải có khoá sẽ khoá mất một cấu hình đã được ghi trong hợp đồng.
  const apiKeyRequired = provider.requires.includes('apiKey')
  const canSubmit = Boolean(
    (!apiKeyRequired || apiKey.trim() || (editing && provider.hasSecret))
    && (!wantsAccountId || accountId.trim())
    && !endpointMissing && !endpointInvalid,
  )

  const handleSave = async () => {
    setError(null)
    const values = {
      ...(wantsApiKey && apiKey.trim() ? { apiKey: apiKey.trim() } : {}),
      ...(wantsEndpoint ? { endpoint: endpoint.trim() } : {}),
      ...(wantsAccountId ? { accountId: accountId.trim() } : {}),
    }
    try {
      await request(
        editing ? searchProviderPath(provider.id) : searchProvidersPath(),
        editing ? 'PATCH' : 'POST',
        editing ? values : { providerId: provider.id, ...values },
      )
      onClose()
    } catch (err) {
      const code = err instanceof ProviderApiError ? err.code : null
      setError(searchErrorLabel(t, code, err instanceof Error ? err.message : null))
    }
  }

  const title = editing ? t('providerSearch.modalEditTitle') : t('providerSearch.modalAddTitle')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs">
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${title} — ${provider.name}`}
        className="w-full max-w-lg rounded-2xl border border-line bg-panel p-5 shadow-xl sm:p-6"
      >
        <div className="flex items-center justify-between border-b border-line/50 pb-3">
          <div className="flex items-center gap-2.5">
            <div className="flex size-8 shrink-0 items-center justify-center rounded-lg border border-line/60 bg-panel2 p-1">
              <ProviderIcon providerId={provider.icon ?? ''} name={provider.name} className="size-5" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-fg">{title}</h2>
              <p className="text-[11px] text-muted">{t('providerSearch.modalSubtitle', { name: provider.name })}</p>
            </div>
          </div>
          <button type="button" onClick={onClose} aria-label={t('common.close')} className="rounded-lg p-1 text-muted transition hover:bg-panel2 hover:text-fg">
            <X className="size-4" />
          </button>
        </div>

        {error && (
          <div role="alert" className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-600 dark:text-red-300">
            {error}
          </div>
        )}

        <div className="mt-4 space-y-3.5">
          {editing && provider.hasSecret && (
            <div className="flex items-center gap-2 rounded-lg border border-line/60 bg-panel2 px-3 py-2">
              <KeyRound className="size-3.5 shrink-0 text-muted/70" />
              <span className="font-mono text-xs font-semibold text-fg">{provider.prefix ?? '••••••'}</span>
              <span className="text-[11px] text-muted">{t('providerSearch.saved')}</span>
            </div>
          )}

          {wantsAccountId && (
            <label className="block text-xs font-semibold">
              {t('providerSearch.fieldAccountId')}
              <input
                type="text"
                value={accountId}
                onChange={(event) => setAccountId(event.target.value)}
                autoComplete="off"
                className={`${field} mt-1.5 font-mono`}
              />
              <span className="mt-1 block text-[11px] font-normal text-muted">{t('providerSearch.accountHint')}</span>
            </label>
          )}

          {wantsEndpoint && (
            <label className="block text-xs font-semibold">
              {t('providerSearch.fieldEndpoint')}
              <input
                type="text"
                value={endpoint}
                onChange={(event) => setEndpoint(event.target.value)}
                placeholder="http://127.0.0.1:8888"
                autoComplete="off"
                aria-invalid={endpointInvalid}
                className={`${field} mt-1.5 font-mono`}
              />
              <span className={`mt-1 block text-[11px] font-normal ${endpointInvalid ? 'text-red-600 dark:text-red-300' : 'text-muted'}`}>
                {endpointInvalid ? t('providerSearch.endpointRequired') : t('providerSearch.endpointHint')}
              </span>
            </label>
          )}

          {wantsApiKey && (
            <label className="block text-xs font-semibold">
              {t('providerSearch.fieldApiKey')}
              <div className="relative mt-1.5">
                <input
                  type={showKey ? 'text' : 'password'}
                  autoComplete="off"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                  className={`${field} pr-8 font-mono`}
                />
                <button
                  type="button"
                  onClick={() => setShowKey((value) => !value)}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted transition hover:bg-panel hover:text-fg"
                  title={showKey ? t('providerSearch.hide') : t('providerSearch.reveal')}
                  aria-label={showKey ? t('providerSearch.hide') : t('providerSearch.reveal')}
                >
                  {showKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
                </button>
              </div>
              <span className="mt-1 block text-[11px] font-normal text-muted">
                {editing && provider.hasSecret ? t('providerSearch.keepKeyHint') : t('providerSearch.fieldHint')}
              </span>
            </label>
          )}
        </div>

        <div className="mt-5 flex items-center justify-end gap-2 border-t border-line/40 pt-4">
          <button type="button" onClick={onClose} className={secondary}>{t('providerSearch.cancel')}</button>
          <button type="button" disabled={busy || !canSubmit} onClick={() => run(handleSave())} className={primary}>
            <Plus className="size-3.5" />
            {t('providerSearch.modalSave')}
          </button>
        </div>
      </div>
    </div>
  )
}
