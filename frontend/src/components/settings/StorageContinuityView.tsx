import { useEffect, useState } from 'react'
import { useT } from '../../i18n/context'
import { agentApi } from '../../lib/agentApi'
import { capsuleVerified, type DeletionPreview, type StorageSnapshot } from '../../types/longtask'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { useAgentStore } from '../../store/agentStore'

const button = 'rounded-lg border border-line px-3 py-1.5 disabled:opacity-40 hover:bg-panel2'
export function StorageContinuityView({ sessionId, onDeleted }: { sessionId: string; onDeleted?: () => void }) {
  const t = useT()
  const [storage, setStorage] = useState<StorageSnapshot | null>(null)
  const [preview, setPreview] = useState<DeletionPreview | null>(null)
  const [ack, setAck] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [outcome, setOutcome] = useState<string | null>(null)
  const load = () => agentApi<StorageSnapshot>(`/history/storage?callerSessionId=${encodeURIComponent(sessionId)}`).then(setStorage)
  useEffect(() => {
    let active = true
    agentApi<StorageSnapshot>(`/history/storage?callerSessionId=${encodeURIComponent(sessionId)}`)
      .then(value => { if (active) setStorage(value) }).catch(reason => { if (active) setError(String(reason)) })
    return () => { active = false }
  }, [sessionId])
  const contribution = storage?.bySession?.[sessionId]
  const verified = capsuleVerified(preview)
  // Sau khi xoá, `history/storage` của chính phiên đó trả 404 `SESSION_NOT_FOUND` — đó là KẾT QUẢ
  // MONG ĐỢI của việc vừa xong, không phải lỗi. Hiện số đo cũ là sai (dữ liệu đã bị xoá), nên bỏ số
  // đo và giữ nguyên thông báo thành công; mọi lỗi khác vẫn phải nói ra.
  const reloadAfterDelete = async () => {
    try {
      await load()
    } catch (reason) {
      if (String(reason).includes('SESSION_NOT_FOUND')) setStorage(null)
      else setError(String(reason))
    }
  }
  const prepare = async () => {
    setBusy(true); setPreview(null); setAck(false); setConfirm(false); setError(null); setOutcome(null)
    try {
      // Kho tính `expectedRevision` trong `deletion_preview` và trả về ở preview; GET session không có
      // trường revision nào để prebind, nên gửi đúng một body tối thiểu.
      const value = await agentApi<DeletionPreview>(`/sessions/${encodeURIComponent(sessionId)}/deletion-preview`, { mode: 'history_only' })
      setPreview(value)
    } catch (reason) { setError(String(reason)) } finally { setBusy(false) }
  }
  const remove = async () => {
    if (!verified || !ack || !confirm || !preview || busy) return
    setBusy(true); setError(null)
    try {
      const result = await useHarnessChatStore.getState().deleteSession(sessionId, {
        operationId: preview.operationId, expectedRevision: preview.expectedRevision! })
      setOutcome(result.status)
      setConfirm(false); setAck(false); setPreview(null)
      await reloadAfterDelete()
      if (result.status === 'deleted') onDeleted?.()
    } catch (reason) {
      setError(String(reason)); setPreview(null); setAck(false); setConfirm(false)
    } finally { setBusy(false) }
  }
  return <section data-testid="storage-continuity" className="rounded-xl border border-line bg-panel p-4 text-xs space-y-3">
    <h2 className="font-semibold">{t('continuity.storage')}</h2>
    {storage && <>
      <p className={storage.level === 'elevated' ? 'text-rose-400' : storage.level === 'warning' ? 'text-amber-400' : 'text-muted'}>{t('continuity.global')}: {typeof storage.bytes === 'number' ? (storage.bytes / 1e9).toFixed(2) : '—'} GB · {t('continuity.selected')}: {contribution === undefined ? '—' : (contribution / 1e9).toFixed(2)} GB</p>
      <p className="text-muted">{t('continuity.thresholds')} · {String(storage.measuredAt)}{!storage.measurementComplete && ` · ${t('continuity.incomplete')}`}</p>
    </>}
    <p className="break-all text-muted">{t('continuity.scope')}: {sessionId}</p>
    <p>{t('continuity.rawWarning')}</p>
    <button className={button} disabled={busy || !sessionId || outcome === 'cleanup_pending'} onClick={() => void prepare()}>{t('continuity.preview')}</button>
    {preview && <div className="space-y-2">
      <p className="break-all">{t('continuity.scope')}: {preview.sessionIds.join(', ')}</p>
      <p>{t('continuity.retained')}</p>
      <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words bg-panel2 rounded-lg p-3">{typeof preview.retainedSummary === 'string' ? preview.retainedSummary : JSON.stringify(preview.retainedSummary, null, 2)}</pre>
      <p className={verified ? 'text-emerald-400' : 'text-amber-400'}>{t('continuity.validation')}: {preview.validation.status} {preview.capsuleId}</p>
      {[...(preview.validation.errors ?? []), ...(preview.warnings ?? [])].map((warning, i) => <p key={i} className="text-amber-400">{warning}</p>)}
      <label className="flex gap-2"><input type="checkbox" disabled={!verified || busy} checked={ack} onChange={e => { setAck(e.target.checked); setConfirm(false) }} />{t('continuity.ack')}</label>
    </div>}
    {!confirm ? <button className={button} disabled={!verified || !ack || busy} onClick={() => setConfirm(true)}>{t('continuity.delete')}</button> : <div role="alertdialog" aria-label={t('continuity.finalConfirm')} className="space-y-2 border border-rose-500/40 rounded-lg p-3">
      <p>{t('continuity.finalConfirm')}</p>
      <button className={button} disabled={busy} onClick={() => void remove()}>{t('continuity.confirmDelete')}</button>
      <button className={button} disabled={busy} onClick={() => setConfirm(false)}>{t('common.close')}</button>
    </div>}
    {outcome && <p role="status">{outcome === 'cleanup_pending' ? t('continuity.cleanupPending') : outcome === 'deleted' ? t('continuity.deleted') : outcome}</p>}
    {error && <p role="alert" className="text-rose-400">{error}</p>}
  </section>
}
export function ActiveStorageContinuityView() {
  const t = useT()
  const chatId = useAgentStore(s => s.activeSessionId)
  const sessionId = useHarnessChatStore(s => s.sessions[chatId]?.id) ?? chatId
  // Không có phiên đang mở thì không có phạm vi gọi `callerSessionId`: hiện lời nhắc trung tính
  // thay vì gọi route với tham số rỗng rồi báo lỗi sai.
  if (!sessionId) return <section data-testid="storage-continuity" className="rounded-xl border border-line bg-panel p-4 text-xs text-muted">{t('continuity.noSession')}</section>
  return <StorageContinuityView key={sessionId} sessionId={sessionId} />
}
