/**
 * Khung ⑤ — Nhãn & Giấy phép.
 *
 * Hai tab: "Ngữ cảnh" và "Giấy phép".
 * Hai chỉ số integrity_floor / confidentiality_ceiling tính lại từ toàn bộ
 * danh sách mỗi lần thêm mảnh mới — đúng mục 9.3.
 */
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n/context'
import { PanelShell, PlainText, Chip } from '../ui'
import { IntegrityBadge, ConfidentialityBadge } from '../LabelDot'
import { INTEGRITY, CONFIDENTIALITY } from '../../types/labels'
import type { Lease } from '../../types/lease'
import { PermissionCard } from '../PermissionCard'

export function LabelsLeasesPanel() {
  const t = useT()
  const tab = useUiStore((s) => s.labelsTab)
  const setTab = useUiStore((s) => s.setLabelsTab)

  return (
    <PanelShell
      title={t('labels.title')}
      toolbar={
        <div className="flex gap-1 text-[11px]">
          <Tab active={tab === 'context'} onClick={() => setTab('context')}>
            {t('labels.tabContext')}
          </Tab>
          <Tab active={tab === 'leases'} onClick={() => setTab('leases')}>
            {t('labels.tabLeases')}
          </Tab>
        </div>
      }
    >
      {tab === 'context' ? <ContextTab /> : <LeasesTab />}
    </PanelShell>
  )
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-selected={active}
      className={`rounded px-2 py-0.5 font-medium transition ${
        active ? 'bg-brand/15 text-brand' : 'text-muted hover:text-fg'
      }`}
    >
      {children}
    </button>
  )
}

