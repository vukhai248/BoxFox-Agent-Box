/**
 * Panel "Màn hình máy" (host mode) — chọn đích CUA cho phiên, xem ảnh của đích,
 * đi theo agent khi agent tự chuyển cửa sổ, và soi phần tử tại một điểm.
 *
 * Ba thứ panel này CHỊU TRÁCH NHIỆM (và ba thứ nó không làm):
 *
 *   1. **Đích là của phiên, không phải của panel.** Nguồn sự thật là
 *      `GET /machines/target`; panel poll 2 s một nhịp khi tab đang hiện (không
 *      websocket — harness không có kênh đẩy nào), và khi `revision` đổi thì coi
 *      như đích vừa bị người khác đổi: xoá ảnh cũ, đóng ngăn kéo, chụp lại.
 *   2. **Không có response cũ nào được vẽ.** Mọi lượt chụp/thanh tra đi kèm một
 *      `AbortController` riêng và một `epochRef`; đổi đích là tăng epoch, nên
 *      một `fetch` đang bay có về muộn cũng bị bỏ (không nháy ảnh của cửa sổ cũ
 *      lên trên cửa sổ mới).
 *   3. **Chỉ xem.** Panel không có nút gửi chuột/phím; mọi hành động thật của
 *      agent vẫn phải qua thẻ duyệt của harness. Nút "Chọn phần tử" chỉ gọi
 *      route thanh tra (đọc), và bị KHOÁ khi người dùng đang giữ quyền — route
 *      đó đòi agent lease, nên khoá nút + mời "Trả quyền cho agent" là hành vi
 *      đúng hợp đồng, không phải một lỗi của panel.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, AppWindow, Crosshair, Eye, Monitor, Pause, Play, RefreshCw, X } from 'lucide-react'
import { useT, type TKey, type TVars } from '../../i18n/context'
import { Chip, IconButton, PanelShell } from '../ui'
import { useAgentStore } from '../../store/agentStore'
import { useComposerStore } from '../../store/composerStore'
import { useUiStore } from '../../store/uiStore'
import { useElementInspector } from '../../hooks/useElementInspector'
import { ElementInspectorDrawer } from '../sandbox/ElementInspectorDrawer'
import { HostInspectRepository } from '../../lib/inspect/host'
import { ApiError } from '../../lib/agentApi'
import {
  CUA_POLL_MS,
  captureMachine,
  captureWindow,
  clearTarget,
  getTarget,
  isCuaTargetErrorCode,
  listWindows,
  setTarget,
  targetKey,
  type CuaTargetErrorCode,
} from '../../lib/desktop/target'
import { actOnDesktopLease, getExecutionStatus } from '../../lib/permissions/http'
import { CuaTargetPicker, type WindowsState } from './host/CuaTargetPicker'
import { CuaTargetOverlay } from './host/CuaTargetOverlay'
import type { CuaTarget, CuaTargetState, HostSnapshot, HostWindowEntry } from '../../types/desktopTarget'
import type { DesktopLease, PermissionScope } from '../../types/machinePermissions'

/** Mã lỗi của nhóm route target/ảnh chụp → khoá i18n (bảng §7.5 của kế hoạch). */
const TARGET_ERROR_KEY: Partial<Record<CuaTargetErrorCode, TKey>> = {
  TARGET_KIND_INVALID: 'machineScreen.errorTargetKindInvalid',
  TARGET_CONSENT_REQUIRED: 'machineScreen.errorTargetConsent',
  CUA_MACHINE_SCOPE_REQUIRED: 'machineScreen.errorTargetScope',
  SESSION_NOT_FOUND: 'machineScreen.errorSessionNotFound',
  HOST_SESSION_REQUIRED: 'machineScreen.errorHostSessionRequired',
  TARGET_UNKNOWN: 'machineScreen.errorTargetUnknown',
  TARGET_CHANGED: 'machineScreen.errorTargetChanged',
  TARGET_REVISION_CONFLICT: 'machineScreen.errorRevisionConflict',
  CUA_UNAVAILABLE: 'machineScreen.errorCuaUnavailable',
  HOST_SCREEN_UNAVAILABLE: 'machineScreen.errorScreenUnavailable',
  SCREEN_CONSENT_REQUIRED: 'machineScreen.errorScreenConsent',
  SCREEN_TARGET_CHANGED: 'machineScreen.errorScreenTargetChanged',
  SCREEN_SNAPSHOT_STALE: 'machineScreen.errorScreenSnapshotStale',
  SCREEN_OCCLUDED: 'machineScreen.errorScreenOccluded',
}

