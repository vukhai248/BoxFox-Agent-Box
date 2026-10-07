import { useAgentStore } from '../store/agentStore'
import { useMachineStore, DOCKER_BINDING } from '../store/machineStore'

export function useActiveMachine() {
  const chatId = useAgentStore(s => s.activeSessionId)
  return useMachineStore(s => s.bindings[chatId] ?? s.configuration ?? DOCKER_BINDING)
}
