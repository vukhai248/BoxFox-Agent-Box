import { useState, useEffect } from 'react'
import {
  Sparkles,
  Search,
  CheckCircle2,
  Sliders,
  Code2,
  Bug,
  TestTube2,
  FileSearch,
  HelpCircle,
  ShieldCheck,
  Power,
} from 'lucide-react'
import { useSkillsStore } from '../../store/skillsStore'
import { CommandsView } from './CommandsView'
import { agentApi } from '../../lib/agentApi'

const SKILL_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  'systematic-debugging': Bug,
  'test-driven-development': TestTube2,
  'simplify-code': Code2,
  'codebase-inspection': FileSearch,
  'requesting-code-review': ShieldCheck,
  'subagent-driven-development': Sliders,
  'ast-grep': FileSearch,
  'grill-me': HelpCircle,
}

export function SkillsView() {
  const [tab, setTab] = useState<'skills' | 'commands'>('skills')
  const [readiness, setReadiness] = useState('')
  const load = useSkillsStore((s) => s.load)
  const loadInstructions = useSkillsStore((s) => s.loadInstructions)
  const error = useSkillsStore((s) => s.error)
  useEffect(() => { void load().catch(() => {}) }, [load])
  const {
    skills,
    searchQuery,
    selectedCategory,
    setSearchQuery,
    setSelectedCategory,
    toggleSkill,
    enableAll,
    disableAll,
  } = useSkillsStore()

  const [activeSkillId, setActiveSkillId] = useState<string | null>(skills[0]?.id ?? null)

  const filteredSkills = skills.filter((skill) => {
    const matchesSearch =
      skill.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      skill.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      skill.tags.some((t) => t.toLowerCase().includes(searchQuery.toLowerCase()))
    const matchesCat = selectedCategory === 'all' || skill.category === selectedCategory
    return matchesSearch && matchesCat
  })

  const activeSkill = skills.find((s) => s.id === activeSkillId) ?? skills[0]
  useEffect(() => { if (activeSkill?.id) void loadInstructions(activeSkill.id) }, [activeSkill?.id, loadInstructions])
  const enabledCount = skills.filter((s) => s.enabled).length

  return (
    <div className="mx-auto max-w-6xl px-6 py-7 select-text">
      {/* Header */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4 border-b border-line pb-5">
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-xs text-muted">
            <span>Settings</span>
            <span>›</span>
            <span>Agents</span>
            <span>›</span>
            <span className="font-semibold text-fg">Skills</span>
          </div>
          <h1 className="flex items-center gap-2 text-xl font-bold text-fg">
            <Sparkles className="size-5 text-brand" />
            Skills · Hermes source packages
          </h1>
          <p className="mt-1 text-xs text-muted">
            Enabled skills are available to new harness sessions. Agents load full instructions when relevant; optional dependencies may require setup.
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <span className="rounded-full border border-line bg-panel2 px-3 py-1 text-xs font-medium text-fg">
            <span className="text-brand font-semibold">{enabledCount}</span> / {skills.length} active
          </span>
          <button
            type="button"
            onClick={enableAll}
            className="rounded-md border border-line bg-panel2 px-2.5 py-1.5 text-xs font-medium text-fg hover:border-brand hover:text-brand transition cursor-pointer"
          >
            Enable all
          </button>
          <button
            type="button"
            onClick={disableAll}
            className="rounded-md border border-line bg-panel2 px-2.5 py-1.5 text-xs font-medium text-muted hover:text-fg transition cursor-pointer"
          >
            Disable all
          </button>
        </div>
      </div>
      {error && <p role="alert" className="mb-4 text-xs text-red-500">{error}</p>}
      <div role="tablist" aria-label="Skills settings" className="mb-4 flex gap-3">
        {(['skills', 'commands'] as const).map(value => <button key={value} role="tab" aria-selected={tab === value} onClick={() => setTab(value)} className={`rounded-lg px-4 py-2 text-sm ${tab === value ? 'bg-brand text-brandfg' : 'bg-panel2 text-fg'}`}>{value === 'skills' ? 'Skills' : 'Commands'}</button>)}
      </div>
      {tab === 'commands' ? <CommandsView /> : <>

      {/* Search & Filter Bar */}
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="relative flex-1 min-w-[240px]">
          <Search className="pointer-events-none absolute left-3 top-2.5 size-3.5 text-muted" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search skills, tags, or methodologies..."
            className="w-full rounded-md border border-line bg-panel2 pl-9 pr-3 py-1.5 text-xs text-fg outline-hidden transition focus:border-brand"
          />
        </div>

        <div className="flex items-center gap-1">
          {['all', 'software-development', 'code-intelligence', 'productivity'].map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setSelectedCategory(cat)}
              className={`rounded-md px-2.5 py-1 text-xs font-medium transition cursor-pointer ${
                selectedCategory === cat
                  ? 'bg-brand text-brandfg shadow-xs font-semibold'
                  : 'text-muted hover:bg-panel2 hover:text-fg'
              }`}
            >
              {cat === 'all'
                ? 'All'
                : cat === 'software-development'
                ? 'Development'
                : cat === 'code-intelligence'
                ? 'Intelligence'
                : 'Productivity'}
            </button>
          ))}
        </div>
      </div>

      {/* Two Column Layout: Skills List & Detail Inspector */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Left Column: Skill Cards List */}
        <div className="space-y-2.5 lg:col-span-7">
          {filteredSkills.map((skill) => {
            const Icon = SKILL_ICONS[skill.id] || Sparkles
            const isSelected = skill.id === activeSkill?.id

            return (
              <div
                key={skill.id}
                onClick={() => setActiveSkillId(skill.id)}
                className={`group flex items-start justify-between gap-4 rounded-xl border p-4 transition cursor-pointer ${
                  isSelected
                    ? 'border-brand bg-panel2/80 shadow-xs ring-1 ring-brand/40'
                    : 'border-line bg-panel hover:border-line hover:bg-panel2/40'
                }`}
              >
                <div className="flex items-start gap-3 min-w-0">
                  <div
                    className={`mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border ${
                      skill.enabled
                        ? 'border-brand/40 bg-brand/10 text-brand'
                        : 'border-line bg-panel text-muted'
                    }`}
                  >
                    <Icon className="size-4" />
                  </div>

                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="text-xs font-bold text-fg truncate">{skill.name}</h3>
                      <span
                        className={`rounded px-1.5 py-0.5 text-[11px] font-bold uppercase ${
                          skill.source === 'claude-code'
                            ? 'bg-amber-500/15 text-amber-600 dark:text-amber-400 border border-amber-500/20'
                            : 'bg-brand/15 text-brand dark:text-brand border border-brand/20'
                        }`}
                      >
                        {skill.source}
                      </span>
                    </div>

                    <p className="mt-1 text-[11px] leading-relaxed text-muted line-clamp-2">
                      {skill.description}
                    </p>

                    <div className="mt-2 flex flex-wrap gap-1">
                      {skill.tags.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-full bg-panel border border-line px-1.5 py-0.5 text-[11px] text-muted font-mono"
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>

                {/* Toggle Switch */}
                <div className="shrink-0 pt-0.5" onClick={(e) => e.stopPropagation()}>
                  <label className="relative inline-flex items-center cursor-pointer">
                    <input
                      type="checkbox"
                      checked={skill.enabled}
                      onChange={() => toggleSkill(skill.id)}
                      className="sr-only peer"
                    />
                    <div className="w-9 h-5 bg-panel border border-line peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-brand"></div>
                  </label>
                </div>
              </div>
            )
          })}
        </div>

        {/* Right Column: Selected Skill Guidelines & Instructions */}
        <div className="lg:col-span-5">
          {activeSkill ? (
            <div className="sticky top-6 rounded-xl border border-line bg-panel p-5 shadow-xs space-y-4">
              <div className="flex items-start justify-between gap-3 border-b border-line pb-4">
                <div>
                  <span className="text-[11px] font-bold tracking-wider text-brand uppercase">
                    Skill Specification
                  </span>
                  <h2 className="text-sm font-bold text-fg mt-0.5">{activeSkill.name}</h2>
                  <p className="text-[11px] text-muted font-mono mt-0.5">id: {activeSkill.id}</p>
                </div>

                <button
                  type="button"
                  onClick={() => toggleSkill(activeSkill.id)}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-semibold transition cursor-pointer ${
                    activeSkill.enabled
                      ? 'bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30'
                      : 'bg-panel2 text-muted border border-line hover:text-fg'
                  }`}
                >
                  <Power className="size-3" />
                  <span>{activeSkill.enabled ? 'Enabled' : 'Disabled'}</span>
                </button>
              </div>

              <div>
                <h4 className="text-xs font-semibold text-fg mb-1">Operational Purpose</h4>
                <p className="text-xs leading-relaxed text-muted">{activeSkill.description}</p>
              </div>

              <div>
                <h4 className="text-xs font-semibold text-fg mb-1.5">Injected Prompt Instructions</h4>
                <div className="rounded-lg border border-line bg-panel2 p-3 font-mono text-[11px] leading-relaxed text-fg whitespace-pre-wrap">
                  {activeSkill.instructions}
                </div>
              </div>

              <div className="rounded-lg border border-line bg-panel2/50 p-3 text-xs text-muted flex items-center gap-2">
                <CheckCircle2 className="size-4 text-emerald-400 shrink-0" />
                <span>Available from the next turn when enabled. Full instructions load only when selected. {activeSkill.readiness}</span>
              </div>
              <button className="rounded border border-line px-3 py-2 text-xs" onClick={() => { setReadiness('Checking sandbox…'); void agentApi(`/skills/${encodeURIComponent(activeSkill.id)}/readiness`).then(r => setReadiness(JSON.stringify(r, null, 2))).catch(e => setReadiness(String(e))) }}>Check sandbox readiness</button>
              {readiness && <pre className="whitespace-pre-wrap break-words text-xs">{readiness}</pre>}
            </div>
          ) : (
            <div className="rounded-xl border border-line bg-panel p-8 text-center text-xs text-muted">
              Select a skill to inspect its instructions.
            </div>
          )}
        </div>
      </div>
      </>}
    </div>
  )
}
