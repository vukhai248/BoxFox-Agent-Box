import { useEffect, useState } from 'react'
import { AlertTriangle, Check, Globe, LoaderCircle, ShieldCheck, Sparkles } from 'lucide-react'
import { useT } from '../../i18n/context'
import { run, useProviderStore } from '../../store/providerStore'
import type { ProviderSnapshot, SearchProviderView, SearchTestResult } from '../../types/provider'
import { ProviderIcon } from '../providers/ProviderIcon'
import { Pill } from '../providers/ProviderStatus'
import { searchErrorLabel, SearchProviderModal } from './SearchProviderModal'

const secondary = 'inline-flex items-center justify-center gap-1.5 rounded-md border border-line bg-panel2 px-2.5 py-1.5 text-[11px] font-semibold text-fg transition hover:border-brand/60 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50'

/** How long a revealed key stays on screen. The timer is the panel's, not the user's
 *  memory: the secret leaves the DOM even if nobody clicks "Hide". */
export const SEARCH_KEY_REVEAL_MS = 30_000

function clockTime(value: string | null) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toLocaleString()
}

/** The verdict line of one row: the fresh test result when there is one, otherwise the
 *  last test the router recorded. Never the key, never a raw payload. */
function verdictLine(
  t: ReturnType<typeof useT>,
  lastTest: SearchProviderView['lastTest'],
): { tone: 'passed' | 'failed'; text: string } | null {
  if (!lastTest) return null
  if (lastTest.status === 'passed') return { tone: 'passed', text: t('providerSearch.testPassed', { ms: lastTest.latencyMs ?? 0 }) }
  return { tone: 'failed', text: t('providerSearch.testFailed', { message: searchErrorLabel(t, lastTest.code, lastTest.message) }) }
}

/**
 * Settings → Provider → Web Search. One tab, two jobs:
 *
 * 1. say which search source is in use — by default the built-in SearXNG that needs no
 *    key at all, and that is also the fallback whenever the chosen source fails;
 * 2. let the owner store, test, reveal and delete a key for one of the eight catalog
 *    providers.
 *
 * The raw key never enters this component's store-backed state: the router hands it over
 * only through an explicit reveal call, it is kept in local state for at most
 * `SEARCH_KEY_REVEAL_MS`, and every other surface shows the router's `prefix`.
 */
