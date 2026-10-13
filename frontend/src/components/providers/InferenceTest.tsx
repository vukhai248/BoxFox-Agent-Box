import { useEffect, useRef, useState } from 'react'
import { Activity, Square } from 'lucide-react'
import { api } from '../../lib/providerApi'
import { routable } from '../../lib/routeOptions'
import { streamRouterGenerate, type RouterTokenUsage } from '../../lib/routerStream'
import { useProviderStore } from '../../store/providerStore'
import type { ProviderConnection, RouterRequestMeta } from '../../types/provider'

interface Completion {
  boxfox?: RouterRequestMeta
  choices?: Array<{ message?: { content?: string | null; tool_calls?: unknown[] }; finish_reason?: string | null }>
  usage?: RouterTokenUsage | null
}

export function InferenceTest({ connection }: { connection: ProviderConnection }) {
  const models = connection.models.filter(model => model.enabled)
  const [modelId, setModelId] = useState(models[0]?.id ?? '')
  const [stream, setStream] = useState(false)
  const [prompt, setPrompt] = useState('Reply exactly: BOXFOX_OK')
  const [status, setStatus] = useState('')
  const [content, setContent] = useState('')
  const [meta, setMeta] = useState<RouterRequestMeta | null>(null)
  const [usage, setUsage] = useState<RouterTokenUsage | null>(null)
  const [latency, setLatency] = useState<number | null>(null)
  const active = useRef<AbortController | null>(null)
  const running = status === 'running'
  const selected = models.some(model => model.id === modelId) ? modelId : models[0]?.id ?? ''
  // Panel này gửi thẳng `connectionId` + `modelId` tới `/v1/router/generate`, và router khẳng định
  // lại đích bằng `validTarget`, nên nút Test phải theo ĐÚNG luật đó (vòng 29): connection dò hỏng
  // mà model là thứ người dùng gõ tay thì vẫn là đích hợp lệ — đứng khoá nút lại, vì đây chính là
  // chỗ để kiểm chứng model gõ tay; còn dò hỏng với model `live` thì router sẽ từ chối.
  const ready = routable(connection, connection.models.find(model => model.id === selected))
  useEffect(() => () => { active.current?.abort(); active.current = null }, [])

  const test = async () => {
    if (active.current || !ready || !selected || !prompt.trim()) return
    const controller = new AbortController()
    active.current = controller
    const started = performance.now()
    setStatus('running'); setContent(''); setMeta(null); setUsage(null); setLatency(null)
    let meaningful = false
    let finished = false
    let requestMeta: RouterRequestMeta | null = null
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(100000)])
    try {
      const body = { connectionId: connection.id, modelId: selected, messages: [{ role: 'user' as const, content: prompt.trim() }], max_tokens: 64 }
      if (stream) {
        await streamRouterGenerate({ ...body, stream: true }, { signal, onEvent: event => {
          if (active.current !== controller) return
          if (event.type === 'content') { meaningful ||= Boolean(event.content); setContent(value => value + event.content) }
          if (event.type === 'tools') { meaningful = true; setContent(value => value + '\n[Tool-call returned; not executed]') }
          if (event.type === 'finish') finished = true
          if (event.type === 'meta') { requestMeta = event.meta; setMeta(event.meta) }
          if (event.type === 'usage') setUsage(event.usage)
        } })
      } else {
        const result = await api<Completion>('/v1/router/generate', { method: 'POST', body: { ...body, stream: false }, signal })
        const choice = result.choices?.[0]
        meaningful = Boolean(choice?.message?.content || choice?.message?.tool_calls?.length)
        finished = Boolean(choice?.finish_reason)
        requestMeta = result.boxfox ?? null
        if (active.current !== controller) return
        setContent(choice?.message?.content ?? (choice?.message?.tool_calls?.length ? '[Tool-call returned; not executed]' : ''))
        setMeta(requestMeta); setUsage(result.usage ?? null)
      }
      if (!meaningful || !finished || !requestMeta?.requestId) throw new Error('Incomplete inference response; not counted as passed.')
      if (active.current === controller) setStatus('passed')
    } catch (error) {
      if (active.current === controller) setStatus(controller.signal.aborted ? 'cancelled' : `failed: ${error instanceof Error ? error.message : 'Request failed.'}`)
    } finally {
      if (active.current === controller) {
        active.current = null; setLatency(Math.round(performance.now() - started))
        await useProviderStore.getState().load().catch(() => undefined)
      }
    }
  }

  return <section aria-label={`Inference test for ${connection.name}`} className="mt-4 border-t border-line pt-4">
    <p className="text-xs font-semibold">Inference verification</p>
    <div className="mt-2 flex flex-col gap-2 sm:flex-row">
      <select aria-label={`Inference model for ${connection.name}`} disabled={running} value={selected} onChange={event => setModelId(event.target.value)} className="min-w-0 flex-1 rounded-md border border-line bg-panel2 px-3 py-2 text-xs text-fg">
        {!models.length && <option value="">Discover and enable a model first</option>}
        {models.map(model => <option key={model.id} value={model.id}>{model.name}</option>)}
      </select>
      <label className="flex items-center gap-2 text-xs"><input type="checkbox" disabled={running} checked={stream} onChange={event => setStream(event.target.checked)} />SSE stream</label>
      {running ? <button type="button" onClick={() => active.current?.abort()} className="flex items-center justify-center gap-2 rounded-md border border-line px-3 py-2 text-xs"><Square className="size-3.5" />Stop</button> : <button type="button" disabled={!ready || !selected || !prompt.trim()} onClick={() => { void test() }} className="flex items-center justify-center gap-2 rounded-md border border-line px-3 py-2 text-xs disabled:opacity-50"><Activity className="size-3.5" />Test inference</button>}
    </div>
    <input aria-label={`Test prompt for ${connection.name}`} disabled={running} value={prompt} onChange={event => setPrompt(event.target.value)} className="mt-2 w-full rounded-md border border-line bg-panel2 px-3 py-2 text-xs" />
    {status && <div role="status" className="mt-3 break-words rounded-lg border border-line bg-panel2 p-3 text-xs">
      <p className={status.startsWith('failed') ? 'text-red-600 dark:text-red-300' : 'text-muted'}>{status}{latency !== null && ` · ${latency} ms`}</p>
      {content && <p className="mt-2 whitespace-pre-wrap">{content}</p>}
      {meta && <p className="mt-2 font-mono text-[11px] text-muted">Target: {meta.connectionId}/{meta.modelId}<br />Request: {meta.requestId}</p>}
      <p className="mt-1 text-muted">Tokens: {usage?.prompt_tokens ?? 'No data'} / {usage?.completion_tokens ?? 'No data'} · Cost: No data</p>
    </div>}
  </section>
}
