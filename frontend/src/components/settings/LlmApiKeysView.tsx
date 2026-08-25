import { useState } from 'react'
import {
  Plus,
  ArrowLeft,
  Trash2,
  Edit2,
  Zap,
  Eye,
  EyeOff,
  KeyRound,
} from 'lucide-react'
import { CustomSelect } from './CustomSelect'
import { CustomCheckbox } from './CustomCheckbox'

export interface ProviderItem {
  id: string
  name: string
  providerType: string
  access: 'All users' | 'Only me'
  apiKey: string
  endpointUrl?: string
  models: string[]
  fallbackEnabled: boolean
  fallbackTarget: string
  active: boolean
  createdAt: string
}

export const PROVIDER_TYPES = [
  'Anthropic',
  'Bedrock',
  'Fireworks',
  'Google Gemini',
  'Google Vertex AI',
  'Moonshot API',
  'OpenAI',
  'OpenRouter',
  'Vercel AI Gateway',
  'OpenAI-compatible Gateway',
  'Azure OpenAI',
  'z.ai',
  'MiniMax Token Plan',
]

const ACCESS_OPTIONS = [
  { value: 'All users', label: 'All users' },
  { value: 'Only me', label: 'Only me' },
]

const FALLBACK_TARGETS = [
  { value: 'BoxFox Hosted (Default)', label: 'BoxFox Hosted (Default Gateway)' },
  { value: 'OpenRouter Backup', label: 'OpenRouter (High-capacity Backup)' },
  { value: 'Google Gemini Pro', label: 'Google Gemini (Fast Fallback)' },
  { value: 'Local Ollama Offline', label: 'Local Ollama (Offline Sandbox Fallback)' },
]

const DEFAULT_MODELS_BY_PROVIDER: Record<string, string[]> = {
  Anthropic: [
    'Claude Fable 5',
    'Claude Haiku 4.5',
    'Claude Opus 4.6',
    'Claude Opus 4.7',
    'Claude Opus 4.8',
    'Claude Opus 5',
    'Claude Sonnet 4.6',
    'Claude Sonnet 5',
    'Claude 3.7 Sonnet',
    'Claude 3.5 Sonnet',
  ],
  OpenAI: ['GPT-4.5', 'GPT-4o', 'GPT-4o mini', 'o1', 'o1-mini', 'o3-mini'],
  'Google Gemini': ['Gemini 2.5 Pro', 'Gemini 2.5 Flash', 'Gemini 2.0 Flash', 'Gemini 1.5 Pro'],
  OpenRouter: ['DeepSeek R1', 'DeepSeek V3', 'Claude 3.7 Sonnet (Router)', 'Llama 3.3 70B', 'Qwen 2.5 72B'],
  default: ['Default Model 1', 'Default Model 2', 'Fast Model', 'Reasoning Model'],
}

const INITIAL_PROVIDERS: ProviderItem[] = []

