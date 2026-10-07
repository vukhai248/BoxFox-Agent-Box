import { useAgentStore } from '../store/agentStore'
import { activeBinding, useMachineStore, type MachineBinding } from '../store/machineStore'

/** Snapshot the chosen environment before the first message creates the server session. */
export function startMachineChat(binding: MachineBinding = activeBinding(useAgentStore.getState().activeSessionId)): string {
  const id = `session-${crypto.randomUUID()}`
  useMachineStore.getState().bind(id, {
    mode: binding.mode, revision: binding.revision, projectId: binding.projectId, workspace: binding.workspace,
  })
  useAgentStore.getState().setActiveSessionId(id)
  return id
}
