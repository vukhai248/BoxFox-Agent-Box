import {
  Search,
  Plus,
  Eye,
  Copy,
  Pencil,
  Trash2,
  ChevronDown,
  Layers,
  Bot,
} from 'lucide-react'
import { useHarnessStore } from '../../store/harnessStore'
import { useUiStore } from '../../store/uiStore'

export function HarnessList() {
  const harnesses = useHarnessStore((s) => s.harnesses)
  const teamDefaultId = useHarnessStore((s) => s.teamDefaultId)
  const myDefaultId = useHarnessStore((s) => s.myDefaultId)
  const searchQuery = useHarnessStore((s) => s.searchQuery)
  const setTeamDefault = useHarnessStore((s) => s.setTeamDefault)
  const setMyDefault = useHarnessStore((s) => s.setMyDefault)
  const setSearchQuery = useHarnessStore((s) => s.setSearchQuery)
  const createHarness = useHarnessStore((s) => s.createHarness)
  const cloneHarness = useHarnessStore((s) => s.cloneHarness)
  const deleteHarness = useHarnessStore((s) => s.deleteHarness)

  const setEditingHarnessId = useUiStore((s) => s.setEditingHarnessId)

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

  const handleClone = (id: string) => {
    const clonedId = cloneHarness(id)
    setEditingHarnessId(clonedId)
  }

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

      {/* Default Selectors Row */}
      <div className="mb-7 grid grid-cols-1 gap-5 sm:grid-cols-2">
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted">Team Default</label>
          <div className="relative">
            <select
              value={teamDefaultId}
              onChange={(e) => setTeamDefault(e.target.value)}
              className="w-full appearance-none rounded-md border border-line bg-panel2 px-3 py-2 text-xs font-medium text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
            >
              {harnesses.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-2.5 size-3.5 text-muted" />
          </div>
        </div>

        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted">My Default</label>
          <div className="relative">
            <select
              value={myDefaultId}
              onChange={(e) => setMyDefault(e.target.value)}
              className="w-full appearance-none rounded-md border border-line bg-panel2 px-3 py-2 text-xs font-medium text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
            >
              {harnesses.map((h) => (
                <option key={h.id} value={h.id}>
                  {h.name}
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-2.5 size-3.5 text-muted" />
          </div>
        </div>
      </div>

      {/* Search & Actions Bar */}
      <div className="mb-5 flex items-center justify-between gap-4">
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

        <button
          type="button"
          onClick={handleCreateNew}
          className="flex items-center gap-1.5 rounded-md bg-brand px-3.5 py-2 text-xs font-semibold text-brandfg shadow-xs transition hover:opacity-90 active:scale-98 cursor-pointer"
        >
          <Plus className="size-3.5" />
          <span>New Harness</span>
        </button>
      </div>

      {/* Harness Table / List */}
      <div className="overflow-hidden rounded-lg border border-line bg-panel shadow-xs">
        <div className="border-b border-line bg-panel2/40 px-4 py-2.5 text-[11px] font-medium uppercase tracking-wider text-muted">
          Name
        </div>

        <div className="divide-y divide-line">
          {filteredHarnesses.length === 0 ? (
            <div className="p-8 text-center text-xs text-muted">
              No harnesses found matching your search.
            </div>
          ) : (
            filteredHarnesses.map((harness) => (
              <div
                key={harness.id}
                className="flex items-center justify-between px-4 py-3 transition hover:bg-panel2/40"
              >
                <div className="flex items-center gap-3">
                  <span className="text-xs font-medium text-fg">{harness.name}</span>
                  <div className="flex items-center gap-1 text-muted">
                    <Bot className="size-3" />
                    <Layers className="size-3" />
                  </div>
                  {harness.isBuiltIn && (
                    <span className="rounded bg-panel2 px-1.5 py-0.5 text-[10px] font-mono text-muted border border-line">
                      Built-in
                    </span>
                  )}
                </div>

                <div className="flex items-center gap-1 text-muted">
                  {harness.isBuiltIn ? (
                    <>
                      <button
                        type="button"
                        onClick={() => handleEdit(harness.id)}
                        className="rounded p-1.5 hover:bg-panel2 hover:text-fg transition cursor-pointer"
                        title="View details"
                      >
                        <Eye className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleClone(harness.id)}
                        className="rounded p-1.5 hover:bg-panel2 hover:text-fg transition cursor-pointer"
                        title="Duplicate harness"
                      >
                        <Copy className="size-3.5" />
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => handleClone(harness.id)}
                        className="rounded p-1.5 hover:bg-panel2 hover:text-fg transition cursor-pointer"
                        title="Duplicate harness"
                      >
                        <Copy className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleEdit(harness.id)}
                        className="rounded p-1.5 hover:bg-panel2 hover:text-fg transition cursor-pointer"
                        title="Edit harness"
                      >
                        <Pencil className="size-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => deleteHarness(harness.id)}
                        className="rounded p-1.5 hover:bg-red-500/15 hover:text-red-400 transition cursor-pointer"
                        title="Delete harness"
                      >
                        <Trash2 className="size-3.5" />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
