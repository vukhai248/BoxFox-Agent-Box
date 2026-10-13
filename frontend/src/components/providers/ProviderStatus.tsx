// Shared provider status primitives. Moved verbatim out of ProviderView.tsx so the
// provider rail, the connection cards and the hand-typed model form use one copy
// of the same status colours.
export function statusTone(value: string) {
  if (['ready', 'passed', 'ok', 'completed'].includes(value)) return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300'
  if (['failed', 'expired'].includes(value)) return 'border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300'
  return 'border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300'
}

export function Pill({ children, value = '' }: { children: React.ReactNode; value?: string }) {
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-semibold ${statusTone(value)}`}>{children}</span>
}
