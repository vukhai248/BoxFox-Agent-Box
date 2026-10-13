/** Original BoxFox chat presentation; independent native-router turns. */
import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Copy, LoaderCircle, RotateCcw, Sparkles } from 'lucide-react'
import type { ProviderSnapshot } from '../../types/provider'
import { useRouterChatStore, type RouterChatTurn } from '../../store/routerChatStore'
import { useProviderStore } from '../../store/providerStore'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n/context'
import { MarkdownRenderer } from '../chat/MarkdownRenderer'
import { ProviderIcon } from '../providers/ProviderIcon'
import { MediaLightboxModal } from '../chat/MediaLightboxModal'
import { ChatInputBar } from './ChatInputBar'
// Vòng 29: danh sách option sống ở `lib/routeOptions.ts` (một hàm dùng chung cho cả picker lẫn
// composer), để `HarnessModelPicker` import được mà không tạo vòng qua RouterTestChat.
import { composerModels, findRouteOption, routerChatOptions, selectionKey } from '../../lib/routeOptions'
function tokenLabel(t: RouterChatTurn | undefined) { return !t?.usage || (t.usage.prompt_tokens == null && t.usage.completion_tokens == null) ? 'Usage chưa có dữ liệu' : `${t.usage.prompt_tokens ?? '?'} in · ${t.usage.completion_tokens ?? '?'} out` }
function RouterTurn({ turn, snapshot, busy, onOpenLightbox }: { turn: RouterChatTurn; snapshot: ProviderSnapshot | null; busy: boolean; onOpenLightbox?: (src: string) => void }) {
  const [copied, setCopied] = useState(false)
  const retry = useRouterChatStore(s => s.retry)
  const id = turn.meta?.connectionId ?? (turn.selection.kind === 'model' ? turn.selection.connectionId : null)
  const c = snapshot?.connections.find(c => c.id === id)
  return <div className="space-y-6" data-testid="router-chat-turn">
    <div className="flex flex-col items-end gap-1.5">
      <div className="max-w-[85%] rounded-2xl bg-panel2 border border-line px-4 py-3 text-xs leading-relaxed text-fg shadow-xs">
        {turn.imageUrl && (
          <div
            onClick={() => onOpenLightbox?.(turn.imageUrl!)}
            className="mb-2.5 max-w-sm cursor-pointer overflow-hidden rounded-xl border border-line/80 bg-panel hover:border-brand/60 transition shadow-xs group"
            title="Nhấp vào để phóng to ảnh"
          >
            <img src={turn.imageUrl} alt="Attached context" className="w-full object-cover max-h-56 rounded-lg group-hover:scale-[1.02] transition duration-200" />
          </div>
        )}
        <MarkdownRenderer content={turn.prompt} />
      </div>
      <div className="flex items-center gap-2 text-[11px] text-muted pr-1 select-none">
        <time dateTime={turn.startedAt}>{new Date(turn.startedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time>
        <button type="button" title="Copy message" aria-label="Copy message" onClick={() => { void navigator.clipboard.writeText(turn.prompt).then(() => setCopied(true)) }} className="hover:text-fg transition cursor-pointer">{copied ? <Check className="size-3 text-emerald-500" /> : <Copy className="size-3" />}</button>
        <span className="flex size-4 items-center justify-center rounded-full bg-panel border border-line text-[8px] font-bold text-muted">KV</span>
      </div>
    </div>
    <div className="space-y-3 pl-0.5">
      <div className="flex items-center gap-1.5 text-[11px] text-muted select-none">
        {c ? <ProviderIcon key={c.providerId} providerId={c.providerId} name={c.name} className="size-3.5" /> : <Sparkles className="size-3.5 text-brand" />}
        <span className="font-medium text-fg">{c?.name ?? 'BoxFox'}</span>{turn.status === 'streaming' && <LoaderCircle className="size-3 animate-spin" />}<span>{turn.meta?.modelId}</span>
      </div>
      {turn.response ? <MarkdownRenderer content={turn.response} /> : turn.status === 'streaming' ? <p className="text-xs text-muted">Đang chờ phản hồi…</p> : null}
      {turn.error && <p role="alert" className="text-xs leading-relaxed text-rose-500">{turn.error}</p>}
      {turn.status === 'cancelled' && <p className="text-xs text-muted">Đã dừng request.</p>}
      <div className="flex items-start justify-between gap-3 select-none">
        <details className="min-w-0 text-[11px] text-muted">
          <summary className="cursor-pointer hover:text-fg">{turn.status === 'streaming' ? 'Đang chạy' : turn.status === 'failed' ? 'Request thất bại' : turn.status === 'cancelled' ? 'Đã dừng' : 'Đã hoàn thành'}{turn.latencyMs != null ? ` · ${(turn.latencyMs / 1000).toFixed(2)}s` : ''} · {tokenLabel(turn)}</summary>
          <div className="mt-2 space-y-1 break-all font-mono"><div>Request ID: {turn.meta?.requestId ?? 'chưa nhận được'}</div><div>Target: {turn.meta ? `${turn.meta.connectionId}/${turn.meta.modelId}` : 'chưa nhận được'}</div><div>Finish: {turn.finishReason ?? 'chưa có dữ liệu'}</div><div>Chi phí: chưa có dữ liệu</div>{turn.toolCalls.length > 0 && <><div>Tool-call được trả về, không được thực thi:</div><pre className="overflow-auto rounded-lg border border-line bg-panel2 p-2">{JSON.stringify(turn.toolCalls, null, 2)}</pre></>}</div>
        </details>
        {turn.status !== 'streaming' && <button type="button" onClick={() => void retry(turn.id)} disabled={busy} aria-label="Retry request" title="Retry request" className="shrink-0 text-muted transition hover:text-fg disabled:opacity-30 cursor-pointer"><RotateCcw className="size-3" /></button>}
      </div>
    </div>
  </div>
}

export function RouterTestChat() {
  const t = useT()
  const { snapshot, loading, error, load } = useProviderStore()
  const { selection, turns, isSending, setSelection, send, stop } = useRouterChatStore()
  const openSettings = useUiStore(s => s.openSettings)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const options = useMemo(() => snapshot ? routerChatOptions(snapshot) : [], [snapshot])
  const selected = findRouteOption(options, selectionKey(selection))
  const routerModels = useMemo(() => composerModels(options), [options])
  // A failed per-model probe is shown in Provider, but does not mean that the
  // router engine or another verified model is unavailable.
  const routerUnavailable = !snapshot && Boolean(error)
  const [lightboxSrc, setLightboxSrc] = useState<string | null>(null)
  useEffect(() => { void load().catch(() => { }) }, [load])
  useEffect(() => { if (!snapshot || selected) return; const r = snapshot.defaultRoute, key = r.aliasId ? `alias:${r.aliasId}` : `model:${r.connectionId}:${r.modelId}`; const next = findRouteOption(options, key)?.selection ?? options[0]?.selection ?? null; if (selectionKey(next) !== selectionKey(selection)) setSelection(next) }, [snapshot, options, selected, selection, setSelection])
  useEffect(() => { messagesEndRef.current?.scrollIntoView?.({ behavior: 'smooth' }) }, [turns.length])
  useEffect(() => { const onKey = (e: globalThis.KeyboardEvent) => { if (e.key === 'Escape' && isSending) stop() }; window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey) }, [isSending, stop])
  const openProvider = () => openSettings('provider' as Parameters<typeof openSettings>[0])
  return <div className="flex h-full flex-col overflow-hidden bg-bg" data-testid="router-chat">
    <div className="flex shrink-0 items-center justify-between gap-2 border-b border-line bg-panel px-4 py-2 select-none">
      <div className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted" title={routerUnavailable ? error ?? undefined : 'Mỗi prompt là một request độc lập; không gửi lại lịch sử.'}><span className={`size-1.5 shrink-0 rounded-full ${routerUnavailable ? 'bg-rose-500' : !selected ? 'bg-muted/40' : 'bg-brand'}`} /><span className="truncate">{routerUnavailable ? 'Router chưa kết nối' : loading ? 'Đang kết nối…' : !selected ? 'Chưa cấu hình Provider' : 'Chat một lượt'}</span></div>
      <span className="truncate text-[11px] text-muted">{tokenLabel(turns.at(-1))}</span><button type="button" onClick={openProvider} className="shrink-0 text-[11px] text-muted hover:text-fg cursor-pointer">{routerUnavailable || !selected ? 'Mở Provider' : 'Provider'}</button>
    </div>
    <div className="min-h-0 flex-1 overflow-y-auto p-5 space-y-6 select-text">
      {turns.length === 0 ? <div className="flex h-full flex-col items-center justify-center p-8 text-center"><div className="max-w-sm space-y-2"><div className="mx-auto flex size-10 items-center justify-center rounded-xl bg-panel2 border border-line text-muted"><Sparkles className="size-5 text-brand" /></div><h3 className="text-sm font-semibold text-fg">{t('chat.empty.title')}</h3><p className="text-xs leading-relaxed text-muted">{t('chat.routerEmptyBody')}</p></div></div> : turns.map(turn => <RouterTurn key={turn.id} turn={turn} snapshot={snapshot} busy={isSending} onOpenLightbox={setLightboxSrc} />)}<div ref={messagesEndRef} />
    </div>
    <ChatInputBar router={{ models: routerModels, activeModelId: selectionKey(selection), isBusy: isSending, onModelChange: id => setSelection(findRouteOption(options, id)?.selection ?? null), onSend: (prompt, images) => { if (selected && !routerUnavailable && !loading) void send(prompt, undefined, images?.[0]) }, onStop: stop }} />
    {lightboxSrc && <MediaLightboxModal type="image" src={lightboxSrc} caption="Ảnh người dùng đính kèm" onClose={() => setLightboxSrc(null)} />}
  </div>
}
