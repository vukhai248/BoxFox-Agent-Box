import { useState } from 'react'
import {
  Link2,
  Plus,
  ArrowLeft,
  Copy,
  Check,
  Trash2,
  Zap,
} from 'lucide-react'
import { CustomSelect } from './CustomSelect'

export interface AutomationItem {
  id: string
  name: string
  webhookUrl: string
  instructions: string
  spendLimit: string
  rateLimit: string
  harness: string
  assignee: string
  active: boolean
  triggerCount: number
}

const INITIAL_AUTOMATIONS: AutomationItem[] = []

const HARNESS_OPTIONS = [
  'Default',
  'Open Model Harness',
  'Fable code + GPT review',
]

const ASSIGNEE_OPTIONS = [
  { value: 'Dynamic', label: '👤+ Dynamic' },
  { value: 'khải vũ', label: '👤+ khải vũ' },
]

const PERIOD_OPTIONS = ['1 hour', '24 hours']

const SAMPLE_WEBHOOK_URL =
  'https://integrations.us1.boxfox.com/v1/automations/webhook/vfx_wh__FbB94TyV'

export function AutomationsView() {
  const [automations, setAutomations] = useState<AutomationItem[]>(INITIAL_AUTOMATIONS)
  const [isCreating, setIsCreating] = useState(false)

  // Form State
  const [name, setName] = useState('')
  const [includeSecret, setIncludeSecret] = useState(false)
  const [instructions, setInstructions] = useState('')
  const [spendLimit, setSpendLimit] = useState('')
  const [rateLimitNumber, setRateLimitNumber] = useState('')
  const [rateLimitPeriod, setRateLimitPeriod] = useState('1 hour')
  const [harness, setHarness] = useState('Default')
  const [assignee, setAssignee] = useState('Dynamic')

  const [copiedUrl, setCopiedUrl] = useState(false)
  const [copiedCurl, setCopiedCurl] = useState(false)

  const curlCommand = `curl -X POST '${SAMPLE_WEBHOOK_URL}' -H 'Content-Type: application/json' -d '{"event":"issue.created"}'`

  const handleCopyUrl = () => {
    navigator.clipboard.writeText(SAMPLE_WEBHOOK_URL)
    setCopiedUrl(true)
    setTimeout(() => setCopiedUrl(false), 2000)
  }

  const handleCopyCurl = () => {
    navigator.clipboard.writeText(curlCommand)
    setCopiedCurl(true)
    setTimeout(() => setCopiedCurl(false), 2000)
  }

  const handleCreateAutomation = () => {
    if (!name.trim()) return
    const newAutomation: AutomationItem = {
      id: `AUTO-${Date.now().toString().slice(-4)}`,
      name: name.trim(),
      webhookUrl: SAMPLE_WEBHOOK_URL,
      instructions: instructions.trim(),
      spendLimit: spendLimit || 'No limit',
      rateLimit: rateLimitNumber ? `${rateLimitNumber} per ${rateLimitPeriod}` : 'No rate limit',
      harness,
      assignee,
      active: true,
      triggerCount: 0,
    }
    setAutomations((prev) => [newAutomation, ...prev])
    setIsCreating(false)
    resetForm()
  }

  const resetForm = () => {
    setName('')
    setIncludeSecret(false)
    setInstructions('')
    setSpendLimit('')
    setRateLimitNumber('')
    setRateLimitPeriod('1 hour')
    setHarness('Default')
    setAssignee('Dynamic')
  }

  const toggleActive = (id: string) => {
    setAutomations((prev) =>
      prev.map((a) => (a.id === id ? { ...a, active: !a.active } : a)),
    )
  }

  const handleDelete = (id: string) => {
    setAutomations((prev) => prev.filter((a) => a.id !== id))
  }

  // CREATE AUTOMATION VIEW
  if (isCreating) {
    return (
      <div className="p-8 max-w-4xl mx-auto space-y-6 select-text">
        {/* Top Breadcrumb */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-muted">
            <span>Settings</span>
            <span>›</span>
            <span>Agents</span>
            <span>›</span>
            <span>Automations</span>
            <span>›</span>
            <span className="text-fg font-semibold">Create</span>
          </div>

          <button
            type="button"
            onClick={() => setIsCreating(false)}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-fg transition cursor-pointer"
          >
            <ArrowLeft className="size-3.5" />
            <span>Back to app</span>
          </button>
        </div>

        {/* Title Header */}
        <div className="flex items-center justify-between pt-2 border-b border-line pb-4">
          <h1 className="text-xl font-bold text-fg">Create automation</h1>
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
              onClick={handleCreateAutomation}
              disabled={!name.trim()}
              className="rounded-md bg-brand px-4 py-1.5 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 disabled:opacity-50 transition cursor-pointer"
            >
              Create automation
            </button>
          </div>
        </div>

        {/* Form Content */}
        <div className="space-y-6">
          {/* 1. Name */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-fg">Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Triage incoming issues"
              className="w-full rounded-lg border border-line bg-panel2 px-3 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand"
              autoFocus
            />
          </div>

          {/* 2. Trigger Webhook Card */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-fg">Trigger</label>
            <p className="text-[11px] text-muted">Choose what starts this automation</p>

            <div className="rounded-xl border border-line bg-panel p-4 space-y-4 shadow-xs">
              <div className="flex items-center gap-2 text-xs font-semibold text-fg">
                <Link2 className="size-4 text-brand" />
                <span>Webhook</span>
              </div>

              {/* Webhook URL Box */}
              <div className="space-y-1.5">
                <span className="text-xs font-medium text-fg">Webhook URL</span>
                <div className="flex items-center rounded-lg border border-line bg-panel2 px-3 py-2">
                  <input
                    type="text"
                    readOnly
                    value={SAMPLE_WEBHOOK_URL}
                    className="w-full bg-transparent font-mono text-xs text-fg outline-hidden"
                  />
                  <button
                    type="button"
                    onClick={handleCopyUrl}
                    className="ml-2 text-muted hover:text-fg transition cursor-pointer"
                    title="Copy URL"
                  >
                    {copiedUrl ? (
                      <Check className="size-3.5 text-emerald-500" />
                    ) : (
                      <Copy className="size-3.5" />
                    )}
                  </button>
                </div>
              </div>

              {/* Toggle: Include webhook secret */}
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-fg">Include webhook secret (optional)</span>
                <button
                  type="button"
                  onClick={() => setIncludeSecret(!includeSecret)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                    includeSecret ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                      includeSecret ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>

              {/* Test command code snippet */}
              <div className="space-y-1.5 pt-1">
                <span className="text-xs font-medium text-fg">Test command</span>
                <div className="flex items-center justify-between rounded-lg border border-line bg-panel2 px-3 py-2.5 font-mono text-[11px] text-fg">
                  <span className="truncate pr-2">{curlCommand}</span>
                  <button
                    type="button"
                    onClick={handleCopyCurl}
                    className="text-muted hover:text-fg transition cursor-pointer shrink-0"
                    title="Copy curl command"
                  >
                    {copiedCurl ? (
                      <Check className="size-3.5 text-emerald-500" />
                    ) : (
                      <Copy className="size-3.5" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* 3. Instructions */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-fg">Instructions</label>
            <p className="text-[11px] text-muted">What should the agent do when triggered?</p>
            <textarea
              rows={4}
              value={instructions}
              onChange={(e) => setInstructions(e.target.value)}
              placeholder="e.g. Triage this PagerDuty alert and raise a pull request"
              className="w-full rounded-lg border border-line bg-panel2 p-3 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono leading-relaxed"
            />
          </div>

          {/* 4. Advanced options */}
          <div className="space-y-4 pt-2 border-t border-line">
            <div>
              <h3 className="text-xs font-bold text-fg">Advanced options</h3>
              <p className="text-[11px] text-muted">
                Spend limits, rate limits, delivery, and the harness sessions run with.
              </p>
            </div>

            {/* Spend limit per session */}
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-xs font-medium text-fg">
                    Spend limit per session
                  </label>
                  <p className="text-[11px] text-muted">
                    Session pauses if it exceeds this budget.
                  </p>
                </div>
                <div className="relative w-40">
                  <input
                    type="text"
                    value={spendLimit}
                    onChange={(e) => setSpendLimit(e.target.value)}
                    placeholder="$ No limit"
                    className="w-full rounded-lg border border-line bg-panel2 px-3 py-1.5 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand text-right"
                  />
                </div>
              </div>
            </div>

            {/* Rate limit */}
            <div className="space-y-1 pt-1">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-xs font-medium text-fg">Rate limit</label>
                  <p className="text-[11px] text-muted">
                    {rateLimitNumber
                      ? `Max ${rateLimitNumber} triggers per ${rateLimitPeriod}.`
                      : 'No rate limit — every matching event triggers a session.'}
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <input
                    type="number"
                    value={rateLimitNumber}
                    onChange={(e) => setRateLimitNumber(e.target.value)}
                    placeholder="—"
                    className="w-14 rounded-lg border border-line bg-panel2 px-2 py-1.5 text-xs text-fg placeholder:text-muted outline-hidden text-center focus:border-brand font-mono"
                  />
                  <span className="text-xs text-muted">per</span>
                  <CustomSelect
                    value={rateLimitPeriod}
                    onChange={setRateLimitPeriod}
                    options={PERIOD_OPTIONS}
                    className="w-28"
                  />
                </div>
              </div>
            </div>

            {/* Harness Selection */}
            <div className="space-y-1 pt-1">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-xs font-medium text-fg">Harness</label>
                  <p className="text-[11px] text-muted">
                    Which harness sessions triggered by this automation run with.
                  </p>
                </div>
                <CustomSelect
                  value={harness}
                  onChange={setHarness}
                  options={HARNESS_OPTIONS}
                  className="w-48"
                />
              </div>
            </div>

            {/* Slack channel */}
            <div className="space-y-1 pt-1">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-xs font-medium text-fg">Slack channel</label>
                  <p className="text-[11px] text-muted">
                    Channel where sessions created by this automation are posted.
                  </p>
                </div>
                <span className="text-[11px] text-muted italic">
                  No Slack workspace connected. Connect Slack in Integrations settings.
                </span>
              </div>
            </div>

            {/* Assignee */}
            <div className="space-y-1 pt-1">
              <div className="flex items-center justify-between">
                <div>
                  <label className="block text-xs font-medium text-fg">Assignee</label>
                  <p className="text-[11px] text-muted max-w-sm">
                    Choose a fixed assignee, or let the investigation select the most relevant engineer.
                  </p>
                </div>
                <CustomSelect
                  value={assignee}
                  onChange={setAssignee}
                  options={ASSIGNEE_OPTIONS}
                  className="w-48"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  // LIST / EMPTY STATE VIEW
  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Agents</span>
        <span>›</span>
        <span className="text-fg font-semibold">Automations</span>
      </div>

      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-line pb-4">
        <div>
          <h1 className="text-xl font-bold text-fg">Automations</h1>
          <p className="text-xs text-muted mt-0.5">
            Webhook triggers that automatically initiate agent sessions.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setIsCreating(true)}
          className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
        >
          <Plus className="size-3.5" />
          <span>Create automation</span>
        </button>
      </div>

      {/* List of Automations or Empty State */}
      {automations.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center rounded-2xl border border-line bg-panel shadow-xs">
          <div className="flex size-12 items-center justify-center rounded-xl bg-brand/10 text-brand mb-3">
            <Zap className="size-6" />
          </div>

          <h3 className="text-sm font-semibold text-fg">No automations yet</h3>
          <p className="text-xs text-muted max-w-md mt-1 mb-4">
            Create your first automation to run agent tasks automatically from a webhook.
          </p>

          <button
            type="button"
            onClick={() => setIsCreating(true)}
            className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
          >
            <Plus className="size-3.5" />
            <span>Create automation</span>
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {automations.map((item) => (
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
                  {item.instructions || 'No instructions provided.'}
                </p>

                <div className="flex flex-wrap items-center gap-4 text-[11px] text-muted pt-1 font-mono">
                  <span className="flex items-center gap-1 text-brand truncate max-w-xs">
                    <Link2 className="size-3" />
                    <span>{item.webhookUrl}</span>
                  </span>
                  <span>Harness: {item.harness}</span>
                  <span>Assignee: {item.assignee}</span>
                </div>
              </div>

              {/* Actions */}
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
                  title="Delete automation"
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
