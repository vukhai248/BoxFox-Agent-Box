import { useCallback, useEffect, useRef, useState } from 'react'
import { createPlanRepository, PlanRepositoryHttpError, reconcilePlanSelection } from '../lib/plans'
import type { PlanDocument, PlanManifest, PlanRepository, PlanSelection } from '../lib/plans'

export type PlanFilesStatus = 'loading' | 'ready' | 'empty' | 'error'

export interface PlanFilesState {
  status: PlanFilesStatus
  manifest: PlanManifest | null
  selection: PlanSelection | null
  document: PlanDocument | null
  error: string | null
  refresh: () => Promise<void>
  selectIdentity: (identity: string) => void
  selectVersion: (version: number) => void
}

/** Hook cho manifest/content, giữ lựa chọn khi refresh và bỏ mọi response cũ. */
export function usePlanFiles(repository?: PlanRepository): PlanFilesState {
  const defaultRepository = useRef<PlanRepository | null>(null)
  if (!defaultRepository.current) defaultRepository.current = createPlanRepository()
  const activeRepository = repository ?? defaultRepository.current
  const [manifest, setManifest] = useState<PlanManifest | null>(null)
  const [selection, setSelection] = useState<PlanSelection | null>(null)
  const [document, setDocument] = useState<PlanDocument | null>(null)
  const [status, setStatus] = useState<PlanFilesStatus>('loading')
  const [error, setError] = useState<string | null>(null)
  const generationRef = useRef(0)
  const selectionRef = useRef<PlanSelection | null>(null)
  const refreshRef = useRef<(() => Promise<void>) | null>(null)

  useEffect(() => {
    selectionRef.current = selection
  }, [selection])

  const loadDocument = useCallback(
    async (nextSelection: PlanSelection, retryOnMissing: boolean) => {
      const generation = ++generationRef.current
      setDocument(null)
      setStatus('loading')
      setError(null)
      try {
        const nextDocument = await activeRepository.read(nextSelection.identity, nextSelection.version)
        if (generation !== generationRef.current) return
        setDocument(nextDocument)
        setStatus('ready')
      } catch (cause) {
        if (generation !== generationRef.current) return
        if (retryOnMissing && cause instanceof PlanRepositoryHttpError && cause.status === 404) {
          void refreshRef.current?.()
          return
        }
        setError(messageFor(cause))
        setStatus('error')
      }
    },
    [activeRepository],
  )

  const refresh = useCallback(async () => {
    const generation = ++generationRef.current
    setStatus('loading')
    setError(null)
    try {
      const nextManifest = await activeRepository.list()
      if (generation !== generationRef.current) return
      const nextSelection = reconcilePlanSelection(nextManifest, selectionRef.current)
      setManifest(nextManifest)
      setSelection(nextSelection)
      setDocument(null)
      if (!nextSelection) {
        setStatus('empty')
        return
      }

      const nextDocument = await activeRepository.read(nextSelection.identity, nextSelection.version)
      if (generation !== generationRef.current) return
      setDocument(nextDocument)
      setStatus('ready')
    } catch (cause) {
      if (generation !== generationRef.current) return
      if (cause instanceof PlanRepositoryHttpError && cause.status === 404) {
        // File có thể biến mất giữa list/read; refresh manifest đúng một lần.
        try {
          const retryManifest = await activeRepository.list()
          if (generation !== generationRef.current) return
          const retrySelection = reconcilePlanSelection(retryManifest, selectionRef.current)
          setManifest(retryManifest)
          setSelection(retrySelection)
          if (!retrySelection) {
            setDocument(null)
            setStatus('empty')
            return
          }
          const retryDocument = await activeRepository.read(retrySelection.identity, retrySelection.version)
          if (generation !== generationRef.current) return
          setDocument(retryDocument)
          setStatus('ready')
          return
        } catch (retryCause) {
          if (generation !== generationRef.current) return
          setError(messageFor(retryCause))
          setStatus('error')
          return
        }
      }
      setError(messageFor(cause))
      setStatus('error')
    }
  }, [activeRepository])

  refreshRef.current = refresh

  useEffect(() => {
    void refresh()
    return () => {
      generationRef.current += 1
    }
  }, [refresh])

  const selectIdentity = useCallback(
    (identity: string) => {
      const plan = manifest?.plans.find((item) => item.identity === identity)
      const version = plan?.versions[0]
      if (!plan || !version) return
      const nextSelection = { identity, version: version.version }
      setSelection(nextSelection)
      void loadDocument(nextSelection, true)
    },
    [loadDocument, manifest],
  )

  const selectVersion = useCallback(
    (version: number) => {
      if (!selection || selection.version === version) return
      const plan = manifest?.plans.find((item) => item.identity === selection.identity)
      if (!plan?.versions.some((item) => item.version === version)) return
      const nextSelection = { identity: selection.identity, version }
      setSelection(nextSelection)
      void loadDocument(nextSelection, true)
    },
    [loadDocument, manifest, selection],
  )

  return { status, manifest, selection, document, error, refresh, selectIdentity, selectVersion }
}

function messageFor(cause: unknown): string {
  return cause instanceof Error ? cause.message : 'Unable to load plan files.'
}
