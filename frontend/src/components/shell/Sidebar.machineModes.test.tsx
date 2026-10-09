import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { Sidebar } from './Sidebar'
import { useAgentStore } from '../../store/agentStore'
import { useUiStore } from '../../store/uiStore'
import { useHarnessChatStore, type SavedSessionRow } from '../../store/harnessChatStore'
import { useMachineStore, type MachineConfiguration } from '../../store/machineStore'

const { api } = vi.hoisted(() => ({api: vi.fn()}))
vi.mock('../../lib/agentApi', () => ({agentApi: api}))
;(globalThis as typeof globalThis & {IS_REACT_ACT_ENVIRONMENT: boolean}).IS_REACT_ACT_ENVIRONMENT = true

const projectA = {id: 'a', name: 'App A', path: 'D:\\projects\\App A', trusted: false}
const projectB = {id: 'b', name: 'App B', path: 'D:\\projects\\App B', trusted: true}
const bindingA = {mode: 'host' as const, revision: 1, projectId: 'a', workspace: projectA.path}
const bindingB = {...bindingA, projectId: 'b', workspace: projectB.path}
let configuration: MachineConfiguration
let rows: SavedSessionRow[]
let picked: typeof projectA | {cancelled: boolean}
let root: Root
let host: HTMLDivElement
const originalMachine = useMachineStore.getState()
const originalChat = useHarnessChatStore.getState()
const originalAgent = useAgentStore.getState()

beforeEach(() => {
  window.innerWidth = 1400
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  configuration = {revision: 1, mode: 'host', projectId: 'a', projects: [projectA, projectB]}
  rows = [
    {id: 'ha', role: 'orchestrator', status: 'completed', updated: 3, config: {machineBinding: bindingA}},
    {id: 'hb', role: 'orchestrator', status: 'completed', updated: 2, config: {machineBinding: bindingB}},
    {id: 'legacy', role: 'orchestrator', status: 'completed', updated: 1, config: {}},
  ]
  picked = {cancelled: true}
  useUiStore.setState({sidebarCollapsed: false, sessionTab: 'recent'})
  useAgentStore.setState({activeSessionId: 'ha', sessions: []})
  useHarnessChatStore.setState({sessions: {}})
  useMachineStore.setState({...originalMachine, configuration, bindings: {ha: bindingA}, error: null})
  api.mockReset()
  api.mockImplementation(async (path: string, body?: Record<string, unknown>, method?: string) => {
    if (path === '/sessions') return {sessions: rows}
    if (path === '/machines/pick-folder') return picked
    if (path === '/machines/projects') return picked
    if (path === '/machines/configuration' && method === 'PUT') {
      configuration = {...configuration, mode: body!.mode as 'host' | 'docker', projectId: body!.projectId as string | null, revision: configuration.revision + 1}
    }
    if (path === '/machines/configuration') return configuration
    if (method === 'DELETE') {rows = rows.filter(row => path !== `/sessions/${row.id}`); return {deleted: true}}
    return {}
  })
})
afterEach(() => {
  act(() => root.unmount()); host.remove()
  useMachineStore.setState(originalMachine, true)
  useHarnessChatStore.setState(originalChat, true)
  useAgentStore.setState(originalAgent, true)
  vi.restoreAllMocks()
})
async function render() {await act(async () => {root.render(<I18nProvider><Sidebar /></I18nProvider>)})}
async function click(element: Element) {await act(async () => {element.dispatchEvent(new MouseEvent('click', {bubbles: true}))})}
const button = (label: string) => host.querySelector(`[aria-label="${label}"]`)!
const modalButton = (label: string) => [...document.querySelectorAll('[role="dialog"] button')].find(item => item.textContent?.trim() === label)!

