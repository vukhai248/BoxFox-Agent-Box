import { create } from 'zustand'
import type { Harness, ModelOption, SubagentConfig } from '../types/harness'

export const AVAILABLE_MODELS: ModelOption[] = [
  {
    id: 'deepseek-v4-pro',
    name: 'DeepSeek V4 Pro (Global) 1M High',
    provider: 'DeepSeek',
    supportsImages: false,
    contextWindow: '1M',
  },
  {
    id: 'deepseek-v4-flash',
    name: 'DeepSeek V4 Flash',
    provider: 'DeepSeek',
    supportsImages: false,
    contextWindow: '128k',
  },
  {
    id: 'glm-5.2',
    name: 'GLM 5.2',
    provider: 'Zhipu AI',
    supportsImages: true,
    contextWindow: '128k',
  },
  {
    id: 'kimi-2.7-code',
    name: 'Kimi 2.7 Code',
    provider: 'Moonshot AI',
    supportsImages: false,
    contextWindow: '256k',
  },
  {
    id: 'gemini-2.5-flash',
    name: 'Gemini 2.5 Flash',
    provider: 'Google',
    supportsImages: true,
    contextWindow: '1M',
  },
  {
    id: 'gemini-2.5-pro',
    name: 'Gemini 2.5 Pro',
    provider: 'Google',
    supportsImages: true,
    contextWindow: '2M',
  },
  {
    id: 'claude-3.7-sonnet',
    name: 'Claude 3.7 Sonnet',
    provider: 'Anthropic',
    supportsImages: true,
    contextWindow: '200k',
  },
]

const DEFAULT_SUBAGENTS: SubagentConfig[] = [
  {
    id: 'explore',
    name: 'Explore',
    isBuiltIn: true,
    enabled: true,
    model: 'DeepSeek V4 Flash',
    systemPromptAppended: '',
  },
  {
    id: 'code',
    name: 'Code & Build',
    isBuiltIn: true,
    enabled: true,
    model: 'GLM 5.2',
    systemPromptAppended: '',
  },
  {
    id: 'review',
    name: 'Review & Verify',
    isBuiltIn: true,
    enabled: true,
    model: 'DeepSeek V4 Pro (Global) 1M High',
    systemPromptAppended: '',
  },
  {
    id: 'test',
    name: 'Debug & Test',
    isBuiltIn: true,
    enabled: true,
    model: 'Kimi 2.7 Code',
    systemPromptAppended: '',
  },
]

const INITIAL_HARNESSES: Harness[] = [
  {
    id: 'gpt-code-gpt-review',
    name: 'GPT code + GPT review',
    description: 'Fast dual GPT architecture for code generation and self-critique review.',
    isBuiltIn: true,
    mainModel: 'DeepSeek V4 Pro (Global) 1M High',
    subagents: DEFAULT_SUBAGENTS,
  },
  {
    id: 'gpt-code-opus-review',
    name: 'GPT code + Opus review',
    description: 'Balanced throughput with Opus high-accuracy reasoning on validation gates.',
    isBuiltIn: true,
    mainModel: 'Claude 3.7 Sonnet',
    subagents: DEFAULT_SUBAGENTS,
  },
  {
    id: 'opus-code-gpt-review',
    name: 'Opus code + GPT review',
    description: 'Complex architecture generation powered by Opus with automated sanity check.',
    isBuiltIn: true,
    mainModel: 'Claude 3.7 Sonnet',
    subagents: DEFAULT_SUBAGENTS,
  },
  {
    id: 'open-model-harness',
    name: 'Open Model Harness',
    description:
      'Open Model Harness — open-weight model mix: DeepSeek V4 Pro for the main agent, plan and review; DeepSeek V4 Flash for explore; GLM 5.2 for design, build and simplify; Kimi 2.7 Code for debug and testing.',
    isBuiltIn: true,
    mainModel: 'DeepSeek V4 Pro (Global) 1M High',
    modelWarning:
      'Some models in this harness do not support images (e.g. DeepSeek V4 Pro). Sessions will continue; image inputs are replaced with placeholder text so the run does not fail.',
    subagents: DEFAULT_SUBAGENTS,
  },
  {
    id: 'fable-code-gpt-review',
    name: 'Fable code + GPT review',
    description: 'Creative code flow with structured validation.',
    isBuiltIn: true,
    mainModel: 'Gemini 2.5 Flash',
    subagents: DEFAULT_SUBAGENTS,
  },
  {
    id: 'open-model-harness-copy-1',
    name: 'Open Model Harness (Copy)1',
    description:
      'Customized open-weight pipeline with user-specific system instructions and specialized debug prompts.',
    isBuiltIn: false,
    mainModel: 'DeepSeek V4 Pro (Global) 1M High',
    modelWarning:
      'Some models in this harness do not support images (DeepSeek V4 Pro). Sessions will continue; image inputs are replaced with placeholder text so the run does not fail.',
    subagents: [
      {
        id: 'explore',
        name: 'Explore',
        isBuiltIn: true,
        enabled: true,
        model: 'DeepSeek V4 Pro (Global) 1M High',
        systemPromptAppended: 'Focus strictly on discovering hidden invariants and checking security boundaries.',
      },
      {
        id: 'code',
        name: 'Code & Build',
        isBuiltIn: true,
        enabled: true,
        model: 'GLM 5.2',
        systemPromptAppended: 'Always generate clean typed code without any unnecessary wrapper functions.',
      },
    ],
  },
  {
    id: 'open-model-harness-copy',
    name: 'Open Model Harness (Copy)',
    description: 'Staging harness copy for experimentation.',
    isBuiltIn: false,
    mainModel: 'DeepSeek V4 Flash',
    subagents: DEFAULT_SUBAGENTS,
  },
]