function ContextTab() {
  const t = useT()
  const ctx = useAgentStore((s) => s.context)
  const openSource = useUiStore((s) => s.openSource)

  return (
    <div className="p-2">
      <div className="mb-3 grid grid-cols-2 gap-2">
        <div className="rounded-md border border-line bg-panel2 p-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            {t('labels.integrityFloor')}
          </p>
          <IntegrityBadge value={ctx.integrity_floor} />
          <p className="mt-0.5 text-[10px] text-muted">
            {ctx.integrity_floor === INTEGRITY.USER_AUTHORIZED
              ? t('labels.floorExplanation.clean')
              : t('labels.floorExplanation.dirty')}
          </p>
        </div>
        <div className="rounded-md border border-line bg-panel2 p-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
            {t('labels.confidentialityCeiling')}
          </p>
          <ConfidentialityBadge value={ctx.confidentiality_ceiling} />
          <p className="mt-0.5 text-[10px] text-muted">
            {ctx.confidentiality_ceiling === CONFIDENTIALITY.SECRET
              ? t('labels.ceilingExplanation.secret')
              : ctx.confidentiality_ceiling === CONFIDENTIALITY.INTERNAL
                ? t('labels.ceilingExplanation.internal')
                : t('labels.ceilingExplanation.public')}
          </p>
        </div>
      </div>

      {ctx.chunks.length === 0 ? (
        <p className="py-6 text-center text-[12px] text-muted">{t('labels.contextEmpty')}</p>
      ) : (
        <ul className="space-y-1">
          {ctx.chunks.map((chunk) => (
            <li key={chunk.provenance.label_id} className="rounded-md border border-line bg-bg p-2">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[12px] font-mono font-medium">
                    {chunk.provenance.source_uri || chunk.provenance.label_id}
                  </p>
                  <p className="text-[10px] text-muted">
                    {chunk.provenance.source_kind} · {chunk.provenance.tool_name}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <IntegrityBadge value={chunk.integrity} />
                  <ConfidentialityBadge value={chunk.confidentiality} />
                </div>
              </div>
              <div className="mt-2 max-h-24 overflow-y-auto rounded border border-line bg-panel2 p-1.5">
                <PlainText text={chunk.content} className="text-[11px]" />
              </div>
              {chunk.provenance.derived_from.length > 0 && (
                <div className="mt-1.5 flex flex-wrap items-center gap-1">
                  <span className="text-[10px] text-muted">{t('labels.derivedFrom')}:</span>
                  {chunk.provenance.derived_from.map((labelId) => (
                    <button
                      key={labelId}
                      type="button"
                      onClick={() => openSource(labelId)}
                      className="rounded bg-panel2 px-1.5 py-px text-[10px] font-mono text-brand hover:underline"
                    >
                      {labelId}
                    </button>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function LeasesTab() {
  const t = useT()
  const leases = useAgentStore((s) => s.leases)
  const sendCommand = useAgentStore((s) => s.sendCommand)
  const requests = useAgentStore((s) => s.requests)

  const activeLeases = leases.filter((l) => l.status === 'con_hieu_luc' && !l.revoked)
  const revokedLeases = leases.filter((l) => l.status !== 'con_hieu_luc' || l.revoked)

  return (
    <div className="p-2">
      {Object.values(requests)
        .filter((r) => r.status === 'dang_cho')
        .map((r) => (
          <div key={r.request_id} className="mb-3">
            <PermissionCard request={r} />
          </div>
        ))}

      {activeLeases.length === 0 && revokedLeases.length === 0 ? (
        <p className="py-6 text-center text-[12px] text-muted">{t('labels.leasesEmpty')}</p>
      ) : (
        <>
          {activeLeases.length > 0 && (
            <>
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
                {t('labels.leasesActive')} ({activeLeases.length})
              </p>
              {activeLeases.map((lease) => (
                <LeaseRow
                  key={lease.lease_id}
                  lease={lease}
                  onRevoke={() => sendCommand({ type: 'revoke_lease', lease_id: lease.lease_id })}
                />
              ))}
            </>
          )}
          {revokedLeases.length > 0 && (
            <>
              <p className="mb-2 mt-4 text-[11px] font-semibold uppercase tracking-wide text-muted">
                {t('labels.leasesHistory')}
              </p>
              {revokedLeases.map((lease) => (
                <LeaseRow key={lease.lease_id} lease={lease} onRevoke={undefined} />
              ))}
            </>
          )}
        </>
      )}
    </div>
  )
}

function LeaseRow({ lease, onRevoke }: { lease: Lease; onRevoke?: () => void }) {
  const t = useT()
  const expired = lease.status !== 'con_hieu_luc' || lease.revoked

  return (
    <div
      className={`mb-2 rounded-md border p-2 ${
        expired ? 'border-line bg-bg opacity-60' : 'border-amber-500/30 bg-amber-500/5'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <Chip tone="brand">{lease.tool_name}</Chip>
            {lease.max_confidentiality === 'bi_mat' && (
              <Chip tone="danger">{t('labels.leaseMaxConfidentiality.secret')}</Chip>
            )}
            {expired && <Chip tone="neutral">{t('labels.leaseExpired')}</Chip>}
          </div>
          <p className="mt-1 text-[11px] text-muted">
            {t('labels.leaseResources')}:{' '}
            <span className="font-mono">{lease.canonical_resources.join(', ') || '—'}</span>
          </p>
          <p className="text-[10px] text-muted">
            {t('labels.leaseUses', { used: lease.used_count, max: lease.max_uses ?? '∞' })} ·{' '}
            {lease.expires_at
              ? t('labels.leaseExpires', { time: lease.expires_at })
              : t('labels.leaseNoExpiry')}
          </p>
          {lease.granted_after_label_id && (
            <p className="text-[10px] text-muted">
              Neo: <span className="font-mono">{lease.granted_after_label_id}</span>
            </p>
          )}
        </div>
        {onRevoke && !expired && (
          <button
            type="button"
            onClick={onRevoke}
            className="shrink-0 rounded px-2 py-0.5 text-[11px] font-medium text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950/30"
          >
            {t('labels.leaseRevoke')}
          </button>
        )}
      </div>
    </div>
  )
}