export function LlmApiKeysView() {
  const [providers, setProviders] = useState<ProviderItem[]>(INITIAL_PROVIDERS)
  const [isCreating, setIsCreating] = useState(false)
  const [editingId, setEditingId] = useState<string | null>(null)

  // Form State
  const [name, setName] = useState('My Anthropic')
  const [providerType, setProviderType] = useState('Anthropic')
  const [access, setAccess] = useState<'All users' | 'Only me'>('All users')
  const [apiKey, setApiKey] = useState('')
  const [showApiKey, setShowApiKey] = useState(false)
  const [endpointUrl, setEndpointUrl] = useState('')
  const [selectedModels, setSelectedModels] = useState<string[]>(
    DEFAULT_MODELS_BY_PROVIDER['Anthropic'],
  )
  const [fallbackEnabled, setFallbackEnabled] = useState(true)
  const [fallbackTarget, setFallbackTarget] = useState('BoxFox Hosted (Default)')

  const currentAvailableModels =
    DEFAULT_MODELS_BY_PROVIDER[providerType] || DEFAULT_MODELS_BY_PROVIDER.default

  const isAllModelsSelected =
    currentAvailableModels.length > 0 &&
    currentAvailableModels.every((m) => selectedModels.includes(m))

  const handleProviderTypeChange = (newType: string) => {
    setProviderType(newType)
    setName(`My ${newType}`)
    const newModels = DEFAULT_MODELS_BY_PROVIDER[newType] || DEFAULT_MODELS_BY_PROVIDER.default
    setSelectedModels(newModels)
  }

  const toggleAllModels = () => {
    if (isAllModelsSelected) {
      setSelectedModels([])
    } else {
      setSelectedModels([...currentAvailableModels])
    }
  }

  const toggleModel = (modelName: string) => {
    if (selectedModels.includes(modelName)) {
      setSelectedModels(selectedModels.filter((m) => m !== modelName))
    } else {
      setSelectedModels([...selectedModels, modelName])
    }
  }

  const handleOpenCreate = () => {
    setName('My Anthropic')
    setProviderType('Anthropic')
    setAccess('All users')
    setApiKey('')
    setEndpointUrl('')
    setSelectedModels(DEFAULT_MODELS_BY_PROVIDER['Anthropic'])
    setFallbackEnabled(true)
    setFallbackTarget('BoxFox Hosted (Default)')
    setEditingId(null)
    setIsCreating(true)
  }

  const handleOpenEdit = (p: ProviderItem) => {
    setName(p.name)
    setProviderType(p.providerType)
    setAccess(p.access)
    setApiKey(p.apiKey)
    setEndpointUrl(p.endpointUrl || '')
    setSelectedModels(p.models)
    setFallbackEnabled(p.fallbackEnabled)
    setFallbackTarget(p.fallbackTarget)
    setEditingId(p.id)
    setIsCreating(true)
  }

  const handleSaveProvider = () => {
    if (!name.trim() || !apiKey.trim()) return

    if (editingId) {
      setProviders((prev) =>
        prev.map((p) =>
          p.id === editingId
            ? {
                ...p,
                name: name.trim(),
                providerType,
                access,
                apiKey: apiKey.trim(),
                endpointUrl: endpointUrl.trim() || undefined,
                models: selectedModels,
                fallbackEnabled,
                fallbackTarget,
              }
            : p,
        ),
      )
    } else {
      const newProvider: ProviderItem = {
        id: `PRV-${Date.now().toString().slice(-4)}`,
        name: name.trim(),
        providerType,
        access,
        apiKey: apiKey.trim(),
        endpointUrl: endpointUrl.trim() || undefined,
        models: selectedModels,
        fallbackEnabled,
        fallbackTarget,
        active: true,
        createdAt: 'Active',
      }
      setProviders((prev) => [newProvider, ...prev])
    }

    setIsCreating(false)
  }

  const handleDelete = (id: string) => {
    setProviders((prev) => prev.filter((p) => p.id !== id))
  }

  // =========================================================================
  // CREATE / EDIT PROVIDER VIEW
  // =========================================================================
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
            <span>LLM API Keys</span>
            <span>›</span>
            <span className="text-fg font-semibold">
              {editingId ? 'Edit Provider' : 'Add Provider'}
            </span>
          </div>

          <button
            type="button"
            onClick={() => setIsCreating(false)}
            className="flex items-center gap-1.5 text-xs text-muted hover:text-fg transition cursor-pointer"
          >
            <ArrowLeft className="size-3.5" />
            <span>Back to LLM API Keys</span>
          </button>
        </div>

        {/* Title Header */}
        <div className="flex items-center justify-between pt-2 border-b border-line pb-4">
          <h1 className="text-xl font-bold text-fg">
            {editingId ? 'Edit Provider' : 'Add Provider'}
          </h1>
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
              onClick={handleSaveProvider}
              disabled={!name.trim() || !apiKey.trim()}
              className="rounded-md bg-brand px-5 py-1.5 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 disabled:opacity-50 transition cursor-pointer"
            >
              {editingId ? 'Save Changes' : 'Add Provider'}
            </button>
          </div>
        </div>

        {/* Form Fields */}
        <div className="space-y-5">
          {/* Row 1: Name and Provider Type */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. My Anthropic"
                className="w-full rounded-lg border border-line bg-panel2 px-3.5 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-medium"
                autoFocus
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">Provider Type</label>
              <CustomSelect
                value={providerType}
                onChange={handleProviderTypeChange}
                options={PROVIDER_TYPES}
              />
            </div>
          </div>

          {/* Row 2: Access */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-fg">Access</label>
            <CustomSelect
              value={access}
              onChange={(val) => setAccess(val as 'All users' | 'Only me')}
              options={ACCESS_OPTIONS}
            />
            <p className="text-[11px] text-muted">
              "Only me" restricts this provider to sessions assigned to you.
            </p>
          </div>

          {/* Row 3: API Key */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-fg">
              API Key <span className="text-rose-500">*</span>
            </label>
            <div className="relative">
              <input
                type={showApiKey ? 'text' : 'password'}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full rounded-lg border border-line bg-panel2 px-3.5 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono pr-10"
              />
              <button
                type="button"
                onClick={() => setShowApiKey(!showApiKey)}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-muted hover:text-fg transition cursor-pointer"
              >
                {showApiKey ? <EyeOff className="size-3.5" /> : <Eye className="size-3.5" />}
              </button>
            </div>
          </div>

          {/* Optional: Custom Endpoint URL for OpenAI-compatible or Azure */}
          {(providerType.includes('Gateway') ||
            providerType.includes('Azure') ||
            providerType.includes('Vertex')) && (
            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-fg">
                Custom Endpoint / Base URL
              </label>
              <input
                type="text"
                value={endpointUrl}
                onChange={(e) => setEndpointUrl(e.target.value)}
                placeholder="https://api.openai.com/v1 or https://my-custom-llm.corp/v1"
                className="w-full rounded-lg border border-line bg-panel2 px-3.5 py-2 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono"
              />
            </div>
          )}

          {/* Row 4: Model Routing Box */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-fg">Model Routing</label>

            <div className="rounded-2xl border border-line bg-panel p-4 space-y-2.5 max-h-64 overflow-y-auto">
              {/* All Models Toggle */}
              <div className="pb-2 border-b border-line">
                <CustomCheckbox
                  checked={isAllModelsSelected}
                  onChange={toggleAllModels}
                  label="All Models"
                />
              </div>

              {/* Individual Model Checkboxes */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 pt-1">
                {currentAvailableModels.map((model) => {
                  const isChecked = selectedModels.includes(model)
                  return (
                    <CustomCheckbox
                      key={model}
                      checked={isChecked}
                      onChange={() => toggleModel(model)}
                      label={model}
                    />
                  )
                })}
              </div>
            </div>
          </div>

          {/* Row 5: Fall back to BoxFox / Default Fallback Provider */}
          <div className="rounded-2xl border border-line bg-panel p-5 space-y-4 shadow-xs">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="flex size-9 items-center justify-center rounded-xl bg-brand/15 text-brand border border-brand/30">
                  <Zap className="size-4" />
                </div>
                <div>
                  <h3 className="text-xs font-bold text-fg">Fall back to BoxFox / Backup</h3>
                  <p className="text-xs text-muted">
                    Routes to fallback hosted models if this provider errors, times out, or hits rate limits.
                  </p>
                </div>
              </div>

              {/* Toggle Switch */}
              <button
                type="button"
                onClick={() => setFallbackEnabled(!fallbackEnabled)}
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                  fallbackEnabled ? 'bg-brand border-brand' : 'bg-panel border-line'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                    fallbackEnabled ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>

            {/* Fallback Target Selector */}
            {fallbackEnabled && (
              <div className="space-y-1.5 pt-2 border-t border-line animate-in fade-in duration-100">
                <span className="text-xs font-semibold text-fg">Fallback Provider Target:</span>
                <CustomSelect
                  value={fallbackTarget}
                  onChange={setFallbackTarget}
                  options={FALLBACK_TARGETS}
                />
                <p className="text-[10px] text-muted">
                  If requests fail with rate limits (429) or provider outages, queries are instantly rerouted to this fallback.
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  // =========================================================================
  // LIST OF CONFIGURED LLM PROVIDERS
  // =========================================================================
  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Agents</span>
        <span>›</span>
        <span className="text-fg font-semibold">LLM API Keys</span>
      </div>

      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-line pb-4">
        <div>
          <h1 className="text-xl font-bold text-fg">LLM API Keys & Providers</h1>
          <p className="text-xs text-muted mt-0.5">
            Configure custom API keys, model routing rules, and automatic fallback providers.
          </p>
        </div>

        <button
          type="button"
          onClick={handleOpenCreate}
          className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
        >
          <Plus className="size-3.5" />
          <span>Add Provider</span>
        </button>
      </div>

      {/* Providers List Container or Empty State */}
      {providers.length === 0 ? (
        <div className="flex flex-col items-center justify-center p-12 text-center rounded-2xl border border-line bg-panel shadow-xs">
          <div className="flex size-12 items-center justify-center rounded-xl bg-brand/10 text-brand mb-3">
            <KeyRound className="size-6" />
          </div>
          <h3 className="text-sm font-semibold text-fg">No LLM API keys configured</h3>
          <p className="text-xs text-muted max-w-md mt-1 mb-4">
            Add your custom provider keys (Anthropic, OpenAI, Gemini, Bedrock, etc.) to configure model routing and automatic fallbacks.
          </p>
          <button
            type="button"
            onClick={handleOpenCreate}
            className="flex items-center gap-1.5 rounded-md bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
          >
            <Plus className="size-3.5" />
            <span>Add Provider</span>
          </button>
        </div>
      ) : (
        <div className="space-y-3">
          {providers.map((p) => (
            <div
              key={p.id}
              className="flex items-center justify-between rounded-2xl border border-line bg-panel p-5 shadow-xs transition hover:border-brand/40"
            >
              <div className="space-y-1.5 min-w-0 flex-1">
                <div className="flex items-center gap-3">
                  <span className="font-bold text-sm text-fg">{p.name}</span>
                  <span className="rounded bg-brand/15 border border-brand/30 px-2 py-0.2 text-[10px] font-bold text-brand font-mono">
                    {p.providerType}
                  </span>
                  <span className="rounded bg-emerald-500/15 border border-emerald-500/30 px-2 py-0.2 text-[10px] font-bold text-emerald-500">
                    {p.access}
                  </span>
                </div>

                <div className="flex flex-wrap items-center gap-4 text-[11px] text-muted pt-1 font-mono">
                  <span className="text-fg">
                    Key: ••••••••••••••{p.apiKey.slice(-6)}
                  </span>
                  <span>
                    Routed Models: <strong className="text-fg">{p.models.length} models</strong>
                  </span>
                  {p.fallbackEnabled && (
                    <span className="flex items-center gap-1 text-brand font-medium">
                      <Zap className="size-3" />
                      <span>Fallback: {p.fallbackTarget}</span>
                    </span>
                  )}
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center gap-2 pl-4">
                <button
                  type="button"
                  onClick={() => handleOpenEdit(p)}
                  className="p-1.5 rounded-lg text-muted hover:text-fg hover:bg-panel2 transition cursor-pointer"
                  title="Edit provider"
                >
                  <Edit2 className="size-4" />
                </button>
                <button
                  type="button"
                  onClick={() => handleDelete(p.id)}
                  className="p-1.5 rounded-lg text-muted hover:text-rose-500 hover:bg-rose-500/10 transition cursor-pointer"
                  title="Delete provider"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
