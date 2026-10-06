import { useState } from 'react'

export const ICONS: Record<string, string> = {
  antigravity: '/providers/antigravity.png',
  openai: '/providers/openai.svg',
  anthropic: '/providers/anthropic.svg',
  gemini: '/providers/gemini.svg',
  custom: '/providers/custom.svg',
  'brave-search': '/providers/brave-search.png',
  tavily: '/providers/tavily.png',
  exa: '/providers/exa.png',
  firecrawl: '/providers/firecrawl.png',
  searxng: '/providers/searxng.png',
  'cloudflare-ai': '/providers/cloudflare-ai.png',
}

export function ProviderIcon({
  providerId,
  name,
  className = 'size-6',
  decorative = false,
}: {
  providerId: string
  name?: string
  className?: string
  decorative?: boolean
}) {
  const [failedProvider, setFailedProvider] = useState<string | null>(null)
  const label = name ?? providerId
  // An empty id means "this entry has no logo of its own" (the search catalog sends
  // `icon: null` for Parallel): render the monogram straight away instead of asking the
  // server for a file that does not exist.
  const src = providerId ? ICONS[providerId] ?? `/providers/${providerId}.png` : null

  if (!src || failedProvider === providerId) {
    return (
      <span
        aria-label={decorative ? undefined : `${label} icon`}
        role={decorative ? 'presentation' : undefined}
        className={`inline-flex shrink-0 items-center justify-center rounded-md border border-line bg-panel2 text-[10px] font-bold uppercase text-muted ${className}`}
      >
        {label.slice(0, 2)}
      </span>
    )
  }

  if (decorative) {
    return (
      <span
        role="presentation"
        aria-hidden="true"
        className={`inline-block shrink-0 bg-contain bg-center bg-no-repeat ${className}`}
        style={{ backgroundImage: `url(${src})` }}
      />
    )
  }

  return <img src={src} alt={`${label} icon`} className={`shrink-0 object-contain ${className}`} onError={() => setFailedProvider(providerId)} />
}