describe('IDE projects and Docker session boundaries', () => {
  it('keeps IDE sessions inside their project and legacy sessions inside Docker', async () => {
    await render()
    expect(host.querySelector('[data-testid="project-sessions-a"]')?.textContent).toContain('Session ha')
    expect(host.querySelector('[data-testid="project-sessions-a"]')?.textContent).not.toContain('Session hb')
    expect(host.querySelector('[data-testid="project-sessions-b"]')?.textContent).toContain('Session hb')
    const docker = host.querySelector('[data-testid="docker-sessions"]')!
    expect(docker.textContent).toContain('Session legacy')
    expect(docker.textContent).not.toContain('Session ha')
    expect(button('Choose folder')).toBeTruthy()
    expect(host.textContent).not.toContain('Execution environment')
  })
  it('creates a project draft with an explicit binding, without changing existing sessions', async () => {
    await render()
    await click(button('New session in App B'))
    const draft = useAgentStore.getState().activeSessionId
    expect(draft).toMatch(/^session-/)
    expect(useMachineStore.getState().bindings[draft]).toEqual(bindingB)
    expect(useMachineStore.getState().bindings.ha).toEqual(bindingA)
    expect(host.querySelector('[data-testid="project-sessions-b"] [data-testid="machine-session-draft"]')).not.toBeNull()
    expect(api.mock.calls.filter(([path, body]) => path === '/sessions' && body)).toHaveLength(0)
  })
  it('global New session inherits the active project instead of the configured default', async () => {
    await render()
    await click(button('New session in App B'))
    await click([...host.querySelectorAll('button')].find(item => item.textContent?.trim() === 'New session')!)
    expect(useMachineStore.getState().bindings[useAgentStore.getState().activeSessionId]).toEqual(bindingB)
    expect(configuration.projectId).toBe('a')
  })
  it('can open a Docker draft without rebinding any IDE session', async () => {
    await render()
    await click(button('New session in Docker'))
    expect(useMachineStore.getState().bindings[useAgentStore.getState().activeSessionId].mode).toBe('docker')
    expect(host.querySelector('[data-testid="docker-sessions"] [data-testid="machine-session-draft"]')).not.toBeNull()
    expect(host.querySelector('[aria-label="Choose folder"]')).toBeNull()
    expect(useMachineStore.getState().bindings.ha).toEqual(bindingA)
  })
  it('canceling the picker preserves project and current session', async () => {
    await render()
    await click(button('Choose folder'))
    await click(modalButton('Add'))
    expect(useAgentStore.getState().activeSessionId).toBe('ha')
    expect(configuration.projectId).toBe('a')
    expect(api.mock.calls.some(([path, , method]) => path === '/machines/configuration' && method === 'PUT')).toBe(false)
  })
  it('a successful picker opens a new session in the selected folder without auto-trust', async () => {
    picked = projectB
    await render()
    await click(button('Choose folder'))
    await click(modalButton('Add'))
    expect(useAgentStore.getState().activeSessionId).toBe('ha')
    expect(api.mock.calls.some(([path]) => path === '/machines/projects')).toBe(false)
    await click(modalButton('Create project'))
    const draft = useAgentStore.getState().activeSessionId
    expect(draft).not.toBe('ha')
    expect(useMachineStore.getState().bindings[draft]).toEqual(bindingB)
    expect(configuration.projectId).toBe('b')
    expect(api.mock.calls.some(([path]) => path === '/machines/trust')).toBe(false)
  })
  it('canceling Create project after choosing a folder does not register or start anything', async () => {
    picked = projectB
    await render()
    await click(button('Choose folder'))
    await click(modalButton('Add'))
    await click(modalButton('Cancel'))
    expect(document.querySelector('[role="dialog"]')).toBeNull()
    expect(useAgentStore.getState().activeSessionId).toBe('ha')
    expect(api.mock.calls.some(([path]) => path === '/machines/projects')).toBe(false)
  })
  it('shows the selected path and sends the project name only when Create is confirmed', async () => {
    picked = projectB
    await render()
    await click(button('Choose folder'))
    expect(modalButton('Create project').hasAttribute('disabled')).toBe(true)
    await click(modalButton('Add'))
    expect(document.querySelector<HTMLInputElement>('[role="dialog"] [aria-label="Folder path"]')?.value).toBe(projectB.path)
    const input = document.querySelector<HTMLInputElement>('[aria-label="Project name"]')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, 'Custom project')
      input.dispatchEvent(new Event('input', {bubbles: true}))
    })
    await click(modalButton('Create project'))
    expect(api.mock.calls.find(([path]) => path === '/machines/projects')?.[1]).toEqual({path: projectB.path, name: 'Custom project'})
  })
  it('opening a saved Docker session changes the active environment but retains IDE history', async () => {
    await render()
    await click(host.querySelector('[data-testid="session-row-legacy"] [role="button"]')!)
    expect(host.querySelector('[data-testid="sidebar-active-environment"]')?.textContent).toBe('Docker · Isolated')
    expect(host.querySelector('[data-testid="project-sessions-a"]')?.textContent).toContain('Session ha')
    expect(host.querySelector('[aria-label="Choose folder"]')).toBeNull()
  })
  it('Groups remain separated by project and execution environment', async () => {
    useAgentStore.setState({sessions: [
      {session_id: 'ha', title: 'A group', initials: 'BF', status: 'xong', mode: 'PLAN', relative_time: '', active_lease_count: 0, group_name: 'Shared'},
      {session_id: 'legacy', title: 'Docker group', initials: 'BF', status: 'xong', mode: 'PLAN', relative_time: '', active_lease_count: 0, group_name: 'Shared'},
    ]})
    useUiStore.setState({sessionTab: 'groups'})
    await render()
    const a = host.querySelector('[data-testid="project-sessions-a"]')!
    await click([...a.querySelectorAll('button')].find(item => item.textContent?.includes('Shared'))!)
    expect(a.textContent).toContain('A group')
    expect(a.textContent).not.toContain('Docker group')
    expect(host.querySelector('[data-testid="docker-sessions"]')?.textContent).not.toContain('A group')
  })
  it('recognizes an active frontend alias after the session is saved without duplicating a draft', async () => {
    useAgentStore.setState({activeSessionId: 'session-local-alias'})
    useHarnessChatStore.setState({sessions: {'session-local-alias': {id: 'ha', status: 'completed', events: [], error: null}}})
    useMachineStore.getState().bind('session-local-alias', bindingA)
    await render()
    expect(host.querySelector('[data-testid="machine-session-draft"]')).toBeNull()
    expect(host.querySelector('[data-testid="session-row-ha"] > div')?.className).toContain('bg-panel2')
  })
  it('deleting the last session in a project opens a draft in that project, not another mode', async () => {
    await render()
    await click(host.querySelector('[data-testid="session-menu-ha"]')!)
    await click([...host.querySelectorAll('button')].find(item => item.textContent?.trim() === 'Delete session')!)
    expect(useMachineStore.getState().bindings[useAgentStore.getState().activeSessionId]).toEqual(bindingA)
  })
})
