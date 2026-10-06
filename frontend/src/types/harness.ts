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
  // Ba trường dưới là tuỳ chọn: record cũ trong `boxfox_harness_v0` thiếu trường vẫn nạp được,
  // và thiếu trường nghĩa là engine tự quyết (16 bước / 180 giây / đủ công cụ) — không bịa số ở client.
  maxSteps?: number
  deadlineSeconds?: number
  tools?: string[]
  // Bản sao nhớ bản gốc để dòng tóm tắt nói được nó từ đâu ra; xoá bản gốc thì trường này được gỡ.
  duplicatedFrom?: { id: string; name: string }
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
  | 'provider'
  | 'llm_api_keys'
  | 'router'
  | 'scheduled_sessions'
  | 'automations'
  // MACHINES
  | 'configuration'
  | 'machine_permissions'
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
  thinkingLevels?: string[]
}
