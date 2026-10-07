import { create } from 'zustand'
import { agentApi } from '../lib/agentApi'

export interface MachineBinding { mode: 'host' | 'docker'; revision: number; projectId: string | null; workspace: string | null }
export interface LocalProject { id: string; path: string; name: string; trusted: boolean }
export interface MachineConfiguration { mode: 'host' | 'docker'; revision: number; projectId: string | null; projects: LocalProject[] }
interface State {
  configuration: MachineConfiguration | null
  bindings: Record<string, MachineBinding>
  error: string | null
  load: () => Promise<void>
  bind: (chatId: string, binding: MachineBinding) => void
  configure: (mode: 'host' | 'docker', projectId?: string | null) => Promise<boolean>
  register: (path?: string) => Promise<LocalProject | null>
  trust: (projectId: string, trusted: boolean) => Promise<void>
}

export const useMachineStore = create<State>((set, get) => ({
  configuration: null, bindings: {}, error: null,
  load: async () => {
    try {
      const value = await agentApi<MachineConfiguration>('/machines/configuration')
      if (!value || !Array.isArray(value.projects) || !['host', 'docker'].includes(value.mode) || !Number.isInteger(value.revision)) throw new Error('MACHINE_CONFIGURATION_UNAVAILABLE: configuration endpoint returned an invalid response')
      set({ configuration: value, error: null })
    }
    catch (error) { set({ error: String(error) }) }
  },
  bind: (chatId, binding) => set(state => ({ bindings: { ...state.bindings, [chatId]: binding } })),
  configure: async (mode, projectId = null) => {
    if (!get().configuration) await get().load()
    const configuration = get().configuration
    if (!configuration) return false
    try {
      set({ configuration: await agentApi<MachineConfiguration>('/machines/configuration', {
        revision: configuration.revision, mode, projectId,
      }, 'PUT'), error: null })
      return true
    } catch (error) { set({ error: String(error) }); await get().load(); set({ error: String(error) }); return false }
  },
  register: async (path) => {
    try {
      const result = await agentApi<LocalProject & { cancelled?: boolean }>(path === undefined ? '/machines/pick-folder' : '/machines/projects', path === undefined ? {} : { path })
      if (result.cancelled) return null
      await get().load()
      return result
    } catch (error) { set({ error: String(error) }); return null }
  },
  trust: async (projectId, trusted) => {
    try { await agentApi('/machines/trust', { projectId, trusted }); await get().load() }
    catch (error) { set({ error: String(error) }) }
  },
}))

export const DOCKER_BINDING: MachineBinding = { mode: 'docker', revision: 1, projectId: null, workspace: '/home/agent/workspace' }
export function activeBinding(chatId: string): MachineBinding {
  const state = useMachineStore.getState()
  return state.bindings[chatId] ?? (state.configuration
    ? { ...state.configuration, workspace: state.configuration.projects.find(p => p.id === state.configuration?.projectId)?.path ?? null }
    : DOCKER_BINDING)
}
