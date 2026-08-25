import { useState } from 'react'
import {
  Calendar,
  Plus,
  ArrowLeft,
  Clock,
  User,
  GitBranch,
  Trash2,
} from 'lucide-react'
import { CustomSelect } from './CustomSelect'
import { CustomCheckbox } from './CustomCheckbox'

export interface ScheduledSessionItem {
  id: string
  name: string
  prompt: string
  repositories: string
  harness: string
  assignee: string
  frequency: string
  timezone: string
  slackNotification: boolean
  active: boolean
  lastRun?: string
}

const INITIAL_SCHEDULES: ScheduledSessionItem[] = []

const REPO_OPTIONS = ['All repositories', 'cloud-agent-p', 'backend-api']
const HARNESS_OPTIONS = [
  'Use team default harness',
  'Open Model Harness',
  'Fable code + GPT review',
]
const ASSIGNEE_OPTIONS = [
  { value: 'khải vũ', label: '👤+ khải vũ' },
  { value: 'Dynamic', label: '👤+ Dynamic (Auto-assign)' },
]
const FREQUENCY_OPTIONS = [
  'Daily at 9:00 AM',
  'Daily at 12:00 AM',
  'Every 6 hours',
  'Every hour',
  'Weekly on Monday at 9:00 AM',
]
const TIMEZONE_OPTIONS = [
  { value: 'Etc/GMT-7', label: 'Etc/GMT-7 (Bangkok, Hanoi, Jakarta)' },
  { value: 'UTC', label: 'UTC (Coordinated Universal Time)' },
  { value: 'America/New_York', label: 'America/New_York (EST)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo (JST)' },
]

