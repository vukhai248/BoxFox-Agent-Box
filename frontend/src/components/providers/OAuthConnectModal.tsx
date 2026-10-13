import { useState, useEffect } from 'react'
import {
  AlertCircle,
  Check,
  Copy,
  ExternalLink,
  LoaderCircle,
  RotateCw,
  X,
} from 'lucide-react'
import { api } from '../../lib/providerApi'
import type { OAuthAttempt, ProviderDefinition } from '../../types/provider'
import { ProviderIcon } from './ProviderIcon'

interface OAuthConnectModalProps {
  isOpen: boolean
  provider: ProviderDefinition
  attempt: OAuthAttempt | null
  onClose: () => void
  onSuccess: () => void
}

export function OAuthConnectModal({
  isOpen,
  provider,
  attempt,
  onClose,
  onSuccess,
}: OAuthConnectModalProps) {
  const [callbackInput, setCallbackInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [copiedLink, setCopiedLink] = useState(false)
  const [copiedCode, setCopiedCode] = useState(false)

  const isDeviceFlow =
    attempt?.flowType === 'device_code' ||
    Boolean(attempt?.userCode)

  // Listen for popup callback messages via window.postMessage & BroadcastChannel
  useEffect(() => {
    if (!isOpen || !attempt?.id) return

    const handleMessage = async (event: MessageEvent) => {
      if (
        event.data?.type === 'oauth_callback' &&
        (event.data.code || event.data.fullUrl)
      ) {
        await submitCallback(event.data.fullUrl || event.data.code)
      }
    }

    window.addEventListener('message', handleMessage)

    let bc: BroadcastChannel | null = null
    if (typeof BroadcastChannel !== 'undefined') {
      try {
        bc = new BroadcastChannel('oauth_callback')
        bc.onmessage = async (event) => {
          if (event.data?.code || event.data?.fullUrl) {
            await submitCallback(event.data.fullUrl || event.data.code)
          }
        }
      } catch {
        /* best effort */
      }
    }

    return () => {
      window.removeEventListener('message', handleMessage)
      bc?.close()
    }
  }, [isOpen, attempt?.id])

  if (!isOpen || !attempt) return null

  const handleCopyLink = () => {
    if (!attempt.authorizationUrl) return
    navigator.clipboard.writeText(attempt.authorizationUrl)
    setCopiedLink(true)
    setTimeout(() => setCopiedLink(false), 2000)
  }

  const handleCopyCode = () => {
    if (!attempt.userCode) return
    navigator.clipboard.writeText(attempt.userCode)
    setCopiedCode(true)
    setTimeout(() => setCopiedCode(false), 2000)
  }

  const submitCallback = async (rawInput?: string) => {
    const input = (rawInput ?? callbackInput).trim()
    if (!input) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      await api(`/api/router/oauth/attempts/${encodeURIComponent(attempt.id)}/callback`, {
        method: 'POST',
        body: { callbackUrl: input },
      })
      onSuccess()
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to complete authorization.')
    } finally {
      setSubmitting(false)
    }
  }

  const handleReopenPopup = () => {
    if (attempt.authorizationUrl) {
      window.open(attempt.authorizationUrl, 'boxfox-provider-oauth', 'popup,width=560,height=740')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 p-4 backdrop-blur-xs animate-fade-in">
      <div className="relative w-full max-w-lg rounded-2xl border border-line bg-panel p-6 shadow-2xl text-fg space-y-5 animate-pop-in">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <ProviderIcon
              providerId={provider.id}
              name={provider.name}
              className="size-10 rounded-xl border border-line bg-panel2 p-1.5"
            />
            <div>
              <h2 className="text-base font-semibold">Connect {provider.name}</h2>
              <p className="text-xs text-muted">
                {isDeviceFlow
                  ? 'Complete authorization using the device code below'
                  : 'Sign in to your account to authorize access'}
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-muted transition hover:bg-panel2 hover:text-fg"
          >
            <X className="size-4" />
          </button>
        </div>

        {/* Global Error Banner */}
        {(attempt.error || submitError) && (
          <div className="flex items-start gap-2 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-700 dark:text-red-300">
            <AlertCircle className="size-4 shrink-0 mt-0.5" />
            <div className="space-y-1">
              <p className="font-semibold">Authorization failed</p>
              <p className="opacity-90">{submitError || attempt.error}</p>
            </div>
          </div>
        )}

        {/* Device Flow UI */}
        {isDeviceFlow ? (
          <div className="space-y-4">
            <div className="rounded-xl border border-line bg-panel2 p-4 text-center space-y-3">
              <p className="text-xs text-muted">Enter this code on the verification page:</p>
              <div className="flex items-center justify-center gap-3">
                <span className="font-mono text-2xl font-bold tracking-wider text-brand px-3 py-1 rounded-lg bg-panel border border-brand/20">
                  {attempt.userCode || '----'}
                </span>
                <button
                  type="button"
                  onClick={handleCopyCode}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-2 text-xs font-semibold text-fg transition hover:border-brand/60 hover:text-brand"
                >
                  {copiedCode ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
                  {copiedCode ? 'Copied' : 'Copy'}
                </button>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <a
                href={attempt.verificationUri || 'https://github.com/login/device'}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-brand px-4 py-2.5 text-xs font-semibold text-brandfg transition hover:opacity-90"
              >
                <ExternalLink className="size-3.5" />
                Open GitHub Verification Page
              </a>
            </div>

            <div className="flex items-center justify-center gap-2 py-2 text-xs text-muted">
              <LoaderCircle className="size-4 animate-spin text-brand" />
              Waiting for authorization confirmation...
            </div>
          </div>
        ) : (
          /* Browser OAuth Flow UI */
          <div className="space-y-4">
            {/* Waiting status */}
            <div className="flex items-center justify-between rounded-xl border border-brand/20 bg-brand/5 p-3.5">
              <div className="flex items-center gap-2.5">
                <LoaderCircle className="size-4 animate-spin text-brand" />
                <span className="text-xs font-medium">Waiting for authorization in popup...</span>
              </div>
              <button
                type="button"
                onClick={handleReopenPopup}
                className="inline-flex items-center gap-1 text-xs font-semibold text-brand transition hover:underline"
              >
                <RotateCw className="size-3" />
                Re-open popup
              </button>
            </div>

            {/* Manual fallback section */}
            <div className="rounded-xl border border-line bg-panel2/60 p-4 space-y-3.5">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold">Manual authorization fallback</p>
                <span className="text-[11px] text-muted">If popup is blocked or fails</span>
              </div>

              {/* Step 1: Copy auth link */}
              <div className="space-y-1.5">
                <label className="text-[11px] text-muted font-medium">
                  Step 1: Copy authorization link
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    readOnly
                    value={attempt.authorizationUrl || ''}
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-mono text-muted outline-hidden truncate select-all"
                  />
                  <button
                    type="button"
                    onClick={handleCopyLink}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-semibold text-fg transition hover:border-brand/60 hover:text-brand"
                  >
                    {copiedLink ? <Check className="size-3.5 text-emerald-500" /> : <Copy className="size-3.5" />}
                    {copiedLink ? 'Copied' : 'Copy'}
                  </button>
                </div>
              </div>

              {/* Step 2: Paste callback URL */}
              <div className="space-y-1.5">
                <label className="text-[11px] text-muted font-medium">
                  Step 2: Paste callback URL or code from address bar
                </label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={callbackInput}
                    onChange={(e) => setCallbackInput(e.target.value)}
                    placeholder={
                      provider.id === 'codex'
                        ? 'http://localhost:1455/auth/callback?code=...'
                        : 'http://localhost:.../oauth-callback?code=...'
                    }
                    className="w-full rounded-lg border border-line bg-panel px-3 py-1.5 text-xs font-mono text-fg outline-hidden transition focus:border-brand focus:ring-2 focus:ring-brand/15"
                  />
                  <button
                    type="button"
                    disabled={submitting || !callbackInput.trim()}
                    onClick={() => submitCallback()}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-brandfg transition hover:opacity-90 disabled:opacity-50"
                  >
                    {submitting ? <LoaderCircle className="size-3.5 animate-spin" /> : null}
                    Complete
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end gap-2 pt-1 border-t border-line">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-line bg-panel2 px-4 py-2 text-xs font-semibold text-fg transition hover:border-brand/60 hover:text-brand"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