export function SearchProviderPanel({ snapshot }: { snapshot: ProviderSnapshot }) {
  const t = useT()
  const busy = useProviderStore((state) => state.busy)
  const setActive = useProviderStore((state) => state.setActiveSearchProvider)
  const remove = useProviderStore((state) => state.deleteSearchProvider)
  const reveal = useProviderStore((state) => state.revealSearchProvider)
  const test = useProviderStore((state) => state.testSearchProvider)
  const [editing, setEditing] = useState<SearchProviderView | null>(null)
  const [revealed, setRevealed] = useState<{ id: string; key: string } | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [verdict, setVerdict] = useState<{ id: string; result: SearchTestResult } | null>(null)

  useEffect(() => {
    if (!revealed) return
    const timer = window.setTimeout(() => setRevealed(null), SEARCH_KEY_REVEAL_MS)
    return () => window.clearTimeout(timer)
  }, [revealed])

  const search = snapshot.search
  // An older router answers without the search section. That is a state to explain, not
  // an error to crash on.
  if (!search) {
    return (
      <div className="rounded-xl border border-line bg-panel p-6 text-sm">
        <p className="font-semibold text-fg">{t('providerSearch.disconnectedTitle')}</p>
        <p className="mt-1 text-xs text-muted">{t('providerSearch.disconnectedBody')}</p>
      </div>
    )
  }

  const active = search.providers.find((provider) => provider.id === search.activeProviderId) ?? null
  const configured = search.providers.filter((provider) => provider.credentialPresent)
  const activeFailed = active?.lastTest?.status === 'failed'

  const revealKey = (provider: SearchProviderView) => {
    if (revealed?.id === provider.id) {
      setRevealed(null)
      return
    }
    run(reveal(provider.id).then((key) => {
      if (key) setRevealed({ id: provider.id, key })
    }))
  }

  const runTest = async (provider: SearchProviderView) => {
    setTesting(provider.id)
    try {
      const result = await test(provider.id)
      setVerdict({ id: provider.id, result })
    } finally {
      setTesting(null)
    }
  }

  const rowVerdict = (provider: SearchProviderView) => {
    const fresh = verdict?.id === provider.id ? verdict.result : null
    if (fresh) {
      return fresh.ok
        ? { tone: 'passed' as const, text: t('providerSearch.testPassed', { ms: fresh.latencyMs ?? 0 }) }
        : { tone: 'failed' as const, text: t('providerSearch.testFailed', { message: searchErrorLabel(t, fresh.code, fresh.message) }) }
    }
    return verdictLine(t, provider.lastTest)
  }

  return (
    <div aria-label={t('providerSearch.tab')} className="space-y-4">
      <p className="text-[11px] leading-4 text-muted">{t('providerSearch.subtitle')}</p>

      <section className="rounded-xl border border-line bg-panel p-3 shadow-xs sm:p-4">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg border border-line/60 bg-panel2 text-muted">
            {active ? <ProviderIcon providerId={active.icon ?? ''} name={active.name} className="size-5" decorative /> : <Globe className="size-5" />}
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-bold text-fg">{t('providerSearch.active', { name: active?.name ?? t('providerSearch.default') })}</p>
            <p className="text-[11px] text-muted">{active ? t('providerSearch.activeHint') : t('providerSearch.defaultHint')}</p>
          </div>
        </div>
        {activeFailed && (
          <p role="status" className="mt-2 flex items-center gap-1.5 text-[11px] font-semibold text-amber-700 dark:text-amber-300">
            <AlertTriangle className="size-3.5 shrink-0" />
            {t('providerSearch.warningFailed')}
          </p>
        )}
      </section>

      <section className="space-y-2">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-fg">{t('providerSearch.title')}</h2>
            {configured.length === 0 && (
              <p className="mt-0.5 text-[11px] text-muted">
                <b className="font-semibold text-fg">{t('providerSearch.emptyTitle')}</b> {t('providerSearch.emptyBody')}
              </p>
            )}
          </div>
          <span className="text-[11px] font-semibold text-muted">
            {t('providerSearch.configuredCount', { done: configured.length, total: search.providers.length })}
          </span>
        </div>

        <div className="space-y-2">
          <article data-search-provider="default" className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-panel px-3.5 py-3 shadow-xs">
            <span aria-hidden="true" className={`size-3.5 shrink-0 rounded-full border ${active ? 'border-line bg-panel2' : 'border-brand bg-brand'}`} />
            <span className="flex size-8 shrink-0 items-center justify-center rounded-md border border-line/60 bg-panel2 text-muted">
              <Sparkles className="size-4" />
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-semibold text-fg">{t('providerSearch.default')}</p>
              <p className="text-[11px] text-muted">{t('providerSearch.defaultHint')}</p>
            </div>
            {/* "In use" here means the built-in source is the selection: that is exactly when
                no named provider is active (`!active`), the same condition as the header card. */}
            {!active ? (
              <Pill value="passed">
                <span className="inline-flex items-center gap-1">
                  <Check className="size-3" />
                  {t('providerSearch.activeBadge')}
                </span>
              </Pill>
            ) : (
              <button type="button" disabled={busy} onClick={() => run(setActive(null))} className={secondary}>
                {t('providerSearch.useThis')}
              </button>
            )}
          </article>

          {search.providers.map((provider) => {
            const isActive = provider.id === search.activeProviderId
            const line = rowVerdict(provider)
            const isRevealed = revealed?.id === provider.id
            const testedAt = clockTime(provider.lastTestedAt)
            return (
              <article
                key={provider.id}
                data-search-provider={provider.id}
                className={`flex flex-wrap items-center gap-3 rounded-xl border bg-panel px-3.5 py-3 shadow-xs ${isActive ? 'border-brand/50' : 'border-line'}`}
              >
                <span aria-hidden="true" className={`size-3.5 shrink-0 rounded-full border ${isActive ? 'border-brand bg-brand' : 'border-line bg-panel2'}`} />
                <ProviderIcon providerId={provider.icon ?? ''} name={provider.name} className="size-8" decorative />
                <div className="min-w-0 flex-1">
                  <p className="text-xs font-semibold text-fg">{provider.name}</p>
                  <p className="text-[11px] text-muted">
                    {provider.credentialPresent
                      ? `${t('providerSearch.saved')}${provider.prefix ? ` · ${provider.prefix}` : ''}`
                      : t('providerSearch.notConfigured')}
                  </p>
                  {provider.envKeys.length > 0 && (
                    <p className="mt-0.5 font-mono text-[10px] text-muted/80">{t('providerSearch.envFallback', { keys: provider.envKeys.join(', ') })}</p>
                  )}
                  {line && (
                    <p className={`mt-0.5 text-[10px] font-semibold ${line.tone === 'passed' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-300'}`}>
                      {line.text}
                      {testedAt && <span className="ml-1 font-normal text-muted">· {t('providerSearch.lastTested', { time: testedAt })}</span>}
                    </p>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-1.5">
                  {isActive && (
                    <Pill value="passed">
                      <span className="inline-flex items-center gap-1">
                        <Check className="size-3" />
                        {t('providerSearch.activeBadge')}
                      </span>
                    </Pill>
                  )}
                  {!isActive && provider.credentialPresent && (
                    <button type="button" disabled={busy} onClick={() => run(setActive(provider.id))} className={secondary}>
                      {t('providerSearch.useThis')}
                    </button>
                  )}
                  <button type="button" disabled={busy} onClick={() => setEditing(provider)} className={secondary}>
                    {provider.credentialPresent ? t('providerSearch.edit') : t('providerSearch.add')}
                  </button>
                  {provider.hasSecret && (
                    <button type="button" disabled={busy} onClick={() => void revealKey(provider)} className={secondary}>
                      {isRevealed ? t('providerSearch.hide') : t('providerSearch.reveal')}
                    </button>
                  )}
                  <button type="button" disabled={testing === provider.id} onClick={() => void runTest(provider)} className={secondary}>
                    {testing === provider.id ? <LoaderCircle className="size-3 animate-spin" /> : <ShieldCheck className="size-3" />}
                    {testing === provider.id ? t('providerSearch.testing') : t('providerSearch.test')}
                  </button>
                  {provider.credentialPresent && (
                    <button type="button" disabled={busy} onClick={() => run(remove(provider.id))} className={secondary}>
                      {t('providerSearch.delete')}
                    </button>
                  )}
                </div>

                {isRevealed && (
                  <p className="w-full rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2">
                    <span className="font-mono text-xs break-all text-fg">{revealed?.key}</span>
                  </p>
                )}
              </article>
            )
          })}
        </div>
      </section>

      {editing && <SearchProviderModal provider={editing} onClose={() => setEditing(null)} />}
    </div>
  )
}
