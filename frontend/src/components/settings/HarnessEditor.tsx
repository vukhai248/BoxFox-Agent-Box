import { useState } from 'react'
import {
  AlertTriangle,
  Plus,
  Trash2,
  ChevronDown,
  ChevronUp,
} from 'lucide-react'
import { useHarnessStore, AVAILABLE_MODELS } from '../../store/harnessStore'
import { useUiStore } from '../../store/uiStore'
import type { Harness, SubagentConfig } from '../../types/harness'
import { CustomCheckbox } from './CustomCheckbox'

interface HarnessEditorProps {
  harnessId: string
}

export function HarnessEditor({ harnessId }: HarnessEditorProps) {
  const getHarnessById = useHarnessStore((s) => s.getHarnessById)
  const saveHarness = useHarnessStore((s) => s.saveHarness)
  const setEditingHarnessId = useUiStore((s) => s.setEditingHarnessId)

  const initialHarness = getHarnessById(harnessId)

  const [form, setForm] = useState<Harness>(() => {
    if (initialHarness) {
      return JSON.parse(JSON.stringify(initialHarness))
    }
    return {
      id: harnessId,
      name: 'New Custom Harness',
      description: '',
      isBuiltIn: false,
      mainModel: 'DeepSeek V4 Pro (Global) 1M High',
      subagents: [],
    }
  })

  const [expandedSubagents, setExpandedSubagents] = useState<Record<string, boolean>>({
    explore: true,
    code: true,
  })

  const handleSave = () => {
    saveHarness(form)
    setEditingHarnessId(null)
  }

  const handleCancel = () => {
    setEditingHarnessId(null)
  }

  const handleModelChange = (modelName: string) => {
    const selectedModel = AVAILABLE_MODELS.find((m) => m.name === modelName)
    let warning = ''
    if (selectedModel && !selectedModel.supportsImages) {
      warning = `Some models in this harness do not support images (${selectedModel.name}). Sessions will continue; image inputs are replaced with placeholder text so the run does not fail.`
    }
    setForm((f) => ({
      ...f,
      mainModel: modelName,
      modelWarning: warning,
    }))
  }

  const handleAddSubagent = () => {
    const newSubagentId = `custom-sub-${Date.now()}`
    const newSubagent: SubagentConfig = {
      id: newSubagentId,
      name: 'Custom Subagent',
      isBuiltIn: false,
      enabled: true,
      model: form.mainModel,
      systemPromptAppended: '',
    }
    setForm((f) => ({
      ...f,
      subagents: [...f.subagents, newSubagent],
    }))
    setExpandedSubagents((prev) => ({ ...prev, [newSubagentId]: true }))
  }

  const handleUpdateSubagent = (subId: string, updates: Partial<SubagentConfig>) => {
    setForm((f) => ({
      ...f,
      subagents: f.subagents.map((s) => (s.id === subId ? { ...s, ...updates } : s)),
    }))
  }

  const handleDeleteSubagent = (subId: string) => {
    setForm((f) => ({
      ...f,
      subagents: f.subagents.filter((s) => s.id !== subId),
    }))
  }

  const toggleExpand = (subId: string) => {
    setExpandedSubagents((prev) => ({
      ...prev,
      [subId]: !prev[subId],
    }))
  }

  return (
    <div className="mx-auto max-w-4xl px-8 py-7 select-text">
      {/* Breadcrumbs */}
      <div className="mb-4 flex items-center gap-1.5 text-xs text-muted">
        <span>Settings</span>
        <span className="text-muted/60">›</span>
        <span>Agents</span>
        <span className="text-muted/60">›</span>
        <button
          type="button"
          onClick={handleCancel}
          className="text-muted hover:text-fg hover:underline cursor-pointer"
        >
          Harness
        </button>
        <span className="text-muted/60">›</span>
        <span className="font-medium text-fg">Editor</span>
      </div>

      {/* Header with Title and Action Buttons */}
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-fg">Edit Harness</h1>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={handleCancel}
            className="rounded-md border border-line bg-panel px-3.5 py-1.5 text-xs font-medium text-fg transition hover:bg-panel2 cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            className="rounded-md bg-brand px-4 py-1.5 text-xs font-semibold text-brandfg shadow-xs transition hover:opacity-90 active:scale-98 cursor-pointer"
          >
            Save changes
          </button>
        </div>
      </div>

      {/* Form Fields */}
      <div className="space-y-5">
        {/* Name */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted">Name</label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            className="w-full rounded-md border border-line bg-panel px-3 py-2 text-xs text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
            placeholder="Harness name"
          />
        </div>

        {/* Description */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted">Description</label>
          <textarea
            rows={3}
            value={form.description}
            onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
            className="w-full rounded-md border border-line bg-panel px-3 py-2 text-xs leading-relaxed text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
            placeholder="Describe what this harness configuration does..."
          />
        </div>

        {/* Model Selection */}
        <div>
          <label className="mb-1.5 block text-xs font-medium text-muted">Model</label>
          <div className="relative">
            <select
              value={form.mainModel}
              onChange={(e) => handleModelChange(e.target.value)}
              className="w-full appearance-none rounded-md border border-line bg-panel px-3 py-2 text-xs font-medium text-fg outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
            >
              {AVAILABLE_MODELS.map((m) => (
                <option key={m.id} value={m.name}>
                  {m.name} ({m.provider})
                </option>
              ))}
            </select>
            <ChevronDown className="pointer-events-none absolute right-3 top-2.5 size-3.5 text-muted" />
          </div>

          {/* Model Warning Banner */}
          {form.modelWarning && (
            <div className="mt-3 flex items-start gap-2.5 rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
              <AlertTriangle className="size-4 shrink-0 text-amber-400 mt-0.5" />
              <div>
                <p className="font-semibold text-amber-200">Some models in this harness do not support images</p>
                <p className="mt-0.5 text-amber-300/80 leading-relaxed text-[11px]">{form.modelWarning}</p>
              </div>
            </div>
          )}
        </div>

        {/* Subagents Section */}
        <div className="pt-3">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold text-fg">Subagents</h2>
            <button
              type="button"
              onClick={handleAddSubagent}
              className="flex items-center gap-1.5 rounded-md border border-line bg-panel px-2.5 py-1 text-xs font-medium text-fg transition hover:bg-panel2 cursor-pointer"
            >
              <Plus className="size-3" />
              <span>Add Custom Subagent</span>
            </button>
          </div>

          {/* Subagents List */}
          <div className="space-y-2.5">
            {form.subagents.map((subagent) => {
              const isExpanded = expandedSubagents[subagent.id] ?? true
              return (
                <div
                  key={subagent.id}
                  className="overflow-hidden rounded-lg border border-line bg-panel transition"
                >
                  {/* Card Top Row */}
                  <div className="flex items-center justify-between border-b border-line bg-panel2/40 px-3.5 py-2.5">
                    <div className="flex items-center gap-2.5">
                      <CustomCheckbox
                        checked={subagent.enabled}
                        onChange={() =>
                          handleUpdateSubagent(subagent.id, { enabled: !subagent.enabled })
                        }
                      />
                      {subagent.isBuiltIn ? (
                        <span className="text-xs font-medium text-fg">{subagent.name}</span>
                      ) : (
                        <input
                          type="text"
                          value={subagent.name}
                          onChange={(e) =>
                            handleUpdateSubagent(subagent.id, { name: e.target.value })
                          }
                          className="rounded border border-line bg-panel px-2 py-0.5 text-xs font-medium text-fg outline-hidden focus:border-brand"
                        />
                      )}
                      {subagent.isBuiltIn && (
                        <span className="rounded bg-panel2 px-1.5 py-0.5 text-[10px] font-mono text-muted border border-line">
                          Built-in
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-2.5">
                      {/* Subagent Model Selector */}
                      <select
                        value={subagent.model}
                        onChange={(e) =>
                          handleUpdateSubagent(subagent.id, { model: e.target.value })
                        }
                        className="appearance-none rounded border border-line bg-panel px-2 py-1 text-[11px] text-fg outline-hidden transition hover:border-muted focus:border-brand"
                      >
                        {AVAILABLE_MODELS.map((m) => (
                          <option key={m.id} value={m.name}>
                            {m.name}
                          </option>
                        ))}
                      </select>

                      {!subagent.isBuiltIn && (
                        <button
                          type="button"
                          onClick={() => handleDeleteSubagent(subagent.id)}
                          className="rounded p-1 text-muted hover:bg-red-500/15 hover:text-red-400 transition cursor-pointer"
                          title="Delete subagent"
                        >
                          <Trash2 className="size-3" />
                        </button>
                      )}

                      <button
                        type="button"
                        onClick={() => toggleExpand(subagent.id)}
                        className="rounded p-1 text-muted hover:bg-panel2 hover:text-fg transition cursor-pointer"
                      >
                        {isExpanded ? (
                          <ChevronUp className="size-3.5" />
                        ) : (
                          <ChevronDown className="size-3.5" />
                        )}
                      </button>
                    </div>
                  </div>

                  {/* System Prompt (appended) Body */}
                  {isExpanded && (
                    <div className="p-3.5">
                      <div className="mb-1 flex items-center justify-between">
                        <label className="text-xs font-medium text-fg">
                          System Prompt (appended)
                        </label>
                      </div>
                      <p className="mb-2 text-[11px] text-muted">
                        Appended to the built-in agent's system prompt. Base system instructions remain managed under the hood.
                      </p>
                      <textarea
                        rows={3}
                        value={subagent.systemPromptAppended}
                        onChange={(e) =>
                          handleUpdateSubagent(subagent.id, {
                            systemPromptAppended: e.target.value,
                          })
                        }
                        placeholder="Enter specialized custom instructions for this subagent..."
                        className="w-full rounded-md border border-line bg-panel2/50 p-2.5 font-mono text-xs leading-relaxed text-fg placeholder:text-muted/50 outline-hidden transition focus:border-brand focus:ring-1 focus:ring-brand"
                      />
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
