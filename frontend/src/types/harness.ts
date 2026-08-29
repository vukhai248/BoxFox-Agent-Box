export interface SubagentConfig {
  id: string
  name: string
  isBuiltIn?: boolean
  enabled: boolean
  model: string
  systemPromptAppended: string // User-entered appended prompt
}

export interface Harness {
  id: string
  name: string
  description: string
  isBuiltIn?: boolean
  mainModel: string
  modelWarning?: string
  subagents: SubagentConfig[]
  createdAt?: string
  updatedAt?: string
}

export type SettingSectionId = 'ACCOUNT' | 'AGENTS' | 'MACHINES' | 'FEATURES' | 'ADMINISTRATION'

export type SettingTabId =
  // ACCOUNT
  | 'account'
  | 'notifications'
  // AGENTS
  | 'harness'
  | 'instructions'
  | 'skills'
  | 'llm_api_keys'
  | 'scheduled_sessions'
  | 'automations'
  // MACHINES
  | 'configuration'
  | 'secrets'
  | 'browser'
  // FEATURES
  | 'integrations'
  | 'pull_requests'
  | 'appearance'
  // ADMINISTRATION
  | 'api'
  | 'billing'
  | 'usage'
  | 'referrals'
  | 'support'

export interface ModelOption {
  id: string
  name: string
  provider: string
  supportsImages: boolean
  contextWindow?: string
}
