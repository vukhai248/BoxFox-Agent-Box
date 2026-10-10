/**
 * Settings → Machines → Machine & Permissions.
 *
 * Một tab cho phần host mode đã chốt ở `docs/plan/desktop-host-mode.md`:
 *
 * - **Chế độ chạy** — `docker` hay `host`, giá trị đang cấu hình và giá trị mặc định;
 * - **Quyền** — ba mức (ask/auto/trusted), phạm vi file suy từ mức; mạng độc lập,
 *   bảng năng lực đọc/ghi/lệnh/CUA, số mục sàn cứng và số lần đã va;
 * - **Luật** — từng luật kèm tầng + tệp nguồn, thu hồi được (có xác nhận);
 * - **Thẻ duyệt đang chờ** — bốn câu trả lời: một lần / phiên / luôn / từ chối;
 * - **Điều khiển desktop** — ai đang giữ quyền, epoch/generation, hook/mutex, và ba nút
 *   Trả quyền cho agent · Trả quyền về người · Dừng khẩn.
 *
 * Chế độ docker không có động cơ quyền: view chỉ gọi các route quyền khi health nói
 * `execution.policy`, và nếu vẫn gặp 409 `PERMISSIONS_UNAVAILABLE` /
 * `DESKTOP_CONTROL_UNAVAILABLE` thì hiện thông báo đọc được thay vì vỡ.
 *
 * Tự làm mới bằng GET sau mỗi thao tác — không dùng websocket.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  Cpu,
  Info,
  ListChecks,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  Siren,
  Trash2,
} from 'lucide-react'
import { ApiError } from '../../lib/agentApi'
import { useT } from '../../i18n/context'
import {
  actOnDesktopLease,
  decidePermission,
  getDesktopLease,
  getExecutionStatus,
  getPendingApprovals,
  getPermissionRules,
  getPermissionSnapshot,
  revokePermissionRule,
  updatePermissions,
} from '../../lib/permissions/http'
import type {
  CapabilityValue,
  DesktopLease,
  DesktopLeaseAction,
  ExecutionStatus,
  PendingApproval,
  PermissionDecision,
  PermissionLayer,
  PermissionMode,
  PermissionNetwork,
  PermissionRulesSnapshot,
  PermissionSnapshot,
  RuleKind,
} from '../../types/machinePermissions'

const CARD = 'rounded-xl border border-line bg-panel p-5 shadow-xs'
const FIELD = 'mt-1 w-full rounded-md border border-line bg-panel2 px-2.5 py-1.5 text-xs text-fg outline-hidden transition focus:border-brand disabled:opacity-50'
const BUTTON = 'inline-flex items-center gap-1.5 rounded-md border border-line bg-panel2 px-2.5 py-1.5 text-[11px] font-semibold text-fg transition hover:border-brand/60 hover:text-brand disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer'
const DANGER_BUTTON = 'inline-flex items-center gap-1.5 rounded-md border border-red-500/40 bg-red-500/10 px-2.5 py-1.5 text-[11px] font-semibold text-red-600 transition hover:border-red-500 hover:text-red-500 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer dark:text-red-400'

/** Three levels and independent network choices; fallback when the server omits its list. */
const MODE_FALLBACK: PermissionMode[] = ['ask', 'auto', 'trusted']
const NETWORK_FALLBACK: PermissionNetwork[] = ['restricted', 'enabled']

/** Bốn dòng của bảng năng lực — nhãn người dùng, khoá lấy từ `capabilities`. */
const CAPABILITY_ROWS: Array<{ key: keyof PermissionSnapshot['capabilities']; label: string }> = [
  { key: 'read', label: 'Đọc' },
  { key: 'write', label: 'Ghi' },
  { key: 'exec', label: 'Chạy lệnh' },
  { key: 'cua', label: 'Điều khiển desktop (CUA)' },
]

const DECISION_LABELS: Array<{ decision: PermissionDecision; label: string }> = [
  { decision: 'allow', label: 'Cho phép một lần' },
  { decision: 'allow_session', label: 'Cho phép phiên' },
  { decision: 'allow_always', label: 'Luôn cho phép' },
  { decision: 'deny', label: 'Từ chối' },
]

