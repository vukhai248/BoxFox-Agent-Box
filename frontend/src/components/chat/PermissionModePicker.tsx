/**
 * Nút chọn quyền ở thanh chat (host mode) — tương đương `/approvals` của Codex.
 *
 * Vì sao đặt ở thanh chat: người dùng phải đổi được mức cho phép NGAY TRƯỚC khi gõ câu lệnh, chứ
 * không phải mở Settings → Machines giữa lượt. Nút chỉ hiện ở `host` vì chế độ docker không có động
 * cơ quyền (mọi route quyền trả 409 `PERMISSIONS_UNAVAILABLE`).
 *
 * Nguồn dữ liệu là `GET/PUT /api/agent/permissions` (`lib/permissions/http.ts`) — cùng nguồn với
 * tab Settings → Machines, không dựng bản sao thứ hai. Bốn chế độ đến từ máy chủ (`snapshot.modes`),
 * nhãn đến từ i18n, nên thêm chế độ ở harness là giao diện tự có.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, ChevronDown, Loader2, Shield } from 'lucide-react'
import { useActiveMachine } from '../../hooks/useActiveMachine'
import { useAgentStore } from '../../store/agentStore'
import { getPermissionSnapshot, updatePermissions } from '../../lib/permissions/http'
import { useT } from '../../i18n/context'
import type { PermissionMode, PermissionScope } from '../../types/machinePermissions'

/** Thứ tự hiển thị cố định: từ chặt nhất tới rộng nhất, không theo thứ tự máy chủ trả về. */
const MODE_ORDER: PermissionMode[] = ['plan', 'ask', 'auto', 'trusted']
const SCOPE_ORDER: PermissionScope[] = ['workspace', 'machine']

/** Chế độ `trusted` cho phép sửa và chạy không hỏi ⇒ tô đỏ để không ai bật nhầm. */
function modeTone(mode: PermissionMode): string {
  if (mode === 'trusted') return 'text-rose-400'
  if (mode === 'auto') return 'text-amber-400'
  if (mode === 'ask') return 'text-emerald-400'
  return 'text-sky-400'
}