export function ScheduledSessionsView() {
  const [schedules, setSchedules] = useState<ScheduledSessionItem[]>(INITIAL_SCHEDULES)
  const [isCreating, setIsCreating] = useState(false)

  // Form State
  const [name, setName] = useState('')
  const [repositories, setRepositories] = useState('All repositories')
  const [prompt, setPrompt] = useState('')
  const [harness, setHarness] = useState('Use team default harness')
  const [assignee, setAssignee] = useState('khải vũ')
  const [frequency, setFrequency] = useState('Daily at 9:00 AM')
  const [timezone, setTimezone] = useState('Etc/GMT-7')
  const [slackNotification, setSlackNotification] = useState(false)

  const handleCreateSchedule = () => {
    if (!name.trim()) return
    const newSchedule: ScheduledSessionItem = {
      id: `SCH-${Date.now().toString().slice(-4)}`,
      name: name.trim(),
      prompt: prompt.trim(),
      repositories,
      harness,
      assignee,
      frequency,
      timezone,
      slackNotification,
      active: true,
    }
    setSchedules((prev) => [newSchedule, ...prev])
    setIsCreating(false)
    resetForm()
  }

  const resetForm = () => {
    setName('')
    setRepositories('All repositories')
    setPrompt('')
    setHarness('Use team default harness')
    setAssignee('khải vũ')
    setFrequency('Daily at 9:00 AM')
    setTimezone('Etc/GMT-7')
    setSlackNotification(false)
  }

  const toggleActive = (id: string) => {
    setSchedules((prev) =>
      prev.map((s) => (s.id === id ? { ...s, active: !s.active } : s)),
    )
  }

  const handleDelete = (id: string) => {
    setSchedules((prev) => prev.filter((s) => s.id !== id))
  }

  // CREATE VIEW
  if (isCreating) {
    return (
      <div className="p-8 max-w-4xl mx-auto space-y-6 select-text">
        {/* Top Breadcrumb & Actions */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-muted">
            <span>Settings</span>
            <span>›</span>
            <span>Agents</span>
            <span>›</span>
            <span>Scheduled Sessions</span>
            <span>›</span>
            <span className="text-fg font-semibold">Create</span>
          </div>

          <button
            type="button"
            onClick={() => setIsCreating(false)}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-fg transition cursor-pointer"
          >
            <ArrowLeft className="size-3.5" />
            <span>Back to Scheduled Sessions</span>
          </button>
        </div>

        {/* Title Header */}
        <div className="flex items-center justify-between pt-2 border-b border-line pb-4">
          <h1 className="text-xl font-bold text-fg">Create Schedule</h1>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => setIsCreating(false)}
              className="rounded-md border border-line bg-panel2 px-4 py-1.5 text-xs font-medium text-muted hover:text-fg transition cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleCreateSchedule}
              disabled={!name.trim()}
              className="rounded-md bg-brand px-4 py-1.5 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 disabled:opacity-50 transition cursor-pointer"
            >
              Create Schedule
            </button>
          </div>
        </div>

        {/* Form Fields */}
        <div className="space-y-5">
          {/* Row 1: Name and Repositories */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g., Daily code review"
                className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-medium"
                autoFocus
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Repositories</label>
              <CustomSelect
                value={repositories}
                onChange={setRepositories}
                options={REPO_OPTIONS}
              />
            </div>
          </div>

          {/* Row 2: Prompt */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-fg">Prompt</label>
            <textarea
              rows={5}
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Describe what the session should do..."
              className="w-full rounded-lg border border-line bg-panel2 p-3 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono leading-relaxed"
            />
          </div>

          {/* Row 3: Harness & Assignee */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Harness</label>
              <CustomSelect
                value={harness}
                onChange={setHarness}
                options={HARNESS_OPTIONS}
              />
              <p className="text-[11px] text-muted">
                Use team default follows your account default harness setting.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Assignee</label>
              <CustomSelect
                value={assignee}
                onChange={setAssignee}
                options={ASSIGNEE_OPTIONS}
              />
            </div>
          </div>

          {/* Row 4: Frequency & Timezone */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Frequency</label>
              <CustomSelect
                value={frequency}
                onChange={setFrequency}
                options={FREQUENCY_OPTIONS}
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Timezone</label>
              <CustomSelect
                value={timezone}
                onChange={setTimezone}
                options={TIMEZONE_OPTIONS}
              />
            </div>
          </div>

          {/* Row 5: Slack Notification Checkbox */}
          <div className="pt-2">
            <CustomCheckbox
              checked={slackNotification}
              onChange={() => setSlackNotification(!slackNotification)}
              label="Slack Notification"
            />
          </div>
        </div>
      </div>
    )
  }

  // LIST VIEW
  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Agents</span>
        <span>›</span>
        <span className="text-fg font-semibold">Scheduled Sessions</span>
      </div>

      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-line pb-4">
        <div>
          <h1 className="text-xl font-bold text-fg">Scheduled Sessions</h1>
          <p className="text-xs text-muted mt-0.5">
            Configure periodic and recurring agent tasks triggered by time schedules.
          </p>
        </div>

        <button
          type="button"
          onClick={() => setIsCreating(true)}
          className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
        >
          <Plus className="size-3.5" />
          <span>Create Schedule</span>
        </button>
      </div>

      {/* List of Schedules */}
      {schedules.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center rounded-xl border border-line bg-panel">
          <div className="flex size-12 items-center justify-center rounded-xl bg-brand/10 text-brand mb-3">
            <Calendar className="size-6" />
          </div>
          <h3 className="text-sm font-semibold text-fg">No scheduled sessions yet</h3>
          <p className="text-xs text-muted max-w-md mt-1 mb-4">
            Create recurring sessions to perform daily code reviews, linting, or documentation updates automatically.
          </p>
          <button
            type="button"
            onClick={() => setIsCreating(true)}
            className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
          >
            <Plus className="size-3.5" />
            <span>Create Schedule</span>
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {schedules.map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between rounded-xl border border-line bg-panel p-4 transition hover:border-brand/40 shadow-xs"
            >
              <div className="space-y-1 min-w-0 flex-1">
                <div className="flex items-center gap-2.5">
                  <span className="font-semibold text-xs text-fg">{item.name}</span>
                  <span
                    className={`rounded px-1.5 py-0.2 text-[9px] font-bold uppercase ${
                      item.active
                        ? 'bg-emerald-500/15 text-emerald-500 border border-emerald-500/30'
                        : 'bg-muted/15 text-muted border border-line'
                    }`}
                  >
                    {item.active ? 'Active' : 'Paused'}
                  </span>
                </div>

                <p className="text-xs text-muted line-clamp-1 font-mono">
                  {item.prompt || 'No prompt specified.'}
                </p>

                <div className="flex flex-wrap items-center gap-4 text-[11px] text-muted pt-1">
                  <span className="flex items-center gap-1">
                    <Clock className="size-3 text-brand" />
                    <span>{item.frequency} ({item.timezone})</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <GitBranch className="size-3 text-amber-500" />
                    <span>{item.repositories}</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <User className="size-3 text-emerald-500" />
                    <span>{item.assignee}</span>
                  </span>
                  {item.lastRun && (
                    <span className="text-muted">Last run: {item.lastRun}</span>
                  )}
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center gap-2 pl-4">
                <button
                  type="button"
                  onClick={() => toggleActive(item.id)}
                  className="rounded-md border border-line bg-panel2 px-2.5 py-1 text-xs font-medium text-muted hover:text-fg transition cursor-pointer"
                >
                  {item.active ? 'Pause' : 'Resume'}
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(item.id)}
                  className="p-1.5 rounded-md text-muted hover:text-rose-500 hover:bg-rose-500/10 transition cursor-pointer"
                  title="Delete schedule"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