const DECISION_DONE: Record<PermissionDecision, string> = {
  allow: 'Đã cho phép một lần.',
  allow_session: 'Đã cho phép trong phiên này.',
  allow_always: 'Đã lưu luật "luôn cho phép" (vẫn qua kiểm tra phạm vi của động cơ).',
  deny: 'Đã từ chối.',
}

const LEASE_DONE: Record<DesktopLeaseAction, string> = {
  claim: 'Đã trả quyền điều khiển cho agent.',
  release: 'Đã trả quyền điều khiển về người.',
  stop: 'Đã dừng khẩn: epoch tăng, phím/chuột đang giữ được nhả, quyền về người.',
}

interface RuleRow {
  kind: RuleKind
  rule: string
  layer: PermissionLayer | ''
  file: string
}

/** Gộp `rules` (theo nhóm) với `sources` (cùng thứ tự) thành từng dòng để hiện bảng. */
function flattenRules(rules: PermissionRulesSnapshot | null): RuleRow[] {
  if (!rules) return []
  const out: RuleRow[] = []
  for (const kind of ['deny', 'ask', 'allow'] as const) {
    const list = rules.rules?.[kind] ?? []
    const sources = rules.sources?.[kind] ?? []
    list.forEach((rule, index) => {
      out.push({ kind, rule, layer: sources[index]?.layer ?? '', file: sources[index]?.file ?? '' })
    })
  }
  return out
}

function capabilityLabel(value: CapabilityValue | undefined): string {
  if (value === true || value === 'allow') return 'Cho phép'
  if (value === false) return 'Không'
  return 'Phải hỏi'
}

function capabilityTone(value: CapabilityValue | undefined): string {
  if (value === true || value === 'allow')
    return 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30 dark:text-emerald-300'
  if (value === false) return 'bg-red-500/10 text-red-600 border-red-500/30 dark:text-red-400'
  return 'bg-amber-500/15 text-amber-700 border-amber-500/30 dark:text-amber-300'
}

const KIND_TONE: Record<RuleKind, string> = {
  deny: 'bg-red-500/10 text-red-600 border-red-500/30 dark:text-red-400',
  ask: 'bg-amber-500/15 text-amber-700 border-amber-500/30 dark:text-amber-300',
  allow: 'bg-emerald-500/15 text-emerald-700 border-emerald-500/30 dark:text-emerald-300',
}

/** Lỗi có mã: `ApiError.message` đã mang sẵn tiền tố mã (`PERMISSION_WRITE_FAILED: …`). */
function describeError(err: unknown): string {
  if (err instanceof ApiError) return err.message
  return err instanceof Error ? err.message : String(err)
}

/** Một dòng gọn cho `args` của thẻ duyệt — văn bản thuần, cắt bớt cho vừa thẻ. */
function argsLine(args: Record<string, unknown> | null | undefined): string {
  if (!args || typeof args !== 'object') return ''
  const text = Object.entries(args)
    .map(([key, value]) => `${key}=${typeof value === 'string' ? value : JSON.stringify(value)}`)
    .join('  ')
  return text.length > 240 ? `${text.slice(0, 240)}…` : text
}

function isUnavailable(err: unknown): boolean {
  return (
    err instanceof ApiError &&
    (err.code === 'PERMISSIONS_UNAVAILABLE' || err.code === 'DESKTOP_CONTROL_UNAVAILABLE')
  )
}