export function PermissionModePicker({ compact = false }: { compact?: boolean }) {
  const t = useT()
  const machine = useActiveMachine()
  const sessionId = useAgentStore((s) => s.activeSessionId)
  const [mode, setMode] = useState<PermissionMode | null>(null)
  const [scope, setScope] = useState<PermissionScope | null>(null)
  const [modes, setModes] = useState<PermissionMode[]>(MODE_ORDER)
  const [scopes, setScopes] = useState<PermissionScope[]>(SCOPE_ORDER)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const boxRef = useRef<HTMLDivElement | null>(null)

  const hostMode = machine.mode === 'host'

  // Nạp lại khi đổi phiên hoặc đổi máy: quyền là chuyện của MÁY, nhưng người dùng đổi phiên thì
  // vẫn phải thấy giá trị hiện hành thay vì bản đọc của phiên trước.
  useEffect(() => {
    if (!hostMode) return
    let alive = true
    getPermissionSnapshot()
      .then((snapshot) => {
        if (!alive) return
        setMode(snapshot.mode)
        setScope(snapshot.scope)
        if (snapshot.modes?.length) setModes(snapshot.modes as PermissionMode[])
        if (snapshot.scopes?.length) setScopes(snapshot.scopes as PermissionScope[])
        setError('')
      })
      .catch((exc: unknown) => {
        if (!alive) return
        setMode(null)
        setError(exc instanceof Error ? exc.message : String(exc))
      })
    return () => {
      alive = false
    }
  }, [hostMode, sessionId, machine.projectId])

  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const patch = useCallback(
    async (next: { mode?: PermissionMode; scope?: PermissionScope }) => {
      const previous = { mode, scope }
      if (next.mode) setMode(next.mode)
      if (next.scope) setScope(next.scope)
      setBusy(true)
      try {
        const snapshot = await updatePermissions({ ...next, layer: 'user' })
        setMode(snapshot.mode)
        setScope(snapshot.scope)
        setError('')
        setOpen(false)
      } catch (exc) {
        // Không nuốt lỗi: trả về giá trị cũ và giữ thông báo cho người dùng đọc.
        setMode(previous.mode)
        setScope(previous.scope)
        setError(exc instanceof Error ? exc.message : String(exc))
      } finally {
        setBusy(false)
      }
    },
    [mode, scope],
  )

  if (!hostMode) return null

  const label = mode ? t(`composer.permission.mode.${mode}`) : t('composer.permission.unknown')
  const hint = mode ? t(`composer.permission.hint.${mode}`) : error
  const scopeLabel = scope ? t(`composer.permission.scope.${scope}`) : ''
  // Phạm vi nằm trong `title` của nút: người dùng thấy ngay mức cho phép đang áp cho đâu mà không
  // phải mở menu (mức `trusted` + phạm vi `machine` là tổ hợp nguy hiểm nhất).
  const title = scopeLabel ? `${hint} · ${scopeLabel}` : hint

  return (
    <div className="relative" ref={boxRef}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label={t('composer.permission.label')}
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="composer-permission"
        data-permission-mode={mode ?? 'unknown'}
        data-permission-scope={scope ?? 'unknown'}
        title={title}
        className="flex items-center gap-1 rounded-lg border border-transparent px-2 py-1 text-[11px] font-medium text-muted transition hover:bg-panel2 hover:text-fg cursor-pointer"
      >
        {busy ? (
          <Loader2 className="size-3 animate-spin" />
        ) : error ? (
          <AlertTriangle className="size-3 text-amber-400" />
        ) : (
          <Shield className={`size-3 ${mode ? modeTone(mode) : 'text-muted'}`} />
        )}
        {!compact && <span>{label}</span>}
        <ChevronDown className="size-3 opacity-60" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label={t('composer.permission.label')}
          className="absolute bottom-full right-0 z-50 mb-1.5 w-72 rounded-xl border border-line bg-panel p-1.5 shadow-lg"
        >
          <p className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            {t('composer.permission.sectionMode')}
          </p>
          {modes.map((item) => (
            <button
              key={item}
              type="button"
              role="menuitemradio"
              aria-checked={item === mode}
              onClick={() => void patch({ mode: item })}
              disabled={busy}
              className="flex w-full items-start gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-fg transition hover:bg-panel2 disabled:opacity-50 cursor-pointer"
            >
              <Check className={`mt-0.5 size-3 shrink-0 ${item === mode ? 'opacity-100' : 'opacity-0'}`} />
              <span className="min-w-0">
                <span className={`block font-medium ${modeTone(item)}`}>
                  {t(`composer.permission.mode.${item}`)}
                </span>
                <span className="mt-0.5 block text-[10px] leading-4 text-muted">
                  {t(`composer.permission.hint.${item}`)}
                </span>
              </span>
            </button>
          ))}

          <p className="mt-1 border-t border-line px-2 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            {t('composer.permission.sectionScope')}
          </p>
          {scopes.map((item) => (
            <button
              key={item}
              type="button"
              role="menuitemradio"
              aria-checked={item === scope}
              onClick={() => void patch({ scope: item })}
              disabled={busy}
              className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-xs text-fg transition hover:bg-panel2 disabled:opacity-50 cursor-pointer"
            >
              <Check className={`size-3 shrink-0 ${item === scope ? 'opacity-100' : 'opacity-0'}`} />
              <span>{t(`composer.permission.scope.${item}`)}</span>
            </button>
          ))}

          {scopeLabel && (
            <p className="px-2 pt-1 pb-0.5 text-[10px] text-muted" data-testid="composer-permission-scope">
              {scopeLabel}
            </p>
          )}
          {error && (
            <p role="alert" className="px-2 pt-1 pb-0.5 text-[10px] text-amber-400">
              {error}
            </p>
          )}
        </div>
      )}
    </div>
  )
}