/** `HH:MM` theo giờ máy người dùng — đủ để nói "ảnh này chụp lúc nào". */
function formatClock(ms: number): string {
  const date = new Date(ms)
  return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

/** Câu lỗi đọc được: ưu tiên mã máy đã biết, lùi về `message` của harness. */
function describeError(error: unknown, t: (key: TKey, vars?: TVars) => string): string {
  if (error instanceof ApiError) {
    if (isCuaTargetErrorCode(error.code)) {
      const key = TARGET_ERROR_KEY[error.code]
      if (key) return t(key)
    }
    return error.message || t('machineScreen.errorGeneric')
  }
  return error instanceof Error ? error.message : String(error)
}

/** Chi tiết nền tảng cho câu "window list: không hỗ trợ" — lấy từ chính câu lỗi của máy. */
function platformDetail(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error)
  const message = raw.replace(/^[A-Z_]+:\s*/, '').trim()
  return message.length > 80 ? `${message.slice(0, 80)}…` : message
}

export function HostMachineScreen() {
  const t = useT()
  const sessionId = useAgentStore((s) => s.activeSessionId)
  const addPendingElement = useComposerStore((s) => s.addPendingElement)
  const hostInspect = useMemo(() => new HostInspectRepository(), [])
  const inspector = useElementInspector(hostInspect)

  const [windows, setWindows] = useState<HostWindowEntry[]>([])
  const [windowsState, setWindowsState] = useState<WindowsState>('idle')
  const [windowsError, setWindowsError] = useState<string | null>(null)
  const [targetState, setTargetState] = useState<CuaTargetState | null>(null)
  const [snapshot, setSnapshot] = useState<HostSnapshot | null>(null)
  const [snapshotAt, setSnapshotAt] = useState<number | null>(null)
  const [snapshotPaused, setSnapshotPaused] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [lease, setLease] = useState<DesktopLease | null>(null)
  const [scope, setScope] = useState<PermissionScope | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showPicker, setShowPicker] = useState(true)

  // `epochRef` là hàng rào duy nhất chống "response cũ vẽ đè": tăng nó lên là
  // mọi lượt đang bay trở thành vô hiệu, kể cả khi `fetch` không huỷ được.
  const epochRef = useRef(0)
  const targetKeyRef = useRef('')
  const revisionRef = useRef(-1)
  const capturingRef = useRef(false)
  const captureAbortRef = useRef<AbortController | null>(null)
  // Đích đã được backend KIỂM LẠI là mất (`effective: null`) — hwnd chết hoặc bị
  // tái dùng cho tiến trình khác. Cờ này chặn mọi lượt chụp lặp vô hạn.
  const deadRef = useRef(false)
  const pausedRef = useRef(false)
  pausedRef.current = snapshotPaused
  // Bản sao mới nhất của `t`/`inspector`: nhịp poll không được phụ thuộc vào
  // danh tính của chúng (hook trả object mới mỗi lần render ⇒ effect tự chạy lại).
  const tRef = useRef(t)
  tRef.current = t
  const inspectorRef = useRef(inspector)
  inspectorRef.current = inspector

  useEffect(
    () => () => {
      // Rời panel: cắt mọi thứ đang bay để không setState lên component đã gỡ.
      epochRef.current += 1
      capturingRef.current = false
      captureAbortRef.current?.abort()
    },
    [],
  )

  /** Chụp lại ảnh của một đích — mọi lời gọi đều mang epoch của lượt nó thuộc về. */
  const captureFor = useCallback(async (target: CuaTarget) => {
    // Đích đã mất: backend đã xác nhận cửa sổ không còn; chụp lại chỉ ra lỗi.
    if (deadRef.current) return
    const epoch = epochRef.current
    captureAbortRef.current?.abort()
    const controller = new AbortController()
    captureAbortRef.current = controller
    capturingRef.current = true
    setCapturing(true)
    try {
      const shot =
        target.kind === 'machine'
          ? await captureMachine(controller.signal)
          : await captureWindow({ windowId: target.windowId, pid: target.pid }, controller.signal)
      if (epoch !== epochRef.current) return
      // Cùng `hash` ⇒ không set state: tránh re-render và nháy ảnh mỗi 2 giây.
      setSnapshot((previous) => (previous && previous.hash === shot.hash ? previous : shot))
      setSnapshotAt(Date.now())
    } catch (cause) {
      if (epoch !== epochRef.current) return
      setError(describeError(cause, tRef.current))
    } finally {
      if (epoch === epochRef.current) {
        capturingRef.current = false
        setCapturing(false)
      }
    }
  }, [])

  /** Áp một hình dạng đích mới từ backend: cắt mọi thứ của đích cũ rồi chụp lại. */
  const applyTargetState = useCallback(
    (next: CuaTargetState, { recapture = true }: { recapture?: boolean } = {}) => {
      epochRef.current += 1
      capturingRef.current = false
      captureAbortRef.current?.abort()
      deadRef.current = false
      targetKeyRef.current = targetKey(next.target)
      revisionRef.current = next.revision
      setTargetState(next)
      setSnapshot(null)
      setSnapshotAt(null)
      inspectorRef.current.disarm()
      inspectorRef.current.closeDrawer()
      setError(null)
      if (recapture && next.target) void captureFor(next.target)
    },
    [captureFor],
  )

  const refreshWindows = useCallback(async () => {
    setWindowsState('loading')
    try {
      const entries = await listWindows()
      setWindows(entries)
      setWindowsState(entries.length === 0 ? 'empty' : 'ready')
      setWindowsError(null)
    } catch (cause) {
      // Nền tảng không có danh sách cửa sổ KHÔNG phải lỗi: đây là đường thật của
      // Linux (và là trạng thái duy nhất hiện được trên máy kiểm).
      const code = cause instanceof ApiError ? cause.code : undefined
      if (code === 'HOST_SCREEN_UNAVAILABLE' || code === 'UNSUPPORTED_IN_HOST_MODE') {
        setWindows([])
        setWindowsState('unsupported')
        setWindowsError(platformDetail(cause))
      } else {
        setWindows([])
        setWindowsState('error')
        setWindowsError(describeError(cause, tRef.current))
      }
    }
  }, [])

  const refreshLease = useCallback(async () => {
    try {
      const health = await getExecutionStatus()
      const execution = health.execution
      setScope((execution?.scope as PermissionScope | null) ?? null)
      setLease(execution?.lease ?? null)
    } catch {
      // `/health` hỏng thì giữ trạng thái cũ — panel vẫn dùng được, chỉ thiếu
      // thông tin lease; không được biến lỗi phụ này thành lỗi chính.
    }
  }, [])

  const tick = useCallback(async () => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
    try {
      const next = await getTarget(sessionId)
      const key = targetKey(next.target)
      if (key !== targetKeyRef.current || next.revision !== revisionRef.current) {
        applyTargetState(next)
        return
      }
      // Backend kiểm lại đích mỗi lần đọc: `effective: null` nghĩa là hwnd đã chết
      // hoặc đã bị tiến trình khác dùng lại. Ảnh đang có là ảnh của cửa sổ CŨ (có
      // thể của ứng dụng khác), nên phải xoá và dừng chụp — không lặp vô hạn.
      const dead = next.target?.kind === 'window' && next.effective === null
      if (dead) {
        if (!deadRef.current) {
          deadRef.current = true
          epochRef.current += 1
          capturingRef.current = false
          captureAbortRef.current?.abort()
          setSnapshot(null)
          setSnapshotAt(null)
          inspectorRef.current.disarm()
          inspectorRef.current.closeDrawer()
          setError(tRef.current('machineScreen.errorTargetUnknown'))
        }
        setTargetState(next)
        return
      }
      deadRef.current = false
      setTargetState(next)
      if (next.target && !pausedRef.current && !capturingRef.current) void captureFor(next.target)
    } catch (cause) {
      setError(describeError(cause, tRef.current))
    }
  }, [sessionId, applyTargetState, captureFor])

  useEffect(() => {
    void tick()
    const interval = setInterval(() => void tick(), CUA_POLL_MS)
    // Về lại tab ⇒ đọc ngay, đừng chờ hết nhịp: người dùng vừa nhìn lại màn hình
    // thì ảnh phải là ảnh hiện tại.
    const onVisible = () => {
      if (document.visibilityState === 'visible') void tick()
    }
    const onFocus = () => void tick()
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onFocus)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onFocus)
    }
  }, [tick])

  useEffect(() => {
    void refreshWindows()
    void refreshLease()
  }, [refreshWindows, refreshLease])

  // Đang giữ quyền là trạng thái MẶC ĐỊNH của người dùng (H7): nút chọn phần tử
  // phải khoá ngay, và phải có đường trả quyền ngay tại chỗ.
  const humanHoldsLease = lease?.holder === 'human'
  const target = targetState?.target ?? null
  const activeWindow = targetState?.activeWindow ?? null
  const working = lease?.holder === 'agent'
  // Backend đã tính sẵn "cả máy có được phép không" cho phiên này; `/health` chỉ
  // là đường dự phòng khi hình dạng đích chưa về tới.
  const machineAllowed =
    targetState?.machineAllowed ?? (scope === null ? null : scope === 'machine')

  useEffect(() => {
    if (!target && inspector.armed) inspector.disarm()
  }, [target, inspector.armed, inspector.disarm])

  const clock = formatClock(snapshotAt ?? Date.now())
  const selectDisabled = !snapshot || humanHoldsLease || busy
  const selectHint = humanHoldsLease ? t('machineScreen.selectElementLeaseLocked') : t('machineScreen.selectElementHint')

  async function pickTarget(request: Parameters<typeof setTarget>[0]) {
    setBusy(true)
    try {
      applyTargetState(await setTarget(request))
    } catch (cause) {
      setError(describeError(cause, t))
    } finally {
      setBusy(false)
    }
  }

  async function revokeTarget() {
    setBusy(true)
    try {
      const next = await clearTarget(sessionId)
      applyTargetState(next, { recapture: false })
    } catch (cause) {
      setError(describeError(cause, t))
    } finally {
      setBusy(false)
    }
  }

  async function claimLease() {
    setBusy(true)
    try {
      setLease(await actOnDesktopLease('claim'))
      setError(null)
    } catch (cause) {
      setError(describeError(cause, t))
    } finally {
      setBusy(false)
    }
  }

  function toggleSelect() {
    if (inspector.armed) {
      inspector.disarm()
      return
    }
    if (selectDisabled) return
    inspector.toggleArmed()
  }

  function handleAddToChat() {
    const state = inspector.drawer
    if (!state || state.status !== 'success') return
    const id = typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : `element-${Date.now()}`
    addPendingElement({ id, point: state.point, result: state.result })
    inspector.closeDrawer()
  }

  // Khung sáng phần tử vừa soi: `dom` và `uia` đều trả hộp trong toạ độ framebuffer,
  // nhánh `desktop` không có toạ độ nào để khoanh vùng nên không vẽ gì.
  const highlighted = inspector.drawer?.status === 'success' ? inspector.drawer.result : null
  const highlightBox =
    highlighted?.type === 'dom'
      ? highlighted.screenBox
      : highlighted?.type === 'uia'
        ? highlighted.bounds.screenBox
        : null
  const highlightLabel = highlighted
    ? t('screen.inspector.highlightLabel', {
        tag: highlighted.type === 'dom' ? highlighted.tagName : highlighted.type === 'uia' ? highlighted.name || highlighted.controlType : '',
        width: Math.round(highlightBox?.width ?? 0),
        height: Math.round(highlightBox?.height ?? 0),
      })
    : null

  const note = inspector.armed
    ? t('machineScreen.noteSelectArmed')
    : target && humanHoldsLease
      ? t('machineScreen.noteHumanLease')
      : target
        ? t('machineScreen.noteTarget')
        : windowsState === 'unsupported'
          ? t('machineScreen.noteNoWindowList')
          : t('machineScreen.noteNoTarget')

  const toolbar = (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {target ? (
        <Chip tone="brand" title={t('machineScreen.statusWorking', { time: clock })}>
          {target.kind === 'machine' ? t('machineScreen.targetChipMachine') : t('machineScreen.targetChipWindow')}
        </Chip>
      ) : (
        <Chip tone="warn" title={t('machineScreen.statusIdle', { time: clock })}>
          {t('machineScreen.noTarget')}
        </Chip>
      )}
      {lease && (
        <Chip tone={humanHoldsLease ? 'warn' : 'neutral'} title={humanHoldsLease ? t('machineScreen.leaseClaim') : undefined}>
          {humanHoldsLease ? t('machineScreen.leaseHuman') : t('machineScreen.leaseAgent')}
        </Chip>
      )}
      <Chip title={t('machineScreen.viewOnlyHint')}>{t('machineScreen.viewOnly')}</Chip>
      <IconButton
        label={t('machineScreen.snapshotRefresh')}
        testId="ms-snapshot-refresh"
        disabled={!target || capturing}
        onClick={() => {
          if (target) void captureFor(target)
        }}
      >
        <RefreshCw className={`size-3.5 ${capturing ? 'animate-spin' : ''}`} />
      </IconButton>
      {target && (
        <IconButton
          label={snapshotPaused ? t('machineScreen.snapshotResume') : t('machineScreen.snapshotPause')}
          testId="ms-snapshot-pause"
          active={snapshotPaused}
          onClick={() => setSnapshotPaused((value) => !value)}
        >
          {snapshotPaused ? <Play className="size-3.5" /> : <Pause className="size-3.5" />}
        </IconButton>
      )}
      <button
        type="button"
        aria-pressed={inspector.armed}
        disabled={!inspector.armed && selectDisabled}
        onClick={toggleSelect}
        data-testid="ms-select-element"
        title={selectHint}
        className="inline-flex items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg disabled:cursor-not-allowed disabled:opacity-50 aria-pressed:border-brand/50 aria-pressed:bg-brand/15 aria-pressed:text-brand"
      >
        <Crosshair className="size-3.5" aria-hidden="true" />
        {inspector.armed ? t('machineScreen.selectElementCancel') : t('machineScreen.selectElement')}
      </button>
      {humanHoldsLease && (
        <button
          type="button"
          onClick={() => void claimLease()}
          disabled={busy}
          data-testid="ms-lease-claim"
          className="rounded-md bg-fg px-2 py-1 text-[11px] font-semibold text-bg disabled:opacity-50"
        >
          {t('machineScreen.leaseClaim')}
        </button>
      )}
      {target && (
        <IconButton label={t('machineScreen.revoke')} testId="ms-revoke" disabled={busy} onClick={() => void revokeTarget()}>
          <X className="size-3.5" />
        </IconButton>
      )}
    </div>
  )

  // Backend có thể trả `target` mảnh (chỉ `windowId`/`pid`) — nhất là ngay sau
  // `PUT`. Danh sách cửa sổ đang có trong tay là nguồn bổ sung cho TÊN và TIẾN
  // TRÌNH, để chip nhận dạng luôn nói được "cửa sổ nào" chứ không chỉ một số.
  const targetWindowEntry =
    target && target.kind === 'window'
      ? windows.find((entry) => String(entry.windowId) === String(target.windowId)) ?? null
      : null
  const identityTitle = target
    ? target.kind === 'machine'
      ? t('machineScreen.pickWholeMachine')
      : target.title || targetWindowEntry?.title || t('machineScreen.pickWindow')
    : ''
  const identityMeta =
    target && target.kind === 'window'
      ? t('machineScreen.targetIdentityMeta', {
          process: target.processName || target.windowClass || targetWindowEntry?.processName || targetWindowEntry?.windowClass || '—',
          windowId: String(target.windowId),
        })
      : activeWindow
        ? t('machineScreen.targetIdentityMeta', {
            process: activeWindow.processName || '—',
            windowId: String(activeWindow.windowId),
          })
        : ''

  return (
    <PanelShell title={t('machineScreen.title')} note={note} toolbar={toolbar}>
      <div className="flex h-full min-h-0 flex-col">
        <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-auto p-3 md:flex-row">
          {showPicker && (
            <div className="w-full shrink-0 md:w-64">
              <CuaTargetPicker
                windows={windows}
                windowsState={windowsState}
                windowsError={windowsError}
                platform={windowsState === 'unsupported' ? windowsError : null}
                scope={scope}
                machineAllowed={machineAllowed}
                target={target}
                activeWindowId={activeWindow?.windowId ?? null}
                busy={busy}
                onRefreshWindows={() => void refreshWindows()}
                onPickMachine={() => void pickTarget({ sessionId, kind: 'machine', consent: true, expectedRevision: revisionRef.current >= 0 ? revisionRef.current : undefined })}
                onPickWindow={(entry) =>
                  void pickTarget({
                    sessionId,
                    kind: 'window',
                    windowId: entry.windowId,
                    pid: entry.pid,
                    consent: true,
                    expectedRevision: revisionRef.current >= 0 ? revisionRef.current : undefined,
                  })
                }
                onOpenPermissions={() => useUiStore.getState().openSettings('configuration')}
              />
            </div>
          )}

          <div className="relative flex min-h-0 min-w-0 flex-1 flex-col gap-2">
            {error && (
              <p
                role="alert"
                className="break-words rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-[11px] text-amber-800 dark:text-amber-200"
              >
                {error}
              </p>
            )}

            {target && (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <span
                  data-testid="ms-target-identity"
                  title={`${t('machineScreen.targetIdentityTitle', { title: identityTitle })} · ${identityMeta}`}
                  className="inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border border-line bg-panel2 px-2 py-0.5"
                >
                  {target.kind === 'machine' ? (
                    <Monitor className="size-3.5 shrink-0 text-cua" aria-hidden="true" />
                  ) : (
                    <AppWindow className="size-3.5 shrink-0 text-cua" aria-hidden="true" />
                  )}
                  <span className="truncate text-[12px] font-semibold">{identityTitle}</span>
                  {identityMeta && (
                    <>
                      <span className="text-muted" aria-hidden="true">
                        ·
                      </span>
                      <span className="truncate font-mono text-[11px] text-muted">{identityMeta}</span>
                    </>
                  )}
                </span>
                {targetState?.requestedBy === 'agent' && (
                  <span className="text-[11px] text-cua">{t('machineScreen.targetByAgent')}</span>
                )}
                {targetState?.requestedBy === 'user' && (
                  <span className="text-[11px] text-muted">{t('machineScreen.targetByUser')}</span>
                )}
                <button
                  type="button"
                  aria-pressed={showPicker}
                  onClick={() => setShowPicker((value) => !value)}
                  data-testid="ms-change-target"
                  className="rounded-md border border-line px-2 py-0.5 text-[11px] font-semibold text-muted hover:text-fg"
                >
                  {t('machineScreen.changeTarget')}
                </button>
              </div>
            )}

            {target && (
              <div
                role="status"
                className={`flex flex-wrap items-center gap-2 rounded-md px-2 py-1 text-[11px] ${
                  humanHoldsLease
                    ? 'bg-amber-500/10 text-amber-800 dark:text-amber-200'
                    : 'bg-cua/10 text-cua'
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`size-1.5 shrink-0 rounded-full ${humanHoldsLease ? 'bg-amber-400' : 'animate-pulse bg-cua'}`}
                />
                <span className="font-semibold">{working ? t('machineScreen.targetWorking') : t('machineScreen.humanLeaseChip')}</span>
                <span className="text-muted">
                  {humanHoldsLease
                    ? t('machineScreen.bannerHumanLease')
                    : target.kind === 'machine'
                      ? t('machineScreen.bannerWorkingMachine')
                      : t('machineScreen.bannerWorkingWindow')}
                </span>
              </div>
            )}

            <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-auto">
              {snapshot && target ? (
                <>
                  <CuaTargetOverlay
                    snapshot={snapshot}
                    target={target}
                    activeWindow={activeWindow}
                    armed={inspector.armed}
                    working={working}
                    highlightBox={highlightBox}
                    highlightLabel={highlightLabel}
                    onPick={inspector.handlePick}
                    onEscape={inspector.disarm}
                  >
                    {inspector.drawer && (
                      <ElementInspectorDrawer
                        state={inspector.drawer}
                        onClose={inspector.closeDrawer}
                        onRetry={inspector.retry}
                        onAddToChat={handleAddToChat}
                      />
                    )}
                  </CuaTargetOverlay>
                  <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted">
                    <span>{t('machineScreen.snapshotMeta', { width: snapshot.width, height: snapshot.height })}</span>
                    <span className="inline-flex items-center gap-1">
                      <AlertTriangle className="size-3.5" aria-hidden="true" />
                      {t('machineScreen.snapshotUntrusted')}
                    </span>
                  </div>
                </>
              ) : (
                <div className="flex min-h-40 flex-1 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line p-4 text-center">
                  <Eye className="size-4 text-muted" aria-hidden="true" />
                  <p className="text-[12px] font-semibold">{t('machineScreen.noLiveImage')}</p>
                  <p className="max-w-md text-[11px] text-muted">{t('machineScreen.noLiveImageHint')}</p>
                  {target && (
                    <button
                      type="button"
                      onClick={() => void captureFor(target)}
                      className="rounded-md border border-line px-2 py-1 text-[11px] font-semibold text-muted hover:text-fg"
                    >
                      {t('machineScreen.snapshotRefresh')}
                    </button>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-x-2 gap-y-1 border-t border-line bg-panel2/60 px-3 py-1 text-[11px] text-muted">
          <span className="inline-flex items-center gap-1">
            <Monitor className="size-3" aria-hidden="true" />
            {t('machineScreen.factRealWindow')}
          </span>
          <span aria-hidden="true">·</span>
          <span>{t('machineScreen.factApproval')}</span>
          <span aria-hidden="true">·</span>
          <span>{t('machineScreen.factUntrusted')}</span>
        </div>
      </div>
    </PanelShell>
  )
}