export function MachinePermissionsView() {
  const t = useT()
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [execution, setExecution] = useState<ExecutionStatus | null>(null)
  const [snapshot, setSnapshot] = useState<PermissionSnapshot | null>(null)
  const [rules, setRules] = useState<PermissionRulesSnapshot | null>(null)
  const [pending, setPending] = useState<PendingApproval[]>([])
  const [lease, setLease] = useState<DesktopLease | null>(null)

  /** Đọc lại toàn bộ: health (rẻ, luôn có) → quyền/luật/thẻ duyệt → lease. */
  const load = useCallback(async () => {
    try {
      const health = await getExecutionStatus()
      const status = health.execution ?? null
      setExecution(status)
      if (!status || !status.policy) {
        // Docker (hoặc harness không trả khối `execution`): các route quyền sẽ 409 —
        // không gọi, và nói rõ vì sao phần còn lại trống.
        setSnapshot(null)
        setRules(null)
        setPending([])
        setLease(null)
        setError(status ? '' : 'Không đọc được khối `execution` từ /api/agent/health.')
        return
      }
      const [nextSnapshot, nextRules, nextPending] = await Promise.all([
        getPermissionSnapshot(),
        getPermissionRules(),
        getPendingApprovals(),
      ])
      setSnapshot(nextSnapshot)
      setRules(nextRules)
      setPending(nextPending.pending ?? [])
      setError('')
      // Lease là hàng rào của host mode trên Windows; nền khác không có ⇒ `null` là
      // trạng thái bình thường, không phải lỗi.
      try {
        setLease(await getDesktopLease())
      } catch (err) {
        if (isUnavailable(err)) setLease(null)
        else throw err
      }
    } catch (err) {
      if (isUnavailable(err)) {
        setSnapshot(null)
        setRules(null)
        setPending([])
        setLease(null)
        setError('')
      } else {
        setError(describeError(err))
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  /** Một thao tác ghi: chạy → báo kết quả → GET lại toàn bộ. */
  const runAction = useCallback(
    async (action: () => Promise<void>, done: string) => {
      setBusy(true)
      setNotice('')
      setError('')
      try {
        await action()
        setNotice(done)
        await load()
      } catch (err) {
        setError(describeError(err))
      } finally {
        setBusy(false)
      }
    },
    [load],
  )

  const changeMode = (mode: PermissionMode) =>
    void runAction(async () => {
      await updatePermissions({ mode, layer: 'user' })
    }, 'Đã lưu chế độ quyền.')

  const changeNetwork = (network: PermissionNetwork) =>
    void runAction(async () => {
      await updatePermissions({ network, layer: 'user' })
    }, 'Đã lưu mức mạng.')

  const revokeRule = (row: RuleRow) => {
    const where = row.layer ? ` ở tầng ${row.layer}` : ''
    if (!window.confirm(`Thu hồi luật "${row.rule}"${where}? Luật có hiệu lực từ lần gọi kế tiếp.`)) return
    void runAction(async () => {
      await revokePermissionRule(row.rule, row.layer || undefined)
    }, 'Đã thu hồi luật.')
  }

  const decide = (item: PendingApproval, decision: PermissionDecision) =>
    void runAction(async () => {
      await decidePermission({
        tool: item.tool,
        args: item.args ?? {},
        sessionId: item.sessionId,
        decision,
      })
    }, DECISION_DONE[decision])

  const actOnLease = (action: DesktopLeaseAction) =>
    void runAction(async () => {
      setLease(await actOnDesktopLease(action))
    }, LEASE_DONE[action])

  const ruleRows = useMemo(() => flattenRules(rules), [rules])
  const modeOptions = (snapshot?.modes ?? MODE_FALLBACK).filter(mode => MODE_FALLBACK.includes(mode))
  const networkOptions = snapshot?.networks ?? NETWORK_FALLBACK

  return (
    <div className="mx-auto max-w-5xl space-y-4 px-6 py-7 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Machines</span>
        <span>›</span>
        <span className="font-semibold text-fg">Machine &amp; Permissions</span>
      </div>

      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line pb-4">
        <div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-fg">
            <ShieldCheck className="size-5 text-brand" />
            Machine &amp; Permissions
          </h1>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-muted">
            Chế độ chạy, động cơ quyền bốn tầng và hàng rào điều khiển desktop. Quyền chi tiết và CUA
            chỉ có ở host mode — agent chạy trên chính máy này thay vì trong box Docker.
          </p>
        </div>
        <button
          type="button"
          data-testid="mp-refresh"
          onClick={() => void load()}
          disabled={busy}
          className={BUTTON}
        >
          <RefreshCw className="size-3.5" />
          Làm mới
        </button>
      </div>

      {notice && (
        <p data-testid="mp-notice" className="flex items-center gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-700 dark:text-emerald-300">
          <CheckCircle2 className="size-4 shrink-0" />
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" data-testid="mp-error" className="rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-600 dark:text-red-400">
          {error}
        </p>
      )}

      {loading ? (
        <p className="text-xs text-muted">Đang tải…</p>
      ) : execution === null ? (
        <div data-testid="mp-execution-unknown" className={CARD}>
          <p className="text-sm font-semibold text-fg">Không đọc được trạng thái chế độ chạy</p>
          <p className="mt-1 text-xs text-muted">
            Harness không trả khối `execution` trong /api/agent/health. Kiểm tra harness còn chạy không rồi bấm Làm mới.
          </p>
        </div>
      ) : (
        <>
          {/* -- Chế độ chạy ------------------------------------------------ */}
          <section data-testid="mp-execution" className={CARD}>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
              <Cpu className="size-4 text-brand" />
              Chế độ chạy
            </h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div>
                <p className="text-[10px] font-semibold tracking-wider text-muted uppercase">Đang chạy</p>
                <p data-testid="mp-execution-mode" className="mt-1 font-mono text-xs font-semibold text-fg">
                  {execution.mode}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold tracking-wider text-muted uppercase">Đang cấu hình</p>
                <p data-testid="mp-execution-configured" className="mt-1 font-mono text-xs text-fg">
                  {execution.configured}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold tracking-wider text-muted uppercase">Mặc định</p>
                <p data-testid="mp-execution-default" className="mt-1 font-mono text-xs text-fg">
                  {execution.modeDefault}
                </p>
              </div>
            </div>
            {execution.mode === 'docker' && (
              <p className="mt-3 flex items-start gap-2 rounded-lg border border-line bg-panel2 p-3 text-[11px] text-muted">
                <Info className="size-4 shrink-0 text-brand" />
                Chế độ docker không có động cơ quyền: quyền chi tiết và điều khiển desktop (CUA) chỉ có ở host mode.
              </p>
            )}
          </section>

          {!execution.policy ? (
            <div data-testid="mp-unavailable" className={CARD}>
              <p className="flex items-center gap-2 text-sm font-semibold text-fg">
                <ShieldOff className="size-4 text-muted" />
                Máy này không có động cơ quyền
              </p>
              <p className="mt-1 text-xs leading-relaxed text-muted">
                Quyền theo luật, thẻ duyệt và điều khiển desktop chỉ có ở host mode (agent chạy trực tiếp
                trên máy). Ở chế độ docker, agent nằm trong box nên không cần cấp quyền cho máy thật.
              </p>
            </div>
          ) : snapshot ? (
            <>
              {/* -- Quyền ------------------------------------------------ */}
              <section data-testid="mp-permissions" className={CARD}>
                <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
                  <ShieldCheck className="size-4 text-brand" />
                  Quyền
                </h2>
                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <label className="text-xs text-muted">
                    {t('composer.permission.sectionMode')}
                    <select
                      data-testid="mp-mode"
                      className={FIELD}
                      value={snapshot.mode}
                      disabled={busy}
                      onChange={(event) => changeMode(event.target.value as PermissionMode)}
                    >
                      {modeOptions.map((mode) => (
                        <option key={mode} value={mode}>
                          {t(`composer.permission.mode.${mode}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="text-xs text-muted">
                    {t('composer.permission.sectionNetwork')}
                    <select
                      data-testid="mp-network"
                      className={FIELD}
                      value={snapshot.network ?? 'restricted'}
                      disabled={busy}
                      onChange={(event) => changeNetwork(event.target.value as PermissionNetwork)}
                    >
                      {networkOptions.map((network) => (
                        <option key={network} value={network}>
                          {t(`composer.permission.network.${network}`)}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <p className="mt-2 text-[10px] text-muted">
                  {t(`composer.permission.hint.${snapshot.mode}`)}{' '}
                  {t(`composer.permission.scopeHint.${snapshot.scope}`)}{' '}
                  {t(snapshot.network === 'enabled' ? 'composer.permission.hint.networkEnabled' : 'composer.permission.hint.networkRestricted')}
                </p>

                <div className="mt-4 overflow-hidden rounded-lg border border-line">
                  <table className="w-full text-xs">
                    <thead className="bg-panel2 text-[10px] tracking-wider text-muted uppercase">
                      <tr>
                        <th className="px-3 py-1.5 text-left font-semibold">Năng lực</th>
                        <th className="px-3 py-1.5 text-left font-semibold">Chế độ hiện tại</th>
                      </tr>
                    </thead>
                    <tbody>
                      {CAPABILITY_ROWS.map((row) => (
                        <tr key={row.key} className="border-t border-line">
                          <td className="px-3 py-1.5 text-fg">{row.label}</td>
                          <td className="px-3 py-1.5">
                            <span
                              data-testid={`mp-capability-${row.key}`}
                              className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${capabilityTone(snapshot.capabilities?.[row.key])}`}
                            >
                              {capabilityLabel(snapshot.capabilities?.[row.key])}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                <p data-testid="mp-hardline" className="mt-3 text-[11px] leading-relaxed text-muted">
                  Sàn cứng: <span className="font-semibold text-fg">{snapshot.hardlineCount}</span> mục — đã chặn{' '}
                  <span className="font-semibold text-fg">{snapshot.hardlineHits}</span> lần. Không chế độ nào,
                  kể cả <code className="font-mono">trusted</code>, bỏ qua được.
                </p>
              </section>

              {/* -- Luật -------------------------------------------------- */}
              <section data-testid="mp-rules" className={CARD}>
                <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
                  <ListChecks className="size-4 text-brand" />
                  Luật
                  {ruleRows.length > 0 && (
                    <span className="rounded-full border border-line bg-panel2 px-2 py-0.5 text-[10px] font-semibold text-muted">
                      {ruleRows.length}
                    </span>
                  )}
                </h2>
                {ruleRows.length === 0 ? (
                  <p data-testid="mp-rules-empty" className="mt-2 text-xs text-muted">
                    Chưa có luật nào. Luật sinh ra khi bạn chọn "Luôn cho phép" trên thẻ duyệt.
                  </p>
                ) : (
                  <ul className="mt-3 divide-y divide-line rounded-lg border border-line">
                    {ruleRows.map((row, index) => (
                      <li
                        key={`${row.kind}:${row.rule}:${row.layer}:${index}`}
                        data-rule={row.rule}
                        className="flex items-start justify-between gap-3 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className={`rounded border px-1.5 py-0.5 text-[9px] font-bold uppercase ${KIND_TONE[row.kind]}`}>
                              {row.kind}
                            </span>
                            <code className="truncate font-mono text-[11px] text-fg">{row.rule}</code>
                          </div>
                          <p className="mt-0.5 truncate text-[10px] text-muted" title={row.file}>
                            tầng {row.layer || '—'}
                            {row.file ? ` · ${row.file}` : ''}
                          </p>
                        </div>
                        <button
                          type="button"
                          onClick={() => revokeRule(row)}
                          disabled={busy}
                          className={DANGER_BUTTON}
                        >
                          <Trash2 className="size-3" />
                          Thu hồi
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </section>

              {/* -- Thẻ duyệt đang chờ ----------------------------------- */}
              <section data-testid="mp-pending" className={CARD}>
                <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
                  <AlertTriangle className="size-4 text-amber-500" />
                  Thẻ duyệt đang chờ
                  {pending.length > 0 && (
                    <span className="rounded-full border border-amber-500/30 bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                      {pending.length}
                    </span>
                  )}
                </h2>
                {pending.length === 0 ? (
                  <p data-testid="mp-pending-empty" className="mt-2 text-xs text-muted">
                    Không có thẻ nào đang chờ.
                  </p>
                ) : (
                  <div className="mt-3 space-y-3">
                    {pending.map((item) => (
                      <article key={item.id} className="rounded-lg border border-line bg-panel2/50 p-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <code className="rounded border border-line bg-panel px-1.5 py-0.5 font-mono text-[11px] text-fg">
                            {item.tool}
                          </code>
                          {item.sessionId && <span className="text-[10px] text-muted">phiên {item.sessionId}</span>}
                        </div>
                        {item.reason && <p className="mt-1.5 text-xs text-fg">{item.reason}</p>}
                        {argsLine(item.args) && (
                          <pre className="mt-1.5 overflow-x-auto rounded border border-line bg-panel p-2 font-mono text-[10px] whitespace-pre-wrap text-muted">
                            {argsLine(item.args)}
                          </pre>
                        )}
                        <div className="mt-2 flex flex-wrap gap-2">
                          {DECISION_LABELS.map(({ decision, label }) => (
                            <button
                              key={decision}
                              type="button"
                              disabled={busy}
                              onClick={() => decide(item, decision)}
                              className={decision === 'deny' ? DANGER_BUTTON : BUTTON}
                            >
                              {label}
                            </button>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>

              {/* -- Điều khiển desktop ------------------------------------ */}
              <section data-testid="mp-lease" className={CARD}>
                <h2 className="flex items-center gap-2 text-sm font-semibold text-fg">
                  <Siren className="size-4 text-brand" />
                  Điều khiển desktop
                </h2>
                {lease === null ? (
                  <p data-testid="mp-lease-none" className="mt-2 text-xs text-muted">
                    Máy này không có hàng rào điều khiển desktop (chỉ host mode trên Windows mới có).
                  </p>
                ) : (
                  <>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <span
                        data-testid="mp-lease-holder"
                        className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${
                          lease.holder === 'agent'
                            ? 'border-emerald-500/30 bg-emerald-500/15 text-emerald-700 dark:text-emerald-300'
                            : 'border-amber-500/30 bg-amber-500/15 text-amber-700 dark:text-amber-300'
                        }`}
                      >
                        {lease.holder === 'agent' ? 'Agent đang điều khiển' : 'Bạn đang điều khiển'}
                      </span>
                      <span className="text-[11px] text-muted">
                        epoch {lease.epoch} · generation {lease.generation}
                      </span>
                    </div>

                    <dl className="mt-3 grid gap-x-4 gap-y-1 text-[11px] sm:grid-cols-2">
                      <div className="flex gap-2">
                        <dt className="text-muted">Hook:</dt>
                        <dd className="text-fg">{lease.hooksInstalled ? 'đã cài' : 'chưa cài'}</dd>
                      </div>
                      <div className="flex gap-2">
                        <dt className="text-muted">Mutex:</dt>
                        <dd className="text-fg">
                          {lease.mutexHeld ? `đang giữ${lease.mutexName ? ` (${lease.mutexName})` : ''}` : 'không giữ'}
                        </dd>
                      </div>
                      {lease.since && (
                        <div className="flex gap-2">
                          <dt className="text-muted">Từ:</dt>
                          <dd className="text-fg">{lease.since}</dd>
                        </div>
                      )}
                      {lease.reason && (
                        <div className="flex gap-2">
                          <dt className="text-muted">Lý do:</dt>
                          <dd className="min-w-0 text-fg">{lease.reason}</dd>
                        </div>
                      )}
                    </dl>

                    {lease.holder === 'human' && (
                      <p
                        data-testid="mp-human-warning"
                        role="alert"
                        className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[11px] leading-relaxed text-amber-800 dark:text-amber-200"
                      >
                        <AlertTriangle className="size-4 shrink-0" />
                        <span>
                          Bạn đang giữ quyền điều khiển desktop — agent không chụp được màn hình, không soi được
                          phần tử và không gửi được chuột/phím cho tới khi bạn bấm "Trả quyền cho agent".
                          {pending.length > 0 && ` Agent đang chờ ${pending.length} thẻ duyệt.`}
                        </span>
                      </p>
                    )}

                    <div className="mt-3 flex flex-wrap gap-2">
                      <button
                        type="button"
                        data-testid="mp-claim"
                        disabled={busy || lease.holder === 'agent'}
                        onClick={() => actOnLease('claim')}
                        className={BUTTON}
                      >
                        Trả quyền cho agent
                      </button>
                      <button
                        type="button"
                        data-testid="mp-release"
                        disabled={busy}
                        onClick={() => actOnLease('release')}
                        className={BUTTON}
                      >
                        Trả quyền về người
                      </button>
                      <button
                        type="button"
                        data-testid="mp-stop"
                        disabled={busy}
                        onClick={() => actOnLease('stop')}
                        className={DANGER_BUTTON}
                      >
                        <Siren className="size-3" />
                        Dừng khẩn
                      </button>
                    </div>
                  </>
                )}
              </section>
            </>
          ) : null}
        </>
      )}
    </div>
  )
}
