import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '../../i18n'
import { CreateProjectModal } from './CreateProjectModal'
import { useAgentStore } from '../../store/agentStore'
import { useMachineStore, type MachineConfiguration, type LocalProject } from '../../store/machineStore'

const { api } = vi.hoisted(() => ({api: vi.fn()}))
vi.mock('../../lib/agentApi', () => ({agentApi: api}))
;(globalThis as typeof globalThis & {IS_REACT_ACT_ENVIRONMENT: boolean}).IS_REACT_ACT_ENVIRONMENT = true

const project: LocalProject = {id: 'p1', name: 'Host workspace', path: '/home/boxfox/host-workspace', trusted: false}
let configuration: MachineConfiguration
let picked: {path: string} | {cancelled: boolean}
let pickerError: Error | null
let root: Root
let host: HTMLDivElement
let closed: number
const originalMachine = useMachineStore.getState()
const originalAgent = useAgentStore.getState()

beforeEach(() => {
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  configuration = {revision: 1, mode: 'host', projectId: null, projects: []}
  picked = {cancelled: true}
  pickerError = null
  closed = 0
  useAgentStore.setState({activeSessionId: 'chat-1', sessions: []})
  useMachineStore.setState({...originalMachine, configuration, bindings: {}, error: null})
  api.mockReset()
  api.mockImplementation(async (path: string, body?: Record<string, unknown>, method?: string) => {
    if (path === '/machines/pick-folder') {
      if (pickerError) throw pickerError
      return picked
    }
    if (path === '/machines/projects') return project
    if (path === '/machines/configuration' && method === 'PUT') {
      configuration = {...configuration, mode: body!.mode as 'host' | 'docker', projectId: body!.projectId as string | null, revision: configuration.revision + 1}
    }
    if (path === '/machines/configuration') return configuration
    return {}
  })
})
afterEach(() => {
  act(() => root.unmount()); host.remove()
  useMachineStore.setState(originalMachine, true)
  useAgentStore.setState(originalAgent, true)
  vi.restoreAllMocks()
})

async function render() {await act(async () => {root.render(<I18nProvider><CreateProjectModal onClose={() => {closed += 1}} /></I18nProvider>)})}
async function click(element: Element) {await act(async () => {element.dispatchEvent(new MouseEvent('click', {bubbles: true}))})}
async function type(input: HTMLInputElement, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
    input.dispatchEvent(new Event('input', {bubbles: true}))
  })
}
const field = (label: string) => document.querySelector<HTMLInputElement>(`[role="dialog"] [aria-label="${label}"]`)!
const modalButton = (label: string) => [...document.querySelectorAll('[role="dialog"] button')].find(item => item.textContent?.trim() === label)!
const alert = () => document.querySelector('[role="dialog"] [role="alert"]')?.textContent ?? ''

describe('Create project dialog', () => {
  it('creates a project from a typed folder path without opening the picker', async () => {
    await render()
    await type(field('Project name'), 'Host workspace')
    await type(field('Folder path'), project.path)
    await click(modalButton('Create project'))
    expect(api.mock.calls.filter(([path]) => path === '/machines/pick-folder')).toHaveLength(0)
    expect(api.mock.calls.find(([path]) => path === '/machines/projects')?.[1]).toEqual({path: project.path, name: 'Host workspace'})
    expect(api.mock.calls.find(([path, , method]) => path === '/machines/configuration' && method === 'PUT')?.[1]).toEqual({revision: 1, mode: 'host', projectId: 'p1'})
    expect(closed).toBe(1)
    expect(useMachineStore.getState().bindings[useAgentStore.getState().activeSessionId]).toMatchObject({mode: 'host', projectId: 'p1', workspace: project.path})
  })
  it('keeps Create project disabled until a path is typed or picked', async () => {
    await render()
    expect(modalButton('Create project').hasAttribute('disabled')).toBe(true)
    await type(field('Project name'), 'Host workspace')
    expect(modalButton('Create project').hasAttribute('disabled')).toBe(true)
    await type(field('Folder path'), project.path)
    expect(modalButton('Create project').hasAttribute('disabled')).toBe(false)
  })
  it('fills the path and the name from a successful picker', async () => {
    picked = {path: 'D:\\projects\\App B'}
    await render()
    await click(modalButton('Add'))
    expect(field('Folder path').value).toBe('D:\\projects\\App B')
    expect(field('Project name').value).toBe('App B')
    expect(api.mock.calls.find(([path]) => path === '/machines/pick-folder')?.[1]).toEqual({selectOnly: true})
  })
  it('shows the picker error but still creates from the typed path', async () => {
    pickerError = new Error('FOLDER_PICKER_UNAVAILABLE: Nhập đường dẫn folder trên máy chạy BoxFox.')
    await render()
    await click(modalButton('Add'))
    expect(alert()).toContain('FOLDER_PICKER_UNAVAILABLE')
    await type(field('Project name'), 'Host workspace')
    await type(field('Folder path'), project.path)
    await click(modalButton('Create project'))
    expect(api.mock.calls.find(([path]) => path === '/machines/projects')?.[1]).toEqual({path: project.path, name: 'Host workspace'})
    expect(closed).toBe(1)
  })
})
