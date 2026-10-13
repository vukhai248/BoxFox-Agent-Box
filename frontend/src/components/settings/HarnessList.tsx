import {
  Search,
  Plus,
  Copy,
  Pencil,
  Trash2,
  ChevronDown,
  Bot,
  Layers,
  Network,
  List,
  CircleAlert,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { useHarnessStore } from '../../store/harnessStore'
import { useUiStore } from '../../store/uiStore'
import { useRuntimeInfoStore, RUNTIME_INFO_UNAVAILABLE } from '../../store/runtimeInfoStore'
import type { RuntimeLimits } from '../../store/runtimeInfoStore'
import { HarnessFlowVisualizer } from './HarnessFlowVisualizer'
import { HarnessDuplicateDialog } from './HarnessDuplicateDialog'
import type { Harness } from '../../types/harness'

const ENGINE_DEFAULT = 'engine default'

/** Nhãn model đang lưu, bỏ tiền tố định tuyến cho dễ đọc. */
function modelLabel(harness: Harness): string {
  const model = harness.mainModel ?? 'default'
  if (!model || model === 'default') return 'router default model'
  if (model.startsWith('model:')) return model.slice('model:'.length)
  if (model.startsWith('alias:')) return model.slice('alias:'.length)
  return model
}

/** Số tool đang bật: chưa lưu danh sách ⇒ engine cấp toàn bộ registry. */
function toolsOn(harness: Harness, toolTotal: number): number {
  return harness.tools ? harness.tools.length : toolTotal
}

/** Harness chưa lưu gì khác mặc định của engine — đúng thứ mà store đang làm với mọi built-in. */
function changesNothing(harness: Harness): boolean {
  if (harness.mainModel && harness.mainModel !== 'default') return false
  if (harness.maxSteps !== undefined || harness.deadlineSeconds !== undefined) return false
  if (harness.tools !== undefined) return false
  return (harness.subagents ?? []).every(
    (s) => s.enabled && s.model === 'inherit' && !(s.systemPromptAppended ?? '').trim()
  )
}

/**
 * Dòng tóm tắt chỉ đọc từ dữ liệu thật: mọi con số đến từ store hoặc từ
 * `runtime-info`. Không có số thật thì ghi `unavailable` — không hiển thị lại
 * con số của lần chạy trước, cũng không trang trí cho dòng nào khác dòng nào.
 */
function rowSummary(
  harness: Harness,
  roleTotal: number | null,
  toolTotal: number | null,
  limits: RuntimeLimits | null
): string {
  const subagents = harness.subagents ?? []
  const enabled = subagents.filter((s) => s.enabled).length
  const appended = subagents.filter((s) => s.enabled && (s.systemPromptAppended ?? '').trim().length > 0).length

  const parts: string[] = [modelLabel(harness)]
  parts.push(
    roleTotal === null
      ? `${enabled} specialists on · roles ${RUNTIME_INFO_UNAVAILABLE}`
      : `${enabled} of ${roleTotal} specialists on`
  )
  parts.push(`${appended} carry an appended prompt`)
  parts.push(
    toolTotal === null
      ? `tools ${RUNTIME_INFO_UNAVAILABLE}`
      : `${toolsOn(harness, toolTotal)} of ${toolTotal} tools`
  )

  const steps = harness.maxSteps ?? limits?.maxStepsDefault ?? null
  parts.push(
    steps === null
      ? `steps ${RUNTIME_INFO_UNAVAILABLE}`
      : `${steps} steps${harness.maxSteps === undefined ? ` (${ENGINE_DEFAULT})` : ''}`
  )

  const deadline = harness.deadlineSeconds ?? limits?.deadlineDefaultSeconds ?? null
  parts.push(
    deadline === null
      ? `deadline ${RUNTIME_INFO_UNAVAILABLE}`
      : `${deadline} s${harness.deadlineSeconds === undefined ? ` (${ENGINE_DEFAULT})` : ''}`
  )

  return `${changesNothing(harness) ? 'Changes nothing yet: ' : ''}${parts.join(' · ')}`
}

export function HarnessList() {
  const [viewMode, setViewMode] = useState<'topology' | 'list'>('topology')
  const harnesses = useHarnessStore((s) => s.harnesses)
  const activeHarnessId = useHarnessStore((s) => s.activeHarnessId)
  const searchQuery = useHarnessStore((s) => s.searchQuery)
  const setActiveHarness = useHarnessStore((s) => s.setActiveHarness)
  const setSearchQuery = useHarnessStore((s) => s.setSearchQuery)
  const createHarness = useHarnessStore((s) => s.createHarness)
  const deleteHarness = useHarnessStore((s) => s.deleteHarness)

  const setEditingHarnessId = useUiStore((s) => s.setEditingHarnessId)

  const runtimeInfo = useRuntimeInfoStore((s) => s.info)
  const runtimeStatus = useRuntimeInfoStore((s) => s.status)
  const loadRuntimeInfo = useRuntimeInfoStore((s) => s.load)
  useEffect(() => {
    void loadRuntimeInfo()
  }, [loadRuntimeInfo])

  const roleTotal = runtimeInfo ? runtimeInfo.roles.length : null
  const toolTotal = runtimeInfo ? runtimeInfo.tools.length : null
  const limits = runtimeInfo ? runtimeInfo.limits : null

  const [duplicateOfId, setDuplicateOfId] = useState<string | null>(null)
  const [deleteTargetId, setDeleteTargetId] = useState<string | null>(null)
  const [refusal, setRefusal] = useState<{ id: string; title: string; hint: string } | null>(null)
  const [receipt, setReceipt] = useState<string | null>(null)
  const [freshRowId, setFreshRowId] = useState<string | null>(null)

  // Tìm kiếm vẫn chỉ khớp tên + mô tả, không khớp dòng tóm tắt.
  const filteredHarnesses = harnesses.filter(
    (h) =>
      h.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      h.description.toLowerCase().includes(searchQuery.toLowerCase())
  )

  const handleCreateNew = () => {
    const newId = createHarness()
    setEditingHarnessId(newId)
  }

  const handleEdit = (id: string) => {
    setEditingHarnessId(id)
  }

  const openDuplicateDialog = (harness: Harness) => {
    setDuplicateOfId(harness.id)
    setRefusal(null)
    setReceipt(null)
  }

  const closeDuplicateDialog = () => setDuplicateOfId(null)

  const duplicateSource = duplicateOfId ? harnesses.find((h) => h.id === duplicateOfId) : undefined

  const handleDuplicated = (newId: string, name: string, openInEditor: boolean) => {
    const source = duplicateSource
    setFreshRowId(newId)
    setReceipt(`${name} created · ${source?.isBuiltIn ? 'built-in' : 'original'} untouched`)
    closeDuplicateDialog()
    // Bản sao không tự thành harness đang dùng; chỉ mở editor khi người dùng muốn sửa.
    if (openInEditor) setEditingHarnessId(newId)
  }

  const requestDelete = (harness: Harness) => {
    if (harness.isBuiltIn) {
      // Built-in không xoá được: nói thẳng luật ra, không im lặng bỏ qua.
      setRefusal({
        id: harness.id,
        title: 'Built-in harnesses cannot be deleted',
        hint: 'They are the reference the app ships with. Duplicate this one to get a copy you can change or remove.',
      })
      setReceipt(null)
      return
    }
    setRefusal(null)
    setDeleteTargetId(harness.id)
  }

  const confirmDelete = () => {
    if (deleteTargetId) deleteHarness(deleteTargetId)
    setDeleteTargetId(null)
  }

  const deleteTarget = deleteTargetId
    ? (harnesses.find((h) => h.id === deleteTargetId) as Harness | undefined)
    : undefined

  return (
    <div className="mx-auto max-w-5xl px-8 py-7 select-text">
      {/* Breadcrumbs */}
      <div className="mb-6 flex items-center gap-1.5 text-xs text-muted">
        <span>Settings</span>
        <span className="text-muted/60">›</span>
        <span>Agents</span>
        <span className="text-muted/60">›</span>
        <span className="font-medium text-fg">Harness</span>
      </div>

      {/* Default for new sessions — thay cho hai ô chọn Team/My Default không ai đọc */}
      <div className="mb-7">
        <label htmlFor="default-harness" className="mb-1.5 block text-xs font-medium text-muted">
          Default harness for new sessions
        </label>
        <div className="relative max-w-md">
          <select
            id="default-harness"
            value={activeHarnessId}
            onChange={(e) => setActiveHarness(e.target.value)}
            className="w-full appearance-none rounded-md border border-line bg-panel2 px-3 py-2 text-xs font-medium text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
          >
            {harnesses.map((h) => (
              <option key={h.id} value={h.id}>
                {h.name}
              </option>
            ))}
            {!harnesses.some((h) => h.id === activeHarnessId) && (
              <option value={activeHarnessId}>{activeHarnessId} (not in the list)</option>
            )}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-2.5 size-3.5 text-muted" />
        </div>
        <p className="mt-1.5 max-w-xl text-[11px] leading-4 text-muted">
          A chat that is already open keeps the harness it started with. The composer still switches
          mid-session; this row is the standing default for new sessions.
        </p>
      </div>

      {/* View Mode & Actions Bar */}
      <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-1 rounded-lg border border-line bg-panel2 p-1">
          <button
            type="button"
            onClick={() => setViewMode('topology')}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition cursor-pointer ${
              viewMode === 'topology'
                ? 'bg-brand text-brandfg shadow-xs'
                : 'text-muted hover:text-fg'
            }`}
          >
            <Network className="size-3.5" />
            <span>Topology Flow</span>
          </button>
          <button
            type="button"
            onClick={() => setViewMode('list')}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition cursor-pointer ${
              viewMode === 'list'
                ? 'bg-brand text-brandfg shadow-xs'
                : 'text-muted hover:text-fg'
            }`}
          >
            <List className="size-3.5" />
            <span>List View</span>
          </button>
        </div>

        {viewMode === 'list' && (
          <div className="relative max-w-xs flex-1">
            <Search className="absolute left-3 top-2.5 size-3.5 text-muted" />
            <input
              type="text"
              placeholder="Search harnesses..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full rounded-md border border-line bg-panel px-3 py-2 pl-9 text-xs text-fg placeholder:text-muted/60 outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
            />
          </div>
        )}

        <button
          type="button"
          onClick={handleCreateNew}
          className="flex items-center gap-1.5 rounded-md bg-brand px-3.5 py-2 text-xs font-semibold text-brandfg shadow-xs transition hover:opacity-90 active:scale-98 cursor-pointer"
        >
          <Plus className="size-3.5" />
          <span>New Harness</span>
        </button>
      </div>

      {viewMode === 'topology' ? (
        <div className="space-y-4">
          <HarnessFlowVisualizer />
        </div>
      ) : (
        /* Harness Table / List */
        <div className="overflow-hidden rounded-lg border border-line bg-panel shadow-xs">
          <div className="flex items-center justify-between border-b border-line bg-panel2/40 px-4 py-2.5">
            <span className="text-[11px] font-medium uppercase tracking-wider text-muted">Name</span>
            <span className="text-[11px] text-muted">
              {runtimeStatus === 'failed'
                ? `Engine numbers ${RUNTIME_INFO_UNAVAILABLE}`
                : runtimeStatus === 'ready'
                  ? `${toolTotal} tools · ${roleTotal} roles`
                  : 'Reading engine numbers...'}
            </span>
          </div>

          <div className="divide-y divide-line">
            {filteredHarnesses.length === 0 ? (
              <div className="p-8 text-center text-xs text-muted">
                <p>No harnesses found matching your search.</p>
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="mt-3 rounded-md border border-line px-3 py-1.5 text-xs font-semibold hover:bg-panel2 cursor-pointer"
                >
                  Clear search
                </button>
              </div>
            ) : (
              <>
                <p className="border-b border-line bg-panel2/20 px-4 py-2 text-[11px] leading-4 text-muted">
                  Every built-in harness is stored with the same settings right now, so their summary
                  lines read the same. The line prints what is actually stored, not a copy-paste bug.
                </p>
                {filteredHarnesses.map((harness) => {
                  const row = harness as Harness
                  const origin = row.duplicatedFrom
                  const isActive = harness.id === activeHarnessId
                  return (
                    <div key={harness.id} className="px-4 py-3 transition hover:bg-panel2/40">
                      <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <button
                              type="button"
                              onClick={() => handleEdit(harness.id)}
                              className="text-xs font-medium text-fg hover:underline cursor-pointer"
                              title={harness.isBuiltIn ? 'Open the read-only screen' : 'Edit harness'}
                            >
                              {harness.name}
                            </button>
                            <div className="flex items-center gap-1 text-muted">
                              <Bot className="size-3" />
                              <Layers className="size-3" />
                            </div>
                            {harness.isBuiltIn && (
                              <span className="rounded-full bg-panel2 px-1.5 py-0.5 text-[11px] font-mono text-muted border border-line">
                                Built-in
                              </span>
                            )}
                            {isActive && (
                              <span className="rounded-full border border-emerald-500/40 px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                                In use
                              </span>
                            )}
                            {freshRowId === harness.id && (
                              <span className="rounded-full bg-brand px-1.5 py-0.5 text-[11px] font-semibold text-brandfg">
                                NEW
                              </span>
                            )}
                          </div>
                          <p className="mt-1 text-[11px] leading-4 text-muted">
                            {rowSummary(row, roleTotal, toolTotal, limits)}
                          </p>
                          {origin && (
                            <p className="mt-0.5 text-[11px] text-muted">
                              Duplicate of {origin.name} (
                              {harnesses.find((h) => h.id === origin.id)?.isBuiltIn ? 'built-in' : 'copy'})
                            </p>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-1.5">
                          {harness.isBuiltIn ? (
                            <button
                              type="button"
                              onClick={() => openDuplicateDialog(row)}
                              className="rounded-md border border-line px-2.5 py-1.5 text-xs font-semibold hover:border-brand hover:text-brand transition cursor-pointer"
                            >
                              Duplicate and edit
                            </button>
                          ) : (
                            <>
                              <button
                                type="button"
                                onClick={() => handleEdit(harness.id)}
                                className="rounded p-1.5 text-muted hover:bg-panel2 hover:text-fg transition cursor-pointer"
                                title="Edit harness"
                                aria-label={`Edit ${harness.name}`}
                              >
                                <Pencil className="size-3.5" />
                              </button>
                              <button
                                type="button"
                                onClick={() => openDuplicateDialog(row)}
                                className="rounded p-1.5 text-muted hover:bg-panel2 hover:text-fg transition cursor-pointer"
                                title="Duplicate harness"
                                aria-label={`Duplicate ${harness.name}`}
                              >
                                <Copy className="size-3.5" />
                              </button>
                            </>
                          )}
                          <button
                            type="button"
                            onClick={() => requestDelete(row)}
                            className="rounded p-1.5 text-muted hover:bg-red-500/15 hover:text-red-400 transition cursor-pointer"
                            title="Delete harness"
                            aria-label={`Delete ${harness.name}`}
                          >
                            <Trash2 className="size-3.5" />
                          </button>
                        </div>
                      </div>

                      {refusal?.id === harness.id && (
                        <div
                          role="alert"
                          className="mt-3 rounded-lg border border-red-500/30 bg-red-500/10 p-3 text-xs"
                        >
                          <div className="flex gap-2">
                            <CircleAlert className="mt-0.5 size-4 shrink-0 text-red-600 dark:text-red-400" />
                            <div>
                              <p className="font-semibold">{refusal.title}</p>
                              <p className="mt-1 text-muted">{refusal.hint}</p>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </>
            )}
          </div>
        </div>
      )}

      {receipt && (
        <p role="status" className="mt-4 text-xs text-emerald-600 dark:text-emerald-400">
          {receipt}
        </p>
      )}

      {duplicateSource && (
        <HarnessDuplicateDialog
          source={duplicateSource}
          harnesses={harnesses}
          onCancel={closeDuplicateDialog}
          onDone={handleDuplicated}
        />
      )}

      {/* Hộp thoại xoá bản sao */}
      {deleteTarget && (
        <div className="fixed inset-0 z-60 flex items-center justify-center bg-black/60 p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-harness-title"
            className="w-full max-w-md rounded-xl border border-line bg-bg p-5 shadow-2xl"
          >
            <h2 id="delete-harness-title" className="text-base font-bold">
              Delete harness?
            </h2>
            <p className="mt-2 text-xs leading-5 text-muted">
              {deleteTarget.name} will be removed from this list. There is no undo.
              {deleteTarget.duplicatedFrom ? ' The built-in it came from is not affected.' : ''}
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteTargetId(null)}
                className="rounded-md border border-line px-3 py-2 text-xs font-semibold hover:bg-panel2 cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDelete}
                className="rounded-md bg-red-600 px-3 py-2 text-xs font-semibold text-white hover:bg-red-500 cursor-pointer"
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
