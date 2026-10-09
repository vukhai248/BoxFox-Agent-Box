import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest'
import { MachineConfigurationView } from './MachineConfigurationView'
import { useMachineStore } from '../../store/machineStore'
import { useAgentStore } from '../../store/agentStore'
import { useHarnessChatStore } from '../../store/harnessChatStore'
import { TopBar, availablePanelTabs } from '../../App'
import { I18nProvider } from '../../i18n'
import { HostWorkspacePanel } from '../panels/HostWorkspacePanel'
import { useUiStore } from '../../store/uiStore'

;(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true
let root: Root
let host: HTMLDivElement
const originalActions = useMachineStore.getState()
beforeEach(() => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  useAgentStore.setState({ activeSessionId: 'new-chat' })
  useHarnessChatStore.setState({ sessions: {} })
  useMachineStore.setState({ configuration: {revision: 1, mode: 'docker', projectId: null, projects: []}, bindings: {}, error: null, load: vi.fn().mockResolvedValue(undefined) })
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ok: true, json: async () => ({power: 'on', network: 'on'})}))
})
afterEach(() => { act(() => root.unmount()); host.remove(); useMachineStore.setState(originalActions); vi.unstubAllGlobals() })
async function render(node: React.ReactNode) { await act(async () => { root.render(<I18nProvider>{node}</I18nProvider>) }) }
async function click(button: Element) { await act(async () => { button.dispatchEvent(new MouseEvent('click', {bubbles: true})) }) }

describe('Web machine configuration', () => {
  it('shows IDE/Docker choices only in the configuration view', async () => {
    await render(<MachineConfigurationView />)
    expect(host.textContent).toContain('IDE · This machine')
    expect(host.textContent).toContain('Docker · Isolated')
    expect(host.textContent).not.toContain('Choose folder')
  })
  it('offers a folder picker for IDE', async () => {
    useMachineStore.setState({configuration: {revision: 1, mode: 'host', projectId: null, projects: []}})
    await render(<MachineConfigurationView />)
    expect(host.textContent).toContain('Choose folder')
    expect(host.querySelector('[aria-label="Project folder path"]')).not.toBeNull()
  })
  it('does not mutate the current chat on save failure', async () => {
    const configure = vi.fn().mockResolvedValue(false)
    useMachineStore.setState({configure})
    await render(<MachineConfigurationView />)
    await click([...host.querySelectorAll('button')].find(b => b.textContent?.includes('IDE ·'))!)
    expect(configure).toHaveBeenCalledWith('host', null)
    expect(useAgentStore.getState().activeSessionId).toBe('new-chat')
  })
  it('does not offer Docker when this build runs directly on the machine', async () => {
    useMachineStore.setState({configuration: {revision: 1, mode: 'host', projectId: null, projects: [], processMode: 'host'}})
    await render(<MachineConfigurationView />)
    const docker = [...host.querySelectorAll('button')].find(b => b.textContent?.includes('Docker ·'))!
    expect(docker.hasAttribute('disabled')).toBe(true)
    expect(docker.getAttribute('title')).toContain('no Docker box')
    const ide = [...host.querySelectorAll('button')].find(b => b.textContent?.includes('IDE ·'))!
    expect(ide.hasAttribute('disabled')).toBe(false)
  })
  it('keeps Docker selectable when the process can run a box', async () => {
    useMachineStore.setState({configuration: {revision: 1, mode: 'docker', projectId: null, projects: [], processMode: 'docker'}})
    await render(<MachineConfigurationView />)
    const docker = [...host.querySelectorAll('button')].find(b => b.textContent?.includes('Docker ·'))!
    expect(docker.hasAttribute('disabled')).toBe(false)
  })
  it('keeps a saved session binding and opens a new chat when environment changes', async () => {
    useMachineStore.setState({bindings: {'new-chat': {mode: 'docker', revision: 1, projectId: null, workspace: '/home/agent/workspace'}}, configure: vi.fn().mockResolvedValue(true)})
    await render(<MachineConfigurationView />)
    await click([...host.querySelectorAll('button')].find(b => b.textContent?.includes('IDE ·'))!)
    expect(useAgentStore.getState().activeSessionId).not.toBe('new-chat')
    expect(useMachineStore.getState().bindings['new-chat'].mode).toBe('docker')
  })
  it('keeps Machine screen in the workspace menu', () => {
    expect(availablePanelTabs().find(tab => tab.id === 'sandbox')?.label).toBe('Machine screen')
  })
  it('opens Settings Configuration from an IDE panel without embedding a second mode form', async () => {
    useMachineStore.setState({bindings: {'new-chat': {mode: 'host', revision: 1, projectId: null, workspace: null}}})
    await render(<HostWorkspacePanel view="editor" />)
    expect(host.textContent).not.toContain('Execution environment')
    await click([...host.querySelectorAll('button')].find(b => b.textContent === 'Open Configuration')!)
    expect(useUiStore.getState().settingsTab).toBe('configuration')
    useUiStore.getState().closeSettings()
  })
  it.each(['host', 'docker'] as const)('menu has no mode form; controls depend on %s binding', async mode => {
    useMachineStore.setState({bindings: {'new-chat': {mode, revision: 1, projectId: null, workspace: null}}})
    await render(<TopBar mode="PLAN" budget={{steps: 0, tokens: 0, costUsd: 0, capUsd: 0}} elapsedSeconds={0} />)
    await click(host.querySelector('[data-testid="workspace-more-btn"]')!)
    expect(host.textContent).toContain('Machine screen')
    expect(host.textContent).not.toContain('Execution environment')
    expect(host.textContent?.includes('Sandbox Controls')).toBe(mode === 'docker')
    if (mode === 'host') expect(vi.mocked(fetch).mock.calls.filter(([url]) => String(url).includes('/__box/'))).toHaveLength(0)
  })
})