export interface HarnessState {
  harnesses: Harness[]
  teamDefaultId: string
  myDefaultId: string
  activeHarnessId: string
  activeType: 'harness' | 'model'
  activeModelId: string
  searchQuery: string

  setSearchQuery: (query: string) => void
  setTeamDefault: (id: string) => void
  setMyDefault: (id: string) => void
  setActiveHarness: (id: string) => void
  setActiveModel: (id: string) => void
  setActiveType: (type: 'harness' | 'model') => void

  getHarnessById: (id: string) => Harness | undefined
  saveHarness: (harness: Harness) => void
  createHarness: (baseHarness?: Partial<Harness>) => string
  cloneHarness: (id: string) => string
  deleteHarness: (id: string) => void
}

export const useHarnessStore = create<HarnessState>((set, get) => ({
  harnesses: INITIAL_HARNESSES,
  teamDefaultId: 'open-model-harness-copy-1',
  myDefaultId: 'open-model-harness-copy-1',
  activeHarnessId: 'open-model-harness-copy-1',
  activeType: 'harness',
  activeModelId: 'claude-3.7-sonnet',
  searchQuery: '',

  setSearchQuery: (searchQuery) => set({ searchQuery }),
  setTeamDefault: (teamDefaultId) => set({ teamDefaultId }),
  setMyDefault: (myDefaultId) => set({ myDefaultId }),
  setActiveHarness: (activeHarnessId) => set({ activeHarnessId, activeType: 'harness' }),
  setActiveModel: (activeModelId) => set({ activeModelId, activeType: 'model' }),
  setActiveType: (activeType) => set({ activeType }),

  getHarnessById: (id) => get().harnesses.find((h) => h.id === id),

  saveHarness: (updatedHarness) =>
    set((state) => {
      const exists = state.harnesses.some((h) => h.id === updatedHarness.id)
      if (exists) {
        return {
          harnesses: state.harnesses.map((h) => (h.id === updatedHarness.id ? updatedHarness : h)),
        }
      }
      return { harnesses: [...state.harnesses, updatedHarness] }
    }),

  createHarness: (base) => {
    const newId = `harness-${Date.now()}`
    const newHarness: Harness = {
      id: newId,
      name: base?.name || 'New Custom Harness',
      description: base?.description || 'Custom configured agent and sub-agents pipeline.',
      isBuiltIn: false,
      mainModel: base?.mainModel || 'DeepSeek V4 Pro (Global) 1M High',
      subagents: base?.subagents || [
        {
          id: `sub-${Date.now()}-1`,
          name: 'Explore',
          isBuiltIn: true,
          enabled: true,
          model: 'DeepSeek V4 Flash',
          systemPromptAppended: '',
        },
      ],
      createdAt: new Date().toISOString(),
    }
    set((state) => ({ harnesses: [...state.harnesses, newHarness] }))
    return newId
  },

  cloneHarness: (id) => {
    const source = get().harnesses.find((h) => h.id === id)
    const newId = `harness-${Date.now()}`
    if (!source) return newId

    const cloned: Harness = {
      ...source,
      id: newId,
      name: `${source.name} (Copy)`,
      isBuiltIn: false,
      createdAt: new Date().toISOString(),
    }
    set((state) => ({ harnesses: [...state.harnesses, cloned] }))
    return newId
  },

  deleteHarness: (id) =>
    set((state) => ({
      harnesses: state.harnesses.filter((h) => h.id !== id || h.isBuiltIn),
    })),
}))
