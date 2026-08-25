/**
 * Khung phụ — Sổ audit.
 *
 * CHỈ ĐỌC, CHỈ THÊM. Mỗi dòng là một `AuditRecord`. Có bộ lọc theo
 * `AuditQueryId`: du_lieu_da_roi_may / vi_sao_duoc_phep / bat_nguon_tu_du_lieu_nao / all.
 */
import { useMemo, useState } from 'react'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { useT } from '../../i18n/context'
import { PanelShell } from '../ui'

const QUERY_OPTIONS: { value: string; labelKey: string }[] = [
  { value: 'all', labelKey: 'audit.queries.all' },
  { value: 'du_lieu_da_roi_may', labelKey: 'audit.queries.du_lieu_da_roi_may' },
  { value: 'vi_sao_duoc_phep', labelKey: 'audit.queries.vi_sao_duoc_phep' },
  { value: 'bat_nguon_tu_du_lieu_nao', labelKey: 'audit.queries.bat_nguon_tu_du_lieu_nao' },
]

export function AuditPanel() {
  const t = useT()
  const records = useAgentStore((s) => s.audit)
  const query = useUiStore((s) => s.auditQuery)
  const setQuery = useUiStore((s) => s.setAuditQuery)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const filtered = useMemo(() => records, [records])

  return (
    <PanelShell
      title={t('audit.title')}
      note={t('audit.intro')}
      toolbar={
        <select
          value={query}
          onChange={(e) => setQuery(e.target.value as typeof query)}
          className="rounded border border-line bg-panel px-1.5 py-0.5 text-[11px] text-fg"
        >
          {QUERY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey as 'audit.queries.all')}
            </option>
          ))}
        </select>
      }
    >
      {filtered.length === 0 ? (
        <div className="flex h-full items-center justify-center p-6 text-center">
          <p className="text-[12px] text-muted">{t('audit.empty')}</p>
        </div>
      ) : (
        <div className="p-1">
          {filtered.map((record) => (
            <div key={record.record_id} className="mb-1 rounded border border-line bg-bg p-2">
              <button
                type="button"
                onClick={() => setExpandedId(expandedId === record.record_id ? null : record.record_id)}
                className="flex w-full items-start justify-between gap-2 text-left"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[11px] font-mono font-medium">{record.tool_name}</span>
                    <span className="text-[10px] text-muted">epoch #{record.task_epoch}</span>
                  </div>
                  <p className="truncate text-[10px] text-muted">{record.decision}</p>
                </div>
                <span className="shrink-0 text-[10px] tabular-nums text-muted">
                  {record.created_at.slice(11, 19)}
                </span>
              </button>
              {expandedId === record.record_id && (
                <div className="mt-2 space-y-1 text-[11px]">
                  <p><span className="text-muted">Tham số:</span> {record.params_masked}</p>
                  {record.destination && (
                    <p><span className="text-muted">Đích ra ngoài:</span> {record.destination}</p>
                  )}
                  {record.label_ids.length > 0 && (
                    <p>
                      <span className="text-muted">label_id đã ảnh hưởng:</span>{' '}
                      {record.label_ids.join(', ')}
                    </p>
                  )}
                  <p><span className="text-muted">lease_id:</span> {record.lease_id ?? '—'}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </PanelShell>
  )
}
